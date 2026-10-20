"""Advanced Configuration Stage 1 prototype: the Stage 1 package as an exact TRANSFORMATION of the installed Stage 0 package.

WHAT THIS IS. render_stage1() takes the text of the installed Stage 0 package (home-assistant/packages/ecco_tou_target_soc_edit.yaml,
the guarded owner edit of ONE TOU slot's target SOC) and applies an ordered list of EXACT (before, after, expected_count) text
replacements (PAIRS), the technique the repository's proof-chain scope modules use (for example registry/tests/_rtcf1_scope.py): each
`before` must be present exactly the declared number of times, otherwise ValueError names the pair. The result is the Stage 1
package: the same guarded flow (Review -> typed phrase -> Apply through the firmware's existing manual TOU path, fresh evidence,
staged == live proof, quiet-gap press, two independent later reads, UNCERTAIN lock, restart watchdog) for ONE setting of ONE slot:
target SOC, power, start time or charge source (SETTINGS).

WHY A TRANSFORMATION, NOT A FILE. The frozen proof-chain suites scan every file under home-assistant/ and fail when a file that no chain
entry declares spells one of the reserved fallback / failback tokens. The Stage 0 package is a declared holder because its fail-closed
gate reads six such entity ids. Stage 1 must keep that gate byte for byte, so it is derived from the Stage 0 text instead of being
written out: every gate line that carries a reserved token is inherited untouched (no pair anchors on, spells or rewrites one), and
neither this module nor its test spells a reserved token.

WHAT IT DOES NOT DO. It writes nothing (no file, no network, no Home Assistant, no hardware) and its output is never installed. Stage 1
is a drop-in SUPERSET of Stage 0 (same helpers, same acknowledge script, same watchdog automation) and would REPLACE the Stage 0
package at integration, under a reviewed chain entry that declares the Stage 1 holder files; the two can never be installed together.
"""

from __future__ import annotations

from pathlib import Path

ACS0_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
SETTINGS = ("target_soc", "power", "start_time", "charge_source")


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def _ind(tmpl: str, spaces: int) -> str:
    """Fill the @I@ placeholders of a multi-line template with `spaces` spaces (the indent of the copy being edited)."""
    return tmpl.replace("@I@", " " * spaces)


# ---- Jinja building blocks shared by the replacements ------------------------------------------------------------------------
# The live value of the edited setting in its canonical form: SOC int, power int W, start HHMM int, charge source word.
CUR = ("(states(e.live_soc) | int(-1) if setting == 'target_soc' else "
       "(states(e.live_pw) | float(-1) | int(-1) if setting == 'power' else "
       "((states(e.live_t) | replace(':', '')) | int(-1) if setting == 'start_time' else states(e.live_src))))")


def _disp(x: str) -> str:
    """Display text of a canonical value `x` (a variable name): '41 %', '3000 W', '09:30' or the source word."""
    return ("{% if setting == 'target_soc' %}{{ @X@ }} %{% elif setting == 'power' %}{{ @X@ }} W{% elif setting == 'start_time' %}"
            "{{ '%02d:%02d' | format(@X@ // 100, @X@ % 100) }}{% else %}{{ @X@ }}{% endif %}").replace("@X@", x)


def _phr(w: str, d: str) -> str:
    """The typed-phrase core for canonical value `w` with display text `d`."""
    return ("{% if setting == 'target_soc' %}TARGET SOC {{ @W@ }}{% elif setting == 'power' %}POWER {{ @W@ }} W{% elif setting == 'start_time' %}"
            "START {{ @D@ }}{% else %}CHARGE SOURCE {{ @W@ | string | upper }}{% endif %}").replace("@W@", w).replace("@D@", d)


_REG = "{{ {'target_soc': 267, 'power': 255, 'start_time': 249, 'charge_source': 273}.get(setting, 0) + n }}"
_LABEL = "{{ {'target_soc': 'target SOC', 'power': 'power', 'start_time': 'start time', 'charge_source': 'charge source'}.get(setting, 'setting') }}"
_WMIN = "{{ ((want // 100) * 60 + want % 100) if (setting == 'start_time' and want >= 0) else -1 }}"

# The new value of a Review, parsed from the `value` field into the setting's canonical form (-1 = not acceptable).
_REVIEW_WANT = (
    "{% if setting == 'target_soc' %}{{ value | int(-1) }}"
    "{% elif setting == 'power' %}{{ (value | int(-1)) if (value | float(-1)) == (value | int(-1)) else -1 }}"
    "{% elif setting == 'start_time' %}{% set s = (value | string) %}{% set s = s[:5] if (s | length == 8 and s[5:] == ':00') else s %}"
    "{{ ((s[:2] | int(99)) * 100 + (s[3:] | int(99))) if (s | length == 5 and s[2] == ':' and s[:2].isdigit() and s[3:].isdigit()"
    " and (s[:2] | int(99)) <= 23 and (s[3:] | int(99)) <= 59 and (s[3:] | int(1)) % 5 == 0) else -1 }}"
    "{% elif setting == 'charge_source' %}{{ value | string }}{% else %}-1{% endif %}")

_TZ = ["states('sensor.ecco_clock_dongle_ecco_timezone%d_time')" % k for k in range(1, 7)]

# Gate, part 1 (replaces the SOC-only `live_soc` line; the lines after it - among them the ones that read the reserved ids - are untouched).
_GATE_HEAD_BEFORE = ("{% set lo = [shutdown, reserve] | max %}\n"
                     "@I@{% set live_soc = states(e.live_soc) | int(-1) if e else -1 %}")
