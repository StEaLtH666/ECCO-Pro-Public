"""Seeded, deterministic fault injectors for the data-quality rules (tests and offline self-checks only; SHADOW).

Each injector takes a CycleInputs (or the History inside one) and a seed and returns a NEW CycleInputs with one fault; its
input is never modified. FAULTS names every fault with the rule that must detect it:

    kind       "cycle" (live snapshot / readings) or "history" (the hourly History)
    detector   "assess" (quality.assess_inputs), "prepare" (quality.prepare_history) or "both"
    codes      finding codes, any one of which detects the fault
    blocks     items that must be BLOCKED when the fault is present (empty for a WARN-only rule)

The bases are synthetic: intelligence/tests/_cycle_fixtures.py (fictional 2030, every reading fresh) and
synthetic.make_history households. Injected values are drawn from random.Random seeded with "<fault>:<seed>", so a run is
identical in every process. Nothing here reads a clock, a file or any real installation.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Callable, Mapping

from ecco_core.state import Snapshot

from .advisor import LiveInputs
from .advisory_contract import SITE_READING_KEYS, CycleInputs, SiteReading
from .config import SiteConfig
from .history import History, HourRecord
from .inputs import live_inputs_from_snapshot
from .periods import clock_changes
from .synthetic import make_history
from .timeutil import HOUR, UTC, day_bounds, local_date, local_wall, zone

FAULTS_VERSION = "intel-faults-0.2.0"
CUTOVER = datetime(2029, 12, 1, tzinfo=UTC)      # the synthetic I-D8 cut-over of the fixtures (fictional)


@dataclass(frozen=True)
class FaultSpec:
    name: str
    kind: str
    detector: str
    codes: frozenset
    blocks: tuple[str, ...]
    description: str


def _rnd(name: str, seed: int) -> random.Random:
    return random.Random(f"{name}:{seed}")


# ---------------------------------------------------------------------------------------------------------------------
# helpers: copies with one thing changed
# ---------------------------------------------------------------------------------------------------------------------

def with_signals(inp: CycleInputs, values: Mapping[str, object] | None = None, *, drop: tuple[str, ...] = (),
                 observed_at: Mapping[str, datetime] | None = None) -> CycleInputs:
    """A copy whose snapshot has some signal values or observation times replaced (or signals dropped); the LiveInputs is
    rebuilt from the new snapshot when the original carried one, so it stays consistent."""
    snap = inp.snapshot
    if not isinstance(snap, Snapshot):
        return inp
    obs = dict(snap.observations)
    for sig in drop:
        obs.pop(sig, None)
    for sig, v in (values or {}).items():
        if sig in obs:
            obs[sig] = replace(obs[sig], value=v, raw=v)
    for sig, t in (observed_at or {}).items():
        if sig in obs:
            obs[sig] = replace(obs[sig], observed_at=t)
    new = Snapshot(snap.as_of, obs)
    live = live_inputs_from_snapshot(new) if isinstance(inp.live, LiveInputs) else inp.live
    return replace(inp, snapshot=new, live=live)


def with_reading(inp: CycleInputs, key: str, *, drop: bool = False, **changes: object) -> CycleInputs:
    """A copy with one site reading changed (value / unit / observed_at / source) or dropped."""
    out = []
    for r in inp.site_readings:
        if isinstance(r, SiteReading) and r.key == key:
            if drop:
                continue
            r = replace(r, **changes)
        out.append(r)
    return replace(inp, site_readings=tuple(out))


def _reading(inp: CycleInputs, key: str) -> SiteReading | None:
    return next((r for r in inp.site_readings if isinstance(r, SiteReading) and r.key == key), None)


def _hist_copy(inp: CycleInputs) -> History:
    return History(copy.deepcopy(r) for r in inp.history.by_start.values())


def _recent_hours(h: History, now: datetime, lo_h: int, hi_h: int) -> list[int]:
    """Hour starts present in h that began between hi_h and lo_h hours before now (lo_h < hi_h)."""
    end = int(now.timestamp()) - int(now.timestamp()) % HOUR
    return [s for s in sorted(h.by_start) if end - hi_h * HOUR <= s < end - lo_h * HOUR]


# ---------------------------------------------------------------------------------------------------------------------
# live faults (on a complete, fresh CycleInputs)
# ---------------------------------------------------------------------------------------------------------------------

def ct_reversal(inp: CycleInputs, seed: int) -> CycleInputs:
    """A balanced set of powers with the grid CT reporting the opposite sign."""
    r = _rnd("ct_reversal", seed)
    while True:
        house, pv, batt = r.uniform(300, 3000), r.uniform(0, 4000), r.uniform(-2000, 2000)
        grid = house - pv - batt
        if abs(grid) >= 600:
            break
    return with_signals(inp, {"house.power": round(house, 1), "pv.power": round(pv, 1), "battery.power": round(batt, 1),
                              "grid.power": round(-grid, 1)})


def load_false_zero(inp: CycleInputs, seed: int) -> CycleInputs:
    """The native load reads zero while exporting (the HD1 defect): PV covers a real load and exports the rest."""
    r = _rnd("load_false_zero", seed)
    house, pv, batt = r.uniform(200, 2000), r.uniform(2500, 6000), r.uniform(-300, 300)
    grid = house - pv - batt                      # negative: exporting
    return with_signals(inp, {"house.power": 0.0, "pv.power": round(pv, 1), "battery.power": round(batt, 1),
                              "grid.power": round(grid, 1)})


def soc_false_zero(inp: CycleInputs, seed: int) -> CycleInputs:
    """The canonical SOC reads 0 % while the raw SOC reads a real level (the raw reading must be used)."""
    raw = float(_rnd("soc_false_zero", seed).randint(20, 95))
    return with_reading(with_signals(inp, {"battery.soc": 0.0}), "battery.soc_raw_pct", value=raw)


def soc_false_zero_no_raw(inp: CycleInputs, seed: int) -> CycleInputs:
    """The canonical SOC reads 0 % and no raw SOC exists (must BLOCK)."""
    r = _rnd("soc_false_zero_no_raw", seed)
    out = with_signals(inp, {"battery.soc": 0.0})
    if r.random() < 0.5:
        return with_reading(out, "battery.soc_raw_pct", drop=True)
    return with_reading(out, "battery.soc_raw_pct", value=float("nan"))


def soc_disagree(inp: CycleInputs, seed: int) -> CycleInputs:
    """The canonical and the raw SOC disagree by more than one SOC step either way."""
    r = _rnd("soc_disagree", seed)
    canon = float(r.randint(30, 70))
    raw = canon + r.choice((-1, 1)) * r.randint(3, 25)
    return with_reading(with_signals(inp, {"battery.soc": canon}), "battery.soc_raw_pct", value=raw)


def frozen_poll_text(inp: CycleInputs, seed: int) -> CycleInputs:
    """The dongle poll text stopped changing (the dongle hangs) while the values still look recent."""
    age = _rnd("frozen_poll_text", seed).uniform(181, 7200)
    t = inp.now - timedelta(seconds=age)
    return with_reading(inp, "liveness.dongle_poll_changed_at", value=t, observed_at=t)


CONFIG_LIVENESS_KEY = "liveness.config_poll_changed_at"     # site_decisions.CONFIG_LIVENESS_KEY (a contract reading key)


def frozen_config_poll_text(inp: CycleInputs, seed: int) -> CycleInputs:
    """The configuration-poll text stopped changing (read-only configuration polling switched off, or the poll deferred
    by writes or clock corrections) while the telemetry poll text keeps moving: the TOU table still looks current."""
    age = _rnd("frozen_config_poll_text", seed).uniform(301, 7200)
    t = inp.now - timedelta(seconds=age)
    return with_reading(inp, CONFIG_LIVENESS_KEY, value=t, observed_at=t)


def config_liveness_fault(inp: CycleInputs, seed: int) -> CycleInputs:
    """No usable configuration-poll liveness reading: missing (the runtime withheld it, e.g. configuration offline), not
    an aware time, or a change time in the future."""
    r = _rnd("config_liveness_fault", seed)
    kind = r.randrange(3)
    if kind == 0:
        return with_reading(inp, CONFIG_LIVENESS_KEY, drop=True)
    if kind == 1:
        return with_reading(inp, CONFIG_LIVENESS_KEY, value=r.choice(("2030-01-15T20:59:30+00:00", inp.now.replace(tzinfo=None),
                                                                       float(r.randint(0, 10 ** 6)))))
    future = inp.now + timedelta(seconds=r.uniform(1, 3600))
    return with_reading(inp, CONFIG_LIVENESS_KEY, value=future, observed_at=future)


def supervision_poll_frozen(inp: CycleInputs, seed: int) -> CycleInputs:
    """The telemetry poll text stopped beyond the supervision bound but inside the liveness bound, while the supervision
    state and stable readings still look recent: they are aged by the poll text, so supervision is not current."""
    age = _rnd("supervision_poll_frozen", seed).uniform(91, 179)
    t = inp.now - timedelta(seconds=age)
    return with_reading(inp, "liveness.dongle_poll_changed_at", value=t, observed_at=t)


def online_flag_stale(inp: CycleInputs, seed: int) -> CycleInputs:
    """The poll text stopped and the inverter still reads healthy (a flag without a timeout)."""
    return with_signals(frozen_poll_text(inp, seed), {"inverter.healthy": True})


def supervisor_outage(inp: CycleInputs, seed: int) -> CycleInputs:
    """Supervision is not stable: LOST / SUSPECT / STARTUP, not stable, an old heartbeat, or a missing reading."""
    r = _rnd("supervisor_outage", seed)
    kind = r.randrange(4)
    if kind == 0:
        return with_reading(inp, "supervision.state", value=r.choice(("LOST", "SUSPECT", "STARTUP")))
    if kind == 1:
        return with_reading(inp, "supervision.stable", value=False)
    if kind == 2:
        return with_reading(inp, "supervision.heartbeat_age_s", value=round(r.uniform(91, 900), 1))
    return with_reading(inp, r.choice(("supervision.state", "supervision.stable", "supervision.heartbeat_age_s")), drop=True)


def near_protection(inp: CycleInputs, seed: int) -> CycleInputs:
    """SOC within the PROPOSED margin of the protection level (fixtures: protection 12 %)."""
    soc = float(_rnd("near_protection", seed).randint(1, 22))
    return with_reading(with_signals(inp, {"battery.soc": soc}), "battery.soc_raw_pct", value=soc)


def clock_offset(inp: CycleInputs, seed: int) -> CycleInputs:
    """The inverter clock is off by more than the PROPOSED block bound (a TOU-derived window is refused)."""
    r = _rnd("clock_offset", seed)
    return with_reading(inp, "inverter.clock_offset_s", value=round(r.choice((-1, 1)) * r.uniform(121, 3600), 1))


def clock_offset_warn(inp: CycleInputs, seed: int) -> CycleInputs:
    """The inverter clock is off by a little more than the warning bound (a WARN, and a TOU-derived window BLOCKs too)."""
    r = _rnd("clock_offset_warn", seed)
    return with_reading(inp, "inverter.clock_offset_s", value=round(r.choice((-1, 1)) * r.uniform(31, 119), 1))


def shift_snapshot(inp: CycleInputs, back_s: float) -> CycleInputs:
    """A copy whose snapshot was taken `back_s` seconds earlier (as_of and every observation moved back), with the
    LiveInputs rebuilt from it as the bridge would; the readings, the liveness and the caller's assessments (ages relative
    to the snapshot's own time) are unchanged."""
    snap = inp.snapshot
    if not isinstance(snap, Snapshot):
        return inp
    back = timedelta(seconds=float(back_s))
    obs = {k: (replace(o, observed_at=o.observed_at - back) if o.observed_at is not None else o)
           for k, o in snap.observations.items()}
    new = Snapshot(snap.as_of - back, obs)
    live = live_inputs_from_snapshot(new) if isinstance(inp.live, LiveInputs) else inp.live
    return replace(inp, snapshot=new, live=live)


