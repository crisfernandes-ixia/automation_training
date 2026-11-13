"""
common_rest.py - The building blocks shared by lessons 02 and 03, written as plain
REST calls on top of ixn_rest.IxnRest (GET / POST / PATCH / DELETE + operations).

Each function lists the exact HTTP calls it makes, so it can be ported line by
line to C# (HttpClient) or any other language. Lesson 01 shows the same session
handling with nothing but the 'requests' package.
"""
import contextlib
import csv
import datetime
import getpass
import os
import re
import struct
import time

import lab_config as cfg
from ixn_rest import IxnRest, IxnRestError, LOG, setup_logging

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, 'results')
CONFIGS_DIR = os.path.join(HERE, 'configs')


class Lab(object):
    """What a lesson needs: the REST client and the hrefs of the session."""
    def __init__(self, rest, session_id, name):
        self.rest = rest
        self.session_id = session_id
        self.name = name
        self.session = '/api/v1/sessions/{}'.format(session_id)     # session href
        self.ixn = self.session + '/ixnetwork'                        # root of the config tree


def unique_session_name(prefix):
    return '{}-{}-{:%Y%m%d-%H%M%S}'.format(prefix, getpass.getuser().replace(' ', '_'),
                                          datetime.datetime.now())


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def ixnetwork_session(lesson, keep=cfg.KEEP_SESSION):
    """Connect, get a session, clear its config ... and ALWAYS clean up.

    REST calls:
      POST  /api/v1/auth/session                                  find server + login
      Linux:   POST  /api/v1/sessions {"applicationType": "ixnrest"}            create
               POST  /api/v1/sessions/<id>/operations/start {...}               start (async)
               PATCH /ixnetworkweb/api/v1/sessions/<id> {"sessionName": ...}    name it
      Windows: GET   /api/v1/sessions                     the GUI has exactly one session
      POST  /api/v1/sessions/<id>/ixnetwork/operations/newconfig  empty configuration
    """
    os.makedirs(RESULTS_DIR, exist_ok=True)
    name = unique_session_name('{}-{}'.format(cfg.SESSION_PREFIX, lesson))
    log_file = os.path.join(RESULTS_DIR, name + '_rest.log')
    setup_logging(log_file, console_bodies=(cfg.CONSOLE_LOG == 'bodies'))
    LOG.info('Full REST transcript: %s', log_file)

    rest = IxnRest(cfg.API_SERVER, cfg.REST_PORT)
    rest.detect()
    rest.login(cfg.USERNAME, cfg.PASSWORD)

    if rest.platform == 'windows':
        session_id = rest.get('/api/v1/sessions')[0]['id']
    else:
        created = rest.post('/api/v1/sessions', {'applicationType': 'ixnrest'})
        href = created['links'][0]['href'] if created.get('links') else None
        session = rest.get(href) if href else created
        session_id = session['id']
        rest.post('/api/v1/sessions/{}/operations/start'.format(session_id),
                  {'applicationType': 'ixnrest'})
        if rest.platform == 'linux':
            rest.patch('/ixnetworkweb/api/v1/sessions/{}'.format(session_id), {'sessionName': name})

    lab = Lab(rest, session_id, name if rest.platform == 'linux' else '<windows GUI session>')
    build = rest.get(lab.ixn + '/globals', includes='buildNumber,username')
    LOG.info('Session %s (%s) on %s, IxNetwork %s', session_id, lab.name, rest.platform,
             build.get('buildNumber'))
    rest.operation(lab.ixn, 'newConfig')
    try:
        yield lab
    finally:
        cleanup_session(lab, keep)


