"""Inputs of the S1 offline advice harness (PROTOTYPE, SHADOW): explicit, typed, caller-supplied data only.

Everything the harness knows arrives in one `Scenario`: mock hourly records, a site configuration, the tariff's recurring
cheap window, a handful of point observations with the instant they were observed, the Intelligence decisions D1-D9
(display labels I-D1..I-D9) and optional events / power limits. Nothing here reads a file, a Home Assistant entity, a
statistics export or a clock: `now` is part of the scenario.

Decisions. The register, its ids, titles, statuses, provenance and typed values are those of
intelligence/site_decisions.py (the single source of truth); this module declares none of its own. Every one of D1-D9
starts OPEN. A scenario fills one with a `DecisionRecord` whose value is a TYPED site_decisions record (PlanningFloor,
Protection, CapacityAuthority, CapacityBand, Efficiency, FreshnessOverrides, RequiredInputsOverride, HD1Cutover,
DSTPolicy) with provenance SYNTHETIC_TEST, and the report then says, on every item that used it, that the numbers rest on
synthetic decisions and not on the owner's. A bare number or free text is never recorded (the decision is INVALID and
BLOCKs). The harness accepts only SYNTHETIC_TEST: it has no way to mark a decision as the owner's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ...config import SiteConfig
from ...site_decisions import DECISION_IDS, DECISION_TITLES, DecisionStatus, Provenance  # noqa: F401  (re-exported)

OPEN = DecisionStatus.OPEN
RECORDED = DecisionStatus.RECORDED
INVALID = DecisionStatus.INVALID
SYNTHETIC_TEST = Provenance.SYNTHETIC_TEST     # the only provenance this prototype accepts for a filled decision


@dataclass(frozen=True)
class MockHour:
    """One hour of synthetic history. `start` must be an aware, hour-aligned instant; energies are kWh in that hour."""
    start: datetime
    load_kwh: float | None
    pv_kwh: float | None = 0.0
    soc_mean: float | None = None


@dataclass(frozen=True)
class Observation:
    """A point reading and the instant its SOURCE observed it (aware). observed_at None = age unknown."""
    value: object
    observed_at: datetime | None


@dataclass(frozen=True)
class TariffDecl:
    """A recurring local cheap window (minutes after local midnight; end <= start means it crosses midnight) and optional
    rates in p/kWh. Rates are carried for the report only; the V1.1 advisors are energy budgets.

    The declared window stands in for the charge-window source: it is judged as observed at `now`, under the I-D6 limit
    of `tariff.import_rates`. It is a synthetic declaration, not a verified tariff, and the report says so. A window
    that crosses local midnight cannot be carried into the effective SiteConfig by the foundation contract
    (site_decisions.CHARGE_WINDOW_KEY needs 0 <= start < end <= 1440), so the battery items are then withheld."""
    cheap_start_min: int
    cheap_end_min: int
    source: str = "declared"
    import_cheap_p: float | None = None
    import_peak_p: float | None = None
    export_p: float | None = None


@dataclass(frozen=True)
class EventDecl:
    """A Saving Session / export event (aware start and end)."""
    start: datetime
    end: datetime
    label: str = "saving_session"


@dataclass(frozen=True)
class ReserveContext:
    """The other levels people call "reserve". Informational: only the planning floor (I-D1), the protection level (I-D2)
    and the raise-only helper enter any arithmetic. None = not known here (never assumed)."""
    tou_slot_floor_pct: float | None = None       # a TOU slot's target SOC as currently set on the inverter
    dump_stop_soc_pct: float | None = None        # the Dump to Grid stop SOC as currently set


@dataclass(frozen=True)
class PowerLimits:
    max_discharge_kw: float | None = None
    max_export_kw: float | None = None


@dataclass(frozen=True)
class DecisionRecord:
    """One declared decision: a TYPED site_decisions value and its provenance (SYNTHETIC_TEST by default). Anything else
    (a bare number, free text, an unknown provenance, an OWNER_RECORD) makes the decision INVALID; a known provenance
    other than SYNTHETIC_TEST is refused and counts as OPEN."""
    value: object
    provenance: str = SYNTHETIC_TEST


@dataclass(frozen=True)
class Scenario:
    now: datetime
    hours: tuple[MockHour, ...]
    cfg: SiteConfig = field(default_factory=SiteConfig)   # site facts only: its battery fields and window are replaced
    tariff: TariffDecl | None = None
    soc: Observation | None = None                       # battery.soc, %
    inverter_healthy: Observation | None = None          # inverter.healthy: True / False
    ha_reserve_helper: Observation | None = None         # reserve.ha_minimum_soc, %: raise-only input
    grid_charge_limit_w: Observation | None = None       # limits.max_grid_charge_w, W: never the SiteConfig example 8 kW
    decisions: dict[str, DecisionRecord] = field(default_factory=dict)   # D1..D9 or I-D1..I-D9; absent = OPEN
    capacity_sources: tuple[tuple[str, float], ...] = ()  # other capacity figures to cross-check (name, kWh)
    reserve_context: ReserveContext = field(default_factory=ReserveContext)
    events: tuple[EventDecl, ...] = ()
    dump_duration_min: float | None = None                # request a Dump-to-Grid stop-level advice for this duration
    power_limits: PowerLimits = field(default_factory=PowerLimits)
    overnight_prior_kwh: float | None = None              # an owner-configured conservative default (S1 site input); None = none
    include_v1_summary: bool = True
    label: str = "synthetic scenario"
