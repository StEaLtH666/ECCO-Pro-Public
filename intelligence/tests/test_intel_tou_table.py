#!/usr/bin/env python3
"""Planning stream: the grid-charge classification of the read-only TOU slot table (intelligence/tou_table.py;
INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.5). SYNTHETIC tables only (fixtures/plan/tou_tables_2030.json).

  [1] the shared fixture's table and the target-vocabulary table classify: one grid-charge run, its target and power
  [2] slot classes by the exact texts only: Grid and Grid + Generator are GRID, None (the literal text) and Generator are
      NOT_GRID; a null, unknown or differently spelt source or mode, and a flags word that is null or disagrees with the
      texts, make the slot UNKNOWN (TOU_SOURCE_DECODE_CONFLICT for a disagreement); Unknown 0x14 is UNKNOWN; a flags word
      with any bit outside 0x1F set (bits 5-15, not decoded) is UNKNOWN too (TOU_FLAGS_UNDECODED_BITS; A33, ENG-4)
  [3] an unknown slot beside a grid slot BLOCKs (no window), a one-row table with no source is never a window
  [4] the schema: a v1 table (TOU_TABLE_LEGACY_SCHEMA), not six rows / a bad time / an end that is not the next start / a
      zero-length slot / two wraps (TOU_RING_INVALID), a wrong key, slot number, type or range (TOU_TABLE_MALFORMED)
  [5] runs: adjacent grid slots merge into one window; two separate runs BLOCK; a run across local midnight (by 2 h, and
      by one short slot each side: 23:30-00:30, 23:55-00:05, 23:59-00:01; PR2-3) and a run of the whole day BLOCK; a run
      that ends exactly at midnight is a window
  [6] the enables and the overlay: false, missing, stale, of unresolved age or not a bool / not a known state each BLOCK
      with its own code
  [7] target and power: any null target or power BLOCKs; a zero power in the run BLOCKs, outside the run it does not
  [8] the window: its next occurrence that ends after now (in progress, tonight, tomorrow), its local minutes, the run,
      and the freshness of everything it rests on (all fresh, the largest age, the smallest limit); a stale table gives
      no window and no TOU_* BLOCK (the caller BLOCKs CHARGE_WINDOW_UNKNOWN); a Grid slot in the spring-forward gap
      never gives an occurrence with end <= start (PR2-3)
  [9] every code: a BLOCK (except TOU_TABLE_NOT_FRESH), at most MAX_CODE_CHARS, a fixed text with no digit
  [10] 2000 seeded mutated tables never raise; any window is one contiguous run of GRID slots inside one local day
  [11] the module is pure: no clock read, file, os or network access, no dynamic import or exec
  [12] every code it can publish is named in INTELLIGENCE_FOUNDATION_CONTRACT.md section 13
"""

from __future__ import annotations

import ast
import copy
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence import tou_table as tt  # noqa: E402
from intelligence.site_decisions import InputState  # noqa: E402
from intelligence.timeutil import zone  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
Z = zone("Europe/London")
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
TABLES = json.loads((Path(__file__).resolve().parent / "fixtures" / "plan" / "tou_tables_2030.json")
                    .read_text(encoding="utf-8"))["tables"]


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def table(name: str) -> list[dict]:
    return copy.deepcopy(TABLES[name])


def st(key: str, value, fresh: bool = True, age: float | None = 30.0, limit: float | None = 300.0) -> InputState:
    return InputState(key, value, fresh, age, limit)


def ok_inputs(value, **over):
    """(table, enabled, grid_enabled, overlay) states, all fresh and usable unless overridden."""
    s = {"table": st(tt.TOU_TABLE_KEY, value), "enabled": st(tt.TOU_ENABLED_KEY, True),
         "grid": st(tt.TOU_GRID_CHARGE_ENABLED_KEY, True), "overlay": st(tt.TOU_OVERLAY_KEY, "NONE")}
    s.update(over)
    return s["table"], s["enabled"], s["grid"], s["overlay"]


def judge(value, **over) -> tt.Classification:
    return tt.classify(*ok_inputs(value, **over))


def window(value, now=NOW, **over):
    return tt.grid_window(*ok_inputs(value, **over), now, Z)


def codes(c) -> list[str]:
    fs = c.findings if isinstance(c, tt.Classification) else c
    return [f.code for f in fs]