def cleanup_session(lab, keep=False):
    """Stop traffic/protocols, then release (Windows) or delete (Linux) the session.

    REST calls:
      GET  <ixn>/traffic                                  -> "state"
      POST <ixn>/traffic/operations/stopstatelesstrafficblocking {"arg1": [<ixn>/traffic]}
      POST <ixn>/operations/stopallprotocols {"arg1": "sync"}
      Windows: POST <ixn>/vport/operations/releaseport {"arg1": [<vport hrefs>]}
               POST <ixn>/operations/newconfig
      Linux:   POST /api/v1/sessions/<id>/operations/stop?deleteAfterStop=true
    """
    rest = lab.rest
    try:
        if rest.get(lab.ixn + '/traffic').get('state') == 'started':
            rest.operation(lab.ixn + '/traffic', 'stopStatelessTrafficBlocking', [lab.ixn + '/traffic'])
        rest.operation(lab.ixn, 'stopAllProtocols', 'sync')
    except IxnRestError as err:
        LOG.warning('Cleanup: could not stop traffic/protocols: %s', err)

    if keep:
        LOG.warning('KEEP_SESSION set - session %s left running. Delete it when done!', lab.session_id)
        return
    if rest.platform == 'windows':
        LOG.info('Windows API server: releasing ports and clearing the config')
        try:
            vports = [v['href'] for v in rest.list(lab.ixn + '/vport')]
            if vports:
                rest.operation(lab.ixn + '/vport', 'releasePort', vports)
            rest.operation(lab.ixn, 'newConfig')
        except IxnRestError as err:
            LOG.warning('Could not release ports: %s', err)
    else:
        LOG.info('Deleting session %s', lab.session_id)
        try:
            rest.post(lab.session + '/operations/stop', deleteAfterStop='true')
        except IxnRestError as err:
            LOG.warning('Could not delete session: %s', err)


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
def connect_ports(lab, port_list, names=None, media=cfg.PORT_MEDIA, speed=cfg.PORT_SPEED,
                  link_up_timeout=120):
    """Connect virtual ports to chassis ports, set L1, wait for link up.
    Existing vports (e.g. from a loaded config) are reused by name.

    REST calls:
      GET   <ixn>/availableHardware/chassis                       is the chassis known?
      POST  <ixn>/availableHardware/chassis {"hostname": ip}      add it, poll "state" == "ready"
      GET   <ixn>/vport                                           existing vports
      POST  <ixn>/vport {"name": "Port_1"}                        create missing ones
      PATCH <vport> {"location": "10.80.81.2;2;13"}               chassis;card;port
      POST  <ixn>/vport/operations/connectports {"arg1": [vports], "arg2": true}  take ownership
      GET   <vport>                                               -> "type" e.g. novusTenGigLan
      PATCH <vport>/l1Config/<type> {"media": "fiber", "selectedSpeeds": ["speed10g"]}
      GET   <vport>                                               poll "connectionState" == "connectedLinkUp"
    Returns the vport hrefs in the same order as port_list.
    """
    rest, ixn = lab.rest, lab.ixn
    names = names or ['Port_{}'.format(i) for i in range(1, len(port_list) + 1)]

    # 1. chassis
    chassis_url = ixn + '/availableHardware/chassis'
    if cfg.CHASSIS_IP not in [c.get('hostname') for c in rest.get(chassis_url)]:
        rest.create(ixn + '/availableHardware', 'chassis', {'hostname': cfg.CHASSIS_IP})
    _wait(lambda: all(c.get('state') == 'ready' for c in rest.get(chassis_url)
                      if c.get('hostname') == cfg.CHASSIS_IP), 120, 'chassis ready')

    # 2. vports (reuse by name, create the missing ones)
    existing = {v['name']: v['href'] for v in rest.list(ixn + '/vport')}
    vports = [existing.get(n) or rest.create(ixn, 'vport', {'name': n}) for n in names]

    # 3. map each vport to its test port, then force ownership
    for vport, (card, port) in zip(vports, port_list):
        rest.patch(vport, {'location': '{};{};{}'.format(cfg.CHASSIS_IP, card, port)})
    rest.operation(ixn + '/vport', 'connectPorts', vports, True)

    # 4. Layer 1 BEFORE waiting for link (fiber never links up with copper settings)
    for vport in vports:
        set_l1(lab, vport, media, speed)

    # 5. link up
    LOG.info('Waiting up to %ss for link up on %s', link_up_timeout, names)
    _wait(lambda: all(rest.get(v).get('connectionState') == 'connectedLinkUp' for v in vports),
          link_up_timeout, 'link up')
    return vports


