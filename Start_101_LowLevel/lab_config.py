"""
lab_config.py - ONE place to describe your lab (same values as ../Start_101).

Every value can be overridden with an environment variable, e.g.:
    Windows:      set IXN_API_SERVER=10.80.81.2
    Linux/macOS:  export IXN_API_SERVER=10.80.81.2
"""
import os

# ---------------------------------------------------------------------------
# IxNetwork API server
#   - Windows IxNetwork GUI on your PC : 'localhost'  -> https, port 11009
#   - Linux API server / Web Edition   : its IP       -> https, port 443
# Leave REST_PORT as None to auto-detect (tries 443, then 11009).
# ---------------------------------------------------------------------------
API_SERVER = os.environ.get('IXN_API_SERVER', 'localhost')
REST_PORT = int(os.environ['IXN_REST_PORT']) if os.environ.get('IXN_REST_PORT') else None
USERNAME = os.environ.get('IXN_USERNAME', 'admin')
PASSWORD = os.environ.get('IXN_PASSWORD', 'admin')      # never commit real passwords

# ---------------------------------------------------------------------------
# Chassis and test ports (card, port) - lab: 2/13 <-> 2/14, 10G fiber, back to back
# ---------------------------------------------------------------------------
CHASSIS_IP = os.environ.get('IXN_CHASSIS', '10.80.81.2')
PORTS = [(2, 13), (2, 14)]

# Layer-1 settings applied after the ports are connected (None = keep default)
PORT_MEDIA = 'fiber'        # 'copper' | 'fiber'
PORT_SPEED = 'speed10g'     # e.g. 'speed1000', 'speed10g'

# ---------------------------------------------------------------------------
# Session housekeeping
# ---------------------------------------------------------------------------
SESSION_PREFIX = os.environ.get('IXN_SESSION_PREFIX', 'lowlevel101')
KEEP_SESSION = os.environ.get('IXN_KEEP_SESSION', '0') == '1'

# Console verbosity of the REST log. The full transcript (every request and
# response body) is ALWAYS written to results/<lesson>-<time>_rest.log.
#   'calls' : one line per HTTP call (default)
#   'bodies': also print the JSON request/response bodies on the console
CONSOLE_LOG = os.environ.get('IXN_CONSOLE_LOG', 'calls')
