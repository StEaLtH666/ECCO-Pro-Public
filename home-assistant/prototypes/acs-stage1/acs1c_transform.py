"""Advanced Configuration Stage 1, cyclic TOU correction (post-export entry acs1c): how the installed package's start-time ordering rule
was changed from "the six starts are strictly ascending" to "the six starts are one 24-hour cycle in slot order", as an exact, INVERTIBLE
transformation layered on the Stage 1 text.

WHY. The inverter's six TOU slots are circular: slot N runs from its own start to slot N+1's start, and slot 6 runs into slot 1 the next
day. A layout such as the owner's (starts 00:30, 05:30, 12:00, 16:35, 22:00, 00:25 by slot number: slot 5 runs 22:00 -> 00:25 past
midnight, slot 6 runs 00:25 -> 00:30) is a valid 24-hour schedule, but the Stage 1 gate demanded tt[0] < tt[1] < ... < tt[5] on the
HH:MM values and set naive neighbour bounds, so every start-time Review of that layout was refused ("not strictly ascending"). This layer
models the six starts as a circular sequence: comparisons use day-offset ("unwrapped") minutes counted from the previous slot's start;
the value written to the inverter is still the HH:MM the owner typed, on the 5-minute grid, 00:00-23:55 (never 24:25 or any > 23:55 form).

THE RULES THIS LAYER INSTALLS (the start_time setting only; every other setting and every other guard is untouched):
  cyc   the LIVE layout is one valid cycle: every one of the six starts reads as HH:MM on the 5-minute grid, every slot lasts at least
        5 minutes (the gap from each start to the next slot's start, taken modulo 24 h, is >= 5), and the six gaps add up to exactly
        1440 minutes (so the slots go round the clock exactly once: exactly one wrap past midnight, no overlap, no gap). A layout that is
        not one cycle (two equal starts, a slot order that goes round twice, an off-grid or unreadable start) refuses the edit as an
        "unexpected TOU layout", as before.
  order the NEW start stays strictly inside the window between the previous slot's start and the next slot's start, counted round the
        clock (0 < (new - prev) mod 1440 < (next - prev) mod 1440): slot 6 precedes slot 1 and slot 1 follows slot 6, so slots 1, 5 and 6
        are edited like any other. The slot keeps its identity and its neighbours; no slot can become zero or negative, change owner,
        overlap, leave a gap or cross another slot's boundary.
  cyc2  the PROPOSED layout (the live one with the edited start replaced) is itself one valid cycle. Given `cyc` and `order` this is
        implied (the two gaps around the moved boundary still add up to the old window), and the Stage 1 suite proves the equivalence;
        it is kept as an independent, defence-in-depth check of the whole proposed schedule.
  mid   the "active slot right now" guard (the local time lies between the old and the new boundary, so the edit would change which
        slot is active now) is evaluated in the same unwrapped minutes, so a window that crosses midnight is judged correctly (the
        Stage 1 form compared HH:MM minutes on a line and would have taken the complement of such a window).
  Kept exactly: the 15-minute distance from the old and the new boundary (already circular), the inverter-clock rule, the 5-minute grid
  of the typed value, the clock-change-night refusal, every fail-closed dongle / fallback / Free Power / Dump / RTC / supervision gate,
  the fresh evidence, the staged == live proof, the quiet-window single press, the readback and the UNCERTAIN lock.

WHAT THIS IS. render_cyclic() takes the Stage 1 package text (render_stage1(<Stage 0 text>) of acs_stage1_transform.py, sha256 pinned
here as STAGE1_BASE_SHA256 and there as STAGE1_SHA256) and applies an ordered list of EXACT (before, after, expected_count) text
replacements (CYCLIC_PAIRS), the technique of acs_stage1_transform.py and of the repository's proof-chain scope modules: each `before`
must be present exactly the declared number of times, otherwise ValueError names the pair. The result is the installed package
(sha256 STAGE1C_SHA256). unrender_cyclic() applies the pairs in reverse order as (after -> before) with the same exact counts and gives
the Stage 1 text back: it is the file a rollback of this correction restores (the package installed on 2026-10-25). The acs1 transform,
its three pins and its chain entry are unchanged: the installed package is render_cyclic(render_stage1(<Stage 0 text>)) and
unrender_stage1(unrender_cyclic(<installed>)) is the Stage 0 text.

WHAT IT TOUCHES. Only: the four copies of the gate (the Review, the Apply's gate, its fresh-read re-check and its last check before the
press: the `asc` / `lb` / `hb` lines, the `mid` line, the two start-time ordering refusals and the typed value's form check), the package
header's description of the rule, the Review notification's start-time sentence (it now names the two slot windows that result) and, for
that sentence, a `live_t_prev` entry in the per-slot entity map (the previous slot's live start sensor). No pair anchors on, spells or
rewrites a line that carries a reserved fallback / failback token, and this module spells none. No firmware byte, no new register, no new
write path, no new service call. "The installed package" below means the package file at the install path after this correction is
installed; until then the live install is the Stage 1 site render of 2026-10-25 and this text is the candidate.

WHAT IT DOES NOT DO. No I/O (no file, no network, no Home Assistant, no hardware). It does not change what is written: a start-time Apply
still stages the one HH:MM value and drives the existing firmware path (Load -> write enable -> Apply slot N), which writes the slot's
start register and its end register (the next slot's start, register 250 for slot 6) with their staged values and verifies by readback.
"""