def set_l1(lab, vport, media=None, speed=None):
    """The L1 object is named after the card type: <vport>/l1Config/<vport.type>."""
    if not (media or speed):
        return
    vport_type = lab.rest.get(vport)['type']
    payload = {}
    if media:
        payload['media'] = media
    if speed:
        payload['selectedSpeeds'] = [speed]
    try:
        lab.rest.patch('{}/l1Config/{}'.format(vport, vport_type), payload)
    except IxnRestError as err:
        LOG.warning('%s: could not set L1 %s: %s', vport, payload, err)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------
def start_protocols(lab, settle_seconds=10):
    """POST <ixn>/operations/startallprotocols {"arg1": "sync"}"""
    LOG.info('Starting all protocols')
    lab.rest.operation(lab.ixn, 'startAllProtocols', 'sync')
    time.sleep(settle_seconds)


def verify_protocol_sessions(lab, timeout=90):
    """Poll the 'Protocols Summary' view until no session is Down or Not Started."""
    start = time.time()
    while True:
        cols, rows = lab.rest.read_view(lab.ixn, 'Protocols Summary')
        table = [dict(zip(cols, r)) for r in rows]
        if all(r['Sessions Down'] == '0' and r['Sessions Not Started'] == '0' for r in table):
            break
        if time.time() - start > timeout:
            raise IxnRestError('Protocol sessions not all up after {}s: {}'.format(timeout, table))
        time.sleep(5)
    for r in table:
        print('  {:<20} up={:<6} down={:<6} notStarted={:<6} total={}'.format(
            r['Protocol Type'], r['Sessions Up'], r['Sessions Down'],
            r['Sessions Not Started'], r['Sessions Total']))


# ---------------------------------------------------------------------------
# Traffic
# ---------------------------------------------------------------------------
def apply_traffic(lab):
    """Generate + apply every traffic item.

    REST calls:
      GET  <ixn>/traffic/trafficItem                                  list the items
      POST <ixn>/traffic/trafficItem/operations/generate {"arg1": [<item hrefs>]}
      POST <ixn>/traffic/operations/apply {"arg1": "<ixn>/traffic"}
    """
    rest, ixn = lab.rest, lab.ixn
    items = [t['href'] for t in rest.list(ixn + '/traffic/trafficItem')]
    rest.operation(ixn + '/traffic/trafficItem', 'generate', items)
    try:
        rest.operation(ixn + '/traffic', 'apply', ixn + '/traffic')
    except IxnRestError:
        for item in rest.get(ixn + '/traffic/trafficItem'):     # the real reason is per item
            LOG.warning('%s: errors=%s warnings=%s', item.get('name'), item.get('errors'),
                        item.get('warnings'))
        raise


