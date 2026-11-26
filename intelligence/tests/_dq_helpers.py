"""Shared helpers for the data-quality suites (tests only; fictional 2030 data from _cycle_fixtures and synthetic houses)."""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
from ecco_core.state import Observation, Snapshot  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import quality as _quality  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.advisor import LiveInputs  # noqa: E402
from intelligence.history import HourRecord  # noqa: E402
from intelligence.quality import DQ_PROPOSED, QualityResult, assess_inputs  # noqa: E402
from intelligence.timeutil import local_date, zone  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = cf.NOW
SYN = cf.SYNTHETIC_ACCEPT
# the frozen contract suite's pattern for a number with a unit (findings' texts must never carry one)
UNIT_NUMBER = re.compile(r"\d(?:[\d.,]*\d)?\s?(?:%|kwh\b|kw\b|wh\b|w\b|ah\b|v\b|p/kwh|£|gbp\b|pence\b)", re.IGNORECASE)
# the inputs dq may BLOCK on: REQUIRED_SIGNALS, REQUIRED_READINGS, SITE_READING_KEYS, and the reserve helper signal that
# I-D1's HA_RESERVE_HELPER source adds through site_decisions.required_inputs
DECLARED_INPUTS = (set(s for v in sd.REQUIRED_SIGNALS.values() for s in v) | set(r for v in sd.REQUIRED_READINGS.values() for r in v)
                   | set(ac.SITE_READING_KEYS) | {"reserve.ha_minimum_soc"})


def clean(**kw) -> ac.CycleInputs:
    """A complete, fresh CycleInputs with the synthetic decisions accepted (the clean base for positive rule tests)."""
    return cf.cycle_inputs(synthetic_recorded=True, **kw)


def codes(q: QualityResult, severity: str | None = None) -> set[str]:
    return {f.code for f in q.findings if severity is None or f.severity == severity}


def item_codes(q: QualityResult, item: str) -> set[str]:
    return {f.code for f in q.findings if f.subject == item and f.severity == sd.BLOCK}


def blocks(q: QualityResult) -> list:
    return [f for f in q.findings if f.severity == sd.BLOCK]


def text_leaks(q: QualityResult) -> list[str]:
    return [f"{f.code}: {f.text}" for f in q.findings if UNIT_NUMBER.search(f.text)]


def add_observation(inp: ac.CycleInputs, sig: str, value, at: datetime | None = None) -> ac.CycleInputs:
    """A copy whose snapshot also carries `sig` (observed at the fixture poll time unless `at` is given)."""
    obs = dict(inp.snapshot.observations)
    obs[sig] = Observation(sig, value, at or (inp.now - timedelta(seconds=cf.POLL_AGE_S)), f"synthetic:{sig}", "normalized")
    return replace(inp, snapshot=Snapshot(inp.snapshot.as_of, obs))


def decisions_with(did: str, value, base: sd.DecisionSet | None = None) -> sd.DecisionSet:
    return (base or cf.synthetic_decisions()).with_decision(did, value, sd.Provenance.SYNTHETIC_TEST)


# ---------------------------------------------------------------------------------------------------------------------
# CCR-DQ-1 (landed at integration; this block is a historical record). Before it, the raw SOC, the clock offset and the
# event table had no freshness limit in the contract, so the quality layer judged them UNRESOLVED (never fresh), and the
# rule suites proved the rules that need them by SIMULATING the change request in the test process only: _cycle_fixtures'
# synthetic_decisions() records 300 s for every UNRESOLVED key, so the simulation gave exactly what CCR-DQ-1 now gives. It
# never touched a file; it swapped quality's reference to freshness_limits. CCR_DQ1_LANDED is True on the integrated code,
# so the simulation does nothing.
# ---------------------------------------------------------------------------------------------------------------------

QUALIFYING_READING_KEYS = ("battery.soc_raw_pct", "inverter.clock_offset_s", "tariff.events")
CCR_DQ1_LANDED = all(k in sd.FRESHNESS_OVERRIDE_KEYS for k in QUALIFYING_READING_KEYS)
CCR_DQ1_LIMIT_S = 300.0


