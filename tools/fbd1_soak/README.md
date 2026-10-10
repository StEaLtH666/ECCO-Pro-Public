# FB-D1 seven-day soak evidence analyser

An offline, read-only tool that decides whether the FB-D1 soak of the ECCO clock dongle met its acceptance criteria. It reads
exported Home Assistant history and `esphome logs` captures. It never connects to Home Assistant, the dongle or the inverter.

```
python tools/fbd1_soak_analyse.py history.json [more.json export.csv dongle.log[@YYYY-MM-DD] ...] --out report-dir
```

The default soak window is the FB-D1 soak: 2026-10-04 23:14:37 BST (22:14:37 UTC) plus 7 x 24 h, ending 2026-10-11 23:14:37
BST. You can change it with `--start` / `--days` / `--end`. A naive time is read as Europe/London.

Other options:

- `--as-of`: the analysis instant. Before the end of the window, the soak is reported as incomplete.
- `--threshold`: the Clock Correction Threshold, used when the export has no setting row.
- `--entity KEY=entity_id`: maps a renamed entity to its catalogue key.
- `--rules rules.json`: overrides decision thresholds.
- `--verdict-exit-code`: exits with 0 / 10 / 20 / 30 for PASS / WARNING / INSUFFICIENT_EVIDENCE / FAIL.

## Outputs

| File | Content |
|---|---|
| `fbd1_soak_analysis.json` | Machine-readable result, schema `ecco-fbd1-soak-analysis/1`: window, overall verdict, criteria (verdict, basis, confidence, reasons, metrics, evidence references), the daily table, per-area detail, A3 what-if, suspicious and informational events, outstanding live-proof requirements, input hashes and diagnostics, the rules used and the limitations. |
| `fbd1_soak_report.md` | Human-readable report with the same content. |
| `fbd1_soak_daily.csv` | One row per soak day (24 h blocks from the start). |
| `fbd1_soak_events.csv` | Every FAIL / WARNING event with its UTC and local time and its source references. |

Every timestamp is given in UTC and in Europe/London time (`2026-10-05 00:03:12 BST`). Every finding names its source rows
(`<file>#<entity_id>[<row>]` or `<file>:<line>`).

## Supported evidence

| Format | Shape |
|---|---|
| HA REST history | `GET /api/history/period/<start>?end_time=<end>&filter_entity_id=<ids>&minimal_response&no_attributes`: a list per entity. With `minimal_response`, later rows carry only `state` and `last_changed`. |
| HA websocket history | `history/history_during_period`, compressed `{entity_id: [{"s", "lu", "lc"?}]}`, optionally wrapped in `{"result": ...}`. |
| State snapshots | A flat list of `{entity_id, state, last_changed}` objects, as returned by `/api/states`. |
| Long CSV | `entity_id,state,last_changed`: the Home Assistant History panel download. |
| Wide CSV | A `timestamp` column, then one column per entity id. |
| Firmware log | `esphome logs` output. Supported: ANSI colours, ESPHome 2026 millisecond clocks and hexadecimal source lines, ISO-prefixed lines, and a `# ... start=<ISO>` capture header. A clock-only log takes its date from that header, from `LOG@YYYY-MM-DD`, or from its first `Inverter RTC: <date time> \| Difference from NTP` line. |

Entity ids are recognised by their ESPHome object id: any `<domain>.<optional area prefix>_ecco_clock_dongle_<suffix>`. The
catalogue (`catalogue.py`) lists every diagnostic used. The test suite proves that each one exists in the firmware under that
name. Unknown entities are counted and ignored. A malformed row is rejected and reported with its reference, never coerced.

## What to export on 11 October

Export the window from 2026-10-04 22:00 UTC to after 2026-10-11 22:14:37 UTC, preferably the whole window in one export. All
of the following are dongle entities.