def stale_snapshot(inp: CycleInputs, seed: int) -> CycleInputs:
    """The runtime handed over a snapshot taken minutes to hours before the cycle while the poll text is still changing."""
    return shift_snapshot(inp, _rnd("stale_snapshot", seed).uniform(181, 7200))


def live_disagree(inp: CycleInputs, seed: int) -> CycleInputs:
    """The LiveInputs carry one value (or a time) that differs from the snapshot's: they were not built from it."""
    r = _rnd("live_disagree", seed)
    live = inp.live
    attr = r.choice(("soc_pct", "load_w", "pv_w", "inverter_ok", "ha_reserve_pct", "now"))
    cur = getattr(live, attr)
    if attr == "inverter_ok":
        v = not cur if isinstance(cur, bool) else False
    elif attr == "now":
        v = cur - timedelta(seconds=r.uniform(30, 3600))
    else:
        v = round((cur if isinstance(cur, (int, float)) else 50.0) + r.choice((-1, 1)) * r.uniform(1, 400), 1)
    return replace(inp, live=replace(live, **{attr: v}))


MALFORMED_KEYS = ("limits.max_grid_charge_w", "tariff.export_rates", "stop.dump_soc_pct", "tou.slot_table",
                  "liveness.dongle_poll_changed_at", "pv.forecast_tomorrow_kwh", "tariff.events")


