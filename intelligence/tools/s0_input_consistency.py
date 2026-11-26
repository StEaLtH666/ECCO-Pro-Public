#!/usr/bin/env python3
"""Intelligence S0 (DRAFT, decisions D1-D9 OPEN): an OFFLINE consistency diagnostic for the inputs a recommendation would rest on
(SHADOW, advisory). It is NOT configured runtime policy and nothing reads its output as configuration.

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

Decisions are the typed register of intelligence/site_decisions.py (internal ids D1..D9, display labels I-D1..I-D9): a
declaration's decisions block is a strict DecisionSet mapping, free text is never RECORDED (it is INVALID and BLOCKs), I-D2
is its own explicit record, I-D7 is retired to code constants (a declaration may only add required signals), and the
reserve roles, proposed thresholds, efficiency normalisation, freshness mirror and gate table come from that module. Night
lengths come from intelligence/periods.py. The check functions below stay in this tool.

Authority: like every Intelligence module this has no write path (tests/test_s0_input_contract.py checks the imports and
the vocabulary). Existing SiteConfig, ecco_core and the V1 / V1.1 outputs are only READ. A report always says
mode SHADOW and applies_nothing true. Design and open questions: docs/intelligence/INTELLIGENCE_S0_INPUT_CONTRACT.md and
docs/intelligence/INTELLIGENCE_FOUNDATION_CONTRACT.md.

    python intelligence/tools/s0_input_consistency.py --example            # synthetic, mostly consistent, decisions open
    python intelligence/tools/s0_input_consistency.py --example-faulty     # synthetic, seeded faults
    python intelligence/tools/s0_input_consistency.py --declaration my.json [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecco_core.state import spec_for  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.explain import FRESH, STALE, UNKNOWN, InputAge, finite_number  # noqa: E402
from intelligence.periods import OK as BOUNDARY_OK, period_profile  # noqa: E402
from intelligence.site_decisions import (  # noqa: E402
    ADVISORY_LIMITS_S, ALL_PROVENANCE, BLOCK, CAPACITY_KINDS, DECISION_IDS, DECISION_QUESTIONS, DECISION_TITLES,
    EXCLUDE, EXCLUDE_PRE_CUTOVER, INFO, ONE_WAY, OWNER_STATEMENT, ROUND_TRIP, WARN, DecisionSet, DecisionStatus, Finding,
    HD1Cutover, ProposedThresholds, Provenance, ReserveRole, display_label, efficiency_round_trip, finding,
    freshness_limits, items_gated_by)
from intelligence.timeutil import UTC  # noqa: E402

MODEL_VERSION = "intel-s0-input-consistency-0.1.0-draft"
MODE = "SHADOW"
STATUS = "DRAFT_S0"
DRAFT_NOTICE = ("DRAFT S0: offline, SHADOW-only, NOT configured runtime policy. Decisions D1-D9 are OPEN unless the caller's own "
                "declaration records them (this repository records none). Every threshold is PROPOSED, not accepted.")
ORIGIN_SYNTHETIC = "SYNTHETIC_EXAMPLE_NOT_SITE_EVIDENCE"
ORIGIN_CALLER = "CALLER_DECLARATION_NOT_VERIFIED_AGAINST_THE_SITE"
PROV_SYNTHETIC, PROV_CALLER = Provenance.SYNTHETIC_EXAMPLE, Provenance.CALLER_DECLARATION_UNVERIFIED
SYNTHETIC_LABEL = "SYNTHETIC EXAMPLE, NOT AN OWNER DECISION"
SYNTHETIC_PREFIX = "[SYNTHETIC] "

OPEN, RECORDED, INVALID = DecisionStatus.OPEN, DecisionStatus.RECORDED, DecisionStatus.INVALID
# the typed register (intelligence.site_decisions.DecisionSet); the S0 name is kept. OwnerDecisions() is all OPEN.
OwnerDecisions = DecisionSet
DECLARATION_SOURCE = "declaration"

# ---- reserve roles (intelligence.site_decisions.ReserveRole; a declaration uses these four) ---------------------------
SOFT_PLANNING_FLOOR = ReserveRole.SOFT_PLANNING_FLOOR    # a preference every recommendation stays above
HA_RESERVE_HELPER = ReserveRole.HA_RESERVE_HELPER        # a Home Assistant helper; an input that can only RAISE the floor
FEATURE_STOP_LEVEL = ReserveRole.FEATURE_STOP_LEVEL      # where one feature stops (for example the Dump to Grid stop SOC)
PHYSICAL_PROTECTION = ReserveRole.PHYSICAL_PROTECTION    # the inverter's own battery protection; ECCO cannot write it
RESERVE_ROLES = (SOFT_PLANNING_FLOOR, HA_RESERVE_HELPER, FEATURE_STOP_LEVEL, PHYSICAL_PROTECTION)

# ---- signal reading kinds ----------------------------------------------------------------------------------------------
RAW, CANONICAL, DERIVED, LEGACY = "RAW", "CANONICAL", "DERIVED", "LEGACY"
READING_KINDS = (RAW, CANONICAL, DERIVED, LEGACY)
NON_NUMERIC_STATES = frozenset({"unavailable", "unknown", "none", "", "nan", "null"})

# Sign conventions the repository already uses (ecco_core.state.SIGNALS): the token a reading must declare.
SIGN_TOKEN = {"battery.power": "discharge_positive", "grid.power": "import_positive"}

# Advisory age limits the project ALREADY defines: the defined entries of site_decisions.ADVISORY_LIMITS_S (the mirror of
# ecco_core.freshness). Anything absent is unresolved and can never be fresh.
DEFINED_ADVISORY_LIMITS_S: dict[str, float] = {k: v for k, v in ADVISORY_LIMITS_S.items() if v is not None}

# History period vocabulary (what a stored series IS, not an entity id).
LOAD_POWER_MEAN, LOAD_ENERGY_COUNTER = "load_power_mean", "load_energy_counter"
HISTORY_SIGNALS = (LOAD_POWER_MEAN, LOAD_ENERGY_COUNTER)
# S0's own required set for a declaration (I-D7 is retired: a declaration may only ADD to it)
BASE_REQUIRED_SIGNALS = ("battery.soc",)


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
class Declaration:
    cfg: SiteConfig = field(default_factory=SiteConfig)
    reserves: tuple[ReserveDecl, ...] = ()
    capacities: tuple[CapacityDecl, ...] = ()
    efficiencies: tuple[EfficiencyDecl, ...] = ()
    readings: tuple[ReadingDecl, ...] = ()
    history: tuple[HistoryPeriod, ...] = ()
    nights: NightSpec | None = None
    decisions: DecisionSet = field(default_factory=lambda: DecisionSet(source=DECLARATION_SOURCE))
    thresholds: ProposedThresholds = field(default_factory=ProposedThresholds)
    synthetic: bool = False                # True only for the built-in examples: every value is fictional, none is site evidence


def _finding_dict(f: Finding) -> dict:
    """S0's JSON form of the shared Finding (the text is called 'message' here, as before)."""
    return {"code": f.code, "severity": f.severity, "subject": f.subject, "message": f.text,
            "evidence": {k: v for k, v in f.evidence}}