def ring(starts, sources, targets=None, powers=None, modes=None) -> list[dict]:
    """Six schema v2 rows from six start times and six source texts (flags agree with the texts)."""
    n = len(starts)
    targets = targets or [20.0] * n
    powers = powers or [5000.0] * n
    modes = modes or ["None"] * n
    return [{"slot": i + 1, "start": starts[i], "end": starts[(i + 1) % n], "target_soc_pct": targets[i],
             "charge_source": sources[i], "flags_raw": ac.TOU_CHARGE_SOURCE_BITS[sources[i]] | ac.TOU_MODE_BITS[modes[i]],
             "mode": modes[i], "power_w": powers[i]} for i in range(n)]


STARTS = ["00:00", "01:00", "04:30", "08:00", "16:00", "19:00"]


print("== [1] the shared fixture's table and the target-vocabulary table")
c = judge(table("one_grid"))
check("the shared fixture's table: one run 01:00-04:30, target 80, power 5000, no finding",
      c.run is not None and (c.run.start_min, c.run.end_min) == (60, 270) and c.run.single_target_pct == 80.0
      and c.run.min_power_w == 5000.0 and not c.findings and [s.slot for s in c.run.slots] == [2], str(c))
c = judge(table("target_vocabulary"))
check("the target-vocabulary table (the literal text None, mode None everywhere, flags 1 / 0, a short slot before the grid "
      "slot): one run 00:30-05:30; None is NOT_GRID, never unknown",
      c.run is not None and (c.run.start_min, c.run.end_min) == (30, 330) and not c.findings
      and [s.cls for s in c.slots] == [tt.NOT_GRID, tt.NOT_GRID, tt.GRID, tt.NOT_GRID, tt.NOT_GRID, tt.NOT_GRID], str(c))
c = judge(table("grid_generator"))
check("Grid + Generator (mode Charge) counts as GRID; Generator and None are NOT_GRID", c.run is not None
      and (c.run.start_min, c.run.end_min) == (120, 300) and c.slots[0].cls == tt.NOT_GRID and not c.findings, str(c))

print("== [2] slot classes by the exact texts")
check("the class map is exactly the four dongle texts", dict(tt.CHARGE_SOURCE_CLASS) == {
    "None": tt.NOT_GRID, "Grid": tt.GRID, "Generator": tt.NOT_GRID, "Grid + Generator": tt.GRID})
for src, mode, flags, want in (("Grid", "None", 1, (tt.GRID, False)), ("Grid + Generator", "General", 7, (tt.GRID, False)),
                               ("None", "None", 0, (tt.NOT_GRID, False)), ("Generator", "Backup", 10, (tt.NOT_GRID, False)),
                               ("grid", "None", 1, (tt.UNKNOWN, False)), ("GRID", "None", 1, (tt.UNKNOWN, False)),
                               (" Grid", "None", 1, (tt.UNKNOWN, False)), ("Grid+Generator", "None", 3, (tt.UNKNOWN, False)),
                               ("Unknown", "None", 1, (tt.UNKNOWN, False)), (None, "None", 1, (tt.UNKNOWN, False)),
                               ("Grid", None, 1, (tt.UNKNOWN, False)), ("Grid", "Unknown 0x14", 1, (tt.UNKNOWN, False)),
                               ("Grid", "none", 1, (tt.UNKNOWN, False)), ("Grid", "None", None, (tt.UNKNOWN, False)),
                               ("Grid", "None", 0, (tt.UNKNOWN, True)), ("None", "None", 1, (tt.UNKNOWN, True)),
                               ("Grid", "General", 1, (tt.UNKNOWN, True)), ("Grid", "None", 5, (tt.UNKNOWN, True)),
                               ("Grid", "None", 0x21, (tt.UNKNOWN, False)), ("Grid", "None", 0x8001, (tt.UNKNOWN, False)),
                               ("None", "None", 0x20, (tt.UNKNOWN, False)), ("Grid", "None", 0x25, (tt.UNKNOWN, True))):
    check(f"slot_class({src!r}, {mode!r}, {flags!r}) -> {want}", tt.slot_class(src, mode, flags) == want,
          str(tt.slot_class(src, mode, flags)))
