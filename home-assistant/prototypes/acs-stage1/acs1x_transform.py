"""Advanced Configuration Stage 1, midnight-crossing hold (post-export entry acs1x): a fail-closed, script-level refusal of any start-time
edit that would move the midnight crossing to a different slot boundary, as an exact, INVERTIBLE transformation layered on the acs1c text.

WHY. acs1c made the start-time ordering rule cyclic (one 24-hour cycle in slot order), so every slot of the owner's layout (starts 00:30,
05:30, 12:00, 16:35, 22:00, 00:25 by slot number: slot 5 runs 22:00 -> 00:25 past midnight) became start-time editable through the Review /
Apply scripts. A single edit can then also move the midnight crossing to another slot (slot 6 00:25 -> 23:55 makes slot 6 the slot that
runs into the next day; slot 5 22:00 -> 00:05 makes slot 4 run past midnight). The only crossing position evidenced on the inverter is the
owner's (slot 5 into slot 6); the scheduler's behaviour with the crossing elsewhere has not been observed. The owner restricted such moves
(policy P3c, restriction R1, 2026-10-27) until a separately authorised, supervised hardware test proves the behaviour, and directed that
the restriction be enforced by the scripts themselves, fail closed, not only by the dashboard or by operating instructions. The dashboard
keeps start times display-only; this layer is the backend half.

THE RULE THIS LAYER INSTALLS (the start_time setting only; every other setting and every other guard is untouched):
  xw    In a layout that passes acs1c's `cyc` (six starts on the 5-minute grid, every forward gap >= 5 minutes, the six gaps modulo 24 h
        adding up to exactly 1440), exactly one index k in 0..5 has tt[(k + 1) % 6] < tt[k] in raw HH:MM minutes: that slot pair is the
        midnight crossing (slot k + 1 runs into slot k + 2 the next day; k = 4, slot 5 into slot 6, in the owner's layout). Proof: each gap
        is the raw difference plus 1440 exactly when the raw difference is negative, the raw differences of a cycle sum to 0, so the gaps
        sum to 1440 times the number of raw decreases. The gate counts the raw decreases of the LIVE layout `tt` and of the PROPOSED layout
        (the same list with slot n's start replaced by `wmin`, built exactly as `cyc2` builds it) and requires exactly one in each AND at
        the same index; otherwise it refuses with REFUSE_XW. It fails closed on anything unparsable: every live start and the new start
        must read as minutes (>= 0) and n must be a slot 1-6, else `xw` is false. The refusal sits right after the `cyc2` refusal in all
        four copies of the gate, before the 15-minute and active-slot guards.
  Equivalently: the slot that owns the last minute of the day (the slot with the latest start) must be the same slot before and after
  the edit. On the owner's layout this refuses moving slot 6's start before midnight (22:05 .. 23:55) and slot 5's start past midnight
  (00:00 .. 00:20), and still allows slot 6 00:25 -> 00:00 .. 00:20, slot 5 16:40 .. 23:55 and every slot 1-4 edit that `order` and
  `cyc2` allow (slots 1-4 never reach midnight there). A start at exactly 00:00 is after midnight (raw 0): slot 6 at 00:00 keeps the
  crossing at slot 5 -> 6 (slot 5 then ends at midnight); slot 5 at 00:00 moves it to slot 4 -> 5.
  The rule does not know where the crossing "should" be: it holds the crossing wherever the live layout has it. A layout whose crossing
  was moved by another tool (for example Manual Controls) can therefore not have it moved back through this editor while the hold
  stands; Manual Controls (the firmware path itself) is outside this package and unchanged.

WHAT THIS IS. render_crossing() takes the acs1c package text (render_cyclic(render_stage1(<Stage 0 text>)), sha256 pinned here as
STAGE1C_BASE_SHA256 and in acs1c_transform.py as STAGE1C_SHA256) and applies an ordered list of EXACT (before, after, expected_count) text
replacements (CROSSING_PAIRS), the technique of acs_stage1_transform.py and acs1c_transform.py: each `before` must be present exactly the
declared number of times, otherwise ValueError names the pair. The result is the installed package (sha256 STAGE1X_SHA256).
unrender_crossing() applies the pairs in reverse order as (after -> before) with the same exact counts and gives the acs1c text back: it
is the file a rollback of this layer restores. The acs1 and acs1c transforms, their pins and their chain entries are unchanged: the
installed package is render_crossing(render_cyclic(render_stage1(<Stage 0 text>))).

WHAT IT TOUCHES. Only: the four copies of the gate (the Review, the Apply's gate, its fresh-read re-check and its last check before the
press: one pair adds the `xc` / `xw` lines right before acs1c's proposed-layout test, one adds the refusal right after the `cyc2`
refusal) and the package header (the description of the rule and of the generation). Every pair anchors with its line start on lines that
carry no reserved fallback / failback token, and this module spells none. No firmware byte, no new register, no new write path, no new service call, no new entity.
"The installed package" below means the package file at the install path after this layer is installed; until then it is the candidate.

WHAT IT DOES NOT DO. No I/O (no file, no network, no Home Assistant, no hardware). It writes nothing and changes nothing that is written:
it only adds a refusal. It does not lift R1: a relocated-crossing edit needs the supervised proof, a separately reviewed change that
removes or relaxes this layer, and the owner's authorisation.
"""