from __future__ import annotations

import hashlib
import json

PACKAGE_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
# sha256 (LF text) of the Stage 1 package the pairs apply to: acs_stage1_transform.STAGE1_SHA256, the package installed on 2026-10-25.
STAGE1_BASE_SHA256 = "2e8813973d133b7bd25fe273af16403af4cea0b8e64b338a015f35412346e9de"
# sha256 (LF text) of the installed, corrected package: render_cyclic(<the Stage 1 text>).
STAGE1C_SHA256 = "4ee898311a6abe7a7b0bc1874bff2cd10027d14f4122b341f5145833e3d90405"
# sha256 of the canonical serialisation of CYCLIC_PAIRS (cyclic_pairs_sha256()): a silent edit of any pair changes it.
CYCLIC_PAIRS_SHA256 = "6cb46976e90d4c7a7e24206d562ee532e4b4246c3595100e10de514075f4d761"

GRID_MINUTES = 5          # the TOU time grid (the firmware's valid_hhmm: minutes % 5 == 0)
DAY_MINUTES = 1440        # the cycle length
MIN_SLOT_MINUTES = 5      # every slot lasts at least one grid step (the firmware refuses start == end)
GATE_COPIES = ((12, 2), (16, 1), (24, 1))   # the four copies of the gate: Review and Apply (12 spaces), fresh read (16), last check (24)


def _ind(tmpl: str, spaces: int) -> str:
    """Fill the @I@ placeholders of a multi-line template with `spaces` spaces (the indent of the copy being edited)."""
    return tmpl.replace("@I@", " " * spaces)


# ---- the gate: ordering model ------------------------------------------------------------------------------------------------------
# Stage 1: a strictly ascending line of HH:MM minutes and naive neighbour bounds (-1 below slot 1, 1440 above slot 6).
GATE_HEAD_BEFORE = (
    "@I@{% set asc = tt[0] >= 0 and tt[0] < tt[1] and tt[1] < tt[2] and tt[2] < tt[3] and tt[3] < tt[4] and tt[4] < tt[5] and tt[5] < 1440 %}\n"
    "@I@{% set lb = (tt[n - 2] if n > 1 else -1) if e else 0 %}\n"
    "@I@{% set hb = (tt[n] if n < 6 else 1440) if e else 0 %}")
# acs1c: one 24-hour cycle in slot order. g.s is the sum of the six forward gaps (each modulo 24 h); g.ok needs every start readable, on
# the 5-minute grid, and every gap at least 5 minutes. pv / nx are the previous and the next slot's starts (slot 6 before slot 1, slot 1
# after slot 6); arc is the window between them and uw the new start, both counted from pv round the clock.
GATE_HEAD_AFTER = (
    "@I@{% set g = namespace(s=0, ok=true) %}{% for k in range(6) %}{% set d = (tt[(k + 1) % 6] - tt[k]) % 1440 %}"
    "{% set g.ok = g.ok and tt[k] >= 0 and tt[k] % 5 == 0 and d >= 5 %}{% set g.s = g.s + d %}{% endfor %}\n"
    "@I@{% set cyc = g.ok and g.s == 1440 %}\n"
    "@I@{% set pv = tt[(n + 4) % 6] if e else -1 %}\n"
    "@I@{% set nx = tt[n % 6] if e else -1 %}\n"
    "@I@{% set arc = ((nx - pv) % 1440) if (pv >= 0 and nx >= 0) else 0 %}\n"
    "@I@{% set uw = ((wmin - pv) % 1440) if (pv >= 0 and wmin >= 0) else -1 %}")