@dataclass(frozen=True)
class DecisionState:
    id: str
    title: str
    status: str
    question: str
    blocks: tuple[str, ...]                # the items this decision gates (site_decisions.ITEM_GATES, conditional ones too)
    recorded: object = None
    provenance: str = ""                   # who supplied a RECORDED value: SYNTHETIC_EXAMPLE or CALLER_DECLARATION_UNVERIFIED (empty otherwise)
    problems: tuple[str, ...] = ()         # why an INVALID decision is invalid

    @property
    def label(self) -> str:
        return display_label(self.id)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "title": self.title, "status": self.status, "question": self.question,
                "blocks": list(self.blocks), "recorded": self.recorded, "provenance": self.provenance,
                "problems": list(self.problems)}


@dataclass(frozen=True)
class Report:
    verdict: str                           # BLOCKED | OPEN_DECISIONS | CONSISTENT_WITH_WARNINGS | CONSISTENT
    findings: tuple[Finding, ...]
    decisions: tuple[DecisionState, ...]
    thresholds: ProposedThresholds
    mode: str = MODE
    applies_nothing: bool = True
    model_version: str = MODEL_VERSION
    origin: str = ORIGIN_CALLER
    status: str = STATUS
    notice: str = DRAFT_NOTICE

    def codes(self, severity: str | None = None) -> list[str]:
        return [f.code for f in self.findings if severity is None or f.severity == severity]

    def to_dict(self) -> dict:
        counts = {s: sum(1 for f in self.findings if f.severity == s) for s in (BLOCK, WARN, INFO)}
        return {"model_version": self.model_version, "status": self.status, "notice": self.notice,
                "declaration_origin": self.origin, "mode": self.mode, "applies_nothing": self.applies_nothing,
                "verdict": self.verdict, "counts": counts, "findings": [_finding_dict(f) for f in self.findings],
                "decisions": [d.to_dict() for d in self.decisions],
                "proposed_thresholds": {k.name: _jsonable(getattr(self.thresholds, k.name)) for k in fields(self.thresholds)}}


