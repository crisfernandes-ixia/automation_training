"""
ixn_rest.py - a minimal IxNetwork REST client built on the 'requests' package only.

This is the "transport layer" that every IxNetwork library (RestPy, or the C#
HttpClient code your team writes) implements. It has NO IxNetwork knowledge
beyond these 8 rules:

  1. Find the API server and log in      POST /api/v1/auth/session        -> {"apiKey": ...}
                                          then send header  X-Api-Key: <apiKey>
  2. Work inside a session                /api/v1/sessions/<id>/ixnetwork/...
  3. Read an object or a list             GET    <href>
  4. Create a child object                POST   <parent href>/<child>  {attributes}
                                          -> 201 {"links": [{"href": "<new object href>"}]}
  5. Change attributes                    PATCH  <href>  {"attribute": value}
  6. Delete an object                     DELETE <href>
  7. Run an operation (verb)              POST   <href>/operations/<name>  {"arg1": ..., "arg2": ...}
                                          -> 202 {"state": "IN_PROGRESS", "url": "<status href>"}
                                          poll GET <status href> until state is SUCCESS (or ERROR)
  8. Move files                           POST/GET /api/v1/sessions/<id>/ixnetwork/files?filename=<name>

Plus two conventions:
  * "Multivalues": per-device attributes (MAC, IP, VLAN ...) are not plain values.
    The attribute holds an href like /api/v1/sessions/1/ixnetwork/multivalue/42;
    you set it with PATCH <mv>/singleValue {"value": ...} or <mv>/counter {...}.
  * Statistics are read from /statistics/view/<id>/data (columnCaptions + pageValues).

Every call is logged: one line per call on the console, and the FULL request and
response bodies in results/<lesson>_rest.log - a ready-made spec for porting to C#.
"""
import json
import logging
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOG = logging.getLogger('ixn_rest')


class IxnRestError(Exception):
    """An HTTP error or a failed operation, with the server's explanation."""