def run_traffic(lab, timeout=60, apply=True):
    """Apply, start, wait until traffic stops by itself (fixed frame count / duration).
    Pass apply=False if apply_traffic() was already called (lesson 06).

    REST calls:
      POST <ixn>/traffic/operations/startstatelesstrafficblocking {"arg1": ["<ixn>/traffic"]}
      GET  <ixn>/traffic                                    poll "state" until "stopped"
      POST <ixn>/traffic/operations/stopstatelesstrafficblocking {"arg1": ["<ixn>/traffic"]}
    """
    rest, traffic = lab.rest, lab.ixn + '/traffic'
    if apply:
        apply_traffic(lab)
    LOG.info('Starting traffic')
    rest.operation(traffic, 'startStatelessTrafficBlocking', [traffic])
    start = time.time()
    while True:
        state = rest.get(traffic).get('state')
        if state == 'stopped':
            break
        if time.time() - start > timeout:
            LOG.warning('Traffic still running after %ss - stopping it', timeout)
            rest.operation(traffic, 'stopStatelessTrafficBlocking', [traffic])
            break
        LOG.info('Traffic state: %s', state)
        time.sleep(5)
    time.sleep(5)    # let the last counters arrive


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def view_to_csv(lab, caption, filename):
    """Read every page of a statistic view and save it to results/<filename>."""
    cols, rows = lab.rest.read_view(lab.ixn, caption)
    path = os.path.join(RESULTS_DIR, filename)
    with open(path, 'w', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        writer.writerows(rows)
    LOG.info('Saved "%s" -> %s', caption, path)
    return cols, rows


def export_views(lab, contains, prefix, timeout=30):
    """Save every view whose caption contains <contains> (case-insensitive) to CSV.
    Drill-down views only fill in when opened in the GUI: they time out and are skipped."""
    for caption in lab.rest.view_captions(lab.ixn):
        if caption and contains.lower() in caption.lower():
            try:
                cols, rows = lab.rest.read_view(lab.ixn, caption, timeout=timeout)
            except IxnRestError as err:
                LOG.warning('Skipping view "%s": %s', caption, err)
                continue
            path = os.path.join(RESULTS_DIR, '{}_{}.csv'.format(prefix, re.sub(r'\W+', '_', caption)))
            with open(path, 'w', newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(cols)
                writer.writerows(rows)
            LOG.info('Saved "%s" -> %s', caption, path)


def check_traffic_loss(lab):
    """PASS when every traffic item has Tx > 0 and Tx == Rx."""
    cols, rows = lab.rest.read_view(lab.ixn, 'Traffic Item Statistics')
    passed = True
    for row in (dict(zip(cols, r)) for r in rows):
        tx, rx = int(row['Tx Frames']), int(row['Rx Frames'])
        ok = tx > 0 and tx == rx
        passed &= ok
        print('{:<40} Tx={:<12} Rx={:<12} Loss%={:<8} {}'.format(
            row['Traffic Item'], tx, rx, row['Loss %'], 'PASS' if ok else 'FAIL'))
    return passed


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------
def get_child(lab, parent, name):
    """Read a child that exists exactly once, e.g. <staticMacsec>/txSakPool, <mka>/cakCache,
    <vport>/capture. Returns (attributes, href).
    GET <parent>/<name> answers with ONE object on some builds and a one-item list on
    others: accept both. A single object lives at <parent>/<name> itself (like
    <configElement>/frameSize); a list item carries its own href in links[0].href."""
    url = '{}/{}'.format(parent, name)
    obj = lab.rest.get(url)
    if isinstance(obj, list):
        obj = obj[0]
        href = obj.get('href') or (obj['links'][0]['href'] if obj.get('links')
                                   else '{}/{}'.format(url, obj['id']))
    else:
        href = obj.get('href') or url
    return obj, href


def count_capture_packets(path):
    """Count the packets in a downloaded .cap (pcapng) file - pure Python, no Wireshark.
    More reliable than <vport>/capture dataPacketCounter, which can stay 0 via the API."""
    count = 0
    with open(path, 'rb') as fh:
        data = fh.read()
    endian = '<' if data[8:12] == b'\x4d\x3c\x2b\x1a' else '>'    # byte-order magic
    offset = 0
    while offset + 8 <= len(data):
        block_type, block_len = struct.unpack(endian + 'II', data[offset:offset + 8])
        if block_type in (2, 3, 6):          # (obsolete / simple / enhanced) packet blocks
            count += 1
        if block_len < 12:
            break                            # corrupt file: stop instead of looping
        offset += block_len
    return count


# ---------------------------------------------------------------------------
def _wait(condition, timeout, what, interval=3):
    start = time.time()
    while not condition():
        if time.time() - start > timeout:
            raise IxnRestError('Timeout after {}s waiting for {}'.format(timeout, what))
        time.sleep(interval)
