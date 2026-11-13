# Start_101_LowLevel: IxNetwork automation with raw REST calls

The six lessons of [Start_101](../Start_101), rewritten with **no IxNetwork library**:
every step is a plain HTTP `GET` / `POST` / `PATCH` / `DELETE`. It is written for
teams that drive IxNetwork from their own code, such as **C# `HttpClient`**, Java or
Go. The Python here is only a readable way to show the HTTP calls, so port the calls,
not the Python.

| File | What it is |
|---|---|
| `01_session_rest.py` | Find the API server, log in, get a session, read the config, clean up. Uses only the `requests` package, no helpers. |
| `02_load_saved_config_rest.py` | Upload and load an `.ixncfg`, re-map ports, start protocols, run traffic, check loss, export CSV |
| `03_build_l2l3_rest.py` | Build Topology → DeviceGroup → Ethernet → IPv4 with multivalues, plus a traffic item, from an empty config |
| `04_macsec_static_sak_rest.py` | MACsec with static SAKs: `staticMacsec` and its Tx/Rx SAK pools, encrypted traffic, a frame-size sweep, MACsec stats |
| `05_macsec_mka_rest.py` | MACsec with MKA: `mka` and `cakCache` (CAK/CKN, key server priority), verifying MKA, encrypted traffic |
| `06_capture_save_and_report_rest.py` | eBGP with advertised routes, data and control-plane capture, downloading the `.cap` files, saving and downloading the config, CSV reports |
| `ixn_rest.py` | The whole REST "library": about 150 lines covering transport, async operations, multivalues, files and statistics |
| `common_rest.py` | Session, port, protocol, traffic and statistics steps. Each function lists the exact HTTP calls it makes. |
| `lab_config.py` | API server, chassis, ports (2/13 and 2/14, 10G fiber), credentials |
| `configs/my_test.ixncfg` | The same saved config as Start_101, used by lesson 02 |

## Run

```bash
pip install -r requirements.txt
```

```bash
python 01_session_rest.py
```

```bash
python 02_load_saved_config_rest.py configs/my_test.ixncfg
```

```bash
python 03_build_l2l3_rest.py
```

```bash
python 04_macsec_static_sak_rest.py
```

```bash
python 05_macsec_mka_rest.py
```

```bash
python 06_capture_save_and_report_rest.py
```

The console shows one line per HTTP call. Every lesson also writes a **complete REST
transcript** to `results/<lesson>-<time>_rest.log`, with every request and response
body. **That transcript is the spec for porting a test to C#.** To see the bodies on
the console too, set `IXN_CONSOLE_LOG=bodies`.

## The REST model in 8 rules

Everything in the lessons is one of these. There is nothing else.

| # | What | HTTP |
|---|---|---|
| 1 | Find the server and log in | `POST /api/v1/auth/session {"username","password"}` returns `{"apiKey"}`. Then send the header `X-Api-Key: <apiKey>` on every request. |
| 2 | Work in a session | Windows GUI: `GET /api/v1/sessions`, always id 1. Linux: `POST /api/v1/sessions` then `POST .../operations/start`. |
| 3 | Read | `GET <href>`. A GET on a collection (`.../vport`) returns a JSON list. Add `?includes=a,b` to fetch only some attributes. |
| 4 | Create | `POST <parent>/<child> {attributes}` returns **201** `{"links":[{"href": "<new object>"}]}` |
| 5 | Change | `PATCH <href> {"attribute": value}` |
| 6 | Delete | `DELETE <href>` |
| 7 | Operation (verb) | `POST <href>/operations/<name> {"arg1": …, "arg2": …}` returns **202** `{"state":"IN_PROGRESS","url":…}`. Poll `GET <url>` until `state` is `SUCCESS`. |
| 8 | Files | `POST <ixn>/files?filename=x` with the raw bytes (`application/octet-stream`). `GET` the same URL to download. |

`<ixn>` means `/api/v1/sessions/<id>/ixnetwork`, the root of the configuration.

## Cheat sheet: every call used in lessons 01–03

