"""Offline suite for Advanced Configuration Stage 0 (post-export entry acs0): a guarded owner edit of ONE TOU slot's
target SOC, home-assistant/packages/ecco_tou_target_soc_edit.yaml.

The REAL package runs, together with the REAL Manual Controls helper package (ecco_manual_controls_helpers.yaml, whose
bidirectional sync automations touch the same staging entities), under _ha_script_sim.py (a fail-loud HA script /
automation interpreter) against _manual_tou_sim.py, a model of the firmware's existing manual TOU path.

  [0] static        services, entities, scope (only the target SOC staging value is ever set), fail-closed gates, no
                    hard-coded reserve, the reserve helper never written
  [1] edit          every slot: REVIEW (writes nothing) -> CONFIRM (phrase + review code) -> APPLY; only that slot's target
                    SOC register changes; firmware VERIFIED OK + an independent later read of every written register
  [2] bounds        max(inverter shutdown SOC, ECCO reserve), read again just before the Apply
  [3] review        missing / expired / wrong phrase / reused / the slot changed since the review
  [4] gate          every unsafe state (Free Power, Dump, register 244, recovery, fallback arm / Review / Save, supervision,
                    failback shadow, leases, arms, schedules) and `unavailable` for each: at Review, at Apply, mid-flow
  [5] freshness     a fresh configuration read before the Load; a change made after the last poll is kept; a late Load
  [6] helpers       stale helpers; the owner editing a helper mid-flow; no helper package
  [7] firmware      a refusal at the Apply gate: nothing written, no retry
  [8] uncertain     a failed verification, a partial write at every step, a clamp, a later read that disagrees or never
                    comes, a dropped press: stop, disarm, alert with the observed values, lock further edits until the
                    owner acknowledges; never retried, never a compensating write
  [9] races         Free Power starting during the flow; a second request
  [10] mutation     in-memory mutants are each caught
  [11] PEX          the acs0 declaration

Writes nothing; no Home Assistant, no network, no hardware. It proves the package against models of the firmware path
and of Home Assistant; it does NOT prove how a real interrupted multi-register write behaves on the inverter.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _ha_script_sim as S  # noqa: E402
import _manual_tou_sim as M  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
HELPERS_TEXT = (ROOT / "home-assistant/packages/ecco_manual_controls_helpers.yaml").read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
REVIEW, APPLY, ACK = "ecco_cfg_review_tou_slot_soc", "ecco_cfg_apply_tou_slot_soc", "ecco_cfg_acknowledge_edit_review"
RESULT = "input_text.ecco_cfg_edit_last_result"
EDIT = "input_text.ecco_cfg_last_owner_edit"
PLAN = "input_text.ecco_cfg_edit_review"
LOCK = "input_boolean.ecco_cfg_edit_review_required"
RESERVE = "input_number.ecco_minimum_reserve_soc"
D = "ecco_clock_dongle_"

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


T0 = S.parse_local("2026-10-12 14:00:00")


class Run:
    """Home Assistant with the edit package and the Manual Controls helper package, and the dongle model."""

    def __init__(self, text=PKG_TEXT, setup=None, fp_sched=None, dump_sched=None, reserve=20, shutdown=10, helpers=True):
        self.w = S.World(T0)
        w = self.w
        pk = [yaml.safe_load(text)] + ([yaml.safe_load(HELPERS_TEXT)] if helpers else [])
        self.d = M.ManualTouDongle(w, shutdown_soc=shutdown)
        w.set("input_boolean.ecco_free_power_schedule_armed", "on" if fp_sched else "off")
        w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "on" if dump_sched else "off")
        w.set("input_datetime.ecco_free_power_schedule_start", fp_sched or "2026-10-13 11:00:00")
        w.set("input_datetime.ecco_dump_to_grid_schedule_start", dump_sched or "2026-10-13 18:00:00")
        w.set(RESERVE, f"{float(reserve)}")
        self.ha = S.HA(w, pk)
        self.ha.start()
        w.run_until(T0 + 70)                       # one configuration poll (14:00:42) and the helper startup refresh
        self.before = {n: dict(s) for n, s in self.d.regs["slots"].items()}
        self.gc_before = self.d.regs["gc"]
        if setup:
            setup(self)

    def review(self, slot, soc):
        self.ha.start_script(REVIEW, {"slot": slot, "target_soc": soc})
        self.w.run_until(self.w.t + 1)
        return self

    def code(self):
        parts = self.w.state(PLAN).split("|")
        return parts[2] if len(parts) == 5 else "----"

    def apply(self, phrase=None, run=420):
        if phrase is None:
            parts = self.w.state(PLAN).split("|")
            phrase = f"SET SLOT {parts[0]} TARGET SOC {parts[1]} REVIEW {parts[2]}" if len(parts) == 5 else "-"
        self.ha.start_script(APPLY, {"confirmation": phrase})
        self.w.run_until(self.w.t + run)
        return self

    def edit(self, slot, soc, run=420):
        return self.review(slot, soc).apply(run=run)

    def changed(self):
        out = {}
        for n, s in self.d.regs["slots"].items():
            for k, v in s.items():
                if self.before[n][k] != v:
                    out[(n, k)] = (self.before[n][k], v)
        if self.d.regs["gc"] != self.gc_before:
            out[("gc", "gc")] = (self.gc_before, self.d.regs["gc"])
        return out

    def applies(self):
        return [p for p in self.d.presses if p[1].startswith("apply")]

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


# ======================================================================================================================
print("[0] static")
# ======================================================================================================================
pkg = yaml.safe_load(PKG_TEXT)
check("the package: three result / plan helpers, one lock, three scripts; no automation, no template",
      {k: len(v) for k, v in pkg.items()} == {"input_text": 3, "input_boolean": 1, "script": 3})
services = sorted(set(re.findall(r"action: ([a-z_]+\.[a-z_]+)", PKG_TEXT)))
check("services: helpers, the write enable, two buttons, one number, notifications - nothing else", services == [
    "button.press", "input_boolean.turn_off", "input_boolean.turn_on", "input_text.set_value", "number.set_value",
    "persistent_notification.create", "persistent_notification.dismiss", "switch.turn_off", "switch.turn_on"], str(services))
check("no ESPHome action, Modbus service, select, input_number write or register path",
      not re.search(r"esphome\.|modbus|select_option|write_register|input_number\.set_value", PKG_TEXT))
check("number.set_value is called exactly once, on the slot's target SOC staging entity (the edit's only staged value)",
      PKG_TEXT.count("action: number.set_value") == 1
      and '"{{ e.soc }}"' in PKG_TEXT.split("action: number.set_value")[1][:220])
check("button.press exactly twice (the slot's Load and its Apply); switch.turn_on only on the Manual Configuration Write "
      "Enable", PKG_TEXT.count("action: button.press") == 2 and '"{{ e.load }}"' in PKG_TEXT and '"{{ e.apply }}"' in PKG_TEXT
      and re.findall(r"action: switch\.turn_on\n(?:.*\n){0,3}?\s+entity_id: (\S+)", PKG_TEXT) == [M.ARM])
check("the ECCO reserve helper is only read (never set) and no reserve or bound value is hard-coded",
      "input_number.ecco_minimum_reserve_soc" in PKG_TEXT and not re.search(r"\b40\b", PKG_TEXT.split("script:")[1]))
fw_names = set(re.findall(r'name: "([^"]+)"', FW_TEXT))
fw_slugs = {re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_") for n in fw_names}
used = set(re.findall(r"\b(?:binary_sensor|sensor|switch|button|number|select)\.ecco_clock_dongle_([a-z0-9_]+)", PKG_TEXT))
check(f"every dongle entity the package names exists in the firmware ({len(used)} ids)", used <= fw_slugs,
      str(sorted(used - fw_slugs)))
pk_dir = ROOT / "home-assistant" / "packages"
others = "\n".join(p.read_text(encoding="utf-8") for p in pk_dir.glob("*.yaml") if p.name != "ecco_tou_target_soc_edit.yaml")
named = set(re.findall(r"\b((?:script|input_boolean|input_number|input_datetime)\.ecco_[a-z0-9_]+)", PKG_TEXT))
own = {f"input_text.{k}" for k in pkg["input_text"]} | {f"input_boolean.{k}" for k in pkg["input_boolean"]} \
    | {f"script.{k}" for k in pkg["script"]}
missing = sorted(e for e in named - own if e.split(".", 1)[1] + ":" not in others)
check(f"every other HA entity the gate reads exists in the repository's packages ({len(named - own)})", missing == [], str(missing))
gate = PKG_TEXT.split("refusal: >-", 1)[1].split("- choose:", 1)[0]
binaries = re.findall(r"(?<!not )is_state\('(?:binary_sensor|switch)\.[^']+', 'on'\)", gate)
check("the gate is fail-closed: every flag is refused unless it reads exactly its safe value - no `is_state(x, 'on')` "
      "refusal that would let 'unavailable' through", binaries == [] and gate.count("not is_state(") >= 20, str(binaries))
mp = {}
for n in range(1, 7):
    m = re.search(r"\n\s*%d: \{(.*?)\}" % n, PKG_TEXT, re.S)
    mp[n] = dict(re.findall(r"'(\w+)': '([^']+)'", m.group(1))) if m else {}
check("the per-slot map is exact for slots 1-6 (own Load / Apply / staging, own live TimezoneN, the next slot's start as "
      "the end, own helpers) and names register 267+N", all(
          mp[n].get("load") == f"button.{D}load_current_slot_{n}_to_manual_staging"
          and mp[n].get("apply") == f"button.{D}apply_manual_slot_{n}_settings"
          and mp[n].get("soc") == f"number.{D}manual_slot_{n}_target_soc"
          and mp[n].get("live_soc") == f"sensor.{D}ecco_timezone{n}_soc"
          and mp[n].get("live_t_next") == f"sensor.{D}ecco_timezone{n % 6 + 1}_time"
          and mp[n].get("h_soc") == f"input_number.ecco_manual_slot_{n}_soc_staged" for n in range(1, 7))
      and all(f"{n}: {{'reg': {267 + n}," in PKG_TEXT for n in range(1, 7)))

# ======================================================================================================================
print("\n[1] the edit, every slot (with the real Manual Controls helper package running)")
# ======================================================================================================================
for n in range(1, 7):
    r = Run()
    want = 55 if r.before[n]["soc"] != 55 else 60
    r.review(n, want)
    reviewed = r.res().startswith("REVIEWED") and r.d.presses == [] and r.changed() == {}
    r.apply()
    check(f"slot {n}: {r.before[n]['soc']} -> {want} %: REVIEW wrote nothing; APPLY: one Load, one Apply; ONLY register "
          f"{267 + n} changed; verified by the firmware and an independent later read; recorded; DRIFT notice; disarmed",
          reviewed and r.changed() == {(n, "soc"): (r.before[n]["soc"], want)} and len(r.applies()) == 1
          and sum(1 for p in r.d.presses if p[1].startswith("load")) == 1 and r.res().startswith("APPLIED AND VERIFIED")
          and f"register {267 + n}" in r.w.state(EDIT) and "DRIFT" in r.note() and not r.arm_on() and not r.locked(),
          f"{r.changed()} {r.res()} {r.d.presses}")
r = Run().edit(3, 41)
st = r.d.apply_staging[0]
check("at the Apply, every staged field except the target SOC equals the inverter's registers (start, end, power, source, "
      "mode, grid-charge bit)", st["staging"]["start"] == st["regs"]["slots"][3]["start"]
      and st["staging"]["end"] == st["regs"]["slots"][4]["start"] and st["staging"]["power"] == st["regs"]["slots"][3]["power"]
      and st["staging"]["src"] == st["regs"]["slots"][3]["src"] and st["staging"]["mode"] == st["regs"]["slots"][3]["mode"]
      and st["gc"] == st["regs"]["gc"] and st["staging"]["soc"] == 41, str(st))
phrase = f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}"
r.apply(phrase="SET SLOT 3 TARGET SOC 41 REVIEW 0000")
check("the review is single-use: another Apply after it is refused", r.res().startswith("REFUSED - no pending review")
      and len(r.applies()) == 1, r.res())
r = Run().review(3, 41)
note = r.note("ecco_cfg_edit_review")
check("the review shows the register, old -> new, every unchanged value, the allowed range and the exact phrase",
      "register 270" in note and "40 % -> 41 %" in note and "start 09:00" in note and "power 8000.0 W" in note
      and "Allowed range 20-100 %" in note and f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}" in note, note)

# ======================================================================================================================
print("\n[2] the bound: max(inverter shutdown SOC, ECCO reserve), read fresh")
# ======================================================================================================================
for shutdown, reserve, low_ok, low_bad in ((10, 20, 20, 19), (25, 20, 25, 24), (15, 15, 15, 14)):
    r1 = Run(shutdown=shutdown, reserve=reserve).review(3, low_bad)
    r2 = Run(shutdown=shutdown, reserve=reserve).edit(3, low_ok)
    check(f"shutdown {shutdown} %, reserve {reserve} %: {low_bad} % refused at review, {low_ok} % applied",
          r1.res().startswith("REVIEW REFUSED - target SOC must be") and r1.d.presses == []
          and r2.res().startswith("APPLIED"), f"{r1.res()} | {r2.res()}")
r = Run().review(3, 25)
r.w.set(RESERVE, "30.0")                         # the owner raises the reserve after the review
r.apply()
check("the reserve raised above the reviewed value before the Apply: refused at the Apply, nothing written",
      r.res().startswith("REFUSED - target SOC must be 30-100") and r.d.presses == [] and r.changed() == {}, r.res())
r = Run(setup=lambda x: x.w.at(T0 + 100, lambda: x.w.set(M.SHUTDOWN, "30.0"))).review(3, 25).apply()
check("the inverter shutdown SOC rises to 30 % in the fresh read the Apply waits for: FAILED before the Load, nothing written",
      r.res().startswith("FAILED - target SOC must be 30-100") and r.applies() == [] and r.changed() == {}, r.res())
for ent, label in ((RESERVE, "the ECCO reserve"), (M.SHUTDOWN, "the inverter shutdown SOC")):
    r = Run(setup=lambda x, e_=ent: x.w.set(e_, "unavailable")).review(3, 41)
    check(f"{label} unavailable: refused", r.res().startswith("REVIEW REFUSED") and "unavailable" in r.res(), r.res())
r = Run().edit(3, 41)
check("the reserve helper is never changed by an edit", r.w.state(RESERVE) == "20.0")

# ======================================================================================================================
print("\n[3] review and confirmation")
# ======================================================================================================================
r = Run().apply(phrase="SET SLOT 3 TARGET SOC 41 REVIEW 0000")
check("no review: refused", r.res().startswith("REFUSED - no pending review") and r.d.presses == [], r.res())
r = Run().review(3, 41)
r.w.run_until(r.w.t + 601)
r.apply()
check("a review older than 10 minutes: refused", r.res().startswith("REFUSED - the review has expired"), r.res())
for bad in ("SET SLOT 3 TARGET SOC 41", "SET SLOT 3 TARGET SOC 42 REVIEW {c}", "SET SLOT 4 TARGET SOC 41 REVIEW {c}",
            "set slot 3 target soc 41 review {c}", "SET SLOT 3 TARGET SOC 41 REVIEW {c}x"):
    r = Run().review(3, 41)
    r.apply(phrase=bad.format(c=r.code()))
    check(f"phrase {bad!r}: refused, nothing written", r.res().startswith("REFUSED - the confirmation phrase")
          and r.d.presses == [], r.res())


def soc_changes_after_review(r):
    def go():
        r.d.regs["slots"][3]["soc"] = 50
        r.d.poll()
    r.w.at(T0 + 72, go)


r = Run(setup=soc_changes_after_review).review(3, 41)
r.w.run_until(T0 + 80)
r.apply()
check("the slot changed since the review (e.g. on the inverter's own panel): refused, review again",
      r.res().startswith("REFUSED - the slot changed since the review") and r.d.presses == [], r.res())

# ======================================================================================================================
print("\n[4] the safety gate (fail-closed)")
# ======================================================================================================================
UNSAFE = [
    (f"binary_sensor.{D}free_power_active", "on"), (f"binary_sensor.{D}free_power_operation_in_progress", "on"),
    (f"binary_sensor.{D}free_power_snapshot_valid", "on"), (f"binary_sensor.{D}dump_to_grid_active", "on"),
    (f"binary_sensor.{D}dump_to_grid_operation_in_progress", "on"), (f"binary_sensor.{D}dump_to_grid_snapshot_valid", "on"),
    (f"binary_sensor.{D}manual_write_in_progress", "on"), (f"binary_sensor.{D}rtc_correction_in_progress", "on"),
    (f"switch.{D}manual_configuration_write_enable", "on"), (f"switch.{D}free_power_write_enable", "on"),
    (f"switch.{D}free_power_recovery_arm", "on"), (f"switch.{D}dump_to_grid_write_enable", "on"),
    (f"switch.{D}dump_to_grid_recovery_arm", "on"),
    (f"sensor.{D}ecco_fallback_profile_live_match", "m=PAUSED;obl=FP:AC,DP:CR,R4:CR,BUS:OK;ca=P"),
    (f"sensor.{D}ecco_fallback_profile_live_match", "m=PAUSED_IO;obl=FP:CR,DP:CR,R4:CR,BUS:BY;ca=P"),
    (f"sensor.{D}ecco_fallback_profile_live_match", "m=PAUSED;obl=FP:CR,DP:CR,R4:PC,BUS:OK;ca=P"),
    (f"sensor.{D}ecco_fallback_profile_live_match", "m=UNKNOWN;obl=-;ca=-"),
    (f"sensor.{D}ecco_fallback_profile_review", "st=READING;id=-"),
    (f"sensor.{D}ecco_fallback_profile_review", "st=CANDIDATE_READY;id=AB12"),
    (f"sensor.{D}ecco_fallback_profile_review", "st=SAVING;id=AB12"),
    ("binary_sensor.ecco_fallback_save_available", "on"), ("binary_sensor.ecco_fallback_replace_corrupt_available", "on"),
    ("binary_sensor.ecco_fallback_invalidate_available", "on"),
    (f"sensor.{D}ecco_fallback_profile_review", "prior=VALID;st=CANDIDATE_READY;id=AB12"),
    (f"sensor.{D}ecco_supervision_state", "SUSPECT"), (f"sensor.{D}ecco_supervision_state", "LOST"),
    (f"binary_sensor.{D}ecco_supervision_stable", "off"), (f"sensor.{D}ecco_failback_shadow_state", "SHADOW_EPISODE"),
    (f"sensor.{D}dump_to_grid_export_containment", "CONTAINED"), (f"sensor.{D}free_power_recovery_evidence_id", "E1234"),
    (f"sensor.{D}reg244_original_snapshot", "0"), (f"sensor.{D}free_power_recovery_state", "LOCKED_REVIEW_REQUIRED"),
    (f"sensor.{D}dump_to_grid_recovery_state", "PENDING - restore owed"),
    ("script.ecco_free_power_start_scheduled", "on"), ("script.ecco_dump_to_grid_start_scheduled", "on"),
    (LOCK, "on"), (f"binary_sensor.{D}telemetry_online", "off"), (f"binary_sensor.{D}configuration_online", "off"),
    (f"binary_sensor.{D}manual_configuration_raw_cache_valid", "off"),
]
bad = []
for ent, val in UNSAFE:
    for v in (val, "unavailable"):
        r = Run(setup=lambda x, e_=ent, v_=v: x.w.set(e_, v_)).review(3, 41)
        if not (r.res().startswith("REVIEW REFUSED") and r.d.presses == []):
            bad.append((ent, v, r.res()[:80]))
check(f"each of {len(UNSAFE)} unsafe states, and 'unavailable' for each entity: the review is refused, nothing pressed",
      bad == [], str(bad[:4]))
for label, kw in (("a Free Power schedule starting in 10 min", dict(fp_sched="2026-10-12 14:11:00")),
                  ("a Dump to Grid schedule starting in 10 min", dict(dump_sched="2026-10-12 14:11:00"))):
    r = Run(**kw).review(3, 41)
    check(f"{label}: refused", r.res().startswith("REVIEW REFUSED") and "within 15 minutes" in r.res(), r.res())
check("a Free Power schedule an hour away does not block", Run(fp_sched="2026-10-12 15:00:00").edit(3, 41).res()
      .startswith("APPLIED"))
r = Run().review(3, 41)
r.w.set(f"sensor.{D}ecco_fallback_profile_review", "st=CANDIDATE_READY;id=AB12")   # the owner starts a fallback Review
r.apply()
check("an unsafe state appearing between the review and the Apply: refused at the Apply (the fallback Review is kept)",
      r.res().startswith("REFUSED - a fallback profile Review") and r.d.presses == [], r.res())


def late_flip(ent, val):
    """Flip `ent` right after the Load is pressed (between the Load and the press)."""
    def setup(x):
        orig = x.d._load

        def load_then_flip(n):
            orig(n)
            x.w.after(0.5, lambda: x.w.set(ent, val))
        x.d._load = load_then_flip
    return setup


for ent, val in ((f"binary_sensor.{D}rtc_correction_in_progress", "on"), (f"sensor.{D}ecco_supervision_state", "SUSPECT"),
                 (RESERVE, "50.0")):
    r = Run(setup=late_flip(ent, val)).edit(3, 41)
    check(f"{ent.split('.')[1]} -> {val} after the Load, before the press: the last check stops it - nothing pressed",
          r.applies() == [] and r.changed() == {} and r.res().startswith("FAILED") and not r.arm_on(), f"{r.res()} {r.d.presses}")

# ======================================================================================================================
print("\n[5] freshness of the configuration read")
# ======================================================================================================================


def external_change(r):
    r.w.at(T0 + 75, lambda: r.d.regs["slots"][3].__setitem__("power", 3000))   # e.g. the inverter's own panel


r = Run(setup=external_change).edit(3, 41)
check("an inverter change after the last configuration poll (slot 3 power 8000 -> 3000) is kept: the Apply waits for a "
      "fresh read and Loads from it", r.d.regs["slots"][3]["power"] == 3000 and r.d.regs["slots"][3]["soc"] == 41
      and r.res().startswith("APPLIED"), f"{r.d.regs['slots'][3]} {r.res()}")
r = Run(setup=lambda x: x.w.at(T0 + 72, lambda: x.d.flags.__setitem__("cfg", False))).edit(3, 41)
check("no fresh configuration read within 90 s: FAILED, nothing written", r.res().startswith("FAILED - no fresh configuration")
      and r.d.presses == [], r.res())
r = Run().review(3, 41)
r.d.fault["slow_load"] = 40                      # the Load is answered 40 s late
r.apply()
check("a Load completed more than 30 s after the fresh read: refused (the cache would be too old), nothing pressed",
      r.applies() == [] and r.res().startswith("FAILED") and r.changed() == {}, f"{r.res()} {r.d.presses}")
r = Run().edit(3, 41)
fresh_poll = max(t for t, e, s in r.w.history if e == f"sensor.{D}last_configuration_update" and t < r.applies()[0][0])
check(f"measured cache age at the Apply press on the happy path: {r.applies()[0][0] - fresh_poll:.1f} s (bounded by the "
      "30 s Load check plus the settle waits)", r.applies()[0][0] - fresh_poll < 45)

# ======================================================================================================================
print("\n[6] the Manual Controls helper sync")
# ======================================================================================================================


def stale_helpers(r):
    for n in range(1, 7):
        r.w.set(f"input_number.ecco_manual_slot_{n}_power_staged", "0.0")


r = Run(setup=stale_helpers).edit(3, 41)
check("stale friendly helpers (power 0 W in every slot's helper): the Load + refresh converge them; the edit changes only "
      "the SOC", r.changed() == {(3, "soc"): (40, 41)} and r.res().startswith("APPLIED"), f"{r.changed()} {r.res()}")
r = Run(setup=late_flip("input_number.ecco_manual_slot_3_power_staged", "2000.0")).edit(3, 41)
check("the owner edits slot 3's power helper mid-flow (the sync pushes it into staging): the staged-equals-live proof "
      "stops the edit - nothing pressed, nothing written", r.applies() == [] and r.changed() == {}
      and r.res().startswith("FAILED"), f"{r.res()} {r.d.presses}")
r = Run(helpers=False).edit(3, 41)
check("without the helper package installed (helpers unknown) the edit works the same", r.res().startswith("APPLIED")
      and r.changed() == {(3, "soc"): (40, 41)}, r.res())

# ======================================================================================================================
print("\n[7] a refusal at the firmware's Apply gate")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.fault.__setitem__("refuse_bus", True)).edit(3, 41)
check("bus busy at the gate: FAILED (refused by the dongle; nothing written), one Apply, never retried, not locked, alerted",
      r.res().startswith("FAILED - the firmware refused") and len(r.applies()) == 1 and r.changed() == {}
      and not r.arm_on() and not r.locked() and r.notes() != [], r.res())

# ======================================================================================================================
print("\n[8] uncertain outcomes: stop, disarm, alert, lock")
# ======================================================================================================================


def uncertain(r, label, cond=True):
    check(f"{label}: UNCERTAIN, one Apply, never retried or compensated, disarmed, LOCKED, alerted with the observed values "
          "and recovery steps", cond and r.res().startswith("UNCERTAIN") and len(r.applies()) == 1 and not r.arm_on()
          and r.locked() and "Do NOT retry" in r.note() and sum(1 for p in r.d.presses if p[1].startswith("load")) == 1,
          f"{r.res()} {r.notes()}")


r = Run(setup=lambda x: x.d.fault.__setitem__("verify_fail", True)).edit(3, 41)
uncertain(r, "the firmware's verification fails")
for k in range(0, 6):
    r = Run(setup=lambda x, k_=k: x.d.fault.__setitem__("partial", k_)).edit(3, 41)
    uncertain(r, f"a partial write stopping after {k} of 6 transactions (in the model each rewrites its current value)",
              set(r.changed()) <= {(3, "soc")})
r = Run(setup=lambda x: x.d.fault.__setitem__("clamp_soc", 45)).edit(3, 41)
uncertain(r, "the inverter stores 45 % instead of 41 %")


def other_field_changes(r):
    orig = r.d._finish

    def finish(n, failed):
        orig(n, failed)
        r.d.regs["slots"][3]["power"] = 5000      # something changes another written register right after the Apply
    r.d._finish = finish


r = Run(setup=other_field_changes).edit(3, 41)
uncertain(r, "the firmware says VERIFIED OK but the independent later read shows another register changed (power)",
          "power 5000" in r.note())


def no_later_read(r):
    orig = r.d._finish

    def finish(n, failed):
        orig(n, failed)
        r.w.after(1.5, lambda: r.d.flags.__setitem__("cfg", False))   # after the firmware's own post-Apply poll
    r.d._finish = finish


r = Run(setup=no_later_read).edit(3, 41)
uncertain(r, "no independent later configuration read arrives", "no new configuration read" in r.note())


def drop_apply(r):
    orig = r.d._press

    def press(entity, data):
        if "apply_manual" in entity:
            r.d.presses.append((r.w.t, "apply-dropped", "DROPPED"))
            return
        orig(entity, data)
    r.w.service_handlers["button.press"] = press


r = Run(setup=drop_apply).edit(3, 41)
uncertain(r, "an Apply press that never arrives (nothing written, but that cannot be proven)", r.changed() == {})
r.review(2, 60)
check("while locked, a new review is refused", r.res().startswith("REVIEW REFUSED - an earlier edit"), r.res())
r.ha.start_script(ACK, {"confirmation": "I have checked"})
r.w.run_until(r.w.t + 1)
check("a wrong acknowledgement phrase keeps it locked", r.locked())
r.ha.start_script(ACK, {"confirmation": "I HAVE CHECKED THE TOU SLOTS"})
r.w.run_until(r.w.t + 1)
check("the exact acknowledgement unlocks (and writes nothing to the inverter)", not r.locked()
      and r.res().startswith("ACKNOWLEDGED") and len(r.applies()) == 1)

# ======================================================================================================================
print("\n[9] races")
# ======================================================================================================================
r = Run(setup=lambda x: x.w.at(T0 + 80, lambda: x.d.set_flag("fp_op", True))).edit(3, 41)
check("Free Power starts a transaction while the Apply waits for the fresh read: FAILED, nothing written",
      r.res().startswith("FAILED") and r.changed() == {} and r.applies() == [], f"{r.res()} {r.d.presses}")
r = Run(setup=late_flip(f"binary_sensor.{D}free_power_operation_in_progress", "on")).edit(3, 41)
check("Free Power takes ownership right after the Load: never pressed; nothing written",
      r.changed() == {} and r.applies() == [] and r.res().startswith("FAILED"), f"{r.res()} {r.d.presses}")
r = Run().review(3, 41)
phrase = f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}"
r.ha.start_script(APPLY, {"confirmation": phrase})
r.w.run_until(r.w.t + 5)
r.ha.start_script(APPLY, {"confirmation": phrase})
r.w.run_until(r.w.t + 420)
check("a second Apply while one runs is not started (single mode): one Apply press", len(r.applies()) == 1
      and any("already running" in m for m in r.w.warnings))

# ======================================================================================================================
print("\n[10] mutation")
# ======================================================================================================================
SAME_PW = "and (states(e.pw) | float(-1)) == (states(e.live_pw) | float(-2))"


def battery(text: str) -> dict:
    res = {}
    try:
        x = Run(text).edit(3, 41)
        res["happy"] = x.changed() == {(3, "soc"): (40, 41)} and x.res().startswith("APPLIED") and not x.arm_on()
        x = Run(text).review(3, 41)
        x.apply(phrase=f"SET SLOT 3 TARGET SOC 41 REVIEW {(int(x.code()) + 1) % 10000:04d}")
        res["phrase"] = x.d.presses == []
        x = Run(text, shutdown=10, reserve=20).review(3, 19)
        res["reserve"] = x.d.presses == [] and x.res().startswith("REVIEW REFUSED")
        x = Run(text, shutdown=25, reserve=20).review(3, 24)
        res["shutdown"] = x.d.presses == [] and x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=external_change).edit(3, 41)
        res["fresh"] = x.d.regs["slots"][3]["power"] == 3000
        x = Run(text, setup=late_flip("input_number.ecco_manual_slot_3_power_staged", "2000.0")).edit(3, 41)
        res["same"] = x.changed() == {}
        x = Run(text, setup=lambda y: y.w.set(f"sensor.{D}ecco_fallback_profile_review", "st=SAVING;id=AB12")).review(3, 41)
        res["fallback"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.w.set(f"binary_sensor.{D}rtc_correction_in_progress", "unavailable")).review(3, 41)
        res["failclosed"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.d.fault.__setitem__("verify_fail", True)).edit(3, 41)
        res["lock"] = x.locked() and len(x.applies()) == 1
        x = Run(text, setup=other_field_changes).edit(3, 41)
        res["readback"] = x.res().startswith("UNCERTAIN")
        x = Run(text, setup=drop_apply).edit(3, 41)
        res["arm_off"] = not x.arm_on()
    except Exception as exc:  # noqa: BLE001
        res["crash"] = f"{type(exc).__name__}: {exc}"
    return res


base = battery(PKG_TEXT)
check("the mutation battery holds on the real package", all(v is True for v in base.values()), str(base))
MUTANTS = [
    ("the review code not required", "' TARGET SOC ' ~ want ~ ' REVIEW ' ~ code)", "' TARGET SOC ' ~ want ~ ' REVIEW ' ~ "
     "(confirmation | string)[-4:])", "phrase"),
    ("the reserve ignored", "{% set lo = [shutdown, reserve] | max %}", "{% set lo = shutdown %}", "reserve"),
    ("the shutdown SOC ignored", "{% set lo = [shutdown, reserve] | max %}", "{% set lo = reserve %}", "shutdown"),
    ("no fresh read before the Load (no wait, no freshness refusal)",
     [('timeout: "00:01:30"', 'timeout: "00:00:00.1"'), ("{{ not fresh or refusal2", "{{ refusal2")], None, "fresh"),
    ("the staged power not compared with the live power", SAME_PW, "and true", "same"),
    ("the fallback Review / Save not checked", "{% elif ';st=IDLE;' not in (';' ~ states('sensor.ecco_clock_dongle_ecco_"
     "fallback_profile_review') ~ ';') %}", "{% elif false %}", "fallback"),
    ("a refusal that lets 'unavailable' through (RTC)",
     "not is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'off')",
     "is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on')", "failclosed"),
    ("an uncertain outcome that does not lock", "- action: input_boolean.turn_on\n", "- action: input_boolean.turn_off\n",
     "lock"),
    ("the independent later read ignored", "and diff | length == 0 }}", "}}", "readback"),
    ("the final disarm removed", "      # The write enable always ends off (it only permits an Apply).\n"
     "      - action: switch.turn_off\n", "      # The write enable always ends off (it only permits an Apply).\n"
     "      - action: switch.turn_on\n", "arm_off"),
]
for name, anchor, repl, key in MUTANTS:
    pairs = anchor if isinstance(anchor, list) else [(anchor, repl)]
    if any(PKG_TEXT.count(a) < 1 for a, _ in pairs):
        check(f"mutant '{name}': its anchors occur", False, str([a[:50] for a, _ in pairs if PKG_TEXT.count(a) < 1]))
        continue
    mutated = PKG_TEXT
    for a, b in pairs:
        mutated = mutated.replace(a, b)
    res = battery(mutated)
    check(f"mutant '{name}' is caught by '{key}'", res.get(key) is not True or "crash" in res, str(res))

# ======================================================================================================================
print("\n[11] the post-export declaration (PEX entry acs0)")
# ======================================================================================================================
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite pins acs0's declaration)
import _acs0_scope as F  # noqa: E402

ACS0_FINGERPRINT = "8b60fc3f44c9a1a8ce0e3ed1eaef6742f53d1f1e2256de030df88e03c7c9b37a"
FSW1_FINGERPRINT = "a380efdfa34b1acfc626ceaa47c8faf56347960d5603a9b98c47077ef7439db5"
E = sc.CHAIN.entry("acs0")
ids = [x.id for x in sc.POST_EXPORT_ENTRIES]
check("acs0 is the fourteenth post-export entry, appended right after fsw1", ids.index("acs0") == 13
      and sc.CHAIN.prev_id("acs0") == "fsw1", str(ids))
check("acs0 declares exactly the manifest as chain-pinned and no frozen file; no delta, op path, include, substitution, "
      "banned token or tag", set(E.reverts) == set(E.checkpoints) == {sc.HA_MANIFEST} == set(F.PINNED_REVERTERS)
      and not E.frozen_reverts and not E.frozen_checkpoints and not F.FROZEN_REVERTERS
      and not E.deltas and not E.op_paths_changed and not E.includes_added and not E.subst_added
      and not E.subst_changed and not E.subst_removed and not E.banned_fw_added and not E.banned_files
      and not E.tags_declared and not E.tags_promoted)
check("acs0 declares the files it adds and each exists (the package first)", E.added_files == F.ADDED_FILES
      and PKG_REL in F.ADDED_FILES and all((ROOT / f).is_file() for f in E.added_files))
# PEX: acs0's own fingerprint and its hash link to fsw1
check("acs0's fingerprint is the pinned value, linked to fsw1's", E.fingerprint == ACS0_FINGERPRINT == _pex.fingerprint(E)
      and _pex.record(E)["parent"] == FSW1_FINGERPRINT)   # PEX: hash link
man = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
# PEX: the manifest as of fsw1 (acs0's chain reverter undone exactly, sha256-checked)
old_man = _pex.as_of("deployment/ha-manifest.yaml", "fsw1", _pex.read("deployment/ha-manifest.yaml"))   # PEX: chain reverter
check("the manifest gains exactly one package stanza for this package (and nothing else)", F.add_acs0_manifest(old_man) == man
      and man.count("ecco_tou_target_soc_edit.yaml") == 2 and old_man.count("ecco_tou_target_soc_edit") == 0)

print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    sys.exit(1)
print(f"All {PASSES} Advanced Configuration Stage 0 checks passed.")
print("These prove the package's control flow against models of the firmware's manual TOU path and of Home Assistant "
      "offline; they prove nothing about a live Home Assistant, the dongle, or how a real interrupted write behaves.")
