"""The S1 offline advice harness (PROTOTYPE, SHADOW, applies nothing).

`run_harness(scenario)` turns explicit mock records into a typed report built from the EXISTING Intelligence V1.1 advisors
(overnight demand, charge target, export event, Dump-to-Grid stop level) and a summary of the V1 engine's shadow report. It
adds three things around them, and changes none of them:

  1. an input gate: malformed, duplicated, future or non-finite records are excluded and listed; a stale history, an
     invalid or missing tariff, an invalid decision, an input without a fresh value under its own freshness limit or a
     capacity mismatch withholds what depends on it;
  2. the Intelligence decision gates D1-D9 (display labels I-D1..I-D9) of intelligence/site_decisions.py, the single
     source of truth: an item whose arithmetic depends on an OPEN, INVALID or unaccepted decision is BLOCKED with the
     decision named, and carries no number. The effective SiteConfig comes only from site_decisions.apply_to_siteconfig
     (never the shipped example's capacity, efficiency, reserve, grid-charge limit or window). Clock-change periods and
     the cheap windows are measured by intelligence/periods.py. The harness never fills an open decision with a
     convenient default;
  3. one report shape: every item has a status (OK / INSUFFICIENT_DATA / BLOCKED), confidence, explanation, assumptions and
     input ages, and the whole report is mode SHADOW and applies_nothing true.

Decisions count only with provenance SYNTHETIC_TEST: the harness passes accept_provenance={SYNTHETIC_TEST} to every
site_decisions call explicitly and refuses any wider set. It schedules nothing, decides nothing for the battery and sends
nothing anywhere. It is a prototype for review, not production runtime and not configured policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Mapping

from ...advisor import STALE_SOC_SECONDS, LiveInputs, TariffInfo
from ...charge_target import ChargeTargetInputs, advise_charge_target
from ...config import SiteConfig
from ...dump_advice import DumpInputs, advise_dump
from ...engine import IntelligenceEngine
from ...events import EventInputs, ExportEvent, advise_event
from ...explain import BLOCKED, OK, Advice, Blocker, InputAge, Reason, blocked, finite_number
from ...history import History, HourRecord
from ...overnight import OvernightSettings, learn_overnight, nightly_totals
from ...periods import PeriodProfile, period_profile
from ...site_decisions import (BLOCK as FINDING_BLOCK, CHARGE_WINDOW_KEY, CONDITIONAL_D4_ITEMS, DECISION_IDS,
                               DECISION_TITLES, EXCLUDE, EXCLUDE_CHANGED_PERIODS, EXCLUDE_PRE_CUTOVER, ITEM_GATES,
                               KEEP_NON_EXPORTING_ONLY, OWNER_STATEMENT, SCALE_TO_ACTUAL, Decision, DecisionSet,
                               DecisionStatus, Finding, GateContext, InputState, Provenance, ReserveRole,
                               apply_to_siteconfig, capacity_context, decide, display_label, freshness_limits, gate,
                               normalise_id)
from ...timeutil import HOUR, UTC, local_wall, ts, zone
from .scenario import DecisionRecord, Observation, Scenario

PROTOTYPE_VERSION = "intel-s1-offline-advice-0.2.0-prototype"
MODE = "SHADOW"
NOTICE = ("PROTOTYPE S1 offline advice harness: explicit synthetic / offline inputs only; SHADOW, applies nothing; not production "
          "runtime and not configured policy. Intelligence decisions D1-D9 (I-D1..I-D9) belong to the owner: an OPEN "
          "decision withholds every item that depends on it.")
SYNTHETIC_TEST = Provenance.SYNTHETIC_TEST
S1_ACCEPT_PROVENANCE = frozenset({SYNTHETIC_TEST})      # the only provenance this prototype ever accepts

KINDS = ("overnight_demand", "charge_target", "export_event", "dump_to_grid", "v1_report_summary")
_CONTRACT_ITEM = MappingProxyType({"v1_report_summary": "v1_summary"})   # the S1 kind -> its site_decisions item
# Which decisions each item's arithmetic rests on: a view of site_decisions.ITEM_GATES (never a copy). I-D4 is added when
# two or more capacity sources are present, and I-D9 when the item's period, or a period in its learning history, crosses a
# clock change. The prototype is stricter than the register for I-D9: export and Dump advice learn period demand too, so
# they need I-D9 under the same rule, and an INVALID I-D9 withholds them as well.
GATES: Mapping[str, tuple[str, ...]] = MappingProxyType({k: ITEM_GATES[_CONTRACT_ITEM.get(k, k)] for k in KINDS})
D9_LEARNING_KINDS = ("overnight_demand", "charge_target", "export_event", "dump_to_grid")


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str           # BLOCK | WARN | INFO
    text: str

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "text": self.text}


@dataclass(frozen=True)
class Item:
    kind: str
    status: str                                 # OK | INSUFFICIENT_DATA | BLOCKED
    advice: dict | None                         # the V1.1 Advice.to_dict() (or the V1 summary); None when withheld
    withheld_because: tuple[Blocker, ...] = ()
    decisions_used: tuple[str, ...] = ()
    decision_provenance: str | None = None      # SYNTHETIC_TEST when any decision it used was synthetic
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"kind": self.kind, "status": self.status, "mode": MODE, "applies_nothing": True, "advice": self.advice,
                "withheld_because": [b.to_dict() for b in self.withheld_because],
                "decisions_used": list(self.decisions_used), "decision_provenance": self.decision_provenance,
                "notes": list(self.notes)}


@dataclass(frozen=True)
class Report:
    items: tuple[Item, ...]
    issues: tuple[Issue, ...]
    decisions: tuple[dict, ...]
    reserve_semantics: tuple[dict, ...]
    data_quality: dict
    inputs: tuple[dict, ...]
    now: str
    label: str
    accept_provenance: tuple[str, ...] = (SYNTHETIC_TEST,)
    mode: str = MODE
    applies_nothing: bool = True
    version: str = PROTOTYPE_VERSION
    notice: str = NOTICE

    def item(self, kind: str) -> Item | None:
        return next((i for i in self.items if i.kind == kind), None)

    def to_dict(self) -> dict:
        d = {"version": self.version, "notice": self.notice, "mode": self.mode, "applies_nothing": self.applies_nothing,
             "now": self.now, "label": self.label, "accept_provenance": list(self.accept_provenance),
             "items": [i.to_dict() for i in self.items], "issues": [i.to_dict() for i in self.issues],
             "decisions": list(self.decisions), "reserve_semantics": list(self.reserve_semantics),
             "data_quality": self.data_quality, "inputs": list(self.inputs)}
        json.dumps(d, allow_nan=False)            # strict JSON or a loud ValueError, never NaN in a report
        return d


# ---------------------------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------------------------

def _aware(x: object) -> bool:
    return isinstance(x, datetime) and x.tzinfo is not None and x.utcoffset() is not None


def _num(x: object) -> float | None:
    return float(x) if finite_number(x) else None


def _age(obs: Observation | None, now: datetime) -> float | None:
    """Age in seconds; None when unknown. A future observation is reported as a negative age, which InputAge reads as unknown."""
    if obs is None or not _aware(getattr(obs, "observed_at", None)):
        return None
    return (now - obs.observed_at).total_seconds()


def _wall_minutes(t: datetime, day: date, tz) -> int:
    """Local wall-clock minutes of `t` counted from local midnight of `day` (may exceed 1440)."""
    lt = t.astimezone(tz)
    return (lt.date() - day).days * 1440 + lt.hour * 60 + lt.minute


def _item(kind: str) -> str:
    return _CONTRACT_ITEM.get(kind, kind)


def _accept(accept_provenance) -> frozenset:
    acc = frozenset(accept_provenance)
    if not acc <= S1_ACCEPT_PROVENANCE:
        raise ValueError("the S1 prototype accepts only SYNTHETIC_TEST decisions; an owner decision is recorded outside it")
    return acc


# ---------------------------------------------------------------------------------------------------------------------
# 1. decisions (site_decisions) -> per-signal freshness limits and an effective SiteConfig (or the reasons why not)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionStates:
    """The scenario's decisions as a site_decisions DecisionSet, the accepted provenance, the I-D6 freshness limits per
    signal / reading, and one report row per decision."""
    dset: DecisionSet
    accept: frozenset
    limits: Mapping[str, float | None]
    limit_findings: tuple[Finding, ...]
    rows: Mapping[str, dict]

    def ok(self, did: str) -> bool:
        """Satisfied: RECORDED, valid and with an accepted provenance."""
        return self.dset.satisfied(did, self.accept)

    def status(self, did: str) -> str:
        return self.dset.status(did)

    def value(self, did: str) -> object:
        return self.dset.value(did)

    def code(self, did: str) -> str:
        """The finding code of a decision that is not satisfied (INVALID, else OPEN)."""
        return f"DECISION_{did}_INVALID" if self.status(did) == DecisionStatus.INVALID else f"DECISION_{did}_OPEN"

    def why(self, did: str) -> str:
        if self.status(did) == DecisionStatus.INVALID:
            return "INVALID"
        if self.status(did) == DecisionStatus.RECORDED and not self.ok(did):
            return "not accepted (provenance)"
        return self.status(did)


def _decision_set(sc: Scenario, issues: list[Issue]) -> DecisionSet:
    if isinstance(sc.decisions, DecisionSet):
        return sc.decisions
    built: dict[str, Decision] = {}
    entries = sc.decisions.items() if isinstance(sc.decisions, Mapping) else ()
    if not isinstance(sc.decisions, Mapping):
        issues.append(Issue("DECISIONS_MALFORMED", "BLOCK", "the scenario decisions are not a mapping; every decision is OPEN"))
    for k, rec in entries:
        did = normalise_id(k)
        if did is None:
            issues.append(Issue("UNKNOWN_DECISION_ID", "WARN", f"{k!r} is not one of {DECISION_IDS} (or I-D1..I-D9); ignored"))
            continue
        if did in built:
            issues.append(Issue("DECISION_GIVEN_TWICE", "BLOCK", f"{display_label(did)} is given twice; it is INVALID"))
            built[did] = Decision(did, DecisionStatus.INVALID, problems=("given twice",))
            continue
        if not isinstance(rec, DecisionRecord):
            issues.append(Issue("DECISION_RECORD_INVALID", "BLOCK", f"{did}: {rec!r} is not a DecisionRecord; it is INVALID"))
            built[did] = Decision(did, DecisionStatus.INVALID, problems=("not a DecisionRecord",))
            continue
        if rec.provenance != SYNTHETIC_TEST:
            issues.append(Issue("DECISION_PROVENANCE_REFUSED", "BLOCK",
                                f"{did}: provenance {rec.provenance!r} refused; this prototype accepts only SYNTHETIC_TEST "
                                "values, an owner decision is recorded outside it"))
        built[did] = decide(did, rec.value, rec.provenance, None, "test")
    return DecisionSet(built, "test")


def _decision_states(sc: Scenario, issues: list[Issue], *,
                     accept_provenance=S1_ACCEPT_PROVENANCE) -> DecisionStates:
    acc = _accept(accept_provenance)
    dset = _decision_set(sc, issues)
    limits, lim_findings = freshness_limits(dset, accept_provenance=acc)
    rows: dict[str, dict] = {}
    for did in DECISION_IDS:
        d = dset.get(did)
        ok = dset.satisfied(did, acc)
        if d.status == DecisionStatus.INVALID:
            issues.append(Issue("INVALID_DECISION_VALUE", "BLOCK", f"{did} ({display_label(did)}): "
                                + "; ".join(d.problems) + " - it is INVALID and withholds every item it can gate"))
        rows[did] = {"id": did, "label": display_label(did), "title": DECISION_TITLES[did], "status": d.status,
                     "satisfied": ok, "provenance": d.provenance, "value": d.recorded_json(),
                     "problems": list(d.problems)}
    rows["D4"]["effect"] = ("needed only when two or more capacity sources are present (the stated I-D3 value and the "
                            "scenario's capacity sources); OPEN then withholds the battery items")
    rows["D7"]["effect"] = ("retired: the required inputs are the code constants REQUIRED_SIGNALS / REQUIRED_READINGS "
                            "(a site may only add); not consulted by this prototype, whose scenarios carry no power "
                            "observations: the advisors' own input requirements apply. Residual divergence: export and "
                            "Dump advice are given without the stop.dump_soc_pct and tariff.export_rates readings and the "
                            "house / PV / battery / grid power signals the register requires; the SHADOW cycle must "
                            "enforce them")
    for f in lim_findings:
        issues.append(Issue(f.code, f.severity, f"{f.subject}: {f.text}"))
    return DecisionStates(dset, acc, limits, tuple(lim_findings), MappingProxyType(rows))


def _judge(key: str, obs: Observation | None, now: datetime, limit: float | None) -> InputState:
    """One input judged under its own I-D6 / defined limit: fresh only with a known, non-future age within a defined limit."""
    if obs is None:
        return InputState(key, None, False, None, limit)
    age = _age(obs, now)
    age = age if age is not None and age >= 0.0 else None
    return InputState(key, obs.value, age is not None and limit is not None and age <= limit, age, limit)


def _judged_readings(sc: Scenario, states: DecisionStates) -> dict[str, InputState]:
    """The judged inputs apply_to_siteconfig may read: the reserve helper, the grid-charge limit and the charge window
    (the scenario's declared tariff window, standing in for the charge-window source as observed at `now`)."""
    out = {"reserve.ha_minimum_soc": _judge("reserve.ha_minimum_soc", sc.ha_reserve_helper, sc.now,
                                            states.limits.get("reserve.ha_minimum_soc")),
           "limits.max_grid_charge_w": _judge("limits.max_grid_charge_w", sc.grid_charge_limit_w, sc.now,
                                              states.limits.get("limits.max_grid_charge_w"))}
    t = sc.tariff
    if t is not None:
        lim = states.limits.get("tariff.import_rates")
        out[CHARGE_WINDOW_KEY] = InputState(CHARGE_WINDOW_KEY, (t.cheap_start_min, t.cheap_end_min), lim is not None,
                                            0.0, lim)
    return out


def _effective(sc: Scenario, states: DecisionStates) -> tuple[SiteConfig | None, list[Finding]]:
    return apply_to_siteconfig(sc.cfg, states.dset, _judged_readings(sc, states), accept_provenance=states.accept)


def _config_issues(sc: Scenario, findings: list[Finding], issues: list[Issue]) -> None:
    for f in findings:
        if f.code.startswith("DECISION_"):
            continue                                    # the decision rows and the item gates name these
        issues.append(Issue(f.code, f.severity, f"{f.subject}: {f.text}"))
        if f.code == "CHARGE_WINDOW_UNKNOWN" and sc.tariff is not None:
            s, e = sc.tariff.cheap_start_min, sc.tariff.cheap_end_min
            if isinstance(s, int) and isinstance(e, int) and not s < e:
                issues.append(Issue("CHARGE_WINDOW_CROSSES_MIDNIGHT", "BLOCK",
                                    "the declared window crosses local midnight; the foundation contract carries only a "
                                    "window within one local day into SiteConfig, so the battery items are withheld"))


def _effective_cfg(sc: Scenario, states: DecisionStates, issues: list[Issue]) -> tuple[SiteConfig | None, set[str]]:
    """The effective SiteConfig: a thin wrapper over site_decisions.apply_to_siteconfig (satisfied I-D1 / I-D2 / I-D3 /
    I-D5, the judged grid-charge limit, reserve helper and charge window). Returns (cfg or None, decisions that are
    INVALID)."""
    cfg, findings = _effective(sc, states)
    _config_issues(sc, findings, issues)
    return cfg, {d for d in ("D1", "D2", "D3", "D5") if states.status(d) == DecisionStatus.INVALID}


_CAPACITY_BAND_CODES = ("CAPACITY_MISMATCH_BEYOND_BAND", "CAPACITY_MISMATCH_UNKNOWN")


def _capacity_check(cfg: SiteConfig | None, sc: Scenario, states: DecisionStates, issues: list[Issue]
                    ) -> tuple[bool, GateContext]:
    """(False when the capacity sources disagree beyond a SATISFIED I-D4 band or no configuration exists, the gate
    context). The sources are the capacity in use (I-D3: the effective SiteConfig's, else a satisfied stated value) and
    the scenario's capacity sources, all in kWh, counted and compared by site_decisions.capacity_context. The band check
    itself is the register's (site_decisions.gate: CAPACITY_MISMATCH_BEYOND_BAND / _UNKNOWN); the prototype does no band
    arithmetic of its own and only mirrors that finding as its CAPACITY_MISMATCH issue and blocker. With two or more
    sources present an OPEN I-D4 BLOCKs in the gate; no band is ever assumed."""
    d3 = states.value("D3") if states.ok("D3") else None
    stated = d3.value_kwh if d3 is not None and not d3.resolve_at_run else None
    values = [cfg.battery_capacity_kwh] if cfg is not None else ([float(stated)] if finite_number(stated) else [])
    for name, kwh in sc.capacity_sources:
        v = _num(kwh)
        if v is None or v <= 0.0:
            issues.append(Issue("CAPACITY_SOURCE_INVALID", "WARN", f"capacity source {name!r} = {kwh!r} is not a positive number"))
            continue
        values.append(v)
    n, worst = capacity_context(values)
    ctx = GateContext(capacity_sources=n, capacity_mismatch_pct=worst)
    if cfg is None:
        return False, ctx
    found = [f for f in gate("charge_target", states.dset, ctx, accept_provenance=states.accept)
             if f.code in _CAPACITY_BAND_CODES]
    for f in found:
        ev = dict(f.evidence)
        diff, band = (f"{ev[k]:.1f}" if finite_number(ev.get(k)) else "unknown" for k in ("difference_pct", "band_pct"))
        issues.append(Issue("CAPACITY_MISMATCH", "BLOCK",
                            f"{f.code}: {f.text} (largest difference {diff} %, band {band} %, SYNTHETIC_TEST value of "
                            "I-D4): battery arithmetic withheld"))
    return not found, ctx


# ---------------------------------------------------------------------------------------------------------------------
# 2. history: input gate
# ---------------------------------------------------------------------------------------------------------------------

def _build_history(sc: Scenario, states: DecisionStates, issues: list[Issue]) -> tuple[History, dict]:
    now = sc.now
    seen: dict[int, int] = {}
    good: dict[int, HourRecord] = {}
    counts = {"supplied": len(sc.hours), "malformed": 0, "duplicate_hours": 0, "future_or_incomplete": 0,
              "pre_cutover_load_excluded": 0, "pre_cutover_load_power_excluded": 0, "accepted": 0}
    pol = states.value("D8") if states.ok("D8") else None          # a satisfied, typed HD1Cutover only
    cut = None if pol is None else ts(pol.cutover.astimezone(UTC))
    for h in sc.hours:
        start = getattr(h, "start", None)
        load, pv, soc = getattr(h, "load_kwh", None), getattr(h, "pv_kwh", None), getattr(h, "soc_mean", None)
        if not _aware(start) or start.minute or start.second or start.microsecond:
            counts["malformed"] += 1
            continue
        s = ts(start)
        if s % HOUR:
            counts["malformed"] += 1
            continue
        bad_e = (load is not None and not (finite_number(load) and 0.0 <= load <= sc.cfg.max_hourly_kwh)) or \
                (pv is not None and not (finite_number(pv) and 0.0 <= pv <= sc.cfg.max_hourly_kwh))
        bad_soc = soc is not None and not (finite_number(soc) and 0.0 <= soc <= 100.0)
        if bad_e or bad_soc or load is None:
            counts["malformed"] += 1
            continue
        seen[s] = seen.get(s, 0) + 1
        if s + HOUR > ts(now):
            counts["future_or_incomplete"] += 1
            continue
        r = HourRecord(start=s)
        r.e["load"] = float(load)
        if pv is not None:
            r.e["pv"] = float(pv)
            r.pv_w_mean = float(pv) * 1000.0
        r.load_w_mean = float(load) * 1000.0
        r.soc_mean = None if soc is None else float(soc)
        if cut is not None and s < cut:                  # an hour that begins before the I-D8 cut-over
            # load power: EXCLUDE drops it; KEEP_NON_EXPORTING_ONLY keeps it only for an hour with a recorded zero
            # export, which a mock hour never has. Load energy (what learning uses): EXCLUDE_PRE_CUTOVER drops it.
            if pol.load_power_policy in (EXCLUDE, KEEP_NON_EXPORTING_ONLY):
                r.load_w_mean = None
                counts["pre_cutover_load_power_excluded"] += 1
            if pol.load_counter_policy == EXCLUDE_PRE_CUTOVER:
                del r.e["load"]
                counts["pre_cutover_load_excluded"] += 1
        good[s] = r
    dup = {s for s, c in seen.items() if c > 1}
    counts["duplicate_hours"] = sum(seen[s] for s in dup)
    for s in dup:
        good.pop(s, None)                              # a duplicated hour is ambiguous: neither copy is used
    counts["accepted"] = len(good)
    hist = History(good.values())
    if counts["malformed"]:
        issues.append(Issue("MALFORMED_HOURS_EXCLUDED", "WARN", f"{counts['malformed']} hour record(s) were malformed "
                            "(naive or unaligned time, missing / non-finite / negative / implausible energy, SOC outside 0-100) "
                            "and were excluded"))
    if dup:
        issues.append(Issue("DUPLICATE_HOURS_EXCLUDED", "WARN", f"{len(dup)} hour(s) appeared more than once; every copy was excluded"))
    if counts["future_or_incomplete"]:
        issues.append(Issue("FUTURE_HOURS_EXCLUDED", "INFO", f"{counts['future_or_incomplete']} record(s) end after `now` and were "
                            "not used (no leakage)"))
    limit = states.limits.get("history.hourly")
    newest = max(good) if good else None
    age = None if newest is None else ts(now) - (newest + HOUR)
    stale = age is None or limit is None or age > limit
    dq = dict(counts)
    dq.update({"newest_complete_hour_end": None if newest is None else datetime.fromtimestamp(newest + HOUR, UTC).isoformat(),
               "history_age_s": age, "history_limit_s": limit, "history_fresh": not stale,
               "d8_policy": None if pol is None else {"load_power_policy": pol.load_power_policy,
                                                      "load_counter_policy": pol.load_counter_policy},
               "note": "synthetic / offline records only; no quality claim about real data"})
    if stale:
        issues.append(Issue("STALE_HISTORY", "BLOCK", "the newest complete hour is missing or older than the history "
                            "limit (6 h, or tighter under I-D6): learning is withheld"))
    return hist, dq


# ---------------------------------------------------------------------------------------------------------------------
# 3. tariff
# ---------------------------------------------------------------------------------------------------------------------

def _tariff_ok(sc: Scenario, issues: list[Issue]) -> bool:
    t = sc.tariff
    if t is None:
        issues.append(Issue("NO_TARIFF", "BLOCK", "no tariff window was supplied; none is assumed"))
        return False
    probs = []
    for name in ("cheap_start_min", "cheap_end_min"):
        v = getattr(t, name)
        if not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1440):
            probs.append(f"{name} {v!r} is not an integer minute 0-1439")
    if not probs:
        length = (t.cheap_end_min - t.cheap_start_min) % 1440
        if length == 0:
            probs.append("the cheap window has zero length")
        elif length > 23 * 60:
            probs.append("the cheap window is longer than 23 hours")
    rates = {k: getattr(t, k) for k in ("import_cheap_p", "import_peak_p", "export_p")}
    for k, v in rates.items():
        if v is not None and not finite_number(v):
            probs.append(f"{k} {v!r} is not a finite number")
    c, p = rates["import_cheap_p"], rates["import_peak_p"]
    if finite_number(c) and finite_number(p) and c > p:
        probs.append(f"the cheap rate {c:g} is above the peak rate {p:g}")
    for p_ in probs:
        issues.append(Issue("INVALID_TARIFF", "BLOCK", p_))
    if not probs:
        issues.append(Issue("CHARGE_WINDOW_FROM_DECLARED_TARIFF", "WARN",
                            "the charge window is the scenario's declared (synthetic) tariff window, not a verified "
                            "tariff and not the SiteConfig example window"))
    return not probs


