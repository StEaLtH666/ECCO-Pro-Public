"""Honest financial value of the battery for a period (read-only analysis, SHADOW package: it applies nothing).

Question answered: over these slots, what did having the battery really earn, once battery losses, the export income the
stored solar could have earned instead, and (when known) wear are counted? "Gross avoided import" is NOT the benefit: it is
only the first line of the ledger.

Units: energy in kWh per slot, AC side (what the meters and the inverter's AC flows show); prices in pence per kWh; money in
pence. Every pence figure is a positive magnitude of the thing it names, and the net adds and subtracts them, so the signs are
in the formula, not hidden in the numbers. `bill_p` is the one signed figure: grid import cost minus export income (positive =
the household paid).

Slot balance (AC side):   pv + import + discharge = load + export + charge + curtailed
    charge / discharge are the battery's AC-side flows; the cell stores charge * eta and gives up discharge / eta, with eta the
    one-way efficiency of config (`battery.eta_one_way`, sqrt of the round trip). `Slot.derive` builds import/export from the
    other flows when a series has no meter figures; a series whose slots do not balance is reported (max residual, count).

What the battery earned, in the order of the ledger:
    gross_avoided_import_p        import price x battery energy that served the house (the headline people quote)
  + export_revenue_battery_p      export price x battery energy that was exported
  - grid_energy_cost_p            what the grid energy that was later discharged cost when it was charged (face price, no loss)
  - solar_opportunity_cost_p      what the stored solar that was later discharged could have earned if exported instead
  - opening_stock_cost_p          the same for energy that was already in the battery when the period began
  - losses_p                      the round-trip loss on the discharged energy, at the cost of the energy that was lost
  = net_before_wear_p
  - wear_p                        wear_p_per_kwh x throughput; None when no wear price is known
  = net_benefit_p                 None (never silently the full net) when wear is unknown; then `headline_*` says so

Solar is not free and not worth the export tariff by assumption. Solar that is stored costs the export price of its slot ONLY
if it could have been exported then: export permitted in that slot, headroom under the export limit (limit x slot length minus
what was exported), and no curtailment in that slot. Otherwise it costs 0 (it would have been wasted). Stored solar and grid
energy are tagged by source in a well-mixed tank (one pool per source, drawn pro rata), so a discharge is valued by the real
mix it came from. Energy the data cannot attribute (a discharge beyond the tracked stock) is tagged `unattributed` at cost 0
and flagged, never hidden; `net_before_wear_excl_unattributed_p` removes the income credited to it, and the headline basis says
when it is included. Energy left in the battery at the end is not realised value: it stays in the tank at its cost, and
the closing composition says what it is made of (which is why two runs ending with different charge need that line next to them).

Throughput (for wear) = mean of stored energy in and stored energy out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Sequence

from .battery import eta_one_way
from .config import SiteConfig
from .timeutil import zone

MODEL_VERSION = "intel-value/1"
SRC_GRID, SRC_SOLAR_X, SRC_SOLAR_N, SRC_OPEN, SRC_UNATTR = (
    "grid", "solar_exportable", "solar_not_exportable", "opening", "unattributed")
SOURCES = (SRC_GRID, SRC_SOLAR_X, SRC_SOLAR_N, SRC_OPEN, SRC_UNATTR)
DEFAULT_BALANCE_TOL_KWH = 0.02


def _fin(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class Slot:
    """One fixed-length step of an actual (or simulated) period. All energies are >= 0 kWh in the slot."""
    start: datetime          # aware
    hours: float
    pv: float
    load: float
    imp: float               # grid import
    exp: float               # grid export
    chg: float               # battery charge, AC side
    dis: float               # battery discharge, AC side
    curtailed: float = 0.0   # PV that was spilled (counted in pv, not usable)

    def __post_init__(self) -> None:
        if not isinstance(self.start, datetime) or self.start.tzinfo is None:
            raise ValueError("Slot.start must be an aware datetime")
        if not (_fin(self.hours) and self.hours > 0):
            raise ValueError("Slot.hours must be a positive number")
        for n in ("pv", "load", "imp", "exp", "chg", "dis", "curtailed"):
            v = getattr(self, n)
            if not (_fin(v) and v >= 0):
                raise ValueError(f"Slot.{n} must be a finite number >= 0, got {v!r}")

    @property
    def residual(self) -> float:
        """pv + import + discharge - load - export - charge - curtailed (0 for a balanced slot)."""
        return self.pv + self.imp + self.dis - self.load - self.exp - self.chg - self.curtailed

    @classmethod
    def derive(cls, start: datetime, hours: float, pv: float, load: float, chg: float, dis: float,
               curtailed: float = 0.0) -> "Slot":
        """Grid import / export from the other flows (what the grid must have supplied or taken)."""
        net = load + chg + curtailed - pv - dis
        return cls(start, hours, pv, load, max(0.0, net), max(0.0, -net), chg, dis, curtailed)


@dataclass(frozen=True)
class Tariff:
    """Per-slot prices and export rules. Build with `Tariff.make` (scalars are broadcast to every slot)."""
    import_p: tuple[float, ...]
    export_p: tuple[float, ...]
    export_permitted: tuple[bool, ...]
    export_limit_kw: float | None = None      # None = no limit

    def __post_init__(self) -> None:
        n = len(self.import_p)
        if not (n == len(self.export_p) == len(self.export_permitted)):
            raise ValueError("Tariff series must have the same length")
        if not all(_fin(x) for x in self.import_p + self.export_p):
            raise ValueError("Tariff prices must be finite numbers")
        if self.export_limit_kw is not None and not (_fin(self.export_limit_kw) and self.export_limit_kw >= 0):
            raise ValueError("export_limit_kw must be None or a finite number >= 0")

    def __len__(self) -> int:
        return len(self.import_p)

    @classmethod
    def make(cls, n: int, import_p, export_p, export_permitted=True, export_limit_kw: float | None = None) -> "Tariff":
        def seq(v, kind):
            if isinstance(v, (list, tuple)):
                if len(v) != n:
                    raise ValueError(f"{kind} has {len(v)} entries for {n} slots")
                return tuple(v)
            return (v,) * n
        return cls(tuple(float(x) for x in seq(import_p, "import_p")), tuple(float(x) for x in seq(export_p, "export_p")),
                   tuple(bool(x) for x in seq(export_permitted, "export_permitted")), export_limit_kw)


class _Tank:
    """Well-mixed tank: one pool per source holding stored kWh and its cost basis in pence."""

    def __init__(self, eta: float) -> None:
        self.eta = eta
        self.kwh = {s: 0.0 for s in SOURCES}
        self.cost = {s: 0.0 for s in SOURCES}

    def add(self, src: str, ac_kwh: float, price_p: float) -> None:
        if ac_kwh > 0:
            self.kwh[src] += ac_kwh * self.eta
            self.cost[src] += ac_kwh * price_p

    def draw(self, stored: float) -> dict[str, tuple[float, float]]:
        """Remove `stored` kWh pro rata over the pools. Returns {source: (stored kWh taken, cost taken)}; any part the tank
        cannot supply comes from `unattributed` at cost 0."""
        total = sum(self.kwh.values())
        out: dict[str, tuple[float, float]] = {}
        take = min(stored, total)
        if take > 0 and total > 0:
            frac = take / total
            for s in SOURCES:
                k, c = self.kwh[s] * frac, self.cost[s] * frac
                if k > 0 or c > 0:
                    out[s] = (k, c)
                self.kwh[s] -= k
                self.cost[s] -= c
        short = stored - take
        if short > 1e-12:
            k0, c0 = out.get(SRC_UNATTR, (0.0, 0.0))
            out[SRC_UNATTR] = (k0 + short, c0)
        return out


@dataclass
class SlotRow:
    """What one slot contributed to the ledger (kept so a run can be summed over any sub-period, e.g. per day)."""
    start: datetime
    hours: float
    chg: float
    dis: float
    imp: float
    exp: float
    residual: float
    bill_p: float
    dis_to_load: float
    dis_to_export: float
    avoided_import_p: float
    export_revenue_p: float
    grid_cost_p: float
    solar_cost_p: float
    opening_cost_p: float
    losses_p: float
    grid_charged_p: float            # all grid energy charged in the slot, at the import price (realised or not)
    loss_kwh: float                  # physical loss in the slot: charge loss + discharge loss
    stored_in: float
    stored_out: float
    solar_exportable_kwh: float
    solar_not_exportable_kwh: float
    grid_charged_kwh: float
    unattributed_kwh: float          # stored kWh discharged that the tank could not attribute
    unattr_value_p: float            # the avoided import / export income credited to that unattributed share (at cost 0)
    tank_kwh: tuple[float, ...]      # stored kWh per source after the slot (order SOURCES)
    tank_cost_p: tuple[float, ...]


@dataclass(frozen=True)
class ValueSummary:
    """The ledger for a set of slots. See the module docstring for every line."""
    slots: int
    pv_kwh: float
    load_kwh: float
    import_kwh: float
    export_kwh: float
    charge_kwh: float
    discharge_kwh: float
    discharge_to_load_kwh: float
    discharge_to_export_kwh: float
    gross_avoided_import_p: float
    export_revenue_battery_p: float
    grid_energy_cost_p: float
    solar_opportunity_cost_p: float
    opening_stock_cost_p: float
    losses_p: float
    losses_kwh: float
    grid_charged_total_p: float
    solar_stored_exportable_kwh: float
    solar_stored_not_exportable_kwh: float
    throughput_kwh: float
    wear_p: float | None
    wear_known: bool
    net_before_wear_p: float
    net_benefit_p: float | None
    unattributed_kwh: float
    unattributed_value_p: float
    net_before_wear_excl_unattributed_p: float
    headline_excl_unattributed_p: float
    headline_p: float
    headline_basis: str
    bill_p: float
    closing_stored_kwh: float
    closing_cost_basis_p: float
    closing_composition: dict
    flags: tuple[str, ...]

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["flags"] = list(self.flags)
        return _round(d)


def _round(x, nd: int = 4):
    if isinstance(x, float):
        return round(x, nd)
    if isinstance(x, dict):
        return {k: _round(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v, nd) for v in x]
    return x


@dataclass
class ValueResult:
    rows: list[SlotRow]
    slots: list[Slot]
    total: ValueSummary
    eta: float
    wear_p_per_kwh: float | None
    max_abs_residual_kwh: float
    unbalanced_slots: int
    flags: tuple[str, ...] = ()

    def summarise(self, idx: Sequence[int]) -> ValueSummary:
        """The ledger for the slots at positions `idx` (the closing composition is that after the last of them)."""
        return _with_totals(_summarise([self.rows[i] for i in idx], self.wear_p_per_kwh, self.eta, self.flags),
                            [self.slots[i] for i in idx])


def _summarise(rows: Sequence[SlotRow], wear: float | None, eta: float, flags: tuple[str, ...]) -> ValueSummary:
    s = lambda f: math.fsum(getattr(r, f) for r in rows)  # noqa: E731
    thr = math.fsum((r.stored_in + r.stored_out) / 2.0 for r in rows)
    avoided, exp_rev = s("avoided_import_p"), s("export_revenue_p")
    grid_c, sol_c, open_c, loss_p = s("grid_cost_p"), s("solar_cost_p"), s("opening_cost_p"), s("losses_p")
    before = avoided + exp_rev - grid_c - sol_c - open_c - loss_p
    unattr_v = s("unattr_value_p")
    unattr_k = s("unattributed_kwh")
    before_x = before - unattr_v
    wear_p = None if wear is None else wear * thr
    net = None if wear_p is None else before - wear_p
    head_x = before_x if wear_p is None else before_x - wear_p
    last = rows[-1] if rows else None
    comp: dict = {}
    closing = 0.0
    cbasis = 0.0
    if last is not None:
        closing = math.fsum(last.tank_kwh)
        cbasis = math.fsum(last.tank_cost_p)
        for name, k, c in zip(SOURCES, last.tank_kwh, last.tank_cost_p):
            if k > 1e-9:
                comp[name] = {"kwh": k, "share": k / closing if closing > 0 else 0.0, "cost_p": c}
    fl = list(flags)
    if wear is None:
        fl.append("WEAR_UNKNOWN: net_benefit_p is None; the headline is the net BEFORE wear")
    if s("unattributed_kwh") > 1e-9:
        fl.append("UNATTRIBUTED_DISCHARGE: some discharged energy was not in the tracked stock and is valued at cost 0")
    return ValueSummary(
        slots=len(rows), pv_kwh=0.0, load_kwh=0.0, import_kwh=s("imp"), export_kwh=s("exp"), charge_kwh=s("chg"),
        discharge_kwh=s("dis"), discharge_to_load_kwh=s("dis_to_load"), discharge_to_export_kwh=s("dis_to_export"),
        gross_avoided_import_p=avoided, export_revenue_battery_p=exp_rev, grid_energy_cost_p=grid_c,
        solar_opportunity_cost_p=sol_c, opening_stock_cost_p=open_c, losses_p=loss_p, losses_kwh=s("loss_kwh"),
        grid_charged_total_p=s("grid_charged_p"), solar_stored_exportable_kwh=s("solar_exportable_kwh"),
        solar_stored_not_exportable_kwh=s("solar_not_exportable_kwh"), throughput_kwh=thr, wear_p=wear_p,
        wear_known=wear is not None, net_before_wear_p=before, net_benefit_p=net, unattributed_kwh=unattr_k,
        unattributed_value_p=unattr_v, net_before_wear_excl_unattributed_p=before_x, headline_excl_unattributed_p=head_x,
        headline_p=before if net is None else net,
        headline_basis=("net_before_wear (wear price unknown)" if net is None else "net_after_wear")
        + (" [INCLUDES unattributed energy valued at cost 0; see net_before_wear_excl_unattributed_p]" if unattr_k > 1e-9 else ""),
        bill_p=s("bill_p"), closing_stored_kwh=closing, closing_cost_basis_p=cbasis, closing_composition=comp,
        flags=tuple(fl))


def value_run(slots: Sequence[Slot], tariff: Tariff, cfg: SiteConfig | None = None, *, eta: float | None = None,
              wear_p_per_kwh: float | None = None, opening_stored_kwh: float = 0.0,
              opening_cost_p_per_kwh: float | None = None, balance_tol_kwh: float = DEFAULT_BALANCE_TOL_KWH,
              strict: bool = False) -> ValueResult:
    """Value the battery over `slots` (time-ordered, any fixed step). `eta` defaults to the config's one-way efficiency.
    `opening_stored_kwh` is the energy stored at the start; its cost basis (a face price per kWh delivered) is
    `opening_cost_p_per_kwh` (pence per AC-charged kWh, like a grid price; None = unknown = 0 and flagged). strict=True raises on a slot that does not balance."""
    cfg = cfg or SiteConfig()
    eta = eta_one_way(cfg) if eta is None else eta
    if not (_fin(eta) and 0.0 < eta <= 1.0):
        raise ValueError("eta must be in (0, 1]")
    if wear_p_per_kwh is not None and not (_fin(wear_p_per_kwh) and wear_p_per_kwh >= 0):
        raise ValueError("wear_p_per_kwh must be None (unknown) or a finite number >= 0")
    if not (_fin(opening_stored_kwh) and opening_stored_kwh >= 0):
        raise ValueError("opening_stored_kwh must be a finite number >= 0")
    if opening_cost_p_per_kwh is not None and not _fin(opening_cost_p_per_kwh):
        raise ValueError("opening_cost_p_per_kwh must be None or finite")
    if len(tariff) != len(slots):
        raise ValueError(f"tariff has {len(tariff)} slots, the series has {len(slots)}")
    for a, b in zip(slots, slots[1:]):
        if not b.start > a.start:
            raise ValueError("slots must be strictly increasing in time")

    flags: list[str] = []
    tank = _Tank(eta)
    if opening_stored_kwh > 0:
        tank.kwh[SRC_OPEN] = opening_stored_kwh
        tank.cost[SRC_OPEN] = (opening_cost_p_per_kwh or 0.0) * opening_stored_kwh / eta
        if opening_cost_p_per_kwh is None:
            flags.append("OPENING_STOCK_UNPRICED: energy already stored at the start is valued at cost 0")
    face = eta * eta                       # taken cost -> face price of the energy delivered
    rows: list[SlotRow] = []
    max_res = 0.0
    bad = 0
    for i, sl in enumerate(slots):
        imp_p, exp_p = tariff.import_p[i], tariff.export_p[i]
        res = sl.residual
        max_res = max(max_res, abs(res))
        if abs(res) > balance_tol_kwh:
            bad += 1
            if strict:
                raise ValueError(f"slot {i} ({sl.start.isoformat()}) does not balance: residual {res:.3f} kWh")
        # --- discharge first (from the stock that existed at the start of the slot), then charge
        drawn = tank.draw(sl.dis / eta) if sl.dis > 0 else {}
        taken_cost = math.fsum(c for s_, (_, c) in drawn.items())
        grid_c = drawn.get(SRC_GRID, (0, 0))[1] * face
        sol_c = (drawn.get(SRC_SOLAR_X, (0, 0))[1] + drawn.get(SRC_SOLAR_N, (0, 0))[1]) * face
        open_c = drawn.get(SRC_OPEN, (0, 0))[1] * face
        priced_cost = taken_cost - drawn.get(SRC_UNATTR, (0, 0))[1]
        loss_p = priced_cost * (1.0 - face)
        unattr_stored = drawn.get(SRC_UNATTR, (0.0, 0.0))[0]
        unattr_frac = min(1.0, unattr_stored / (sl.dis / eta)) if sl.dis > 0 else 0.0
        # --- where the discharge went and where the charge came from
        pv_use = max(0.0, sl.pv - sl.curtailed)
        direct = min(pv_use, sl.load)
        surplus = pv_use - direct
        pv_to_batt = min(sl.chg, surplus)
        pv_to_exp = min(sl.exp, max(0.0, surplus - pv_to_batt))
        dis_to_exp = min(sl.dis, max(0.0, sl.exp - pv_to_exp))
        dis_to_load = sl.dis - dis_to_exp
        if tariff.export_permitted[i] and sl.curtailed <= 1e-12:
            head = math.inf if tariff.export_limit_kw is None else max(0.0, tariff.export_limit_kw * sl.hours - sl.exp)
            sol_x = min(pv_to_batt, head)
        else:
            sol_x = 0.0
        sol_n = pv_to_batt - sol_x
        grid_to_batt = sl.chg - pv_to_batt
        if grid_to_batt > sl.imp + balance_tol_kwh and "CHARGE_FROM_GRID_EXCEEDS_IMPORT" not in flags:
            flags.append("CHARGE_FROM_GRID_EXCEEDS_IMPORT: in some slot the inferred grid charge is above the metered import")
        tank.add(SRC_SOLAR_X, sol_x, max(0.0, exp_p))
        tank.add(SRC_SOLAR_N, sol_n, 0.0)
        tank.add(SRC_GRID, grid_to_batt, imp_p)
        rows.append(SlotRow(
            start=sl.start, hours=sl.hours, chg=sl.chg, dis=sl.dis, imp=sl.imp, exp=sl.exp, residual=res,
            bill_p=sl.imp * imp_p - sl.exp * exp_p, dis_to_load=dis_to_load, dis_to_export=dis_to_exp,
            avoided_import_p=dis_to_load * imp_p, export_revenue_p=dis_to_exp * exp_p, grid_cost_p=grid_c,
            solar_cost_p=sol_c, opening_cost_p=open_c, losses_p=loss_p, grid_charged_p=grid_to_batt * imp_p,
            loss_kwh=sl.chg * (1.0 - eta) + sl.dis * (1.0 / eta - 1.0), stored_in=sl.chg * eta,
            stored_out=sl.dis / eta, solar_exportable_kwh=sol_x, solar_not_exportable_kwh=sol_n,
            grid_charged_kwh=grid_to_batt, unattributed_kwh=unattr_stored,
            unattr_value_p=unattr_frac * (dis_to_load * imp_p + dis_to_exp * exp_p),
            tank_kwh=tuple(tank.kwh[s_] for s_ in SOURCES), tank_cost_p=tuple(tank.cost[s_] for s_ in SOURCES)))
    if bad:
        flags.append(f"UNBALANCED_SLOTS: {bad} slot(s) off by more than {balance_tol_kwh} kWh (max {max_res:.3f} kWh)")
    if any(r.chg > 1e-9 and r.dis > 1e-9 for r in rows):
        flags.append("SIMULTANEOUS_CHARGE_DISCHARGE: some slots show both; they are valued as given")
    base = tuple(flags)
    total = _with_totals(_summarise(rows, wear_p_per_kwh, eta, base), slots)
    return ValueResult(rows, list(slots), total, eta, wear_p_per_kwh, max_res, bad, base)


def _with_totals(s: ValueSummary, slots: Sequence[Slot]) -> ValueSummary:
    return replace(s, pv_kwh=math.fsum(x.pv for x in slots), load_kwh=math.fsum(x.load for x in slots))


def by_day(result: ValueResult, tz_name: str) -> dict[date, ValueSummary]:
    """One summary per local calendar day. The tank runs across the whole period, so a day's discharge is valued by the
    energy that was really in the battery, wherever it was charged."""
    tz = zone(tz_name)
    groups: dict[date, list[int]] = {}
    for i, r in enumerate(result.rows):
        groups.setdefault(r.start.astimezone(tz).date(), []).append(i)
    return {d: result.summarise(groups[d]) for d in sorted(groups)}