| Task | Call |
|---|---|
| New empty config | `POST <ixn>/operations/newconfig` (no body) |
| IxNetwork version | `GET <ixn>/globals?includes=buildNumber,username` |
| Load a config | `POST <ixn>/files?filename=my_test.ixncfg` (bytes), then `POST <ixn>/operations/loadconfig {"arg1":"my_test.ixncfg"}` |
| Add the chassis | `POST <ixn>/availableHardware/chassis {"hostname":"10.80.81.2"}`, then poll `GET` until `"state":"ready"` |
| Create a vport | `POST <ixn>/vport {"name":"Port_1"}` |
| Map the vport to a test port | `PATCH <vport> {"location":"10.80.81.2;2;13"}` (chassis;card;port) |
| Take port ownership | `POST <ixn>/vport/operations/connectports {"arg1":[<vports>],"arg2":true}` |
| Set L1 | `GET <vport>` returns `"type":"novusTenGigLan"`; then `PATCH <vport>/l1Config/novusTenGigLan {"media":"fiber","selectedSpeeds":["speed10g"]}` |
| Wait for link | Poll `GET <vport>` until `"connectionState":"connectedLinkUp"` |
| Topology / device group | `POST <ixn>/topology {"name","ports":[<vport>]}`, then `POST <topology>/deviceGroup {"name","multiplier":10}` |
| Ethernet / IPv4 | `POST <deviceGroup>/ethernet {"name"}`, then `POST <ethernet>/ipv4 {"name"}` |
| Set a multivalue | `GET <ethernet>` returns `"mac":"<ixn>/multivalue/7"`; then `PATCH <ixn>/multivalue/7/counter {"start","step","direction"}` or `/singleValue {"value"}` |
| Start / stop protocols | `POST <ixn>/operations/startallprotocols {"arg1":"sync"}` (`stopallprotocols` to stop) |
| Traffic item | `POST <ixn>/traffic/trafficItem {"name","trafficType":"ipv4","biDirectional":true}` |
| Endpoints | `POST <trafficItem>/endpointSet {"sources":[<ipv4>],"destinations":[<ipv4>]}` |
| Rate / size / count | `PATCH <trafficItem>/configElement/1/frameSize {"type":"fixed","fixedSize":512}`, and the same for `/frameRate` and `/transmissionControl` |
| Flow tracking | `PATCH <trafficItem>/tracking/1 {"trackBy":["trackingenabled0","sourceDestEndpointPair0"]}` |
| Generate | `POST <ixn>/traffic/trafficItem/operations/generate {"arg1":[<trafficItem hrefs>]}` |
| Apply | `POST <ixn>/traffic/operations/apply {"arg1":"<ixn>/traffic"}`. Note that `arg1` is a **string** here. |
| Start / stop traffic | `POST <ixn>/traffic/operations/startstatelesstrafficblocking {"arg1":["<ixn>/traffic"]}`. Here `arg1` is a **list**. |
| Traffic state | `GET <ixn>/traffic` returns `"state"`: `started`, `stoppedWaitingForStats` or `stopped` |
| Statistics | `GET <ixn>/statistics/view` and find the item whose `caption` matches, e.g. `Traffic Item Statistics`. Then `GET <view>/data` returns `isReady`, `totalPages`, `columnCaptions` and `pageValues`. Use `PATCH <view>/data {"currentPage":2}` for more pages. |
| Clear statistics | `POST <ixn>/operations/clearstats` (no body) |
| Release ports (Windows) | `POST <ixn>/vport/operations/releaseport {"arg1":[<vports>]}` |
| Delete a session (Linux) | `POST /api/v1/sessions/<id>/operations/stop?deleteAfterStop=true` |

## Cheat sheet: the extra calls in lessons 04–06

