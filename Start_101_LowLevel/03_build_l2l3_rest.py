"""
03_build_l2l3_rest.py
=====================
Lesson 3 (low level) - Build Ethernet + IPv4 + traffic from an empty config.

Same test as ../Start_101/03_build_l2l3_from_scratch.py. Every object is created
with POST and configured with PATCH; per-device fields use multivalues.

    POST <ixn>/topology                              {"name": ..., "ports": [<vport>]}
    POST <topology>/deviceGroup                      {"name": ..., "multiplier": 10}
    POST <deviceGroup>/ethernet                      {"name": ...}
    POST <ethernet>/ipv4                             {"name": ...}
    GET  <ethernet>  -> {"mac": "/api/v1/sessions/1/ixnetwork/multivalue/7", ...}
    PATCH <multivalue>/counter      {"start": "00:11:01:00:00:01", "step": "00:00:00:00:00:01", "direction": "increment"}
    PATCH <multivalue>/singleValue  {"value": 24}

    POST <ixn>/traffic/trafficItem                   {"name", "trafficType": "ipv4", "biDirectional": true}
    POST <trafficItem>/endpointSet                   {"sources": [<ipv4>], "destinations": [<ipv4>]}
    PATCH <configElement>/frameSize | frameRate | transmissionControl
    PATCH <trafficItem>/tracking/1                   {"trackBy": [...]}

Run
  python 03_build_l2l3_rest.py
"""
import lab_config as cfg
from common_rest import (LOG, check_traffic_loss, connect_ports, ixnetwork_session, run_traffic,
                         start_protocols, verify_protocol_sessions, view_to_csv)

DEVICES_PER_PORT = 10      # try 1 or 100 - nothing else needs to change

with ixnetwork_session('lesson03') as lab:
    rest, ixn = lab.rest, lab.ixn

    # 1. Ports ----------------------------------------------------------------------
    vports = connect_ports(lab, cfg.PORTS[:2])

    # 2. Topology -> DeviceGroup -> Ethernet -> IPv4 on each port ----------------------
    ipv4_stacks = []
    for idx, vport in enumerate(vports, start=1):
        topology = rest.create(ixn, 'topology', {'name': 'Topo_{}'.format(idx), 'ports': [vport]})
        device_group = rest.create(topology, 'deviceGroup',
                                   {'name': 'DG_{}'.format(idx), 'multiplier': DEVICES_PER_PORT})
        ethernet = rest.create(device_group, 'ethernet', {'name': 'Eth_{}'.format(idx)})

        # 'mac' is a multivalue href, not a value: configure it with a counter pattern
        mac_mv = rest.get(ethernet)['mac']
        rest.set_multivalue(mac_mv, 'counter', {'start': '00:1{}:01:00:00:01'.format(idx),
                                                'step': '00:00:00:00:00:01',
                                                'direction': 'increment'})

        ipv4 = rest.create(ethernet, 'ipv4', {'name': 'IPv4_{}'.format(idx)})
        attrs = rest.get(ipv4)    # address / gatewayIp / prefix / resolveGateway are multivalues
        # Both ports on one subnet (back to back or through an L2 switch):
        #   port 1 = 10.1.0.1..10, port 2 = 10.1.0.101..110, each the other's gateway.
        me, peer = ('10.1.0.1', '10.1.0.101') if idx == 1 else ('10.1.0.101', '10.1.0.1')
        rest.set_multivalue(attrs['address'], 'counter',
                            {'start': me, 'step': '0.0.0.1', 'direction': 'increment'})
        rest.set_multivalue(attrs['gatewayIp'], 'counter',
                            {'start': peer, 'step': '0.0.0.1', 'direction': 'increment'})
        rest.set_multivalue(attrs['prefix'], 'singleValue', {'value': 24})
        rest.set_multivalue(attrs['resolveGateway'], 'singleValue', {'value': True})
        ipv4_stacks.append(ipv4)

    # 3. Start protocols (ARP) and verify -------------------------------------------------
    start_protocols(lab)
    verify_protocol_sessions(lab)

    # 4. Traffic item -----------------------------------------------------------------------
    traffic_item = rest.create(ixn + '/traffic', 'trafficItem',
                               {'name': 'IPv4_P1_to_P2', 'trafficType': 'ipv4', 'biDirectional': True})
    rest.create(traffic_item, 'endpointSet',
                {'sources': [ipv4_stacks[0]], 'destinations': [ipv4_stacks[1]]})

    config_element = rest.list(traffic_item + '/configElement')[0]['href']
    rest.patch(config_element + '/frameSize', {'type': 'fixed', 'fixedSize': 512})
    rest.patch(config_element + '/frameRate', {'type': 'percentLineRate', 'rate': 50})
    rest.patch(config_element + '/transmissionControl', {'type': 'fixedFrameCount', 'frameCount': 100000})
    tracking = rest.list(traffic_item + '/tracking')[0]['href']
    rest.patch(tracking, {'trackBy': ['trackingenabled0', 'sourceDestEndpointPair0']})

    # 5. Run and results ----------------------------------------------------------------------
    run_traffic(lab)
    passed = check_traffic_loss(lab)
    view_to_csv(lab, 'Traffic Item Statistics', 'lesson03_traffic_items.csv')
    view_to_csv(lab, 'Flow Statistics', 'lesson03_flows.csv')
    LOG.info('Lesson 03 finished')
    print('\nRESULT: {}'.format('PASS' if passed else 'FAIL'))
