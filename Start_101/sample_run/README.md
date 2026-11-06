# Sample run

A complete run of lessons 01–06 on 2026-11-06, kept as a reference for what a good run looks like.
Your own runs write to `Start_101/results/`, which is not committed.

**Setup:** IxNetwork 26.0 (Windows GUI API server), chassis `10.80.81.2`, ports 2/13 and 2/14,
10G fiber through the DUT (see `lab_config.py`).

| File | What it is |
|---|---|
| `summary.txt` | Exit code, result and duration per lesson |
| `<lesson>_console.txt` | Everything the lesson printed to the terminal |
| `results/*.log` | The RestPy log for each lesson |
| `results/*.csv` | Statistic views exported by the lessons |
| `results/Port_2_HW.cap` / `Port_2_SW.cap` | Lesson 06 data / control plane capture (open in Wireshark) |
| `results/lesson06_saved.ixncfg` | Config saved by lesson 06 (open in the IxNetwork GUI) |

Expected warnings, not failures:
* `Bypassing link state check`: ports connect first, link up is checked after L1 is set.
* `Traffic still running after 60s - stopping it` (lesson 02): `my_test.ixncfg` uses continuous traffic.
* `Skipping view "... Drill Down"`: drill-down views only fill in when opened in the GUI.