# Stage 1: the active-slot-now guard on a line of HH:MM minutes (wrong for a window that crosses midnight). A one-line anchor carries
# the newline before it: a deeper-indented copy of the same line contains the shallower-indented text, the line start does not.
GATE_MID_BEFORE = (
    "\n@I@{% set mid = setting == 'start_time' and bo >= 0 and wmin >= 0 and (((cm - (bo if wmin > bo else wmin)) % 1440) < ((wmin - bo) | abs)) %}")
# acs1c: the old boundary (ub), the local time (uc) and the new boundary (uw) counted from the previous slot's start; the edit changes
# the owner of every minute between the old and the new boundary. h is the PROPOSED layout's cycle test (cyc2), the live starts with
# slot n's replaced by the new value.
GATE_MID_AFTER = (
    "\n@I@{% set ub = ((bo - pv) % 1440) if (pv >= 0 and bo >= 0) else -1 %}\n"
    "@I@{% set uc = ((cm - pv) % 1440) if pv >= 0 else -1 %}\n"
    "@I@{% set mid = setting == 'start_time' and ub >= 0 and uw >= 0 and uc >= 0 and ([ub, uw] | min) <= uc and uc < ([ub, uw] | max) %}\n"
    "@I@{% set h = namespace(s=0, ok=true) %}{% for k in range(6) %}{% set a = wmin if k == n - 1 else tt[k] %}"
    "{% set b = wmin if (k + 1) % 6 == n - 1 else tt[(k + 1) % 6] %}{% set d = (b - a) % 1440 %}"
    "{% set h.ok = h.ok and a >= 0 and d >= 5 %}{% set h.s = h.s + d %}{% endfor %}\n"
    "@I@{% set cyc2 = h.ok and h.s == 1440 %}")

GATE_VALID_BEFORE = (
    "@I@{% elif setting == 'start_time' and not asc %}the six live slot start times are not strictly ascending (unexpected TOU layout)\n"
    "@I@{% elif setting == 'start_time' and not (lb < wmin and wmin < hb) %}the new start time must stay strictly after the previous slot's start and strictly before the next one")
# The refusal texts are stored as "REVIEW REFUSED - <text>; nothing written" in an input_text of 255 characters: each stays well under
# 221 characters (checked by the Stage 1 suite).
REFUSE_CYC = ("the six live slot start times are not one valid 24-hour cycle in slot order (5-minute grid, every slot at least 5 minutes, "
              "exactly one wrap past midnight): unexpected TOU layout")
REFUSE_ORDER = ("the new start time must stay strictly after the previous slot's start and strictly before the next slot's start, counted round "
                "the clock (slot 6 is followed by slot 1)")
REFUSE_CYC2 = "the edit would not leave one valid 24-hour cycle in slot order (every slot at least 5 minutes, exactly one wrap past midnight)"
GATE_VALID_AFTER = (
    "@I@{% elif setting == 'start_time' and not cyc %}" + REFUSE_CYC + "\n"
    "@I@{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}" + REFUSE_ORDER + "\n"
    "@I@{% elif setting == 'start_time' and not cyc2 %}" + REFUSE_CYC2)

# The typed value's form. The Review parses `value` into the HHMM integer `want` (HH <= 23, MM <= 59, MM % 5 == 0, else -1); the Apply
# takes `want` from the review record (an input_text) and the Stage 1 gate re-checked only `want < 0`. acs1 refused a hand-edited record
# value such as 2400 incidentally (its linear bound `wmin < hb` with hb <= 1440); the cyclic window counts modulo 24 h and would not, so
# every copy of the gate now re-checks the form itself (review finding, 2026-10-25): no record value that is not a well-formed HH:MM on
# the grid, 00:00-23:55, passes any copy of the gate, whatever wrote it. The staging number's 0..2359 range, the firmware's valid_hhmm and
# the pre-press staged == want check already stopped such a value from being written; this closes the gate as well.
GATE_WANT_BEFORE = "@I@{% elif setting == 'start_time' and want < 0 %}start time must be HH:MM on the 5-minute grid, 00:00-23:55"
GATE_WANT_AFTER = ("@I@{% elif setting == 'start_time' and (want < 0 or want >= 2400 or want % 100 >= 60 or want % 5 != 0) %}"
                   "start time must be HH:MM on the 5-minute grid, 00:00-23:55")