_GATE_HEAD_AFTER = (
    "{% set lo = [shutdown, reserve] | max %}\n"
    "@I@{% set cur = (" + CUR + ") if e else -1 %}\n"
    "@I@{% set tz = [" + ", ".join(_TZ[:3]) + ",\n"
    "@I@    " + ", ".join(_TZ[3:]) + "] %}\n"
    "@I@{% set tm = namespace(v=[]) %}{% for s in tz %}{% set ok = s | length == 5 and s[2] == ':' and s[:2].isdigit() and s[3:].isdigit()"
    " and (s[:2] | int(99)) <= 23 and (s[3:] | int(99)) <= 59 %}"
    "{% set tm.v = tm.v + [((s[:2] | int(99)) * 60 + (s[3:] | int(99))) if ok else -1] %}{% endfor %}\n"
    "@I@{% set tt = tm.v %}\n"
    "@I@{% set asc = tt[0] >= 0 and tt[0] < tt[1] and tt[1] < tt[2] and tt[2] < tt[3] and tt[3] < tt[4] and tt[4] < tt[5] and tt[5] < 1440 %}\n"
    "@I@{% set lb = (tt[n - 2] if n > 1 else -1) if e else 0 %}\n"
    "@I@{% set hb = (tt[n] if n < 6 else 1440) if e else 0 %}\n"
    "@I@{% set cm = now().hour * 60 + now().minute + now().second / 60 %}\n"
    "@I@{% set bo = ((cur // 100) * 60 + cur % 100) if (setting == 'start_time' and cur >= 0) else -9999 %}\n"
    "@I@{% set near = setting == 'start_time' and bo >= 0 and (([(cm - bo) % 1440, (bo - cm) % 1440] | min) <= 15"
    " or ([(cm - wmin) % 1440, (wmin - cm) % 1440] | min) <= 15) %}\n"
    "@I@{% set mid = setting == 'start_time' and bo >= 0 and wmin >= 0 and (((cm - (bo if wmin > bo else wmin)) % 1440) < ((wmin - bo) | abs)) %}\n"
    "@I@{% set invd = ((as_timestamp(states('sensor.ecco_clock_dongle_inverter_time'), 0) - as_timestamp(now())) | abs) %}\n"
    "@I@{% set cc = now().month in [3, 10] and now().weekday() == 6 and now().day >= 25 and now().hour < 3 %}")

# Gate, part 2 (the SOC-only validation chain becomes a per-setting one, plus the HA-policy refusals).
_GATE_VALID_BEFORE = (
    "{% elif not e %}invalid slot (1-6)\n"
    "@I@{% elif shutdown < 0 %}inverter shutdown SOC unavailable\n"
    "@I@{% elif reserve < 0 %}ECCO minimum battery reserve unavailable\n"
    "@I@{% elif want < lo or want > 100 %}target SOC must be {{ lo }}-100 % (the greater of the inverter shutdown SOC {{ shutdown }} % and the ECCO reserve {{ reserve }} %)\n"
    "@I@{% elif live_soc < 0 %}live slot SOC unavailable\n"
    "@I@{% elif live_soc == want %}no change (slot {{ n }} is already {{ want }} %)")
_GATE_VALID_AFTER = (
    "{% elif not e %}invalid slot (1-6)\n"
    "@I@{% elif setting not in ['target_soc', 'power', 'start_time', 'charge_source'] %}unknown setting (target_soc, power, start_time or charge_source)\n"
    "@I@{% elif setting == 'target_soc' and shutdown < 0 %}inverter shutdown SOC unavailable\n"
    "@I@{% elif setting == 'target_soc' and reserve < 0 %}ECCO minimum battery reserve unavailable\n"
    "@I@{% elif setting == 'target_soc' and (want < lo or want > 100) %}target SOC must be {{ lo }}-100 % (the greater of the inverter shutdown SOC {{ shutdown }} % and the ECCO reserve {{ reserve }} %)\n"
    "@I@{% elif setting == 'power' and (want < 500 or want > 8000 or want % 100 != 0) %}power must be a whole number of watts, a multiple of 100, from 500 to 8000 W (below 500 W the live settings would leave the saved fallback profile's domain, and every further edit, an undo included, would be refused)\n"
    "@I@{% elif setting == 'start_time' and want < 0 %}start time must be HH:MM on the 5-minute grid, 00:00-23:55\n"
    "@I@{% elif setting == 'charge_source' and (want | string) not in ['Grid', 'None'] %}charge source must be exactly Grid or None (no generator is evidenced and the fallback domain is None or Grid)\n"
    "@I@{% elif setting != 'charge_source' and cur < 0 %}live slot {{ label }} unavailable\n"
    "@I@{% elif setting == 'charge_source' and cur not in ['None', 'Grid'] %}the live charge source of slot {{ n }} is {{ cur }}: only None and Grid can be edited\n"
    "@I@{% elif (cur | string) == (want | string) %}no change (slot {{ n }} is already {{ wdisp }})\n"
    "@I@{% elif setting == 'start_time' and not asc %}the six live slot start times are not strictly ascending (unexpected TOU layout)\n"
    "@I@{% elif setting == 'start_time' and not (lb < wmin and wmin < hb) %}the new start time must stay strictly after the previous slot's start and strictly before the next one\n"
    "@I@{% elif near %}the local time is within 15 minutes of the old or the new slot boundary\n"
    "@I@{% elif mid %}the current local time lies between the old and the new boundary: the edit would change which slot is active right now\n"
    "@I@{% elif setting == 'start_time' and invd > 120 %}the inverter clock is more than 120 s from Home Assistant's clock, or unreadable (the inverter runs its TOU slots on its own clock)\n"
    "@I@{% elif cc %}UK clock change night: no edit between 00:00 and 03:00 local on the last Sunday of March and of October")

