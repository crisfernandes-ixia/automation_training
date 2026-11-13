"""
02_load_saved_config_rest.py
============================
Lesson 2 (low level) - Load a GUI-built config, run it, check the results.

Same test as ../Start_101/02_load_saved_config.py, written as REST calls:

  1. Upload the file        POST <ixn>/files?filename=my_test.ixncfg   (raw bytes)
  2. Load it                POST <ixn>/operations/loadconfig {"arg1": "my_test.ixncfg"}   (async)
  3. Re-map the ports       see common_rest.connect_ports()
  4. Protocols              POST <ixn>/operations/startallprotocols {"arg1": "sync"}
                            read view 'Protocols Summary'
  5. Traffic                generate / apply / start / poll state      (common_rest.run_traffic)
  6. Results                read views 'Traffic Item Statistics', 'Port Statistics' -> CSV

Run
  python 02_load_saved_config_rest.py configs/my_test.ixncfg
"""
import os
import sys

import lab_config as cfg
from common_rest import (CONFIGS_DIR, LOG, check_traffic_loss, connect_ports, ixnetwork_session,
                         run_traffic, start_protocols, verify_protocol_sessions, view_to_csv)

config_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(CONFIGS_DIR, 'my_test.ixncfg')
if not os.path.isfile(config_file):
    sys.exit('Config file not found: {}\nUsage: python {} <file.ixncfg>'.format(config_file, sys.argv[0]))

with ixnetwork_session('lesson02') as lab:
    rest, ixn = lab.rest, lab.ixn

    # 1 + 2. Upload the file to the API server, then load it --------------------
    remote_name = os.path.basename(config_file)
    LOG.info('Uploading and loading %s', config_file)
    rest.upload_file(ixn, config_file, remote_name)
    rest.operation(ixn, 'loadConfig', remote_name)

    # 3. Re-map the vports of the config to OUR test ports -------------------------
    vports = rest.list(ixn + '/vport')
    names = [v['name'] for v in vports]
    LOG.info('Config has %s vports: %s', len(names), names)
    connect_ports(lab, cfg.PORTS[:len(names)], names=names)

    # 4. Protocols -------------------------------------------------------------------
    if rest.get(ixn + '/topology'):
        start_protocols(lab)
        verify_protocol_sessions(lab)

    # 5 + 6. Traffic and results -----------------------------------------------------
    # my_test.ixncfg sends continuous traffic: run_traffic() stops it after 60 s.
    if rest.get(ixn + '/traffic/trafficItem'):
        run_traffic(lab, timeout=60)
        passed = check_traffic_loss(lab)
        view_to_csv(lab, 'Traffic Item Statistics', 'lesson02_traffic_items.csv')
        view_to_csv(lab, 'Port Statistics', 'lesson02_ports.csv')
        print('\nRESULT: {}'.format('PASS' if passed else 'FAIL'))
