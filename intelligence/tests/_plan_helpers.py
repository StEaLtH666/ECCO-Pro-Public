"""Planning-stream test helpers (tests only): integration-shaped SYNTHETIC tariff payloads (fictional 2030 prices),
reading substitution on the shared cycle fixtures, and a synthetic backtest campaign. Nothing here is site data, an owner
decision or a real price.

    go_like_rates(day, days, tz)        half-hour rows over `days` local days: 7.5 p/kWh 01:00-04:30, 30 p/kWh otherwise,
                                        in the integration's unit (GBP/kWh) and with local UTC offsets
    rates_payload(t, tz)                {current_day, next_day} as the integration publishes it in the evening of t
    flat_export(day, days, tz)          a flat synthetic 15 p/kWh export table
    with_reading(inputs, key, value, age_s=...) / without(inputs, key)
    with_signal(inputs, name, value)    the same inputs with one snapshot signal's value replaced (same observation time)
    simulated_ccr_plan_1(limit_s)       TEST ONLY, a context manager: simulates CCR-PLAN-1 in process (a satisfied I-D6
                                        gives tariff.events and tou.current_target_soc_pct a limit), so the export /
                                        Dump / HOLD_CURRENT paths the foundation seam cannot reach are exercised
    synthetic_campaign(...)             a SYNTHETIC backtest campaign on intelligence.synthetic histories
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
from ecco_core.state import Observation, Snapshot  # noqa: E402  (tests may read ecco_core freely)
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import backtest_advice as bt  # noqa: E402
from intelligence import shadow_cycle as sc  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.inputs import live_inputs_from_snapshot  # noqa: E402
from intelligence.synthetic import make_history, solcast_like  # noqa: E402
from intelligence.timeutil import local_wall, zone  # noqa: E402

UTC = timezone.utc
TZ = cf.TZ
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "plan"
CHEAP_GBP = 0.075        # synthetic 2030 prices (GBP/kWh, the integration's unit): fictional
PEAK_GBP = 0.30
EXPORT_GBP = 0.15
CHEAP_WINDOW = (60, 270)  # 01:00-04:30 local, as the shared fixtures' TOU slot


def go_like_rates(day: date, days: int = 2, tz: str = TZ, cheap=CHEAP_WINDOW, cheap_gbp: float = CHEAP_GBP,
                  peak_gbp: float = PEAK_GBP, step_min: int = 30) -> list[dict]:
    """Rate rows for `days` local days from `day`: elapsed half-hours from local midnight to local midnight (so a 25 h /
    23 h day has 50 / 46 rows), cheap where the slot's local start lies in `cheap`."""
    z = zone(tz)
    rows = []
    for k in range(days):
        d = day + timedelta(days=k)
        t, end = local_wall(d, 0, z), local_wall(d, 1440, z)
        while t < end:
            u = t + timedelta(minutes=step_min)
            loc = t.astimezone(z)
            m = loc.hour * 60 + loc.minute
            v = cheap_gbp if cheap[0] <= m < cheap[1] else peak_gbp
            rows.append({"start": loc.isoformat(), "end": u.astimezone(z).isoformat(), "value_inc_vat": v,
                         "is_capped": False, "is_intelligent_adjusted": False})
            t = u
    return rows


def flat_export(day: date, days: int = 2, tz: str = TZ, gbp: float = EXPORT_GBP) -> list[dict]:
    return go_like_rates(day, days, tz, cheap=(0, 0), cheap_gbp=gbp, peak_gbp=gbp)


def rate_events(t: datetime, tz: str = TZ, export: bool = False) -> dict:
    """The rate events as published in the evening of t: {current_day: {rates}, next_day: {rates}}."""
    d = t.astimezone(zone(tz)).date()
    mk = flat_export if export else go_like_rates
    return {"current_day": {"rates": mk(d, 1, tz)}, "next_day": {"rates": mk(d + timedelta(days=1), 1, tz)}}


def rates_payload(t: datetime, tz: str = TZ, export: bool = False) -> list:
    """The SiteReading value: the rate events of the evening of t merged into one table (a list of rows), as the
    reading's unit ('table') says."""
    ev = rate_events(t, tz, export)
    return ev["current_day"]["rates"] + ev["next_day"]["rates"]


def _reading(key: str, value, now: datetime, age_s: float) -> ac.SiteReading:
    at = now - timedelta(seconds=age_s)
    return ac.SiteReading(key, value, ac.SITE_READING_KEYS[key], at, f"synthetic:{key}")