def _jsonable(v: object) -> object:
    return list(v) if isinstance(v, tuple) else v


def _f(code: str, sev: str, subject: str, message: str, **evidence: object) -> Finding:
    return finding(code, sev, subject, message, **evidence)


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

# efficiency_round_trip (round-trip fraction, one-way fraction, finding when unusable) is site_decisions' (I-D5 uses it too).


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

def effective_limits(decisions: DecisionSet) -> tuple[dict[str, float], list[Finding]]:
    """Defined project limits, tightened (never loosened) by the declaration's I-D6 (site_decisions.freshness_limits, the
    FreshnessPolicy semantics with the 900 s ceiling). An INVALID I-D6 applies nothing; its entries are reported here and the
    decision itself BLOCKs (DECISION_D6_INVALID, reported with the other decisions). The diagnostic judges what the
    declaration says, so every provenance is accepted here; publishing advice never does that."""
    limits, notes = freshness_limits(decisions, ALL_PROVENANCE)
    return ({k: v for k, v in limits.items() if v is not None},
            [n for n in notes if n.code != "DECISION_D6_INVALID"])


def required_signals(decisions: DecisionSet) -> set[str]:
    """S0's base required set plus any signals a RECORDED I-D7 adds (add-only)."""
    out = set(BASE_REQUIRED_SIGNALS)
    d7 = decisions.get("D7")
    if d7.status == RECORDED:
        for sigs in d7.value.add_signals.values():
            out |= set(sigs)
    return out


def _agree(signal: str, a: float, b: float, th: ProposedThresholds) -> bool:
    if signal == "battery.soc":
        return abs(a - b) <= th.soc_agree_points
    if signal.endswith(".power") or ".string_power" in signal:
        return abs(a - b) <= max(th.power_agree_w, th.power_agree_fraction * max(abs(a), abs(b)))
    return abs(a - b) <= th.other_agree_fraction * max(abs(a), abs(b), 1e-9)


def check_readings(readings: tuple[ReadingDecl, ...], owner: DecisionSet, th: ProposedThresholds) -> list[Finding]:
    out: list[Finding] = []
    limits, notes = effective_limits(owner)
    out += notes
    required = required_signals(owner)
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
    """Elapsed hours of one local wall-clock window, and of the local day it starts in (intelligence.periods measures
    both). Raises ValueError for a malformed window and for one with no real length (the spring gap: factor 0)."""
    p = period_profile(night, start_min, end_min, tz_name)
    day_h = period_profile(night, 0, 1440, tz_name).actual_h
    # the window may cross midnight into the next local day, which can be the short/long one
    next_day_h = period_profile(night + timedelta(days=1), 0, 1440, tz_name).actual_h
    return {"night": night.isoformat(), "nominal_hours": p.nominal_h, "actual_hours": p.actual_h,
            "delta_hours": p.actual_h - p.nominal_h, "length_factor": p.factor, "clock_change": p.change_kind,
            "local_day_hours": day_h, "next_local_day_hours": next_day_h,
            "start_boundary": p.start_boundary, "end_boundary": p.end_boundary}


def check_nights(spec: NightSpec | None) -> list[Finding]:
    if spec is None:
        return []
    out: list[Finding] = []
    d = spec.first_night
    while d <= spec.last_night:
        try:
            p = night_profile(d, spec.start_min, spec.end_min, spec.tz)
        except ValueError as exc:
            out.append(_f("NIGHT_WINDOW_HAS_NO_LENGTH", BLOCK, d.isoformat(),
                          "the window has no real length on this night (it lies in the hour skipped when the clocks go "
                          "forward), so no figure for it can be learned or planned", error=str(exc)))
            d += timedelta(days=1)
            continue
        if p["start_boundary"] != BOUNDARY_OK or p["end_boundary"] != BOUNDARY_OK:
            out.append(_f("NIGHT_BOUNDARY_IN_CHANGED_HOUR", BLOCK, p["night"],
                          "a window boundary falls in a repeated or missing local hour (the fixed I-D9 rule)",
                          start_boundary=p["start_boundary"], end_boundary=p["end_boundary"]))
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
    """One state per decision, read from the typed register. A decision's `blocks` are the items site_decisions.ITEM_GATES
    (with the conditional I-D4 / I-D9 items) says it gates. A RECORDED decision of a synthetic declaration is always shown
    as SYNTHETIC_EXAMPLE."""
    out = []
    for did in DECISION_IDS:
        d = decl.decisions.get(did)
        prov = ""
        if d.status == RECORDED:
            prov = PROV_SYNTHETIC if decl.synthetic else (d.provenance or "")
        out.append(DecisionState(did, DECISION_TITLES[did], d.status, DECISION_QUESTIONS[did], items_gated_by(did),
                                 d.recorded_json(), prov, d.problems))
    return tuple(out)