t = table("one_grid")
t[1]["flags_raw"] = 4                                  # Grid text, but the flags say no source
c = judge(t)
check("a flags word that disagrees with the Grid text: UNKNOWN, BLOCK TOU_SLOT_SOURCE_UNKNOWN and TOU_SOURCE_DECODE_CONFLICT",
      c.run is None and {"TOU_SLOT_SOURCE_UNKNOWN", "TOU_SOURCE_DECODE_CONFLICT"} <= set(codes(c)), str(codes(c)))
for bits, label in ((0x20, "bit 5"), (0x8000, "bit 15"), (0x0400, "bit 10")):
    t = table("one_grid")
    t[1]["flags_raw"] = t[1]["flags_raw"] | bits             # the Grid slot, its source and mode bits still agreeing
    c = judge(t)
    check(f"ENG-4: the Grid slot's flags word with {label} set (undecoded): UNKNOWN, no window, BLOCK TOU_SLOT_SOURCE_UNKNOWN "
          "and TOU_FLAGS_UNDECODED_BITS (never an ordinary Grid slot)", c.run is None and c.slots[1].cls == tt.UNKNOWN
          and {"TOU_SLOT_SOURCE_UNKNOWN", "TOU_FLAGS_UNDECODED_BITS"} <= set(codes(c))
          and "TOU_SOURCE_DECODE_CONFLICT" not in codes(c), str(codes(c)))
t = table("one_grid")
t[0]["flags_raw"] = t[0]["flags_raw"] | 0x40                 # a None slot: an undecoded bit could hide a second grid slot
c = judge(t)
check("ENG-4: a None slot with an undecoded bit set is UNKNOWN too (BLOCK, TOU_FLAGS_UNDECODED_BITS); the decoded mask is "
      "0x1F", c.run is None and "TOU_FLAGS_UNDECODED_BITS" in codes(c) and tt.DECODED_FLAGS_MASK == 0x1F
      and not tt.undecoded_flag_bits(0x1F) and tt.undecoded_flag_bits(0x20) and not tt.undecoded_flag_bits(None),
      str(codes(c)))
t = table("one_grid")
t[3]["mode"] = "Unknown 0x14"
c = judge(t)
check("the mode Unknown 0x14 on a non-grid slot: UNKNOWN, BLOCK (it could hide a second window), no decode conflict",
      c.run is None and codes(c) == ["TOU_SLOT_SOURCE_UNKNOWN"], str(codes(c)))

print("== [3] unknown slots and invented windows")
c = judge(table("unknown_beside_grid"))
check("an unknown slot beside a Grid slot: BLOCK TOU_SLOT_SOURCE_UNKNOWN, no window (the old reading gave one)",
      c.run is None and "TOU_SLOT_SOURCE_UNKNOWN" in codes(c), str(codes(c)))
w, notes, _c = window([{"slot": 1, "start": "01:00", "end": "04:30"}])
check("a one-row table with no source is never a window (TOU_TABLE_LEGACY_SCHEMA)", w is None
      and codes(notes) == ["TOU_TABLE_LEGACY_SCHEMA"], str(codes(notes)))
c = judge(ring(STARTS, ["None"] * 6))
check("six NOT_GRID slots: BLOCK TOU_NO_GRID_SLOT (no period is invented)", c.run is None and codes(c) == ["TOU_NO_GRID_SLOT"])

print("== [4] the schema")
check("a v1 table (start / end / target only): TOU_TABLE_LEGACY_SCHEMA", codes(judge(table("legacy_v1"))) == ["TOU_TABLE_LEGACY_SCHEMA"])
check("... also six v1 rows", codes(judge([{"slot": i + 1, "start": s, "end": STARTS[(i + 1) % 6], "target_soc_pct": 20}
                                            for i, s in enumerate(STARTS)])) == ["TOU_TABLE_LEGACY_SCHEMA"])
for label, val in (("not a list", "x"), ("empty", []), ("a list of numbers", [1, 2]), ("None", None), ("a dict", {"a": 1})):
    check(f"{label}: TOU_TABLE_MALFORMED", codes(judge(val)) == ["TOU_TABLE_MALFORMED"], str(codes(judge(val))))
for n in (5, 7):
    rows = ring(STARTS, ["None", "Grid", "None", "None", "None", "None"])
    rows = rows[:5] if n == 5 else rows + [dict(rows[-1], slot=7)]
    check(f"{n} rows: TOU_RING_INVALID", codes(judge(rows)) == ["TOU_RING_INVALID"], str(codes(judge(rows))))