SRC_WORDS = "['None', 'Grid', 'Generator', 'Grid + Generator']"      # the options of the charge_source select (firmware 5959-6079)
MODE_WORDS = "['None', 'General', 'Backup', 'Charge']"
FIXED_SRC_BEFORE = "and states(e.src) == states(e.live_src) and states(e.mode) == states(e.live_mode)"
FIXED_SRC_AFTER = ("and states(e.src) == states(e.live_src) and states(e.src) in " + SRC_WORDS + " and states(e.mode) == states(e.live_mode)"
                   " and states(e.mode) in " + MODE_WORDS)

# Staged == live for every field except the edited one, which must equal the request (staging check, then the last check before the press).
_STAGE_EQ = (
    "(states(e.soc) | float(-1)) == ((want | float(-2)) if setting == 'target_soc' else (states(e.live_soc) | float(-2)))\n"
    "@I@and (states(e.st) | float(-1)) == ((want | float(-2)) if setting == 'start_time' else ((states(e.live_t) | replace(':', '')) | int(-2)))\n"
    "@I@and (states(e.en) | float(-1)) == ((states(e.live_t_next) | replace(':', '')) | int(-2))\n"
    "@I@and (states(e.pw) | float(-1)) == ((want | float(-2)) if setting == 'power' else (states(e.live_pw) | float(-2)))\n"
    "@I@and states(e.src) == ((want | string) if setting == 'charge_source' else states(e.live_src)) and states(e.src) in " + SRC_WORDS
    + " and states(e.live_src) in " + SRC_WORDS + "\n"
    "@I@and states(e.mode) == states(e.live_mode) and states(e.mode) in " + MODE_WORDS + " and states(e.live_mode) in " + MODE_WORDS)


def _stage_choose(i: int) -> str:
    def num(setting: str, ent: str) -> str:
        return (f"{' ' * i}- conditions:\n{' ' * i}    - condition: template\n{' ' * i}      value_template: \"{{{{ setting == '{setting}' }}}}\"\n"
                f"{' ' * i}  sequence:\n{' ' * i}    - action: number.set_value\n{' ' * i}      continue_on_error: true\n"
                f"{' ' * i}      target:\n{' ' * i}        entity_id: \"{{{{ {ent} }}}}\"\n{' ' * i}      data:\n"
                f"{' ' * i}        value: \"{{{{ want }}}}\"\n")

    def sel(word: str, option: str) -> str:
        # Home Assistant result-parses even static service data, so a static "None" reaches the service as Python None and the call is
        # rejected; the charge source None is therefore staged with select.select_first (its first option is None), Grid by name.
        pad = " " * i
        head = (f"{pad}- conditions:\n{pad}    - condition: template\n"
                f"{pad}      value_template: \"{{{{ setting == 'charge_source' and (want | string) == '{word}' }}}}\"\n"
                f"{pad}  sequence:\n")
        if option:
            return (head + f"{pad}    - action: select.select_option\n{pad}      continue_on_error: true\n"
                    f"{pad}      target:\n{pad}        entity_id: \"{{{{ e.src }}}}\"\n{pad}      data:\n"
                    f"{pad}        option: {option}\n")
        return (head + f"{pad}    - action: select.select_first\n{pad}      continue_on_error: true\n"
                f"{pad}      target:\n{pad}        entity_id: \"{{{{ e.src }}}}\"\n")
    return (num("target_soc", "e.soc") + num("power", "e.pw") + num("start_time", "e.st") + sel("Grid", "Grid") + sel("None", ""))


# ---- the replacements -------------------------------------------------------------------------------------------------------------
HDR_BEFORE = _blk(r"""
# ECCO Pro - Advanced Configuration, Stage 0: a guarded owner edit of ONE TOU slot's target SOC (post-export entry acs0)
#
# Scope: exactly one value - TOU slot N's target SOC (inverter register 267+N, %). Nothing else is staged. This package
# writes NO register itself: it drives the existing, live-proven firmware path once per request (Load Current Slot N To
# Manual Staging -> Manual Configuration Write Enable -> Apply Manual Slot N Settings). That path rewrites the whole slot
# (232 bit0, the slot's start/end pair, power, SOC, flags) from staging, verifies by exact readback, and has NO durable
# snapshot and NO rollback; this package therefore proves, immediately before arming, that every other staged value
# equals the live slot, and never claims success without an independent later read of every one of those registers.
#
# Stages (explicit, separate):
#   EDIT     the owner picks a slot and a value (script fields)
#   REVIEW   script.ecco_cfg_review_tou_slot_soc - writes nothing; runs the full safety gate; records the plan (register,
#            old -> new, the unchanged values, the allowed range) with a one-time review code (valid 10 minutes)
#   CONFIRM  the exact phrase "SET SLOT <n> TARGET SOC <x> REVIEW <code>"
#   APPLY    script.ecco_cfg_apply_tou_slot_soc - re-runs the gate; waits for a fresh configuration read; re-reads the
#            shutdown SOC and the reserve; Loads; waits until the Manual Controls helper sync is at a fixed point; stages
#            only the SOC; proves staged == live for every other field; waits for a quiet gap of the dongle's Modbus poll
#            cycle (acs0r1: 1.5 s after an observed telemetry poll completion, clear of the inverter clock read, at most
#            25 s after the fresh read); arms; re-checks; presses Apply ONCE
#   VERIFY   success only on the firmware's VERIFIED OK AND an independent later configuration read in which the SOC is
#            the request and every other written register is its pre-edit value
#   ANYTHING ELSE: stop, disarm, alert with the observed values and recovery steps, and lock further edits until the owner
#            acknowledges (script.ecco_cfg_acknowledge_edit_review). Never retried, never a compensating write.
# An Apply holds input_boolean.ecco_cfg_edit_in_flight from before its first press until its outcome is judged; a run that
# stops while it is still on (a Home Assistant restart, a script reload) is caught by the watchdog automation below, which
# locks and alerts at once and then disarms. Review and Acknowledge refuse while an Apply runs or is in flight.
# The allowed range is max(inverter shutdown SOC, ECCO minimum battery reserve) .. 100, read fresh before the Apply; the
# reserve helper is only read, never changed.
""")

