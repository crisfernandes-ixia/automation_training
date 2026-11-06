"""
common.py - Small helpers shared by all Start_101 scripts.

Nothing here is magic: each helper wraps a few RestPy calls so the numbered
scripts can focus on the concept being taught. Read this file once you are
comfortable with 01_create_and_delete_session.py.
"""
import contextlib
import csv
import datetime
import getpass
import os
import re
import struct
import time

from ixnetwork_restpy import SessionAssistant, StatViewAssistant

import lab_config as cfg

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, 'results')
CONFIGS_DIR = os.path.join(HERE, 'configs')


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def unique_session_name(prefix=cfg.SESSION_PREFIX):
    """<prefix>-<user>-<timestamp>: easy to spot in the Web UI session list."""
    user = getpass.getuser().replace(' ', '_')
    return '{}-{}-{:%Y%m%d-%H%M%S}'.format(prefix, user, datetime.datetime.now())


@contextlib.contextmanager
def ixnetwork_session(prefix=cfg.SESSION_PREFIX, clear_config=True, keep=cfg.KEEP_SESSION):
    """Create (or connect to) an IxNetwork session and ALWAYS clean it up.

    Usage:
        with ixnetwork_session('demo') as session:
            ixnetwork = session.Ixnetwork
            ...

    The 'finally' block runs even if your test raises an exception, so the
    session and its license are released. On a Windows GUI API server there is
    only one session and it cannot be deleted, so we release the ports instead.
    """
    name = unique_session_name(prefix)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    session = SessionAssistant(
        IpAddress=cfg.API_SERVER,
        RestPort=cfg.REST_PORT,
        UserName=cfg.USERNAME,
        Password=cfg.PASSWORD,
        SessionName=name,            # ignored (with a warning) on Windows GUI
        ClearConfig=clear_config,    # start from an empty configuration
        LogLevel=cfg.LOG_LEVEL,
        LogFilename=os.path.join(RESULTS_DIR, name + '.log'),
    )
    ixnetwork = session.Ixnetwork
    ixnetwork.info('Connected: platform={} session id={} name={}'.format(
        session.TestPlatform.Platform, session.Session.Id, session_name(session)))
    try:
        yield session
    finally:
        cleanup_session(session, keep)


def session_name(session):
    """Session name, or '<none>' on the Windows GUI (which has no name property)."""
    try:
        return session.Session.Name
    except KeyError:
        return '<none>'


def cleanup_session(session, keep=False):
    ixnetwork = session.Ixnetwork
    try:
        if ixnetwork.Traffic.State == 'started':
            ixnetwork.Traffic.StopStatelessTrafficBlocking()
        ixnetwork.StopAllProtocols(Arg1='sync')
    except Exception as err:  # never let cleanup hide the original error
        ixnetwork.warn('Cleanup: could not stop traffic/protocols: {}'.format(err))

    if keep:
        ixnetwork.warn('KEEP_SESSION is set - session "{}" left running. '
                       'Delete it when you are done!'.format(session_name(session)))
        return

    if session.TestPlatform.Platform == 'windows':
        ixnetwork.info('Windows API server: releasing ports (the GUI session cannot be deleted)')
        try:
            ixnetwork.Vport.find().ReleasePort()
            ixnetwork.NewConfig()
        except Exception as err:
            ixnetwork.warn('Could not release ports: {}'.format(err))
    else:
        ixnetwork.info('Deleting session "{}"'.format(session.Session.Name))
        session.Session.remove()


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
def connect_ports(session, port_list, names=None, media=cfg.PORT_MEDIA, speed=cfg.PORT_SPEED,
                  link_up_timeout=120):
    """Map (card, port) tuples to virtual ports, take ownership, apply L1, wait for link up.

    If the configuration already has vports with these names (e.g. after LoadConfig)
    they are reused; otherwise new vports are created.
    Returns the list of Vport objects in the same order as port_list.
    """
    ixnetwork = session.Ixnetwork
    names = names or ['Port_{}'.format(i) for i in range(1, len(port_list) + 1)]
    port_map = session.PortMapAssistant()
    for (card, port), name in zip(port_list, names):
        port_map.Map(IpAddress=cfg.CHASSIS_IP, CardId=card, PortId=port, Name=name)

    ixnetwork.info('Connecting ports {} on chassis {}'.format(port_list, cfg.CHASSIS_IP))
    # Don't wait for link yet: the port comes up with its default L1 (e.g. copper)
    # and would never link with fiber optics. Set L1 first, then wait.
    port_map.Connect(ForceOwnership=True, IgnoreLinkUp=True)

    vports = [ixnetwork.Vport.find(Name='^{}$'.format(n)) for n in names]
    for vport in vports:
        set_l1(vport, media, speed)
    wait_for_link_up(session, names, timeout=link_up_timeout)
    return vports