def check_decisions(decl: Declaration) -> list[Finding]:
    """An INVALID decision BLOCKs (free text, an incomplete record or a refused provenance is never RECORDED); an explicit
    I-D2 owner statement must agree with a declared PHYSICAL_PROTECTION level."""
    out: list[Finding] = []
    for did in DECISION_IDS:
        d = decl.decisions.get(did)
        if d.status == INVALID:
            out.append(finding(f"DECISION_{did}_INVALID", BLOCK, display_label(did),
                               f"{display_label(did)} ({DECISION_TITLES[did]}) is INVALID: " + "; ".join(d.problems)))
    d2 = decl.decisions.get("D2")
    if d2.status == RECORDED and d2.value.supplied_by == OWNER_STATEMENT:
        for r in decl.reserves:
            v = _num(r.value_pct)
            if r.role == PHYSICAL_PROTECTION and v is not None and abs(v - float(d2.value.value_pct)) > 1e-9:
                out.append(_f("PROTECTION_RECORD_MISMATCH", BLOCK, r.name,
                              "the declared protection level differs from the I-D2 owner statement",
                              declared_pct=v, recorded_pct=float(d2.value.value_pct)))
    return out


def _band_pct(decisions: DecisionSet) -> float | None:
    d4 = decisions.get("D4")
    return float(d4.value.pct) if d4.status == RECORDED else None


def _cutover(decisions: DecisionSet) -> datetime | None:
    d8 = decisions.get("D8")
    return d8.value.cutover if d8.status == RECORDED else None


