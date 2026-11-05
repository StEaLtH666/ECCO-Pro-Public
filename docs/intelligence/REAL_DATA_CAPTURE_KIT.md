# Real-data capture kit (PENDING)

> **Status: PENDING.** The offline validator is IMPLEMENTED OFFLINE and tested on synthetic, fictional-2030 data only.
> The real-data run has **not** happened. It needs the owner's own, separate go/no-go, given **after the owner's release
> closeout is committed** and **only while no supervised live step is in progress**. Nothing in this kit is run by an
> agent against Home Assistant, the dongle, the inverter or InfluxDB.

This runbook says how a real statistics capture is checked offline, so the Intelligence data-quality rules
([`DATA_QUALITY_METHOD.md`](DATA_QUALITY_METHOD.md), sections 10 to 12) can be confirmed on real history before any advice is
trusted. It uses placeholders only:

| Placeholder | Meaning |
|---|---|
| `<OFFLINE_EVIDENCE_DIR>` | a folder in the owner's local-only evidence area (no git remote, never pushed) |
| `<PUBLIC_CLONE>` | the owner's local clone of this repository (the validator runs from it; it never writes into it) |
| `<PYTHON>` | a Python 3.12 interpreter on the owner's PC |
| `<CUTOVER_ISO>` | the I-D8 cut-over instant with its UTC offset, from the owner's own record |
| `<slug>` | the dongle's device name in the profile's entity ids |

## 1. Who does what

| Step | Who | Touches the live system? |
|---|---|---|
| Go/no-go after the owner's release closeout | owner | no |
| Run the read-only exporter where the recorder lives | owner | read-only, under the go/no-go |
| Copy the export into `<OFFLINE_EVIDENCE_DIR>` | owner | no |
| Run the validator on the PC | owner (or an agent the owner asks, on the PC only) | no |
| Read the **aggregate summary** | owner; an agent only when the owner hands it the summary | no |

Agents never read the raw CSV, never copy it anywhere, and never put the summary on GitHub or any shared or AI
coordination channel. The summary's first and last lines say so: `REAL DATA - LOCAL ONLY - DO NOT PUBLISH`.

## 2. Go/no-go checklist (owner)

- [ ] The owner's release closeout is committed and no supervised live step is in progress.
- [ ] The capture is authorised as its own job (it is not part of any install or proof session).
- [ ] The exporter used is the repository's unchanged read-only exporter (`intelligence/tools/export_ha_statistics.py`):
      it opens the recorder database read-only, exports only the statistic ids listed, and writes nothing to Home Assistant.
- [ ] The ids file lists only the statistic ids of the site-local profile (copy of `site_profile.example.json` with the
      `<slug>` placeholders filled in, kept in `<OFFLINE_EVIDENCE_DIR>`, never in the repository).
- [ ] `<OFFLINE_EVIDENCE_DIR>` is outside every repository (the validator refuses otherwise).

## 3. Export (owner, under the go/no-go)

Follow the exporter's own docstring: run it where the recorder database lives, at low priority, and copy the
`hist_hourly.csv.gz` it writes into `<OFFLINE_EVIDENCE_DIR>`. Delete the temporary copies on the host afterwards, as the
exporter's docstring says. The 5-minute file is not used by this kit.

Record the file's checksum before anything reads it:

```powershell
cls
$Evidence = '<OFFLINE_EVIDENCE_DIR>'
Get-FileHash -Algorithm SHA256 (Join-Path $Evidence 'hist_hourly.csv.gz') | Format-List
```

## 4. Validate (offline, on the PC)

```powershell
cls
$Evidence = '<OFFLINE_EVIDENCE_DIR>'
$Repo = '<PUBLIC_CLONE>'
$env:PYTHONDONTWRITEBYTECODE = '1'
& '<PYTHON>' -I -B (Join-Path $Repo 'intelligence\tools\validate_capture.py') `
    --hourly (Join-Path $Evidence 'hist_hourly.csv.gz') `
    --profile (Join-Path $Evidence 'site.local.json') `
    --out (Join-Path $Evidence 'capture-summary') `
    --cutover '<CUTOVER_ISO>'
"exit code: $LASTEXITCODE"
```