HDR_AFTER = _blk(r"""
# ECCO Pro - Advanced Configuration, Stage 1 (prototype): a guarded owner edit of ONE setting of ONE TOU slot
#
# GENERATED TEXT, never hand-written: home-assistant/prototypes/acs-stage1/acs_stage1_transform.py derives this package in memory from
# the installed Stage 0 package (ecco_tou_target_soc_edit.yaml) by exact replacements. It is a drop-in SUPERSET of Stage 0 with the same
# helpers, the same acknowledge script and the same watchdog automation, and it would REPLACE Stage 0 at integration: the two packages
# can never be installed together (they declare the same helpers, the same acknowledge script and the same watchdog automation).
#
# Scope: exactly one value of one slot per request, and nothing else is staged. The settings:
#   target_soc     TOU slot N target SOC (inverter register 267+N, %), bound max(inverter shutdown SOC, ECCO reserve)..100
#   power          slot N power (register 255+N, W): a multiple of 100, 500..8000. The firmware accepts 0..8000; below 500 W the live
#                  slot would leave the saved fallback profile's domain and every further edit, an undo included, would be refused
#   start_time     slot N start (register 249+N, HH:MM on the 5-minute grid). It is ALSO slot N-1's end, and slot 1's start is slot 6's
#                  end. The six starts (each in the firmware's HH:MM form) must be strictly ascending before and after; the edit is
#                  refused within 15 minutes of the old or the new boundary, while the local time lies between the old and the new
#                  boundary (it would change the active slot now), and when the inverter's own clock (Inverter Time) is more than 120 s
#                  from Home Assistant's. Slot N-1's Manual Controls staging keeps the old end until it is Loaded again (see the notice)
#   charge_source  slot N charge source (bits 0-1 of register 273+N): None or Grid only (no generator is evidenced). The mode bits and
#                  the reserved bits are kept because the staged mode equals the live mode and the firmware keeps cache & 0xFFE0. None is
#                  staged with select.select_first (None is the select's first option) and Grid with select.select_option, because
#                  Home Assistant result-parses even static service data and would turn a static "None" into Python None
# Refused on every setting: 00:00-03:00 local on the last Sunday of March and of October (UK clock change nights).
# This package writes NO register itself: it drives the existing, live-proven firmware path once per request (Load Current Slot N To
# Manual Staging -> Manual Configuration Write Enable -> Apply Manual Slot N Settings). That path rewrites the whole slot (232 bit0, the
# slot's start/end pair, power, SOC, flags) from staging, verifies by exact readback, and has NO durable snapshot and NO rollback; this
# package therefore proves, immediately before arming, that every staged value except the edited one equals the live slot, and never
# claims success without an independent later read of every one of those registers.
#
# Stages (explicit, separate):
#   EDIT     the owner picks a slot, a setting and a value (script fields)
#   REVIEW   script.ecco_cfg_review_tou_slot_setting - writes nothing; runs the full safety gate; records the plan (register, setting,
#            old -> new) with a one-time review code (valid 10 minutes)
#   CONFIRM  the exact phrase "SET SLOT <n> TARGET SOC <x> REVIEW <code>", "SET SLOT <n> POWER <w> W REVIEW <code>",
#            "SET SLOT <n> START <HH:MM> REVIEW <code>" or "SET SLOT <n> CHARGE SOURCE <GRID|NONE> REVIEW <code>"
#   APPLY    script.ecco_cfg_apply_tou_slot_setting - re-runs the gate; waits for a fresh configuration read; re-reads the shutdown SOC
#            and the reserve; Loads; waits until the Manual Controls helper sync is at a fixed point; stages only the edited field;
#            proves staged == live for every other field; waits for a quiet gap of the dongle's Modbus poll cycle (acs0r1: 1.5 s after
#            an observed telemetry poll completion, clear of the inverter clock read, at most 25 s after the fresh read); arms;
#            re-checks; presses Apply ONCE
#   VERIFY   success only on the firmware's VERIFIED OK AND an independent later configuration read in which the edited field is the
#            request and every other written register is its pre-edit value (for the charge source: the raw flags are the pre-edit
#            flags with bits 0-1 replaced; for the start time: the slot's end, the next slot's start, is unchanged)
#   ANYTHING ELSE: stop, disarm, alert with the observed values and recovery steps, and lock further edits until the owner
#            acknowledges (script.ecco_cfg_acknowledge_edit_review). Never retried, never a compensating write.
# An Apply holds input_boolean.ecco_cfg_edit_in_flight from before its first press until its outcome is judged; a run that
# stops while it is still on (a Home Assistant restart, a script reload) is caught by the watchdog automation below, which
# locks and alerts at once and then disarms. Review and Acknowledge refuse while an Apply runs or is in flight.
# The target SOC range is max(inverter shutdown SOC, ECCO minimum battery reserve) .. 100, read fresh before the Apply; the
# reserve helper is only read, never changed.
""")

REVIEW_HEAD_BEFORE = _blk(r"""
    alias: "ECCO - Review a TOU slot target SOC edit"
    description: >-
      REVIEW stage: writes nothing. Checks the edit against every safety gate and records the plan with a one-time
      review code for script.ecco_cfg_apply_tou_slot_soc.
    mode: single
    fields:
      slot:
        description: "TOU slot 1-6"
      target_soc:
        description: "New target SOC (%)"
""")