def mutated(fn) -> list[str]:
    t = table("one_grid")
    fn(t)
    return codes(judge(t))


for label, fn, want in (
        ("an extra row key", lambda t: t[0].update(voltage=50), "TOU_TABLE_MALFORMED"),
        ("a missing row key", lambda t: t[2].pop("mode"), "TOU_TABLE_MALFORMED"),
        ("slots out of order", lambda t: t.__setitem__(slice(0, 2), [dict(t[1]), dict(t[0])]), "TOU_TABLE_MALFORMED"),
        ("a slot number that is a bool", lambda t: t[0].update(slot=True), "TOU_TABLE_MALFORMED"),
        ("a target above 100", lambda t: t[1].update(target_soc_pct=101.0), "TOU_TABLE_MALFORMED"),
        ("a target that is text", lambda t: t[1].update(target_soc_pct="80"), "TOU_TABLE_MALFORMED"),
        ("a negative power", lambda t: t[1].update(power_w=-1.0), "TOU_TABLE_MALFORMED"),
        ("a power that is not finite", lambda t: t[1].update(power_w=float("inf")), "TOU_TABLE_MALFORMED"),
        ("a flags word above 65535", lambda t: t[1].update(flags_raw=70000), "TOU_TABLE_MALFORMED"),
        ("a flags word that is a float", lambda t: t[1].update(flags_raw=5.0), "TOU_TABLE_MALFORMED"),
        ("a flags word that is a bool", lambda t: t[1].update(flags_raw=True), "TOU_TABLE_MALFORMED"),
        ("a source that is a number", lambda t: t[1].update(charge_source=1), "TOU_TABLE_MALFORMED"),
        ("an end that is not the next start", lambda t: t[1].update(end="04:00"), "TOU_RING_INVALID"),
        ("a null start", lambda t: t[3].update(start=None), "TOU_RING_INVALID"),
        ("a start of 24:00", lambda t: t[3].update(start="24:00"), "TOU_RING_INVALID"),
        ("a start written 8:00", lambda t: t[3].update(start="8:00"), "TOU_RING_INVALID"),
        ("a zero-length slot", lambda t: (t[2].update(start="04:30", end="04:30"), t[1].update(end="04:30"),
                                          t[3].update(start="04:30")), "TOU_RING_INVALID"),
        ("two wraps past midnight", lambda t: (t[3].update(start="02:00", end="16:00"), t[2].update(end="02:00")),
         "TOU_RING_INVALID")):
    got = mutated(fn)
    check(f"{label}: {want}", got == [want], str(got))

print("== [5] runs")
adj = ring(["00:00", "01:00", "02:30", "04:30", "16:00", "19:00"], ["None", "Grid", "Grid", "None", "None", "None"],
           targets=[20.0, 80.0, 80.0, 20.0, 20.0, 20.0], powers=[5000.0, 5000.0, 3000.0, 5000.0, 5000.0, 5000.0])
c = judge(adj)
check("two adjacent Grid slots merge into one window 01:00-04:30 (one target, the lowest power)",
      c.run is not None and (c.run.start_min, c.run.end_min) == (60, 270) and [s.slot for s in c.run.slots] == [2, 3]
      and c.run.single_target_pct == 80.0 and c.run.min_power_w == 3000.0, str(c))
adj2 = copy.deepcopy(adj)
adj2[2]["target_soc_pct"] = 70.0
check("... with different targets the run has no single target", judge(adj2).run.single_target_pct is None)
check("two separate Grid runs: BLOCK TOU_MULTIPLE_GRID_WINDOWS", codes(judge(table("two_grid_runs"))) == ["TOU_MULTIPLE_GRID_WINDOWS"])
check("a Grid run across local midnight (slot 6 into slot 1): BLOCK CHARGE_WINDOW_CROSSES_MIDNIGHT",
      codes(judge(table("across_midnight"))) == ["CHARGE_WINDOW_CROSSES_MIDNIGHT"], str(codes(judge(table("across_midnight")))))
