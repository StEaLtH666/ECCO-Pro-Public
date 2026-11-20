"""Intelligence versus reality: a simulated "ghost" battery that follows the recorded advice (read-only, SHADOW package).

THE GHOST IS A SIMULATION. Intelligence controlled nothing: the real battery did what it did, and every ghost figure is
arithmetic on the recorded PV, load and prices. It is evidence for the owner's decision about assisted mode, never a decision,
and nothing here can write, arm or change anything.

What goes in
    ActualPeriod   fixed-step `value.Slot`s (what really happened), a `value.Tariff`, the SOC at the start, and optionally the
                   recorded SOC at the end of each slot.
    AdviceRecord   one piece of recorded advice, adapted from the real advice kinds of the package:
        kind "charge_target"  (charge_target.py)   needs: status, issued_at, window_start, window_end, target_soc_pct,
                                                   effective_reserve_pct (optional), conservative_fallback
        kind "dump_to_grid"   (dump_advice.py)     needs: status, issued_at, window_start, window_end, target_soc_pct (the stop
                                                   level), export_kwh, export_kw (optional), effective_reserve_pct (optional)
    Where the fields come from in the recorded Home Assistant states (the advice sensors' state and attributes, placeholders):
        status                  the advice sensor's state (OK / INSUFFICIENT_DATA / BLOCKED)
        issued_at               that state's last_updated time
        charge_target:          recommendation.target_soc_pct, recommendation.window[0], [1], recommendation.effective_reserve_pct,
                                recommendation.conservative_fallback
        dump_to_grid:           recommendation.stop_soc_pct, .export_kwh, .export_kw_avg, .effective_reserve_pct, .dump_advisable;
                                the window is issued_at + the intended duration, and that duration is an INPUT of the advice
                                (DumpInputs.duration_min), not part of its recommendation, so it has to be recorded with it.
    `AdviceRecord.from_advice(advice, issued_at, duration_min)` builds one straight from an `explain.Advice`.

How the ghost runs (slot by slot, stored energy = SOC x capacity, one-way efficiency from `battery.eta_one_way`)
    * Inside the window of a followed charge-target advice it uses the same reading as battery.py: below the target the grid
      carries the house and charges the battery (at the charge power limit); at or above the target the battery may cover the
      house only down to the target; solar surplus still charges.
    * Inside a followed dump advice it discharges (house first, then export) down to the stop level, within the discharge power,
      the advised export energy and power, the export limit and only in slots where export is permitted.
    * Everywhere else it does what the real battery did ("follow_actual"). REPLAY RULE: while the ghost's stored energy equals
      reality's (no divergence yet) and no advice is in force, the slot is replayed EXACTLY: the recorded gross charge and
      discharge (even both in one slot) and the metered import and export, so its value ledger equals the actual one. Real flows
      that break the config's power limits or reserve are replayed as recorded and disclosed (replayed_outside_limits, kWh and
      slots); advice-driven flows never get that leeway. After a divergence the gross recorded charge and discharge are replayed
      only as far as the ghost's own stored energy and the reserve allow (clipped to what the ghost's own state allows; where the real battery was pinned at its floor or at full, the ghost may use the energy it
      holds the way self-use would, so extra stored energy is not wasted) or, with outside_advice="self_use", plain self-use. With no advice at all the "follow_actual"
      ghost therefore reproduces reality (a test pins that), so any difference is the advice, not the model.
    * Always: SOC never above max_soc_pct; the ghost never discharges below the reserve (config effective reserve, or the higher
      reserve recorded with the advice); charge and discharge are limited by the power limits (advice-driven flows only; outside advice
      reality's own flows are not cut by them).
    * PERTURBATION RULE for the grid (never re-derived from the balance): every slot starts from the recorded one (metered import
      and export, curtailed) and only the changed battery energy is priced, dg = (c' - c) - (d' - d). dg > 0: reduce export
      first (to 0), then add import. dg < 0: reduce import first (to 0), then add export if permitted and within the export limit;
      the rest is curtailed and counted (ghost_extra_curtailed_kwh); extra charge first absorbs PV that reality spilled
      (curtailed_absorbed_kwh). A ghost identical to reality therefore costs exactly the
      same, and noise in the recorded flows (0.1 kWh counters, simultaneous charge and discharge) cancels.
    * Advice is used only from its issue time (no look-ahead); of overlapping advice the latest wins; BLOCKED advice and, by
      default, INSUFFICIENT_DATA fallbacks are not followed (include_fallback=True follows a fallback target). A row that is not
      followed (BLOCKED, a fallback, no window or target, a dump that is not advisable) and was issued AFTER earlier advice of the
      same kind withdraws that advice from its issue time on (the engine's latest word on that kind is "none"); a later followable
      row of that kind is advice again. Advice of another kind is untouched.
    Both runs are valued by `net_value.py` (same tariff, same wear price), so they are directly comparable. The closing-stock
    difference is valued by a stated rule (STOCK_RULE) and the ahead/behind counts use that stock-adjusted figure; a no-advice
    baseline run shows the simulator's own error, and `strict=True` switches off the constraint release (its value is reported
    separately). Dump advice: each record is a fresh export budget sized from the SOC at its issue; a later one in force replaces
    the remainder of an earlier one. Energy left in the battery
    at the end is not realised value: the closing stored energy of each run is reported next to the money.

Export format for tools/ghost_report.py: see that module's docstring.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Mapping, Sequence

from .battery import eta_one_way
from .charge_target import KIND as KIND_CHARGE
from .config import SiteConfig
from .dump_advice import KIND as KIND_DUMP
from .explain import BLOCKED, INSUFFICIENT, OK, STATUSES, Advice
from .timeutil import zone
from .net_value import Slot, Tariff, by_day, value_run

MODEL_VERSION = "intel-ghost/1"
LABEL = ("SIMULATION: the ghost is arithmetic on recorded data. Intelligence controlled nothing; the real battery did "
         "what the real settings told it to. This is evidence for a decision, not a decision.")
KINDS = (KIND_CHARGE, KIND_DUMP)
LEVEL_BAND_P = 0.5            # a day within half a penny either way is "level"
DIVERGE_KWH = 0.005
EPS = 1e-9


def _fin(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _aware(x: object, name: str) -> datetime:
    if isinstance(x, str):
        x = datetime.fromisoformat(x.replace("Z", "+00:00"))
    if not isinstance(x, datetime) or x.tzinfo is None:
        raise ValueError(f"{name} must be an aware datetime")
    return x


@dataclass(frozen=True)
class AdviceRecord:
    """A piece of recorded advice, reduced to what the ghost needs (see the module docstring for the source of each field)."""
    kind: str
    status: str
    issued_at: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    target_soc_pct: float | None = None       # charge_target: SOC to reach; dump_to_grid: the stop level
    export_kwh: float | None = None           # dump_to_grid: energy advised to export
    export_kw: float | None = None            # dump_to_grid: average export power advised
    effective_reserve_pct: float | None = None
    conservative_fallback: bool = False
    dump_advisable: bool = True
    advice_id: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown advice kind {self.kind!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown advice status {self.status!r}")
        object.__setattr__(self, "issued_at", _aware(self.issued_at, "issued_at"))
        for n in ("window_start", "window_end"):
            v = getattr(self, n)
            if v is not None:
                object.__setattr__(self, n, _aware(v, n))
        if self.window_start and self.window_end and not self.window_end > self.window_start:
            raise ValueError("window_end must be after window_start")
        for n in ("target_soc_pct", "export_kwh", "export_kw", "effective_reserve_pct"):
            v = getattr(self, n)
            if v is not None and not (_fin(v) and v >= 0):
                raise ValueError(f"{n} must be None or a finite number >= 0")
        for n in ("target_soc_pct", "effective_reserve_pct"):
            v = getattr(self, n)
            if v is not None and v > 100:
                raise ValueError(f"{n} above 100")

    def not_followed_reason(self, include_fallback: bool = False) -> str | None:
        """None if a ghost would act on this record, else why not (BLOCKED, FALLBACK_EXCLUDED, NO_WINDOW, NO_TARGET,
        NOT_ADVISABLE)."""
        if self.status == BLOCKED:
            return "BLOCKED"
        if self.status == INSUFFICIENT and not (include_fallback and self.conservative_fallback):
            return "FALLBACK_EXCLUDED"
        if self.window_start is None or self.window_end is None:
            return "NO_WINDOW"
        if self.target_soc_pct is None:
            return "NO_TARGET"
        if self.kind == KIND_DUMP and not (self.dump_advisable and self.export_kwh is not None and self.export_kwh > 0):
            return "NOT_ADVISABLE"
        return None

    def followable(self, include_fallback: bool = False) -> bool:
        """Would a ghost act on this record? Needs a usable status, a window and a target."""
        return self.not_followed_reason(include_fallback) is None

    @classmethod
    def from_advice(cls, advice: Advice, issued_at: datetime, duration_min: float | None = None,
                    advice_id: str = "") -> "AdviceRecord":
        """Adapt an `explain.Advice` of kind charge_target or dump_to_grid. A dump advice carries no window of its own: pass
        the intended duration it was computed for (a missing duration leaves the record without a window = not followable)."""
        if advice.kind not in KINDS:
            raise ValueError(f"unsupported advice kind {advice.kind!r}")
        issued_at = _aware(issued_at, "issued_at")
        rec = advice.recommendation
        if rec is None:
            return cls(advice.kind, advice.status, issued_at, advice_id=advice_id)
        reserve = rec.get("effective_reserve_pct")
        if advice.kind == KIND_CHARGE:
            w = rec.get("window")
            return cls(advice.kind, advice.status, issued_at, _aware(w[0], "window"), _aware(w[1], "window"),
                       rec.get("target_soc_pct"), effective_reserve_pct=reserve,
                       conservative_fallback=bool(rec.get("conservative_fallback", False)), advice_id=advice_id)
        end = issued_at + timedelta(minutes=duration_min) if _fin(duration_min) and duration_min > 0 else None
        return cls(advice.kind, advice.status, issued_at, issued_at if end else None, end, rec.get("stop_soc_pct"),
                   rec.get("export_kwh"), rec.get("export_kw_avg"), reserve,
                   dump_advisable=bool(rec.get("dump_advisable", False)), advice_id=advice_id)

    @classmethod
    def from_dict(cls, d: Mapping) -> "AdviceRecord":
        allowed = {"kind", "status", "issued_at", "window_start", "window_end", "target_soc_pct", "export_kwh", "export_kw",
                   "effective_reserve_pct", "conservative_fallback", "dump_advisable", "advice_id"}
        extra = set(d) - allowed
        if extra:
            raise ValueError(f"unknown advice field(s): {sorted(extra)}")
        return cls(**{k: v for k, v in d.items()})

    def to_dict(self) -> dict:
        out = {k: getattr(self, k) for k in self.__dataclass_fields__}
        for n in ("issued_at", "window_start", "window_end"):
            out[n] = None if out[n] is None else out[n].isoformat()
        return out


@dataclass(frozen=True)
class ActualPeriod:
    """What really happened. `soc_pct`, when given, is the recorded SOC at the END of each slot."""
    slots: tuple[Slot, ...]
    tariff: Tariff
    soc0_pct: float
    soc_pct: tuple[float, ...] | None = None
    opening_cost_p_per_kwh: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", tuple(self.slots))
        if not self.slots:
            raise ValueError("an empty period")
        if len(self.tariff) != len(self.slots):
            raise ValueError("tariff and slots differ in length")
        if not (_fin(self.soc0_pct) and 0 <= self.soc0_pct <= 100):
            raise ValueError("soc0_pct must be within 0-100")
        if self.soc_pct is not None:
            object.__setattr__(self, "soc_pct", tuple(self.soc_pct))
            if len(self.soc_pct) != len(self.slots) or not all(_fin(x) and 0 <= x <= 100 for x in self.soc_pct):
                raise ValueError("soc_pct must have one value in 0-100 per slot")


@dataclass(frozen=True)
class GhostLimits:
    """Physical limits of the battery's power. None = the config's max_grid_charge_kw (an assumption, stated in the report)."""
    max_charge_kw: float | None = None
    max_discharge_kw: float | None = None


@dataclass
class _Run:
    slots: list[Slot]
    soc_pct: list[float]                 # SOC at the end of each slot
    advice_idx: list[int | None]         # which advice (index into the followable list) was in force
    notes: list[str]
    released_dis_kwh: float = 0.0        # discharge the ghost made where the real battery was pinned at its floor
    released_chg_kwh: float = 0.0        # charge it made where the real battery was full
    replayed: list[bool] = field(default_factory=list)   # slot replayed exactly as recorded (not diverged, no advice, follow_actual)
    outside_kwh: float = 0.0             # recorded flow replayed although it broke the config's limits or reserve
    outside_slots: int = 0
    curtailed_absorbed_kwh: float = 0.0  # recorded curtailed PV the ghost used for its extra charge
    curtailed_extra_kwh: float = 0.0     # surplus the ghost could neither export nor use, spilled on top of the recorded curtailment


def _withdrawn(a: AdviceRecord, start: datetime, withdrawn: Mapping[str, Sequence[datetime]] | None) -> bool:
    """True when a row of the same kind that is NOT followed (BLOCKED, a fallback, ...) was issued at or after `a` and by `start`:
    the engine's latest word on that kind at that time was "none" (a tie counts as withdrawn: the safe reading)."""
    lst = withdrawn.get(a.kind) if withdrawn else None
    if not lst:
        return False
    i = bisect_right(lst, start)
    return i > 0 and lst[i - 1] >= a.issued_at