def _ccr_dq1_limits(decisions, accept_provenance=sd.DEFAULT_ACCEPT_PROVENANCE):
    limits, notes = sd.freshness_limits(decisions, accept_provenance)
    try:
        applied = decisions.satisfied("D6", frozenset(accept_provenance)) and not any(
            f.code == "DECISION_D6_INVALID" for f in notes)
    except Exception:  # noqa: BLE001 - a junk decision set or acceptance applies nothing, as the real function does
        applied = False
    if not applied:
        return limits, notes
    out = dict(limits)
    for k in QUALIFYING_READING_KEYS:
        if out.get(k) is None:
            out[k] = CCR_DQ1_LIMIT_S
    return MappingProxyType(out), notes


def simulate_ccr_dq1(on: bool = True) -> None:
    """Judge the CCR-DQ-1 readings as if the change request had landed (on) or strictly, as shipped (off)."""
    _quality.freshness_limits = _ccr_dq1_limits if (on and not CCR_DQ1_LANDED) else sd.freshness_limits


def active_limits(decisions, accept_provenance):
    """The limits the quality layer is being run with (the contract's, or the CCR-DQ-1 simulation's)."""
    return _quality.freshness_limits(decisions, accept_provenance)[0]


# ---------------------------------------------------------------------------------------------------------------------
# an independent oracle for "this input is fresh" (it shares no code with quality.py beyond the contract constants)
# ---------------------------------------------------------------------------------------------------------------------

def _aware(t) -> bool:
    return isinstance(t, datetime) and t.tzinfo is not None and t.tzinfo.utcoffset(t) is not None


def finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


def _liveness_age(inp, key: str) -> float | None:
    rs = [r for r in (inp.site_readings if isinstance(inp.site_readings, (tuple, list)) else ())
          if isinstance(r, ac.SiteReading) and r.key == key]
    if len(rs) != 1:
        return None
    r = rs[0]
    if r.problems() or not _aware(r.value) or not _aware(r.observed_at):
        return None
    t = min(r.value, r.observed_at)
    age = (inp.now - t).total_seconds()
    if (inp.now - r.value).total_seconds() < 0 or (inp.now - r.observed_at).total_seconds() < 0:
        return None
    return age


def oracle_liveness_age(inp) -> float | None:
    """The telemetry poll text's age (the dongle liveness reading), or None when it cannot be trusted."""
    return _liveness_age(inp, sd.LIVENESS_KEY)


# DATA_QUALITY_METHOD section 11 (written out here, not imported from quality): the configuration-poll liveness bound
CONFIG_LIVENESS_MAX_S = 300.0
# DATA_QUALITY_METHOD section 11: the supervision readings' bound (state and stable aged by the telemetry liveness) and the
# heartbeat's (its reported age plus its reading's own age)
SUPERVISION_MAX_S = 90.0
# the configuration poll's readings (contract section 13.3, written out): aged by the larger of the two liveness ages
CONFIG_POLL_KEYS = ("tou.slot_table", "tou.current_target_soc_pct", "tou.enabled", "tou.grid_charge_enabled",
                    "protection.shutdown_soc_pct", "capacity.reg204_ah")


def oracle_config_liveness_age(inp) -> float | None:
    """The configuration-poll text's age (the configuration-poll liveness reading), or None when it cannot be trusted."""
    return _liveness_age(inp, sd.CONFIG_LIVENESS_KEY)


