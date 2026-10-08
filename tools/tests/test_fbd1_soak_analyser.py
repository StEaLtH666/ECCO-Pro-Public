#!/usr/bin/env python3
"""FB-D1 seven-day soak evidence analyser (tools/fbd1_soak, CLI tools/fbd1_soak_analyse.py) - offline proof.

  [1] firmware cross-checks: every catalogue entity name, every Last Correction Result string, every log line pattern and every
      B10 mode the analyser reads exists in the firmware exactly as the analyser expects it; the catalogue slugs are HA's
  [2] time: Europe/London BST/GMT conversion (soak start, spring gap, autumn fold, against zoneinfo when available), parsing
  [3] import formats: HA REST history (minimal / full), websocket compressed, flat state list, long and wide CSV, esphome logs
      (anchored, auto-anchored, ISO-prefixed, ANSI, midnight roll-over, DST fall-back); area-prefixed ids; overrides; malformed
      rows rejected with references; unknown entities and invalid values reported, never coerced
  [4] scenarios on synthetic evidence (tools/tests/_fbd1_soak_synth.py), each checked against ground truth computed by the
      scenario itself: perfect seven-day soak; incomplete evidence; missing day; unexpected restart; normal correction; -60/-60
      stale pair; -36/-47 candidate; false-confirmation candidate without stall; single frozen read; genuine drift; RTC abort;
      repeated failures; Block C read failure; B10 recovery; B10 NOT MATCH; MATCH under the RTC lock; clock / timestamp
      discontinuity; malformed data; unknown entity values; partial history coverage; policy violations and window edges;
      lease violation; empty evidence; a window across the BST -> GMT change
  [5] cross-format consistency, CLI end-to-end and the report outputs
  [6] the FB-D1 harness: the REAL firmware lambdas (registry/tests/_fbd1_harness.D1Sim) replay a two-freeze stale-read pattern;
      their own publications, fed to the analyser, give the -60/-60 stale-first-read candidate

Test-only, no network, no hardware. I/O: reads the firmware YAML / header, writes only to a temporary directory.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "tests"))

import _fbd1_soak_synth as S  # noqa: E402
import fbd1_soak_analyse as CLI  # noqa: E402
from fbd1_soak import b10 as B10  # noqa: E402
from fbd1_soak import catalogue, ingest, logparse, rtc, timeutil  # noqa: E402
from fbd1_soak.analyse import run  # noqa: E402
from fbd1_soak.evidence import Evidence, Sample, Series, counter_delta  # noqa: E402
from fbd1_soak.report import daily_csv, events_csv, markdown  # noqa: E402

UTC = timezone.utc
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def analyse(d: "S.Dongle", *, days: float | None = None, now=None, logs=(), fmt: str = "rest", start=None, rules=None):
    ev = Evidence()
    if fmt == "rest":
        ingest.load_object(d.ha_history(), ev)
    elif fmt == "rest-full":
        ingest.load_object(d.ha_history(minimal=False), ev)
    elif fmt == "ws":
        ingest.load_object(d.ws_history(), ev)
    elif fmt == "csv":
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "h.csv"
            p.write_text(d.long_csv(), encoding="utf-8")
            ingest.load(p, ev)
    for text, anchor in logs:
        ingest.load_log_text(text, ev, log_date=anchor)
    st = start or S.START
    days = days if days is not None else (d.end - d.start).total_seconds() / 86400
    return run(ev, start=st, days=days, now=now or (st + timedelta(days=days + 1)), rules=rules)


def crit(rep: dict, cid: str) -> dict:
    return next(c for c in rep["criteria"] if c["id"] == cid)


def verdicts(rep: dict) -> dict:
    return {c["id"]: c["verdict"] for c in rep["criteria"]}


def events(rep: dict, code: str) -> list:
    return [e for e in rep["suspicious_events"] + rep["informational_events"] if e["code"] == code]


def episodes(rep: dict) -> list:
    return rep["areas"]["rtc"]["episodes"]


FW = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
CAP_H = (ROOT / "firmware" / "include" / "ecco_fallback_capture.h").read_text(encoding="utf-8")

# =============================================================================================================================
print("[1] firmware cross-checks")
names = set(re.findall(r'^\s+name: "([^"]+)"', FW, re.M))
missing = [e.firmware_name for e in catalogue.ENTITIES if e.firmware_name not in names]
check("every catalogue entity is a firmware entity name (name: \"...\" in the stage 3.4 YAML)", not missing, str(missing))
bad = [e.key for e in catalogue.ENTITIES if catalogue.slugify(e.firmware_name) != e.suffix]
check("every catalogue object-id suffix is Home Assistant's slug of the firmware name", not bad, str(bad))
used = re.findall(r"sensor\.ecco_clock_dongle_([a-z0-9_]+)", "\n".join(
    p.read_text(encoding="utf-8") for p in sorted((ROOT / "home-assistant").rglob("*.yaml"))))
cat_suffixes = {e.suffix for e in catalogue.ENTITIES}
for sfx in ("clock_difference", "rtc_stall_detected", "ecco_fallback_profile_live_match", "telemetry_read_failures_since_boot",
            "configuration_online", "rtc_correction_in_progress", "ecco_supervision_challenge"):
    check(f"the HA packages use the same object id `{sfx}` as the catalogue", sfx in set(used) and sfx in cat_suffixes)
check("catalogue keys are unique and every id matcher is anchored (last_correction never matches last_correction_result)",
      len(catalogue.BY_KEY) == len(catalogue.ENTITIES)
      and catalogue.match("sensor.ecco_clock_dongle_last_correction_result") == "last_correction_result"
      and catalogue.match("sensor.ecco_clock_dongle_last_correction") == "last_correction"
      and catalogue.match("sensor.loft_ecco_clock_dongle_rtc_stall_count") == "rtc_stall_count"
      and catalogue.match("sensor.other_device_rtc_stall_count") is None
      and catalogue.match("binary_sensor.ecco_clock_dongle_clock_difference") is None)

# Last Correction Result: (firmware literal / printf format, a rendering, expected kind)
RESULTS = [
    ('"Automatic correction queued (%s) - error %d s"', "Automatic correction queued (background) - error -60 s", "START"),
    ('"Manual correction started"', "Manual correction started", "MANUAL"),
    ('"Write acknowledged - verifying attempt %d"', "Write acknowledged - verifying attempt 2", "ACK"),
    ('"Verified OK - error now %d s"', "Verified OK - error now -3 s", "VERIFIED"),
    ('"Verification failed (%d s) - retry %d queued"', "Verification failed (-45 s) - retry 1 queued", "VFAIL"),
    ('"FAILED after retries - error %d s - 5 min cooldown"', "FAILED after retries - error -45 s - 5 min cooldown", "FAILED"),
    ('"FAILED after communication errors - 5 min cooldown"', "FAILED after communication errors - 5 min cooldown", "FAILED"),
    ('"ABORTED - correction exceeded its deadline - 5 min cooldown"', "ABORTED - correction exceeded its deadline - 5 min cooldown",
     "ABORTED"),
    ('"Communication failure - retry %d queued"', "Communication failure - retry 1 queued", "RETRY"),
    ('"Modbus write error - processing retry"', "Modbus write error - processing retry", "WRITE_ERR"),
    ('"No response to write - processing retry"', "No response to write - processing retry", "WRITE_ERR"),
    ('"Write not sent - processing retry"', "Write not sent - processing retry", "WRITE_ERR"),
    ('"Non-standard write reply - processing retry"', "Non-standard write reply - processing retry", "WRITE_ERR"),
    ('"Verification read timed out - processing retry"', "Verification read timed out - processing retry", "VREAD_ERR"),
    ('"Verification read stalled - NTP invalid; processing retry"', "Verification read stalled - NTP invalid; processing retry",
     "VREAD_ERR"),
    ('"Deferred - inverter write path busy; will retry"', "Deferred - inverter write path busy; will retry", "DEFER"),
    ('"Correction cancelled"', "Correction cancelled", "CANCELLED"),
    ('"Correction cancelled - confirmed NTP time unavailable"', "Correction cancelled - confirmed NTP time unavailable", "CANCELLED"),
    ('"None since boot"', "None since boot", "BOOT"),
]
for lit, rendered, kind in RESULTS:
    got = rtc.parse_result(rendered)[0]
    check(f"Last Correction Result {lit} is in the firmware and parses as {kind}", lit in FW and got == kind, f"in_fw={lit in FW} got={got}")
check("an unknown result string is reported, not guessed", rtc.parse_result("Something new")[0] is None)

LOGS = [
    ('"Inverter RTC: %s | Difference from NTP: %d s"', "Inverter RTC: 2026-10-05 00:03:12 | Difference from NTP: -47 s", "rtc_read"),
    ('"RTC STALL detected - inverter advanced %d s while NTP advanced %d s"',
     "RTC STALL detected - inverter advanced 10 s while NTP advanced 60 s", "rtc_stall"),
    ('"RTC correction queued - clock difference: %d seconds"', "RTC correction queued - clock difference: -47 seconds", "rtc_queued"),
    ('"RTC policy: %s (threshold %d s, full error %d s)"', "RTC policy: background (threshold 30 s, full error -47 s)", "rtc_policy"),
    ('"RTC correction held (%s) - full error %d s, threshold %d s"',
     "RTC correction held (unconfirmed) - full error -31 s, threshold 30 s", "rtc_held"),
    ('"Starting RTC write attempt %d"', "Starting RTC write attempt 1", "rtc_write_start"),
    ('"RTC write acknowledged - verification scheduled in 10 seconds"',
     "RTC write acknowledged - verification scheduled in 10 seconds", "rtc_write_ack"),
    ('"Performing post-write RTC verification"', "Performing post-write RTC verification", "rtc_verify_start"),
    ('"RTC correction VERIFIED - error now %d seconds"', "RTC correction VERIFIED - error now -3 seconds", "rtc_verified"),
    ('"RTC verification failed at %d seconds - retry queued"', "RTC verification failed at -45 seconds - retry queued",
     "rtc_verify_failed"),
    ('"RTC correction failed after retries - entering 5 minute cooldown"',
     "RTC correction failed after retries - entering 5 minute cooldown", "rtc_failed_retries"),
    ('"RTC correction failed after communication errors"', "RTC correction failed after communication errors", "rtc_failed_comm"),
    ('"RTC correction held its lock %u s - deadline breaker released RTC state only (5 min cooldown)"',
     "RTC correction held its lock 91 s - deadline breaker released RTC state only (5 min cooldown)", "rtc_aborted"),
    ('"RTC write deferred - inverter write path owned by another transaction; will retry on the next scheduled correction check"',
     "RTC write deferred - inverter write path owned by another transaction; will retry on the next scheduled correction check",
     "rtc_write_deferred"),
    ('"No response while reading inverter RTC"', "No response while reading inverter RTC", "rtc_read_error"),
    ('"No response to configuration register 330"', "No response to configuration register 330", "block_c_error"),
    ('"Configuration register 330 Modbus exception: 0x%02X"', "Configuration register 330 Modbus exception: 0x02", "block_c_error"),
    ('"No response to configuration block 241-293"', "No response to configuration block 241-293", "config_block_error"),
    ('"Configuration block 200-240 Modbus exception: 0x%02X"', "Configuration block 200-240 Modbus exception: 0x0B",
     "config_block_error"),
    ('"No response to telemetry block 59-116"', "No response to telemetry block 59-116", "telemetry_error"),
    ('"Configuration poll yielded before Block B - inverter write path owned by another transaction; nothing stamped, catch-up owed"',
     "Configuration poll yielded before Block B - inverter write path owned by another transaction; nothing stamped, catch-up owed",
     "config_yield"),
    ('"Configuration register 330 read skipped - inverter write path owned by another transaction"',
     "Configuration register 330 read skipped - inverter write path owned by another transaction", "block_c_skipped"),
    ('"boot %08X shadow ready"', "boot 62CEE2AF shadow ready", "boot_shadow"),
]
for lit, rendered, kind in LOGS:
    got = logparse.classify(rendered)[0]
    check(f"log line {lit[:60]}... is in the firmware and classifies as {kind}", lit in FW and got == kind,
          f"in_fw={lit in FW} got={got}")
modes = set(re.findall(r'case LM_[A-Z_]+:\s*return "([A-Z_]+)";', CAP_H)) | {"UNKNOWN"}
check("every B10 mode the firmware can publish has an analyser category (and nothing else is MATCH)",
      modes == set(B10.CATEGORY) and [k for k, v in B10.CATEGORY.items() if v == "MATCH"] == ["MATCH"], str(modes ^ set(B10.CATEGORY)))
check("the B10 text field order is m= first, as the analyser parses it", 'put(t, "m=");' in CAP_H and
      B10.mode_of("m=PAUSED_IO;dx=-;cx=-") == "PAUSED_IO" and B10.mode_of("unavailable") == "UNKNOWN"
      and B10.category(B10.mode_of("garbage")) == "UNKNOWN" and B10.category(B10.mode_of(None)) == "NO_EVIDENCE")

# =============================================================================================================================
print("[2] time handling (Europe/London)")
st = timeutil.parse_ts("2026-10-04 23:14:37", naive_is_local=True)
check("the soak start 2026-10-04 23:14:37 BST is 22:14:37 UTC", st == datetime(2026, 10, 4, 22, 14, 37, tzinfo=UTC), str(st))
check("the scheduled completion is 2026-10-11 23:14:37 BST (7 x 24 h, no DST change inside)",
      timeutil.fmt_local(st + timedelta(days=7)) == "2026-10-11 23:14:37 BST")
check("BST ends 2026-10-25 01:00 UTC and starts 2026-03-29 01:00 UTC",
      timeutil.bst_bounds_utc(2026) == (datetime(2026, 3, 29, 1, tzinfo=UTC), datetime(2026, 10, 25, 1, tzinfo=UTC)))
amb = datetime(2026, 10, 25, 1, 30)
check("the autumn fall-back hour is ambiguous: fold 0 = BST, fold 1 = GMT",
      timeutil.is_ambiguous_local(amb) and timeutil.local_to_utc(amb) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
      and timeutil.local_to_utc(amb, fold=1) == datetime(2026, 10, 25, 1, 30, tzinfo=UTC))
try:
    timeutil.local_to_utc(datetime(2026, 3, 29, 1, 30))
    gap_ok = False
except timeutil.TimeParseError:
    gap_ok = True
check("a wall time in the spring-forward gap is refused, never guessed", gap_ok)
check("parse_local_near picks the fall-back occurrence nearest the row time",
      timeutil.parse_local_near("2026-10-25 01:30:00", datetime(2026, 10, 25, 1, 31, tzinfo=UTC)) ==
      datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
      and timeutil.parse_local_near("2026-10-25 01:30:00", datetime(2026, 10, 25, 0, 29, tzinfo=UTC)) ==
      datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
forms = ["2026-10-05T00:03:12Z", "2026-10-05T01:03:12+01:00", "2026-10-05T01:03:12+0100", "2026-10-05 00:03:12.000+00:00",
         "2026-10-05T00:03:12.123456789Z", 1791158592, 1791158592000, "1791158592"]
exp = datetime(2026, 10, 5, 0, 3, 12, tzinfo=UTC)
got = [timeutil.parse_ts(f).replace(microsecond=0) for f in forms]
check("ISO (Z, +01:00, +0100, fractions) and epoch s / ms timestamps all parse to the same instant", all(g == exp for g in got), str(got))
check("a naive ISO string is local by default and UTC on request",
      timeutil.parse_ts("2026-10-05 01:03:12") == exp and timeutil.parse_ts("2026-10-05 00:03:12", naive_is_local=False) == exp)
try:
    import zoneinfo
    zl = zoneinfo.ZoneInfo("Europe/London")
    t = datetime(2026, 1, 1, tzinfo=UTC)
    diffs = []
    while t < datetime(2027, 1, 1, tzinfo=UTC):
        if timeutil.to_local(t) != t.astimezone(zl).replace(tzinfo=None):
            diffs.append(t)
        t += timedelta(minutes=30)
    check("to_local == zoneinfo Europe/London at every half hour of 2026", not diffs, str(diffs[:3]))
except Exception as exc:  # noqa: BLE001 - no tz database on this host: the hand-coded rule is still pinned above
    print(f"  info  zoneinfo unavailable ({exc}); cross-check skipped")

# =============================================================================================================================
print("[3] import formats")
d = S.Dongle(hours=2).run()
ev_rest = Evidence()
ingest.load_object(d.ha_history(), ev_rest)
ev_full = Evidence()
ingest.load_object(d.ha_history(minimal=False), ev_full)
ev_ws = Evidence()
ingest.load_object(d.ws_history(), ev_ws)
n_rows = sum(len(d.history(e)) for e in d.rows)
check("REST history (minimal_response) imports every row", ev_rest.inputs[0].accepted == n_rows and not ev_rest.inputs[0].rejected,
      f"{ev_rest.inputs[0].accepted} vs {n_rows}")
check("REST (full rows) and websocket compressed history import the same rows",
      ev_full.inputs[0].accepted == n_rows and ev_ws.inputs[0].accepted == n_rows)
flat = [{"entity_id": d.eid("b10"), "state": S.B10_MATCH, "last_changed": "2026-10-05T00:00:00+00:00"}]
ev_flat = Evidence()
ingest.load_object(flat, ev_flat)
check("a flat list of state objects (/api/states shape) imports", ev_flat.has("b10"))
with tempfile.TemporaryDirectory() as td:
    pl = Path(td) / "long.csv"
    pl.write_text(d.long_csv(), encoding="utf-8")
    ev_csv = Evidence()
    info = ingest.load(pl, ev_csv)
    check("long CSV (entity_id,state,last_changed) imports every row", info.fmt == "csv" and info.accepted == n_rows,
          f"{info.accepted} vs {n_rows}")
    pw = Path(td) / "wide.csv"
    eb, ec = d.eid("b10"), d.eid("clock_difference")
    pw.write_text(f"timestamp,{eb},{ec}\n2026-10-05T00:00:00Z,{S.B10_MATCH.replace(',', ';')},-6\n2026-10-05T00:01:00Z,,-7\n"
                  "bad-time,x,1\n", encoding="utf-8")
    ev_w = Evidence()
    iw = ingest.load(pw, ev_w)
    check("wide CSV (timestamp + one column per entity) imports, empty cells skipped, a bad timestamp rejected with its line",
          iw.accepted == 3 and iw.rejected == 2 and any(x.ref.endswith(":4:" + eb) for x in ev_w.diagnostics), f"{iw}")
    pj = Path(td) / "bad.json"
    pj.write_text("{not json", encoding="utf-8")
    ev_bj = Evidence()
    ij = ingest.load(pj, ev_bj)
    check("an unreadable JSON file is rejected and reported, not skipped silently", ij.rejected == 1 and ev_bj.diagnostics)
    pc = Path(td) / "short.csv"
    pc.write_text("entity_id,state,last_changed\nsensor.ecco_clock_dongle_clock_difference,-6\n", encoding="utf-8")
    ev_sc = Evidence()
    isc = ingest.load(pc, ev_sc)
    check("a short CSV row is rejected with its line reference", isc.rejected == 1 and ev_sc.diagnostics[0].ref.endswith(":2"))
ev_p = Evidence()
dp = S.Dongle(hours=1, prefix="loft_").run()
ingest.load_object(dp.ha_history(), ev_p)
check("area-prefixed entity ids (loft_ecco_clock_dongle_*) are recognised", ev_p.has("b10") and ev_p.has("clock_difference")
      and ev_p.get("b10").entity_id.startswith("sensor.loft_"))
ev_o = Evidence()
ingest.load_object([[{"entity_id": "sensor.my_live_match", "state": S.B10_MATCH, "last_changed": "2026-10-05T00:00:00Z"}]], ev_o,
                   overrides={"b10": "sensor.my_live_match"})
check("--entity overrides map a renamed entity to its catalogue key", ev_o.has("b10"))
ev_u = Evidence()
ingest.load_object([[{"entity_id": "sensor.ecco_clock_dongle_brand_new_thing", "state": "1", "last_changed": "2026-10-05T00:00:00Z"}],
                    [{"entity_id": "light.kitchen", "state": "on", "last_changed": "2026-10-05T00:00:00Z"}]], ev_u)
check("entities outside the catalogue are counted as unknown and ignored", ev_u.unknown_entities == {
    "sensor.ecco_clock_dongle_brand_new_thing": 1, "light.kitchen": 1} and not ev_u.series)
ev_n = Evidence()
ingest.load_object([[{"entity_id": d.eid("b10"), "state": "x", "last_changed": "2026-10-05T00:00:00"}]], ev_n)
check("a timestamp without offset in an HA export is read as UTC and flagged", ev_n.has("b10")
      and any(x.code == "naive-timestamp" for x in ev_n.diagnostics))

LOG = """INFO Reading configuration ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml...
\x1b[0;32m[23:59:20][I][ecco:21070]: Inverter RTC: 2026-10-04 23:59:14 | Difference from NTP: -6 s\x1b[0m
[00:00:20.512][I][ecco:21070]: Inverter RTC: 2026-10-05 00:00:14 | Difference from NTP: -6 s
[00:01:20][W][ecco:21160]: RTC STALL detected - inverter advanced 10 s while NTP advanced 60 s
continuation line without a prefix
[00:01:21][W][config:15847]: No response to configuration register 330
"""
ev_l = Evidence()
il = ingest.load_log_text(LOG, ev_l)
ts = [e.t for e in ev_l.logs]
check("esphome log: auto-anchored from its Inverter RTC line, ANSI stripped, ms clocks accepted, midnight rolled over",
      il.accepted == 4 and ts[0] == datetime(2026, 10, 4, 22, 59, 20, tzinfo=UTC)
      and ts[1] == datetime(2026, 10, 4, 23, 0, 20, 512000, tzinfo=UTC)
      and [e.kind for e in ev_l.logs] == ["rtc_read", "rtc_read", "rtc_stall", "block_c_error"], f"{il} {ts}")
ev_l2 = Evidence()
il2 = ingest.load_log_text("[10:00:00][I][config:1]: anything\n", ev_l2)
check("a clock-only log with no anchor is rejected (never placed on a guessed date)", il2.rejected == 1 and not ev_l2.logs)
ev_l3 = Evidence()
ingest.load_log_text("2026-10-05T00:03:12+01:00 [W][ecco:21267]: RTC correction queued - clock difference: -47 seconds\n", ev_l3)
check("ISO-prefixed log lines carry their own instant", ev_l3.logs and ev_l3.logs[0].t == datetime(2026, 10, 4, 23, 3, 12, tzinfo=UTC)
      and ev_l3.logs[0].fields == {"diff": "-47"})
# ESPHome 2026 capture (as written by the project's `esphome logs` wrapper): a `# ... start=<ISO>` header, millisecond clocks,
# HEXADECIMAL source line numbers and an [S] state level. Shape taken from real pre-FB-D1 captures (values made up).
CAP = ("# esphome logs --device dongle.invalid  start=2026-10-04T15:36:58.1234567+01:00  end=2026-10-04T15:38:30+01:00\r\n"
       "INFO ESPHome 2026.8.2\r\n"
       "[15:37:13.059][I][ecco:D802]: Inverter RTC: 2026-10-04 15:37:33 | Difference from NTP: 20 s\r\n"
       "[15:37:13.059][W][ecco:D951]: RTC correction queued - clock difference: 20 seconds\r\n"
       "[15:37:13.691][I][ecco:7475]: Starting RTC write attempt 1\r\n"
       "[15:37:13.691][I][ecco:7509]: RTC write acknowledged - verification scheduled in 10 seconds\r\n"
       "[15:37:24.592][I][ecco:F266]: Performing post-write RTC verification\r\n"
       "[15:37:24.649][I][ecco:D802]: Inverter RTC: 2026-10-04 15:37:15 | Difference from NTP: -9 s\r\n"
       "[15:37:24.782][I][ecco:D842]: RTC correction VERIFIED - error now -9 seconds\r\n"
       "[15:37:59.795][S][sensor]: 'ECCO PV Power' >> 812 W\r\n"
       "[15:38:13.005][I][ecco:D802]: Inverter RTC: 2026-10-04 15:38:10 | Difference from NTP: -3 s\r\n")
ev_c = Evidence()
ic = ingest.load_log_text(CAP, ev_c)
kinds = [e.kind for e in ev_c.logs]
check("ESPHome 2026 capture: anchored from its header, hex line numbers and the [S] level accepted, milliseconds kept",
      ic.accepted == 9 and ev_c.logs[0].t == datetime(2026, 10, 4, 14, 37, 13, 59000, tzinfo=UTC)
      and kinds[:4] == ["rtc_read", "rtc_queued", "rtc_write_start", "rtc_write_ack"]
      and any(x.code == "log-anchor" and "header" in x.detail for x in ev_c.diagnostics), f"{ic} {kinds}")
rep_c = run(ev_c, start=datetime(2026, 10, 4, 14, 36, tzinfo=UTC), end=datetime(2026, 10, 4, 14, 39, tzinfo=UTC),
            now=datetime(2026, 10, 8, tzinfo=UTC))
ec = episodes(rep_c)
stl_c = rep_c["areas"]["rtc"]["stalls"]["sources"]
check("ESPHome 2026 capture: one verified correction (+20 -> -9 s), the verification read recognised, and the next regular read "
      "(-3 s, 60 s after the +20 s queue read) is NOT a stall: the write acknowledged 0.6 s after the queue read re-based it",
      len(ec) == 1 and ec[0]["outcome"] == "verified" and ec[0]["residual_s"] == -9 and ec[0]["error_s"] == 20
      and stl_c["stall_reads"] == 0, json.dumps([ec, stl_c])[:400])
check("a pre-FB-D1 log (no `RTC policy:` line) leaves the policy reason unknown: C-RTC-2 INSUFFICIENT, never PASS",
      crit(rep_c, "C-RTC-2")["verdict"] == "INSUFFICIENT_EVIDENCE" and "policy reason" in crit(rep_c, "C-RTC-2")["reasons"][0])
fb = "[01:59:40][I][ecco:1]: x\n[01:00:10][I][ecco:1]: y\n[01:30:00][I][ecco:1]: z\n[02:00:20][I][ecco:1]: w\n"
ev_fb = Evidence()
ingest.load_log_text(fb, ev_fb, log_date=date(2026, 10, 25))
check("a clock-only log across the autumn fall-back keeps time moving forward (repeated hour read as GMT)",
      [e.t for e in ev_fb.logs] == [datetime(2026, 10, 25, 0, 59, 40, tzinfo=UTC), datetime(2026, 10, 25, 1, 0, 10, tzinfo=UTC),
                                    datetime(2026, 10, 25, 1, 30, tzinfo=UTC), datetime(2026, 10, 25, 2, 0, 20, tzinfo=UTC)]
      and not ev_fb.diagnostics, str([e.t for e in ev_fb.logs]))

# counter delta (restart-aware), independent arithmetic
ser = Series("verified_corrections", "x")
t0 = datetime(2026, 10, 5, tzinfo=UTC)
for i, v in enumerate(["5", "7", "unavailable", "2", "abc", "4"]):
    ser.samples.append(Sample(t0 + timedelta(hours=i), v, f"r{i}"))
cd = counter_delta(ser, t0 - timedelta(minutes=1), t0 + timedelta(hours=6))
check("counter delta: 5 -> 7 (+2) -> reset to 2 (+2) -> 4 (+2) = 6, one reset, unavailable / invalid rows skipped",
      cd.delta == 6 and len(cd.resets) == 1 and cd.available, f"{cd.delta} {cd.resets}")
cd2 = counter_delta(ser, t0 + timedelta(minutes=30), t0 + timedelta(hours=2, minutes=30))
check("counter delta inside a sub-window uses the value in force at its start (5 at +30 min -> 7: +2)", cd2.delta == 2, str(cd2.delta))
check("a missing counter is unavailable (delta None), never zero", counter_delta(None, t0, t0 + timedelta(hours=1)).delta is None)

# =============================================================================================================================
print("[4] scenarios")
# --- S1 perfect seven-day soak ------------------------------------------------------------------------------------------------
p = S.Dongle()
g0 = p.at_bst(1, 13, 0)
p.set_drift(g0, -7.0)  # high PV, from the -3 s precision residual: -3, -10, -17, -24, -31, -38
tg = p.at_bst(1, 13, 5)
p.correction(tg, "background")
p.set_drift(tg, 0.0)
p.set_offset(p.at_bst(1, 0, 20), -11)  # 00:20:20 BST: an 11 s error, corrected only by the 00:23:20 precision window
tp = p.at_bst(1, 0, 23)
p.correction(tp, "precision")
p.run()
rep = analyse(p)
v = verdicts(rep)
required = [c["id"] for c in rep["criteria"] if c["required"]]
check("perfect soak: overall PASS", rep["overall"]["verdict"] == "PASS", json.dumps(v))
check("perfect soak: every required criterion PASS", all(v[c] == "PASS" for c in required), json.dumps(v))
check("perfect soak: no FAIL or WARNING event", not rep["suspicious_events"], json.dumps(rep["suspicious_events"][:3]))
check("perfect soak: the one optional criterion without evidence (Block C needs a log) is INSUFFICIENT and does not block",
      v["C-POLL-3"] == "INSUFFICIENT_EVIDENCE")
eps = episodes(rep)
check("perfect soak: two corrections as planned (precision -11 s at 00:23:20; background -38 s at 13:05:20, i.e. the -3 s residual "
      "of the precision correction drifting -7 s/min for 5 min)",
      [(e["reason"], e["error_s"], e["start"]["local"]) for e in eps] ==
      [("precision", -11, "2026-10-05 00:23:20 BST"), ("background", -38, "2026-10-05 13:05:20 BST")], str(eps))
check("perfect soak: the high-PV correction is consistent with drift (never a false-confirmation label)",
      eps[1]["analysis"]["classification"] == "consistent_with_drift" and not eps[1]["analysis"]["suspected_noop"])
check("perfect soak: every policy check of both corrections passes",
      all(c["result"] in ("ok", "ok-partial") for e in eps for c in e["analysis"]["policy"]["checks"]),
      str([c for e in eps for c in e["analysis"]["policy"]["checks"] if c["result"] not in ("ok", "ok-partial")]))
nm = sum((c["end"] + timedelta(seconds=c["recovery_s"]) - (c["t"] + timedelta(seconds=1))).total_seconds()
         for c in p.truth["corrections"])
b = rep["areas"]["b10"]
check(f"perfect soak: B10 non-MATCH time equals the scenario's own sum ({nm:.0f} s) and MATCH % is exact",
      b["time_s"]["UNKNOWN"] == nm and abs(b["match_pct_window"] - 100 * (1 - nm / (7 * 86400))) < 1e-3,
      f"{b['time_s']} {b['match_pct_window']}")
check("perfect soak: release-to-MATCH recovery is 31 s for both corrections",
      [x["match_after_s"] for x in b["recovery_after_corrections"]] == [31.0, 31.0])
check("perfect soak: seven daily rows of exactly 24 h, D1 starting at the soak start",
      len(rep["daily"]) == 7 and all(r["hours"] == 24 for r in rep["daily"]) and rep["daily"][0]["from"]["local"] ==
      "2026-10-04 23:14:37 BST")
check("perfect soak: daily corrections are D1 = 2 (00:23 and 13:05 on 5 Oct are both before 23:14:37), others 0",
      [r["corrections"] for r in rep["daily"]] == [2, 0, 0, 0, 0, 0, 0], str([r["corrections"] for r in rep["daily"]]))
check("perfect soak: the counters agree with the episodes (verified +2, write attempts +2, failed +0)",
      rep["areas"]["rtc"]["counters"]["verified"]["delta"] == 2 and rep["areas"]["rtc"]["counters"]["write_attempts"]["delta"] == 2
      and rep["areas"]["rtc"]["counters"]["failed"]["delta"] == 0)
check("perfect soak: continuity proven by the boot nonce and the heartbeat counter", rep["areas"]["continuity"]["continuity_proven"]
      and len(rep["areas"]["continuity"]["continuity_witnesses"]) == 2)
pwin = rep["areas"]["rtc"]["precision_windows"]
check("perfect soak: 42 precision windows (6 zones x 7 days), one precision correction, none missed",
      pwin["windows"] == 42 and pwin["precision_corrections"] == 1 and not pwin.get("expected_not_observed"), str(pwin))
check("perfect soak: the outstanding list still asks for the post-completion counter snapshot and write attribution",
      any("24-48 h counter snapshot" in x["requirement"] for x in rep["outstanding_live_proof"]))
md = markdown(rep)
check("perfect soak: the Markdown report has every required section", all(h in md for h in (
    "## 1. Acceptance summary", "## 2. Daily metrics", "## 3. RTC corrections", "## 4. RTC stall detection", "## 5. B10 Live Match",
    "## 6. Modbus and polling", "## 7. Continuity", "## 8. Safety", "## 9. Suspicious events", "## 10. FB-D1 A3 stall-veto",
    "## 11. Evidence coverage", "## 12. Outstanding live-proof", "## 13. Decision thresholds")))
check("perfect soak: daily CSV has 7 data rows; events CSV only a header", len(daily_csv(rep).splitlines()) == 8
      and len(events_csv(rep).splitlines()) == 1)
check("perfect soak: the JSON report is serialisable and names its schema", json.loads(json.dumps(rep, default=str))["schema"] ==
      "ecco-fbd1-soak-analysis/1")

# --- S2 incomplete evidence -------------------------------------------------------------------------------------------------
inc = S.Dongle(hours=72).run()
rep = analyse(inc, days=7, now=S.START + timedelta(days=3))
v = verdicts(rep)
check("incomplete evidence (3 of 7 days, analysed mid-soak): C-CONT-3 INSUFFICIENT and overall INSUFFICIENT, never PASS",
      v["C-CONT-3"] == "INSUFFICIENT_EVIDENCE" and rep["overall"]["verdict"] == "INSUFFICIENT_EVIDENCE"
      and not rep["window"]["complete"], json.dumps(v))
check("incomplete evidence: B10 coverage 3/7 is INSUFFICIENT, not a low MATCH FAIL", v["C-B10-1"] == "INSUFFICIENT_EVIDENCE"
      and abs(rep["areas"]["b10"]["coverage_pct"] - 100 * 3 / 7) < 0.1, str(rep["areas"]["b10"]["coverage_pct"]))
check("incomplete evidence: the first outstanding requirement is a re-export after 2026-10-11 23:14:37 BST",
      "2026-10-11 23:14:37 BST" in rep["outstanding_live_proof"][0]["requirement"])

# --- S3 missing day ------------------------------------------------------------------------------------------------------------
md_ = S.Dongle().run()
a, z = S.START + timedelta(days=3), S.START + timedelta(days=4)
md_.drop(a, z)
rep = analyse(md_)
v = verdicts(rep)
d4 = rep["daily"][3]
check("missing day: C-CONT-2 INSUFFICIENT (D4 has no evidence), overall INSUFFICIENT",
      v["C-CONT-2"] == "INSUFFICIENT_EVIDENCE" and rep["overall"]["verdict"] == "INSUFFICIENT_EVIDENCE", json.dumps(v))
check("missing day: continuity across the gap is still proven (same boot nonce, heartbeat counter never reset)",
      v["C-CONT-1"] == "PASS", crit(rep, "C-CONT-1")["summary"])
nev = rep["areas"]["b10"]["time_s"]["NO_EVIDENCE"]
check("missing day: B10 has 24 h (+ < 2 min of row spacing) of NO_EVIDENCE, never MATCH", 86400 <= nev <= 86400 + 120, str(nev))
check("missing day: D4 coverage is below 1 %, D3 and D5 are complete", d4["coverage_pct"] < 1 and rep["daily"][2]["coverage_pct"] > 99.8
      and rep["daily"][4]["coverage_pct"] > 99.8, f"{d4['coverage_pct']}")

# --- S4 unexpected restart ---------------------------------------------------------------------------------------------------
rs = S.Dongle()
rs.set_offset(rs.at_bst(1, 13, 0), -35)
rs.correction(rs.at_bst(1, 13, 2), "background")  # before the restart
bt = rs.at_bst(2, 10, 0, 0)
rs.restart(bt)
rs.set_offset(rs.at_bst(3, 0, 20), -12)
rs.correction(rs.at_bst(3, 0, 23), "precision")  # after it
rs.run()
rep = analyse(rs)
v = verdicts(rep)
rst = rep["areas"]["continuity"]["restarts"]
check("unexpected restart: C-CONT-1 FAIL and overall FAIL", v["C-CONT-1"] == "FAIL" and rep["overall"]["verdict"] == "FAIL")
check("unexpected restart: exactly one restart, timed within 1 min of the boot, signals nonce + counter + boot-text",
      len(rst) == 1 and abs((timeutil.parse_ts(rst[0]["time"]["utc"]) - bt).total_seconds()) <= 60
      and {"nonce", "counter", "boot-text"} <= set(rst[0]["signals"]), str(rst))
check("unexpected restart: the verified counter delta is restart-aware (1 before + 1 after = 2)",
      rep["areas"]["rtc"]["counters"]["verified"]["delta"] == 2)
check("unexpected restart: the daily table puts it in D2 (6 Oct 10:00 BST)", [r["restarts"] for r in rep["daily"]] == [0, 1, 0, 0, 0, 0, 0])
check("unexpected restart: a FAIL event with references", any(e["code"] == "unexpected-restart" and e["severity"] == "FAIL"
                                                               and e["refs"] for e in rep["suspicious_events"]))

# --- S5..S9 RTC classification ---------------------------------------------------------------------------------------------
rt = S.Dongle(hours=48)
t60a, t60b = rt.at_bst(0, 23, 26), rt.at_bst(0, 23, 27)
rt.stale_read(t60a, -60)
rt.stale_read(t60b, -60)
rt.correction(t60b, "background", label="-60/-60")
t36a, t36b = rt.at_bst(1, 0, 2), rt.at_bst(1, 0, 3)
rt.stale_read(t36a, -36)
rt.stale_read(t36b, -47)
rt.correction(t36b, "background", label="-36/-47")
for hh_mm, val in (((2, 8), -16), ((2, 9), -30), ((2, 10), -32)):  # 13-14 s steps from -3 s: no stall
    rt.stale_read(rt.at_bst(1, *hh_mm), val)
rt.correction(rt.at_bst(1, 2, 10), "background", label="no-stall")
rt.stale_read(rt.at_bst(1, 3, 15), -63)  # one frozen read: the image repeated, the inverter advanced 0 s in 60 s (-3 -> -63)
g1 = rt.at_bst(1, 12, 0)
rt.set_drift(g1, -7.0)
tg2 = rt.at_bst(1, 12, 5)
rt.correction(tg2, "background", label="genuine")
rt.set_drift(tg2, 0.0)
rt.run()
rep = analyse(rt)
E = {e["start"]["local"][11:16]: e for e in episodes(rep)}
e60, e36, ens, egn = E["23:27"], E["00:03"], E["02:10"], E["12:05"]
a60 = e60["analysis"]
check("-60/-60: classified stale_first_read_candidate (stall on the prior read, jump of -54 s against a -6 s night trend)",
      a60["classification"] == "stale_first_read_candidate" and a60["stall_on_prior_read"] and a60["trend_error_s"] == -6
      and a60["prior_vs_trend_s"] == -54 and a60["daylight"] is False, json.dumps(a60)[:400])
check("-60/-60: suspected no-op; the write moved the clock about +3 s (-3 residual - -6 trend), not 60 s",
      a60["suspected_noop"] and a60["estimated_effective_correction_s"] == 3)
check("-60/-60: identical confirming reads (pair difference 0) - the policy itself was followed (confirmation ok)",
      a60["pair_difference_s"] == 0 and a60["policy"]["result"] == "consistent")
a36 = e36["analysis"]
check("-36/-47: stale_first_read_candidate; the pair differs by -11 s, beyond the 3.5 s night allowance",
      a36["classification"] == "stale_first_read_candidate" and a36["pair_difference_s"] == -11 and a36["pair_disagrees"]
      and a36["suspected_noop"], json.dumps(a36)[:400])
ans = ens["analysis"]
check("no-stall false confirmation: 13-14 s steps never trip the stall rule, yet the -30 s prior read is far from the -3 s trend",
      ans["classification"] == "false_confirmation_candidate" and not ans["stall_on_prior_read"] and ans["suspected_noop"],
      json.dumps(ans)[:400])
agn = egn["analysis"]
check("genuine drift (-7 s/min at 2.5 kW): consistent_with_drift, not a stale label", agn["classification"] == "consistent_with_drift"
      and agn["daylight"] is True and not agn["suspected_noop"], json.dumps(agn)[:300])
stl = rep["areas"]["rtc"]["stalls"]
check("stalls: the counter (+3: the -60 read, the -36 read, the frozen read; never the forward jump back) matches the scenario",
      stl["sources"]["counter"] == rt.truth["stalls"] and rt.truth["stalls"] == 3, f"{stl['sources']} truth={rt.truth['stalls']}")
check("a single frozen read is counted as a repeated read and never becomes a correction or a candidate",
      stl["repeated_frozen_reads"] == 1 and not any(e["start"]["local"][11:16] in ("03:15", "03:16") for e in episodes(rep)))
v = verdicts(rep)
check("C-RTC-4 is WARNING (3 candidates of 4 background corrections), required criteria unaffected",
      v["C-RTC-4"] == "WARNING" and crit(rep, "C-RTC-4")["metrics"]["candidates"] == 3 and v["C-RTC-2"] == "PASS", json.dumps(v))
a3 = rep["a3_stall_veto"]
v1 = a3["variants"][0]
check("A3: V1 stall veto holds 2/3 candidates (not the no-stall one) and 0/1 genuine",
      v1["would_hold_candidates"] == 2 and v1["would_hold_drift_consistent"] == 0, json.dumps(v1))
check("A3: V2(10 s) holds only the -36/-47 pair; a pair-difference rule cannot catch -60/-60",
      next(x for x in a3["variants"] if x["name"] == "V2 pair-consistency 10 s")["held_candidate_ids"] == [e36["id"]]
      and any("identical confirming reads" in r for r in a3["recommendations"]), json.dumps(a3["variants"])[:300])
check("A3: the stall-veto safety argument and the simulate-first rule are always in the recommendations",
      any("-15 s/min" in r for r in a3["recommendations"]) and any("simulate it offline" in r for r in a3["recommendations"]))
check("A3: normal read-to-read deltas exclude stalled pairs (night max 14 s = the no-stall stale steps, daylight max 7 s)",
      a3["consecutive_read_delta_s"]["night"]["max"] == 14 and a3["consecutive_read_delta_s"]["daylight"]["max"] == 7
      and a3["stalled_read_pairs_excluded"] >= 3, json.dumps(a3["consecutive_read_delta_s"]))

# --- S10 RTC abort ------------------------------------------------------------------------------------------------------------
# --- correction storm (the pre-FB-D1 cadence: a correction every 4 min) ------------------------------------------------------
cs = S.Dongle(hours=7)
base = S.START.replace(second=0) + timedelta(minutes=1, seconds=20)
for k in range(0, 360, 4):
    cs.set_offset(base + timedelta(minutes=k - 1), -35)
    cs.correction(base + timedelta(minutes=k), "background")
cs.run()
rep = analyse(cs, days=0.25)
m = crit(rep, "C-RTC-3")["metrics"]
check("correction storm: 90 corrections in a 6 h window = 360 per 24 h, C-RTC-3 FAIL (> 144)",
      crit(rep, "C-RTC-3")["verdict"] == "FAIL" and m["per_day"] == [90] and m["max_rate_per_24h"] == 360, json.dumps(m))
ab = S.Dongle(hours=48)
ab.set_offset(ab.at_bst(1, 14, 0), -41)
ab.correction(ab.at_bst(1, 14, 2), "background", outcome="aborted", lock_s=90)
ab.correction(ab.at_bst(1, 14, 8), "background")
ab.run()
rep = analyse(ab)
v = verdicts(rep)
check("RTC abort: C-RTC-1 WARNING (one failure, one abort, below the FAIL bounds)", v["C-RTC-1"] == "WARNING",
      json.dumps(crit(rep, "C-RTC-1")))
check("RTC abort: C-RTC-3 WARNING (lock held 90 s: above 50 s, below the 100 s breaker bound)",
      v["C-RTC-3"] == "WARNING" and crit(rep, "C-RTC-3")["metrics"]["lock_max_s"] == 90)
check("RTC abort: episode outcomes aborted then verified; failed counter +1; an abort event",
      [e["outcome"] for e in episodes(rep)] == ["aborted", "verified"] and rep["areas"]["rtc"]["counters"]["failed"]["delta"] == 1
      and events(rep, "correction-aborted"))

# --- S11 repeated failures -----------------------------------------------------------------------------------------------------
rf = S.Dongle(hours=48)
rf.set_offset(rf.at_bst(1, 14, 0), -45)
for mm in (5, 15, 25):
    rf.correction(rf.at_bst(1, 14, mm), "background", outcome="failed", attempts=2, verify_errs=(-45, -45))
rf.run()
rep = analyse(rf)
v = verdicts(rep)
check("repeated failures: C-RTC-1 FAIL (3 failed corrections in a row)", v["C-RTC-1"] == "FAIL"
      and crit(rep, "C-RTC-1")["metrics"]["longest_failure_run"] == 3 and rep["overall"]["verdict"] == "FAIL")
check("repeated failures: 6 RTC writes for 3 failed corrections are fully attributed (2 attempts each)",
      crit(rep, "C-SAFE-1")["metrics"]["rtc_write_attempts"] == 6 and crit(rep, "C-SAFE-1")["metrics"]["unexplained_rtc_writes"] == 0)
check("repeated failures: each episode recorded one retry and the residual -45 s",
      all(e["retries"] == 1 and e["residual_s"] == -45 and e["outcome"] == "failed" for e in episodes(rep)))

# --- S12 Block C read failure (log + counter + online state) ------------------------------------------------------------------
bc = S.Dongle(hours=48)
tf = bc.at_bst(1, 10, 0, 45)
bc.put("configuration_online", tf, "off")
bc.put("configuration_online", tf + timedelta(seconds=60), "on")
bc.bump("configuration_failures", tf)
bc.run()
blog = ("[10:00:20][I][ecco:21070]: Inverter RTC: 2026-10-05 10:00:14 | Difference from NTP: -6 s\n"
        "[10:00:45][W][config:15847]: No response to configuration register 330\n")
rep = analyse(bc, logs=[(blog, None)])
v = verdicts(rep)
check("Block C failure: C-POLL-1 WARNING (configuration failures +1, Configuration Online off 60 s)",
      v["C-POLL-1"] == "WARNING" and crit(rep, "C-POLL-1")["metrics"]["configuration_failures"] == 1
      and crit(rep, "C-POLL-1")["metrics"]["longest_offline_s"] == 60, json.dumps(crit(rep, "C-POLL-1")))
check("Block C failure: C-POLL-3 WARNING, attributed to register 330 from the log",
      v["C-POLL-3"] == "WARNING" and crit(rep, "C-POLL-3")["metrics"]["block_c_errors"] == 1)
check("Block C failure: telemetry failures are a confirmed zero (counter present and spanning)",
      rep["areas"]["polling"]["telemetry_failures"] == {"available": True, "delta": 0.0, "spans_window": True})

# --- S13 B10 recovery + S14 NOT MATCH + S15 MATCH under the lock -------------------------------------------------------------
br = S.Dongle(hours=48)
br.set_offset(br.at_bst(1, 13, 0), -35)
br.correction(br.at_bst(1, 13, 2), "background", recovery_s=31)
br.set_offset(br.at_bst(1, 15, 0), -35)
br.correction(br.at_bst(1, 15, 2), "background", recovery_s=300)
dr0 = br.at_bst(1, 18, 0, 0)
br.b10(dr0, dr0 + timedelta(minutes=20), S.B10_DRIFT)
lk = br.at_bst(1, 20, 0, 5)
br.put("rtc_correction_in_progress", lk, "on")
br.put("rtc_correction_in_progress", lk + timedelta(seconds=60), "off")
br.run()
rep = analyse(br)
b = rep["areas"]["b10"]
check("B10 recovery: release-to-MATCH 31 s and 300 s measured exactly; C-B10-2 WARNING (300 s > 120 s)",
      [x["match_after_s"] for x in b["recovery_after_corrections"]] == [31.0, 300.0] and verdicts(rep)["C-B10-2"] == "WARNING")
check("B10 NOT MATCH: 20 min of DRIFT measured exactly (1200 s) and reported as an event",
      b["time_s"]["NOT_MATCH"] == 1200 and b["time_by_mode_s"]["DRIFT"] == 1200 and events(rep, "b10-not-match"))
check("B10 under the RTC lock: 60 s of MATCH while RTC Correction In Progress was on makes C-B10-1 FAIL",
      verdicts(rep)["C-B10-1"] == "FAIL" and b["lock_overlaps"] and b["lock_overlaps"][0]["match_s"] == 60
      and any(e["code"] == "match-while-rtc-lock" and e["severity"] == "FAIL" for e in rep["suspicious_events"]))
lng = b["longest_interruption"]
check("B10: the longest interruption is the 20 min DRIFT, its cause unexplained by corrections or leases",
      lng["seconds"] == 1200 and lng["modes"] == ["DRIFT"] and lng["causes"] == ["unexplained"], json.dumps(lng))

# --- S16 clock / timestamp discontinuity ------------------------------------------------------------------------------------------
ck = S.Dongle(hours=24)
ck.run()
ca, cz = ck.at_bst(0, 23, 30, 0) + timedelta(hours=2), ck.at_bst(0, 23, 30, 0) + timedelta(hours=2, minutes=30)
eid = ck.eid("ntp_time")
ck.rows[eid] = [(t, S.lstr(t + timedelta(seconds=120)) if ca <= t < cz else s) for t, s in ck.rows[eid]]
rep = analyse(ck)
check("clock discontinuity: one NTP-vs-HA jump of 120 s found, C-CONT-4 WARNING",
      verdicts(rep)["C-CONT-4"] == "WARNING" and len(rep["areas"]["continuity"]["clock"]["discontinuities"]) == 1
      and rep["areas"]["continuity"]["clock"]["discontinuities"][0]["offset_s"] == 120)
with tempfile.TemporaryDirectory() as td:
    lines = ck.long_csv().splitlines()
    pth = Path(td) / "ooo.csv"
    pth.write_text("\n".join([lines[0]] + lines[1:][::-1]) + "\n", encoding="utf-8")
    ev_o2 = Evidence()
    ingest.load(pth, ev_o2)
    n_ooo = sum(1 for x in ev_o2.diagnostics if x.code == "out-of-order")
    rep2 = run(ev_o2, start=S.START, days=1, now=S.START + timedelta(days=2))
check("out-of-order rows: reported per entity, re-sorted, the analysis is unchanged",
      n_ooo > 0 and crit(rep2, "C-CONT-4")["metrics"]["out_of_order_rows"] == n_ooo
      and rep2["areas"]["b10"]["time_s"] == rep["areas"]["b10"]["time_s"], f"{n_ooo}")

# --- S17 malformed data + S18 unknown entity values -------------------------------------------------------------------------------
mf = S.Dongle(hours=24)
mf.run()
iso = (S.START + timedelta(hours=1)).isoformat()
mf.extra = ["junk", [{"entity_id": mf.eid("clock_difference"), "state": "-6", "last_changed": "not-a-time"}],
            [{"entity_id": mf.eid("clock_difference"), "last_changed": iso}], [{"state": "x", "last_changed": iso}], [42]]
u0 = S.START + timedelta(hours=3)
mf.put("b10", u0, "garbage")
mf.put("b10", u0 + timedelta(minutes=10), S.B10_MATCH)
mf.put("verified_corrections", u0, "abc")
mf.put("rtc_stall_detected", u0, "maybe")
rep = analyse(mf)
ins = rep["evidence"]["inputs"][0]
check("malformed data: exactly the 5 malformed rows are rejected, each reported with a reference",
      ins["rejected"] == 5 and sum(1 for x in rep["evidence"]["diagnostics"] if x["severity"] == "error") == 5, json.dumps(ins))
check("malformed data: the analysis still completes and C-CONT-4 reports the rejected rows",
      crit(rep, "C-CONT-4")["metrics"]["rejected_rows"] == 5 and verdicts(rep)["C-CONT-4"] == "WARNING")
check("unknown values: an unreadable B10 state is 10 min UNKNOWN (mode UNREADABLE), never MATCH",
      rep["areas"]["b10"]["time_s"]["UNKNOWN"] == 600 and rep["areas"]["b10"]["time_by_mode_s"].get("UNREADABLE") == 600)
check("unknown values: a non-numeric counter row and a non-boolean binary row are reported (invalid-values) and ignored",
      len([e for e in events(rep, "invalid-values")]) == 2 and rep["areas"]["rtc"]["counters"]["verified"]["delta"] == 0)

# --- S19 partial history coverage ------------------------------------------------------------------------------------------------
ph = S.Dongle()
ph.run()
ph.only(["b10", "clock_difference"])
rep = analyse(ph)
v = verdicts(rep)
need_insuff = ("C-CONT-1", "C-CONT-2", "C-RTC-1", "C-POLL-1", "C-POLL-2", "C-SAFE-1", "C-SAFE-2", "C-SUP-1")
check("partial coverage (only B10 + Clock Difference): every criterion needing the missing diagnostics is INSUFFICIENT",
      all(v[c] == "INSUFFICIENT_EVIDENCE" for c in need_insuff), json.dumps(v))
check("partial coverage: nothing absent is ever PASS: overall INSUFFICIENT", rep["overall"]["verdict"] == "INSUFFICIENT_EVIDENCE")
check("partial coverage: the outstanding list names the missing diagnostics", any(
    "Failed Corrections Since Boot" in x["requirement"] and "ECCO Supervision Challenge" in x["requirement"]
    for x in rep["outstanding_live_proof"]))
nw = S.Dongle()
nw.run()
nw.without(["inverter_time", "ntp_time", "valid_heartbeats", "last_telemetry_update", "last_configuration_update"])
rep = analyse(nw)
check("no periodic witness entity: coverage is estimated from on-change rows (here the 2-min challenge) and C-CONT-2 is at "
      "best WARNING, never PASS", verdicts(rep)["C-CONT-2"] == "WARNING" and crit(rep, "C-CONT-2")["basis"] == "inferred"
      and "on-change rows" in rep["areas"]["continuity"]["coverage_basis"], json.dumps(crit(rep, "C-CONT-2"))[:300])
check("no periodic witness entity: continuity is still PROVEN by the boot nonce (a confirmed witness)", verdicts(rep)["C-CONT-1"] == "PASS")
pb = S.Dongle()
pb.run()
cut = S.START + timedelta(days=2)  # B10 exported from day 3 only (HA's export opens with the state in force at its start)
eb = pb.eid("b10")
pb.rows[eb] = [r for r in pb.rows[eb] if r[0] >= cut] + [(cut, S.B10_MATCH)]
rep = analyse(pb)
check("partial B10 history (last 5 of 7 days): C-B10-1 INSUFFICIENT; exactly 2 days of NO_EVIDENCE, never MATCH",
      verdicts(rep)["C-B10-1"] == "INSUFFICIENT_EVIDENCE" and rep["areas"]["b10"]["time_s"]["NO_EVIDENCE"] == 2 * 86400,
      str(rep["areas"]["b10"]["time_s"]))

# --- S20 policy violations and window edges --------------------------------------------------------------------------------------
pv = S.Dongle(hours=48)
pv.set_offset(pv.at_bst(0, 23, 27), -40)
pv.correction(pv.at_bst(0, 23, 29), "background")  # 23:29:20: inside the half-hour quiet window [23:29, 23:31)
pv.set_offset(pv.at_bst(1, 0, 19), -12)
pv.correction(pv.at_bst(1, 0, 20), "precision")  # 00:20:20: not in [00:23, 00:24)
edge = pv.at_bst(1, 3, 31, 1)  # 03:31:01: one second after the quiet window ends
pv.run()
pv.put("last_correction_result", edge, "Automatic correction queued (background) - error -40 s")
pv.put("last_correction_result", edge + timedelta(seconds=11), "Verified OK - error now -2 s")
rep = analyse(pv)
E = {e["start"]["local"][11:19]: e for e in episodes(rep)}
qcheck = lambda e, name: next(c for c in e["analysis"]["policy"]["checks"] if c["check"] == name)  # noqa: E731
check("policy: a background correction at 23:29:20 is a quiet-window violation", qcheck(E["23:29:20"], "quiet-window")["result"] == "violation")
check("policy: a precision correction at 00:20:20 is outside every precision window",
      qcheck(E["00:20:20"], "precision-window")["result"] == "violation")
check("policy: a correction 1 s after a quiet window is an `edge`, never a violation",
      qcheck(E["03:31:01"], "quiet-window")["result"] == "edge" and E["03:31:01"]["analysis"]["policy"]["result"] == "warning")
check("policy: C-RTC-2 FAIL with exactly 2 violations and 2 policy-violation events",
      verdicts(rep)["C-RTC-2"] == "FAIL" and crit(rep, "C-RTC-2")["metrics"]["violations"] == 2
      and len(events(rep, "policy-violation")) == 2, json.dumps(crit(rep, "C-RTC-2")["metrics"]))

# --- S21 lease violation -------------------------------------------------------------------------------------------------------------
ls = S.Dongle(hours=48)
l0 = ls.at_bst(1, 14, 0, 0)
ls.put("free_power_active", l0, "on")
ls.put("free_power_active", l0 + timedelta(hours=1), "off")
ls.bump("fp_start_attempts", l0)
ls.set_offset(ls.at_bst(1, 14, 8), -40)
ls.correction(ls.at_bst(1, 14, 10), "background")
ls.set_offset(ls.at_bst(1, 14, 38), -400)
ls.correction(ls.at_bst(1, 14, 40), "large", residual=-2)
ls.run()
rep = analyse(ls)
v = verdicts(rep)
check("lease: a background correction during Free Power is a lease violation; C-SAFE-2 FAIL and C-RTC-2 FAIL",
      v["C-SAFE-2"] == "FAIL" and v["C-RTC-2"] == "FAIL" and crit(rep, "C-SAFE-2")["metrics"]["lease_violations"] == 1)
check("lease: the large (-400 s) correction inside the same lease is exempt (no lease-hold check for large errors)",
      not any(c["check"] == "lease-hold" for c in next(e for e in episodes(rep) if e["reason"] == "large")["analysis"]["policy"]["checks"]))
check("lease: the Free Power start is reported as a write operation needing attribution",
      any(e["code"] == "write-operation" for e in rep["suspicious_events"]))

# --- S22 empty evidence -----------------------------------------------------------------------------------------------------------------
rep = run(Evidence(), now=S.START + timedelta(days=8))
v = verdicts(rep)
check("empty evidence: every required criterion INSUFFICIENT, none PASS, overall INSUFFICIENT",
      all(v[c["id"]] == "INSUFFICIENT_EVIDENCE" for c in rep["criteria"] if c["required"])
      and rep["overall"]["verdict"] == "INSUFFICIENT_EVIDENCE", json.dumps(v))

# --- S23 a window across the BST -> GMT change ---------------------------------------------------------------------------------------
gs = datetime(2026, 10, 22, 22, 0, tzinfo=UTC)  # 23:00 BST
gm = S.Dongle(start=gs, hours=168).run()
rep = analyse(gm, start=gs)
check("BST->GMT window: soak days stay 24 h; D4 starts 2026-10-25 22:00:00 GMT",
      rep["daily"][3]["from"]["local"] == "2026-10-25 22:00:00 GMT" and rep["daily"][0]["from"]["local"] == "2026-10-22 23:00:00 BST")
check("BST->GMT window: the repeated 01:00-02:00 hour causes no clock discontinuity and no Block B gap",
      not rep["areas"]["continuity"]["clock"]["discontinuities"] and not rep["areas"]["polling"]["block_b"]["gaps"]
      and verdicts(rep)["C-CONT-4"] == "PASS", json.dumps(rep["areas"]["continuity"]["clock"]))

# =============================================================================================================================
print("[5] cross-format consistency, CLI and outputs")
cf = S.Dongle(hours=48)
cf.set_offset(cf.at_bst(1, 14, 0), -45)
cf.correction(cf.at_bst(1, 14, 5), "background")
cf.stale_read(cf.at_bst(1, 23, 26), -60)
cf.stale_read(cf.at_bst(1, 23, 27), -60)
cf.correction(cf.at_bst(1, 23, 27), "background")
cf.run()
reps = {f: analyse(cf, fmt=f) for f in ("rest", "rest-full", "ws", "csv")}
sig = {f: (verdicts(r), [(e["reason"], e["error_s"], e["analysis"].get("classification")) for e in episodes(r)],
           r["areas"]["b10"]["time_s"]) for f, r in reps.items()}
check("REST minimal / REST full / websocket / long CSV give identical verdicts, episodes and B10 times",
      all(sig[f] == sig["rest"] for f in sig), json.dumps({f: s[1] for f, s in sig.items()}))
with tempfile.TemporaryDirectory() as td:
    hp = Path(td) / "history.json"
    hp.write_text(json.dumps(cf.ha_history()), encoding="utf-8")
    lp = Path(td) / "dongle.log"
    lp.write_text("[23:26:20][W][ecco:21160]: RTC STALL detected - inverter advanced 0 s while NTP advanced 60 s\n", encoding="utf-8")
    out = Path(td) / "out"
    rc = CLI.main([str(hp), f"{lp}@2026-10-05", "--out", str(out), "--days", "2", "--as-of", "2026-10-08T00:00:00Z"])
    files = sorted(x.name for x in out.iterdir())
    js = json.loads((out / "fbd1_soak_analysis.json").read_text(encoding="utf-8"))
    check("CLI: exit 0, four output files, the JSON names both inputs", rc == 0 and files == [
        "fbd1_soak_analysis.json", "fbd1_soak_daily.csv", "fbd1_soak_events.csv", "fbd1_soak_report.md"]
        and [Path(i["path"]).name for i in js["evidence"]["inputs"]] == ["history.json", "dongle.log"], f"{rc} {files}")
    check("CLI: the clock-only log anchored with @2026-10-05 lands on the stall read (log stall line attached)",
          any("log" in (x.get("detector_basis") or "") for x in js["areas"]["rtc"]["stalls"]["events"]))
    rc2 = CLI.main([str(hp), "--out", str(out), "--days", "2", "--as-of", "2026-10-08T00:00:00Z", "--verdict-exit-code"])
    check("CLI: --verdict-exit-code maps the verdict (WARNING -> 10)", rc2 == CLI.EXIT[js["overall"]["verdict"]] == 10, f"{rc2}")
    rules_p = Path(td) / "rules.json"
    rules_p.write_text(json.dumps({"b10_match_pass": 1.01}), encoding="utf-8")
    CLI.main([str(hp), "--out", str(out), "--days", "2", "--as-of", "2026-10-08T00:00:00Z", "--rules", str(rules_p)])
    js2 = json.loads((out / "fbd1_soak_analysis.json").read_text(encoding="utf-8"))
    check("CLI: --rules overrides a threshold and the report records it", js2["rules"]["b10_match_pass"] == 1.01
          and next(c for c in js2["criteria"] if c["id"] == "C-B10-1")["verdict"] == "WARNING")
    rc3 = CLI.main([str(Path(td) / "missing.json"), "--out", str(out)])
    check("CLI: a missing input exits 2", rc3 == 2)

# =============================================================================================================================
print("[6] the FB-D1 harness: real firmware lambdas, two-freeze stale-read replay")
try:
    sys.path.insert(0, str(ROOT / "registry" / "tests"))
    import _fbd1_harness as X  # noqa: E402
    sim = X.make_rig(None, local=(2026, 10, 5, 0, 1, 0), offset_s=-10.0, intervals=("rtc_read", "rtc_tick"))
    sim.pub_timed |= {"clock_difference", "rtc_stall_detected", "inverter_clock", "last_correction_result", "last_correction"}
    # find the phase of the 60 s regular read from the firmware itself, then freeze the register image 50 s before two
    # consecutive reads: each shows a 50 s old image, so both read about -60 s while the true error stays -10 s
    t_begin = sim.now_ms
    sim.run_for(45_000)
    first = next(t for t, name, _ in sim.pub_times if name == "clock_difference")
    r1 = first + 6 * 60_000
    r2 = r1 + 60_000
    sim.rtc.freeze(r1 - 50_000, r1 + 5_000)
    sim.rtc.freeze(r2 - 50_000, r2 + 5_000)
    sim.run_for(12 * 60_000)
    ids = {"clock_difference": "sensor.ecco_clock_dongle_clock_difference", "inverter_clock": "sensor.ecco_clock_dongle_inverter_time",
           "rtc_stall_detected": "binary_sensor.ecco_clock_dongle_rtc_stall_detected",
           "last_correction_result": "sensor.ecco_clock_dongle_last_correction_result",
           "last_correction": "sensor.ecco_clock_dongle_last_correction"}
    rows = {}
    for t_ms, name, val in sim.pub_times:
        if name not in ids:
            continue
        t = datetime.fromtimestamp(sim.clock.utc_ms(t_ms) / 1000, tz=UTC)
        st = {"True": "on", "False": "off"}.get(val, val)
        lst = rows.setdefault(ids[name], [])
        if not lst or lst[-1][1] != st:
            lst.append((t, st))
    hist = [[{"entity_id": e, "state": s, "last_changed": t.isoformat()} for t, s in lst] for e, lst in rows.items()]
    w0 = datetime.fromtimestamp(sim.clock.utc_ms(t_begin) / 1000, tz=UTC)
    ev_h = Evidence()
    ingest.load_object(hist, ev_h)
    rep = run(ev_h, start=w0, end=w0 + timedelta(minutes=13), now=w0 + timedelta(days=1))
    eps = episodes(rep)
    writes = sim.rtc_write_attempts()
    check("harness: the real firmware queued exactly one correction on the two frozen reads (the documented false confirmation)",
          len(writes) == 1 and len(eps) == 1, f"writes={len(writes)} episodes={len(eps)}")
    a = eps[0]["analysis"] if eps else {}
    check("harness: the analyser reads the firmware's own publications as a background -60 s correction confirmed by -60/-60",
          eps and eps[0]["reason"] == "background" and eps[0]["error_s"] == -60 and a["prior_read"]["error_s"] == -60
          and a["queue_read"]["error_s"] == -60, json.dumps(eps[0] if eps else {})[:500])
    check("harness: ... with the stall detector's own publication on the first read -> stale_first_read_candidate, suspected no-op",
          a.get("classification") == "stale_first_read_candidate" and a.get("stall_on_prior_read") and a.get("suspected_noop")
          and a["prior_read"]["stall_detector"] is True, json.dumps(a)[:500])
    check("harness: the firmware's verified residual is what the analyser reports",
          eps and eps[0]["outcome"] == "verified" and eps[0]["residual_s"] is not None and abs(eps[0]["residual_s"]) <= 2,
          json.dumps(eps[0] if eps else {})[:300])
except ImportError as exc:  # pragma: no cover - the harness needs PyYAML, which every validation job installs
    check("the FB-D1 harness is importable (PyYAML installed)", False, str(exc))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED")
    sys.exit(1)
print("all checks passed")
