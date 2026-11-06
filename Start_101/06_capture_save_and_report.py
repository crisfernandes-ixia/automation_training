"""
06_capture_save_and_report.py
=============================
Lesson 6 - Keep the evidence: packet captures, the config, and the stats.

The script builds its own small test so the capture stays small and has
something interesting in both planes:

    Port 1                                   Port 2 (captured)
    Topology -> DG -> Ethernet -> IPv4 -> BGP  <-- eBGP -->  BGP <- IPv4 <- Ethernet <- DG <- Topology
                 └── NetworkGroup (routes advertised over BGP) ┘
    Traffic: routes behind port 1 <-> routes behind port 2, FINITE frame count

    Control plane (software capture): ARP, BGP OPEN / UPDATE / KEEPALIVE
    Data plane    (hardware capture): the traffic frames received on port 2

What you learn
  * Enable data-plane (hardware) and control-plane (software) capture on a port
  * The right ORDER: apply traffic -> start capture -> generate events -> stop capture
  * Keep captures small: finite traffic (fixedFrameCount), never continuous
  * Save the captures on the API server and download them to your PC (.cap -> Wireshark)
  * Save the running configuration (.ixncfg) and download it
  * Export statistic views to CSV

Run
  python 06_capture_save_and_report.py
"""
import os
import time

from ixnetwork_restpy import Files

import lab_config as cfg
from common import (RESULTS_DIR, apply_traffic, check_traffic_loss, connect_ports,
                    count_capture_packets, export_views, ixnetwork_session, run_traffic, start_protocols_and_wait, stat_view_to_csv,
                    verify_protocol_sessions)

# ----------------------------- test parameters --------------------------------
PORT_IPS = ['10.1.0.1', '10.1.0.2']           # same subnet, through the L2 DUT
BGP_AS = [65001, 65002]                        # different AS -> eBGP
ROUTE_START = ['201.1.0.0', '202.1.0.0']       # routes advertised by each side
ROUTES_PER_PORT = 10
KEEPALIVE_SEC = 5                              # short timers -> KEEPALIVEs show up in the capture

FRAMES = 1000                                  # per direction: a capture you can open in Wireshark
FRAME_SIZE = 256
LINE_RATE_PERCENT = 1
# --------------------------------------------------------------------------------

