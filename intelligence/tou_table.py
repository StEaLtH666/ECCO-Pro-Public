"""The grid-charge classification of the read-only TOU slot table (planning layer; fail closed).

INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.5. The value of `tou.slot_table` is schema v2 (advisory_contract
TOU_SLOT_TABLE_*): exactly six rows in slot order, each {slot, start, end, target_soc_pct, charge_source, flags_raw, mode,
power_w}, `end` the next row's start (slot 6 runs into slot 1), a null field unknown. This module says which part of the
day the inverter is CONFIGURED to grid-charge in, and refuses to say anything when the table, the two enables or the
overlay state are unknown, stale or in conflict:

  slot class        by the exact dongle texts only: `Grid` and `Grid + Generator` are GRID, `None` and `Generator` are
                    NOT_GRID. A slot is UNKNOWN when its source or mode is null or not one of the exact texts, or its
                    flags word is null or disagrees with them (bits 0-1 against the source, bits 2-4 against the mode),
                    or has any bit outside those set (bits 5-15 are not decoded: TOU_FLAGS_UNDECODED_BITS). The
                    literal text `None` is an explicit "no source", never an unknown value.
  effectively GRID  GRID, and `tou.enabled` and `tou.grid_charge_enabled` fresh and true, and `tou.overlay_state` fresh
                    and NONE (no Free Power, Dump to Grid or manual write overriding the table).
  the window        the single maximal run of ring-adjacent, effectively GRID slots, at its next occurrence that ends
                    after `now`; a run that crosses local midnight or lasts the whole day is refused.

Every refusal is a BLOCK with a named code (TOU_* and CHARGE_WINDOW_*); no charging period is ever invented, no single-slot
fallback exists and the SiteConfig example window is never used. A configured grid source is necessary for grid charging,
never proof that it happens: what the advice may claim about it is decided by the SHADOW cycle (section 13.6).

Pure: no clock read (every time is an argument), no file or network access, never raises for any input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Mapping

from .advisory_contract import (TOU_CHARGE_SOURCE_BITS, TOU_MODE_BITS, TOU_OVERLAY_STATES, TOU_SLOT_ROW_KEYS,
                                TOU_SLOT_TABLE_ROWS)
from .explain import finite_number
from .site_decisions import BLOCK, CHARGE_WINDOW_KEY, WARN, Finding, InputState, finding
from .timeutil import local_date, local_wall

TOU_TABLE_VERSION = "intel-tou-table-0.1.0"

GRID, NOT_GRID, UNKNOWN = "GRID", "NOT_GRID", "UNKNOWN"
# exact dongle texts only (firmware decode of flags bits 0-1); anything else is UNKNOWN
CHARGE_SOURCE_CLASS: Mapping[str, str] = MappingProxyType({
    "None": NOT_GRID, "Grid": GRID, "Generator": NOT_GRID, "Grid + Generator": GRID})
SOURCE_MASK = 0x03
MODE_MASK = 0x1C
DECODED_FLAGS_MASK = SOURCE_MASK | MODE_MASK     # 0x1F: bits 5-15 of a slot flags word are not decoded (UNKNOWN when set)
FLAGS_MAX = 0xFFFF
TOU_OVERLAY_NONE = "NONE"
TOU_OVERLAY_ACTIVE = "ACTIVE"

TOU_TABLE_KEY = "tou.slot_table"
TOU_ENABLED_KEY = "tou.enabled"
TOU_GRID_CHARGE_ENABLED_KEY = "tou.grid_charge_enabled"
TOU_OVERLAY_KEY = "tou.overlay_state"
# the readings a TOU charge window rests on: its validity is bounded by each one's remaining freshness
TOU_INPUT_KEYS = (TOU_TABLE_KEY, TOU_ENABLED_KEY, TOU_GRID_CHARGE_ENABLED_KEY, TOU_OVERLAY_KEY)

_DAY_MIN = 1440

# fixed, value-free texts (they are published as blocker texts)
_TEXTS = MappingProxyType({
    "TOU_TABLE_NOT_FRESH": "the TOU slot table is missing, stale or has no defined freshness limit",
    "TOU_TABLE_LEGACY_SCHEMA": "the TOU slot table has the old start and target only shape; the charge source of each slot "
                               "is needed, so no grid-charge window is read from it",
    "TOU_TABLE_MALFORMED": "the TOU slot table is not the expected six-slot shape (a key, a slot number, a type or a range "
                           "is wrong); no grid-charge window is read from it",
    "TOU_RING_INVALID": "the TOU slot times do not form one daily ring (a slot count, a missing or invalid time, an end "
                        "that is not the next start, an empty slot or more than one wrap past midnight)",
    "TOU_SLOT_SOURCE_UNKNOWN": "a TOU slot's charge source or mode is unknown; an unknown slot could be a second grid-charge "
                               "window, so no window is read",
    "TOU_SOURCE_DECODE_CONFLICT": "a TOU slot's flags word disagrees with its charge source or mode text",
    "TOU_FLAGS_UNDECODED_BITS": "a TOU slot's flags word has a bit set outside the decoded charge source and mode bits; "
                                "what it means is unknown, so the slot is unknown",
    "TOU_SLOT_TARGET_UNKNOWN": "a TOU slot's target state of charge is unknown",
    "TOU_SLOT_POWER_UNKNOWN": "a TOU slot's power is unknown",
    "TOU_ENABLE_UNKNOWN": "the inverter's time-of-use enable is missing, stale or not a yes / no value",
    "TOU_DISABLED": "the inverter's time-of-use schedule is disabled, so no slot is in effect",
    "TOU_GRID_CHARGE_ENABLE_UNKNOWN": "the inverter's grid-charge enable is missing, stale or not a yes / no value",
    "TOU_GRID_CHARGE_DISABLED": "the inverter's grid charging is disabled, so no slot charges from the grid",
    "TOU_OVERLAY_STATE_UNKNOWN": "whether Free Power, Dump to Grid or a manual write is overriding the TOU table is unknown",
    "TOU_OVERLAY_ACTIVE": "Free Power, Dump to Grid or a manual write is overriding the TOU table, so it is not the "
                          "standing schedule",
    "TOU_NO_GRID_SLOT": "no TOU slot is configured to charge from the grid",
    "TOU_MULTIPLE_GRID_WINDOWS": "the TOU slots that charge from the grid form more than one separate window",
    "TOU_SLOT_POWER_ZERO": "a TOU slot of the grid-charge window has zero power, so it cannot charge",
    "CHARGE_WINDOW_CROSSES_MIDNIGHT": "the TOU grid-charge window crosses local midnight and cannot be used as a one-date "
                                      "window",
    "CHARGE_WINDOW_NOT_REPRESENTABLE": "the TOU grid-charge window lasts the whole day or has no usable local occurrence, "
                                       "so it leaves no period for a charge target to carry",
})


def _f(code: str, severity: str = BLOCK, **evidence: object) -> Finding:
    return finding(code, severity, CHARGE_WINDOW_KEY, _TEXTS[code], **evidence)


# ---------------------------------------------------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """One parsed TOU row: local minutes [start_min, end_min) (end_min > start_min; above 1440 for the slot that wraps
    past midnight), its fields as given (None = unknown) and its class."""
    slot: int
    start_min: int
    end_min: int
    target_soc_pct: float | None
    charge_source: str | None
    flags_raw: int | None
    mode: str | None
    power_w: float | None
    cls: str
    decode_conflict: bool = False


@dataclass(frozen=True)
class GridRun:
    """The single run of effectively GRID slots: local minutes [start_min, end_min) (end_min > 1440 when it crosses
    midnight) and its slots in ring order."""
    start_min: int
    end_min: int
    slots: tuple[Slot, ...]

    @property
    def min_power_w(self) -> float | None:
        """The lowest slot power of the run (the grid-charge power cap); None when any is unknown."""
        ps = [s.power_w for s in self.slots]
        return None if not ps or any(p is None for p in ps) else float(min(ps))

    @property
    def single_target_pct(self) -> float | None:
        """The one target SOC every slot of the run shares, or None when they differ or one is unknown."""
        ts = {s.target_soc_pct for s in self.slots}
        return float(next(iter(ts))) if len(ts) == 1 and None not in ts else None


def _hhmm(v: object) -> int | None:
    """'HH:MM' (00:00..23:59, as the dongle shows a slot time) -> minutes after local midnight; anything else None."""
    if not (isinstance(v, str) and len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit()):
        return None
    h, m = int(v[:2]), int(v[3:])
    return h * 60 + m if h < 24 and m < 60 else None


def _int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def undecoded_flag_bits(flags_raw: object) -> bool:
    """True when a flags word (an int) has any bit outside DECODED_FLAGS_MASK set: bits whose meaning is unknown."""
    return _int(flags_raw) and bool(flags_raw & ~DECODED_FLAGS_MASK)


def slot_class(charge_source: object, mode: object, flags_raw: object) -> tuple[str, bool]:
    """(class, decode conflict) of one slot from its exact texts and flags word. A flags word with an undecoded bit
    set (undecoded_flag_bits) is UNKNOWN too, without the conflict flag (TOU_FLAGS_UNDECODED_BITS names it)."""
    if not isinstance(charge_source, str) or charge_source not in CHARGE_SOURCE_CLASS:
        return UNKNOWN, False
    if not isinstance(mode, str) or mode not in TOU_MODE_BITS or not _int(flags_raw):
        return UNKNOWN, False
    if (flags_raw & SOURCE_MASK) != TOU_CHARGE_SOURCE_BITS[charge_source] or (flags_raw & MODE_MASK) != TOU_MODE_BITS[mode]:
        return UNKNOWN, True
    if undecoded_flag_bits(flags_raw):
        return UNKNOWN, False
    return CHARGE_SOURCE_CLASS[charge_source], False


def _row_malformed(i: int, row: Mapping) -> bool:
    if set(row) != set(TOU_SLOT_ROW_KEYS):
        return True
    if not _int(row["slot"]) or row["slot"] != i + 1:
        return True
    t, p, fl = row["target_soc_pct"], row["power_w"], row["flags_raw"]
    if t is not None and not (finite_number(t) and 0.0 <= float(t) <= 100.0):
        return True
    if p is not None and not (finite_number(p) and float(p) >= 0.0):
        return True
    if fl is not None and not (_int(fl) and 0 <= fl <= FLAGS_MAX):
        return True
    return any(row[k] is not None and not isinstance(row[k], str) for k in ("charge_source", "mode"))


def parse_table(value: object) -> tuple[tuple[Slot, ...] | None, list[Finding]]:
    """The six slots of a schema v2 table, or None with the BLOCK that refuses it (TOU_TABLE_MALFORMED,
    TOU_TABLE_LEGACY_SCHEMA or TOU_RING_INVALID). Classes are judged here; the enables and the overlay are not."""
    if not isinstance(value, (list, tuple)) or not value or not all(isinstance(r, Mapping) for r in value):
        return None, [_f("TOU_TABLE_MALFORMED")]
    rows = list(value)
    with_source = sum(1 for r in rows if "charge_source" in r)
    if with_source == 0:
        return None, [_f("TOU_TABLE_LEGACY_SCHEMA", rows=len(rows))]
    if len(rows) != TOU_SLOT_TABLE_ROWS:
        return None, [_f("TOU_RING_INVALID", rows=len(rows))]
    if any(_row_malformed(i, r) for i, r in enumerate(rows)):
        return None, [_f("TOU_TABLE_MALFORMED")]
    starts = [_hhmm(r["start"]) for r in rows]
    ends = [_hhmm(r["end"]) for r in rows]
    n = len(rows)
    if any(x is None for x in starts + ends):
        return None, [_f("TOU_RING_INVALID", reason="time")]
    if any(ends[i] != starts[(i + 1) % n] for i in range(n)):
        return None, [_f("TOU_RING_INVALID", reason="end_not_next_start")]
    if any(starts[i] == starts[(i + 1) % n] for i in range(n)):
        return None, [_f("TOU_RING_INVALID", reason="zero_length")]
    wraps = sum(1 for i in range(n) if starts[(i + 1) % n] < starts[i])
    if wraps != 1:
        return None, [_f("TOU_RING_INVALID", reason="wraps", wraps=wraps)]
    out = []
    for i, r in enumerate(rows):
        a, b = starts[i], starts[(i + 1) % n]
        cls, conflict = slot_class(r["charge_source"], r["mode"], r["flags_raw"])
        out.append(Slot(i + 1, a, b if b > a else b + _DAY_MIN,
                        None if r["target_soc_pct"] is None else float(r["target_soc_pct"]), r["charge_source"],
                        r["flags_raw"], r["mode"], None if r["power_w"] is None else float(r["power_w"]), cls, conflict))
    return tuple(out), []


# ---------------------------------------------------------------------------------------------------------------------
# the enables and the overlay
# ---------------------------------------------------------------------------------------------------------------------

def _usable(st: object, key: str) -> bool:
    return isinstance(st, InputState) and st.key == key and st.fresh is True and st.limit_s is not None


def bool_setting(st: object, key: str) -> bool | None:
    """A fresh yes / no reading's value, or None when it is missing, stale, of unresolved age or not a bool."""
    return st.value if _usable(st, key) and isinstance(st.value, bool) else None