REVIEW_HEAD_AFTER = _blk(r"""
    alias: "ECCO - Review a TOU slot setting edit"
    description: >-
      REVIEW stage: writes nothing. Checks the edit of ONE setting of ONE slot (target SOC, power, start time or charge source)
      against every safety gate and records the plan with a one-time review code for script.ecco_cfg_apply_tou_slot_setting.
    mode: single
    fields:
      slot:
        description: "TOU slot 1-6"
      setting:
        description: "target_soc, power, start_time or charge_source"
      value:
        description: "New value: SOC in %, power in W (500-8000, multiple of 100), start time HH:MM (5-minute grid) or charge source Grid / None"
""")

REVIEW_WANT_BEFORE = 'want: "{{ target_soc | int(-1) }}"'
REVIEW_WANT_AFTER = (
    "want: >-\n"
    "            " + _REVIEW_WANT + "\n"
    "          reg: \"" + _REG + "\"\n"
    "          label: \"" + _LABEL + "\"\n"
    "          wdisp: >-\n"
    "            " + _disp("want") + "\n"
    "          phr: >-\n"
    "            " + _phr("want", "wdisp") + "\n"
    "          wmin: \"" + _WMIN + "\"")

REVIEW_BEFORE_VAR_BEFORE = 'before: "{{ states(e.live_soc) | int(-1) }}"'
REVIEW_BEFORE_VAR_AFTER = (
    'before: "{{ ' + CUR + ' }}"\n'
    "              bdisp: >-\n"
    "                " + _disp("before"))

REVIEW_RECORD_BEFORE = 'value: "{{ n }}|{{ want }}|{{ code }}|{{ as_timestamp(now()) | int }}|{{ before }}"'
REVIEW_RECORD_AFTER = 'value: "{{ n }}|{{ setting }}|{{ want }}|{{ code }}|{{ as_timestamp(now()) | int }}|{{ before }}"'

REVIEWED_BEFORE = ("REVIEWED - slot {{ n }} target SOC (register {{ e.reg }}) {{ before }} -> {{ want }} %; confirm with: "
                   "SET SLOT {{ n }} TARGET SOC {{ want }} REVIEW {{ code }}")
REVIEWED_AFTER = ("REVIEWED - slot {{ n }} {{ label }} (register {{ reg }}) {{ bdisp }} -> {{ wdisp }}; confirm with: "
                  "SET SLOT {{ n }} {{ phr }} REVIEW {{ code }}")

REVIEW_TITLE_BEFORE = 'title: "ECCO: review TOU slot {{ n }} target SOC {{ before }} -> {{ want }} %"'
REVIEW_TITLE_AFTER = 'title: "ECCO: review TOU slot {{ n }} {{ label }} {{ bdisp }} -> {{ wdisp }}"'

REVIEW_MSG_BEFORE = _blk(r"""
                Change: register {{ e.reg }} (slot {{ n }} target SOC) {{ before }} % -> {{ want }} %.
                Unchanged and rewritten with their current values: start {{ states(e.live_t) }}, end {{ states(e.live_t_next) }},
                power {{ states(e.live_pw) }} W, charge source {{ states(e.live_src) }}, mode {{ states(e.live_mode) }},
                grid charge {{ states('binary_sensor.ecco_clock_dongle_ecco_battery_grid_charge_enabled') }}.
                Allowed range {{ lo }}-100 % (inverter shutdown SOC and ECCO reserve, re-read before applying).
                The fallback profile will then differ (DRIFT) until you Review and Save it.
                To apply within 10 minutes, run ECCO - Apply a reviewed TOU slot target SOC edit with:
                SET SLOT {{ n }} TARGET SOC {{ want }} REVIEW {{ code }}
""")

REVIEW_MSG_AFTER = _blk(r"""
                Change: register {{ reg }} (slot {{ n }} {{ label }}) {{ bdisp }} -> {{ wdisp }}.
                {% if setting == 'target_soc' %}Allowed range {{ lo }}-100 % (inverter shutdown SOC and ECCO reserve, re-read before applying). The fallback profile will then differ (DRIFT) until you Review and Save it.
                {% elif setting == 'power' %}Slot power is the per-slot battery charge/discharge power ceiling, 500-8000 W in steps of 100 W; its meaning depends on register 244 (load/export mode), and Dump to Grid and Free Power temporarily own it. The fallback profile will then differ (DRIFT) until you Review and Save it.
                {% elif setting == 'start_time' %}Register {{ reg }} is also the end of slot {{ 6 if n == 1 else n - 1 }}, which now ends at {{ wdisp }} too (slot 1's start is slot 6's end). The six start times must stay strictly ascending. The fallback profile will show CONTEXT (slot times are context) until you Review and Save it. Slot {{ 6 if n == 1 else n - 1 }}'s Manual Controls staging keeps the old end until you Load it again.
                {% else %}Only None and Grid can be set (no generator is evidenced); the mode bits and the reserved bits are kept. The fallback profile will then differ (DRIFT) until you Review and Save it.
                {% endif %}
                Unchanged and rewritten with their current values: {% if setting != 'start_time' %}start {{ states(e.live_t) }}, {% endif %}end {{ states(e.live_t_next) }}, {% if setting != 'power' %}power {{ states(e.live_pw) }} W, {% endif %}{% if setting != 'target_soc' %}target SOC {{ states(e.live_soc) }} %, {% endif %}{% if setting != 'charge_source' %}charge source {{ states(e.live_src) }}, {% endif %}mode {{ states(e.live_mode) }},
                grid charge {{ states('binary_sensor.ecco_clock_dongle_ecco_battery_grid_charge_enabled') }}.
                To apply within 10 minutes, run ECCO - Apply a reviewed TOU slot setting edit with:
                SET SLOT {{ n }} {{ phr }} REVIEW {{ code }}
""")

APPLY_HEAD_BEFORE = _blk(r"""
    alias: "ECCO - Apply a reviewed TOU slot target SOC edit"
    description: >-
      CONFIRM + APPLY stage for the plan recorded by the review. Changes only that slot's target SOC through the existing
      verified firmware path; never retried; an unproven outcome locks further edits for manual review.
    mode: single
    fields:
      confirmation:
        description: "Exactly: SET SLOT <n> TARGET SOC <x> REVIEW <code> (from the review)"
""")