with ixnetwork_session('lesson06') as session:
    ixnetwork = session.Ixnetwork
    vports = connect_ports(session, cfg.PORTS[:2])

    # 1. Build the config: IPv4 + eBGP + advertised routes on each port -------------
    ipv4_stacks, route_pools = [], []
    for idx, vport in enumerate(vports):
        topology = ixnetwork.Topology.add(Name='BGP_Topo_{}'.format(idx + 1), Ports=vport)
        dg = topology.DeviceGroup.add(Name='BGP_DG_{}'.format(idx + 1), Multiplier=1)
        eth = dg.Ethernet.add(Name='Eth_{}'.format(idx + 1))
        eth.Mac.Single('00:1{}:01:00:00:01'.format(idx + 1))

        ipv4 = eth.Ipv4.add(Name='IPv4_{}'.format(idx + 1))
        ipv4.Address.Single(PORT_IPS[idx])
        ipv4.GatewayIp.Single(PORT_IPS[1 - idx])
        ipv4.Prefix.Single(24)

        bgp = ipv4.BgpIpv4Peer.add(Name='BGP_{}'.format(idx + 1))
        bgp.Type.Single('external')
        bgp.LocalAs2Bytes.Single(BGP_AS[idx])
        bgp.DutIp.Single(PORT_IPS[1 - idx])        # the BGP neighbor
        bgp.KeepaliveTimer.Single(KEEPALIVE_SEC)
        bgp.HoldTimer.Single(KEEPALIVE_SEC * 3)

        # Routes behind this port, advertised to the neighbor in a BGP UPDATE.
        ng = dg.NetworkGroup.add(Name='Routes_{}'.format(idx + 1), Multiplier=ROUTES_PER_PORT)
        pool = ng.Ipv4PrefixPools.add(NumberOfAddresses=1)
        pool.NetworkAddress.Increment(start_value=ROUTE_START[idx], step_value='0.0.1.0')
        pool.PrefixLength.Single(24)

        ipv4_stacks.append(ipv4)
        route_pools.append(pool)

    # 2. Traffic between the advertised routes - FINITE --------------------------------
    ti = ixnetwork.Traffic.TrafficItem.add(Name='BGP_Routes', TrafficType='ipv4',
                                           BiDirectional=True)
    ti.EndpointSet.add(Sources=route_pools[0], Destinations=route_pools[1])
    ti.Tracking.find()[0].TrackBy = ['trackingenabled0']
    ce = ti.ConfigElement.find()[0]
    ce.FrameSize.update(Type='fixed', FixedSize=FRAME_SIZE)
    ce.FrameRate.update(Type='percentLineRate', Rate=LINE_RATE_PERCENT)
    ce.TransmissionControl.update(Type='fixedFrameCount', FrameCount=FRAMES)

    # 3. Configure capture on port 2 (the receiver) ----------------------------------
    rx_port = vports[-1]
    rx_port.RxMode = 'captureAndMeasure'         # capture without losing statistics
    rx_port.Capture.HardwareEnabled = True       # data plane (traffic)
    rx_port.Capture.SoftwareEnabled = True       # control plane (ARP, BGP, MKA ...)

    # 4. Bring up BGP and apply traffic BEFORE starting the capture ---------------------
    start_protocols_and_wait(ixnetwork)
    verify_protocol_sessions(session)            # BGP sessions Up
    apply_traffic(ixnetwork)

    # 5. Capture window: everything below ends up in the .cap files ----------------------
    ixnetwork.StartCapture()
    for ipv4 in ipv4_stacks:
        ipv4.SendArp()                           # control plane: ARP request/reply
    run_traffic(ixnetwork, apply=False)          # data plane: 2 x FRAMES, then stops by itself
    time.sleep(KEEPALIVE_SEC * 2)                # control plane: a couple of BGP KEEPALIVEs
    ixnetwork.StopCapture()

    # 6. Save captures on the server, then download them --------------------------
    # <port>_HW.cap = data plane, <port>_SW.cap = control plane (pcapng -> Wireshark).
    # Count packets from the files: vport.Capture.*PacketCounter can stay 0 via the API.
    server_dir = ixnetwork.Globals.PersistencePath   # a writable folder on the API server
    sep = '\\' if session.TestPlatform.Platform == 'windows' else '/'
    capture_dir = server_dir + sep + 'start101_captures'
    for remote in ixnetwork.SaveCaptureFiles(Arg1=capture_dir) or []:
        local = os.path.join(RESULTS_DIR, os.path.basename(remote.replace('\\', '/')))
        session.Session.DownloadFile(remote, local)
        ixnetwork.info('Capture downloaded -> {} ({} packets)'.format(
            local, count_capture_packets(local)))

    # 7. Save and download the configuration ---------------------------------------
    cfg_name = 'lesson06_saved.ixncfg'
    ixnetwork.SaveConfig(Files(cfg_name))
    session.Session.DownloadFile(cfg_name, os.path.join(RESULTS_DIR, cfg_name))
    ixnetwork.info('Config downloaded -> {}'.format(os.path.join(RESULTS_DIR, cfg_name)))

    # 8. Statistics -------------------------------------------------------------------
    passed = check_traffic_loss(session)
    stat_view_to_csv(session, 'Port Statistics', 'lesson06_ports.csv')
    stat_view_to_csv(session, 'Traffic Item Statistics', 'lesson06_traffic_items.csv')
    export_views(session, 'bgp', 'lesson06')     # e.g. 'BGP Peer Per Port'
    print('\nRESULT: {}'.format('PASS' if passed else 'FAIL'))
