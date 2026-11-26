#!/usr/bin/env python3
"""L2 scenarios of the Ghost diagnostics block (the BUILT kit under the stand-in Home Assistant, SYNTHETIC data, fictional 2030).

NOT a suite on its own (the leading underscore keeps the runner from listing it): it runs inside a WIRED tree, one that has
tests/ghost_diag_wiring.patch applied (test_runtime_ghost_diag.py builds that overlay and runs this file in it). In the live tree,
where the wiring is not applied, the diagnostics have no `ghost` block and this file fails at its first check: that is the
fail-first evidence.

Scenarios: the download carries the block (money with a verified tariff over the covered days; NO MONEY without one;
INSUFFICIENT_HISTORY naming the hourly fields no hour carries; NO_ADVICE_LOGGED; advice followed and not followed with the
reasons; SITE_CONFIG_NOT_DECIDED; NO_CYCLE_YET); the feed raising leaves a small ERROR block and the rest of the download byte-
identical; the block's size bound; nothing leaks (entity ids, coordinates, an exception message, advice ids); nothing is written,
no service is called, the eleven entities are exactly the contract's; the time budget and the one-job-at-a-time rule; the
placeholder charge window does not matter; the block is computed on request only (a cycle's work and result are unchanged);
timing on a 30-day recorder table; an import-time fault of the Ghost code only affects the download; the last cycle's job is kept
only after a published result.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
NOW = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
PREFIX = "ecco_intel_ghost_diag_"
CHG_ID, DIS_ID = H.eid("sensor", "total_battery_charge"), H.eid("sensor", "total_battery_discharge")
LATITUDE, LONGITUDE = 51.123456, -1.654321                 # fictional; the fake HA's own config carries them
root = H.mktemp(PREFIX)
b = H.build_kit(root / "kit")
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(root / "kit")
C = h.contract
DIAG = importlib.import_module("custom_components.ecco_intelligence.diagnostics")
LINK = importlib.import_module("custom_components.ecco_intelligence.runtime.ghost_link")
COORD = importlib.import_module("custom_components.ecco_intelligence.coordinator")
VEN_SC = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.scorecard")
VEN_GC = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.ghost_compare")
VEN_GF = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.ghost_feed")


def ghost_statistics(now: datetime, days: int = 30, with_battery: bool = True) -> dict[str, list[dict]]:
    """Hourly statistics of a synthetic house with a 20 kWh battery that charges to 80 % in the cheap hours 01:00-04:59 and
    otherwise self-uses down to 25 %; the six energy counters (cumulative), the powers and the SOC, ending at the last complete
    hour before `now`. With with_battery=False the two battery counters are not produced (a site file that maps none)."""
    end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    cap, eta, soc = 20.0, 0.96, 70.0
    cum = dict.fromkeys(("load", "pv", "imp", "exp", "chg", "dis"), 0.0)
    ids = {"load": H.SOURCE_ENTITIES["load_energy"], "pv": H.SOURCE_ENTITIES["pv_energy"], "imp": H.SOURCE_ENTITIES["imp_energy"],
           "exp": H.SOURCE_ENTITIES["exp_energy"], "chg": CHG_ID, "dis": DIS_ID}
    out: dict[str, list[dict]] = {v: [] for v in H.SOURCE_ENTITIES.values()}
    out.update({CHG_ID: [], DIS_ID: []})
    empty = {"mean": None, "min": None, "max": None, "state": None, "sum": None}
    for k in range(days * 24, 0, -1):
        start = end - timedelta(hours=k)
        hr = start.hour
        load = 0.4 + (0.9 if 17 <= hr <= 21 else 0.0) + 0.05 * ((start.day * 7 + hr) % 5)
        pv = max(0.0, 1.6 - abs(hr - 12) * 0.3) if 8 <= hr <= 16 else 0.0
        stored = soc / 100.0 * cap
        chg = dis = 0.0
        if 1 <= hr < 5 and soc < 80.0:
            chg = min(3.0, (0.8 * cap - stored) / eta)
        elif pv > load:
            chg = min(pv - load, (cap - stored) / eta)
        else:
            dis = min(load - pv, max(0.0, stored - 0.25 * cap) * eta)
        new = stored + chg * eta - dis / eta
        grid = load + chg - pv - dis
        imp, exp = max(0.0, grid), max(0.0, -grid)
        soc_end = new / cap * 100.0
        soc_mean = (soc + soc_end) / 2.0
        soc = soc_end
        for f, v in zip(("load", "pv", "imp", "exp", "chg", "dis"), (load, pv, imp, exp, chg, dis)):
            cum[f] += v
        ts = start.timestamp()
        rows = {ids[f]: {"state": round(cum[f], 4)} for f in cum if with_battery or f not in ("chg", "dis")}
        rows.update({H.SOURCE_ENTITIES["load_power"]: {"mean": load * 1000, "min": load * 900, "max": load * 1100},
                     H.SOURCE_ENTITIES["pv_power"]: {"mean": pv * 1000, "min": 0.0, "max": pv * 1200},
                     H.SOURCE_ENTITIES["batt_power"]: {"mean": (dis - chg) * 1000, "min": -3000.0, "max": 3000.0},
                     H.SOURCE_ENTITIES["soc"]: {"mean": soc_mean, "min": soc_mean - 1, "max": soc_mean + 1}})
        for sid, r in rows.items():
            out[sid].append({**empty, "start": ts, **r})
    return out


def rates(now: datetime, back_days: int = 4) -> list[dict]:
    """Half-hour import rates in the integration's form, from `back_days` days before now's date to the end of tomorrow:
    0.075 in 01:00-04:29 UTC, 0.30 otherwise (fictional GBP/kWh)."""
    first = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=back_days)
    end = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=2)
    rows, t = [], first
    while t < end:
        m = t.hour * 60 + t.minute
        rows.append({"start": t.isoformat(), "end": (t + timedelta(minutes=30)).isoformat(),
                     "value_inc_vat": 0.075 if 60 <= m < 270 else 0.30})
        t += timedelta(minutes=30)
    return rows


def advice_payload(issued: datetime, target: float, status: str = "OK", window: tuple | None = None, reserve: float = 30.0) -> dict:
    """What coordinator publishes for a charge target, in the shape Scorecard.record_advice reads."""
    w = window or (issued + timedelta(hours=2), issued + timedelta(hours=6))
    rec = {"kind": "charge_target", "status": status, "generated_at": issued.isoformat(),
           "valid_until": (issued + timedelta(minutes=10)).isoformat(), "reason_codes": []}
    unrec = {"advice": {"target_soc_pct": target, "effective_reserve_pct": reserve, "conservative_fallback": status != "OK",
                        "window": [w[0].isoformat(), w[1].isoformat()]}}
    return {"sensor.x": (status, rec, unrec)}


def log_advice(cfg_dir: Path, rows: list[tuple]) -> None:
    """Write rows (issued, target, status) into the scenario's scorecard, as the slot cycle's store step does."""
    sc = VEN_SC.Scorecard(str(cfg_dir / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"))
    try:
        for issued, target, status in rows:
            sc.record_advice(advice_payload(issued, target, status))
        check("the test's advice rows were written", sc.advice_write_failures == 0)
    finally:
        sc.db.close()


def nights(first_back: int, last_back: int, target: float, status: str = "OK") -> list[tuple]:
    """One charge-target advice per night, issued 23:00 the evening before, for the nights `first_back`..`last_back` days before
    now's date (window 01:00-05:00)."""
    out = []
    for back in range(first_back, last_back - 1, -1):
        day = datetime(NOW.year, NOW.month, NOW.day, tzinfo=UTC) - timedelta(days=back)
        out.append((day - timedelta(hours=1), target, status))
    return out


