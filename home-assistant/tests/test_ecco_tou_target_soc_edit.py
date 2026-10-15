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
  [12] tokens       the owner-approved reserved-token amendment: exactly six ids, read only, in exactly three files; no
                    seventh id, variant, undeclared file, write or indirect route

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
FLIGHT = "input_boolean.ecco_cfg_edit_in_flight"
RESERVE = "input_number.ecco_minimum_reserve_soc"
D = "ecco_clock_dongle_"
# The six reserved fallback / failback entity ids the gate READS. The acs0 token amendment (owner-approved Option A) authorises
# exactly these, spelled in full, in exactly this suite, the package and its dongle model. Every other reserved token in this file
# is assembled from parts (the FB-B3 convention), so the suite never spells one.
LIVE_MATCH = "sensor.ecco_clock_dongle_ecco_fallback_profile_live_match"
FB_REVIEW = "sensor.ecco_clock_dongle_ecco_fallback_profile_review"
SAVE_AV = "binary_sensor.ecco_fallback_save_available"
REPLACE_AV = "binary_sensor.ecco_fallback_replace_corrupt_available"
INVALIDATE_AV = "binary_sensor.ecco_fallback_invalidate_available"
SHADOW_STATE = "sensor.ecco_clock_dongle_ecco_failback_shadow_state"
ACS0_IDS = (LIVE_MATCH, FB_REVIEW, SAVE_AV, REPLACE_AV, INVALIDATE_AV, SHADOW_STATE)


def b10(m="MATCH", ca="F", eh="0", obl="FP:CR,DP:CR,R4:CR,BUS:OK"):
    """A live-match (B10) text in the firmware's grammar: m;dx;cx;ox;ix;eh;obl;ca;elig;ew, every key present."""
    cmp = m in ("MATCH", "DRIFT", "CONTEXT", "EXPORT", "OUT_OF_DOMAIN")
    return (f"m={m};dx={'00080' if cmp else '-'};cx={'000' if cmp else '-'};ox={'00000' if cmp else '-'};"
            f"ix={'00' if cmp else '-'};eh={eh};obl={obl};ca={ca};elig={'OK' if cmp else 'UNK'};ew=-")

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
check("the package: three result / plan helpers, the lock and the in-flight marker, three scripts, one automation (the "
      "interrupted-edit watchdog); no template", {k: len(v) for k, v in pkg.items()} == {"input_text": 3, "input_boolean": 2,
                                                                                         "script": 3, "automation": 1}
      and not any("initial" in (v or {}) for v in pkg["input_boolean"].values()))
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
    (LIVE_MATCH, b10("PAUSED", ca="P", eh="U", obl="FP:AC,DP:CR,R4:CR,BUS:OK")),
    (LIVE_MATCH, b10("PAUSED_IO", ca="P", eh="U", obl="FP:CR,DP:CR,R4:CR,BUS:BY")),
    (LIVE_MATCH, b10("PAUSED", ca="P", eh="U", obl="FP:CR,DP:CR,R4:PC,BUS:OK")),
    (LIVE_MATCH, "m=UNKNOWN;obl=-;ca=-"),
    (FB_REVIEW, "st=READING;id=-"), (FB_REVIEW, "st=CANDIDATE_READY;id=AB12"), (FB_REVIEW, "st=SAVING;id=AB12"),
    (SAVE_AV, "on"), (REPLACE_AV, "on"), (INVALIDATE_AV, "on"),
    (FB_REVIEW, "prior=VALID;st=CANDIDATE_READY;id=AB12"),
    (f"sensor.{D}ecco_supervision_state", "SUSPECT"), (f"sensor.{D}ecco_supervision_state", "LOST"),
    (f"binary_sensor.{D}ecco_supervision_stable", "off"), (SHADOW_STATE, "SHADOW_EPISODE"),
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
# Fallback state that is unknown, unavailable, stale, malformed, duplicated or names an incompatible operation: never an edit.
AMBIGUOUS = [
    *[(LIVE_MATCH, v) for v in (
        "", "unknown", "none", "m=MATCH", "MATCH",                                         # empty / truncated / bare word
        b10("UNKNOWN", ca="P", eh="U"), b10("NO_PROFILE"), b10("EXPORT"), b10("OUT_OF_DOMAIN"),   # not a compatible comparison
        b10("MATCH", ca="S"), b10("MATCH", ca="P"), b10("MATCH", ca="I"), b10("MATCH", ca="O"),    # cache stale / pre-fence /
        b10("MATCH", ca="M"), b10("MATCH", ca="B"),                                        # invalid / polling off / unfilled / boot
        b10("MATCH", eh="U"), b10("MATCH", eh="1"),                                        # export hazard unknown / present
        b10("match"), b10("MATCH").replace("m=MATCH", "m=MATCH "),                         # case / whitespace
        b10("PAUSED", ca="P", eh="U", obl="FP:AC,DP:CR,R4:CR,BUS:OK") + ";" + b10("MATCH"),  # duplicated keys (two texts)
        b10("MATCH").replace(";obl=", ";xobl="), b10("MATCH", obl="FP:CR,DP:CR,R4:CR,BUS:OK,X:1"),
        b10("MATCH", obl="FP:CR,DP:CR,R4:CR,BUS:BY"))],
    *[(FB_REVIEW, v) for v in ("", "unknown", "st=IDLE;st=SAVING", "st=SAVING;st=IDLE", "st=idle", "st=IDLE ", "xst=IDLE",
                               "st=IDLEX", "prior=VALID", "st=")],
    *[(e, v) for e in (SAVE_AV, REPLACE_AV, INVALIDATE_AV) for v in ("unknown", "", "true", "On", "ON")],
    *[(SHADOW_STATE, v) for v in ("SHADOW_WATCH", "SHADOW_BOOT", "SHADOW_WOULD_AWAIT_ACK", "SHADOW_EPISODE_HA_BACK", "shadow_idle",
                                  "SHADOW_IDLE ", "", "unknown")],
]
bad = []
for ent, val in AMBIGUOUS:
    r = Run(setup=lambda x, e_=ent, v_=val: x.w.set(e_, v_)).review(3, 41)
    if not (r.res().startswith("REVIEW REFUSED") and r.d.presses == []):
        bad.append((ent[-30:], val, r.res()[:80]))
