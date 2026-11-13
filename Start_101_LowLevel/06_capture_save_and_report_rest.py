"""
06_capture_save_and_report_rest.py
==================================
Lesson 6 (low level) - Captures, saved config and reports, as REST calls.

Same test as ../Start_101/06_capture_save_and_report.py: a small eBGP setup with
advertised routes and FINITE traffic, so both capture planes have something to show.

    Port 1                                   Port 2 (captured)
    Topology -> DG -> Ethernet -> IPv4 -> BGP  <-- eBGP -->  BGP <- IPv4 <- Ethernet <- DG <- Topology
                 └── NetworkGroup (routes advertised over BGP) ┘

    POST  <ipv4>/bgpIpv4Peer                        {"name": ...}  (type/localAs2Bytes/dutIp/timers: multivalues)
    POST  <deviceGroup>/networkGroup                {"name": ..., "multiplier": 10}
    POST  <networkGroup>/ipv4PrefixPools            {"numberOfAddresses": 1}
    PATCH <vport>                                   {"rxMode": "captureAndMeasure"}
    PATCH <vport>/capture                           {"hardwareEnabled": true, "softwareEnabled": true}
    POST  <ixn>/operations/startcapture | stopcapture
    POST  <ipv4>/operations/sendarp                 {"arg1": [<ipv4>]}
    POST  <ixn>/operations/savecapturefiles         {"arg1": "<folder on the API server>"}  -> list of files
    POST  <ixn>/operations/saveconfig               {"arg1": "lesson06_saved.ixncfg"}
    GET   <ixn>/files?filename=<file>               download (captures and config)

The ORDER matters: apply traffic -> start capture -> generate events -> stop capture.

Run
  python 06_capture_save_and_report_rest.py
"""
import os
import time

import lab_config as cfg
from common_rest import (LOG, RESULTS_DIR, apply_traffic, check_traffic_loss, connect_ports,
                         count_capture_packets, export_views, get_child, ixnetwork_session,
                         run_traffic, start_protocols, verify_protocol_sessions, view_to_csv)

# ----------------------------- test parameters --------------------------------
PORT_IPS = ['10.1.0.1', '10.1.0.2']           # same subnet, back to back / through an L2 DUT
BGP_AS = [65001, 65002]                        # different AS -> eBGP
ROUTE_START = ['201.1.0.0', '202.1.0.0']       # routes advertised by each side
ROUTES_PER_PORT = 10
KEEPALIVE_SEC = 5                              # short timers -> KEEPALIVEs show up in the capture

FRAMES = 1000                                  # per direction: a capture you can open in Wireshark
FRAME_SIZE = 256
LINE_RATE_PERCENT = 1
# --------------------------------------------------------------------------------