def malformed_choice(seed: int) -> tuple[str, int, random.Random]:
    """(the reading malformed_reading corrupts, the corruption kind 0..8, the generator for the rest) for a seed."""
    r = _rnd("malformed_reading", seed)
    key = r.choice(MALFORMED_KEYS)
    return key, r.randrange(9), r


def malformed_reading(inp: CycleInputs, seed: int) -> CycleInputs:
    """One reading an item requires made unusable: NaN, infinity, None, a wrong unit, a naive or future time, no source,
    a junk entry, or a duplicate."""
    key, kind, r = malformed_choice(seed)
    rd = _reading(inp, key)
    naive = inp.now.replace(tzinfo=None)
    if kind == 0:
        return with_reading(inp, key, value=float("nan"))
    if kind == 1:
        return with_reading(inp, key, value=float("inf"))
    if kind == 2:
        return with_reading(inp, key, value=None)
    if kind == 3:
        return with_reading(inp, key, unit="kW" if SITE_READING_KEYS[key] != "kW" else "W")
    if kind == 4:
        return with_reading(inp, key, observed_at=naive)
    if kind == 5:
        future = inp.now + timedelta(seconds=r.uniform(60, 86400))
        if key == "liveness.dongle_poll_changed_at":
            return with_reading(inp, key, value=future, observed_at=future)
        return with_reading(inp, key, observed_at=future)
    if kind == 6:
        return with_reading(inp, key, source="")
    if kind == 7:
        others = tuple(x for x in inp.site_readings if not (isinstance(x, SiteReading) and x.key == key))
        return replace(inp, site_readings=others + ({"key": key, "value": getattr(rd, "value", None)},))
    return replace(inp, site_readings=tuple(inp.site_readings) + (rd,))


