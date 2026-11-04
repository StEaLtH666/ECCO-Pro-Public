#!/usr/bin/env python3
"""Intelligence engine: the exact, bounded memo of usage.build_profile (INTELLIGENCE_FOUNDATION_CONTRACT.md 13.4, A50).

  [1] exact: on generated and hand-made day tables (gaps, ties, outliers, zeros) every call, cold or warm, equals
      build_profile_uncached bit for bit, and each part of the key matters: alpha, k, mode, a slot value, which slots
      are missing, the sign of a zero, the order of the days, SLOT_SIGMA_FLOOR_KWH, PROFILE_REFERENCE_WINDOW and
      stats.MAD_TO_SIGMA; a revised past day (a new table), a replaced row (the same table) and a day that is no longer
      complete are misses
  [2] inputs with no exact image (a NaN or infinite value or parameter, an int value, a bool parameter, a list row, a
      short row) bypass the memo, store nothing and still give what a fresh build gives (or raise as it raises)
  [3] copies: every call returns a new SlotProfile with its own lists and the memo keeps tuples, so a caller that
      changes a result changes nothing the memo or a later caller sees; the audit: over two whole recorded cycles no
      caller changes a profile it was given
  [4] bounded: the memo uses PROFILE_MEMO_MAX_ENTRIES; it never holds more, evicts the least recently used first, keeps
      nothing at a bound of 0; the bound is at least three times one cycle's working set, and a second cycle on the
      same history is all hits, its envelope byte-identical to a cold run
  [5] threads: concurrent calls with a small bound (evictions racing) never raise, stay exact and keep the bound; the
      two steps a lock-free memo can lose to an overlapping cycle (its entry evicted between the read and the move to
      the recent end; the memo emptied between the size check and the eviction), made deterministic, never raise
  [6] differential, memo on against memo off over simulated days on a 120-day history window that slides each hour: a
      winter day through local midnight and the early-morning cycles in which the window's oldest partial day changes,
      and the 2030-10-27 clock change (a 25 h day) from the evening before to the next local midnight; recorded
      (SYNTHETIC_TEST, accepted explicitly) and all-OPEN decisions; the next day's rates unpublished before 16:00
      local and published after: every envelope and its entity payloads byte-identical, the memo warm (hits) and
      missing exactly where the content changes
  [7] the docs say so: contract 13.4 names the memo, its bound with the code's value and this suite; the usage and
      shadow_cycle module docstrings and the run_cycle docstring say the engine keeps this one memo and that it never
      changes a result
All values are synthetic (2030, intelligence.synthetic histories); none is site data.
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _plan_helpers as ph  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import stats  # noqa: E402
from intelligence import usage  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History  # noqa: E402
from intelligence.shadow_cycle import REFRESH_MARGIN_S, run_cycle  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import HOUR, ts, zone  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
TZ = cf.TZ
Z = zone(TZ)
CFG = SiteConfig(pv_array_kwp=cf.FACTS.pv_array_kwp)
WINDOW_DAYS = 120          # the runtime's history window (whole hours back from the start of the current hour)
EXPERTS = (("fast", CFG.fast_alpha, CFG.lookback_days_fast, CFG.winsor_k, "ewma"),
           ("slow", CFG.slow_alpha, CFG.lookback_days_slow, CFG.winsor_k, "ewma"),
           ("median14", 0.0, 14, CFG.winsor_k, "median"),
           ("median30", 0.0, CFG.baseline_days, CFG.winsor_k, "median"))


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _fbits(x) -> object:
    return None if x is None else (type(x).__name__, x.hex() if isinstance(x, float) else repr(x))


def bits(p) -> tuple:
    """A SlotProfile bit for bit: the types, every value's exact bits (the sign of a zero included), n_days, clipped."""
    return (type(p).__name__, type(p.values).__name__, type(p.sigma).__name__, tuple(_fbits(x) for x in p.values),
            tuple(_fbits(x) for x in p.sigma), p.n_days, p.clipped)


def info() -> dict:
    return usage.profile_memo_info()


def bp(table, upto, alpha, lookback, k, mode="ewma"):
    return usage.build_profile(table, upto, alpha, lookback, k, mode)


def fresh(table, upto, alpha, lookback, k, mode="ewma"):
    return usage.build_profile_uncached(table, upto, alpha, lookback, k, mode)


def made_table(rows: dict) -> usage.DayTable:
    """A DayTable with the given rows (date -> tuple of 24)."""
    t = usage.DayTable(History(), "load", TZ)
    t.days = dict(rows)
    return t


def row(rnd: random.Random, base: float = 1.0, none_at: tuple = ()) -> tuple:
    return tuple(None if s in none_at else round(base * (0.3 + rnd.random()), 2) for s in range(24))