check(f"each of {len(AMBIGUOUS)} unknown, empty, stale, malformed, duplicated or incompatible fallback states (live match: every "
      "verdict but MATCH / DRIFT / CONTEXT, every cache letter but F, an unknown or present export hazard, a lease or bus not clear; "
      "Review not exactly st=IDLE; an operator gate not exactly off; the shadow not exactly SHADOW_IDLE): refused, nothing pressed",
      bad == [], str(bad[:4]))
ok_states = []
for label, ent, val in (("DRIFT (e.g. after an earlier edit)", LIVE_MATCH, b10("DRIFT")),
                        ("CONTEXT", LIVE_MATCH, b10("CONTEXT"))):
    r = Run(setup=lambda x, e_=ent, v_=val: x.w.set(e_, v_)).edit(3, 41)
    ok_states.append((label, r.res()[:40]))
check("a current comparison other than MATCH (DRIFT, CONTEXT) still allows the edit (step B of the live proof starts in DRIFT)",
      all(v.startswith("APPLIED AND VERIFIED") for _l, v in ok_states), str(ok_states))
named = {}
for m_ in ("NO_PROFILE", "EXPORT", "OUT_OF_DOMAIN"):
    named[m_] = Run(setup=lambda x, v_=m_: x.w.set(LIVE_MATCH, b10(v_))).review(3, 41).res()
check("NO_PROFILE, EXPORT and OUT_OF_DOMAIN (a trusted comparison, but no valid saved profile, export open against it, or live "
      "settings outside its domain) are refused with the verdict named - a deliberate fail-closed choice the safety case documents",
      all(v.startswith("REVIEW REFUSED - the fallback live match is " + m_ + ":") for m_, v in named.items()), str(named))
for label, kw in (("a Free Power schedule starting in 10 min", dict(fp_sched="2026-10-12 14:11:00")),
                  ("a Dump to Grid schedule starting in 10 min", dict(dump_sched="2026-10-12 14:11:00"))):
    r = Run(**kw).review(3, 41)
    check(f"{label}: refused", r.res().startswith("REVIEW REFUSED") and "within 15 minutes" in r.res(), r.res())
check("a Free Power schedule an hour away does not block", Run(fp_sched="2026-10-12 15:00:00").edit(3, 41).res()
      .startswith("APPLIED"))