| Task | Call |
|---|---|
| Static MACsec endpoint | `POST <ethernet>/staticMacsec {"name"}`, then `PATCH <staticMacsec> {"encryptedTrafficType":"statelessL23"}` |
| MACsec per-device fields | `GET <staticMacsec>` returns multivalue hrefs for `dutMac`, `sourceIp` and `endStation`. Set each with `/singleValue {"value"}`. |
| SAK keys | `PATCH <staticMacsec> {"txSakPoolSize":1,"rxSakPoolSize":1}`. Then `GET <staticMacsec>/txSakPool` returns `txSak128` / `txSak256`, which are multivalues. `rxSakPool` works the same way. |
| MKA | `POST <ethernet>/mka {"name"}`, then `PATCH <mka> {"cakCount":1}`. `GET <mka>` returns the `keyServerPriority` and `keyDerivationFunction` multivalues (`aescmac128` / `aescmac256`). |
| CAK / CKN | `GET <mka>/cakCache` returns the `cakValue128` / `cakValue256` and `cakName` multivalues |
| MKA rekey (optional) | `PATCH <mka> {"rekeyMode":"timerBased","rekeyBehaviour":"rekeyContinuous","periodicRekeyInterval":30}` |
| Encrypted traffic | `trafficType: "ethernetVlan"`. The endpoints are the **staticMacsec** hrefs. Do **not** set `trackBy`: MACsec rejects it at apply. |
| Custom payload | `PATCH <configElement>/framePayload {"type":"custom","customPattern":"CAFEC0FFEE","customRepeat":true}` |
| BGP peer | `POST <ipv4>/bgpIpv4Peer {"name"}`. Its `type`, `localAs2Bytes`, `dutIp`, `keepaliveTimer` and `holdTimer` are multivalues. |
| Advertised routes | `POST <deviceGroup>/networkGroup {"name","multiplier":10}`, then `POST <networkGroup>/ipv4PrefixPools {"numberOfAddresses":1}`. `networkAddress` and `prefixLength` are multivalues. |
| Enable capture | `PATCH <vport> {"rxMode":"captureAndMeasure"}`, then `PATCH <vport>/capture {"hardwareEnabled":true,"softwareEnabled":true}` |
| Capture window | `POST <ixn>/operations/startcapture`, then `stopcapture`. Apply traffic **before** you start the capture. |
| Send ARP | `POST <ipv4>/operations/sendarp {"arg1":[<ipv4>]}`. This posts to the object itself, not to the collection. |
| Save captures | `GET <ixn>/globals` returns `persistencePath`. Then `POST <ixn>/operations/savecapturefiles {"arg1":"<persistencePath>\\start101_captures"}` returns a list of the files saved. |
| Save the config | `POST <ixn>/operations/saveconfig {"arg1":"lesson06_saved.ixncfg"}` |
| Download a file | `GET <ixn>/files?filename=<name or full server path>` returns the raw bytes |

## Pitfalls (each one is handled in the code)

1. **Self-signed certificate.** Turn off certificate validation for the API server. In
   Python, also pass `verify=False` on each request: `requests` ignores
   `Session.verify` when `REQUESTS_CA_BUNDLE` is set, which is common on corporate PCs.
2. **Windows and Linux differ only in sessions.** The Windows GUI is one session (id 1)
   that you cannot name or delete, so release its ports instead. A Linux API server
   needs create, start, name and delete.
3. **Operation names are lower case in the URL**: `startAllProtocols` becomes
   `.../operations/startallprotocols`.
4. **The type of `arg1` matters.** It is a list of hrefs for `generate`, `connectports`,
   `releaseport` and `startstatelesstrafficblocking`, but a single href string for
   `traffic/operations/apply`.
5. **202 means "not done yet".** Always poll the returned `url`. If you skip that, the
   next call runs against a half-finished operation.
6. **409 means "busy".** The server is still processing another request: wait a few
   seconds and retry the same call.
7. **Multivalues.** `PATCH <mv>/<pattern>` works only if the multivalue already uses that
   pattern. To switch, for example from `counter` to `singleValue`, `POST <mv>/singleValue`.
   `ixn_rest.set_multivalue()` does this check for you.
8. **Set L1 before you wait for link up.** A fiber port never links with the default
   copper settings.
9. **Collection items** carry their own href in `links[0].href`. If `href` is missing,
   build it as `<collection>/<id>`.
   **Single children** (`tracking`, `txSakPool`, `cakCache`, `capture`) answer with **one
   object** on 26.0, not a list. That object lives at `<parent>/<child>` itself. The
   `list()` and `get_child()` helpers accept both shapes.