MISSING_KEYS = ("battery.soc", "house.power", "grid.power", "inverter.healthy", "limits.max_grid_charge_w",
                "tariff.export_rates", "stop.dump_soc_pct", "tou.slot_table", "liveness.dongle_poll_changed_at",
                "pv.forecast_tomorrow_kwh", "history.hourly")


def missing_choice(seed: int) -> str:
    """The input missing_input drops for a seed."""
    return _rnd("missing_input", seed).choice(MISSING_KEYS)


def missing_input(inp: CycleInputs, seed: int) -> CycleInputs:
    """One required signal, reading or the history dropped."""
    key = missing_choice(seed)
    if key == "history.hourly":
        return replace(inp, history=None)
    if key in SITE_READING_KEYS:
        return with_reading(inp, key, drop=True)
    return with_signals(inp, drop=(key,))


FUTURE_SIGNALS = ("battery.soc", "house.power", "pv.power", "inverter.healthy")


def future_choice(seed: int) -> tuple[str, random.Random]:
    """(the signal future_timestamp moves into the future, the generator for the rest) for a seed."""
    r = _rnd("future_timestamp", seed)
    return r.choice(FUTURE_SIGNALS), r


def future_timestamp(inp: CycleInputs, seed: int) -> CycleInputs:
    """A required signal observed in the future (clock skew): its age cannot be trusted."""
    sig, r = future_choice(seed)
    return with_signals(inp, observed_at={sig: inp.now + timedelta(seconds=r.uniform(60, 86400))})