def wait_for_link_up(session, names, timeout=120):
    """Wait until every named vport shows 'Link Up' in Port Statistics."""
    session.Ixnetwork.info('Waiting up to {}s for link up on {}'.format(timeout, names))
    view = session.StatViewAssistant('Port Statistics', Timeout=timeout)
    view.AddRowFilter('Port Name', StatViewAssistant.REGEX,
                      '^({})$'.format('|'.join(names)))
    view.CheckCondition('Link State', StatViewAssistant.REGEX, '^Link Up$', Timeout=timeout)


def set_l1(vport, media=None, speed=None):
    """Set media/speed. The L1 object name depends on the card type (vport.Type),
    e.g. 'novusTenGigLan' -> vport.L1Config.NovusTenGigLan."""
    if not (media or speed):
        return
    l1_name = vport.Type[0].upper() + vport.Type[1:]
    l1 = getattr(vport.L1Config, l1_name, None)
    if l1 is None:
        vport.parent.warn('{}: no L1Config.{} - L1 left at default'.format(vport.Name, l1_name))
        return
    try:
        if media:
            l1.Media = media
        if speed:
            l1.SelectedSpeeds = [speed]
        vport.parent.info('{}: L1 {} set to media={} speed={}'.format(
            vport.Name, l1_name, media, speed))
    except Exception as err:
        vport.parent.warn('{}: could not set L1 {}/{}: {}'.format(vport.Name, media, speed, err))


# ---------------------------------------------------------------------------
# Protocols & traffic
# ---------------------------------------------------------------------------
def start_protocols_and_wait(ixnetwork, settle_seconds=10):
    ixnetwork.info('Starting all protocols')
    ixnetwork.StartAllProtocols(Arg1='sync')
    time.sleep(settle_seconds)


def verify_protocol_sessions(session, view_name='Protocols Summary', timeout=90):
    """Wait until every protocol in 'Protocols Summary' has all sessions up."""
    view = session.StatViewAssistant(view_name)
    view.CheckCondition('Sessions Not Started', StatViewAssistant.EQUAL, 0, Timeout=timeout)
    view.CheckCondition('Sessions Down', StatViewAssistant.EQUAL, 0, Timeout=timeout)
    print(view)


def apply_traffic(ixnetwork):
    """Generate + apply every traffic item (push the streams to the ports)."""
    for ti in ixnetwork.Traffic.TrafficItem.find():
        ti.Generate()
    try:
        ixnetwork.Traffic.Apply()
    except Exception:
        # The REST error is generic; the real reason is on each traffic item.
        for ti in ixnetwork.Traffic.TrafficItem.find():
            ixnetwork.warn('{}: errors={} warnings={}'.format(ti.Name, ti.Errors, ti.Warnings))
        raise