class Scenario:
    def __init__(self, name: str, *, stats: dict | None = None, money: bool = True, decisions: dict | None = None,
                 cycles: int = 3, advice: list[tuple] | None = None, with_battery_map: bool = True) -> None:
        self.cfg = root / name
        self.cfg.mkdir()
        self.hass = h.new_hass(self.cfg, NOW)
        self.hass.states.events = False
        prof = H.site_profile(decisions=decisions if decisions is not None else H.owner_decisions())
        if with_battery_map:
            ents = prof["sources"][0]["entities"]
            ents["chg_energy"], ents["dis_energy"] = {"id": CHG_ID}, {"id": DIS_ID}
        H.write_site(self.cfg, prof)
        self.money = money
        self.seed(NOW)
        h.recorder().statistics = stats if stats is not None else ghost_statistics(NOW)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = 120.0
        self.c.refresh_enabled = False
        if advice:
            log_advice(self.cfg, advice)
        for _ in range(cycles):
            h.set_now(h.now + timedelta(seconds=60))
            self.seed(h.now)
            h.tick(0, settle=20.0)

    def seed(self, now: datetime) -> None:
        H.seed_fresh_states(self.hass.states, now)
        if self.money:
            self.hass.states.seed("event.test_your_import_rates", now.isoformat(), {"rates": rates(now)},
                                  changed_at=now - timedelta(minutes=5))
        else:
            self.hass.states.seed("event.test_your_import_rates", now.isoformat(), {}, changed_at=now - timedelta(minutes=5))

    def download(self) -> dict:
        return h.run(DIAG.async_get_config_entry_diagnostics(self.hass, self.entry), timeout=120.0)

    def close(self) -> None:
        h.unload(self.entry)


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:  # noqa: BLE001 - the test asks only whether it raised
        return True
    return False


