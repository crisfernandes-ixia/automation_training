# Sample run

A complete run of lessons 01–06 on the lab on 2026-11-13, kept as a reference for what a
good run looks like. Your own runs write to `Start_101_LowLevel/results/`, which is not
committed. Passwords and API keys are masked (`"***"`) in every file.

**Setup:** IxNetwork 26.0.2620.9 (Windows GUI API server, `https://localhost:11009`),
chassis `10.80.81.2`, ports 2/13 and 2/14, 10G fiber, back to back.

| Lesson | REST calls | Result |
|---|---|---|
| 01 Session | see `01_console.txt` | Server found, logged in, session 1, build 26.0.2620.9 |
| 02 Load saved config | 62 | 107,474,830 frames sent and received, 0 loss |
| 03 L2/L3 from scratch | 94 | 200,000 / 200,000, 0 loss |
| 04 MACsec static SAK | 163 | 20,000 / 20,000 at 64, 512 and 1500 bytes, 0 loss; both MACsec sessions up |
| 05 MACsec MKA | 163 | MKA and Static MACsec sessions all up, MKPDUs 25/26 each way, 20,000 / 20,000, 0 loss |
| 06 Capture, save, report | 157 | eBGP up with 10 routes advertised each way, 2,000 / 2,000, 0 loss; 1,014 data and 24 control packets captured |

None of the 639 REST calls in the logs returned a 4xx or 5xx error.

| File | What it is |
|---|---|
| `01_console.txt` | Lesson 01 prints every HTTP exchange to the console (it writes no log file) |
| `lowlevel101-<lesson>-…_rest.log` | **The full REST transcript**: every request and response with its JSON body. This is the reference for porting to C#. |
| `lesson0*_*.csv` | Statistic views exported by the lessons |
| `Port_2_HW.cap` / `Port_2_SW.cap` | Lesson 06 data-plane / control-plane capture (open in Wireshark) |
| `lesson06_saved.ixncfg` | The config saved by lesson 06 (open in the IxNetwork GUI) |

Drill-down views (`... Drill Down`) are skipped with a warning: they only fill in when
opened in the GUI.