def oracle_supervision_ok(inp) -> bool:
    """Supervision is current and stable as DATA_QUALITY_METHOD section 10 states it: exactly one well-formed state
    (SUPERVISED), stable flag (true) and heartbeat reading, none observed after now; the state and the stable flag aged by
    the telemetry liveness (a valid liveness reading at most the supervision bound old); the heartbeat's reported age
    (not negative) plus its own reading age within the same bound."""
    now = inp.now
    readings = inp.site_readings if isinstance(inp.site_readings, (tuple, list)) else ()
    got = {}
    for key in ("supervision.state", "supervision.stable", "supervision.heartbeat_age_s"):
        rs = [r for r in readings if isinstance(r, ac.SiteReading) and r.key == key]
        if len(rs) != 1 or rs[0].problems() or not oracle_value_ok(key, rs[0].value):
            return False
        if (now - rs[0].observed_at).total_seconds() < 0:
            return False
        got[key] = rs[0]
    live = oracle_liveness_age(inp)
    if live is None or live > SUPERVISION_MAX_S:
        return False
    if got["supervision.state"].value != "SUPERVISED" or got["supervision.stable"].value is not True:
        return False
    hb = got["supervision.heartbeat_age_s"]
    return hb.value >= 0 and hb.value + (now - hb.observed_at).total_seconds() <= SUPERVISION_MAX_S


# Plausibility as DATA_QUALITY_METHOD section 11 states it (written out here, not imported from quality):
# % in 0..100 (the raw SOC is the SOC rule's), W in 0..100 kW (the grid-charge limit above 0), kWh in 0..500 (the capacity
# helper 0.5..500), Wh/% such that x 100 / 1000 lies in 0.5..500, Ah above 0 up to 20000, a heartbeat age not negative, a
# day-ahead PV forecast at most 10 kWh per kWp of array.
_PRESENCE_TABLES = ("tariff.import_rates", "tariff.export_rates", "tou.slot_table")


def oracle_value_ok(key: str, v) -> bool:
    unit = ac.SITE_READING_KEYS.get(key)
    if unit == "datetime":
        return _aware(v)
    if key == "tou.overlay_state":
        return isinstance(v, str) and v in ("NONE", "ACTIVE")
    if unit == "enum":
        return isinstance(v, str) and v.strip() != ""
    if unit == "bool":
        return isinstance(v, bool)
    if unit == "table":
        return isinstance(v, (list, tuple)) and (len(v) > 0 or key not in _PRESENCE_TABLES)
    if not finite(v):
        return False
    if key == "battery.soc_raw_pct" or unit in ("s", "p/kWh"):
        return key != "supervision.heartbeat_age_s" or v >= 0
    if key == "limits.max_grid_charge_w":
        return 0 < v <= 100000
    if key == "capacity.helper_kwh":
        return 0.5 <= v <= 500
    if key == "capacity.fe1_wh_per_pct":
        return 0.5 <= v / 10.0 <= 500
    return {"%": 0 <= v <= 100, "W": 0 <= v <= 100000, "kWh": 0 <= v <= 500, "Ah": 0 < v <= 20000}.get(unit, False)


def _signal_ok(sig: str, v) -> bool:
    if sig == "inverter.healthy":
        return isinstance(v, bool)
    if sig == "reserve.ha_minimum_soc":
        return finite(v) and 0 <= v <= 100
    return finite(v)


def _well_formed_hours(h) -> list[int]:
    """Hour starts of the records that can date a history: int key, an HourRecord filed under its own start, hour aligned,
    dict energies / flags / sources, at least one finite energy."""
    out = []
    for s, r in getattr(h, "by_start", {}).items():
        if (type(s) is int and isinstance(r, HourRecord) and r.start == s and s % 3600 == 0 and isinstance(r.e, dict)
                and isinstance(r.flags, dict) and isinstance(r.sources, dict)
                and all(isinstance(x, (set, frozenset, tuple, list)) for x in r.flags.values())
                and any(finite(x) for x in r.e.values())):
            out.append(s)
    return out


def snapshot_age(inp) -> float | None:
    snap = inp.snapshot
    if not isinstance(snap, Snapshot):
        return None
    a = (inp.now - snap.as_of).total_seconds()
    return a if a >= 0 else None


def _tz(inp):
    try:
        return zone(getattr(inp.site_facts, "tz", "Europe/London"))
    except Exception:  # noqa: BLE001
        return None