# PR2-3: the midnight bound is exact. A run that crosses local midnight by one short slot each side BLOCKs as well (the
# fixture's run crosses by 2 h, so a bound with slack would pass it)
for label, starts in (("23:30-00:30", ["00:00", "00:30", "06:00", "12:00", "18:00", "23:30"]),
                      ("23:55-00:05", ["00:00", "00:05", "06:00", "12:00", "18:00", "23:55"]),
                      ("23:59-00:01", ["00:00", "00:01", "06:00", "12:00", "18:00", "23:59"])):
    xm = judge(ring(starts, ["Grid", "None", "None", "None", "None", "Grid"]))
    check(f"PR2-3: a Grid run {label} (slot 6 into slot 1, crossing local midnight by one slot edge): BLOCK "
          "CHARGE_WINDOW_CROSSES_MIDNIGHT, no run", codes(xm) == ["CHARGE_WINDOW_CROSSES_MIDNIGHT"] and xm.run is None,
          str((codes(xm), xm.run)))
check("all six slots Grid (the whole day): BLOCK CHARGE_WINDOW_NOT_REPRESENTABLE",
      codes(judge(ring(STARTS, ["Grid"] * 6))) == ["CHARGE_WINDOW_NOT_REPRESENTABLE"])
late = judge(ring(STARTS, ["None", "None", "None", "None", "None", "Grid"]))
check("a Grid run 19:00-00:00 ends exactly at midnight: a window (19:00-24:00)", late.run is not None
      and (late.run.start_min, late.run.end_min) == (1140, 1440) and not late.findings, str(late))
first = judge(ring(STARTS, ["Grid", "None", "None", "None", "None", "None"]))
check("a Grid run 00:00-01:00 starts exactly at midnight: a window", first.run is not None
      and (first.run.start_min, first.run.end_min) == (0, 60))

print("== [6] the enables and the overlay")
T = table("one_grid")
for label, over, want in (
        ("the TOU enable off", {"enabled": st(tt.TOU_ENABLED_KEY, False)}, "TOU_DISABLED"),
        ("the TOU enable missing", {"enabled": None}, "TOU_ENABLE_UNKNOWN"),
        ("the TOU enable stale", {"enabled": st(tt.TOU_ENABLED_KEY, True, fresh=False, age=900.0)}, "TOU_ENABLE_UNKNOWN"),
        ("the TOU enable of unresolved age", {"enabled": st(tt.TOU_ENABLED_KEY, True, limit=None)}, "TOU_ENABLE_UNKNOWN"),
        ("the TOU enable not a bool", {"enabled": st(tt.TOU_ENABLED_KEY, "on")}, "TOU_ENABLE_UNKNOWN"),
        ("the TOU enable under another key", {"enabled": st(tt.TOU_GRID_CHARGE_ENABLED_KEY, True)}, "TOU_ENABLE_UNKNOWN"),
        ("the grid-charge enable off", {"grid": st(tt.TOU_GRID_CHARGE_ENABLED_KEY, False)}, "TOU_GRID_CHARGE_DISABLED"),
        ("the grid-charge enable missing", {"grid": None}, "TOU_GRID_CHARGE_ENABLE_UNKNOWN"),
        ("the grid-charge enable stale", {"grid": st(tt.TOU_GRID_CHARGE_ENABLED_KEY, True, fresh=False)},
         "TOU_GRID_CHARGE_ENABLE_UNKNOWN"),
        ("the grid-charge enable a number", {"grid": st(tt.TOU_GRID_CHARGE_ENABLED_KEY, 1)}, "TOU_GRID_CHARGE_ENABLE_UNKNOWN"),
        ("an overlay active (Free Power, Dump to Grid or a manual write)", {"overlay": st(tt.TOU_OVERLAY_KEY, "ACTIVE")},
         "TOU_OVERLAY_ACTIVE"),
        ("the overlay state missing", {"overlay": None}, "TOU_OVERLAY_STATE_UNKNOWN"),
        ("the overlay state stale", {"overlay": st(tt.TOU_OVERLAY_KEY, "NONE", fresh=False)}, "TOU_OVERLAY_STATE_UNKNOWN"),
        ("the overlay state not a known state", {"overlay": st(tt.TOU_OVERLAY_KEY, "none")}, "TOU_OVERLAY_STATE_UNKNOWN")):
    got = codes(judge(T, **over))
    check(f"{label}: BLOCK {want}, no window", got == [want] and judge(T, **over).run is None, str(got))
both = codes(judge(T, enabled=st(tt.TOU_ENABLED_KEY, False), overlay=st(tt.TOU_OVERLAY_KEY, "ACTIVE")))
check("several problems: each is named", set(both) == {"TOU_DISABLED", "TOU_OVERLAY_ACTIVE"}, str(both))