from __future__ import annotations

import hashlib
import json

PACKAGE_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
# sha256 (LF text) of the acs1c package the pairs apply to: acs1c_transform.STAGE1C_SHA256 (public main e97ba36c, PR #45).
STAGE1C_BASE_SHA256 = "4ee898311a6abe7a7b0bc1874bff2cd10027d14f4122b341f5145833e3d90405"
# sha256 (LF text) of the installed package with the crossing hold: render_crossing(<the acs1c text>).
STAGE1X_SHA256 = "1d2b20a602b939fe9f4ef583c3ed0af52bceae28519d120b1d1476e075480010"
# sha256 of the canonical serialisation of CROSSING_PAIRS (crossing_pairs_sha256()): a silent edit of any pair changes it.
CROSSING_PAIRS_SHA256 = "48c7b2d28040a9afdf227dd944b723df849c3173f1758b5c9f99d702eba0ebac"

DAY_MINUTES = 1440
GATE_COPIES = ((12, 2), (16, 1), (24, 1))   # the four copies of the gate: Review and Apply (12 spaces), fresh read (16), last check (24)


def _ind(tmpl: str, spaces: int) -> str:
    """Fill the @I@ placeholders of a multi-line template with `spaces` spaces (the indent of the copy being edited)."""
    return tmpl.replace("@I@", " " * spaces)


# ---- the gate ----------------------------------------------------------------------------------------------------------------------
# A one-line anchor carries the newline before it: a deeper-indented copy of the same line contains the shallower-indented text, the line
# start does not. The two lines of the hold go right before acs1c's proposed-layout test (its `h` loop, then `cyc2`), whose list they
# build the same way. Inserted INSIDE acs1c's block of ordering lines, they break it, so unrender_cyclic refuses the installed text
# (unrender_crossing comes first; no half-reversed rollback file).
GATE_SET_BEFORE = "\n@I@{% set h = namespace(s=0, ok=true) %}"
# acs1x: xc.c / xc.i count and place the raw decreases of the live layout, xc.c2 / xc.i2 those of the proposed layout (a and b exactly as
# acs1c's `h` loop builds them for cyc2: slot n's start replaced by wmin); xc.ok needs every live start and the new start readable. xw: one
# decrease in each, at the same index, for a slot 1-6.
GATE_XW = (
    "\n@I@{% set xc = namespace(ok=true, c=0, i=-1, c2=0, i2=-1) %}{% for k in range(6) %}{% set a = wmin if k == n - 1 else tt[k] %}"
    "{% set b = wmin if (k + 1) % 6 == n - 1 else tt[(k + 1) % 6] %}{% set xc.ok = xc.ok and tt[k] >= 0 and a >= 0 %}"
    "{% set xc.i = k if tt[(k + 1) % 6] < tt[k] else xc.i %}{% set xc.c = xc.c + (1 if tt[(k + 1) % 6] < tt[k] else 0) %}"
    "{% set xc.i2 = k if b < a else xc.i2 %}{% set xc.c2 = xc.c2 + (1 if b < a else 0) %}{% endfor %}"
    "\n@I@{% set xw = n >= 1 and n <= 6 and wmin >= 0 and xc.ok and xc.c == 1 and xc.c2 == 1 and xc.i == xc.i2 %}")