# ---------------------------------------------------------------------------------------------------------------------
# history faults (on the History inside a CycleInputs; `now` is the cycle time)
# ---------------------------------------------------------------------------------------------------------------------

def flaps(inp: CycleInputs, seed: int) -> CycleInputs:
    """Two to five separate one-hour dropouts in the last day (each recovered)."""
    r = _rnd("flaps", seed)
    h = _hist_copy(inp)
    cand = _recent_hours(h, inp.now, 2, 23)
    k = r.randint(2, 5)
    picked: list[int] = []
    for s in r.sample(cand, len(cand)):
        if all(abs(s - p) > HOUR for p in picked):
            picked.append(s)
        if len(picked) == k:
            break
    for s in picked:
        del h.by_start[s]
    return replace(inp, history=h)


def gaps(inp: CycleInputs, seed: int) -> CycleInputs:
    """One recovered gap of six to twenty-four hours within the last week."""
    r = _rnd("gaps", seed)
    h = _hist_copy(inp)
    n = r.randint(6, 24)
    end = int(inp.now.timestamp()) - int(inp.now.timestamp()) % HOUR
    first = end - r.randint(n + 30, 160) * HOUR
    for s in range(first, first + n * HOUR, HOUR):
        h.by_start.pop(s, None)
    return replace(inp, history=h)


def stalls(inp: CycleInputs, seed: int) -> CycleInputs:
    """A load counter stuck for two to five hours while the power shows flow, then a catch-up hour."""
    r = _rnd("stalls", seed)
    h = _hist_copy(inp)
    cand = [s for s in _recent_hours(h, inp.now, 8, 24 * 20) if (h.by_start[s].load_w_mean or 0) >= 400]
    k = r.randint(2, 5)
    for _ in range(200):
        s0 = r.choice(cand)
        run = [s0 + i * HOUR for i in range(k + 1)]
        if all(s in h.by_start and "load" in h.by_start[s].e for s in run):
            break
    total = sum(h.by_start[s].e["load"] for s in run)
    for s in run[:-1]:
        h.by_start[s].e["load"] = 0.0
    h.by_start[run[-1]].e["load"] = total
    return replace(inp, history=h)


def catchup(inp: CycleInputs, seed: int) -> CycleInputs:
    """One counter hour far above its power integral (a catch-up jump without a visible stall)."""
    r = _rnd("catchup", seed)
    h = _hist_copy(inp)
    s = r.choice([s for s in _recent_hours(h, inp.now, 4, 24 * 20) if "load" in h.by_start[s].e])
    rec = h.by_start[s]
    rec.e["load"] = (rec.load_w_mean or 0.0) / 1000.0 + r.uniform(2.5, 8.0)
    return replace(inp, history=h)


def no_pv(inp: CycleInputs, seed: int) -> CycleInputs:
    """The PV produced nothing on the last two to four complete local days while a forecast said it would."""
    r = _rnd("no_pv", seed)
    h = _hist_copy(inp)
    tz = zone(getattr(inp.site_facts, "tz", "Europe/London"))
    days = r.randint(2, 4)
    today = local_date(inp.now, tz)
    fc: dict[date, float] = {}
    for k in range(1, days + 1):
        d = today - timedelta(days=k)
        t0, t1 = day_bounds(d, tz)
        for s in range(int(t0.timestamp()), int(t1.timestamp()), HOUR):
            rec = h.by_start.get(s)
            if rec is not None:
                rec.e["pv"] = 0.0
                rec.pv_w_mean = 0.0
        fc[d] = round(r.uniform(1.0, 8.0), 2)
    pvh = {k: dict(v) for k, v in (inp.pv_forecast_history or {}).items()} if isinstance(inp.pv_forecast_history, Mapping) else {}
    pvh.setdefault("synthetic_forecast", {}).update(fc)
    return replace(inp, history=h, pv_forecast_history=pvh)


def add_balanced_counters(h: History) -> History:
    """A copy with import / export counters that balance load and PV exactly (no battery flow)."""
    out = History(copy.deepcopy(r) for r in h.by_start.values())
    for rec in out.by_start.values():
        load, pv = rec.e.get("load"), rec.e.get("pv")
        if load is None or pv is None:
            continue
        rec.e["imp"] = max(load - pv, 0.0)
        rec.e["exp"] = max(pv - load, 0.0)
        rec.e["chg"] = 0.0
        rec.e["dis"] = 0.0
    return out