class patched:
    """Set a module attribute for the duration of a with-block; always restored."""

    def __init__(self, obj, name: str, value) -> None:
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)
        return False


D0 = date(2030, 3, 1)

# ---------------------------------------------------------------------------------------------------------------------
print("== [1] exact: every call equals a fresh build, and each part of the key matters")
H_GAPS = make_history(date(2029, 11, 1), 130, CFG, seed=21,
                      drop_hours={ts(datetime(2030, 1, 5, h, tzinfo=UTC)) for h in range(3, 9)}
                      | {ts(datetime(2030, 2, 2, h, tzinfo=UTC)) for h in (12, 13)},
                      load_overrides={ts(datetime(2030, 1, 20, 18, tzinfo=UTC)): 9.5,
                                      ts(datetime(2030, 1, 21, 3, tzinfo=UTC)): 0.0,
                                      ts(datetime(2030, 2, 10, 3, tzinfo=UTC)): 0.0})
H_FLAT = make_history(date(2029, 11, 1), 100, CFG, seed=3, hour_noise=0.0, day_sigma=0.0)    # ties everywhere
TABLES = {"gaps and outliers": usage.DayTable(H_GAPS, "load", TZ), "flat (ties)": usage.DayTable(H_FLAT, "load", TZ)}
sweep_bad, sweep_n = [], 0
usage.clear_profile_memo()
for tname, tab in TABLES.items():
    days = sorted(tab.days)
    for up in days[5::9] + days[-2:]:
        for name, a, lb, k, mode in EXPERTS:
            want = bits(fresh(tab, up, a, lb, k, mode))
            got = [bits(bp(tab, up, a, lb, k, mode)) for _ in range(2)]
            sweep_n += 1
            if got != [want, want]:
                sweep_bad.append((tname, up.isoformat(), name))
i1 = info()
check(f"{sweep_n} (table, day, expert) cases: the cold call and the warm call both equal build_profile_uncached "
      "bit for bit", not sweep_bad and sweep_n > 50, str(sweep_bad[:3]))
check("... and the warm calls were hits: one miss and one hit per distinct case, nothing bypassed",
      i1["hits"] >= sweep_n - 4 and i1["misses"] <= sweep_n and i1["bypassed"] == 0, str(i1))

rnd = random.Random(2030)
ROWS = {D0 + timedelta(days=i): row(rnd, none_at=(i % 3,)) for i in range(40)}
OUTLIERS = dict(ROWS)
for i in (30, 33, 36):
    OUTLIERS[D0 + timedelta(days=i)] = tuple(None if x is None else x * 12.0 for x in ROWS[D0 + timedelta(days=i)])
T_OUT = made_table(OUTLIERS)
UP = D0 + timedelta(days=40)


def pair(label: str, first: tuple, second: tuple, patch=None) -> None:
    """Build `first` then `second` (each (table, upto, alpha, lookback, k, mode)) with the memo on: the second must
    equal a fresh build of itself, and must differ from the first (so a key that ignored the difference would return a
    wrong profile)."""
    usage.clear_profile_memo()
    p1 = bits(bp(*first))
    if patch is not None:
        with patched(*patch):
            p2, w2 = bits(bp(*second)), bits(fresh(*second))
    else:
        p2, w2 = bits(bp(*second)), bits(fresh(*second))
    check(f"{label}: equals a fresh build and differs from the first", p2 == w2 and p2 != p1,
          f"same_as_fresh={p2 == w2} differs={p2 != p1}")


pair("alpha 0.30 then 0.08 (same days)", (T_OUT, UP, 0.30, 40, 5.0), (T_OUT, UP, 0.08, 40, 5.0))
pair("k 5.0 then 1.5 (the outlier days clip differently)", (T_OUT, UP, 0.30, 40, 5.0), (T_OUT, UP, 0.30, 40, 1.5))
pair("mode ewma then median (same alpha, k, days)", (T_OUT, UP, 0.30, 40, 5.0, "ewma"),
     (T_OUT, UP, 0.30, 40, 5.0, "median"))
_rev = dict(OUTLIERS)
_d = D0 + timedelta(days=20)
_rev[_d] = tuple(x + 0.25 if x is not None and s == 7 else x for s, x in enumerate(OUTLIERS[_d]))
pair("a revised past day: one slot of one day changed (a new table)", (T_OUT, UP, 0.30, 40, 5.0),
     (made_table(_rev), UP, 0.30, 40, 5.0))
_miss_a, _miss_b = dict(OUTLIERS), dict(OUTLIERS)
_d = D0 + timedelta(days=35)
_miss_a[_d] = tuple(0.0 if s == 9 else x for s, x in enumerate(OUTLIERS[_d]))
_miss_b[_d] = tuple(None if s == 9 else x for s, x in enumerate(OUTLIERS[_d]))
pair("a slot 0.0 then the same slot missing (the doubles alike, only the missing-slot mask differs)",
     (made_table(_miss_a), UP, 0.0, 14, 5.0, "median"), (made_table(_miss_b), UP, 0.0, 14, 5.0, "median"))