def _window_on(day: date, sc: Scenario, tz) -> tuple[datetime, datetime]:
    s, e = sc.tariff.cheap_start_min, sc.tariff.cheap_end_min
    return local_wall(day, s, tz), local_wall(day, e if e > s else e + 1440, tz)


def _next_window_day(sc: Scenario, tz) -> date:
    """The local date whose cheap window is the next one to end after `now`."""
    d = sc.now.astimezone(tz).date() - timedelta(days=1)
    for k in range(4):
        _, w1 = _window_on(d + timedelta(days=k), sc, tz)
        if w1 > sc.now:
            return d + timedelta(days=k)
    raise AssertionError("unreachable: a window ends within four days")


def _next_window(sc: Scenario, tz) -> tuple[datetime, datetime]:
    return _window_on(_next_window_day(sc, tz), sc, tz)


def _window_profile(day: date, sc: Scenario, tz) -> PeriodProfile | None:
    """periods.period_profile of the declared cheap window on `day` (None when it refuses the window)."""
    s, e = sc.tariff.cheap_start_min, sc.tariff.cheap_end_min
    return _profile(day, s, e if e > s else e + 1440, tz)


def _window_dst(days, sc: Scenario, tz) -> tuple[bool, bool]:
    """(boundary, changed) over the cheap windows an item uses, measured by periods.period_profile: `boundary` when a
    window starts or ends in a repeated or missing local hour, or periods refuses it (the fixed rule, whatever I-D9 says);
    `changed` when a window crosses a clock change (I-D9 in scope)."""
    boundary = changed = False
    for day in dict.fromkeys(days):
        p = _window_profile(day, sc, tz)
        boundary = boundary or p is None or p.boundary_in_changed_hour
        changed = changed or (p is not None and p.changed)
    return boundary, changed