APPLY_HEAD_AFTER = _blk(r"""
    alias: "ECCO - Apply a reviewed TOU slot setting edit"
    description: >-
      CONFIRM + APPLY stage for the plan recorded by the review. Changes only the reviewed setting of that slot through the existing
      verified firmware path; never retried; an unproven outcome locks further edits for manual review.
    mode: single
    fields:
      confirmation:
        description: "Exactly: SET SLOT <n> TARGET SOC <x> | POWER <w> W | START <HH:MM> | CHARGE SOURCE <GRID|NONE>, then REVIEW <code> (from the review)"
""")

APPLY_VARS_BEFORE = _blk(r"""
          n: "{{ rv[0] | int(0) if rv | count == 5 else 0 }}"
          want: "{{ rv[1] | int(-1) if rv | count == 5 else -1 }}"
          code: "{{ rv[2] if rv | count == 5 else '' }}"
          reviewed_at: "{{ rv[3] | int(0) if rv | count == 5 else 0 }}"
          before: "{{ rv[4] | int(-1) if rv | count == 5 else -1 }}"
""")

APPLY_VARS_AFTER = (
    "          n: \"{{ rv[0] | int(0) if rv | count == 6 else 0 }}\"\n"
    "          setting: \"{{ rv[1] if rv | count == 6 else '' }}\"\n"
    "          want: >-\n"
    "            {% if rv | count != 6 %}-1{% elif rv[1] == 'charge_source' %}{{ rv[2] }}{% else %}{{ rv[2] | int(-1) }}{% endif %}\n"
    "          code: \"{{ rv[3] if rv | count == 6 else '' }}\"\n"
    "          reviewed_at: \"{{ rv[4] | int(0) if rv | count == 6 else 0 }}\"\n"
    "          before: >-\n"
    "            {% if rv | count != 6 %}-1{% elif rv[1] == 'charge_source' %}{{ rv[5] }}{% else %}{{ rv[5] | int(-1) }}{% endif %}\n"
    "          reg: \"" + _REG + "\"\n"
    "          label: \"" + _LABEL + "\"\n"
    "          wdisp: >-\n"
    "            " + _disp("want") + "\n"
    "          bdisp: >-\n"
    "            " + _disp("before") + "\n"
    "          phr: >-\n"
    "            " + _phr("want", "wdisp") + "\n"
    "          uphr: >-\n"
    "            " + _phr("before", "bdisp") + "\n"
    "          wmin: \"" + _WMIN + "\"\n")

PROBLEM_COUNT_BEFORE = "| count) != 5 or n < 1 %}no pending review"
PROBLEM_COUNT_AFTER = "| count) != 6 or n < 1 %}no pending review"
PROBLEM_PHRASE_BEFORE = "('SET SLOT ' ~ n ~ ' TARGET SOC ' ~ want ~ ' REVIEW ' ~ code)"
PROBLEM_PHRASE_AFTER = "('SET SLOT ' ~ n ~ ' ' ~ phr ~ ' REVIEW ' ~ code)"
PROBLEM_LIVE_BEFORE = "{% elif (states(e.live_soc) | int(-1)) != before %}the slot changed since the review; review again"
PROBLEM_LIVE_AFTER = "{% elif ((" + CUR + ") | string) != (before | string) %}the slot changed since the review; review again"

IN_PROGRESS_BEFORE = "IN PROGRESS - slot {{ n }} target SOC {{ before }} -> {{ want }} %: waiting for a fresh configuration read"
IN_PROGRESS_AFTER = "IN PROGRESS - slot {{ n }} {{ label }} {{ bdisp }} -> {{ wdisp }}: waiting for a fresh configuration read"

PRE_BEFORE = "'soc': states(e.live_soc) | int(-1)} }}"
PRE_AFTER = "'soc': states(e.live_soc) | int(-1),\n                    'cur': " + CUR + ", 'fl': states(e.live_flags) | float(-1)} }}"

FRESH_COND_BEFORE = "{{ not fresh or refusal2 | length > 0 or pre.soc != before }}"
FRESH_COND_AFTER = "{{ not fresh or refusal2 | length > 0 or pre.fl < 0 or (pre.cur | string) != (before | string) }}"
FRESH_MSG_BEFORE = "(refusal2 if refusal2 else 'the slot changed since the review')"
FRESH_MSG_AFTER = "(refusal2 if refusal2 else ('the slot raw flags are unavailable' if pre.fl < 0 else 'the slot changed since the review'))"

STAGE3_BEFORE = _blk(r"""
                  # 3. Stage ONLY the target SOC, then wait for the sync's echo and a fixed point again.
                  - action: number.set_value
                    continue_on_error: true
                    target:
                      entity_id: "{{ e.soc }}"
                    data:
                      value: "{{ want }}"
                  - delay:
                      seconds: 2
                  - wait_template: >-
                      {{ (states(e.soc) | float(-1)) == (want | float(-2))
                         and (states(e.st) | float(-1)) == ((states(e.live_t) | replace(':', '')) | int(-2))
                         and (states(e.en) | float(-1)) == ((states(e.live_t_next) | replace(':', '')) | int(-2))
                         and (states(e.pw) | float(-1)) == (states(e.live_pw) | float(-2))
                         and states(e.src) == states(e.live_src) and states(e.mode) == states(e.live_mode)
""")

STAGE3_AFTER = (
    "                  # 3. Stage ONLY the edited field - the slot's target SOC, power or start time number, or its charge source select -\n"
    "                  #    then wait for the sync's echo and a fixed point again.\n"
    "                  - choose:\n"
    + _stage_choose(22)
    + "                  - delay:\n"
    "                      seconds: 2\n"
    "                  - wait_template: >-\n"
    "                      {{ " + _ind(_STAGE_EQ, 25) + "\n")