ONE = D0 + timedelta(days=60)
_pos = {ONE: tuple(0.0 if s == 3 else 0.5 for s in range(24))}
_neg = {ONE: tuple(-0.0 if s == 3 else 0.5 for s in range(24))}
pair("a zero then a negative zero in one slot (equal as floats, different bits)",
     (made_table(_pos), ONE + timedelta(days=1), 0.0, 1, 5.0, "median"),
     (made_table(_neg), ONE + timedelta(days=1), 0.0, 1, 5.0, "median"))
_swap = dict(OUTLIERS)
_a, _b = D0 + timedelta(days=30), D0 + timedelta(days=38)
_swap[_a], _swap[_b] = OUTLIERS[_b], OUTLIERS[_a]
pair("the same rows in another day order (the EWMA reads them oldest first)", (T_OUT, UP, 0.30, 40, 5.0),
     (made_table(_swap), UP, 0.30, 40, 5.0))
pair("SLOT_SIGMA_FLOOR_KWH raised (read at call time)", (T_OUT, UP, 0.30, 40, 5.0), (T_OUT, UP, 0.30, 40, 5.0),
     patch=(usage, "SLOT_SIGMA_FLOOR_KWH", 0.9))
pair("PROFILE_REFERENCE_WINDOW shortened (read at call time)", (T_OUT, UP, 0.30, 40, 5.0), (T_OUT, UP, 0.30, 40, 5.0),
     patch=(usage, "PROFILE_REFERENCE_WINDOW", 3))
pair("stats.MAD_TO_SIGMA changed (read at call time)", (T_OUT, UP, 0.30, 40, 5.0), (T_OUT, UP, 0.30, 40, 5.0),
     patch=(stats, "MAD_TO_SIGMA", 0.5))
usage.clear_profile_memo()
_t = made_table(OUTLIERS)
_before = bits(bp(_t, UP, 0.30, 40, 5.0))
_t.days[D0 + timedelta(days=35)] = tuple(None if x is None else x + 1.0 for x in OUTLIERS[D0 + timedelta(days=35)])
_after, _want = bits(bp(_t, UP, 0.30, 40, 5.0)), bits(fresh(_t, UP, 0.30, 40, 5.0))
check("a row replaced in the same table after a call: the next call equals a fresh build of the new row (the per-table "
      "row image is checked against the row object)", _after == _want and _after != _before)
usage.clear_profile_memo()
_t20 = dict(OUTLIERS)
_d20 = D0 + timedelta(days=39)
_t20[_d20] = tuple(None if s < 4 else x for s, x in enumerate(OUTLIERS[_d20]))     # 20 valid slots: a complete day
_t19 = dict(_t20)
_t19[_d20] = tuple(None if s < 5 else x for s, x in enumerate(OUTLIERS[_d20]))     # 19: not complete
_p20 = bits(bp(made_table(_t20), UP, 0.30, 40, 5.0))
_p19, _w19 = bits(bp(made_table(_t19), UP, 0.30, 40, 5.0)), bits(fresh(made_table(_t19), UP, 0.30, 40, 5.0))
check("a day that falls from 20 to 19 valid slots leaves the profile (complete_days): a miss, equal to a fresh build "
      "with one day fewer", _p19 == _w19 and _p19 != _p20 and _p19[5] == _p20[5] - 1, f"{_p19[5]} {_p20[5]}")

# ---------------------------------------------------------------------------------------------------------------------
print("== [2] inputs with no exact image bypass the memo")


def bypass_case(label: str, table, args: tuple) -> None:
    usage.clear_profile_memo()
    try:
        got = ("ok", bits(bp(table, *args)))
    except Exception as exc:  # noqa: BLE001 - the fresh build must raise the same
        got = ("raise", type(exc).__name__)
    try:
        want = ("ok", bits(fresh(table, *args)))
    except Exception as exc:  # noqa: BLE001
        want = ("raise", type(exc).__name__)
    i = info()
    check(f"{label}: bypassed, nothing stored, the same result as a fresh build ({want[0]})",
          got == want and i["bypassed"] == 1 and i["entries"] == 0 and i["hits"] == 0 and i["misses"] == 0,
          f"{got[0]} {want[0]} {i}")


D10 = D0 + timedelta(days=10)


def with_row(new_row) -> usage.DayTable:
    rows = dict(ROWS)
    rows[D10] = new_row
    return made_table(rows)


bypass_case("a NaN slot value", with_row(tuple(float("nan") if s == 5 else x for s, x in enumerate(ROWS[D10]))),
            (UP, 0.30, 40, 5.0))