GATE_SET_AFTER = GATE_XW + GATE_SET_BEFORE

# acs1c's proposed-layout refusal, followed by the 15-minute guard: the crossing hold goes between them. The pair anchors on both lines,
# so the rendered text no longer contains its anchor and render_crossing refuses an already-rendered text (no silent double hold).
REFUSE_CYC2 = "the edit would not leave one valid 24-hour cycle in slot order (every slot at least 5 minutes, exactly one wrap past midnight)"
# Stored as "REVIEW REFUSED - <text>; nothing written" in an input_text of 255 characters: well under 221 characters (checked by the suite).
REFUSE_XW = ("the edit would move the midnight crossing to another slot boundary (the owner's restriction R1 of policy P3c): refused until a "
             "supervised relocated-crossing proof is separately authorised")
GATE_REFUSE_HEAD = "\n@I@{% elif setting == 'start_time' and not cyc2 %}" + REFUSE_CYC2
GATE_REFUSE_TAIL = "\n@I@{% elif near %}"
GATE_REFUSE_XW = "\n@I@{% elif setting == 'start_time' and not xw %}" + REFUSE_XW
GATE_REFUSE_BEFORE = GATE_REFUSE_HEAD + GATE_REFUSE_TAIL
GATE_REFUSE_AFTER = GATE_REFUSE_HEAD + GATE_REFUSE_XW + GATE_REFUSE_TAIL

# ---- the header ----------------------------------------------------------------------------------------------------------------------
# The start_time description's last line, followed by the charge_source entry.
HDR_RULE_HEAD = (
    "#                  from Home Assistant's. Slot N-1's Manual Controls staging keeps the old end until it is Loaded again (see the notice)\n")
HDR_RULE_TAIL = "#   charge_source  "
HDR_RULE_BEFORE = HDR_RULE_HEAD + HDR_RULE_TAIL
HDR_RULE_AFTER = (HDR_RULE_HEAD
    + "#                  acs1x (crossing hold): also refused if the edit would move the midnight crossing (the one slot pair whose next\n"
    "#                  start is earlier than its own, in HH:MM minutes) to another slot boundary, until a supervised relocated-crossing\n"
    "#                  proof is separately authorised; every copy of the gate checks it and fails closed on an unreadable start\n"
    + HDR_RULE_TAIL)

# acs1c's generation note, followed by the blank comment line.
HDR_GEN_HEAD = (
    "# as one 24-hour cycle in slot order (the same technique, its own pins): the installed text is render_cyclic(render_stage1(Stage 0)).\n")
HDR_GEN_TAIL = "#\n"
HDR_GEN_BEFORE = HDR_GEN_HEAD + HDR_GEN_TAIL
HDR_GEN_AFTER = (HDR_GEN_HEAD
    + "# acs1x (2026-10-27): home-assistant/prototypes/acs-stage1/acs1x_transform.py then adds the midnight-crossing hold to that text (the\n"
    "# same technique, its own pins): the installed text is render_crossing(render_cyclic(render_stage1(Stage 0))).\n"
    + HDR_GEN_TAIL)