LAST_BEFORE = _blk(r"""
                             and (states(e.soc) | float(-1)) == (want | float(-2))
                             and (states(e.st) | float(-1)) == ((states(e.live_t) | replace(':', '')) | int(-2))
                             and (states(e.en) | float(-1)) == ((states(e.live_t_next) | replace(':', '')) | int(-2))
                             and (states(e.pw) | float(-1)) == (states(e.live_pw) | float(-2))
                             and states(e.src) == states(e.live_src) and states(e.mode) == states(e.live_mode)
""")
LAST_AFTER = "                             and " + _ind(_STAGE_EQ, 29) + "\n"

DIFF_BEFORE = _blk(r"""
                            {% if (states(e.live_soc) | int(-1)) != want %}{% set d.v = d.v + ['SOC ' ~ states(e.live_soc) ~ ' (expected ' ~ want ~ ')'] %}{% endif %}
                            {% if states(e.live_t) != pre.t %}{% set d.v = d.v + ['start ' ~ states(e.live_t) ~ ' (was ' ~ pre.t ~ ')'] %}{% endif %}
                            {% if states(e.live_t_next) != pre.t_next %}{% set d.v = d.v + ['end ' ~ states(e.live_t_next) ~ ' (was ' ~ pre.t_next ~ ')'] %}{% endif %}
                            {% if (states(e.live_pw) | float(-1)) != pre.pw %}{% set d.v = d.v + ['power ' ~ states(e.live_pw) ~ ' (was ' ~ pre.pw ~ ')'] %}{% endif %}
                            {% if states(e.live_src) != pre.src or states(e.live_mode) != pre.mode or states(e.live_flags) != pre.flags %}{% set d.v = d.v + ['flags ' ~ states(e.live_flags) ~ ' (was ' ~ pre.flags ~ ')'] %}{% endif %}
""")

DIFF_AFTER = _blk(r"""
                            {% set flx = (pre.fl - pre.fl % 4 + (1 if (want | string) == 'Grid' else 0)) if setting == 'charge_source' else pre.fl %}
                            {% if (states(e.live_soc) | int(-1)) != (want if setting == 'target_soc' else pre.soc) %}{% set d.v = d.v + ['SOC ' ~ states(e.live_soc) ~ ' (expected ' ~ (want if setting == 'target_soc' else pre.soc) ~ ')'] %}{% endif %}
                            {% if states(e.live_t) != (wdisp if setting == 'start_time' else pre.t) %}{% set d.v = d.v + ['start ' ~ states(e.live_t) ~ ' (expected ' ~ (wdisp if setting == 'start_time' else pre.t) ~ ')'] %}{% endif %}
                            {% if states(e.live_t_next) != pre.t_next %}{% set d.v = d.v + ['end ' ~ states(e.live_t_next) ~ ' (was ' ~ pre.t_next ~ ')'] %}{% endif %}
                            {% if (states(e.live_pw) | float(-1)) != ((want | float(-1)) if setting == 'power' else pre.pw) %}{% set d.v = d.v + ['power ' ~ states(e.live_pw) ~ ' (expected ' ~ ((want | float(-1)) if setting == 'power' else pre.pw) ~ ')'] %}{% endif %}
                            {% if states(e.live_src) != ((want | string) if setting == 'charge_source' else pre.src) %}{% set d.v = d.v + ['source ' ~ states(e.live_src) ~ ' (expected ' ~ ((want | string) if setting == 'charge_source' else pre.src) ~ ')'] %}{% endif %}
                            {% if states(e.live_mode) != pre.mode %}{% set d.v = d.v + ['mode ' ~ states(e.live_mode) ~ ' (was ' ~ pre.mode ~ ')'] %}{% endif %}
                            {% if (states(e.live_flags) | float(-1)) < 0 or (states(e.live_flags) | float(-1)) != flx %}{% set d.v = d.v + ['flags ' ~ states(e.live_flags) ~ ' (expected ' ~ flx ~ ')'] %}{% endif %}
""")

OWNER_EDIT_BEFORE = ("slot {{ n }} target SOC (register {{ e.reg }}) {{ before }} -> {{ want }} % (owner, Advanced Configuration)")
OWNER_EDIT_AFTER = ("slot {{ n }} {{ label }} (register {{ reg }}) {{ bdisp }} -> {{ wdisp }} (owner, Advanced Configuration)")

APPLIED_BEFORE = "APPLIED AND VERIFIED - slot {{ n }} target SOC {{ before }} -> {{ want }} %: firmware readback"
APPLIED_AFTER = "APPLIED AND VERIFIED - slot {{ n }} {{ label }} {{ bdisp }} -> {{ wdisp }}: firmware readback"

OK_NOTE_BEFORE = _blk(r"""
                                      title: "ECCO: TOU slot {{ n }} target SOC changed to {{ want }} %"
                                      message: >-
                                        Verified on the inverter (was {{ before }} %); every other slot {{ n }} value is unchanged.
                                        The fallback profile now differs from the inverter (Fallback status DRIFT): if this is the new
                                        normal, Review and Save the fallback profile. To undo, review and apply slot {{ n }} back to
                                        {{ before }} % the same way.
""")