print("== [7] target and power")
t = table("one_grid")
t[4]["target_soc_pct"] = None
check("a null target on any slot: BLOCK TOU_SLOT_TARGET_UNKNOWN", codes(judge(t)) == ["TOU_SLOT_TARGET_UNKNOWN"])
t = table("one_grid")
t[0]["power_w"] = None
check("a null power on any slot: BLOCK TOU_SLOT_POWER_UNKNOWN", codes(judge(t)) == ["TOU_SLOT_POWER_UNKNOWN"])
t = table("one_grid")
t[1]["power_w"] = 0.0
check("a zero power in the grid run: BLOCK TOU_SLOT_POWER_ZERO", codes(judge(t)) == ["TOU_SLOT_POWER_ZERO"])
t = table("one_grid")
t[4]["power_w"] = 0.0
check("... outside the run a zero power changes nothing", judge(t).run is not None and not judge(t).findings)
t = table("one_grid")
t[1]["power_w"] = 2500.0
check("the run's lowest power is the power cap the cycle applies", judge(t).run.min_power_w == 2500.0)

print("== [8] the window")
w, notes, c = window(table("one_grid"))
check("tonight: the next occurrence 01:00-04:30 tomorrow (local wall clock), no finding",
      w is not None and w.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC) and w.end == datetime(2030, 1, 16, 4, 30, tzinfo=UTC)
      and w.local_minutes == (60, 270) and notes == [] and w.run == c.run, str((w, notes)))
w2, _n, _c = window(table("one_grid"), now=datetime(2030, 1, 16, 2, 0, tzinfo=UTC))
check("inside the window: the current occurrence", w2 is not None and w2.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC))
w3, _n, _c = window(table("one_grid"), now=datetime(2030, 1, 16, 4, 30, tzinfo=UTC))
check("at its end: the next day's occurrence", w3 is not None and w3.start == datetime(2030, 1, 17, 1, 0, tzinfo=UTC))
ws, _n, _c = window(table("target_vocabulary"), now=datetime(2030, 7, 1, 20, 0, tzinfo=UTC))
check("in summer the wall-clock window is 00:30-05:30 BST", ws is not None and ws.start == datetime(2030, 7, 1, 23, 30, tzinfo=UTC)
      and ws.end == datetime(2030, 7, 2, 4, 30, tzinfo=UTC), str(ws))
w4, _n, _c = window(table("one_grid"), table=st(tt.TOU_TABLE_KEY, table("one_grid"), age=40.0, limit=600.0),
                    enabled=st(tt.TOU_ENABLED_KEY, True, age=90.0, limit=300.0))
check("its freshness rests on all four readings: fresh, the largest age and the smallest limit",
      w4 is not None and w4.fresh is True and w4.age_s == 90.0 and w4.limit_s == 300.0, str(w4))
# PR2-3: a Grid slot 01:00-02:00 local, which does not exist on the Europe/London spring-forward day (2030-03-31): no
# occurrence ever has end <= start. Every half-hour from two days before to the day after: on the eve, once the 30th's
# occurrence has ended, the next one (the 31st's) is empty, so there is no window (CHARGE_WINDOW_NOT_REPRESENTABLE, a
# BLOCK); on the day itself the window is the 1st of April's 01:00-02:00 BST (00:00-01:00 UTC)
SPRING_GAP = ring(["00:00", "01:00", "02:00", "06:00", "12:00", "18:00"], ["None", "Grid", "None", "None", "None", "None"])
sg_bad, sg_seen = [], {}
for k in range(4 * 48):
    t_ = datetime(2030, 3, 29, 0, 0, tzinfo=UTC) + timedelta(minutes=30 * k)
    wg, ng, _c = window(SPRING_GAP, now=t_)
    if wg is not None and not (wg.end > wg.start and wg.end > t_):
        sg_bad.append((t_.isoformat(), wg.start.isoformat(), wg.end.isoformat()))
    sg_seen[t_] = (None if wg is None else (wg.start, wg.end), codes(ng))
check("PR2-3: a Grid slot 01:00-02:00 local before and on the spring-forward day: never an occurrence with end <= start",
      not sg_bad, str(sg_bad[:3]))