with ixnetwork_session('lesson06') as lab:
    rest, ixn = lab.rest, lab.ixn
    vports = connect_ports(lab, cfg.PORTS[:2])

    # 1. Build the config: IPv4 + eBGP + advertised routes on each port -------------
    ipv4_stacks, route_pools = [], []
    for idx, vport in enumerate(vports):
        topology = rest.create(ixn, 'topology', {'name': 'BGP_Topo_{}'.format(idx + 1), 'ports': [vport]})
        device_group = rest.create(topology, 'deviceGroup', {'name': 'BGP_DG_{}'.format(idx + 1),
                                                             'multiplier': 1})
        ethernet = rest.create(device_group, 'ethernet', {'name': 'Eth_{}'.format(idx + 1)})
        rest.set_multivalue(rest.get(ethernet)['mac'], 'singleValue',
                            {'value': '00:1{}:01:00:00:01'.format(idx + 1)})

        ipv4 = rest.create(ethernet, 'ipv4', {'name': 'IPv4_{}'.format(idx + 1)})
        ip = rest.get(ipv4)
        rest.set_multivalue(ip['address'], 'singleValue', {'value': PORT_IPS[idx]})
        rest.set_multivalue(ip['gatewayIp'], 'singleValue', {'value': PORT_IPS[1 - idx]})
        rest.set_multivalue(ip['prefix'], 'singleValue', {'value': 24})

        bgp = rest.create(ipv4, 'bgpIpv4Peer', {'name': 'BGP_{}'.format(idx + 1)})
        peer = rest.get(bgp)
        rest.set_multivalue(peer['type'], 'singleValue', {'value': 'external'})
        rest.set_multivalue(peer['localAs2Bytes'], 'singleValue', {'value': BGP_AS[idx]})
        rest.set_multivalue(peer['dutIp'], 'singleValue', {'value': PORT_IPS[1 - idx]})   # the neighbor
        rest.set_multivalue(peer['keepaliveTimer'], 'singleValue', {'value': KEEPALIVE_SEC})
        rest.set_multivalue(peer['holdTimer'], 'singleValue', {'value': KEEPALIVE_SEC * 3})

        # Routes behind this port, advertised to the neighbor in a BGP UPDATE.
        network_group = rest.create(device_group, 'networkGroup',
                                    {'name': 'Routes_{}'.format(idx + 1), 'multiplier': ROUTES_PER_PORT})
        pool = rest.create(network_group, 'ipv4PrefixPools', {'numberOfAddresses': 1})
        pool_attrs = rest.get(pool)
        rest.set_multivalue(pool_attrs['networkAddress'], 'counter',
                            {'start': ROUTE_START[idx], 'step': '0.0.1.0', 'direction': 'increment'})
        rest.set_multivalue(pool_attrs['prefixLength'], 'singleValue', {'value': 24})

        ipv4_stacks.append(ipv4)
        route_pools.append(pool)

    # 2. Traffic between the advertised routes - FINITE --------------------------------
    traffic_item = rest.create(ixn + '/traffic', 'trafficItem',
                               {'name': 'BGP_Routes', 'trafficType': 'ipv4', 'biDirectional': True})
    rest.create(traffic_item, 'endpointSet', {'sources': [route_pools[0]],
                                              'destinations': [route_pools[1]]})
    tracking = rest.list(traffic_item + '/tracking')[0]['href']
    rest.patch(tracking, {'trackBy': ['trackingenabled0']})
    config_element = rest.list(traffic_item + '/configElement')[0]['href']
    rest.patch(config_element + '/frameSize', {'type': 'fixed', 'fixedSize': FRAME_SIZE})
    rest.patch(config_element + '/frameRate', {'type': 'percentLineRate', 'rate': LINE_RATE_PERCENT})
    rest.patch(config_element + '/transmissionControl', {'type': 'fixedFrameCount', 'frameCount': FRAMES})

    # 3. Capture on port 2 (the receiver) ----------------------------------------------
    rx_port = vports[-1]
    rest.patch(rx_port, {'rxMode': 'captureAndMeasure'})        # capture without losing stats
    _, capture = get_child(lab, rx_port, 'capture')
    rest.patch(capture, {'hardwareEnabled': True,                # data plane (traffic)
                         'softwareEnabled': True})               # control plane (ARP, BGP ...)

    # 4. Bring up BGP and apply traffic BEFORE starting the capture -----------------------
    start_protocols(lab)
    verify_protocol_sessions(lab)               # BGP Peer + IPv4 sessions Up
    apply_traffic(lab)

    # 5. Capture window: everything below ends up in the .cap files --------------------------
    rest.operation(ixn, 'startCapture')
    for ipv4 in ipv4_stacks:
        rest.operation(ipv4, 'sendArp', [ipv4])                 # control plane: ARP
    run_traffic(lab, apply=False)               # data plane: 2 x FRAMES, then stops by itself
    time.sleep(KEEPALIVE_SEC * 2)               # control plane: a couple of BGP KEEPALIVEs
    rest.operation(ixn, 'stopCapture')

    # 6. Save captures on the API server, then download them ----------------------------
    # <port>_HW.cap = data plane, <port>_SW.cap = control plane (pcapng -> Wireshark).
    server_dir = rest.get(ixn + '/globals')['persistencePath']    # writable folder on the server
    sep = '\\' if rest.platform == 'windows' else '/'
    saved = rest.operation(ixn, 'saveCaptureFiles', server_dir + sep + 'start101_captures') or []
    for remote in saved:
        if rest.platform != 'windows':
            remote = remote.replace('\\', '/')
        local = os.path.join(RESULTS_DIR, os.path.basename(remote.replace('\\', '/')))
        rest.download_file(ixn, remote, local)
        LOG.info('Capture downloaded -> %s (%s packets)', local, count_capture_packets(local))

    # 7. Save the configuration on the server and download it --------------------------
    cfg_name = 'lesson06_saved.ixncfg'
    rest.operation(ixn, 'saveConfig', cfg_name)
    rest.download_file(ixn, cfg_name, os.path.join(RESULTS_DIR, cfg_name))
    LOG.info('Config downloaded -> %s', os.path.join(RESULTS_DIR, cfg_name))

    # 8. Statistics -------------------------------------------------------------------------
    passed = check_traffic_loss(lab)
    view_to_csv(lab, 'Port Statistics', 'lesson06_ports.csv')
    view_to_csv(lab, 'Traffic Item Statistics', 'lesson06_traffic_items.csv')
    export_views(lab, 'bgp', 'lesson06')        # e.g. 'BGP Peer Per Port'
    print('\nRESULT: {}'.format('PASS' if passed else 'FAIL'))
