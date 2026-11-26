"""Offline suite for Advanced Configuration Stage 1 (post-export entry acs1): a guarded owner edit of ONE setting of ONE TOU slot (target
SOC, power, start time or charge source), the INSTALLED package home-assistant/packages/ecco_tou_target_soc_edit.yaml.

That file is, byte for byte, render_crossing(render_cyclic(render_stage1(<the Stage 0 package>))): three invertible exact-replacement
layers, home-assistant/prototypes/acs-stage1/acs_stage1_transform.py (acs1, the Stage 1 editor; its pins unchanged), acs1c_transform.py
(acs1c, 2026-10-25: the start-time ordering rule becomes one 24-hour cycle in slot order instead of strictly ascending HH:MM values; its
pins unchanged) and acs1x_transform.py (acs1x, 2026-10-27: the midnight-crossing hold, a start-time edit that would move the midnight
crossing to another slot boundary is refused by the scripts themselves, at the owner's direction; it also rewrites four refusal texts, shorter
and never truncated, so that every value written to the result helper fits its 255 characters).
Git history is not needed: unrender_crossing(<installed>) gives the acs1c text of public main e97ba36c back (sha256 pinned; a provenance
artefact: installed alone it would accept crossing-moving edits, so while the hold stands an installed rollback goes to the Stage 1 site
render of 2026-10-25 or to a render that keeps the hold), unrender_cyclic() of that gives the Stage 1 text of 2026-10-25 (sha256 pinned;
the rollback file of the acs1c correction) and unrender_stage1() of that gives the Stage 0 text (sha256 pinned), so the reuse proof, the
SOC parity checks and every earlier text derive from the installed file alone.

The INSTALLED package runs, together with the REAL Manual Controls helper package (ecco_manual_controls_helpers.yaml, whose sync
automations touch the same staging entities), under _ha_script_sim.py (a fail-loud HA script / automation interpreter) against a
subclass of _manual_tou_sim.py's model of the firmware's manual TOU path that adds what Stage 1 needs: the charge-source select, the
firmware's EXACT verify of start / end / power / SOC / flags (+ register 232 bit 0), the select.select_first service, the mode-canonical
gate and per-field clamp faults. In this process the sim also parses template results like Home Assistant does (static service data
included) and aborts a run on service data that Home Assistant's schema would reject (see ha_native / InvalidServiceData below).

  [0] provenance      the installed package IS render_crossing(render_cyclic(render_stage1(Stage 0))); unrender_crossing(installed) IS the pinned
                      acs1c text, unrender_cyclic of that IS the pinned Stage 1 text and unrender_stage1 of that IS the pinned Stage 0 text
                      (sha256), both ways and all three layers; every pair applies exactly its
                      declared count; the result is YAML; the gate lines that carry a reserved token are inherited byte for byte; none of the
                      three files spells a reserved token; deterministic; an altered anchor raises, both ways; the acs1c layer touches only
                      the gate's ordering lines, the header, the Review sentence and the per-slot map
  [0x] crossing hold  the acs1x layer: its twelve pairs, both directions, the untouched-line proof, the check and its refusal in each of the four
                      copies of the gate at its own place (right after the proposed-layout refusal, its lines right before that test), and
                      every value written to the three input_text helpers within 255 characters at its longest (each substitution at a stated
                      maximum, each refusal variable at the longest refusal of its copy; four refusals rewritten, none truncated; a
                      refusal variable written in any form other than whole - a slice, a filter, any expression, however spelled - fails)
  [1] static scope    which services and entities the installed package may touch; every firmware entity exists; Stage 0 untouched
  [2] happy path      every slot x every setting: Review -> typed phrase -> Apply; exactly the intended register changes; verified
  [3] SOC parity      the Stage 0 package (unrendered from the installed one) and the installed one (setting target_soc) on identical
                      worlds: same outcome class, same writes, same lock
  [4] validation      per setting (power floor, start grid / cyclic ordering / wrap / 15-minute guard / active-slot-now guard / inverter clock /
                      malformed live starts, charge source, SOC bounds), raw flags and source / mode words, the UK clock change nights
  [4c] cyclic (acs1c) the six starts as one 24-hour cycle in slot order: the owner's exact baseline (00:30, 05:30, 12:00, 16:35, 22:00, 00:25;
                      slot 5 runs past midnight, slot 6 lasts 5 minutes) with named cases for every slot, its six rotations, layouts that
                      are not one cycle (two wraps, equal starts, off-grid, a slot shorter than 5 minutes, unreadable), the active-slot
                      guard on a window that crosses midnight, a seeded fuzz comparison of the template against a plain-Python reference
                      model (and of that model against the fallback capture's ring rule), the equivalence of the neighbour rule and the
                      proposed-layout rule, forward and undo Applies on the baseline with their write logs, the live-proven SOC / power /
                      source edits of 25 Oct repeated on the baseline, a neighbour that moves between the Review and the Apply, and a
                      hand-edited review record refused by the Apply's own gate
  [4x] crossing hold  (acs1x) every single-slot start edit of the owner's layout (6 slots x 288 grid values) through each of the four gate copies
                      rendered alone and against the reference model, the slot 5 / 6 edits around midnight and every slot at each full hour
                      through the real Review, random cyclic layouts, two independent oracles (the slot that owns the last minute of the day;
                      the moved boundary passing midnight), the Apply's own gate on a hand-edited record, the hold alone failing closed,
                      the crossing held wherever the live layout has it, every other setting unaffected, and one case per conjunct of the
                      hold (each refused only by that conjunct, through all four copies)
  [5] review          phrase per setting, code, expiry, single use, the edited value changed since the review
  [6] gate            every unsafe state and `unavailable` refuses at Review and at Apply, for each setting
  [7] staged == live  any other staged field changed between Load and press stops the edit; the helper mirror reaches its fixed point
  [8] fresh read      an inverter change to an unrelated field after the last poll is kept, for each setting
  [9] faults          firmware refusal, verify failure, partial writes, clamps, disagreeing / missing later read, dropped press, restart
  [10] races          Free Power starting, a second Review / Apply during an Apply, the shared in-flight markers
  [11] acs0r1 timing  the quiet-gap press and a bus-busy refusal behave as in Stage 0
  [11b] follow-ups    F1 (Load slot N-1 after a start-time edit), F2 (re-Load slot N after a conclusively write-free FAILED run, never otherwise),
                      F3 (live power must be a multiple of 100), F4 (Review warnings; input_text values under 255 characters)
  [11x] last check   (acs1x) the last copy of the gate alone refuses (a live start or the fallback live match changes after the Load): the hold
                      for slot 6 and its mirror for slot 5, acs1c's cycle and neighbour refusals and the fallback live match refusal each give
                      the FAILED result within 255 characters, the notice, the F2 re-Load (staging == live) and no press; on the package as
                      first committed (rebuilt in memory) each case fails as the review reproduced it; the fresh-read copy alone refuses (a
                      live start changes between the Apply's gate and the fresh read): the exact 'FAILED - <the whole refusal>; nothing
                      written', no Load, no press
  [12] mutation      in-memory mutants of the installed package, each KILLED by a failing behavioural check (a harness crash is no kill);
                      acs1x: the hold dropped from all four copies and from each copy alone, its index comparison dropped, each conjunct of
                      the hold dropped, its proposed layout built without the new start, the hold moved after the 15-minute and active-slot
                      guards, a rewritten refusal restored to its long form in the last check, a refusal sliced in the Review's, the
                      Apply's gate's or the fresh read's result
  [13] PEX           the acs1, acs1c and acs1x declarations: position, hash link, added files, no frozen or chain-pinned edit, no new token holder

PROVES: the control flow of the installed package against models of the firmware's manual TOU path and of Home Assistant, offline.
DOES NOT PROVE: anything about a live Home Assistant, the dongle or the inverter; how a real interrupted multi-register write behaves
on the inverter; that the real inverter accepts or keeps these values (no live write of power, start time or charge source has been
proven through this path); the Home Assistant time zone (the sim has one fixed zone, so the real clock-change hour is not tested);
register 232's bits other than bit 0 (not exposed to Home Assistant); every detail of real Home Assistant template typing (this suite
reproduces its result parsing, _cached_parse_result, but is still a model; the package compares source words with `| string`).
The residual that a later Manual Controls Apply of slot N-1 with stale loaded staging reverts a start-time edit is DOCUMENTED by a test, not
prevented (the success notice tells the owner to Load first). Writes nothing; no network, no hardware.
"""

from __future__ import annotations

import copy
import ast
import hashlib
import re
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "home-assistant" / "prototypes" / "acs-stage1"))
import _ha_script_sim as S  # noqa: E402
import _manual_tou_sim as M  # noqa: E402
import acs_stage1_transform as X  # noqa: E402
import acs1c_transform as C  # noqa: E402
import acs1x_transform as XW  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------------
# Home-Assistant-faithful template result parsing, installed in THIS test process only (the sim modules are not edited).
# Home Assistant parses EVERY rendered template result - and a static string in script data is a static template that is parsed
# too (Template.async_render -> _parse_result -> literal_eval) - so a static `option: "None"` reaches select.select_option as Python
# None, the service schema (cv.string) rejects it with vol.Invalid, which `continue_on_error` does not cover, and the script run
# aborts. The sim's own parser only converts numbers, lists, dicts and booleans, so it cannot show that. These patches make the sim
# parse like Home Assistant (strings that do not parse stay strings) and make a service call whose data the schema would reject abort
# the run (S.StopRun, logged in World.invalid_calls) instead of being swallowed.
# ----------------------------------------------------------------------------------------------------------------------
_IS_NUMERIC = re.compile(r"^[+-]?(?!0\d)\d*(?:\.\d*)?$")


def ha_native(text):
    """homeassistant.helpers.template._cached_parse_result: literal_eval the rendered text; keep it as the string unless the result is a
    bool, a number that looks numeric, or a container / None."""
    if not isinstance(text, str):
        return text
    s = text.strip()
    try:
        result = ast.literal_eval(s)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return s
    if not isinstance(result, (str, complex)) and (not isinstance(result, (int, float)) or isinstance(result, bool)
                                                   or _IS_NUMERIC.match(s) is not None):
        return result
    return s


def _ha_render_native(self, template, variables=None):
    if not isinstance(template, str):
        return template
    if "{{" not in template and "{%" not in template:
        return ha_native(template)                 # a static string is a static template: parsed as well
    return ha_native(self.render(template, variables))


class InvalidServiceData(Exception):
    """vol.Invalid from a service schema: raised before the service runs, so `continue_on_error` does not cover it."""


_orig_call = S.World.call


def _ha_call(self, service, entity_ids, data):
    try:
        return _orig_call(self, service, entity_ids, data)
    except InvalidServiceData as exc:
        self.__dict__.setdefault("invalid_calls", []).append((self.t, service, str(exc)))
        raise S.StopRun(f"service data rejected: {exc}")


S.World.render_native = _ha_render_native
S.World.call = _ha_call

T_START = time.time()
TRANSFORM_PATH = ROOT / "home-assistant" / "prototypes" / "acs-stage1" / "acs_stage1_transform.py"
CYCLIC_PATH = ROOT / "home-assistant" / "prototypes" / "acs-stage1" / "acs1c_transform.py"
CROSSING_PATH = ROOT / "home-assistant" / "prototypes" / "acs-stage1" / "acs1x_transform.py"
PKG_PATH = ROOT / X.ACS0_REL
S1 = PKG_PATH.read_text(encoding="utf-8")                  # the INSTALLED package (the Stage 1 editor with the acs1c cyclic correction and the acs1x crossing hold)
S1C = XW.unrender_crossing(S1)                             # the acs1c text of public main e97ba36c it was derived from (provenance; NOT an installed rollback while the hold stands)
S1B = C.unrender_cyclic(S1C)                               # the Stage 1 text of 2026-10-25 (the acs1c rollback file)
PKG0 = X.unrender_stage1(S1B)                              # the Stage 0 text, reconstructed from the installed file alone through all three layers
HELPERS_TEXT = (ROOT / "home-assistant/packages/ecco_manual_controls_helpers.yaml").read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
ACS0_SHA = "9fa32b9bb843cfc7b42bae9ed7c06a50f461e564d7f0609e2536c28968d6affe"   # the Stage 0 package that PAIRS apply to, LF line ends
S1_SHA = "2e8813973d133b7bd25fe273af16403af4cea0b8e64b338a015f35412346e9de"      # the Stage 1 package of 2026-10-25 (the acs1c rollback file), LF line ends
PAIRS_SHA = "9924673e2c512edb4048b897aa073c779727d88aa453c345eac0934f29d75a37"   # the canonical serialisation of the 62 pairs (40 reviewed + 22 follow-up)
S1C_SHA = "4ee898311a6abe7a7b0bc1874bff2cd10027d14f4122b341f5145833e3d90405"      # the acs1c text (public main e97ba36c, the acs1x base): the Stage 1 text with the cyclic correction, LF line ends
CPAIRS_SHA = "6cb46976e90d4c7a7e24206d562ee532e4b4246c3595100e10de514075f4d761"   # the canonical serialisation of the 21 acs1c pairs
S1X_SHA = "850f10fda78071220521ab04d2ca46c43bbbed2649090502a0e9e82a02b71262"      # the INSTALLED package: the acs1c text with the acs1x crossing hold, LF line ends
XPAIRS_SHA = "13e6b93c7336f786cad82bb0ba0fd1dd60c6dae02423299f26e185b5a4b5b719"   # the canonical serialisation of the 12 acs1x pairs

REVIEW, APPLY, ACK = "ecco_cfg_review_tou_slot_setting", "ecco_cfg_apply_tou_slot_setting", "ecco_cfg_acknowledge_edit_review"
REVIEW0, APPLY0 = "ecco_cfg_review_tou_slot_soc", "ecco_cfg_apply_tou_slot_soc"
RESULT = "input_text.ecco_cfg_edit_last_result"
EDIT = "input_text.ecco_cfg_last_owner_edit"
PLAN = "input_text.ecco_cfg_edit_review"
LOCK = "input_boolean.ecco_cfg_edit_review_required"
FLIGHT = "input_boolean.ecco_cfg_edit_in_flight"
RESERVE = "input_number.ecco_minimum_reserve_soc"
D = "ecco_clock_dongle_"
SETTINGS = X.SETTINGS

# The reserved fallback / failback tokens exist in this suite only as fragments, to SEARCH for them (as the frozen suites do).
RES_TOKENS = ("ecco_" + "fallback", "fallback_" + "profile", "FALLBACK_" + "PROFILE", "FAILBACK_" + "STATE", "ecco_" + "failback",
              "fbc_" + "raw_")

FAILURES: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f"\n        {detail}" if detail else ""))


T0 = S.parse_local("2026-10-12 14:00:00")           # a Monday, not a clock change night
DEF = M.DEFAULT_SLOTS


# ======================================================================================================================
# The firmware model: the base model plus the select, the firmware's exact verify and per-field clamps
# ======================================================================================================================
class Dongle1(M.ManualTouDongle):
    """_manual_tou_sim.ManualTouDongle with what Stage 1 needs (the base module is not edited):
      (a) select.select_option on manual_slot_<n>_charge_source (staging source, published like the numbers); any other select raises;
      (b) the firmware's verify as an EXACT compare: firmware/ecco_clock_dongle_stage3_4_free_power.yaml apply_manual_slot1 (13666)
          composes expected 250/251/256/268 straight from staging and expected 274 = (cache & 0xFFE0) | source | mode (13737-13771),
          reads 232 and compares bit 0 only (13983-13984), then reads 250.. and compares start, end, power, SOC and flags exactly
          (14027-14033; the failure text is `VERIFY FAILED read T1/T2/P/SOC/FLAG=... expected=...`, 14040ff);
      (c) a per-field clamp fault, fault['clamp'] = {'power': 7000, ...} (keys start, end, power, soc, src, mode): the inverter stores
          the clamped value instead of the written one, so the firmware's exact verify fails."""

    def __init__(self, *a, **k):
        self._expect: dict = {}
        self.select_log: list = []
        super().__init__(*a, **k)
        self.w.service_handlers["select.select_first"] = self._select_first

    def _select(self, entity, data):
        """select.select_option: the service schema wants a string among the options (cv.string): Python None, a number or an unknown word
        is vol.Invalid, raised before the service runs."""
        for n in range(1, 7):
            if entity == f"select.{M.P}manual_slot_{n}_charge_source":
                opt = data.get("option")
                if not isinstance(opt, str) or opt not in M.SRC_BITS:
                    raise InvalidServiceData(f"select.select_option option {opt!r} for {entity}")
                self.select_log.append((self.w.t, "select_option", entity, opt))
                self.staging[n]["src"] = opt
                self.w.after(0.1, lambda n=n: self._publish_staging(n))
                return
        raise S.Unsupported(f"select {entity}")

    def _select_first(self, entity, data):
        """select.select_first: the select's first option, which the firmware lists as "None" for all six charge sources (checked in [1])."""
        for n in range(1, 7):
            if entity == f"select.{M.P}manual_slot_{n}_charge_source":
                first = list(M.SRC_BITS)[0]
                self.select_log.append((self.w.t, "select_first", entity, first))
                self.staging[n]["src"] = first
                self.w.after(0.1, lambda n=n: self._publish_staging(n))
                return
        raise S.Unsupported(f"select_first {entity}")

    def _apply(self, n):
        st = self.staging[n]
        # firmware ~13720-13734: the existing flags register's mode bits (& 0x001C) must be 0x00 / 0x04 / 0x08 / 0x10, else the staged
        # values "failed safety validation" (fault['noncanon'] = {n, ...} puts 0x0C in the cached flags of those slots)
        mode_bits = 0x0C if n in self.fault.get("noncanon", ()) else M.MODE_BITS[self.cache["slots"][n]["mode"]]
        valid = all(0 <= v <= 2359 and v % 100 <= 59 and v % 5 == 0 for v in (st["start"], st["end"])) \
            and st["start"] != st["end"] and 0 <= st["power"] <= 8000 and 0 <= st["soc"] <= 100 \
            and (mode_bits & 0x1C) in (0x00, 0x04, 0x08, 0x10)
        refuse = None
        if self._owner():
            refuse = "REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings"
        elif self.fault.get("refuse_bus") or self.bus_busy(self.w.t):
            if not self.fault.get("refuse_bus"):
                self.bus_refusals.append(self.w.t)
            refuse = "REJECTED - Modbus bus busy with another transaction; try again shortly"
        elif not self.flags["cfg"]:
            refuse = "REJECTED - inverter configuration is offline"
        elif self.flags["rtc"]:
            refuse = "REJECTED - RTC correction currently active"
        elif self.manual:
            refuse = "REJECTED - manual configuration write already active"
        elif not self.arm:
            refuse = "REJECTED - arm Manual Configuration Write Enable first"
        elif not self.loaded[n]:
            refuse = f"REJECTED - load current Slot {n} values into staging first"
        elif not valid:
            refuse = f"REJECTED - staged Slot {n} values failed safety validation"
        self.arm = False
        if refuse:
            self.presses.append((self.w.t, f"apply{n}", refuse))
            self.w.after(0.12, lambda: (self.w.set(M.RESULT, refuse), self.w.set(M.ARM, "off")))
            return
        self.presses.append((self.w.t, f"apply{n}", "PASSED"))
        self.attempts += 1
        self.apply_staging.append(dict(staging=copy.deepcopy(st), gc=self.staged_gc, regs=copy.deepcopy(self.regs)))
        self.loaded[n] = False
        self.manual = True
        self.w.after(0.12, lambda: (self.w.set(M.MANUAL, "on"), self.w.set(M.ARM, "off")))
        cache_reserved = self.cache["slots"][n].get("reserved", 0)         # flags = (cache & 0xFFE0) | source | mode
        self._expect[n] = dict(start=st["start"], end=st["end"], power=st["power"], soc=st["soc"], src=st["src"], mode=st["mode"],
                               reserved=cache_reserved, gc=self.staged_gc)
        base = 250 + n - 1
        plan = [(232, "gc", self.staged_gc), (base, "start", st["start"]), (base + 1 if n < 6 else 250, "end", st["end"]),
                (256 + n - 1, "power", st["power"]), (268 + n - 1, "soc", st["soc"]), (274 + n - 1, "flags", (st["src"], st["mode"]))]
        landed = self.fault.get("partial", len(plan))
        clamp = self.fault.get("clamp", {})

        def write(i):
            if i >= landed:
                self._finish(n, "FAILED - one or more write transactions failed; no automatic retry")
                return
            reg, key, val = plan[i]
            slot = self.regs["slots"][n]
            if key == "gc":
                self.regs["gc"] = val
            elif key == "start":
                slot["start"] = clamp.get("start", val)
            elif key == "end":
                self.regs["slots"][n % 6 + 1]["start"] = clamp.get("end", val)
            elif key == "power":
                slot["power"] = clamp.get("power", val)
            elif key == "soc":
                slot["soc"] = clamp.get("soc", self.fault.get("clamp_soc", val))
            else:
                slot["src"], slot["mode"] = clamp.get("src", val[0]), clamp.get("mode", val[1])
                if cache_reserved or "reserved" in slot:
                    slot["reserved"] = cache_reserved
            self.writes.append((self.w.t, reg, val if not isinstance(val, tuple) else 0))
            if i + 1 < len(plan):
                self.w.after(0.7, lambda: write(i + 1))
            else:
                self.w.after(0.7, lambda: self._finish(n, None))
        self.w.after(0.5, lambda: write(0))

    def _finish(self, n, failed):
        ex = self._expect.get(n)
        if failed is None and self.fault.get("verify_fail"):
            failed = f"VERIFY FAILED - Slot {n} verification timed out"
        if failed is None and ex:
            s = self.regs["slots"][n]
            got = dict(start=s["start"], end=self.end_of(self.regs, n), power=s["power"], soc=s["soc"], src=s["src"], mode=s["mode"],
                       reserved=s.get("reserved", 0))
            bad = [k for k in ("start", "end", "power", "soc", "src", "mode", "reserved") if got[k] != ex[k]]
            if bad or self.regs["gc"] != ex["gc"]:
                failed = f"VERIFY FAILED read mismatch {'/'.join(bad + (['gc'] if self.regs['gc'] != ex['gc'] else []))}"
        self.manual = False
        text = failed or f"VERIFIED OK - manual Slot {n} settings match inverter readback"
        if failed is None:
            self.successes += 1
        self.w.after(0.12, lambda: (self.w.set(M.RESULT, text), self.w.set(M.MANUAL, "off"),
                                    self.w.set(M.SUCCESSES, f"{float(self.successes)}")))
        if not text.startswith("FAILED"):
            self.w.after(3.9, self.poll)


# ======================================================================================================================
# The run harness
# ======================================================================================================================
def core(setting: str, want) -> str:
    """The typed-phrase core for a recorded canonical value, spelled independently of the package."""
    if setting == "target_soc":
        return f"TARGET SOC {want}"
    if setting == "power":
        return f"POWER {want} W"
    if setting == "start_time":
        return f"START {int(want) // 100:02d}:{int(want) % 100:02d}"
    return f"CHARGE SOURCE {str(want).upper()}"


class Run:
    """Home Assistant with the package (Stage 1 by default; legacy=True runs the Stage 0 package unrendered from it) and the REAL Manual
    Controls helper package, and the dongle model."""

    def __init__(self, text=None, setup=None, fp_sched=None, dump_sched=None, reserve=20, shutdown=10, helpers=True, dkw=None,
                 t0=T0, layout=None, legacy=False):
        self.legacy = legacy
        text = text if text is not None else (PKG0 if legacy else S1)
        self.t0 = t0
        self.w = S.World(t0)
        w = self.w
        pk = [yaml.safe_load(text)] + ([yaml.safe_load(HELPERS_TEXT)] if helpers else [])
        self.d = Dongle1(w, shutdown_soc=shutdown, **(dkw or {}))
        if layout:
            layout(self.d)
            self.d.cache = copy.deepcopy(self.d.regs)
            self.d._publish_live()
        day = S.local_str(t0)[:10]
        w.set("input_boolean.ecco_free_power_schedule_armed", "on" if fp_sched else "off")
        w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "on" if dump_sched else "off")
        w.set("input_datetime.ecco_free_power_schedule_start", fp_sched or f"{day} 03:00:00")
        w.set("input_datetime.ecco_dump_to_grid_schedule_start", dump_sched or f"{day} 03:00:00")
        w.set(RESERVE, f"{float(reserve)}")
        self.ha = S.HA(w, pk)
        self.ha.start()
        w.run_until(t0 + 70)                       # one configuration poll (:42) and the helper startup refresh
        self.before = copy.deepcopy(self.d.regs["slots"])
        self.gc_before = self.d.regs["gc"]
        if setup:
            setup(self)

    @property
    def review_script(self):
        return REVIEW0 if self.legacy else REVIEW

    @property
    def apply_script(self):
        return APPLY0 if self.legacy else APPLY

    def review(self, slot, setting, value=None):
        if self.legacy:                              # (slot, soc): the Stage 0 field names
            value = setting if value is None else value
            self.ha.start_script(REVIEW0, {"slot": slot, "target_soc": value})
        else:
            self.ha.start_script(REVIEW, {"slot": slot, "setting": setting, "value": value})
        self.w.run_until(self.w.t + 1)
        return self

    def rec(self):
        return self.w.state(PLAN).split("|")

    def code(self):
        p = self.rec()
        return p[2] if self.legacy and len(p) == 5 else (p[3] if len(p) == 6 else "----")

    def phrase(self):
        p = self.rec()
        if self.legacy:
            return f"SET SLOT {p[0]} TARGET SOC {p[1]} REVIEW {p[2]}" if len(p) == 5 else "-"
        return f"SET SLOT {p[0]} {core(p[1], p[2])} REVIEW {p[3]}" if len(p) == 6 else "-"

    def apply(self, phrase=None, run=420):
        self.ha.start_script(self.apply_script, {"confirmation": self.phrase() if phrase is None else phrase})
        self.w.run_until(self.w.t + run)
        return self

    def edit(self, slot, setting, value=None, run=420):
        return self.review(slot, setting, value).apply(run=run)

    def changed(self):
        out = {}
        for n, s in self.d.regs["slots"].items():
            for k in set(s) | set(self.before[n]):
                a, b = self.before[n].get(k, 0 if k == "reserved" else None), s.get(k, 0 if k == "reserved" else None)
                if a != b:
                    out[(n, k)] = (a, b)
        if self.d.regs["gc"] != self.gc_before:
            out[("gc", "gc")] = (self.gc_before, self.d.regs["gc"])
        return out

    def applies(self):
        return [p for p in self.d.presses if p[1].startswith("apply")]

    def loads(self):
        return [p for p in self.d.presses if p[1].startswith("load")]

    def res(self):
        return self.w.state(RESULT)

    def arm_on(self):
        return self.w.state(M.ARM) == "on"

    def notes(self):
        return [n for n in self.w.notification_log if n[1] == "create"]

    def note(self, nid="ecco_cfg_edit"):
        return self.w.notifications.get(nid, {}).get("message", "")

    def locked(self):
        return self.w.state(LOCK) == "on"

    def calls(self, service):
        return [c for c in self.w.service_log if c[1] == service]

    def invalid(self):
        """Service calls whose data Home Assistant's schema would have rejected (the run was aborted)."""
        return self.w.__dict__.get("invalid_calls", [])


# the reserved-entity ids the gate reads, taken from the sim's safe-state table by neutral predicates (never spelled here)
GATE_KEYS = {
    "live_match": [k for k in M.SAFE_STATES if k.endswith("_live_match")][0],
    "review": [k for k in M.SAFE_STATES if k.endswith("_profile_review")][0],
    "shadow": [k for k in M.SAFE_STATES if k.endswith("_shadow_state")][0],
    "avail": sorted(k for k in M.SAFE_STATES if k.endswith("_available")),
}
LIVE_MATCH, FB_REVIEW, SHADOW_STATE = GATE_KEYS["live_match"], GATE_KEYS["review"], GATE_KEYS["shadow"]


def b10(m="MATCH", ca="F", eh="0", obl="FP:CR,DP:CR,R4:CR,BUS:OK"):
    """A live-match (B10) text in the firmware's grammar: m;dx;cx;ox;ix;eh;obl;ca;elig;ew, every key present."""
    cmp = m in ("MATCH", "DRIFT", "CONTEXT", "EXPORT", "OUT_OF_DOMAIN")
    return (f"m={m};dx={'00080' if cmp else '-'};cx={'000' if cmp else '-'};ox={'00000' if cmp else '-'};"
            f"ix={'00' if cmp else '-'};eh={eh};obl={obl};ca={ca};elig={'OK' if cmp else 'UNK'};ew=-")


# the edit table: for each slot and setting, a valid new value (as given to Review), the register key it changes and old -> new
NEW_SOC = {n: (55 if DEF[n]["soc"] != 55 else 60) for n in DEF}
NEW_START = {1: "00:30", 2: "05:30", 3: "09:30", 4: "16:30", 5: "19:30", 6: "23:30"}
NEW_SRC = {n: ("None" if DEF[n]["src"] == "Grid" else "Grid") for n in DEF}
NEW_POWER = {n: 3000 for n in DEF}


def hhmm_of(text: str) -> int:
    return int(text[:2]) * 100 + int(text[3:5])


def value_for(n, setting):
    return {"target_soc": NEW_SOC, "power": NEW_POWER, "start_time": NEW_START, "charge_source": NEW_SRC}[setting][n]


def expected_change(n, setting):
    """What the model's registers must show after a successful edit of (slot n, setting): exactly this one register."""
    v = value_for(n, setting)
    if setting == "target_soc":
        return {(n, "soc"): (DEF[n]["soc"], v)}
    if setting == "power":
        return {(n, "power"): (DEF[n]["power"], v)}
    if setting == "start_time":
        return {(n, "start"): (DEF[n]["start"], hhmm_of(v))}
    return {(n, "src"): (DEF[n]["src"], v)}


def key_of(setting):
    return {"target_soc": "soc", "power": "power", "start_time": "start", "charge_source": "src"}[setting]


def regs_flat(r):
    """EVERY model register that a slot apply can write: 232 and, per slot, start, power, SOC, source, mode, reserved bits."""
    out = {"232": r.d.regs["gc"]}
    for n, s in r.d.regs["slots"].items():
        for k in ("start", "power", "soc", "src", "mode"):
            out[f"{n}.{k}"] = s[k]
        out[f"{n}.reserved"] = s.get("reserved", 0)
    return out


def uncertain(r, label, cond=True):
    check(f"{label}: UNCERTAIN, one Apply, never retried or compensated, disarmed, LOCKED, alerted with the observed values and "
          "recovery steps", cond and r.res().startswith("UNCERTAIN") and len(r.applies()) == 1 and not r.arm_on()
          and r.locked() and "Do NOT retry" in r.note() and len(r.loads()) == 1, f"{r.res()} {r.notes()}")


def late_flip(ent, val):
    """Flip `ent` right after the Load is pressed (between the Load and the press)."""
    def setup(x):
        orig = x.d._load

        def load_then_flip(n):
            orig(n)
            x.w.after(0.5, lambda: x.w.set(ent, val))
        x.d._load = load_then_flip
    return setup


def after_finish(fn, delay=0.0):
    """Run fn(r) right after the firmware's Apply finished (its outcome published)."""
    def setup(r):
        orig = r.d._finish

        def finish(n, failed):
            orig(n, failed)
            r.w.after(delay, lambda: fn(r, n))
        r.d._finish = finish
    return setup


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


# ======================================================================================================================
print("[0] provenance: the installed package and the Stage 0 text it was derived from")
# ======================================================================================================================
text = PKG0.replace("\r\n", "\n")
bad = []
for i, (before, after, count) in enumerate(X.PAIRS):
    if text.count(before) != count or count < 1 or before == after:
        bad.append((i, text.count(before), count))
    text = text.replace(before, after)
check(f"every one of the {len(X.PAIRS)} pairs applies exactly its declared count, in order, to the Stage 0 text (unrendered from the installed "
      "package through both layers), and changes it, and the result is the Stage 1 text", not bad and text == S1B, str(bad))
raw_pkg = PKG_PATH.read_bytes()
check("PROVENANCE (forward): render_stage1(Stage 0) IS the Stage 1 text byte for byte (sha256 pinned), render_cyclic of that IS the acs1c text "
      "byte for byte (sha256 pinned) and render_crossing of that IS the installed package byte for byte (sha256 pinned); the file has consistent "
      "line ends (LF in the repository)",
      X.render_stage1(PKG0) == S1B and hashlib.sha256(S1B.encode()).hexdigest() == S1_SHA
      and C.render_cyclic(S1B) == S1C and hashlib.sha256(S1C.encode()).hexdigest() == S1C_SHA
      and XW.render_crossing(S1C) == S1 and hashlib.sha256(S1.encode()).hexdigest() == S1X_SHA and b"\r" not in raw_pkg.replace(b"\r\n", b""))
check("PROVENANCE (backward): unrender_crossing(installed) hashes to the pinned acs1c sha256, unrender_cyclic of it to the pinned Stage 1 sha256 and "
      "unrender_stage1 of that to the pinned Stage 0 sha256 (suite pins == the transforms' constants); render(unrender(text)) == text for all three "
      "layers, from the LF text and from a CRLF copy",
      hashlib.sha256(PKG0.encode()).hexdigest() == ACS0_SHA == X.ACS0_BASE_SHA256 and X.render_stage1(X.unrender_stage1(S1B)) == S1B
      and X.unrender_stage1(S1B.replace("\n", "\r\n")) == PKG0 and X.render_stage1(X.unrender_stage1(S1B.replace("\n", "\r\n"))) == S1B
      and C.render_cyclic(C.unrender_cyclic(S1C)) == S1C and C.unrender_cyclic(S1C.replace("\n", "\r\n")) == S1B
      and C.render_cyclic(C.unrender_cyclic(S1C.replace("\n", "\r\n"))) == S1C
      and XW.render_crossing(XW.unrender_crossing(S1)) == S1 and XW.unrender_crossing(S1.replace("\n", "\r\n")) == S1C
      and XW.render_crossing(XW.unrender_crossing(S1.replace("\n", "\r\n"))) == S1)
check("the pins are asserted, not printed: the Stage 1 text's sha256 == the suite's == the acs1 transform's STAGE1_SHA256 == the acs1c transform's "
      "STAGE1_BASE_SHA256; the acs1c text's sha256 == the suite's == the acs1c transform's STAGE1C_SHA256 == the acs1x transform's STAGE1C_BASE_SHA256; "
      "the installed package's sha256 == the suite's == the acs1x transform's STAGE1X_SHA256; the 62 acs1 pairs, the 21 acs1c pairs and the 12 acs1x "
      "pairs hash (canonical serialisation) to their pinned values, so a silent edit of any pair is caught",
      hashlib.sha256(S1B.encode()).hexdigest() == S1_SHA == X.STAGE1_SHA256 == C.STAGE1_BASE_SHA256
      and hashlib.sha256(S1C.encode()).hexdigest() == S1C_SHA == C.STAGE1C_SHA256 == XW.STAGE1C_BASE_SHA256
      and hashlib.sha256(S1.encode()).hexdigest() == S1X_SHA == XW.STAGE1X_SHA256
      and len(XW.CROSSING_PAIRS) == 12 and XW.crossing_pairs_sha256() == XPAIRS_SHA == XW.CROSSING_PAIRS_SHA256
      and len(X.PAIRS) == 62 and X.BASE_PAIR_COUNT == 40 and X.pairs_sha256() == PAIRS_SHA == X.PAIRS_SHA256
      and len(C.CYCLIC_PAIRS) == 21 and C.cyclic_pairs_sha256() == CPAIRS_SHA == C.CYCLIC_PAIRS_SHA256)
SENT = "\x00"


def outside_pairs(installed):
    """(identical, covered, total): the follow-up pairs (index 40 on) are undone exactly first; then the installed package and the Stage 0
    baseline, each with every one of the 40 reviewed pairs' region (the `after` text in the installed one, the `before` text in the baseline;
    the two id renames applied to the baseline first) replaced by a sentinel, must be EQUAL; `covered` is the number of baseline lines no
    reviewed pair touches. None when a pair's text is not present the declared number of times."""
    a = installed
    for bef, aft, c in reversed(X.PAIRS[X.BASE_PAIR_COUNT:]):
        if a.count(aft) != c:
            return None
        a = a.replace(aft, bef)
    for _b, aft, c in reversed(X.PAIRS[2:X.BASE_PAIR_COUNT]):
        if a.count(aft) != c:
            return None
        a = a.replace(aft, SENT)
    base = PKG0
    for old, new, _c in X.PAIRS[:2]:
        base = base.replace(old, new)
    for bef, _a, c in X.PAIRS[2:X.BASE_PAIR_COUNT]:
        if base.count(bef) != c:
            return None
        base = base.replace(bef, SENT)
    ren = [n for _o, n, _c in X.PAIRS[:2]]
    lines = base.split("\n")
    return a == base, sum(1 for ln in lines if SENT not in ln and not any(n in ln for n in ren)), len(PKG0.split("\n"))


OUT = outside_pairs(S1B)
check(f"EVERY part of the Stage 0 baseline that no pair (40 reviewed + 22 follow-up) touches is byte-identical in the Stage 1 text, in the same place and the same number of "
      f"times (the acs0r1 press timing, the fresh-evidence code, the gate, the verdict reads...): {OUT[1] if OUT else '?'} of the baseline's "
      f"{OUT[2] if OUT else '?'} lines are wholly outside the 40 reviewed pairs, and the follow-up pairs are undone exactly first", OUT is not None and OUT[0] is True and OUT[1] > 800, str(OUT))
OUT_MUTANTS = [
    ("the acs0r1 press delay", 'seconds: "{{ 1.5 if bus_quiet else 0 }}"', 'seconds: "{{ 1.6 if bus_quiet else 0 }}"'),
    ("the telemetry period bound of the fresh evidence", "and clk_at > 0 and tel_period >= 8 }}", "and clk_at > 0 and tel_period >= 7 }}"),
    ("the gate-pass counter condition", "and later_read and not attempts_moved and unchanged", "and later_read and unchanged"),
    ("the final disarm", "      # The write enable always ends off (it only permits an Apply) - and must be SEEN off.\n      - action: switch.turn_off\n",
     "      # The write enable always ends off (it only permits an Apply) - and must be SEEN off.\n      - action: switch.turn_on\n"),
]
bad = []
for name, anchor, repl in OUT_MUTANTS:
    n_anchor = S1B.count(anchor)
    mut = S1B.replace(anchor, repl, 1)
    got = outside_pairs(mut)
    if n_anchor < 1 or mut == S1B or got is None or got[0] is not False:
        bad.append((name, n_anchor, got))
check(f"the check kills {len(OUT_MUTANTS)} in-memory mutants that alter one untouched line of the Stage 1 text (the press delay, the telemetry "
      "period bound, the gate-pass counter condition, the final disarm)", not bad, str(bad))
check("the Stage 0 text is itself NOT a rendered package (unrender refuses it), the installed package is NOT a Stage 0, Stage 1 or acs1c text "
      "(render refuses it, every layer; unrender_cyclic refuses it too: the acs1x lines sit inside acs1c's block), the acs1c text is not an installed "
      "package (unrender_crossing refuses it, render_cyclic refuses it) and the Stage 1 text is not an acs1c text (unrender_cyclic and render_crossing "
      "refuse it): no direction can be confused",
      all(_raises(lambda f=f, t=t: f(t)) for f, t in ((X.unrender_stage1, PKG0), (X.render_stage1, S1), (X.render_stage1, S1B),
                                                      (X.unrender_stage1, S1), (C.unrender_cyclic, S1B), (C.render_cyclic, S1), (C.render_cyclic, PKG0),
                                                      (C.unrender_cyclic, S1), (C.render_cyclic, S1C), (XW.render_crossing, S1), (XW.unrender_crossing, S1C),
                                                      (XW.render_crossing, S1B), (XW.unrender_crossing, S1B), (XW.render_crossing, PKG0))))
pkg = yaml.safe_load(S1)
check("the result parses as YAML with Stage 0's shape plus the write-seen recorder: 3 text helpers, 3 booleans (Stage 0's two and ecco_cfg_edit_write_seen), "
      "3 scripts (review, apply, acknowledge), 2 automations (the watchdog and the write-seen recorder)",
      {k: len(v) for k, v in pkg.items()} == {"input_text": 3, "input_boolean": 3, "script": 3, "automation": 2}
      and sorted(pkg["script"]) == sorted([REVIEW, APPLY, ACK]) and pkg["automation"][0]["id"] == "ecco_cfg_edit_interrupted"
      and pkg["automation"][1]["id"] == "ecco_cfg_edit_write_seen" and "ecco_cfg_edit_write_seen" in pkg["input_boolean"]
      and sorted(pkg["script"][REVIEW]["fields"]) == ["setting", "slot", "value"] and list(pkg["script"][APPLY]["fields"]) == ["confirmation"]
      and not any("initial" in (v or {}) for v in pkg["input_boolean"].values()))
pkg0 = yaml.safe_load(PKG0)
check("Stage 0's helpers keep their ids and definitions (one NEW helper: the write-seen marker) - a drop-in superset that replaced it; the watchdog automation (same id) watches the NEW apply script",
      pkg["input_text"] == pkg0["input_text"]
      and {k: v for k, v in pkg["input_boolean"].items() if k != "ecco_cfg_edit_write_seen"} == pkg0["input_boolean"]
      and pkg["script"][ACK] == pkg0["script"][ACK] | {"sequence": pkg["script"][ACK]["sequence"]}
      and f"script.{APPLY}" in S1 and f"script.{APPLY0}" not in S1 and REVIEW0 not in S1
      and str(pkg["automation"][0]).count(f"script.{APPLY}") == str(pkg0["automation"][0]).count(f"script.{APPLY0}") == 2
      and "never be installed together" in S1)
tok_lines0 = [ln for ln in PKG0.replace("\r\n", "\n").split("\n") if any(t in ln for t in RES_TOKENS)]
tok_lines1 = [ln for ln in S1.split("\n") if any(t in ln for t in RES_TOKENS)]
c0, c1 = Counter(tok_lines0), Counter(tok_lines1)
check(f"the gate lines that carry a reserved token ({len(tok_lines0)} lines, {len(c0)} distinct) appear in the result byte for byte, exactly "
      "as many times as in Stage 0, and the result has no other such line", c0 == c1 and len(tok_lines0) == len(tok_lines1) == 20,
      f"{len(tok_lines0)} {len(tok_lines1)}")
check("no pair's `before` or `after`, in any of the three layers, contains a line that carries a reserved token (so no pair can touch one)",
      not [i for i, (b, a, _c) in enumerate(X.PAIRS + C.CYCLIC_PAIRS + XW.CROSSING_PAIRS) if any(t in b or t in a for t in RES_TOKENS)])
own = {p.name: p.read_text(encoding="utf-8") for p in (Path(__file__).resolve(), TRANSFORM_PATH, CYCLIC_PATH, CROSSING_PATH)}
check("none of the four files (this suite, the acs1, acs1c and acs1x transforms) contains any reserved token or fragment (ecco + fallback / "
      "failback, FALLBACK + PROFILE, FAILBACK + STATE, fallback + profile ids, fbc + raw)", all(not any(t in txt for t in RES_TOKENS) for txt in own.values()),
      str({k: [t for t in RES_TOKENS if t in v] for k, v in own.items()}))
check("deterministic: rendering twice, and from a CRLF copy, gives identical text in all three layers (sha256 pinned above)",
      X.render_stage1(PKG0) == S1B == X.render_stage1(PKG0.replace("\n", "\r\n")) == X.render_stage1(X.unrender_stage1(S1B))
      and C.render_cyclic(S1B) == S1C == C.render_cyclic(S1B.replace("\n", "\r\n")) == C.render_cyclic(C.unrender_cyclic(S1C))
      and XW.render_crossing(S1C) == S1 == XW.render_crossing(S1C.replace("\n", "\r\n")) == XW.render_crossing(XW.unrender_crossing(S1)))
print(f"        Stage 1 text sha256 {hashlib.sha256(S1B.encode()).hexdigest()}  ({len(S1B.splitlines())} lines, {len(X.PAIRS)} pairs)")
print(f"        acs1c text sha256 {hashlib.sha256(S1C.encode()).hexdigest()}  ({len(S1C.splitlines())} lines, {len(C.CYCLIC_PAIRS)} more pairs)")
print(f"        installed (acs1x) sha256 {hashlib.sha256(S1.encode()).hexdigest()}  ({len(S1.splitlines())} lines, {len(XW.CROSSING_PAIRS)} more pairs)")
check("the Stage 0 text reconstructed from the installed package is the pinned file (sha256 of its LF text)",
      hashlib.sha256(PKG0.replace("\r\n", "\n").encode()).hexdigest() == ACS0_SHA)
fail_to_raise = []


def render_from(text, start):
    """render_stage1's loop from pair `start` on (the text is the state right BEFORE that pair): ValueError names the pair."""
    for j in range(start, len(X.PAIRS)):
        b, a, c = X.PAIRS[j]
        if text.count(b) != c:
            raise ValueError(f"stage1 pair {j}: expected {c} occurrence(s), found {text.count(b)}")
        text = text.replace(b, a)
    return text


state = PKG0.replace("\r\n", "\n")
for i, (before, after, count) in enumerate(X.PAIRS):
    # `state` is the text right before pair i (pairs 0..i-1 applied): the anchors of the later pairs are spelled as they read there
    fewer = state.replace(before, "", 1) if count == 1 else None
    more = state + "\n" + before
    for label, variant in (("one occurrence removed", fewer), ("one occurrence added", more)):
        if variant is None:
            continue
        try:
            render_from(variant, i)
            fail_to_raise.append((i, label))
        except ValueError as exc:
            if f"pair {i}:" not in str(exc):
                fail_to_raise.append((i, label, str(exc)[:60]))
    state = state.replace(before, after)
assert state == S1B
altered = PKG0.replace("{% elif not e %}invalid slot (1-6)", "{% elif not e %}invalid slot (1-6) ")
assert altered != PKG0
try:
    X.render_stage1(altered)
    fail_to_raise.append(("anchor altered",))
except ValueError as exc:
    if "pair" not in str(exc):
        fail_to_raise.append(("altered message", str(exc)[:60]))
check("a text with ANY pair's anchor removed or duplicated (taken at the state right before that pair), or the Stage 0 text altered, is "
      "refused with ValueError naming exactly that pair (no silent half-transformation)", not fail_to_raise, str(fail_to_raise[:5]))
un_fail, n_real, n_state = [], 0, 0


def unrender_from(text, start):
    """unrender_stage1's loop from pair `start` down (the text is the state right AFTER that pair): ValueError names the pair."""
    for j in range(start, -1, -1):
        b_, a_, c_ = X.PAIRS[j]
        if text.count(a_) != c_:
            raise ValueError(f"stage1 unrender pair {j}: expected {c_} occurrence(s), found {text.count(a_)}")
        text = text.replace(a_, b_)
    return text


prefix_states, _t = [], PKG0
for _b, _a, _c in X.PAIRS:
    _t = _t.replace(_b, _a)
    prefix_states.append(_t)
for i, (before, after, count) in enumerate(X.PAIRS):
    # a pair whose `after` text a LATER pair did not touch is tested on the installed text with the real unrender_stage1; a pair a later
    # pair modified (the follow-up pairs edit text of earlier pairs) is tested on the state right after it with the same loop
    intact = S1B.count(after) == count
    base = S1B if intact else prefix_states[i]
    fn = X.unrender_stage1 if intact else (lambda v, i_=i: unrender_from(v, i_))
    n_real, n_state = n_real + intact, n_state + (not intact)
    fewer = base.replace(after, "", 1) if count == 1 else None
    more = base + "\n" + after
    for label, variant in (("one occurrence removed", fewer), ("one occurrence added", more)):
        if variant is None:
            continue
        try:
            fn(variant)
            un_fail.append((i, label))
        except ValueError as exc:
            if "pair" not in str(exc) or (not intact and f"pair {i}:" not in str(exc)):
                un_fail.append((i, label, str(exc)[:60]))
try:
    X.unrender_stage1(S1B.replace("unknown setting (target_soc", "unknown setting  (target_soc", 1))
    un_fail.append(("after text altered",))
except ValueError as exc:
    if "pair" not in str(exc):
        un_fail.append(("altered message", str(exc)[:60]))
check(f"a Stage 1 text with ANY pair's `after` text removed, duplicated or altered is refused with ValueError naming the pair (a rollback file can "
      f"never be silently half-reconstructed): {n_real} pairs on the Stage 1 text with unrender_stage1 itself, {n_state} pairs that a later "
      "pair modified on the state right after them", not un_fail, str(un_fail[:5]))
check("SETTINGS is exactly the four settings", X.SETTINGS == ("target_soc", "power", "start_time", "charge_source"))
src_t = TRANSFORM_PATH.read_text(encoding="utf-8") + "\n" + CYCLIC_PATH.read_text(encoding="utf-8") + "\n" + CROSSING_PATH.read_text(encoding="utf-8")
check("no transform performs any I/O or uses the network (no read_text / open / write_text / socket / urllib / subprocess)",
      not re.search(r"read_text|read_bytes|write_text|write_bytes|\bopen\(|socket|urllib|requests|subprocess|os\.system|import pathlib|from pathlib", src_t))

# ---- [0c] the acs1c layer: the Stage 1 text -> the installed package --------------------------------------------------------------
print("[0c] the acs1c layer (the cyclic start-time rule): the Stage 1 text -> the acs1c text (the acs1x layer's base, [0x])")
text, bad = S1B, []
for i, (before, after, count) in enumerate(C.CYCLIC_PAIRS):
    if text.count(before) != count or count < 1 or before == after:
        bad.append((i, text.count(before), count))
    text = text.replace(before, after)
check(f"every one of the {len(C.CYCLIC_PAIRS)} acs1c pairs applies exactly its declared count, in order, to the Stage 1 text, changes it, and the "
      "result is the acs1c text", not bad and text == S1C, str(bad))
c_fail = []


def render_cyclic_from(text, start):
    for j in range(start, len(C.CYCLIC_PAIRS)):
        b, a, c = C.CYCLIC_PAIRS[j]
        if text.count(b) != c:
            raise ValueError(f"acs1c pair {j}: expected {c} occurrence(s), found {text.count(b)}")
        text = text.replace(b, a)
    return text


state = S1B
for i, (before, after, count) in enumerate(C.CYCLIC_PAIRS):
    fewer = state.replace(before, "", 1) if count == 1 else None
    more = state + "\n" + before
    for label, variant in (("one occurrence removed", fewer), ("one occurrence added", more)):
        if variant is None:
            continue
        try:
            render_cyclic_from(variant, i)
            c_fail.append((i, label))
        except ValueError as exc:
            if f"pair {i}:" not in str(exc):
                c_fail.append((i, label, str(exc)[:60]))
    state = state.replace(before, after)
assert state == S1C
for i, (before, after, count) in enumerate(C.CYCLIC_PAIRS):
    fewer = S1C.replace(after, "", 1) if count == 1 else None
    more = S1C + "\n" + after
    for label, variant in (("after removed", fewer), ("after added", more)):
        if variant is None:
            continue
        try:
            C.unrender_cyclic(variant)
            c_fail.append((i, label))
        except ValueError as exc:
            if "pair" not in str(exc):
                c_fail.append((i, label, str(exc)[:60]))
for fn, t_, label in ((C.render_cyclic, S1B.replace("{% set asc = tt[0] >= 0 and", "{% set asc = tt[0] >= 0  and", 1), "a Stage 1 anchor altered"),
                      (C.unrender_cyclic, S1C.replace("{% set cyc = g.ok and g.s == 1440 %}", "{% set cyc = g.ok and g.s == 1440  %}", 1), "an acs1c line altered")):
    try:
        fn(t_)
        c_fail.append((label,))
    except ValueError as exc:
        if "pair" not in str(exc):
            c_fail.append((label, str(exc)[:60]))
check("acs1c: a text with ANY pair's anchor removed, duplicated or altered (taken at the state right before that pair, or the acs1c text) is "
      "refused with ValueError naming the pair, in both directions (no silent half-transformation, no half-reconstructed rollback file)",
      not c_fail, str(c_fail[:5]))


def outside_cyclic(installed):
    """(identical, untouched): the installed package with every acs1c pair's `after` region replaced by a sentinel must EQUAL the Stage 1
    text with every `before` region replaced by the same sentinel; `untouched` counts the Stage 1 lines no acs1c pair touches."""
    a, b = installed, S1B
    for bef, aft, c in reversed(C.CYCLIC_PAIRS):
        if a.count(aft) != c or b.count(bef) != c:
            return None
        a, b = a.replace(aft, SENT), b.replace(bef, SENT)
    return a == b, sum(1 for ln in b.split("\n") if SENT not in ln)


OUTC = outside_cyclic(S1C)
check(f"EVERY part of the Stage 1 text that no acs1c pair touches is byte-identical in the acs1c text, in the same place and the same number "
      f"of times: {OUTC[1] if OUTC else '?'} of its {len(S1B.splitlines())} lines are wholly outside the 21 pairs (only the gate's ordering lines, the "
      "header's rule, the Review sentence and the per-slot map change)", OUTC is not None and OUTC[0] is True and OUTC[1] >= len(S1B.splitlines()) - 60, str(OUTC))
bad = []
for name, anchor, repl in OUT_MUTANTS + [("the 15-minute guard", "{% elif near %}", "{% elif false %}"), ("the clock-change-night guard", "{% elif cc %}", "{% elif false %}")]:
    mut = S1C.replace(anchor, repl, 1)
    got = outside_cyclic(mut)
    if mut == S1C or got is None or got[0] is not False:
        bad.append((name, got))
check("that check kills in-memory mutants that alter one line the acs1c layer does not touch (the press delay, the telemetry period bound, the gate-pass "
      "counter condition, the final disarm, the 15-minute guard, the clock-change-night guard)", not bad, str(bad))
check("the installed gate has the cyclic rule in all four copies and no trace of the linear one: `cyc`, `cyc2`, the neighbour window `uw > 0 and uw < arc` "
      "and the unwrapped active-slot guard occur exactly 4 times each; `asc`, `lb`, `hb` and the linear `mid` form are gone",
      S1.count("{% set cyc = g.ok and g.s == 1440 %}") == 4 and S1.count("{% set cyc2 = h.ok and h.s == 1440 %}") == 4
      and S1.count("{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}") == 4 and S1.count("{% elif setting == 'start_time' and not cyc %}") == 4
      and S1.count("{% elif setting == 'start_time' and not cyc2 %}") == 4
      and S1.count("{% elif setting == 'start_time' and (want < 0 or want >= 2400 or want % 100 >= 60 or want % 5 != 0) %}") == 4
      and S1.count("{% elif setting == 'start_time' and want < 0 %}") == 0 and S1B.count("{% elif setting == 'start_time' and want < 0 %}") == 4
      and S1.count("and ([ub, uw] | min) <= uc and uc < ([ub, uw] | max) %}") == 4 and S1.count("{% set pv = tt[(n + 4) % 6] if e else -1 %}") == 4
      and "{% set asc" not in S1 and "lb < wmin" not in S1 and "{% set lb" not in S1 and "{% set hb" not in S1 and "(wmin - bo) | abs" not in S1
      and "strictly ascending" not in S1 and S1B.count("{% set asc") == 4)
REFUSALS, _blocks = set(), 0
for marker in ("refusal: >-", "refusal2: >-", "refusal3: >-"):
    pos = 0
    while True:
        i_ = S1.find(marker, pos)
        if i_ < 0:
            break
        j_ = S1.index("{% endif %}", i_)
        _blocks += 1
        for ln in S1[i_:j_].split("\n"):
            ln = ln.strip()
            if (ln.startswith("{% elif") or ln.startswith("{% if")) and "%}" in ln and ln.split("%}", 1)[1].strip():
                REFUSALS.add(ln.split("%}", 1)[1].strip())
        pos = j_
REFUSALS = sorted(REFUSALS)
check(f"every literal refusal text of the gate's four copies ({len(REFUSALS)} distinct, {_blocks} blocks) fits the 255-character input_text with its "
      "'REVIEW REFUSED - ' and '; nothing written' frame (at most 221 characters before template substitution); the three acs1c texts are among them "
      "(the cycle and neighbour texts as acs1x shortened them; acs1c's own wording is in the acs1c text, four times each)",
      _blocks == 4 and len(REFUSALS) >= 30 and all(len(re.sub(r"{{.*?}}", "", t)) <= 221 for t in REFUSALS)
      and {XW.REFUSE_CYC_NEW, XW.REFUSE_ORDER_NEW, C.REFUSE_CYC2} <= set(REFUSALS)   # acs1x shortened the cycle and neighbour texts ([0x])
      and (C.REFUSE_CYC, C.REFUSE_ORDER) == (XW.REFUSE_CYC_OLD, XW.REFUSE_ORDER_OLD) and S1C.count("%}" + C.REFUSE_CYC + "\n") == 4
      and S1C.count("%}" + C.REFUSE_ORDER + "\n") == 4 and max(len(C.REFUSE_CYC), len(C.REFUSE_ORDER), len(C.REFUSE_CYC2)) <= 221,
      str([(len(re.sub(r"{{.*?}}", "", t)), t[:40]) for t in REFUSALS if len(re.sub(r"{{.*?}}", "", t)) > 221]))
check("the acs1c transform's model constants are the firmware's TOU facts: 5-minute grid, 1440-minute day, slots of at least one grid step; its pins name "
      "the package path and the gate copies acs1 renders (12 spaces twice, 16 once, 24 once)",
      C.GRID_MINUTES == 5 and C.DAY_MINUTES == 1440 and C.MIN_SLOT_MINUTES == 5 and C.PACKAGE_REL == X.ACS0_REL and C.GATE_COPIES == ((12, 2), (16, 1), (24, 1)))


# ---- [0x] the acs1x layer: the acs1c text -> the installed package --------------------------------------------------------------
print("[0x] the acs1x layer (the midnight-crossing hold): the acs1c text -> the installed package")
text, bad = S1C, []
for i, (before, after, count) in enumerate(XW.CROSSING_PAIRS):
    if text.count(before) != count or count < 1 or before == after:
        bad.append((i, text.count(before), count))
    text = text.replace(before, after)
check(f"every one of the {len(XW.CROSSING_PAIRS)} acs1x pairs applies exactly its declared count, in order, to the acs1c text, changes it, and the "
      "result is the installed package", not bad and text == S1, str(bad))
x_fail = []


def render_crossing_from(text, start):
    for j in range(start, len(XW.CROSSING_PAIRS)):
        b, a, c = XW.CROSSING_PAIRS[j]
        if text.count(b) != c:
            raise ValueError(f"acs1x pair {j}: expected {c} occurrence(s), found {text.count(b)}")
        text = text.replace(b, a)
    return text


state = S1C
for i, (before, after, count) in enumerate(XW.CROSSING_PAIRS):
    for label, variant in (("one occurrence removed", state.replace(before, "", 1)), ("one occurrence added", state + "\n" + before)):
        try:
            render_crossing_from(variant, i)
            x_fail.append((i, label))
        except ValueError as exc:
            if f"pair {i}:" not in str(exc):
                x_fail.append((i, label, str(exc)[:60]))
    state = state.replace(before, after)
assert state == S1
for i, (before, after, count) in enumerate(XW.CROSSING_PAIRS):
    for label, variant in (("after removed", S1.replace(after, "", 1)), ("after added", S1 + "\n" + after)):
        try:
            XW.unrender_crossing(variant)
            x_fail.append((i, label))
        except ValueError as exc:
            if "pair" not in str(exc):
                x_fail.append((i, label, str(exc)[:60]))
for fn, t_, label in ((XW.render_crossing, S1C.replace("{% elif near %}", "{% elif  near %}", 1), "an acs1c anchor altered"),
                      (XW.unrender_crossing, S1.replace("{% elif setting == 'start_time' and not xw %}", "{% elif setting == 'start_time' and not  xw %}", 1),
                       "an installed line altered")):
    try:
        fn(t_)
        x_fail.append((label,))
    except ValueError as exc:
        if "pair" not in str(exc):
            x_fail.append((label, str(exc)[:60]))
check("acs1x: a text with ANY pair's anchor removed, duplicated or altered (taken at the state right before that pair, or the installed text) is "
      "refused with ValueError naming the pair, in both directions; every pair is tested for removal, those of the two 12-space copies included",
      not x_fail, str(x_fail[:5]))


def outside_crossing(installed):
    """(identical, untouched): the installed package with every acs1x pair's `after` region replaced by a sentinel must EQUAL the acs1c text
    with every `before` region replaced by the same sentinel; `untouched` counts the acs1c lines no acs1x pair touches."""
    a, b = installed, S1C
    for bef, aft, c in reversed(XW.CROSSING_PAIRS):
        if a.count(aft) != c or b.count(bef) != c:
            return None
        a, b = a.replace(aft, SENT), b.replace(bef, SENT)
    return a == b, sum(1 for ln in b.split("\n") if SENT not in ln)


OUTX = outside_crossing(S1)
check(f"EVERY part of the acs1c text that no acs1x pair touches is byte-identical in the installed package, in the same place and the same number "
      f"of times: {OUTX[1] if OUTX else '?'} of its {len(S1C.splitlines())} lines are wholly outside the 12 pairs (only the header's two notes, the "
      "proposed-layout test's first line, the proposed-layout refusal with the 15-minute guard's line start and the four rewritten refusals with "
      "their next line's start, in each copy)", OUTX is not None and OUTX[0] is True and OUTX[1] == len(S1C.splitlines()) - 36, str(OUTX))
bad = []
for name, anchor, repl in OUT_MUTANTS + [("the clock-change-night guard", "{% elif cc %}", "{% elif false %}"),
                                         ("the cycle rule", "{% elif setting == 'start_time' and not cyc %}", "{% elif false %}"),
                                         ("the active-slot guard", "{% elif mid %}", "{% elif false %}"),
                                         ("the neighbour rule", "{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}", "{% elif false %}")]:
    mut = S1.replace(anchor, repl, 1)
    got = outside_crossing(mut)
    if mut == S1 or got is None or got[0] is not False:
        bad.append((name, got))
check("that check kills in-memory mutants that alter one line the acs1x layer does not touch (the press delay, the telemetry period bound, the gate-pass "
      "counter condition, the final disarm, the clock-change-night guard, the cycle rule, the active-slot guard, the neighbour rule)", not bad, str(bad))
XW_SET_LINE = "{% set xw = n >= 1 and n <= 6 and wmin >= 0 and xc.ok and xc.c == 1 and xc.c2 == 1 and xc.i == xc.i2 %}"
XW_REFUSE_LINE = "{% elif setting == 'start_time' and not xw %}" + XW.REFUSE_XW
x_blocks, x_bad = [], []
for marker in ("refusal: >-", "refusal2: >-", "refusal3: >-"):
    pos = 0
    while True:
        i_ = S1.find(marker, pos)
        if i_ < 0:
            break
        j_ = S1.index("{% endif %}", i_)
        blk = S1[i_:j_]
        ind = len(blk.split("\n")[1]) - len(blk.split("\n")[1].lstrip(" "))
        x_blocks.append((S1.count("\n", 0, i_) + 1, marker.split(":")[0], ind, blk))
        pos = j_
x_blocks.sort()
for line_no, key, ind, blk in x_blocks:
    sp = " " * ind
    if not (blk.count("{% set xc = namespace(") == 1 and blk.count(XW_SET_LINE) == 1 and blk.count(XW_REFUSE_LINE) == 1
            and XW._ind(XW.GATE_XW + XW.GATE_SET_BEFORE, ind) in blk and XW._ind(XW.GATE_REFUSE_AFTER, ind) in blk
            and blk.index("{% set xw = ") < blk.index("{% set h = namespace(") < blk.index("{% set cyc2 = ")
            and ("\n" + sp + XW_REFUSE_LINE + "\n" + sp + "{% elif near %}") in blk):
        x_bad.append((line_no, key, ind))
check("the hold is in all four copies of the gate (the Review, the Apply's gate, its fresh-read re-check, its last check before the press: indents "
      "12 / 12 / 16 / 24, in document order), once each, at its place: the `xc` / `xw` lines right before acs1c's proposed-layout test (`h`, then "
      "`cyc2`), the refusal right after the proposed-layout refusal and right before the 15-minute guard",
      [(k, i) for _l, k, i, _b in x_blocks] == [("refusal", 12), ("refusal", 12), ("refusal2", 16), ("refusal3", 24)] and not x_bad
      and S1.count(XW_SET_LINE) == 4 and S1.count(XW_REFUSE_LINE) == 4 and S1.count("{% set xc = namespace(") == 4
      and S1.count("{% elif setting == 'start_time' and not xw %}") == 4 and " xw " not in S1C and "xc." not in S1C,
      str(x_bad) + " " + str([(l_, k, i) for l_, k, i, _b in x_blocks]))
check("the hold's refusal is one of the gate's literal refusal texts, in plain words (no policy identifier), short enough for every frame whole (at "
      "most 165 characters: 255 less the last check's 90-character frame), and names none of the other refusal classes (a result is never ambiguous)",
      XW.REFUSE_XW in REFUSALS and len(XW.REFUSE_XW) <= XW.REFUSAL_MAX == 165 and "midnight crossing" in XW.REFUSE_XW
      and not re.search(r"\b(R1|R2|P3c?)\b", XW.REFUSE_XW)
      and not any(t in XW.REFUSE_XW for t in ("24-hour cycle", "strictly after the previous slot", "within 15 minutes", "between the old and the new boundary",
                                              "no change", "unavailable", "5-minute grid")))
# --- every value written to the three input_text helpers (255 characters each) at its longest (review finding X1) ---------------------------
# A value longer than the helper's 255 characters is not stored (the helper keeps its old text): a refusal by the last copy of the gate then
# leaves no FAILED result, so its notice and the F2 re-Load do not run. Each substitution below is bounded by the longest text it can produce
# (with the reason); a sliced one by its slice; a conditional by its longest alternative; the refusal variables by the longest refusal of
# their own copy of the gate. An expression not listed fails the check, so a new one must be bounded here. Nothing is truncated to fit:
# a refusal variable is written whole or not at all (review finding FB-1: any other expression of one fails, however it is spelled).
REFUSAL_VARS = ("refusal", "refusal2", "refusal3", "review_problem", "fresh_why")
_REFUSAL_RE = re.compile(r"\b(?:" + "|".join(REFUSAL_VARS) + r")\b")


class Shortened(KeyError):
    """A substitution that writes a refusal variable in any form other than the bare variable (a slice, a filter, a method, any expression)."""


SUB_MAX = {
    "n": (1, "the slot, 1-6: printed only once the slot is checked"),
    "label": (13, "one of the fixed setting labels ('charge source')"),
    "reg": (3, "a register number, 250-279"),
    "bdisp": (7, "the value read live at the Review in display form: a 16-bit register with ' %' or ' W', HH:MM, Grid or None"),
    "wdisp": (7, "the requested value in display form, already checked: 100 %, 8000 W, HH:MM, Grid or None"),
    "phr": (18, "the typed-phrase core ('CHARGE SOURCE NONE')"),
    "code": (4, "the four-digit review code"),
    "setting": (13, "one of the four settings ('charge_source')"),
    "want": (4, "the requested value, already checked: at most four digits, Grid or None"),
    "before": (5, "the value read live at the Review: a 16-bit register, HHMM, Grid or None"),
    "as_timestamp(now()) | int": (10, "Unix seconds (ten digits until 2286)"),
    "now().strftime('%Y-%m-%d %H:%M:%S')": (19, "the local date and time, YYYY-MM-DD HH:MM:SS"),
    "fw_result": (120, "sliced where it is defined: the firmware's last result [:120]"),
    "att0": (13, "the firmware's int write counter as a float (ten digits, a sign and '.0')"),
    "w_att": (13, "the same counter as a float"),
    "att0 | int(-1)": (11, "the same counter as an int"),
    "att_now | int(-1)": (11, "the same counter as an int"),
    "lo": (5, "the greater of the inverter shutdown SOC (a 16-bit register) and the reserve (0-100)"),
    "shutdown": (5, "the inverter shutdown SOC, a 16-bit register"),
    "reserve": (5, "the ECCO reserve input_number, 0-100"),
    "states(e.live_pw)": (11, "a numeric sensor of a 16-bit register ('65535.0'), or 'unavailable'"),
    "cur": (16, "the live charge-source word: the firmware's None, Grid, Generator or 'Grid + Generator', or 'unavailable'"),
}


def _balanced(t):
    d = 0
    for ch in t:
        d += (ch == "(") - (ch == ")")
        if d < 0:
            return False
    return d == 0


def _alts(expr):
    """The value alternatives of a (nested) conditional expression `A if C else B`, outer parentheses removed."""
    e = expr.strip()
    while e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        e = e[1:-1].strip()
    depth, quote, at_if = 0, None, None
    for i, ch in enumerate(e):
        if quote:
            quote = None if ch == quote else quote
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and at_if is None and e.startswith(" if ", i):
            at_if = i
        elif depth == 0 and at_if is not None and e.startswith(" else ", i):
            return _alts(e[:at_if]) + _alts(e[i + 6:])
    return [e]


def sub_bound(expr, var):
    """The longest text the substitution {{ expr }} can produce (KeyError for an expression that is not bounded here; Shortened for a refusal
    variable written in any form but whole)."""
    alts = _alts(expr)
    if len(alts) > 1:
        return max(sub_bound(a, var) for a in alts)
    e = alts[0]
    if re.fullmatch(r"'[^']*'|\"[^\"]*\"", e):
        return len(e) - 2
    if _REFUSAL_RE.search(e) and e not in REFUSAL_VARS:
        raise Shortened(e)
    m = re.fullmatch(r"(.+)\[:(\d+)\]", e)
    if m:
        return int(m.group(2))
    if e in var:
        return var[e]
    if e in SUB_MAX:
        return SUB_MAX[e][0]
    raise KeyError(e)


def text_bound(t, var=None):
    """The longest a text with {{ }} substitutions (and {% %} tags, whose branches are all counted) can become."""
    return len(re.sub(r"{{.*?}}|{%.*?%}", "", t, flags=re.S)) + sum(sub_bound(x, var or {}) for x in re.findall(r"{{(.*?)}}", t, flags=re.S))


def _strings(node, pred, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and pred(k, v, path):
                yield path + (k,), v
            else:
                yield from _strings(v, pred, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, pred, path + (i,))


def _segments(tmpl):
    """The texts a {% if %} / {% elif %} chain can return: what follows each tag up to the next tag, stripped, non-empty."""
    return [x.strip() for x in re.findall(r"%}(.*?)(?={%|$)", tmpl, flags=re.S) if x.strip()]


HELPERS3 = ("input_text.ecco_cfg_edit_last_result", "input_text.ecco_cfg_edit_review", "input_text.ecco_cfg_last_owner_edit")


def writers_report(text):
    """[(script or automation, helper, bound, value[:60])] for every input_text.set_value of the three helpers, and the refusal maxima per copy;
    raises KeyError for an unbounded expression."""
    doc = yaml.safe_load(text)
    copies = [v for _p, v in _strings(doc, lambda k, v, p: "{% set cyc2 =" in v)]
    rmax = [max(text_bound(t) for t in _segments(c)) for c in copies]
    rp = [v for _p, v in _strings(doc, lambda k, v, p: k == "review_problem")]
    fw = [v for _p, v in _strings(doc, lambda k, v, p: k == "fresh_why")]
    assert len(copies) == 4 and len(rp) == 1 and len(fw) == 1
    var = {"Review": {"refusal": rmax[0]},
           "Apply": {"refusal": rmax[1], "review_problem": max(text_bound(t) for t in _segments(rp[0])), "refusal2": rmax[2],
                     "fresh_why": max(len(x) for x in re.findall(r"'([^']*)'", fw[0])), "refusal3": rmax[3]}}
    out = []

    def walk(node, owner):
        if isinstance(node, dict):
            if node.get("action") == "input_text.set_value" and (node.get("target") or {}).get("entity_id") in HELPERS3:
                v = str((node.get("data") or {}).get("value"))
                out.append((owner, node["target"]["entity_id"], text_bound(v, var.get(owner, {})), v[:60]))
            for v in node.values():
                walk(v, owner)
        elif isinstance(node, list):
            for v in node:
                walk(v, owner)
    for sid, sc_ in doc["script"].items():
        walk(sc_, {REVIEW: "Review", APPLY: "Apply"}.get(sid, sid))
    for au in doc["automation"]:
        walk(au, au.get("id"))
    return out, rmax


WR, WR_RMAX = writers_report(S1)
WR_WORST = {h: max(b for _o, h_, b, _v in WR if h_ == h) for h in HELPERS3}
try:
    WR_C = writers_report(S1C)[0]
except KeyError as exc:
    WR_C = [("?", "?", 10 ** 6, f"unbounded {exc}")]
check(f"EVERY value written to the three input_text helpers ({len(WR)} writers: the result, the review record, the owner-edit record) fits 255 "
      f"characters at its longest, nothing truncated: worst {WR_WORST['input_text.ecco_cfg_edit_last_result']} / "
      f"{WR_WORST['input_text.ecco_cfg_edit_review']} / {WR_WORST['input_text.ecco_cfg_last_owner_edit']}; the longest refusal per gate copy "
      f"{WR_RMAX} (the last check's frame adds 90, so its refusals stay within 165); every substitution is bounded with its reason (SUB_MAX), "
      "and on the acs1c text (acs1c's cycle and neighbour texts, acs1's power and fallback live match texts) the last check's writer did not fit "
      f"({max(b for _o, _h, b, _v in WR_C)}) - review finding X1",
      len(WR) == 17 and sum(1 for _o, h_, _b, _v in WR if h_ == HELPERS3[0]) == 14 and all(b <= 255 for _o, _h, b, _v in WR)
      and WR_RMAX[3] <= XW.REFUSAL_MAX and max(b for _o, _h, b, _v in WR_C) > 255
      and all(len(re.sub(r"{{.*?}}", "", n_)) + 16 * n_.count("{{") <= XW.REFUSAL_MAX < len(re.sub(r"{{.*?}}", "", o_)) + 16 * o_.count("{{")
              for o_, n_ in XW.REWRITES),
      str([w for w in WR if w[2] > 255]) + " " + str(WR_RMAX))


def writers_whole(text):
    """None when every value written to the three helpers writes each refusal variable whole; else the first expression that does not."""
    try:
        writers_report(text)
    except Shortened as exc:
        return str(exc)
    return None


# Forms that shorten a refusal (each must be refused, however spelled) and forms that write it whole (each must be bounded).
SHORT_FORMS = ("refusal2[:120]", "refusal2[0:120]", "refusal2 [ : 120 ]", "refusal2[:-10]", "(refusal2)[:120]", "refusal[:100]",
               "(review_problem if review_problem else refusal)[:120]", "refusal3 | truncate(150)", "refusal3|truncate(150, true)",
               "fresh_why[:80]", "refusal2.split(';')[0]", "(refusal2 | string)[:120]", "refusal ~ ''",
               "fresh_why if not fresh else (refusal2[:120] if refusal2 else 'x')")
WHOLE_FORMS = ("refusal", "(refusal2)", "( refusal3 )", "review_problem if review_problem else refusal",
               "fresh_why if not fresh else (refusal2 if refusal2 else ('a' if pre.fl < 0 else 'b'))")
_V5 = dict.fromkeys(REFUSAL_VARS, 10)


def _raises_shortened(expr):
    try:
        sub_bound(expr, _V5)
    except Shortened:
        return True
    return False


check("no refusal is shortened to fit (review finding FB-1): every value written to the three helpers writes each refusal variable "
      f"({', '.join(REFUSAL_VARS)}) whole; any other expression of one fails the bound however it is spelled ({len(SHORT_FORMS)} forms: slices "
      "with and without a start, spaced, negative, of a parenthesised or conditional expression, the truncate filter, a method, a "
      f"concatenation, inside a conditional), and the {len(WHOLE_FORMS)} whole forms (bare, parenthesised, conditional) are bounded",
      writers_whole(S1) is None and all(_raises_shortened(f_) for f_ in SHORT_FORMS)
      and all(sub_bound(f_, _V5) == 10 for f_ in WHOLE_FORMS),
      str((writers_whole(S1), [f_ for f_ in SHORT_FORMS if not _raises_shortened(f_)])))
check("the four rewritten refusals keep their meaning and the words the editor's other texts and suites rely on (the grid, the cycle, the "
      "neighbour rule, 500 to 8000 W, the fallback profile, the live match value), and each replaces its long form in all four copies",
      all(S1.count("%}" + n_ + "\n") == 4 and S1C.count("%}" + o_ + "\n") == 4 and S1.count(o_) == 0 for o_, n_ in XW.REWRITES)
      and "24-hour cycle" in XW.REFUSE_CYC_NEW and "unexpected TOU layout" in XW.REFUSE_CYC_NEW
      and "strictly after the previous slot" in XW.REFUSE_ORDER_NEW and "slot 6 is followed by slot 1" in XW.REFUSE_ORDER_NEW
      and "500 to 8000 W" in XW.REFUSE_POWER_NEW and "fallback profile" in XW.REFUSE_POWER_NEW
      and XW.REFUSE_MATCH_NEW.startswith("the fallback live match is {{ L.split(';m=')[1].split(';')[0][:16] }}: ")
      and "(MATCH, DRIFT or CONTEXT)" in XW.REFUSE_MATCH_NEW)
check("the acs1x transform's constants are acs1c's: the package path, the gate copies (12 spaces twice, 16 once, 24 once), the day, the proposed-layout "
      "refusal it follows, and its base pin is acs1c's result pin",
      XW.PACKAGE_REL == C.PACKAGE_REL == X.ACS0_REL and XW.GATE_COPIES == C.GATE_COPIES and XW.DAY_MINUTES == C.DAY_MINUTES
      and XW.REFUSE_CYC2 == C.REFUSE_CYC2 and XW.STAGE1C_BASE_SHA256 == C.STAGE1C_SHA256)
check("the hold's proposed layout is built exactly as acs1c's proposed-layout test builds it: the same two expressions for a slot's start and the next "
      "slot's start, slot n's start replaced by the new value (wmin)",
      XW.GATE_XW.count("{% set a = wmin if k == n - 1 else tt[k] %}{% set b = wmin if (k + 1) % 6 == n - 1 else tt[(k + 1) % 6] %}") == 1
      and S1.count("{% set a = wmin if k == n - 1 else tt[k] %}{% set b = wmin if (k + 1) % 6 == n - 1 else tt[(k + 1) % 6] %}{% set d = (b - a) % 1440 %}") == 4)

# ======================================================================================================================
print("\n[1] static scope of the installed package")
# ======================================================================================================================


def walk_actions(node, out):
    if isinstance(node, dict):
        if "action" in node and isinstance(node["action"], str):
            tgt = (node.get("target") or {}).get("entity_id", "")
            out.append((node["action"], tgt if isinstance(tgt, str) else str(tgt)))
        for v in node.values():
            walk_actions(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_actions(v, out)
    return out


acts1, acts0 = walk_actions(pkg, []), walk_actions(pkg0, [])
set1 = set(acts1)
check("services: exactly the helpers, notifications, the write enable, Load / Apply buttons, three number.set_value, one select_option and one "
      "select_first - nothing else", {a for a, _ in acts1} == {"button.press", "input_boolean.turn_off", "input_boolean.turn_on", "input_text.set_value",
                                                              "number.set_value", "persistent_notification.create", "persistent_notification.dismiss",
                                                              "select.select_option", "select.select_first", "switch.turn_off", "switch.turn_on"},
      str(sorted(set1)))
check("number.set_value ONLY on the slot's target SOC, power and start_hhmm staging numbers - never end_hhmm",
      sorted(t for a, t in acts1 if a == "number.set_value") == ["{{ e.pw }}", "{{ e.soc }}", "{{ e.st }}"]
      and "{{ e.en }}" not in S1.split("script:", 1)[1].replace("states(e.en)", "") and "e.en }}\"" not in S1)
check("select.select_option (option Grid, a static word) and select.select_first (None, the select's first option) ONLY on the slot's "
      "charge_source select, one each - never the mode select, never a static `None` option",
      sorted(t for a, t in acts1 if a == "select.select_option") == ["{{ e.src }}"]
      and sorted(t for a, t in acts1 if a == "select.select_first") == ["{{ e.src }}"] and "{{ e.mode }}\"" not in S1
      and re.findall(r"action: select\.select_option\n(?:.*\n){4}\s+option: (.*)", S1) == ["Grid"]
      and S1.split("action: select.select_first\n", 1)[1].split("\n")[2].strip() == 'entity_id: "{{ e.src }}"'
      and S1.split("action: select.select_first\n", 1)[1].split("\n")[3].strip().startswith("- delay")      # no data: at all
      and "option: \"None\"" not in S1 and "option: None" not in S1)


def static_service_data(node, out):
    """Every service-data value that is a static string (no template markers): Home Assistant result-parses these too."""
    if isinstance(node, dict):
        if "action" in node and isinstance(node["action"], str):
            for k, v in (node.get("data") or {}).items():
                if isinstance(v, str) and "{{" not in v and "{%" not in v:
                    out.append((node["action"], k, v))
        for v in node.values():
            static_service_data(v, out)
    elif isinstance(node, list):
        for v in node:
            static_service_data(v, out)
    return out


def ha_nonstring_statics(text):
    return [(a, k, v) for a, k, v in static_service_data(yaml.safe_load(text), []) if not isinstance(ha_native(v), str)]


check("Home Assistant's result parsing is reproduced (None, True, 12, 0042, Grid, 09:30, 41 %): None -> None, True -> True, 12 -> 12, "
      "0042 / Grid / 09:30 / '41 %' stay strings", ha_native("None") is None and ha_native("True") is True and ha_native("12") == 12
      and ha_native("0042") == "0042" and ha_native("Grid") == "Grid" and ha_native("09:30") == "09:30" and ha_native("41 %") == "41 %")
check("no static service-data value in the installed package would be parsed by Home Assistant into a non-string (the class of bug that "
      "makes a static `option: \"None\"` reach the select as Python None); the check does flag the old form",
      ha_nonstring_statics(S1) == [] and ha_nonstring_statics(S1.replace("action: select.select_first", "action: select.select_option\n"
                                                                         + " " * 28 + "data:\n" + " " * 30 + "option: \"None\"\n" + " " * 28 + "x: y"))
      != [] and static_service_data(yaml.safe_load(S1), []) != [])
fw_opts = []
for n_ in range(1, 7):
    m_ = re.search(r"id: manual_slot%d_charge_source\n\s+optimistic: true\n\s+options:\n((?:\s+- \"[^\"]+\"\n)+)" % n_, FW_TEXT)
    fw_opts.append(re.findall(r'"([^"]+)"', m_.group(1)) if m_ else None)
check("the firmware lists exactly None, Grid, Generator, Grid + Generator - None FIRST - as the options of all six manual_slotN_charge_source "
      "selects (so select.select_first stages None), and the model's select has the same order",
      all(o == ["None", "Grid", "Generator", "Grid + Generator"] for o in fw_opts) and list(M.SRC_BITS) == fw_opts[0], str(fw_opts))
check("button.press ONLY slot N's Load (the pre-Apply Load and the F2 re-Load), slot N's Apply and, for a start-time edit only, slot N-1's Load "
      "(F1: p_load, the previous slot's Load); switch.turn_on ONLY the Manual Configuration Write Enable",
      sorted(t for a, t in acts1 if a == "button.press") == ["{{ e.apply }}", "{{ e.load }}", "{{ e.load }}", "{{ e.p_load }}"]
      and {t for a, t in acts1 if a == "switch.turn_on"} == {M.ARM} and {t for a, t in acts1 if a == "switch.turn_off"} == {M.ARM})
check("never the grid-charge staging switch, the end number or the mode select as a target, never an ESPHome / Modbus service, the reserve "
      "helper never written", not re.search(r"esphome\.|modbus|write_register|input_number\.set_value", S1)
      and not any(M.GC_STAGED in t or "e.en" in t or "e.mode" in t or "reserve" in t for _a, t in acts1) and RESERVE in S1)
INDIRECT = re.compile(r"\b(?:is_)?state_attr\(|\bhas_value\(|\bstate_translated\(|\bstates\b(?!\()|\bexpand\(|_entities\("
                      r"|\b(?:device|area|floor|label)_[a-z_]+\(|\b(?:device_id|area_id|floor_id|labels|areas|floors)\(|\bthis\.")
ARG = re.compile(r"\b(?:states|is_state)\(([^,)]*)")
LITERAL_ARG = re.compile(r"'[a-z_]+\.[a-z0-9_]+'|e\.[a-z_]+")
check("no indirect route to another entity (state_attr, states.<domain>, expand, *_entities, ...) and every states() / is_state() argument "
      "is a literal entity id or the slot map (the Stage 0 declared-holder rules still hold)", not INDIRECT.search(S1)
      and all(LITERAL_ARG.fullmatch(a.strip()) for a in ARG.findall(S1)), str(INDIRECT.findall(S1)[:3]))
fw_slugs = {re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_") for n in set(re.findall(r'name: "([^"]+)"', FW_TEXT))}
ENT = re.compile(r"\b(?:binary_sensor|sensor|switch|button|number|select)\.ecco_clock_dongle_([a-z0-9_]+)")
used1, used0 = set(ENT.findall(S1)), set(ENT.findall(PKG0))
allowed_new = ({f"manual_slot_{n}_power" for n in range(1, 7)} | {f"manual_slot_{n}_start_hhmm" for n in range(1, 7)}
               | {f"manual_slot_{n}_charge_source" for n in range(1, 7)})
check(f"every dongle entity the installed package names exists in the firmware ({len(used1)} ids), and any beyond Stage 0's is one of the "
      f"18 allowed (power, start_hhmm, charge_source x 6): {len(used1 - used0)} beyond Stage 0", used1 <= fw_slugs and (used1 - used0) <= allowed_new,
      str(sorted(used1 - fw_slugs)) + str(sorted((used1 - used0) - allowed_new)))


def slot_map(txt):
    mp = {}
    for n in range(1, 7):
        m = re.search(r"\n\s*%d: \{(.*?)\}" % n, txt, re.S)
        mp[n] = dict(re.findall(r"'(\w+)': '([^']+)'", m.group(1))) if m else {}
    return mp


mp1, mp0 = slot_map(S1), slot_map(PKG0)


def touched(acts, mp):
    out = set()
    for a, t in acts:
        m = re.fullmatch(r"\{\{ e\.(\w+) \}\}", t)
        if m:
            out |= {mp[n][m.group(1)] for n in mp}
        else:
            out.add(t)
    return out


new_touch = touched(acts1, mp1) - touched(acts0, mp0)
WRITE_SEEN = "input_boolean.ecco_cfg_edit_write_seen"        # the F2 proof's marker: the editor's own helper, cleared before the staging
check("the entities the installed package ACTS on beyond Stage 0's are exactly the 18 allowed ones (6 power numbers, 6 start_hhmm numbers, "
      "6 charge_source selects) plus the editor's own write-seen marker (input_boolean, cleared before the staging, set by its recorder automation); "
      "everything else is read-only or already Stage 0's", len(new_touch) == 19
      and new_touch == {WRITE_SEEN} | {f"{d}.{D}{s}" for s, d in [(x, "number") for x in sorted(allowed_new) if not x.endswith("source")]
                                       + [(x, "select") for x in sorted(allowed_new) if x.endswith("source")]}, str(sorted(new_touch)))
check("the per-slot map is exact for slots 1-6: own Load / Apply / staging / live TimezoneN, the next slot's start as the end, own helpers",
      all(mp1[n].get("load") == f"button.{D}load_current_slot_{n}_to_manual_staging"
          and mp1[n].get("apply") == f"button.{D}apply_manual_slot_{n}_settings"
          and mp1[n].get("pw") == f"number.{D}manual_slot_{n}_power" and mp1[n].get("st") == f"number.{D}manual_slot_{n}_start_hhmm"
          and mp1[n].get("src") == f"select.{D}manual_slot_{n}_charge_source" and mp1[n].get("soc") == f"number.{D}manual_slot_{n}_target_soc"
          and mp1[n].get("live_t") == f"sensor.{D}ecco_timezone{n}_time" and mp1[n].get("live_t_next") == f"sensor.{D}ecco_timezone{n % 6 + 1}_time"
          and mp1[n].get("p_load") == f"button.{D}load_current_slot_{6 if n == 1 else n - 1}_to_manual_staging"
          and mp1[n].get("p_en") == f"number.{D}manual_slot_{6 if n == 1 else n - 1}_end_hhmm"
          and "reg" not in mp1[n] for n in range(1, 7))
      and all(S1.count(f"{n}: {{'reg_soc': {267 + n}, ") == 2 for n in range(1, 7)) and "'reg':" not in S1)
check("no new firmware entity, no firmware / registry / package file is written by the transform or this suite (the Stage 0 text it derives "
      "from is the pinned base; the transform performs no I/O)", hashlib.sha256(PKG0.replace("\r\n", "\n").encode()).hexdigest() == ACS0_SHA
      and src_t.count("read_text(") == 0)

# ======================================================================================================================
print("\n[2] the edit: every slot x every setting (with the real Manual Controls helper package running)")
# ======================================================================================================================
happy_bad = []
for setting in SETTINGS:
    for n in range(1, 7):
        v = value_for(n, setting)
        r = Run()
        regs0 = regs_flat(r)
        r.review(n, setting, v)
        reviewed = r.res().startswith("REVIEWED") and r.d.presses == [] and r.changed() == {} and regs_flat(r) == regs0
        want_phrase = r.phrase()
        phrase_in_note = want_phrase in r.note("ecco_cfg_edit_review") and want_phrase in r.res()
        r.apply()
        exp = expected_change(n, setting)
        flat1 = regs_flat(r)
        diff = {k for k in flat1 if flat1[k] != regs0[k]}
        reg = {"target_soc": 267, "power": 255, "start_time": 249, "charge_source": 273}[setting] + n
        ok = (reviewed and phrase_in_note and r.changed() == exp and diff == {f"{n}.{key_of(setting)}"} and len(r.applies()) == 1
              and len(r.loads()) == (2 if setting == "start_time" else 1) and r.applies()[0][2] == "PASSED" and r.d.successes == 1
              and r.res().startswith("APPLIED AND VERIFIED") and f"register {reg}" in r.w.state(EDIT)
              and not r.arm_on() and not r.locked() and r.w.state(FLIGHT) == "off" and not r.w.warnings and not r.invalid()
              and f"SET SLOT {n} " in r.note() and "REVIEW <" in r.note())
        if not ok:
            happy_bad.append((setting, n, r.res()[:70], r.changed(), r.w.warnings[:2]))
check("all 24 edits (6 slots x 4 settings): REVIEW wrote nothing and showed the phrase; APPLY: one Load, one Apply, VERIFIED by the "
      "firmware and two later reads; ONLY the one register changed (every model register compared); recorded; undo phrase shown; disarmed; "
      "no input_text overflow", not happy_bad, str(happy_bad[:3]))
r = Run().edit(3, "power", 3000)
st = r.d.apply_staging[0]
check("at the Apply, every staged field except the edited one equals the inverter's registers (start, end, SOC, source, mode, grid-charge "
      "bit) and the edited one is the request", st["staging"]["start"] == st["regs"]["slots"][3]["start"]
      and st["staging"]["end"] == st["regs"]["slots"][4]["start"] and st["staging"]["soc"] == st["regs"]["slots"][3]["soc"]
      and st["staging"]["src"] == st["regs"]["slots"][3]["src"] and st["staging"]["mode"] == st["regs"]["slots"][3]["mode"]
      and st["gc"] == st["regs"]["gc"] and st["staging"]["power"] == 3000, str(st))
note = r.note()
check("the success notice gives the undo phrase (the same setting back to the old value) and the DRIFT fallback note",
      "SET SLOT 3 POWER 8000 W REVIEW" in note and "DRIFT" in note and "was 8000 W" in note, note)
r = Run().edit(3, "start_time", "09:30")
note = r.note()
check("a start-time success notice: the fallback profile will show CONTEXT, slot 2's end moved with it, the undo phrase back to 09:00",
      "CONTEXT" in note and "end of slot 2" in note and "SET SLOT 3 START 09:00 REVIEW" in note and "DRIFT" not in note, note)
r = Run().edit(1, "start_time", "00:30")
check("slot 1's start is slot 6's end: the success notice says slot 6 ends at 00:30 too", "end of slot 6" in r.note()
      and r.d.regs["slots"][1]["start"] == 30, r.note())
r = Run().review(3, "start_time", "09:30")
n_ = r.note("ecco_cfg_edit_review")
check("the start-time review text: register 252, 'also the end of slot 2', the unchanged list leaves out the start, the fallback profile "
      "will show CONTEXT (slot times are context) until you Review and Save it",
      "register 252" in n_ and "also the end of slot 2" in n_ and "CONTEXT (slot times are context) until you Review and Save it" in n_
      and "start 09:00" not in n_ and "power 8000.0 W" in n_ and "09:00 -> 09:30" in n_, n_)
r = Run().review(3, "power", 3000)
n_ = r.note("ecco_cfg_edit_review")
check("the power review text: register 258, per-slot battery charge/discharge power ceiling, depends on register 244 (load/export mode), "
      "Dump to Grid / Free Power temporarily own it", "register 258" in n_ and "charge/discharge power ceiling" in n_
      and "register 244 (load/export mode)" in n_ and "Dump to Grid and Free Power temporarily own it" in n_ and "8000 W -> 3000 W" in n_, n_)
r = Run().review(3, "charge_source", "Grid")
n_ = r.note("ecco_cfg_edit_review")
check("the charge-source review text: register 276, None -> Grid, mode and reserved bits kept, the other values listed as unchanged",
      "register 276" in n_ and "None -> Grid" in n_ and "mode bits and the reserved bits are kept" in n_ and "mode General" in n_
      and "charge source" not in n_.split("Unchanged and rewritten", 1)[1].split(" A slot with a charge source set", 1)[0].split(" Do not use SmartDeye", 1)[0], n_)
r = Run().review(3, "target_soc", 41)
n_ = r.note("ecco_cfg_edit_review")
check("the SOC review text is Stage 0's: register 270, 40 % -> 41 %, allowed range 20-100 %, DRIFT", "register 270" in n_
      and "40 % -> 41 %" in n_ and "Allowed range 20-100 %" in n_ and "DRIFT" in n_ and f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}" in n_, n_)

# reserved bits (5+) of the flags register survive a charge-source edit, and the expected raw flags are (pre & ~3) | bit
def reserved_bits(d):
    for n in range(1, 7):
        d.regs["slots"][n]["reserved"] = 0x60


r = Run(layout=reserved_bits)
raw0 = float(r.w.state(f"sensor.{D}ecco_timezone3_raw_flags"))
r.edit(3, "charge_source", "Grid")
raw1 = float(r.w.state(f"sensor.{D}ecco_timezone3_raw_flags"))
check("charge source with reserved bits 0x60 set: raw flags go from %d to %d = (pre & ~3) | 1, reserved bits and mode untouched; only the "
      "source changed" % (raw0, raw1), raw1 == (int(raw0) & ~3) | 1 and r.d.regs["slots"][3]["reserved"] == 0x60
      and r.changed() == {(3, "src"): ("None", "Grid")} and r.res().startswith("APPLIED"), f"{r.res()} {r.changed()}")


# --- the charge source services under Home-Assistant-faithful result parsing (B1)
def b1_bad(text):
    """The Stage 1 text with the charge source None staged the way a Home Assistant schema rejects: select.select_option with a static
    "None" option (Home Assistant result-parses it to Python None; cv.string raises vol.Invalid, which continue_on_error does not cover)."""
    pad = " " * 26
    old = (f"{pad}- action: select.select_first\n{pad}  continue_on_error: true\n{pad}  target:\n{pad}    entity_id: \"{{{{ e.src }}}}\"\n")
    new = (f"{pad}- action: select.select_option\n{pad}  continue_on_error: true\n{pad}  target:\n{pad}    entity_id: \"{{{{ e.src }}}}\"\n"
           f"{pad}  data:\n{pad}    option: \"None\"\n")
    assert text.count(old) == 1
    return text.replace(old, new)


r = Run().edit(1, "charge_source", "None")
check("charge source Grid -> None (slot 1) end to end under Home-Assistant-faithful parsing: staged with ONE select.select_first on the slot's "
      "select (no select_option, no data), no service data rejected, APPLIED AND VERIFIED, only the source changed",
      [c[1] for c in r.w.service_log if c[1].startswith("select.")] == ["select.select_first"]
      and [x[1:] for x in r.d.select_log] == [("select_first", f"select.{D}manual_slot_1_charge_source", "None")] and not r.invalid()
      and r.res().startswith("APPLIED AND VERIFIED") and r.changed() == {(1, "src"): ("Grid", "None")}, f"{r.res()} {r.invalid()}")
r = Run().edit(3, "charge_source", "Grid")
check("charge source None -> Grid (slot 3) end to end: ONE select.select_option with the string option 'Grid', no select_first, APPLIED AND VERIFIED",
      [(c[1], c[3]) for c in r.w.service_log if c[1].startswith("select.")] == [("select.select_option", {"option": "Grid"})]
      and not r.invalid() and r.res().startswith("APPLIED AND VERIFIED") and r.changed() == {(3, "src"): ("None", "Grid")}, r.res())
r = Run(b1_bad(S1)).edit(1, "charge_source", "None")
check("the harness reproduces the live symptom of the rejected design (a static `option: \"None\"`): Home Assistant's parsing turns it into None, "
      "the select call is rejected before it runs (not covered by continue_on_error), the Apply aborts after the Load, nothing is pressed, and the "
      "watchdog locks with a misleading 'interrupted' UNCERTAIN", len(r.invalid()) == 1 and r.applies() == [] and r.changed() == {}
      and r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked(), f"{r.res()} {r.invalid()}")

# (M1 / residual 7: repaired by F1, tested in section [11b])

# --- the firmware's mode-canonical gate (existing flags register mode bits & 0x001C must be 0x00 / 0x04 / 0x08 / 0x10)
r = Run(setup=lambda x: x.d.fault.__setitem__("noncanon", {3})).edit(3, "target_soc", 41)
r4 = Run(setup=lambda x: x.d.fault.__setitem__("noncanon", {3})).edit(4, "target_soc", 41)
check("the firmware refuses a slot whose cached flags have non-canonical mode bits (0x0C): FAILED - the firmware refused (staged values failed "
      "safety validation), nothing written, not locked, one press; another slot is unaffected",
      r.res().startswith("FAILED - the firmware refused") and "failed safety validation" in r.res() and r.changed() == {} and not r.locked()
      and len(r.applies()) == 1 and r.d.attempts == 0 and r4.res().startswith("APPLIED"), f"{r.res()} | {r4.res()}")


# ======================================================================================================================
print("\n[3] SOC parity: the Stage 0 package (unrendered from the installed one) and the installed package (setting target_soc) on identical worlds")
# ======================================================================================================================


def cls(r):
    return r.res().split(" - ")[0]


def summary(r):
    # F2 (acs1) re-Loads slot N after a conclusively write-free FAILED run, which Stage 0 does not: Loads after the Apply press are compared
    # separately ([11b]), the rest of the presses must be identical
    ap_t = min([p[0] for p in r.d.presses if p[1].startswith("apply")] or [float("inf")])
    return dict(cls=cls(r), writes=[(round(t - r.t0, 2), reg, val) for t, reg, val in r.d.writes],
                presses=[(round(p[0] - r.t0, 2), p[1], p[2][:48]) for p in r.d.presses if not (p[1].startswith("load") and p[0] > ap_t)],
                regs=regs_flat(r), locked=r.locked(),
                flight=r.w.state(FLIGHT), arm=r.arm_on(), attempts=r.d.attempts, plan_used=r.w.state(PLAN) == "used")


def parity(slot, soc, setup=None, phrase_fn=None, wait=0, review_only=False, **kw):
    out = []
    for legacy in (True, False):
        r = Run(legacy=legacy, setup=setup, **kw)
        r.review(slot, "target_soc", soc)
        if not review_only:
            if wait:
                r.w.run_until(r.w.t + wait)
            r.apply(phrase=phrase_fn(r) if phrase_fn else None, run=420 if not wait else 60)
        out.append(summary(r))
    return out


PARITY = []
for n in range(1, 7):
    PARITY.append((f"happy path slot {n}", lambda n=n: parity(n, 55 if DEF[n]["soc"] != 55 else 60)))
PARITY += [
    ("firmware refusal (bus busy at the gate)", lambda: parity(3, 41, setup=lambda x: x.d.fault.__setitem__("refuse_bus", True))),
    ("verify failure", lambda: parity(3, 41, setup=lambda x: x.d.fault.__setitem__("verify_fail", True))),
    ("clamp to 45 %", lambda: parity(3, 41, setup=lambda x: x.d.fault.__setitem__("clamp_soc", 45))),
    *[(f"partial write after {k} transactions", lambda k=k: parity(3, 41, setup=lambda x, k_=k: x.d.fault.__setitem__("partial", k_)))
      for k in range(6)],
    ("gate refusal at Review (Free Power transaction)", lambda: parity(3, 41, setup=lambda x: x.d.set_flag("fp_op", True), review_only=True)),
    ("gate refusal at Review (fallback Review in progress)", lambda: parity(3, 41, setup=lambda x: x.w.set(FB_REVIEW, "st=SAVING;id=AB12"),
                                                                           review_only=True)),
    ("target SOC below the reserve", lambda: parity(3, 19, review_only=True)),
    ("target SOC above 100", lambda: parity(3, 101, review_only=True)),
    ("no change", lambda: parity(3, 40, review_only=True)),
    ("invalid slot 7", lambda: parity(7, 41, review_only=True)),
    ("expired review", lambda: parity(3, 41, wait=601)),
    ("wrong phrase", lambda: parity(3, 41, phrase_fn=lambda r: "SET SLOT 3 TARGET SOC 42 REVIEW " + r.code())),
    ("reserve raised after the review", lambda: parity(3, 25, setup=None, phrase_fn=None)),
]
bad = []
for name, fn in PARITY:
    a, b = fn()
    if a != b:
        bad.append((name, {k: (a[k], b[k]) for k in a if a[k] != b[k]}))
check(f"{len(PARITY)} scenarios (happy path per slot, firmware refusal, verify failure, clamp, partial writes 0-5, gate and bound refusals "
      "at Review, no change, invalid slot, expired review, wrong phrase): the Stage 0 and Stage 1 packages give the same outcome class, "
      "the same model writes (register, value and time), the same presses, the same registers and the same lock / marker / arm state",
      not bad, str(bad[:2]))
r0 = Run(legacy=True).review(3, "target_soc", 41)
r1 = Run().review(3, "target_soc", 41)
check("the Review text for a SOC edit is the same outcome class and carries the same typed phrase",
      cls(r0) == cls(r1) == "REVIEWED" and r0.phrase() == r1.phrase() == f"SET SLOT 3 TARGET SOC 41 REVIEW {r1.code()}"
      and r0.code() == r1.code(), f"{r0.res()} | {r1.res()}")

# ======================================================================================================================
print("\n[4] validation per setting, and the UK clock change nights")
# ======================================================================================================================


def at(stamp, **kw):
    """A Run whose Review lands exactly at the local time `stamp` ('YYYY-MM-DD HH:MM:SS')."""
    return Run(t0=S.parse_local(stamp) - 70, **kw)


def rejects(r):
    return r.res().startswith("REVIEW REFUSED") and r.d.presses == [] and r.w.state(PLAN) in ("", "unknown")


def accepts(r):
    return r.res().startswith("REVIEWED") and r.d.presses == [] and r.changed() == {}


def starts(*v):
    """A layout callback: set the six slot starts (HHMM)."""
    def f(d):
        for i, x in enumerate(v, 1):
            d.regs["slots"][i]["start"] = x
    return f


def slot_set(n, **kv):
    def f(d):
        d.regs["slots"][n].update(kv)
    return f


# --- power
bad = []
for v, ok in ((499, False), (500, True), (550, False), (8000, True), (8100, False), (450, False), (0, False), (-100, False), (3000.5, False),
              ("abc", False), ("", False), (3000, True), ("3000", True), (3000.0, True), (100, False), (7999, False)):
    r = Run(layout=slot_set(3, power=6000)).review(3, "power", v)
    if (accepts(r) if ok else rejects(r)) is not True:
        bad.append((v, ok, r.res()[:70]))
check("power: 499, 450, 100, 0, -100, 550, 7999, 8100, 3000.5, 'abc' and '' refused; 500, 3000, '3000', 3000.0 and 8000 accepted "
      "(whole watts, a multiple of 100, 500..8000)", not bad, str(bad))
r = Run().review(3, "power", 8000)
check("power: no change (8000 -> 8000) refused", rejects(r) and "no change (slot 3 is already 8000 W)" in r.res(), r.res())
r = Run().review(3, "power", 499)
check("power 499 W is refused with the reason: below 500 W the saved fallback profile's domain is left", "500 to 8000 W" in r.res()
      and "fallback profile" in r.res(), r.res())
r = Run().edit(3, "power", 500)
check("power 500 W, the floor, applies end to end", r.res().startswith("APPLIED") and r.changed() == {(3, "power"): (8000, 500)}, r.res())
r = Run(layout=slot_set(3, power=500)).edit(3, "power", 8000)
check("power 8000 W (the ceiling) applies end to end, from 500 W", r.res().startswith("APPLIED") and r.changed() == {(3, "power"): (500, 8000)},
      r.res())

# --- start time
bad = []
cases = [
    (3, "09:32", False), (3, "09:33", False), (3, "9:30", False), (3, "24:00", False), (3, "23:60", False), (3, "09:30:15", False),
    (3, "0930", False), (3, "", False), (3, "ab:cd", False), (3, "09-30", False), (3, "-9:30", False), (3, "09:30", True),
    (3, "09:30:00", True), (3, "05:05", True), (3, "15:55", False), (3, "05:00", False), (3, "16:00", False), (3, "04:55", False),
    (3, "16:05", False), (3, "09:00", False), (3, "04:00", False), (3, "17:00", False),
    (1, "00:05", True), (1, "04:55", True), (1, "05:00", False), (1, "23:55", False), (1, "00:00", False), (1, "00:01", False),   # acs1c let slot 1 start at 23:55, after slot 6's 23:00; acs1x refuses it (the crossing would move from slot 6 -> 1 to slot 1 -> 2)
    (6, "23:55", True), (6, "19:05", True), (6, "19:00", False), (6, "18:55", False), (6, "00:00", False), (6, "23:00", False),
    (2, "00:00", False), (2, "00:05", True), (2, "08:55", True), (2, "09:00", False),
    (5, "16:00", False), (5, "16:05", True), (5, "22:55", True), (5, "23:00", False),
]
for slot, v, ok in cases:
    r = Run().review(slot, "start_time", v)
    if (accepts(r) if ok else rejects(r)) is not True:
        bad.append((slot, v, ok, r.res()[:80]))
check(f"start time ({len(cases)} cases): off the 5-minute grid, 24:00, 23:60, seconds, malformed, equal to a neighbour, crossing a neighbour "
      "and no change refused; strictly between the neighbours accepted - slot 1 (slot 6's end) and slot 6 (slot 1's start) included; slot 1 to 23:55 "
      "(after slot 6's 23:00 round the clock, which acs1c accepted) is refused since acs1x: it would move the midnight crossing", not bad, str(bad[:4]))
r = Run().review(1, "start_time", "23:55")
check("...and that refusal names the midnight-crossing hold (the default layout's crossing is slot 6 -> 1, slot 1 starting at 00:00)",
      rejects(r) and XW.REFUSE_XW in r.res(), r.res())
r = Run().review(3, "start_time", "09:32")
check("an off-grid start time is refused with the 5-minute grid named", "5-minute grid" in r.res(), r.res())
r = Run().review(3, "start_time", "05:00")
check("a start equal to the previous slot's start is refused with the ordering named", "strictly after the previous slot" in r.res(), r.res())
bad = []
LAYOUTS = {
    "a slot start earlier than the one before (09:00 then 04:00 for slot 3)": starts(0, 500, 400, 1600, 1900, 2300),
    "two equal starts": starts(0, 500, 500, 1600, 1900, 2300),
    "slot 1 not at the start of the day, slot 6 before slot 5": starts(0, 500, 900, 1600, 2000, 1900),
    "descending": starts(2300, 1900, 1600, 900, 500, 0),
    "an unreadable start": lambda d: d.w.set(f"sensor.{D}ecco_timezone5_time", "unavailable"),
}
for label, lay in LAYOUTS.items():
    for slot, v in ((3, "09:30"), (1, "00:30"), (6, "23:30"), (2, "05:30")):
        if "unreadable" in label:
            r = Run(setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone5_time", "unavailable")).review(slot, "start_time", v)
        else:
            r = Run(layout=lay).review(slot, "start_time", v)
        if not (rejects(r) and ("24-hour cycle" in r.res() or "unavailable" in r.res())):
            bad.append((label, slot, r.res()[:80]))
check("a live layout that is not one 24-hour cycle in slot order (a slot before the one before it, two equal starts, slot 6 before slot 5 with slot 1 at 00:00, "
      "descending) or has an unreadable start refuses every start-time edit: 'unexpected TOU layout', nothing written", not bad, str(bad[:3]))
r = Run(layout=starts(0, 500, 400, 1600, 1900, 2300)).review(3, "power", 3000)
check("...but a power edit does not care about the start layout", accepts(r), r.res())
# the 15-minute guard around the old and the new boundary (circular, mod 24 h), and the "active slot right now" guard (the local time lies between
# the old and the new boundary, in the direction of the change). Expected: True (accepted), "near" (refused: within 15 minutes) or "mid" (refused:
# between the boundaries).
bad = []
NEAR_MSG, MID_MSG = "within 15 minutes", "between the old and the new boundary"
NEAR_CASES = (
        # slot 3 09:00 -> 12:00 (later: the interval [09:00, 12:00) changes from slot 3 to slot 2)
        (3, "12:00", "2026-10-12 08:44:00", True), (3, "12:00", "2026-10-12 08:45:00", "near"), (3, "12:00", "2026-10-12 08:45:01", "near"),
        (3, "12:00", "2026-10-12 08:44:30", True), (3, "12:00", "2026-10-12 08:00:00", True), (3, "12:00", "2026-10-12 09:15:00", "near"),
        (3, "12:00", "2026-10-12 09:16:00", "mid"), (3, "12:00", "2026-10-12 10:00:00", "mid"), (3, "12:00", "2026-10-12 11:44:00", "mid"),
        (3, "12:00", "2026-10-12 11:45:00", "near"), (3, "12:00", "2026-10-12 12:15:00", "near"), (3, "12:00", "2026-10-12 12:16:00", True),
        (3, "11:00", "2026-10-12 10:00:00", "mid"), (3, "11:00", "2026-10-12 08:30:00", True), (3, "11:00", "2026-10-12 11:30:00", True),
        # slot 3 09:00 -> 06:00 (earlier: the interval [06:00, 09:00) changes from slot 2 to slot 3)
        (3, "06:00", "2026-10-12 05:44:00", True), (3, "06:00", "2026-10-12 05:45:00", "near"), (3, "06:00", "2026-10-12 06:16:00", "mid"),
        (3, "06:00", "2026-10-12 07:00:00", "mid"), (3, "06:00", "2026-10-12 08:44:00", "mid"), (3, "06:00", "2026-10-12 08:45:00", "near"),
        (3, "06:00", "2026-10-12 09:15:00", "near"), (3, "06:00", "2026-10-12 09:16:00", True), (3, "06:00", "2026-10-12 09:30:00", True),
        (3, "06:00", "2026-10-12 05:30:00", True),
        # across midnight: slot 6 23:00 -> 23:55, slot 1 00:00 -> 00:30 / 04:30, slot 6 23:00 -> 19:05
        (6, "23:55", "2026-10-12 00:09:00", "near"), (6, "23:55", "2026-10-12 00:11:00", True), (6, "23:55", "2026-10-12 00:30:00", True),
        (6, "23:55", "2026-10-12 22:44:00", True), (6, "23:55", "2026-10-12 22:45:00", "near"), (6, "23:55", "2026-10-12 23:20:00", "mid"),
        (6, "23:55", "2026-10-12 23:30:00", "mid"), (6, "23:55", "2026-10-12 23:40:00", "near"),
        (1, "00:30", "2026-10-12 23:50:00", "near"), (1, "00:30", "2026-10-12 23:44:00", True), (1, "00:30", "2026-10-12 00:15:00", "near"),
        (1, "00:30", "2026-10-12 00:46:00", True),
        (1, "04:30", "2026-10-12 02:00:00", "mid"), (1, "04:30", "2026-10-12 23:30:00", True), (1, "04:30", "2026-10-12 05:00:00", True),
        (1, "04:30", "2026-10-12 00:20:00", "mid"), (1, "04:30", "2026-10-12 00:10:00", "near"), (1, "04:30", "2026-10-12 01:00:00", "mid"),
        (6, "19:05", "2026-10-12 21:00:00", "mid"), (6, "19:05", "2026-10-12 23:20:00", True), (6, "19:05", "2026-10-12 18:40:00", True))
for slot, v, stamp, ok in NEAR_CASES:
    r = at(stamp).review(slot, "start_time", v)
    if ok is True:
        got = accepts(r)
    else:
        got = rejects(r) and {"near": NEAR_MSG, "mid": MID_MSG}[ok] in r.res()
    if got is not True:
        bad.append((slot, v, stamp, ok, r.res()[:70]))
check("the 15-minute boundary guard: refused at exactly 15 min before / after the OLD or the NEW boundary (also across midnight, slot 1 and "
      "slot 6), accepted at 16 min; and a start-time edit is refused while the local time lies between the old and the new boundary (it would "
      "change the active slot right now) - later and earlier moves, across midnight - with the reason named (" + str(len(NEAR_CASES)) + " cases)", not bad, str(bad[:4]))
r = at("2026-10-12 08:50:00").review(3, "power", 3000)
check("...the guard applies to start-time edits only (a power edit 10 minutes before a boundary is fine)", accepts(r), r.res())
r = at("2026-10-12 08:44:00").edit(3, "start_time", "12:00")
check("a start-time edit whose clock then runs into the 15-minute zone before the Apply's last gates (08:44 at the Review): FAILED, "
      "nothing pressed, nothing written", r.res().startswith("FAILED") and "within 15 minutes" in r.res() and r.d.presses == []
      and r.changed() == {}, f"{r.res()} {r.d.presses}")

# the inverter runs its TOU slots on its OWN clock: a start-time edit is refused when Inverter Time (published once a minute) is more than 120 s
# from Home Assistant's clock, or unreadable
bad = []
for label, val, ok in (("in step", 0, True), ("+119 s", 119, True), ("-100 s", -100, True), ("+121 s", 121, False), ("-121 s", -121, False),
                       ("+3 h", 10800, False), ("-1 h", -3600, False)):
    r = Run(setup=lambda x, v_=val: x.w.set(M.CLOCK, S.local_str(x.w.t + v_))).review(3, "start_time", "09:30")
    if (accepts(r) if ok else (rejects(r) and "inverter clock" in r.res())) is not True:
        bad.append((label, r.res()[:80]))
for label, val in (("unavailable", "unavailable"), ("unknown", "unknown"), ("empty", ""), ("garbage", "not a time"), ("date only", "2026-10-12")):
    r = Run(setup=lambda x, v_=val: x.w.set(M.CLOCK, v_)).review(3, "start_time", "09:30")
    if not (rejects(r) and "inverter clock" in r.res()):
        bad.append((label, r.res()[:80]))
    for setting in ("target_soc", "power", "charge_source"):
        r = Run(setup=lambda x, v_=val: x.w.set(M.CLOCK, v_)).review(3, setting, value_for(3, setting))
        if not accepts(r):
            bad.append((label, setting, r.res()[:60]))
check("start time vs the inverter's own clock: Inverter Time within 120 s of Home Assistant's (either way) accepted; 121 s, hours off, "
      "unavailable, unknown, empty, garbage or date-only refused with 'inverter clock' named; no other setting is affected", not bad, str(bad[:4]))
r = Run().review(3, "start_time", "09:30")
r.w.set(M.CLOCK, S.local_str(r.w.t + 400))
r.apply(run=5)
check("the inverter clock drifting away between the Review and the Apply: refused at the Apply, nothing pressed, nothing written",
      r.res().startswith("REFUSED") and "inverter clock" in r.res() and r.d.presses == [] and r.changed() == {}, r.res())
r2 = Run().edit(3, "start_time", "09:30")
check("with the normal minute-by-minute clock read the staleness of Inverter Time (up to 60 s) never trips the guard: the happy path applies",
      r2.res().startswith("APPLIED") and r2.changed() == {(3, "start"): (900, 930)}, r2.res())

# the firmware publishes "?%u" for an out-of-range start word (and the live starts must be HH:MM): every one of the six is validated
bad = []
MALFORMED = ("?2475", "?0", "9:30", "24:00", "09:60", "ab:cd", "09-30", "0930 ", " 0930", "09:3", "09:300", "unknown", "unavailable", "")
for label_n in range(1, 7):
    for mal in MALFORMED:
        r = Run(setup=lambda x, k=label_n, m_=mal: x.w.set(f"sensor.{D}ecco_timezone{k}_time", m_)).review(3, "start_time", "09:30")
        # (the slot's OWN value "9:30" etc. reads as 09:30 = no change: still a refusal, by the no-change rule)
        if not (rejects(r) and ("24-hour cycle" in r.res() or "unavailable" in r.res() or "no change" in r.res())):
            bad.append((label_n, mal, r.res()[:70]))
    r = Run(setup=lambda x, k=label_n: x.w.set(f"sensor.{D}ecco_timezone{k}_time", "?2475")).review(3, "power", 3000)
    if not accepts(r):
        bad.append((label_n, "power edit", r.res()[:60]))
check(f"a malformed live start (\"?2475\", a bare \"9:30\", 24:00, 09:60, padded, empty, unavailable, ...) in ANY of the six slots - own, previous or "
      f"next neighbour or a distant one - refuses a start-time edit (fail closed: 6 slots x {len(MALFORMED)} forms); a power edit is unaffected",
      not bad, str(bad[:4]))
r = Run(setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone2_time", "?2475")).review(3, "start_time", "09:30")
check("...the case that a naive parse would let through: \"?2475\" as slot 2's start (read as 15 minutes, 'in order') is refused", rejects(r)
      and "24-hour cycle" in r.res(), r.res())

# ======================================================================================================================
print("\n[4c] acs1c: the six starts as one 24-hour cycle in slot order (the owner's wrap layout and its kin)")
# ======================================================================================================================
sys.path.insert(0, str(ROOT / "registry"))
import fallback_capture as FC  # noqa: E402  (the fallback capture's ring rule: the project's existing cyclic predicate for the six starts)
import random  # noqa: E402

OWNER_STARTS = (30, 530, 1200, 1635, 2200, 25)        # the owner's live layout by slot number (HHMM): slot 5 runs 22:00 -> 00:25, slot 6 00:25 -> 00:30
OWNER_LAYOUT = starts(*OWNER_STARTS)
NOON = S.parse_local("2026-10-26 12:00:00") - 70      # a Review at 12:00 local, slot 3's own boundary: fine for every slot but 3
TWO_AM = S.parse_local("2026-10-26 02:00:00") - 70    # inside slot 1 (00:30 -> 05:30): fine for the slot 3 and 4 cases
OWNER_ORDER_REFUSALS = ((6, "00:30"), (6, "00:35"), (1, "00:25"), (1, "00:20"), (5, "00:25"), (5, "16:35"), (2, "00:30"), (4, "22:00"))
SEVEN_AM = S.parse_local("2026-10-26 07:00:00") - 70   # for the two-wrap layout cases: outside the window the (then meaningless) active-slot guard spans
TWO_PM = S.parse_local("2026-10-26 14:00:00") - 70     # for the off-grid slot 3 cases: clear of 12:02 and 09:30


def owner_full(d):
    """The owner's full 25 Oct baseline: the six starts, 8000 W everywhere, slot 1 100 % / Grid, slots 2-6 0 % / None, mode General."""
    for i, x in enumerate(OWNER_STARTS, 1):
        d.regs["slots"][i].update(start=x, power=8000, soc=100 if i == 1 else 0, src="Grid" if i == 1 else "None", mode="General")


def c_mins(hhmm_):
    return (hhmm_ // 100) * 60 + hhmm_ % 100


def c_hhmm(m):
    return (m // 60) * 100 + m % 60


def c_txt(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def c_cls(r):
    """The outcome class of a Review: the first refusal the gate named, or 'accept'."""
    s = r.res()
    if s.startswith("REVIEWED"):
        return "accept"
    for k, t in (("crossing", "midnight crossing"), ("cycle2", "would not leave one valid 24-hour cycle"), ("cycle", "24-hour cycle"), ("order", "strictly after the previous slot"),
                 ("near", "within 15 minutes"), ("mid", "between the old and the new boundary"), ("nochange", "no change"), ("unavailable", "unavailable")):
        if t in s:
            return k
    return "other:" + s[:60]


OWNER_MIN = [c_mins(x) for x in OWNER_STARTS]
check("the owner's layout is one 24-hour cycle in slot order: gaps 300, 390, 275, 325, 145 and 5 minutes (slot 5 past midnight, slot 6 five minutes), "
      "every start on the grid, and the fallback capture's ring rule agrees", C.is_cycle(OWNER_MIN) and C.gaps(OWNER_MIN) == [300, 390, 275, 325, 145, 5]
      and FC.ring_valid([0] * 22 + list(OWNER_STARTS)) and all(FC.on_5min_grid(x) for x in OWNER_STARTS))
r = Run(S1B, layout=OWNER_LAYOUT, t0=NOON).review(1, "start_time", "00:35")
r2 = Run(S1B, layout=OWNER_LAYOUT, t0=NOON).review(2, "start_time", "05:35")
check("L1 reproduced on the Stage 1 text of 2026-10-25 (the package installed that day): a start-time Review of the owner's layout was refused as "
      "'not strictly ascending (unexpected TOU layout)', nothing written - the limitation the acs1c layer removes",
      rejects(r) and rejects(r2) and "strictly ascending" in r.res() and "strictly ascending" in r2.res(), f"{r.res()[:80]} | {r2.res()[:80]}")
# --- the owner's baseline, slot by slot: every neighbour relation, including slot 1 <-> 6 and 5 <-> 6
OWNER_CASES = (
    # slot 1 (00:30; previous slot 6 at 00:25, next slot 2 at 05:30)
    (1, "00:35", "accept"), (1, "05:25", "accept"), (1, "00:25", "order"), (1, "00:20", "order"), (1, "05:30", "order"), (1, "05:35", "order"),
    (1, "23:55", "order"), (1, "00:30", "nochange"),
    # slot 2 (05:30; between 00:30 and 12:00)
    (2, "05:35", "accept"), (2, "00:35", "accept"), (2, "11:00", "accept"), (2, "11:55", "near"), (2, "00:30", "order"), (2, "12:00", "order"),
    (2, "05:30", "nochange"),
    # slot 3 (12:00; between 05:30 and 16:35)
    (3, "12:05", "accept"), (3, "05:35", "accept"), (3, "16:30", "accept"), (3, "05:30", "order"), (3, "16:35", "order"), (3, "00:30", "order"),
    # slot 4 (16:35; between 12:00 and 22:00)
    (4, "16:40", "accept"), (4, "21:55", "accept"), (4, "12:05", "accept"), (4, "22:00", "order"), (4, "12:00", "order"),
    # slot 5 (22:00; between 16:35 and slot 6's 00:25 the next day: the slot that runs past midnight). acs1c accepted 00:00 .. 00:20; acs1x
    # refuses them (slot 4 would run past midnight: the crossing would move from slot 5 -> 6 to slot 4 -> 5)
    (5, "21:55", "accept"), (5, "23:55", "accept"), (5, "00:00", "crossing"), (5, "00:05", "crossing"), (5, "00:20", "crossing"), (5, "16:40", "accept"),
    (5, "00:25", "order"), (5, "00:30", "order"), (5, "16:35", "order"), (5, "16:30", "order"), (5, "22:00", "nochange"),
    # slot 6 (00:25; between 22:00 the day before and slot 1's 00:30: the five-minute slot). acs1c accepted 22:05 .. 23:55; acs1x refuses them
    # (slot 6 would run past midnight: the crossing would move from slot 5 -> 6 to slot 6 -> 1)
    (6, "00:20", "accept"), (6, "00:00", "accept"), (6, "23:55", "crossing"), (6, "22:05", "crossing"), (6, "00:30", "order"), (6, "00:35", "order"),
    (6, "22:00", "order"), (6, "21:55", "order"), (6, "00:25", "nochange"),
)
c_bad = []
for slot, v, exp in OWNER_CASES:
    t0_ = TWO_AM if slot in (3, 4) else NOON
    r = Run(layout=OWNER_LAYOUT, t0=t0_).review(slot, "start_time", v)
    now_min = 120 if slot in (3, 4) else 720
    model = XW.verdict(C.verdict(OWNER_MIN, slot, c_mins(hhmm_of(v)), now_min), OWNER_MIN, slot, c_mins(hhmm_of(v)))
    if c_cls(r) != exp or model != exp or (exp == "accept") != accepts(r) or (exp != "accept" and not rejects(r)) or len(r.res()) >= 255:
        c_bad.append((slot, v, exp, c_cls(r), model, r.res()[:70]))
check(f"the owner's baseline, every slot ({len(OWNER_CASES)} named cases): a new start strictly between the previous and the next slot's start, counted round "
      "the clock, is accepted (slot 1 after slot 6's 00:25, slot 6 before slot 1's 00:30 down to 00:00, slot 5 up to 23:55) unless it would move the "
      "midnight crossing (acs1x: slot 5 past midnight, slot 6 before it); equal to or beyond a neighbour is refused with the neighbour rule named; no "
      "change refused; the reference model agrees; every result text fits the input_text",
      not c_bad, str(c_bad[:4]))
r = Run(layout=OWNER_LAYOUT, t0=NOON).review(5, "start_time", "23:55")
r2 = Run(layout=OWNER_LAYOUT, t0=NOON).review(1, "start_time", "00:35")
check("the Review notification names the two windows that result: slot 5 23:55-00:25 and slot 4 16:35-23:55; slot 1 00:35-05:30 and slot 6 00:25-00:35 - "
      "and says that register 254 / 250 is also the previous slot's end",
      "Slot 5 will then run 23:55-00:25 and slot 4 16:35-23:55" in r.note("ecco_cfg_edit_review") and "also the end of slot 4" in r.note("ecco_cfg_edit_review")
      and "Slot 1 will then run 00:35-05:30 and slot 6 00:25-00:35" in r2.note("ecco_cfg_edit_review") and "also the end of slot 6" in r2.note("ecco_cfg_edit_review"),
      r.note("ecco_cfg_edit_review")[:300])
c_bad = []
for n_ in range(1, 7):
    pv_ = 6 if n_ == 1 else n_ - 1
    want_prev = f"sensor.{D}ecco_timezone{pv_}_time"
    maps = re.findall(r"\n\s+%d: \{'reg_soc'.*?\}" % n_, S1, flags=re.S)
    if not (len(maps) == 2 and all(f"'live_t_prev': '{want_prev}'" in m_ for m_ in maps) and S1.count(f"'live_t_prev': '{want_prev}'") == 2):
        c_bad.append((n_, "map", len(maps)))
    new_ = (c_mins(OWNER_STARTS[n_ - 1]) + (-5 if n_ == 6 else 5)) % 1440      # slot 6 lasts five minutes: +5 would be slot 1's start
    r = Run(layout=OWNER_LAYOUT, t0=TWO_AM if n_ in (3, 4) else NOON).review(n_, "start_time", c_txt(new_))
    nxt, prv = OWNER_STARTS[n_ % 6], OWNER_STARTS[pv_ - 1]
    want_text = f"Slot {n_} will then run {c_txt(new_)}-{nxt // 100:02d}:{nxt % 100:02d} and slot {pv_} {prv // 100:02d}:{prv % 100:02d}-{c_txt(new_)}"
    if not (accepts(r) and want_text in r.note("ecco_cfg_edit_review") and f"also the end of slot {pv_}" in r.note("ecco_cfg_edit_review")):
        c_bad.append((n_, c_txt(new_), r.res()[:40], r.note("ecco_cfg_edit_review")[:120]))
check("every slot's map entry (Review and Apply copies) names the previous slot's live start sensor (slot 6's for slot 1), and a 5-minute Review of every "
      "slot (later; earlier for the five-minute slot 6) names its two resulting windows with the previous slot's live start", not c_bad, str(c_bad[:3]))
# --- the same schedule under every slot numbering (rotation): the verdicts do not depend on where the wrap sits
c_bad = []
ROT_CASES = ((5, "00:05", "crossing"), (6, "00:20", "accept"), (1, "00:35", "accept"), (6, "00:30", "order"), (1, "00:25", "order"), (5, "00:25", "order"),
             (6, "23:55", "crossing"), (5, "23:55", "accept"))
for rot in range(6):
    lay = OWNER_STARTS[rot:] + OWNER_STARTS[:rot]          # slot 1 is now the owner's slot rot+1
    lay_min = [c_mins(x) for x in lay]
    for slot, v, exp in ROT_CASES:
        s_ = (slot - 1 - rot) % 6 + 1                       # the owner's slot `slot` under this numbering
        r = Run(layout=starts(*lay), t0=NOON).review(s_, "start_time", v)
        if c_cls(r) != exp or XW.verdict(C.verdict(lay_min, s_, c_mins(hhmm_of(v)), 720), lay_min, s_, c_mins(hhmm_of(v))) != exp:
            c_bad.append((rot, s_, v, exp, c_cls(r)))
check(f"slot rotation: the owner's schedule under all six slot numberings (the wrap between slots 5/6, 4/5, ... 6/1) gives the same verdicts for the same "
      f"physical edits ({6 * len(ROT_CASES)} cases): accepted up to the wrap, refused at a neighbour, refused where the edit would move the crossing "
      "(acs1x: the hold follows the physical crossing, not a slot number)", not c_bad, str(c_bad[:4]))
# --- layouts that are not one cycle: refused with the cycle rule named, for every slot; every other setting is unaffected
BAD_LAYOUTS = {
    "two wraps (slot 6 at 13:00: the slots go round the clock twice)": (30, 530, 1200, 1635, 2200, 1300),
    "two equal starts (slots 2 and 3)": (30, 530, 530, 1635, 2200, 25),
    "an off-grid start in a distant slot (slot 3 at 12:02)": (30, 530, 1202, 1635, 2200, 25),
    "an off-grid start in the edited slot (slot 2 at 05:32: its undo could never be typed)": (30, 532, 1200, 1635, 2200, 25),
    "a slot shorter than 5 minutes (slot 6 at 00:27)": (30, 530, 1200, 1635, 2200, 27),
    "descending": (2300, 1900, 1600, 900, 500, 0),
    "all six equal": (30, 30, 30, 30, 30, 30),
    "a slot at 24:00 (the firmware would publish ?2400)": (30, 530, 1200, 1635, 2200, 2400),
}
c_bad = []
for label, lay in BAD_LAYOUTS.items():
    lay_min = [c_mins(x) if (x // 100 <= 23 and x % 100 <= 59) else -1 for x in lay]
    for slot in range(1, 7):
        v = "05:35" if slot == 2 else c_txt((((lay_min[slot - 1] + 5) // 5) * 5) % 1440 if lay_min[slot - 1] >= 0 else 0)
        r = Run(layout=starts(*lay), t0=NOON).review(slot, "start_time", v)
        model = XW.verdict(C.verdict(lay_min, slot, c_mins(hhmm_of(v)), 720), lay_min, slot, c_mins(hhmm_of(v)))
        agree = c_cls(r) == model or (model == "unavailable" and c_cls(r) == "cycle")   # "24:00": numeric for the template, unreadable for the model
        if not (rejects(r) and c_cls(r) in ("cycle", "unavailable", "nochange", "near") and agree):
            c_bad.append((label, slot, v, c_cls(r), model, r.res()[:60]))
    for setting in ("target_soc", "power", "charge_source"):
        r = Run(layout=starts(*lay), t0=NOON).review(3, setting, value_for(3, setting))
        if not accepts(r):
            c_bad.append((label, setting, r.res()[:60]))
check(f"a live layout that is not one 24-hour cycle ({len(BAD_LAYOUTS)} kinds: two wraps, equal starts, an off-grid start in a distant or in the edited slot, "
      "a slot under 5 minutes, descending, all equal, a 24:00 word) refuses a start-time edit of EVERY slot with the cycle rule named (fail closed; the "
      "reference model agrees), and a target SOC, power or charge-source edit on the same layout is unaffected", not c_bad, str(c_bad[:4]))
# --- the active-slot-now guard on a window that crosses midnight: slot 5 22:00 -> 00:05 changes the owner of [22:00, 00:05). Since acs1x the
# installed package refuses every such edit first (it moves the midnight crossing); the guard's lines are inherited byte for byte ([0x]), so
# they are exercised on the acs1c text (S1C, the acs1x base), and the installed package is shown to refuse every case with the hold.
c_bad = []
MID_WRAP = (("12:00:00", "accept"), ("21:44:00", "accept"), ("21:45:00", "near"), ("22:15:00", "near"), ("22:16:00", "mid"), ("23:00:00", "mid"),
            ("23:49:00", "mid"), ("23:50:00", "near"), ("00:05:00", "near"), ("00:20:00", "near"), ("00:21:00", "accept"), ("03:00:00", "accept"))
for hm, exp in MID_WRAP:
    r = Run(S1C, layout=OWNER_LAYOUT, t0=S.parse_local("2026-10-26 " + hm) - 70).review(5, "start_time", "00:05")
    rx = at("2026-10-26 " + hm, layout=OWNER_LAYOUT).review(5, "start_time", "00:05")
    now_min = int(hm[:2]) * 60 + int(hm[3:5])
    if c_cls(r) != exp or C.verdict(OWNER_MIN, 5, 5, now_min) != exp or c_cls(rx) != "crossing" or not rejects(rx):
        c_bad.append((hm, exp, c_cls(r), c_cls(rx)))
# and the move back across midnight: slot 5 00:05 -> 22:00 on the moved layout changes the owner of the same window
MOVED = starts(30, 530, 1200, 1635, 5, 25)
for hm, exp in (("12:00:00", "accept"), ("23:00:00", "mid"), ("00:21:00", "accept"), ("21:50:00", "near")):
    r = Run(S1C, layout=MOVED, t0=S.parse_local("2026-10-26 " + hm) - 70).review(5, "start_time", "22:00")
    rx = at("2026-10-26 " + hm, layout=MOVED).review(5, "start_time", "22:00")
    if c_cls(r) != exp or c_cls(rx) != "crossing":
        c_bad.append(("back", hm, exp, c_cls(r), c_cls(rx)))
check(f"the active-slot-now guard across midnight ({len(MID_WRAP) + 4} cases, on the acs1c text): moving slot 5's start from 22:00 to 00:05 (and back) is "
      "refused between 22:16 and 23:49 local ('between the old and the new boundary': the owner of that window changes), refused within 15 minutes of "
      "either boundary, and accepted at 12:00, 21:44, 00:21 and 03:00 - a linear comparison of the two HH:MM values would have refused the daytime "
      "cases; the installed package refuses all of them with the crossing hold (acs1x), at every one of those times", not c_bad, str(c_bad[:4]))
c_bad = []
MID_SIX = (("12:00:00", "accept"), ("22:44:00", "accept"), ("22:45:00", "near"), ("23:15:00", "near"), ("23:16:00", "mid"), ("00:00:00", "mid"), ("00:09:00", "mid"),
           ("00:10:00", "near"), ("00:25:00", "near"), ("00:40:00", "near"), ("00:41:00", "accept"), ("03:00:00", "accept"))
for hm, exp in MID_SIX:
    r = Run(S1C, layout=OWNER_LAYOUT, t0=S.parse_local("2026-10-26 " + hm) - 70).review(6, "start_time", "23:00")
    rx = at("2026-10-26 " + hm, layout=OWNER_LAYOUT).review(6, "start_time", "23:00")
    now_min = int(hm[:2]) * 60 + int(hm[3:5])
    if c_cls(r) != exp or C.verdict(OWNER_MIN, 6, 23 * 60, now_min) != exp or c_cls(rx) != "crossing":
        c_bad.append((hm, exp, c_cls(r), c_cls(rx)))
check(f"the five-minute slot 6 moved back across midnight (00:25 -> 23:00; {len(MID_SIX)} cases, on the acs1c text): refused between 23:16 and 00:09 local "
      "(the owner of that window changes from slot 5 to slot 6), refused within 15 minutes of 23:00 or 00:25, accepted at 12:00, 22:44, 00:41 and 03:00; "
      "the installed package refuses all of them with the crossing hold (acs1x)", not c_bad, str(c_bad[:4]))
# a review record that was not written by the Review (hand-edited input_text): the Apply's own copy of the gate re-checks the value's form
c_bad = []
for bad_want, why in ((2400, "24:00"), (2475, "24:75"), (1275, "12:75"), (1233, "off the grid"), (2360, "23:60"), (99999, "nonsense")):
    r = Run(layout=OWNER_LAYOUT, t0=NOON).review(5, "start_time", "21:55")
    rec = r.w.state(PLAN).split("|")
    rec[2] = str(bad_want)
    r.w.set(PLAN, "|".join(rec))
    r.apply(phrase=f"SET SLOT 5 START {bad_want // 100:02d}:{bad_want % 100:02d} REVIEW {rec[3]}", run=120)
    if not (r.res().startswith("REFUSED") and "5-minute grid" in r.res() and r.applies() == [] and r.loads() == [] and r.changed() == {} and not r.arm_on()):
        c_bad.append((bad_want, why, r.res()[:70], r.loads()))
check("a review record whose value is not a well-formed HH:MM on the grid (2400, 2475, 1275, 1233, 2360, 99999 written into the record by hand, with the "
      "matching phrase): the Apply's own gate refuses it with the grid rule named before any Load, nothing pressed, nothing written (the cyclic window counts "
      "modulo 24 h and would not have refused 2400 by itself; review finding, 2026-10-25)", not c_bad, str(c_bad[:3]))
# --- the other start-time guards still hold on the wrap layout
c_bad = []
for label, kw in (("the inverter clock 400 s off", dict(setup=lambda x: x.w.set(M.CLOCK, S.local_str(x.w.t + 400)))),
                  ("the inverter clock unreadable", dict(setup=lambda x: x.w.set(M.CLOCK, "unavailable"))),
                  ("a fallback Save in progress", dict(setup=lambda x: x.w.set(FB_REVIEW, "st=SAVING;id=AB12"))),
                  ("an RTC flag unavailable (fail closed)", dict(setup=lambda x: x.w.set(f"binary_sensor.{D}rtc_correction_in_progress", "unavailable"))),
                  ("the UK clock change night", dict(t0=S.parse_local("2026-10-25 01:30:00") - 70))):
    kw2 = dict(layout=OWNER_LAYOUT, t0=NOON)
    kw2.update(kw)
    r = Run(**kw2).review(2, "start_time", "05:35")
    if not rejects(r):
        c_bad.append((label, r.res()[:60]))
check("on the wrap layout an otherwise valid start-time edit is still refused by the inverter-clock rule (off or unreadable), a fallback Save in progress, "
      "an unavailable RTC flag and the clock-change night (the acs1c layer changed the ordering rule only)", not c_bad, str(c_bad))
# --- seeded fuzz: the template against the reference model on random cycles (random wrap position), random edits and random local times
rng = random.Random(20261025)


def rand_cycle():
    pts = sorted(rng.sample(range(0, 1440, 5), 6))
    rot = rng.randrange(6)
    return pts[rot:] + pts[:rot]


FUZZ, fuzz_bad, fuzz_seen = [], [], Counter()
while len(FUZZ) < 120:
    lay = rand_cycle()
    kind = rng.choice(["valid"] * 8 + ["dup", "twowrap", "offgrid", "unreadable"])
    unread = None
    if kind == "dup":
        i, j = rng.sample(range(6), 2)
        lay[i] = lay[j]
    elif kind == "twowrap":
        i, j = sorted(rng.sample(range(6), 2))
        lay[i], lay[j] = lay[j], lay[i]
    elif kind == "offgrid":
        lay[rng.randrange(6)] += rng.choice((1, 2, 3, 4))
    elif kind == "unreadable":
        unread = rng.randrange(6)
    n = rng.randrange(1, 7)
    pv, nx = lay[(n + 4) % 6], lay[n % 6]
    choice = rng.choice(["inside"] * 3 + ["neighbour", "beyond", "anywhere", "anywhere", "same"])
    arc = (nx - pv) % 1440
    if choice == "inside" and arc > 10:
        new = (pv + rng.randrange(5, arc, 5)) % 1440
    elif choice == "neighbour":
        new = rng.choice((pv, nx))
    elif choice == "beyond":
        new = (nx + rng.randrange(5, 120, 5)) % 1440
    elif choice == "same":
        new = lay[n - 1]
    else:
        new = rng.randrange(0, 1440, 5)
    dice = rng.random()
    if dice < 0.3 and kind == "valid":                            # the local time inside the window the edit changes (the 'mid' cases)
        lo_, hi_ = sorted(((lay[n - 1] - pv) % 1440, (new - pv) % 1440))
        now_min = (pv + rng.randrange(lo_, hi_ + 1)) % 1440 if hi_ > lo_ else rng.randrange(0, 1440)
    elif dice < 0.45 and kind == "valid":                         # within 15 minutes of the old or the new boundary (the 'near' cases)
        now_min = (rng.choice((lay[n - 1], new)) + rng.randrange(-14, 15)) % 1440
    else:
        now_min = rng.randrange(0, 1440)
    model_lay = [(-1 if unread == k else lay[k]) for k in range(6)]
    if any(min((now_min - b) % 1440, (b - now_min) % 1440) == 15 for b in (lay[n - 1], new)):
        continue                                                # exactly 15.0 minutes: both say near, but the clock has seconds
    FUZZ.append((lay, unread, n, new, now_min, model_lay))
for lay, unread, n, new, now_min, model_lay in FUZZ:
    layout = starts(*[c_hhmm(v) for v in lay])
    setup = (lambda x, k=unread: x.w.set(f"sensor.{D}ecco_timezone{k + 1}_time", "unavailable")) if unread is not None else None
    r = at(f"2026-10-26 {c_txt(now_min)}:00", layout=layout, setup=setup).review(n, "start_time", c_txt(new))
    exp = XW.verdict(C.verdict(model_lay, n, new, now_min), model_lay, n, new)
    fuzz_seen[exp] += 1
    if c_cls(r) != exp or (exp == "accept") != accepts(r) or (exp != "accept") != rejects(r):
        fuzz_bad.append((lay, unread, n, c_txt(new), c_txt(now_min), exp, c_cls(r), r.res()[:60]))
check(f"seeded fuzz ({len(FUZZ)} cases: random cycles with the wrap anywhere, random slot, a new start inside the window, at a neighbour, beyond it or anywhere, "
      f"a random local time; plus duplicate, two-wrap, off-grid and unreadable layouts): the template's verdict is the reference model's in every case "
      f"(classes seen: {dict(fuzz_seen)}); the wrap-aware window, the unwrapped active-slot guard and (acs1x) the crossing hold are all reached", not fuzz_bad
      and fuzz_seen["accept"] >= 10 and fuzz_seen["order"] >= 5 and fuzz_seen["cycle"] >= 5 and fuzz_seen["mid"] >= 3 and fuzz_seen["near"] >= 3
      and fuzz_seen["nochange"] >= 1 and fuzz_seen["crossing"] >= 3, str(fuzz_bad[:3]) + " " + str(dict(fuzz_seen)))
# --- properties of the reference model (plain Python, many cases): the rules the template computes


def active_slot(lay, now_min):
    """The slot (1-6) that owns the minute `now_min` on the ring `lay`: the slot whose start is the latest at or before now, round the clock."""
    return 1 + min(range(6), key=lambda k: (now_min - lay[k]) % 1440)


PROP_N, prop_bad, unreachable = 20000, [], 0
for _ in range(PROP_N):
    lay = rand_cycle()
    kind = rng.choice(["valid"] * 3 + ["dup", "twowrap", "offgrid"])
    if kind == "dup":
        i, j = rng.sample(range(6), 2)
        lay[i] = lay[j]
    elif kind == "twowrap":
        i, j = sorted(rng.sample(range(6), 2))
        lay[i], lay[j] = lay[j], lay[i]
    elif kind == "offgrid":
        lay[rng.randrange(6)] += rng.choice((1, 2, 3, 4))
    words = [0] * 22 + [c_hhmm(v) for v in lay]
    ring = FC.ring_valid(words) and all(FC.on_5min_grid(w) for w in words[22:28])
    if C.is_cycle(lay) != ring:                                  # the editor's cycle rule == the fallback capture's ring rule + the grid
        prop_bad.append(("ring", lay))
    n = rng.randrange(1, 7)
    new = rng.randrange(0, 1440, 5)
    now_min = rng.randrange(0, 1440)
    v = C.verdict(lay, n, new, now_min)
    cyc = C.is_cycle(lay)
    pv, nx = lay[(n + 4) % 6], lay[n % 6]
    order = 0 < (new - pv) % 1440 < (nx - pv) % 1440
    proposed = list(lay)
    proposed[n - 1] = new
    if cyc and new != lay[n - 1] and (order != C.is_cycle(proposed)):   # the neighbour rule == the proposed-layout rule (one slot changed)
        prop_bad.append(("equivalence", lay, n, new))
    if v == "cycle2":
        unreachable += 1
    if v in ("accept", "near", "mid"):
        if not (C.is_cycle(proposed) and sum(C.gaps(proposed)) == 1440 and all(d >= 5 for d in C.gaps(proposed))
                and [x for k, x in enumerate(proposed) if k != n - 1] == [x for k, x in enumerate(lay) if k != n - 1]
                and C.gaps(proposed)[(n + 4) % 6] + C.gaps(proposed)[n - 1] == C.gaps(lay)[(n + 4) % 6] + C.gaps(lay)[n - 1]):
            prop_bad.append(("partition", lay, n, new))
        if v == "accept" and (min((now_min - lay[n - 1]) % 1440, (lay[n - 1] - now_min) % 1440) <= 15
                              or min((now_min - new) % 1440, (new - now_min) % 1440) <= 15):
            prop_bad.append(("near-missed", lay, n, new, now_min))
    if cyc and new != lay[n - 1]:
        if (v == "order") != (not FC.ring_valid([0] * 22 + [c_hhmm(x) for x in proposed])):   # 'order' iff the proposed layout breaks the ring rule
            prop_bad.append(("order-oracle", lay, n, new))
        if v in ("accept", "mid") and (v == "mid") != (active_slot(lay, now_min) != active_slot(proposed, now_min)):   # 'mid' iff the owner of now changes
            prop_bad.append(("mid-oracle", lay, n, new, now_min))
    rot = rng.randrange(6)
    rl = lay[rot:] + lay[:rot]
    if C.verdict(rl, (n - 1 - rot) % 6 + 1, new, now_min) != v:   # rotation invariance
        prop_bad.append(("rotation", lay, n, new, rot))
    if (v == "nochange") != (new == lay[n - 1]) and lay[n - 1] >= 0:
        prop_bad.append(("nochange", lay, n, new))
check(f"the reference model over {PROP_N} random cases: its cycle rule equals the fallback capture's ring rule plus the 5-minute grid; for a one-slot change the "
      "neighbour rule and the proposed-layout rule are equivalent (so the proposed-layout branch is defence in depth: reached "
      f"{unreachable} times); 'order' is refused exactly when the proposed layout breaks the ring rule and 'mid' exactly when the owner of the current "
      "minute would change (two independent oracles); an accepted edit keeps the other five starts, the 1440-minute partition and the two gaps around "
      "the moved boundary summing to the old window; nothing within 15 minutes of a boundary is accepted; verdicts are invariant under slot rotation",
      not prop_bad and unreachable == 0, str(prop_bad[:3]))
# --- defence in depth, shown on in-memory mutants (NOT kills: each rule alone still refuses every crossing case of the owner's baseline)
S1_NO_ORDER = S1.replace("{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}", "{% elif false %}")
S1_NO_CYC2 = S1.replace("{% elif setting == 'start_time' and not cyc2 %}", "{% elif false %}")
assert S1_NO_ORDER != S1 and S1_NO_CYC2 != S1
c_bad = []
for label, text_, said in (("without the neighbour rule", S1_NO_ORDER, "would not leave one valid 24-hour cycle"),
                           ("without the proposed-layout rule", S1_NO_CYC2, "strictly after the previous slot")):
    for slot, v in OWNER_ORDER_REFUSALS:
        r = Run(text_, layout=OWNER_LAYOUT, t0=NOON).review(slot, "start_time", v)
        if not (rejects(r) and said in r.res()):
            c_bad.append((label, slot, v, r.res()[:50]))
    for slot, v in ((1, "00:35"), (6, "00:20"), (5, "23:55")):
        r = Run(text_, layout=OWNER_LAYOUT, t0=NOON).review(slot, "start_time", v)
        if not accepts(r):
            c_bad.append((label, slot, v, r.res()[:50]))
check("defence in depth: with the neighbour rule removed the proposed-layout rule alone still refuses every crossing case of the owner's baseline, with "
      "its own text ('would not leave one valid 24-hour cycle'), and with the proposed-layout rule removed the neighbour rule alone still does, with its "
      "text; the accepted edits stay accepted either way (the two rules are equivalent, checked above; [12] kills the mutant that drops both)",
      not c_bad, str(c_bad[:3]))
# --- forward and undo Applies on the owner's baseline: every slot, slot 5 across midnight; exactly one register, counter +1, F1 Load of slot N-1
c_bad = []
REVERSE = ((1, "00:35", NOON), (2, "05:25", NOON), (3, "12:05", TWO_AM), (4, "16:30", TWO_AM), (5, "23:55", NOON), (6, "00:20", NOON), (6, "00:00", NOON))


def slot_writes(r, slot, start, end):
    """The registers the firmware wrote for one Apply of `slot`, in order: 232, the start (249+N), the end (the next slot's start register; 250 for
    slot 6), power, SOC, flags - the start at the request, the end at the next slot's unchanged start."""
    soc, src = (100, "Grid") if slot == 1 else (0, "None")
    return [(w[1], w[2]) for w in r.d.writes] == [(232, r.d.staged_gc), (249 + slot, start), (250 if slot == 6 else 250 + slot, end), (255 + slot, 8000),
                                                   (267 + slot, soc), (273 + slot, 0)]


for slot, v, t0_ in REVERSE:
    pv = 6 if slot == 1 else slot - 1
    old, new = OWNER_STARTS[slot - 1], hhmm_of(v)
    r = Run(layout=owner_full, t0=t0_)
    r.d._load(pv)                                        # slot N-1 was Loaded earlier: its staged end holds the old boundary (F1 refreshes it)
    r.w.run_until(r.w.t + 1)
    loads0 = len(r.loads())
    r.edit(slot, "start_time", v, run=480)
    fwd = (r.res().startswith("APPLIED AND VERIFIED") and r.changed() == {(slot, "start"): (old, new)} and len(r.applies()) == 1
           and len(r.loads()) - loads0 == 2 and r.d.attempts == 1 and r.d.staging[pv]["end"] == new and not r.locked() and not r.arm_on()
           and r.d.regs["slots"][slot % 6 + 1]["start"] == OWNER_STARTS[slot % 6] and "refreshed by the editor" in r.note()
           and slot_writes(r, slot, new, OWNER_STARTS[slot % 6]))
    moved = list(OWNER_STARTS)
    moved[slot - 1] = new
    r2 = Run(layout=lambda d, m=moved: (owner_full(d), [d.regs["slots"][i].update(start=x) for i, x in enumerate(m, 1)]), t0=t0_)
    r2.edit(slot, "start_time", c_txt(c_mins(old)), run=480)
    back = (r2.res().startswith("APPLIED AND VERIFIED") and r2.changed() == {(slot, "start"): (new, old)} and len(r2.applies()) == 1
            and r2.d.attempts == 1 and [s["start"] for s in r2.d.regs["slots"].values()] == list(OWNER_STARTS)
            and slot_writes(r2, slot, old, OWNER_STARTS[slot % 6]))
    if not (fwd and back):
        c_bad.append((slot, v, r.res()[:60], r.changed(), r2.res()[:60], r2.changed()))
check("forward and undo on the owner's baseline, every slot (slot 5 22:00 -> 23:55 up to midnight and slot 6 00:25 -> 00:00 at it - acs1x: their moves "
      "across midnight are refused, [4x] - slot 6 the five-minute slot, slot 1 after slot 6): each Apply is APPLIED AND VERIFIED with exactly that slot's start register changed, one Load, one press, the gate-pass counter "
      "+1, the write log exactly 232, the start (249+N) at the request, the end register (the next slot's start; 250 for slot 6) at its unchanged value, "
      "power, SOC, flags; slot N-1's staging refreshed (F1), and the undo restores the baseline exactly", not c_bad, str(c_bad[:2]))
# --- the live-proven edits of 25 Oct (I3), repeated on the baseline: unchanged by acs1c
c_bad = []
for slot, setting, a, b in ((1, "target_soc", 99, 100), (5, "power", 7900, 8000), (5, "charge_source", "Grid", "None")):
    r = Run(layout=owner_full, t0=NOON).edit(slot, setting, a)
    key = key_of(setting)
    if not (r.res().startswith("APPLIED AND VERIFIED") and r.changed() == {(slot, key): (b, a)} and len(r.applies()) == 1 and len(r.loads()) == 1
            and r.d.attempts == 1 and not r.locked()):
        c_bad.append((slot, setting, a, r.res()[:60], r.changed()))
    r2 = Run(layout=lambda d, s_=slot, k_=key, v_=a: (owner_full(d), d.regs["slots"][s_].update({k_: v_})), t0=NOON).edit(slot, setting, b)
    if not (r2.res().startswith("APPLIED AND VERIFIED") and r2.changed() == {(slot, key): (a, b)} and len(r2.applies()) == 1 and len(r2.loads()) == 1):
        c_bad.append((slot, setting, b, r2.res()[:60], r2.changed()))
check("the three edits live-proven on 25 Oct (slot 1 target SOC 100 -> 99 -> 100, slot 5 power 8000 -> 7900 -> 8000 W, slot 5 charge source None -> Grid -> "
      "None) repeat on the wrap layout exactly as before: APPLIED AND VERIFIED, one Load, one press, one register, counter +1 - the acs1c layer touches "
      "start-time edits only", not c_bad, str(c_bad[:2]))
# --- a neighbour that moves between the Review and the Apply (someone else edited the inverter): the Apply re-gates on the fresh read
r = Run(layout=owner_full, t0=NOON).review(1, "start_time", "00:35")
r.d.regs["slots"][2]["start"] = 35                          # slot 2 moved to 00:35 on the inverter after the Review (still one cycle): slot 1's 00:35 would equal it
r.apply(run=480)
check("a neighbour moved on the inverter after the Review (slot 2 05:30 -> 00:35 while slot 1 00:30 -> 00:35 is pending; the live layout is still one "
      "cycle): the Apply's fresh-read gate recomputes the window and refuses with the neighbour rule named, nothing pressed, nothing written, not locked",
      r.res().startswith("FAILED") and "strictly after the previous slot" in r.res() and r.applies() == [] and r.changed() == {(2, "start"): (530, 35)}
      and not r.locked() and not r.arm_on(), f"{r.res()[:90]} {r.changed()}")
r = Run(layout=owner_full, t0=NOON).review(1, "start_time", "00:35")
r.d.regs["slots"][6]["start"] = 40                          # slot 6 moved to 00:40, past slot 1's start: the live layout is no longer one cycle
r.apply(run=480)
check("a neighbour moved so that the live layout is no longer one cycle (slot 6 00:25 -> 00:40 past slot 1's 00:30 while slot 1 -> 00:35 is pending): the "
      "Apply's fresh-read gate refuses with the cycle rule named (unexpected TOU layout), nothing pressed, nothing written, not locked",
      r.res().startswith("FAILED") and "24-hour cycle" in r.res() and r.applies() == [] and r.changed() == {(6, "start"): (25, 40)}
      and not r.locked() and not r.arm_on(), f"{r.res()[:90]} {r.changed()}")
r = Run(layout=owner_full, t0=NOON).review(1, "start_time", "00:35")
r.d.regs["slots"][2]["start"] = 520                          # slot 2 moved to 05:20: still a valid window for slot 1; the new end is written back as read
r.apply(run=480)
check("the next slot's start moved after the Review (slot 2 05:30 -> 05:20): the edit still applies, the fresh end (05:20) is Loaded and rewritten unchanged, "
      "only slot 1's start changed", r.res().startswith("APPLIED AND VERIFIED") and r.changed() == {(1, "start"): (30, 35), (2, "start"): (530, 520)}
      and r.d.regs["slots"][2]["start"] == 520 and len(r.applies()) == 1, f"{r.res()[:80]} {r.changed()}")

# ======================================================================================================================
print("\n[4x] acs1x: the midnight-crossing hold (the owner's restriction on moving the crossing, enforced by the scripts)")
# ======================================================================================================================


def x_model(lay, n, new, now_min):
    """The installed gate's start-time ordering verdict in plain Python: acs1c's reference model, then the crossing hold."""
    return XW.verdict(C.verdict(lay, n, new, now_min), lay, n, new)


def x_cls_text(s):
    """The outcome class of one gate copy's own result ('' = no refusal = 'accept'); the classes and texts of c_cls."""
    if not s:
        return "accept"
    for k, t in (("crossing", "midnight crossing"), ("cycle2", "would not leave one valid 24-hour cycle"), ("cycle", "24-hour cycle"),
                 ("order", "strictly after the previous slot"), ("near", "within 15 minutes"), ("mid", "between the old and the new boundary"),
                 ("nochange", "no change"), ("unavailable", "unavailable")):
        if t in s:
            return k
    return "other:" + s[:60]


def _yaml_strings(text, pred):
    """(key, value) of every string value in the parsed package for which pred(key, value) holds, in document order."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and pred(k, v):
                    out.append((k, v))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(yaml.safe_load(text))
    return out


def gate_copies(text):
    """The four copies of the gate in `text` as Home Assistant reads them (parsed, folded), in document order: the Review's `refusal`, the
    Apply's `refusal` (its gate), `refusal2` (its fresh-read re-check) and `refusal3` (its last check before the press)."""
    return _yaml_strings(text, lambda k, v: "{% set cyc2 =" in v)


class GateWorld:
    """A Run (the owner's layout unless given) whose four gate copies are rendered ALONE in its world, with the variables the scripts give them
    (slot, setting, the typed value, its minutes, the per-slot entity map, label, display value), so each copy is checked on its own. The
    later copies are NOT redundant: the edited slot's own live start is re-checked against the review record only by the Apply's gate and at
    the fresh read, so between the fresh read and the press the last copy is the only check that sees it change (another tool moving slot N's
    start can turn an accepted edit into a crossing-moving one there: [11x]); and the fresh-read copy can differ from the Apply's gate when the
    other five starts move. A copy without the hold is caught here and end to end ([11x], [12])."""

    def __init__(self, text=None, layout=OWNER_LAYOUT, t0=NOON, setup=None):
        text = S1 if text is None else text
        self.r = Run(text, layout=layout, t0=t0, setup=setup)
        self.copies = gate_copies(text)
        maps = _yaml_strings(text, lambda k, v: k == "e" and "{% set m = {" in v)
        assert len(maps) == 2 and maps[0] == maps[1] and [k for k, _v in self.copies] == ["refusal", "refusal", "refusal2", "refusal3"]
        self.etmpl, self.e = maps[0][1], {}

    def results(self, n, hhmm_txt):
        if n not in self.e:
            self.e[n] = self.r.w.render_native(self.etmpl, {"n": n})
        want = hhmm_of(hhmm_txt)
        v = dict(n=n, setting="start_time", want=want, wmin=c_mins(want), e=self.e[n], label="start time", wdisp=hhmm_txt)
        return [self.r.w.render(t, v).strip() for _k, t in self.copies]


check("the descent model: for every one of the owner's layout's rotations exactly one slot pair has a next start earlier than its own (the midnight "
      "crossing: slot 5 -> 6, index 4, in the owner's numbering), and it runs from the latest start to the earliest",
      XW.descents(OWNER_MIN) == [4] and all(XW.descents(OWNER_MIN[r_:] + OWNER_MIN[:r_]) == [(4 - r_) % 6] for r_ in range(6))
      and max(range(6), key=lambda k: OWNER_MIN[k]) == 4 and min(range(6), key=lambda k: OWNER_MIN[k]) == 5)
# --- exhaustive: every single-slot start edit of the owner's layout, through each of the four gate copies rendered alone
GW_DAY = GateWorld(t0=S.parse_local("2026-10-26 12:02:30") - 70)      # 12:02:30: no grid value is exactly 15 minutes from the local time
GW_NIGHT = GateWorld(t0=S.parse_local("2026-10-26 02:02:30") - 70)    # inside slot 1, clear of slots 3 and 4's boundaries
x_bad, x_seen, x_cross = [], Counter(), set()
for n in range(1, 7):
    gw, now_min = (GW_NIGHT, 122.5) if n in (3, 4) else (GW_DAY, 722.5)
    for new in range(0, 1440, 5):
        exp = x_model(OWNER_MIN, n, new, now_min)
        got = gw.results(n, c_txt(new))
        cls_ = [x_cls_text(g) for g in got]
        x_seen[exp] += 1
        if exp == "crossing":
            x_cross.add((n, new))
        if cls_ != [exp] * 4 or (exp == "crossing" and got != [XW.REFUSE_XW] * 4):
            x_bad.append((n, c_txt(new), exp, cls_))
WANT_CROSS = {(5, m) for m in range(0, 25, 5)} | {(6, m) for m in range(22 * 60 + 5, 1440, 5)}
check(f"EXHAUSTIVE on the owner's layout: every single-slot start edit (6 slots x 288 grid values = {6 * 288} cases) through each of the four gate "
      f"copies rendered alone gives the reference model's verdict in all four (classes: {dict(x_seen)}); the hold refuses exactly slot 5 moved past "
      "midnight (00:00 .. 00:20) and slot 6 moved before it (22:05 .. 23:55), 28 cases, with its own text in every copy, and never fires for slots 1-4",
      not x_bad and x_cross == WANT_CROSS and len(WANT_CROSS) == 28
      and dict(x_seen) == {"order": 1158, "nochange": 6, "accept": 534, "near": 2, "crossing": 28}, str(x_bad[:4]) + " " + str(dict(x_seen)))
# --- the same through the real Review script: slots 5 and 6 at every grid value from 21:00 to 00:55, every slot at each full hour
x_bad, x_seen = [], Counter()
E2E = [(n, m) for n in (5, 6) for m in list(range(21 * 60, 1440, 5)) + list(range(0, 60, 5))] + [(n, h * 60) for n in range(1, 7) for h in range(24)]
for n, new in E2E:
    stamp, now_min = ("2026-10-26 02:02:30", 122.5) if n in (3, 4) else ("2026-10-26 12:02:30", 722.5)
    r = at(stamp, layout=OWNER_LAYOUT).review(n, "start_time", c_txt(new))
    exp = x_model(OWNER_MIN, n, new, now_min)
    x_seen[exp] += 1
    if (c_cls(r) != exp or (exp == "accept") != accepts(r) or (exp != "accept") != rejects(r) or len(r.res()) >= 255
            or (exp == "crossing" and r.res() != "REVIEW REFUSED - " + XW.REFUSE_XW + "; nothing written")):
        x_bad.append((n, c_txt(new), exp, c_cls(r), r.res()[:70]))
check(f"the real Review script on the owner's layout ({len(E2E)} cases: slots 5 and 6 at every grid value 21:00 .. 00:55, every slot at each full hour): "
      f"its verdict is the reference model's in every case (classes: {dict(x_seen)}); a crossing-moving edit is 'REVIEW REFUSED - <the hold's text>; "
      "nothing written', with no press and no plan recorded", not x_bad and x_seen["crossing"] >= 20 and x_seen["accept"] >= 40, str(x_bad[:4]))
# --- the owner's named cases: acs1c accepted the crossing-moving ones; the installed package refuses them, nothing written
x_bad = []
for (slot, v), exp in (((6, "23:55"), "crossing"), ((6, "23:00"), "crossing"), ((6, "22:05"), "crossing"), ((5, "00:00"), "crossing"),
                       ((5, "00:05"), "crossing"), ((5, "00:20"), "crossing"), ((6, "00:20"), "accept"), ((6, "00:00"), "accept"),
                       ((5, "23:55"), "accept"), ((5, "21:55"), "accept"), ((1, "05:25"), "accept"), ((4, "21:55"), "accept")):
    t0_ = TWO_AM if slot in (3, 4) else NOON
    r = Run(layout=OWNER_LAYOUT, t0=t0_).review(slot, "start_time", v)
    r_c = Run(S1C, layout=OWNER_LAYOUT, t0=t0_).review(slot, "start_time", v)
    if not (c_cls(r) == exp and (rejects(r) and r.w.state(PLAN) in ("", "unknown") and r.d.presses == [] if exp == "crossing" else accepts(r))
            and accepts(r_c)):
        x_bad.append((slot, v, exp, c_cls(r), c_cls(r_c)))
check("the owner's named cases: slot 6 moved before midnight (23:55, 23:00, 22:05) and slot 5 moved past it (00:00, 00:05, 00:20) are refused by the "
      "hold, nothing pressed, no plan recorded; slot 6 00:25 -> 00:20 and -> 00:00, slot 5 -> 23:55 and -> 21:55, slot 1 -> 05:25 and slot 4 -> 21:55 "
      "are accepted; the acs1c text (the hold's base) accepts every one of them, so the hold is what refuses", not x_bad, str(x_bad))
# --- the Apply's own gate refuses a hand-edited record that would move the crossing (the Review never saw that value)
x_bad = []
for slot, ok_v, bad_v in ((5, "21:55", 5), (6, "00:20", 2355), (5, "23:55", 20), (6, "00:00", 2205)):
    r = Run(layout=OWNER_LAYOUT, t0=NOON).review(slot, "start_time", ok_v)
    rec = r.w.state(PLAN).split("|")
    rec[2] = str(bad_v)
    r.w.set(PLAN, "|".join(rec))
    r.apply(phrase=f"SET SLOT {slot} START {bad_v // 100:02d}:{bad_v % 100:02d} REVIEW {rec[3]}", run=120)
    if not (r.res() == "REFUSED - " + XW.REFUSE_XW + "; nothing written" and r.applies() == [] and r.loads() == [] and r.changed() == {}
            and not r.arm_on() and not r.locked()):
        x_bad.append((slot, ok_v, bad_v, r.res()[:80], r.loads()))
check("a review record edited by hand to a crossing-moving value (slot 5 21:55 -> 00:05 and 23:55 -> 00:20; slot 6 00:20 -> 23:55 and 00:00 -> 22:05, "
      "each with the matching phrase): the Apply's own gate refuses it with the hold's text before any Load - nothing pressed, nothing written, not "
      "armed, not locked", not x_bad, str(x_bad[:2]))
# --- the hold alone fails closed (in-memory: the cycle, neighbour and proposed-layout refusals turned off, so only the hold stands)
S1_HOLD_ONLY = S1
for _a in ("{% elif setting == 'start_time' and not cyc %}", "{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}",
           "{% elif setting == 'start_time' and not cyc2 %}"):
    assert S1_HOLD_ONLY.count(_a) == 4
    S1_HOLD_ONLY = S1_HOLD_ONLY.replace(_a, "{% elif false %}")
x_bad = []
for label, kw, slot, v in (("an unreadable live start (slot 2)", dict(layout=OWNER_LAYOUT, setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone2_time", "unavailable")), 5, "23:55"),
                           ("a live start that is not HH:MM (slot 3 '?2475')", dict(layout=OWNER_LAYOUT, setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone3_time", "?2475")), 6, "00:20"),
                           ("a live layout that goes round the clock twice (two crossings)", dict(layout=starts(30, 530, 1200, 1635, 2200, 1300)), 2, "05:35"),
                           ("a proposed layout with two crossings (slot 6 -> 00:35, past slot 1)", dict(layout=OWNER_LAYOUT), 6, "00:35")):
    r = Run(S1_HOLD_ONLY, t0=NOON, **kw).review(slot, "start_time", v)
    if not (rejects(r) and XW.REFUSE_XW in r.res()):
        x_bad.append((label, r.res()[:70]))
for slot, v in ((5, "23:55"), (6, "00:20"), (1, "00:35")):
    r = Run(S1_HOLD_ONLY, layout=OWNER_LAYOUT, t0=NOON).review(slot, "start_time", v)
    if not accepts(r):
        x_bad.append(("accept", slot, v, r.res()[:70]))
check("defence in depth: with the cycle, neighbour and proposed-layout refusals turned off in memory the hold alone still refuses an unreadable or "
      "malformed live start, a live layout with two crossings and a proposed layout with two crossings (fail closed), and still accepts the edits that "
      "keep the crossing", not x_bad, str(x_bad))
# one case per conjunct of the hold: each is refused by the hold alone through all four copies, and not by the hold once that one conjunct is
# removed in memory, so each conjunct is pinned by its own case (review finding X4)
HOLD_CONJUNCTS = (
    ("xc.ok (an unreadable start of another slot whose -1 keeps one decrease at the same place: slot 6 'unavailable', slot 2 -> 05:35)",
     ("and wmin >= 0 and xc.ok and xc.c == 1", "and wmin >= 0 and xc.c == 1"),
     dict(setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone6_time", "unavailable")), 2, "05:35"),
    ("tt[k] >= 0 (the edited slot's own live start malformed but read as a number by the value parse: slot 6 '0:25', slot 6 -> 00:20)",
     ("{% set xc.ok = xc.ok and tt[k] >= 0 and a >= 0 %}", "{% set xc.ok = xc.ok and a >= 0 %}"),
     dict(setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone6_time", "0:25")), 6, "00:20"),
    ("xc.c == 1 (a live layout with two crossings that the edit reduces to one at the same place: slot 6 at 21:40 -> 22:10)",
     ("and xc.ok and xc.c == 1 and xc.c2 == 1", "and xc.ok and xc.c2 == 1"),
     dict(layout=starts(30, 530, 1200, 1635, 2200, 2140)), 6, "22:10"),
    ("xc.c2 == 1 (a proposed layout with two crossings, the last at the live crossing: slot 4 16:35 -> 06:00)",
     ("and xc.c == 1 and xc.c2 == 1 and xc.i == xc.i2", "and xc.c == 1 and xc.i == xc.i2"),
     dict(layout=OWNER_LAYOUT), 4, "06:00"),
)


def hold_only(t):
    """`t` with the cycle, neighbour and proposed-layout refusals turned off in memory (all four copies): only the hold stands."""
    for a_ in ("{% elif setting == 'start_time' and not cyc %}", "{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}",
               "{% elif setting == 'start_time' and not cyc2 %}"):
        assert t.count(a_) == 4
        t = t.replace(a_, "{% elif false %}")
    return t


def hold_alone_refuses(t):
    """Every HOLD_CONJUNCTS case is refused with the hold's text by each of the four copies of hold_only(t), rendered alone."""
    ho = hold_only(t)
    return all(GateWorld(ho, t0=NOON, **{"layout": OWNER_LAYOUT, **kw}).results(n_, v_) == [XW.REFUSE_XW] * 4
               for _label, _cut, kw, n_, v_ in HOLD_CONJUNCTS)


x_bad = []
for label, (cut_a, cut_b), kw, n_, v_ in HOLD_CONJUNCTS:
    assert S1_HOLD_ONLY.count(cut_a) == 4
    got = GateWorld(S1_HOLD_ONLY, t0=NOON, **{"layout": OWNER_LAYOUT, **kw}).results(n_, v_)
    got_cut = GateWorld(S1_HOLD_ONLY.replace(cut_a, cut_b), t0=NOON, **{"layout": OWNER_LAYOUT, **kw}).results(n_, v_)
    if got != [XW.REFUSE_XW] * 4 or any(XW.REFUSE_XW in g for g in got_cut):
        x_bad.append((label[:40], got, got_cut))
check("each conjunct of the hold is pinned by its own case (xc.ok, tt[k] >= 0, xc.c == 1, xc.c2 == 1): with only the hold standing, each case is "
      "refused with the hold's text by all four copies rendered alone, and with that one conjunct removed in memory no copy refuses it with the hold",
      not x_bad and hold_alone_refuses(S1), str(x_bad[:2]))
# --- the hold keeps the crossing wherever the live layout has it (here slot 4 -> 5, after slot 5 was moved past midnight by another tool)
MOVED_MIN = [c_mins(x) for x in (30, 530, 1200, 1635, 5, 25)]
x_bad = []
for slot, v, exp in ((5, "22:00", "crossing"), (5, "00:10", "accept"), (4, "23:55", "accept"), (4, "00:00", "crossing"), (6, "00:20", "accept"),
                     (6, "23:55", "order"), (3, "12:05", "near")):
    r = Run(layout=MOVED, t0=NOON).review(slot, "start_time", v)
    if c_cls(r) != exp or x_model(MOVED_MIN, slot, c_mins(hhmm_of(v)), 720) != exp:
        x_bad.append((slot, v, exp, c_cls(r)))
check("the hold keeps the crossing where the live layout has it: on a layout whose crossing is slot 4 -> 5 (slot 5 at 00:05), moving slot 5 back to "
      "22:00 is refused (the crossing would move; the editor cannot move it back while the hold stands), slot 4 -> 00:00 is refused, slot 4 -> 23:55, "
      "slot 5 -> 00:10 and slot 6 -> 00:20 are accepted; the model agrees", not x_bad, str(x_bad))
# --- every other setting is unaffected: the same Review result and notification as on the acs1c text
x_bad = []
for lay_name, lay, slots in (("owner", OWNER_LAYOUT, range(1, 7)), ("crossing at slot 4 -> 5", MOVED, (4, 5, 6))):
    for n in slots:
        for setting in ("target_soc", "power", "charge_source"):
            r = Run(layout=lay, t0=NOON).review(n, setting, value_for(n, setting))
            r_c = Run(S1C, layout=lay, t0=NOON).review(n, setting, value_for(n, setting))
            if not (accepts(r) and r.res() == r_c.res() and r.note("ecco_cfg_edit_review") == r_c.note("ecco_cfg_edit_review")):
                x_bad.append((lay_name, n, setting, r.res()[:60]))
check("target SOC, power and charge-source Reviews are unaffected by the hold: on the owner's layout (every slot) and on a layout whose crossing sits "
      "elsewhere, each is accepted with exactly the result text and notification of the acs1c text", not x_bad, str(x_bad[:3]))
# --- random cyclic layouts: the four copies rendered alone against the model, edits around each slot and around midnight
rng_x = random.Random(20261027)


def x_rand_cycle():
    pts = sorted(rng_x.sample(range(0, 1440, 5), 6))
    rot = rng_x.randrange(6)
    return pts[rot:] + pts[:rot]


x_bad, x_seen, n_cases = [], Counter(), 0
for _ in range(30):
    lay = x_rand_cycle()
    m_ = rng_x.randrange(0, 1440)
    gw = GateWorld(layout=starts(*[c_hhmm(x) for x in lay]), t0=S.parse_local(f"2026-10-26 {c_txt(m_)}:30") - 70)
    for n in range(1, 7):
        pv, nx, cur = lay[(n + 4) % 6], lay[n % 6], lay[n - 1]
        for new in sorted({(pv + 5) % 1440, (nx - 5) % 1440, 1435, 0, 5, (cur + 5) % 1440, (cur - 5) % 1440, rng_x.randrange(0, 1440, 5)}):
            exp = x_model(lay, n, new, m_ + 0.5)
            cls_ = [x_cls_text(g) for g in gw.results(n, c_txt(new))]
            x_seen[exp] += 1
            n_cases += 1
            if cls_ != [exp] * 4:
                x_bad.append((lay, n, c_txt(new), c_txt(m_), exp, cls_))
check(f"random cyclic layouts (30 seeded layouts with the crossing anywhere, {n_cases} edits next to each neighbour, around the old start and around "
      f"midnight, a random local time): each of the four gate copies rendered alone gives the reference model's verdict (classes: {dict(x_seen)})",
      not x_bad and x_seen["crossing"] >= 30 and x_seen["accept"] >= 30, str(x_bad[:3]))
# --- the model (plain Python, many cases): the crossing identity and two independent oracles
xp_bad, xp_cross = [], 0
for _ in range(20000):
    lay = x_rand_cycle()
    kind = rng_x.choice(["valid"] * 3 + ["dup", "twowrap", "offgrid"])
    if kind == "dup":
        i, j = rng_x.sample(range(6), 2)
        lay[i] = lay[j]
    elif kind == "twowrap":
        i, j = sorted(rng_x.sample(range(6), 2))
        lay[i], lay[j] = lay[j], lay[i]
    elif kind == "offgrid":
        lay[rng_x.randrange(6)] += rng_x.choice((1, 2, 3, 4))
    if sum(C.gaps(lay)) != 1440 * len(XW.descents(lay)):          # each gap is the raw difference, plus 1440 when it is negative
        xp_bad.append(("identity", lay))
    if C.is_cycle(lay) and XW.descents(lay) != [max(range(6), key=lambda k: lay[k])]:   # one crossing, from the latest start
        xp_bad.append(("one crossing", lay))
    n, new, now_min = rng_x.randrange(1, 7), rng_x.randrange(0, 1440, 5), rng_x.randrange(0, 1440) + 0.5
    base, v = C.verdict(lay, n, new, now_min), x_model(lay, n, new, now_min)
    proposed = list(lay)
    proposed[n - 1] = new
    if base in ("accept", "near", "mid"):
        owner_2359 = active_slot(lay, 1439.5) != active_slot(proposed, 1439.5)     # oracle 1: the slot that owns the day's last minute changes
        pv = lay[(n + 4) % 6]
        ub, uw, mn = (lay[n - 1] - pv) % 1440, (new - pv) % 1440, (0 - pv) % 1440
        across = min(ub, uw) < mn <= max(ub, uw)                                    # oracle 2: the moved boundary passes 00:00
        if (v == "crossing") != owner_2359 or (v == "crossing") != across:
            xp_bad.append(("oracle", lay, n, new, v, owner_2359, across))
        if v == "crossing":
            xp_cross += 1
            if (n - 1) not in (XW.descents(lay)[0], (XW.descents(lay)[0] + 1) % 6):  # only the two slots around the crossing can move it
                xp_bad.append(("adjacent", lay, n, new))
        elif v != base:
            xp_bad.append(("kept", lay, n, new, base, v))
    elif v != base:                                                                  # every earlier refusal stands
        xp_bad.append(("earlier", lay, n, new, base, v))
    rot = rng_x.randrange(6)
    if x_model(lay[rot:] + lay[:rot], (n - 1 - rot) % 6 + 1, new, now_min) != v:      # rotation invariance
        xp_bad.append(("rotation", lay, n, new, rot))
check(f"the reference model over 20000 random cases (valid cycles, duplicates, two wraps, off-grid starts): the six gaps always sum to 1440 x the number "
      "of raw decreases (so one 24-hour cycle has exactly one crossing, from its latest start); for an edit acs1c would accept (or refuse only by the "
      "15-minute or active-slot guard) the hold refuses exactly when the slot that owns the day's last minute changes and exactly when the moved "
      f"boundary passes 00:00 (two independent oracles; {xp_cross} crossing cases), only for the two slots around the crossing; every earlier refusal "
      "stands; verdicts are invariant under slot rotation", not xp_bad and xp_cross >= 400, str(xp_bad[:3]) + f" {xp_cross}")

# the raw flags are what the charge-source verdict (and every 'unchanged' proof) compares: unreadable flags stop the edit before the Load
def flags_unavailable(r, n=3):
    ent = f"sensor.{D}ecco_timezone{n}_raw_flags"
    real = r.w.set
    r.w.set = lambda e, v, a=None: real(e, "unavailable" if e == ent else v, a)
    real(ent, "unavailable")


bad = []
for setting in SETTINGS:
    r = Run(setup=flags_unavailable).edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("FAILED") and "raw flags are unavailable" in r.res() and r.d.presses == [] and r.changed() == {}
            and not r.arm_on() and not r.locked()):
        bad.append((setting, r.res()[:80], r.d.presses[-1:]))
check("the slot's raw flags unavailable at the fresh read: FAILED before the Load, nothing pressed, nothing written, not locked - for each setting",
      not bad, str(bad))

# the live and staged source / mode must be real option words before they count as equal ("unavailable" == "unavailable" proves nothing)
def src_mode_unavailable(which, n=3):
    def setup(r):
        ents = {f"sensor.{D}ecco_timezone{n}_{'charge' if which == 'src' else 'mode'}",
                f"select.{D}manual_slot_{n}_{'charge_source' if which == 'src' else 'mode'}"}
        real = r.w.set
        r.w.set = lambda e, v, a=None: real(e, "unavailable" if e in ents else v, a)
        for e in ents:
            real(e, "unavailable")
    return setup


bad = []
for which in ("src", "mode"):
    for setting in ("target_soc", "power", "start_time"):
        r = Run(setup=src_mode_unavailable(which)).edit(3, setting, value_for(3, setting))
        if not (r.res().startswith("FAILED") and r.applies() == [] and len(r.loads()) == 1 and r.changed() == {} and not r.arm_on()
                and not r.locked()):
            bad.append((which, setting, r.res()[:80], r.d.presses[-1:]))
check("the live AND the staged charge source (or mode) both 'unavailable' (so equal): FAILED, nothing pressed, nothing written - for the SOC, "
      "power and start-time edits", not bad, str(bad))

# --- charge source
bad = []
for slot, lay, v, ok in (
        (3, None, "Grid", True), (3, None, "None", False), (1, None, "None", True), (1, None, "Grid", False),
        (3, None, "Generator", False), (3, None, "Grid + Generator", False), (3, None, "grid", False), (3, None, "GRID", False),
        (3, None, "none", False), (3, None, "NONE", False), (3, None, "", False),
        (3, None, "Backup", False), (3, None, 1, False),
        (3, slot_set(3, src="Generator"), "None", False), (3, slot_set(3, src="Generator"), "Grid", False),
        (3, slot_set(3, src="Grid + Generator"), "None", False), (3, slot_set(3, src="Grid + Generator"), "Grid", False)):
    r = Run(layout=lay).review(slot, "charge_source", v)
    if (accepts(r) if ok else rejects(r)) is not True:
        bad.append((slot, v, ok, r.res()[:80]))
r = Run().review(3, "charge_source", " Grid ")
check("charge source ' Grid ' (padded): the template engine trims it, so it is the canonical Grid and the record says so",
      accepts(r) and r.rec()[2] == "Grid", r.res())
check(f"charge source: Grid and None accepted; Generator, Grid + Generator, lower-case / upper-case / empty / other words refused; "
      "a LIVE Generator or Grid + Generator source refused for any value; no change refused", not bad, str(bad[:4]))
r = Run(layout=slot_set(3, src="Generator")).review(3, "charge_source", "None")
check("a live Generator source is refused with the reason: only None and Grid can be edited", "only None and Grid can be edited" in r.res(), r.res())
r = Run().review(3, "charge_source", "Generator")
check("the Generator is refused with the reason: no generator is evidenced", "no generator is evidenced" in r.res(), r.res())
for slot, a, b in ((1, "Grid", "None"), (3, "None", "Grid")):
    r = Run().edit(slot, "charge_source", b)
    r2 = Run(layout=slot_set(slot, src=b)).edit(slot, "charge_source", a)
    check(f"slot {slot} charge source {a} -> {b} and back {b} -> {a} both applied, only bits 0-1 of the flags (mode General kept)",
          r.res().startswith("APPLIED") and r.changed() == {(slot, "src"): (a, b)} and r.d.regs["slots"][slot]["mode"] == "General"
          and r2.res().startswith("APPLIED") and r2.changed() == {(slot, "src"): (b, a)}, f"{r.res()} {r2.res()}")

# --- target SOC (Stage 0's bounds)
for shutdown, reserve, low_ok, low_bad in ((10, 20, 20, 19), (25, 20, 25, 24), (15, 15, 15, 14)):
    r1 = Run(shutdown=shutdown, reserve=reserve).review(3, "target_soc", low_bad)
    r2 = Run(shutdown=shutdown, reserve=reserve).edit(3, "target_soc", low_ok)
    check(f"target SOC, shutdown {shutdown} %, reserve {reserve} %: {low_bad} % refused at Review, {low_ok} % applied", rejects(r1)
          and "target SOC must be" in r1.res() and r2.res().startswith("APPLIED"), f"{r1.res()} | {r2.res()}")
r = Run().review(3, "target_soc", 101)
check("target SOC 101 % refused; 100 % accepted from 40 %", rejects(r) and accepts(Run().review(3, "target_soc", 100)), r.res())
r = Run().review(3, "target_soc", 25)
r.w.set(RESERVE, "30.0")
r.apply()
check("the reserve raised above the reviewed value before the Apply: refused at the Apply, nothing written",
      r.res().startswith("REFUSED - target SOC must be 30-100") and r.d.presses == [] and r.changed() == {}, r.res())
r = Run(setup=lambda x: x.w.at(T0 + 100, lambda: x.w.set(M.SHUTDOWN, "30.0"))).review(3, "target_soc", 25).apply()
check("the shutdown SOC rises to 30 % in the fresh read the Apply waits for: FAILED before the Load, nothing written",
      r.res().startswith("FAILED - target SOC must be 30-100") and r.applies() == [] and r.changed() == {}, r.res())
bad = []
for ent in (RESERVE, M.SHUTDOWN):
    r = Run(setup=lambda x, e_=ent: x.w.set(e_, "unavailable")).review(3, "target_soc", 41)
    if not (rejects(r) and "unavailable" in r.res()):
        bad.append((ent, r.res()))
    r = Run(setup=lambda x, e_=ent: x.w.set(e_, "unavailable")).review(3, "power", 3000)
    if not accepts(r):
        bad.append((ent, "power", r.res()))
check("the reserve or the shutdown SOC unavailable refuses a SOC edit (fail-closed) but not a power edit", not bad, str(bad))
r = Run().edit(3, "target_soc", 41)
check("the reserve helper is never changed by an edit", r.w.state(RESERVE) == "20.0")

# --- unknown settings and slots
bad = []
for slot, setting, v in ((3, "mode", "General"), (3, "end_time", "10:00"), (3, "", 5), (3, "Target_SOC", 41), (3, "TARGET_SOC", 41), (3, "soc", 41),
                         (3, "grid_charge", "on"), (3, "target_soc ", 41), (0, "power", 3000), (7, "power", 3000), ("x", "power", 3000),
                         (-1, "power", 3000), (3.5, "power", 3000)):
    r = Run().review(slot, setting, v)
    if slot == 3.5:
        if not (accepts(r) and r.rec()[0] == "3"):
            bad.append((slot, setting, r.res()[:70]))
    elif not rejects(r):
        bad.append((slot, setting, v, r.res()[:70]))
check("an unknown setting (mode, end_time, empty, wrong case, padded, 'soc', grid charge) and an invalid slot (0, 7, 'x', -1) are refused; "
      "slot 3.5 is truncated to 3 as in Stage 0, and the Review shows it", not bad, str(bad))

# --- UK clock change nights (the sim has one fixed zone: this tests the package's rule on local time, not the zone itself)
bad = []
NIGHTS = [("2026-10-25 00:00:00", False), ("2026-10-25 00:30:00", False), ("2026-10-25 01:30:00", False), ("2026-10-25 02:59:00", False),
          ("2026-10-25 03:00:00", True), ("2026-10-25 12:00:00", True), ("2026-10-24 01:30:00", True), ("2026-10-24 23:59:00", True),
          ("2026-10-26 01:30:00", True), ("2026-10-18 01:30:00", True), ("2026-10-11 01:30:00", True),
          ("2026-03-29 00:30:00", False), ("2026-03-29 02:59:00", False), ("2026-03-29 03:00:00", True), ("2026-03-22 01:30:00", True),
          ("2026-03-28 01:30:00", True), ("2027-03-28 01:30:00", False), ("2027-03-28 03:00:00", True), ("2027-03-21 01:30:00", True),
          ("2027-10-31 01:30:00", False), ("2027-10-31 03:00:00", True), ("2026-09-27 01:30:00", True), ("2026-11-01 01:30:00", True)]
for stamp, ok in NIGHTS:
    for setting in SETTINGS:
        slot = 3
        v = value_for(slot, setting)
        if setting == "start_time":                      # keep clear of the 15-minute guard: boundaries 09:00 / 09:30 are hours from 00:00-03:00
            pass
        r = at(stamp).review(slot, setting, v)
        got = accepts(r) if ok else (rejects(r) and "clock change night" in r.res())
        if got is not True:
            bad.append((stamp, setting, ok, r.res()[:70]))
check(f"clock change nights: 00:00-03:00 local on the last Sunday of March and of October (2026-03-29, 2026-10-25, 2027-03-28, 2027-10-31) "
      f"refuses every setting; 03:00 allowed; the Saturday before, the Monday after, other Sundays allowed ({len(NIGHTS)} instants x 4 settings)",
      not bad, str(bad[:4]))
r = at("2026-10-25 00:30:00").review(3, "target_soc", 41)
rr = at("2026-10-25 00:30:00", legacy=True).review(3, "target_soc", 41)
check("the clock-change rule is the one deliberate difference to Stage 0 on a SOC edit: Stage 0 reviews it, Stage 1 refuses it",
      cls(rr) == "REVIEWED" and rejects(r), f"{rr.res()} | {r.res()}")
r = at("2026-10-24 23:56:00").review(3, "target_soc", 41)
r.w.run_until(r.w.t + 300)
r.apply(run=5)
check("a review made on Saturday 23:56 and applied at 00:01 on the Sunday clock change night: refused at the Apply, nothing written",
      r.res().startswith("REFUSED") and "clock change night" in r.res() and r.d.presses == [] and r.changed() == {}, r.res())


# ======================================================================================================================
print("\n[5] review and confirmation, per setting")
# ======================================================================================================================
bad = []
for setting in SETTINGS:
    v = value_for(3, setting)
    r0 = Run().review(3, setting, v)
    code = r0.code()
    variants = {}
    for other in SETTINGS:
        if other != setting:
            variants[f"the {other} phrase"] = f"SET SLOT 3 {core(other, hhmm_of(value_for(3, other)) if other == 'start_time' else value_for(3, other))} REVIEW {code}"
    ph = r0.phrase()
    variants.update({
        "another slot": ph.replace("SET SLOT 3", "SET SLOT 4"), "another code": ph[:-4] + f"{(int(code) + 1) % 10000:04d}",
        "lower case": ph.lower(), "trailing text": ph + "x", "trailing space": ph + " ", "no code": ph.rsplit(" REVIEW", 1)[0], "empty": "",
        "a bare dash": "-", "the code only": code, "doubled space": ph.replace("SET SLOT", "SET  SLOT"),
    })
    if setting == "target_soc":
        variants["another value"] = ph.replace("TARGET SOC 55", "TARGET SOC 56")
    elif setting == "power":
        variants["another value"] = ph.replace("POWER 3000 W", "POWER 3100 W")
        variants["no unit"] = ph.replace(" W REVIEW", " REVIEW")
    elif setting == "start_time":
        variants["another value"] = ph.replace("START 09:30", "START 09:35")
        variants["not zero-padded"] = ph.replace("START 09:30", "START 9:30")
    else:
        variants["lower-case word"] = ph.replace("GRID", "grid")
        variants["the other word"] = ph.replace("GRID", "NONE")
    for label, phrase in variants.items():
        r = Run().review(3, setting, v)
        r.apply(phrase=phrase, run=5)
        if not (r.res().startswith("REFUSED - the confirmation phrase") and r.d.presses == [] and r.changed() == {}):
            bad.append((setting, label, r.res()[:70]))
check(f"phrase per setting ({len(SETTINGS)} settings x ~14 variants): another setting's / slot's / value's phrase, a wrong or missing code, lower case, "
      "padding, trailing text, empty: refused, nothing written", not bad, str(bad[:4]))
r = Run().apply(phrase="SET SLOT 3 POWER 3000 W REVIEW 0000")
check("no review: refused", r.res().startswith("REFUSED - no pending review") and r.d.presses == [], r.res())
bad = []
for setting in SETTINGS:
    r = Run().review(3, setting, value_for(3, setting))
    r.w.run_until(r.w.t + 601)
    r.apply(run=5)
    if not (r.res().startswith("REFUSED - the review has expired") and r.d.presses == []):
        bad.append((setting, r.res()[:60]))
check("a review older than 10 minutes: refused, for each setting", not bad, str(bad))
r = Run().review(3, "power", 3000)
r.w.run_until(r.w.t + 560)
r.apply()
check("a review 9 minutes 20 seconds old is still accepted (the expiry is 10 minutes)", r.res().startswith("APPLIED")
      and r.changed() == {(3, "power"): (8000, 3000)}, r.res())
bad = []
for setting in SETTINGS:
    r = Run().edit(3, setting, value_for(3, setting))
    p = r.rec()
    r.apply(phrase="SET SLOT 3 TARGET SOC 41 REVIEW 0000", run=5)
    if not (r.res().startswith("REFUSED - no pending review") and len(r.applies()) == 1 and p == ["used"]):
        bad.append((setting, r.res()[:60], p))
check("the review is single-use for each setting: a second Apply after it is refused, one press in all", not bad, str(bad))
# the live value of the EDITED setting changed since the review (the inverter's own panel, a second master): refused; another field: not
CHG = {"target_soc": ("soc", 50), "power": ("power", 5000), "start_time": ("start", 1000), "charge_source": ("src", "Generator")}
OTHER = {"target_soc": ("power", 5000), "power": ("soc", 50), "start_time": ("power", 5000), "charge_source": ("soc", 50)}


def inverter_change(key, value, n=3, at_t=T0 + 72):
    def setup(r):
        def go():
            r.d.regs["slots"][n][key] = value
            r.d.poll()
        r.w.at(at_t, go)
    return setup


bad = []
for setting in SETTINGS:
    key, val = CHG[setting]
    r = Run(setup=inverter_change(key, val)).review(3, setting, value_for(3, setting))
    r.w.run_until(T0 + 80)
    r.apply(run=5)
    if not (r.res().startswith("REFUSED - the slot changed since the review") and r.d.presses == []):
        bad.append((setting, "edited field changed", r.res()[:70]))
    key, val = OTHER[setting]
    r = Run(setup=inverter_change(key, val)).review(3, setting, value_for(3, setting))
    r.w.run_until(T0 + 80)
    r.apply()
    exp = expected_change(3, setting)
    exp[(3, key)] = (DEF[3][key], val)
    if not (r.res().startswith("APPLIED") and r.changed() == exp):
        bad.append((setting, "other field changed", r.res()[:70], r.changed()))
check("the slot's live value of the EDITED setting changed since the review: refused, review again; a change of ANOTHER field of the slot does "
      "not invalidate the review and is kept (rewritten with its new live value)", not bad, str(bad))

# ======================================================================================================================
print("\n[6] the safety gate (fail-closed), for each setting")
# ======================================================================================================================
UNSAFE = [
    (f"binary_sensor.{D}free_power_active", "on"), (f"binary_sensor.{D}free_power_operation_in_progress", "on"),
    (f"binary_sensor.{D}free_power_snapshot_valid", "on"), (f"binary_sensor.{D}dump_to_grid_active", "on"),
    (f"binary_sensor.{D}dump_to_grid_operation_in_progress", "on"), (f"binary_sensor.{D}dump_to_grid_snapshot_valid", "on"),
    (f"binary_sensor.{D}manual_write_in_progress", "on"), (f"binary_sensor.{D}rtc_correction_in_progress", "on"),
    (f"switch.{D}manual_configuration_write_enable", "on"), (f"switch.{D}free_power_write_enable", "on"),
    (f"switch.{D}free_power_recovery_arm", "on"), (f"switch.{D}dump_to_grid_write_enable", "on"),
    (f"switch.{D}dump_to_grid_recovery_arm", "on"),
    (LIVE_MATCH, b10("PAUSED", ca="P", eh="U", obl="FP:AC,DP:CR,R4:CR,BUS:OK")),
    (LIVE_MATCH, b10("PAUSED_IO", ca="P", eh="U", obl="FP:CR,DP:CR,R4:CR,BUS:BY")),
    (LIVE_MATCH, b10("PAUSED", ca="P", eh="U", obl="FP:CR,DP:CR,R4:PC,BUS:OK")),
    (LIVE_MATCH, "m=UNKNOWN;obl=-;ca=-"),
    (FB_REVIEW, "st=READING;id=-"), (FB_REVIEW, "st=CANDIDATE_READY;id=AB12"), (FB_REVIEW, "st=SAVING;id=AB12"),
    *[(e, "on") for e in GATE_KEYS["avail"]],
    (f"sensor.{D}ecco_supervision_state", "SUSPECT"), (f"sensor.{D}ecco_supervision_state", "LOST"),
    (f"binary_sensor.{D}ecco_supervision_stable", "off"), (SHADOW_STATE, "SHADOW_EPISODE"),
    (f"sensor.{D}dump_to_grid_export_containment", "CONTAINED"), (f"sensor.{D}free_power_recovery_evidence_id", "E1234"),
    (f"sensor.{D}reg244_original_snapshot", "0"), (f"sensor.{D}free_power_recovery_state", "LOCKED_REVIEW_REQUIRED"),
    (f"sensor.{D}dump_to_grid_recovery_state", "PENDING - restore owed"),
    ("script.ecco_free_power_start_scheduled", "on"), ("script.ecco_dump_to_grid_start_scheduled", "on"),
    (LOCK, "on"), (f"binary_sensor.{D}telemetry_online", "off"), (f"binary_sensor.{D}configuration_online", "off"),
    (f"binary_sensor.{D}manual_configuration_raw_cache_valid", "off"),
]
covered = {e for e, _ in UNSAFE}
check(f"the unsafe-state table covers EVERY gate entity of the model: all {len(M.SAFE_STATES)} in M.SAFE_STATES and all {len(M.FLAGS)} in M.FLAGS",
      set(M.SAFE_STATES) <= covered and set(M.FLAGS.values()) <= covered,
      str(sorted((set(M.SAFE_STATES) | set(M.FLAGS.values())) - covered)))
AMBIGUOUS = [
    *[(LIVE_MATCH, v) for v in ("", "unknown", "none", "m=MATCH", "MATCH", b10("UNKNOWN", ca="P", eh="U"), b10("NO_PROFILE"), b10("EXPORT"),
                                b10("OUT_OF_DOMAIN"), b10("MATCH", ca="S"), b10("MATCH", ca="P"), b10("MATCH", ca="B"), b10("MATCH", eh="U"),
                                b10("MATCH", eh="1"), b10("match"), b10("MATCH").replace("m=MATCH", "m=MATCH "),
                                b10("PAUSED", ca="P", eh="U", obl="FP:AC,DP:CR,R4:CR,BUS:OK") + ";" + b10("MATCH"),
                                b10("MATCH").replace(";obl=", ";xobl="), b10("MATCH", obl="FP:CR,DP:CR,R4:CR,BUS:OK,X:1"),
                                b10("MATCH", obl="FP:CR,DP:CR,R4:CR,BUS:BY"))],
    *[(FB_REVIEW, v) for v in ("", "unknown", "st=IDLE;st=SAVING", "st=SAVING;st=IDLE", "st=idle", "st=IDLE ", "xst=IDLE", "st=IDLEX",
                               "prior=VALID", "st=")],
    *[(e, v) for e in GATE_KEYS["avail"] for v in ("unknown", "", "true", "On", "ON")],
    *[(SHADOW_STATE, v) for v in ("SHADOW_WATCH", "SHADOW_BOOT", "SHADOW_WOULD_AWAIT_ACK", "shadow_idle", "SHADOW_IDLE ", "", "unknown")],
]
t_gate = time.time()
bad_rev, bad_app = [], []
for setting in SETTINGS:
    v = value_for(3, setting)
    for ent, val in UNSAFE:
        for x in (val, "unavailable"):
            r = Run(setup=lambda y, e_=ent, x_=x: y.w.set(e_, x_)).review(3, setting, v)
            if not (r.res().startswith("REVIEW REFUSED") and r.d.presses == []):
                bad_rev.append((setting, ent[-30:], x[:20], r.res()[:60]))
    for ent, val in AMBIGUOUS:
        r = Run(setup=lambda y, e_=ent, x_=val: y.w.set(e_, x_)).review(3, setting, v)
        if not (r.res().startswith("REVIEW REFUSED") and r.d.presses == []):
            bad_rev.append((setting, ent[-30:], val[:20], r.res()[:60]))
check(f"each setting: each of {len(UNSAFE)} unsafe states, and 'unavailable' for each entity, and {len(AMBIGUOUS)} ambiguous fallback states "
      f"(stale, malformed, duplicated, wrong-case, hazard, wrong operation): the REVIEW is refused, nothing pressed "
      f"({4 * (2 * len(UNSAFE) + len(AMBIGUOUS))} cases)", not bad_rev, str(bad_rev[:4]))
for setting in SETTINGS:
    v = value_for(3, setting)
    for ent, val in UNSAFE:
        for x in (val, "unavailable"):
            r = Run().review(3, setting, v)
            r.w.set(ent, x)
            r.apply(run=3)
            if not (r.res().startswith("REFUSED") and r.d.presses == [] and r.changed() == {}):
                bad_app.append((setting, ent[-30:], x[:20], r.res()[:60]))
check(f"each setting: the same {2 * len(UNSAFE)} states appearing between the Review and the Apply: the APPLY is refused, nothing pressed, nothing written",
      not bad_app, str(bad_app[:4]))
print(f"        (gate sweeps: {time.time() - t_gate:.0f}s)")
bad = []
for setting in SETTINGS:
    v = value_for(3, setting)
    for label, kw in (("a Free Power schedule starting in 10 min", dict(fp_sched="2026-10-12 14:11:00")),
                      ("a Dump to Grid schedule starting in 10 min", dict(dump_sched="2026-10-12 14:11:00")),
                      ("a Free Power schedule starting in 14 min", dict(fp_sched="2026-10-12 14:15:00"))):
        r = Run(**kw).review(3, setting, v)
        if not (r.res().startswith("REVIEW REFUSED") and "within 15 minutes" in r.res()):
            bad.append((setting, label, r.res()[:60]))
    if not Run(fp_sched="2026-10-12 15:00:00").edit(3, setting, v).res().startswith("APPLIED"):
        bad.append((setting, "an hour away"))
check("a Free Power or Dump to Grid schedule within 15 minutes refuses each setting; one an hour away does not block", not bad, str(bad))
for setting in SETTINGS:
    bad = []
    v = value_for(3, setting)
    for ent, val in ((f"binary_sensor.{D}rtc_correction_in_progress", "on"), (f"sensor.{D}ecco_supervision_state", "SUSPECT"),
                     (f"binary_sensor.{D}free_power_operation_in_progress", "on"), (LIVE_MATCH, b10("PAUSED", ca="P", eh="U"))):
        r = Run(setup=late_flip(ent, val)).edit(3, setting, v)
        if not (r.applies() == [] and r.changed() == {} and r.res().startswith("FAILED") and not r.arm_on()):
            bad.append((ent.split(".")[1][-30:], val[:12], r.res()[:60]))
    check(f"{setting}: RTC, supervision, Free Power or the live match going unsafe after the Load, before the press: the last check stops it - "
          "nothing pressed, nothing written, disarmed", not bad, str(bad))
r = Run(setup=late_flip(RESERVE, "50.0")).edit(3, "target_soc", 41)
check("target SOC: the reserve raised after the Load, before the press: the last check stops it", r.applies() == [] and r.changed() == {}
      and r.res().startswith("FAILED"), r.res())

# ======================================================================================================================
print("\n[7] staged == live for every field except the edited one; the helper mirror")
# ======================================================================================================================
OTHER_FIELDS = {"target_soc": ["start", "end", "power", "src", "mode", "gc"], "power": ["start", "end", "soc", "src", "mode", "gc"],
                "start_time": ["end", "power", "soc", "src", "mode", "gc"], "charge_source": ["start", "end", "power", "soc", "mode", "gc"]}
POKE = {"start": 1000, "end": 1700, "power": 2000, "soc": 77, "src": "Generator", "mode": "Backup"}


def poke_after_load(field, edited=False, slot=3, delay=8.0, value=None):
    """Another actor changes a staged field `delay` s after the Load (between the Load and the press)."""
    def setup(x):
        orig = x.d._load

        def load_then(n):
            orig(n)

            def go():
                if field == "gc":
                    x.d.staged_gc = not x.d.staged_gc
                    x.w.set(M.GC_STAGED, "on" if x.d.staged_gc else "off")
                else:
                    x.d.staging[slot][field] = POKE[field] if value is None else value
                    x.d._publish_staging(slot)
            x.w.after(delay, go)
        x.d._load = load_then
    return setup


bad = []
for setting in SETTINGS:
    for field in OTHER_FIELDS[setting] + [key_of(setting)]:
        r = Run(setup=poke_after_load(field)).edit(3, setting, value_for(3, setting))
        if not (r.applies() == [] and r.changed() == {} and r.res().startswith("FAILED") and not r.arm_on()):
            bad.append((setting, field, r.res()[:70], r.d.presses[-1:]))
check("another actor changes ANY other staged field of the slot (start, end_hhmm, power, SOC, charge source, the mode select, the grid-charge "
      "staging switch) - or the edited one - between the Load and the press: FAILED, nothing pressed, nothing written, disarmed "
      f"({sum(len(OTHER_FIELDS[s]) + 1 for s in SETTINGS)} cases)", not bad, str(bad[:4]))
bad = []
for setting in SETTINGS:
    r = Run(setup=poke_after_load("power", slot=4, value=2000)).edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("APPLIED") and r.changed() == expected_change(3, setting) and r.d.regs["slots"][4]["power"] == 8000):
        bad.append((setting, r.res()[:70], r.changed()))
check("a DIFFERENT slot's staged field is not part of this Apply (the firmware reads only the slot's own staging): the edit completes and the "
      "other slot's registers are untouched [requirement 'a different slot's field -> stop' is not what the package does, by construction]",
      not bad, str(bad))
bad = []
HELPER_FLIP = {"target_soc": ("input_number.ecco_manual_slot_3_soc_staged", "77.0"), "power": ("input_number.ecco_manual_slot_3_power_staged", "2000.0"),
               "start_time": ("input_datetime.ecco_manual_slot_3_start_time", None)}
for setting, (ent, val) in HELPER_FLIP.items():
    def flip(x, ent_=ent, val_=val):
        orig = x.d._load

        def load_then(n):
            orig(n)
            if val_ is None:
                x.w.after(8.0, lambda: x.w.call("input_datetime.set_datetime", [ent_], {"time": "10:00:00"}))
            else:
                x.w.after(8.0, lambda: x.w.set(ent_, val_))
        x.d._load = load_then
    r = Run(setup=flip).edit(3, setting, value_for(3, setting))
    if not (r.applies() == [] and r.changed() == {} and r.res().startswith("FAILED")):
        bad.append((setting, r.res()[:70], r.d.presses[-1:]))
    # a helper changed mid-flow for a DIFFERENT field than the edit: also stops (here: the power helper during a SOC / start / source edit)
for setting in ("target_soc", "start_time", "charge_source"):
    r = Run(setup=late_flip("input_number.ecco_manual_slot_3_power_staged", "2000.0")).edit(3, setting, value_for(3, setting))
    if not (r.applies() == [] and r.changed() == {} and r.res().startswith("FAILED")):
        bad.append((setting, "power helper", r.res()[:70]))
check("the owner edits slot 3's helper (SOC, power or start time) mid-flow, or the power helper during another edit: the sync pushes it into "
      "staging and the staged == live proof stops the edit - nothing pressed, nothing written", not bad, str(bad))
check("the charge source has no helper (the Manual Controls helper package declares none, and the package reads none for it)",
      "charge_source" not in HELPERS_TEXT and "input_select" not in HELPERS_TEXT and "h_src" not in S1)


def stale_helpers(r):
    for n in range(1, 7):
        r.w.set(f"input_number.ecco_manual_slot_{n}_power_staged", "0.0")
        r.w.set(f"input_number.ecco_manual_slot_{n}_soc_staged", "9.0")


bad = []
for setting in SETTINGS:
    r = Run(setup=stale_helpers).edit(3, setting, value_for(3, setting))
    r2 = Run(helpers=False).edit(3, setting, value_for(3, setting))
    for x in (r, r2):
        if not (x.res().startswith("APPLIED") and x.changed() == expected_change(3, setting)):
            bad.append((setting, x.res()[:60], x.changed()))
check("stale friendly helpers (power 0 W and SOC 9 % in every slot's helper): the Load + refresh converge them and the edit changes only its "
      "register; the same edit works without the helper package, for each setting", not bad, str(bad))
r = Run().edit(3, "start_time", "09:30")
h = r.w.state("input_datetime.ecco_manual_slot_3_start_time")
check("the start-time helper mirror reaches its fixed point at the NEW staged time (09:30) before the press, and the edit completes",
      h.startswith("09:30") and r.res().startswith("APPLIED"), h)

# ======================================================================================================================
print("\n[8] a fresh read: an inverter change after the last poll to an unrelated field is kept")
# ======================================================================================================================
EXT = {"target_soc": ("power", 3000), "power": ("soc", 45), "start_time": ("power", 3000), "charge_source": ("soc", 45)}
bad = []
for setting in SETTINGS:
    key, val = EXT[setting]

    def external_change(r, key_=key, val_=val):
        # after the last configuration poll before the Load (acs0r1's step 0 holds the Apply until the next inverter clock read), so only a
        # fresh read can carry it into the Load
        r.w.at(T0 + 42 + 7.37 + 60 + 1.5, lambda: r.d.regs["slots"][3].__setitem__(key_, val_))
    r = Run(setup=external_change).edit(3, setting, value_for(3, setting))
    exp = expected_change(3, setting)
    exp[(3, key)] = (DEF[3][key], val)
    if not (r.res().startswith("APPLIED") and r.changed() == exp):
        bad.append((setting, r.res()[:60], r.changed()))
check("an inverter change after the last poll (slot 3: power / SOC) is kept, not reverted: the Apply waits for a fresh read and Loads from "
      "it - for each setting", not bad, str(bad))
r = Run(setup=lambda x: x.w.at(T0 + 72, lambda: x.d.flags.__setitem__("cfg", False))).edit(3, "power", 3000)
check("no fresh configuration read within 90 s: FAILED, nothing written", r.res().startswith("FAILED - no fresh configuration") and r.d.presses == [],
      r.res())
r = Run().review(3, "start_time", "09:30")
r.d.fault["slow_load"] = 40
r.apply()
check("a Load completed more than 30 s after the fresh read: refused (the cache would be too old), nothing pressed",
      r.applies() == [] and r.res().startswith("FAILED") and r.changed() == {}, f"{r.res()} {r.d.presses}")


# ======================================================================================================================
print("\n[9] uncertain outcomes and firmware faults, for each setting: stop, disarm, alert, lock")
# ======================================================================================================================
CLAMP = {"target_soc": {"soc": 45}, "power": {"power": 7000}, "start_time": {"start": 935}, "charge_source": {"src": "None"}}
AFTER_OTHER = {"target_soc": ("power", 5000), "power": ("soc", 45), "start_time": ("power", 5000), "charge_source": ("soc", 45)}
REVERT = {"target_soc": ("soc", 40), "power": ("power", 8000), "start_time": ("start", 900), "charge_source": ("src", "None")}


def other_field_changes(setting):
    key, val = AFTER_OTHER[setting]
    return after_finish(lambda r, n: r.d.regs["slots"][3].__setitem__(key, val))


def edited_field_reverts(setting):
    key, val = REVERT[setting]
    return after_finish(lambda r, n: r.d.regs["slots"][3].__setitem__(key, val))


def no_later_read(r):
    after_finish(lambda x, n: x.w.after(5.0, lambda: x.d.flags.__setitem__("cfg", False)))(r)   # right AFTER the firmware's own post-Apply poll


def cache_invalid_after(r):
    after_finish(lambda x, n: x.w.after(20.0, lambda: x.w.set(f"binary_sensor.{D}manual_configuration_raw_cache_valid", "off")))(r)


def api_blip(polls_after=False):
    """The ESPHome connection drops right after the outcome (before the firmware's own post-Apply poll publishes) and reconnects later,
    re-sending that poll's time; with polls_after=False no periodic poll lands before the judgement."""
    def setup(r):
        st = {"t0": None, "pending": None}
        orig_poll, orig_finish = r.d.poll, r.d._finish

        def poll():
            t0 = st["t0"]
            if t0 is not None and t0 + 2.6 <= r.w.t < t0 + 8.0:
                real_set = r.w.set
                r.w.set = lambda e, v, a=None: (st.__setitem__("pending", v) if e == M.CFG_UPDATE else real_set(e, v, a))
                try:
                    orig_poll()
                finally:
                    r.w.set = real_set
                return
            if not polls_after and t0 is not None and t0 + 8.0 <= r.w.t:
                return
            orig_poll()
        r.d.poll = poll

        def finish(n, failed):
            st["t0"] = r.w.t
            orig_finish(n, failed)
            r.w.after(2.6, lambda: r.w.set(M.CFG_UPDATE, "unavailable"))
            r.w.after(8.0, lambda: r.w.set(M.CFG_UPDATE, st["pending"]))
        r.d._finish = finish
    return setup


LANDED_BEFORE_EDITED = {"target_soc": 4, "power": 3, "start_time": 1, "charge_source": 5}    # write order: 232, start, end, power, SOC, flags


def partial_then_rejected(setting):
    """Transactions land up to (not including) the edited register (each rewrites its current value, so every register reads unchanged),
    the sequence stops, and an unrelated REJECTED text overwrites the result: only the gate-pass counter shows that a write happened."""
    def setup(r):
        r.d.fault["partial"] = LANDED_BEFORE_EDITED[setting]
        after_finish(lambda x, n: x.w.after(0.5, lambda: x.w.set(M.RESULT, "REJECTED - arm Manual Configuration Write Enable first")))(r)
    return setup


def rejected_text_overwrites(r):
    after_finish(lambda x, n: x.w.after(0.5, lambda: x.w.set(M.RESULT, "REJECTED - cannot load Slot 2 staging while Free Power or Dump to "
                                                                       "Grid owns TOU settings")))(r)


def skew_after_write(r):
    after_finish(lambda x, n: x.d.fault.__setitem__("clock_skew", 900.0))(r)


def drop_apply(r):
    orig = r.d._press

    def press(entity, data):
        if "apply_manual" in entity:
            r.d.presses.append((r.w.t, "apply-dropped", "DROPPED"))
            return
        orig(entity, data)
    r.w.service_handlers["button.press"] = press


def arm_stuck(r):
    """The Apply press and every later turn_off are lost (API trouble): the write enable stays ON."""
    orig_off, orig_press = r.d._switch(False), r.d._press

    def turn_off(entity, data):
        if entity == M.ARM:
            return
        orig_off(entity, data)

    def press(entity, data):
        if "apply_manual" in entity:
            r.d.presses.append((r.w.t, "apply-dropped", "DROPPED"))
            return
        orig_press(entity, data)
    r.w.service_handlers["switch.turn_off"] = turn_off
    r.w.service_handlers["button.press"] = press


for setting in SETTINGS:
    v, key = value_for(3, setting), key_of(setting)
    print(f"  -- {setting}")
    r = Run(setup=lambda x: x.d.fault.__setitem__("refuse_bus", True)).edit(3, setting, v)
    check(f"{setting}: bus busy at the gate: FAILED (refused; nothing written, confirmed by the unchanged gate-pass counter and two later reads), "
          "one Apply, never retried, not locked, alerted", r.res().startswith("FAILED - the firmware refused") and len(r.applies()) == 1
          and r.changed() == {} and not r.arm_on() and not r.locked() and r.notes() != [] and r.d.attempts == 0, r.res())
    r = Run(setup=lambda x: x.d.fault.__setitem__("verify_fail", True)).edit(3, setting, v)
    uncertain(r, f"{setting}: the firmware's verification fails")
    for k in range(0, 6):
        r = Run(setup=lambda x, k_=k: x.d.fault.__setitem__("partial", k_)).edit(3, setting, v)
        uncertain(r, f"{setting}: a partial write stopping after {k} of 6 transactions (only the edited register may differ)",
                  set(r.changed()) <= {(3, key)})
    r = Run(setup=lambda x, c=CLAMP[setting]: x.d.fault.__setitem__("clamp", c)).edit(3, setting, v)
    uncertain(r, f"{setting}: the inverter stores {CLAMP[setting]} instead of the request (the firmware's exact verify fails)")
    r = Run(setup=lambda x: x.d.fault.__setitem__("clamp", {"mode": "Backup"})).edit(3, setting, v)
    uncertain(r, f"{setting}: the inverter stores another MODE than written (a non-edited field)", "mode" in r.note())
    r = Run(setup=lambda x: x.d.fault.__setitem__("clamp", {"end": 1700})).edit(3, setting, v)
    uncertain(r, f"{setting}: the inverter stores another END than written (slot 4's start, a non-edited register)", (4, "start") in r.changed())
    r = Run(setup=other_field_changes(setting)).edit(3, setting, v)
    uncertain(r, f"{setting}: the firmware says VERIFIED OK but the independent later read shows another register changed "
                 f"({AFTER_OTHER[setting][0]}) - the alert names it", {"power": "power ", "soc": "SOC "}[AFTER_OTHER[setting][0]] in r.note())
    r = Run(setup=edited_field_reverts(setting)).edit(3, setting, v)
    uncertain(r, f"{setting}: the firmware says VERIFIED OK but the later read shows the EDITED field not at the request ({REVERT[setting][0]} "
                 "back to its old value)", REVERT[setting][0] in r.note() or {"soc": "SOC", "start": "start", "power": "power", "src": "source"}[
                     REVERT[setting][0]] in r.note())
    r = Run(setup=no_later_read).edit(3, setting, v)
    uncertain(r, f"{setting}: only the firmware's own post-Apply poll arrives (no poll that began after it): not enough",
              "no complete later configuration read" in r.note())
    r = Run(setup=cache_invalid_after).edit(3, setting, v)
    uncertain(r, f"{setting}: the later read is incomplete (raw configuration cache invalid)", "no complete later configuration read" in r.note())
    r = Run(setup=api_blip()).edit(3, setting, v)
    uncertain(r, f"{setting}: a connection drop and the reconnect's re-sent time are not two reads", "no complete later configuration read" in r.note())
    r = Run(setup=api_blip(polls_after=True)).edit(3, setting, v, run=480)
    check(f"{setting}: ...the same drop with the periodic polls continuing: APPLIED AND VERIFIED on a poll that began after the firmware's own",
          r.res().startswith("APPLIED AND VERIFIED") and r.changed() == expected_change(3, setting) and not r.locked(), r.res())
    r = Run(setup=partial_then_rejected(setting)).edit(3, setting, v)
    uncertain(r, f"{setting}: registers unchanged + a REJECTED text, but the gate-pass counter moved: never 'nothing written'",
              not r.res().startswith("FAILED") and r.changed() == {})
    r = Run(setup=rejected_text_overwrites).edit(3, setting, v)
    uncertain(r, f"{setting}: a REJECTED text from an unrelated press overwrites the result after a real write: never 'nothing written'",
              not r.res().startswith("FAILED") and r.changed() == expected_change(3, setting))
    r = Run(setup=skew_after_write).edit(3, setting, v, run=480)
    uncertain(r, f"{setting}: the later reads' times are not coherent with Home Assistant's clock (a dongle clock jump after the write)",
              "no complete later configuration read" in r.note())
    r = Run(setup=arm_stuck).edit(3, setting, v)
    check(f"{setting}: the write enable cannot be confirmed off at the end: UNCERTAIN, LOCKED, alerted", r.res().startswith("UNCERTAIN")
          and r.locked() and "not confirmed off" in str(r.notes()), f"{r.res()} {r.notes()}")
    r = Run(setup=drop_apply)
    r.review(3, setting, v)
    r.ha.start_script(APPLY, {"confirmation": r.phrase()})
    on_t = off_t = None
    for _ in range(4200):
        r.w.run_until(r.w.t + 0.1)
        if r.w.state(M.ARM) == "on" and on_t is None:
            on_t = r.w.t
        if on_t is not None and r.w.state(M.ARM) == "off" and off_t is None:
            off_t = r.w.t
    check(f"{setting}: an Apply press that never arrives: the write enable is turned off right after the firmware's 45 s window (on for at most 50 s)",
          on_t is not None and off_t is not None and off_t - on_t <= 50, f"{on_t} {off_t}")
    uncertain(r, f"{setting}: an Apply press that never arrives (nothing written, but that cannot be proven)", r.changed() == {})
    r.review(2, "target_soc", 60)
    check(f"{setting}: while locked, a new Review is refused", r.res().startswith("REVIEW REFUSED - an earlier edit"), r.res())
    r.ha.start_script(ACK, {"confirmation": "I have checked"})
    r.w.run_until(r.w.t + 1)
    check(f"{setting}: a wrong acknowledgement phrase keeps it locked", r.locked())
    r.ha.start_script(ACK, {"confirmation": "I HAVE CHECKED THE TOU SLOTS"})
    r.w.run_until(r.w.t + 1)
    check(f"{setting}: the exact acknowledgement unlocks (and writes nothing to the inverter)", not r.locked() and r.res().startswith("ACKNOWLEDGED")
          and len(r.applies()) == 1)
    r.review(3, setting, v)
    check(f"{setting}: after the acknowledgement a new Review is accepted again", r.res().startswith("REVIEWED"), r.res())


def restart_mid_edit(setting, v, unreachable=False):
    """Review + Apply, Home Assistant goes down mid-flow with the write enable ON, and comes back with the dongle's entities unavailable."""
    r = Run().review(3, setting, v)
    r.ha.start_script(APPLY, {"confirmation": r.phrase()})
    r.w.run_until(r.w.t + 45)
    r.ha.stop()
    r.d.arm = True
    r.w.set(M.ARM, "unavailable")
    r.w.run_until(r.w.t + 30)
    orig = r.d._switch(False)
    if unreachable:
        r.w.service_handlers["switch.turn_off"] = lambda ent, data: None if ent == M.ARM else orig(ent, data)
    r.ha = S.HA(r.w, [yaml.safe_load(S1), yaml.safe_load(HELPERS_TEXT)])
    if unreachable:
        r.w.service_handlers["switch.turn_off"] = lambda ent, data: None if ent == M.ARM else orig(ent, data)
    r.ha.start()
    return r


for setting in SETTINGS:
    v = value_for(3, setting)
    r = restart_mid_edit(setting, v)
    n_apply = len(r.applies())
    r.w.run_until(r.w.t + 1)
    locked_at_once = r.locked() and r.res().startswith("UNCERTAIN - the edit was interrupted")
    r.review(2, "target_soc", 60)
    review_blocked = r.res().startswith("REVIEW REFUSED - an earlier edit") and r.w.state(PLAN) == "used"
    r.ha.start_script(APPLY, {"confirmation": "SET SLOT 3 POWER 3000 W REVIEW 0000"})
    r.w.run_until(r.w.t + 2)
    check(f"{setting}: restart mid-edit: LOCKED and UNCERTAIN within a second of Home Assistant starting; a Review or Apply in that window is refused",
          locked_at_once and review_blocked and r.res().startswith("REFUSED") and r.locked() and len(r.applies()) == n_apply, f"{r.res()} {r.w.state(PLAN)}")
    r.w.at(r.w.t + 90, lambda: r.w.set(M.ARM, "on"))
    r.w.run_until(r.w.t + 120)
    check(f"{setting}: ...when the dongle returns with the write enable ON, the watchdog turns it off and confirms it", not r.arm_on()
          and r.w.state(M.ARM) == "off" and "ecco_cfg_edit_arm" not in r.w.notifications and r.w.state(FLIGHT) == "off")
r = restart_mid_edit("power", 3000, unreachable=True)
r.w.at(r.w.t + 60, lambda: r.w.set(M.ARM, "on"))
r.w.run_until(r.w.t + 700)
check("...when the write enable cannot be turned off: a separate 'NOT confirmed off' alert, still LOCKED", r.locked()
      and "NOT confirmed off" in r.w.notifications.get("ecco_cfg_edit_arm", {}).get("title", ""), str(list(r.w.notifications)))
r = Run()
r.w.set(FLIGHT, "on")
r.w.run_until(r.w.t + 5)
check("an Apply cancelled mid-flight (script reload): the watchdog fires on the stopped run - UNCERTAIN, LOCKED",
      r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked() and r.w.state(FLIGHT) == "off", r.res())

# ======================================================================================================================
print("\n[10] races")
# ======================================================================================================================
for setting in SETTINGS:
    v = value_for(3, setting)
    r = Run(setup=lambda x: x.w.at(T0 + 80, lambda: x.d.set_flag("fp_op", True))).edit(3, setting, v)
    r2 = Run(setup=late_flip(f"binary_sensor.{D}free_power_operation_in_progress", "on")).edit(3, setting, v)
    check(f"{setting}: Free Power starts a transaction while the Apply waits for the fresh read, or takes ownership right after the Load: "
          "FAILED, never pressed, nothing written", r.res().startswith("FAILED") and r.changed() == {} and r.applies() == []
          and r2.res().startswith("FAILED") and r2.changed() == {} and r2.applies() == [], f"{r.res()} | {r2.res()}")
bad = []
for setting in SETTINGS:
    v = value_for(3, setting)
    r = Run().review(3, setting, v)
    ph = r.phrase()
    r.ha.start_script(APPLY, {"confirmation": ph})
    r.w.run_until(r.w.t + 5)
    r.ha.start_script(APPLY, {"confirmation": ph})
    r.w.run_until(r.w.t + 420)
    if not (len(r.applies()) == 1 and any("already running" in m for m in r.w.warnings) and r.res().startswith("APPLIED")):
        bad.append((setting, len(r.applies()), r.res()[:50]))
check("a second Apply while one runs is not started (single mode): one Apply press, for each setting", not bad, str(bad))
bad = []
for setting in SETTINGS:
    v = value_for(3, setting)
    r = Run().review(3, setting, v)
    r.ha.start_script(APPLY, {"confirmation": r.phrase()})
    r.w.run_until(r.w.t + 75)
    mid = r.res()
    r.ha.start_script(REVIEW, {"slot": 2, "setting": "target_soc", "value": 55})
    r.ha.start_script(ACK, {"confirmation": "I HAVE CHECKED THE TOU SLOTS"})
    r.w.run_until(r.w.t + 2)
    ok = (mid.startswith("IN PROGRESS") and r.res() == mid and r.w.state(PLAN) == "used" and r.w.state(FLIGHT) == "on"
          and "ecco_cfg_edit_busy" in r.w.notifications)
    r.ha.stop()
    r.w.run_until(r.w.t + 30)
    r.ha = S.HA(r.w, [yaml.safe_load(S1), yaml.safe_load(HELPERS_TEXT)])
    r.ha.start()
    r.w.run_until(r.w.t + 120)
    ok = ok and r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked()
    if not ok:
        bad.append((setting, mid[:40], r.res()[:40]))
check("a Review or Acknowledge while an Apply runs is refused and touches neither the result, the plan nor the in-flight marker, and a restart "
      "after it still catches the interrupted run - for each setting", not bad, str(bad))

# ======================================================================================================================
print("\n[11] acs0r1 timing is inherited: the ONE press in a quiet gap of the Modbus poll cycle")
# ======================================================================================================================
TEL = f"sensor.{D}last_telemetry_update"


def cfg_before_press(r):
    ap = r.applies()
    cfgs = [t for t, e, s in r.w.history if e == M.CFG_UPDATE and ap and t < ap[0][0]]
    return round(ap[0][0] - max(cfgs), 2) if ap and cfgs else None


def tel_before_press(r):
    ap = r.applies()
    tels = [t for t, e, s in r.w.history if e == TEL and s not in ("unknown", "unavailable") and ap and t < ap[0][0]]
    return round(ap[0][0] - max(tels), 2) if ap and tels else None


def ok1(r, setting="target_soc", n=3):
    """APPLIED with exactly one press, no bus refusal, and the press 1.5-4.6 s after a real telemetry completion."""
    d = tel_before_press(r)
    return (not r.d.bus_refusals and len(r.applies()) == 1 and r.res().startswith("APPLIED") and d is not None and 1.5 <= d <= 4.6
            and cfg_before_press(r) < 30 and r.changed() == expected_change(n, setting))


bad = []
for setting in SETTINGS:
    r = Run().edit(3, setting, value_for(3, setting))
    if not ok1(r, setting):
        bad.append((setting, r.res()[:50], tel_before_press(r), cfg_before_press(r)))
    else:
        print(f"        {setting}: the press is {tel_before_press(r)} s after a telemetry completion, {cfg_before_press(r)} s after the fresh read")
check("each setting: the press is 1.5-4.6 s after a clean telemetry completion and < 30 s after the fresh read: APPLIED, one press, no refusal",
      not bad, str(bad))
bad = []
for i in range(12):
    off = round(0.1 + i * 0.9, 2)
    for setting in ("power", "start_time", "charge_source"):
        r = Run(dkw=dict(tel_offset=off)).edit(3, setting, value_for(3, setting))
        if not ok1(r, setting):
            bad.append((setting, off, r.res()[:50]))
check("telemetry phase sweep (12 offsets x power / start time / charge source): APPLIED, one quiet press, cache age < 30 s", not bad, str(bad[:3]))
bad = []
for clk in range(0, 60, 6):
    r = Run(dkw=dict(clock_offset=clk + 0.37)).edit(3, "start_time", "09:30")
    if not ok1(r, "start_time"):
        bad.append((clk, r.res()[:50]))
check("inverter clock read phase sweep (10 offsets) for a start-time edit: APPLIED, one quiet press", not bad, str(bad))
bad = []
for arm in (0.05, 1.5, 2.6):
    for press in (0.05, 0.4):
        r = Run(dkw=dict(arm_latency=arm, press_latency=press)).edit(3, "power", 3000)
        if r.d.bus_refusals or len(r.applies()) != 1 or not r.res().startswith("APPLIED"):
            bad.append((arm, press, r.res()[:50]))
check("scheduler jitter (arm latency 0.05-2.6 s x press latency 0.05-0.4 s): APPLIED, no refusal", not bad, str(bad))
r = Run(dkw=dict(arm_latency=4.5)).edit(3, "charge_source", "Grid")
check("an arm confirmed only 4.5 s after the delay: the press would leave the quiet window, so nothing is pressed (FAILED)", r.applies() == []
      and r.res().startswith("FAILED - a safety check changed just before the Apply") and r.changed() == {} and not r.arm_on(), r.res())
r = Run(dkw=dict(tel_period=5.0)).edit(3, "power", 3000)
check("a 5 s telemetry period (no gap long enough): FAILED before the Load, nothing pressed", r.d.presses == []
      and "telemetry poll period" in r.res() and r.changed() == {}, r.res())
r = Run(dkw=dict(clock_offset=None)).edit(3, "start_time", "09:30")
check("no inverter clock read seen within 65 s: FAILED before the Load, nothing pressed (fail-closed)", r.d.presses == []
      and "no inverter clock read was seen" in r.res() and r.changed() == {}, r.res())
bad = []
for setting in SETTINGS:
    a = Run(legacy=True, setup=lambda x: x.d.fault.__setitem__("refuse_bus", True)).edit(3, "target_soc", 41)
    b = Run(setup=lambda x: x.d.fault.__setitem__("refuse_bus", True)).edit(3, setting, value_for(3, setting))
    if not (cls(a) == cls(b) == "FAILED" and b.res().startswith("FAILED - the firmware refused") and len(b.applies()) == len(a.applies()) == 1
            and b.changed() == a.changed() == {} and not b.locked() and not a.locked() and b.d.attempts == a.d.attempts == 0
            and a.res().split("(", 1)[0] == b.res().split("(", 1)[0]):
        bad.append((setting, a.res()[:60], b.res()[:60]))
check("a bus-busy refusal at the quiet press (another, unmodelled bus user) is final and handled exactly as Stage 0 handles it, for each setting: "
      "one press, FAILED - the firmware refused, nothing written, no retry, not locked", not bad, str(bad))
r = Run(dkw=dict(tel_offset=5.1, post_busy=0.6)).edit(3, "power", 3000)
check("a bus still busy 0.6 s after the telemetry publish does not meet the press (1.5 s into the gap)", ok1(r, "power"), r.res())
check("still exactly one Apply press in the package (Loads: the pre-Apply Load and F2's re-Load of slot N, F1's one Load of slot N-1); no repeat "
      "(no retry path) in the Apply",
      S1.count('entity_id: "{{ e.apply }}"') == 1 and S1.count('entity_id: "{{ e.load }}"') == 2 and S1.count('entity_id: "{{ e.p_load }}"') == 1
      and "repeat:" not in S1.split(f"{APPLY}:", 1)[1].split(f"{ACK}:", 1)[0])

# ======================================================================================================================
print("\n[11b] follow-up behaviours (owner-approved 2026-10-20): F1 Load of slot N-1, F2 re-Load of slot N, F3 live power multiple of 100, F4 Review warnings")
# ======================================================================================================================


WSEEN = "input_boolean.ecco_cfg_edit_write_seen"


def btn(r):
    """The entities of every button.press service call, in order."""
    return [c[2] for c in r.w.service_log if c[1] == "button.press"]


def arms_on(r):
    return [c for c in r.w.service_log if c[1] == "switch.turn_on" and M.ARM in c[2]]


def load_seq(r, since=0):
    return [p[1] for p in r.d.presses[since:] if p[1].startswith("load")]


def staged_eq_live(r, n):
    """Slot n's staging in the model equals the live slot in every field (start, end, power, SOC, source, mode)."""
    s, st = r.d.regs["slots"][n], r.d.staging[n]
    return (st["start"], st["end"], st["power"], st["soc"], st["src"], st["mode"]) == (
        s["start"], r.d.end_of(r.d.regs, n), s["power"], s["soc"], s["src"], s["mode"])


def prev_of(n):
    return 6 if n == 1 else n - 1


# --- F1: after a VERIFIED start-time edit of slot N the editor presses Load Current Slot N-1 (slot 1 -> slot 6) and verifies its staged end
bad = []
for n in range(1, 7):
    pv = prev_of(n)
    r = Run()
    r.d._load(pv)                                     # the owner loaded slot N-1 into Manual Controls earlier: its staged end holds the OLD boundary
    r.w.run_until(r.w.t + 1)
    old_end, k0 = r.d.staging[pv]["end"], len(r.d.presses)
    r.edit(n, "start_time", NEW_START[n])
    new = hhmm_of(NEW_START[n])
    ok = (r.res().startswith("APPLIED AND VERIFIED") and old_end != new and r.d.staging[pv]["end"] == new and r.d.loaded[pv]
          and load_seq(r, k0) == [f"load{n}", f"load{pv}"] and len(r.applies()) == 1 and len(arms_on(r)) == 1
          and btn(r) == [f"button.{D}load_current_slot_{n}_to_manual_staging", f"button.{D}apply_manual_slot_{n}_settings",
                         f"button.{D}load_current_slot_{pv}_to_manual_staging"]
          and r.changed() == expected_change(n, "start_time") and "refreshed by the editor" in r.note() and "could NOT" not in r.note()
          and not r.locked() and r.w.state(FLIGHT) == "off" and not r.arm_on() and not r.w.warnings and not r.invalid())
    if not ok:
        bad.append((n, pv, r.res()[:60], load_seq(r, k0), r.d.staging[pv]["end"], r.note()[-160:]))
check("F1: a verified start-time edit of every slot (1..6; slot 1 -> slot 6) is followed by exactly ONE Load Current Slot N-1 (after the Apply), "
      "slot N-1's pre-loaded staged end holds the new boundary, ONE arm and ONE Apply in the whole run, the notice says the staging was refreshed, "
      "only the edited register changed", not bad, str(bad[:3]))
bad = []
for setting in ("target_soc", "power", "charge_source"):
    r = Run().edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("APPLIED") and load_seq(r) == ["load3"] and len(r.applies()) == 1
            and btn(r) == [f"button.{D}load_current_slot_3_to_manual_staging", f"button.{D}apply_manual_slot_3_settings"]
            and "Manual Controls staging" not in r.note()):
        bad.append((setting, load_seq(r), btn(r)))
check("F1: no extra Load for a SOC, power or charge-source edit (one Load, one Apply, no staging sentence in the notice)", not bad, str(bad))
r = Run()
r.d._load(2)
r.w.run_until(r.w.t + 1)
assert r.d.loaded[2] and r.d.staging[2]["end"] == 900
r.edit(3, "start_time", "09:30")
staged_new = r.d.staging[2]["end"] == 930
r.d.busy = 0.0                                       # a quiet bus: the point is the staging, not the poll timing
r.w.call("switch.turn_on", [M.ARM], {})
r.w.run_until(r.w.t + 2)
r.w.call("button.press", [f"button.{D}apply_manual_slot_2_settings"], {})
r.w.run_until(r.w.t + 20)
check("REPAIRED (was residual 7): after the edit moved slot 3's start to 09:30 the editor refreshed slot 2's staging, so a later Manual Controls "
      "Apply of slot 2 no longer writes the old end back - slot 3's start stays 09:30 and the firmware says VERIFIED OK",
      staged_new and r.d.regs["slots"][3]["start"] == 930 and r.w.state(M.RESULT).startswith("VERIFIED OK - manual Slot 2"),
      f"{r.d.regs['slots'][3]} {r.w.state(M.RESULT)}")


fp_on_finish = after_finish(lambda y, k: y.d.set_flag("fp_op", True))


bad = []
for n in (3, 1, 2, 6):
    pv = prev_of(n)
    r = Run(setup=fp_on_finish)
    r.d._load(pv)
    r.w.run_until(r.w.t + 1)
    old_end, k0 = r.d.staging[pv]["end"], len(r.d.presses)
    r.edit(n, "start_time", NEW_START[n], run=480)
    ok = (r.res().startswith("APPLIED AND VERIFIED") and load_seq(r, k0) == [f"load{n}"] and r.d.staging[pv]["end"] == old_end
          and f"Slot {pv}'s Manual Controls staging could NOT be refreshed by the editor" in r.note()
          and f"Before any Manual Controls Apply of slot {pv}, press Load Current Slot {pv} (or Load All): its staged end still holds the old" in r.note()
          and not r.locked() and len(r.applies()) == 1 and len(arms_on(r)) == 1 and r.changed() == expected_change(n, "start_time"))
    if not ok:
        bad.append((n, r.res()[:60], load_seq(r, k0), r.note()[-200:]))
check("F1: when the Load is not allowed (Free Power takes the TOU settings right after the edit) the edit STAYS successful (verified, not locked), no "
      "Load of slot N-1 is pressed, and the notice says plainly that the staging could not be refreshed and to press Load Current Slot N-1 "
      "(or Load All) before any Manual Controls Apply", not bad, str(bad[:2]))


def load_ignored(slot, after_first=False):
    """The Load of `slot` is pressed but has no effect (the firmware dropped it); with after_first the first press still works."""
    def setup(x):
        orig, seen = x.d._load, {"n": 0}

        def ld(n):
            if n == slot:
                seen["n"] += 1
                if seen["n"] > (1 if after_first else 0):
                    x.d.presses.append((x.w.t, f"load{n}", "IGNORED"))
                    return
            orig(n)
        x.d._load = ld
    return setup


bad = []
for n in (3, 1):
    pv = prev_of(n)
    r = Run(setup=load_ignored(pv))
    r.d.staging[pv]["end"] = 1234                      # a stale value that is NOT the new boundary
    r.d._publish_staging(pv)
    r.edit(n, "start_time", NEW_START[n], run=480)
    if not (r.res().startswith("APPLIED AND VERIFIED") and load_seq(r).count(f"load{pv}") == 1 and not r.locked()
            and f"Slot {pv}'s Manual Controls staging could NOT be refreshed" in r.note() and len(r.applies()) == 1):
        bad.append((n, r.res()[:60], load_seq(r), r.note()[-160:]))
check("F1: the Load is pressed once but slot N-1's staged end does not become the new boundary: the edit stays SUCCESSFUL, never retried (one press), "
      "the notice says the staging could not be refreshed", not bad, str(bad[:2]))

# --- F2: re-Load slot N ONLY when the run has conclusively established that no inverter write was attempted
F2_NOTE_OK, F2_NOTE_BAD = "staging was refreshed to the live values", "staging may still hold the reviewed value"


def f2_ok_case(r, n=3):
    return (r.res().startswith("FAILED") and load_seq(r) == [f"load{n}", f"load{n}"] and staged_eq_live(r, n) and not r.locked() and not r.arm_on()
            and r.changed() == {} and F2_NOTE_OK in r.note() and F2_NOTE_BAD not in r.note() and r.w.state(FLIGHT) == "off"
            and r.d.attempts == 0 and r.w.state(M.ATTEMPTS) == "0.0" and r.w.state(WSEEN) == "off" and "nothing written" in r.res())   # the counter-proven path


bad = []
for setting in SETTINGS:
    v = value_for(3, setting)
    for label, setup, dkw in (
            ("RTC correction starts after the Load", late_flip(f"binary_sensor.{D}rtc_correction_in_progress", "on"), None),
            ("supervision turns SUSPECT after the Load", late_flip(f"sensor.{D}ecco_supervision_state", "SUSPECT"), None),
            ("no quiet window (telemetry stops after the fresh read)", lambda x: x.w.at(T0 + 165, lambda: x.d.flags.__setitem__("tel", False)), None),
            ("the arm confirmed too late", None, dict(arm_latency=4.5))):
        r = Run(setup=setup, dkw=dkw).edit(3, setting, v)
        if not (r.res().startswith("FAILED") and r.applies() == [] and f2_ok_case(r)):
            bad.append((setting, label, r.res()[:60], load_seq(r), r.note()[-120:]))
check("F2(a): every FAILED branch that ends after the editor staged the value and BEFORE the Apply press (a safety check changing after the Load, "
      "no quiet window, a late arm) re-Loads slot N once: staging equals the live slot again, nothing pressed, nothing written, not locked, the notice says "
      "so (4 branches x 4 settings)", not bad, str(bad[:3]))
bad = []
r = Run(setup=late_flip(RESERVE, "50.0")).edit(3, "target_soc", 41)
if not (r.res().startswith("FAILED") and f2_ok_case(r)):
    bad.append(("reserve", r.res()[:70], load_seq(r)))
for setting in SETTINGS:
    # another actor changes a staged field between the Load and the press: the re-Load puts the live values back
    r = Run(setup=poke_after_load("soc" if setting == "power" else "power")).edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("FAILED") and r.applies() == [] and len(r.loads()) == 2 and F2_NOTE_OK in r.note() and not r.locked()):
        bad.append((setting, "poke", r.res()[:60], load_seq(r), r.note()[-100:]))
check("F2(a): the reserve rises after the Load (SOC edit) and another actor changes a staged field between the Load and the press: FAILED, re-Loaded once "
      "(a poked field is overwritten by the Load), not locked", not bad, str(bad[:3]))
bad = []
for setting in SETTINGS:
    r = Run(setup=lambda x: x.d.fault.__setitem__("refuse_bus", True)).edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("FAILED - the firmware refused") and f2_ok_case(r) and len(r.applies()) == 1 and r.d.attempts == 0):
        bad.append((setting, r.res()[:70], load_seq(r), r.note()[-100:]))
check("F2(b): the firmware refused at its gate - refusal text AND an unchanged gate-pass counter AND both later reads at the pre-edit values - re-Loads slot N "
      "once (staging equals live), one Apply press only, not locked, for each setting", not bad, str(bad[:3]))

# negatives: nothing but the two conclusive verdicts may re-Load
bad = []
NEG_CASES = [
    ("the firmware's verification fails", lambda x: x.d.fault.__setitem__("verify_fail", True)),
    *[(f"a partial write stopping after {k} transactions", lambda x, k_=k: x.d.fault.__setitem__("partial", k_)) for k in range(6)],
    ("the inverter stores a clamped power", lambda x: x.d.fault.__setitem__("clamp", {"power": 7000})),
    ("another register changes right after the Apply", other_field_changes("power")),
    ("no later configuration read", no_later_read),
    ("the cache invalid after the Apply", cache_invalid_after),
    ("an API blip and a replayed time", api_blip()),
    ("registers unchanged, a REJECTED text, but the counter moved", partial_then_rejected("power")),
    ("a REJECTED text overwrites a real write", rejected_text_overwrites),
    ("the write enable cannot be confirmed off", arm_stuck),
    ("the Apply press never arrives", drop_apply),
    ("the dongle clock jumps after the write", skew_after_write),
]
for label, setup in NEG_CASES:
    r = Run(setup=setup).edit(3, "power", 3000, run=520)
    if not (r.res().startswith("UNCERTAIN") and r.locked() and load_seq(r) == ["load3"] and "Do NOT retry" in r.note()
            and F2_NOTE_OK not in r.note() and F2_NOTE_BAD not in r.note() and len(r.applies()) <= 1):
        bad.append((label, r.res()[:70], load_seq(r), r.locked(), r.note()[-80:]))
for setting in ("start_time", "charge_source", "target_soc"):
    r = Run(setup=lambda x: x.d.fault.__setitem__("verify_fail", True)).edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("UNCERTAIN") and r.locked() and load_seq(r) == ["load3"] and btn(r)[-1].endswith("apply_manual_slot_3_settings")):
        bad.append(("verify_fail", setting, r.res()[:50], load_seq(r)))
for setting in SETTINGS:
    r = restart_mid_edit(setting, value_for(3, setting))
    r.w.run_until(r.w.t + 200)
    if not (r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked() and len(load_seq(r)) <= 1):
        bad.append(("restart", setting, r.res()[:50], load_seq(r)))
check(f"F2 negatives: for EVERY unproven outcome ({len(NEG_CASES)} faults on power, verify failure on the other settings, a restart mid-edit for each "
      "setting) - UNCERTAIN, partial writes 0-5, clamp, another register changing, no or incomplete later reads, a REJECTED text with a moved counter, a "
      "dropped press, the arm not confirmed off, a clock jump - there is NO extra Load, the lock is kept, the notice is the unchanged manual-recovery one",
      not bad, str(bad[:3]))
bad = []
for label, setup in (("the heartbeat is dead (no fresh evidence)", lambda x: x.d.fault.__setitem__("hb_dead", True)),
                     ("the helpers do not settle after the Load", late_flip("input_number.ecco_manual_slot_3_power_staged", "2000.0"))):
    r = Run(setup=setup).edit(3, "power", 3000)
    if not (r.res().startswith("FAILED") and r.applies() == [] and len(r.loads()) <= 1 and F2_NOTE_OK not in r.note() and F2_NOTE_BAD not in r.note()):
        bad.append((label, r.res()[:70], load_seq(r)))
r = Run().review(3, "power", 3000)
r.ha.start_script(APPLY, {"confirmation": "SET SLOT 3 POWER 3000 W REVIEW 0000"})
r.w.run_until(r.w.t + 5)
if not (r.res().startswith("REFUSED") and r.loads() == []):
    bad.append(("refused", r.res()[:50], load_seq(r)))
check("F2 scope: a run that stopped BEFORE the editor staged anything (a refused Apply, a Review problem, the helpers not settling after the Load) is not re-Loaded",
      not bad, str(bad))
bad = []
for setting in ("power", "start_time"):
    r = Run(setup=late_flip(f"binary_sensor.{D}free_power_operation_in_progress", "on")).edit(3, setting, value_for(3, setting), run=520)
    if not (r.res().startswith("FAILED") and load_seq(r) == ["load3"] and F2_NOTE_BAD in r.note() and "Load Current Slot 3 (or Load All)" in r.note()
            and not r.locked() and r.applies() == []):
        bad.append((setting, "free power", r.res()[:60], load_seq(r), r.note()[-140:]))
r = Run(setup=lambda x: (load_ignored(3, after_first=True)(x), late_flip(f"binary_sensor.{D}rtc_correction_in_progress", "on")(x))).edit(3, "power", 3000, run=520)
if not (r.res().startswith("FAILED") and load_seq(r).count("load3") == 2 and not staged_eq_live(r, 3) and F2_NOTE_BAD in r.note() and not r.locked()):
    bad.append(("ignored", r.res()[:60], load_seq(r), r.note()[-140:]))
check("F2: when the re-Load is refused (Free Power owns the TOU settings) or has no effect, nothing else is done (one Load press at most, no Apply, not locked) and "
      "the notice says slot N's staging may still hold the reviewed value and to press Load Current Slot N (or Load All) before any Manual Controls Apply",
      not bad, str(bad[:2]))

# --- F3: a power edit is refused when the LIVE slot power is not a multiple of 100 W (Review and every later gate copy)
r = Run(layout=slot_set(3, power=2550)).review(3, "power", 3000)
check("F3: live slot power 2550 W: the power Review is refused with the reason (not a multiple of 100 W; the undo would be refused; align it first in Manual Controls)",
      rejects(r) and "the live slot power 2550.0 W is not a multiple of 100 W; the undo would be refused - align it first in Manual Controls" in r.res(), r.res())
r = Run(layout=slot_set(3, power=2500)).edit(3, "power", 3000)
check("F3: live 2500 W is fine - the power edit applies", r.res().startswith("APPLIED") and r.changed() == {(3, "power"): (2500, 3000)}, r.res())
r = Run(layout=slot_set(3, power=2550)).review(3, "target_soc", 55)
check("F3 scope: the rule is for power edits only - a target-SOC Review on a slot with live power 2550 W is accepted", accepts(r), r.res())
r = Run().review(3, "power", 3000)
r.d.regs["slots"][3]["power"] = 2550                 # the live power changes between the Review and the Apply
r.d.poll()
r.w.run_until(r.w.t + 100)
r.apply()
check("F3: the live power changes to 2550 W between the Review and the Apply: refused at the Apply, nothing pressed, nothing written",
      r.res().startswith("REFUSED") and r.d.presses == [] and r.changed() == {(3, "power"): (8000, 2550)}, r.res())


def power_to_2550_at(t_off):
    def setup(x):
        def go():
            x.d.regs["slots"][3]["power"] = 2550
            x.d.poll()
        x.w.at(T0 + t_off, go)
    return setup


r = Run(setup=power_to_2550_at(100)).edit(3, "power", 3000)
check("F3: the live power changes to 2550 W after the Apply started (the fresh-read gate): FAILED with the reason, nothing pressed",
      r.res().startswith("FAILED") and "the live slot power 2550.0 W is not a multiple of 100 W" in r.res() and r.d.presses == [], r.res())


def power_to_2550_after_load(x):
    orig = x.d._load

    def ld(n):
        orig(n)

        def go():
            x.d.regs["slots"][3]["power"] = 2550
            x.d.poll()
        x.w.after(8.0, go)
    x.d._load = ld


r = Run(setup=power_to_2550_after_load).edit(3, "power", 3000)
check("F3: the live power changes to 2550 W between the Load and the press (the last-check gate): FAILED with the reason, nothing pressed",
      r.res().startswith("FAILED") and "the live slot power 2550.0 W is not a multiple of 100 W" in r.res() and r.applies() == [], r.res())

# --- F4: Review notification text (a persistent notification) and the input_text limit
DUMP_W = "A slot with a charge source set makes a scheduled Dump to Grid whose window overlaps it refuse at start (no health alert counts that refusal)."
SMART_W = "Do not use SmartDeye or the inverter's own panel until this edit is finished."
cases = [("charge_source -> Grid", 3, "charge_source", "Grid", None, True), ("charge_source -> None", 1, "charge_source", "None", None, False),
         ("start_time on a slot whose live source is None", 3, "start_time", "09:30", None, False),
         ("start_time on a slot whose live source is Grid", 1, "start_time", "00:30", None, True),
         ("power", 3, "power", 3000, None, False), ("target_soc", 3, "target_soc", 41, None, False)]
bad = []
for label, n, setting, v, lay, dump in cases:
    r = Run().review(n, setting, v)
    nt = r.note("ecco_cfg_edit_review")
    if not ((DUMP_W in nt) == dump and SMART_W in nt and r.res().startswith("REVIEWED")):
        bad.append((label, DUMP_W in nt, SMART_W in nt))
check("F4: the Review notification always says not to use SmartDeye or the inverter's own panel until the edit is finished, and carries the Dump to Grid "
      "warning for a charge source set to Grid and for a start-time edit on a slot whose live charge source is not None - and for no other case", not bad, str(bad))
bad = []
for setting in SETTINGS:
    for n in (1, 3):
        r = Run().review(n, setting, value_for(n, setting))
        vals = [r.w.state(PLAN), r.res()]
        r.apply()
        vals += [r.w.state(PLAN), r.res(), r.w.state(EDIT)]
        if not (all(len(x) < 255 for x in vals) and not r.w.warnings):
            bad.append((setting, n, [len(x) for x in vals]))
r = Run(setup=lambda x: x.d.fault.__setitem__("refuse_bus", True)).edit(3, "charge_source", "Grid")
if not (len(r.res()) < 255 and len(r.w.state(PLAN)) < 255 and not r.w.warnings):
    bad.append(("refusal", len(r.res())))
check("F4: every input_text value (plan, last result, last owner edit) stays under 255 characters, through Review and Apply and a firmware refusal, "
      "for every setting (no Home Assistant overflow)", not bad, str(bad))


# --- F2 correction: "nothing pressed" is not "no inverter write" - the write enable is shared and the firmware accepts ANY Apply press while it is on
def after_load(fn, delay):
    """Run fn(run) `delay` s after every Load the dongle receives."""
    def setup(x):
        orig = x.d._load

        def ld(n):
            orig(n)
            x.w.after(delay, lambda: fn(x))
        x.d._load = ld
    return setup


def ext_apply_after_arm(delay, slot=3):
    """Another actor presses Apply of `slot` `delay` s after the write enable is switched on (the editor's own arm)."""
    def setup(x):
        orig = x.w.service_handlers["switch.turn_on"]

        def on(ent, data):
            orig(ent, data)
            if ent == M.ARM:
                x.w.after(delay, lambda: x.w.call("button.press", [f"button.{D}apply_manual_slot_{slot}_settings"], {}))
        x.w.service_handlers["switch.turn_on"] = on
    return setup


def counter_unavailable(x):
    real = x.w.set
    x.w.set = lambda e, v, a=None: real(e, "unavailable" if e == M.ATTEMPTS else v, a)
    real(M.ATTEMPTS, "unavailable")


def bump_counter(x):
    x.d.attempts += 1
    x.w.set(M.ATTEMPTS, f"{float(x.d.attempts)}")


def bump_counter_late(x):
    """An armed-window write whose write-in-progress edge nobody sees and whose gate-pass counter reaches Home Assistant only 40 s later (the firmware
    publishes it every 30 s): only the counter delta, read after the publish wait, proves the write."""
    real, t_pub = x.w.set, x.w.t + 40.0

    def held(e, v, a=None):
        if e == M.ATTEMPTS and x.w.t < t_pub:
            return None
        return real(e, v, a)
    x.w.set = held
    x.d.attempts += 1
    x.w.after(40.0, lambda: real(M.ATTEMPTS, f"{float(x.d.attempts)}"))


def blip_write_in_progress(x):
    x.w.set(M.MANUAL, "on")
    x.w.after(2.0, lambda: x.w.set(M.MANUAL, "off"))


RTC_LATE = lambda: late_flip(f"binary_sensor.{D}rtc_correction_in_progress", "on")      # noqa: E731  (a pre-press FAILED, after the staging)


def both(*setups):
    return lambda x: [f(x) for f in setups]


def unproven_ok(r, n=3):
    """UNCERTAIN, locked, the existing UNCERTAIN notification, NO extra Load, and the claim 'nothing written' appears nowhere."""
    every = r.res() + " " + str(r.w.notifications)
    return (r.res().startswith("UNCERTAIN") and r.locked() and load_seq(r) == [f"load{n}"] and "Do NOT retry" in r.note()
            and "nothing written" not in every and F2_NOTE_OK not in r.note() and F2_NOTE_BAD not in r.note() and r.w.state(FLIGHT) == "off" and not r.arm_on())


bad = []
for setting in ("power", "start_time", "target_soc"):
    for dly in (0.02, 0.1):
        # the editor's last check runs 0.5 s after it armed (a slow arm confirmation), so the write-in-progress flag of the other actor's Apply is visible:
        # the run stops before its press (the pre-press branch) and cannot prove that nothing was written
        r = Run(setup=ext_apply_after_arm(dly), dkw=dict(arm_latency=0.5)).edit(3, setting, value_for(3, setting), run=520)
        if not (unproven_ok(r) and r.changed() == expected_change(3, setting) and "an Apply by someone else may have run" in r.note()):
            bad.append((setting, dly, r.res()[:90], load_seq(r), r.locked(), r.changed()))
check("F2 correction: an Apply by ANOTHER actor lands 0.02 s / 0.1 s after the editor armed and its write-in-progress is visible at the editor's last check "
      "(the firmware accepts any Apply press while the write enable is on) - the inverter IS written (power, start time and target SOC): the run stops "
      "before its press and is UNCERTAIN, locked, with the manual-recovery notification saying an Apply by someone else may have run, NO re-Load, and "
      "'nothing written' appears in neither the result nor any notification", not bad, str(bad[:3]))
bad = []
for setting in ("power", "start_time", "target_soc"):
    # the other actor's Apply lands before the editor's last check can see its flag: the editor presses (the firmware refuses it, a write is running)
    r = Run(setup=ext_apply_after_arm(0.05)).edit(3, setting, value_for(3, setting), run=520)
    every = r.res() + " " + str(r.w.notifications)
    if not ("nothing written" not in every and F2_NOTE_OK not in r.note() and load_seq(r)[:1] == ["load3"] and "load3" not in load_seq(r)[1:]
            and r.changed() == expected_change(3, setting) and len(r.applies()) >= 1):
        bad.append((setting, r.res()[:80], load_seq(r), r.changed()))
check("F2 correction: the same external Apply landing so early that the editor's flag check misses it: the editor presses (refused by the firmware: a write is "
      "running) and the usual success verdict judges the final state (the requested value, firmware readback, two later reads); no 'nothing written' claim, no "
      "re-Load of slot N (a start-time edit's F1 Load of slot N-1 may follow a verified success)", not bad, str(bad[:3]))
bad = []
for label, setup in (
        ("only the firmware's gate-pass counter moved (an Apply whose write-in-progress and text were never seen)", both(RTC_LATE(), after_load(bump_counter, 5.0))),
        ("the gate-pass counter is unavailable (unreadable)", both(RTC_LATE(), counter_unavailable)),
        ("the write-in-progress flag was on for 2 s inside the staged window, the counter unchanged", both(RTC_LATE(), after_load(blip_write_in_progress, 6.0))),
        ("the firmware's last result showed a write", both(RTC_LATE(), after_load(lambda x: x.w.set(M.RESULT, "Writing Slot3 0900-1600, 8000W, 40%, None/General, grid charge on"), 6.0)))):
    r = Run(setup=setup).edit(3, "power", 3000, run=520)
    if not unproven_ok(r):
        bad.append((label, r.res()[:90], load_seq(r), r.locked()))
check("F2 correction: after a pre-press FAILED the 'nothing written' claim needs ALL of: the counter unchanged since before the staging, no write-in-progress "
      "or write text seen. Counter moved only / counter unavailable / write-in-progress seen / a write text seen: UNCERTAIN, locked, no re-Load", not bad, str(bad[:3]))
r = Run(setup=both(RTC_LATE(), after_load(bump_counter_late, 5.0))).edit(3, "power", 3000, run=520)
check("F2 correction: an armed-window write whose write-in-progress edge is never seen and whose gate-pass counter reaches Home Assistant 40 s late: only the counter "
      "delta read AFTER the 35 s publish wait proves it - UNCERTAIN, locked, no re-Load, no 'nothing written'", unproven_ok(r), f"{r.res()} {load_seq(r)}")
r = Run(setup=RTC_LATE()).edit(3, "power", 3000, run=520)
fail_t = [t for t, e, v in r.w.history if e == RESULT and v.startswith("FAILED - a safety check")]
arm_off_t = [t for t, e, v in r.w.history if e == M.ARM and v == "off" and fail_t and t < fail_t[0]]
check("F2 correction: the proven path waits for the counter to publish (the FAILED result is set at least 35 s after the editor disarmed) and then still "
      "re-Loads: counter unchanged, no write seen", bool(fail_t) and bool(arm_off_t) and fail_t[0] - arm_off_t[-1] >= 35 and f2_ok_case(r), f"{fail_t} {arm_off_t} {r.res()}")


def live_power_fraction_after_review(t):
    x = Run(t, layout=slot_set(3, power=2500)).review(3, "power", 3000)
    x.d.regs["slots"][3]["power"] = 2500.5            # int() of it is still the reviewed 2500, so only the live-power rule can refuse
    x.d.poll()
    x.w.run_until(x.w.t + 100)
    x.apply()
    return x


r = live_power_fraction_after_review(S1)
check("F3: the Apply-start gate copy itself: the live power becomes 2500.5 W after a Review made at 2500 W (the reviewed integer is unchanged): REFUSED with the "
      "multiple-of-100 reason, nothing pressed", r.res().startswith("REFUSED") and "multiple of 100" in r.res() and r.d.presses == [], r.res())


# --- N2 (owner-approved 2026-10-21): the success verdict also needs the firmware's gate-pass counter to have moved by EXACTLY 1 since before the staging
def ext_after_finish(slot, delay=3.0, preload=True):
    """Another actor: `delay` s after the editor's Apply finished it arms and presses Apply of `slot` (preloaded into Manual Controls staging at the start,
    or loaded just before its own Apply). The firmware counts it as a second gate pass."""
    def setup(x):
        if preload:
            x.d._load(slot)

        fired = []

        def go(y, n):
            if fired:                                    # only the editor's own Apply triggers the other actor, once
                return
            fired.append(1)
            if not preload:
                y.d._load(slot)
            y.d.busy = 0.0
            y.w.call("switch.turn_on", [M.ARM], {})
            y.w.after(1.5, lambda: (setattr(y.d, "busy", 0.0), y.w.call("button.press", [f"button.{D}apply_manual_slot_{slot}_settings"], {})))
        after_finish(go, delay)(x)
    return setup


def counter_reset_setup(x):
    x.d.attempts = 5
    x.w.set(M.ATTEMPTS, "5.0")
    after_finish(lambda y, n: setattr(y.d, "attempts", 0), 1.0)(x)


def n2_uncertain(r, setting="start_time", n=3, passes=None, apply_presses=1):
    """UNCERTAIN, locked, the manual-recovery notification names the counter and the delta, NO undo offer, NO F1 Load, NO re-Load, one editor Apply press."""
    prev = 6 if n == 1 else n - 1
    b = btn(r)
    return (r.res().startswith("UNCERTAIN") and r.locked() and "To undo" not in r.note() and "gate-pass counter went" in r.note()
            and "another Apply - possibly of a different slot - may have run" in r.note() and "Do NOT retry" in r.note()
            and f"button.{D}load_current_slot_{prev}_to_manual_staging" not in b and b.count(f"button.{D}load_current_slot_{n}_to_manual_staging") == 1
            and b.count(f"button.{D}apply_manual_slot_{n}_settings") == apply_presses and F2_NOTE_OK not in r.note() and F2_NOTE_BAD not in r.note()
            and (passes is None or r.d.attempts == passes) and "APPLIED" not in r.res() and r.w.state(FLIGHT) == "off" and len(r.res()) < 255)


bad = []
for setting in SETTINGS:
    r = Run().edit(3, setting, value_for(3, setting))
    if not (r.res().startswith("APPLIED AND VERIFIED") and r.d.attempts == 1 and r.w.state(M.ATTEMPTS) == "1.0" and not r.locked()):
        bad.append((setting, r.res()[:60], r.d.attempts))
check("N2: a normal verified edit moves the gate-pass counter by exactly 1 (read 35 s after the press, after the counter published): APPLIED AND VERIFIED for "
      "every setting", not bad, str(bad))
bad = []
for setting in ("power", "start_time", "target_soc"):
    r = Run(setup=ext_apply_after_arm(0.05)).edit(3, setting, value_for(3, setting), run=520)
    if not (r.res().startswith("APPLIED AND VERIFIED") and r.d.attempts == 1 and "nothing written" not in r.res()):
        bad.append((setting, r.res()[:70], r.d.attempts))
check("N2 caveat (i): another actor's Apply wrote the reviewed staging and the editor's own press was refused (the firmware was already writing): the counter "
      "moved by exactly 1, the final state is the requested one and verified, so it stays APPLIED AND VERIFIED, as documented", not bad, str(bad))
bad = []
for setting in ("start_time", "power", "target_soc"):
    r = Run(setup=ext_after_finish(5, 3.0)).edit(3, setting, value_for(3, setting), run=520)
    if not (n2_uncertain(r, setting, passes=2)):
        bad.append((setting, r.res()[:90], r.d.attempts, r.note()[-160:]))
check("N2: another actor's Apply of a DIFFERENT, already loaded slot (5) passes the firmware's gate while the editor's own Apply also passed: the counter moved "
      "by 2 - UNCERTAIN, locked, the notification shows the counter and says another Apply, possibly of a different slot, may have run, no undo offer, no F1 Load "
      "of slot N-1, no re-Load, for a start-time, power and SOC edit", not bad, str(bad[:2]))
r = Run(setup=ext_after_finish(3, 5.0, preload=False)).edit(3, "start_time", "09:30", run=520)
check("N2: a second Apply of the SAME slot passes after the editor's own (counter +2): UNCERTAIN, locked, no undo, no F1 Load", n2_uncertain(r, passes=2, apply_presses=2),
      f"{r.res()} {r.d.attempts} {btn(r)}")
r = Run(setup=lambda x: after_finish(lambda y, n: counter_unavailable(y), 5.0)(x)).edit(3, "start_time", "09:30", run=520)
check("N2: the counter is unavailable when the verdict reads it: UNCERTAIN, locked, no undo, no F1 Load", n2_uncertain(r), f"{r.res()} {r.note()[-120:]}")
r = Run(setup=lambda x: after_finish(lambda y, n: setattr(y.d, "attempts", y.d.attempts - 1), 1.0)(x)).edit(3, "start_time", "09:30", run=520)
check("N2: the counter did not move at all (delta 0) on an otherwise verified run: UNCERTAIN, locked, no undo, no F1 Load", n2_uncertain(r), f"{r.res()} {r.note()[-120:]}")
r = Run(setup=counter_reset_setup).edit(3, "start_time", "09:30", run=520)
check("N2: the counter was reset (the dongle rebooted: a value below the one recorded before the staging): UNCERTAIN, locked, no undo, no F1 Load",
      n2_uncertain(r), f"{r.res()} {r.note()[-120:]}")

# ======================================================================================================================
print("\n[11x] acs1x: the last copy of the gate refuses alone (something changes between the fresh read and the press)")
# ======================================================================================================================


def live_start_after_load(slot, hhmm, delay=8.0):
    """Another tool changes slot `slot`'s live start to `hhmm` `delay` s after the editor's first Load (after the fresh read, before the last
    check before the press); the dongle polls it at once."""
    def setup(x):
        orig, done = x.d._load, []

        def ld(n):
            orig(n)
            if not done:
                done.append(n)

                def go():
                    x.d.regs["slots"][slot]["start"] = hhmm
                    x.d.poll()
                x.w.after(delay, go)
        x.d._load = ld
    return setup


LAST_FRAME = "FAILED - a safety check changed just before the Apply ({}); nothing pressed, nothing written"


def last_check_alone(t, edit_slot, v, setup, text_, changed):
    """The edit is Reviewed and passes the Apply's gate and the fresh read; then `setup`'s change happens after the Load, and only the last
    check refuses. True when the designed path runs: the FAILED result (within the helper) is recorded, the ecco_cfg_edit notice is sent, the
    F2 re-Load restores the edited slot's staging to the live slot, nothing is pressed or written by the editor (no Apply press, no gate
    pass), not locked, not armed, out of flight, and only the other actor's change is on the inverter."""
    r = Run(t, layout=owner_full, t0=NOON, setup=setup).edit(edit_slot, "start_time", v, run=480)
    return (r.res() == LAST_FRAME.format(text_) and len(r.res()) <= 255 and r.applies() == [] and r.d.attempts == 0
            and r.d.writes == [] and load_seq(r) == [f"load{edit_slot}", f"load{edit_slot}"] and staged_eq_live(r, edit_slot)
            and LAST_FRAME.format(text_) in r.note() and F2_NOTE_OK in r.note() and F2_NOTE_BAD not in r.note() and not r.locked()
            and not r.arm_on() and r.w.state(FLIGHT) == "off" and r.changed() == changed), r


MATCH_VALUE = "OUT_OF_DOMAIN"
LAST_CASES = (
    ("the hold, slot 6 00:25 -> 00:20 Reviewed, live slot 6 moved to 23:00 after the Load (the crossing would move)",
     6, "00:20", live_start_after_load(6, 2300), XW.REFUSE_XW, {(6, "start"): (25, 2300)}),
    ("the hold, mirror: slot 5 22:00 -> 23:55 Reviewed, live slot 5 moved to 00:10 after the Load",
     5, "23:55", live_start_after_load(5, 10), XW.REFUSE_XW, {(5, "start"): (2200, 10)}),
    ("acs1c's cycle refusal (rewritten, 163 characters): slot 6 -> 00:20 Reviewed, live slot 2 moved to 00:20 (not one cycle)",
     6, "00:20", live_start_after_load(2, 20), XW.REFUSE_CYC_NEW, {(2, "start"): (530, 20)}),
    ("acs1c's neighbour refusal (rewritten, 157 characters): slot 6 -> 00:20 Reviewed, live slot 5 moved to 00:20 (the new start equals it)",
     6, "00:20", live_start_after_load(5, 20), XW.REFUSE_ORDER_NEW, {(5, "start"): (2200, 20)}),
    ("the fallback live match refusal (rewritten, 161 characters with its value): slot 6 -> 00:20 Reviewed, the live match turns "
     f"{MATCH_VALUE} after the Load", 6, "00:20", late_flip(LIVE_MATCH, b10(m=MATCH_VALUE)),
     XW.REFUSE_MATCH_NEW.replace("{{ L.split(';m=')[1].split(';')[0][:16] }}", MATCH_VALUE), {}),
)
x_bad = []
for label, es, v, setup, txt, chg in LAST_CASES:
    ok, r = last_check_alone(S1, es, v, setup, txt, chg)
    if not ok:
        x_bad.append((label[:50], r.res()[:120], load_seq(r), r.changed(), r.d.writes, r.note()[:80]))
check(f"the last copy of the gate alone refuses ({len(LAST_CASES)} cases: the hold for slot 6 and its mirror for slot 5, acs1c's cycle and neighbour "
      "refusals, the fallback live match refusal): each records 'FAILED - a safety check changed just before the Apply (<the whole refusal>); nothing "
      "pressed, nothing written' within the 255-character helper, sends the ecco_cfg_edit notice, re-Loads the edited slot (F2: its staging equals "
      "the live slot), presses no Apply and writes no register, passes no gate, is not locked or armed; only the other actor's change is on the "
      "inverter (review findings X1 / X2)", not x_bad, str(x_bad[:2]))
r_x = Run(S1C, layout=owner_full, t0=NOON, setup=live_start_after_load(6, 2300)).edit(6, "start_time", "00:20", run=480)
check("...and on the acs1c text the slot 6 race is pressed and written (APPLIED AND VERIFIED, slot 6 at 00:20, the crossing moved): the last copy's "
      "hold is what stops it", r_x.res().startswith("APPLIED AND VERIFIED") and r_x.d.regs["slots"][6]["start"] == 20, r_x.res()[:80])
# The same cases on the defect itself (review finding X1): the package as first committed had the long refusal texts and a hold text of 187
# characters. Rebuilt in memory (the four rewrites undone; the hold's text replaced by a neutral text of that length), every case above fails
# there as the review reproduced it: the over-long FAILED text is not stored, the result stays IN PROGRESS, no notice, no F2 re-Load, and the
# refused start stays staged in Manual Controls (staging != live), although nothing is pressed.
FIRST_HOLD_LEN = 187
S1_X1 = S1.replace(XW.REFUSE_XW, XW.REFUSE_XW.ljust(FIRST_HOLD_LEN, "."))
for _old, _new in XW.REWRITES:
    S1_X1 = S1_X1.replace("%}" + _new + "\n", "%}" + _old + "\n")
assert S1_X1.count(XW.REFUSE_XW.ljust(FIRST_HOLD_LEN, ".")) == 4 and all(S1_X1.count("%}" + o_ + "\n") == 4 for o_, _n in XW.REWRITES)


def stuck_in_progress(t, edit_slot, v, setup):
    """The X1 failure mode: nothing pressed or written, but no FAILED result, no notice, no F2 re-Load, and the edited slot's staging differs
    from the live slot."""
    r = Run(t, layout=owner_full, t0=NOON, setup=setup).edit(edit_slot, "start_time", v, run=480)
    return (r.res().startswith("IN PROGRESS") and r.applies() == [] and r.d.attempts == 0 and r.d.writes == []
            and load_seq(r) == [f"load{edit_slot}"] and "FAILED" not in r.note() and not staged_eq_live(r, edit_slot)), r


x_bad = []
for label, es, v, setup, _txt, _chg in LAST_CASES:
    ok, r = stuck_in_progress(S1_X1, es, v, setup)
    if not ok:
        x_bad.append((label[:50], r.res()[:80], load_seq(r), r.note()[:60]))
check(f"...and the {len(LAST_CASES)} cases detect the defect: on the package as first committed (the long refusal texts, a 187-character hold "
      "text; rebuilt in memory) each leaves the result 'IN PROGRESS', no notice, no F2 re-Load and the refused value staged (staging != live), as "
      "the review reproduced; with the rewritten texts (above) each takes the designed FAILED path", not x_bad, str(x_bad[:2]))


def live_start_before_fresh_read(slot, hhmm, delay=1.0):
    """Another tool changes slot `slot`'s live start to `hhmm` `delay` s after the Apply's gate passed (its 'waiting for a fresh configuration
    read' result written), before the fresh read; the dongle polls it at once. Only the fresh-read copy of the gate sees it first."""
    def setup(x):
        orig, done = x.w.set, []

        def set_(entity_id, state, attrs=None):
            orig(entity_id, state, attrs)
            if not done and entity_id == RESULT and str(state).startswith("IN PROGRESS") and "waiting for a fresh configuration read" in str(state):
                done.append(entity_id)

                def go():
                    x.d.regs["slots"][slot]["start"] = hhmm
                    x.d.poll()
                x.w.after(delay, go)
        x.w.set = set_
    return setup


FRESH_FRAME = "FAILED - {}; nothing written"


def fresh_read_alone(t, edit_slot, v, setup, text_, changed):
    """The edit is Reviewed and passes the Apply's gate; `setup`'s change happens before the fresh read, so the fresh-read copy alone refuses.
    True when its result is exactly 'FAILED - <the whole refusal>; nothing written' (FB-1: pinned in full), the notice carries it, and no Load,
    press or register write happened (the refusal is not the last check's, which follows the Load)."""
    r = Run(t, layout=owner_full, t0=NOON, setup=setup).edit(edit_slot, "start_time", v, run=480)
    return (r.res() == FRESH_FRAME.format(text_) and FRESH_FRAME.format(text_) in r.note() and r.loads() == [] and r.applies() == []
            and r.d.attempts == 0 and r.d.writes == [] and not r.locked() and not r.arm_on() and r.w.state(FLIGHT) == "off"
            and r.changed() == changed), r


FRESH_CASES = (
    ("the hold (156 characters), slot 6 00:25 -> 00:20 Reviewed, live slot 6 moved to 23:00 after the Apply's gate",
     6, "00:20", live_start_before_fresh_read(6, 2300), XW.REFUSE_XW, {(6, "start"): (25, 2300)}),
    ("acs1c's cycle refusal (rewritten, 163 characters, the longest), slot 6 -> 00:20 Reviewed, live slot 2 moved to 00:20 after the Apply's gate",
     6, "00:20", live_start_before_fresh_read(2, 20), XW.REFUSE_CYC_NEW, {(2, "start"): (530, 20)}),
)
x_bad = []
for label, es, v, setup, txt, chg in FRESH_CASES:
    ok, r = fresh_read_alone(S1, es, v, setup, txt, chg)
    if not ok:
        x_bad.append((label[:50], r.res()[:200], r.loads(), r.changed(), r.d.writes, r.note()[:80]))
check(f"the fresh-read copy of the gate alone refuses ({len(FRESH_CASES)} cases: the hold, acs1c's cycle refusal; a live start changes between the "
      "Apply's gate and the fresh read): the result is exactly 'FAILED - <the whole refusal>; nothing written' (pinned in full, so a shortened "
      "refusal fails), the notice carries it, no Load, no press, no register write, not locked or armed (review finding FB-1)",
      not x_bad, str(x_bad[:2]))

# ======================================================================================================================
print("\n[12] mutation: in-memory mutants of the installed package, each caught by the battery")
# ======================================================================================================================


def rv(text, slot, setting, value, **kw):
    return Run(text, **kw).review(slot, setting, value)


def tampered_apply(text, bad_want):
    """A Review of slot 5 -> 21:55 on the owner's layout, its record's value replaced by hand, then the Apply with the matching phrase."""
    r = Run(text, layout=OWNER_LAYOUT, t0=NOON).review(5, "start_time", "21:55")
    rec = r.w.state(PLAN).split("|")
    rec[2] = str(bad_want)
    r.w.set(PLAN, "|".join(rec))
    return r.apply(phrase=f"SET SLOT 5 START {bad_want // 100:02d}:{bad_want % 100:02d} REVIEW {rec[3]}", run=120)


def no_hold(t):
    """`t` with the acs1x refusal turned off in memory (all four copies). acs1x refuses a two-wrap live layout and every move across midnight
    before acs1c's own rules see them; the acs1c rules it pre-empts (the cycle rule's single wrap, the active-slot guard across midnight) are
    killed on this text, so a mutant of those inherited lines is still caught ([0x] proves the lines byte-identical to acs1c's)."""
    return t.replace("{% elif setting == 'start_time' and not xw %}", "{% elif false %}")


def xw_review_check(t):
    """The Review refuses the crossing-moving edits with the hold's text and accepts the edits that keep the crossing."""
    return (all(XW.REFUSE_XW in rv(t, s, "start_time", v, layout=OWNER_LAYOUT, t0=NOON).res() for s, v in ((6, "23:55"), (5, "00:05")))
            and all(accepts(rv(t, s, "start_time", v, layout=OWNER_LAYOUT, t0=NOON)) for s, v in ((6, "00:20"), (5, "23:55"))))


def xw_apply_check(t):
    """The Apply's OWN gate (its first copy, before the fresh read) refuses a hand-edited record that moves the crossing: REFUSED, no Load."""
    x = tampered_apply(t, 5)
    return x.res() == "REFUSED - " + XW.REFUSE_XW + "; nothing written" and x.loads() == [] and x.applies() == []


def xw_copies_check(t):
    """Each of the four gate copies, rendered alone (GateWorld), refuses the crossing-moving edits with the hold's text and passes the others."""
    gw = GateWorld(t)
    return (all(gw.results(s, v) == [XW.REFUSE_XW] * 4 for s, v in ((5, "00:05"), (6, "23:55"), (5, "00:00")))
            and gw.results(6, "00:20") == [""] * 4 and gw.results(5, "23:55") == [""] * 4)


def xw_first_check(t):
    """The hold refuses before the 15-minute and active-slot guards: at 23:00 (between the old and the new boundary of slot 5 -> 00:05) the
    refusal names the crossing."""
    return XW.REFUSE_XW in rv(t, 5, "start_time", "00:05", layout=OWNER_LAYOUT, t0=S.parse_local("2026-10-26 23:00:00") - 70).res()


def _restore_last(new, old):
    """The rewritten refusal `new` put back to its long form `old` in the LAST copy of the gate only (its fourth occurrence)."""
    def f(t):
        a = "%}" + new + "\n"
        assert t.count(a) == 4
        i = t.rindex(a)
        return t[:i] + "%}" + old + "\n" + t[i + len(a):]
    return f


def _drop_xw_copy(k):
    """The hold's refusal turned off in ONE copy of the gate: k = 0 the Review, 1 the Apply's gate, 2 its fresh-read re-check, 3 its last check."""
    def f(t):
        a = "{% elif setting == 'start_time' and not xw %}"
        assert t.count(a) == 4
        i = -1
        for _ in range(k + 1):
            i = t.index(a, i + 1)
        return t[:i] + "{% elif false %}" + t[i + len(a):]
    return f


# The three results that write a refusal outside the last check (the Review, the Apply's gate, the fresh read), for the FB-1 mutants
SLICE_REVIEW = "REVIEW REFUSED - {{ refusal }}; nothing written"
SLICE_GATE = "REFUSED - {{ review_problem if review_problem else refusal }}; nothing written"
SLICE_FRESH = "FAILED - {{ fresh_why if not fresh else (refusal2 if refusal2 else"
assert all(S1.count(a_) == 1 for a_ in (SLICE_REVIEW, SLICE_GATE, SLICE_FRESH))


def _xw_after_mid(t):
    """The hold's refusal moved from right after the proposed-layout refusal to right after the active-slot guard, in every copy."""
    for ind, _c in XW.GATE_COPIES:
        sp = "\n" + " " * ind
        line = sp + "{% elif setting == 'start_time' and not xw %}" + XW.REFUSE_XW
        mid_line = (sp + "{% elif mid %}the current local time lies between the old and the new boundary: the edit would change which slot is "
                    "active right now")
        assert t.count(line) == t.count(mid_line) >= 1
        t = t.replace(line, "").replace(mid_line, mid_line + line)
    return t


def poke_check(setting, field, **kw):
    def f(text):
        x = Run(text, setup=poke_after_load(field, **kw)).edit(3, setting, value_for(3, setting))
        return x.changed() == {} and x.applies() == []
    return f


def uncertain_locked(x):
    return x.res().startswith("UNCERTAIN") and x.locked() and len(x.applies()) == 1


def happy(setting):
    def f(text):
        x = Run(text).edit(3, setting, value_for(3, setting))
        return x.changed() == expected_change(3, setting) and x.res().startswith("APPLIED") and not x.arm_on()
    return f


def phrase_check(text):
    x = Run(text).review(3, "power", 3000)
    code = x.code()
    x.apply(phrase=f"SET SLOT 3 TARGET SOC 3000 REVIEW {code}", run=240)
    y = Run(text).review(3, "power", 3000)
    y.apply(phrase=f"SET SLOT 3 POWER 3000 W REVIEW {(int(y.code()) + 1) % 10000:04d}", run=240)
    return x.d.presses == [] and y.d.presses == []


def changed_check(text):
    x = Run(text, setup=inverter_change("power", 5000)).review(3, "power", 3000)
    x.w.run_until(T0 + 80)
    x.apply(run=240)
    return x.d.presses == []


def verdict_edited(text):
    out = []
    for setting in SETTINGS:
        x = Run(text, setup=edited_field_reverts(setting)).edit(3, setting, value_for(3, setting))
        out.append(uncertain_locked(x))
    return all(out)


def verdict_other(text):
    x = Run(text, setup=other_field_changes("target_soc")).edit(3, "target_soc", 41)
    return uncertain_locked(x)


def clamp_check(text):
    out = []
    for setting in SETTINGS:
        x = Run(text, setup=lambda y, c=CLAMP[setting]: y.d.fault.__setitem__("clamp", c)).edit(3, setting, value_for(3, setting))
        out.append(uncertain_locked(x))
    return all(out)


def external(text):
    def ch(r):
        r.w.at(T0 + 42 + 7.37 + 60 + 1.5, lambda: r.d.regs["slots"][3].__setitem__("power", 3000))
    x = Run(text, setup=ch).edit(3, "target_soc", 41)
    return x.d.regs["slots"][3]["power"] == 3000 and x.res().startswith("APPLIED")


def clean_refusal(fn):
    try:
        return rejects(fn())
    except Exception:  # noqa: BLE001 - a raising template is not a refusal
        return False


def f1_check(t):
    r = Run(t)
    r.d._load(2)
    r.w.run_until(r.w.t + 1)
    k0 = len(r.d.presses)
    r.edit(3, "start_time", "09:30")
    r2 = Run(t).edit(1, "start_time", "00:30")
    return (r.res().startswith("APPLIED") and load_seq(r, k0) == ["load3", "load2"] and r.d.staging[2]["end"] == 930
            and r2.res().startswith("APPLIED") and load_seq(r2) == ["load1", "load6"] and r2.d.staging[6]["end"] == 30)


def f1_nonstart(t):
    return all(load_seq(Run(t).edit(3, st, value_for(3, st))) == ["load3"] for st in ("target_soc", "power", "charge_source"))


def f2_pre(t):
    return f2_ok_case(Run(t, setup=late_flip(f"binary_sensor.{D}rtc_correction_in_progress", "on")).edit(3, "power", 3000))


def f2_unc(t):
    out = []
    for setup in (lambda x: x.d.fault.__setitem__("verify_fail", True), lambda x: x.d.fault.__setitem__("partial", 2), other_field_changes("power")):
        x = Run(t, setup=setup).edit(3, "power", 3000)
        out.append(x.res().startswith("UNCERTAIN") and load_seq(x) == ["load3"] and x.locked())
    return all(out)


def f2_counter(t):
    x = Run(t, setup=partial_then_rejected("power")).edit(3, "power", 3000)
    return x.res().startswith("UNCERTAIN") and load_seq(x) == ["load3"] and x.locked()


def f3_review(t):
    return rejects(rv(t, 3, "power", 3000, layout=slot_set(3, power=2550)))


def f3_fresh(t):
    x = Run(t, setup=power_to_2550_at(100)).edit(3, "power", 3000)
    return x.res().startswith("FAILED") and "multiple of 100" in x.res() and x.d.presses == []


def f3_last(t):
    x = Run(t, setup=power_to_2550_after_load).edit(3, "power", 3000)
    return x.res().startswith("FAILED") and "multiple of 100" in x.res() and x.applies() == []


def f4_check(t):
    a = Run(t).review(3, "charge_source", "Grid").note("ecco_cfg_edit_review")
    b = Run(t).review(3, "power", 3000).note("ecco_cfg_edit_review")
    return DUMP_W in a and SMART_W in a and DUMP_W not in b and SMART_W in b


def f2_ext(t):
    return all(unproven_ok(Run(t, setup=ext_apply_after_arm(0.05), dkw=dict(arm_latency=0.5)).edit(3, st, value_for(3, st), run=520)) for st in ("power", "target_soc"))


def f2_cnt(t):
    return unproven_ok(Run(t, setup=both(RTC_LATE(), after_load(bump_counter, 5.0))).edit(3, "power", 3000, run=520))


def f2_unav(t):
    return unproven_ok(Run(t, setup=both(RTC_LATE(), counter_unavailable)).edit(3, "power", 3000, run=520))


def f2_wip(t):
    return unproven_ok(Run(t, setup=both(RTC_LATE(), after_load(blip_write_in_progress, 6.0))).edit(3, "power", 3000, run=520))


def f2_cap(t):
    # the counter moves AFTER the staging began and BEFORE a capture made after the staging: only a capture before the staging notices it
    return unproven_ok(Run(t, setup=both(RTC_LATE(), after_load(bump_counter, 3.5))).edit(3, "power", 3000, run=520))


def n2_ok_check(t):
    return all(Run(t).edit(3, st, value_for(3, st)).res().startswith("APPLIED AND VERIFIED") for st in ("start_time", "power"))


def n2_other_check(t):
    return n2_uncertain(Run(t, setup=ext_after_finish(5, 3.0)).edit(3, "start_time", "09:30", run=520), passes=2)


def n2_double_check(t):
    return n2_uncertain(Run(t, setup=ext_after_finish(3, 5.0, preload=False)).edit(3, "start_time", "09:30", run=520), passes=2, apply_presses=2)


def n2_unav_check(t):
    return n2_uncertain(Run(t, setup=lambda x: after_finish(lambda y, n: counter_unavailable(y), 5.0)(x)).edit(3, "start_time", "09:30", run=520))


def n2_zero_check(t):
    return n2_uncertain(Run(t, setup=lambda x: after_finish(lambda y, n: setattr(y.d, "attempts", y.d.attempts - 1), 1.0)(x)).edit(3, "start_time", "09:30", run=520))


def n2_reset_check(t):
    return n2_uncertain(Run(t, setup=counter_reset_setup).edit(3, "start_time", "09:30", run=520))


CHECKS = {
    **{f"happy_{s}": happy(s) for s in SETTINGS},
    "phrase": phrase_check,
    "floor": lambda t: all(rejects(rv(t, 3, "power", v)) for v in (499, 450, 100)) and accepts(rv(t, 3, "power", 500)),
    "order": lambda t: (all(rejects(rv(t, 3, "start_time", v)) for v in ("04:00", "05:00", "16:00", "17:00"))
                        and all(rejects(rv(t, s, "start_time", v, layout=OWNER_LAYOUT, t0=NOON)) for s, v in OWNER_ORDER_REFUSALS)),
    "grid5": lambda t: all(rejects(rv(t, 3, "start_time", v)) for v in ("09:32", "24:00", "23:60")),
    "cyc": lambda t: (rejects(rv(t, 3, "start_time", "09:30", layout=starts(0, 500, 400, 1600, 1900, 2300), t0=SEVEN_AM))
                      and rejects(rv(t, 3, "start_time", "09:30", layout=starts(30, 530, 1202, 1635, 2200, 25), t0=TWO_PM))),
    # acs1x refuses a two-wrap live layout too (two raw decreases): the inherited cycle rule is exercised with the hold turned off in memory
    "one_wrap": lambda t: rejects(rv(no_hold(t), 3, "start_time", "09:30", layout=starts(0, 500, 400, 1600, 1900, 2300), t0=SEVEN_AM)),
    "min_slot": lambda t: ("24-hour cycle" in rv(t, 2, "start_time", "05:35", layout=starts(30, 530, 530, 1635, 2200, 25), t0=NOON).res()
                           and rejects(rv(t, 3, "start_time", "05:35", layout=starts(30, 530, 530, 1635, 2200, 25), t0=NOON))),
    "want_record": lambda t: all(tampered_apply(t, w).res().startswith("REFUSED") and tampered_apply(t, w).loads() == [] for w in (2400, 1275)),
    "grid_live": lambda t: rejects(rv(t, 2, "start_time", "05:35", layout=starts(30, 530, 1202, 1635, 2200, 25), t0=NOON)),
    "wrap_edit": lambda t: all(accepts(rv(t, s, "start_time", v, layout=OWNER_LAYOUT, t0=NOON)) for s, v in ((1, "00:35"), (6, "00:20"), (5, "23:55"), (6, "00:00"))),
    # acs1x refuses every move across midnight first: the inherited active-slot guard is exercised with the hold turned off in memory
    "mid_wrap": lambda t: (accepts(rv(no_hold(t), 5, "start_time", "00:05", layout=OWNER_LAYOUT, t0=NOON))
                           and rejects(rv(no_hold(t), 5, "start_time", "00:05", layout=OWNER_LAYOUT, t0=S.parse_local("2026-10-26 23:00:00") - 70))),
    "xw_review": xw_review_check, "xw_apply": xw_apply_check, "xw_copies": xw_copies_check, "xw_first": xw_first_check,
    "xw_alone": hold_alone_refuses,
    "xw_last": lambda t: last_check_alone(t, *LAST_CASES[0][1:])[0],
    "frame_fit": lambda t: all(last_check_alone(t, *c_[1:])[0] for c_ in LAST_CASES[2:]),
    "whole": lambda t: writers_whole(t) is None,
    "fresh_exact": lambda t: all(fresh_read_alone(t, *c_[1:])[0] for c_ in FRESH_CASES),
    "gen": lambda t: all(rejects(rv(t, 3, "charge_source", v)) for v in ("Generator", "Grid + Generator", "grid")),
    "src_live": lambda t: rejects(rv(t, 3, "charge_source", "None", layout=slot_set(3, src="Generator"))),
    "near": lambda t: rejects(rv(t, 3, "start_time", "12:00", **{"t0": S.parse_local("2026-10-12 08:45:00") - 70})),
    "cc": lambda t: all(rejects(rv(t, 3, s, value_for(3, s), t0=S.parse_local("2026-10-25 01:30:00") - 70)) for s in ("power", "charge_source")),
    # a CLEAN refusal is the property: without the guard the chain evaluates the wrong branch and the template raises, which is not a refusal
    "unknown": lambda t: clean_refusal(lambda: rv(t, 3, "mode", "General")),
    "same_power": poke_check("target_soc", "power"),
    "same_soc": poke_check("power", "soc"), "same_start": poke_check("power", "start"), "same_src": poke_check("target_soc", "src"),
    "same_end": poke_check("power", "end"), "same_gc": poke_check("power", "gc"), "same_mode": poke_check("power", "mode"),
    "same_edited": poke_check("power", "power"),
    "verdict_edited": verdict_edited, "verdict_other": verdict_other, "clamp": clamp_check,
    "changed": changed_check,
    "lock": lambda t: (lambda x: x.locked() and len(x.applies()) == 1)(
        Run(t, setup=lambda y: y.d.fault.__setitem__("verify_fail", True)).edit(3, "power", 3000)),
    "arm_off": lambda t: not Run(t, setup=drop_apply).edit(3, "power", 3000).arm_on(),
    "reserve": lambda t: rejects(rv(t, 3, "target_soc", 19)),
    "fallback": lambda t: rejects(rv(t, 3, "power", 3000, setup=lambda y: y.w.set(FB_REVIEW, "st=SAVING;id=AB12"))),
    "failclosed": lambda t: rejects(rv(t, 3, "power", 3000, setup=lambda y: y.w.set(f"binary_sensor.{D}rtc_correction_in_progress", "unavailable"))),
    "fresh": external,
    "happy_charge_none": lambda t: (lambda x: x.changed() == {(1, "src"): ("Grid", "None")} and x.res().startswith("APPLIED") and not x.invalid()
                                    and not x.arm_on())(Run(t).edit(1, "charge_source", "None")),
    "notice": lambda t: ("Before any Manual Controls Apply of slot 2, press Load Current Slot 2 (or Load All): its staged end still holds the old 09:00."
                         in Run(t, setup=fp_on_finish).edit(3, "start_time", "09:30", run=480).note()
                         and "refreshed by the editor" in Run(t).edit(3, "start_time", "09:30").note()),
    "f1": f1_check, "f1_nonstart": f1_nonstart, "f2_pre": f2_pre, "f2_unc": f2_unc, "f2_counter": f2_counter,
    "f3_review": f3_review, "f3_fresh": f3_fresh, "f3_last": f3_last, "f3_start": lambda t: (lambda x: x.res().startswith("REFUSED") and "multiple of 100" in x.res()
                                                                                              and x.d.presses == [])(live_power_fraction_after_review(t)),
    "f4": f4_check,
    "f2_late": lambda t: unproven_ok(Run(t, setup=both(RTC_LATE(), after_load(bump_counter_late, 5.0))).edit(3, "power", 3000, run=520)),
    "n2_ok": n2_ok_check, "n2_other": n2_other_check, "n2_double": n2_double_check, "n2_unav": n2_unav_check, "n2_zero": n2_zero_check,
    "n2_reset": n2_reset_check,
    "f2_ext": f2_ext, "f2_cnt": f2_cnt, "f2_unav": f2_unav, "f2_wip": f2_wip, "f2_cap": f2_cap,
    "inv_clock": lambda t: (rejects(rv(t, 3, "start_time", "09:30", setup=lambda x: x.w.set(M.CLOCK, S.local_str(x.w.t + 400))))
                            and rejects(rv(t, 3, "start_time", "09:30", setup=lambda x: x.w.set(M.CLOCK, "unavailable")))),
    "mid": lambda t: (rejects(rv(t, 3, "start_time", "11:00", t0=S.parse_local("2026-10-12 10:00:00") - 70))
                      and rejects(rv(t, 3, "start_time", "06:00", t0=S.parse_local("2026-10-12 07:00:00") - 70))
                      and rejects(rv(t, 1, "start_time", "04:30", t0=S.parse_local("2026-10-12 02:00:00") - 70))),
    "fmt": lambda t: rejects(rv(t, 3, "start_time", "09:30", setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone2_time", "?2475"))),
    "flags_unavail": lambda t: (lambda x: x.d.presses == [] and x.res().startswith("FAILED"))(Run(t, setup=flags_unavailable).edit(3, "power", 3000)),
    "words": lambda t: all((lambda x: x.applies() == [] and x.changed() == {})(Run(t, setup=src_mode_unavailable(w)).edit(3, "power", 3000))
                           for w in ("src", "mode")),
}


def battery(text: str, keys=None) -> dict:
    res = {}
    for k, fn in CHECKS.items():
        if keys is not None and k not in keys:
            continue
        try:
            res[k] = bool(fn(text))
        except Exception as exc:  # noqa: BLE001
            res["crash"] = f"{k}: {type(exc).__name__}: {exc}"
    return res


base = battery(S1)
check(f"the mutation battery ({len(CHECKS)} checks) holds on the installed package", all(v is True for v in base.values()),
      str({k: v for k, v in base.items() if v is not True}))
PW_LIVE = "else (states(e.live_pw) | float(-2)))"
MUTANTS = [
    ("the staged power of a non-edited field is not compared with the live power", [(PW_LIVE, "else (states(e.pw) | float(-2)))")], "same_power"),
    ("the staged SOC of a non-edited field is not compared with the live SOC", [("else (states(e.live_soc) | float(-2)))", "else (states(e.soc) | float(-2)))")],
     "same_soc"),
    ("the staged start of a non-edited field is not compared with the live start",
     [("else ((states(e.live_t) | replace(':', '')) | int(-2)))", "else (states(e.st) | float(-2)))")], "same_start"),
    ("the staged charge source of a non-edited field is not compared with the live source", [("else states(e.live_src))", "else states(e.src))")],
     "same_src"),
    ("the staged END is not compared with the live end (staging check, last check and fixed point)",
     [("and (states(e.en) | float(-1)) == ((states(e.live_t_next) | replace(':', '')) | int(-2))", "and true")], "same_end"),
    ("the staged mode is not compared with the live mode", [("and states(e.mode) == states(e.live_mode)", "and true")], "same_mode"),
    ("the grid-charge staging switch is not compared with the live bit", [(
        "and states('switch.ecco_clock_dongle_manual_stage_grid_charge_enabled') == states('binary_sensor.ecco_clock_dongle_ecco_battery_grid_charge_enabled')",
        "and true")], "same_gc"),
    ("the edited field is not required to be at the request at the last check", [("== ((want | float(-2)) if setting == 'power' else", "== ((states(e.pw) | float(-2)) if setting == 'power' else")],
     "same_edited"),
    ("the new start time is not checked against its neighbours nor the proposed layout against the cycle rule (acs1c: both branches dropped)",
     [("{% elif setting == 'start_time' and not (uw > 0 and uw < arc) %}", "{% elif false %}"), ("{% elif setting == 'start_time' and not cyc2 %}", "{% elif false %}")],
     "order"),
    ("the live start layout is not required to be one 24-hour cycle (acs1c)", [("{% elif setting == 'start_time' and not cyc %}", "{% elif false %}")], "cyc"),
    ("acs1c: a live layout whose slots go round the clock twice passes (the gaps need only sum to a multiple of a day)",
     [("{% set cyc = g.ok and g.s == 1440 %}", "{% set cyc = g.ok and g.s % 1440 == 0 %}")], "one_wrap"),
    ("acs1c: a zero-length slot is allowed in the live layout", [("tt[k] % 5 == 0 and d >= 5 %}", "tt[k] % 5 == 0 and d >= 0 %}")], "min_slot"),
    ("acs1c: the live starts need not be on the 5-minute grid", [("g.ok and tt[k] >= 0 and tt[k] % 5 == 0 and d >= 5", "g.ok and tt[k] >= 0 and d >= 5")], "grid_live"),
    ("acs1c: slot 1's previous slot is not slot 6 (the linear sentinel again)", [("{% set pv = tt[(n + 4) % 6] if e else -1 %}", "{% set pv = (tt[n - 2] if n > 1 else -1) if e else -1 %}")],
     "wrap_edit"),
    ("acs1c: slot 6's next slot is not slot 1 (the linear sentinel again)", [("{% set nx = tt[n % 6] if e else -1 %}", "{% set nx = (tt[n] if n < 6 else -1) if e else -1 %}")],
     "wrap_edit"),
    ("acs1c: the Apply's gate re-checks only `want < 0` again (the Stage 1 form: a hand-edited record value such as 2400 reaches the cyclic window)",
     [("{% elif setting == 'start_time' and (want < 0 or want >= 2400 or want % 100 >= 60 or want % 5 != 0) %}", "{% elif setting == 'start_time' and want < 0 %}")],
     "want_record"),
    ("acs1c: the active-slot-now guard is evaluated on a line of HH:MM minutes again (the Stage 1 form, wrong across midnight)",
     [("{% set mid = setting == 'start_time' and ub >= 0 and uw >= 0 and uc >= 0 and ([ub, uw] | min) <= uc and uc < ([ub, uw] | max) %}",
       "{% set mid = setting == 'start_time' and bo >= 0 and wmin >= 0 and (((cm - (bo if wmin > bo else wmin)) % 1440) < ((wmin - bo) | abs)) %}")], "mid_wrap"),
    ("the Generator is allowed", [("(want | string) not in ['Grid', 'None']", "(want | string) not in ['Grid', 'None', 'Generator', 'Grid + Generator']")],
     "gen"),
    ("a live Generator source is allowed", [("cur not in ['None', 'Grid']", "cur not in ['None', 'Grid', 'Generator', 'Grid + Generator']")], "src_live"),
    ("the 500 W floor is dropped", [("want < 500 or", "want < 0 or")], "floor"),
    ("the 15-minute boundary guard is dropped", [("{% elif near %}", "{% elif false %}")], "near"),
    ("the clock-change-night guard is dropped", [("{% elif cc %}", "{% elif false %}")], "cc"),
    ("the clock-change-night guard fires only 00:00-01:00", [("now().hour < 3 %}", "now().hour < 1 %}")], "cc"),
    ("the wrong verdict field: the power verdict compares the pre-edit power", [("((want | float(-1)) if setting == 'power' else pre.pw)", "pre.pw")],
     "happy_power"),
    ("the verdict ignores the edited SOC / start / power / source", [
        ("{% if (states(e.live_soc) | int(-1)) != (want if setting == 'target_soc' else pre.soc) %}", "{% if false %}"),
        ("{% if states(e.live_t) != (wdisp if setting == 'start_time' else pre.t) %}", "{% if false %}"),
        ("{% if (states(e.live_pw) | float(-1)) != ((want | float(-1)) if setting == 'power' else pre.pw) %}", "{% if false %}"),
        ("{% if states(e.live_src) != ((want | string) if setting == 'charge_source' else pre.src) %}", "{% if false %}"),
        ("{% if (states(e.live_flags) | float(-1)) < 0 or (states(e.live_flags) | float(-1)) != flx %}", "{% if false %}")], "verdict_edited"),
    ("the verdict ignores the non-edited power", [("{% if (states(e.live_pw) | float(-1)) != ((want | float(-1)) if setting == 'power' else pre.pw) %}",
                                                  "{% if (states(e.live_pw) | float(-1)) != ((want | float(-1)) if setting == 'power' else (states(e.live_pw) | float(-1))) %}")],
     "verdict_other"),
    ("the expected flags drop the source bit", [("(1 if (want | string) == 'Grid' else 0)", "0")], "happy_charge_source"),
    ("the end is staged instead of the start", [('entity_id: "{{ e.st }}"', 'entity_id: "{{ e.en }}"')], "happy_start_time"),
    ("the power is staged into the SOC number", [('entity_id: "{{ e.pw }}"', 'entity_id: "{{ e.soc }}"')], "happy_power"),
    ("the confirmation phrase is not tied to the setting", [("(confirmation | string) != ('SET SLOT ' ~ n ~ ' ' ~ phr ~ ' REVIEW ' ~ code)",
                                                              "(confirmation | string)[-4:] != (code | string)")], "phrase"),
    ("the edited setting's live value is not re-checked against the review (Apply start and fresh read)", [
        ("{% elif (((states(e.live_soc) | int(-1) if setting", "{% elif false and (((states(e.live_soc) | int(-1) if setting"),
        ("or (pre.cur | string) != (before | string) }}", "}}")], "changed"),
    ("the final disarm is removed", ["      # The write enable always ends off (it only permits an Apply) - and must be SEEN off.\n      - action: switch.turn_off\n",
                                     "      # The write enable always ends off (it only permits an Apply) - and must be SEEN off.\n      - action: switch.turn_on\n"],
     "arm_off"),
    ("an uncertain outcome that does not lock", [("- action: input_boolean.turn_on\n", "- action: input_boolean.turn_off\n")], "lock"),
    ("the reserve ignored", [("{% set lo = [shutdown, reserve] | max %}", "{% set lo = shutdown %}")], "reserve"),
    ("the fallback Review / Save not checked", [("{% elif R.count(';st=') != 1 or ';st=IDLE;' not in R %}", "{% elif false %}")], "fallback"),
    ("a refusal that lets 'unavailable' through (RTC)", [("not is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'off')",
                                                          "is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on')")], "failclosed"),
    ("no fresh read before the Load", [('timeout: "00:01:30"', 'timeout: "00:00:00.1"'), ("{{ not fresh or refusal2", "{{ refusal2")], "fresh"),
    ("an unknown setting is not refused", [("{% elif setting not in ['target_soc', 'power', 'start_time', 'charge_source'] %}", "{% elif false %}")],
     "unknown"),
    # --- the review fixes
    ("B1: the charge source None is staged with select.select_option and a static \"None\" option (Home Assistant rejects the data)", b1_bad,
     "happy_charge_none"),
    ("M1: the start-time notice no longer tells the owner to Load slot N-1 first", [("Before any Manual Controls Apply of slot {{",
                                                                                       "Afterwards, a Manual Controls Apply of slot {{")], "notice"),
    ("the inverter-clock guard (more than 120 s from Home Assistant's clock, or unreadable) is dropped",
     [("{% elif setting == 'start_time' and invd > 120 %}", "{% elif false %}")], "inv_clock"),
    ("the 'between the old and the new boundary' (active slot right now) guard is dropped", [("{% elif mid %}", "{% elif false %}")], "mid"),
    ("the live start-time format is not validated (the naive parse that reads \"?2475\" as 15 minutes)", [(
        "{% set tm.v = tm.v + [((s[:2] | int(99)) * 60 + (s[3:] | int(99))) if ok else -1] %}",
        "{% set tm.v = tm.v + [(s[:2] | int(-1)) * 60 + (s[3:5] | int(-1))] %}")], "fmt"),
    ("unreadable raw flags no longer stop the edit before the Load", [("or pre.fl < 0 or", "or")], "flags_unavail"),
    ("the live / staged source and mode need not be option words (unavailable == unavailable passes)", [
        (" and states(e.src) in " + X.SRC_WORDS, ""), (" and states(e.live_src) in " + X.SRC_WORDS, ""),
        (" and states(e.mode) in " + X.MODE_WORDS, ""), (" and states(e.live_mode) in " + X.MODE_WORDS, "")], "words"),
]
def _drop_f1_load(t):
    i = t.index('entity_id: "{{ e.p_load }}"')
    j = t.rindex("- action: button.press", 0, i)
    return t[:t.rindex("\n", 0, j) + 1] + t[t.index("\n", i) + 1:]


def _f1_wrong_slot(t):
    return t.replace('entity_id: "{{ e.p_load }}"', 'entity_id: "button.ecco_clock_dongle_load_current_slot_{{ 1 if n == 6 else n + 1 }}_to_manual_staging"')


def _f1_every_setting(t):
    i = t.index('pn: "{{ 6 if n == 1 else n - 1 }}"')
    old = "value_template: \"{{ setting == 'start_time' }}\""
    j = t.index(old, i)
    return t[:j] + "value_template: \"{{ true }}\"" + t[j + len(old):]


def _f2_on_uncertain(t):
    a = ("{{ is_state('input_boolean.ecco_cfg_edit_review_required', 'off')\n               and (states('input_text.ecco_cfg_edit_last_result')"
         ".startswith('FAILED - a safety check")
    b = ".startswith('FAILED - the firmware refused the Apply')) }}"
    assert t.count(a) == 1 and t.count(b) == 1
    t = t.replace(a, "{{ (states('input_text.ecco_cfg_edit_last_result').startswith('FAILED - a safety check")
    return t.replace(b, ".startswith('FAILED - the firmware refused the Apply') or states('input_text.ecco_cfg_edit_last_result').startswith('UNCERTAIN')) }}")


def _f2_no_load(t):
    ind = " " * 14
    blk = (ind + "- action: button.press\n" + ind + "  continue_on_error: true\n" + ind + "  target:\n" + ind + "    entity_id: \"{{ e.load }}\"\n")
    i = t.rindex(blk)
    return t[:i] + t[i + len(blk):]


def _f3_gone(*inds):
    def f(t):
        for ind in inds:
            assert t.count(X._ind(X.F3_AFTER, ind)) == {12: 2, 16: 1, 24: 1}[ind]
            t = t.replace(X._ind(X.F3_AFTER, ind), X._ind(X.F3_BEFORE, ind))
        return t
    return f


MUTANTS += [
    ("F1: the Load of slot N-1 is removed", _drop_f1_load, "f1"),
    ("F1: the Load is pressed for the WRONG slot (N+1)", _f1_wrong_slot, "f1"),
    ("F1: the Load of slot N-1 is also pressed after a SOC, power or charge-source edit", _f1_every_setting, "f1_nonstart"),
    ("F2: slot N is also re-Loaded after an UNCERTAIN outcome (and the lock is not consulted)", _f2_on_uncertain, "f2_unc"),
    ("F2: the re-Load of slot N is removed", _f2_no_load, "f2_pre"),
    ("F2(b): the firmware-refused verdict no longer needs the unchanged gate-pass counter", [(
        "{{ fw_result.startswith('REJECTED') and later_read and not attempts_moved and unchanged }}",
        "{{ fw_result.startswith('REJECTED') and later_read and unchanged }}")], "f2_counter"),
    ("F3: the live-power multiple-of-100 rule is removed everywhere", _f3_gone(12, 16, 24), "f3_review"),
    ("F3: the rule is removed from the fresh-read gate only", _f3_gone(16), "f3_fresh"),
    ("F3: the rule is removed from the last check only", _f3_gone(24), "f3_last"),
    ("F4: the Dump to Grid warning is removed", [(DUMP_W, "")], "f4"),
]
def _f2_no_publish_wait(t):
    i = t.index("w_att:")
    j = t.rindex("seconds: 35", 0, i)
    return t[:j] + "seconds: 0" + t[j + len("seconds: 35"):]


_ATT_VAR = "                  - variables:\n                      att0: \"{{ states('" + X._ATT + "') | float(-1) }}\"\n"


def _f2_capture_after_staging(t):
    assert t.count(_ATT_VAR) == 1
    t = t.replace(_ATT_VAR, "")
    anchor = "                  # 3b. acs0r1:"
    assert t.count(anchor) == 1
    return t.replace(anchor, _ATT_VAR + anchor)


def _f3_start_gone(t):
    a, b = X._ind(X.F3_AFTER, 12), X._ind(X.F3_BEFORE, 12)
    i = t.index(a, t.index(a) + 1)                     # the Apply-start gate is the SECOND 12-space copy (the Review has the first)
    return t[:i] + b + t[i + len(a):]


MUTANTS += [
    ("F2 correction: the gate-pass counter comparison is dropped from the pre-press proof", [("att0 >= 0 and w_att >= 0 and w_att == att0 and not w_seen", "att0 >= 0 and w_att >= 0 and not w_seen")], "f2_cnt"),
    ("F2 correction: the write-in-progress tracking (the marker and the flag) is dropped", [(
        "{{ not is_state('input_boolean.ecco_cfg_edit_write_seen', 'off') or not is_state('binary_sensor.ecco_clock_dongle_manual_write_in_progress', 'off')\n",
        "{{ false\n")], "f2_wip"),
    ("F2 correction: the counter is captured AFTER the staging instead of before", _f2_capture_after_staging, "f2_cap"),
    ("F2 correction: an unavailable counter is treated as unchanged", [("att0 >= 0 and w_att >= 0 and w_att == att0 and not w_seen", "w_att == att0 and not w_seen")], "f2_unav"),
    ("F2 correction: the pre-press branch claims 'nothing written' without any proof (the old behaviour)", [(
        "{{ att0 >= 0 and w_att >= 0 and w_att == att0 and not w_seen }}", "{{ true }}")], "f2_ext"),
    ("F2 correction: the 35 s wait for the counter to publish is removed from the pre-press verdict", _f2_no_publish_wait, "f2_late"),
    ("F4: the SmartDeye / inverter-panel advice is removed", [(SMART_W, "")], "f4"),
    ("F3: the rule is removed from the Apply-start gate copy only", _f3_start_gone, "f3_start"),
]
def _n2_after_f1(t):
    """The counter check is moved to AFTER F1's Load of slot N-1: the verdict no longer needs it, a late block locks once the Load has been pressed."""
    t = t.replace("and diff | length == 0 and n2_ok }}", "and diff | length == 0 }}")
    ind = " " * 34
    late = (ind + "- if:\n" + ind + "    - condition: template\n" + ind + "      value_template: \"{{ not n2_ok }}\"\n" + ind + "  then:\n"
            + ind + "    - action: input_text.set_value\n" + ind + "      target:\n" + ind + "        entity_id: input_text.ecco_cfg_edit_last_result\n"
            + ind + "      data:\n" + ind + "        value: \"UNCERTAIN - late counter check\"\n"
            + ind + "    - action: input_boolean.turn_on\n" + ind + "      target:\n" + ind + "        entity_id: input_boolean.ecco_cfg_edit_review_required\n")
    assert t.count(X.F1_ANCHOR) == 1
    return t.replace(X.F1_ANCHOR, late + X.F1_ANCHOR)


def _n2_read_before_wait(t):
    """The counter is read right after the press (before the 35 s publish wait) instead of at the verdict."""
    line = "                          att_now: \"{{ states('" + X._ATT + "') | float(-1) }}\"\n"
    assert t.count(line) == 1
    t = t.replace(line, "")
    anchor = "                          fw_result: \"{{ states('" + X._FWRES + "')[:120] }}\"\n"
    assert t.count(anchor) == 1
    return t.replace(anchor, anchor + line)


MUTANTS += [
    ("acs1x: the crossing hold's refusal is dropped from all four copies of the gate", [("{% elif setting == 'start_time' and not xw %}", "{% elif false %}")],
     "xw_review"),
    ("acs1x: the hold is dropped from the Review's copy only", _drop_xw_copy(0), "xw_review"),
    ("acs1x: the hold is dropped from the Apply's gate only", _drop_xw_copy(1), "xw_apply"),
    ("acs1x: the hold is dropped from the Apply's fresh-read re-check only", _drop_xw_copy(2), "xw_copies"),
    ("acs1x: the hold is dropped from the last check before the press only", _drop_xw_copy(3), "xw_copies"),
    ("acs1x: the live and the proposed crossing are not compared (any layout with one crossing passes)",
     [("and xc.c == 1 and xc.c2 == 1 and xc.i == xc.i2 %}", "and xc.c == 1 and xc.c2 == 1 %}")], "xw_review"),
    ("acs1x: the proposed layout is built without the new start (the hold compares the live layout with itself)",
     [("{% set a = wmin if k == n - 1 else tt[k] %}{% set b = wmin if (k + 1) % 6 == n - 1 else tt[(k + 1) % 6] %}{% set xc.ok",
       "{% set a = tt[k] %}{% set b = tt[(k + 1) % 6] %}{% set xc.ok")], "xw_review"),
    ("acs1x: the hold sits after the 15-minute and active-slot guards instead of right after the proposed-layout rule", _xw_after_mid, "xw_first"),
    ("acs1x: the hold is dropped from the last check only (end to end: the race of [11x] is pressed)", _drop_xw_copy(3), "xw_last"),
    *[(f"acs1x: the conjunct {label.split(' (')[0]} is dropped from the hold", [cut], "xw_alone") for label, cut, _kw, _n, _v in HOLD_CONJUNCTS],
    *[(f"acs1x: the last check's {name} refusal is restored to its long form (it no longer fits the result helper there)", _restore_last(new_, old_),
       "frame_fit") for name, (old_, new_) in zip(("cycle", "neighbour", "power", "fallback live match"), XW.REWRITES) if name != "power"],
    # FB-1: a refusal shortened in a frame the last check's cases do not reach (each survived the suite of d2a20c7d)
    ("acs1x: the fresh read's FAILED result slices its refusal (refusal2[:120])",
     [(SLICE_FRESH, SLICE_FRESH.replace("(refusal2 if refusal2", "(refusal2[:120] if refusal2"))], "whole"),
    ("acs1x: the fresh read's FAILED result slices its refusal (refusal2[:120]), end to end",
     [(SLICE_FRESH, SLICE_FRESH.replace("(refusal2 if refusal2", "(refusal2[:120] if refusal2"))], "fresh_exact"),
    ("acs1x: the Review's REFUSED result slices its refusal (refusal[:100])", [(SLICE_REVIEW, SLICE_REVIEW.replace("{{ refusal }}", "{{ refusal[:100] }}"))],
     "whole"),
    ("acs1x: the Apply's gate's REFUSED result slices its refusal ((review_problem if review_problem else refusal)[:120])",
     [(SLICE_GATE, SLICE_GATE.replace("{{ review_problem if review_problem else refusal }}",
                                      "{{ (review_problem if review_problem else refusal)[:120] }}"))], "whole"),
]
MUTANTS += [
    ("N2: the gate-pass counter check is removed from the success verdict", [("and diff | length == 0 and n2_ok }}", "and diff | length == 0 }}")], "n2_other"),
    ("N2: the delta may be 1 or more (>= 1 instead of == 1)", [("(att_now - att0) == 1 }}", "(att_now - att0) >= 1 }}")], "n2_double"),
    ("N2: the delta may be 1 or less (<= 1 instead of == 1)", [("(att_now - att0) == 1 }}", "(att_now - att0) <= 1 }}")], "n2_zero"),
    ("N2: an unavailable counter is treated as delta 1", [("n2_ok: \"{{ att0 >= 0 and att_now >= 0 and (att_now - att0) == 1 }}\"", "n2_ok: \"{{ att_now < 0 or (att0 >= 0 and (att_now - att0) == 1) }}\"")], "n2_unav"),
    ("N2: the check is placed after F1's Load of slot N-1", _n2_after_f1, "n2_other"),
    ("N2: the counter is read before the 35 s publish wait", _n2_read_before_wait, "n2_ok"),
]
for name, pairs, key in MUTANTS:
    if callable(pairs):
        mutated = pairs(S1)
    else:
        if isinstance(pairs, list) and pairs and isinstance(pairs[0], str):
            pairs = [(pairs[0], pairs[1])]
        missing = [a[:60] for a, _ in pairs if S1.count(a) < 1]
        if missing:
            check(f"mutant '{name}': its anchors occur in the output", False, str(missing))
            continue
        mutated = S1
        for a, b in pairs:
            mutated = mutated.replace(a, b)
    keys = {key} | {k for k in CHECKS if k.startswith("happy_")} if key.startswith("happy_") else {key}
    res = battery(mutated, keys)
    # a kill is a behavioural check that FAILS on the mutant; a crash of the harness is not a kill
    check(f"mutant '{name}' is KILLED by the failing check '{key}'", res.get(key) is False and "crash" not in res, str(res))

# ======================================================================================================================
print("\n[13] the post-export declarations (PEX entries acs1, acs1c and acs1x)")
# ======================================================================================================================
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite pins acs1's declaration)
import _acs0_scope as F0  # noqa: E402
import _acs1_scope as F1  # noqa: E402
import _acs1c_scope as F1C  # noqa: E402
import _acs1x_scope as F1X  # noqa: E402

ACS1_FINGERPRINT = "e0bb9298dbcdb84041abd25633d3305d2338cba92a88fcefe826e6ad587bc318"
ACU1_FINGERPRINT = "352c542819485963e3b30be6dbefca189c04b8b6fdc9491fa6edc901548405b7"
ACS1C_FINGERPRINT = "9b4e5b349ef18de9c9ddf36bd61e98d85ac8da5443ce3240377cd370797aaffc"
ACS1X_FINGERPRINT = "775ddcd098a21f4971c594abf383af696fe40785654197b5916bd62c1ce2014f"
HD1_FINGERPRINT = "0986be0342fad759b6b500b2759233491ca3c52901120f00dfda17709029838e"
PKG_REL = X.ACS0_REL
E1 = sc.CHAIN.entry("acs1")
ids1 = [x.id for x in sc.POST_EXPORT_ENTRIES]
check("acs1 is the twenty-first post-export entry, appended right after hd1", ids1.index("acs1") == 20 and sc.CHAIN.prev_id("acs1") == "hd1",
      str(ids1[-3:]))
check("acs1 declares NO reverter and NO checkpoint (chain-pinned or frozen), no reserved-token holder, no delta, op path, include, substitution, "
      "firmware banned token or tag: the package is an added file of acs0, neither chain-pinned nor frozen, so the chain could not even hold a "
      "reverter for it; its record is the invertible transform proved in [0]",
      not E1.reverts and not E1.checkpoints and not E1.frozen_reverts and not E1.frozen_checkpoints and not E1.banned_files
      and not E1.deltas and not E1.op_paths_changed and not E1.includes_added and not E1.subst_added and not E1.subst_changed
      and not E1.subst_removed and not E1.banned_fw_added and not E1.fbh_includers and not E1.tags_declared and not E1.tags_promoted
      and PKG_REL not in sc.PINNED and PKG_REL not in _pex.FROZEN and PKG_REL in F0.ADDED_FILES and PKG_REL == F1.PACKAGE_REL)
check("the reserved-token holders are exactly those declared before acs1 (acs1 adds none and amends no allowlist; acs0's three files are among "
      "them and the package is one of those), and the package still names exactly the six ids acs0's amendment authorises (read from the "
      "installed text, spelled nowhere in this suite)",
      sc.CHAIN.declared_banned_files() == frozenset().union(*(e.banned_files for e in sc.CHAIN.upto("hd1"))) >= F0.BANNED_FILES
      and PKG_REL in F0.BANNED_FILES
      and sorted(set(re.findall(r"[a-z_]+\.[a-z0-9_]*(?:" + RES_TOKENS[0] + "|" + RES_TOKENS[4] + r")[a-z0-9_]*", S1))) == sorted(F0.RESERVED_IDS)
      and sorted(set(re.findall(r"[a-z_]+\.[a-z0-9_]*(?:" + RES_TOKENS[0] + "|" + RES_TOKENS[4] + r")[a-z0-9_]*", PKG0))) == sorted(F0.RESERVED_IDS))
check("acs1 declares the files it adds, each exists, none is deny-listed historical data, and its scope module spells no reserved token",
      E1.added_files == F1.ADDED_FILES and all((ROOT / f).is_file() for f in E1.added_files) and not (E1.added_files & _pex.DENY)
      and "registry/tests/_acs1_scope.py" in E1.added_files and not any(t in Path(F1.__file__).read_text(encoding="utf-8") for t in RES_TOKENS)
      and {Path(__file__).resolve().relative_to(ROOT).as_posix(), "home-assistant/prototypes/acs-stage1/acs_stage1_transform.py"} <= E1.added_files)
check("acs1's fingerprint is the pinned value, the sha256 of its record, linked to hd1's", E1.fingerprint == ACS1_FINGERPRINT == _pex.fingerprint(E1)   # PEX: its own fingerprint
      and _pex.record(E1)["parent"] == HD1_FINGERPRINT == sc.CHAIN.entry("hd1").fingerprint)   # PEX: hash link
man_txt = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
check("the deployment manifest is unchanged by acs1 (no chain-pinned edit: its checkpoint is hd1's, and acs0's stanza names the same package path as "
      "source and destination)", _pex.checkpoint(sc.HA_MANIFEST, "acs1") == _pex.checkpoint(sc.HA_MANIFEST, "hd1")   # PEX: no manifest edit
      and man_txt.count("ecco_tou_target_soc_edit.yaml") == 2 and man_txt.count(PKG_REL) == 1 and f"source: {PKG_REL}\n    destination: /config/packages/ecco_tou_target_soc_edit.yaml\n" in man_txt)
check("the scope module's pins are the suite's and the transform's: the Stage 0 package and the Stage 1 package hashes, the two renamed script ids "
      "and the four settings", F1.ACS0_PACKAGE_SHA256 == ACS0_SHA == X.ACS0_BASE_SHA256 and F1.STAGE1_PACKAGE_SHA256 == S1_SHA and F1.PAIRS_SHA256 == PAIRS_SHA
      and F1.SCRIPT_RENAMES == tuple((o, n) for o, n, _c in X.RENAMES) == ((REVIEW0, REVIEW), (APPLY0, APPLY)) and F1.SETTINGS == X.SETTINGS)
# acs1c: the cyclic correction, appended after acu1 (its parent since the rebase onto main 07b37c14; acs1 before that): declares only the files it adds and its fingerprint; acs1's record is unchanged
E2 = sc.CHAIN.entry("acs1c")
check("acs1c is the twenty-third post-export entry, appended right after acu1 (its parent since the rebase onto main 07b37c14; acs1 before that) "
      "and followed by acs1x", ids1.index("acs1c") == 22 and sc.CHAIN.prev_id("acs1c") == "acu1" and sc.CHAIN.prev_id("acu1") == "acs1"
      and ids1[23] == "acs1x", str(ids1[-3:]))
check("acs1c declares NO reverter and NO checkpoint (chain-pinned or frozen), no reserved-token holder, no delta, op path, include, substitution, "
      "firmware banned token or tag: like acs1, its exact record is the invertible acs1c transform proved in [0c]; acs1's own declaration and files "
      "(scope module, transform, pins) are unchanged",
      not E2.reverts and not E2.checkpoints and not E2.frozen_reverts and not E2.frozen_checkpoints and not E2.banned_files
      and not E2.deltas and not E2.op_paths_changed and not E2.includes_added and not E2.subst_added and not E2.subst_changed
      and not E2.subst_removed and not E2.banned_fw_added and not E2.fbh_includers and not E2.tags_declared and not E2.tags_promoted
      and E1.added_files == F1.ADDED_FILES and E1.fingerprint == ACS1_FINGERPRINT and F1C.PACKAGE_REL == PKG_REL == C.PACKAGE_REL)
check("acs1c declares the files it adds (the acs1c transform, its scope module and its design document), each exists, none is deny-listed, none is "
      "an acs1 file, and its scope module spells no reserved token",
      E2.added_files == F1C.ADDED_FILES and all((ROOT / f).is_file() for f in E2.added_files) and not (E2.added_files & _pex.DENY)
      and not (E2.added_files & E1.added_files) and "registry/tests/_acs1c_scope.py" in E2.added_files
      and "home-assistant/prototypes/acs-stage1/acs1c_transform.py" in E2.added_files and "docs/dev/acs1c-cyclic-tou.md" in E2.added_files
      and not any(t in Path(F1C.__file__).read_text(encoding="utf-8") for t in RES_TOKENS))
check("acs1c's fingerprint is the pinned value, the sha256 of its record, linked to acu1's (its parent; acu1's own link to acs1 is proven by "
      "the PEX suite and the card suite)", E2.fingerprint == ACS1C_FINGERPRINT == F1C.FINGERPRINT == _pex.fingerprint(E2)   # PEX: acs1c's own fingerprint
      and _pex.record(E2)["parent"] == ACU1_FINGERPRINT == sc.CHAIN.entry("acu1").fingerprint)   # PEX: hash link to acu1
check("the deployment manifest is unchanged by acs1c (its checkpoint is its parent acu1's: same package path as source and destination)",
      _pex.checkpoint(sc.HA_MANIFEST, "acs1c") == _pex.checkpoint(sc.HA_MANIFEST, "acu1"))   # PEX: no manifest edit by acs1c
check("the acs1c scope module's pins are the suite's and the transforms': the Stage 1 text (the base and the rollback file), the installed package and "
      "the 21 pairs; its base commit is public main at the acs1 merge",
      F1C.STAGE1_PACKAGE_SHA256 == S1_SHA == X.STAGE1_SHA256 == C.STAGE1_BASE_SHA256 and F1C.STAGE1C_PACKAGE_SHA256 == S1C_SHA == C.STAGE1C_SHA256
      and F1C.CYCLIC_PAIRS_SHA256 == CPAIRS_SHA == C.CYCLIC_PAIRS_SHA256 and F1C.BASE_COMMIT == "a7235433ce711e6a8fae5dab0fc8ca6c6f533de6"
      and F1C.CYCLIC_PAIR_COUNT == len(C.CYCLIC_PAIRS) == 21)
# acs1x: the midnight-crossing hold, appended after acs1c (public main e97ba36c): declares only the files it adds and its fingerprint; the acs1 and acs1c records are unchanged
E3 = sc.CHAIN.entry("acs1x")
# ovw3 (the 3D Energy Flow card on the Overview; it edits only the dashboard and VERSION.yaml) is appended after acs1x: acs1x is no longer the last
check("acs1x is the twenty-fourth post-export entry, appended right after acs1c, and followed by ovw3",
      ids1.index("acs1x") == 23 and sc.CHAIN.prev_id("acs1x") == "acs1c" and ids1[24] == "ovw3", str(ids1[-3:]))
check("acs1x declares NO reverter and NO checkpoint (chain-pinned or frozen), no reserved-token holder, no delta, op path, include, substitution, "
      "firmware banned token or tag: like acs1 and acs1c, its exact record is its invertible transform, proved in [0x]; the acs1 and acs1c "
      "declarations and files (scope modules, transforms, pins) are unchanged",
      not E3.reverts and not E3.checkpoints and not E3.frozen_reverts and not E3.frozen_checkpoints and not E3.banned_files
      and not E3.deltas and not E3.op_paths_changed and not E3.includes_added and not E3.subst_added and not E3.subst_changed
      and not E3.subst_removed and not E3.banned_fw_added and not E3.fbh_includers and not E3.tags_declared and not E3.tags_promoted
      and E2.added_files == F1C.ADDED_FILES and E2.fingerprint == ACS1C_FINGERPRINT and F1X.PACKAGE_REL == PKG_REL == XW.PACKAGE_REL)
check("acs1x declares the files it adds (the acs1x transform, its scope module and its design document), each exists, none is deny-listed, none is "
      "an acs1 or acs1c file, and its scope module spells no reserved token",
      E3.added_files == F1X.ADDED_FILES and all((ROOT / f).is_file() for f in E3.added_files) and not (E3.added_files & _pex.DENY)
      and not (E3.added_files & (E1.added_files | E2.added_files)) and "registry/tests/_acs1x_scope.py" in E3.added_files
      and "home-assistant/prototypes/acs-stage1/acs1x_transform.py" in E3.added_files and "docs/dev/acs1x-crossing-hold.md" in E3.added_files
      and not any(t in Path(F1X.__file__).read_text(encoding="utf-8") for t in RES_TOKENS))
check("acs1x's fingerprint is the pinned value, the sha256 of its record, linked to acs1c's (its parent)",
      E3.fingerprint == ACS1X_FINGERPRINT == F1X.FINGERPRINT == _pex.fingerprint(E3)   # PEX: acs1x's own fingerprint
      and _pex.record(E3)["parent"] == ACS1C_FINGERPRINT == sc.CHAIN.entry("acs1c").fingerprint)   # PEX: hash link to acs1c
check("the deployment manifest is unchanged by acs1x (its checkpoint is its parent acs1c's: same package path as source and destination)",
      _pex.checkpoint(sc.HA_MANIFEST, "acs1x") == _pex.checkpoint(sc.HA_MANIFEST, "acs1c"))   # PEX: no manifest edit by acs1x
check("the acs1x scope module's pins are the suite's and the transforms': the acs1c text (the base), the installed package and "
      "the 12 pairs; its base commit is public main at the acs1c merge",
      F1X.STAGE1C_PACKAGE_SHA256 == S1C_SHA == C.STAGE1C_SHA256 == XW.STAGE1C_BASE_SHA256 and F1X.STAGE1X_PACKAGE_SHA256 == S1X_SHA == XW.STAGE1X_SHA256
      and F1X.CROSSING_PAIRS_SHA256 == XPAIRS_SHA == XW.CROSSING_PAIRS_SHA256 and F1X.BASE_COMMIT == "e97ba36cdc19796d0d1b136b6da27c0212dd6bef"
      and F1X.CROSSING_PAIR_COUNT == len(XW.CROSSING_PAIRS) == 12)

print("")
dt = time.time() - T_START
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed in {dt:.0f}s")
    sys.exit(1)
print(f"All {PASSES} Advanced Configuration Stage 1 (with the acs1c cyclic correction and the acs1x crossing hold) checks passed in {dt:.0f}s.")
print("These prove the installed package's control flow against models of the firmware's manual TOU path and of Home Assistant offline; they prove "
      "nothing about a live Home Assistant, the dongle, the inverter, the Home Assistant time zone, or how a real interrupted write behaves.")