def _select(adv: Sequence[AdviceRecord], start: datetime, withdrawn: Mapping[str, Sequence[datetime]] | None = None) -> int | None:
    """The index of the followable advice in force at `start` (the latest issued of those covering it that no later non-followed
    row of the same kind has withdrawn), or None. `withdrawn`: {kind: sorted issue times of the non-followed rows}."""
    best = None
    for i, a in enumerate(adv):
        if a.window_start <= start < a.window_end and a.issued_at <= start:
            if _withdrawn(a, start, withdrawn):
                continue
            if best is None or (a.issued_at, a.kind) >= (adv[best].issued_at, adv[best].kind):
                best = i
    return best


def _simulate(period: ActualPeriod, adv: Sequence[AdviceRecord], cfg: SiteConfig, limits: GhostLimits, policy: str,
              ha_reserve_pct: float | None, release: bool = True,
              withdrawn: Mapping[str, Sequence[datetime]] | None = None) -> _Run:
    eta = eta_one_way(cfg)
    cap = cfg.battery_capacity_kwh
    base_floor_pct = cfg.effective_min_soc_pct(ha_reserve_pct)
    ceil_kwh = cfg.max_soc_pct / 100.0 * cap
    kw_c = cfg.max_grid_charge_kw if limits.max_charge_kw is None else limits.max_charge_kw
    kw_d = cfg.max_grid_charge_kw if limits.max_discharge_kw is None else limits.max_discharge_kw
    soc = period.soc0_pct / 100.0 * cap
    a_end, _ = _actual_soc(period, cfg)
    left = {i: (a.export_kwh or 0.0) for i, a in enumerate(adv) if a.kind == KIND_DUMP}
    out_slots: list[Slot] = []
    socs: list[float] = []
    which: list[int | None] = []
    notes: list[str] = []
    rel_d_total = rel_c_total = 0.0
    replayed: list[bool] = []
    out_kwh, out_slots_n = 0.0, 0
    curt_extra = absorbed = 0.0
    act = soc                                           # stored energy of reality replayed through the same arithmetic
    for i, sl in enumerate(period.slots):
        h = sl.hours
        net = sl.pv - sl.load
        k = _select(adv, sl.start, withdrawn)
        floor_pct = base_floor_pct if k is None else max(base_floor_pct, adv[k].effective_reserve_pct or 0.0)
        floor = min(floor_pct, 100.0) / 100.0 * cap
        room_ac = max(0.0, (ceil_kwh - soc) / eta)
        avail_ac = max(0.0, (soc - floor) * eta)
        note = ""
        act_next = min(cap, max(0.0, act + sl.chg * eta - sl.dis / eta))
        if policy == "follow_actual" and k is None and abs(soc - act) <= 1e-6:
            # Not diverged, no advice in force: reality is replayed exactly (gross charge and discharge AND the metered import
            # and export), so this slot's ledger is identical to the actual one. Flows beyond the config's limits or reserve are
            # replayed anyway (reality is reality) and disclosed; advice-driven flows never get this leeway.
            ex_c = max(0.0, sl.chg - max(0.0, min(sl.chg, kw_c * h, room_ac)))
            ex_d = max(0.0, sl.dis - max(0.0, min(sl.dis, kw_d * h, avail_ac)))
            if ex_c > EPS or ex_d > EPS:
                out_kwh += ex_c + ex_d
                out_slots_n += 1
            soc = act = act_next
            out_slots.append(sl)
            socs.append(soc / cap * 100.0)
            which.append(None)
            notes.append("")
            replayed.append(True)
            continue
        replayed.append(False)
        rel_d = rel_c = False
        if policy == "follow_actual":
            want_c, want_d = sl.chg, sl.dis
            a_prev = period.soc0_pct if i == 0 else a_end[i - 1]
            # Constraint release: where the REAL battery was pinned at its floor (or full), the ghost, which may hold more (or
            # less) energy, is allowed to do what self-use would do with it. Elsewhere it repeats the real flows.
            if release and a_prev <= base_floor_pct + 0.5 and sl.chg <= EPS and net < 0:
                want_d, rel_d = max(want_d, -net), True
            if release and a_prev >= cfg.max_soc_pct - 0.5 and sl.dis <= EPS and net > 0:
                want_c, rel_c = max(want_c, net), True
        else:
            want_c, want_d = max(0.0, net), max(0.0, -net)
        dump_export = 0.0
        if k is not None:
            rel_d = rel_c = False                       # the advice, not the release, decides in its window
        if k is not None and adv[k].kind == KIND_CHARGE:
            tgt = min(max(adv[k].target_soc_pct, floor_pct), cfg.max_soc_pct) / 100.0 * cap
            if soc < tgt - EPS:
                want_c, want_d = max(max(0.0, net), (tgt - soc) / eta), 0.0
                note = "charging to the advised target"
            else:
                want_c, want_d = max(0.0, net), min(max(0.0, -net), max(0.0, soc - tgt) * eta)
                note = "at or above the advised target"
        elif k is not None:
            stop = max(adv[k].target_soc_pct, floor_pct) / 100.0 * cap
            cover = max(0.0, -net)
            avail_stop = max(0.0, soc - stop) * eta
            surplus = max(0.0, net)
            head = math.inf if period.tariff.export_limit_kw is None else max(
                0.0, period.tariff.export_limit_kw * h - surplus)
            want_c = 0.0
            if period.tariff.export_permitted[i]:
                pw = kw_d * h - cover
                if adv[k].export_kw is not None:
                    pw = min(pw, adv[k].export_kw * h)
                dump_export = max(0.0, min(left[k], head, pw, avail_stop - cover))
                note = "exporting down to the advised stop level"
            else:
                note = "advised export not possible: export not permitted in this slot"
            want_d = min(cover + dump_export, avail_stop)
            dump_export = max(0.0, want_d - cover)
            left[k] -= dump_export
        kc, kd = kw_c * h, kw_d * h
        if policy == "follow_actual" and k is None:
            kc, kd = max(kc, sl.chg), max(kd, sl.dis)     # outside advice reality's own flows are not cut by the assumed power limit
        chg = max(0.0, min(want_c, kc, room_ac))
        dis = max(0.0, min(want_d, kd, avail_ac))
        soc = max(0.0, min(max(ceil_kwh, soc), soc + chg * eta - dis / eta))
        if rel_d:
            rel_d_total += max(0.0, dis - sl.dis)
        if rel_c:
            rel_c_total += max(0.0, chg - sl.chg)
        # PERTURBATION: the slot starts from the recorded one (metered import and export, curtailed) and only the energy that
        # really differs is priced: dg = (c' - c) - (d' - d). More needed from the grid: export first, then import. Less
        # needed: import first, then export (if permitted and within the limit), the rest is curtailed and counted.
        dg = (chg - sl.chg) - (dis - sl.dis)
        imp, exp, cur = sl.imp, sl.exp, sl.curtailed
        if dg > 0:
            use = min(cur, dg)                            # PV that reality spilled is free energy: use it first
            cur -= use
            dg -= use
            absorbed += use
            cut = min(exp, dg)
            exp -= cut
            imp += dg - cut
        elif dg < 0:
            need = -dg
            cut = min(imp, need)
            imp -= cut
            need -= cut
            if period.tariff.export_permitted[i]:
                lim = math.inf if period.tariff.export_limit_kw is None else period.tariff.export_limit_kw * h
                more = min(need, max(0.0, lim - exp))
            else:
                more = 0.0
            exp += more
            spill = need - more
            if spill > EPS:
                cur += spill
                curt_extra += spill
        out_slots.append(Slot(sl.start, h, sl.pv, sl.load, imp, exp, chg, dis, cur))
        socs.append(soc / cap * 100.0)
        which.append(k)
        notes.append(note)
        act = act_next
    return _Run(out_slots, socs, which, notes, rel_d_total, rel_c_total, replayed, out_kwh, out_slots_n, absorbed, curt_extra)