OK_NOTE_AFTER = _blk(r"""
                                      title: "ECCO: TOU slot {{ n }} {{ label }} changed to {{ wdisp }}"
                                      message: >-
                                        Verified on the inverter (was {{ bdisp }}); every other value written with slot {{ n }} is unchanged{% if setting == 'start_time' %} (register {{ reg }} is also the end of slot {{ 6 if n == 1 else n - 1 }}, which now ends at {{ wdisp }}){% endif %}.
                                        {% if setting == 'start_time' %}The fallback profile now shows CONTEXT (slot times are context): if this is the new normal, Review and Save the fallback profile. Before any Manual Controls Apply of slot {{ 6 if n == 1 else n - 1 }}, press Load Current Slot {{ 6 if n == 1 else n - 1 }} (or Load All): its staged end still holds the old {{ bdisp }}.{% else %}The fallback profile now differs from the inverter (Fallback status DRIFT): if this is the new normal, Review and Save the fallback profile.{% endif %}
                                        To undo, review slot {{ n }} {{ label }} back to {{ bdisp }} (setting {{ setting }}) and confirm with: SET SLOT {{ n }} {{ uphr }} REVIEW <the new review code>
""")

LASTCOMMENT_BEFORE = _blk(r"""
                  # 4. The last check before the press: the full gate (bounds re-read), staged == live except the
                  #    SOC, the helper sync at its fixed point, the arm confirmed; then ONE press.
""")

LASTCOMMENT_AFTER = _blk(r"""
                  # 4. The last check before the press: the full gate (bounds re-read), staged == live except the edited field (which
                  #    must equal the request), the helper sync at its fixed point, the arm confirmed; then ONE press.
""")

UNCERTAIN_BEFORE = "Slot {{ n }} target SOC {{ before }} -> {{ want }} %. Firmware said:"
UNCERTAIN_AFTER = "Slot {{ n }} {{ label }} {{ bdisp }} -> {{ wdisp }}. Firmware said:"


def _pairs() -> "list[tuple[str, str, int]]":
    p: list[tuple[str, str, int]] = []
    add = lambda b, a, n=1: p.append((b, a, n))  # noqa: E731
    add(HDR_BEFORE, HDR_AFTER)
    add(REVIEW_HEAD_BEFORE, REVIEW_HEAD_AFTER)
    add(REVIEW_WANT_BEFORE, REVIEW_WANT_AFTER)
    for reg in range(268, 274):
        add("{'reg': %d, " % reg, "{'reg_soc': %d, " % reg, 2)       # the per-slot map's SOC register is no longer "the" register
    for ind, count in ((12, 2), (16, 1), (24, 1)):                   # the four copies of the gate: Review, Apply, fresh read, last check
        add(_ind(_GATE_HEAD_BEFORE, ind), _ind(_GATE_HEAD_AFTER, ind), count)
        add(_ind(_GATE_VALID_BEFORE, ind), _ind(_GATE_VALID_AFTER, ind), count)
    add(REVIEW_BEFORE_VAR_BEFORE, REVIEW_BEFORE_VAR_AFTER)
    add(REVIEW_RECORD_BEFORE, REVIEW_RECORD_AFTER)
    add(REVIEWED_BEFORE, REVIEWED_AFTER)
    add(REVIEW_TITLE_BEFORE, REVIEW_TITLE_AFTER)
    add(REVIEW_MSG_BEFORE, REVIEW_MSG_AFTER)
    add(APPLY_HEAD_BEFORE, APPLY_HEAD_AFTER)
    add(APPLY_VARS_BEFORE, APPLY_VARS_AFTER)
    add(PROBLEM_COUNT_BEFORE, PROBLEM_COUNT_AFTER)
    add(PROBLEM_PHRASE_BEFORE, PROBLEM_PHRASE_AFTER)
    add(PROBLEM_LIVE_BEFORE, PROBLEM_LIVE_AFTER)
    add(IN_PROGRESS_BEFORE, IN_PROGRESS_AFTER)
    add(PRE_BEFORE, PRE_AFTER)
    add(FRESH_COND_BEFORE, FRESH_COND_AFTER)
    add(FRESH_MSG_BEFORE, FRESH_MSG_AFTER)
    add(STAGE3_BEFORE, STAGE3_AFTER)
    add(LASTCOMMENT_BEFORE, LASTCOMMENT_AFTER)
    add(LAST_BEFORE, LAST_AFTER)
    add(FIXED_SRC_BEFORE, FIXED_SRC_AFTER, 2)       # the pre-staging fixed point (the two sites STAGE3 / LAST did not consume)
    add(DIFF_BEFORE, DIFF_AFTER)
    add(OWNER_EDIT_BEFORE, OWNER_EDIT_AFTER)
    add(APPLIED_BEFORE, APPLIED_AFTER)
    add(OK_NOTE_BEFORE, OK_NOTE_AFTER)
    add(UNCERTAIN_BEFORE, UNCERTAIN_AFTER)
    # the two script ids, last: every remaining mention (the busy checks, the watchdog automation) follows the new Apply script
    add("ecco_cfg_review_tou_slot_soc", "ecco_cfg_review_tou_slot_setting", 1)
    add("ecco_cfg_apply_tou_slot_soc", "ecco_cfg_apply_tou_slot_setting", 5)
    return p


PAIRS: "list[tuple[str, str, int]]" = _pairs()


def render_stage1(acs0_text: str) -> str:
    """Apply PAIRS, in order, to the Stage 0 package text. Raises ValueError naming the pair if any `before` is present a different
    number of times than declared (so a changed Stage 0 package can never be silently half-transformed). Line ends are normalised to LF."""
    text = acs0_text.replace("\r\n", "\n")
    for i, (before, after, count) in enumerate(PAIRS):
        found = text.count(before)
        if found != count:
            raise ValueError(f"stage1 pair {i}: expected {count} occurrence(s) of {before[:90]!r}, found {found}")
        text = text.replace(before, after)
    return text


def stage1_text(root: Path) -> str:
    """The Stage 1 package text, derived from the Stage 0 package under `root` (the repository root). Writes nothing."""
    return render_stage1((Path(root) / ACS0_REL).read_text(encoding="utf-8"))