def _pairs() -> "list[tuple[str, str, int]]":
    p: list[tuple[str, str, int]] = []
    p.append((HDR_GEN_BEFORE, HDR_GEN_AFTER, 1))
    p.append((HDR_RULE_BEFORE, HDR_RULE_AFTER, 1))
    for ind, count in GATE_COPIES:
        p.append((_ind(GATE_SET_BEFORE, ind), _ind(GATE_SET_AFTER, ind), count))
        p.append((_ind(GATE_REFUSE_BEFORE, ind), _ind(GATE_REFUSE_AFTER, ind), count))
    return p


CROSSING_PAIRS: "list[tuple[str, str, int]]" = _pairs()


def render_crossing(stage1c_text: str) -> str:
    """Apply CROSSING_PAIRS, in order, to the acs1c package text. Raises ValueError naming the pair if any `before` is present a different
    number of times than declared (so a changed acs1c text can never be silently half-transformed). Line ends are normalised to LF."""
    text = stage1c_text.replace("\r\n", "\n")
    for i, (before, after, count) in enumerate(CROSSING_PAIRS):
        found = text.count(before)
        if found != count:
            raise ValueError(f"acs1x pair {i}: expected {count} occurrence(s) of {before[:90]!r}, found {found}")
        text = text.replace(before, after)
    return text


def unrender_crossing(installed_text: str) -> str:
    """The inverse of render_crossing: apply CROSSING_PAIRS in REVERSE order as (after -> before), each with its declared count. Raises
    ValueError naming the pair on any mismatch. Line ends are normalised to LF. For the installed package the result is the acs1c text
    (sha256 STAGE1C_BASE_SHA256), the file a rollback of this layer restores."""
    text = installed_text.replace("\r\n", "\n")
    for i in range(len(CROSSING_PAIRS) - 1, -1, -1):
        before, after, count = CROSSING_PAIRS[i]
        found = text.count(after)
        if found != count:
            raise ValueError(f"acs1x unrender pair {i}: expected {count} occurrence(s) of {after[:90]!r}, found {found}")
        text = text.replace(after, before)
    return text


def crossing_pairs_sha256() -> str:
    """sha256 of the canonical serialisation of CROSSING_PAIRS (JSON, ASCII-escaped, no whitespace): pinned as CROSSING_PAIRS_SHA256."""
    blob = json.dumps([[b, a, c] for b, a, c in CROSSING_PAIRS], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


# ---- a reference model of the crossing hold (what the gate computes, in plain Python; used by the suites) ----------------------------
def descents(starts: "list[int]") -> "list[int]":
    """The indices k (0-5) whose next slot's start is earlier in raw minutes of the day: tt[(k + 1) % 6] < tt[k]. Exactly one for a layout
    that is one 24-hour cycle in slot order (acs1c_transform.is_cycle); that one is the midnight crossing."""
    return [k for k in range(6) if starts[(k + 1) % 6] < starts[k]]


def holds_crossing(starts: "list[int]", n: int, new: int) -> bool:
    """`xw`: slot n (1-6) moved to `new` (minutes of the day) keeps the midnight crossing where the live layout `starts` has it (minutes, -1 =
    unreadable): one raw decrease in the live and in the proposed layout, at the same index; False on anything unreadable."""
    if not (1 <= n <= 6) or new < 0 or any(t < 0 for t in starts):
        return False
    proposed = list(starts)
    proposed[n - 1] = new
    live, prop = descents(starts), descents(proposed)
    return len(live) == 1 and len(prop) == 1 and live == prop


def verdict(cyclic: str, starts: "list[int]", n: int, new: int) -> str:
    """The installed gate's start-time ordering verdict, given acs1c's verdict `cyclic` for the same case (acs1c_transform.verdict: the
    first refusal name in the gate's order, or 'accept'). The crossing hold sits after the proposed-layout refusal and before the 15-minute
    and active-slot guards, so it turns 'near', 'mid' and 'accept' into 'crossing' when the edit would move the crossing; every earlier
    refusal ('unavailable', 'nochange', 'cycle', 'order', 'cycle2') stands."""
    if cyclic in ("near", "mid", "accept") and not holds_crossing(starts, n, new):
        return "crossing"
    return cyclic