def run_traffic(ixnetwork, timeout=60, apply=True):
    """Generate + apply + start traffic, then wait until it stops by itself
    (use fixedFrameCount / fixedDuration in the traffic item) and stats are ready.
    Pass apply=False if you already called apply_traffic()."""
    if apply:
        apply_traffic(ixnetwork)
    ixnetwork.info('Starting traffic')
    ixnetwork.Traffic.StartStatelessTrafficBlocking()

    start = time.time()
    while ixnetwork.Traffic.State != 'stopped':
        if time.time() - start > timeout:
            ixnetwork.warn('Traffic still running after {}s - stopping it'.format(timeout))
            ixnetwork.Traffic.StopStatelessTrafficBlocking()
            break
        ixnetwork.info('Traffic state: {}'.format(ixnetwork.Traffic.State))
        time.sleep(5)
    time.sleep(5)  # let the last counters arrive


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def stat_view_to_csv(session, view_name, filename=None, timeout=180):
    """Snapshot any statistic view (as named in the GUI) to results/<file>.csv.
    Returns (columns, rows) so the caller can also assert on the values."""
    # StatViewAssistant treats the name as a regex: escape captions like 'MACsec (Per Port)'.
    rows = session.StatViewAssistant(re.escape(view_name), Timeout=timeout).Rows
    filename = filename or view_name.replace(' ', '_') + '.csv'
    path = os.path.join(RESULTS_DIR, filename)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(path, 'w', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(rows.Columns)
        writer.writerows(rows.RawData)
    session.Ixnetwork.info('Saved "{}" -> {}'.format(view_name, path))
    return rows.Columns, rows.RawData


def export_views(session, contains, prefix, timeout=30):
    """Save every view whose name contains <contains> to results/<prefix>_<view>.csv.
    Some views (drill-downs, disabled views) never become ready: they are skipped."""
    for view in list_views(session, contains):
        try:
            stat_view_to_csv(session, view, '{}_{}.csv'.format(prefix, re.sub(r'\W+', '_', view)),
                             timeout=timeout)
        except Exception as err:
            session.Ixnetwork.warn('Skipping view "{}": {}'.format(view, err))


def count_capture_packets(path):
    """Count the packets in a downloaded .cap file (pcapng, what IxNetwork saves).
    More reliable than vport.Capture.*PacketCounter, which can stay 0 via the API."""
    count = 0
    with open(path, 'rb') as fh:
        data = fh.read()
    endian = '<' if data[8:12] == b'\x4d\x3c\x2b\x1a' else '>'   # byte-order magic
    offset = 0
    while offset + 8 <= len(data):
        block_type, block_len = struct.unpack(endian + 'II', data[offset:offset + 8])
        if block_type in (2, 3, 6):          # (obsolete / simple / enhanced) packet blocks
            count += 1
        if block_len < 12:
            break                            # corrupt file: stop instead of looping
        offset += block_len
    return count


def check_traffic_loss(session, view_name='Traffic Item Statistics'):
    """Print Tx/Rx per traffic item and return True if there is no frame loss."""
    passed = True
    for row in session.StatViewAssistant(view_name).Rows:
        tx, rx = int(row['Tx Frames']), int(row['Rx Frames'])
        status = 'PASS' if tx > 0 and tx == rx else 'FAIL'
        passed &= status == 'PASS'
        print('{:<40} Tx={:<12} Rx={:<12} Loss%={:<8} {}'.format(
            row['Traffic Item'], tx, rx, row['Loss %'], status))
    return passed


def list_views(session, contains=''):
    """List the statistic view names available right now (they appear as
    protocols/traffic are configured), optionally filtered by a substring."""
    names = StatViewAssistant.GetViewNames(session.Ixnetwork)
    return [n for n in names if contains.lower() in n.lower()]


# ---------------------------------------------------------------------------
# Learning aid
# ---------------------------------------------------------------------------
def describe(obj):
    """Print the properties and methods of any RestPy object, e.g.
        describe(ethernet.StaticMacsec.find())
    Same information as the REST API browser, without leaving Python."""
    names = sorted(n for n in dir(type(obj)) if n[0].isupper())
    print('{} -> {}'.format(type(obj).__name__, ', '.join(names)))