def walk(o):
    """Every (path, leaf) of a JSON structure."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from ((f"{k}.{p}", x) for p, x in walk(v))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from ((f"[{i}].{p}", x) for p, x in walk(v))
    else:
        yield "", o


def money_keys(o) -> list[str]:
    return [p for p, _ in walk(o) if re.search(r"(^|\.|_)p(\.|$|_)", p)]


try:
    print("== no cycle yet: the block says so, the download is intact")
    cfg0 = root / "nocycle"
    cfg0.mkdir()
    hass0 = h.new_hass(cfg0, NOW)
    hass0.states.events = False
    H.write_site(cfg0, H.site_profile(decisions=H.owner_decisions()))
    H.seed_fresh_states(hass0.states, NOW)
    h.recorder().statistics = ghost_statistics(NOW)
    e0 = h.new_entry()
    h.setup(e0)
    dl0 = h.run(DIAG.async_get_config_entry_diagnostics(hass0, e0), timeout=60.0)
    check("before the first cycle: ghost block UNAVAILABLE / NO_CYCLE_YET, no figure",
          dl0.get("ghost", {}).get("status") == "UNAVAILABLE" and dl0["ghost"]["reason"] == "NO_CYCLE_YET"
          and dl0["ghost"]["money_available"] is False and "totals" not in dl0["ghost"], str(dl0.get("ghost")))
    check("... and the rest of the download is there", dl0.get("loaded") is True and "self_test" in dl0 and "counters" in dl0)
    h.unload(e0)

    print("== S1 money: a verified tariff over the covered days, advice logged, a normal download")
    s1 = Scenario("money", advice=nights(9, 1, 80.0) + nights(3, 3, 55.0))
    check("non-vacuity: a cycle ran and published the eleven contract entities",
          s1.c.counters["runs_published"] >= 1 and len([e for e in s1.hass.states._states if e.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel"))])
          == len(C.INTEGRATION_ENTITY_KEYS), str(s1.c.counters["runs_published"]))
    before_states = {e: (st.state, json.dumps(dict(st.attributes), sort_keys=True, default=str)) for e, st in s1.hass.states._states.items()}
    t0 = time.perf_counter()
    dl1 = s1.download()
    dl_s = time.perf_counter() - t0
    g = dl1.get("ghost")
    check("the download has a ghost block (schema, simulated, read-only, nothing controlled)",
          isinstance(g, dict) and g.get("schema") == "ecco-intel-ghost-diagnostics/1" and g.get("simulated") is True
          and g.get("read_only") is True and g.get("intelligence_controlled_nothing") is True and "SIMULATION" in g.get("banner", ""),
          str(g)[:300])
    check("status OK with money from the verified tariff (VERIFIED_FROM_INTEGRATION); the tariff covers only the days it covers",
          g["status"] == "OK" and g["money_available"] is True and g["tariff"]["import"] == "VERIFIED_FROM_INTEGRATION"
          and 24 <= g["period"]["hours"] <= 5 * 24 + 24, str(g["period"]))
    check("the export tariff is NOT_VERIFIED here (the seeded export rates cover only one day) and the import one is judged on its own table",
          g["tariff"]["export"] == "NOT_VERIFIED" and any("EXPORT_TARIFF_NOT_VERIFIED" in n for n in g["data_quality"]["notes"]),
          str(g["tariff"]))
    check("it names the cycle's time the inputs are as of", g["inputs_as_of"] == s1.c._ghost_job.now.isoformat())
    t = g["totals"]
    need = ("existing_net_p", "advice_net_p", "advice_effect_p", "existing_min_soc_pct", "advice_min_soc_pct", "end_soc_diff_pct")
    check("money, SOC, reserve and uncertainty are all there, per period and per day",
          all(k in t for k in need) and {"in_force_pct", "existing_margin_pct", "advice_margin_pct", "advice_would_breach", "verdict"} <= set(g["reserve"])
          and {"noise_p", "components_p", "verdict", "effect_at_efficiency_p"} <= set(g["uncertainty"])
          and g["days"] and all({"existing_net_p", "advice_net_p", "noise_p", "verdict", "existing_end_soc_pct", "advice_end_soc_pct",
                                 "advice_reserve_margin_pct"} <= set(d) for d in g["days"]), str(g["days"][0]))
    check("advice was followed in the simulation and nothing was a reserve breach on this house",
          g["advice"]["followed"] >= 3 and g["reserve"]["advice_would_breach"] is False and g["reserve"]["verdict"] == "NO_BREACH",
          str(g["advice"]) + str(g["reserve"]))
    check("the uncertainty verdict is one of the constants and never claims a win inside the noise",
          g["uncertainty"]["verdict"] in VEN_GC.VERDICTS and (abs(g["uncertainty"]["advice_effect_p"]) > g["uncertainty"]["noise_p"]
                                                            or g["uncertainty"]["verdict"] in ("WITHIN_NOISE", "NO_ADVICE_EFFECT")),
          str(g["uncertainty"]["verdict"]))
    size = len(json.dumps(g, sort_keys=True, separators=(",", ":")).encode())
    check(f"the block is bounded ({size} bytes <= {VEN_GC.MAX_BYTES})", size <= VEN_GC.MAX_BYTES)
    after_states = {e: (st.state, json.dumps(dict(st.attributes), sort_keys=True, default=str)) for e, st in s1.hass.states._states.items()}
    check("the download changed no state and no attribute in the state machine", before_states == after_states)
    check("nothing was written and no stand-in rule was broken (no service call, no state or bus write, no recorder write)",
          not s1.hass.violations and not s1.hass.write_attempts, str(s1.hass.violations[:2]) + str(s1.hass.write_attempts[:2]))
    check("the eleven contract entities are exactly the integration's (no twelfth entity, none renamed)",
          sorted(e for e in s1.hass.states._states if e.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel")))
          == sorted(C.ENTITY_IDS[k] for k in C.INTEGRATION_ENTITY_KEYS) and len(C.INTEGRATION_ENTITY_KEYS) == 11
          and C.CONTRACT_VERSION == "ecco-intel-entities/1")
    print(f"  INFO  the whole download with the Ghost block took {dl_s:.2f} s; history rows "
          f"{sum(len(v) for v in h.recorder().statistics.values())}")

    print("== S1a the report tool reads this very download")
    dl_file = root / "download.json"
    dl_file.write_text(json.dumps({"home_assistant": {"version": "2030.1.0"}, "data": dl1}, default=str), encoding="utf-8")
    rp = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(H.REPO / "intelligence" / "tools" / "ghost_diag_report.py"), str(dl_file)],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    check("the plain-text report of the real download: exit 0, the simulation banner, both sides, the money, the SOC, the reserve, the "
          "uncertainty verdict, nothing on stderr",
          rp.returncode == 0 and rp.stderr == "" and all(w in rp.stdout for w in ("SIMULATION", "EXISTING SCHEDULE", "INTELLIGENCE ADVICE",
                                                                             "Money (pence", "SOC %", "RESERVE", "VERDICT", "Limits:")),
          (rp.stdout + rp.stderr)[-400:])
    print("  INFO  the report of this download (first lines):")
    for ln in rp.stdout.splitlines()[:14]:
        print("        " + ln)

    print("== S1b the rest of the download is unchanged by the block")
    keys_plain = {"loaded"} | set(s1.c.diagnostics())
    check("the download's keys are exactly the coordinator's diagnostics plus ghost (nothing else added or removed)",
          set(dl1) == keys_plain | {"ghost"}, str(set(dl1) ^ (keys_plain | {"ghost"})))

    print("== S1c redaction: nothing from the site, the entities or the advice reaches the block")
    text = json.dumps(g)
    ents = set(re.findall(r"\b(?:sensor|binary_sensor|input_number|input_boolean|event|number|switch|select)\.[a-z0-9_]+", text))
    check("no entity id appears in the block", not ents, str(sorted(ents)[:3]))
    site_ids = set(H.SOURCE_ENTITIES.values()) | {CHG_ID, DIS_ID, "sensor.x"}
    check("none of the site's statistic ids, the test slug, the test advice entity or an advice_id appears",
          not any(i in text for i in site_ids) and "test_dongle" not in text and "advice_log" not in text, "")
    check("no coordinates", str(LATITUDE)[:6] not in text and str(abs(LONGITUDE))[:6] not in text)
    check("no time zone name or other site setting (only numbers, dates and constant words)", "Europe/London" not in text
          and "config_hash" not in text and "git_sha" not in text and "latitude" not in text)
    leaves = [x for _p, x in walk(g) if isinstance(x, str)]
    ok_re = re.compile(r"^[A-Za-z0-9 _:.,;()/+%'=<>&\-]+$")
    check("every string in the block is plain constant text or a date / time (a fixed character set, nothing free-form)",
          all(ok_re.match(x) for x in leaves), str([x for x in leaves if not ok_re.match(x)][:3]))
    s1.close()

    print("== S2 no verified tariff: NO MONEY, behaviour only")
    s2 = Scenario("nomoney", money=False, advice=nights(9, 1, 80.0))
    g2 = s2.download()["ghost"]
    check("status OK, money_available False, tariff NOT_VERIFIED", g2["status"] == "OK" and g2["money_available"] is False
          and g2["tariff"]["import"] == "NOT_VERIFIED", str(g2.get("tariff")))
    check("no pence figure anywhere in the block (not in totals, uncertainty, days) and the verdict says not assessed",
          money_keys(g2) == [] and g2["uncertainty"]["verdict"] == "NOT_ASSESSED_NO_MONEY"
          and all(d["verdict"] if "verdict" in d else True for d in g2["days"]) and "noise_p" not in g2["uncertainty"], str(money_keys(g2)[:5]))
    check("the behaviour comparison is still there (SOC both runs, reserve margin, advice followed)",
          all(k in g2["days"][0] for k in ("existing_min_soc_pct", "advice_min_soc_pct", "existing_end_soc_pct", "advice_end_soc_pct",
                                          "advice_reserve_margin_pct")) and g2["advice"]["followed"] >= 1)
    check("it says why: NO_VERIFIED_TARIFF in the notes", any("NO_VERIFIED_TARIFF" in n for n in g2["data_quality"]["notes"]),
          str(g2["data_quality"]["notes"]))
    s2.close()

    print("== S3 insufficient history: a site file that maps no battery counters")
    s3 = Scenario("nohist", stats=ghost_statistics(NOW, with_battery=False), with_battery_map=False, advice=nights(5, 1, 80.0))
    g3 = s3.download()["ghost"]
    check("INSUFFICIENT_HISTORY with a constant reason and the hourly fields no hour carries (chg, dis)",
          g3["status"] == "INSUFFICIENT_HISTORY" and g3["reason"] == "NO_24H_RUN_OF_USABLE_HOURS"
          and g3["history_fields_absent"] == ["chg", "dis"] and g3["money_available"] is False, str(g3))
    check("the small block carries no comparison figure", not ({"totals", "days", "reserve", "uncertainty"} & set(g3)))
    s3.close()

    print("== S4 an empty or unreadable advice log")
    s4 = Scenario("noadvice", cycles=2)
    j4 = dataclasses.replace(s4.c._ghost_job, statistics=s4.c._hist["stats"])

    class FakeStore:
        def __init__(self, rows=None, error=None):
            self.rows, self.error = rows, error

        def advice_rows(self, start, end):
            if self.error is not None:
                raise self.error
            return list(self.rows)
    g4 = LINK.ghost_block(j4, FakeStore([]))
    check("an empty log: NO_ADVICE_LOGGED with a constant reason, the period, and no comparison figure",
          g4["status"] == "NO_ADVICE_LOGGED" and g4["reason"] == "NO_ADVICE_IN_PERIOD" and g4["period"]["hours"] >= 24
          and not ({"totals", "days", "reserve", "uncertainty"} & set(g4)), str(g4)[:300])
    g4b = LINK.ghost_block(j4, FakeStore(error=OSError("disk gone sensor.test_secret_entity")))
    check("an unreadable log is not an empty one: UNAVAILABLE / ADVICE_LOG_UNREADABLE and the message is not kept",
          g4b["status"] == "UNAVAILABLE" and g4b["reason"] == "ADVICE_LOG_UNREADABLE" and "test_secret_entity" not in json.dumps(g4b), str(g4b))
    g4e = LINK.ghost_block(dataclasses.replace(j4, states=None), FakeStore([]))
    check("an exception inside the job itself (broken inputs): ERROR / FEED_EXCEPTION with the class name, never raised",
          g4e["status"] == "ERROR" and g4e["reason"] == "FEED_EXCEPTION" and g4e["error_type"] and "totals" not in g4e, str(g4e))
    g4c = LINK.ghost_block(None, FakeStore([]))
    check("no job at all: UNAVAILABLE / NO_CYCLE_YET", g4c["reason"] == "NO_CYCLE_YET")
    g4d = LINK.ghost_block(dataclasses.replace(j4, statistics=None), FakeStore([]))
    check("no statistics at all: UNAVAILABLE / NO_STATISTICS_READ", g4d["reason"] == "NO_STATISTICS_READ", str(g4d))
    s4.close()

    print("== S5 advice followed and not followed, with the reasons")
    adv5 = nights(3, 3, 80.0) + nights(2, 2, 80.0, "BLOCKED") + nights(1, 1, 70.0, "INSUFFICIENT_DATA")
    s5 = Scenario("mixed", advice=adv5)
    g5 = s5.download()["ghost"]
    nf = g5["advice"]["not_followed"]
    check("followed and not followed are counted, with the constant reasons (BLOCKED, FALLBACK_EXCLUDED)",
          g5["status"] == "OK" and g5["advice"]["followed"] >= 1 and nf.get("BLOCKED", 0) >= 1 and nf.get("FALLBACK_EXCLUDED", 0) >= 1,
          str(g5["advice"]))
    check("a day with blocked advice shows it per day", any("advice_not_followed" in d for d in g5["days"]))
    s5.close()

    print("== S6 the feed raises: a small ERROR block, the rest of the download byte-identical, the message never leaks")
    s6 = Scenario("raises", advice=nights(5, 1, 80.0))
    good = s6.download()
    real = VEN_GF.build_ghost_feed

    def boom(*a, **k):
        raise RuntimeError("synthetic ghost failure SECRET-123 sensor.test_secret_entity")
    VEN_GF.build_ghost_feed = boom
    try:
        bad = s6.download()
    finally:
        VEN_GF.build_ghost_feed = real
    check("the block is ERROR / FEED_EXCEPTION with the exception class only",
          bad["ghost"]["status"] == "ERROR" and bad["ghost"]["reason"] == "FEED_EXCEPTION" and bad["ghost"]["error_type"] == "RuntimeError"
          and "totals" not in bad["ghost"], str(bad["ghost"]))
    check("the exception message appears nowhere in the download", "SECRET-123" not in json.dumps(bad, default=str)
          and "test_secret_entity" not in json.dumps(bad["ghost"]))
    keep = lambda d: {k: v for k, v in d.items() if k != "ghost"}  # noqa: E731
    check("every other part of the download is the same as without the failure", keep(good) == keep(bad), str(set(keep(good)) ^ set(keep(bad))))
    check("the cycle's own state is untouched by the failure (no exception counted, the self-test is the same)",
          s6.c.counters["exceptions"] == 0 and good["self_test"] == bad["self_test"])
    # a failure of the whole Ghost path in the coordinator is caught too
    real_m = COORD.EccoIntelCoordinator.async_ghost_diagnostics

    async def raising(self):
        raise OSError("boom")
    COORD.EccoIntelCoordinator.async_ghost_diagnostics = raising
    try:
        bad2 = s6.download()
    finally:
        COORD.EccoIntelCoordinator.async_ghost_diagnostics = real_m
    check("even a failure outside the executor job gives a small block and an intact download",
          bad2["ghost"]["status"] == "UNAVAILABLE" and bad2["ghost"]["reason"] == "OTHER" and bad2["loaded"] is True)
    real_submit = COORD.EccoIntelCoordinator._submit

    def no_submit(self, *a, **k):
        raise RuntimeError("cannot submit sensor.test_secret_entity")
    COORD.EccoIntelCoordinator._submit = no_submit
    try:
        bad3 = s6.download()
    finally:
        COORD.EccoIntelCoordinator._submit = real_submit
    check("a failure before the job is submitted is caught in the coordinator: ERROR with the class only, the busy flag is not left set",
          bad3["ghost"]["status"] == "ERROR" and bad3["ghost"]["error_type"] == "RuntimeError" and "test_secret_entity" not in json.dumps(bad3)
          and s6.c._ghost_busy is False, str(bad3["ghost"]))
    check("the next download computes again", s6.download()["ghost"]["status"] == "OK")
    s6.close()

    print("== S7 decisions not recorded: the battery configuration is not decided")
    s7 = Scenario("open", decisions=H.all_open_decisions(), advice=nights(5, 1, 80.0))
    g7 = s7.download()["ghost"]
    check("UNAVAILABLE / SITE_CONFIG_NOT_DECIDED, no figure", g7["status"] == "UNAVAILABLE" and g7["reason"] == "SITE_CONFIG_NOT_DECIDED"
          and "totals" not in g7, str(g7))
    s7.close()

    print("== S8 the time budget and one job at a time")
    s8 = Scenario("budget", advice=nights(5, 1, 80.0))
    real_blk, gate = LINK.ghost_block, threading.Event()

    def slow(job, store):
        gate.wait(10.0)
        return real_blk(job, store)
    LINK.ghost_block = slow
    real_budget = LINK.PROPOSED_GHOST_BUDGET_S
    LINK.PROPOSED_GHOST_BUDGET_S = 0.3
    try:
        t0 = time.perf_counter()
        a = s8.download()["ghost"]
        waited = time.perf_counter() - t0
        bb = s8.download()["ghost"]                         # the first thread is still running
        gate.set()
        h.run(asyncio.sleep(0.8))
        c = s8.download()["ghost"]
    finally:
        LINK.PROPOSED_GHOST_BUDGET_S = real_budget
        LINK.ghost_block = real_blk
        gate.set()
    check("a job that outlives the budget gives TIME_BUDGET after about the budget, not after the job", a["reason"] == "TIME_BUDGET"
          and waited < 5.0, f"{a} {waited:.2f}")
    check("a request while the job still runs gets BUSY (one at a time)", bb["status"] == "UNAVAILABLE" and bb["reason"] == "BUSY", str(bb))
    check("once the thread has ended the next download computes again", c["status"] == "OK", str(c)[:200])
    s8.close()

    print("== S9 the charge window the engine insists on is a placeholder: the block does not depend on it")
    s9 = Scenario("window", advice=nights(5, 1, 80.0))
    job = s9.c._ghost_job
    stats = s9.c._hist["stats"]
    j0 = dataclasses.replace(job, statistics=stats)
    j1 = dataclasses.replace(job, statistics=stats, base_cfg=dataclasses.replace(job.base_cfg, cheap_window_start_min=13 * 60,
                                                                                 cheap_window_end_min=15 * 60))
    check("the base configurations differ only in the placeholder window", j0.base_cfg != j1.base_cfg)
    r0, r1 = LINK.ghost_block(j0, s9.c.store), LINK.ghost_block(j1, s9.c.store)
    check("the two blocks are identical", r0 == r1 and r0["status"] == "OK", f"{r0['status']} {r1['status']}")
    db = s9.cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    far0, far1 = NOW - timedelta(days=40), NOW + timedelta(days=1)
    rows_ro = s9.c.store.advice_rows(far0, far1)
    sc9 = VEN_SC.Scorecard(str(db))
    rows_sc = sc9.advice_records(far0, far1)
    sc9.db.close()
    check("the store's read-only advice read gives exactly the rows Scorecard.advice_records gives",
          rows_ro and rows_ro == rows_sc, f"{len(rows_ro)} {len(rows_sc)}")
    newest2 = s9.c.store.advice_rows(far0, far1, limit=2)
    check("a row cap keeps the NEWEST rows, oldest first", len(rows_ro) > 2 and newest2 == rows_ro[-2:], f"{len(rows_ro)} {len(newest2)}")
    sc9b = VEN_SC.Scorecard(str(db))
    sc9b.db.close()
    garbage = root / "garbage_store"
    (garbage / "ecco" / "intelligence" / "state").mkdir(parents=True)
    (garbage / "ecco" / "intelligence" / "state" / "scorecard.sqlite3").write_bytes(b"this is not a database" * 50)
    check("an unreadable database RAISES (so the caller can tell it from an empty log)",
          _raises(lambda: s9.c.store.__class__(str(garbage)).advice_rows(far0, far1)))
    check("a missing database gives [] and creates nothing", s9.c.store.__class__(str(root / "elsewhere")).advice_rows(far0, far1) == []
          and not (root / "elsewhere").exists())
    s9.close()

    print("== S10 computed on request only: the cycle is the same with or without a download")
    sA = Scenario("plainA", advice=nights(5, 1, 80.0))
    entA = {e: (st.state, json.dumps(dict(st.attributes), sort_keys=True, default=str)) for e, st in sA.hass.states._states.items()
            if e.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel"))}
    cA, tA = dict(sA.c.counters), dict(sA.c.last_timing)
    sA.download()
    sA.download()
    check("downloads started no cycle and changed no counter", dict(sA.c.counters) == cA, str(set(cA.items()) ^ set(sA.c.counters.items())))
    sA.close()
    print(f"  INFO  cycle timings of the last cycle (s): {tA}")

    print("== S11 timing of the Ghost job on a 30-day recorder table (diagnostics only)")
    s11 = Scenario("timing", advice=nights(12, 1, 80.0))
    j = dataclasses.replace(s11.c._ghost_job, statistics=s11.c._hist["stats"])
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        blk = LINK.ghost_block(j, s11.c.store)
        ts.append(time.perf_counter() - t0)
    check("the job returns OK and finishes in a few seconds even on this machine", blk["status"] == "OK" and max(ts) < 20.0, str(ts))
    print(f"  INFO  ghost_block on the cached 30-day table: {', '.join(f'{x:.2f}' for x in ts)} s; "
          f"pure comparison only: see test_intel_ghost_compare")
    s11.close()

    print("== S12 an import-time fault of the Ghost code only affects the download (G9)")
    s12 = Scenario("importfault", advice=nights(5, 1, 80.0))
    good12 = s12.download()
    check("non-vacuity: the download carries a real block before the fault", good12["ghost"]["status"] == "OK")
    RT = importlib.import_module("custom_components.ecco_intelligence.runtime")
    VX = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence")
    MISSING = object()

    def block_import(parent, attr: str, modname: str):
        """Make `import modname` / `from parent import attr` fail again, as an import-time fault of that module would."""
        saved_mod, saved_attr = sys.modules.get(modname, MISSING), getattr(parent, attr, MISSING)
        sys.modules[modname] = None
        if saved_attr is not MISSING:
            delattr(parent, attr)

        def restore():
            if saved_mod is MISSING:
                sys.modules.pop(modname, None)
            else:
                sys.modules[modname] = saved_mod
            if saved_attr is not MISSING:
                setattr(parent, attr, saved_attr)
        return restore
    keep12 = lambda d: {k: v for k, v in d.items() if k != "ghost"}  # noqa: E731
    for label, parent, attr, modname in (("runtime/ghost_link", RT, "ghost_link", "custom_components.ecco_intelligence.runtime.ghost_link"),
                                         ("intelligence.ghost_compare", VX, "ghost_compare",
                                          "custom_components.ecco_intelligence._vendor.intelligence.ghost_compare")):
        restore = block_import(parent, attr, modname)
        try:
            bad12 = s12.download()
        finally:
            restore()
        gb = bad12.get("ghost", {})
        check(f"{label} cannot be imported: the download still comes, the Ghost block is a small ERROR / UNAVAILABLE block with a class name only",
              bad12.get("loaded") is True and gb.get("status") in ("ERROR", "UNAVAILABLE") and "totals" not in gb
              and gb.get("money_available") is False and (gb.get("error_type") in (None, "ImportError", "ModuleNotFoundError")), str(gb))
        check(f"... and every other part of the download is the same as without the fault ({label})", keep12(bad12) == keep12(good12),
              str(set(keep12(bad12)) ^ set(keep12(good12))))
        check(f"... and the cycle's own state is untouched ({label})", s12.c.counters["exceptions"] == 0 and s12.c._ghost_busy is False)
    check("once the import works again the next download computes the block", s12.download()["ghost"]["status"] == "OK")
    mk_fb = getattr(importlib.import_module("custom_components.ecco_intelligence.coordinator"), "_ghost_fallback", None)
    fb = mk_fb("FEED_EXCEPTION", "ImportError") if mk_fb else {}
    ref = VEN_GC.small_block("ERROR", "FEED_EXCEPTION", error_type="ImportError")
    check("the hand-built fallback block (made without importing any Ghost code) is the same schema, flags and reason vocabulary as the real small block",
          fb.get("schema") == ref["schema"] == VEN_GC.SCHEMA and fb.get("status") == ref["status"] and fb.get("reason") == ref["reason"] in VEN_GC.REASONS
          and all(fb.get(k) == ref[k] for k in ("simulated", "read_only", "intelligence_controlled_nothing", "money_available")) and set(fb) <= set(ref),
          f"{fb} {ref}")
    s12.close()

    print("== S13 the last cycle's job is kept for the Ghost only once its result is published (G10)")
    s13 = Scenario("jobafterpublish", cycles=0, advice=nights(5, 1, 80.0))
    s13.c._run_cycle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic engine failure"))
    for _ in range(4):
        h.set_now(h.now + timedelta(seconds=60))
        s13.seed(h.now)
        h.tick(0, settle=20.0)
    check("non-vacuity: a cycle ran and its engine failed (an exception counted, nothing published)",
          s13.c.counters["exceptions"] >= 1 and s13.c.counters["runs_published"] == 0, str(s13.c.counters))
    check("a cycle whose engine failed leaves NO job for the Ghost (it is kept only after a published result)", s13.c._ghost_job is None)
    check("... so the download says NO_CYCLE_YET", s13.download()["ghost"].get("reason") == "NO_CYCLE_YET")
    s13.c._run_cycle = None                                     # the engine works again; refreshes are off here, so the next SLOT cycle runs
    for step in range(4):
        h.set_now(datetime(2030, 1, 15, 21, 1, tzinfo=UTC) + timedelta(seconds=60 * step))
        s13.seed(h.now)
        h.tick(0, settle=20.0)
    check("after a published result the job is the published cycle's (its time, no rows)", s13.c.counters["runs_published"] >= 1
          and s13.c._ghost_job is not None and s13.c._ghost_job.statistics is None, str(s13.c.counters))
    s13.close()

    print("== S14 an advice_log table of another shape: the block says so, the download is intact (G1, reading)")
    s14 = Scenario("oddtable", advice=nights(5, 1, 80.0))
    good14 = s14.download()
    dbp = s14.cfg / "ecco" / "intelligence" / "state" / "scorecard.sqlite3"
    import sqlite3
    con14 = sqlite3.connect(str(dbp))
    con14.execute("DROP TABLE advice_log")
    con14.execute("CREATE TABLE advice_log (foo TEXT, bar INTEGER)")
    con14.commit()
    con14.close()
    odd14 = s14.download()
    check("non-vacuity: with the proper table the block was a real comparison", good14["ghost"]["status"] == "OK")
    check("with a table of another shape the block is UNAVAILABLE / ADVICE_LOG_UNREADABLE (an unreadable log is not an empty one), no figure, "
          "nothing raised", odd14["ghost"]["status"] == "UNAVAILABLE" and odd14["ghost"]["reason"] == "ADVICE_LOG_UNREADABLE"
          and "totals" not in odd14["ghost"], str(odd14["ghost"])[:300])
    check("... and every other part of the download is the same", {k: v for k, v in odd14.items() if k != "ghost"} ==
          {k: v for k, v in good14.items() if k != "ghost"})
    s14.close()
finally:
    h.loop.close()
    H.rmtree_own(root, PREFIX)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the Ghost diagnostics L2 scenarios:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all Ghost diagnostics L2 checks passed")
