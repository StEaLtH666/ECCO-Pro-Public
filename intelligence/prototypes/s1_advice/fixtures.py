"""Synthetic scenarios for the S1 offline advice harness (PROTOTYPE). Fictional year 2030, as the other Intelligence fixtures;
no value here describes a real installation. Every filled decision is a typed site_decisions record with provenance
SYNTHETIC_TEST and says so in the report; none is an owner decision and none is a recommended value."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

from ...config import SiteConfig
from ...site_decisions import (EXCLUDE, EXCLUDE_PRE_CUTOVER, FRACTION, INTELLIGENCE_USER_RESERVE, NORMALISE_TO_NOMINAL,
                               OWNER_STATEMENT, ROUND_TRIP, SCALE_UP_ONLY, CapacityAuthority, CapacityBand, DSTPolicy,
                               Efficiency, FreshnessOverrides, HD1Cutover, PlanningFloor, Protection)
from ...synthetic import make_history
from ...timeutil import UTC, local_wall, utc_from_ts, zone
from .scenario import (DecisionRecord, EventDecl, MockHour, Observation, PowerLimits, ReserveContext, Scenario, TariffDecl)

TZ = "Europe/London"
AUTUMN_2030 = date(2030, 10, 27)        # last Sunday of October 2030: a 25 h local day
SPRING_2030 = date(2030, 3, 31)         # last Sunday of March 2030: a 23 h local day

# fictional synthetic inputs (SYNTHETIC_TEST): not the owner's, not recommended values, not the SiteConfig example ones
SYNTHETIC_STATEMENT_AT = datetime(2030, 9, 1, 12, tzinfo=UTC)     # when a synthetic protection statement was "read"
SYNTHETIC_CUTOVER = datetime(2030, 1, 1, tzinfo=UTC)               # a synthetic I-D8 cut-over, before every fixture hour
SYNTHETIC_GRID_CHARGE_LIMIT_W = 6000.0                             # a synthetic limits.max_grid_charge_w reading
SYNTHETIC_FRESHNESS_S = {"inverter.healthy": 300.0, "reserve.ha_minimum_soc": 300.0,
                         "limits.max_grid_charge_w": 900.0, "tariff.import_rates": 900.0}


def hours_from_history(start_day: date, days: int, cfg: SiteConfig, seed: int = 2, flat_kwh: float | None = None) -> tuple[MockHour, ...]:
    """MockHours from the existing seeded synthetic household (or a flat house of `flat_kwh` per hour)."""
    if flat_kwh is not None:
        h = make_history(start_day, days, cfg, seed=seed, profile=[flat_kwh] * 24, hour_noise=0.0, day_sigma=0.0)
    else:
        h = make_history(start_day, days, cfg, seed=seed)
    out = []
    for s in sorted(h.by_start):
        r = h.by_start[s]
        out.append(MockHour(utc_from_ts(s), r.e.get("load"), r.e.get("pv", 0.0), r.soc_mean))
    return tuple(out)


def synthetic_value(did: str, x: object) -> object:
    """The typed record a fixture uses for a decision. A typed site_decisions value passes through unchanged; a number is
    the fixture shorthand for one documented record shape (fixtures only, never in the harness):

        D1 n -> PlanningFloor(INTELLIGENCE_USER_RESERVE, n, advice_honours=True)
        D2 n -> Protection(OWNER_STATEMENT, n, a fictional statement time)
        D3 n -> CapacityAuthority(CONFIGURED_HELPER, value_kwh=n)
        D4 n -> CapacityBand(n)
        D5 n -> Efficiency(n, fraction, ROUND_TRIP)

    Anything else is returned as is (and the harness then finds the decision INVALID)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return x
    if did == "D1":
        return PlanningFloor(INTELLIGENCE_USER_RESERVE, float(x), True)
    if did == "D2":
        return Protection(OWNER_STATEMENT, float(x), SYNTHETIC_STATEMENT_AT)
    if did == "D3":
        return CapacityAuthority("CONFIGURED_HELPER", float(x))
    if did == "D4":
        return CapacityBand(float(x))
    if did == "D5":
        return Efficiency(float(x), FRACTION, ROUND_TRIP)
    return x


def synthetic_record(did: str, x: object) -> DecisionRecord:
    """A SYNTHETIC_TEST DecisionRecord for `did` (see synthetic_value)."""
    return DecisionRecord(synthetic_value(did, x))


