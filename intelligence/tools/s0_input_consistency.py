#!/usr/bin/env python3
"""Intelligence S0: an OFFLINE consistency diagnostic for the inputs a recommendation would rest on (SHADOW, advisory).

It answers one question about a *declaration* of inputs that the caller writes down by hand (or the built-in synthetic
example): are the reserve levels, battery capacity, efficiency, signal readings and history periods mutually consistent,
and which owner decisions are still open? It reads no Home Assistant state, no statistics export, no network and no file
other than an optional declaration JSON that the caller names. It calls nothing, writes nothing and recommends no value:

  * reserves are classified by what they ARE (a soft planning floor, a Home Assistant helper, a feature stop level, the
    inverter's physical protection) and compared only when both values are known;
  * capacity from several sources is compared pairwise; a disagreement above the band is a WARNING. The 8 % band is a
    PROPOSAL until the owner records a band (OwnerDecisions.capacity_warn_band_pct);
  * efficiency is normalised to a round-trip fraction and checked for the one-way / round-trip confusion;
  * every signal reading is judged fail closed: a missing, non-numeric, unit- or sign-mismatching, stale or unknown-age
    reading is never usable, and a canonical 0 over a non-numeric raw state is flagged as a suspected false zero;
  * history periods are classified against the (owner-supplied) instant the derived house-load sensor took effect;
  * overnight windows are measured in elapsed hours so the 25-hour autumn and 23-hour spring local days are visible.

Authority: like every Intelligence module this has no write path (tests/test_s0_input_contract.py checks the imports and
the vocabulary). Existing SiteConfig, ecco_core and the V1 / V1.1 outputs are only READ. A report always says
mode SHADOW and applies_nothing true. Design and open questions: docs/intelligence/INTELLIGENCE_S0_INPUT_CONTRACT.md.

    python intelligence/tools/s0_input_consistency.py --example            # synthetic, mostly consistent, decisions open
    python intelligence/tools/s0_input_consistency.py --example-faulty     # synthetic, seeded faults
    python intelligence/tools/s0_input_consistency.py --declaration my.json [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecco_core.state import spec_for  # noqa: E402
from intelligence.advisor import STALE_SOC_SECONDS  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.explain import FRESH, STALE, UNKNOWN, InputAge, finite_number  # noqa: E402
from intelligence.timeutil import UTC, local_wall, zone  # noqa: E402

MODEL_VERSION = "intel-s0-input-consistency-0.1.0-draft"
MODE = "SHADOW"

INFO, WARN, BLOCK = "INFO", "WARN", "BLOCK"
OPEN, RECORDED = "OPEN", "RECORDED"

# ---- reserve roles ---------------------------------------------------------------------------------------------------
SOFT_PLANNING_FLOOR = "SOFT_PLANNING_FLOOR"      # a preference every recommendation stays above (Intelligence user reserve)
HA_RESERVE_HELPER = "HA_RESERVE_HELPER"          # a Home Assistant helper; an input that can only RAISE the planning floor
FEATURE_STOP_LEVEL = "FEATURE_STOP_LEVEL"        # where one feature stops (for example the Dump to Grid stop SOC)
PHYSICAL_PROTECTION = "PHYSICAL_PROTECTION"      # the inverter's own battery protection; ECCO cannot write it
RESERVE_ROLES = (SOFT_PLANNING_FLOOR, HA_RESERVE_HELPER, FEATURE_STOP_LEVEL, PHYSICAL_PROTECTION)

# ---- capacity / efficiency source kinds --------------------------------------------------------------------------------
CAPACITY_KINDS = ("CONFIGURED_HELPER", "SITECONFIG_VALUE", "LEARNED_FROM_DISCHARGE", "REGISTER_AH", "EXAMPLE_DEFAULT")
ROUND_TRIP, ONE_WAY = "ROUND_TRIP", "ONE_WAY"

# ---- signal reading kinds ----------------------------------------------------------------------------------------------
RAW, CANONICAL, DERIVED, LEGACY = "RAW", "CANONICAL", "DERIVED", "LEGACY"
READING_KINDS = (RAW, CANONICAL, DERIVED, LEGACY)
NON_NUMERIC_STATES = frozenset({"unavailable", "unknown", "none", "", "nan", "null"})

# Sign conventions the repository already uses (ecco_core.state.SIGNALS): the token a reading must declare.
SIGN_TOKEN = {"battery.power": "discharge_positive", "grid.power": "import_positive"}

# Advisory age limits the project ALREADY defines, with where. Anything absent is unresolved and can never be fresh.
# (tests/test_s0_input_contract.py reads these back from ecco_core.freshness so they cannot drift.)
DEFINED_ADVISORY_LIMITS_S: dict[str, float] = {"battery.soc": float(STALE_SOC_SECONDS), "history.hourly": 6 * 3600.0}

# History period vocabulary (what a stored series IS, not an entity id).
LOAD_POWER_MEAN, LOAD_ENERGY_COUNTER = "load_power_mean", "load_energy_counter"
HISTORY_SIGNALS = (LOAD_POWER_MEAN, LOAD_ENERGY_COUNTER)


@dataclass(frozen=True)
class ProposedThresholds:
    """Every number below is a PROPOSAL made by this draft. None is an owner decision."""
    status: str = "PROPOSED_PENDING_OWNER"
    capacity_warn_band_pct: float = 8.0          # symmetric: |a-b| / mean(a,b); 8 % is the stated capacity uncertainty
    capacity_plausible_kwh: tuple[float, float] = (0.5, 500.0)
    efficiency_round_trip_max_plausible: float = 0.97   # a "round-trip" figure above this is probably one-way
    efficiency_one_way_min_plausible: float = 0.88      # a "one-way" figure below this is probably round-trip
    efficiency_agree_tolerance: float = 0.01
    soc_agree_points: float = 2.0                # SOC is an integer percentage; allow one step either way
    power_agree_w: float = 100.0
    power_agree_fraction: float = 0.05
    other_agree_fraction: float = 0.05


# ---------------------------------------------------------------------------------------------------------------------
# declaration data (all plain, frozen, JSON-serialisable)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ReserveDecl:
    name: str
    role: str
    value_pct: float | None
    source: str
    scope: tuple[str, ...] = ()
    enforced_by: str | None = None
    writable_by_ecco: bool = False


@dataclass(frozen=True)
class CapacityDecl:
    name: str
    kind: str
    value: float | None
    unit: str = "kWh"                      # kWh | Wh | Ah
    nominal_voltage_v: float | None = None  # needed to compare an Ah figure
    age_s: float | None = None
    provenance: str = ""


@dataclass(frozen=True)
class EfficiencyDecl:
    name: str
    value: float | None
    unit: str | None = None                # fraction | percent
    basis: str | None = None               # ROUND_TRIP | ONE_WAY
    provenance: str = ""


@dataclass(frozen=True)
class ReadingDecl:
    signal: str                            # an ecco_core.state signal name
    source_id: str
    kind: str                              # RAW | CANONICAL | DERIVED | LEGACY
    value: float | None
    raw_state: str | None = None           # the source's own state text, when it has one
    unit: str | None = None
    sign: str | None = None
    age_s: float | None = None


@dataclass(frozen=True)
class HistoryPeriod:
    series: str                            # load_power_mean | load_energy_counter
    start: datetime
    end: datetime
    exporting_hours: float | None = None


@dataclass(frozen=True)
class NightSpec:
    first_night: date
    last_night: date
    start_min: int                         # local wall-clock minutes after midnight of the night's date
    end_min: int                           # may exceed 1440 (the next day)
    tz: str = "Europe/London"


@dataclass(frozen=True)
class OwnerDecisions:
    """Everything the owner has NOT yet decided is None. The diagnostic never fills these in."""
    canonical_planning_floor_source: str | None = None
    capacity_authority: str | None = None
    capacity_warn_band_pct: float | None = None
    efficiency_canonical_basis: str | None = None
    advisory_limits_s: dict[str, float] | None = None
    required_signals: tuple[str, ...] | None = None
    hd1_effective_from: datetime | None = None
    dst_night_policy: str | None = None


@dataclass(frozen=True)
class Declaration:
    cfg: SiteConfig = field(default_factory=SiteConfig)
    reserves: tuple[ReserveDecl, ...] = ()
    capacities: tuple[CapacityDecl, ...] = ()
    efficiencies: tuple[EfficiencyDecl, ...] = ()
    readings: tuple[ReadingDecl, ...] = ()
    history: tuple[HistoryPeriod, ...] = ()
    nights: NightSpec | None = None
    decisions: OwnerDecisions = field(default_factory=OwnerDecisions)
    thresholds: ProposedThresholds = field(default_factory=ProposedThresholds)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    subject: str
    message: str
    evidence: tuple[tuple[str, object], ...] = ()

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "subject": self.subject, "message": self.message,
                "evidence": {k: v for k, v in self.evidence}}


@dataclass(frozen=True)
class DecisionState:
    id: str
    title: str
    status: str
    question: str
    blocks: tuple[str, ...]
    recorded: object = None

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status, "question": self.question,
                "blocks": list(self.blocks), "recorded": self.recorded}


@dataclass(frozen=True)
class Report:
    verdict: str                           # BLOCKED | OPEN_DECISIONS | CONSISTENT_WITH_WARNINGS | CONSISTENT
    findings: tuple[Finding, ...]
    decisions: tuple[DecisionState, ...]
    thresholds: ProposedThresholds
    mode: str = MODE
    applies_nothing: bool = True
    model_version: str = MODEL_VERSION

    def codes(self, severity: str | None = None) -> list[str]:
        return [f.code for f in self.findings if severity is None or f.severity == severity]

    def to_dict(self) -> dict:
        counts = {s: sum(1 for f in self.findings if f.severity == s) for s in (BLOCK, WARN, INFO)}
        return {"model_version": self.model_version, "mode": self.mode, "applies_nothing": self.applies_nothing,
                "verdict": self.verdict, "counts": counts, "findings": [f.to_dict() for f in self.findings],
                "decisions": [d.to_dict() for d in self.decisions],
                "proposed_thresholds": {k.name: _jsonable(getattr(self.thresholds, k.name)) for k in fields(self.thresholds)}}


def _jsonable(v: object) -> object:
    return list(v) if isinstance(v, tuple) else v


def _f(code: str, sev: str, subject: str, message: str, **evidence: object) -> Finding:
    return Finding(code, sev, subject, message, tuple(sorted((k, _jsonable(v)) for k, v in evidence.items())))


def _num(x: object) -> float | None:
    return float(x) if finite_number(x) else None


# ---------------------------------------------------------------------------------------------------------------------
# 1. reserves
# ---------------------------------------------------------------------------------------------------------------------

def check_reserves(decls: tuple[ReserveDecl, ...], cfg: SiteConfig) -> list[Finding]:
    out: list[Finding] = []
    names = [d.name for d in decls]
    for n in sorted({n for n in names if names.count(n) > 1}):
        out.append(_f("RESERVE_DUPLICATE_NAME", BLOCK, n, "two reserve declarations share this name"))
    values: dict[str, float] = {}
    by_role: dict[str, list[ReserveDecl]] = {r: [] for r in RESERVE_ROLES}
    for d in decls:
        if d.role not in RESERVE_ROLES:
            out.append(_f("RESERVE_ROLE_UNKNOWN", BLOCK, d.name, f"role {d.role!r} is not one of {RESERVE_ROLES}"))
            continue
        by_role[d.role].append(d)
        v = _num(d.value_pct)
        if d.value_pct is None:
            if d.role == PHYSICAL_PROTECTION:
                out.append(_f("PHYSICAL_PROTECTION_UNKNOWN", BLOCK, d.name,
                              "the inverter's own protection level is not known here; ECCO reads it but cannot write it, "
                              "so the owner must supply it (display or an authorised read), it is never assumed"))
            else:
                out.append(_f("RESERVE_VALUE_UNKNOWN", BLOCK, d.name, "no value declared"))
        elif v is None or not 0.0 <= v <= 100.0:
            out.append(_f("RESERVE_VALUE_INVALID", BLOCK, d.name, "not a finite percentage in 0..100", value=repr(d.value_pct)))
        else:
            values[d.name] = v
        if d.role in (SOFT_PLANNING_FLOOR, HA_RESERVE_HELPER) and d.enforced_by:
            out.append(_f("ENFORCEMENT_CLAIM_UNVERIFIED", WARN, d.name,
                          "a soft floor / helper is claimed to be enforced; SAFETY.md section 9 says nothing enforces it "
                          "(a feature stop level and the inverter protection are the only limits that act)",
                          claimed=d.enforced_by))
        if d.role == PHYSICAL_PROTECTION and d.writable_by_ecco:
            out.append(_f("PROTECTION_DECLARED_WRITABLE", BLOCK, d.name,
                          "ECCO has no write path to the inverter's protection levels and they are owner-locked"))
    if not by_role[SOFT_PLANNING_FLOOR]:
        out.append(_f("NO_PLANNING_FLOOR_DECLARED", BLOCK, "reserves", "no SOFT_PLANNING_FLOOR is declared"))
    if not by_role[PHYSICAL_PROTECTION]:
        out.append(_f("PHYSICAL_PROTECTION_UNKNOWN", BLOCK, "reserves", "no PHYSICAL_PROTECTION level is declared"))

    def vals(role: str) -> list[tuple[ReserveDecl, float]]:
        return [(d, values[d.name]) for d in by_role[role] if d.name in values]

    prot = vals(PHYSICAL_PROTECTION)
    for soft, sv in vals(SOFT_PLANNING_FLOOR):
        for p, pv in prot:
            if sv < pv:
                out.append(_f("PLANNING_FLOOR_BELOW_PROTECTION", WARN, soft.name,
                              "the planning floor is below the inverter's protection level, so the protection binds first",
                              floor_pct=sv, protection_pct=pv))
        for h, hv in vals(HA_RESERVE_HELPER):
            if hv < sv:
                out.append(_f("HA_HELPER_BELOW_PLANNING_FLOOR", INFO, h.name,
                              "the helper is below the planning floor; a helper can only raise the floor, so it has no effect",
                              helper_pct=hv, floor_pct=sv))
        for s, stv in vals(FEATURE_STOP_LEVEL):
            if stv < sv:
                out.append(_f("FEATURE_STOP_BELOW_PLANNING_FLOOR", INFO, s.name,
                              "the feature stops below the planning floor; today that feature does not read the floor",
                              stop_pct=stv, floor_pct=sv))
    for s, stv in vals(FEATURE_STOP_LEVEL):
        for p, pv in prot:
            if stv < pv:
                out.append(_f("FEATURE_STOP_BELOW_PROTECTION", WARN, s.name,
                              "the feature stop level is below the inverter's protection level", stop_pct=stv, protection_pct=pv))
    for p, pv in prot:
        if cfg.technical_min_soc_pct < pv:
            out.append(_f("TECHNICAL_MIN_BELOW_PROTECTION", WARN, "SiteConfig.technical_min_soc_pct",
                          "the configured technical minimum is below the inverter's protection level",
                          technical_min_pct=cfg.technical_min_soc_pct, protection_pct=pv))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# 2. capacity
# ---------------------------------------------------------------------------------------------------------------------

def capacity_kwh(d: CapacityDecl, th: ProposedThresholds) -> tuple[float | None, Finding | None]:
    """(usable kWh, a finding when it is not usable). Fail closed."""
    if d.kind not in CAPACITY_KINDS:
        return None, _f("CAPACITY_KIND_UNKNOWN", BLOCK, d.name, f"kind {d.kind!r} is not one of {CAPACITY_KINDS}")
    v = _num(d.value)
    if v is None or v <= 0.0:
        return None, _f("CAPACITY_VALUE_MISSING", WARN, d.name, "no positive finite value declared")
    if d.unit == "kWh":
        kwh = v
    elif d.unit == "Wh":
        kwh = v / 1000.0
    elif d.unit == "Ah":
        volts = _num(d.nominal_voltage_v)
        if volts is None or volts <= 0.0:
            return None, _f("CAPACITY_AH_NEEDS_VOLTAGE", WARN, d.name,
                            "an Ah figure cannot be compared without a nominal voltage; it is left out, never guessed")
        kwh = v * volts / 1000.0
    else:
        return None, _f("CAPACITY_UNIT_UNKNOWN", BLOCK, d.name, f"unit {d.unit!r} is not kWh, Wh or Ah")
    lo, hi = th.capacity_plausible_kwh
    if not lo <= kwh <= hi:
        return None, _f("CAPACITY_IMPLAUSIBLE", BLOCK, d.name,
                        "outside the plausible range; a Wh figure read as kWh (or the reverse) is the usual cause",
                        kwh=round(kwh, 3), plausible_kwh=(lo, hi))
    return kwh, None


def check_capacity(decls: tuple[CapacityDecl, ...], cfg: SiteConfig, th: ProposedThresholds,
                   band_pct: float | None) -> list[Finding]:
    out: list[Finding] = []
    band = band_pct if band_pct is not None else th.capacity_warn_band_pct
    band_note = "owner-recorded" if band_pct is not None else "PROPOSED, not yet accepted by the owner"
    example_default = SiteConfig.__dataclass_fields__["battery_capacity_kwh"].default
    sources = list(decls)
    if not any(d.kind == "SITECONFIG_VALUE" for d in sources):
        sources.append(CapacityDecl("SiteConfig.battery_capacity_kwh", "SITECONFIG_VALUE", cfg.battery_capacity_kwh,
                                    provenance="the SiteConfig under test"))
    usable: list[tuple[str, float]] = []
    for d in sources:
        kwh, bad = capacity_kwh(d, th)
        if bad is not None:
            out.append(bad)
            continue
        usable.append((d.name, kwh))
        if d.kind == "LEARNED_FROM_DISCHARGE" and d.age_s is None:
            out.append(_f("CAPACITY_SOURCE_AGE_UNKNOWN", WARN, d.name, "a learned capacity without an age cannot be judged current"))
        if d.kind == "EXAMPLE_DEFAULT":
            out.append(_f("CAPACITY_IS_EXAMPLE_DEFAULT", WARN, d.name, "this value is the shipped example, not a measurement"))
    if cfg.battery_capacity_kwh == example_default and not any(
            d.kind in ("CONFIGURED_HELPER", "LEARNED_FROM_DISCHARGE", "REGISTER_AH") for d in sources
            if capacity_kwh(d, th)[0] is not None):
        out.append(_f("CAPACITY_IS_EXAMPLE_DEFAULT", WARN, "SiteConfig.battery_capacity_kwh",
                      "SiteConfig still holds the shipped example capacity and no independent source confirms it",
                      kwh=example_default))
    if not usable:
        out.append(_f("CAPACITY_UNKNOWN", BLOCK, "capacity", "no usable capacity source"))
        return out
    if len(usable) == 1:
        out.append(_f("CAPACITY_SINGLE_SOURCE", INFO, usable[0][0], "one usable source only: nothing to cross-check it against"))
        return out
    worst = None
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            (na, a), (nb, b) = usable[i], usable[j]
            rel = abs(a - b) / ((a + b) / 2.0) * 100.0
            if worst is None or rel > worst[0]:
                worst = (rel, na, a, nb, b)
            if rel > band:
                out.append(_f("CAPACITY_MISMATCH", WARN, f"{na} vs {nb}",
                              f"the two capacities differ by {rel:.1f} %, above the {band:g} % band ({band_note})",
                              a_kwh=round(a, 3), b_kwh=round(b, 3), difference_pct=round(rel, 2), band_pct=band))
    if worst is not None and worst[0] <= band:
        out.append(_f("CAPACITY_WITHIN_BAND", INFO, "capacity",
                      f"largest pairwise difference {worst[0]:.1f} % is within the {band:g} % band ({band_note})",
                      difference_pct=round(worst[0], 2), band_pct=band))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# 3. efficiency
# ---------------------------------------------------------------------------------------------------------------------

def efficiency_round_trip(d: EfficiencyDecl) -> tuple[float | None, float | None, Finding | None]:
    """(round-trip fraction, one-way fraction, finding when unusable)."""
    v = _num(d.value)
    if v is None:
        return None, None, _f("EFFICIENCY_VALUE_MISSING", BLOCK, d.name, "no finite value declared")
    if d.unit not in ("fraction", "percent"):
        return None, None, _f("EFFICIENCY_UNIT_UNSTATED", BLOCK, d.name, "unit must be stated as fraction or percent")
    frac = v / 100.0 if d.unit == "percent" else v
    if (d.unit == "fraction" and v > 1.0) or (d.unit == "percent" and v <= 1.0):
        return None, None, _f("EFFICIENCY_UNIT_MISMATCH", BLOCK, d.name,
                              "the number does not fit the stated unit (a fraction above 1, or a percentage of 1 or less)",
                              value=v, unit=d.unit)
    if not 0.5 <= frac <= 1.0:
        return None, None, _f("EFFICIENCY_OUT_OF_RANGE", BLOCK, d.name, "outside 0.5..1.0", fraction=round(frac, 4))
    if d.basis not in (ROUND_TRIP, ONE_WAY):
        return None, None, _f("EFFICIENCY_BASIS_UNSTATED", BLOCK, d.name,
                              "the basis (ROUND_TRIP or ONE_WAY) must be stated; the engine applies sqrt(round-trip) each way")
    if d.basis == ROUND_TRIP:
        return frac, math.sqrt(frac), None
    return frac * frac, frac, None


def check_efficiency(decls: tuple[EfficiencyDecl, ...], cfg: SiteConfig, th: ProposedThresholds) -> list[Finding]:
    out: list[Finding] = []
    sources = list(decls)
    if not any(d.name == "SiteConfig.round_trip_efficiency" for d in sources):
        sources.append(EfficiencyDecl("SiteConfig.round_trip_efficiency", cfg.round_trip_efficiency, "fraction", ROUND_TRIP,
                                      "the SiteConfig under test; the engine applies sqrt() each way"))
    ok: list[tuple[EfficiencyDecl, float, float]] = []
    for d in sources:
        rt, ow, bad = efficiency_round_trip(d)
        if bad is not None:
            out.append(bad)
            continue
        frac = d.value / 100.0 if d.unit == "percent" else d.value
        if d.basis == ROUND_TRIP and frac > th.efficiency_round_trip_max_plausible:
            out.append(_f("EFFICIENCY_LOOKS_ONE_WAY", WARN, d.name,
                          "declared round-trip but above the plausible round-trip level: it may be a one-way figure",
                          declared=round(frac, 4), as_round_trip_if_one_way=round(frac * frac, 4)))
        if d.basis == ONE_WAY and frac < th.efficiency_one_way_min_plausible:
            out.append(_f("EFFICIENCY_LOOKS_ROUND_TRIP", WARN, d.name,
                          "declared one-way but below the plausible one-way level: it may be a round-trip figure",
                          declared=round(frac, 4), as_one_way_if_round_trip=round(math.sqrt(frac), 4)))
        ok.append((d, rt, ow))
    tol = th.efficiency_agree_tolerance
    for i in range(len(ok)):
        for j in range(i + 1, len(ok)):
            (a, rta, owa), (b, rtb, owb) = ok[i], ok[j]
            if abs(rta - rtb) <= tol:
                if a.basis != b.basis:
                    out.append(_f("EFFICIENCY_BASES_DIFFER_BUT_CONSISTENT", INFO, f"{a.name} vs {b.name}",
                                  "different bases, same physics after conversion", round_trip=round(rta, 4)))
                continue
            va = a.value / 100.0 if a.unit == "percent" else a.value
            vb = b.value / 100.0 if b.unit == "percent" else b.value
            mixed = a.basis == b.basis and (abs(math.sqrt(min(va, vb)) - max(va, vb)) <= tol
                                            or abs(min(va, vb) ** 2 - max(va, vb)) <= tol)
            if mixed:
                out.append(_f("EFFICIENCY_ONE_WAY_ROUND_TRIP_MIX", BLOCK, f"{a.name} vs {b.name}",
                              "both claim the same basis but one value is the square root of the other: one-way and "
                              "round-trip figures are being mixed", a=round(va, 4), b=round(vb, 4)))
            else:
                out.append(_f("EFFICIENCY_DISAGREE", WARN, f"{a.name} vs {b.name}",
                              "round-trip equivalents differ by more than the tolerance",
                              a_round_trip=round(rta, 4), b_round_trip=round(rtb, 4), tolerance=tol))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# 4. signal readings
# ---------------------------------------------------------------------------------------------------------------------

def effective_limits(owner: dict[str, float] | None) -> tuple[dict[str, float], list[Finding]]:
    """Defined project limits, tightened (never loosened) by an owner override. Mirrors ecco_core.freshness."""
    limits = dict(DEFINED_ADVISORY_LIMITS_S)
    notes: list[Finding] = []
    for sig, v in sorted((owner or {}).items()):
        n = _num(v)
        if n is None or n <= 0.0:
            notes.append(_f("FRESHNESS_OVERRIDE_INVALID", BLOCK, sig, "an override must be a positive finite number of seconds"))
        elif sig in limits and n > limits[sig]:
            notes.append(_f("FRESHNESS_OVERRIDE_REFUSED", WARN, sig, "an override may tighten a defined limit, never loosen it",
                            defined_s=limits[sig], requested_s=n))
        else:
            limits[sig] = n
    return limits, notes


def _agree(signal: str, a: float, b: float, th: ProposedThresholds) -> bool:
    if signal == "battery.soc":
        return abs(a - b) <= th.soc_agree_points
    if signal.endswith(".power") or ".string_power" in signal:
        return abs(a - b) <= max(th.power_agree_w, th.power_agree_fraction * max(abs(a), abs(b)))
    return abs(a - b) <= th.other_agree_fraction * max(abs(a), abs(b), 1e-9)


def check_readings(readings: tuple[ReadingDecl, ...], owner: OwnerDecisions, th: ProposedThresholds) -> list[Finding]:
    out: list[Finding] = []
    limits, notes = effective_limits(owner.advisory_limits_s)
    out += notes
    required = set(owner.required_signals if owner.required_signals is not None else ("battery.soc",))
    groups: dict[str, list[ReadingDecl]] = {}
    for r in readings:
        groups.setdefault(r.signal, []).append(r)
    for sig in sorted(required - set(groups)):
        out.append(_f("REQUIRED_SIGNAL_MISSING", BLOCK, sig, "a required signal has no reading at all"))
    for sig, rs in sorted(groups.items()):
        spec = spec_for(sig)
        if spec is None:
            out.append(_f("SIGNAL_UNKNOWN_NAME", BLOCK, sig, "not a signal of the state model (ecco_core.state.SIGNALS)"))
            continue
        usable: list[ReadingDecl] = []
        for r in rs:
            subject = f"{sig} <- {r.source_id}"
            if r.kind not in READING_KINDS:
                out.append(_f("READING_KIND_UNKNOWN", BLOCK, subject, f"kind {r.kind!r} is not one of {READING_KINDS}"))
                continue
            if spec.unit is not None and r.unit != spec.unit:
                out.append(_f("UNIT_MISMATCH", BLOCK, subject, "the declared unit is not the signal's canonical unit",
                              declared=r.unit, canonical=spec.unit))
                continue
            token = SIGN_TOKEN.get(sig)
            if token is not None and r.sign is None:
                out.append(_f("SIGN_UNDECLARED", WARN, subject, "a signed signal needs its sign convention declared", expected=token))
            elif token is not None and r.sign != token:
                out.append(_f("SIGN_CONVENTION_MISMATCH", BLOCK, subject, "the reading uses another sign convention",
                              declared=r.sign, expected=token))
                continue
            v = _num(r.value)
            state = (r.raw_state or "").strip().lower() if r.raw_state is not None else None
            if v is None:
                out.append(_f("READING_NOT_NUMERIC", WARN, subject, "no usable numeric value", raw_state=r.raw_state))
                continue
            if v == 0.0 and r.kind == CANONICAL:
                twin = [x for x in rs if x.kind == RAW and x is not r]
                if any((_num(x.value) is None) or ((x.raw_state or "").strip().lower() in NON_NUMERIC_STATES and x.raw_state is not None)
                       for x in twin):
                    out.append(_f("FALSE_ZERO_SUSPECTED", BLOCK, subject,
                                  "the canonical value is 0 while the raw source gives no number: an invalid input has "
                                  "probably been turned into 0", raw_sources=[x.source_id for x in twin]))
                    continue
                if sig == "battery.soc" and not twin:
                    out.append(_f("ZERO_UNCONFIRMED", WARN, subject, "a canonical SOC of 0 with no raw source to confirm it"))
            if state in NON_NUMERIC_STATES and r.kind != RAW:
                out.append(_f("NON_NUMERIC_STATE_WITH_VALUE", WARN, subject, "the source state text is not numeric but a value is carried",
                              raw_state=r.raw_state))
            usable.append(r)
        lim = limits.get(sig)
        unresolved_noted = False
        status: dict[str, str] = {}
        for r in usable:
            ia = InputAge.assess(sig, r.age_s, lim, required=True, note=r.source_id)
            status[r.source_id] = ia.status
            subject = f"{sig} <- {r.source_id}"
            if ia.status == STALE:
                out.append(_f("READING_STALE", BLOCK if sig in required else WARN, subject, "older than its advisory limit",
                              age_s=ia.age_s, max_age_s=ia.max_age_s))
            elif ia.status == UNKNOWN and sig in required:
                out.append(_f("READING_AGE_UNKNOWN", BLOCK, subject,
                              "age missing/invalid, or no advisory limit is defined for a required signal", note=ia.note))
            elif ia.status == UNKNOWN and lim is None:
                if not unresolved_noted:
                    out.append(_f("ADVISORY_LIMIT_UNRESOLVED", INFO, sig,
                                  "no advisory freshness limit is defined for this signal; it can never be shown fresh"))
                    unresolved_noted = True
            elif ia.status == UNKNOWN:
                out.append(_f("READING_AGE_UNKNOWN", WARN, subject, "age missing or invalid", note=ia.note))
        fresh = [r for r in usable if status[r.source_id] == FRESH]
        if sig in required and not fresh:
            out.append(_f("SIGNAL_NO_USABLE_SOURCE", BLOCK, sig, "no numeric, correctly-typed, fresh reading is available"))
        comparable = [r for r in usable if status[r.source_id] != STALE]
        for i in range(len(comparable)):
            for j in range(i + 1, len(comparable)):
                a, b = comparable[i], comparable[j]
                if not _agree(sig, float(a.value), float(b.value), th):
                    out.append(_f("SOURCE_DISAGREEMENT", WARN, sig, f"{a.source_id} and {b.source_id} disagree beyond the tolerance",
                                  a=a.value, b=b.value))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# 5. history periods (HD1) and 6. local overnight windows (DST)
# ---------------------------------------------------------------------------------------------------------------------

def _aware(dt: datetime, what: str) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError(f"{what} must be a timezone-aware datetime")
    return dt


def classify_history(periods: tuple[HistoryPeriod, ...], hd1_effective_from: datetime | None) -> list[Finding]:
    out: list[Finding] = []
    if hd1_effective_from is not None:
        _aware(hd1_effective_from, "hd1_effective_from")
    for p in periods:
        _aware(p.start, "period start")
        _aware(p.end, "period end")
        if not p.end > p.start:
            raise ValueError("a history period must end after it starts")
        subject = f"{p.series} {p.start.astimezone(UTC):%Y-%m-%d %H:%M}Z..{p.end.astimezone(UTC):%Y-%m-%d %H:%M}Z"
        if p.series not in HISTORY_SIGNALS:
            out.append(_f("HISTORY_SERIES_UNKNOWN", BLOCK, subject, f"series must be one of {HISTORY_SIGNALS}"))
        elif p.series == LOAD_ENERGY_COUNTER:
            out.append(_f("LOAD_COUNTER_RELIABILITY_UNKNOWN", WARN, subject,
                          "whether the load energy counter shares the false-0 W fault is UNKNOWN and cannot be settled "
                          "offline: it needs a check on real data (owner-authorised, read-only)"))
        elif hd1_effective_from is None:
            out.append(_f("HD1_CUTOVER_UNKNOWN", BLOCK, subject,
                          "the instant the derived house-load sensor took effect is not recorded, so no load-power history "
                          "can be classed as reliable"))
        elif p.end <= hd1_effective_from:
            out.append(_f("LOAD_HISTORY_PRE_HD1_UNRELIABLE", WARN, subject,
                          "before the derived house-load sensor: the native load can read 0 W while exporting",
                          exporting_hours=p.exporting_hours))
        elif p.start < hd1_effective_from:
            before = (hd1_effective_from - p.start).total_seconds() / 3600.0
            out.append(_f("LOAD_HISTORY_STRADDLES_HD1", WARN, subject, "the period starts before the derived sensor took effect",
                          hours_before_cutover=round(before, 2)))
        else:
            out.append(_f("LOAD_HISTORY_POST_HD1", INFO, subject, "after the derived sensor took effect (still subject to the quality gate)"))
    return out


def night_profile(night: date, start_min: int, end_min: int, tz_name: str) -> dict:
    """Elapsed hours of one local wall-clock window, and of the local day it starts in."""
    if not end_min > start_min:
        raise ValueError("the window must end after it starts (end_min may exceed 1440)")
    tz = zone(tz_name)
    t0, t1 = local_wall(night, start_min, tz), local_wall(night, end_min, tz)
    d0, d1 = local_wall(night, 0, tz), local_wall(night, 1440, tz)
    nominal = (end_min - start_min) / 60.0
    actual = (t1 - t0).total_seconds() / 3600.0
    day_h = (d1 - d0).total_seconds() / 3600.0
    # the window may cross midnight into the next local day, which can be the short/long one
    nd0, nd1 = local_wall(night + timedelta(days=1), 0, tz), local_wall(night + timedelta(days=1), 1440, tz)
    next_day_h = (nd1 - nd0).total_seconds() / 3600.0
    change = "NONE"
    if actual > nominal + 1e-9:
        change = "AUTUMN_BACK"
    elif actual < nominal - 1e-9:
        change = "SPRING_FORWARD"
    return {"night": night.isoformat(), "nominal_hours": nominal, "actual_hours": actual, "delta_hours": actual - nominal,
            "length_factor": actual / nominal, "clock_change": change, "local_day_hours": day_h,
            "next_local_day_hours": next_day_h}


def check_nights(spec: NightSpec | None) -> list[Finding]:
    if spec is None:
        return []
    out: list[Finding] = []
    d = spec.first_night
    while d <= spec.last_night:
        p = night_profile(d, spec.start_min, spec.end_min, spec.tz)
        if p["clock_change"] != "NONE":
            out.append(_f("NIGHT_LENGTH_DIFFERS", WARN, p["night"],
                          f"the {p['nominal_hours']:g} h nominal window lasts {p['actual_hours']:g} h ({p['clock_change']}); a "
                          "raw total from this night is not comparable with an ordinary night's",
                          **{k: v for k, v in p.items() if k in ("nominal_hours", "actual_hours", "length_factor", "clock_change")}))
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# decisions, the whole run, example declarations, JSON loader, CLI
# ---------------------------------------------------------------------------------------------------------------------

def decision_states(decl: Declaration) -> tuple[DecisionState, ...]:
    o = decl.decisions
    prot_known = any(r.role == PHYSICAL_PROTECTION and _num(r.value_pct) is not None for r in decl.reserves)

    def st(rec: object) -> str:
        return RECORDED if rec not in (None, "", ()) else OPEN

    return (
        DecisionState("D1", "Canonical soft planning floor", st(o.canonical_planning_floor_source),
                      "Which of the helper, the Intelligence user reserve, a feature stop level or a new single setting is THE "
                      "planning floor, and must precharge and Dump advice honour it or only display it?",
                      ("RESERVE_*", "S3", "S5a", "S6b"), o.canonical_planning_floor_source),
        DecisionState("D2", "Inverter physical protection level", RECORDED if prot_known else OPEN,
                      "What is the inverter's own protection (shutdown) level, and how is it to be supplied without a write?",
                      ("PHYSICAL_PROTECTION_UNKNOWN", "technical_min_soc_pct"), None),
        DecisionState("D3", "Battery capacity authority", st(o.capacity_authority),
                      "Which source is canonical (owner helper, learned from discharge, or an Ah register with a stated "
                      "voltage), and what is each other source for?", ("CAPACITY_*", "S3", "S5a"), o.capacity_authority),
        DecisionState("D4", "Capacity mismatch band", st(o.capacity_warn_band_pct),
                      "Is 8 % (|a-b| / mean) the right warning band?", ("CAPACITY_MISMATCH",), o.capacity_warn_band_pct),
        DecisionState("D5", "Efficiency basis", st(o.efficiency_canonical_basis),
                      "Is the single canonical value round-trip (the engine applies sqrt each way) and in what unit?",
                      ("EFFICIENCY_*",), o.efficiency_canonical_basis),
        DecisionState("D6", "Advisory freshness limits", st(o.advisory_limits_s),
                      "What limit applies to house / PV / battery / grid power, inverter status and the reserve helper "
                      "(only SOC and hourly history have one today)?", ("READING_AGE_UNKNOWN", "S2", "S3"),
                      o.advisory_limits_s),
        DecisionState("D7", "Required signals per advisor", st(o.required_signals),
                      "Which signals must be fresh for the overnight, charge-target and export advisors?",
                      ("REQUIRED_SIGNAL_MISSING", "SIGNAL_NO_USABLE_SOURCE"), o.required_signals),
        DecisionState("D8", "Derived house-load cut-over and pre-fix history", st(o.hd1_effective_from),
                      "At what instant did the derived load sensor take effect, and is earlier load history excluded, "
                      "replaced, or kept only where not exporting?", ("HD1_CUTOVER_UNKNOWN", "S1"),
                      o.hd1_effective_from.isoformat() if o.hd1_effective_from else None),
        DecisionState("D9", "Clock-change night policy", st(o.dst_night_policy),
                      "Should a 25 h or 23 h night be excluded from learning, normalised per hour, or planned as its own length?",
                      ("NIGHT_LENGTH_DIFFERS", "S1"), o.dst_night_policy),
    )


def run(decl: Declaration) -> Report:
    findings: list[Finding] = []
    findings += check_reserves(decl.reserves, decl.cfg)
    findings += check_capacity(decl.capacities, decl.cfg, decl.thresholds, decl.decisions.capacity_warn_band_pct)
    findings += check_efficiency(decl.efficiencies, decl.cfg, decl.thresholds)
    findings += check_readings(decl.readings, decl.decisions, decl.thresholds)
    findings += classify_history(decl.history, decl.decisions.hd1_effective_from)
    findings += check_nights(decl.nights)
    decisions = decision_states(decl)
    if any(f.severity == BLOCK for f in findings):
        verdict = "BLOCKED"
    elif any(d.status == OPEN for d in decisions):
        verdict = "OPEN_DECISIONS"
    elif any(f.severity == WARN for f in findings):
        verdict = "CONSISTENT_WITH_WARNINGS"
    else:
        verdict = "CONSISTENT"
    return Report(verdict, tuple(findings), decisions, decl.thresholds)


# ---- synthetic examples (no real site values; the fictional year follows the other Intelligence fixtures) ------------

def _example_readings(*, faulty: bool) -> tuple[ReadingDecl, ...]:
    base = [
        ReadingDecl("battery.soc", "raw:soc", RAW, 62.0, "62", "%", None, 20.0),
        ReadingDecl("battery.soc", "canonical:soc", CANONICAL, 62.0, "62", "%", None, 20.0),
        ReadingDecl("battery.power", "raw:battery_power", RAW, 800.0, "800", "W", "discharge_positive", 20.0),
        ReadingDecl("grid.power", "ct:grid", RAW, -120.0, "-120", "W", "import_positive", 20.0),
        ReadingDecl("house.power", "derived:house", DERIVED, 930.0, "930", "W", None, 20.0),
    ]
    if not faulty:
        return tuple(base)
    return (
        ReadingDecl("battery.soc", "raw:soc", RAW, None, "unavailable", "%", None, 20.0),
        ReadingDecl("battery.soc", "canonical:soc", CANONICAL, 0.0, "0", "%", None, 20.0),
        ReadingDecl("battery.power", "raw:battery_power", RAW, 800.0, "800", "W", "charge_positive", 20.0),
        ReadingDecl("grid.power", "ct:grid", RAW, -0.12, "-0.12", "kW", "import_positive", 20.0),
        ReadingDecl("house.power", "derived:house", DERIVED, 930.0, "930", "W", None, 20.0),
        ReadingDecl("house.power", "native:house", RAW, 2400.0, "2400", "W", None, 20.0),
        ReadingDecl("pv.power", "raw:pv", RAW, 0.0, "0", "W", None, None),
    )


def example_declaration(faulty: bool = False) -> Declaration:
    tz = "Europe/London"
    cfg = SiteConfig()
    reserves = (
        ReserveDecl("Intelligence user reserve (SiteConfig default)", SOFT_PLANNING_FLOOR, cfg.user_reserve_soc_pct,
                    "SiteConfig.user_reserve_soc_pct", ("Intelligence advisors",), None),
        ReserveDecl("HA reserve helper (example value)", HA_RESERVE_HELPER, 15.0, "input_number.ecco_minimum_reserve_soc",
                    ("Intelligence input", "advanced-config bound", "time-to-reserve display"), None),
        ReserveDecl("Dump to Grid stop SOC (example value)", FEATURE_STOP_LEVEL, 10.0, "Dump to Grid Stop SOC control",
                    ("Dump to Grid",), "firmware refuses a stop level below 10 %"),
        ReserveDecl("Inverter protection level (not supplied)", PHYSICAL_PROTECTION, None,
                    "read-only inverter setting", ("inverter",), "inverter", False),
    )
    efficiencies = (
        EfficiencyDecl("HA helper round-trip efficiency", 90.0, "percent", ROUND_TRIP, "input_number.ecco_round_trip_efficiency"),
    )
    capacities = (
        CapacityDecl("HA helper capacity (example)", "CONFIGURED_HELPER", cfg.battery_capacity_kwh, provenance="owner-set helper"),
    )
    if faulty:
        reserves = reserves[:3] + (
            ReserveDecl("Inverter protection level (example)", PHYSICAL_PROTECTION, 20.0, "read-only inverter setting",
                        ("inverter",), "inverter", True),
            ReserveDecl("Planning floor claimed enforced", SOFT_PLANNING_FLOOR, 5.0, "claim", (), "the inverter"),
        )
        efficiencies = (EfficiencyDecl("helper", 95.0, "percent", ROUND_TRIP, "helper"),
                        EfficiencyDecl("flux sqrt", 0.9747, "fraction", ROUND_TRIP, "derived one-way value mislabelled"))
        capacities = (CapacityDecl("helper", "CONFIGURED_HELPER", 28.0), CapacityDecl("learned", "LEARNED_FROM_DISCHARGE", 31.7),
                      CapacityDecl("register", "REGISTER_AH", 300.0, "Ah"), CapacityDecl("wh as kwh", "CONFIGURED_HELPER", 31700.0))
    cutover = datetime(2030, 3, 10, 12, 0, tzinfo=UTC)
    history = (
        HistoryPeriod(LOAD_POWER_MEAN, datetime(2030, 2, 1, tzinfo=UTC), datetime(2030, 3, 10, 12, 0, tzinfo=UTC), 14.0),
        HistoryPeriod(LOAD_POWER_MEAN, datetime(2030, 3, 10, 0, 0, tzinfo=UTC), datetime(2030, 3, 20, tzinfo=UTC)),
        HistoryPeriod(LOAD_ENERGY_COUNTER, datetime(2030, 2, 1, tzinfo=UTC), datetime(2030, 3, 20, tzinfo=UTC)),
    )
    return Declaration(
        cfg=cfg, reserves=reserves, capacities=capacities, efficiencies=efficiencies,
        readings=_example_readings(faulty=faulty), history=history,
        nights=NightSpec(date(2026, 10, 23), date(2026, 10, 27), cfg.cheap_window_start_min, cfg.cheap_window_end_min, tz),
        decisions=OwnerDecisions(hd1_effective_from=None if faulty else cutover),
    )


def _dt(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s)


def declaration_from_dict(d: dict) -> Declaration:
    """Strict loader: unknown keys are an error. Only values written in the file are used."""
    def only(obj: dict, allowed: set[str], what: str) -> dict:
        extra = set(obj) - allowed
        if extra:
            raise ValueError(f"{what}: unknown keys {sorted(extra)}")
        return obj

    only(d, {"cfg", "reserves", "capacities", "efficiencies", "readings", "history", "nights", "decisions"}, "declaration")
    cfg = SiteConfig(**d["cfg"]) if "cfg" in d else SiteConfig()
    o = dict(d.get("decisions", {}))
    if "hd1_effective_from" in o:
        o["hd1_effective_from"] = _dt(o["hd1_effective_from"])
    if o.get("required_signals") is not None:
        o["required_signals"] = tuple(o["required_signals"])
    nights = None
    if d.get("nights"):
        n = dict(d["nights"])
        n["first_night"], n["last_night"] = date.fromisoformat(n["first_night"]), date.fromisoformat(n["last_night"])
        nights = NightSpec(**n)
    return Declaration(
        cfg=cfg,
        reserves=tuple(ReserveDecl(**{**r, "scope": tuple(r.get("scope", ()))}) for r in d.get("reserves", [])),
        capacities=tuple(CapacityDecl(**c) for c in d.get("capacities", [])),
        efficiencies=tuple(EfficiencyDecl(**e) for e in d.get("efficiencies", [])),
        readings=tuple(ReadingDecl(**r) for r in d.get("readings", [])),
        history=tuple(HistoryPeriod(**{**p, "start": _dt(p["start"]), "end": _dt(p["end"])}) for p in d.get("history", [])),
        nights=nights, decisions=OwnerDecisions(**o))


def render_text(rep: Report) -> str:
    lines = [f"{rep.model_version}  mode={rep.mode}  applies_nothing={rep.applies_nothing}", f"VERDICT: {rep.verdict}", ""]
    for sev in (BLOCK, WARN, INFO):
        for f in rep.findings:
            if f.severity == sev:
                lines.append(f"  {sev:5} {f.code:36} {f.subject}: {f.message}")
    lines += ["", "Owner decisions:"]
    lines += [f"  {d.id} [{d.status:8}] {d.title}: {d.question}" for d in rep.decisions]
    lines += ["", f"Thresholds are {rep.thresholds.status}; nothing above is a recommendation."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--example", action="store_true")
    g.add_argument("--example-faulty", action="store_true")
    g.add_argument("--declaration", help="path to a declaration JSON written by hand (synthetic or owner-supplied)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.declaration:
        decl = declaration_from_dict(json.loads(Path(a.declaration).read_text(encoding="utf-8")))
    else:
        decl = example_declaration(faulty=a.example_faulty)
    rep = run(decl)
    print(json.dumps(rep.to_dict(), indent=2, sort_keys=True) if a.json else render_text(rep))
    return 0 if rep.verdict != "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