def _window_blocker(days, sc: Scenario, tz, what: str) -> list[Blocker]:
    """[DST_BOUNDARY_IN_CHANGED_HOUR] when one of the cheap windows on `days` starts or ends in a repeated or missing
    local hour (or periods refuses it), else []."""
    if not _window_dst(days, sc, tz)[0]:
        return []
    return [Blocker("DST_BOUNDARY_IN_CHANGED_HOUR", f"the {what} cheap window starts or ends inside the repeated or missing "
                    "hour of a clock change, so it is not a recurring local wall-clock window; withheld whatever I-D9 "
                    "says")]


# ---------------------------------------------------------------------------------------------------------------------
# 4. period demand (existing learner) with the I-D9 clock-change rule (periods measure; site_decisions decides)
# ---------------------------------------------------------------------------------------------------------------------

def _profile(day: date, start_min: int, end_min: int, tz) -> PeriodProfile | None:
    """periods.period_profile, or None when it refuses the window (no real length, wholly in the gap, malformed)."""
    try:
        return period_profile(day, start_min, end_min, tz)
    except ValueError:
        return None


def _period_lengths(day: date, start_min: int, end_min: int, tz) -> tuple[float, float]:
    """(nominal, actual) hours of a local window: a thin wrapper over periods.period_profile (actual 0.0 when refused)."""
    p = _profile(day, start_min, end_min, tz)
    return (end_min - start_min) / 60.0, (0.0 if p is None else p.actual_h)