- **Continuity witnesses:** `ECCO Supervision Challenge` (boot nonce), `ECCO Supervision Valid Heartbeat Count`, `NTP Time`,
  `Inverter Time`, `Last Telemetry Update`, `Last Configuration Update`.
- **RTC:** `Clock Difference`, `Last Correction Result`, `Last Correction`, `Verified Corrections Since Boot`,
  `Failed Corrections Since Boot`, `RTC Write Attempts Since Boot`, `RTC Stall Count`, `RTC Stall Detected`,
  `RTC Correction In Progress`, `ECCO RTC Correction Lock Max Age Since Boot`, `Clock Correction Threshold`,
  `Automatic Clock Sync`, `ECCO Timezone1..6 Time`, `ECCO PV Power`.
- **B10 and polling:** `ECCO Fallback Profile Live Match`, `Telemetry/Configuration Read Failures Since Boot`,
  `Telemetry Online`, `Configuration Online`.
- **Supervision and safety:** `ECCO Supervision State`, `ECCO Supervision Suspect Events`, `ECCO Supervision Lost Events`,
  `ECCO Fallback Profile State`, the manual / Free Power / Dump to Grid counters and active / in-progress states,
  `Manual Write In Progress`, `ECCO Modbus Write Lock Max Age Since Boot`, and the write-enable switches.

Add any `esphome logs` captures from the soak. They are the only direct evidence for `RTC policy:`, `RTC STALL detected` and
Block C errors.

Keep the export files outside the repository. They name the installation.

## Decision rules

The overall verdict is the worst verdict among the required criteria, ranked FAIL > INSUFFICIENT_EVIDENCE > WARNING > PASS.
An optional criterion can only add a WARNING or a FAIL. Its INSUFFICIENT_EVIDENCE does not block.

All thresholds are fields of `model.Rules` and are printed in every report.

| Id | Criterion | FAIL | INSUFFICIENT | WARNING | PASS |
|---|---|---|---|---|---|
| C-CONT-1 | No unexpected restart | A confirmed restart signal after start + 10 min. | No witness spans the window (unavailable periods are then listed as possible restarts). | - | One boot nonce, or the heartbeat count never resets, across the window. |
| C-CONT-2 | Evidence coverage | - | Coverage < 90 %, a gap > 2 h, or a day < 50 %. | Coverage < 98 %, a gap > 15 min, a device-unavailable period, or no periodic witness. | Otherwise. |
| C-CONT-3 | Evidence reaches the scheduled end | - | Evidence starts after the start or ends before the end (more than 5 min). | - | Evidence spans the window. |
| C-CONT-4 (optional) | Timestamp / clock integrity | - | No NTP Time rows. | NTP-vs-HA offset jumps > 5 s, rejected rows or out-of-order rows. | Otherwise. |
| C-RTC-1 | No failed / aborted corrections | 3 or more failures, 2 consecutive, or 2 aborts. | Neither the counter nor result text / logs. A zero without a spanning counter. | Any failure or abort. | Counter +0, spanning the window. |
| C-RTC-2 | Corrections follow the policy | A policy violation. | Reasons unknown (counter-only or pre-FB-D1 logs). | A manual correction, a window edge or an unchecked item. | Every check passes. |
| C-RTC-3 | Rate and lock hold | More than 144 per 24 h, or lock > 100 s. | No lock-age evidence. | More than 48 per 24 h, or lock > 50 s. | Otherwise. |
| C-RTC-4 (optional) | No stale-read false confirmation (A3) | - | Confirming reads missing. | Candidates found. | None. |
| C-RTC-5 (optional) | Stall detection accounted for | - | No stall evidence. | Counter < log lines, or a stall followed by a background correction. | Otherwise. |
| C-B10-1 | B10 MATCH availability | MATCH < 80 % of observed time, or MATCH > 12 s under the RTC lock. | B10 coverage < 90 %. | MATCH < 95 %, any NOT MATCH, or a day < 80 %. | Otherwise. |
| C-B10-2 (optional) | Recovery after corrections | - | Release times unknown. | Release-to-MATCH > 120 s, or never. | Otherwise. |
| C-POLL-1 | Read failures / online state | More than 50 failures per day, or offline > 10 min. | A counter missing or not spanning the window. | Any failure or offline period. | Both counters +0, spanning the window. |
| C-POLL-2 | Block B continuity | A verifiable gap > 10 min. | No Last Configuration Update values. | A verifiable gap > 150 s. | Otherwise. |
| C-POLL-3 (optional) | Block A/B/C errors | - | No firmware log. | Any error. | None. |
| C-SAFE-1 | Write accounting | Modbus write lock > 180 s (leak). | RTC or other write counters missing. | Unexplained RTC writes (> 3 per correction), other write paths ran, write failures, protected-state or setting changes, or write lock > 60 s. | Otherwise. |
| C-SAFE-2 | Lease / ownership | A non-large correction during a lease, or an RTC write acknowledged during a manual write. | No lease state. | - | Otherwise. |
| C-SUP-1 | Supervision / durable state | A `RECOVERY BLOCKED` log line. | No supervision evidence, or incomplete event counters. | SUSPECT / LOST events, profile-state changes, or E-level log lines. | Otherwise. |