def overlay_setting(st: object) -> str | None:
    """NONE / ACTIVE from a fresh overlay reading, or None when missing, stale or not one of TOU_OVERLAY_STATES."""
    if not _usable(st, TOU_OVERLAY_KEY) or not isinstance(st.value, str) or st.value not in TOU_OVERLAY_STATES:
        return None
    return st.value


# ---------------------------------------------------------------------------------------------------------------------
# the classification and the window
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Classification:
    """The judged table: its slots (None when refused), the single grid-charge run (None when refused) and why."""
    slots: tuple[Slot, ...] | None
    run: GridRun | None
    findings: tuple[Finding, ...]


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """(first index, length) of every maximal cyclic run of True in `flags` (the ring); one (0, n) run when all are True."""
    n = len(flags)
    if all(flags):
        return [(0, n)]
    out = []
    for i in range(n):
        if flags[i] and not flags[i - 1]:
            k = 0
            while flags[(i + k) % n] and k < n:
                k += 1
            out.append((i, k))
    return out


def classify(table: InputState | None, enabled: InputState | None, grid_enabled: InputState | None,
             overlay: InputState | None) -> Classification:
    """Judge the fresh table, the two enables and the overlay state together (section 13.5). Never raises."""
    if not _usable(table, TOU_TABLE_KEY):
        return Classification(None, None, (_f("TOU_TABLE_NOT_FRESH", WARN),))
    slots, notes = parse_table(table.value)
    if slots is None:
        return Classification(None, None, tuple(notes))
    out: list[Finding] = []
    unknown = [s.slot for s in slots if s.cls == UNKNOWN]
    if unknown:
        out.append(_f("TOU_SLOT_SOURCE_UNKNOWN", slots=unknown))
        conflict = [s.slot for s in slots if s.decode_conflict]
        if conflict:
            out.append(_f("TOU_SOURCE_DECODE_CONFLICT", slots=conflict))
        undecoded = [s.slot for s in slots if undecoded_flag_bits(s.flags_raw)]
        if undecoded:
            out.append(_f("TOU_FLAGS_UNDECODED_BITS", slots=undecoded))
    if any(s.target_soc_pct is None for s in slots):
        out.append(_f("TOU_SLOT_TARGET_UNKNOWN", slots=[s.slot for s in slots if s.target_soc_pct is None]))
    if any(s.power_w is None for s in slots):
        out.append(_f("TOU_SLOT_POWER_UNKNOWN", slots=[s.slot for s in slots if s.power_w is None]))
    en = bool_setting(enabled, TOU_ENABLED_KEY)
    if en is None:
        out.append(_f("TOU_ENABLE_UNKNOWN"))
    elif en is False:
        out.append(_f("TOU_DISABLED"))
    gen = bool_setting(grid_enabled, TOU_GRID_CHARGE_ENABLED_KEY)
    if gen is None:
        out.append(_f("TOU_GRID_CHARGE_ENABLE_UNKNOWN"))
    elif gen is False:
        out.append(_f("TOU_GRID_CHARGE_DISABLED"))
    ov = overlay_setting(overlay)
    if ov is None:
        out.append(_f("TOU_OVERLAY_STATE_UNKNOWN"))
    elif ov != TOU_OVERLAY_NONE:
        out.append(_f("TOU_OVERLAY_ACTIVE"))
    if out:
        return Classification(slots, None, tuple(out))
    runs = _runs([s.cls == GRID for s in slots])
    if not runs:
        return Classification(slots, None, (_f("TOU_NO_GRID_SLOT"),))
    if len(runs) > 1:
        return Classification(slots, None, (_f("TOU_MULTIPLE_GRID_WINDOWS", runs=len(runs)),))
    i0, length = runs[0]
    members = tuple(slots[(i0 + k) % len(slots)] for k in range(length))
    start = members[0].start_min
    end = start + sum(s.end_min - s.start_min for s in members)
    if end - start >= _DAY_MIN:
        return Classification(slots, None, (_f("CHARGE_WINDOW_NOT_REPRESENTABLE", reason="whole_day"),))
    if end > _DAY_MIN:
        return Classification(slots, None, (_f("CHARGE_WINDOW_CROSSES_MIDNIGHT"),))
    run = GridRun(start, end, members)
    if any(s.power_w == 0.0 for s in members):
        return Classification(slots, None, (_f("TOU_SLOT_POWER_ZERO"),))
    return Classification(slots, run, ())