Exit codes: `0` summary written, `1` input error (nothing written), `2` refused (nothing written). It is refused when `--out`
is inside the repository it runs from, inside any folder tree whose git configuration lists a remote (a plain `.git`
folder or a worktree's shared configuration, `config` or `config.worktree`, in any spelling git accepts), inside one whose
configuration includes other files (`[include]` / `[includeIf]`) or cannot be read, or when any of that holds for the path
with its links and junctions resolved. Options: `--tz` (default
`Europe/London`), `--step-days` (replay spacing, default 7), `--replay-hour` (local hour of each replay, default 21).
Without `--cutover` the I-D8 load-counter check is reported as `NOT_RUN`.

Show the result:

```powershell
cls
$Evidence = '<OFFLINE_EVIDENCE_DIR>'
Get-Content (Join-Path $Evidence 'capture-summary\capture_summary.txt')
```

## 5. What the summary contains (aggregates only)

`capture_summary.json` (schema `ecco-intel-capture-summary/1`) and `capture_summary.txt` hold:

| Block | Content |
|---|---|
| `input` | the CSV's SHA-256, size, row and statistic-id counts (no ids, no file names) |
| `audit` | hours expected / present / missing, missing-run count and longest run, per-field coverage and flag counts, first and last date |
| `energy_balance` | hours that balance, balance only with import and export swapped, or balance neither way (`balanced`, `balanced_only_swapped`, `unbalanced`: together every hour with all six counters); the hours in which import and export can be told apart (`distinguishable`) and those of them that balance only swapped (`distinguishable_only_swapped`); `ct_reversed`: the share rule over the whole capture, which reads only the last two counts |
| `counter_faults` | counter stall hours and catch-up hours |
| `dropouts` | recovered dropout runs, the longest, days with repeated dropouts |
| `dst_nights` | each clock-change date in the capture, its kind, hours expected and present |
| `load_counter_check` | the I-D8 check before and after the cut-over: the load counter against the balance-derived load and against the load-power integral (count, median, 90th percentile of the relative difference, share beyond the PROPOSED tolerance), exporting hours and the share of them whose load reads zero |
| `replay` | `assess_inputs` over replayed snapshots (one instant every `--step-days` days, every decision OPEN): the number of instants carrying each finding code |
| `backtest` | `PENDING`: the advice backtest needs DP-1 (the owner's decision on the source of each decided input; OPEN), synthetic decisions are never used on real data, and a capture with the TOU and tariff readings at each issue time, which a statistics capture does not carry |
| `thresholds` | the PROPOSED detection thresholds the run used |

There is no per-hour series, no entity id and no timestamp finer than a date. A capture records no decision: the replay
runs with every I-D OPEN, so the live-only rules (liveness, supervision, readings) report their inputs as missing by
design. The live rules are exercised by the synthetic fault suites instead.

## 6. Reading the result

- `load_counter_check.before` against `.after` is the evidence the owner needs for I-D8: a counter that agrees with the
  balance-derived load before the cut-over as well as after supports `KEEP_AFTER_COUNTER_CHECK`; a high share of zero load
  while exporting before the cut-over supports `EXCLUDE`. The owner records the decision privately (a `REC-YYYYMMDD-<slug>`
  reference); the tool records nothing.
- `energy_balance.ct_reversed: true`, many `unbalanced` hours, repeated dropouts or a large longest gap are reasons to stop
  and look before any learning uses the history.
- Every threshold is PROPOSED (a technical detection constant), never an owner decision.

## 7. What stays PENDING

- The real-data run itself (the owner's separate go/no-go, after the owner's release closeout is committed).
- The advice backtest step. It stays PENDING: it needs DP-1 (the owner's decision on the source of each decided
  input; OPEN), synthetic decisions are never used on real data, and a capture that carries the TOU and tariff
  readings at each issue time.
- Any change the real summary shows is needed in the PROPOSED thresholds (a reviewed code change, never a site file).