10. **Errors.** A 4xx response has `{"errors":[{"detail":…}]}`. The server's own
    explanation is at `GET <ixn>/globals/appErrors/error`. `ixn_rest` prints both.
11. **Drill-down views** (`... Drill Down`) only fill in when opened in the GUI. Through
    the API they stay `isReady: false`, so `export_views()` skips them after 30 seconds.
12. **Captures:** count packets from the downloaded `.cap` file
    (`count_capture_packets()`). `<vport>/capture` `dataPacketCounter` can stay 0
    through the API.

## The same thing in C#

This is an **untested sketch**: it was not compiled, so treat it as a guide. It shows
the four calls everything else is built from, with .NET 6+ and `System.Text.Json`.

```csharp
using System.Text;
using System.Text.Json.Nodes;

var handler = new HttpClientHandler {
    // IxNetwork uses a self-signed certificate
    ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator
};
var http = new HttpClient(handler) { BaseAddress = new Uri("https://localhost:11009") };

// Rule 1: log in, then send the API key on every request
var login = await Send(HttpMethod.Post, "/api/v1/auth/session",
    new JsonObject { ["username"] = "admin", ["password"] = "admin", ["ignorePolicy"] = true });
http.DefaultRequestHeaders.Add("X-Api-Key", login!["apiKey"]!.GetValue<string>());

const string ixn = "/api/v1/sessions/1/ixnetwork";        // Windows GUI session

// Rule 4: create -> 201 + links[0].href
var created = await Send(HttpMethod.Post, ixn + "/vport", new JsonObject { ["name"] = "Port_1" });
string vport = created!["links"]![0]!["href"]!.GetValue<string>();

// Rule 5: change an attribute
await Send(HttpMethod.Patch, vport, new JsonObject { ["location"] = "10.80.81.2;2;13" });

// Rule 7: run an operation (Send() polls the 202 until it finishes)
await Send(HttpMethod.Post, ixn + "/vport/operations/connectports",
    new JsonObject { ["arg1"] = new JsonArray(vport), ["arg2"] = true });

async Task<JsonNode?> Send(HttpMethod method, string path, JsonNode? body = null)
{
    var request = new HttpRequestMessage(method, path);
    if (body != null)
        request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
    var response = await http.SendAsync(request);
    var text = await response.Content.ReadAsStringAsync();
    if (!response.IsSuccessStatusCode)
        throw new Exception($"{method} {path} -> {(int)response.StatusCode}: {text}");
    var json = string.IsNullOrEmpty(text) ? null : JsonNode.Parse(text);

    if ((int)response.StatusCode == 202)                   // asynchronous operation
    {
        while (json?["state"]?.GetValue<string>() == "IN_PROGRESS")
        {
            await Task.Delay(1000);
            var poll = await http.GetAsync(json["url"]!.GetValue<string>());
            json = JsonNode.Parse(await poll.Content.ReadAsStringAsync());
        }
        if (json?["state"]?.GetValue<string>() != "SUCCESS")
            throw new Exception($"{path} failed: {json?["message"]}");
        return json["result"];
    }
    return json;
}
```

This sketch leaves out the 409 retry, the `?includes=` filter and the statistics paging.
Copy those from `ixn_rest.py` once the basic calls work.

## Status

* **Lessons 01–03: verified on the lab** (IxNetwork 26.0.2620.9, Windows GUI). Note:
  the 26.6.2681.9 Windows GUI returned an empty HTTP 500 on every REST request, so use
  26.0 until that is fixed.
* **Lessons 04–06: verified offline only.** They were run end to end against a strict mock of the
  IxNetwork REST API, in both Windows-GUI and Linux-API-server modes. The mock checks
  URLs, payload shapes, `arg1` types, multivalue patterns, the async-operation protocol,
  statistics paging, session cleanup and `X-Api-Key`.
  The calls mirror what RestPy sends to the 26.0 server that the Start_101 lessons
  04–06 passed on. Run them on the lab before you share them.
