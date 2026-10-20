"""Offline suite for Advanced Configuration Stage 1 (post-export entry acs1): a guarded owner edit of ONE setting of ONE TOU slot (target
SOC, power, start time or charge source), the INSTALLED package home-assistant/packages/ecco_tou_target_soc_edit.yaml.

That file is, byte for byte, render_stage1() of the Stage 0 package (home-assistant/prototypes/acs-stage1/acs_stage1_transform.py, which
now documents how the installed package was derived). Git history is not needed: unrender_stage1(<installed>) gives the Stage 0 text back
(sha256 pinned here and in the transform), so the reuse proof, the SOC parity checks and the rollback file all derive from the installed
file alone.

The INSTALLED package runs, together with the REAL Manual Controls helper package (ecco_manual_controls_helpers.yaml, whose sync
automations touch the same staging entities), under _ha_script_sim.py (a fail-loud HA script / automation interpreter) against a
subclass of _manual_tou_sim.py's model of the firmware's manual TOU path that adds what Stage 1 needs: the charge-source select, the
firmware's EXACT verify of start / end / power / SOC / flags (+ register 232 bit 0), the select.select_first service, the mode-canonical
gate and per-field clamp faults. In this process the sim also parses template results like Home Assistant does (static service data
included) and aborts a run on service data that Home Assistant's schema would reject (see ha_native / InvalidServiceData below).

  [0] provenance      the installed package IS render(Stage 0) and unrender(installed) IS the pinned Stage 0 text (sha256), both ways; every
                      pair applies exactly its declared count; the result is YAML; the gate lines that carry a reserved token are inherited
                      byte for byte; neither file spells a reserved token; deterministic; an altered anchor raises, both ways
  [1] static scope    which services and entities the generated package may touch; every firmware entity exists; Stage 0 untouched
  [2] happy path      every slot x every setting: Review -> typed phrase -> Apply; exactly the intended register changes; verified
  [3] SOC parity      the Stage 0 package (unrendered from the installed one) and the installed one (setting target_soc) on identical
                      worlds: same outcome class, same writes, same lock
  [4] validation      per setting (power floor, start grid / ordering / wrap / 15-minute guard / active-slot-now guard / inverter clock /
                      malformed live starts, charge source, SOC bounds), raw flags and source / mode words, the UK clock change nights
  [5] review          phrase per setting, code, expiry, single use, the edited value changed since the review
  [6] gate            every unsafe state and `unavailable` refuses at Review and at Apply, for each setting
  [7] staged == live  any other staged field changed between Load and press stops the edit; the helper mirror reaches its fixed point
  [8] fresh read      an inverter change to an unrelated field after the last poll is kept, for each setting
  [9] faults          firmware refusal, verify failure, partial writes, clamps, disagreeing / missing later read, dropped press, restart
  [10] races          Free Power starting, a second Review / Apply during an Apply, the shared in-flight markers
  [11] acs0r1 timing  the quiet-gap press and a bus-busy refusal behave as in Stage 0
  [12] mutation       in-memory mutants of the installed package, each KILLED by a failing behavioural check (a harness crash is no kill)
  [13] PEX            the acs1 declaration: position, hash link, added files, no frozen or chain-pinned edit, no new token holder

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
PKG_PATH = ROOT / X.ACS0_REL
S1 = PKG_PATH.read_text(encoding="utf-8")                  # the INSTALLED package (Stage 1)
PKG0 = X.unrender_stage1(S1)                               # the Stage 0 text it was derived from, reconstructed from the installed file alone
HELPERS_TEXT = (ROOT / "home-assistant/packages/ecco_manual_controls_helpers.yaml").read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
ACS0_SHA = "9fa32b9bb843cfc7b42bae9ed7c06a50f461e564d7f0609e2536c28968d6affe"   # the Stage 0 package that PAIRS apply to, LF line ends
S1_SHA = "8af4d4392c4f406aef16d9aa76f011da4be964be3085b3a595e4966346beae89"      # the installed Stage 1 package, LF line ends
PAIRS_SHA = "1a49696d5a3ba6dde154692b82852055c8f0d41e52897227b27078a18c30e5f1"   # the canonical serialisation of the 40 pairs

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
      "package), and changes it, and the result is the installed package", not bad and text == S1, str(bad))
raw_pkg = PKG_PATH.read_bytes()
check("PROVENANCE (forward): the installed package IS render_stage1(Stage 0) byte for byte and its sha256 is the pinned one; the file has "
      "consistent line ends (LF in the repository)", X.render_stage1(PKG0) == S1 and hashlib.sha256(S1.encode()).hexdigest() == S1_SHA
      and b"\r" not in raw_pkg.replace(b"\r\n", b""))
check("PROVENANCE (backward): unrender_stage1(installed) hashes to the pinned Stage 0 sha256 (suite pin == the transform's constant) and "
      "render_stage1(unrender_stage1(installed)) == installed, from the LF text and from a CRLF copy", hashlib.sha256(PKG0.encode()).hexdigest()
      == ACS0_SHA == X.ACS0_BASE_SHA256 and X.render_stage1(X.unrender_stage1(S1)) == S1
      and X.unrender_stage1(S1.replace("\n", "\r\n")) == PKG0 and X.render_stage1(X.unrender_stage1(S1.replace("\n", "\r\n"))) == S1)
check("the pins are asserted, not printed: the installed package's sha256 == the suite's == the transform's STAGE1_SHA256; the 40 pairs hash "
      "(canonical serialisation) to the pinned PAIRS_SHA256, so a silent edit of any pair is caught", hashlib.sha256(S1.encode()).hexdigest()
      == S1_SHA == X.STAGE1_SHA256 and len(X.PAIRS) == 40 and X.pairs_sha256() == PAIRS_SHA == X.PAIRS_SHA256)
check("the Stage 0 text is itself NOT a rendered package (unrender refuses it) and the installed package is NOT a Stage 0 text (render refuses it): "
      "the two directions cannot be confused", all(_raises(lambda f=f, t=t: f(t)) for f, t in ((X.unrender_stage1, PKG0), (X.render_stage1, S1))))
pkg = yaml.safe_load(S1)
check("the result parses as YAML with Stage 0's shape: 3 text helpers, 2 booleans, 3 scripts (review, apply, acknowledge), 1 automation",
      {k: len(v) for k, v in pkg.items()} == {"input_text": 3, "input_boolean": 2, "script": 3, "automation": 1}
      and sorted(pkg["script"]) == sorted([REVIEW, APPLY, ACK]) and pkg["automation"][0]["id"] == "ecco_cfg_edit_interrupted"
      and sorted(pkg["script"][REVIEW]["fields"]) == ["setting", "slot", "value"] and list(pkg["script"][APPLY]["fields"]) == ["confirmation"]
      and not any("initial" in (v or {}) for v in pkg["input_boolean"].values()))
pkg0 = yaml.safe_load(PKG0)
check("same helpers (same ids) as Stage 0 - a drop-in superset that replaced it; the watchdog automation (same id) watches the NEW apply script",
      pkg["input_text"] == pkg0["input_text"] and pkg["input_boolean"] == pkg0["input_boolean"]
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
check("no pair's `before` or `after` contains a line that carries a reserved token (so no pair can touch one)",
      not [i for i, (b, a, _c) in enumerate(X.PAIRS) if any(t in b or t in a for t in RES_TOKENS)])
own = {p.name: p.read_text(encoding="utf-8") for p in (Path(__file__).resolve(), TRANSFORM_PATH)}
check("neither new file contains any reserved token or fragment (ecco + fallback / failback, FALLBACK + PROFILE, FAILBACK + STATE, "
      "fallback + profile ids, fbc + raw)", all(not any(t in txt for t in RES_TOKENS) for txt in own.values()),
      str({k: [t for t in RES_TOKENS if t in v] for k, v in own.items()}))
check("deterministic: rendering twice, and from a CRLF copy of Stage 0, gives identical text (sha256 pinned above)",
      X.render_stage1(PKG0) == S1 == X.render_stage1(PKG0.replace("\n", "\r\n")) == X.render_stage1(X.unrender_stage1(S1)))
print(f"        installed Stage 1 sha256 {hashlib.sha256(S1.encode()).hexdigest()}  ({len(S1.splitlines())} lines, {len(X.PAIRS)} pairs)")
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
assert state == S1
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
un_fail = []
for i, (before, after, count) in enumerate(X.PAIRS):
    fewer = S1.replace(after, "", 1) if count == 1 else None
    more = S1 + "\n" + after
    for label, variant in (("one occurrence removed", fewer), ("one occurrence added", more)):
        if variant is None:
            continue
        try:
            X.unrender_stage1(variant)
            un_fail.append((i, label))
        except ValueError as exc:
            if "pair" not in str(exc):
                un_fail.append((i, label, str(exc)[:60]))
try:
    X.unrender_stage1(S1.replace("unknown setting (target_soc", "unknown setting  (target_soc", 1))
    un_fail.append(("after text altered",))
except ValueError as exc:
    if "pair" not in str(exc):
        un_fail.append(("altered message", str(exc)[:60]))
check("an installed text with ANY pair's `after` text removed, duplicated or altered is refused by unrender_stage1 with ValueError naming the "
      "pair (a rollback file can never be silently half-reconstructed)", not un_fail, str(un_fail[:5]))
check("SETTINGS is exactly the four settings", X.SETTINGS == ("target_soc", "power", "start_time", "charge_source"))
src_t = TRANSFORM_PATH.read_text(encoding="utf-8")
check("the transform performs no I/O at all and uses no network (no read_text / open / write_text / socket / urllib / subprocess)",
      not re.search(r"read_text|read_bytes|write_text|write_bytes|\bopen\(|socket|urllib|requests|subprocess|os\.system|import pathlib|from pathlib", src_t))

# ======================================================================================================================
print("\n[1] static scope of the generated package")
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
check("no static service-data value in the generated package would be parsed by Home Assistant into a non-string (the class of bug that "
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
check("button.press ONLY the slot's Load and Apply; switch.turn_on ONLY the Manual Configuration Write Enable",
      sorted(t for a, t in acts1 if a == "button.press") == ["{{ e.apply }}", "{{ e.load }}"]
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
check(f"every dongle entity the generated package names exists in the firmware ({len(used1)} ids), and any beyond Stage 0's is one of the "
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
check("the entities the generated package ACTS on beyond Stage 0's are exactly the 18 allowed ones (6 power numbers, 6 start_hhmm numbers, "
      "6 charge_source selects); everything else is read-only or already Stage 0's", len(new_touch) == 18
      and new_touch == {f"{d}.{D}{s}" for s, d in [(x, "number") for x in sorted(allowed_new) if not x.endswith("source")]
                        + [(x, "select") for x in sorted(allowed_new) if x.endswith("source")]}, str(sorted(new_touch)))
check("the per-slot map is exact for slots 1-6: own Load / Apply / staging / live TimezoneN, the next slot's start as the end, own helpers",
      all(mp1[n].get("load") == f"button.{D}load_current_slot_{n}_to_manual_staging"
          and mp1[n].get("apply") == f"button.{D}apply_manual_slot_{n}_settings"
          and mp1[n].get("pw") == f"number.{D}manual_slot_{n}_power" and mp1[n].get("st") == f"number.{D}manual_slot_{n}_start_hhmm"
          and mp1[n].get("src") == f"select.{D}manual_slot_{n}_charge_source" and mp1[n].get("soc") == f"number.{D}manual_slot_{n}_target_soc"
          and mp1[n].get("live_t") == f"sensor.{D}ecco_timezone{n}_time" and mp1[n].get("live_t_next") == f"sensor.{D}ecco_timezone{n % 6 + 1}_time"
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
              and len(r.loads()) == 1 and r.applies()[0][2] == "PASSED" and r.d.successes == 1
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
      and "charge source" not in n_.split("Unchanged and rewritten", 1)[1], n_)
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

# --- M1: a start-time edit leaves slot N-1's Manual Controls staging (its END is register 249+N) stale
bad = []
for n, prev, old_t in ((3, 2, "09:00"), (1, 6, "00:00"), (2, 1, "05:00"), (6, 5, "23:00")):
    r = Run().edit(n, "start_time", {1: "00:30", 2: "05:30", 3: "09:30", 6: "23:30"}[n])
    want = (f"Before any Manual Controls Apply of slot {prev}, press Load Current Slot {prev} (or Load All): its staged end still holds the old "
            f"{old_t}.")
    if want not in r.note() or len(r.loads()) != 1 or [c[1] for c in r.w.service_log if c[1] == "button.press"] != ["button.press"] * 2:
        bad.append((n, r.note()[-200:]))
for setting in ("target_soc", "power", "charge_source"):
    if "Before any Manual Controls Apply" in Run().edit(3, setting, value_for(3, setting)).note():
        bad.append((setting, "notice on a setting that does not move a boundary"))
check("the start-time success notice says plainly: Before any Manual Controls Apply of slot <N-1>, press Load Current Slot <N-1> (or Load All): its "
      "staged end still holds the old <HH:MM> - for slots 3, 1 (slot 6), 2 and 6; only the Load and Apply buttons are ever pressed (no extra "
      "Load); the other settings carry no such notice", not bad, str(bad))
r = Run()
r.d._load(2)                                         # the owner loaded slot 2 into Manual Controls earlier: staged end = 09:00
r.w.run_until(r.w.t + 1)
assert r.d.loaded[2] and r.d.staging[2]["end"] == 900
r.edit(3, "start_time", "09:30")
moved = r.d.regs["slots"][3]["start"] == 930 and r.d.loaded[2] and r.d.staging[2]["end"] == 900
r.d.busy = 0.0                                       # a quiet bus: the point is the stale staging, not the poll timing
r.w.call("switch.turn_on", [M.ARM], {})
r.w.run_until(r.w.t + 2)
r.w.call("button.press", [f"button.{D}apply_manual_slot_2_settings"], {})
r.w.run_until(r.w.t + 20)
check("RESIDUAL (documented, not fixed): after the edit moved slot 3's start to 09:30, a later Manual Controls Apply of slot 2 with its stale "
      "loaded staging silently writes the old end back - slot 3's start is 09:00 again and the firmware says VERIFIED OK; only the notice's "
      "Load-first instruction prevents it", moved and r.d.regs["slots"][3]["start"] == 900
      and r.w.state(M.RESULT).startswith("VERIFIED OK - manual Slot 2"), f"{r.d.regs['slots'][3]} {r.w.state(M.RESULT)}")

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
    return dict(cls=cls(r), writes=[(round(t - r.t0, 2), reg, val) for t, reg, val in r.d.writes],
                presses=[(round(p[0] - r.t0, 2), p[1], p[2][:48]) for p in r.d.presses], regs=regs_flat(r), locked=r.locked(),
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
    (1, "00:05", True), (1, "04:55", True), (1, "05:00", False), (1, "23:55", False), (1, "00:00", False), (1, "00:01", False),
    (6, "23:55", True), (6, "19:05", True), (6, "19:00", False), (6, "18:55", False), (6, "00:00", False), (6, "23:00", False),
    (2, "00:00", False), (2, "00:05", True), (2, "08:55", True), (2, "09:00", False),
    (5, "16:00", False), (5, "16:05", True), (5, "22:55", True), (5, "23:00", False),
]
for slot, v, ok in cases:
    r = Run().review(slot, "start_time", v)
    if (accepts(r) if ok else rejects(r)) is not True:
        bad.append((slot, v, ok, r.res()[:80]))
check(f"start time ({len(cases)} cases): off the 5-minute grid, 24:00, 23:60, seconds, malformed, equal to a neighbour, crossing a neighbour "
      "and no change refused; strictly between the neighbours accepted - slot 1 (slot 6's end) and slot 6 (slot 1's start) included",
      not bad, str(bad[:4]))
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
        if not (rejects(r) and ("strictly ascending" in r.res() or "unavailable" in r.res())):
            bad.append((label, slot, r.res()[:80]))
check("an already non-ascending (or unreadable) live layout refuses every start-time edit: 'unexpected TOU layout', nothing written",
      not bad, str(bad[:3]))
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
        if not (rejects(r) and ("strictly ascending" in r.res() or "unavailable" in r.res() or "no change" in r.res())):
            bad.append((label_n, mal, r.res()[:70]))
    r = Run(setup=lambda x, k=label_n: x.w.set(f"sensor.{D}ecco_timezone{k}_time", "?2475")).review(3, "power", 3000)
    if not accepts(r):
        bad.append((label_n, "power edit", r.res()[:60]))
check(f"a malformed live start (\"?2475\", a bare \"9:30\", 24:00, 09:60, padded, empty, unavailable, ...) in ANY of the six slots - own, previous or "
      f"next neighbour or a distant one - refuses a start-time edit (fail closed: 6 slots x {len(MALFORMED)} forms); a power edit is unaffected",
      not bad, str(bad[:4]))
r = Run(setup=lambda x: x.w.set(f"sensor.{D}ecco_timezone2_time", "?2475")).review(3, "start_time", "09:30")
check("...the case that a naive parse would let through: \"?2475\" as slot 2's start (read as 15 minutes, 'ascending') is refused", rejects(r)
      and "strictly ascending" in r.res(), r.res())

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
check("still exactly one Apply press and one Load in the package; no repeat (no retry path) in the Apply",
      S1.count('entity_id: "{{ e.apply }}"') == 1 and S1.count('entity_id: "{{ e.load }}"') == 1
      and "repeat:" not in S1.split(f"{APPLY}:", 1)[1].split(f"{ACK}:", 1)[0])

# ======================================================================================================================
print("\n[12] mutation: in-memory mutants of the generated output, each caught by the battery")
# ======================================================================================================================


def rv(text, slot, setting, value, **kw):
    return Run(text, **kw).review(slot, setting, value)


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


CHECKS = {
    **{f"happy_{s}": happy(s) for s in SETTINGS},
    "phrase": phrase_check,
    "floor": lambda t: all(rejects(rv(t, 3, "power", v)) for v in (499, 450, 100)) and accepts(rv(t, 3, "power", 500)),
    "order": lambda t: all(rejects(rv(t, 3, "start_time", v)) for v in ("04:00", "05:00", "16:00", "17:00")),
    "grid5": lambda t: all(rejects(rv(t, 3, "start_time", v)) for v in ("09:32", "24:00", "23:60")),
    "asc": lambda t: rejects(rv(t, 3, "start_time", "09:30", layout=starts(0, 500, 400, 1600, 1900, 2300))),
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
                         in Run(t).edit(3, "start_time", "09:30").note()),
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
check(f"the mutation battery ({len(CHECKS)} checks) holds on the generated package", all(v is True for v in base.values()),
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
    ("the new start time is not checked against its neighbours (strictly ascending)", [("{% elif setting == 'start_time' and not (lb < wmin and wmin < hb) %}",
                                                                                       "{% elif false %}")], "order"),
    ("the live start layout is not required to be ascending", [("{% elif setting == 'start_time' and not asc %}", "{% elif false %}")], "asc"),
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

print("")
dt = time.time() - T_START
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed in {dt:.0f}s")
    sys.exit(1)
print(f"All {PASSES} Advanced Configuration Stage 1 prototype checks passed in {dt:.0f}s.")
print("These prove the generated package's control flow against models of the firmware's manual TOU path and of Home Assistant offline; they prove "
      "nothing about a live Home Assistant, the dongle, the inverter, the Home Assistant time zone, or how a real interrupted write behaves.")