### Policy checks (C-RTC-2)

Each automatic correction is checked with `registry/rtc_policy.py`, the C++-exact mirror of
`firmware/include/ecco_rtc_policy.h`. The checks are:

- quiet window;
- the threshold for the reason (background max(P, 30), precision max(P/2, 5) up to 300, large 300);
- the precision window and once-per-boundary;
- zone-cross;
- lease hold;
- the 5 min gap;
- for a background correction, the two confirming reads.

A time within 2 s of a window edge is reported as `edge`, never as a violation.

### Stale-read classification (C-RTC-4, A3)

The classification is inferred, never stated as fact. It compares the prior confirming read with the trend of the preceding
non-stalled reads. The allowance is the measured drift for the PV level (night 0.5, low PV 4.5, high PV 7.5 s/min) plus
10 s of register-image staleness.

| Label | Meaning |
|---|---|
| `stale_first_read_candidate` | A jump away from the trend, with the stall detector firing on the first read (the -60/-60 and -36/-47 pattern). |
| `false_confirmation_candidate` | A jump away from the trend without a stall flag. |
| `inconclusive_stale_signature` | A stall flag or disagreeing pair, but consistent with the trend. |
| `consistent_with_drift` | Genuine drift. |
| `undetermined` | Not enough reads. |

A candidate whose trend error is below the background threshold is a suspected no-op.

The A3 section replays three veto variants over the observed corrections:

- V1: stall veto;
- V2: pair-consistency at 8, 10, 12 and 15 s;
- V3: V1 or V2(10).

For each variant it reports how many candidates and how many drift-consistent corrections the variant would have held. It
also gives the distribution of read-to-read differences for normal reads.

## Limitations

- Home Assistant stores changes only. Repeated equal Clock Difference reads are recovered from Inverter Time.
- Truncating a per-entity export can look like "no change". The analyser cannot tell the two apart and says so.
- Row times are Home Assistant receive times.
- Day/night falls back to a 07:00-19:00 clock window when there are no ECCO PV Power rows.
- Writes by a second Modbus master are invisible.
- Block C errors are attributable only from the log.

## Tests

`tools/tests/test_fbd1_soak_analyser.py` runs offline in about 10 s. It covers:

- firmware string cross-checks;
- time handling;
- every import format;
- more than 25 synthetic scenarios, each checked against ground truth the scenario computes itself;
- cross-format consistency;
- the CLI;
- a replay through the real FB-D1 firmware lambdas (`registry/tests/_fbd1_harness.py`).

`tools/tests/_fbd1_soak_synth.py` generates the synthetic evidence.
