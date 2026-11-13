"""
04_macsec_static_sak_rest.py
============================
Lesson 4 (low level) - MACsec (IEEE 802.1AE) with STATIC keys, as REST calls.

Same test as ../Start_101/04_macsec_static_sak.py. Stack on each port:

    Topology -> DeviceGroup -> Ethernet -> staticMacsec         (encrypted endpoint)
                                             ├── txSakPool      (key used to encrypt)
                                             └── rxSakPool      (key used to decrypt)

    POST  <ethernet>/staticMacsec                 {"name": ...}
    PATCH <staticMacsec>                          {"encryptedTrafficType": "statelessL23"}
    GET   <staticMacsec>  -> dutMac, sourceIp, endStation are multivalues
    PATCH <staticMacsec>                          {"txSakPoolSize": 1, "rxSakPoolSize": 1}
    GET   <staticMacsec>/txSakPool -> {"txSak128": <multivalue>, "txSak256": <multivalue>}
    PATCH <multivalue>/singleValue                {"value": "<32 hex chars>"}

    Traffic: the endpoints are the staticMacsec objects -> the port encrypts the frames.
    POST  <ixn>/traffic/trafficItem               {"trafficType": "ethernetVlan", ...}
    POST  <trafficItem>/endpointSet               {"sources": [<staticMacsec 1>], "destinations": [<staticMacsec 2>]}
    PATCH <configElement>/framePayload            {"type": "custom", "customPattern": "CAFEC0FFEE", ...}
    POST  <ixn>/operations/clearstats             before each frame size

DUT scenarios (DUT_MACS):
  a) DUT terminates MACsec on each link: DUT_MACS = MACs of the DUT interfaces.
  b) Back to back / transparent DUT:      DUT_MACS = None (each side uses the peer port MAC).

Run
  python 04_macsec_static_sak_rest.py
"""
import lab_config as cfg
from common_rest import (LOG, check_traffic_loss, connect_ports, export_views, get_child,
                         ixnetwork_session, run_traffic, start_protocols, view_to_csv)

# ----------------------------- test parameters --------------------------------
PORT_MACS = ['00:11:01:00:00:01', '00:12:01:00:00:01']
DUT_MACS = None        # e.g. ['6c:6c:d3:ac:6a:8b', '6c:6c:d3:ac:6a:8c'] for scenario (a)
SOURCE_IPS = ['101.1.1.1', '101.1.2.1']

# 128-bit SAK = 32 hex chars, 256-bit SAK = 64 hex chars (needs a 256-bit cipher suite)
SAK = 'f123456789caffee0123456789abcdef'

FRAME_SIZES = [64, 512, 1500]  # one run per size; MACsec adds 24-32 bytes on the wire
LINE_RATE_PERCENT = 90         # leave headroom for the SecTAG + ICV overhead
FRAMES_PER_RUN = 10000
# --------------------------------------------------------------------------------

with ixnetwork_session('lesson04-macsec-static') as lab:
    rest, ixn = lab.rest, lab.ixn
    vports = connect_ports(lab, cfg.PORTS[:2])

    macsec_endpoints = []
    for idx, vport in enumerate(vports):
        topology = rest.create(ixn, 'topology', {'name': 'MACsec_Topo_{}'.format(idx + 1), 'ports': [vport]})
        device_group = rest.create(topology, 'deviceGroup', {'name': 'MACsec_DG_{}'.format(idx + 1),
                                                             'multiplier': 1})
        ethernet = rest.create(device_group, 'ethernet', {'name': 'Eth_{}'.format(idx + 1)})
        rest.set_multivalue(rest.get(ethernet)['mac'], 'singleValue', {'value': PORT_MACS[idx]})

        # --- the MACsec layer -------------------------------------------------------
        smac = rest.create(ethernet, 'staticMacsec', {'name': 'StaticMACsec_{}'.format(idx + 1)})
        rest.patch(smac, {'encryptedTrafficType': 'statelessL23'})   # L2/L3 (vs 'statefulL47')

        attrs = rest.get(smac)          # per-device fields are multivalue hrefs
        peer_mac = DUT_MACS[idx] if DUT_MACS else PORT_MACS[1 - idx]
        rest.set_multivalue(attrs['dutMac'], 'singleValue', {'value': peer_mac})          # dest MAC of encrypted frames
        rest.set_multivalue(attrs['sourceIp'], 'singleValue', {'value': SOURCE_IPS[idx]})  # IP inside the payload
        rest.set_multivalue(attrs['endStation'], 'singleValue', {'value': True})          # TCI ES bit
        # Other knobs work the same way, e.g. attrs['includeSci'], attrs['enableConfidentiality'],
        # attrs['confidentialityOffset']. GET <staticMacsec> lists them all.

        # --- keys: pool size first, then the key multivalue inside each pool ---------
        rest.patch(smac, {'txSakPoolSize': 1, 'rxSakPoolSize': 1})
        bits = '128' if len(SAK) == 32 else '256'
        tx_pool, _ = get_child(lab, smac, 'txSakPool')
        rx_pool, _ = get_child(lab, smac, 'rxSakPool')
        rest.set_multivalue(tx_pool['txSak' + bits], 'singleValue', {'value': SAK})
        rest.set_multivalue(rx_pool['rxSak' + bits], 'singleValue', {'value': SAK})

        macsec_endpoints.append(smac)

    # Start protocols: brings the MACsec endpoints up
    start_protocols(lab)

    # --- encrypted traffic ------------------------------------------------------------
    traffic_item = rest.create(ixn + '/traffic', 'trafficItem',
                               {'name': 'MACsec_Encrypted', 'trafficType': 'ethernetVlan',
                                'biDirectional': True})
    rest.create(traffic_item, 'endpointSet',
                {'sources': [macsec_endpoints[0]], 'destinations': [macsec_endpoints[1]]})
    # No trackBy here: MACsec traffic rejects trackingenabled0 at apply. The stats row is
    # named 'Quick Flow Groups Egress Only' in Traffic Item Statistics.
    config_element = rest.list(traffic_item + '/configElement')[0]['href']
    rest.patch(config_element + '/frameRate', {'type': 'percentLineRate', 'rate': LINE_RATE_PERCENT})
    rest.patch(config_element + '/transmissionControl', {'type': 'fixedFrameCount',
                                                         'frameCount': FRAMES_PER_RUN})
    rest.patch(config_element + '/framePayload', {'type': 'custom', 'customPattern': 'CAFEC0FFEE',
                                                  'customRepeat': True})

    results = {}
    for size in FRAME_SIZES:
        LOG.info('=== Frame size %s ===', size)
        rest.patch(config_element + '/frameSize', {'type': 'fixed', 'fixedSize': size})
        rest.operation(ixn, 'clearStats')
        run_traffic(lab)                       # generate + apply pick up the new size
        results[size] = check_traffic_loss(lab)
        view_to_csv(lab, 'Traffic Item Statistics', 'lesson04_traffic_{}B.csv'.format(size))

    # --- MACsec statistic views (protected/encrypted packets, ICV errors ...) -----------
    export_views(lab, 'macsec', 'lesson04')

    print('\nSummary: ' + ', '.join('{}B={}'.format(s, 'PASS' if ok else 'FAIL')
                                   for s, ok in results.items()))