class IxnRest(object):
    # The 'Server' response header tells us what kind of API server we talk to.
    PLATFORMS = {'SelfHost': 'windows', 'Kestrel': 'windows',
                 'Microsoft-HTTPAPI': 'connection_manager',
                 'Jetty': 'linux', 'nginx': 'linux'}

    def __init__(self, host, port=None, operation_timeout=600):
        self.host = host
        self.port = port
        self.base_url = None             # e.g. https://localhost:11009
        self.platform = None             # windows | linux | connection_manager
        self.operation_timeout = operation_timeout
        self.http = requests.Session()
        # IxNetwork uses a self-signed certificate. verify=False is also passed on EVERY
        # request: requests ignores Session.verify when REQUESTS_CA_BUNDLE is set.
        self.http.verify = False
        self.http.headers.update({'Content-Type': 'application/json',
                                  'User-Agent': 'start101-lowlevel'})

    # ------------------------------------------------------------------ connect
    def detect(self):
        """Rule 1a: find the REST port. POST empty credentials to /api/v1/auth/session;
        any 200/401/403 answer means an IxNetwork API server is listening there."""
        ports = [self.port] if self.port else [443, 11009]
        for port in ports:
            for scheme in ('https', 'http'):
                url = '{}://{}:{}/api/v1/auth/session'.format(scheme, self.host, port)
                try:
                    r = self.http.post(url, data=json.dumps({'username': '', 'password': ''}),
                                       timeout=5, allow_redirects=False, verify=False)
                except requests.RequestException:
                    LOG.info('no API server at %s', url)
                    continue
                if r.status_code in (200, 401, 403):
                    server = r.headers.get('Server', 'Jetty')
                    self.platform = next((p for k, p in self.PLATFORMS.items() if k in server), 'linux')
                    self.base_url = '{}://{}:{}'.format(scheme, self.host, port)
                    LOG.info('API server found at %s (Server: %s -> platform %s)',
                             self.base_url, server, self.platform)
                    return self.platform
        raise IxnRestError('No IxNetwork API server found on {} (ports {})'.format(self.host, ports))

    def login(self, username, password):
        """Rule 1b: authenticate once, then send the API key with every request."""
        r = self.post('/api/v1/auth/session',
                      {'username': username, 'password': password, 'ignorePolicy': True})
        self.http.headers['X-Api-Key'] = r['apiKey']
        return r['apiKey']

    # ---------------------------------------------------------------- transport
    def request(self, method, path, payload=None, params=None, data=None, headers=None,
                quiet=False):
        """Send one HTTP request and return the decoded JSON (or None).
        - 202 Accepted  -> an asynchronous operation: poll it until it finishes (rule 7)
        - 409 Conflict  -> the server is busy with another request: wait and retry
        - 4xx/5xx       -> raise IxnRestError with the server's error details"""
        url = path if path.startswith('http') else self.base_url + path
        body = data if data is not None else (None if payload is None else json.dumps(payload))
        for _ in range(20):
            start = time.time()
            r = self.http.request(method, url, data=body, params=params, headers=headers,
                                  verify=False)
            self._log(method, url, params, payload, data, r, time.time() - start, quiet)
            if r.status_code != 409:
                break
            time.sleep(5)

        if r.status_code == 202:
            return self.wait_for_operation(r.json(), '{} {}'.format(method, path))
        if r.status_code >= 400:
            raise IxnRestError(self._explain(method, url, r))
        if r.status_code == 204 or not r.content:
            return None
        if 'json' in r.headers.get('Content-Type', ''):
            return r.json()
        return r.content

    def get(self, path, **params):
        return self.request('GET', path, params=params or None)

    def list(self, collection):
        """GET a collection (e.g. <ixn>/vport) and make sure every item has an 'href'.
        Items carry their href in 'href' or in links[0].href; else it is <collection>/<id>.
        Some single-instance children (e.g. trafficItem/<n>/tracking on some builds) answer
        with ONE object instead of a list: wrap it so callers always get a list."""
        items = self.get(collection) or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if 'href' not in item:
                if item.get('links'):
                    item['href'] = item['links'][0]['href']
                elif 'id' in item:
                    item['href'] = '{}/{}'.format(collection, item['id'])
                else:
                    item['href'] = collection
        return items

    def post(self, path, payload=None, **params):
        return self.request('POST', path, payload, params=params or None)

    def patch(self, path, payload):
        return self.request('PATCH', path, payload)

    def delete(self, path):
        return self.request('DELETE', path)

    # ------------------------------------------------------------- conventions
    def create(self, parent_href, child, attributes=None):
        """Rule 4: POST <parent>/<child> and return the new object's href."""
        r = self.post('{}/{}'.format(parent_href, child), attributes or {})
        if r and r.get('links'):
            return r['links'][0]['href']
        return '{}/{}/{}'.format(parent_href, child, r['id'])

    def operation(self, href, name, *args):
        """Rule 7: POST <href>/operations/<name> {"arg1": args[0], "arg2": args[1], ...}.
        Operation names are lower case in the URL (startAllProtocols -> startallprotocols)."""
        payload = {'arg{}'.format(i + 1): a for i, a in enumerate(args)} or None
        return self.post('{}/operations/{}'.format(href, name.lower()), payload)

    def wait_for_operation(self, status, what=''):
        """Poll an asynchronous operation: GET <status url> every second while IN_PROGRESS."""
        start = time.time()
        while status.get('state') == 'IN_PROGRESS' and status.get('url'):
            if time.time() - start > self.operation_timeout:
                raise IxnRestError('{}: still IN_PROGRESS after {}s'.format(what, self.operation_timeout))
            time.sleep(1)
            status = self.request('GET', status['url'], quiet=True)
        state = status.get('state')
        if state in (None, 'SUCCESS'):
            result = status.get('result')
            return None if result == 'kVoid' else result
        raise IxnRestError('{} -> {}: {} {}'.format(what, state, status.get('message') or '',
                                                     status.get('result') or ''))

    def set_multivalue(self, mv_href, pattern, values):
        """Multivalue convention: PATCH <mv>/<pattern> if the multivalue already uses that
        pattern (e.g. 'singleValue', 'counter', 'valueList'), otherwise POST it to switch."""
        current = self.get(mv_href).get('pattern')
        url = '{}/{}'.format(mv_href, pattern)
        if current == pattern:
            self.patch(url, values)
        else:
            self.post(url, values)

    def upload_file(self, ixnetwork_href, local_path, remote_name):
        """Rule 8: the file content is the raw request body (application/octet-stream)."""
        with open(local_path, 'rb') as fh:
            content = fh.read()
        return self.request('POST', '{}/files'.format(ixnetwork_href), params={'filename': remote_name},
                            data=content, headers={'Content-Type': 'application/octet-stream'})

    def download_file(self, ixnetwork_href, remote_name, local_path):
        content = self.request('GET', '{}/files'.format(ixnetwork_href), params={'filename': remote_name})
        with open(local_path, 'wb') as fh:
            fh.write(content if isinstance(content, bytes) else json.dumps(content).encode())
        return local_path

    # ------------------------------------------------------------- statistics
    def find_view(self, ixnetwork_href, caption, timeout=180):
        """GET /statistics/view returns every view; pick the one whose caption matches.
        Views appear only when they have something to show, so retry until timeout."""
        start = time.time()
        while True:
            for view in self.list('{}/statistics/view'.format(ixnetwork_href)):
                if view.get('caption') == caption:
                    return view['href']
            if time.time() - start > timeout:
                raise IxnRestError('View "{}" not found after {}s'.format(caption, timeout))
            time.sleep(2)

    def view_captions(self, ixnetwork_href):
        return [v.get('caption') for v in self.get('{}/statistics/view'.format(ixnetwork_href))]

    def read_view(self, ixnetwork_href, caption, timeout=180):
        """Return (column_names, rows) of a statistic view, all pages.
        GET  <view>/data                      -> isReady, totalPages, columnCaptions, pageValues
        PATCH <view>/data {"currentPage": n}  -> move to page n"""
        view = self.find_view(ixnetwork_href, caption, timeout)
        data_url = view + '/data'
        start = time.time()
        while True:
            data = self.get(data_url)
            if data.get('isReady') and isinstance(data.get('totalPages'), int):
                break
            if time.time() - start > timeout:
                raise IxnRestError('View "{}" not ready after {}s'.format(caption, timeout))
            time.sleep(2)
        rows = []
        for page in range(1, data['totalPages'] + 1):
            if page != data.get('currentPage'):
                self.patch(data_url, {'currentPage': page})
                data = self.get(data_url)
            for row in data.get('pageValues') or []:
                # each row is [[cell, cell, ...]] (drill-down views can nest more rows)
                rows.append(row[0] if row and isinstance(row[0], list) else row)
        return data['columnCaptions'], rows

    # ---------------------------------------------------------------- errors
    def _explain(self, method, url, r):
        """Build a readable error: the response 'errors' plus the server's app errors."""
        lines = ['{} {} -> HTTP {}'.format(method, url, r.status_code)]
        try:
            lines += [e.get('detail', str(e)) for e in r.json().get('errors', [])] or [r.text]
        except ValueError:
            lines.append(r.text)
        if '/sessions/' in url:
            session = url[:url.find('/', url.find('/sessions/') + len('/sessions/'))]
            try:
                for err in self.request('GET', session + '/ixnetwork/globals/appErrors/error',
                                        quiet=True) or []:
                    if err.get('errorLevel') in ('kError', 'kWarning'):
                        lines.append('  server {}: {} {}'.format(err['errorLevel'][1:].upper(),
                                                                 err.get('name'), err.get('description')))
            except Exception:
                pass
        return '\n'.join(lines)

    # --------------------------------------------------------------- logging
    def _log(self, method, url, params, payload, data, r, seconds, quiet):
        path = url[len(self.base_url):] if self.base_url and url.startswith(self.base_url) else url
        if params:
            path += '?' + '&'.join('{}={}'.format(k, v) for k, v in params.items())
        if data is not None:
            req_body = '<{} bytes file content>'.format(len(data))
        elif payload is not None:
            req_body = json.dumps(payload)
        else:
            req_body = ''
        level = logging.DEBUG if quiet else logging.INFO
        LOG.log(level, '%-6s %s %s -> %s (%.2fs)', method, path, _short(req_body), r.status_code, seconds)
        if 'json' in r.headers.get('Content-Type', ''):
            resp_body = r.text
        else:
            resp_body = '<{} bytes {}>'.format(len(r.content), r.headers.get('Content-Type', ''))
        LOG.debug('    request : %s', req_body or '-')
        LOG.debug('    response: %s', resp_body[:4000] + (' ...' if len(resp_body) > 4000 else ''))


def _short(text, limit=110):
    return text if len(text) <= limit else text[:limit] + ' ...'


def setup_logging(log_file, console_bodies=False):
    """Console: one line per call. File: every request/response body (DEBUG)."""
    LOG.setLevel(logging.DEBUG)
    LOG.handlers[:] = []
    fmt = logging.Formatter('%(asctime)s %(message)s', '%H:%M:%S')
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if console_bodies else logging.INFO)
    console.setFormatter(fmt)
    LOG.addHandler(console)
    if log_file:
        fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        LOG.addHandler(fh)