def run(decl: Declaration) -> Report:
    findings: list[Finding] = []
    findings += check_reserves(decl.reserves, decl.cfg)
    findings += check_capacity(decl.capacities, decl.cfg, decl.thresholds, _band_pct(decl.decisions))
    findings += check_efficiency(decl.efficiencies, decl.cfg, decl.thresholds)
    findings += check_readings(decl.readings, decl.decisions, decl.thresholds)
    findings += classify_history(decl.history, _cutover(decl.decisions))
    findings += check_nights(decl.nights)
    findings += check_decisions(decl)
    decisions = decision_states(decl)
    if any(f.severity == BLOCK for f in findings):
        verdict = "BLOCKED"
    elif any(d.status == OPEN and d.id != "D7" for d in decisions):      # I-D7 is retired: OPEN means "no additions"
        verdict = "OPEN_DECISIONS"
    elif any(f.severity == WARN for f in findings):
        verdict = "CONSISTENT_WITH_WARNINGS"
    else:
        verdict = "CONSISTENT"
    return Report(verdict, tuple(findings), decisions, decl.thresholds,
                  origin=ORIGIN_SYNTHETIC if decl.synthetic else ORIGIN_CALLER)


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
        ReserveDecl("HA reserve helper (fictional value)", HA_RESERVE_HELPER, 25.0, "input_number.ecco_minimum_reserve_soc",
                    ("Intelligence input", "advanced-config bound", "time-to-reserve display"), None),
        ReserveDecl("Dump to Grid stop SOC (fictional value)", FEATURE_STOP_LEVEL, 15.0, "Dump to Grid Stop SOC control",
                    ("Dump to Grid",), "firmware refuses a stop level below 10 %"),
        ReserveDecl("Inverter protection level (not supplied)", PHYSICAL_PROTECTION, None,
                    "read-only inverter setting", ("inverter",), "inverter", False),
    )
    efficiencies = (
        EfficiencyDecl("HA helper round-trip efficiency", 90.0, "percent", ROUND_TRIP, "input_number.ecco_round_trip_efficiency"),
    )
    capacities = (
        CapacityDecl("HA helper capacity (fictional)", "CONFIGURED_HELPER", cfg.battery_capacity_kwh, provenance="fictional example helper"),
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
    decl = Declaration(
        cfg=cfg, reserves=reserves, capacities=capacities, efficiencies=efficiencies,
        readings=_example_readings(faulty=faulty), history=history,
        nights=NightSpec(date(2026, 10, 23), date(2026, 10, 27), cfg.cheap_window_start_min, cfg.cheap_window_end_min, tz),
        decisions=_example_decisions(None if faulty else cutover),
        synthetic=True,
    )
    return _label_synthetic(decl)


def _example_decisions(cutover: datetime | None) -> DecisionSet:
    """The built-in example records only a fictional I-D8 (a 2030 cut-over with the conservative EXCLUDE policies),
    labelled SYNTHETIC_EXAMPLE; everything else stays OPEN."""
    ds = DecisionSet(source=DECLARATION_SOURCE)
    if cutover is None:
        return ds
    return ds.with_decision("D8", HD1Cutover(cutover, EXCLUDE, EXCLUDE_PRE_CUTOVER), Provenance.SYNTHETIC_EXAMPLE)


def _label_synthetic(decl: Declaration) -> Declaration:
    """Prefix every named item of a built-in example so that no line of its output can be mistaken for site data. The
    fictional values are: reserve helper and Dump stop (not the site's), the year 2030 history and cut-over, and made-up readings.
    (SiteConfig's own shipped example defaults and the real UK clock-change dates are calendar / code facts, not site data.)"""
    def tag(name: str) -> str:
        return name if name.startswith(SYNTHETIC_PREFIX) else SYNTHETIC_PREFIX + name
    return replace(
        decl,
        reserves=tuple(replace(r, name=tag(r.name)) for r in decl.reserves),
        capacities=tuple(replace(c, name=tag(c.name)) for c in decl.capacities),
        efficiencies=tuple(replace(e, name=tag(e.name)) for e in decl.efficiencies),
        readings=tuple(replace(r, source_id=("synthetic:" + r.source_id) if not r.source_id.startswith("synthetic:") else r.source_id)
                       for r in decl.readings))


def _dt(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s)


def declaration_from_dict(d: dict) -> Declaration:
    """Strict loader: unknown keys are an error. Only values written in the file are used. The `decisions` block is a
    site_decisions DecisionSet mapping (keys D<n> or I-D<n>; typed values; free text is INVALID)."""
    def only(obj: dict, allowed: set[str], what: str) -> dict:
        extra = set(obj) - allowed
        if extra:
            raise ValueError(f"{what}: unknown keys {sorted(extra)}")
        return obj

    only(d, {"cfg", "reserves", "capacities", "efficiencies", "readings", "history", "nights", "decisions", "synthetic_example"},
         "declaration")
    cfg = SiteConfig(**d["cfg"]) if "cfg" in d else SiteConfig()
    decisions = DecisionSet.from_mapping(d.get("decisions", {}), source=DECLARATION_SOURCE)
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
        nights=nights, decisions=decisions, synthetic=bool(d.get("synthetic_example", False)))


def render_text(rep: Report) -> str:
    lines = [f"{rep.model_version}  status={rep.status}  mode={rep.mode}  applies_nothing={rep.applies_nothing}", rep.notice,
             f"Declaration origin: {rep.origin}"]
    if rep.origin == ORIGIN_SYNTHETIC:
        lines.append("*** SYNTHETIC EXAMPLE: every value below is fictional. It is not site evidence and not an owner decision. ***")
    lines += [f"VERDICT: {rep.verdict}", ""]
    for sev in (BLOCK, WARN, INFO):
        for f in rep.findings:
            if f.severity == sev:
                lines.append(f"  {sev:5} {f.code:36} {f.subject}: {f.message}")
    lines += ["", "Owner decisions:"]
    for d in rep.decisions:
        tag = d.status if not (d.status == RECORDED and d.provenance == PROV_SYNTHETIC) else f"{d.status} - {SYNTHETIC_LABEL}"
        lines.append(f"  {d.id} {d.label} [{tag:8}] {d.title}: {d.question}")
    lines += ["", f"Thresholds are {rep.thresholds.status}; nothing above is a recommendation."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--example", action="store_true", help="a SYNTHETIC example with fictional values (not site data)")
    g.add_argument("--example-faulty", action="store_true", help="a SYNTHETIC example with seeded faults (not site data)")
    g.add_argument("--declaration", help="path to a declaration JSON written by hand; its values are not verified against the site by this tool")
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