def learn_period(hist: History, cfg: SiteConfig, t0: datetime, t1: datetime, sc: Scenario, states: DecisionStates,
                 kind_note: str) -> tuple[Advice, tuple[str, ...], list[str]]:
    """Planning demand for [t0, t1) via the EXISTING nightly_totals + learn_overnight, on the same local wall-clock window
    of past days within OvernightSettings.lookback_nights. Returns (advice, extra decisions used, notes). Never raises on a
    valid aware period.

    Clock changes (measured by intelligence/periods.py): a period whose start or end falls in a repeated or missing local
    hour BLOCKs whatever I-D9 says (fixed rule, DST_BOUNDARY_IN_CHANGED_HOUR). A period that crosses a change, or a
    learning history that contains such periods, depends on I-D9: while I-D9 is OPEN, INVALID or not accepted it is
    BLOCKED; with I-D9 satisfied its history rule is applied (EXCLUDE_CHANGED_PERIODS or NORMALISE_TO_NOMINAL) and its
    target rule scales the planning values (SCALE_UP_ONLY never scales a short period down; only SCALE_TO_ACTUAL scales to
    the period's own length). Only periods that had completely ended by `now` are learned from."""
    tz = zone(cfg.tz)
    day = t0.astimezone(tz).date()
    notes: list[str] = []
    if not t1 > t0:
        return blocked("overnight_demand", [Blocker("INVALID_PERIOD", "a demand period must end after it starts")]), (), notes
    s_min, e_min = _wall_minutes(t0, day, tz), _wall_minutes(t1, day, tz)
    prof = _profile(day, s_min, e_min, tz) if e_min > s_min else None
    ambiguous = (prof is None or abs((prof.start_utc - t0).total_seconds()) >= 60.0
                 or abs((prof.end_utc - t1).total_seconds()) >= 60.0 or prof.boundary_in_changed_hour)
    if ambiguous:
        bl = [Blocker("DST_BOUNDARY_IN_CHANGED_HOUR", f"the {kind_note} period {t0.isoformat()} - {t1.isoformat()} starts "
                      "or ends inside the repeated or missing hour of a clock change, so it is not a recurring local "
                      "wall-clock window; it is withheld whatever I-D9 says")]
        if not states.ok("D9"):
            bl.insert(0, Blocker(states.code("D9"), f"I-D9 ({DECISION_TITLES['D9']}) is {states.why('D9')} and this "
                                 f"{kind_note} period touches a clock change"))
        return blocked("overnight_demand", bl), ("D9",), notes
    nominal, actual = prof.nominal_h, prof.actual_h
    prior = sc.overnight_prior_kwh
    if prior is not None and not (finite_number(prior) and 0.0 < prior <= 200.0):
        notes.append(f"overnight_prior_kwh {prior!r} is not a positive number up to 200 kWh and was ignored")
        prior = None
    settings = OvernightSettings.from_site(cfg, prior_kwh=prior)
    lookback = settings.lookback_nights                  # the learner's own window (28 nights by default)
    last = day - timedelta(days=1)
    while last >= day - timedelta(days=lookback) and local_wall(last, e_min, tz) > sc.now:
        last -= timedelta(days=1)                         # never learn from a period still in progress
    obs = nightly_totals(hist, cfg, s_min, e_min, day - timedelta(days=lookback), last)
    hist_prof = {o.night: _profile(o.night, s_min, e_min, tz) for o in obs}
    changed_hist = [o for o in obs if hist_prof[o.night] is None or hist_prof[o.night].changed]
    target_changes = prof.changed
    extra: tuple[str, ...] = ("D9",) if (target_changes or changed_hist) else ()
    if extra and not states.ok("D9"):
        what = (f"the {kind_note} period starting {day.isoformat()} lasts {actual:g} h instead of {nominal:g} h" if target_changes
                else f"{len(changed_hist)} period(s) in the learning history crossed a clock change")
        return (blocked("overnight_demand", [Blocker(states.code("D9"), what + f" and the clock-change policy I-D9 is "
                f"{states.why('D9')}: learning raw totals would be an unstated policy")]), extra, notes)
    pol = states.value("D9") if extra else None
    if changed_hist:
        fix = {o.night for o in changed_hist}
        if pol.history_rule == EXCLUDE_CHANGED_PERIODS:
            obs = [replace(o, excluded="CLOCK_CHANGE_PERIOD") if o.night in fix else o for o in obs]
            notes.append(f"{len(changed_hist)} clock-change period(s) excluded from learning (I-D9 SYNTHETIC_TEST policy)")
        else:
            gone = {n for n in fix if hist_prof[n] is None}          # no real length: nothing to normalise
            obs = [replace(o, excluded="CLOCK_CHANGE_PERIOD") if o.night in gone
                   else replace(o, kwh=o.kwh * nominal / hist_prof[o.night].actual_h)
                   if o.night in fix and o.kwh is not None else o for o in obs]
            notes.append(f"{len(changed_hist)} clock-change period(s) normalised to {nominal:g} h (I-D9 SYNTHETIC_TEST policy)")
    adv = learn_overnight(obs, day, settings, period=f"the {kind_note} period")
    if target_changes and adv.recommendation is not None:
        raw = actual / nominal
        f = raw if pol.target_rule == SCALE_TO_ACTUAL else max(1.0, raw)
        rec = dict(adv.recommendation)
        for k in ("expected_kwh", "planning_kwh", "learned_kwh"):
            if finite_number(rec.get(k)):
                rec[k] = round(rec[k] * f, 3)
        rec["clock_change_length_factor"] = round(f, 4)
        rec["clock_change_target_rule"] = pol.target_rule
        if f != 1.0:
            why = Reason("CLOCK_CHANGE_SCALED", f"This period lasts {actual:g} h, not {nominal:g} h: the learned values "
                                                f"were scaled by {f:.3f} (I-D9 {pol.target_rule}, SYNTHETIC_TEST policy).")
        else:
            why = Reason("CLOCK_CHANGE_NOT_SCALED_DOWN", f"This period lasts {actual:g} h, not {nominal:g} h: the learned "
                                                         "values were kept at the ordinary length (I-D9 SCALE_UP_ONLY, "
                                                         "SYNTHETIC_TEST policy).")
        adv = Advice(adv.kind, adv.status, rec, adv.confidence, adv.reasons + (why,), adv.assumptions, (), adv.inputs,
                     adv.model_version)
    return adv, extra, notes