def ct_reversal_history(inp: CycleInputs, seed: int) -> CycleInputs:
    """Hourly counters recorded through a reversed grid CT: import and export swapped while the load is measured."""
    h = add_balanced_counters(inp.history)
    r = _rnd("ct_reversal_history", seed)
    start = r.choice(sorted(h.by_start)[:24 * 7])
    for s, rec in h.by_start.items():
        if s >= start and "imp" in rec.e:
            rec.e["imp"], rec.e["exp"] = rec.e["exp"], rec.e["imp"]
    return replace(inp, history=h)


def with_reversed_ct(inp: CycleInputs, last_hours: int) -> CycleInputs:
    """Balanced counters, then import and export swapped for the hours that began within `last_hours` before now (a CT
    reversed recently, e.g. after an electrician's visit)."""
    h = add_balanced_counters(inp.history)
    end = int(inp.now.timestamp()) - int(inp.now.timestamp()) % HOUR
    for s, rec in h.by_start.items():
        if s >= end - int(last_hours) * HOUR and "imp" in rec.e:
            rec.e["imp"], rec.e["exp"] = rec.e["exp"], rec.e["imp"]
    return replace(inp, history=h)


def ct_reversal_recent(inp: CycleInputs, seed: int) -> CycleInputs:
    """A CT reversed one to three days ago: far too recent for the share over the whole history or the lookback."""
    return with_reversed_ct(inp, _rnd("ct_reversal_recent", seed).randint(24, 72))


def stale_history_junk(inp: CycleInputs, seed: int) -> CycleInputs:
    """The history stopped seven to forty-eight hours ago, and an entry that is not a usable hour record (junk, None, a
    record filed under another hour, an empty record, malformed flags) sits under the newest key: it must not date it."""
    r = _rnd("stale_history_junk", seed)
    old = inp.history.truncated(inp.now - timedelta(hours=r.uniform(7, 48)))
    h = History()
    h.by_start = dict(old.by_start)
    end = int(inp.now.timestamp()) - int(inp.now.timestamp()) % HOUR
    s = r.choice((end - HOUR, end - HOUR * r.randint(2, 6)))
    kind = r.randrange(5)
    h.by_start[s] = ("junk" if kind == 0 else None if kind == 1 else HourRecord(start=s - HOUR * r.randint(1, 30), e={"load": 1.0})
                     if kind == 2 else HourRecord(start=s, e={}) if kind == 3 else HourRecord(start=s, e={"load": 1.0}, flags=None))
    return replace(inp, history=h)


def soc_zero_history(inp: CycleInputs, seed: int) -> CycleInputs:
    """Hours whose mean SOC reads 0 % while the battery was discharging."""
    r = _rnd("soc_zero_history", seed)
    h = _hist_copy(inp)
    for s in r.sample(_recent_hours(h, inp.now, 2, 24 * 10), r.randint(1, 6)):
        h.by_start[s].soc_mean = 0.0
        h.by_start[s].batt_w_mean = round(r.uniform(300, 3000), 1)
    return replace(inp, history=h)


def load_false_zero_after_cutover(inp: CycleInputs, seed: int) -> CycleInputs:
    """Load hours reading zero while exporting AFTER the recorded cut-over (the cut-over instant cannot be right)."""
    r = _rnd("load_false_zero_after_cutover", seed)
    h = add_balanced_counters(inp.history)
    cut = int(CUTOVER.timestamp())
    for s in r.sample([s for s in sorted(h.by_start) if s >= cut], r.randint(3, 8)):
        rec = h.by_start[s]
        rec.e["load"] = 0.0
        rec.load_w_mean = 0.0                     # the native load power reads zero as well (HD1)
        rec.e["exp"] = round(r.uniform(0.3, 3.0), 3)
    return replace(inp, history=h)


def dst_now(seed: int, tz: str = "Europe/London") -> datetime:
    """A cycle time (21:00 local) one to twenty-seven nights after one of the 2030 clock changes."""
    r = _rnd("dst_now", seed)
    z = zone(tz)
    changes = clock_changes(datetime(2030, 1, 1, tzinfo=UTC), datetime(2031, 1, 1, tzinfo=UTC), tz)
    ch = r.choice(changes)
    return local_wall(ch.local_day + timedelta(days=r.randint(1, 27)), 21 * 60, z)