# ---- the header, the Review notification and the per-slot map -----------------------------------------------------------------------
HDR_RULE_BEFORE = (
    "#                  end. The six starts (each in the firmware's HH:MM form) must be strictly ascending before and after; the edit is\n")
HDR_RULE_AFTER = (
    "#                  end. The six starts (each in the firmware's HH:MM form) form one 24-hour cycle in slot order, slot 6 running into\n"
    "#                  slot 1 (exactly one wrap past midnight, every slot at least 5 minutes; acs1c) before and after; the edit is\n")

HDR_GEN_BEFORE = (
    "# can never be installed together (they declare the same helpers, the same acknowledge script and the same watchdog automation).\n")
HDR_GEN_AFTER = (HDR_GEN_BEFORE
    + "# acs1c (2026-10-25): home-assistant/prototypes/acs-stage1/acs1c_transform.py then rewrites the start-time ordering rule of that text\n"
    "# as one 24-hour cycle in slot order (the same technique, its own pins): the installed text is render_cyclic(render_stage1(Stage 0)).\n")

REVIEW_RULE_BEFORE = "The six start times must stay strictly ascending. "
REVIEW_RULE_AFTER = ("Slot {{ n }} will then run {{ wdisp }}-{{ states(e.live_t_next) }} and slot {{ 6 if n == 1 else n - 1 }} "
                     "{{ states(e.live_t_prev) }}-{{ wdisp }} (the six starts stay one 24-hour cycle in slot order; slot 6 runs into slot 1). ")


def _map_pairs() -> "list[tuple[str, str, int]]":
    """The per-slot entity map (Review and Apply copies) gains `live_t_prev`, the previous slot's live start sensor (slot 6's for slot 1)."""
    p = []
    for slot in range(1, 7):
        prev = 6 if slot == 1 else slot - 1
        before = ("'p_load': 'button.ecco_clock_dongle_load_current_slot_%d_to_manual_staging', "
                  "'p_en': 'number.ecco_clock_dongle_manual_slot_%d_end_hhmm'}" % (prev, prev))
        after = before[:-1] + ",\n" + " " * 16 + "'live_t_prev': 'sensor.ecco_clock_dongle_ecco_timezone%d_time'}" % prev
        p.append((before, after, 2))
    return p


def _pairs() -> "list[tuple[str, str, int]]":
    p: list[tuple[str, str, int]] = []
    p.append((HDR_RULE_BEFORE, HDR_RULE_AFTER, 1))
    p.append((HDR_GEN_BEFORE, HDR_GEN_AFTER, 1))
    for ind, count in GATE_COPIES:
        p.append((_ind(GATE_HEAD_BEFORE, ind), _ind(GATE_HEAD_AFTER, ind), count))
        p.append((_ind(GATE_MID_BEFORE, ind), _ind(GATE_MID_AFTER, ind), count))
        p.append((_ind(GATE_VALID_BEFORE, ind), _ind(GATE_VALID_AFTER, ind), count))
        p.append(("\n" + _ind(GATE_WANT_BEFORE, ind), "\n" + _ind(GATE_WANT_AFTER, ind), count))   # one line: anchored with its line start
    p.append((REVIEW_RULE_BEFORE, REVIEW_RULE_AFTER, 1))
    p.extend(_map_pairs())
    return p


CYCLIC_PAIRS: "list[tuple[str, str, int]]" = _pairs()


def render_cyclic(stage1_text: str) -> str:
    """Apply CYCLIC_PAIRS, in order, to the Stage 1 package text. Raises ValueError naming the pair if any `before` is present a different
    number of times than declared (so a changed Stage 1 text can never be silently half-transformed). Line ends are normalised to LF."""
    text = stage1_text.replace("\r\n", "\n")
    for i, (before, after, count) in enumerate(CYCLIC_PAIRS):
        found = text.count(before)
        if found != count:
            raise ValueError(f"acs1c pair {i}: expected {count} occurrence(s) of {before[:90]!r}, found {found}")
        text = text.replace(before, after)
    return text