# ---------------------------------------------------------------------------------------------------------------------
# 5. the run
# ---------------------------------------------------------------------------------------------------------------------

def _gate(kind: str, states: DecisionStates, extra: tuple[str, ...] = (), ctx: GateContext = GateContext(),
          boundary: bool = False) -> tuple[list[Blocker], tuple[str, ...], str | None]:
    """site_decisions.gate for the item (with the conditional I-D4 / I-D9 context and the fixed DST boundary rule), as
    blockers, plus the prototype's stricter I-D9 rule for the learning kinds."""
    item = _item(kind)
    c = replace(ctx, clock_change_in_scope="D9" in extra, boundary_in_changed_hour=boundary)
    found = gate(item, states.dset, c, accept_provenance=states.accept)
    d4 = ("D4",) if item in CONDITIONAL_D4_ITEMS and ctx.capacity_sources >= 2 else ()
    used = tuple(dict.fromkeys(ITEM_GATES[item] + d4 + extra))
    bl = [Blocker(f.code, f.text) for f in found if f.severity == FINDING_BLOCK]
    have = {b.code for b in bl}
    if kind in D9_LEARNING_KINDS and states.status("D9") == DecisionStatus.INVALID and "DECISION_D9_INVALID" not in have:
        bl.append(Blocker("DECISION_D9_INVALID", f"I-D9 ({DECISION_TITLES['D9']}) is INVALID: this item learns period "
                          "demand and is withheld"))
    return bl, used, _prov(states, used)


def _prov(states: DecisionStates, used: tuple[str, ...]) -> str | None:
    return SYNTHETIC_TEST if any(states.ok(d) for d in used) else None