check("... on the eve after the 30th's occurrence (12:00 UTC): no window, BLOCK CHARGE_WINDOW_NOT_REPRESENTABLE (the 31st's "
      "occurrence does not exist)", sg_seen[datetime(2030, 3, 30, 12, 0, tzinfo=UTC)] == (None, ["CHARGE_WINDOW_NOT_REPRESENTABLE"])
      and all(f.severity == sd.BLOCK for f in window(SPRING_GAP, now=datetime(2030, 3, 30, 12, 0, tzinfo=UTC))[1]),
      str(sg_seen[datetime(2030, 3, 30, 12, 0, tzinfo=UTC)]))
check("... on the day itself (00:30 UTC): the 1st of April's occurrence, 00:00-01:00 UTC; the day before (00:00 UTC): the "
      "30th's, 01:00-02:00 UTC",
      sg_seen[datetime(2030, 3, 31, 0, 30, tzinfo=UTC)] == ((datetime(2030, 4, 1, 0, 0, tzinfo=UTC),
                                                             datetime(2030, 4, 1, 1, 0, tzinfo=UTC)), [])
      and sg_seen[datetime(2030, 3, 30, 0, 0, tzinfo=UTC)] == ((datetime(2030, 3, 30, 1, 0, tzinfo=UTC),
                                                                datetime(2030, 3, 30, 2, 0, tzinfo=UTC)), []),
      str((sg_seen[datetime(2030, 3, 31, 0, 30, tzinfo=UTC)], sg_seen[datetime(2030, 3, 30, 0, 0, tzinfo=UTC)])))
for label, tbl in (("stale", st(tt.TOU_TABLE_KEY, table("one_grid"), fresh=False, age=900.0)),
                   ("of unresolved age", st(tt.TOU_TABLE_KEY, table("one_grid"), limit=None)), ("missing", None)):
    wn, nn, _c = window(table("one_grid"), table=tbl)
    check(f"a table that is {label}: no window, only TOU_TABLE_NOT_FRESH (WARN)", wn is None
          and [(f.code, f.severity) for f in nn] == [("TOU_TABLE_NOT_FRESH", sd.WARN)], str(nn))

print("== [9] codes and texts")
CODES = ("TOU_TABLE_LEGACY_SCHEMA", "TOU_TABLE_MALFORMED", "TOU_RING_INVALID", "TOU_SLOT_SOURCE_UNKNOWN",
         "TOU_SOURCE_DECODE_CONFLICT", "TOU_FLAGS_UNDECODED_BITS", "TOU_SLOT_TARGET_UNKNOWN", "TOU_SLOT_POWER_UNKNOWN",
         "TOU_ENABLE_UNKNOWN", "TOU_DISABLED",
         "TOU_GRID_CHARGE_ENABLE_UNKNOWN", "TOU_GRID_CHARGE_DISABLED", "TOU_OVERLAY_STATE_UNKNOWN", "TOU_OVERLAY_ACTIVE",
         "TOU_NO_GRID_SLOT", "TOU_MULTIPLE_GRID_WINDOWS", "TOU_SLOT_POWER_ZERO", "CHARGE_WINDOW_CROSSES_MIDNIGHT",
         "CHARGE_WINDOW_NOT_REPRESENTABLE")
check("every BLOCK code of section 13.5 has a fixed text here, and nothing else does (but TOU_TABLE_NOT_FRESH)",
      set(tt._TEXTS) == set(CODES) | {"TOU_TABLE_NOT_FRESH"}, str(sorted(set(tt._TEXTS) ^ set(CODES))))  # noqa: SLF001
check("every code fits MAX_CODE_CHARS and every text carries no digit",
      all(len(k) <= ac.MAX_CODE_CHARS and not any(ch.isdigit() for ch in v) for k, v in tt._TEXTS.items()))  # noqa: SLF001
contract = (ROOT / "docs" / "intelligence" / "INTELLIGENCE_FOUNDATION_CONTRACT.md").read_text(encoding="utf-8")
sec = contract[contract.index("### 13.5"):contract.index("### 13.6")]
check("every code is named in FOUNDATION CONTRACT section 13.5", all(f"`{k}`" in sec for k in CODES),
      str([k for k in CODES if f"`{k}`" not in sec]))
seen = set()
for name in ("one_grid", "unknown_beside_grid", "two_grid_runs", "across_midnight", "legacy_v1"):
    for f in window(table(name))[1]:
        seen.add((f.code, f.severity))