def unrender_cyclic(installed_text: str) -> str:
    """The inverse of render_cyclic: apply CYCLIC_PAIRS in REVERSE order as (after -> before), each with its declared count. Raises
    ValueError naming the pair on any mismatch (a package that is not exactly a rendered Stage 1 text can never be silently half-reversed).
    Line ends are normalised to LF. For the installed package the result is the Stage 1 text (sha256 STAGE1_BASE_SHA256), the file a
    rollback of this correction restores."""
    text = installed_text.replace("\r\n", "\n")
    for i in range(len(CYCLIC_PAIRS) - 1, -1, -1):
        before, after, count = CYCLIC_PAIRS[i]
        found = text.count(after)
        if found != count:
            raise ValueError(f"acs1c unrender pair {i}: expected {count} occurrence(s) of {after[:90]!r}, found {found}")
        text = text.replace(after, before)
    return text


def cyclic_pairs_sha256() -> str:
    """sha256 of the canonical serialisation of CYCLIC_PAIRS (JSON, ASCII-escaped, no whitespace): pinned as CYCLIC_PAIRS_SHA256."""
    blob = json.dumps([[b, a, c] for b, a, c in CYCLIC_PAIRS], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


# ---- a reference model of the start-time ordering rules (what the gate computes, in plain Python; used by the suites) ---------------
def gaps(starts: "list[int]") -> "list[int]":
    """The six forward gaps of a layout (minutes of the day, -1 = unreadable), each modulo 24 h."""
    return [(starts[(k + 1) % 6] - starts[k]) % DAY_MINUTES for k in range(6)]


def is_cycle(starts: "list[int]") -> bool:
    """`cyc`: every start readable and on the grid, every slot at least MIN_SLOT_MINUTES, the gaps adding up to exactly one day."""
    g = gaps(starts)
    return (all(t >= 0 and t % GRID_MINUTES == 0 for t in starts) and all(d >= MIN_SLOT_MINUTES for d in g)
            and sum(g) == DAY_MINUTES)


def verdict(starts: "list[int]", n: int, new: int, now_min: float) -> str:
    """The start-time ordering verdict of the gate for slot n (1-6) moved to `new` (minutes of the day, on the grid) at the local time
    `now_min` (minutes of the day, may be fractional), given the live starts (minutes, -1 = unreadable). Returns the FIRST applicable
    refusal name in the gate's order - 'unavailable', 'nochange', 'cycle', 'order', 'cycle2', 'near', 'mid' - or 'accept'. The other
    guards (the inverter clock, the clock-change night, the dongle and fallback gates) are outside this model. -1 stands for a live text
    the gate cannot parse at all ('unavailable', '?2475', ''): for the edited slot the gate then says 'live slot start time unavailable'.
    A text the gate's own-value parse still reads as a number but the strict HH:MM parse rejects ('24:00', '9:30', '12:30:00') is refused
    by the gate with the cycle rule's text instead; the model has no third value for it, so a caller passing -1 for such a text must accept
    'cycle' where the model says 'unavailable' (both refuse)."""
    cur = starts[n - 1]
    if cur < 0:
        return "unavailable"
    if cur == new:
        return "nochange"
    if not is_cycle(starts):
        return "cycle"
    pv, nx = starts[(n + 4) % 6], starts[n % 6]
    arc = (nx - pv) % DAY_MINUTES
    uw = (new - pv) % DAY_MINUTES
    if not (0 < uw < arc):
        return "order"
    proposed = list(starts)
    proposed[n - 1] = new
    if not is_cycle(proposed):
        return "cycle2"
    if min((now_min - cur) % DAY_MINUTES, (cur - now_min) % DAY_MINUTES) <= 15 \
            or min((now_min - new) % DAY_MINUTES, (new - now_min) % DAY_MINUTES) <= 15:
        return "near"
    ub, uc = (cur - pv) % DAY_MINUTES, (now_min - pv) % DAY_MINUTES
    if min(ub, uw) <= uc < max(ub, uw):
        return "mid"
    return "accept"