def _item_from(kind: str, adv: Advice, used: tuple[str, ...], prov: str | None, notes=()) -> Item:
    return Item(kind, adv.status, adv.to_dict() if adv.status != BLOCKED else None,
                adv.blocking if adv.status == BLOCKED else (), used, prov, tuple(notes))


def _withheld(kind: str, blockers: list[Blocker], used: tuple[str, ...] = (), notes=()) -> Item:
    return Item(kind, BLOCKED, None, tuple(blockers), used, None, tuple(notes))


def _inputs_view(sc: Scenario, states: DecisionStates | None = None) -> list[dict]:
    out = []
    lim = states.limits if states is not None else {}
    for name, obs in (("battery.soc", sc.soc), ("inverter.healthy", sc.inverter_healthy),
                      ("reserve.ha_minimum_soc", sc.ha_reserve_helper), ("limits.max_grid_charge_w", sc.grid_charge_limit_w)):
        age = _age(obs, sc.now)
        v = None if obs is None else obs.value
        shown = v if isinstance(v, bool) or v is None or finite_number(v) else repr(v)
        judged = InputAge.assess(name, age, lim.get(name))
        out.append({"signal": name, "value": shown, "age_s": age, "age_known": age is not None and age >= 0.0,
                    "limit_s": lim.get(name), "status": judged.status})
    return out


def _reserve_semantics(sc: Scenario, cfg: SiteConfig | None, states: DecisionStates, helper: float | None) -> list[dict]:
    d1, d2 = states.ok("D1"), states.ok("D2")
    eff = cfg.effective_reserve(helper) if (cfg is not None and d1 and d2) else None
    rc = sc.reserve_context
    prot = states.value("D2") if d2 else None
    prot_pct = float(prot.value_pct) if prot is not None and prot.supplied_by == OWNER_STATEMENT else None
    tech_note = None
    if prot_pct is not None and prot_pct < sc.cfg.technical_min_soc_pct:
        tech_note = (f"the protection level {prot_pct:g} % is below SiteConfig's technical minimum "
                     f"{sc.cfg.technical_min_soc_pct:g} %, which therefore still binds (never lowered)")
    floor = states.value("D1") if d1 else None
    raw_h = _num(sc.ha_reserve_helper.value) if sc.ha_reserve_helper is not None else None
    return [
        {"level": "planning floor (Intelligence user reserve)", "role": ReserveRole.SOFT_PLANNING_FLOOR,
         "value_pct": cfg.user_reserve_soc_pct if (cfg is not None and d1) else None,
         "shipped_default_pct": SiteConfig().user_reserve_soc_pct,
         "source": (f"I-D1 SYNTHETIC_TEST record ({floor.source})" if d1 else
                    f"UNKNOWN: D1 {states.why('D1')} (the shipped default is not a decision)"),
         "enforced_by": "nothing (advice only)"},
        {"level": "HA reserve helper", "role": ReserveRole.HA_RESERVE_HELPER, "value_pct": raw_h,
         "usable": helper is not None,
         "source": "scenario observation", "enforced_by": "nothing; a raise-only input: it can never lower the planning floor"},
        {"level": "inverter battery shutdown SOC", "role": ReserveRole.PHYSICAL_PROTECTION,
         "value_pct": prot_pct,
         "source": ("I-D2 SYNTHETIC_TEST record (owner statement)" if prot_pct is not None else
                    f"UNKNOWN: D2 {states.why('D2')} (never assumed)" if not d2 else "UNKNOWN: no fresh sensor reading"),
         "enforced_by": "the inverter", "note": tech_note},
        {"level": "TOU slot target SOC", "role": ReserveRole.INVERTER_TOU_SETTING, "value_pct": rc.tou_slot_floor_pct,
         "source": "scenario context" if rc.tou_slot_floor_pct is not None else "not known here",
         "enforced_by": "the inverter's TOU schedule; not read by these advisors"},
        {"level": "Dump to Grid stop SOC", "role": ReserveRole.FEATURE_STOP_LEVEL, "value_pct": rc.dump_stop_soc_pct,
         "source": "scenario context" if rc.dump_stop_soc_pct is not None else "not known here",
         "enforced_by": "the Dump to Grid firmware, for that feature only; it does not read the planning floor"},
        # "DERIVED" is this report's name for ReserveRole.DERIVED_EFFECTIVE (SiteConfig.effective_reserve)
        {"level": "effective planning minimum used by the advisors", "role": "DERIVED",
         "value_pct": None if eff is None else eff.effective_pct,
         "source": "not computed: D1 or D2 not satisfied" if eff is None else f"binding: {eff.binding}",
         "enforced_by": "nothing (advice only)",
         "note": None if eff is None else (eff.override_reason or "the user reserve applies")},
    ]


