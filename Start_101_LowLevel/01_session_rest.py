"""
01_session_rest.py
==================
Lesson 1 (low level) - Talk to IxNetwork with nothing but HTTP.

No IxNetwork library at all: only the 'requests' package. Every step below is
one HTTP call you can reproduce with curl, Postman, or C# HttpClient.

  Step 1  Find the API server          POST /api/v1/auth/session  (empty credentials)
  Step 2  Log in                       POST /api/v1/auth/session  -> apiKey
  Step 3  Get a session                Windows: GET /api/v1/sessions
                                       Linux:   POST /api/v1/sessions + operations/start
  Step 4  Read the IxNetwork version   GET  .../ixnetwork/globals
  Step 5  Explore the config tree      GET  .../ixnetwork/vport, /topology, /traffic/trafficItem
  Step 6  Clean up                     Linux: POST /api/v1/sessions/<id>/operations/stop?deleteAfterStop=true

Run
  python 01_session_rest.py
"""
import datetime
import getpass
import json
import time

import requests
import urllib3

import lab_config as cfg

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

http = requests.Session()
http.verify = False                                   # self-signed certificate ...
# ... and verify=False on every call too: requests ignores Session.verify when the
# REQUESTS_CA_BUNDLE environment variable is set (common on corporate PCs).
http.headers['Content-Type'] = 'application/json'


def show(method, url, body, response):
    """Print one HTTP exchange the way you would see it in Postman."""
    print('\n>>> {} {}'.format(method, url))
    if body is not None:
        print('    body: {}'.format(json.dumps(body)))
    text = response.text if len(response.text) < 600 else response.text[:600] + ' ...'
    print('<<< {} {}'.format(response.status_code, text))


def call(method, url, body=None, **kwargs):
    data = None if body is None else json.dumps(body)
    response = http.request(method, url, data=data, verify=False, **kwargs)
    show(method, url, body, response)
    return response


def wait_for_operation(base_url, response):
    """Operations answer 202 + {"state": "IN_PROGRESS", "url": ...}: poll until done."""
    status = response.json()
    while status.get('state') == 'IN_PROGRESS':
        time.sleep(1)
        poll = status['url'] if status['url'].startswith('http') else base_url + status['url']
        r = http.get(poll, verify=False)
        r.raise_for_status()                 # a failed poll is an error, not "done"
        status = r.json()
    print('    operation finished: state={} result={}'.format(status.get('state'), status.get('result')))
    if status.get('state') not in (None, 'SUCCESS'):
        raise RuntimeError(status.get('message'))
    return status


# ---------------------------------------------------------------------------
# Step 1 - Find the API server.
# Windows GUI listens on https:11009, the Linux API server on https:443.
# The 'Server' response header tells which one we found.
# ---------------------------------------------------------------------------
base_url, platform = None, None
for port in ([cfg.REST_PORT] if cfg.REST_PORT else [443, 11009]):
    url = 'https://{}:{}/api/v1/auth/session'.format(cfg.API_SERVER, port)
    try:
        r = call('POST', url, {'username': '', 'password': ''}, timeout=5)
    except requests.RequestException as err:
        print('\n... nothing at {} ({})'.format(url, type(err).__name__))
        continue
    if r.status_code in (200, 401, 403):
        server = r.headers.get('Server', '')
        platform = 'windows' if ('SelfHost' in server or 'Kestrel' in server) else 'linux'
        base_url = 'https://{}:{}'.format(cfg.API_SERVER, port)
        print('    -> API server found: {}  (Server header "{}" = {})'.format(base_url, server, platform))
        break
if base_url is None:
    raise SystemExit('No IxNetwork API server found on {}'.format(cfg.API_SERVER))

# ---------------------------------------------------------------------------
# Step 2 - Log in. Every later request carries the header  X-Api-Key: <apiKey>
# ---------------------------------------------------------------------------
r = call('POST', base_url + '/api/v1/auth/session',
         {'username': cfg.USERNAME, 'password': cfg.PASSWORD, 'ignorePolicy': True})
r.raise_for_status()
http.headers['X-Api-Key'] = r.json()['apiKey']

# ---------------------------------------------------------------------------
# Step 3 - Get a session.
# ---------------------------------------------------------------------------
session_id, created_by_us = None, False
try:
    if platform == 'windows':
        # The Windows GUI is ONE session (id 1). Nothing to create, nothing to delete.
        r = call('GET', base_url + '/api/v1/sessions')
        session_id = r.json()[0]['id']
    else:
        # Linux API server: create a session, start it, give it a recognizable name.
        r = call('POST', base_url + '/api/v1/sessions', {'applicationType': 'ixnrest'})
        r.raise_for_status()
        session_id = r.json()['id'] if 'id' in r.json() else r.json()['links'][0]['href'].split('/')[-1]
        created_by_us = True
        r = call('POST', '{}/api/v1/sessions/{}/operations/start'.format(base_url, session_id),
                 {'applicationType': 'ixnrest'})
        if r.status_code == 202:
            wait_for_operation(base_url, r)
        name = 'lowlevel101-lesson01-{}-{:%Y%m%d-%H%M%S}'.format(getpass.getuser(), datetime.datetime.now())
        call('PATCH', '{}/ixnetworkweb/api/v1/sessions/{}'.format(base_url, session_id),
             {'sessionName': name})

    ixn = '{}/api/v1/sessions/{}/ixnetwork'.format(base_url, session_id)   # root of the config

    # -----------------------------------------------------------------------
    # Step 4 - Read attributes. ?includes= limits the response to what you need.
    # -----------------------------------------------------------------------
    r = call('GET', ixn + '/globals', params={'includes': 'buildNumber,username'})
    globals_ = r.json()

    # -----------------------------------------------------------------------
    # Step 5 - Explore. A GET on a collection returns a JSON list of objects.
    # -----------------------------------------------------------------------
    vports = call('GET', ixn + '/vport').json()
    topologies = call('GET', ixn + '/topology').json()
    traffic_items = call('GET', ixn + '/traffic/trafficItem').json()

    print('\n================ summary ================')
    print('API server      : {} ({})'.format(base_url, platform))
    print('Session id      : {}'.format(session_id))
    print('IxNetwork build : {}'.format(globals_.get('buildNumber')))
    print('User            : {}'.format(globals_.get('username')))
    print('Virtual ports   : {}'.format(len(vports)))
    print('Topologies      : {}'.format(len(topologies)))
    print('Traffic items   : {}'.format(len(traffic_items)))

finally:
    # -----------------------------------------------------------------------
    # Step 6 - Clean up: a Linux session holds a license until it is deleted.
    # -----------------------------------------------------------------------
    if created_by_us:
        r = call('POST', '{}/api/v1/sessions/{}/operations/stop'.format(base_url, session_id),
                 params={'deleteAfterStop': 'true'})
        if r.status_code == 202:
            wait_for_operation(base_url, r)