def with_reading(inputs: ac.CycleInputs, key: str, value, age_s: float = 120.0, observed_at: datetime | None = None
                 ) -> ac.CycleInputs:
    """The same inputs with reading `key` replaced (or added)."""
    rs = [r for r in inputs.site_readings if r.key != key]
    r = _reading(key, value, inputs.now, age_s)
    if observed_at is not None:
        r = ac.SiteReading(key, value, ac.SITE_READING_KEYS[key], observed_at, r.source)
    return replace(inputs, site_readings=tuple(rs + [r]))


def without(inputs: ac.CycleInputs, key: str) -> ac.CycleInputs:
    return replace(inputs, site_readings=tuple(r for r in inputs.site_readings if r.key != key))


def with_signal(inputs: ac.CycleInputs, name: str, value) -> ac.CycleInputs:
    """The same inputs with snapshot signal `name` carrying `value` (same observation time, source and kind). The
    LiveInputs is rebuilt from the new snapshot, as the bridge builds it from the snapshot it reads (the quality layer
    BLOCKs LIVE_INPUTS_DISAGREE when the two differ); inputs without a LiveInputs keep none."""
    old = inputs.snapshot.get(name)
    obs = [o for s, o in inputs.snapshot.observations.items() if s != name]
    obs.append(Observation(name, value, old.observed_at, old.source, old.kind))
    snap = Snapshot.of(inputs.snapshot.as_of, obs)
    return replace(inputs, snapshot=snap, live=None if inputs.live is None else live_inputs_from_snapshot(snap))


PLANNING_READING_KEYS = ("tariff.events", "tou.current_target_soc_pct")     # the readings CCR-PLAN-1 gives an I-D6 key


@contextmanager
def simulated_ccr_plan_1(limit_s: float = 300.0):
    """TEST ONLY. Simulates CCR-PLAN-1 in process: while active, a satisfied I-D6 gives the two planning readings a
    freshness limit of `limit_s` in the cycle's view of the limits (as the CCR's diff does for the synthetic I-D6, which
    gives every unresolved key 300 s). Once the CCR has landed (both readings are I-D6 keys, CCR-DQ-1 / CCR-PLAN-1) the
    satisfied I-D6 already gives them its limit; `limit_s` then stands for a site that recorded a stricter one, so it only
    tightens (never loosens) the contract's limit. Nothing is changed outside this process, and the original is always
    restored."""
    orig = sc.freshness_limits

    def patched(decisions, accept_provenance):
        lim, notes = orig(decisions, accept_provenance)
        d = dict(lim)
        if decisions.satisfied("D6", accept_provenance):
            for k in PLANNING_READING_KEYS:
                d[k] = float(limit_s) if d.get(k) is None else min(float(d[k]), float(limit_s))
        return MappingProxyType(d), notes

    sc.freshness_limits = patched
    try:
        yield
    finally:
        sc.freshness_limits = orig


def verified_inputs(**kw) -> ac.CycleInputs:
    """The shared fixture with an integration-shaped synthetic import and export tariff (fresh)."""
    inp = cf.cycle_inputs(**kw)
    inp = with_reading(inp, "tariff.import_rates", rates_payload(inp.now))
    return with_reading(inp, "tariff.export_rates", rates_payload(inp.now, export=True))


def static_readings() -> dict:
    """The shared fixture's reading values (synthetic), keyed by reading."""
    return {k: v for k, (v, _age) in cf._READINGS.items() if v is not None}  # noqa: SLF001 - test helper reads test data


def synthetic_campaign(start: date = date(2030, 1, 1), days: int = 45, seed: int = 11, level: float = 1.0,
                       tariff: bool = True, decisions=None, accept=None, pv_over: float = 1.3) -> bt.Campaign:
    """A SYNTHETIC campaign: a generated house (intelligence.synthetic), a generated day-ahead PV forecast series, the
    shared fixture's readings, the synthetic decisions (accepted explicitly) and, when `tariff`, the synthetic Go-like
    import and flat export tariffs."""
    gen = SiteConfig(pv_array_kwp=6.0, battery_capacity_kwh=20.0, cheap_window_start_min=CHEAP_WINDOW[0],
                     cheap_window_end_min=CHEAP_WINDOW[1])
    hist = make_history(start, days, gen, seed=seed, level=level)
    pvf = {"synthetic_forecast": solcast_like(hist, gen, over_factor=pv_over, seed=seed, noise=0.15)}
    facts = cf.FACTS
    base = SiteConfig(latitude=facts.latitude, longitude=facts.longitude, tz=facts.tz, pv_array_kwp=facts.pv_array_kwp)
    readings = static_readings()
    imp = (lambda t: rates_payload(t)) if tariff else None
    exp = (lambda t: rates_payload(t, export=True)) if tariff else None
    return bt.Campaign(hist, base, facts, decisions if decisions is not None else cf.synthetic_decisions(), readings, pvf,
                       imp, exp, lambda t: [], accept_provenance=accept if accept is not None else cf.SYNTHETIC_ACCEPT)
