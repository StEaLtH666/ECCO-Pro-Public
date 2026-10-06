# Historical data quality: method and failure modes

This note describes **how** the history behind ECCO Intelligence is audited and which defects the history builder is designed
for. It deliberately contains **no real consumption, occupancy or per-day series**: the numbers from the audit of the reference
installation stay private. Everything here is reproducible on your own data:

```
python intelligence/tools/export_ha_statistics.py --ids ids.txt --out /tmp/hist     # read-only, run where the recorder lives
python intelligence/tools/quality_report.py --hourly /tmp/hist_hourly.csv.gz --profile intelligence/profiles/<site>.local.json
```

`quality_report.py` writes its numbers to a local JSON file (git-ignored); nothing from a real installation is committed.
Nothing is written to Home Assistant and InfluxDB is not queried.

## 1. Depth and sampling (what to expect from an HA installation)

| Series | Typical depth | Sampling |
|---|---|---|
| Hourly long-term statistics | as long as the integration has existed (kept indefinitely) | hourly mean / min / max for power and SOC, hourly last state for counters |
| 5-minute statistics and raw states | about 10 days at default recorder settings | raw power every few seconds; SOC and counters **on change** |
| Dongle energy counters | | published about every 10 minutes, 0.1 kWh resolution |

Consequence: the model runs at **hourly resolution**. Long hourly history is the training set; 5-minute and raw data only
support recurring-signature discovery and SOC validation. If the dongle's own history is short and a legacy integration covers
the same instants, the history builder merges them (dongle first, legacy fill-in).

## 2. Completeness and gaps

The audit counts expected vs present hours, lists missing runs, and reports how many hours were filled by spreading a counter
delta across a gap (up to 6 h, flagged `gap_interpolated`). A merged two-source history should be complete; a source that has
dropouts (reboots, OTA updates, HA restarts produce `unavailable` / `unknown` states) is covered by the other.

## 3. Units, scale and consistency

* Counters may be in different units across integrations (kWh vs MWh): the profile carries a `scale` per entity and a unit test
  pins the legacy MWh case. Powers are W; SOC is a percentage with integer resolution (1 % is about 0.3 kWh on a ~30 kWh
  battery); counters have 0.1 kWh resolution.
* Two paths that measure the same registers should agree to counter resolution over their overlap; the audit reports the mean
  and mean absolute hourly difference and the lag at which the 5-minute power series correlate best (no lag = no time offset).

## 4. Dropouts, stale values and resets (what the builder handles)

* **Flat-lined instantaneous power**: some integrations hold the last power value (min = max, > 0) for hours while the cumulative
  counters keep counting. These hours are flagged and never used for the power integral.
* **Counter stalls**: a counter frozen while power says the house is drawing more than a threshold, then a catch-up jump. The
  jump is re-spread across the run (`stall_redistributed`).
* **Negative deltas and resets** in the *total* counters are treated as faults (flagged, not summed).
* **Day counters are not safe for local-date totals**: they reset at the inverter's clock midnight, which can drift from local
  midnight. Use differences of `total_*` counters, never `day_*`.
* **SOC**: a 0 % reading is flagged only when the battery is simultaneously delivering power (a deep discharge can legitimately
  reach 0); impossible hourly SOC jumps are flagged.
* **A trap, found and documented**: an hourly-*mean* SOC is a poor point value near a charge start, because the mean already
  includes the charge that begins part-way through the hour. SOC outcomes must be scored from point values (HA history / Influx),
  not hourly means; the scorecard does this where it can and says where it cannot.

## 5. Cumulative energy vs instantaneous power

Counters (differenced per hour) are preferred: the power integral drifts by a few percent and is wrong on flat-lined hours,
and the two agree closely on a healthy path. Rule used: interval energy = counter delta; the power integral is a fallback
(flagged `power_integral`) and is never used when power is flat-lined. Counter resolution (0.1 kWh) makes 5- or 10-minute energy
meaningless, so **hourly is the finest honest resolution**.

## 6. Energy-balance sanity and PV alignment

The daily balance PV + import + discharge - load - export - charge should leave a small, stable residual (conversion and standby
losses). A *growing* residual is an anomaly signal. PV and load that share a poll and a clock need no alignment correction.
Effective battery capacity can be regressed from counters vs SOC; it cannot overrule the configured capacity, so a few percent
of uncertainty is carried as a stated assumption.

## 7. Time zone and DST

All storage is UTC; the cheap window and every human-facing window are **local wall-clock**. DST days are 23 / 25 hours;
windows spanning the change keep their wall-clock endpoints (the overnight window lasts one hour longer or shorter on those days;
unit-tested). A fall-back day's repeated local hour is averaged into one slot; a spring-forward day has 23 slots.

## 8. PV forecast sources

Day-ahead values from forecast providers are compared with actual array output (energy from the PV counter). Providers can be
biased by season on a given array, so the engine learns a trailing 7-day median actual/forecast ratio per source (see
`PROTOTYPE_RESULTS.md`, section 2) and, since the safety cleanup, also rejects a forecast that is physically impossible or far
outside anything observed (`ECCO_INTELLIGENCE_V1_ARCHITECTURE.md`, section 7a).

## 9. What the data cannot support

Appliance identification (aggregate CT data only); weather or temperature effects (not consumed); sub-hourly energy; behaviour
across DST in data you do not have yet. If a legacy integration is ever removed, V1 degrades to the dongle's own history:
**do not decommission legacy entities or their statistics before the long Influx history is validated** (decision O-5).
