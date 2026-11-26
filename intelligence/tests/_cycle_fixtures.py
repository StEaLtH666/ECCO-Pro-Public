"""Shared SHADOW-cycle input builder (tests only): a complete, fresh, consistent CycleInputs covering every SITE_READING_KEYS
entry, in the fictional year 2030. Every value is synthetic; none is site data or an owner decision.

    cycle_inputs()                                  all decisions OPEN, default acceptance (OWNER_RECORD only)
    cycle_inputs(synthetic_recorded=True)           every gating decision RECORDED with SYNTHETIC_TEST provenance, and
                                                    accept_provenance={SYNTHETIC_TEST} passed explicitly
    cycle_inputs(paused=True | False | None)        None = the pause control is missing
    cycle_inputs(stale_liveness=True)               the dongle poll text last changed 2 h ago; the caller still says fresh
                                                    (the configuration poll text stays fresh)
    cycle_inputs(missing_key="limits.max_grid_charge_w" | "battery.soc" | ...)   drop one reading or snapshot signal
    cycle_inputs(decisions=..., accept_provenance=...)                           explicit overrides

The readings already meet the rules that later work packages add (INTELLIGENCE_FOUNDATION_CONTRACT.md section 13), so
wiring them changes no expectation built on this fixture: a fresh configuration-poll liveness reading, the TOU table in
its schema v2 shape with exactly one grid-charge slot (the same 01:00-04:30 window as before), both TOU enables on, no
overlay, a slot power equal to the grid-charge limit (the TOU power cap lowers nothing) and a reserve raise preference of
0 % (present and usable, never above any floor). After WP-0 this file changes only through the integrator.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecco_core.bridge import ADVISORY_SIGNALS  # noqa: E402  (tests may read ecco_core freely)
from ecco_core.state import NORMALIZED, RAW, Observation, Snapshot  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.inputs import live_inputs_from_snapshot  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402

UTC = timezone.utc
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
TZ = "Europe/London"
FACTS = ac.SiteFacts(pv_array_kwp=6.0, latitude=51.5, longitude=-0.1, tz=TZ)
VERSIONS = ac.Versions("0.1.0-fixture", "intel-v1.1.0-foundation-shadow", "0000000", None)
POLL_AGE_S = 20.0
CONFIG_POLL_AGE_S = 30.0          # the configuration poll runs about every 60 s; well inside the 300 s bound (section 13.3)
SYNTHETIC_ACCEPT = frozenset({sd.Provenance.SYNTHETIC_TEST})
GRID_CHARGE_LIMIT_W = 5000.0


def _slot(n: int, start: str, end: str, source: str, target_pct: float) -> dict:
    """One schema v2 TOU row (advisory_contract.TOU_SLOT_ROW_KEYS): flags_raw agrees with the source and mode texts."""
    return {"slot": n, "start": start, "end": end, "target_soc_pct": target_pct, "charge_source": source,
            "flags_raw": ac.TOU_CHARGE_SOURCE_BITS[source] | ac.TOU_MODE_BITS["General"], "mode": "General",
            "power_w": GRID_CHARGE_LIMIT_W}


# 01:00-04:30 is the one grid-charge slot: deliberately NOT the SiteConfig example cheap window (00:30-05:30), so a test
# can tell a window read from this table (or the tariff) from the example default. The other five slots charge from no
# source; the six slots form one ring (slot 6 runs into slot 1) that wraps past midnight once.
TOU_TABLE_V2 = (
    _slot(1, "00:00", "01:00", "None", 20.0),
    _slot(2, "01:00", "04:30", "Grid", 80.0),
    _slot(3, "04:30", "08:00", "None", 20.0),
    _slot(4, "08:00", "16:00", "None", 20.0),
    _slot(5, "16:00", "19:00", "None", 20.0),
    _slot(6, "19:00", "00:00", "None", 20.0),
)

# every SITE_READING_KEYS entry: (value, age in seconds)
_READINGS = {
    "liveness.dongle_poll_changed_at": (None, POLL_AGE_S),          # value = the change time itself
    "liveness.config_poll_changed_at": (None, CONFIG_POLL_AGE_S),   # value = the change time itself
    "supervision.state": ("SUPERVISED", 30.0),
    "supervision.stable": (True, 30.0),
    "supervision.heartbeat_age_s": (12.0, 30.0),
    "battery.soc_raw_pct": (55.0, POLL_AGE_S),
    "capacity.helper_kwh": (20.0, 120.0),
    "capacity.fe1_wh_per_pct": (201.0, 120.0),
    "capacity.fe1_basis": ("DISCHARGE_EPISODES", 120.0),
    "capacity.reg204_ah": (400.0, POLL_AGE_S),
    "efficiency.helper_pct": (92.0, 120.0),
    "protection.shutdown_soc_pct": (12.0, POLL_AGE_S),
    "stop.dump_soc_pct": (30.0, POLL_AGE_S),
    "tou.slot_table": ([dict(r) for r in TOU_TABLE_V2], POLL_AGE_S),
    "tou.current_target_soc_pct": (80.0, POLL_AGE_S),
    "tou.enabled": (True, POLL_AGE_S),
    "tou.grid_charge_enabled": (True, POLL_AGE_S),
    "tou.overlay_state": ("NONE", POLL_AGE_S),
    "limits.max_grid_charge_w": (GRID_CHARGE_LIMIT_W, 120.0),
    "tariff.import_rates": ([{"start": "2030-01-16T01:00:00+00:00", "end": "2030-01-16T04:30:00+00:00", "p_per_kwh": 7.5}], 120.0),
    "tariff.export_rates": ([{"start": "2030-01-16T00:00:00+00:00", "end": "2030-01-17T00:00:00+00:00", "p_per_kwh": 15.0}], 120.0),
    "tariff.events": ([], 120.0),
    "pv.forecast_today_kwh": (3.1, 7200.0),
    "pv.forecast_tomorrow_kwh": (4.2, 7200.0),
    "inverter.clock_offset_s": (2.0, POLL_AGE_S),
    "pref.wear_cost_p_per_kwh": (2.0, 3600.0),
    "pref.normal_max_charge_target_pct": (90.0, 3600.0),
    "pref.advisory_reserve_raise_pct": (0.0, 3600.0),
}
_SIGNALS = {  # dongle signals are observed at the poll time
    "battery.soc": 55.0, "battery.power": 400.0, "grid.power": -50.0, "house.power": 450.0, "pv.power": 0.0,
    "inverter.healthy": True, "reserve.ha_minimum_soc": 20.0,
}


def synthetic_decisions() -> sd.DecisionSet:
    """Every gating decision RECORDED with SYNTHETIC_TEST provenance (test values, not recommendations). I-D3 states a
    nominal voltage so the Ah register reading converts to kWh: the four capacity sources (stated 20 kWh, helper 20 kWh,
    FE-1 201 Wh/% = 20.1 kWh, 400 Ah x 51.2 V = 20.48 kWh) agree within the synthetic 10 % band."""
    t = sd.Provenance.SYNTHETIC_TEST
    limits = {k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None}
    vals = {"D1": sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 30.0, True),
            "D2": sd.Protection(sd.OWNER_STATEMENT, 12.0, datetime(2030, 1, 1, tzinfo=UTC)),
            "D3": sd.CapacityAuthority("CONFIGURED_HELPER", 20.0, False, 51.2), "D4": sd.CapacityBand(10.0),
            "D5": sd.Efficiency(0.92, sd.FRACTION, sd.ROUND_TRIP), "D6": sd.FreshnessOverrides(limits),
            "D8": sd.HD1Cutover(datetime(2029, 12, 1, tzinfo=UTC), sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER),
            "D9": sd.DSTPolicy(sd.NORMALISE_TO_NOMINAL, sd.SCALE_UP_ONLY)}
    ds = sd.DecisionSet()
    for did, v in vals.items():
        ds = ds.with_decision(did, v, t)
    return ds


def history(now: datetime = NOW):
    cfg = SiteConfig(pv_array_kwp=FACTS.pv_array_kwp)
    start = (now - timedelta(days=60)).date()
    return make_history(start, 61, cfg, seed=7).truncated(now)


def cycle_inputs(*, synthetic_recorded: bool = False, paused: bool | None = False, stale_liveness: bool = False,
                 missing_key: str | None = None, decisions: sd.DecisionSet | None = None, accept_provenance=None,
                 now: datetime = NOW) -> ac.CycleInputs:
    poll_at = now - timedelta(seconds=7200.0 if stale_liveness else POLL_AGE_S)
    sig_at = now - timedelta(seconds=POLL_AGE_S)                 # the values themselves look recent either way
    obs = []
    for sig, v in _SIGNALS.items():
        if sig == missing_key:
            continue
        obs.append(Observation(sig, v, sig_at, f"synthetic:{sig}", RAW if sig != "inverter.healthy" else NORMALIZED))
    if missing_key != "history.hourly":
        obs.append(Observation("history.hourly", True, now - timedelta(minutes=50), "synthetic:history", NORMALIZED))
    snap = Snapshot.of(now, obs)
    readings = []
    for key, (value, age) in _READINGS.items():
        if key == missing_key:
            continue
        at = poll_at if key == "liveness.dongle_poll_changed_at" else now - timedelta(seconds=age)
        readings.append(ac.SiteReading(key, at if value is None else value, ac.SITE_READING_KEYS[key], at, f"synthetic:{key}"))
    ds = decisions if decisions is not None else (synthetic_decisions() if synthetic_recorded else sd.DecisionSet())
    acc = accept_provenance if accept_provenance is not None else (SYNTHETIC_ACCEPT if synthetic_recorded else sd.DEFAULT_ACCEPT_PROVENANCE)
    limits, _ = sd.freshness_limits(ds, acc)
    caller = []
    for sig in ADVISORY_SIGNALS:
        o = snap.get(sig)
        age = None if o is None else o.age_s(now)
        lim = limits.get(sig)
        fresh = o is not None and o.value is not None and age is not None and lim is not None and age <= lim
        caller.append((sig, bool(fresh or (stale_liveness and sig == "battery.soc")), age))
    hist = None if missing_key == "history" else history(now)
    pv_hist = {"synthetic_forecast": {date(2030, 1, d): 2.0 + 0.1 * d for d in range(1, 15)}}
    base = SiteConfig(latitude=FACTS.latitude, longitude=FACTS.longitude, tz=FACTS.tz, pv_array_kwp=FACTS.pv_array_kwp)
    return ac.CycleInputs(now=now, snapshot=snap, live=live_inputs_from_snapshot(snap), caller_assessments=tuple(caller),
                          history=hist, pv_forecast_history=pv_hist, base_cfg=base, site_facts=FACTS, decisions=ds,
                          accept_provenance=acc, site_readings=tuple(readings),
                          outcome_metrics=ac.OutcomeMetrics(1.1, 0.8, 7), paused=paused, previous=None, versions=VERSIONS)
