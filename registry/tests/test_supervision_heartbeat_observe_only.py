#!/usr/bin/env python3
"""Offline tests for the HA supervision heartbeat - PR A, OBSERVE-ONLY
(2026-09-27). See docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md.

What this proves, offline only (no hardware, no ESPHome toolchain, no HA):

  [1] Centralized provisional timing constants exist and are ordered.
  [2] STATIC SAFETY: the heartbeat action, the evaluation tick, the on_boot
      initialisation and every new entity are RAM-only - no Modbus action,
      no durable commit/load, no script execution, no lease/fallback/restore
      call, no reboot-policy change - and the pre-existing firmware write
      surface, durable-commit surface, script set and Dump/Free Power limits
      are unchanged.
  [3] BEHAVIOUR: the REAL firmware lambdas (heartbeat action body, 1s tick,
      on_boot initialisation) executed through registry/tests/_dump_sim.py's
      C++-subset transpiler: STARTUP, SUPERVISED, SUSPECT, LOST, recovery,
      challenge single-use / replay / previous-boot rejection, counters,
      gap tracking, stability predicate, millis() wrap, HA restart, ESP
      reboot, heartbeat independent of inverter telemetry, and zero side
      effects on every non-supervision global, Modbus, NVS and scripts.
  [4] MUTATION (sensitivity) checks: deliberately broken in-memory copies of
      the firmware are detected by the behavioural scenarios above.
  [5] Home Assistant package: exactly one automation, exactly one service
      call (the dedicated heartbeat action), echoing the firmware challenge
      entity; deployment manifest lists it.

This does NOT prove behaviour on the real ESP32 or in a real Home Assistant
instance - only `esphome compile` plus a live soak can. PR A is observe-only
and NOT live-proven.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import jinja2
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _dump_sim as ds  # noqa: E402
import _scope_chain as chain  # noqa: E402 - FB-T0: the pre-existing-surface pins are evaluated as of chain entry "dump_v2"

ROOT = HERE.parents[1]
FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
HA_PKG = ROOT / "home-assistant" / "packages" / "ecco_supervision_heartbeat.yaml"
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FW_TEXT = FW_PATH.read_text(encoding="utf-8")
FW = ds.load_firmware_text(FW_TEXT)
SUBS = FW["_substitutions"]
# FB-T0: the PRE-EXISTING-surface pins (Modbus op counts, durable call-site counts, script set, pre-existing
# substitutions) are evaluated on the firmware AS OF chain entry "dump_v2" (main @ ca7474e): every LATER chain entry is
# undone by its exact-match reverter first (registry/tests/_scope_chain.py). A later PR's declared deltas (for example an
# `ecco_failback_shadow_*` substitution) therefore never loosen the "none added / removed" filter below and never need a
# re-hash here; any undeclared edit still breaks these pins. The supervision BEHAVIOUR and its forbidden-token checks
# keep using the LIVE firmware.
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_FW = ds.load_firmware_text(SCOPE_FW_TEXT)
SCOPE_SUBS = SCOPE_FW["_substitutions"]

STARTUP, SUPERVISED, SUSPECT, LOST = 0, 1, 2, 3
NAMES = {STARTUP: "STARTUP", SUPERVISED: "SUPERVISED", SUSPECT: "SUSPECT", LOST: "LOST"}


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------
def heartbeat_action(fw: dict) -> dict:
    hits = [a for a in fw["api"].get("actions", []) if a.get("action") == "ha_supervision_heartbeat"]
    assert len(hits) == 1, "expected exactly one ha_supervision_heartbeat action"
    return hits[0]


def heartbeat_lambda(fw: dict) -> str:
    then = heartbeat_action(fw)["then"]
    assert len(then) == 1 and set(then[0]) == {"lambda"}
    return then[0]["lambda"]


def tick_lambda(fw: dict) -> str:
    then = ds.find_interval(fw, "supervision_have_valid")
    assert len(then) == 1 and set(then[0]) == {"lambda"}
    return then[0]["lambda"]


def boot_lambdas(fw: dict) -> list:
    return [a["lambda"] for a in fw["esphome"]["on_boot"]["then"] if "lambda" in a]


def init_lambda(fw: dict) -> str:
    hits = [b for b in boot_lambdas(fw) if "random_uint32" in b]
    assert len(hits) == 1
    return hits[0]


def static_assert_lambda(fw: dict) -> str:
    hits = [b for b in boot_lambdas(fw) if "static_assert" in b and "supervision" in b]
    assert len(hits) == 1
    return hits[0]


def walk_keys(node, key):
    """Yields every value stored under `key` anywhere in a parsed tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from walk_keys(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from walk_keys(v, key)


def count_actions(node, name) -> int:
    return sum(1 for _ in walk_keys(node, name))


def new_entities(fw: dict) -> list:
    """Every sensor / text_sensor / binary_sensor entry added by PR A."""
    out = []
    for domain in ("sensor", "text_sensor", "binary_sensor"):
        for e in fw.get(domain, []):
            eid = str(e.get("id", ""))
            name = str(e.get("name", ""))
            if eid.startswith(("supervision_", "diag_", "api_client_connected")) or e.get("platform") == "debug":
                out.append((domain, e))
            elif "Supervision" in name:
                out.append((domain, e))
    return out


FORBIDDEN_IN_SUPERVISION_CODE = (
    "modbus_client", "write_multiple_registers", "read_holding_registers",
    "commit_record", "load_record", "make_preference", "global_preferences",
    "script.execute", ".execute(", ".stop(",
    "request_dump_end", "start_dump", "restore_dump", "dump_force", "dump_accept",
    "start_free_power", "restore_free_power", "free_power_recovery",
    "reg244", "apply_manual", "fallback", "failback",
    "turn_on", "turn_off", "press(",
    "reboot", "set_reboot_timeout", "safe_reboot", "App.",
    "global_api_server",
)


def assign_targets(code: str) -> set:
    return set(re.findall(r"id\((\w+)\)\s*(?:=(?!=)|\+=|-=|\|=|&=|\+\+|--)", code))


# ---------------------------------------------------------------------------
# Simulation harness around the REAL firmware lambdas
# ---------------------------------------------------------------------------
class Ref:
    """Stands in for ESPHome's StringRef action argument (`.str()`)."""

    def __init__(self, s: str):
        self.s = s

    def str(self):
        return ds.CStr(self.s)


class Harness:
    NONCE = 0x12345678

    def __init__(self, fw: dict = FW, nonce: int | None = None, boot_ms: int = 0):
        self.fw = fw
        self.sim = ds.Sim(fw)
        self.sim.now_ms = boot_ms
        self._tick = tick_lambda(fw)
        self._hb = heartbeat_lambda(fw)
        init = init_lambda(fw).replace("random_uint32()", f"{nonce if nonce is not None else self.NONCE}u")
        self.sim.run_lambda(init)

    # accessors
    def g(self, name):
        return self.sim.g[name]

    @property
    def state(self):
        return self.g("supervision_state")

    @property
    def challenge(self):
        return str(self.g("supervision_challenge"))

    def published(self, entity):
        return [str(v) for v in self.sim.ent(entity).published]

    # actions
    def tick(self):
        self.sim.run_lambda(self._tick)

    def heartbeat(self, challenge: str):
        self.sim.run_lambda(self._hb, {"challenge": Ref(challenge)}, params=("challenge",))

    def beat(self):
        self.heartbeat(self.challenge)

    def run(self, ms: int, beat_every_ms: int | None = None, step_ms: int = 1000):
        """Advance time in 1s ticks, sending a valid heartbeat every
        `beat_every_ms` (measured from the start of this call)."""
        elapsed = 0
        next_beat = beat_every_ms
        while elapsed < ms:
            self.sim.advance(step_ms)
            elapsed += step_ms
            if next_beat is not None and elapsed >= next_beat:
                self.beat()
                next_beat += beat_every_ms
            self.tick()


def other_globals(sim) -> dict:
    return {k: v for k, v in sim.g.items() if not k.startswith(("supervision_", "diag_"))}


SUSPECT_MS = int(SUBS["ecco_supervision_suspect_ms"])
LOST_MS = int(SUBS["ecco_supervision_lost_ms"])
MAX_GAP_MS = int(SUBS["ecco_supervision_stable_max_gap_ms"])
MIN_SPAN_MS = int(SUBS["ecco_supervision_stable_min_span_ms"])
MIN_BEATS = int(SUBS["ecco_supervision_stable_min_beats"])
PERIOD_MS = int(SUBS["ecco_supervision_heartbeat_period_s"]) * 1000


def main() -> int:
    # -----------------------------------------------------------------------
    print("[1] Centralized provisional timing constants")
    expected = {
        "ecco_supervision_heartbeat_period_s": "30",
        "ecco_supervision_suspect_ms": "90000",
        "ecco_supervision_lost_ms": "300000",
        "ecco_supervision_stable_min_beats": "3",
        "ecco_supervision_stable_max_gap_ms": "45000",
        "ecco_supervision_stable_min_span_ms": "55000",
    }
    for k, v in expected.items():
        check(f"substitution {k} = {v} (provisional; soak tunes it)", SUBS.get(k) == v, str(SUBS.get(k)))
    check("ordering: heartbeat period < stable max gap < SUSPECT < LOST",
          PERIOD_MS < MAX_GAP_MS < SUSPECT_MS < LOST_MS)
    check("a stable streak is reachable within the heartbeat cadence ((min_beats-1) * period >= min_span)",
          (MIN_BEATS - 1) * PERIOD_MS >= MIN_SPAN_MS)
    sa = static_assert_lambda(FW)
    check("on_boot static_assert pins stable_max_gap < suspect < lost and period < max_gap",
          "${ecco_supervision_stable_max_gap_ms}UL < ${ecco_supervision_suspect_ms}UL" in sa
          and "${ecco_supervision_suspect_ms}UL < ${ecco_supervision_lost_ms}UL" in sa
          and "${ecco_supervision_heartbeat_period_s}UL * 1000UL < ${ecco_supervision_stable_max_gap_ms}UL" in sa)
    hb_code, tick_code = heartbeat_lambda(FW), tick_lambda(FW)
    check("thresholds are referenced only through the substitutions (no hard-coded 90000/300000/45000/55000)",
          not re.search(r"\b(90000|300000|45000|55000)\b", hb_code + tick_code))

    # -----------------------------------------------------------------------
    print("")
    print("[2] Static safety: PR A has no inverter/control/reboot effect")
    action = heartbeat_action(FW)
    check("heartbeat action takes exactly one string variable, 'challenge'",
          action.get("variables") == {"challenge": "string"}, str(action.get("variables")))
    check("heartbeat action body is exactly one lambda (no script.execute / Modbus action nodes)",
          [list(a) for a in action["then"]] == [["lambda"]])
    supervision_code = {
        "heartbeat action": hb_code,
        "1s evaluation tick": tick_code,
        "on_boot initialisation": init_lambda(FW),
        "on_boot static_assert": static_assert_lambda(FW),
    }
    for label, code in supervision_code.items():
        bad = [t for t in FORBIDDEN_IN_SUPERVISION_CODE if t in code]
        check(f"{label}: contains none of the forbidden control/I-O tokens", not bad, str(bad))
        targets = assign_targets(code)
        check(f"{label}: assigns only supervision_* / diag_* globals",
              all(t.startswith(("supervision_", "diag_")) for t in targets), str(sorted(targets)))
    check("the evaluation tick only READS the inverter locks (never assigns them)",
          "manual_write_in_progress" in tick_code and "correction_in_progress" in tick_code
          and not ({"manual_write_in_progress", "correction_in_progress"} & assign_targets(tick_code)))
    iv = [i for i in FW["interval"] if "supervision_have_valid" in yaml.dump(i["then"])]
    check("the evaluation tick is its own 1s interval containing a single lambda",
          len(iv) == 1 and iv[0].get("interval") == "1s" and [list(a) for a in iv[0]["then"]] == [["lambda"]])

    ents = new_entities(FW)
    check("PR A adds the expected supervision / diagnostic entities", len(ents) >= 20, str(len(ents)))
    for domain, e in ents:
        blob = yaml.dump(e)
        bad = [t for t in FORBIDDEN_IN_SUPERVISION_CODE if t in blob and t != "global_api_server"]
        check(f"{domain} '{e.get('name') or e.get('platform')}' is read-only (no forbidden tokens, no assignments)",
              not bad and not assign_targets(blob) and "on_value" not in e and "on_press" not in e,
              str(bad))
    api_sensor = [e for d, e in ents if e.get("id") == "api_client_connected_sensor"]
    check("'ECCO API Client Connected' exists and is the ONLY place global_api_server is read",
          len(api_sensor) == 1 and FW_TEXT.count("global_api_server") == 2  # lambda: 2 references
          and "global_api_server" not in hb_code + tick_code)

    sup_globals = [g for g in FW["globals"] if str(g["id"]).startswith(("supervision_", "diag_"))]
    check("every supervision/diagnostic global is RAM-only (restore_value: no)",
          sup_globals and all(g.get("restore_value") in (False, "no") for g in sup_globals),
          str([g["id"] for g in sup_globals if g.get("restore_value") not in (False, "no")]))
    check("restore_value: yes globals are unchanged (exactly the 2 pre-existing reg244 drift guards)",
          sorted(g["id"] for g in FW["globals"] if g.get("restore_value") in (True, "yes"))
          == ["reg244_last_applied_valid", "reg244_last_applied_value"])

    # Pre-existing surfaces, pinned against their values on main @ 6c62417
    # (measured again for SG-01 Phase 0 after PR #44/#45/#46 all merged; the
    # numbers below did not move - only this provenance did).
    # SG-02 (fix/sg02-dump-lockout-containment) deliberately added ONE write
    # action (dump_lockout_containment's literal 244 = 2 - register 244 was
    # already in Dump's write surface) and THREE read actions (its fresh 244
    # read, its D5 256-261 evidence read and its exact 244 reread) - see
    # registry/tests/test_dump_lockout_containment_sg02.py. The supervision
    # code itself still adds none.
    check("firmware Modbus write actions: 52 as on main @ 6c62417 (51 @ 34a6547 + 1 SG-02 containment write)",
          count_actions(SCOPE_FW, ds.WRITE) == 52, str(count_actions(SCOPE_FW, ds.WRITE)))
    check("firmware Modbus read actions: 60 as on main @ 6c62417 (57 @ 34a6547 + 3 SG-02 containment reads)",
          count_actions(SCOPE_FW, ds.READ) == 60, str(count_actions(SCOPE_FW, ds.READ)))
    commit_calls = len(re.findall(r"ecco_durable::commit_record\s*\(", SCOPE_FW_TEXT))
    load_calls = len(re.findall(r"ecco_durable::load_record\s*\(", SCOPE_FW_TEXT))
    status_load_calls = len(re.findall(r"ecco_durable::load_record_status\s*\(", SCOPE_FW_TEXT))
    # SG-01 Phase 1/2 (START journal) added 5 commit_record call sites (the
    # B1..B4 journal commits before each START write + the best-effort
    # START_VERIFIED update) and 1 load_record call site (the on_boot journal
    # load) - see registry/tests/test_sg01_journal_phase1_2.py. SG-06 moved
    # the three on_boot MARKER loads from load_record to load_record_status
    # (same load, failure classified) - see
    # registry/tests/test_sg06_boot_durable_read_fail_closed.py. The
    # supervision code itself still adds none.
    check("durable commit_record call sites: 57 (50 as on main @ 6c62417 + 5 SG-01 START journal commits + Dump V2's "
          "controller evidence commit and START V1 tombstone)",
          commit_calls == 57, str(commit_calls))
    check("durable load call sites: 10 (8 as on main @ 6c62417 + 1 SG-01 boot journal load + 1 Dump V2 legacy-V1 "
          "probe) - 7 load_record + SG-06's 3 marker load_record_status",
          (load_calls, status_load_calls) == (7, 3), f"{load_calls}/{status_load_calls}")
    check("no new preference/NVS API used anywhere in PR A code",
          not any(t in "".join(supervision_code.values()) for t in ("make_preference", "global_preferences", "sync()")))
    script_ids = sorted(s["id"] for s in SCOPE_FW["script"])
    # SG-02 added exactly one script (dump_lockout_containment) after PR A.
    check("script set: 29 as of PR A + the SG-02 dump_lockout_containment script = 30",
          len(script_ids) == 30 and "dump_lockout_containment" in script_ids, str(len(script_ids)))
    # FB-B2 hardening: the ONE exception is the commit-time heartbeat re-check inside SAVE_FINAL part 2 of the Fallback dispatch (two reads,
    # one statement, right before the durable commit); every other script stays free of supervision logic.
    _sup_scripts = {s["id"]: yaml.dump(s).count("supervision") for s in FW["script"] if "supervision" in yaml.dump(s)}
    check("no supervision logic lives in a script (FB-B2: except the single commit-time re-check of fallback_profile_capture_dispatch)",
          _sup_scripts in ({}, {"fallback_profile_capture_dispatch": 2}), str(_sup_scripts))
    check("api: still has NO reboot_timeout (ESPHome default 15 min unchanged)", "reboot_timeout" not in FW["api"])
    check("wifi: still has NO reboot_timeout (ESPHome default 15 min unchanged)", "reboot_timeout" not in FW["wifi"])
    check("no on_client_connected / on_client_disconnected / api.connected hooks added",
          not any(k in FW["api"] for k in ("on_client_connected", "on_client_disconnected"))
          and "api.connected" not in FW_TEXT)
    check("no App.reboot / safe_reboot / set_reboot_timeout anywhere in the firmware",
          not re.search(r"App\.(safe_)?reboot|set_reboot_timeout", FW_TEXT))
    check("the pre-existing recovery API action is unchanged and still first",
          FW["api"]["actions"][0]["action"] == "free_power_recovery_execute"
          and FW["api"]["actions"][0]["variables"] == {"action": "string", "evidence_id": "string", "confirmation": "string"})
    # Dump / Free Power limits: every pre-existing substitution value pinned.
    limits = {
        "ecco_inverter_tou_power_ceiling_w": "8000",
        "ecco_free_power_invalid_clock_grace_ms": "300000",
        "ecco_dump_soc_stale_ms": "90000",
        "ecco_dump_cfg_stale_ms": "180000",
        "ecco_dump_runaway_margin_w": "750",
        "ecco_dump_runaway_samples": "3",
        "ecco_dump_runaway_grace_ms": "30000",
        "ecco_dump_runaway_transition_ms": "30000",
        "ecco_dump_runaway_absolute_margin_w": "750",
        "ecco_dump_runaway_absolute_samples": "2",
        "ecco_dump_accept_evidence_ms": "120000",
        "ecco_dump_grid_stale_ms": "90000",
        "ecco_dump_controller_deadband_w": "150",
        "ecco_dump_controller_gain": "0.5",
        "ecco_dump_controller_max_step_w": "1000",
        "ecco_dump_controller_max_ceiling_w": "3000",
        "ecco_dump_controller_settle_ms": "45000",
        "ecco_dump_controller_round_w": "100",
        "ecco_dump_controller_min_ceiling_w": "500",
        "ecco_dump_feedforward_max_start_ceiling_w": "2000",
        "ecco_dump_controller_response_samples": "3",
        "ecco_dump_controller_response_margin_w": "100",
        "ecco_dump_controller_wrong_direction_margin_w": "300",
        "ecco_dump_controller_max_writes_per_lease": "120",
        "ecco_dump_controller_recovery_hold_ms": "60000",
        "ecco_dump_controller_recovery_max_attempts": "1",
        "ecco_dump_feasibility_confirm_samples": "2",
        # SG-02 corrupt-lockout export containment per-boot bounds.
        "ecco_dump_containment_max_mismatches": "2",
        "ecco_dump_containment_max_writes": "3",
    }
    pre_existing = {k: v for k, v in SCOPE_SUBS.items() if not k.startswith("ecco_supervision_")}
    check("every pre-existing Dump/Free Power substitution is unchanged and none was added/removed",
          pre_existing == limits, str(set(pre_existing.items()) ^ set(limits.items())))
    numbers = {n["id"]: (n.get("min_value"), n.get("max_value")) for n in FW["number"]}
    check("Free Power / Dump staging number ranges unchanged",
          numbers.get("free_power_duration_minutes") == (1, 240)
          and numbers.get("free_power_max_power") == (500, "${ecco_inverter_tou_power_ceiling_w}")
          and numbers.get("dump_duration_minutes") == (1, 240), str({k: numbers.get(k) for k in (
              "free_power_duration_minutes", "free_power_max_power", "dump_duration_minutes")}))
    check("no new number/switch/select/button entity added by PR A",
          not any("upervision" in yaml.dump(e) for dom in ("number", "switch", "select", "button")
                  for e in FW.get(dom, [])))
    check("challenge entity is not disabled_by_default (the HA heartbeat reads it)",
          all(not e.get("disabled_by_default") for d, e in ents if e.get("id") == "supervision_challenge_text"))

    # -----------------------------------------------------------------------
    print("")
    print("[3] Behaviour - executing the REAL firmware lambdas")
    # 3.1 startup
    h = Harness()
    check("startup: state is STARTUP after on_boot initialisation", h.state == STARTUP)
    check("startup: 'ECCO Supervision State' published STARTUP (never SUPERVISED at boot)",
          h.published("supervision_state_text") == ["STARTUP"])
    check("startup: challenge is '<8-hex nonce>-1' and published", h.challenge == "12345678-1"
          and h.published("supervision_challenge_text") == ["12345678-1"], h.challenge)
    check("startup: no valid heartbeat recorded", not h.g("supervision_have_valid") and h.g("supervision_valid_count") == 0)
    h.run(LOST_MS - 1000)
    check("startup: stays STARTUP (not SUPERVISED) with API/Wi-Fi up but no heartbeat, until the LOST threshold",
          h.state == STARTUP)
    h.run(1000)
    check("startup: no valid heartbeat within the LOST threshold of uptime -> LOST", h.state == LOST)
    check("startup LOST counted once", h.g("supervision_lost_events") == 1 and h.g("supervision_suspect_events") == 0)
    h.run(10 * 60 * 1000)
    check("API connected but no heartbeat -> remains LOST (the tick never upgrades)", h.state == LOST
          and h.g("supervision_lost_events") == 1)

    # 3.2 valid heartbeat establishes SUPERVISED
    h = Harness(boot_ms=0)
    h.run(8000)
    first = h.challenge
    h.beat()
    check("valid heartbeat establishes SUPERVISED", h.state == SUPERVISED)
    check("valid heartbeat publishes SUPERVISED once", h.published("supervision_state_text")[-1] == "SUPERVISED")
    check("valid heartbeat counted", h.g("supervision_valid_count") == 1 and h.g("supervision_invalid_count") == 0)
    check("first heartbeat after boot recorded (8s)", h.g("supervision_first_valid_ms") == 8000)
    check("challenge consumed and rotated to generation 2", h.challenge == "12345678-2"
          and str(h.g("supervision_previous_challenge")) == first)
    check("rotated challenge published for Home Assistant", h.published("supervision_challenge_text")[-1] == "12345678-2")
    check("a single heartbeat is NOT yet 'Supervision Stable'", not h.g("supervision_stable"))

    # 3.3 repeated valid heartbeats maintain SUPERVISED; stability predicate
    h.run(PERIOD_MS, beat_every_ms=PERIOD_MS)
    check("two beats 30s apart: still not stable (span < min_span)", h.state == SUPERVISED and not h.g("supervision_stable"))
    h.run(PERIOD_MS, beat_every_ms=PERIOD_MS)
    check("three beats spanning 60s: Supervision Stable", h.g("supervision_stable")
          and h.g("supervision_consecutive_beats") == 3)
    h.run(3600 * 1000, beat_every_ms=PERIOD_MS)
    check("one hour of 30s heartbeats: stays SUPERVISED and Stable, no SUSPECT/LOST events",
          h.state == SUPERVISED and h.g("supervision_stable")
          and h.g("supervision_suspect_events") == 0 and h.g("supervision_lost_events") == 0)
    check("valid count = 1 + 2 + 120", h.g("supervision_valid_count") == 123, str(h.g("supervision_valid_count")))
    check("last and longest gap are 30s under a steady cadence",
          h.g("supervision_last_gap_ms") == 30000 and h.g("supervision_longest_gap_ms") == 30000)
    check("heartbeats never touched the invalid counter", h.g("supervision_invalid_count") == 0)

    # 3.4 invalid challenges do not refresh supervision
    h = Harness()
    h.run(5000)
    h.beat()
    last_ok = h.g("supervision_last_valid_ms")
    consumed = str(h.g("supervision_previous_challenge"))
    current = h.challenge
    h.run(20000)
    cases = [("", "EMPTY CHALLENGE"), ("garbage", "WRONG CHALLENGE"), (consumed, "STALE CHALLENGE (already consumed)"),
             ("87654321-2", "WRONG CHALLENGE"), ("12345678-99", "WRONG CHALLENGE"), (current + " ", "WRONG CHALLENGE"),
             (current.lower() if current.lower() != current else "abcdef01-2", "WRONG CHALLENGE")]
    for i, (value, reason) in enumerate(cases, start=1):
        h.heartbeat(value)
        check(f"invalid heartbeat {value!r}: rejected as {reason}", str(h.g("supervision_last_invalid_reason")) == reason,
              str(h.g("supervision_last_invalid_reason")))
        check(f"invalid heartbeat {value!r}: timestamp/challenge/valid count unchanged",
              h.g("supervision_last_valid_ms") == last_ok and h.challenge == current
              and h.g("supervision_valid_count") == 1 and h.g("supervision_invalid_count") == i)
    check("invalid reasons published on their own diagnostic entity",
          h.published("supervision_invalid_reason_text")[-1] == "WRONG CHALLENGE")

    # 3.5 SUSPECT and LOST thresholds; recovery
    h = Harness()
    h.beat()
    t0 = h.g("supervision_last_valid_ms")
    h.run(SUSPECT_MS - 1000)
    check("no SUSPECT before the SUSPECT threshold", h.state == SUPERVISED)
    h.run(1000)
    check("SUSPECT exactly at the SUSPECT threshold", h.state == SUSPECT
          and h.sim.millis() - t0 == SUSPECT_MS and h.g("supervision_suspect_events") == 1)
    check("SUSPECT published", h.published("supervision_state_text")[-1] == "SUSPECT")
    check("'Supervision Stable' is false in SUSPECT", not h.g("supervision_stable"))
    h.run(LOST_MS - SUSPECT_MS - 1000)
    check("still SUSPECT just before the LOST threshold", h.state == SUSPECT)
    h.run(1000)
    check("LOST exactly at the LOST threshold", h.state == LOST and h.g("supervision_lost_events") == 1)
    check("LOST published", h.published("supervision_state_text")[-1] == "LOST")
    h.run(20 * 60 * 1000)
    check("LOST persists without heartbeats (no other upgrade path)", h.state == LOST and h.g("supervision_lost_events") == 1)
    h.beat()
    check("later valid heartbeat returns LOST -> SUPERVISED (observational)", h.state == SUPERVISED)
    check("...but not Stable: a new streak must be built after an outage", not h.g("supervision_stable")
          and h.g("supervision_consecutive_beats") == 1)
    check("the outage is recorded as the last and longest gap (~25.5 min)",
          h.g("supervision_last_gap_ms") == h.g("supervision_longest_gap_ms") == LOST_MS + 20 * 60 * 1000)
    h.run(2 * PERIOD_MS, beat_every_ms=PERIOD_MS)
    check("Stable again after 3 consecutive beats spanning >= 55s", h.g("supervision_stable"))

    # 3.6 SUSPECT -> SUPERVISED on a late but valid beat; stability drop on a late beat
    h = Harness()
    h.beat()
    h.run(2 * PERIOD_MS, beat_every_ms=PERIOD_MS)
    check("stable before the late-beat scenario", h.g("supervision_stable"))
    h.run(MAX_GAP_MS + 1000)
    check("a beat later than the stable max gap clears 'Stable' while still SUPERVISED",
          h.state == SUPERVISED and not h.g("supervision_stable"))
    h.run(SUSPECT_MS - MAX_GAP_MS)
    check("then SUSPECT", h.state == SUSPECT)
    h.beat()
    check("valid heartbeat from SUSPECT -> SUPERVISED, streak reset (gap > max gap)", h.state == SUPERVISED
          and h.g("supervision_consecutive_beats") == 1 and not h.g("supervision_stable"))
    check("event counters: 1 SUSPECT, 0 LOST", h.g("supervision_suspect_events") == 1 and h.g("supervision_lost_events") == 0)

    # 3.7 longest gap tracks the maximum closed gap only
    h = Harness()
    h.beat()
    for gap in (30000, 70000, 30000, 45000, 12000):
        h.run(gap)
        h.beat()
    check("last gap = most recent inter-beat gap", h.g("supervision_last_gap_ms") == 12000)
    check("longest gap = maximum closed gap", h.g("supervision_longest_gap_ms") == 70000)

    # 3.8 millis() wrap / long runtime
    wrap_start = (1 << 32) - 45_000
    h = Harness(boot_ms=wrap_start)
    h.sim.g["supervision_state"] = STARTUP  # boot state at an arbitrary millis() origin
    h.beat()
    h.run(10 * PERIOD_MS, beat_every_ms=PERIOD_MS)
    check("heartbeats across the 32-bit millis() wrap: stays SUPERVISED, no spurious SUSPECT/LOST",
          h.state == SUPERVISED and h.g("supervision_suspect_events") == 0 and h.g("supervision_lost_events") == 0)
    check("gap arithmetic is correct across the wrap (30s)", h.g("supervision_longest_gap_ms") == 30000)
    check("stability survives the wrap", h.g("supervision_stable"))
    h.run(LOST_MS + 5000)
    check("LOST after the wrap as normal", h.state == LOST)
    h.sim.advance((1 << 32) - LOST_MS - 5000)  # ~49.7 days later the unsigned age looks tiny again
    h.tick()
    check("LOST is sticky across a full millis() period (stale supervision never looks fresh)", h.state == LOST)
    h = Harness(boot_ms=0)
    h.run(LOST_MS)  # no heartbeat ever since boot: LOST at LOST_MS of uptime
    check("never-supervised boot reaches LOST at the LOST threshold of uptime", h.state == LOST)
    h.sim.advance((1 << 32) - LOST_MS + 1000)  # millis() wraps: uptime-since-boot looks small again
    h.tick()
    check("never-supervised LOST is sticky across the millis() wrap (never falls back to STARTUP)",
          h.state == LOST and h.g("supervision_lost_events") == 1)

    # 3.9 HA restart simulation (short and long)
    h = Harness()
    h.run(3 * PERIOD_MS, beat_every_ms=PERIOD_MS)
    challenge_before = h.challenge
    h.run(120_000)  # HA Core restart: no heartbeats for 2 minutes
    check("2-minute HA restart: SUSPECT, not LOST", h.state == SUSPECT)
    check("challenge is unchanged while HA is away (nothing consumed it)", h.challenge == challenge_before)
    h.beat()  # HA reconnects, reads the (replayed) current challenge state, echoes it
    check("after HA restart the current challenge is accepted -> SUPERVISED", h.state == SUPERVISED)
    h.run(6 * 60 * 1000)  # longer restart / host reboot
    check("6-minute outage: LOST", h.state == LOST)
    h.beat()
    check("recovers to SUPERVISED on the first valid beat after the outage", h.state == SUPERVISED)

    # 3.10 heartbeat interruption mid-stream and recovery gap recording
    h = Harness()
    h.run(5 * PERIOD_MS, beat_every_ms=PERIOD_MS)
    h.run(100_000)
    check("interruption of 100s: SUSPECT", h.state == SUSPECT)
    h.run(3 * PERIOD_MS, beat_every_ms=PERIOD_MS)
    check("resumed heartbeats: SUPERVISED and Stable again", h.state == SUPERVISED and h.g("supervision_stable"))
    check("the interruption is the longest gap (130s)", h.g("supervision_longest_gap_ms") == 130_000,
          str(h.g("supervision_longest_gap_ms")))

    # 3.11 ESP reboot: new nonce invalidates the previous boot's challenges
    h1 = Harness(nonce=0x11111111)
    old = h1.challenge
    h2 = Harness(nonce=0x22222222)
    h2.heartbeat(old)
    check("after an ESP reboot, the previous boot's challenge is rejected", h2.state == STARTUP
          and h2.g("supervision_invalid_count") == 1 and not h2.g("supervision_have_valid"))
    h2.beat()
    check("...and the new boot's challenge is accepted", h2.state == SUPERVISED)

    # 3.12 heartbeat independent of inverter telemetry / clock
    h = Harness()
    h.sim.ent("telemetry_online").set(False)
    h.sim.ent("configuration_online").set(False)
    h.sim.ntp_valid = False
    h.sim.g["manual_write_in_progress"] = True
    h.sim.g["correction_in_progress"] = True
    h.beat()
    check("valid heartbeat accepted with telemetry/config offline, NTP invalid and both inverter locks held",
          h.state == SUPERVISED and h.g("supervision_valid_count") == 1)
    check("clock invalid -> last-valid wall time recorded as 0 (uptime shown instead)", h.g("supervision_last_valid_epoch") == 0)
    h.sim.ntp_valid = True
    h.run(PERIOD_MS)
    h.beat()
    check("clock valid -> last-valid wall time recorded", h.g("supervision_last_valid_epoch") == h.sim.epoch)

    # 3.13 lock-age diagnostics are read-only samples
    h = Harness()
    h.tick()
    check("lock diagnostics idle at boot", not h.g("diag_write_lock_held") and h.g("diag_write_lock_max_ms") == 0)
    h.sim.g["manual_write_in_progress"] = True
    h.tick()
    h.run(12_000)
    check("write-lock hold age sampled (12s)", h.g("diag_write_lock_held") and h.g("diag_write_lock_max_ms") == 12_000)
    check("the tick never releases or takes the lock itself", h.g("manual_write_in_progress") is True)
    h.sim.g["manual_write_in_progress"] = False
    h.run(3000)
    check("release observed; max age retained", not h.g("diag_write_lock_held") and h.g("diag_write_lock_max_ms") == 12_000)
    h.sim.g["correction_in_progress"] = True
    h.tick()
    h.run(400_000)
    check("RTC correction lock leak would be visible (>= 400s)", h.g("diag_correction_lock_max_ms") == 400_000
          and h.g("correction_in_progress") is True)

    # 3.14 zero side effects on everything else
    h = Harness()
    before = other_globals(h.sim)
    h.run(LOST_MS + 60_000)
    for v in ("", "bogus", h.challenge):
        h.heartbeat(v)
    h.run(10 * 60 * 1000, beat_every_ms=PERIOD_MS)
    h.run(LOST_MS + 1000)
    h.beat()
    after = other_globals(h.sim)
    check("every non-supervision global (Free Power, Dump, reg244, RTC, locks, polling) is untouched",
          before == after, str({k for k in before if before[k] != after.get(k)}))
    check("no Modbus operation was issued", h.sim.modbus_log == [])
    check("no NVS commit was made", h.sim.nvs_commits == [] and h.sim.nvs == {})
    check("no script was executed", h.sim.executed == [])
    touched = {name for name, ent in h.sim.entities.items() if ent.published}
    check("only supervision text entities were published",
          touched <= {"supervision_state_text", "supervision_challenge_text", "supervision_invalid_reason_text"},
          str(sorted(touched)))
    accessed = set(h.sim.entities)
    check("the supervision lambdas access no entity except their own text sensors and the clock "
          "(no switch, button, number, lease or Modbus entity is even referenced)",
          accessed <= {"ntp_time", "supervision_state_text", "supervision_challenge_text",
                       "supervision_invalid_reason_text"}, str(sorted(accessed)))

    # -----------------------------------------------------------------------
    print("")
    print("[4] Mutation (sensitivity) checks against broken firmware copies")

    def mutant(old: str, new: str) -> dict:
        assert FW_TEXT.count(old) == 1, f"mutation anchor not unique/present: {old!r}"
        return ds.load_firmware_text(FW_TEXT.replace(old, new))

    def scenario_rejects_wrong(fw) -> bool:
        m = Harness(fw)
        m.heartbeat("garbage")
        return m.state == STARTUP and m.g("supervision_valid_count") == 0

    def scenario_rejects_replay(fw) -> bool:
        m = Harness(fw)
        c = m.challenge
        m.heartbeat(c)
        m.heartbeat(c)
        return m.g("supervision_valid_count") == 1

    def scenario_suspect_then_lost(fw) -> bool:
        m = Harness(fw)
        m.beat()
        m.run(SUSPECT_MS)
        s = m.state == SUSPECT
        m.run(LOST_MS - SUSPECT_MS)
        return s and m.state == LOST

    def scenario_lost_sticky(fw) -> bool:
        m = Harness(fw)
        m.beat()
        m.run(LOST_MS)
        m.sim.advance((1 << 32) - LOST_MS)
        m.tick()
        return m.state == LOST

    def scenario_startup_not_supervised(fw) -> bool:
        m = Harness(fw)
        m.run(60_000)
        return m.state == STARTUP

    mutations = [
        ("accept any non-empty challenge", "received.empty() || received != id(supervision_challenge)",
         "received.empty()", scenario_rejects_wrong),
        ("challenge not consumed (replay accepted)", "            id(supervision_generation) += 1;\n            char next_challenge",
         "            char next_challenge", scenario_rejects_replay),
        ("no SUSPECT stage", "              next = 2;", "              next = 1;", scenario_suspect_then_lost),
        ("tick upgrades from stale age", "          uint8_t next = prev;",
         "          uint8_t next = id(supervision_have_valid) ? 1 : prev;", scenario_lost_sticky),
        ("boot claims SUPERVISED", "          id(supervision_state) = 0;\n", "          id(supervision_state) = 1;\n",
         scenario_startup_not_supervised),
    ]
    for label, old, new, scenario in mutations:
        check(f"real firmware passes scenario for: {label}", scenario(FW))
        try:
            detected = not scenario(mutant(old, new))
        except ds.Unsupported as exc:
            detected = False
            print(f"        (mutant unsupported: {exc})")
        check(f"mutant detected: {label}", detected)

    # -----------------------------------------------------------------------
    print("")
    print("[5] Home Assistant heartbeat package")
    pkg_text = HA_PKG.read_text(encoding="utf-8")
    pkg = yaml.safe_load(pkg_text)
    check("package defines only automation:", set(pkg) == {"automation"}, str(set(pkg)))
    autos = pkg["automation"]
    check("exactly one automation", len(autos) == 1)
    a = autos[0]
    check("mode single, max_exceeded silent", a.get("mode") == "single" and a.get("max_exceeded") == "silent")
    check("triggered every 30 seconds by time_pattern",
          a.get("triggers") == [{"trigger": "time_pattern", "seconds": "/30"}], str(a.get("triggers")))
    check("time_pattern cadence matches the firmware's documented heartbeat period",
          int(a["triggers"][0]["seconds"].lstrip("/")) * 1000 == PERIOD_MS)
    services = re.findall(r"action:\s*([a-z_]+\.[a-z0-9_]+)", pkg_text)
    check("exactly ONE service call in the whole package: the dedicated heartbeat action",
          services == ["esphome.ecco_clock_dongle_ha_supervision_heartbeat"], str(services))
    act = a["actions"]
    check("single action step, continue_on_error: true",
          len(act) == 1 and act[0].get("continue_on_error") is True)
    check("HA action name matches the firmware node name + action name",
          act[0]["action"] == "esphome." + FW["esphome"]["name"].replace("-", "_") + "_"
          + heartbeat_action(FW)["action"])
    challenge_entity = "sensor.ecco_clock_dongle_ecco_supervision_challenge"
    check("echoes the firmware challenge entity as the only data field",
          act[0].get("data") == {"challenge": "{{ states('" + challenge_entity + "') }}"}, str(act[0].get("data")))
    fw_names = [e.get("name") for e in FW["text_sensor"] if e.get("id") == "supervision_challenge_text"]
    check("challenge entity id matches the firmware text sensor name 'ECCO Supervision Challenge'",
          fw_names == ["ECCO Supervision Challenge"]
          and challenge_entity.endswith("_" + re.sub(r"[^a-z0-9]+", "_", fw_names[0].lower())))
    check("the only firmware entity referenced is the challenge sensor",
          set(re.findall(r"\b(?:sensor|binary_sensor|switch|button|number|select)\.ecco_clock_dongle_\w+", pkg_text))
          == {challenge_entity})
    lowered = yaml.dump(pkg).lower()  # parsed content only - header comments document what is absent
    forbidden_ha = ("button.", "switch.", "number.", "select.", "modbus", "write_register", "homeassistant.restart",
                    "free_power", "dump_to_grid", "restore", "force_restore" + "_original", "accept" + "_current_state",
                    "fallback_profile_execute", "script.")
    check("no control/restore/lease/fallback service or entity in the package",
          not [t for t in forbidden_ha if t in lowered], str([t for t in forbidden_ha if t in lowered]))
    env = jinja2.Environment()
    cond = a["conditions"][0]["value_template"]
    for value, expect in (("unknown", False), ("unavailable", False), ("", False), ("none", False),
                          ("12345678-1", True)):
        rendered = env.from_string(cond).render(states=lambda eid, v=value: v).strip()
        check(f"condition with challenge state {value!r} -> {expect}", (rendered == "True") == expect, rendered)
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    entries = [p for p in manifest["home_assistant_packages"] if p["source"].endswith("ecco_supervision_heartbeat.yaml")]
    check("deployment manifest lists the heartbeat package once",
          len(entries) == 1 and entries[0]["destination"] == "/config/packages/ecco_supervision_heartbeat.yaml")

    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All supervision heartbeat (observe-only) checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
