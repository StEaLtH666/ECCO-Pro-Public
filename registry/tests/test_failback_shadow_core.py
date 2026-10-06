#!/usr/bin/env python3
"""Offline tests for FB-C1 - Failback Shadow instrumentation (RAM-only,
zero-authority). Architecture: docs/architecture/fallback/
FINAL_FBB_FBC_ARCHITECTURE.md section 6 / 11 / 12 and design/S3_fbc_core_final.md.

FB-C1 adds ONE 1s interval (static_asserts lambda + tick lambda) immediately
before the PR-A supervision tick, 42 `failback_shadow_*` RAM globals, five
diagnostic text sensors and five `ecco_failback_shadow_*` substitutions. It
observes HA supervision and publishes; it has no authority: no Modbus, no NVS,
no RTC memory, no script, no control, no API action, and nothing else in the
YAML may reference it.

What this proves, offline only (no hardware, no ESPHome toolchain, no HA):

  [0] CHANGE SCOPE: FB-C1 is a pure insertion of four blocks
      (_fbc_scope.py); reverting exactly those blocks reproduces the chain's
      dump_v2 checkpoint (main @ be143cd's firmware) byte-for-byte; every
      other part of the parsed firmware is identical (no script/button/
      switch/number/select/binary_sensor/api action/on_boot/header change).
  [S] FB-T0 REGISTRATION: chain entry `fbc1` declares exactly FB-C1's
      reverter, checkpoint, deltas, five substitution key -> value pairs and
      14 banned-token occurrences; the zero Modbus / durable / op-path delta
      is measured; mis-declarations are refused (no prefix exemption).
  [1] Substitutions, the static_assert chain and the reboot-policy coupling.
  [Z] STATIC PINS Z1-Z8 (write surface, placement and shape, token ban,
      assignment allowlist, non-authority, RAM-only globals, durable surface,
      no controls).
  [T] BEHAVIOUR T-C01..T-C19, T-C22, T-C23, T-C30 and Z9: the REAL firmware
      lambdas (PR-A heartbeat, PR-A tick, PR-A init, FB-C tick) executed
      through registry/tests/_dump_sim.py with registry/tests/_fbc_harness.py
      (millis_64, two independently scheduled 1s intervals with random phase
      and order control, an api_client_connected model). EVERY FB-C
      invocation is checked for zero side effects (Z9/T-C22).
  [Z11] every string FB-C can publish is <= 200 chars and matches none of the
      Energy Actions card's regex literals (imported from the TypeScript).
  [H] harness self-tests.
  [Z12] MUTATION kill matrix: deliberately broken in-memory copies of the
      firmware are each caught by the detector aimed at them.

FB-T0 CHAIN (registry/tests/_scope_chain.py)
--------------------------------------------
FB-C1 is chain entry `fbc1`. The older suites are NOT edited: each is anchored
at its own entry and reverts fbc1 through the chain. This suite is anchored at
`fbc1` in the same way: the firmware and the chain-pinned headers it checks are
read AS OF fbc1 (every later entry's declared edits reverted exactly), so a
later PR never edits it, while an undeclared edit still breaks it.

This does NOT prove behaviour on the real ESP32, ESPHome scheduling, or that
the firmware compiles - only `esphome compile` and the LP-C1 soak can.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _dump_sim as ds  # noqa: E402
import _fbc_harness as hx  # noqa: E402
import _fbc_scope as scope  # noqa: E402
import _free_power_action_sim as fpas  # noqa: E402
import _scope_chain as chain  # noqa: E402
import analyze_write_surface as aws  # noqa: E402

FW_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
CARD_SRC = ROOT / "frontend" / "ecco-energy-actions-card" / "src"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _raises(fn, exc=AssertionError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


# FB-T0: anchored at chain entry fbc1 (see the module docstring).
CH = chain.CHAIN
LIVE_FW_TEXT = FW_PATH.read_text(encoding="utf-8")
AS_OF = CH.as_of_all("fbc1")                  # every chain-pinned artifact as of fbc1
FW_TEXT = AS_OF[chain.FIRMWARE]
HEADERS = chain._headers_of(AS_OF)           # the esphome.includes headers as of fbc1, for the analyzer
FW = ds.load_firmware_text(FW_TEXT)
# The five substitutions FB-C1 adds, written out independently of _fbc_scope / the chain entry ([S] checks all three agree).
FBC1_SUBSTITUTIONS = {
    "ecco_failback_shadow_episode_close_ms": "300000",
    "ecco_failback_shadow_start_max_ms": "30000",
    "ecco_failback_shadow_assumed_reboot_timeout_ms": "900000",
    "ecco_failback_shadow_publish_min_ms": "10000",
    "ecco_failback_shadow_soak_publish_min_ms": "60000",
}
SUBS = FW["_substitutions"]
BASE_TEXT = None  # set in section [0] (needs the revert)
BASE = None

FBC_TEXT_IDS = hx.FBC_TEXT_IDS
LOST_MS = int(SUBS["ecco_supervision_lost_ms"])
SUSPECT_MS = int(SUBS["ecco_supervision_suspect_ms"])
MAX_GAP_MS = int(SUBS["ecco_supervision_stable_max_gap_ms"])
MIN_SPAN_MS = int(SUBS["ecco_supervision_stable_min_span_ms"])
CLOSE_MS = int(SUBS["ecco_failback_shadow_episode_close_ms"])
ASSUMED_MS = int(SUBS["ecco_failback_shadow_assumed_reboot_timeout_ms"])
PUB_MS = int(SUBS["ecco_failback_shadow_publish_min_ms"])
SOAK_PUB_MS = int(SUBS["ecco_failback_shadow_soak_publish_min_ms"])
WRAP = 1 << 32

# Harness bookkeeping: every harness built for the REAL firmware is kept so
# T-C22 (Z9 over the whole matrix) and Z11 (every published string) can
# aggregate over it. Mutant runs use a scratch list.
ALL_H: list = []
_SINK = [ALL_H]


def mk(fw: dict, **kw) -> hx.Harness:
    h = hx.Harness(fw, **kw)
    _SINK[0].append(h)
    return h


class Exp:
    """Accumulates the failed expectations of one scenario."""

    def __init__(self):
        self.fails: list[str] = []
        self.n = 0

    def ok(self, cond, msg: str):
        self.n += 1
        if not cond:
            self.fails.append(msg)

    def eq(self, got, want, msg: str):
        self.n += 1
        if got != want:
            self.fails.append(f"{msg}: got {got!r}, want {want!r}")

    def near(self, got, want, tol, msg: str):
        self.n += 1
        if abs(got - want) > tol:
            self.fails.append(f"{msg}: got {got!r}, want {want!r} +/- {tol}")

    def z9(self, *hs):
        for h in hs:
            self.n += 1
            if h.violations:
                self.fails.append(f"Z9 violation(s): {h.violations[:3]}")


def sim_text(h, ent):
    return h.text(ent)


# ===========================================================================
# Static helpers
# ===========================================================================
class Ctx:
    """One firmware text, parsed, with the FB-C interval and its lambdas."""

    def __init__(self, text: str):
        self.text = text
        self.fw = ds.load_firmware_text(text)
        self.iv = hx.fbc_interval(self.fw)
        self.lam0, self.lam1 = hx.fbc_lambdas(self.fw)


def assign_targets(code: str) -> set:
    return set(re.findall(r"id\((\w+)\)\s*(?:=(?!=)|\+=|-=|\|=|&=|\+\+|--)", code))


def walk_keys(node, key):
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


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def tree(fw: dict) -> dict:
    return {k: v for k, v in fw.items() if k != "_text"}


def pra_tick_index(fw: dict) -> int:
    hits = [i for i, iv in enumerate(fw["interval"]) if "supervision_have_valid" in yaml.dump(iv["then"])]
    assert len(hits) == 1, f"PR-A tick mentions found {len(hits)} times"
    return hits[0]


# Names FB-C lambda 1 may READ (architecture S3 section 11.3, FB-C1 subset).
READ_ALLOWLIST = {
    "supervision_state", "supervision_stable", "supervision_valid_count", "supervision_last_valid_ms",
    "supervision_last_gap_ms", "supervision_first_valid_ms", "supervision_lost_events",
    "supervision_generation", "supervision_boot_nonce",
    "api_client_connected_sensor", "ntp_synced", "ntp_time",
    "free_power_operation_in_progress", "free_power_snapshot_valid",
    "dump_operation_in_progress", "dump_snapshot_valid",
    "reg244_apply_in_progress", "reg244_snapshot_valid",
}

# Architecture S3 section 10, pin Z3 (+ master section 6.8's `App.` / reboot).
Z3_TOKENS = (
    "modbus_client", "write_multiple_registers", "read_holding_registers", "inverter_modbus",
    "inverter_uart", "commit_record", "load_record", "nvs_", "make_preference", "global_preferences",
    ".save(", "sync(", "RTC_NOINIT", "RTC_DATA_ATTR", "esp_attr", "script.execute", ".execute(", ".stop(",
    "request_", "turn_on", "turn_off", "press(", "set_value", "make_call", "perform(", "set_option",
    "set_level", "App.", "safe_reboot", "set_reboot_timeout", "esp_restart", "arch_restart",
    "esp_reset_reason", "global_api_server", "self_partial", "fallback_profile_execute",
    "free_power_recovery_execute", "delay", "wait_until",
)

# restore_value: yes set on main (PR-A pin).
RESTORE_YES = ["reg244_last_applied_valid", "reg244_last_applied_value"]

# Every `*_TAG` identifier defined in the firmware headers on main @ be143cd (unchanged by FB-C1).
HEADER_TAGS = {
    "ecco_durable_snapshot.h": ["DUMP_TO_GRID_DATA_TAG", "DUMP_TO_GRID_RETRY_TAG", "DUMP_TO_GRID_VALID_TAG",
                                "FREE_POWER_DATA_TAG", "FREE_POWER_RETRY_TAG", "FREE_POWER_START_JOURNAL_TAG",
                                "FREE_POWER_VALID_TAG", "REG244_DATA_TAG", "REG244_VALID_TAG"],
    "ecco_fallback_profile.h": ["FAILBACK_STATE_TAG", "FALLBACK_PROFILE_TAG"],
    "ecco_recovery_evidence.h": ["FINGERPRINT_DOMAIN_TAG"],
}
# The two chain-pinned headers as of fbc1; the FB-A header is not chain-pinned (its content is pinned by FB-A's own suite).
HEADER_TEXTS = {
    "ecco_durable_snapshot.h": AS_OF[chain.DURABLE_HEADER],
    "ecco_recovery_evidence.h": AS_OF[chain.EVIDENCE_HEADER],
    "ecco_fallback_profile.h": (ROOT / "firmware" / "include" / "ecco_fallback_profile.h").read_text(encoding="utf-8"),
}

# The State strings of architecture S3 section 3.7 that exist in FB-C1 (SHADOW_WOULD_AWAIT_ACK is FB-C2). SHADOW_BOOT is
# listed for the card-regex check only: the tick returns before publishing while supervision_generation == 0, and ESPHome
# runs every interval only after on_boot has set it to 1, so FB-C1 never publishes it (the entity is simply unknown until the
# first tick). T-C18 pins that nothing is published while not ready.
STATE_STRINGS = ["SHADOW_BOOT", "SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WATCH", "SHADOW_IDLE"]


# ===========================================================================
# Static detectors (each returns a list of violations; [] = pass)
# ===========================================================================
def z0_scope(c: Ctx) -> list[str]:
    out = []
    base_text = scope.pre_fbc1_text(c.text)
    if scope.sha(base_text) != scope.BASE_FW_SHA:
        out.append("reverting FB-C1's blocks does not reproduce main @ b3fcdfc")
    if scope.add_fbc1_text(base_text) != c.text:
        out.append("FB-C1 is not exactly the four scope blocks at their anchors")
    return out


def z1_write_surface(c: Ctx) -> list[str]:
    out = []
    base_text = scope.pre_fbc1_text(c.text)
    # the analyser resolves includes next to the file: the chain materialises the headers as of fbc1 there
    rb, rf = chain.analyze_text(base_text, HEADERS), chain.analyze_text(c.text, HEADERS)

    def ops(r):
        return sorted((p.name, p.kind, tuple((o.kind, o.start_address, o.count) for o in p.ops)) for p in r["paths"])

    def surf(r):
        return {k: sorted(v) for k, v in aws.write_surface(r["paths"]).items()}

    if ops(rb) != ops(rf):
        out.append("per-path op lists changed")
    if surf(rb) != surf(rf):
        out.append("register -> writers map changed")
    if rf["bus_access_findings"] != []:
        out.append(f"bus access findings: {rf['bus_access_findings']}")
    if rf["unknown_extent_writes"] != rb["unknown_extent_writes"]:
        out.append("unknown-extent writes changed")
    w, r = count_actions(c.fw, ds.WRITE), count_actions(c.fw, ds.READ)
    if (w, r) != (52, 60):
        out.append(f"Modbus actions {w}/{r}, want 52/60 (FB-C1 delta must be 0/0)")
    return out


def z2_placement(c: Ctx) -> list[str]:
    out = []
    iv = c.iv
    if iv.get("interval") != "1s":
        out.append(f"interval {iv.get('interval')!r}, want 1s")
    if [list(a) for a in iv["then"]] != [["lambda"], ["lambda"]]:
        out.append("then: is not exactly [lambda, lambda]")
    if "startup_delay" in iv:
        out.append("startup_delay present (the readiness gate replaces it)")
    if not re.match(r"^(\s*static_assert\([^;]*\);\s*)+$", strip_comments(c.lam0)):
        out.append("lambda 0 is not static_asserts only")
    ivs = c.fw["interval"]
    n_fb = [i for i in ivs if "failback_shadow" in yaml.dump(i)]
    if len(n_fb) != 1:
        out.append(f"{len(n_fb)} intervals mention failback_shadow, want exactly 1")
    idx = ivs.index(iv)
    try:
        pra = pra_tick_index(c.fw)
    except AssertionError as e:
        return out + [str(e)]
    if idx != pra - 1:
        out.append(f"FB-C interval index {idx}, PR-A tick index {pra}: must be immediately before it")
    if idx == len(ivs) - 1:
        out.append("FB-C interval is at EOF")
    # The interval just before FB-C is FB-B's housekeeping slot; FB-B does not exist yet, so it is the
    # Free Power evidence-expiry interval (S6 X-12: FP expiry -> FB-B housekeeping -> FB-C -> PR-A tick).
    if idx == 0 or "free_power_recovery_evidence_valid" not in yaml.dump(ivs[idx - 1]["then"]):
        out.append("the interval before FB-C is not the Free Power evidence-expiry interval")
    l1 = c.lam1
    for pin in (
        "stable_for >= ${ecco_failback_shadow_episode_close_ms}UL",
        "trig_s ? ${ecco_supervision_lost_ms}UL",
        "id(failback_shadow_seen_last_valid_ms) + ${ecco_supervision_lost_ms}UL",
        "id(failback_shadow_noclient_since_ms) + ${ecco_failback_shadow_assumed_reboot_timeout_ms}UL",
        "(age <= ${ecco_supervision_stable_max_gap_ms}UL)",
        ">= ${ecco_failback_shadow_publish_min_ms}UL",
        ">= ${ecco_failback_shadow_soak_publish_min_ms}UL",
    ):
        if pin not in l1:
            out.append(f"expression pin missing: {pin}")
    if re.search(r"stable_for\s*>=\s*\d", l1):
        out.append("literal in the close expression")
    return out


def z3_token_ban(c: Ctx) -> list[str]:
    out = []
    code = fpas._strip_code(c.lam1)
    for t in Z3_TOKENS:
        if t in code:
            out.append(f"forbidden token {t!r} in the FB-C tick")
    # Master section 6.8 lists a bare `reboot` token; design/S3 section 10 (the detailed pin) does not, because
    # FB-C's OWN mandated names contain it (the global `failback_shadow_ep_reboot_margin_s`, S3 section 7.1, and the
    # substitution `ecco_failback_shadow_assumed_reboot_timeout_ms`, section 5.5). The restart CALL forms are banned
    # instead: any `reboot(` / `.reboot` call or `App` access (recorded deviation, see the report).
    if re.search(r"\breboot\s*\(|\.\s*reboot\b|->\s*reboot\b|\bApp\b", code):
        out.append("a reboot call form in the FB-C tick")
    raw = yaml.dump(c.iv)
    if "supervision_have_valid" in raw:
        out.append("supervision_have_valid referenced in the FB-C interval (code or comment)")
    if "dump_overpower_samples" in raw:
        out.append("dump_overpower_samples referenced")
    if re.search(r"start_?journal", raw, re.I):
        out.append("start_journal referenced")
    return out


def z3_pra278(c: Ctx) -> list[str]:
    """PR-A test :278-280 - exactly one interval mentions supervision_have_valid."""
    hits = [i for i in c.fw["interval"] if "supervision_have_valid" in yaml.dump(i["then"])]
    return [] if len(hits) == 1 else [f"{len(hits)} intervals mention supervision_have_valid"]


def z4_assignments(c: Ctx) -> list[str]:
    out = []
    own = set(scope.NEW_GLOBAL_IDS)                # exact ids, not a name prefix
    bad = sorted(t for t in assign_targets(c.lam1) if t not in own)
    if bad:
        out.append(f"assigns non-FB-C ids {bad}")
    pub = set(re.findall(r"id\((\w+)\)\.publish_state", c.lam1))
    if not pub <= set(FBC_TEXT_IDS):
        out.append(f"publishes {sorted(pub - set(FBC_TEXT_IDS))}")
    reads = set(re.findall(r"id\((\w+)\)", c.lam1))
    extra = sorted(x for x in reads if x not in own and x not in FBC_TEXT_IDS and x not in READ_ALLOWLIST)
    if extra:
        out.append(f"reads outside the read-only allowlist: {extra}")
    if re.search(r"id\(\w+\)\s*(?:->|\.)\s*(?!state\b|publish_state\b|now\b)\w+\(", c.lam1):
        m = re.findall(r"id\(\w+\)\s*(?:->|\.)\s*(?!state\b|publish_state\b|now\b)(\w+)\(", c.lam1)
        out.append(f"method calls on entities: {sorted(set(m))}")
    return out


def z5_non_authority(c: Ctx) -> list[str]:
    out = []
    fw = c.fw
    allowed_subs = set(scope.SUBSTITUTIONS)     # FB-C's own nodes by exact key / id, not by name prefix
    rest = {}
    for k, v in tree(fw).items():
        if k == "substitutions":
            rest[k] = {a: b for a, b in v.items() if a not in allowed_subs}
        elif k == "_substitutions":
            continue
        elif k == "globals":
            rest[k] = [g for g in v if str(g["id"]) not in scope.NEW_GLOBAL_IDS]
        elif k == "text_sensor":
            rest[k] = [t for t in v if t.get("id") not in FBC_TEXT_IDS]
        elif k == "interval":
            rest[k] = [i for i in v if "failback_shadow" not in yaml.dump(i)]
        else:
            rest[k] = v
    if "failback_shadow" in yaml.dump(rest):
        out.append("failback_shadow referenced by a YAML node other than FB-C's own")
    try:
        if "failback_shadow" in scope.pre_fbc1_text(c.text):
            out.append("failback_shadow appears in firmware text outside FB-C1's four blocks")
    except AssertionError as e:
        out.append(str(e))
    return out


def z6_ram_only(c: Ctx) -> list[str]:
    out = []
    gl = [g for g in c.fw["globals"] if str(g["id"]).startswith(("failback_shadow_", "fbc_raw_"))]
    if not gl:
        out.append("no FB-C globals")
    bad = [g["id"] for g in gl if g.get("restore_value") not in (False, "no")]
    if bad:
        out.append(f"restore_value not 'no': {bad}")
    yes = sorted(g["id"] for g in c.fw["globals"] if g.get("restore_value") in (True, "yes"))
    if yes != RESTORE_YES:
        out.append(f"restore_value: yes set changed: {yes}")
    return out


def z7_durable(c: Ctx) -> list[str]:
    out = []
    try:
        base_text = scope.pre_fbc1_text(c.text)
    except AssertionError as e:
        return [str(e)]
    pats = {"commit_record": r"ecco_durable::commit_record\s*\(", "load_record": r"ecco_durable::load_record\s*\(",
            "load_record_status": r"ecco_durable::load_record_status\s*\("}
    for n, p in pats.items():
        a, b = len(re.findall(p, base_text)), len(re.findall(p, c.text))
        if a != b:
            out.append(f"{n} call sites {a} -> {b}")
    got = (len(re.findall(pats["commit_record"], c.text)), len(re.findall(pats["load_record"], c.text)),
           len(re.findall(pats["load_record_status"], c.text)))
    if got != (57, 7, 3):
        out.append(f"durable surface {got}, want (57, 7, 3)")
    for t in ("RTC_NOINIT", "RTC_DATA_ATTR", "esp_attr", "make_preference", "global_preferences", "nvs_"):
        if t in fpas._strip_code(c.lam1):
            out.append(f"{t} in the FB-C tick")
    if "rtc_storage" in yaml.dump(c.fw.get("preferences", {})):
        out.append("preferences: rtc_storage enabled")
    for name, tags in HEADER_TAGS.items():
        found = sorted(set(re.findall(r"\b[A-Z0-9_]+_TAG\b", HEADER_TEXTS[name])))
        if found != sorted(tags):
            out.append(f"{name}: *_TAG set changed {found}")
    return out


def z8_no_controls(c: Ctx) -> list[str]:
    out = []
    try:
        base = ds.load_firmware_text(scope.pre_fbc1_text(c.text))
    except AssertionError as e:
        return [str(e)]
    for dom in ("button", "switch", "number", "select", "binary_sensor", "script", "sensor"):
        if base.get(dom) != c.fw.get(dom):
            out.append(f"{dom} section changed")
    if base["api"] != c.fw["api"]:
        out.append("api section (actions) changed")
    if base["esphome"] != c.fw["esphome"]:
        out.append("esphome section (on_boot / includes) changed")
    for k in set(base) | set(c.fw):
        if k in ("_text", "substitutions", "_substitutions", "globals", "text_sensor", "interval"):
            continue
        if base.get(k) != c.fw.get(k):
            out.append(f"top-level section {k!r} changed")
    new_ts = [t for t in c.fw["text_sensor"] if t not in base["text_sensor"]]
    if sorted(t.get("id") for t in new_ts) != sorted(FBC_TEXT_IDS):
        out.append(f"new text sensors {sorted(t.get('id') for t in new_ts)}")
    for t in new_ts:
        if set(t) - {"platform", "name", "id", "entity_category", "update_interval"}:
            out.append(f"{t.get('id')}: unexpected keys {sorted(set(t) - {'platform', 'name', 'id', 'entity_category', 'update_interval'})}")
        if t.get("update_interval") != "never" or t.get("entity_category") != "diagnostic" or t.get("platform") != "template":
            out.append(f"{t.get('id')}: must be a diagnostic template text sensor with update_interval: never")
        if "Supervision" in str(t.get("name")):
            out.append(f"{t.get('name')}: the name must not contain 'Supervision' (PR-A entity scan)")
    return out


STATIC_DETECTORS = {
    "Z0": z0_scope, "Z1": z1_write_surface, "Z2": z2_placement, "Z3": z3_token_ban, "Z3-PRA278": z3_pra278,
    "Z4": z4_assignments, "Z5": z5_non_authority, "Z6": z6_ram_only, "Z7": z7_durable, "Z8": z8_no_controls,
}


# ===========================================================================
# Behavioural scenarios (each returns a list of failed expectations)
# ===========================================================================
EPS = "failback_shadow_episode_text"
SOAK = "failback_shadow_soak_text"
STATE = "failback_shadow_state_text"
FBC_OFF, PRA_OFF = 250, 750  # deterministic phases: FB-C at .250, PR-A at .750


def tick_at_or_after(t: int, off: int = FBC_OFF) -> int:
    """First FB-C tick time >= t for a 1s interval with initial offset `off`."""
    k = max(0, -(-(t - off) // 1000))
    return off + k * 1000


def outage(fw, *, seed=0, tie=hx.Harness.TIE_FBC_FIRST, fbc_off=FBC_OFF, pra_off=PRA_OFF, drift=0, last_beat=130_000,
           first_beat=10_000, cadence=30_000, drop_after=2_000, ntp=False, run_to=None):
    """Healthy beats until `last_beat`, then HA stops (client drops `drop_after` later)."""
    h = mk(fw, seed=seed, tie=tie, fbc_offset_ms=fbc_off, pra_offset_ms=pra_off, drift_ms=drift)
    if ntp:
        h.set_ntp(True, 1_800_000_000)
    h.set_client(True)
    h.schedule_beats_every(first_beat, cadence, last_beat)
    h.run_until(last_beat + drop_after)
    h.set_client(False)
    if run_to is not None:
        h.run_until(run_to)
    return h


def return_beats(h, r, until, cadence=30_000):
    h.schedule_beats_every(r, cadence, until)


def tc01(fw, seed=1):
    e = Exp()
    h = mk(fw, seed=seed, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    first, period, horizon = 10_000, 30_000, 620_000
    h.schedule_beats_every(first, period, horizon)
    third = first + 2 * period
    phases, wrong = set(), []
    for t in range(1000, horizon, 1000):
        h.run_until(t)
        phases.add(h.g("failback_shadow_phase"))
        st = h.text(STATE)
        if t <= third and st != "SHADOW_WATCH":
            wrong.append((t, st))
        if t >= third + 1000 and st != "SHADOW_IDLE":
            wrong.append((t, st))
    e.eq(phases, {0}, "T-C01 phase stays NONE on every tick")
    e.ok(not wrong, f"T-C01 state WATCH until the 3rd beat then IDLE: {wrong[:3]}")
    e.eq(h.published(STATE), ["SHADOW_WATCH", "SHADOW_IDLE"], "T-C01 State published exactly on change")
    e.eq(h.g("failback_shadow_stable_since_ms"), third, "T-C01 stable_since = the 3rd beat")
    e.eq(h.g("failback_shadow_gap_b0"), h.beats_sent - 1, "T-C01 histogram b0 = beats - 1")
    e.eq([h.g(f"failback_shadow_gap_b{i}") for i in range(1, 6)], [0] * 5, "T-C01 no other bucket")
    e.eq(h.published("failback_shadow_verdict_text"), ["NOT_EVALUATED"], "T-C01 Verdict NOT_EVALUATED once")
    e.z9(h)
    return e.fails


def tc02(fw, seed=0, ntp=False):
    e = Exp()
    last = 130_000
    h = outage(fw, seed=seed, ntp=ntp, last_beat=last, run_to=last + LOST_MS + 2_000)
    edge = last + LOST_MS
    g = h.g
    e.eq(g("failback_shadow_phase"), 1, "T-C02 phase OPEN")
    e.eq(g("failback_shadow_ep"), 1, "T-C02 exactly one episode")
    e.eq(g("failback_shadow_ep_trigger"), 1, "T-C02 trigger H")
    e.eq(g("failback_shadow_ep_edge_ms"), edge, "T-C02 t_edge = last_valid + T_lost")
    e.eq(g("failback_shadow_ep_edge_uptime_s"), edge // 1000, "T-C02 u0 from millis_64")
    e.eq(g("failback_shadow_ep_client_at_edge"), False, "T-C02 cli=0")
    e.near(g("failback_shadow_ep_reboot_margin_s"), 600, 3, "T-C02 rb ~ 600 (lower bound on time to restart)")
    e.eq(h.text(STATE), "SHADOW_EPISODE", "T-C02 State")
    e.eq(len(h.published(EPS)), 2, "T-C02 Episode published at the first tick and once at the edge")
    kv = h.parse_kv(EPS)
    e.ok(kv.get("ph") == "O" and kv.get("tr") == "H" and kv.get("cli") == "0" and kv.get("v0") == "-",
         f"T-C02 Episode string {h.text(EPS)}")
    if ntp:
        e.near(g("failback_shadow_ep_edge_epoch"), 1_800_000_000, 2, "T-C02 e0 reconstructed from the trusted clock")
    else:
        e.eq(g("failback_shadow_ep_edge_epoch"), 0, "T-C02 e0 = 0 when the clock is untrusted")
    e.eq(g("supervision_suspect_events"), 1, "T-C02 (PR-A) SUSPECT then LOST")
    e.z9(h)
    return e.fails


def tc03(fw, seed=0):
    e = Exp()
    last = 130_000
    h = outage(fw, seed=seed, last_beat=last, run_to=last + LOST_MS + 2_000)
    edge = last + LOST_MS
    r = 500_000
    return_beats(h, r, r + 900_000)
    h.run_until(r + 5_000)
    g = h.g
    e.eq(g("failback_shadow_phase"), 2, "T-C03 HA_BACK at the first beat back")
    e.eq(g("failback_shadow_ep"), 1, "T-C03 same episode")
    e.eq(g("failback_shadow_ep_return_s"), (r - edge) // 1000, "T-C03 ret exact")
    e.eq(g("failback_shadow_ep_return_gap_ms"), r - last, "T-C03 gap exact (trigger H: closed heartbeat gap)")
    e.eq(h.text(STATE), "SHADOW_EPISODE_HA_BACK", "T-C03 State")
    s3 = r + 2 * 30_000  # Stable rises at the 3rd beat (span 60 s)
    close_tick = tick_at_or_after(s3 + CLOSE_MS)
    h.run_until(close_tick - 1)
    e.eq(g("failback_shadow_phase"), 2, "T-C03 not closed one ms before the close tick")
    e.eq(g("failback_shadow_stable_since_ms"), s3, "T-C03 stable_since = the beat that set Stable")
    h.run_until(close_tick)
    e.eq(g("failback_shadow_phase"), 3, "T-C03 closed at the first FB-C tick with now >= r + 360 s")
    e.eq(g("failback_shadow_ep_close_s"), (close_tick - edge) // 1000, "T-C03 cl")
    e.eq(g("failback_shadow_ep_fbf"), 0, "T-C03 FB-C1 fbf = '-'")
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C03 State after close")
    kv = h.parse_kv(EPS)
    e.ok(kv.get("ph") == "C" and kv.get("fbf") == "-" and kv.get("cl") == str((close_tick - edge) // 1000),
         f"T-C03 Episode {h.text(EPS)}")
    e.z9(h)
    return e.fails


def _episode_signature(h):
    ep = h.episode()
    return ep


def tc04(fw):
    e = Exp()
    last = 130_000
    r = 500_000

    def run(**kw):
        h = outage(fw, last_beat=last, run_to=last + LOST_MS + 2_000, **kw)
        return_beats(h, r, r + 900_000)
        h.run_until(r + 420_000)
        return h

    ref = run(tie=hx.Harness.TIE_FBC_FIRST)
    ref_ep = ref.episode()
    e.eq(ref_ep["phase"], 3, "T-C04 reference run closed")
    exact = ("phase", "ep", "ep_trigger", "ep_edge_ms", "ep_last_edge_ms", "ep_edge_uptime_s", "ep_edge_epoch",
             "ep_client_at_edge", "ep_return_s", "ep_return_gap_ms", "ep_relost", "ep_fbf")
    variants = [
        ("pra first, same offset", dict(tie=hx.Harness.TIE_PRA_FIRST, fbc_off=300, pra_off=300)),
        ("fbc first, same offset", dict(tie=hx.Harness.TIE_FBC_FIRST, fbc_off=300, pra_off=300)),
        ("offsets swapped", dict(fbc_off=PRA_OFF, pra_off=FBC_OFF)),
    ] + [(f"random seed {s} drift", dict(seed=s, fbc_off=None, pra_off=None, drift=30)) for s in range(1, 21)]
    for label, kw in variants:
        h = run(**kw)
        ep = h.episode()
        for f in exact:
            e.eq(ep[f], ref_ep[f], f"T-C04 {label}: {f}")
        e.near(ep["ep_close_s"], ref_ep["ep_close_s"], 1, f"T-C04 {label}: cl (observation stamp)")
        e.near(ep["ep_reboot_margin_s"], ref_ep["ep_reboot_margin_s"], 1, f"T-C04 {label}: rb (observation stamp)")
        e.z9(h)
    return e.fails


def tc05(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h.run_until(LOST_MS + 3_000)
    g = h.g
    e.eq(g("failback_shadow_phase"), 1, "T-C05 OPEN")
    e.eq(g("failback_shadow_ep_trigger"), 2, "T-C05 trigger S (no valid beat this boot)")
    e.eq(g("failback_shadow_ep_edge_ms"), LOST_MS, "T-C05 t_edge = uptime T_lost")
    e.eq(g("failback_shadow_ep_edge_uptime_s"), LOST_MS // 1000, "T-C05 u0 = 300")
    e.eq(g("supervision_suspect_events"), 0, "T-C05 (PR-A) STARTUP never passes through SUSPECT")
    e.eq(g("failback_shadow_ep_reboot_margin_s"), (ASSUMED_MS - LOST_MS) // 1000, "T-C05 rb = 600 (no client since boot)")
    e.eq(h.parse_kv(EPS).get("tr"), "S", "T-C05 Episode tr=S")
    e.z9(h)
    # startup LOST and the first beat inside the same FB-C tick window: the trigger is classified with the
    # PREVIOUS tick's seen_svc, so it is still S, and E1 + E2 both fire in that one tick.
    h2 = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h2.run_until(LOST_MS - 1_000)
    h2.sim.now_ms = LOST_MS + 100
    h2.pra_tick()
    h2.beat()
    h2.sim.now_ms = LOST_MS + 200
    h2.fbc_tick()
    e.eq(h2.g("failback_shadow_ep_trigger"), 2, "T-C05b trigger S even though a beat arrived in the same tick")
    e.eq(h2.g("failback_shadow_phase"), 2, "T-C05b E1 and E2 in one tick")
    e.eq(h2.g("failback_shadow_ep_return_gap_ms"), LOST_MS + 100, "T-C05b gap = first_valid_ms (uptime) for trigger S")
    e.z9(h2)
    return e.fails


def tc06(fw):
    e = Exp()
    last = 130_000
    edge = last + LOST_MS
    # (a) a beat ~1 s after the LOST edge
    h = outage(fw, last_beat=last, run_to=edge + 1_000)
    e.eq(h.g("supervision_state"), 3, "T-C06 (PR-A) LOST")
    h.schedule_beats([edge + 1_750])
    seen = []
    for t in range(edge + 1_500, edge + 6_000, 500):
        h.run_until(t)
        seen.append((h.g("failback_shadow_phase"), h.g("failback_shadow_ep")))
    e.ok(all(p in (1, 2) and n == 1 for p, n in seen), f"T-C06 never NONE or CLOSED, same episode: {seen}")
    e.eq(seen[-1][0], 2, "T-C06 HA_BACK")
    e.z9(h)
    # (b) LOST edge and the return beat between two FB-C ticks
    h2 = outage(fw, last_beat=last, run_to=edge - 1_000)
    h2.sim.now_ms = edge + 750
    h2.pra_tick()  # raises LOST
    e.eq(h2.g("supervision_state"), 3, "T-C06b PR-A raised LOST")
    h2.sim.now_ms = edge + 800
    h2.beat()  # returns to SUPERVISED before FB-C ever samples the state
    e.eq(h2.g("supervision_state"), 1, "T-C06b state is SUPERVISED again at the FB-C tick")
    h2.sim.now_ms = edge + 900
    h2.fbc_tick()
    e.eq(h2.g("failback_shadow_phase"), 2, "T-C06b edge and return in one tick -> HA_BACK (counters, not state sampling)")
    e.eq(h2.g("failback_shadow_ep"), 1, "T-C06b one episode")
    e.eq(h2.g("failback_shadow_ep_edge_ms"), edge, "T-C06b t_edge from the PREVIOUS last_valid, not the new beat")
    e.eq(h2.g("failback_shadow_ep_trigger"), 1, "T-C06b trigger H")
    e.eq(h2.g("failback_shadow_ep_return_s"), 0, "T-C06b ret a fraction of a second")
    e.z9(h2)
    return e.fails


def tc06b(fw):
    e = Exp()
    last = 130_000
    h = outage(fw, last_beat=last, run_to=last + LOST_MS + 2_000)
    e.eq(h.g("failback_shadow_phase"), 1, "T-C06b setup OPEN")
    last_edge = h.g("failback_shadow_ep_last_edge_ms")
    h.sim.set_global("supervision_valid_count", h.g("supervision_valid_count") + 1)
    h.sim.set_global("supervision_last_valid_ms", last_edge - 1_000)  # a beat BEFORE the edge
    h.sim.now_ms += 1_000
    h.fbc_tick()
    e.eq(h.g("failback_shadow_phase"), 1, "T-C06b a beat older than the edge never returns an OPEN episode")
    e.z9(h)
    return e.fails


def tc07(fw):
    e = Exp()
    last, r1, r2 = 130_000, 500_000, 1_000_000
    h = outage(fw, last_beat=last, run_to=last + LOST_MS + 2_000)
    h.schedule_beats_every(r1, 30_000, r1 + 120_000)  # 5 beats, last at 620 s
    h.schedule_beats_every(r2, 30_000, r2 + 400_000)
    seq = []
    for t in range(432_000, 1_100_000, 500):
        h.run_until(t)
        p = h.g("failback_shadow_phase")
        if not seq or seq[-1] != p:
            seq.append(p)
        e.ok(h.g("failback_shadow_ep") == 1, f"T-C07 one episode at t={t}")
        if h.g("failback_shadow_ep") != 1:
            break
    e.eq(seq, [1, 2, 1, 2], "T-C07 OPEN -> HA_BACK -> OPEN -> HA_BACK, never NONE or CLOSED")
    e.eq(h.g("failback_shadow_ep_relost"), 1, "T-C07 rl = 1")
    e.eq(h.g("failback_shadow_ep_return_s"), (r1 - (last + LOST_MS)) // 1000, "T-C07 ret keeps the FIRST return")
    e.eq(h.g("failback_shadow_ep_edge_ms"), last + LOST_MS, "T-C07 t_edge keeps the first edge")
    e.eq(h.g("failback_shadow_ep_last_edge_ms"), (r1 + 120_000) + LOST_MS, "T-C07 last_edge = the re-loss edge")
    e.eq(h.g("failback_shadow_ep_trigger"), 1, "T-C07 trigger")
    e.ok(h.parse_kv(EPS).get("rl") == "1" and h.parse_kv(EPS).get("ph") == "B", f"T-C07 Episode {h.text(EPS)}")
    e.z9(h)
    return e.fails


def tc08(fw):
    e = Exp()
    last, r = 130_000, 500_000
    h = outage(fw, last_beat=last, run_to=last + LOST_MS + 2_000)
    s1 = r + 60_000
    skip_at = r + 270_000
    h.schedule_beats([r + 30_000 * k for k in range(0, 9)])  # r .. r+240 s
    h.schedule_beats_every(r + 300_000, 30_000, r + 1_000_000)  # resume after the skipped beat
    s2 = r + 300_000 + 60_000
    close_tick = tick_at_or_after(s2 + CLOSE_MS)
    phases = []
    for t in range(r + 1_000, close_tick + 3_000, 1_000):
        h.run_until(t)
        phases.append((t, h.g("failback_shadow_phase")))
    closed_at = next((t for t, p in phases if p == 3), None)
    e.ok(all(p == 2 for t, p in phases if t < close_tick), "T-C08 never closed before the re-qualified window ends")
    e.ok(closed_at is not None and close_tick <= closed_at <= close_tick + 1_000,
         f"T-C08 closes 300 s after the RE-LATCHED stable_since: {closed_at} vs {close_tick}")
    e.eq(h.g("failback_shadow_stable_since_ms"), s2, "T-C08 stable_since re-latched at the new 3rd beat")
    e.z9(h)
    return e.fails


def tc09(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h.set_client(True)  # HA is up and its API connection stays; only the heartbeat automation is dead
    h.schedule_beats_every(10_000, 30_000, 130_000)
    h.run_until(130_000 + LOST_MS + 3_000)
    e.eq(h.g("failback_shadow_ep_client_at_edge"), True, "T-C09 cli=1 at the edge")
    e.eq(h.g("failback_shadow_ep_reboot_margin_s"), -1, "T-C09 rb = none (no timer running)")
    h.run_until(130_000 + 7_200_000)
    e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep")), (1, 1), "T-C09 stays OPEN for 2 simulated hours")
    kv = h.parse_kv(EPS)
    e.ok(kv.get("rb") == "-" and kv.get("cli") == "1", f"T-C09 Episode {h.text(EPS)}")
    e.eq(h.text(STATE), "SHADOW_EPISODE", "T-C09 State")
    e.z9(h)
    return e.fails


def tc10(fw):
    e = Exp()
    h = outage(fw, last_beat=130_000, run_to=130_000 + LOST_MS + 2_000)
    nonce1 = h.nonce
    old = h.sim
    e.eq(h.g("failback_shadow_phase"), 1, "T-C10 setup: episode OPEN")
    h.reboot()
    e.ok(h.sim is not old and h.nonce != nonce1, "T-C10 a new boot with a new nonce")
    h.run_until(2_000)
    e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep")), (0, 0), "T-C10 nothing survives the reboot")
    e.ok(h.text(EPS).startswith(f"id={h.nonce:08X}-0;ph=N;"), f"T-C10 Episode {h.text(EPS)}")
    e.eq(h.parse_kv(SOAK).get("b"), f"{h.nonce:08X}", "T-C10 Soak b = the new boot nonce")
    h.run_until(LOST_MS + 3_000)
    e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep_trigger"), h.g("failback_shadow_ep_edge_uptime_s")),
         (1, 2, 300), "T-C10 a new episode, trigger S at 300 s uptime")
    for label, sim in (("old boot", old), ("new boot", h.sim)):
        e.ok(sim.nvs == {} and sim.nvs_commits == [] and sim.nvs_loads == [] and sim.modbus_log == []
             and sim.executed == [], f"T-C10 zero NVS / Modbus / script access ({label})")
    e.z9(h)
    return e.fails


def tc11(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h.set_client(True)
    h.schedule_beats_every(10_000, 30_000, 400_000)
    h.run_until(100_000)
    e.eq((h.g("failback_shadow_nc"), h.g("failback_shadow_ncm_ms")), (0, 0), "T-C11 nothing before the drop")
    h.set_client(False)
    h.run_until(120_000)
    h.set_client(True)
    h.run_until(130_000 + SOAK_PUB_MS)
    e.eq(h.g("failback_shadow_nc"), 1, "T-C11 nc + 1")
    e.eq(h.g("failback_shadow_ncm_ms"), 20_000, "T-C11 ncm = 20 s")
    e.eq(h.parse_kv(SOAK).get("ncm"), "20", "T-C11 Soak ncm=20")
    # a sub-second socket that opens and closes between two ticks is invisible (ncm is an upper bound)
    h.set_client(False)
    h.set_client(True)
    h.run_until(150_000)
    e.eq((h.g("failback_shadow_nc"), h.g("failback_shadow_ncm_ms")), (1, 20_000), "T-C11 the unseen socket changes nothing")
    e.z9(h)
    return e.fails


def tc12(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    nonces = [h.nonce]
    for boot in range(5):
        h.run_until(LOST_MS + 5_000)
        e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep"), h.g("failback_shadow_ep_trigger")),
             (1, 1, 2), f"T-C12 boot {boot}: one trigger-S episode at 300 s")
        e.eq(h.g("failback_shadow_ep_client_at_edge"), False, f"T-C12 boot {boot}: cli=0")
        e.eq(h.g("failback_shadow_ep_reboot_margin_s"), 600, f"T-C12 boot {boot}: rb = 600 (no-client window counted from boot)")
        h.run_until(ASSUMED_MS - 1_000)
        e.eq(h.g("failback_shadow_phase"), 1, f"T-C12 boot {boot}: still OPEN at the restart")
        h.reboot()
        nonces.append(h.nonce)
        e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep")), (0, 0), f"T-C12 boot {boot + 1}: nothing carried across")
    e.eq(len(set(nonces)), 6, "T-C12 a distinct nonce every boot")
    h.schedule_beats_every(120_000, 30_000, 700_000)
    h.run_until(700_000)
    e.eq((h.g("failback_shadow_phase"), h.g("failback_shadow_ep")), (0, 0), "T-C12 HA returns at 120 s uptime: no episode")
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C12 stable supervision after the loop")
    e.z9(h)
    return e.fails


def _set(h, **flags):
    for k, v in flags.items():
        h.sim.set_global(k, v)


def tc13(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)

    def wr():
        return (h.g("failback_shadow_wr_fp"), h.g("failback_shadow_wr_dump"), h.g("failback_shadow_wr_r244"))

    h.run_until(5_000)
    _set(h, free_power_operation_in_progress=True)  # FP START while SHADOW_WATCH
    h.run_until(6_000)
    e.eq(wr(), (1, 0, 0), "T-C13 FP START while WATCH")
    e.eq(h.parse_kv(SOAK).get("wr"), "1/0/0/0", "T-C13 Soak wr=1/0/0/0 published immediately")
    _set(h, free_power_operation_in_progress=False)
    h.run_until(12_000)
    _set(h, free_power_operation_in_progress=True)  # a failed START sets only the op flag
    h.run_until(13_000)
    e.eq(wr(), (2, 0, 0), "T-C13 a failed START (op flag only) counts")
    _set(h, free_power_operation_in_progress=False)
    h.schedule_beats_every(20_000, 30_000, 200_000)
    h.run_until(150_000)
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C13 stable, no episode")
    _set(h, free_power_operation_in_progress=True)
    h.run_until(152_000)
    e.eq(wr(), (2, 0, 0), "T-C13 a START while stable and no episode is NOT counted")
    _set(h, free_power_operation_in_progress=False)
    h.run_until(200_000 + LOST_MS + 3_000)  # LOST edge at 500 s
    e.eq(h.g("failback_shadow_phase"), 1, "T-C13 setup: OPEN")
    _set(h, reg244_apply_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(wr(), (2, 0, 1), "T-C13 R244 START while OPEN")
    _set(h, reg244_apply_in_progress=False)
    r = 600_000
    h.schedule_beats_every(r, 30_000, r + 600_000)
    h.run_until(r + 20_000)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C13 setup: HA_BACK")
    _set(h, dump_operation_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(wr(), (2, 1, 1), "T-C13 Dump START while HA_BACK")
    _set(h, dump_operation_in_progress=False)
    e.eq(h.parse_kv(SOAK).get("wr"), "2/1/1/0", "T-C13 Soak wr")
    h.run_until(r + 420_000)
    e.eq(h.g("failback_shadow_phase"), 3, "T-C13 setup: CLOSED")
    _set(h, free_power_operation_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(wr(), (2, 1, 1), "T-C13 after CLOSED (FB-C1 has no would-be latch) a START is not counted")
    e.z9(h)
    # obligations loaded at boot are not STARTs
    h2 = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    _set(h2, free_power_snapshot_valid=True)
    h2.run_until(5_000)
    e.eq((h2.g("failback_shadow_wr_fp"), h2.g("failback_shadow_busy_fp")), (0, True), "T-C13 a boot-loaded snapshot seeds busy_fp, no count")
    _set(h2, free_power_snapshot_valid=False)
    h2.run_until(8_000)
    _set(h2, free_power_operation_in_progress=True)
    h2.run_until(10_000)
    e.eq(h2.g("failback_shadow_wr_fp"), 1, "T-C13 a real START after the seed counts")
    e.z9(h2)
    return e.fails


def tc14(fw):
    e = Exp()
    X = WRAP - 700_000
    cadence = 20_000

    def boot_at(x):
        h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
        h.jump_to(x)
        h.set_client(True)
        h.beat()
        return h

    # (A) the edge is BEFORE the wrap; the return and the close are after it
    h = boot_at(X)
    last = X + 19 * cadence  # = 2**32 - 320 s
    h.schedule_beats_every(X + cadence, cadence, last)
    h.run_until(last + 2_000)
    h.set_client(False)
    edge_abs = last + LOST_MS
    h.run_until(edge_abs + 2_000)
    e.eq(h.g("failback_shadow_phase"), 1, "T-C14A OPEN before the wrap")
    e.eq(h.g("failback_shadow_ep_edge_ms"), edge_abs % WRAP, "T-C14A t_edge (32-bit)")
    e.eq(h.g("failback_shadow_ep_edge_uptime_s"), edge_abs // 1000, "T-C14A u0 from millis_64")
    r = WRAP + 50_000
    h.schedule_beats_every(r, cadence, r + 900_000)
    h.run_until(r + 5_000)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C14A HA_BACK after the wrap")
    e.eq(h.g("failback_shadow_ep_return_s"), (r - edge_abs) // 1000, "T-C14A ret continuous across the wrap")
    e.eq(h.g("failback_shadow_ep_return_gap_ms"), r - last, "T-C14A gap continuous across the wrap")
    s = r + 3 * cadence  # 20 s cadence: the 3rd beat spans only 40 s < 55 s, so Stable rises at the 4th (60 s)
    h.run_until(s + CLOSE_MS + 3_000)
    e.eq(h.g("failback_shadow_phase"), 3, "T-C14A closed after the wrap")
    e.near(h.g("failback_shadow_ep_close_s"), (s + CLOSE_MS - edge_abs) // 1000, 2, "T-C14A cl continuous")
    e.z9(h)
    # (B) the edge itself is AFTER the wrap: u0 must come from the 64-bit clock, not the wrapped 32-bit one
    last2 = WRAP - 290_000
    start2 = last2 - 16 * cadence
    h2 = boot_at(start2)
    h2.schedule_beats_every(start2 + cadence, cadence, last2)
    h2.run_until(last2 + LOST_MS + 3_000)
    edge2 = last2 + LOST_MS  # = 2**32 + 10 s
    e.eq(h2.g("failback_shadow_phase"), 1, "T-C14B OPEN")
    e.eq(h2.g("failback_shadow_ep_edge_ms"), edge2 % WRAP, "T-C14B t_edge wrapped")
    e.eq(h2.g("failback_shadow_ep_edge_uptime_s"), edge2 // 1000, "T-C14B u0 is the 64-bit uptime (not the wrapped 32-bit value)")
    e.z9(h2)
    return e.fails


def tc15(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    gaps = [29_000, 35_000, 44_000, 45_000, 46_000, 91_000, 299_000, 301_000]
    t = 10_000
    times = [t]
    for g_ in gaps:
        t += g_
        times.append(t)
    h.schedule_beats(times)
    long_checks = []
    for i, g_ in enumerate(gaps):
        bt = times[i + 1]
        h.run_until(bt + 1_300)
        if g_ > 45_000:
            long_checks.append((g_, h.parse_kv(SOAK).get("lg"), h.parse_kv(SOAK).get("mx")))
    e.eq([h.g(f"failback_shadow_gap_b{i}") for i in range(6)], [2, 2, 1, 2, 1, 0],
         "T-C15 buckets exact (29/35 -> b0, 44/45 -> b1, 46 -> b2, 91/299 -> b3, 301 -> b4)")
    e.eq([c[1] for c in long_checks], ["46.0", "91.0", "299.0", "301.0"], "T-C15 lg published immediately on each long gap")
    e.eq(h.g("failback_shadow_gap_last_long_ms"), 301_000, "T-C15 lg")
    e.eq(h.g("failback_shadow_gap_max_ms"), 301_000, "T-C15 mx")
    e.eq(h.g("failback_shadow_gaps_missed"), 0, "T-C15 gm = 0 so far")
    # two valid beats inside one FB-C tick window: the last gap is exact, the other is counted as missed
    base = times[-1] + 30_300  # .300 and .400: between the .250 and .1250 ticks
    h.schedule_beats([base, base + 100])
    h.run_until(base + 2_000)
    e.eq(h.g("failback_shadow_gaps_missed"), 1, "T-C15 two beats in one tick -> gm + 1")
    e.eq(h.g("failback_shadow_gap_b0"), 3, "T-C15 the exact (100 ms) gap lands in b0")
    e.eq(h.g("failback_shadow_gap_last_long_ms"), 301_000, "T-C15 lg unchanged by a short gap")
    e.z9(h)
    return e.fails


def tc16(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h.schedule_beats_every(10_000, 30_000, 3_700_000)
    h.run_until(130_000)
    c0 = h.fbc_publish_counts()
    h.run_until(3_700_000)
    c1 = h.fbc_publish_counts()
    e.eq(c1[STATE], c0[STATE], "T-C16 State: 0 publishes in 1 h steady state")
    e.eq(c1[EPS], c0[EPS], "T-C16 Episode: 0 publishes in 1 h steady state")
    e.eq(c1["failback_shadow_verdict_text"], 1, "T-C16 Verdict published once")
    e.eq(c1["failback_shadow_inputs_text"], 1, "T-C16 Inputs published once")
    e.ok(c1[SOAK] - c0[SOAK] <= 61, f"T-C16 Soak <= 1/min in steady state ({c1[SOAK] - c0[SOAK]})")
    # client flapping once per second: the Soak string changes every second, but publishes are rate-bound
    h2 = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h2.schedule_beats_every(10_000, 30_000, 900_000)
    h2.run_until(60_000)
    stamps = []
    last_n = len(h2.published(SOAK))
    for t in range(61_000, 661_000, 1_000):
        h2.set_client(t % 2000 == 1000)
        h2.run_until(t)
        n = len(h2.published(SOAK))
        if n != last_n:
            stamps.append(t)
            last_n = n
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    e.ok(gaps and min(gaps) >= SOAK_PUB_MS - 1_000, f"T-C16 Soak publishes at least ~{SOAK_PUB_MS // 1000}s apart under 1 Hz churn: min {min(gaps) if gaps else None}")
    e.ok(len(stamps) <= 11, f"T-C16 <= ~1 Soak publish per minute under churn ({len(stamps)} in 10 min)")
    h2.set_client(True)
    h2.run_until(661_000 + SOAK_PUB_MS + 2_000)
    e.eq(h2.parse_kv(SOAK).get("nc"), str(h2.g("failback_shadow_nc")), "T-C16 the final value is flushed within the interval")
    e.z9(h, h2)
    return e.fails


WORST = dict(ep=65535, ep_trigger=2, ep_edge_ms=WRAP - 1, ep_last_edge_ms=WRAP - 1, ep_edge_uptime_s=WRAP - 2,
             ep_edge_epoch=WRAP - 1, ep_client_at_edge=True, ep_reboot_margin_s=2_000_000_000, ep_return_s=WRAP - 2,
             ep_return_gap_ms=WRAP - 2, ep_relost=65535, ep_close_s=WRAP - 2, ep_fbf=2)
WORST_SOAK = dict(gap_b0=65535, gap_b1=65535, gap_b2=65535, gap_b3=65535, gap_b4=65535, gap_b5=65535,
                  gap_max_ms=WRAP - 2, gap_last_long_ms=WRAP - 2, gaps_missed=65535, nc=65535, ncm_ms=WRAP - 2,
                  wr_fp=65535, wr_dump=65535, wr_r244=65535)


def worst_case_strings(fw) -> list[str]:
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF, enforce_z9=True)
    out = []
    h.beat()
    h.run_until(2_000)
    for phase in (1, 2, 3):
        for k, v in {**WORST, **WORST_SOAK}.items():
            h.sim.set_global("failback_shadow_" + k, v)
        h.sim.set_global("failback_shadow_phase", phase)
        h.sim.set_global("supervision_boot_nonce", 0xFFFFFFFF)
        h.sim.set_global("failback_shadow_last_pub_episode_ms", 0)
        h.sim.set_global("failback_shadow_last_pub_soak_ms", 0)
        h.sim.now_ms += 70_000
        h.sim.set_global("supervision_last_valid_ms", h.sim.millis())  # keep the tick in a steady, non-edge state
        h.sim.set_global("failback_shadow_seen_svc", h.g("supervision_valid_count"))
        h.sim.set_global("failback_shadow_seen_lost", h.g("supervision_lost_events"))
        h.sim.set_global("failback_shadow_seen_last_valid_ms", h.sim.millis())
        h.fbc_tick()
        out += [h.text(EPS), h.text(SOAK)]
    return out, h


def tc17(fw):
    e = Exp()
    strings, h = worst_case_strings(fw)
    e.ok(all(len(s) > 0 for s in strings), "T-C17 worst-case strings were produced")
    mx = max(len(s) for s in strings)
    e.ok(mx <= 200, f"T-C17 worst-case length {mx} <= 200")
    e.ok(any("ph=C" in s for s in strings) and any("ph=B" in s for s in strings) and any("ph=O" in s for s in strings),
         "T-C17 every phase rendered")
    e.ok(any("rl=65535" in s for s in strings) and any("e0=4294967295" in s for s in strings),
         "T-C17 maxima are actually exercised")
    e.z9(h)
    e.n += 1
    tc17.worst = mx
    return e.fails


def tc18(fw):
    e = Exp()
    h = mk(fw, fbc_offset_ms=FBC_OFF, pra_offset_ms=PRA_OFF)
    h.sim.set_global("supervision_generation", 0)
    g0 = {k: (v if not isinstance(v, list) else list(v)) for k, v in h.sim.g.items()}
    p0 = {k: len(v.published) for k, v in h.sim.entities.items()}
    for _ in range(5):
        h.sim.now_ms += 1_000
        h.fbc_tick()
    e.ok(h.sim.g == g0, "T-C18 generation == 0: every global (including FB-C's own) unchanged")
    e.ok({k: len(v.published) for k, v in h.sim.entities.items()} == p0, "T-C18 nothing published")
    e.eq(h.g("failback_shadow_ready"), False, "T-C18 not ready")
    e.z9(h)
    return e.fails


def asserts_of(lam0: str) -> list[tuple[str, str]]:
    return re.findall(r"static_assert\((.*?),\s*\"(.*?)\"\)\s*;", strip_comments(lam0), flags=re.S)


def eval_assert(expr: str, subs: dict) -> bool:
    e = re.sub(r"\$\{(\w+)\}", lambda m: subs[m.group(1)], expr)
    e = re.sub(r"(\d+)UL", r"\1", e)
    return bool(eval(e, {"__builtins__": {}}, {}))  # noqa: S307 - a substitution-only arithmetic expression


def tc19(fw):
    e = Exp()
    lam0, _ = hx.fbc_lambdas(fw)
    asserts = asserts_of(lam0)
    subs = fw["_substitutions"]
    e.eq(len(asserts), 5, "T-C19 five static_asserts")
    e.ok(all(eval_assert(a, subs) for a, _ in asserts), "T-C19 all five hold for the shipped constants")
    neg = {
        "lost <= suspect + start_max": {"ecco_supervision_lost_ms": "120000"},
        "lost >= assumed reboot timeout": {"ecco_failback_shadow_assumed_reboot_timeout_ms": "300000"},
        "close = 299999 (< lost)": {"ecco_failback_shadow_episode_close_ms": "299999"},
        "close < stable min span": {"ecco_supervision_stable_min_span_ms": "400000"},
        "publish_min = 30001": {"ecco_failback_shadow_publish_min_ms": "30001"},
    }
    for label, patch in neg.items():
        bad = {**subs, **patch}
        e.ok(any(not eval_assert(a, bad) for a, _ in asserts), f"T-C19 negative control rejected: {label}")
        # and each violation is caught by exactly the assert aimed at it
    # the coupling test: the assumed no-client restart window is ESPHome's default only while nothing overrides it
    api, wifi = fw["api"], fw["wifi"]
    e.ok("reboot_timeout" not in api and "reboot_timeout" not in wifi and "ap" not in wifi and "provisioning" not in fw,
         "T-C19 coupling: neither api nor wifi overrides reboot_timeout and there is no fallback AP / provisioning")
    e.eq(subs["ecco_failback_shadow_assumed_reboot_timeout_ms"], "900000", "T-C19 coupling: assumed window = ESPHome's 15 min default")
    return e.fails


def tc23(fw):
    e = Exp()
    last, r = 130_000, 500_000
    h = outage(fw, tie=hx.Harness.TIE_FBC_FIRST, fbc_off=0, pra_off=0, last_beat=last, run_to=last + LOST_MS + 2_000)
    h.schedule_beats([r + 30_000 * k for k in range(0, 10)])  # r .. r+270 s: Stable from r+60 s
    s = r + 60_000
    b_last = s + 254_700  # 44.7 s after the beat at r+270 s (streak kept); 254.7 s after stable_since
    h.schedule_beats([b_last])
    t_crit = s + CLOSE_MS  # the whole-second tick at which a naive stable_for would reach 300 s
    h.run_until(t_crit - 1_000)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C23 still HA_BACK just before the critical tick")
    e.eq(h.g("failback_shadow_stable_since_ms"), s, "T-C23 stable_since latched")
    e.ok(h.g("supervision_stable") and h.g("supervision_state") == 1,
         "T-C23 setup: PR-A's own flag is still true (its tick has not run past age 45 s)")
    # at t_crit FB-C runs FIRST (same-ms tie) while supervision_stable is still true and the age is 45.3 s
    age = (t_crit - b_last)
    e.ok(MAX_GAP_MS < age, f"T-C23 setup: age {age} ms is past the stable max gap")
    h.run_until(t_crit)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C23 no close: P_STABLE is false at age 45.3 s even though supervision_stable is true")
    e.eq(h.g("failback_shadow_stable_prev"), False, "T-C23 P_STABLE false")
    e.eq(h.g("failback_shadow_stable_since_ms"), s, "T-C23 stable_since unchanged")
    h.run_until(t_crit + 5_000)
    e.eq(h.g("failback_shadow_phase"), 2, "T-C23 no close after PR-A clears Stable either")
    e.z9(h)
    return e.fails


def tc30(fw):
    e = Exp()
    gids = {g["id"] for g in fw["globals"]}
    e.ok(not any(x in gids for x in ("failback_shadow_would_latched", "failback_shadow_ep_kind", "failback_shadow_ep_v0",
                                     "failback_shadow_ep_vu", "failback_shadow_last_verdict")),
         "T-C30 no evaluator / would-latch state exists in FB-C1")
    last, r = 130_000, 500_000
    h = outage(fw, last_beat=last, run_to=last + LOST_MS + 2_000)
    return_beats(h, r, r + 900_000)
    h.run_until(tick_at_or_after(r + 60_000 + CLOSE_MS) + 2_000)
    e.eq(h.g("failback_shadow_phase"), 3, "T-C30 setup: CLOSED")
    e.eq(h.g("failback_shadow_ep_fbf"), 0, "T-C30 every close has fbf = '-'")
    e.eq(h.published("failback_shadow_verdict_text"), ["NOT_EVALUATED"], "T-C30 Verdict NOT_EVALUATED (and only once)")
    e.eq(h.published("failback_shadow_inputs_text"), ["NOT_EVALUATED"], "T-C30 Inputs NOT_EVALUATED (and only once)")
    e.eq(h.text(STATE), "SHADOW_IDLE", "T-C30 CLOSED + stable = IDLE (no SHADOW_WOULD_AWAIT_ACK in FB-C1)")
    # P_WOULD_REFUSE = WATCH or episode open: a START after the close is not counted
    _set(h, free_power_operation_in_progress=True)
    h.run_until(h.now + 2_000)
    e.eq(h.g("failback_shadow_wr_fp"), 0, "T-C30 P_WOULD_REFUSE is false after a close (no latch modelled)")
    e.ok(h.parse_kv(EPS).get("fbf") == "-", "T-C30 Episode fbf=-")
    e.z9(h)
    return e.fails


SCENARIOS = {
    "T-C01": tc01, "T-C02": tc02, "T-C03": tc03, "T-C04": tc04, "T-C05": tc05, "T-C06": tc06, "T-C06b": tc06b,
    "T-C07": tc07, "T-C08": tc08, "T-C09": tc09, "T-C10": tc10, "T-C11": tc11, "T-C12": tc12, "T-C13": tc13,
    "T-C14": tc14, "T-C15": tc15, "T-C16": tc16, "T-C17": tc17, "T-C18": tc18, "T-C19": tc19, "T-C23": tc23,
    "T-C30": tc30,
}


# ===========================================================================
# Host syntax/type/format compile of the REAL lambdas against stub types
# ===========================================================================
_STUBS = r"""
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>
struct TextSensorStub { std::string state; void publish_state(const std::string &s) { state = s; } };
struct BinarySensorStub { bool state = false; };
struct ESPTime { time_t timestamp = 0; bool is_valid() const { return true; } };
struct TimeStub { ESPTime now() { return ESPTime(); } };
static uint32_t millis() { return 0; }
static uint64_t millis_64() { return 0; }
#define id(x) (x)
#define ESP_LOGI(tag, fmt, ...) do { char _b[256]; std::snprintf(_b, sizeof(_b), fmt, ##__VA_ARGS__); (void) _b; } while (0)
#define ESP_LOGW(tag, fmt, ...) ESP_LOGI(tag, fmt, ##__VA_ARGS__)
"""


def host_compile_source(fw: dict, lam0: str, lam1: str, extra_tick: str = "") -> str:
    subs = fw["_substitutions"]

    def sub(code: str) -> str:
        return re.sub(r"\$\{(\w+)\}", lambda m: subs[m.group(1)], code)

    l0, l1 = sub(lam0), sub(lam1) + extra_tick
    gl = {g["id"]: (g["type"], str(g["initial_value"])) for g in fw["globals"]}
    used = sorted(set(re.findall(r"id\((\w+)\)", l1)))
    ents = {"api_client_connected_sensor": "BinarySensorStub", "ntp_time": "TimeStub",
            **{i: "TextSensorStub" for i in FBC_TEXT_IDS}}
    decls = []
    for name in used:
        if name in ents:
            decls.append(f"static {ents[name]} {name};")
        elif name in gl:
            ctype, init = gl[name]
            decls.append(f"static {ctype} {name} = {init};")
        else:
            raise AssertionError(f"lambda references undeclared id({name})")
    return (_STUBS + "\n".join(decls) + "\nvoid fbc_asserts() {\n" + l0 + "\n}\nvoid fbc_tick() {\n" + l1 + "\n}\nint main() { return 0; }\n")


NO_CXX = "no C++ compiler found (this check fails rather than skips, as in the FB-A host-compile suite)"


def find_compiler() -> str | None:
    """Same search order as test_fallback_profile_host_compile.find_compiler(): $ECCO_CXX, a host g++ / c++ (/ clang++) on
    PATH (CI: ubuntu-latest), then the xtensa GCC that ESPHome's own ESP-IDF toolchain installs - the firmware's compiler."""
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    patterns = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*",
                                     "xtensa-esp-elf", "bin", "xtensa-esp32-elf-g++*"))
    home = Path.home()
    patterns += [str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
                 str(home / ".platformio" / "packages" / "toolchain-xtensa*" / "bin" / "xtensa-esp32-elf-g++*"),
                 str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[-1]
    return None


CXX = find_compiler()


def host_compile(fw: dict, lam0: str, lam1: str, extra_tick: str = "") -> list[str]:
    cxx = CXX
    if cxx is None:
        return [NO_CXX]
    src = host_compile_source(fw, lam0, lam1, extra_tick)
    out = []
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "fbc_tick.cpp"
        f.write_text(src, encoding="utf-8")
        for std in ("gnu++17", "gnu++20"):
            r = subprocess.run([cxx, f"-std={std}", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", str(f)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                out.append(f"{std}: {(r.stderr or r.stdout).strip()[:600]}")
    return out


# ===========================================================================
# Z9 probe (per-invocation zero side effects over a representative run)
# ===========================================================================
def z9_probe(fw) -> list[str]:
    last, r = 130_000, 500_000
    h = outage(fw, last_beat=last, run_to=last + LOST_MS + 2_000)
    h.schedule_beats_every(r, 30_000, r + 500_000)
    _set(h, free_power_operation_in_progress=True)
    h.run_until(r + 420_000)
    _set(h, free_power_operation_in_progress=False)
    return list(h.violations) + ([] if h.fbc_invocations > 100 else ["too few FB-C invocations"])


# ===========================================================================
# Z11: string bounds and the Energy Actions card's regex literals
# ===========================================================================
def card_regexes() -> list[tuple[str, int, str]]:
    """Every regex literal in the card's TypeScript source that is used with
    `.test(`: named constants (`const X = /.../i;`) and inline literals
    (`/.../i.test(`). Returns (pattern, flags, origin)."""
    out, seen = [], set()
    files = sorted(CARD_SRC.glob("*.ts")) + sorted((CARD_SRC / "utils").glob("*.ts"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        pats = [m for m in re.finditer(r"const\s+\w+\s*=\s*/((?:\\.|[^/\n\\])+)/([a-z]*)\s*;", src)]
        pats += [m for m in re.finditer(r"(?<![\w/])/((?:\\.|[^/\n\\])+)/([a-z]*)\.test\(", src)]
        for m in pats:
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            out.append((m.group(1), re.I if "i" in m.group(2) else 0, f.name))
    return out


def all_fbc_strings(extra: list[str]) -> list[str]:
    s = set(STATE_STRINGS) | {"NOT_EVALUATED"} | set(extra)
    for h in ALL_H:
        for ent in FBC_TEXT_IDS:
            s.update(h.published(ent))
    return sorted(s)


# ===========================================================================
# Mutation matrix
# ===========================================================================
def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    n = text.count(old)
    if n != count:
        raise AssertionError(f"mutation anchor occurs {n} times, want {count}: {old[:70]!r}")
    return text.replace(old, new)


def _ins_after_ready(line: str):
    anchor = "            id(failback_shadow_ready) = true;\n"
    return lambda t: mutate(t, anchor, anchor + line)


def _m_eof(t: str) -> str:
    t = mutate(t, scope.INTERVAL_BLOCK, "")
    return t.rstrip("\n") + "\n\n" + scope.INTERVAL_BLOCK.rstrip("\n") + "\n"


E2_GUARD = " && (uint32_t) (lv - id(failback_shadow_ep_last_edge_ms)) < 0x80000000UL) {"
MUTANTS = [
    ("M-C1", "FB-C writes a non-FB global", _ins_after_ready("            id(free_power_restore_requested) = true;\n"), ["Z4", "Z9"]),
    ("M-C2", "FB-C calls commit_record", _ins_after_ready("            ecco_durable::commit_record(0, 0);\n"), ["Z3", "Z7"]),
    ("M-C3", "FB-C presses a button", _ins_after_ready("            id(end_free_power_button).press();\n"), ["Z3"]),
    ("M-C4", "a START gate reads failback_shadow_phase",
     lambda t: mutate(t, "          bool owned =\n            id(free_power_active_persisted) ||",
                      "          bool owned = id(failback_shadow_phase) == 0 ||\n            id(free_power_active_persisted) ||"), ["Z5"]),
    ("M-C5", "a failback_shadow_* global restore_value: yes",
     lambda t: mutate(t, "  - id: failback_shadow_phase\n    type: uint8_t\n    restore_value: no",
                      "  - id: failback_shadow_phase\n    type: uint8_t\n    restore_value: yes"), ["Z6"]),
    ("M-C6", "HA return resets the phase to NONE",
     lambda t: mutate(t, '            ph = 2;\n            ep_event = true;\n            ESP_LOGI("failback_shadow", "episode %08X-%u HA_BACK',
                      '            ph = 0;\n            ep_event = true;\n            ESP_LOGI("failback_shadow", "episode %08X-%u HA_BACK'), ["T-C06"]),
    ("M-C7", "close on the first beat (no P_STABLE_FOR)",
     lambda t: mutate(t, "if (ph == 2 && stable && stable_for >= ${ecco_failback_shadow_episode_close_ms}UL) {",
                      "if (ph == 2 && beat) {"), ["T-C03"]),
    ("M-C8", "detect LOST by sampling the state instead of the counters",
     lambda t: mutate(t, "const uint32_t dle = le - id(failback_shadow_seen_lost);",
                      "const uint32_t dle = (st == 3 && id(failback_shadow_phase) != 1) ? 1 : 0;"), ["T-C06"]),
    ("M-C9", "drop the age re-check in P_STABLE",
     lambda t: mutate(t, "(svc > 0) &&\n                              (age <= ${ecco_supervision_stable_max_gap_ms}UL);",
                      "(svc > 0);"), ["T-C23"]),
    ("M-C10", "open a new episode on re-loss instead of rl++",
     lambda t: mutate(t, "            if (ph == 0 || ph == 3) {", "            if (true) {"), ["T-C07"]),
    ("M-C11", "reference supervision_have_valid in the FB-C interval",
     lambda t: mutate(t, "          const uint32_t now = millis();\n          if (id(supervision_generation) == 0) return;",
                      "          const uint32_t now = millis();\n          // supervision_have_valid\n          if (id(supervision_generation) == 0) return;"),
     ["Z3", "Z3-PRA278"]),
    ("M-C12", "persist via an RTC_NOINIT object", _ins_after_ready("            RTC_NOINIT_ATTR static uint32_t fbc_keep;\n"), ["Z3", "Z7"]),
    ("M-C13", "stable_since latched from the streak clock",
     lambda t: mutate(t, "id(failback_shadow_stable_since_ms) = lv;", "id(failback_shadow_stable_since_ms) = id(supervision_streak_start_ms);"),
     ["T-C03"]),
    ("M-C14", "publish State every tick",
     lambda t: mutate(t, "if (id(failback_shadow_state_text).state != state_s) {", "if (true) {"), ["T-C16", "T-C01"]),
    ("M-C15", "hard-code 300000 in the close expression",
     lambda t: mutate(t, "stable_for >= ${ecco_failback_shadow_episode_close_ms}UL", "stable_for >= 300000UL"), ["Z2"]),
    ("M-C16", "load_record_status probe at E1", _ins_after_ready("            ecco_durable::load_record_status(0, 0);\n"), ["Z3"]),
    ("M-C18", "FB-C interval appended at EOF", _m_eof, ["Z2"]),
    ("M-C19", "unbraced E2 (phase = HA_BACK on every tick)",
     lambda t: mutate(t, "          if (beat && ph == 1" + E2_GUARD, "          ph = 2;\n          if (beat && ph == 1" + E2_GUARD), ["T-C01"]),
    ("M-C22", "E2 without the after-edge guard", lambda t: mutate(t, E2_GUARD, ") {"), ["T-C06b"]),
    ("M-C28", "rb computed from the edge-observation time, not the no-client start",
     lambda t: mutate(t, "id(failback_shadow_noclient_since_ms) + ${ecco_failback_shadow_assumed_reboot_timeout_ms}UL - t_edge",
                      "now + ${ecco_failback_shadow_assumed_reboot_timeout_ms}UL - t_edge"), ["T-C02"]),
    ("M-C30", "FB-C calls make_call()", _ins_after_ready("            id(failback_shadow_state_text).make_call();\n"), ["Z3", "Z4"]),
    ("M-X1", "wr counted without the would-refuse condition",
     lambda t: mutate(t, "if (busy_fp && !id(failback_shadow_busy_fp) && wref_prev) {", "if (busy_fp && !id(failback_shadow_busy_fp)) {"), ["T-C13"]),
    ("M-X2", "trigger classified with the current svc instead of the previous tick's",
     lambda t: mutate(t, "const bool trig_s = (seen_svc == 0);", "const bool trig_s = (svc == 0);"), ["T-C05"]),
    ("M-X3", "t_edge taken from the post-beat last_valid",
     lambda t: mutate(t, ": id(failback_shadow_seen_last_valid_ms) + ${ecco_supervision_lost_ms}UL;", ": lv + ${ecco_supervision_lost_ms}UL;"), ["T-C06"]),
    ("M-X4", "u0 from the wrapped 32-bit clock instead of millis_64()",
     lambda t: mutate(t, "(uint32_t) ((millis_64() - (uint64_t) (uint32_t) (now - t_edge)) / 1000ULL)", "t_edge / 1000"), ["T-C14"]),
    ("M-X5", "histogram boundary off by one at 45 s",
     lambda t: mutate(t, "} else if (g <= 45000UL) {", "} else if (g < 45000UL) {"), ["T-C15"]),
    ("M-X6", "gaps closed inside one tick not counted as missed",
     lambda t: mutate(t, "id(failback_shadow_gaps_missed) = gm_new > 65535UL ? 65535UL : gm_new;",
                      "id(failback_shadow_gaps_missed) = id(failback_shadow_gaps_missed);"), ["T-C15"]),
    ("M-X7", "START counted on the busy LEVEL every tick, not on the idle->busy edge",
     lambda t: mutate(t, "if (busy_fp && !id(failback_shadow_busy_fp) && wref_prev) {", "if (busy_fp && wref_prev) {"), ["T-C13"]),
]

BEHAVIOURAL = {k: v for k, v in SCENARIOS.items()}
BEHAVIOURAL["Z9"] = z9_probe


def run_detector(name: str, ctx: Ctx):
    """-> (status, violations). status 'ok' | 'error' (mutant not executable)."""
    try:
        if name in STATIC_DETECTORS:
            return "ok", STATIC_DETECTORS[name](ctx)
        return "ok", BEHAVIOURAL[name](ctx.fw)
    except ds.Unsupported as ex:
        return "error", [f"Unsupported: {ex}"]
    except Exception as ex:  # noqa: BLE001 - any other failure is a detection
        return "ok", [f"{type(ex).__name__}: {ex}"]


# ===========================================================================
# main
# ===========================================================================
def main() -> int:
    global BASE_TEXT, BASE
    ctx = Ctx(FW_TEXT)

    # -----------------------------------------------------------------------
    print("[0] Change scope: FB-C1 is a pure insertion of four blocks")
    # -----------------------------------------------------------------------
    try:
        BASE_TEXT = scope.pre_fbc1_text(FW_TEXT)
        ok_rev = True
    except AssertionError as ex:
        ok_rev, BASE_TEXT = False, FW_TEXT
        print("   ", ex)
    check("every FB-C1 block occurs exactly once in the firmware, directly at its anchor", ok_rev)
    check("reverting exactly FB-C1's four blocks reproduces the FB-C1 base byte-for-byte (sha256 pin == the chain's dump_v2 "
          "checkpoint, main @ ca7474e / be143cd) and equals the chain's as-of-dump_v2 view of the live firmware",
          scope.sha(BASE_TEXT) == scope.BASE_FW_SHA == CH.checkpoint(chain.FIRMWARE, "dump_v2")
          and BASE_TEXT == CH.as_of(chain.FIRMWARE, "dump_v2", LIVE_FW_TEXT), scope.sha(BASE_TEXT))
    check("applying FB-C1 to that base reproduces the firmware exactly (round trip)", scope.add_fbc1_text(BASE_TEXT) == FW_TEXT)
    BASE = ds.load_firmware_text(BASE_TEXT)
    added_lines = len(FW_TEXT.splitlines()) - len(BASE_TEXT.splitlines())
    check("the change is additions only (no base line removed or altered)", FW_TEXT.count("\n") - BASE_TEXT.count("\n") == added_lines
          and all(FW_TEXT.find(b) >= 0 for b in (scope._SUBS_ANCHOR, scope._GLOBALS_ANCHOR, scope._TEXT_ANCHOR, scope._INTERVAL_ANCHOR)))
    changed = sorted(k for k in set(tree(BASE)) | set(tree(FW)) if BASE.get(k) != FW.get(k))
    check("only substitutions, globals, text_sensor and interval differ in the parsed firmware",
          changed == ["_substitutions", "globals", "interval", "substitutions", "text_sensor"], str(changed))
    add_g = [g for g in FW["globals"] if g not in BASE["globals"]]
    add_t = [t for t in FW["text_sensor"] if t not in BASE["text_sensor"]]
    add_i = [i for i in FW["interval"] if i not in BASE["interval"]]
    add_s = {k: v for k, v in SUBS.items() if k not in BASE["_substitutions"]}
    check("change-surface counts: +5 substitutions, +42 globals, +5 text sensors, +1 interval",
          (len(add_s), len(add_g), len(add_t), len(add_i)) == (5, 42, 5, 1), str((len(add_s), len(add_g), len(add_t), len(add_i))))
    check("no base item removed or reordered (globals / text_sensor / interval)",
          [g for g in FW["globals"] if g in BASE["globals"]] == BASE["globals"]
          and [t for t in FW["text_sensor"] if t in BASE["text_sensor"]] == BASE["text_sensor"]
          and [i for i in FW["interval"] if i in BASE["interval"]] == BASE["interval"])
    check("the new substitutions are exactly the five pinned names and values",
          add_s == scope.SUBSTITUTIONS, str(add_s))
    check("the new globals are exactly _fbc_scope.GLOBALS, in order, with their types and initial values",
          [(g["id"], g["type"], str(g["initial_value"])) for g in add_g] == scope.GLOBALS)
    base_subs = dict(BASE["_substitutions"])
    check("every pre-existing substitution is unchanged and none removed; the ONLY additions are the five exact key -> value "
          "pairs (no prefix exemption)",
          {k: SUBS.get(k) for k in base_subs} == base_subs and dict(SUBS) == {**base_subs, **FBC1_SUBSTITUTIONS}
          and not set(base_subs) & set(FBC1_SUBSTITUTIONS), str(set(SUBS.items()) ^ set({**base_subs, **FBC1_SUBSTITUTIONS}.items())))
    check("FB-C1 adds no include, header, script, button, switch, number, select, binary_sensor, sensor or API action",
          all(BASE.get(d) == FW.get(d) for d in ("esphome", "api", "script", "button", "switch", "number", "select",
                                                 "binary_sensor", "sensor", "wifi", "ota", "logger", "debug")))
    later_headers = {Path(f).name for e in CH.after("fbc1") for f in e.added_files if f.startswith("firmware/include/")}
    check("the firmware headers are untouched by name (no FB-C header in FB-C1; a header a LATER chain entry declares it adds "
          "is that entry's)",
          sorted(p.name for p in (ROOT / "firmware" / "include").glob("*") if p.name not in later_headers) ==
          ["ecco_durable_snapshot.h", "ecco_fallback_profile.h", "ecco_recovery_evidence.h"])

    # -----------------------------------------------------------------------
    print("")
    print("[S] FB-T0 scope-chain registration (registry/tests/_scope_chain.py entry `fbc1`): exact, nothing by prefix")
    # -----------------------------------------------------------------------
    e = CH.entry("fbc1")
    check("fbc1 is appended to the chain directly after dump_v2 (merge order on main; later PRs append after it)",
          CH.ids()[:4] == ["fba", "mtou1", "dump_v2", "fbc1"], str(CH.ids()))
    check("fbc1's only reverter is _fbc_scope.pre_fbc1_text, on the firmware YAML only (no header / registry / manifest edit)",
          dict(e.reverts) == {chain.FIRMWARE: scope.pre_fbc1_text} and set(e.checkpoints) == {chain.FIRMWARE})
    check("fbc1's firmware checkpoint is the sha256 of the firmware as of fbc1, and reverting fbc1 reproduces dump_v2's checkpoint",
          e.checkpoints[chain.FIRMWARE] == scope.sha(FW_TEXT)
          and scope.sha(scope.pre_fbc1_text(FW_TEXT)) == CH.checkpoint(chain.FIRMWARE, "dump_v2") == scope.BASE_FW_SHA)
    check("fbc1 declares EXACTLY +42 globals, +1 interval, +5 text sensors, +5 substitutions - and no other metric (Modbus "
          "reads/writes, commit/load/status sites, durable tag strings, scripts, controls, API actions, includes all 0)",
          dict(e.deltas) == {"globals": 42, "intervals": 1, "text_sensors": 5, "substitutions": 5}
          and dict(e.deltas) == {"globals": len(scope.GLOBALS), "intervals": 1, "text_sensors": len(scope.TEXT_SENSORS),
                                 "substitutions": len(scope.SUBSTITUTIONS)}, str(dict(e.deltas)))
    check("fbc1 declares exactly the five substitution key -> value pairs (== _fbc_scope.SUBSTITUTIONS), changes and removes none",
          dict(e.subst_added) == FBC1_SUBSTITUTIONS == scope.SUBSTITUTIONS and dict(e.subst_changed) == {} and tuple(e.subst_removed) == (),
          str(dict(e.subst_added)))
    check("fbc1 declares no op path, no include, no FB-A-header includer, no banned-token FILE, no tag",
          e.op_paths_changed == frozenset() and e.includes_added == () and e.fbh_includers == frozenset()
          and e.banned_files == frozenset() and e.tags_declared == frozenset() and e.tags_promoted == frozenset())
    _banned_by_block = {name: len(chain.BANNED.findall(block)) for name, block, _w, _a in scope.EDITS}
    check("fbc1 declares exactly 14 FB-A banned-token occurrences in the firmware YAML, all inside FB-C1's own blocks "
          "(5 substitution keys + 9 ${ecco_failback_shadow_*} references in the interval; 0 in globals / text sensors)",
          e.banned_fw_added == 14 == sum(_banned_by_block.values()) and _banned_by_block == scope.BANNED_FW_BY_BLOCK
          and len(chain.BANNED.findall(FW_TEXT)) - len(chain.BANNED.findall(BASE_TEXT)) == 14, str(_banned_by_block))
    check("fbc1 declares exactly the three test files it adds; none is a firmware header",
          e.added_files == scope.ADDED_FILES and all((ROOT / f).is_file() for f in e.added_files)
          and not any(f.startswith("firmware/") for f in e.added_files), str(sorted(e.added_files)))
    _rows = [r for r in chain.integrity_report(CH) if r[0].startswith("fbc1:")]
    check("the chain's own integrity report for fbc1 is all green (checkpoint, non-identity reverter, nothing else moved, declared "
          "deltas == measured, op paths, includes, substitution key AND value, no silent change / removal)",
          len(_rows) == 8 and all(ok for _n, ok, _d in _rows), str([(n, d) for n, ok, d in _rows if not ok]))
    _m_prev, _m_fbc = chain.measure(CH.as_of_all("dump_v2")), chain.measure(AS_OF)
    check("measured, not declared: Modbus writes / reads, commit_record / load_record / load_record_status sites and durable tag "
          "strings are identical as of dump_v2 and as of fbc1 (52 / 60, 57 / 7 / 3, 13) - zero Modbus and zero durable / NVS delta",
          all(_m_prev[m] == _m_fbc[m] for m in ("modbus_writes", "modbus_reads", "commit_record", "load_record",
                                                 "load_record_status", "durable_tag_strings"))
          and (_m_fbc["modbus_writes"], _m_fbc["modbus_reads"], _m_fbc["commit_record"], _m_fbc["load_record"],
               _m_fbc["load_record_status"], _m_fbc["durable_tag_strings"]) == (52, 60, 57, 7, 3, 13), str(_m_fbc))
    _ops_prev = chain.per_path_ops(BASE_TEXT, HEADERS)
    _ops_fbc = chain.per_path_ops(FW_TEXT, HEADERS)
    check("measured: every analyzer path's ordered Modbus op list, and the path set, is identical (operation-path delta = 0)",
          _ops_prev == _ops_fbc and len(_ops_fbc) > 0, str(sorted(set(_ops_prev.items()) ^ set(_ops_fbc.items()))[:3]))

    # negative controls: a mis-declared fbc1 entry is refused by the chain, never absorbed by a family / prefix rule
    def _with(**kw) -> "chain.Chain":
        d = {f: getattr(e, f) for f in e.__dataclass_fields__}
        d.update(kw)
        return chain.Chain(CH.upto("dump_v2") + (chain.Entry(**d),))

    def _fails(ch, live, needle) -> bool:
        return any((not ok) and needle in n for n, ok, _d in chain.integrity_report(ch, live))

    _live = {p: AS_OF[p] for p in chain.PINNED}
    _one_off = dict(FBC1_SUBSTITUTIONS)
    _one_off["ecco_failback_shadow_episode_close_ms"] = "300001"
    _missing = {k: v for k, v in FBC1_SUBSTITUTIONS.items() if k != "ecco_failback_shadow_soak_publish_min_ms"}
    check("negative: fbc1 declaring one substitution with the WRONG value is detected",
          _fails(_with(subst_added=_one_off), _live, "substitutions added"))
    check("negative: fbc1 omitting one of its five substitutions from the declaration is detected",
          _fails(_with(subst_added=_missing), _live, "substitutions added"))
    check("negative: fbc1 declaring a sixth substitution the firmware does not carry is detected",
          _fails(_with(subst_added={**FBC1_SUBSTITUTIONS, "ecco_failback_shadow_probe_ms": "1000"}), _live, "substitutions added"))
    check("negative: a prefix / glob substitution declaration (ecco_failback_shadow_*) is refused by Chain() itself",
          _raises(lambda: _with(subst_added={"ecco_failback_shadow_*": "300000"}), chain.ChainError))
    check("negative: a glob banned-file declaration (home-assistant/*.yaml) is refused by Chain() itself",
          _raises(lambda: _with(banned_files=frozenset({"home-assistant/*.yaml"})), chain.ChainError))
    check("negative: fbc1 mis-declaring its banned-token count (13 instead of 14) is detected",
          _fails(_with(banned_fw_added=13), _live, "declared deltas"))
    check("negative: fbc1 declaring a Modbus read it does not add is detected (the zero Modbus delta is measured, not assumed)",
          _fails(_with(deltas={**e.deltas, "modbus_reads": 1}), _live, "declared deltas"))
    check("negative: fbc1 declaring a durable commit site it does not add is detected",
          _fails(_with(deltas={**e.deltas, "commit_record": 1}), _live, "declared deltas"))
    check("negative: fbc1 declaring an op path it does not change is detected",
          _fails(_with(op_paths_changed=frozenset({"free_power_start"})), _live, "op_paths_changed"))
    _extra = '  ecco_failback_shadow_soak_publish_min_ms: "60000"\n'
    _live_x = {**_live, chain.FIRMWARE: mutate(FW_TEXT, _extra, _extra + '  ecco_failback_shadow_extra_ms: "5"\n')}
    check("negative: an UNDECLARED extra ecco_failback_shadow_* substitution in the firmware breaks the chain although five keys "
          "of the same family are declared (no prefix exemption)",
          any(not ok for _n, ok, _d in chain.integrity_report(_with(), _live_x)))
    _live_i = {**_live, chain.FIRMWARE: mutate(FW_TEXT, "          const uint32_t now = millis();\n",
                                               "          const uint32_t now = millis();\n          uint32_t fbc_x = 0;\n")}
    check("negative: ANY undeclared edit inside FB-C1's own interval breaks fbc1's exact reverter / checkpoint",
          any(not ok for _n, ok, _d in chain.integrity_report(CH, _live_i)))

    # -----------------------------------------------------------------------
    print("")
    print("[Z] Static pins Z1-Z8 (run against the real firmware)")
    # -----------------------------------------------------------------------
    zlabels = {
        "Z1": "Z1 write surface unchanged (per-path op lists, register -> writers, 52 writes / 60 reads, FB-C1 delta 0/0)",
        "Z2": "Z2 placement: one 1s interval, then == [lambda(static_asserts only), lambda(tick)], immediately before the PR-A tick, not at EOF",
        "Z3": "Z3 token ban (no Modbus / NVS / RTC / script / control / reboot tokens; no supervision_have_valid in the interval)",
        "Z3-PRA278": "Z3 exactly one interval mentions supervision_have_valid (PR-A pin)",
        "Z4": "Z4 assignments only to failback_shadow_*; publish only to the five FB-C ids; reads inside the read-only allowlist",
        "Z5": "Z5 non-authority: failback_shadow is referenced by no YAML node (or firmware text) outside FB-C's own blocks",
        "Z6": "Z6 every failback_shadow_* global is restore_value: no; the restore_value: yes set is unchanged",
        "Z7": "Z7 durable surface unchanged (57 commit / 7 load / 3 status sites, no RTC/NVS/preference API, header tags unchanged)",
        "Z8": "Z8 no controls added; five diagnostic template text sensors with no lambda/filters/on_value",
    }
    for name, label in zlabels.items():
        v = STATIC_DETECTORS[name](ctx)
        check(label, not v, "; ".join(v))
    # FB-T0: a file a LATER chain entry declares (added_files / banned_files, exact paths) is that entry's; none today.
    later_files = {f for e in CH.after("fbc1") for f in (*e.added_files, *e.banned_files)}
    other = []
    for sub in ("home-assistant", "frontend", "deployment", "influxdb", "health", "tools"):
        for p in (ROOT / sub).rglob("*"):
            if p.is_file() and "node_modules" not in p.parts and p.suffix in (".yaml", ".yml", ".py", ".ts", ".js", ".json", ".md"):
                rel = p.relative_to(ROOT).as_posix()
                try:
                    if rel not in later_files and "failback_shadow" in p.read_text(encoding="utf-8", errors="ignore"):
                        other.append(rel)
                except OSError:
                    pass
    check("Z5 no Home Assistant / frontend / deployment / influx / health / tools file references failback_shadow (beyond files "
          "later chain entries declare)", not other, str(other))
    lam0_asserts = asserts_of(ctx.lam0)
    check("Z2 the five static_asserts live in FB-C's own interval lambda, NOT in on_boot",
          len(lam0_asserts) == 5 and not any("failback_shadow" in a for a in
                                             [b["lambda"] for b in FW["esphome"]["on_boot"]["then"] if "lambda" in b]))
    check("Z2 no hard-coded 300000 / 900000 in the close, edge or reboot-margin expressions",
          "300000UL" not in re.sub(r"g <= 300000UL", "", ctx.lam1) and "900000UL" not in re.sub(r"g <= 900000UL", "", ctx.lam1))

    # -----------------------------------------------------------------------
    print("")
    print("[T] Behaviour - the REAL lambdas through _dump_sim + _fbc_harness (every FB-C invocation Z9-checked)")
    # -----------------------------------------------------------------------
    tlabels = {
        "T-C01": "T-C01 boot + beats every 30 s for 10 min: WATCH until the 3rd beat then IDLE, phase NONE, stable_since, b0 = beats - 1",
        "T-C02": "T-C02 beats stop (HA stops): E1 at last_valid + 300 s, tr=H, cli=0, rb ~ 600, State SHADOW_EPISODE",
        "T-C03": "T-C03 beats resume: HA_BACK with exact ret/gap; closes at the first tick >= return + 360 s, never earlier; fbf '-'",
        "T-C04": "T-C04 identical episode records under fbc-first / pra-first / swapped / 20 random offset+drift schedules",
        "T-C05": "T-C05 no beat since boot: E1 at uptime 300 s, tr=S, no SUSPECT; trigger stays S when a beat shares the tick",
        "T-C06": "T-C06 beat 1 s after the edge -> HA_BACK, same episode; edge + return inside one FB-C tick still opens the episode",
        "T-C06b": "T-C06b synthetic: a beat older than the edge never returns an OPEN episode (after-edge guard)",
        "T-C07": "T-C07 flapping (return, 120 s of beats, 301 s loss, return): one episode, rl = 1, OPEN -> HA_BACK -> OPEN -> HA_BACK",
        "T-C08": "T-C08 one skipped beat while HA_BACK: stable_since re-latched, closes 300 s after the re-qualified Stable",
        "T-C09": "T-C09 HA up, heartbeat dead (cli=1): rb '-', episode OPEN for 2 simulated hours, no restart assumed",
        "T-C10": "T-C10 ESP reboot mid-episode: nothing survives, new nonce, new trigger-S episode at 300 s; zero NVS/Modbus/script",
        "T-C11": "T-C11 API client flicker: nc + 1, ncm = 20 s; a sub-second socket between ticks is invisible",
        "T-C12": "T-C12 15-min restart loop, 5 boots then HA returns at 120 s: per-boot trigger-S episodes, rb = 600, nothing carried",
        "T-C13": "T-C13 wr counters: START while WATCH / failed START / R244 while OPEN / Dump while HA_BACK; none when stable+idle or after close",
        "T-C14": "T-C14 millis() wrap during an OPEN episode: durations continuous; u0 from millis_64() (edge before and after the wrap)",
        "T-C15": "T-C15 gaps 29/35/44/45/46/91/299/301 s: exact buckets and edges, lg immediate, two beats in one tick -> gm + 1",
        "T-C16": "T-C16 de-duplication: 1 h steady state, 0 State/Episode publishes; Soak <= 1/min under 1 Hz churn, final value flushed",
        "T-C17": "T-C17 worst-case Episode and Soak strings <= 200 chars (all phases, all maxima)",
        "T-C18": "T-C18 supervision_generation == 0: zero changes (including FB-C's own globals), nothing published",
        "T-C19": "T-C19 the five static_asserts hold; each violating substitution set is rejected; reboot-policy coupling",
        "T-C23": "T-C23 FB-C before the PR-A tick at age 45.3 s with supervision_stable still true: P_STABLE false, no close",
        "T-C30": "T-C30 FB-C1 build: Verdict/Inputs NOT_EVALUATED, fbf '-', no would-latch, P_WOULD_REFUSE = WATCH or open",
    }
    results = {}
    for name, label in tlabels.items():
        fails = SCENARIOS[name](FW)
        results[name] = fails
        check(label, not fails, "; ".join(fails[:3]))
    inv = sum(h.fbc_invocations for h in ALL_H)
    viol = [v for h in ALL_H for v in h.violations]
    print("")
    check(f"T-C22/Z9 zero side effects on EVERY FB-C invocation across the whole matrix ({inv} invocations, {len(ALL_H)} harnesses): "
          "only failback_shadow_* globals change; modbus_log, nvs, nvs_commits, events, executed unchanged; only the five FB-C "
          "text sensors published; only allow-listed entities read", inv > 50_000 and not viol, f"{inv} invocations; {viol[:3]}")
    check("Z9 also holds on the representative probe run", not z9_probe(FW))

    # -----------------------------------------------------------------------
    print("")
    print("[Z11] String bounds and the Energy Actions card's regex literals")
    # -----------------------------------------------------------------------
    worst, _h = worst_case_strings(FW)
    rx = card_regexes()
    check("the card's regex literals were imported from the TypeScript source (>= 19 distinct, incl. ^FAILED and ^REJECTED/^BLOCKED)",
          len(rx) >= 19 and any(p == "^FAILED" for p, _, _ in rx) and any(p == "^BLOCKED" for p, _, _ in rx), str(len(rx)))
    strs = all_fbc_strings(worst)
    check(f"every string FB-C published in the matrix ({len(strs)} distinct) is <= 200 chars (worst case {max(map(len, strs))})",
          all(len(s) <= 200 for s in strs))
    hits = [(s[:60], p, o) for s in strs for p, fl, o in rx if re.search(p, s, fl)]
    check("no FB-C string (states, episodes, soaks, worst cases, NOT_EVALUATED) matches any card regex, case-insensitively",
          not hits, str(hits[:3]))
    published_states = {s for h in ALL_H for s in h.published(STATE)}
    check("the State strings FB-C1 can publish are exactly SHADOW_EPISODE / _HA_BACK / WATCH / IDLE (SHADOW_BOOT is never "
          "published - see STATE_STRINGS), and none is a card trigger",
          published_states == {"SHADOW_EPISODE", "SHADOW_EPISODE_HA_BACK", "SHADOW_WATCH", "SHADOW_IDLE"}
          and not any(re.search(p, s, fl) for s in STATE_STRINGS for p, fl, o in rx), str(published_states))

    # -----------------------------------------------------------------------
    print("")
    print("[C] Host compile of the REAL lambdas (g++ -fsyntax-only -Wall -Wextra -Werror, gnu++17 and gnu++20) against stubs")
    # -----------------------------------------------------------------------
    print(f"    compiler: {CXX}")
    check("a C++ compiler is available ($ECCO_CXX, g++ / c++ / clang++ on PATH, or ESPHome's xtensa GCC) - never skipped",
          CXX is not None, NO_CXX)
    hc_err = host_compile(FW, ctx.lam0, ctx.lam1)
    check("the FB-C static_assert lambda and the tick lambda compile warning-free against ESPHome-shaped stubs "
          "(types, printf formats, ternaries, snprintf into char[201])", not hc_err, "; ".join(hc_err)[:400])
    neg = host_compile(FW, ctx.lam0, ctx.lam1, extra_tick='\n  id(failback_shadow_ep) = "not a number";\n')
    neg2 = host_compile(FW, ctx.lam0, ctx.lam1, extra_tick='\n  snprintf(nullptr, 0, "%s", (unsigned) 1);\n')
    bad0 = host_compile(FW, ctx.lam0.replace("< ${ecco_supervision_lost_ms}UL,", "> ${ecco_supervision_lost_ms}UL,", 1), ctx.lam1)
    # a missing compiler must not make the negative controls pass vacuously: each must be a real compile rejection
    check("negative controls: a type error, a printf-format error and a violated static_assert are each rejected by the compile",
          all(n and NO_CXX not in n for n in (neg, neg2, bad0)), f"{neg[:1]} {neg2[:1]} {bad0[:1]}")

    # -----------------------------------------------------------------------
    print("")
    print("[H] Harness self-tests (Phase-0 style)")
    # -----------------------------------------------------------------------
    hs = hx.Harness(FW, trace=True, tie=hx.Harness.TIE_FBC_FIRST, fbc_offset_ms=0, pra_offset_ms=0)
    sim = hs.sim
    sim.now_ms = 5
    check("millis_64(): equals millis() below the wrap", sim.millis() == 5 and sim.millis_64() == 5)
    sim.now_ms = WRAP + 7
    check("millis_64(): never wraps; millis() is its low 32 bits", sim.millis() == 7 and sim.millis_64() == WRAP + 7)
    sim.millis64_offset_ms = 400
    check("millis_64(): a constant sub-second offset from millis() can be modelled", sim.millis_64() == WRAP + 407)
    sim.millis64_offset_ms = 0
    sim.run_lambda("uint64_t x = millis_64(); id(failback_shadow_ep_edge_uptime_s) = (uint32_t) (x / 1000ULL);")
    check("the transpiler executes millis_64() inside a real lambda", sim.g["failback_shadow_ep_edge_uptime_s"] == (WRAP + 7) // 1000)
    hs = hx.Harness(FW, trace=True, tie=hx.Harness.TIE_FBC_FIRST, fbc_offset_ms=0, pra_offset_ms=0)
    hs.schedule_beats([1000])
    hs.run_until(2000)
    order = [w for _, w in hs.log]
    check("order control: same-ms tie with fbc_first runs the heartbeat, then FB-C, then the PR-A tick",
          order[:2] == ["fbc", "pra"] and order[2:5] == ["beat", "fbc", "pra"], str(order))
    hs2 = hx.Harness(FW, trace=True, tie=hx.Harness.TIE_PRA_FIRST, fbc_offset_ms=0, pra_offset_ms=0)
    hs2.run_until(2000)
    check("order control: pra_first reverses the same-ms tie", [w for _, w in hs2.log][:2] == ["pra", "fbc"])
    firsts = set()
    traces = {}
    for sd in range(40):
        a = hx.Harness(FW, seed=sd, trace=True)
        a.run_until(1600)
        firsts.add(a.log[0][1])
        traces[sd] = a.log
        b = hx.Harness(FW, seed=sd, trace=True)
        b.run_until(1600)
        if a.log != b.log:
            firsts.add("NONDETERMINISTIC")
    check("randomised initial offsets produce BOTH tick orders across seeds, deterministically per seed", firsts == {"fbc", "pra"}, str(firsts))
    hd = hx.Harness(FW, seed=3, drift_ms=40, trace=True, fbc_offset_ms=0, pra_offset_ms=0)
    hd.run_until(20_000)
    ts = [t for t, w in hd.log if w == "fbc"]
    check("per-execution drift makes the interval non-periodic (phase relation can change)", len({b - a for a, b in zip(ts, ts[1:])}) > 1)
    hc = hx.Harness(FW, fbc_offset_ms=0, pra_offset_ms=0)
    check("api_client_connected model: False at boot, settable, read by the FB-C tick",
          hc.sim.ent("api_client_connected_sensor").state is False)
    hc.set_client(True)
    hc.run_until(1500)
    check("api_client_connected model: the tick saw the connected state", hc.g("failback_shadow_client_seen") is True)
    hr = hx.Harness(FW, seed=1)
    hr.schedule_beats([1000])
    hr.run_until(5000)
    n0, old_sim = hr.nonce, hr.sim
    hr.reboot()
    check("reboot(): a new simulator (RAM and clock), a new nonce, FB-C globals at their initial values",
          hr.sim is not old_sim and hr.nonce != n0 and hr.sim.now_ms == 0 and hr.g("failback_shadow_ready") is False
          and hr.g("supervision_valid_count") == 0 and hr._beat_times == [])
    hj = hx.Harness(FW, fbc_offset_ms=250, pra_offset_ms=750)
    hj.jump_to(WRAP - 1000)
    check("jump_to(): the clock leaps, both intervals are re-phased from the new time",
          hj.sim.now_ms == WRAP - 1000 and hj.fbc_next == WRAP - 750 and hj.pra_next == WRAP - 250)
    check("tick_at_or_after(): first FB-C tick at or after a time", tick_at_or_after(1250) == 1250 and tick_at_or_after(1251) == 2250
          and tick_at_or_after(0) == 250)
    # Z9 has teeth: a FB-C lambda that writes a non-FB global, publishes a foreign entity or reads a foreign entity is caught
    bad = mutate(FW_TEXT, "            id(failback_shadow_ready) = true;\n",
                 "            id(failback_shadow_ready) = true;\n            id(free_power_restore_requested) = true;\n"
                 "            id(dump_status).publish_state(\"x\");\n")
    hb = hx.Harness(ds.load_firmware_text(bad), fbc_offset_ms=0, pra_offset_ms=0)
    hb.run_until(2000)
    vtxt = " ".join(hb.violations)
    check("Z9 negative control: a non-FB global write, a foreign publish and a foreign entity read are each reported",
          "non-FB globals" in vtxt and "published" in vtxt and "accessed" in vtxt, vtxt[:200])
    check("Z9 negative control: the real firmware has none", not hx.Harness(FW, fbc_offset_ms=0, pra_offset_ms=0).violations)

    # -----------------------------------------------------------------------
    print("")
    print("[Z12] Mutation kill matrix (each mutant is caught by the detector aimed at it)")
    # -----------------------------------------------------------------------
    # every detector used below must be green on the real firmware first
    names = sorted({d for _, _, _, ds_ in MUTANTS for d in ds_})
    base_ok = {}
    for n in names:
        st, v = run_detector(n, ctx)
        base_ok[n] = (st == "ok" and not v)
    check("every detector used by the matrix passes on the real firmware", all(base_ok.values()),
          str([n for n, ok in base_ok.items() if not ok]))
    scratch: list = []
    _SINK[0] = scratch
    killed = 0
    for mid, desc, fn, dets in MUTANTS:
        try:
            mtext = fn(FW_TEXT)
            mctx = Ctx(mtext)
        except Exception as ex:  # noqa: BLE001
            check(f"{mid}: {desc}", False, f"mutant could not be built: {type(ex).__name__}: {ex}")
            continue
        caught, errs = [], []
        for d in dets:
            st, v = run_detector(d, mctx)
            if st == "error":
                errs.append(f"{d}: {v[0]}")
            elif v:
                caught.append(d)
        ok = not errs and set(caught) == set(dets)
        killed += ok
        check(f"{mid}: {desc} -> killed by {'+'.join(dets)}", ok, f"caught={caught} errors={errs}")
        for n, _ in MUTANTS and []:
            pass
    _SINK[0] = ALL_H
    print(f"  mutants killed: {killed}/{len(MUTANTS)}")
    check(f"at least 25 distinct mutants, every one killed ({len(MUTANTS)} defined)", len(MUTANTS) >= 25 and killed == len(MUTANTS))

    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    print("(These execute the firmware SOURCE under registry/tests/_dump_sim.py. They do not prove ESPHome timing, the")
    print(" compiled binary, or any live behaviour - only `esphome compile` and the LP-C1 soak can.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