def synthetic_decisions(cfg: SiteConfig | None = None, **override) -> dict[str, DecisionRecord]:
    """A set of SYNTHETIC_TEST decisions for demonstrations and tests: NOT the owner's, NOT recommended values. I-D7 is
    retired (the required inputs are code constants) and stays OPEN. An override of None leaves that decision OPEN."""
    cfg = cfg or SiteConfig()
    vals = {
        "D1": 40.0,                                      # the planning floor the test plans with
        "D2": 10.0,                                      # a fictional inverter protection level (owner statement)
        "D3": cfg.battery_capacity_kwh,                  # the capacity the test treats as authoritative
        "D4": 8.0,
        "D5": 0.90,
        "D6": FreshnessOverrides(SYNTHETIC_FRESHNESS_S),
        "D8": HD1Cutover(SYNTHETIC_CUTOVER, EXCLUDE, EXCLUDE_PRE_CUTOVER),
        "D9": DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY),
    }
    vals.update(override)
    return {k: synthetic_record(k, v) for k, v in vals.items() if v is not None}


def _base(now: datetime, cfg: SiteConfig, days: int = 45, **kw) -> Scenario:
    first = (now.astimezone(zone(cfg.tz)).date()) - timedelta(days=days)
    return Scenario(now=now, hours=kw.pop("hours", None) or hours_from_history(first, days + 1, cfg), cfg=cfg,
                    tariff=kw.pop("tariff", TariffDecl(30, 330, "declared", 7.5, 28.0, 15.0)),
                    soc=kw.pop("soc", Observation(62.0, now - timedelta(seconds=30))),
                    inverter_healthy=kw.pop("inverter_healthy", Observation(True, now - timedelta(seconds=40))),
                    grid_charge_limit_w=kw.pop("grid_charge_limit_w",
                                               Observation(SYNTHETIC_GRID_CHARGE_LIMIT_W, now - timedelta(seconds=60))),
                    **kw)


def example_shadow() -> Scenario:
    """Every decision but the retired I-D7 filled with a SYNTHETIC_TEST value: the advisors run and return SHADOW advice."""
    cfg = SiteConfig()
    now = local_wall(date(2030, 10, 15), 21 * 60 + 30, zone(TZ))
    ev = EventDecl(local_wall(date(2030, 10, 16), 17 * 60, zone(TZ)), local_wall(date(2030, 10, 16), 18 * 60, zone(TZ)))
    return _base(now, cfg, decisions=synthetic_decisions(cfg), events=(ev,), dump_duration_min=60.0,
                 ha_reserve_helper=Observation(5.0, now - timedelta(seconds=60)),
                 power_limits=PowerLimits(5.0, 5.0), label="SYNTHETIC: all decisions SYNTHETIC_TEST")


def example_blocked() -> Scenario:
    """Today's real position in the shape of a scenario: every decision OPEN. Synthetic records, fictional values."""
    cfg = SiteConfig()
    now = local_wall(date(2030, 10, 15), 21 * 60 + 30, zone(TZ))
    ev = EventDecl(local_wall(date(2030, 10, 16), 17 * 60, zone(TZ)), local_wall(date(2030, 10, 16), 18 * 60, zone(TZ)))
    return _base(now, cfg, events=(ev,), dump_duration_min=60.0,
                 ha_reserve_helper=Observation(5.0, now - timedelta(seconds=60)),
                 reserve_context=ReserveContext(tou_slot_floor_pct=None, dump_stop_soc_pct=None),
                 label="SYNTHETIC: decisions D1-D9 OPEN")


def example_dst(autumn: bool = True, d9: DSTPolicy | None = None) -> Scenario:
    """A fictional tariff window 22:00-23:00 whose post-window period crosses the 2030 clock change. `d9` is the typed
    I-D9 record (None = OPEN)."""
    cfg = SiteConfig()
    day = (AUTUMN_2030 if autumn else SPRING_2030) - timedelta(days=1)
    now = local_wall(day, 21 * 60, zone(TZ))
    dec = synthetic_decisions(cfg, D9=d9)
    tag = "OPEN" if d9 is None else (f"{d9.history_rule}+{d9.target_rule}" if isinstance(d9, DSTPolicy) else repr(d9))
    return _base(now, cfg, hours=hours_from_history(day - timedelta(days=45), 46, cfg, flat_kwh=1.0),
                 tariff=TariffDecl(22 * 60, 23 * 60, "declared"), decisions=dec,
                 label=f"SYNTHETIC: {'autumn' if autumn else 'spring'} clock change, D9 {tag}")


def with_(sc: Scenario, **kw) -> Scenario:
    return replace(sc, **kw)