@dataclass(frozen=True)
class TouWindow:
    """The next (or current) occurrence of the grid-charge run: aware UTC endpoints, its local minutes, the run and the
    judged state of everything it rests on (fresh only when all of TOU_INPUT_KEYS are; the largest age, the smallest
    limit)."""
    start: datetime
    end: datetime
    local_minutes: tuple[int, int]
    run: GridRun
    fresh: bool
    age_s: float | None
    limit_s: float | None


def _combined(states: list[InputState]) -> tuple[bool, float | None, float | None]:
    ages = [s.age_s for s in states]
    lims = [s.limit_s for s in states]
    return (all(s.fresh for s in states), None if any(a is None for a in ages) else float(max(ages)),
            None if any(x is None for x in lims) else float(min(lims)))


def grid_window(table: InputState | None, enabled: InputState | None, grid_enabled: InputState | None,
                overlay: InputState | None, now: datetime, tz) -> tuple[TouWindow | None, list[Finding], Classification]:
    """The TOU grid-charge window at its next occurrence that ends after `now`, or None with the reasons (every refusal a
    BLOCK, except TOU_TABLE_NOT_FRESH, which the caller turns into CHARGE_WINDOW_UNKNOWN). Never raises."""
    try:
        c = classify(table, enabled, grid_enabled, overlay)
        if c.run is None:
            return None, list(c.findings), c
        a, b = c.run.start_min, c.run.end_min
        today = local_date(now, tz)
        for day in (today, today + timedelta(days=1)):
            s, e = local_wall(day, a, tz), local_wall(day, b, tz)
            if e > now and e > s:
                fresh, age, lim = _combined([table, enabled, grid_enabled, overlay])
                return TouWindow(s, e, (a, b), c.run, fresh, age, lim), [], c
        return None, [_f("CHARGE_WINDOW_NOT_REPRESENTABLE", reason="no_occurrence")], c
    except Exception as exc:  # noqa: BLE001 - fail closed: an unexpected value is a refused table, never an exception
        return None, [_f("TOU_TABLE_MALFORMED", error=type(exc).__name__)], Classification(None, None, ())