def synthetic_house(seed: int, now: datetime, days: int = 61, cfg: SiteConfig | None = None) -> History:
    """A clean synthetic household history (synthetic.make_history) ending with the hour before `now`."""
    cfg = cfg or SiteConfig(pv_array_kwp=6.0)
    start = (now - timedelta(days=days - 1)).date()
    return make_history(start, days, cfg, seed=seed).truncated(now)


def history_from(inp: CycleInputs, h: History) -> CycleInputs:
    return replace(inp, history=h)


# ---------------------------------------------------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------------------------------------------------

_EXPORT = ("export_event", "dump_to_grid")
_SOC = ("charge_target", "export_event", "dump_to_grid", "v1_summary", "predicted_morning_soc")
_DONGLE = _SOC
_HISTORY = ("overnight_demand", "charge_target", "export_event", "dump_to_grid", "v1_summary", "predicted_morning_soc",
            "predicted_day_load", "pv_tomorrow")
_WINDOW = ("charge_target", "export_event", "dump_to_grid", "v1_summary", "predicted_morning_soc")


def _spec(name, kind, detector, codes, blocks, description) -> FaultSpec:
    return FaultSpec(name, kind, detector, frozenset(codes), tuple(blocks), description)


FAULTS: Mapping[str, FaultSpec] = {s.name: s for s in (
    _spec("ct_reversal", "cycle", "assess", {"CT_SIGN_REVERSED"}, _EXPORT, "grid CT sign reversed (power balance)"),
    _spec("load_false_zero", "cycle", "assess", {"LOAD_FALSE_ZERO"}, _EXPORT, "native load reads zero while exporting"),
    _spec("soc_false_zero", "cycle", "assess", {"SOC_FALSE_ZERO_RAW_USED"}, (), "canonical SOC zero, raw SOC real"),
    _spec("soc_false_zero_no_raw", "cycle", "assess", {"SOC_FALSE_ZERO_UNRESOLVED"}, _SOC, "canonical SOC zero, no raw"),
    _spec("soc_disagree", "cycle", "assess", {"SOC_SOURCES_DISAGREE"}, _SOC, "canonical and raw SOC disagree"),
    _spec("frozen_poll_text", "cycle", "assess", {"LIVENESS_STALE"}, _DONGLE, "the poll text stopped changing"),
    _spec("frozen_config_poll_text", "cycle", "assess", {"CONFIG_LIVENESS_STALE"}, _WINDOW,
          "the configuration-poll text stopped changing while the telemetry poll text moves"),
    _spec("config_liveness_fault", "cycle", "assess", {"CONFIG_LIVENESS_MISSING", "CONFIG_LIVENESS_IN_FUTURE"}, _WINDOW,
          "the configuration-poll liveness reading missing, not an aware time or in the future"),
    _spec("supervision_poll_frozen", "cycle", "assess", {"SUPERVISION_NOT_STABLE"}, _EXPORT,
          "the poll text frozen beyond the supervision bound while the supervision readings look recent"),
    _spec("online_flag_stale", "cycle", "assess", {"ONLINE_FLAG_UNCONFIRMED"}, _EXPORT, "healthy flag with stale liveness"),
    _spec("supervisor_outage", "cycle", "assess", {"SUPERVISION_NOT_STABLE"}, _EXPORT, "supervision not stable"),
    _spec("near_protection", "cycle", "assess", {"SOC_NEAR_PROTECTION"}, _EXPORT, "SOC near the protection level"),
    _spec("clock_offset", "cycle", "assess", {"CHARGE_WINDOW_CLOCK_OFFSET"}, _WINDOW, "inverter clock far off"),
    _spec("clock_offset_warn", "cycle", "assess", {"CHARGE_WINDOW_CLOCK_OFFSET"}, _WINDOW,
          "inverter clock a little beyond the warning bound (WARN, and the TOU-derived window BLOCKs)"),
    _spec("stale_snapshot", "cycle", "assess", {"SNAPSHOT_STALE"}, _DONGLE, "an old snapshot with fresh liveness"),
    _spec("live_disagree", "cycle", "assess", {"LIVE_INPUTS_DISAGREE"}, _DONGLE, "LiveInputs not built from the snapshot"),
    _spec("malformed_reading", "cycle", "assess", {"INPUT_NOT_FRESH", "SITE_READING_DUPLICATE", "CHARGE_WINDOW_UNKNOWN",
                                                   "LIVENESS_MISSING", "LIVENESS_IN_FUTURE", "TARIFF_EVENTS_NOT_FRESH"},
          (), "a required reading malformed, non-finite, mistimed or duplicated"),
    _spec("missing_input", "cycle", "assess", {"INPUT_NOT_FRESH", "CHARGE_WINDOW_UNKNOWN", "LIVENESS_MISSING",
                                               "CALLER_FRESHNESS_DISAGREES"}, (), "a required input missing"),
    _spec("future_timestamp", "cycle", "assess", {"INPUT_NOT_FRESH", "CALLER_FRESHNESS_DISAGREES"}, (),
          "a required signal observed in the future"),
    _spec("flaps", "history", "assess", {"TELEMETRY_FLAPPING"}, _DONGLE, "repeated recovered dropouts in the last day"),
    _spec("gaps", "history", "assess", {"HISTORY_GAP"}, (), "a long recovered gap in the last week"),
    _spec("stalls", "history", "prepare", {"HISTORY_COUNTER_STALL"}, (), "a stuck counter then a catch-up"),
    _spec("catchup", "history", "prepare", {"HISTORY_COUNTER_CATCHUP"}, (), "a counter catch-up jump"),
    _spec("no_pv", "history", "assess", {"PV_NO_OUTPUT_VS_FORECAST"}, ("pv_tomorrow",), "prolonged zero PV against a forecast"),
    _spec("ct_reversal_history", "history", "both", {"HISTORY_CT_REVERSED"}, _HISTORY, "import and export swapped"),
    _spec("ct_reversal_recent", "history", "both", {"HISTORY_CT_REVERSED"}, _HISTORY,
          "import and export swapped for the last one to three days"),
    _spec("stale_history_junk", "history", "assess", {"INPUT_NOT_FRESH"}, _HISTORY,
          "a stale history with an unusable entry under the newest key"),
    _spec("soc_zero_history", "history", "prepare", {"HISTORY_SOC_SUSPECT"}, (), "zero SOC while discharging"),
    _spec("load_false_zero_after_cutover", "history", "prepare", {"HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER"}, (),
          "load zero while exporting after the cut-over"),
)}