def run_harness(sc: Scenario, *, accept_provenance=S1_ACCEPT_PROVENANCE) -> Report:
    """The report for one scenario. `accept_provenance` may only be {SYNTHETIC_TEST} (the default) or empty."""
    issues: list[Issue] = []
    if not _aware(sc.now):
        raise ValueError("scenario.now must be an aware datetime")
    states = _decision_states(sc, issues, accept_provenance=accept_provenance)
    cfg, cfg_findings = _effective(sc, states)
    _config_issues(sc, cfg_findings, issues)
    tz = zone(sc.cfg.tz)
    hist, dq = _build_history(sc, states, issues)
    cap_ok, cap_ctx = _capacity_check(cfg, sc, states, issues)
    tariff_ok = _tariff_ok(sc, issues)

    # every signal is judged under its own limit (site_decisions.freshness_limits: the defined catalogue, tightened or
    # supplied per signal by a satisfied I-D6 within the ceiling); a signal without a defined limit is never fresh
    soc_v = _num(sc.soc.value) if sc.soc is not None else None
    soc_age = _age(sc.soc, sc.now)
    soc_lim = states.limits.get("battery.soc")
    if soc_v is not None and soc_age is not None and 0.0 <= soc_age <= STALE_SOC_SECONDS and (
            soc_lim is None or soc_age > soc_lim):
        issues.append(Issue("SOC_NOT_FRESH_UNDER_LIMIT", "WARN", "the battery SOC is older than its I-D6 limit: it is not "
                            "used (unknown to the advisors)"))
        soc_v, soc_age = None, None
    helper_in = _judge("reserve.ha_minimum_soc", sc.ha_reserve_helper, sc.now, states.limits.get("reserve.ha_minimum_soc"))
    helper = helper_in.usable_number
    helper_block: list[Blocker] = []
    if sc.ha_reserve_helper is not None and (helper is None or not 0.0 <= helper <= 100.0):
        helper = None
        if helper_in.fresh:                              # fresh under a defined limit, but not a percentage 0..100
            issues.append(Issue("RESERVE_HELPER_OUT_OF_RANGE", "BLOCK", "the reserve helper is fresh but not a finite "
                                "percentage in 0..100; as a raise-only input it could raise the floor, so the battery "
                                "advice is withheld"))
            helper_block.append(Blocker("RESERVE_HELPER_OUT_OF_RANGE", "the raise-only reserve helper is fresh but not a "
                                        "finite percentage in 0..100"))
        else:                                            # stale, unknown age, or no defined limit
            issues.append(Issue("RESERVE_HELPER_NOT_USABLE", "BLOCK", "the reserve helper is present but not fresh under a "
                                "defined (I-D6) limit; as a raise-only input it could raise the floor, so the battery "
                                "advice is withheld"))
            helper_block.append(Blocker("RESERVE_HELPER_NOT_FRESH", "the raise-only reserve helper is present but not "
                                        "fresh under its own limit"))
    # inverter status: usable only with a defined (I-D6) limit for inverter.healthy and a fresh True reading
    inv_ok = None
    inv_lim = states.limits.get("inverter.healthy")
    inv_age = _age(sc.inverter_healthy, sc.now)
    inv_in = InputAge.assess("inverter.healthy", inv_age, inv_lim,
                             note="I-D6 limit" if inv_lim is not None else "no limit: I-D6 has none for this signal")
    if sc.inverter_healthy is not None and sc.inverter_healthy.value is True and not inv_in.blocks:
        inv_ok = True
    elif sc.inverter_healthy is not None and sc.inverter_healthy.value is False and not inv_in.blocks:
        inv_ok = False

    items: list[Item] = []
    common_block: list[Blocker] = []
    if not tariff_ok:
        common_block.append(Blocker("INVALID_OR_MISSING_TARIFF", "the tariff window is missing or invalid: no period can be defined"))
    if not dq["history_fresh"]:
        common_block.append(Blocker("STALE_HISTORY", "the hourly history is missing or older than its limit"))

    # ---- overnight demand for the period after the next window ------------------------------------------------------
    demand_adv = None
    window = None
    wday = None
    if common_block:
        items.append(_withheld("overnight_demand", common_block, GATES["overnight_demand"]))
    else:
        wday = _next_window_day(sc, tz)
        w0, w1 = _window_on(wday, sc, tz)
        window = (w0, w1)
        nxt0, _ = _window_on(w0.astimezone(tz).date() + timedelta(days=1), sc, tz)
        gate_bl, used, prov = _gate("overnight_demand", states)
        if gate_bl:
            items.append(_withheld("overnight_demand", gate_bl, used))
        else:
            demand_adv, extra, notes = learn_period(hist, cfg or sc.cfg, w1, nxt0, sc, states, "post-window")
            used = tuple(dict.fromkeys(used + extra))
            prov = _prov(states, used)
            items.append(_item_from("overnight_demand", demand_adv, used, prov, notes))

    # ---- charge target ------------------------------------------------------------------------------------------
    battery_block = list(common_block) + helper_block
    if cfg is None:
        cfg_bl = [Blocker(f.code, f.text) for f in cfg_findings if f.severity == FINDING_BLOCK
                  and not f.code.startswith("DECISION_")]
        battery_block += cfg_bl
    elif not cap_ok:
        battery_block.append(Blocker("CAPACITY_MISMATCH", "capacity sources disagree beyond the band"))
    # the charge window itself (periods.period_profile): crossing a clock change puts I-D9 in scope (register:
    # CONDITIONAL_D9_ITEMS), and a window boundary in a repeated or missing hour BLOCKs whatever I-D9 says (fixed rule)
    cw_boundary, cw_changed = _window_dst((wday,), sc, tz) if wday is not None else (False, False)
    extra = ("D9",) if (items and "D9" in items[0].decisions_used) or cw_changed else ()
    gate_bl, used, prov = _gate("charge_target", states, extra, cap_ctx, boundary=cw_boundary)
    if battery_block or gate_bl or cfg is None or demand_adv is None or demand_adv.status == BLOCKED:
        why = battery_block + gate_bl
        if not why:
            why = ([Blocker("SITE_CONFIG_UNAVAILABLE", "no effective configuration could be formed")] if cfg is None else
                   [Blocker("NO_DEMAND", "the overnight demand item is withheld")])
        items.append(_withheld("charge_target", why, used))
    else:
        adv = advise_charge_target(cfg, ChargeTargetInputs(now=sc.now, window=window, demand=demand_adv, soc_pct=soc_v,
                                                           soc_age_s=soc_age, ha_reserve_pct=helper))
        note = ()
        r_ = adv.recommendation or {}
        if finite_number(r_.get("end_of_period_floor_pct")) and r_["end_of_period_floor_pct"] > cfg.max_soc_pct:
            note = (f"the end-of-period floor ({r_['end_of_period_floor_pct']:g} %) is above the maximum SOC: no target can "
                    "meet it (SHORTFALL)",)
        items.append(_item_from("charge_target", adv, used, prov, note))

    # ---- export events ------------------------------------------------------------------------------------------
    for ev in sc.events:
        kind = "export_event"
        if not (_aware(ev.start) and _aware(ev.end)) or not ev.end > ev.start:
            items.append(_withheld(kind, [Blocker("INVALID_EVENT", "an event needs aware start/end with end after start")]))
            continue
        gate_bl, used, prov = _gate(kind, states, (), cap_ctx)
        if battery_block or gate_bl or cfg is None:
            items.append(_withheld(kind, (battery_block + gate_bl) or [Blocker("SITE_CONFIG_UNAVAILABLE",
                                   "no effective configuration could be formed")], used))
            continue
        segs = []
        notes: list[str] = []
        rday = ev.end.astimezone(tz).date()
        refill0, _ = _window_on(rday, sc, tz)
        if refill0 <= ev.end:
            rday += timedelta(days=1)
            refill0, _ = _window_on(rday, sc, tz)
        wb = _window_blocker((rday,), sc, tz, "refill")
        if wb:
            items.append(_withheld(kind, wb, used))
            continue
        bounds = ((sc.now, ev.start), (max(sc.now, ev.start), ev.end), (ev.end, refill0))
        labels = []
        extra_used: tuple[str, ...] = ()
        for t0, t1 in bounds:
            if t1 <= t0:
                segs.append(0.0)
                continue
            a, ex, n = learn_period(hist, cfg, t0, t1, sc, states, "event segment")
            extra_used += ex
            notes += n
            ok_ = a.status != BLOCKED and a.recommendation is not None
            segs.append(float(a.recommendation["planning_kwh"]) if ok_ else None)
            labels.append(a.confidence.label if ok_ else "INSUFFICIENT")
        used = tuple(dict.fromkeys(used + extra_used))
        prov = _prov(states, used)
        if "D9" in extra_used and not states.ok("D9"):
            items.append(_withheld(kind, [Blocker(states.code("D9"), f"an event segment crosses a clock change and I-D9 "
                                                                     f"is {states.why('D9')}")], used, notes))
            continue
        order = ("INSUFFICIENT", "LOW", "MEDIUM", "HIGH")
        lab = min(labels, key=order.index) if labels else "HIGH"
        adv = advise_event(cfg, EventInputs(now=sc.now, event=ExportEvent(ev.start, ev.end, ev.label), soc_pct=soc_v,
                                            soc_age_s=soc_age, inverter_ok=inv_ok, demand_before_kwh=segs[0],
                                            demand_during_kwh=segs[1], demand_after_kwh=segs[2], demand_label=lab,
                                            max_discharge_kw=sc.power_limits.max_discharge_kw,
                                            max_export_kw=sc.power_limits.max_export_kw, ha_reserve_pct=helper))
        items.append(_item_from(kind, adv, used, prov, notes))

    # ---- Dump-to-Grid stop level (advice for a future reserve-aware Dump; nothing consumes it) -----------------------
    if sc.dump_duration_min is not None:
        kind = "dump_to_grid"
        gate_bl, used, prov = _gate(kind, states, (), cap_ctx)
        wb: list[Blocker] = []
        if not (battery_block or gate_bl or cfg is None):
            w0, w1 = _next_window(sc, tz)
            in_window = w0 <= sc.now < w1
            refill = w0 if sc.now < w0 else _window_on(w0.astimezone(tz).date() + timedelta(days=1), sc, tz)[0]
            rday = wday if sc.now < w0 else w0.astimezone(tz).date() + timedelta(days=1)
            wb = _window_blocker((wday, rday), sc, tz, "next or refill")
        if battery_block or gate_bl or cfg is None:
            items.append(_withheld(kind, (battery_block + gate_bl) or [Blocker("SITE_CONFIG_UNAVAILABLE",
                                   "no effective configuration could be formed")], used))
        elif wb:
            items.append(_withheld(kind, wb, used))
        else:
            a, ex, notes = learn_period(hist, cfg, sc.now, refill, sc, states, "until-refill")
            used = tuple(dict.fromkeys(used + ex))
            prov = _prov(states, used)
            if a.status == BLOCKED and "D9" in ex:
                items.append(_withheld(kind, list(a.blocking), used, notes))
            else:
                ok_ = a.status != BLOCKED and a.recommendation is not None
                adv = advise_dump(cfg, DumpInputs(now=sc.now, soc_pct=soc_v, soc_age_s=soc_age, inverter_ok=inv_ok,
                                                  refill_at=refill,
                                                  demand_until_refill_kwh=float(a.recommendation["planning_kwh"]) if ok_ else None,
                                                  demand_label=a.confidence.label if ok_ else None,
                                                  duration_min=sc.dump_duration_min,
                                                  max_discharge_kw=sc.power_limits.max_discharge_kw,
                                                  max_export_kw=sc.power_limits.max_export_kw, in_charge_window=in_window,
                                                  saving_sessions=tuple((e.start, e.end) for e in sc.events
                                                                        if _aware(e.start) and _aware(e.end)),
                                                  ha_reserve_pct=helper))
                items.append(_item_from(kind, adv, used, prov, notes))

    # ---- V1 engine shadow report (summary only) ------------------------------------------------------------------
    if sc.include_v1_summary:
        kind = "v1_report_summary"
        gate_bl, used, prov = _gate(kind, states, (), cap_ctx)  # the V1 engine sums per-hour slots, so I-D9 does not apply
        wb = []
        if window is not None:      # the fixed DST rule still applies to the windows the engine is given
            wb = _window_blocker([window[0].astimezone(tz).date() + timedelta(days=k) for k in (-1, 0, 1, 2)], sc, tz,
                                 "V1 engine")
        if battery_block or gate_bl or cfg is None or window is None or wb:
            why = battery_block + gate_bl + wb or [Blocker("NO_WINDOW", "no charging window could be defined")]
            items.append(_withheld(kind, why, used))
        else:
            w0, w1 = window
            wins = [_window_on(w0.astimezone(tz).date() + timedelta(days=k), sc, tz) for k in (-1, 0, 1, 2)]
            t = sc.tariff
            rep = IntelligenceEngine(hist, cfg).run(LiveInputs(
                now=sc.now, soc_pct=soc_v, soc_age_s=soc_age, ha_reserve_pct=helper, inverter_ok=inv_ok,
                tariff=TariffInfo(wins, t.import_cheap_p, t.import_peak_p, t.export_p, t.source),
                saving_sessions=[(e.start, e.end) for e in sc.events if _aware(e.start) and _aware(e.end)]))
            rec = rep.get("recommended", {})
            ot = rec.get("overnight_target", {})
            se = rec.get("safe_export", {})
            summary = {"model_version": rep.get("model_version"), "mode": rep.get("mode"),
                       "applies_nothing": rep.get("applies_nothing"), "status": rep.get("status"),
                       "confidence": (rep.get("confidence") or {}).get("label"),
                       "overnight_target_soc_pct": ot.get("recommended_target_soc_pct"),
                       "floor_pct": rec.get("floor_pct"),
                       "safe_export_kwh": se.get("kwh"), "safe_export_withheld_because": se.get("withheld_because")}
            st = OK if rep.get("mode") == "SHADOW" and rep.get("applies_nothing") is True else BLOCKED
            items.append(Item(kind, st, summary if st == OK else None,
                              () if st == OK else (Blocker("V1_NOT_SHADOW", "the V1 report was not shadow-only"),),
                              used, prov, ("the V1 engine's own hourly simulation; compare with charge_target's closed-form budget",)))

    rep = Report(tuple(items), tuple(issues), tuple(states.rows[d] for d in DECISION_IDS),
                 tuple(_reserve_semantics(sc, cfg, states, helper)), dq, tuple(_inputs_view(sc, states)), sc.now.isoformat(),
                 sc.label, tuple(sorted(states.accept)))
    _check_invariants(rep)
    return rep