check("the refusals met on the fixtures are BLOCKs", seen and all(sev == sd.BLOCK for _c, sev in seen), str(seen))

print("== [10] seeded mutated tables never raise")
rnd = random.Random(1301)
VALUES = [None, "", "Grid", "None", "Generator", "Grid + Generator", "grid", "Unknown 0x14", 0, 1, 3, 5, 19, -1, 70000, 1.5,
          float("nan"), True, "01:00", "24:00", "23:59", "00:00", 100.0, 101.0, [], {}]
bad, windows = [], 0
for i in range(2000):
    t = table(rnd.choice(["one_grid", "target_vocabulary", "grid_generator", "two_grid_runs", "across_midnight"]))
    for _ in range(rnd.randint(0, 3)):
        r = rnd.randrange(len(t))
        op = rnd.random()
        if op < 0.75:
            t[r][rnd.choice(list(t[r]))] = rnd.choice(VALUES)
        elif op < 0.85:
            t.pop(r)
        elif op < 0.95:
            t[r].pop(rnd.choice(list(t[r])), None)
        else:
            t.insert(r, copy.deepcopy(t[r]))
    over = {}
    if rnd.random() < 0.3:
        over["enabled"] = st(tt.TOU_ENABLED_KEY, rnd.choice([True, False, None, "on", 1]), fresh=rnd.random() < 0.8)
    if rnd.random() < 0.3:
        over["overlay"] = st(tt.TOU_OVERLAY_KEY, rnd.choice(["NONE", "ACTIVE", None, "x"]))
    try:
        w, notes, c = window(t, now=NOW + timedelta(minutes=rnd.randint(0, 2880)), **over)
    except Exception as exc:  # noqa: BLE001 - the property under test
        bad.append((i, "raised", type(exc).__name__))
        continue
    if w is None:
        if not notes or not any(f.severity == sd.BLOCK for f in notes):
            bad.append((i, "no window without a BLOCK", codes(notes)))
        continue
    windows += 1
    slots = w.run.slots
    if notes or not all(s.cls == tt.GRID for s in slots) or not 0 <= w.local_minutes[0] < w.local_minutes[1] <= 1440:
        bad.append((i, "a window that is not one GRID run inside a day", w.local_minutes))
    if sum(1 for s in c.slots if s.cls == tt.GRID) != len(slots) or any(s.cls == tt.UNKNOWN for s in c.slots):
        bad.append((i, "a window beside another GRID or an UNKNOWN slot"))
    if not w.end > w.start:
        bad.append((i, "an empty occurrence"))
check(f"2000 seeded mutations: never raise; every refusal is a BLOCK; every window is one GRID run inside one local day, "
      f"with no other GRID or UNKNOWN slot ({windows} windows)", not bad and 0 < windows < 2000, str(bad[:3]))

print("== [11] the module is pure")
tree = ast.parse((ROOT / "intelligence" / "tou_table.py").read_text(encoding="utf-8"))
imports = {(n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
    a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
calls = {(n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")) for n in ast.walk(tree)
         if isinstance(n, ast.Call)}
check("only stdlib types and intelligence modules are imported (no os, io, socket, time, importlib)",
      imports <= {"__future__", "dataclasses", "datetime", "types", "typing", "advisory_contract", "explain",
                  "site_decisions", "timeutil"}, str(sorted(imports)))
check("no clock read, open(), exec / eval / compile or dynamic import call",
      not calls & {"now", "utcnow", "today", "time", "open", "exec", "eval", "compile", "__import__", "import_module"},
      str(sorted(calls & {"now", "utcnow", "today", "time", "open", "exec", "eval", "compile", "__import__"})))

print("== [12] every code this module can publish is named in the foundation contract's section 13")
_doc = (ROOT / "docs" / "intelligence" / "INTELLIGENCE_FOUNDATION_CONTRACT.md").read_text(encoding="utf-8")
_s13 = _doc.split("\n## 13.", 1)[1] if "\n## 13." in _doc else ""
_missing = sorted(c for c in tt._TEXTS if f"`{c}`" not in _s13)  # noqa: SLF001 - the module's own code table
check(f"all {len(tt._TEXTS)} TOU-table codes (BLOCKs and the TOU_TABLE_NOT_FRESH WARN) appear in section 13",  # noqa: SLF001
      bool(_s13) and not _missing, str(_missing))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all TOU-table checks passed")