r = Run().review(3, 41)
r.w.set(FB_REVIEW, "st=CANDIDATE_READY;id=AB12")   # the owner starts a fallback Review
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
check("bus busy at the gate: FAILED (refused; nothing written, confirmed by the unchanged gate-pass counter and two later "
      "reads), one Apply, never retried, not locked, alerted",
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
        r.w.after(5.0, lambda: r.d.flags.__setitem__("cfg", False))   # right AFTER the firmware's own post-Apply poll
    r.d._finish = finish


r = Run(setup=no_later_read).edit(3, 41)
uncertain(r, "only the firmware's own post-Apply poll arrives (no poll that began after it): not enough",
          "no complete later configuration read" in r.note())


def cache_invalid_after(r):
    orig = r.d._finish

    def finish(n, failed):
        orig(n, failed)
        r.w.after(20.0, lambda: r.w.set(f"binary_sensor.{D}manual_configuration_raw_cache_valid", "off"))
    r.d._finish = finish


r = Run(setup=cache_invalid_after).edit(3, 41)
uncertain(r, "the later read is incomplete (raw configuration cache invalid, e.g. Block A failed)",
          "no complete later configuration read" in r.note())


def api_blip(polls_after=False):
    """The ESPHome connection drops right after the outcome (before the firmware's own post-Apply poll publishes) and
    reconnects later, re-sending that poll's time; with polls_after=False no periodic poll lands before the judgement."""
    def setup(r):
        st = {"t0": None, "pending": None}
        orig_poll, orig_finish = r.d.poll, r.d._finish

        def poll():
            t0 = st["t0"]
            if t0 is not None and t0 + 2.6 <= r.w.t < t0 + 8.0:      # disconnected: the poll runs, HA hears nothing
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


r = Run(setup=api_blip()).edit(3, 41)
uncertain(r, "a connection drop and the reconnect's re-sent time are not two reads (only the firmware's own poll is real)",
          "no complete later configuration read" in r.note())
r = Run(setup=api_blip(polls_after=True)).edit(3, 41, run=480)
check("...the same drop with the periodic polls continuing: APPLIED AND VERIFIED on a poll that began after the "
      "firmware's own", r.res().startswith("APPLIED AND VERIFIED") and r.changed() == {(3, "soc"): (40, 41)}
      and not r.locked(), r.res())


def partial_then_rejected(r):
    """Four transactions land (each rewrites its current value, so every register reads unchanged), the sequence stops,
    and an unrelated REJECTED text overwrites the result: only the gate-pass counter shows that a write happened."""
    r.d.fault["partial"] = 4
    orig = r.d._finish

    def finish(n, failed):
        orig(n, failed)
        r.w.after(0.5, lambda: r.w.set(M.RESULT, "REJECTED - arm Manual Configuration Write Enable first"))
    r.d._finish = finish


r = Run(setup=partial_then_rejected).edit(3, 41)
uncertain(r, "registers unchanged + a REJECTED text, but the gate-pass counter moved: never 'nothing written'",
          r.changed() == {} and not r.res().startswith("FAILED"))


def rejected_text_overwrites(r):
    orig = r.d._finish

    def finish(n, failed):
        orig(n, failed)                           # the write really happened and verified...
        r.w.after(0.5, lambda: r.w.set(M.RESULT, "REJECTED - cannot load Slot 2 staging while Free Power or Dump to "
                                                 "Grid owns TOU settings"))   # ...then an unrelated refusal text
    r.d._finish = finish


r = Run(setup=rejected_text_overwrites).edit(3, 41)
uncertain(r, "a REJECTED text from an unrelated press overwrites the result after a real write: never 'nothing written'",
          not r.res().startswith("FAILED") and r.changed() == {(3, "soc"): (40, 41)})


def arm_stuck(r):
    """The Apply press and every later turn_off are lost (API trouble): the write enable stays ON."""
    orig_off = r.d._switch(False)
    orig_press = r.d._press

    def turn_off(entity, data):
        if entity == M.ARM:
            return                                    # never reaches the dongle
        orig_off(entity, data)

    def press(entity, data):
        if "apply_manual" in entity:
            r.d.presses.append((r.w.t, "apply-dropped", "DROPPED"))
            return
        orig_press(entity, data)
    r.w.service_handlers["switch.turn_off"] = turn_off
    r.w.service_handlers["button.press"] = press


r = Run(setup=arm_stuck).edit(3, 41)
check("the write enable cannot be confirmed off at the end: UNCERTAIN, LOCKED, alerted", r.res().startswith("UNCERTAIN")
      and r.locked() and "not confirmed off" in str(r.notes()), f"{r.res()} {r.notes()}")
r = Run().review(3, 41)
r.ha.start_script(APPLY, {"confirmation": f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}"})
r.w.run_until(r.w.t + 45)                        # mid-flow (after the fresh read and the Load)
r.ha.stop()
r.w.run_until(r.w.t + 60)
r.ha = S.HA(r.w, [yaml.safe_load(PKG_TEXT), yaml.safe_load(HELPERS_TEXT)])
r.ha.start()
r.w.run_until(r.w.t + 120)
check("Home Assistant restarts in the middle of an edit: the watchdog marks it UNCERTAIN, disarms, LOCKS and alerts",
      r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked() and not r.arm_on()
      and "interrupted" in str(r.notes()), f"{r.res()} {r.notes()}")
check("...and the in-flight marker is cleared once judged", r.w.state(FLIGHT) == "off")
r = Run()
r.w.set(FLIGHT, "on")                            # an Apply was cancelled mid-flight (e.g. a script reload)
r.w.run_until(r.w.t + 5)
check("an Apply cancelled mid-flight (script reload): the watchdog fires on the stopped run - UNCERTAIN, LOCKED",
      r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked() and r.w.state(FLIGHT) == "off", r.res())


def restart_mid_edit(arm_back_after=None, unreachable=False):
    """Review + Apply, Home Assistant goes down mid-flow with the write enable ON, and comes back with the dongle's
    entities unavailable; they return after arm_back_after seconds (never, if unreachable)."""
    r = Run().review(3, 41)
    r.ha.start_script(APPLY, {"confirmation": f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}"})
    r.w.run_until(r.w.t + 45)
    r.ha.stop()
    r.d.arm = True
    r.w.set(M.ARM, "unavailable")
    r.w.run_until(r.w.t + 30)
    if unreachable:
        orig = r.d._switch(False)
        r.w.service_handlers["switch.turn_off"] = lambda ent, data: None if ent == M.ARM else orig(ent, data)
    r.ha = S.HA(r.w, [yaml.safe_load(PKG_TEXT), yaml.safe_load(HELPERS_TEXT)])
    if unreachable:
        r.w.service_handlers["switch.turn_off"] = lambda ent, data: None if ent == M.ARM else orig(ent, data)
    r.ha.start()
    return r


r = restart_mid_edit()
presses_before = len(r.applies())
r.w.run_until(r.w.t + 1)
locked_at_once = r.locked() and r.res().startswith("UNCERTAIN - the edit was interrupted")
r.review(2, 60)
review_blocked = r.res().startswith("REVIEW REFUSED - an earlier edit") and r.w.state(PLAN) == "used"
r.ha.start_script(APPLY, {"confirmation": "SET SLOT 3 TARGET SOC 41 REVIEW 0000"})
r.w.run_until(r.w.t + 2)
check("restart mid-edit: LOCKED and UNCERTAIN within a second of Home Assistant starting (before the dongle is back); a "
      "Review or Apply in that window is refused", locked_at_once and review_blocked and r.res().startswith("REFUSED")
      and r.locked() and len(r.applies()) == presses_before, f"{r.res()} {r.w.state(PLAN)}")
r.w.at(r.w.t + 90, lambda: r.w.set(M.ARM, "on"))
r.w.run_until(r.w.t + 120)
check("...when the dongle returns with the write enable ON, the watchdog turns it off and confirms it (no 'not "
      "confirmed' alert)", not r.arm_on() and r.w.state(M.ARM) == "off" and "ecco_cfg_edit_arm" not in r.w.notifications,
      f"{r.w.state(M.ARM)} {list(r.w.notifications)}")
r = restart_mid_edit(unreachable=True)
r.w.at(r.w.t + 60, lambda: r.w.set(M.ARM, "on"))
r.w.run_until(r.w.t + 700)
check("...when the write enable cannot be turned off: a separate 'NOT confirmed off' alert, still LOCKED",
      r.locked() and "NOT confirmed off" in r.w.notifications.get("ecco_cfg_edit_arm", {}).get("title", ""),
      str(list(r.w.notifications)))

r = Run().review(3, 41)
r.ha.start_script(APPLY, {"confirmation": f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}"})
r.w.run_until(r.w.t + 75)
mid = r.res()
r.ha.start_script(REVIEW, {"slot": 2, "target_soc": 55})
r.ha.start_script(ACK, {"confirmation": "I HAVE CHECKED THE TOU SLOTS"})
r.w.run_until(r.w.t + 2)
check("a Review or Acknowledge while an Apply runs is refused and touches neither the result, the plan nor the marker",
      mid.startswith("IN PROGRESS") and r.res() == mid and r.w.state(PLAN) == "used" and r.w.state(FLIGHT) == "on"
      and "ecco_cfg_edit_busy" in r.w.notifications, f"{mid} | {r.res()} | {r.w.state(PLAN)}")
r.ha.stop()
r.w.run_until(r.w.t + 30)
r.ha = S.HA(r.w, [yaml.safe_load(PKG_TEXT), yaml.safe_load(HELPERS_TEXT)])
r.ha.start()
r.w.run_until(r.w.t + 120)
check("...and a restart after it still catches the interrupted run: UNCERTAIN, LOCKED, alerted",
      r.res().startswith("UNCERTAIN - the edit was interrupted") and r.locked(), r.res())


def drop_apply(r):
    orig = r.d._press

    def press(entity, data):
        if "apply_manual" in entity:
            r.d.presses.append((r.w.t, "apply-dropped", "DROPPED"))
            return
        orig(entity, data)
    r.w.service_handlers["button.press"] = press


r = Run(setup=drop_apply)
r.review(3, 41)
r.ha.start_script(APPLY, {"confirmation": f"SET SLOT 3 TARGET SOC 41 REVIEW {r.code()}"})
on_t = off_t = None
for _ in range(4200):
    r.w.run_until(r.w.t + 0.1)
    if r.w.state(M.ARM) == "on" and on_t is None:
        on_t = r.w.t
    if on_t is not None and r.w.state(M.ARM) == "off" and off_t is None:
        off_t = r.w.t
check("an Apply press that never arrives: the write enable is turned off right after the firmware's 45 s window, not "
      "after the judging waits (on for at most 50 s)", on_t is not None and off_t is not None and off_t - on_t <= 50,
      f"{on_t} {off_t}")
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
        x = Run(text, setup=lambda y: y.w.set(FB_REVIEW, "st=SAVING;id=AB12")).review(3, 41)
        res["fallback"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.w.set(LIVE_MATCH, b10("MATCH", ca="S"))).review(3, 41)
        res["stale"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.w.set(LIVE_MATCH, b10("NO_PROFILE"))).review(3, 41)
        res["verdict"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.w.set(FB_REVIEW, "st=IDLE;st=SAVING")).review(3, 41)
        res["dup"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.w.set(f"binary_sensor.{D}rtc_correction_in_progress", "unavailable")).review(3, 41)
        res["failclosed"] = x.res().startswith("REVIEW REFUSED")
        x = Run(text, setup=lambda y: y.d.fault.__setitem__("verify_fail", True)).edit(3, 41)
        res["lock"] = x.locked() and len(x.applies()) == 1
        x = Run(text, setup=other_field_changes).edit(3, 41)
        res["readback"] = x.res().startswith("UNCERTAIN")
        x = Run(text, setup=drop_apply).edit(3, 41)
        res["arm_off"] = not x.arm_on()
        x = Run(text, setup=partial_then_rejected).edit(3, 41)
        res["counter"] = x.res().startswith("UNCERTAIN")
        x = Run(text, setup=api_blip()).edit(3, 41)
        res["times"] = x.res().startswith("UNCERTAIN")
        x = Run(text).review(3, 41)
        x.ha.start_script(APPLY, {"confirmation": f"SET SLOT 3 TARGET SOC 41 REVIEW {x.code()}"})
        x.w.run_until(x.w.t + 75)
        x.ha.start_script(REVIEW, {"slot": 2, "target_soc": 55})
        x.w.run_until(x.w.t + 2)
        res["busy"] = x.res().startswith("IN PROGRESS")
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
    ("the fallback Review / Save not checked", "{% elif R.count(';st=') != 1 or ';st=IDLE;' not in R %}", "{% elif false %}",
     "fallback"),
    ("the live-match cache freshness and export hazard not checked", "{% elif ';ca=F;' not in L or ';eh=0;' not in L %}",
     "{% elif false %}", "stale"),
    ("the live-match verdict not checked", "{% elif ';m=MATCH;' not in L and ';m=DRIFT;' not in L and ';m=CONTEXT;' not in L %}",
     "{% elif false %}", "verdict"),
    ("a duplicated Review state accepted", "{% elif R.count(';st=') != 1 or ';st=IDLE;' not in R %}",
     "{% elif ';st=IDLE;' not in R %}", "dup"),
    ("a refusal that lets 'unavailable' through (RTC)",
     "not is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'off')",
     "is_state('binary_sensor.ecco_clock_dongle_rtc_correction_in_progress', 'on')", "failclosed"),
    ("an uncertain outcome that does not lock", "- action: input_boolean.turn_on\n", "- action: input_boolean.turn_off\n",
     "lock"),
    ("the independent later read ignored", "and diff | length == 0 }}", "}}", "readback"),
    ("the gate-pass counter ignored", "and later_read and not attempts_moved and unchanged", "and later_read and unchanged",
     "counter"),
    ("the later reads compared as text, not times",
     [("as_timestamp(states('sensor.ecco_clock_dongle_last_configuration_update'), 0) > as_timestamp(cfg_0, 0) }}",
       "states('sensor.ecco_clock_dongle_last_configuration_update') != cfg_0 }}"),
      ("and as_timestamp(states('sensor.ecco_clock_dongle_last_configuration_update'), 0) > as_timestamp(cfg_1, 0) }}",
       "and states('sensor.ecco_clock_dongle_last_configuration_update') != cfg_1 }}"),
      ("and as_timestamp(states('sensor.ecco_clock_dongle_last_configuration_update'), 0) > as_timestamp(cfg_1, 0)\n",
       "and states('sensor.ecco_clock_dongle_last_configuration_update') != cfg_1\n"),
      ("as_timestamp(cfg_0, 0) > 0 and ", ""), ("as_timestamp(cfg_1, 0) > as_timestamp(cfg_0, 0)", "cfg_1 != cfg_0")],
     None, "times"),
    ("a Review allowed while an Apply runs",
     "{{ not is_state('script.ecco_cfg_apply_tou_slot_soc', 'off') or not is_state('input_boolean.ecco_cfg_edit_in_flight', 'off') }}",
     "{{ false }}", "busy"),
    ("the final disarm removed", "      # The write enable always ends off (it only permits an Apply) - and must be SEEN off.\n"
     "      - action: switch.turn_off\n", "      # The write enable always ends off (it only permits an Apply) - and must be SEEN off.\n"
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

ACS0_FINGERPRINT = "d1a56996a4f82cab796c6d01410630453517faca0131824c95f114f53d28253e"
FSW1_FINGERPRINT = "a380efdfa34b1acfc626ceaa47c8faf56347960d5603a9b98c47077ef7439db5"
E = sc.CHAIN.entry("acs0")
ids = [x.id for x in sc.POST_EXPORT_ENTRIES]
check("acs0 is the fourteenth post-export entry, appended right after fsw1", ids.index("acs0") == 13
      and sc.CHAIN.prev_id("acs0") == "fsw1", str(ids))
ACS0_FILES = frozenset({PKG_REL, "home-assistant/tests/_manual_tou_sim.py", "home-assistant/tests/test_ecco_tou_target_soc_edit.py"})
FROZEN_SUITES = {"registry/tests/test_fallback_profile_schema.py", "registry/tests/test_fallback_recovery_dashboard.py",
                 "registry/tests/test_fallback_save_scope.py"}
check("acs0 declares exactly the manifest as chain-pinned, exactly the three amended older suites as frozen edits (each with its "
      "reverter and checkpoint), exactly its own three files as reserved-token holders, and no delta, op path, include, substitution, "
      "firmware banned token or tag", set(E.reverts) == set(E.checkpoints) == {sc.HA_MANIFEST} == set(F.PINNED_REVERTERS)
      and set(E.frozen_reverts) == set(E.frozen_checkpoints) == set(F.FROZEN_REVERTERS) == FROZEN_SUITES
      and all(f in _pex.FROZEN for f in FROZEN_SUITES)   # PEX: each amended suite really is frozen, so the edit is declared
      and E.banned_files == F.BANNED_FILES == ACS0_FILES and F.RESERVED_IDS == ACS0_IDS
      and not E.deltas and not E.op_paths_changed and not E.includes_added and not E.subst_added
      and not E.subst_changed and not E.subst_removed and not E.banned_fw_added
      and not E.tags_declared and not E.tags_promoted)
# PEX: undoing acs0 exactly gives each amended suite as of fsw1, in which nothing of the amendment exists (sha256-checked steps)
_pre = {rel: _pex.as_of(rel, "fsw1", _pex.read(rel)) for rel in sorted(FROZEN_SUITES)}   # PEX: frozen reverters
check("undone exactly, each amended suite is its fsw1 state with no trace of acs0, and re-applying acs0's pairs gives the live file",
      all("acs0" not in t and "ecco_tou_target_soc_edit" not in t for t in _pre.values())
      and F.add_acs0_suite_ps(_pre["registry/tests/test_fallback_profile_schema.py"]) == _pex.read("registry/tests/test_fallback_profile_schema.py")   # PEX
      and F.add_acs0_suite_rd(_pre["registry/tests/test_fallback_recovery_dashboard.py"]) == _pex.read("registry/tests/test_fallback_recovery_dashboard.py")   # PEX
      and F.add_acs0_suite_ss(_pre["registry/tests/test_fallback_save_scope.py"]) == _pex.read("registry/tests/test_fallback_save_scope.py"))   # PEX
check("acs0 declares the files it adds and each exists (the package first)", E.added_files == F.ADDED_FILES
      and PKG_REL in F.ADDED_FILES and all((ROOT / f).is_file() for f in E.added_files))
# PEX: acs0's own fingerprint and its hash link to fsw1
check("acs0's fingerprint is the pinned value, linked to fsw1's", E.fingerprint == ACS0_FINGERPRINT == _pex.fingerprint(E)
      and _pex.record(E)["parent"] == FSW1_FINGERPRINT)   # PEX: hash link
# PEX: the manifest as of acs0 (any later entry that edits it, e.g. fcc1, undone exactly, sha256-checked)
man = _pex.as_of("deployment/ha-manifest.yaml", "acs0", _pex.read("deployment/ha-manifest.yaml"))   # PEX: chain reverter
# PEX: the manifest as of fsw1 (acs0's chain reverter undone exactly, sha256-checked)
old_man = _pex.as_of("deployment/ha-manifest.yaml", "fsw1", _pex.read("deployment/ha-manifest.yaml"))   # PEX: chain reverter
check("the manifest gains exactly one package stanza for this package (and nothing else)", F.add_acs0_manifest(old_man) == man
      and man.count("ecco_tou_target_soc_edit.yaml") == 2 and old_man.count("ecco_tou_target_soc_edit") == 0)

# ======================================================================================================================
print("\n[12] the reserved-token amendment (owner-approved Option A): exactly six ids, read only, in exactly three files")
# ======================================================================================================================
# Every reserved token and every NON-authorised id below is assembled from parts, so this suite spells only the six it may.
FB_TOK, FAB_TOK = "ecco_" + "fallback", "ecco_" + "failback"
RESERVED = re.compile("|".join((FB_TOK, "FALLBACK" + "_PROFILE", "FAILBACK" + "_STATE", FAB_TOK)))
B10_TOK = "fallback_profile_" + "live_match"
ID_RES = [re.compile(r"(?<![a-z0-9_])" + re.escape(i) + r"(?![a-z0-9_])") for i in ACS0_IDS]
READ_CALL = re.compile(r"\b(?:states|is_state)\('(?:" + "|".join(re.escape(i) for i in ACS0_IDS) + r")'[,)]")
# Every Home Assistant template route to another entity's state or attributes that does not name it in states() / is_state():
# state_attr / is_state_attr / has_value / state_translated, the states object in any form other than a call (states.x,
# states[...], states | selectattr(...)), expand, *_entities, device / area / floor / label helpers, and this.
INDIRECT = re.compile(r"\b(?:is_)?state_attr\(|\bhas_value\(|\bstate_translated\(|\bstates\b(?!\()|\bexpand\(|_entities\("
                      r"|\b(?:device|area|floor|label)_[a-z_]+\(|\b(?:device_id|area_id|floor_id|labels|areas|floors)\(|\bthis\.")
ARG = re.compile(r"\b(?:states|is_state)\(([^,)]*)")
LITERAL_ARG = re.compile(r"'[a-z_]+\.[a-z0-9_]+'|e\.[a-z_]+")
status_pkg = yaml.safe_load((ROOT / "home-assistant" / "packages" / (FB_TOK + "_status.yaml")).read_text(encoding="utf-8"))
STATUS_IDS = sorted({x["unique_id"] for block in status_pkg.get("template", []) for kind in ("sensor", "binary_sensor")
                     for x in block.get(kind, []) if "unique_id" in x and not RESERVED.search(x["unique_id"])})


def residue(text: str) -> list:
    """Reserved tokens left once the six authorised ids (full ids, word-bounded) are removed: must be none."""
    for rx in ID_RES:
        text = rx.sub("", text)
    return RESERVED.findall(text) + ([B10_TOK] if B10_TOK in text else [])


def violations(rel: str, text: str) -> list:
    if rel not in F.BANNED_FILES:
        return [("undeclared file", t) for t in RESERVED.findall(text)] + ([("undeclared file", B10_TOK)] if B10_TOK in text else [])
    v = [("not an authorised id", t) for t in residue(text)]
    if rel == PKG_REL:
        n_ids = sum(len(rx.findall(text)) for rx in ID_RES)
        n_reads = len(READ_CALL.findall(text))
        if n_ids != n_reads:
            v.append(("a reserved id outside states() / is_state()", n_ids - n_reads))
        v += [("indirect access", m.group(0)) for m in INDIRECT.finditer(text)]
        v += [("a built entity id", a.strip()) for a in ARG.findall(text) if not LITERAL_ARG.fullmatch(a.strip())]
        v += [("a fallback status entity by another name", u) for u in STATUS_IDS if u in text]
    return v


texts = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in sorted(F.BANNED_FILES)}
check("live: none of the three declared files spells any reserved token but the six ids (no seventh id, variant or fragment)",
      all(violations(rel, t) == [] for rel, t in texts.items()), str({r: violations(r, t)[:3] for r, t in texts.items()}))
check("each declared file really holds all six ids (the declaration is not stale), and the package names exactly these six",
      all(all(rx.search(t) for rx in ID_RES) for t in texts.values())
      and sorted(set(re.findall(r"[a-z_]+\.[a-z0-9_]*(?:" + FB_TOK + "|" + FAB_TOK + r")[a-z0-9_]*", PKG_TEXT))) == sorted(ACS0_IDS))
check("the package READS them only: every occurrence is inside states() / is_state() (24: six ids x four gate copies), never a "
      "target, a service call or a write", len(READ_CALL.findall(PKG_TEXT)) == sum(len(rx.findall(PKG_TEXT)) for rx in ID_RES) == 24
      and not re.search(r"entity_id:[^\n]*(?:" + FB_TOK + "|" + FAB_TOK + ")", PKG_TEXT))
check(f"no indirect route: no state_attr / states.<domain> / states[...] / expand / *_entities / this.; every states() and is_state() "
      f"argument is a literal entity id or the slot map; none of the fallback status package's {len(STATUS_IDS)} other entities "
      "(shadow check, supervision status, episode flag, ...) is read", not INDIRECT.search(PKG_TEXT)
      and all(LITERAL_ARG.fullmatch(a.strip()) for a in ARG.findall(PKG_TEXT)) and not [u for u in STATUS_IDS if u in PKG_TEXT]
      and "ecco_shadow_check" in STATUS_IDS, str(STATUS_IDS))
NEG = {
    "a seventh id (the fallback arm), read": PKG_TEXT + "\n# {{ is_state('switch.ecco_clock_dongle_" + FB_TOK + "_profile_arm', 'off') }}\n",
    "a variant of an authorised id": PKG_TEXT + "\n# {{ states('sensor.ecco_clock_dongle_" + FB_TOK + "_profile_review_id') }}\n",
    "a fragment that builds the B10 id": PKG_TEXT + "\n# {{ states('sensor.ecco_clock_dongle_ecco_' ~ '" + B10_TOK + "') }}\n",
    "a write to an authorised id": PKG_TEXT + "\n      - action: homeassistant.update_entity\n        target:\n          entity_id: "
                                   + LIVE_MATCH + "\n",
    "an id as a bare template value": PKG_TEXT + "\n# {{ '" + SAVE_AV + "' }}\n",
    "a prefixed variant (another domain)": PKG_TEXT + "\n# {{ states('binary_" + FB_REVIEW + "') }}\n",
    "state_attr on the shadow check": PKG_TEXT + "\n# {{ state_attr('sensor.ecco_shadow_check', 'shadow_state') }}\n",
    "the states object": PKG_TEXT + "\n# {{ states.binary_sensor.ecco_shadow_episode_open.state }}\n",
    "expand()": PKG_TEXT + "\n# {{ expand('group.ecco_x') | list }}\n",
    "an entity id built at run time": PKG_TEXT + "\n# {{ states('binary_sensor.ecco_' ~ 'x') }}\n",
    "the status package's shadow check by name": PKG_TEXT + "\n# {{ states('sensor.ecco_shadow_check') }}\n",
    "states | selectattr (a search by name)": PKG_TEXT + "\n# {{ states | selectattr('entity_id', 'search', 'shadow_st') | list }}\n",
    "states.<domain> | selectattr": PKG_TEXT + "\n# {{ states.sensor | selectattr('state', 'eq', 'SHADOW_IDLE') | list }}\n",
    "is_state_attr": PKG_TEXT + "\n# {{ is_state_attr('sensor.ecco_shadow_check', 'shadow_state', 'SHADOW_IDLE') }}\n",
    "has_value on a built id": PKG_TEXT + "\n# {{ has_value('sensor.' ~ 'x') }}\n",
    "state_translated": PKG_TEXT + "\n# {{ state_translated('sensor.ecco_x') }}\n",
    "device_attr": PKG_TEXT + "\n# {{ device_attr('abc', 'name') }}\n",
    "area_entities": PKG_TEXT + "\n# {{ area_entities('garage') }}\n",
}
caught = {k: bool(violations(PKG_REL, t)) for k, t in NEG.items()}
check(f"negatives: each of {len(NEG)} evasions in the package is refused (a seventh id, a variant, a prefixed variant, a fragment, a "
      "write, a bare id, state_attr / is_state_attr / has_value / state_translated, the states object incl. selectattr searches, expand, "
      "device / area helpers, a built id, the status package's sensors by another name)", all(caught.values()),
      str([k for k, v in caught.items() if not v]))
check("negatives: an authorised id in any UNDECLARED file is refused (another package, the dashboard, a frontend file)",
      all(violations(rel, "x: " + LIVE_MATCH) for rel in ("home-assistant/packages/ecco_manual_controls_helpers.yaml",
                                                         "home-assistant/dashboards/ecco_pro.yaml", "frontend/x/card.ts")))
# The amended older checks exempt EXACTLY this: their own regexes and file sets, read from the declared pairs (the PEX proofs show the
# live suites are exactly those pairs; the not-frozen live-match suite is checked against its recorded pairs here).
lm_text = (ROOT / F.SUITE_LM_REL).read_text(encoding="utf-8")
check("the live-match suite carries acs0's three recorded edits exactly once each, and none of the originals",
      all(lm_text.count(new) == 1 and lm_text.count(old) == (1 if old in new else 0) for old, new in F.SUITE_LM_EDITS)
      and F.pre_acs0_suite_lm(lm_text) != lm_text)


def rx_of(block: str, name: str):
    body = block.split(name + " = re.compile(", 1)[1].split(")\n", 1)[0]
    return re.compile("".join(re.findall(r'r"([^"]*)"', body)))


def files_of(block: str) -> set:
    return set(re.findall(r'"(home-assistant/[^"]+)"', block))


PS_RX, RD_RX, LM_RX = rx_of(F.SUITE_PS_0_NEW, "ACS0_SHADOW_RE"), rx_of(F.SUITE_RD_0_NEW, "ACS0_IDS_RE"), rx_of(F.SUITE_LM_0_NEW, "ACS0_B10_RE")
NEAR = [i + s_ for i in ACS0_IDS for s_ in ("_x", "_id", "2")] \
    + [i.replace("ecco_clock_dongle_", "ecco_clock_dongle2_") for i in ACS0_IDS if "ecco_clock_dongle_" in i] \
    + ["binary_" + i for i in ACS0_IDS if i.startswith("sensor.")] + ["x" + i for i in ACS0_IDS] \
    + ["switch.ecco_clock_dongle_" + FB_TOK + "_profile_arm", "sensor.ecco_clock_dongle_" + FAB_TOK + "_shadow_episode",
       "sensor.ecco_clock_dongle_" + FB_TOK + "_profile_state", "binary_sensor." + FB_TOK + "_reset_high_water_available"]


def exempts(rx) -> set:
    return {i for i in ACS0_IDS if rx.sub("", i) == ""}


check("the amended FB-C3 strict rule exempts exactly the shadow State id, the FB-B3 holder scan exactly the six ids, the B10 scan "
      "exactly the live-match id - and none of them any near miss (a suffix, another device, the arm, another shadow id, the profile "
      "state, another gate)", exempts(PS_RX) == {SHADOW_STATE} and exempts(RD_RX) == set(ACS0_IDS) and exempts(LM_RX) == {LIVE_MATCH}
      and not [n for n in NEAR if any(rx.sub("", n) != n and RESERVED.search(rx.sub("", n)) is None for rx in (PS_RX, RD_RX, LM_RX))],
      str([n for n in NEAR if any(rx.sub("", n) != n and RESERVED.search(rx.sub("", n)) is None for rx in (PS_RX, RD_RX, LM_RX))]))
check("...and each applies to exactly acs0's files: the strict rule and the B10 scan to the three declared files, the FB-B3 scan to "
      "the package alone; the exact allowlists name acs0's three files and nothing else new",
      files_of(F.SUITE_PS_0_NEW) == set(F.BANNED_FILES) == files_of(F.SUITE_LM_0_NEW) == files_of(F.SUITE_SS_0_NEW)
      and files_of(F.SUITE_RD_0_NEW) == {PKG_REL}
      and files_of(F.SUITE_PS_1_NEW) - files_of(F.SUITE_PS_1_OLD) == set(F.BANNED_FILES)
      and files_of(F.SUITE_PS_1_OLD) <= files_of(F.SUITE_PS_1_NEW))

print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    sys.exit(1)
print(f"All {PASSES} Advanced Configuration Stage 0 checks passed.")
print("These prove the package's control flow against models of the firmware's manual TOU path and of Home Assistant "
      "offline; they prove nothing about a live Home Assistant, the dongle, or how a real interrupted write behaves.")