def _actual_soc(period: ActualPeriod, cfg: SiteConfig) -> tuple[list[float], str]:
    if period.soc_pct is not None:
        return list(period.soc_pct), "recorded"
    eta, cap = eta_one_way(cfg), cfg.battery_capacity_kwh
    soc = period.soc0_pct / 100.0 * cap
    out = []
    for s in period.slots:
        soc = min(cap, max(0.0, soc + s.chg * eta - s.dis / eta))
        out.append(soc / cap * 100.0)
    return out, "reconstructed from the recorded charge and discharge"


def _day_of(s: Slot, tz) -> date:
    return s.start.astimezone(tz).date()


def _hhmm(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


STOCK_RULE = ("The energy left in each battery at the end is not realised money, so the difference in closing stock is valued two "
              "ways and the one LESS favourable to the ghost is used: (a) each run's closing stock at its own mixed-tank cost "
              "basis; (b) the stock's deliverable energy (stored kWh x one-way efficiency) at the period's mean import price. "
              "Per day the adjustment is the change in that closing-stock difference over the day.")


def _fig(sm, excl: bool, before_wear: bool = False) -> float:
    if before_wear:
        return sm.net_before_wear_excl_unattributed_p if excl else sm.net_before_wear_p
    return sm.headline_excl_unattributed_p if excl else sm.headline_p


def _deltas(av, bv, tz_name: str, mean_p: float, excl: bool) -> dict:
    """Run `bv` minus run `av`: realised money and the closing-stock adjustment, per local day and in total."""
    ad, bd = by_day(av, tz_name), by_day(bv, tz_name)
    days, prev_c, prev_m = {}, 0.0, 0.0
    for d in ad:
        a, b = ad[d], bd[d]
        dc = b.closing_cost_basis_p - a.closing_cost_basis_p
        dm = (b.closing_stored_kwh - a.closing_stored_kwh) * av.eta * mean_p
        ac, am = dc - prev_c, dm - prev_m
        prev_c, prev_m = dc, dm
        real, real_bw, used = _fig(b, excl) - _fig(a, excl), _fig(b, excl, True) - _fig(a, excl, True), min(ac, am)
        days[d] = {"realised_p": real, "realised_before_wear_p": real_bw, "stock_cost_basis_p": ac, "stock_mean_import_p": am,
                   "stock_adjustment_p": used, "adjusted_p": real + used, "adjusted_before_wear_p": real_bw + used}
    tot = {k: sum(x[k] for x in days.values()) for k in next(iter(days.values()))} if days else {}
    tot["closing_stock_cost_basis_diff_p"], tot["closing_stock_mean_import_diff_p"] = prev_c, prev_m
    return {"days": days, "total": tot}


def run_ghost(period: ActualPeriod, advice: Sequence[AdviceRecord], cfg: SiteConfig | None = None, *,
              limits: GhostLimits | None = None, wear_p_per_kwh: float | None = None,
              outside_advice: str = "follow_actual", include_fallback: bool = False,
              ha_reserve_pct: float | None = None, strict: bool = False) -> dict:
    """Simulate the ghost, value both runs, and return the report as plain JSON-able data (see `render_text`)."""
    cfg = cfg or SiteConfig()
    limits = limits or GhostLimits()
    if outside_advice not in ("follow_actual", "self_use"):
        raise ValueError("outside_advice must be 'follow_actual' or 'self_use'")
    followable = [a for a in advice if a.followable(include_fallback)]
    ignored = [(a, a.not_followed_reason(include_fallback)) for a in advice if not a.followable(include_fallback)]
    wd: dict[str, list[datetime]] = {}                # G6: the rows that are not followed still say "none" for their kind from then on
    for a_, _why in ignored:
        wd.setdefault(a_.kind, []).append(a_.issued_at)
    for v_ in wd.values():
        v_.sort()
    cap = cfg.battery_capacity_kwh
    opening = period.soc0_pct / 100.0 * cap
    kw = dict(wear_p_per_kwh=wear_p_per_kwh, opening_stored_kwh=opening,
              opening_cost_p_per_kwh=period.opening_cost_p_per_kwh)
    actual_v = value_run(period.slots, period.tariff, cfg, **kw)
    run = _simulate(period, followable, cfg, limits, outside_advice, ha_reserve_pct, release=not strict, withdrawn=wd)
    ghost_v = value_run(run.slots, period.tariff, cfg, **kw)
    base_run = _simulate(period, [], cfg, limits, outside_advice, ha_reserve_pct, release=not strict)
    base_v = value_run(base_run.slots, period.tariff, cfg, **kw)
    strict_v = ghost_v if strict else value_run(
        _simulate(period, followable, cfg, limits, outside_advice, ha_reserve_pct, release=False, withdrawn=wd).slots,
        period.tariff, cfg, **kw)
    excl = any(v.total.unattributed_kwh > 1e-9 for v in (actual_v, ghost_v, base_v, strict_v))
    mean_p = sum(period.tariff.import_p) / len(period.tariff.import_p)
    dl = _deltas(actual_v, ghost_v, cfg.tz, mean_p, excl)
    bl = _deltas(actual_v, base_v, cfg.tz, mean_p, excl)
    sl_ = _deltas(actual_v, strict_v, cfg.tz, mean_p, excl)
    basis = (("net_after_wear" if wear_p_per_kwh is not None else "net_before_wear (wear price unknown)")
             + (", excluding unattributed energy" if excl else "") + ", stock-adjusted")
    a_soc, a_soc_src = _actual_soc(period, cfg)
    g_soc = run.soc_pct
    tz_name = cfg.tz
    tz = zone(tz_name)
    reserve_pct = cfg.effective_min_soc_pct(ha_reserve_pct)
    a_days, g_days = by_day(actual_v, tz_name), by_day(ghost_v, tz_name)

    def breaches(slots, socs, start_soc, skip=None):
        n, days, prev = 0, set(), start_soc
        for j, (s, x) in enumerate(zip(slots, socs)):
            if skip is not None and skip[j]:            # a slot replayed as recorded is reality's, not the advice's
                prev = x
                continue
            if s.dis > EPS and x < reserve_pct - 1e-6 and x < prev - 1e-12:
                n += 1
                days.add(_day_of(s, tz))
            prev = x
        return n, days

    g_br, g_br_days = breaches(run.slots, g_soc, period.soc0_pct, run.replayed)
    a_br, _ = breaches(period.slots, a_soc, period.soc0_pct)

    # --- per day
    idx_by_day: dict[date, list[int]] = {}
    for i, s in enumerate(period.slots):
        idx_by_day.setdefault(_day_of(s, tz), []).append(i)
    def import_cost(slots, idx):
        return sum(slots[i].imp * period.tariff.import_p[i] for i in idx)

    days = []
    for d, idx in sorted(idx_by_day.items()):
        a, g = a_days[d], g_days[d]
        x, bx = dl["days"][d], bl["days"][d]
        a_imp, g_imp = a.import_kwh, g.import_kwh
        a_ic, g_ic = import_cost(period.slots, idx), import_cost(run.slots, idx)
        days.append({
            "date": d.isoformat(), "slots": len(idx),
            "actual_net_before_wear_p": a.net_before_wear_p, "ghost_net_before_wear_p": g.net_before_wear_p,
            "actual_net_p": a.net_benefit_p, "ghost_net_p": g.net_benefit_p,
            "delta_realised_p": x["realised_p"], "delta_before_wear_p": x["realised_before_wear_p"],
            "stock_adjustment_p": x["stock_adjustment_p"], "stock_adjustment_cost_basis_rule_p": x["stock_cost_basis_p"],
            "stock_adjustment_mean_import_rule_p": x["stock_mean_import_p"],
            "delta_p": x["adjusted_p"], "delta_before_wear_stock_adjusted_p": x["adjusted_before_wear_p"],
            "model_baseline_delta_p": bx["adjusted_p"], "advice_effect_p": x["adjusted_p"] - bx["adjusted_p"], "basis": basis,
            "actual_bill_p": a.bill_p, "ghost_bill_p": g.bill_p,
            "actual_throughput_kwh": a.throughput_kwh, "ghost_throughput_kwh": g.throughput_kwh,
            "actual_min_soc_pct": min(a_soc[i] for i in idx), "ghost_min_soc_pct": min(g_soc[i] for i in idx),
            "actual_end_soc_pct": a_soc[idx[-1]], "ghost_end_soc_pct": g_soc[idx[-1]],
            "actual_closing_stored_kwh": a.closing_stored_kwh, "ghost_closing_stored_kwh": g.closing_stored_kwh,
            "actual_import_kwh": a_imp, "ghost_import_kwh": g_imp,
            "actual_import_avg_p": a_ic / a_imp if a_imp > EPS else None,
            "ghost_import_avg_p": g_ic / g_imp if g_imp > EPS else None,
            "extra_import_kwh_in_ghost": g_imp - a_imp, "extra_export_kwh_in_ghost": g.export_kwh - a.export_kwh,
            "advice_in_force_slots": sum(1 for i in idx if run.advice_idx[i] is not None)})
    # --- decision points where the runs diverged
    div, cur = [], None
    for i, (sa, sg) in enumerate(zip(period.slots, run.slots)):
        if abs(sa.chg - sg.chg) > DIVERGE_KWH or abs(sa.dis - sg.dis) > DIVERGE_KWH:
            if cur is not None and cur["last"] == i - 1:
                cur["last"] = i
                cur["idx"].append(i)
            else:
                cur = {"first": i, "last": i, "idx": [i]}
                div.append(cur)
    decisions = []
    for seg in div:
        ix = seg["idx"]
        f, l = ix[0], ix[-1]
        ks = sorted({run.advice_idx[i] for i in ix if run.advice_idx[i] is not None})
        a_c, g_c = sum(period.slots[i].chg for i in ix), sum(run.slots[i].chg for i in ix)
        a_d, g_d = sum(period.slots[i].dis for i in ix), sum(run.slots[i].dis for i in ix)
        bill_gain = sum(actual_v.rows[i].bill_p - ghost_v.rows[i].bill_p for i in ix)
        t0, t1 = period.slots[f].start, period.slots[l].start + timedelta(hours=period.slots[l].hours)
        when = f"{t0.astimezone(tz).date().isoformat()} {_hhmm(t0, tz)}-{_hhmm(t1, tz)}"
        if ks:
            adv = followable[ks[-1]]
            if adv.kind == KIND_CHARGE:
                why = (f"Intelligence advised charging to {adv.target_soc_pct:.0f}% (window {_hhmm(adv.window_start, tz)}-"
                       f"{_hhmm(adv.window_end, tz)}). The real battery took {a_c:.1f} kWh in, the ghost {g_c:.1f} kWh")
            else:
                why = (f"Intelligence advised exporting down to {adv.target_soc_pct:.0f}% ({adv.export_kwh:.1f} kWh). The real "
                       f"battery gave {a_d:.1f} kWh, the ghost {g_d:.1f} kWh")
        else:
            why = (f"No advice was in force, but the ghost's battery held a different charge ({g_soc[f]:.0f}% against "
                   f"{a_soc[f]:.0f}% at the end of the first slot) from an earlier divergence, so it could not repeat the real "
                   f"battery: charge {a_c:.1f} kWh real, {g_c:.1f} kWh ghost; discharge {a_d:.1f} kWh real, {g_d:.1f} kWh ghost")
        side = "cheaper" if bill_gain > 0 else "dearer"
        decisions.append({
            "when": when, "slots": len(ix), "caused_by_advice": bool(ks),
            "advice_ids": [followable[k].advice_id for k in ks],
            "actual_charge_kwh": a_c, "ghost_charge_kwh": g_c, "actual_discharge_kwh": a_d, "ghost_discharge_kwh": g_d,
            "actual_soc_end_pct": a_soc[l], "ghost_soc_end_pct": g_soc[l], "grid_bill_gain_in_window_p": bill_gain,
            "text": (f"{when}: {why}. SOC at the end: real {a_soc[l]:.0f}%, ghost {g_soc[l]:.0f}%. The ghost's grid bill "
                     f"inside these slots was {abs(bill_gain):.1f} p {side} (the effect carries on after the window).")})
    # --- summary
    lose = [x for x in days if x["delta_p"] < -LEVEL_BAND_P]
    ahead = [x for x in days if x["delta_p"] > LEVEL_BAND_P]
    worst = min(days, key=lambda x: x["delta_p"]) if days else None
    diverged_days = sum(1 for x in days if abs(x["delta_before_wear_p"]) > EPS or abs(x["delta_p"]) > EPS)
    flags_a, flags_g, flags_b = (list(v.total.flags) for v in (actual_v, ghost_v, base_v))
    rel_value = dl["total"]["adjusted_p"] - sl_["total"]["adjusted_p"]
    release = {"enabled": not strict, "discharge_kwh": run.released_dis_kwh, "charge_kwh": run.released_chg_kwh,
               "value_p": 0.0 if strict else rel_value,
               "note": ("Where the real battery was pinned at its floor or at full, the ghost may use the energy it holds the way "
                        "self-use would. This line is the value that adds to the ghost only; strict=True switches it off.")}
    outside = {"kwh": run.outside_kwh, "slots": run.outside_slots,
               "note": ("Real flows that broke the config's power limits or reserve, replayed as recorded while the ghost still held "
                        "the real battery's charge. Reality is reality; advice-driven flows never get this leeway.")}
    n = len(days)
    ready = {
        "evidence_only": True, "decision": None,
        "days_compared": n, "days_diverged": diverged_days, "days_ghost_ahead": len(ahead), "days_ghost_behind": len(lose),
        "days_level": n - len(ahead) - len(lose),
        "share_days_ghost_ahead": (len(ahead) / n) if n else None,
        "worst_ghost_day": None if worst is None else {"date": worst["date"], "delta_p": worst["delta_p"]},
        "ghost_below_reserve_slots": g_br, "ghost_below_reserve_days": len(g_br_days),
        "ghost_below_reserve_dates": sorted(d.isoformat() for d in g_br_days),
        "reserve_pct": reserve_pct, "basis": basis, "stock_rule": STOCK_RULE,
        "delta_realised_p": dl["total"]["realised_p"], "delta_stock_adjusted_p": dl["total"]["adjusted_p"],
        "model_baseline_delta_p": bl["total"]["adjusted_p"], "advice_effect_p": dl["total"]["adjusted_p"] - bl["total"]["adjusted_p"],
        "model_baseline_note": "The no-advice ghost against reality: 0 when the recorded flows are replayed exactly "
                               "(the usual case); it may differ if a recorded SOC series disagrees with the flow reconstruction. It is "
                               "subtracted out of the advice effect either way. Read the advice effect, not the raw delta.",
        "replayed_outside_limits": outside, "ghost_extra_curtailed_kwh": run.curtailed_extra_kwh,
        "curtailed_absorbed_kwh": run.curtailed_absorbed_kwh, "constraint_release": release, "delta_stock_adjusted_without_release_p": sl_["total"]["adjusted_p"],
        "data_quality": {"actual_flags": flags_a, "ghost_flags": flags_g, "model_baseline_flags": flags_b,
                         "unattributed_energy_excluded": excl},
        "note": "Evidence for the owner's decision about assisted mode. It decides nothing and enables nothing."}
    total_a, total_g = actual_v.total, ghost_v.total
    return {
        "model_version": MODEL_VERSION, "label": LABEL, "simulated": True, "intelligence_controlled_nothing": True,
        "timezone": tz_name,
        "settings": {"outside_advice": outside_advice, "include_fallback": include_fallback,
                     "max_charge_kw": cfg.max_grid_charge_kw if limits.max_charge_kw is None else limits.max_charge_kw,
                     "max_discharge_kw": cfg.max_grid_charge_kw if limits.max_discharge_kw is None else limits.max_discharge_kw,
                     "limits_from_config": limits.max_charge_kw is None or limits.max_discharge_kw is None,
                     "reserve_pct": reserve_pct, "wear_p_per_kwh": wear_p_per_kwh, "battery_capacity_kwh": cap,
                     "export_limit_kw": period.tariff.export_limit_kw, "eta_one_way": eta_one_way(cfg),
                     "actual_soc_source": a_soc_src},
        "advice": {"records": len(advice), "followed": len(followable),
                   "not_followed": [{"advice_id": a.advice_id, "kind": a.kind, "status": a.status, "reason": r} for a, r in ignored]},
        "totals": {
            "actual": total_a.to_dict(), "ghost": total_g.to_dict(),
            "delta_headline_p": dl["total"]["adjusted_p"], "delta_realised_p": dl["total"]["realised_p"],
            "delta_before_wear_p": dl["total"]["realised_before_wear_p"],
            "stock_adjustment_p": dl["total"]["stock_adjustment_p"], "stock_rule": STOCK_RULE,
            "stock_adjustment_cost_basis_rule_p": dl["total"]["stock_cost_basis_p"],
            "stock_adjustment_mean_import_rule_p": dl["total"]["stock_mean_import_p"],
            "mean_import_price_p": mean_p, "model_baseline_delta_p": bl["total"]["adjusted_p"],
            "advice_effect_p": dl["total"]["adjusted_p"] - bl["total"]["adjusted_p"], "constraint_release": release,
            "replayed_outside_limits": outside, "ghost_extra_curtailed_kwh": run.curtailed_extra_kwh,
            "curtailed_absorbed_kwh": run.curtailed_absorbed_kwh,
            "delta_bill_p": total_a.bill_p - total_g.bill_p,
            "headline_basis": basis,
            "actual_min_soc_pct": min(a_soc), "ghost_min_soc_pct": min(g_soc),
            "actual_throughput_kwh": total_a.throughput_kwh, "ghost_throughput_kwh": total_g.throughput_kwh,
            "closing_stored_difference_kwh": total_g.closing_stored_kwh - total_a.closing_stored_kwh,
            "actual_below_reserve_slots": a_br},
        "days": days, "decision_points": decisions, "days_ghost_loses": lose,
        "ready_for_assisted_evidence": ready,
        "caveats": [
            "Prices are applied to metered energy; the ghost's flows are simulated, so model error is part of the difference.",
            "Closing stored energy differs between the runs; it is valued by the stock rule (stock_rule), not counted as realised money.",
            "Re-issued dump advice: each advice is a fresh export budget sized from the SOC at its issue; the latest one in force replaces the earlier one's remainder.",
            "Grid bill deltas include battery state differences that carry across midnight.",
            "Replay rule: while the ghost's stored energy equals reality's and no advice is in force, each slot is replayed exactly "
            "(gross charge and discharge, metered import and export), so with no advice the ghost IS reality, including slots where "
            "the real battery charged and discharged together or broke the config's limits or reserve (disclosed as "
            "replayed_outside_limits). After the ghost's charge differs, gross flows are replayed only as far as the ghost's own "
            "charge and the reserve allow, and the grid is the metered one plus the change in the battery flows (perturbation rule: export "
            "first, then import when more is needed; import first, then permitted export, then curtailment when less is needed).",
            f"Replayed outside the config's limits or reserve: {outside['kwh']:.2f} kWh in {outside['slots']} slot(s)."]}


def render_text(rep: Mapping) -> str:
    """The report as plain text for the terminal."""
    L = [rep["label"], ""]
    st = rep["settings"]
    L.append(f"Policy outside advice: {st['outside_advice']}; reserve {st['reserve_pct']:.0f}%; "
             f"power limits {st['max_charge_kw']:g}/{st['max_discharge_kw']:g} kW"
             + (" (taken from the config's grid-charge limit)" if st["limits_from_config"] else "")
             + f"; actual SOC {st['actual_soc_source']}.")
    L.append(f"Advice records {rep['advice']['records']}, followed {rep['advice']['followed']}.")
    t = rep["totals"]
    L += ["", f"TOTAL ({t['headline_basis']}): ghost minus actual, REALISED money {t['delta_realised_p']:+.1f} p; closing-stock "
          f"adjustment {t['stock_adjustment_p']:+.1f} p; STOCK-ADJUSTED {t['delta_headline_p']:+.1f} p (grid bill "
          f"{abs(t['delta_bill_p']):.1f} p {'cheaper' if t['delta_bill_p'] >= 0 else 'dearer'} in the ghost)",
          f"  stock rule: {t['stock_rule']} Here: cost-basis rule {t['stock_adjustment_cost_basis_rule_p']:+.1f} p, mean-import "
          f"rule ({t['mean_import_price_p']:.1f} p) {t['stock_adjustment_mean_import_rule_p']:+.1f} p.",
          f"  model baseline (no advice, ghost minus actual) {t['model_baseline_delta_p']:+.1f} p; advice effect "
          f"{t['advice_effect_p']:+.1f} p; constraint release {t['constraint_release']['discharge_kwh']:.1f} kWh discharged, "
          f"{t['constraint_release']['charge_kwh']:.1f} kWh charged, worth {t['constraint_release']['value_p']:+.1f} p to the ghost"
          + ("" if t["constraint_release"]["enabled"] else " (strict: switched off)"),
          f"  min SOC actual {t['actual_min_soc_pct']:.0f}% / ghost {t['ghost_min_soc_pct']:.0f}%; throughput actual "
          f"{t['actual_throughput_kwh']:.1f} kWh / ghost {t['ghost_throughput_kwh']:.1f} kWh; ghost ends "
          f"{t['closing_stored_difference_kwh']:+.1f} kWh stored vs actual"]
    for k in ("actual", "ghost"):
        s = t[k]
        L.append(f"  {k}: avoided import {s['gross_avoided_import_p']:.1f} + export {s['export_revenue_battery_p']:.1f} - grid "
                 f"{s['grid_energy_cost_p']:.1f} - solar opportunity {s['solar_opportunity_cost_p']:.1f} - losses "
                 f"{s['losses_p']:.1f} = before wear {s['net_before_wear_p']:.1f}; wear "
                 + ("unknown" if s["wear_p"] is None else f"{s['wear_p']:.1f}"))
    L += ["", "PER DAY (ghost minus actual, p; realised | stock-adjusted | no-advice baseline):"]
    for d in rep["days"]:
        L.append(f"  {d['date']}  actual {d['actual_net_before_wear_p']:8.1f}  ghost {d['ghost_net_before_wear_p']:8.1f}  "
                 f"realised {d['delta_realised_p']:+8.1f}  adjusted {d['delta_p']:+8.1f}  baseline {d['model_baseline_delta_p']:+8.1f}"
                 f"  minSOC {d['actual_min_soc_pct']:.0f}/{d['ghost_min_soc_pct']:.0f}%")
    L += ["", f"DAYS THE GHOST LOSES ({len(rep['days_ghost_loses'])}):"]
    for d in rep["days_ghost_loses"]:
        ap, gp = d["actual_import_avg_p"], d["ghost_import_avg_p"]
        L.append(f"  {d['date']}: {d['delta_p']:+.1f} p; the ghost imported {d['ghost_import_kwh']:.1f} kWh"
                 + ("" if gp is None else f" at {gp:.1f} p") + f" against {d['actual_import_kwh']:.1f} kWh"
                 + ("" if ap is None else f" at {ap:.1f} p") + f" in reality, and exported {d['extra_export_kwh_in_ghost']:+.1f} kWh more")
    L += ["", f"DECISION POINTS WHERE THE RUNS DIVERGED ({len(rep['decision_points'])}):"]
    L += [f"  - {x['text']}" for x in rep["decision_points"]]
    r = rep["ready_for_assisted_evidence"]
    w = r["worst_ghost_day"]
    ol = r["replayed_outside_limits"]
    L += ["", "EVIDENCE FOR THE ASSISTED-MODE DECISION (decides nothing):",
          f"  days compared {r['days_compared']}; diverged {r['days_diverged']}; ghost ahead {r['days_ghost_ahead']}, behind "
          f"{r['days_ghost_behind']}, level {r['days_level']}; share ahead "
          + ("n/a" if r["share_days_ghost_ahead"] is None else f"{100 * r['share_days_ghost_ahead']:.0f}%"),
          "  worst ghost day: " + ("n/a" if w is None else f"{w['date']} ({w['delta_p']:+.1f} p)"),
          f"  ghost below the {r['reserve_pct']:.0f}% reserve: {r['ghost_below_reserve_slots']} slot(s)",
          f"  realised {r['delta_realised_p']:+.1f} p, stock-adjusted {r['delta_stock_adjusted_p']:+.1f} p (without constraint "
          f"release {r['delta_stock_adjusted_without_release_p']:+.1f} p); model baseline {r['model_baseline_delta_p']:+.1f} p, advice "
          f"effect {r['advice_effect_p']:+.1f} p",
          f"  replayed outside the config's limits or reserve (real flows kept as recorded): {ol['kwh']:.2f} kWh in {ol['slots']} slot(s)"]
    dq = r["data_quality"]
    L += ["", "DATA QUALITY (flags of each run's value ledger):"]
    for k in ("actual_flags", "ghost_flags", "model_baseline_flags"):
        L.append(f"  {k[:-6]}: " + ("; ".join(dq[k]) if dq[k] else "none"))
    if dq["unattributed_energy_excluded"]:
        L.append("  Unattributed energy is EXCLUDED from every figure above.")
    nf = rep["advice"]["not_followed"]
    if nf:
        L.append("Advice not followed: " + ", ".join(f"{x['advice_id'] or x['kind']} ({x['reason']})" for x in nf))
    L += ["", "Caveats:"] + [f"  - {c}" for c in rep["caveats"]]
    return "\n".join(L)


def parse_export(obj: Mapping) -> dict:
    """Parse the JSON export (format in tools/ghost_report.py) into {cfg, period, advice, limits, wear_p_per_kwh, options}."""
    if obj.get("format") != "ecco-intel-ghost-export/1":
        raise ValueError("unsupported export format (expected ecco-intel-ghost-export/1)")
    fields = set(SiteConfig.__dataclass_fields__)
    site = dict(obj.get("site", {}))
    bad = [k for k in site if k not in fields]
    if bad:
        raise ValueError(f"unknown site field(s): {bad}")
    cfg = SiteConfig(**site)
    step_h = float(obj["step_minutes"]) / 60.0
    slots, imp_p, exp_p, ok, soc = [], [], [], [], []
    for r in obj["slots"]:
        t = _aware(r["t"], "slot t")
        cur = float(r.get("curtailed", 0.0))
        if "import" in r and "export" in r:
            slots.append(Slot(t, step_h, r["pv"], r["load"], r["import"], r["export"], r["charge"], r["discharge"], cur))
        else:
            slots.append(Slot.derive(t, step_h, r["pv"], r["load"], r["charge"], r["discharge"], cur))
        imp_p.append(r["import_p"])
        exp_p.append(r["export_p"])
        ok.append(bool(r.get("export_ok", True)))
        soc.append(r.get("soc_pct"))
    have_soc = all(x is not None for x in soc)
    tariff = Tariff.make(len(slots), imp_p, exp_p, ok, obj.get("export_limit_kw"))
    period = ActualPeriod(tuple(slots), tariff, float(obj["soc0_pct"]), tuple(soc) if have_soc else None,
                          obj.get("opening_cost_p_per_kwh"))
    lim = obj.get("limits", {})
    return {"cfg": cfg, "period": period, "advice": [AdviceRecord.from_dict(a) for a in obj.get("advice", [])],
            "limits": GhostLimits(lim.get("max_charge_kw"), lim.get("max_discharge_kw")),
            "wear_p_per_kwh": obj.get("wear_p_per_kwh"),
            "options": {k: obj[k] for k in ("outside_advice", "include_fallback", "ha_reserve_pct", "strict") if k in obj}}