def oracle_fresh(inp, key: str, limits) -> bool:
    """True only when `key` is present, well formed, plausible, observed no later than now and within its limit (dongle
    inputs: the liveness reading present, at most the PROPOSED liveness bound old, and within the input's limit; a
    configuration-poll reading: both liveness readings within their bounds and the larger of their ages within its limit;
    a snapshot signal is at least as old as its snapshot; a day-ahead forecast observed on the cycle's local date; the
    history dated by its well-formed records only)."""
    now = inp.now
    lim = limits.get(key)
    live_age = oracle_liveness_age(inp)
    live_ok = live_age is not None and live_age <= DQ_PROPOSED.liveness_max_age_s
    cfg_age = oracle_config_liveness_age(inp)
    cfg_ok = cfg_age is not None and cfg_age <= CONFIG_LIVENESS_MAX_S
    if key == sd.LIVENESS_KEY:
        return live_ok
    if key == sd.CONFIG_LIVENESS_KEY:
        return cfg_ok
    if key == "history.hourly":
        hours = _well_formed_hours(inp.history)
        if not hours or lim is None:
            return False
        age = now.timestamp() - (max(hours) + 3600)
        return 0 <= age <= lim
    if key in ac.SITE_READING_KEYS:
        rs = [r for r in (inp.site_readings if isinstance(inp.site_readings, (tuple, list)) else ())
              if isinstance(r, ac.SiteReading) and r.key == key]
        if len(rs) != 1 or rs[0].problems() or rs[0].value is None or not oracle_value_ok(key, rs[0].value):
            return False
        r = rs[0]
        if (now - r.observed_at).total_seconds() < 0:
            return False
        if key in sd.DATE_SCOPED_READINGS:
            tz = _tz(inp)
            kwp = getattr(inp.site_facts, "pv_array_kwp", None)
            if finite(kwp) and kwp > 0 and r.value > 10.0 * kwp:
                return False
            return tz is not None and local_date(r.observed_at, tz) == local_date(now, tz)
        if lim is None:
            return False
        if key in CONFIG_POLL_KEYS:
            return live_ok and cfg_ok and max(live_age, cfg_age) <= lim
        age = live_age if key in sd.DONGLE_READINGS else (now - r.observed_at).total_seconds()
        return (live_ok or key not in sd.DONGLE_READINGS) and age is not None and age <= lim
    snap = inp.snapshot
    if not isinstance(snap, Snapshot):
        return False
    o = snap.get(key)
    if o is None or o.value is None or not _signal_ok(key, o.value) or not _aware(o.observed_at) or lim is None:
        return False
    own = (now - o.observed_at).total_seconds()
    snap_age = snapshot_age(inp)
    if own < 0 or snap_age is None:
        return False
    if key in sd.DONGLE_SIGNALS:
        return live_ok and max(live_age, snap_age) <= lim
    return max(own, snap_age) <= lim


_LIVE_PAIRS = {"soc_pct": "battery.soc", "load_w": "house.power", "pv_w": "pv.power", "inverter_ok": "inverter.healthy",
               "ha_reserve_pct": "reserve.ha_minimum_soc"}


def live_inconsistent(inp) -> str | None:
    """Why the LiveInputs cannot be trusted with this snapshot (None when it can, or when there is none)."""
    live = inp.live
    if live is None:
        return None
    if not isinstance(live, LiveInputs):
        return "malformed"
    snap = inp.snapshot if isinstance(inp.snapshot, Snapshot) else None
    for attr, sig in _LIVE_PAIRS.items():
        lv = getattr(live, attr, None)
        if lv is None:
            continue
        sv = None if snap is None or snap.get(sig) is None else snap.get(sig).value
        if isinstance(lv, bool) or isinstance(sv, bool):
            if lv is not sv:
                return f"differs on {sig}"
        elif finite(lv) or finite(sv):
            if not (finite(lv) and finite(sv) and abs(lv - sv) <= 1e-9):
                return f"differs on {sig}"
        elif lv != sv:
            return f"differs on {sig}"
    if snap is not None and _aware(getattr(live, "now", None)) and live.now != snap.as_of:
        return "differs on the time"
    return None


def run(inp) -> QualityResult:
    return assess_inputs(inp)