FORBIDDEN_KEYS = ("apply", "command", "execute", "write", "set_value", "service", "schedule_at", "arm")


def _check_invariants(rep: Report) -> None:
    """Fail loudly if the report could be read as an instruction or carries a number while BLOCKED."""
    d = rep.to_dict()
    sat = {x["id"]: x.get("satisfied") is True for x in d["decisions"]}
    if not set(d["accept_provenance"]) <= S1_ACCEPT_PROVENANCE:
        raise AssertionError("the S1 prototype accepts only SYNTHETIC_TEST decisions")
    for it in d["items"]:
        if it["mode"] != MODE or it["applies_nothing"] is not True:
            raise AssertionError("every item is SHADOW and applies nothing")
        if it["status"] != BLOCKED and any(not sat.get(x, False) for x in it["decisions_used"]):
            raise AssertionError(f"{it['kind']}: an item resting on an OPEN, invalid or unaccepted decision must be BLOCKED")
        if (it["status"] != BLOCKED and any(sat.get(x, False) for x in it["decisions_used"])
                and it["decision_provenance"] != SYNTHETIC_TEST):
            raise AssertionError(f"{it['kind']}: an item using a filled decision must say SYNTHETIC_TEST")
        if it["advice"] is not None and it["advice"].get("mode") != MODE:
            raise AssertionError(f"{it['kind']}: advice must be SHADOW")
        if it["status"] == BLOCKED and it["advice"] is not None:
            raise AssertionError(f"{it['kind']}: a BLOCKED item carries no advice")
        if it["status"] == BLOCKED and not it["withheld_because"]:
            raise AssertionError(f"{it['kind']}: a BLOCKED item names why")
        if it["advice"] is not None and it["advice"].get("applies_nothing") is False:
            raise AssertionError("advice must apply nothing")

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if any(k.lower() == f or k.lower().startswith(f + "_") for f in FORBIDDEN_KEYS):
                    raise AssertionError(f"forbidden key {k!r} in a report")
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(d)