bypass_case("an infinite slot value", with_row(tuple(float("inf") if s == 5 else x for s, x in enumerate(ROWS[D10]))),
            (UP, 0.30, 40, 5.0))
bypass_case("an int slot value", with_row(tuple(1 if s == 5 else x for s, x in enumerate(ROWS[D10]))),
            (UP, 0.30, 40, 5.0))
bypass_case("a list row (mutable, so never imaged)", with_row(list(ROWS[D10])), (UP, 0.30, 40, 5.0))
bypass_case("a row of 23 values", with_row(ROWS[D10][:23]), (UP, 0.30, 40, 5.0))
bypass_case("a NaN alpha", made_table(ROWS), (UP, float("nan"), 40, 5.0))
bypass_case("an infinite k", made_table(ROWS), (UP, 0.30, 40, float("inf")))
bypass_case("a bool k", made_table(ROWS), (UP, 0.30, 40, True))
usage.clear_profile_memo()
_ti = made_table(ROWS)
_pi = [bits(bp(_ti, UP, 0.30, 40, 5)), bits(bp(_ti, UP, 0.30, 40, 5.0))]
check("an int k and a float k of the same value are two keys (exact by type), each equal to its fresh build",
      _pi == [bits(fresh(_ti, UP, 0.30, 40, 5)), bits(fresh(_ti, UP, 0.30, 40, 5.0))] and info()["misses"] == 2,
      str(info()))

# ---------------------------------------------------------------------------------------------------------------------
print("== [3] copies: no caller can change what the memo holds")
usage.clear_profile_memo()
_tc = made_table(OUTLIERS)
want = bits(fresh(_tc, UP, 0.30, 40, 5.0))
p_miss = bp(_tc, UP, 0.30, 40, 5.0)
p_miss.values[0] = 99.0
p_miss.values.append(1.0)
p_miss.sigma.clear()
p_miss.n_days = -1
p_hit = bp(_tc, UP, 0.30, 40, 5.0)
check("a result of a miss changed in every field: the next call (a hit) still equals a fresh build",
      bits(p_hit) == want and info()["hits"] == 1, str(info()))
p_hit.values[3] = None
p_hit.sigma[3] = -5.0
p_again = bp(_tc, UP, 0.30, 40, 5.0)
check("a result of a hit changed: the next call still equals a fresh build, and it is a new object with new lists",
      bits(p_again) == want and p_again is not p_hit and p_again.values is not p_hit.values
      and p_again.sigma is not p_hit.sigma)
_entries = list(usage._PROFILE_MEMO._entries.values())  # noqa: SLF001 - the test reads the memo's own storage
check("the memo stores tuples only (values and sigma), never a list it handed out",
      bool(_entries) and all(type(v[0]) is tuple and type(v[1]) is tuple for v in _entries))

FULL_A = make_history(date(2030, 7, 10), 130, CFG, seed=7)


def window(full: History, now: datetime) -> History:
    """The history the runtime would read at `now`: whole hours in [start of hour - WINDOW_DAYS, start of hour)."""
    end = ts(now) - ts(now) % HOUR
    start = end - WINDOW_DAYS * 86400
    return History(r for s, r in full.by_start.items() if start <= s and s + HOUR <= end)


def cycle_in(now: datetime, hist: History, recorded: bool = True) -> ac.CycleInputs:
    """The shared fixture at `now` on `hist`, with the day's import and export rates: the current day only before 16:00
    local, the current and the next day from 16:00 (the next day's rates published)."""
    x = replace(cf.cycle_inputs(synthetic_recorded=recorded, now=now, missing_key="history"), history=hist)
    loc = now.astimezone(Z)
    n = 2 if loc.hour >= 16 else 1
    x = ph.with_reading(x, "tariff.import_rates", ph.go_like_rates(loc.date(), n))
    return ph.with_reading(x, "tariff.export_rates", ph.flat_export(loc.date(), n))


AUDIT_NOW = datetime(2030, 11, 15, 21, 0, tzinfo=UTC)
seen: list = []
_orig_bp = usage.build_profile


def recording(*a, **kw):
    p = _orig_bp(*a, **kw)
    seen.append((p, bits(p)))
    return p


usage.clear_profile_memo()
usage.build_profile = recording
try:
    audit_env = run_cycle(cycle_in(AUDIT_NOW, window(FULL_A, AUDIT_NOW)))
    _n_audit = len(seen)
    audit_env2 = run_cycle(cycle_in(AUDIT_NOW + timedelta(minutes=1), window(FULL_A, AUDIT_NOW)))
finally:
    usage.build_profile = _orig_bp