INJECTORS: Mapping[str, Callable[[CycleInputs, int], CycleInputs]] = {
    "ct_reversal": ct_reversal, "load_false_zero": load_false_zero, "soc_false_zero": soc_false_zero,
    "soc_false_zero_no_raw": soc_false_zero_no_raw, "soc_disagree": soc_disagree, "frozen_poll_text": frozen_poll_text,
    "frozen_config_poll_text": frozen_config_poll_text, "config_liveness_fault": config_liveness_fault,
    "supervision_poll_frozen": supervision_poll_frozen, "online_flag_stale": online_flag_stale,
    "supervisor_outage": supervisor_outage, "near_protection": near_protection,
    "clock_offset": clock_offset, "clock_offset_warn": clock_offset_warn, "stale_snapshot": stale_snapshot,
    "live_disagree": live_disagree, "malformed_reading": malformed_reading,
    "missing_input": missing_input, "future_timestamp": future_timestamp, "flaps": flaps, "gaps": gaps, "stalls": stalls,
    "catchup": catchup, "no_pv": no_pv, "ct_reversal_history": ct_reversal_history, "ct_reversal_recent": ct_reversal_recent,
    "stale_history_junk": stale_history_junk, "soc_zero_history": soc_zero_history,
    "load_false_zero_after_cutover": load_false_zero_after_cutover,
}


def inject(name: str, inp: CycleInputs, seed: int) -> CycleInputs:
    """The CycleInputs with fault `name` injected (deterministic for a given seed). The input is not modified."""
    if name not in INJECTORS:
        raise ValueError(f"unknown fault {name!r}")
    return INJECTORS[name](inp, int(seed))
