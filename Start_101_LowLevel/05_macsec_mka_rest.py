"""
05_macsec_mka_rest.py
=====================
Lesson 5 (low level) - MACsec with MKA (802.1X MACsec Key Agreement), as REST calls.

Same test as ../Start_101/05_macsec_mka.py. The peers share a pre-shared CAK + CKN,
run MKA, elect a key server, and the key server distributes the SAK. Each port:

    Topology -> DeviceGroup -> Ethernet ─┬─ mka            (control plane: CAK/CKN, key server)
                                         │    └─ cakCache  (CAK value + name)
                                         └─ staticMacsec   (data plane: encrypts with the MKA SAK)

    POST  <ethernet>/mka                   {"name": ...}
    PATCH <mka>                            {"cakCount": 1}
    GET   <mka>          -> keyServerPriority, keyDerivationFunction are multivalues
    GET   <mka>/cakCache -> cakValue128, cakValue256, cakName are multivalues
    PATCH <multivalue>/singleValue         {"value": ...}
    POST  <ethernet>/staticMacsec          (no SAK pool: the key comes from MKA)

    Verify: 'Protocols Summary' shows MKA and Static MACsec sessions Up;
            'MKA Per Port' shows MKPDU Tx/Rx and the live peer count.

Run
  python 05_macsec_mka_rest.py
"""
import lab_config as cfg
from common_rest import (check_traffic_loss, connect_ports, export_views, get_child,
                         ixnetwork_session, run_traffic, start_protocols,
                         verify_protocol_sessions, view_to_csv)

# ----------------------------- test parameters --------------------------------
PORT_MACS = ['00:11:01:00:00:01', '00:12:01:00:00:01']
DUT_MACS = None              # DUT interface MACs if the DUT terminates MACsec (see lesson 4)
SOURCE_IPS = ['101.1.1.1', '101.1.2.1']

# CAK: 32 hex chars (128-bit, KDF AES-CMAC-128) or 64 hex chars (256-bit, AES-CMAC-256)
CAK = 'f123456789abcdef0123456789abcdeff123456789abcdef0123456789abcdef'
CKN = 'f123456789abcdef'         # CAK name, hex, must match the DUT
KEY_SERVER_PRIORITY = [10, 20]   # lower value = higher priority -> port 1 becomes key server
                                 # use 255 on both ports to let the DUT be the key server
REKEY_INTERVAL_SEC = 30          # optional periodic rekey (see the commented PATCH below)

FRAME_SIZE = 512
LINE_RATE_PERCENT = 90
FRAMES = 10000
# --------------------------------------------------------------------------------

with ixnetwork_session('lesson05-macsec-mka') as lab:
    rest, ixn = lab.rest, lab.ixn
    vports = connect_ports(lab, cfg.PORTS[:2])

    macsec_endpoints = []
    for idx, vport in enumerate(vports):
        topology = rest.create(ixn, 'topology', {'name': 'MKA_Topo_{}'.format(idx + 1), 'ports': [vport]})
        device_group = rest.create(topology, 'deviceGroup', {'name': 'MKA_DG_{}'.format(idx + 1),
                                                             'multiplier': 1})
        ethernet = rest.create(device_group, 'ethernet', {'name': 'Eth_{}'.format(idx + 1)})
        rest.set_multivalue(rest.get(ethernet)['mac'], 'singleValue', {'value': PORT_MACS[idx]})

        # --- MKA (control plane) ------------------------------------------------------
        mka = rest.create(ethernet, 'mka', {'name': 'MKA_{}'.format(idx + 1)})
        rest.patch(mka, {'cakCount': 1})
        mka_attrs = rest.get(mka)
        rest.set_multivalue(mka_attrs['keyServerPriority'], 'singleValue',
                            {'value': KEY_SERVER_PRIORITY[idx]})

        bits = '128' if len(CAK) == 32 else '256'
        rest.set_multivalue(mka_attrs['keyDerivationFunction'], 'singleValue',
                            {'value': 'aescmac' + bits})
        cak_cache, _ = get_child(lab, mka, 'cakCache')
        rest.set_multivalue(cak_cache['cakValue' + bits], 'singleValue', {'value': CAK})
        rest.set_multivalue(cak_cache['cakName'], 'singleValue', {'value': CKN})

        # Periodic rekey every N seconds (the key server distributes a new SAK):
        # rest.patch(mka, {'rekeyMode': 'timerBased', 'rekeyBehaviour': 'rekeyContinuous',
        #                  'periodicRekeyInterval': REKEY_INTERVAL_SEC})

        # --- MACsec (data plane) --------------------------------------------------------
        smac = rest.create(ethernet, 'staticMacsec', {'name': 'MACsec_{}'.format(idx + 1)})
        rest.patch(smac, {'encryptedTrafficType': 'statelessL23'})
        smac_attrs = rest.get(smac)
        rest.set_multivalue(smac_attrs['dutMac'], 'singleValue',
                            {'value': DUT_MACS[idx] if DUT_MACS else PORT_MACS[1 - idx]})
        rest.set_multivalue(smac_attrs['sourceIp'], 'singleValue', {'value': SOURCE_IPS[idx]})
        rest.set_multivalue(smac_attrs['endStation'], 'singleValue', {'value': True})
        macsec_endpoints.append(smac)

    # --- bring up MKA and verify -----------------------------------------------------------
    start_protocols(lab, settle_seconds=20)
    verify_protocol_sessions(lab)               # MKA + Static MACsec sessions Up, none Down
    export_views(lab, 'mka', 'lesson05')        # 'MKA Per Port': MKPDUs, live peers ...

    # --- encrypted traffic ------------------------------------------------------------------
    traffic_item = rest.create(ixn + '/traffic', 'trafficItem',
                               {'name': 'MKA_Encrypted', 'trafficType': 'ethernetVlan',
                                'biDirectional': True})
    rest.create(traffic_item, 'endpointSet',
                {'sources': [macsec_endpoints[0]], 'destinations': [macsec_endpoints[1]]})
    # No trackBy here: MACsec traffic rejects trackingenabled0 at apply (see lesson 4).
    config_element = rest.list(traffic_item + '/configElement')[0]['href']
    rest.patch(config_element + '/frameSize', {'type': 'fixed', 'fixedSize': FRAME_SIZE})
    rest.patch(config_element + '/frameRate', {'type': 'percentLineRate', 'rate': LINE_RATE_PERCENT})
    rest.patch(config_element + '/transmissionControl', {'type': 'fixedFrameCount', 'frameCount': FRAMES})

    run_traffic(lab)
    passed = check_traffic_loss(lab)
    view_to_csv(lab, 'Traffic Item Statistics', 'lesson05_traffic_items.csv')
    export_views(lab, 'macsec', 'lesson05')

    print('\nRESULT: {}'.format('PASS' if passed else 'FAIL'))