_changed = [i for i, (p, b) in enumerate(seen) if bits(p) != b]
check(f"the audit: over two whole recorded cycles ({len(seen)} profiles handed to the usage model, the long baseline, "
      "the anomaly, next-hour, planner and plan readers) no caller changed a profile it was given",
      not _changed and _n_audit > 200 and len(seen) == 2 * _n_audit and audit_env.status == audit_env2.status == "OK",
      f"{_changed[:5]} n={_n_audit}/{len(seen)} {audit_env.status} {audit_env2.status}")

# ---------------------------------------------------------------------------------------------------------------------
print("== [4] bounded, least recently used first")
check("the memo's bound is PROFILE_MEMO_MAX_ENTRIES",
      usage._PROFILE_MEMO.max_entries == usage.PROFILE_MEMO_MAX_ENTRIES > 0)  # noqa: SLF001
usage.clear_profile_memo()
_c1 = run_cycle(cycle_in(AUDIT_NOW, window(FULL_A, AUDIT_NOW)))
w1 = info()
_c2 = run_cycle(cycle_in(AUDIT_NOW + timedelta(minutes=1), window(FULL_A, AUDIT_NOW)))
w2 = info()
check(f"one recorded cycle on a {WINDOW_DAYS}-day history reads {w1['misses']} distinct profiles; the bound "
      f"({usage.PROFILE_MEMO_MAX_ENTRIES}) is at least three times that",
      w1["misses"] == w1["entries"] > 200 and 3 * w1["entries"] <= usage.PROFILE_MEMO_MAX_ENTRIES, str(w1))
check("... and the next cycle on the same history (a refresh a minute later) is all hits, no miss",
      w2["misses"] == w1["misses"] and w2["hits"] - w1["hits"] >= w1["entries"] and w2["entries"] == w1["entries"],
      f"{w1} {w2}")
_cold = json.dumps(_c2.to_dict(), allow_nan=False)
usage.clear_profile_memo()
check("... whose envelope is byte-identical to the same cycle run cold",
      json.dumps(run_cycle(cycle_in(AUDIT_NOW + timedelta(minutes=1), window(FULL_A, AUDIT_NOW))).to_dict(),
                 allow_nan=False) == _cold)

usage.clear_profile_memo()
_tb = made_table({ONE: tuple(0.5 + 0.01 * s for s in range(24))})
N_FILL = usage.PROFILE_MEMO_MAX_ENTRIES + 76
alphas = [0.01 + 0.0005 * i for i in range(N_FILL)]
for a in alphas:
    bp(_tb, ONE + timedelta(days=1), a, 1, 5.0)
fill = info()
_last_hit = (bits(bp(_tb, ONE + timedelta(days=1), alphas[-1], 1, 5.0)), info()["hits"])
_first = (bits(bp(_tb, ONE + timedelta(days=1), alphas[0], 1, 5.0)), info())
check(f"{N_FILL} distinct keys: the memo holds exactly {usage.PROFILE_MEMO_MAX_ENTRIES}; the newest is a hit, the "
      "oldest was evicted (a miss, still exact)",
      fill["entries"] == usage.PROFILE_MEMO_MAX_ENTRIES and fill["misses"] == N_FILL and _last_hit[1] == 1
      and _first[1]["misses"] == N_FILL + 1 and _first[1]["entries"] == usage.PROFILE_MEMO_MAX_ENTRIES
      and _first[0] == bits(fresh(_tb, ONE + timedelta(days=1), alphas[0], 1, 5.0)), f"{fill} {_first[1]}")
_saved_max = usage._PROFILE_MEMO.max_entries  # noqa: SLF001
try:
    usage.clear_profile_memo()
    usage._PROFILE_MEMO.max_entries = 4  # noqa: SLF001
    for a in (0.1, 0.2, 0.3, 0.4):
        bp(_tb, ONE + timedelta(days=1), a, 1, 5.0)
    bp(_tb, ONE + timedelta(days=1), 0.1, 1, 5.0)                    # touch the oldest
    bp(_tb, ONE + timedelta(days=1), 0.5, 1, 5.0)                    # evicts the least recently used: 0.2
    m0 = info()["misses"]
    bp(_tb, ONE + timedelta(days=1), 0.1, 1, 5.0)
    m1 = info()["misses"]
    bp(_tb, ONE + timedelta(days=1), 0.2, 1, 5.0)
    m2 = info()["misses"]
    check("bound 4: after touching the oldest entry a fifth key evicts the least recently used one, not the touched "
          "one",
          m1 == m0 and m2 == m0 + 1 and info()["entries"] == 4, f"{m0} {m1} {m2} {info()}")
    usage.clear_profile_memo()
    usage._PROFILE_MEMO.max_entries = 0  # noqa: SLF001
    _z = [bits(bp(_tb, ONE + timedelta(days=1), 0.3, 1, 5.0)) for _ in range(2)]
    check("bound 0 keeps nothing (every call a miss) and stays exact",
          info()["entries"] == 0 and info()["misses"] == 2 and _z == [bits(fresh(_tb, ONE + timedelta(days=1), 0.3, 1,
                                                                                       5.0))] * 2, str(info()))
finally:
    usage._PROFILE_MEMO.max_entries = _saved_max  # noqa: SLF001
    usage.clear_profile_memo()

# ---------------------------------------------------------------------------------------------------------------------
print("== [5] threads: concurrent calls with a small bound")
_rt = random.Random(5)
THREAD_TABLES = [made_table({D0 + timedelta(days=i): row(_rt) for i in range(30)}) for _ in range(6)]
CASES = [(ti, a) for ti in range(len(THREAD_TABLES)) for a in (0.1, 0.2, 0.3, 0.4, 0.5)]
WANT = {c: bits(fresh(THREAD_TABLES[c[0]], D0 + timedelta(days=30), c[1], 30, 5.0)) for c in CASES}
errors: list = []
wrong: list = []


def worker(seed: int) -> None:
    r = random.Random(seed)
    try:
        for _ in range(600):
            c = r.choice(CASES)
            p = bp(THREAD_TABLES[c[0]], D0 + timedelta(days=30), c[1], 30, 5.0)
            if bits(p) != WANT[c]:
                wrong.append(c)
    except Exception as exc:  # noqa: BLE001 - recorded and reported by the check
        errors.append(repr(exc))


_saved_max = usage._PROFILE_MEMO.max_entries  # noqa: SLF001
_saved_switch = sys.getswitchinterval()
try:
    usage.clear_profile_memo()
    usage._PROFILE_MEMO.max_entries = 8  # noqa: SLF001
    sys.setswitchinterval(1e-6)                     # switch threads as often as the interpreter allows
    threads = [threading.Thread(target=worker, args=(s,)) for s in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    _ti = info()
finally:
    sys.setswitchinterval(_saved_switch)
    usage._PROFILE_MEMO.max_entries = _saved_max  # noqa: SLF001
    usage.clear_profile_memo()
check("4 threads x 600 calls over 30 keys with a bound of 8: no exception, every result exact, the bound kept, both "
      "hits and evictions happened",
      not errors and not wrong and _ti["entries"] <= 8 and _ti["hits"] > 0 and _ti["misses"] > 30,
      f"{errors[:2]} {wrong[:2]} {_ti}")


class EvictedAfterRead(OrderedDict):
    """The memo's storage, with another cycle's eviction made deterministic: the entry is gone right after a get()
    found it (between the read and the move to the recent end)."""

    def get(self, key, default=None):
        v = super().get(key, default)
        if v is not None:
            self.pop(key, None)
        return v


class EmptiedBeforePop(OrderedDict):
    """... and another cycle's eviction between the size check and popitem(): the storage is empty when it runs."""

    def popitem(self, last=True):
        self.clear()
        return super().popitem(last=last)


def lost_race(storage_cls, max_entries: int, label: str) -> None:
    saved = (usage._PROFILE_MEMO._entries, usage._PROFILE_MEMO.max_entries)  # noqa: SLF001
    try:
        usage.clear_profile_memo()
        usage._PROFILE_MEMO._entries = storage_cls()  # noqa: SLF001
        usage._PROFILE_MEMO.max_entries = max_entries  # noqa: SLF001
        tab = THREAD_TABLES[0]
        got = [bits(bp(tab, D0 + timedelta(days=30), a, 30, 5.0)) for a in (0.1, 0.1, 0.2, 0.2)]
        want = [WANT[(0, a)] for a in (0.1, 0.1, 0.2, 0.2)]
        check(label, got == want, "results differ")
    except Exception as exc:  # noqa: BLE001 - the step must not raise
        check(label, False, repr(exc))
    finally:
        usage._PROFILE_MEMO._entries, usage._PROFILE_MEMO.max_entries = saved  # noqa: SLF001
        usage.clear_profile_memo()


lost_race(EvictedAfterRead, 8, "a hit whose entry another cycle evicts between the read and the move to the recent "
          "end: no exception, the value read is returned (exact)")
lost_race(EmptiedBeforePop, 1, "a store whose eviction finds the memo already emptied by another cycle: no exception, "
          "exact results")

# ---------------------------------------------------------------------------------------------------------------------
print("== [6] differential: memo on against memo off over simulated days")


def at(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# winter (local time = UTC): the 16:00 publication, the 21:30 slot and its refresh, local midnight, the early-morning
# cycles in which the window's oldest partial day (a BST day in July) loses its last complete hours
WINTER = [at(2030, 11, 15, 15, 58), at(2030, 11, 15, 16, 3), at(2030, 11, 15, 21, 30), at(2030, 11, 15, 21, 31),
          at(2030, 11, 15, 23, 0), at(2030, 11, 15, 23, 59), at(2030, 11, 16, 0, 0), at(2030, 11, 16, 0, 1),
          at(2030, 11, 16, 1, 0), at(2030, 11, 16, 2, 0), at(2030, 11, 16, 3, 0), at(2030, 11, 16, 3, 1),
          at(2030, 11, 16, 4, 0), at(2030, 11, 16, 5, 0), at(2030, 11, 16, 6, 30)]
# the 2030-10-27 clock change (BST -> GMT at 01:00Z): local midnight 23:00Z on the 26th, the repeated local hour, the
# 25 h day itself as "today", its 16:00 publication, its slot, and the next local midnight (00:00Z on the 28th)
DST = [at(2030, 10, 26, 21, 0), at(2030, 10, 26, 22, 59), at(2030, 10, 26, 23, 0), at(2030, 10, 26, 23, 1),
       at(2030, 10, 27, 0, 0), at(2030, 10, 27, 0, 59), at(2030, 10, 27, 1, 0), at(2030, 10, 27, 1, 1),
       at(2030, 10, 27, 2, 0), at(2030, 10, 27, 3, 0), at(2030, 10, 27, 4, 0), at(2030, 10, 27, 9, 0),
       at(2030, 10, 27, 15, 59), at(2030, 10, 27, 16, 1), at(2030, 10, 27, 21, 30), at(2030, 10, 27, 23, 59),
       at(2030, 10, 28, 0, 0), at(2030, 10, 28, 0, 1)]
OPEN_AT = {at(2030, 11, 15, 21, 30), at(2030, 11, 16, 0, 1), at(2030, 11, 16, 3, 0), at(2030, 10, 26, 23, 1),
           at(2030, 10, 27, 1, 1), at(2030, 10, 27, 16, 1)}
SCHEDULE = [("winter", t) for t in WINTER] + [("dst", t) for t in DST]


def histories() -> dict:
    """Fresh, separate histories for one run (nothing is shared between the memo-on and the memo-off runs)."""
    return {"winter": make_history(date(2030, 7, 10), 130, CFG, seed=7),
            "dst": make_history(date(2030, 6, 20), 132, CFG, seed=9)}


def payload_bytes(e) -> bytes:
    return json.dumps([e.to_dict(), {k: list(v) for k, v in ac.to_entity_payloads(e).items()}],
                      allow_nan=False).encode("utf-8")


def run_schedule(memo: bool) -> tuple[list, list, float]:
    hs = histories()
    out, per = [], []
    usage.clear_profile_memo()
    saved = usage.build_profile
    if not memo:
        usage.build_profile = usage.build_profile_uncached
    t0 = time.process_time()
    try:
        for span, now in SCHEDULE:
            h = window(hs[span], now)
            before = info()
            e = run_cycle(cycle_in(now, h, recorded=True))
            after = info()
            out.append((span, now.isoformat(), "recorded", payload_bytes(e), e.status))
            per.append((now, after["hits"] - before["hits"], after["misses"] - before["misses"]))
            if now in OPEN_AT:
                e = run_cycle(cycle_in(now, h, recorded=False))
                out.append((span, now.isoformat(), "open", payload_bytes(e), e.status))
    finally:
        usage.build_profile = saved
    return out, per, time.process_time() - t0


ON, ON_PER, ON_CPU = run_schedule(memo=True)
ON_INFO = info()
OFF, _off_per, OFF_CPU = run_schedule(memo=False)
OFF_INFO = info()
usage.clear_profile_memo()
diff = [(s, t, kind) for (s, t, kind, b, _st), (_s2, _t2, _k2, b2, _st2) in zip(ON, OFF) if b != b2]
check(f"{len(ON)} cycles ({len(SCHEDULE)} recorded, {len(ON) - len(SCHEDULE)} all-OPEN): every envelope and its entity "
      "payloads byte-identical with the memo on and off",
      len(ON) == len(OFF) == len(SCHEDULE) + len(OPEN_AT) and not diff, str(diff[:4]))


def day_load_ok(blob: bytes) -> bool:
    return any(f.get("key") == "predicted_day_load" and f.get("status") == "OK" and f.get("value") is not None
               for f in json.loads(blob)[0].get("forecasts", []))


def near_midnight(iso: str) -> bool:
    """Less than the refresh margin before local midnight, where the date-scoped day load expires (INPUT_EXPIRING)."""
    now = datetime.fromisoformat(iso)
    loc = now.astimezone(Z)
    nxt = datetime.combine(loc.date() + timedelta(days=1), datetime.min.time(), tzinfo=Z)
    return (nxt - now).total_seconds() < REFRESH_MARGIN_S


_rec = [(t, st, day_load_ok(b)) for _s, t, kind, b, st in ON if kind == "recorded"]
_open = [st for _s, _t, kind, _b, st in ON if kind == "open"]
check("... non-vacuous: every recorded cycle publishes the profile-based predicted_day_load (OK, with a number) except "
      "inside the refresh margin before local midnight, most are OK (the DST day's early cycles BLOCK their "
      "charge-window items on the changed hour, as I-D9 says), every all-OPEN cycle is BLOCKED; the memo-off run never "
      "used the memo",
      all(ok or near_midnight(t) for t, _st, ok in _rec) and sum(st == "OK" for _t, st, _ok in _rec) >= 20
      and {st for _t, st, _ok in _rec} <= {"OK", "BLOCKED"} and set(_open) == {"BLOCKED"}
      and OFF_INFO["hits"] == OFF_INFO["misses"] == 0,
      f"{OFF_INFO} ok={sum(st == 'OK' for _t, st, _ok in _rec)}/{len(_rec)} "
      f"{[r for r in _rec if r[1] != 'OK' or not r[2]][:12]} {_open}")
_per = {t: (h, m) for t, h, m in ON_PER}
_refresh = _per[at(2030, 11, 15, 21, 31)]
check("the memo was warm: a refresh in the same hour (21:31 after 21:30) is all hits",
      _refresh[1] == 0 and _refresh[0] > 200, str(_refresh))
check("... and it missed where the content changed: at local midnight (a new day completes) and in an early-morning "
      "cycle of each span (the window's oldest partial day changes)",
      _per[at(2030, 11, 16, 0, 0)][1] > 0 and _per[at(2030, 10, 26, 23, 0)][1] > 0
      and any(_per[at(2030, 11, 16, h)][1] > 0 for h in (1, 2, 3, 4, 5))
      and any(_per[at(2030, 10, 27, h)][1] > 0 for h in (0, 1, 2, 3, 4)),
      str({t.isoformat(): v for t, v in _per.items() if v[1]}))
check(f"... and over the schedule most calls were hits ({ON_INFO['hits']} hits, {ON_INFO['misses']} misses); CPU "
      f"{ON_CPU:.1f} s with the memo, {OFF_CPU:.1f} s without",
      ON_INFO["hits"] > 3 * ON_INFO["misses"] and ON_INFO["bypassed"] == 0, str(ON_INFO))

# ---------------------------------------------------------------------------------------------------------------------
print("== [7] the docs say the engine holds this memo")
ROOT = Path(__file__).resolve().parents[2]
_contract = (ROOT / "docs" / "intelligence" / "INTELLIGENCE_FOUNDATION_CONTRACT.md").read_text(encoding="utf-8")
_s134 = _contract.split("### 13.4 ", 1)[1].split("\n### 13.5 ", 1)[0] if "### 13.4 " in _contract else ""
_memo_par = _s134[_s134.find("**The engine's profile memo"):] if "**The engine's profile memo" in _s134 else ""
_memo_par = _memo_par.split("\n- **", 1)[0]
_flat = " ".join(_memo_par.split())
check("contract 13.4 has the profile-memo paragraph: exact, bounded, `PROFILE_MEMO_MAX_ENTRIES` with the code's value, "
      "least recently used evicted first, pure in its result, this suite, and no rule changes",
      bool(_flat) and "`build_profile`" in _flat and "exact, bounded memo" in _flat
      and f"`PROFILE_MEMO_MAX_ENTRIES` ({usage.PROFILE_MEMO_MAX_ENTRIES})" in _flat
      and "least recently used evicted first" in _flat and "stays pure in its result" in _flat
      and "`test_intel_profile_memo.py`" in _flat and "`build_profile_uncached`" in _flat
      and "no bound, margin, PROPOSED value, cadence, freshness, input-expiry or fail-closed rule changes" in _flat,
      _flat[:200])
import intelligence.shadow_cycle as _sc  # noqa: E402

_usage_doc = " ".join((usage.__doc__ or "").split())
_sc_doc = " ".join((_sc.__doc__ or "").split())
_rc_doc = " ".join((_sc.run_cycle.__doc__ or "").split())
check("the usage module docstring says it keeps one exact, bounded memo of build_profile between calls, and why",
      "one piece of state between calls: an exact, bounded memo of `build_profile`" in _usage_doc
      and "returns exactly what a fresh build would" in _usage_doc, _usage_doc[-400:])
check("the shadow_cycle module docstring and run_cycle's say the memo is the one state kept and never changes a result",
      "the one state the engine keeps between calls is the exact, bounded memo of intelligence.usage.build_profile"
      in _sc_doc and "byte-identical envelope whether the memo is cold or warm" in _sc_doc
      and "never changes a result" in _rc_doc, _rc_doc)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all profile-memo checks passed")
