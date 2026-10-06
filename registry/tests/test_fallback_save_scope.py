#!/usr/bin/env python3
"""FB-B2 (Fallback Profile SAVE / REPLACE CORRUPT / INVALIDATE) - change scope, FB-T0 scope-chain registration and the
MEASUREMENT REPORT.

SCOPE: test infrastructure. FB-B2 is the first firmware that WRITES the durable Fallback Profile: witness FBW first, then
profile FBP, through the one FB-B0 transaction writer (`ecco_fbdurable::commit_transition_t`), plus the operator surface
(api action `fallback_profile_execute`, the arm switch, two scripts, a second housekeeping lambda). It does NOT add a Modbus
operation (SAVE re-reads through the four FC03 nodes the Review already has), an inverter write, a durable tag/key or a
substitution. It edits the firmware YAML in twenty-one places (registry/tests/_fbb2_scope.py), fourteen of them inside
FB-B1's own text. Older suites are NOT re-hashed: they are anchored at their own chain entry and the entry `fbb2` reverts
FB-B2's edits exactly (newest first, so BEFORE fbb1).

This suite proves that entry, that the revert is exact and complete, what FB-B2 edits in EXISTING code, and it prints the
MEASUREMENT REPORT the owner asked for: every quantity is computed live (base = the exact reverter, cross-checked against
`git show <main @ 65e4be5>:...` whenever that commit is available; head = the working tree) and compared with the declared
chain Entry and with independently typed expectations.

CHAIN-ANCHORED (FB-T0): the firmware this suite proves things about is the artifact AS OF fbb2 - `CHAIN.as_of_all("fbb2",
live)`, an identity while fbb2 is the newest entry - and every chain-level proof runs over the chain that ends at fbb2
(`CH2`). A later PR that appends an entry (and edits the firmware) therefore does not turn this suite red.

  [0] The scope module: twenty-one hunks, each present exactly once at its anchor; exact revert; round trip; independent of
      revert order; every hunk individually missing / duplicated / altered is refused; the git base cross-check
  [1] What FB-B2 edits in EXISTING code: the line diff against the base is ONLY the declared hunks (fourteen insertions, seven
      one-line replacements, no deletion); the seven replaced lines are pinned from -> to; every other pre-existing item of
      every parsed section is identical; the scripts / interval / on_boot / api differ only where declared
  [2] The inserted blocks against the parsed firmware and the scope tables: globals, scripts, the arm switch, the api action,
      the dispatch, the two commit lambdas, no Modbus, supervision / NTP / arm / key / log accounting (named STATIC PINS)
  [3] FB-T0 scope-chain registration (entry `fbb2`): exact declarations, checkpoint, banned count, includes, added files
  [4] THE MEASUREMENT REPORT (printed) and the facts it must satisfy: Modbus reads / writes, analyzer paths, durable call
      sites, tags / keys, banned tokens, added files
  [5] Negative controls: every mis-declaration and every undeclared edit is refused by the chain, never absorbed
  [6] The ledger of older pins and support modules this PR edited (each commented `FB-B2:` or `FB-B2 (D8):`, none weakened;
      complete by construction: every pre-existing suite that mentions FB-B2 is listed, with an exact-content check)
  [7] MUTANTS: a broken copy of the thing under test per decision, each KILLED by a named check
"""

from __future__ import annotations

import difflib
import hashlib
import random
import re
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _dump_sim as ds  # noqa: E402
import _fbb1_scope as scope1  # noqa: E402
import _fbb2_scope as scope  # noqa: E402
import _fbb_scope as fbbs  # noqa: E402
import _fbc_scope as fbcs  # noqa: E402
import _scope_chain as chain  # noqa: E402
import _tag_inventory as ti  # noqa: E402

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


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    """Exact-count replace: raises if the anchor does not occur exactly `count` times (a mutant must hit what it aims at)."""
    found = text.count(old)
    if found != count:
        raise AssertionError(f"mutation anchor {old[:70]!r} found {found}x, expected {count}")
    return text.replace(old, new)


# ---------------------------------------------------------------------------------------------------------------------------
# Typed expectations (written out HERE, independently of _fbb2_scope and of the chain entry: [3] / [4] check all three agree)
# ---------------------------------------------------------------------------------------------------------------------------
FIRMWARE_REL = chain.FIRMWARE
FBB1_FW_SHA = "aa0d9f5286f8613d20957af1b561134007bfc69d8b50f0528295548b6e0d24de"       # main @ 65e4be5 == the chain's fbb1 checkpoint
BASE_COMMIT = "65e4be5c2077d65e8ba5979a8925e473ab6689e3"
# The 20 chain metrics of the FB-B1 state (measured at main @ 65e4be5; FB-B2 testinfra brief section 0).
FBB1_METRICS = {
    "scripts": 33, "globals": 510, "api_actions": 2, "intervals": 11, "sensors": 164, "binary_sensors": 25, "text_sensors": 77,
    "switches": 9, "buttons": 29, "numbers": 30, "selects": 13, "commit_record": 57, "load_record": 7, "load_record_status": 3,
    "modbus_writes": 52, "modbus_reads": 64, "substitutions": 40, "includes": 7, "durable_tag_strings": 13, "banned_fw": 27,
}
FBB2_DELTAS = {"scripts": 2, "globals": 18, "api_actions": 1, "switches": 1, "includes": 1}
FBB2_BANNED = 12
FBB2_METRICS = {k: v + FBB2_DELTAS.get(k, 0) + (FBB2_BANNED if k == "banned_fw" else 0) for k, v in FBB1_METRICS.items()}
FBB2_OP_PATHS = frozenset({"fallback_profile_save"})
FBB2_SCRIPTS = ("fallback_profile_save", "fallback_profile_invalidate")
FBB2_NEW_INCLUDE = "include/ecco_fallback_save.h"
FBB2_PATHS = (46, 47)                      # analyzer paths: FB-B1 state, FB-B2 state
FBB1_READS = [(230, 3), (241, 53), (230, 3), (241, 53)]
COMMIT_LAMBDAS = ("script:fallback_profile_capture_dispatch/then[7]", "script:fallback_profile_invalidate/then[0]")
KEYS = {"FBP": (1609458070, 0x5FEE6196, "ecco_fallback_profile_v1", "FALLBACK_PROFILE_KEY"),
        "FBW": (1000595297, 0x3BA3DF61, "ecco_failback_provision_v1", "FAILBACK_PROVISION_KEY"),
        "FBS": (2156168643, 0x808485C3, "ecco_failback_state_v1", "FAILBACK_STATE_KEY")}
INCLUDE_DIR = ROOT / "firmware" / "include"
NEW_HEADER = "ecco_fallback_save.h"
DURABLE_ADAPTER = "ecco_fallback_durable.h"
DURABLE_MODEL = "ecco_fallback_durable_model.h"

# Tokens no FB-B2 INSERTION may contain (a write side the design does NOT have / authority / forbidden-feature symbol).
# Deliberately absent from this list: `commit_transition_t` (exactly two call sites, pinned separately) and `upervision` (the one
# heartbeat snapshot line of the api action, pinned separately).
FORBIDDEN = re.compile(
    r"nvs_set|nvs_commit|nvs_erase|esp_restart|\bApp\.|global_preferences|make_preference|preference_for|commit_record|"
    r"load_record|write_one_|WriteTarget|self_partial|start_journal|modbus_client\.|write_multiple|write_single|uart\.write|"
    r"queue_command|send_raw|safe_reboot|set_reboot_timeout|api\.respond|homeassistant\.|http_request", re.IGNORECASE)


def banned_leaks() -> list[str]:
    """The FB-A scan (test_fallback_profile_schema.py [9]): every file under home-assistant/, frontend/, deployment/ that
    carries a banned token, exact repo-relative POSIX paths."""
    return sorted(p.relative_to(ROOT).as_posix() for d in ("home-assistant", "frontend", "deployment") if (ROOT / d).is_dir()
                  for p in (ROOT / d).rglob("*") if p.is_file() and "node_modules" not in p.parts
                  and chain.BANNED.search(p.read_text(encoding="utf-8", errors="ignore")))


def banned_files_agree(ch: "chain.Chain", leaks) -> bool:
    """The same equality [9] checks: the live leak set == the set the chain declares."""
    return set(leaks) == set(ch.declared_banned_files())


# ---------------------------------------------------------------------------------------------------------------------------
# git (optional cross-check; the suite never depends on it: a shallow clone without the base commit skips it, explicitly)
# ---------------------------------------------------------------------------------------------------------------------------
def git_show(rev_path: str):
    try:
        r = subprocess.run(["git", "show", rev_path], cwd=ROOT, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8").replace("\r\n", "\n") if r.returncode == 0 else None


def git_base_headers():
    """{name: text} of firmware/include/*.h at BASE_COMMIT, or None when git / the commit is not available."""
    try:
        r = subprocess.run(["git", "ls-tree", "--name-only", BASE_COMMIT, "firmware/include/"], cwd=ROOT, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for rel in r.stdout.decode("utf-8").split():
        if rel.endswith(".h"):
            t = git_show(f"{BASE_COMMIT}:{rel}")
            if t is None:
                return None
            out[Path(rel).name] = t
    return out or None


# ---------------------------------------------------------------------------------------------------------------------------
# Parsed-firmware helpers
# ---------------------------------------------------------------------------------------------------------------------------
_CACHE: dict = {}


def _cached(kind: str, text: str, fn):
    """Memoise a pure function of one text by its sha256 (the 740 KB SAVE header is scanned by many surveys)."""
    key = (kind, sha(text))
    if key not in _CACHE:
        _CACHE[key] = fn(text)
    return _CACHE[key]


def strip_cpp(code: str) -> str:
    return _cached("strip", code, ti.strip_comments)


def tag_inventory(text: str) -> list:
    return _cached("inv", text, ti.inventory)


def durable_literals(text: str) -> set:
    return _cached("lit", text, ti.durable_literals)


def labelled_roots(fw: dict):
    """[(location prefix, node)] covering the whole parsed firmware: every item of a list section is `<section>:<id | name | index>`,
    every api action is `api:<action>`, every other section is its own name."""
    roots = []
    for sec, val in fw.items():
        if sec.startswith("_") or not isinstance(val, (dict, list)):
            continue
        if isinstance(val, list):
            for i, item in enumerate(val):
                label = (item.get("id") or item.get("name") or item.get("action")) if isinstance(item, dict) else None
                roots.append((f"{sec}:{label if label else i}", item))
        elif sec == "api":
            for a in val.get("actions", []):
                roots.append((f"api:{a.get('action')}", a))
            roots.append(("api", {k: v for k, v in val.items() if k != "actions"}))
        else:
            roots.append((sec, val))
    return roots


def lambdas_of(fw: dict) -> list:
    """[(location, lambda text)] for every `lambda` string of the parsed firmware (actions, conditions, on_boot, switch /
    button automations ...). A location is `<root>/<path>` (see labelled_roots)."""
    out: list = []

    def walk(node, loc):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "lambda" and isinstance(v, str):
                    out.append((loc, v))
                else:
                    walk(v, f"{loc}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{loc}[{i}]")

    for loc, node in labelled_roots(fw):
        walk(node, loc)
    return out


def raw_scripts(text: str) -> dict:
    sec = text[text.index("\nscript:\n"):text.index("\nbutton:\n  - platform: restart\n")]
    parts = re.split(r"(?m)^(?=  - id: \w+$)", sec)
    return {re.match(r"  - id: (\w+)", p).group(1): p for p in parts[1:]}


def item_kinds(items) -> list:
    return [list(a)[0] if isinstance(a, dict) else str(a) for a in items]


class Ctx:
    """One firmware text, parsed once, with the lookups the static pins use. Never raises on a damaged text beyond the YAML load."""

    def __init__(self, text: str):
        self.text = text
        self.fw = chain.load_fw(text)
        self.lams = lambdas_of(self.fw)
        self.scripts = {s["id"]: s for s in self.fw["script"]}

    def lam_text(self, loc: str) -> str:
        return next((t for l, t in self.lams if l == loc), "")

    def code(self) -> str:
        return "\n".join(strip_cpp(t) for _l, t in self.lams)

    def fb_lams(self) -> list:
        """The lambdas of the Fallback Profile code: the FB scripts, the execute api action, the arm switch, and any other lambda
        (boot, interval) that names an FB symbol."""
        return [(l, t) for l, t in self.lams if l.startswith(("script:fallback_profile", "api:fallback_profile", "switch:ECCO Fallback"))
                or re.search(r"fallback_profile|fallback_durable|ecco_fb|ecco_fallback", t)]

    def fb_code(self) -> str:
        return "\n".join(strip_cpp(t) for _l, t in self.fb_lams())


STATIC: dict = {}


def static(name: str, label: str):
    def deco(fn):
        STATIC[name] = (label, fn)
        return fn
    return deco


# ---------------------------------------------------------------------------------------------------------------------------
# STATIC PINS (each runs on the real firmware in [2] and on a mutated copy in [7])
# ---------------------------------------------------------------------------------------------------------------------------
ARM_SWITCH = {"platform": "template", "name": "ECCO Fallback Profile Arm", "id": "fallback_profile_arm", "optimistic": True,
              "restore_mode": "ALWAYS_OFF", "icon": "mdi:shield-key-outline",
              "turn_on_action": [{"lambda": "id(fallback_profile_arm_on_ms) = millis();"}]}
HB_LINE = "id(fallback_profile_exec_hb_ok) = (id(supervision_state) == 1) && id(supervision_stable);"
HB_COMMIT_LINE = "if (!((id(supervision_state) == 1) && id(supervision_stable))) {"   # FB-B2 hardening: SAVE_FINAL part 2, right before the commit
EXECUTE_ROUTE = "return ecco_fbsave::is_invalidate_action(id(fallback_profile_exec_action).c_str(), id(fallback_profile_exec_action).size());"


@static("S-SWITCH", "the arm switch: ONE new template switch, appended last, ALWAYS_OFF, optimistic, its turn_on_action only stamps the lifetime start; no 'upervision'")
def s_switch(c: Ctx) -> list:
    v = []
    sw = c.fw["switch"]
    if len(sw) != 10 or sw[-1] != ARM_SWITCH:
        v.append(f"the last switch is not exactly the arm switch: {sw[-1] if sw else None}")
    if sum(1 for s in sw if s.get("id") == "fallback_profile_arm" or "Fallback Profile Arm" in str(s.get("name"))) != 1:
        v.append("the arm switch is not declared exactly once")
    if "upervision" in yaml.dump(sw[-1]):
        v.append("the arm switch names supervision")
    if sw[-1].get("restore_mode") != "ALWAYS_OFF":
        v.append("the arm is not restore_mode: ALWAYS_OFF")
    if any(k in sw[-1] for k in ("turn_off_action", "on_turn_on", "on_turn_off", "lambda", "state")):
        v.append("the arm switch carries an automation other than the one turn_on_action stamp")
    return v


@static("S-ARM-FW", "the firmware only ever turns the arm OFF (7 turn_off sites in the 5 allowed scripts / the tick) and reads it (3 .state reads); no turn_on / toggle / publish_state / control")
def s_arm(c: Ctx) -> list:
    v = []
    uses = []
    for loc, t in c.lams:
        for m in re.finditer(r"id\(fallback_profile_arm\)\s*(\.|->)\s*(\w+)", strip_cpp(t)):
            uses.append((loc.split("/")[0], m.group(2)))
    ops = Counter(op for _l, op in uses)
    if set(ops) - {"turn_off", "state"}:
        v.append(f"the arm is used through {sorted(set(ops) - {'turn_off', 'state'})} (only turn_off and the .state read are allowed)")
    if ops.get("turn_off", 0) != 7 or ops.get("state", 0) != 3:
        v.append(f"arm turn_off sites {ops.get('turn_off', 0)} (want 7), state reads {ops.get('state', 0)} (want 3)")
    where = {l for l, op in uses if op == "turn_off"}
    allowed = {"script:fallback_profile_review", "script:fallback_profile_capture_dispatch", "script:fallback_profile_save",
               "script:fallback_profile_invalidate"}
    iv = {w for w in where if w.startswith("interval")}
    if where - allowed - iv or len(iv) != 1:
        v.append(f"arm turned off from unexpected places: {sorted(where)}")
    if re.search(r"fallback_profile_arm\b", re.sub(r"id\(fallback_profile_arm\)\s*(\.|->)\s*(turn_off|state)\b", "", c.code())) is not None:
        v.append("the arm is named outside id(arm).turn_off() / id(arm).state in a lambda")
    for t in re.findall(r"fallback_profile_arm\b[^\n]*", c.text):
        if not (t.startswith("fallback_profile_arm)") or t.rstrip() == "fallback_profile_arm"):
            v.append(f"unexpected arm reference text {t[:60]!r}")
    return v


@static("S-API", "the api action: appended after ha_supervision_heartbeat (3 actions, actions[0] unchanged, exactly one heartbeat), three string variables, copies via .str(), one routing if, no api.respond")
def s_api(c: Ctx) -> list:
    v = []
    acts = c.fw["api"].get("actions", [])
    names = [a.get("action") for a in acts]
    if names != ["free_power_recovery_execute", "ha_supervision_heartbeat", "fallback_profile_execute"]:
        v.append(f"api actions {names}")
        return v
    a = acts[2]
    if a.get("variables") != {"action": "string", "target_id": "string", "confirmation": "string"}:
        v.append(f"variables {a.get('variables')}")
    then = a.get("then") or []
    if item_kinds(then) != ["lambda", "if"]:
        v.append(f"then = {item_kinds(then)}")
        return v
    lam = then[0]["lambda"]
    want = ["id(fallback_profile_exec_action) = action.str();", "id(fallback_profile_exec_target_id) = target_id.str();",
            "id(fallback_profile_exec_confirmation) = confirmation.str();", HB_LINE]
    if [ln.strip() for ln in lam.strip().splitlines()] != want:
        v.append(f"the action lambda is not exactly the three .str() copies and the heartbeat snapshot: {lam[:120]!r}")
    cond = then[1]["if"]
    if cond.get("condition") != {"lambda": EXECUTE_ROUTE}:
        v.append(f"routing condition {cond.get('condition')}")
    if cond.get("then") != [{"script.execute": {"id": "fallback_profile_invalidate"}}] or \
            cond.get("else") != [{"script.execute": {"id": "fallback_profile_save"}}]:
        v.append(f"routing targets {cond.get('then')} / {cond.get('else')}")
    if len([n for n in names if n == "ha_supervision_heartbeat"]) != 1:
        v.append("not exactly one heartbeat action")
    if "api.respond" in yaml.dump(acts) or "homeassistant" in yaml.dump(acts[2]):
        v.append("the execute action responds / calls HA")
    return v


@static("S-SUP", "the substring 'upervision' appears in FB-B2 code ONLY as the one heartbeat snapshot line of the api action and the one commit-time re-check statement of SAVE_FINAL part 2 (no other script, switch, interval, boot lambda or action mentions it)")
def s_sup(c: Ctx) -> list:
    v = []
    # every Fallback Profile lambda (scripts, interval, boot, switch, api action): 'upervision' ONLY in the execute api action, twice, on the one line
    api_lines, disp_lines = [], []
    for loc, t in c.fb_lams():
        if loc.startswith("api:fallback_profile_execute"):
            api_lines += [ln.strip() for ln in t.splitlines() if "upervision" in ln]
        elif loc.startswith("script:fallback_profile_capture_dispatch"):
            # FB-B2 hardening: the commit-time heartbeat re-check (SAVE_FINAL part 2), one statement
            disp_lines += [ln.strip() for ln in t.splitlines() if "upervision" in ln]
        elif "upervision" in t:
            v.append(f"{loc} mentions supervision")
    if api_lines != [HB_LINE]:
        v.append(f"the execute api action's supervision lines are {api_lines}, not exactly the one heartbeat snapshot line")
    if disp_lines != [HB_COMMIT_LINE]:
        v.append(f"the dispatch's supervision lines are {disp_lines}, not exactly the one commit-time re-check statement")
    # no Fallback Profile script, the arm switch or the housekeeping interval mentions it anywhere (ids, names, comments included)
    for s in c.fw["script"]:
        if s["id"].startswith("fallback_profile") and s["id"] != "fallback_profile_capture_dispatch" and "upervision" in yaml.dump(s):
            v.append(f"script {s['id']} mentions supervision")
        if s["id"] == "fallback_profile_capture_dispatch" and yaml.dump(s).count("supervision") != 2:
            v.append("the dispatch names supervision other than the two reads of the commit-time re-check")
    if "upervision" in yaml.dump(c.fw["switch"][-1]):
        v.append("the arm switch mentions supervision")
    iv = [i for i in c.fw["interval"] if "fallback_profile_cand_valid" in yaml.dump(i)]
    if len(iv) != 1 or "upervision" in yaml.dump(iv[0]):
        v.append("the Fallback Profile housekeeping interval mentions supervision (or is not exactly one)")
    if "upervision" in str(c.fw["esphome"]["on_boot"]["then"][-1]):
        v.append("the Fallback Profile boot lambda mentions supervision")
    if c.text.count("supervision") != 204:
        v.append(f"'supervision' appears {c.text.count('supervision')}x in the YAML (want the FB-B1 200 + 2 of the heartbeat snapshot line + 2 of the commit-time re-check)")
    return v


@static("S-INV", "INVALIDATE: ONE synchronous lambda (mode single), no wait_until / delay / script.execute / Modbus, never assigns the operation flags or the write mutex, bus-quiet re-check right before the one commit")
def s_inv(c: Ctx) -> list:
    v = []
    s = c.scripts.get("fallback_profile_invalidate")
    if s is None:
        return ["script fallback_profile_invalidate is missing"]
    if s.get("mode") != "single" or item_kinds(s["then"]) != ["lambda"]:
        v.append(f"mode {s.get('mode')} then {item_kinds(s['then'])}")
        return v
    lam = strip_cpp(s["then"][0]["lambda"])
    text = yaml.dump(s)
    for tok in ("wait_until", "delay", "script.execute", "modbus_client", "while (", "for (", "goto"):
        if tok in text or tok in lam:
            v.append(f"the invalidate script contains {tok!r}")
    for g in ("manual_write_in_progress", "fallback_profile_op_in_progress", "fallback_profile_op_purpose", "free_power_operation_in_progress",
              "correction_in_progress", "dump_operation_in_progress", "reg244_apply_in_progress", "diag_write_lock_held"):
        if re.search(rf"id\({g}\)\s*=(?!=)", lam):
            v.append(f"the invalidate lambda assigns {g}")
    if len(re.findall(r"ecco_fbdurable::commit_transition_t\s*\(", lam)) != 1:
        v.append("the invalidate lambda does not call commit_transition_t exactly once")
    execs = set(re.findall(r"id\((\w+)\)\.execute\(\)", lam))
    if execs - {"fallback_profile_invalidate_candidate"}:
        v.append(f"the invalidate lambda executes {sorted(execs)}")
    # bus-quiet re-check is the LAST gate before the commit: the text between the last tx_buffer_empty/BusInputs read and the
    # commit holds no other statement that could yield
    i_commit = lam.index("commit_transition_t(") if "commit_transition_t(" in lam else -1
    last_bus = max(lam.rfind("tx_buffer_empty"), lam.rfind("commit_bus_quiet"), lam.rfind("bus_quiet"))
    if i_commit < 0 or last_bus < 0 or last_bus > i_commit:
        v.append("no bus-quiet check before the commit")
    return v


@static("S-SAVE", "SAVE: the gate script is synchronous (lambda, then an `if` that only runs script.execute of the EXISTING dispatch); only the api action executes the two scripts; the only script ever executed from FB-B2 text is the dispatch")
def s_save(c: Ctx) -> list:
    v = []
    s = c.scripts.get("fallback_profile_save")
    if s is None:
        return ["script fallback_profile_save is missing"]
    if s.get("mode") != "single" or item_kinds(s["then"]) != ["lambda", "if"]:
        v.append(f"mode {s.get('mode')} then {item_kinds(s['then'])}")
        return v
    iff = s["then"][1]["if"]
    if iff.get("condition") != {"lambda": "return id(fallback_profile_gate_accepted);"}:
        v.append(f"gate condition {iff.get('condition')}")
    if item_kinds(iff["then"]) != ["lambda", "script.execute"] or iff["then"][1]["script.execute"] != {"id": "fallback_profile_capture_dispatch"} \
            or "else" in iff:
        v.append(f"accepted branch {iff.get('then')}")
    elif iff["then"][0]["lambda"].strip() != "id(fallback_profile_gate_accepted) = false;":
        v.append("the accepted branch lambda is not exactly the gate_accepted reset")
    # who executes the two new scripts: only the api action
    for loc, node in _find_exec(c.fw):
        if node in FBB2_SCRIPTS and not loc.startswith("api:fallback_profile_execute"):
            v.append(f"{node} is executed from {loc}")
    for loc, t in c.lams:
        for tgt in re.findall(r"id\((\w+)\)\.execute\(\)", strip_cpp(t)):
            if tgt in FBB2_SCRIPTS or tgt == "fallback_profile_capture_dispatch" and loc.startswith("script:fallback_profile_save"):
                v.append(f"{loc} calls {tgt}.execute() from a lambda")
    save_lam = strip_cpp(s["then"][0]["lambda"])
    for tok in ("commit_transition_t", "read_direct_t", "EspNvs", "nvs_healthy", "wait_until", "delay("):
        if tok in save_lam:
            v.append(f"the SAVE gate lambda contains {tok!r} (it reads no storage and does not commit)")
    return v


def _find_exec(fw: dict):
    """[(location, target script id)] of every `script.execute: id: X` action anywhere in the parsed firmware."""
    out = []

    def walk(node, loc):
        if isinstance(node, dict):
            for k, val in node.items():
                if k == "script.execute":
                    tgt = val.get("id") if isinstance(val, dict) else val
                    out.append((loc, tgt))
                else:
                    walk(val, f"{loc}/{k}")
        elif isinstance(node, list):
            for i, val in enumerate(node):
                walk(val, f"{loc}[{i}]")

    for loc, node in labelled_roots(fw):
        walk(node, loc)
    return out


@static("S-DISPATCH", "the capture dispatch: the same four FC03 read nodes, one SAVE-only drain `if` (3000 ms == PRECOMMIT_WAIT_MS) before REVIEW_FINAL, two SAVE_FINAL lambdas before RELEASE, RELEASE still last and clearing the SAVE context")
def s_dispatch(c: Ctx) -> list:
    v = []
    d = c.scripts.get("fallback_profile_capture_dispatch")
    if d is None:
        return ["dispatch missing"]
    kinds = item_kinds(d["then"])
    if kinds != ["lambda", "wait_until", "lambda", "if", "if", "lambda", "lambda", "lambda", "lambda"]:
        v.append(f"dispatch item kinds {kinds}")
        return v
    text = yaml.dump(d)
    reads = re.findall(r"modbus_client\.(\w+)", text)
    if reads != ["read_holding_registers"] * 4:
        v.append(f"dispatch Modbus nodes {reads}")
    drain = d["then"][4]["if"]
    wait = drain["then"][0]["wait_until"] if item_kinds(drain["then"]) == ["wait_until"] else {}
    hdr = (INCLUDE_DIR / NEW_HEADER).read_text(encoding="utf-8")
    m = re.search(r"PRECOMMIT_WAIT_MS\s*=\s*(\d+)u?\s*;", hdr)
    if not m or wait.get("timeout") != f"{int(m.group(1))}ms" or int(m.group(1)) != 3000:
        v.append(f"drain timeout {wait.get('timeout')} vs PRECOMMIT_WAIT_MS {m.group(1) if m else None}")
    if "ecco_fbsave::PURPOSE_SAVE" not in str(drain.get("condition")):
        v.append("the drain `if` is not guarded by the SAVE purpose")
    rev_final = d["then"][5]["lambda"]
    first = [ln.strip() for ln in rev_final.splitlines() if ln.strip() and not ln.strip().startswith("//")][0]
    if first != "if (id(fallback_profile_op_purpose) == ecco_fbsave::PURPOSE_SAVE) return;":
        v.append(f"REVIEW_FINAL does not start with the SAVE purpose guard: {first!r}")
    p1 = d["then"][6]["lambda"]
    first1 = [ln.strip() for ln in p1.splitlines() if ln.strip() and not ln.strip().startswith("//")][0]
    if first1 != "if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return;":
        v.append(f"SAVE_FINAL part 1 does not start with the purpose check: {first1!r}")
    rel = d["then"][8]["lambda"]
    if "The single release point" not in rel or "fallback_profile_save_ctx_valid) = false" not in rel \
            or "fallback_profile_save_verified) = false" not in rel:
        v.append("the RELEASE lambda does not clear the SAVE context and the verification hand-over")
    if "manual_write_in_progress) = false" not in rel:
        v.append("RELEASE no longer releases the write mutex")
    return v


@static("S-COMMIT", "the ONLY durable writes: `ecco_fbdurable::commit_transition_t(` in exactly two lambdas (SAVE_FINAL part 2, INVALIDATE), each with its own `EspNvs nvs;`; no other NVS / preference / write-template token in any lambda")
def s_commit(c: Ctx) -> list:
    v = []
    sites = []
    for loc, t in c.lams:
        n = len(re.findall(r"\bcommit_transition_t\b", strip_cpp(t)))
        if n:
            sites.append((loc, n))
    if sorted(sites) != sorted((l, 1) for l in COMMIT_LAMBDAS):
        v.append(f"commit_transition_t sites {sites} (want exactly one in each of {list(COMMIT_LAMBDAS)})")
    for loc, _n in sites:
        t = strip_cpp(c.lam_text(loc))
        if len(re.findall(r"ecco_fbdurable::EspNvs\s+nvs\s*;", t)) != 1 or not re.search(r"ecco_fbdurable::commit_transition_t\s*\(\s*nvs\s*,", t):
            v.append(f"{loc}: the commit is not the one writer call on its own local EspNvs nvs")
    code = c.fb_code()
    for tok in (r"\bnvs_set\w*", r"\bnvs_erase\w*", r"\bnvs_commit\b", r"\bwrite_one_\b", r"\bWriteTarget\b", r"\bglobal_preferences\b",
                r"\bmake_preference\b", r"ecco_durable::commit_record\s*\(\s*[^)]*FBP", r"\bmake_provision\b", r"\bseal_profile\b",
                r"\binvalidate_profile\b", r"\bsave_generation_base\b"):
        if re.search(tok, code):
            v.append(f"a lambda contains {tok!r} (the writer's internals belong to the header; the YAML only calls commit_transition_t)")
    if len(re.findall(r"\bcommit_transition_t\b", strip_cpp("\n".join(t for _l, t in c.lams)))) != 2 or c.text.count("commit_transition_t") != 2:
        v.append("commit_transition_t is named outside the two lambdas or not twice in the YAML text (comments included)")
    # no commit call inside any non-lambda construct (condition, api action, interval, boot, switch, button)
    for loc, t in c.lams:
        if "commit_transition_t" in strip_cpp(t) and loc.startswith(("api:", "interval", "esphome", "switch", "button", "number", "select", "sensor")):
            v.append(f"commit_transition_t in {loc}")
    return v


@static("S-KEYS", "durable keys: the FB-B2 text names only the FBP and FBW key constants (the FB-B0 constants, never a numeric key); the FBS key / record is named exactly once in the whole YAML - the FB-B1 boot lambda's read-only load - and never by an FB-B2 hunk; no FB tag string")
def s_keys(c: Ctx) -> list:
    v = []
    code = c.code()
    consts = Counter(re.findall(r"ecco_fbdurable::(FALLBACK_PROFILE_KEY|FAILBACK_PROVISION_KEY|FAILBACK_STATE_KEY)", code))
    if set(consts) != {"FALLBACK_PROFILE_KEY", "FAILBACK_PROVISION_KEY", "FAILBACK_STATE_KEY"} or consts["FAILBACK_STATE_KEY"] != 1:
        v.append(f"key constants named in the YAML: {dict(consts)} (want FBP and FBW, and FBS exactly once)")
    fbs_locs = sorted({loc for loc, t in c.lams if re.search(r"FAILBACK_STATE|FailbackStateV1|ecco_failback_state", strip_cpp(t))})
    if fbs_locs != ["esphome/on_boot/then[3]"]:
        v.append(f"the FBS key / record is named in {fbs_locs} (want only the FB-B1 boot lambda, a read)")
    for h in scope.HUNKS:
        if re.search(r"FAILBACK_STATE|FailbackStateV1|fbs_write|ecco_failback_state", h.new):
            v.append(f"hunk {h.name} names the FBS key / record")
    for name, (dec, hexv, tag, const) in KEYS.items():
        if re.search(rf"(?<![0-9A-Za-z_]){dec}(?![0-9])|0x{hexv:08X}|0x{hexv:08x}", c.text) or tag in c.text:
            v.append(f"the YAML spells the {name} key / tag literally")
    return v


@static("S-MODBUS", "ZERO Modbus: no FB-B2 hunk carries a modbus_client action; the only inverter_modbus members used by FB-B2 text are the two bus-idle reads; Modbus node text count unchanged")
def s_modbus(c: Ctx) -> list:
    v = []
    for h in scope.HUNKS:
        if "modbus_client" in h.new or "modbus_client" in h.old:
            v.append(f"hunk {h.name} carries a modbus_client node")
    members = set()
    for _l, t in c.fb_lams():
        members |= set(re.findall(r"inverter_modbus\)?\s*(?:->|\.)\s*(\w+)", strip_cpp(t)))
    if members - {"tx_buffer_empty", "tx_blocked"}:
        v.append(f"inverter_modbus members used by Fallback Profile lambdas: {sorted(members)}")
    if c.text.count("modbus_client.") != 119:
        v.append(f"modbus_client. occurrences {c.text.count('modbus_client.')} (want the FB-B1 119)")
    for s in c.fw["script"]:
        if s["id"] in FBB2_SCRIPTS and "modbus_client" in yaml.dump(s):
            v.append(f"script {s['id']} carries a Modbus node")
    return v


@static("S-LOG", "the new log sites: exactly six, all tag \"fbdurable\", all with the format literal \"%s\" (SAVE_FINAL part 2 and INVALIDATE only); no other new ESP_LOG")
def s_log(c: Ctx) -> list:
    v = []
    sites = []
    for loc, t in c.fb_lams():
        code = strip_cpp(t)
        for m in re.finditer(r'ESP_LOG[A-Z]\(\s*"([^"]*)"\s*,\s*("[^"]*")', code):
            sites.append((loc, m.group(1), m.group(2)))
        if code.count("ESP_LOG") != len(re.findall(r'ESP_LOG[A-Z]\(\s*"[^"]*"\s*,\s*"[^"]*"', code)):
            v.append(f"{loc}: an ESP_LOG call the scan could not read")
    by_tag = Counter(tag for _l, tag, _f in sites)
    new_sites = [(l, f) for l, tag, f in sites if tag == "fbdurable"]
    if dict(by_tag) != {"fbcap": 6, "fbdurable": 6}:
        v.append(f"Fallback Profile log sites by tag {dict(by_tag)} (want the six FB-B1 'fbcap' and the six new 'fbdurable')")
    if {f for _l, f in new_sites} != {'"%s"'} or sorted({l for l, _f in new_sites}) != sorted(COMMIT_LAMBDAS):
        v.append(f"the new log sites are not all the format literal \"%s\" in the two commit lambdas: {new_sites}")
    if len(re.findall(r"ESP_LOG", c.text)) != 465:
        v.append(f"ESP_LOG total {len(re.findall('ESP_LOG', c.text))} (want 459 + 6)")
    return v


@static("S-FORBID", "no FB-B2 insertion or replacement contains a forbidden symbol (nvs_set / commit_record / load_record / write_one_ / WriteTarget / modbus_client / App. / reboot / api.respond ...)")
def s_forbid(c: Ctx) -> list:
    v = []
    for loc, t in c.fb_lams():
        m = FORBIDDEN.search(strip_cpp(t))
        if m:
            v.append(f"{loc}: {m.group(0)!r}")
    for h in scope.HUNKS:
        m = FORBIDDEN.search(strip_cpp(h.new)) if h.name not in ("api_action", "globals", "switch_arm") else FORBIDDEN.search(h.new.replace("api.respond", ""))
        if m:
            v.append(f"hunk {h.name}: {m.group(0)!r}")
    return v


@static("S-NTP", "NTP is read ONLY by the SAVE gate and SAVE_FINAL part 2 (5 mentions): the api action, INVALIDATE, REVIEW and the interval read none")
def s_ntp(c: Ctx) -> list:
    got = {l: len(re.findall(r"ntp_", strip_cpp(t))) for l, t in c.fb_lams() if "ntp_" in strip_cpp(t)}
    want = {"script:fallback_profile_capture_dispatch/then[7]": 3, "script:fallback_profile_save/then[0]": 2}
    return [] if got == want else [f"ntp_ mentions per Fallback Profile lambda {got}"]


@static("S-GLOBALS", "the 18 new globals are exactly the scope table, appended after the FB-B1 globals, every one restore_value: no, scalar / std::string / one std::array; no new restore_value: yes")
def s_globals(c: Ctx) -> list:
    v = []
    g = c.fw["globals"]
    new = g[len(g) - len(scope.GLOBALS):]
    if [(x["id"], x["type"], (str(x["initial_value"]) if "initial_value" in x else None)) for x in new] != scope.GLOBALS:
        v.append("the appended globals differ from the scope table")
    if not all(x.get("restore_value") is False for x in new):
        v.append("a new global is not restore_value: no")
    if not all(re.fullmatch(r"bool|u?int(8|16|32|64)_t|std::string|std::array<uint16_t, 31>", x["type"]) for x in new):
        v.append("a new global has a type outside scalar / std::string / the one std::array")
    if len(g) != 528:
        v.append(f"{len(g)} globals (want 528)")
    if sorted(x["id"] for x in g if x.get("restore_value")) != ["reg244_last_applied_valid", "reg244_last_applied_value"]:
        v.append("the restore_value: yes set changed")
    return v


# ---------------------------------------------------------------------------------------------------------------------------
# The measurement (a pure function of the firmware text and the header texts, so the mutants can feed it broken copies)
# ---------------------------------------------------------------------------------------------------------------------------
def survey(fw_text: str, headers: dict) -> dict:
    fw = chain.load_fw(fw_text)
    texts = {chain.FIRMWARE: fw_text, chain.DURABLE_HEADER: headers["ecco_durable_snapshot.h"], chain.EVIDENCE_HEADER: headers["ecco_recovery_evidence.h"]}
    metrics = chain.measure(texts)
    an = chain.analyze_text(fw_text, {f"include/{n}": t for n, t in headers.items()})
    paths = {p.name: tuple((o.kind, o.start_address, o.count) for o in p.ops) for p in an["paths"]}
    lams = lambdas_of(fw)
    code = "\n".join(strip_cpp(t) for _l, t in lams)
    commit_sites = sorted(l for l, t in lams if re.search(r"\bcommit_transition_t\b", strip_cpp(t)))
    hs = {n: strip_cpp(t) for n, t in headers.items()}
    return {
        "metrics": metrics,
        "names": {"scripts": [s["id"] for s in fw["script"]], "globals": [g["id"] for g in fw["globals"]],
                  "api_actions": [a["action"] for a in fw["api"].get("actions", [])], "switches": [s["name"] for s in fw["switch"]],
                  "text_sensors": [s.get("id") or s.get("name") for s in fw["text_sensor"]], "buttons": [b.get("id") or b.get("name") for b in fw["button"]],
                  "includes": list(fw["esphome"].get("includes", []))},
        "paths": paths, "bus_findings": len(an["bus_access_findings"]), "unknown_extent": len(an["unknown_extent_writes"]),
        "modbus_text": fw_text.count("modbus_client."),
        "commit_sites": commit_sites,
        "commit_calls": len(re.findall(r"ecco_fbdurable::commit_transition_t\s*\(", code)),
        "fbdur": {tok: len(re.findall(rf"\b{tok}\b", code)) for tok in ("read_direct_t", "EspNvs", "nvs_healthy", "mirror_after", "note_committed",
                                                                         "next_seen_hw_gen", "read_pair_t")},
        "yaml_write_tokens": sorted(set(re.findall(r"\bnvs_set\w*|\bnvs_erase\w*|\bnvs_commit\b|\bwrite_one_\b|\bWriteTarget\b", code))),
        "yaml_nvs_text": len(re.findall(r"\bnvs_set", fw_text)),
        "key_use": Counter(re.findall(r"ecco_fbdurable::(FALLBACK_PROFILE_KEY|FAILBACK_PROVISION_KEY|FAILBACK_STATE_KEY)", code)),
        "key_literals": sum(len(re.findall(rf"(?<![0-9A-Za-z_]){dec}(?![0-9])|0x{hexv:08X}", fw_text, re.IGNORECASE)) for dec, hexv, _t, _c in KEYS.values()),
        "nvs_set_blob": {n: len(re.findall(r"\bnvs_set_blob\s*\(", t)) for n, t in hs.items() if re.search(r"\bnvs_set_blob\s*\(", t)},
        "write_one_inst": {n: len(re.findall(r"\bwrite_one_\s*<", t)) for n, t in hs.items() if re.search(r"\bwrite_one_\s*<", t)},
        "write_targets": {n: len(re.findall(r"template<>\s*struct\s+WriteTarget<", t)) for n, t in hs.items() if re.search(r"template<>\s*struct\s+WriteTarget<", t)},
        "fbs_write_tokens": {n: len(re.findall(r"write_one_\s*<[^>]*FAILBACK_STATE", t)) for n, t in hs.items() if re.search(r"write_one_\s*<[^>]*FAILBACK_STATE", t)},
        "tags": {n: list(tag_inventory(t)) for n, t in headers.items() if tag_inventory(t)},
        "banned": Counter(chain.BANNED.findall(fw_text)),
        "log_tags": Counter(re.findall(r'ESP_LOG[A-Z]\(\s*"(\w+)"', code)),
        "sup": len(re.findall(r"supervision", fw_text)), "ntp": len(re.findall(r"ntp_", fw_text)),
        "unaccounted": {n: sorted(x) for n, t in headers.items()
                        if (x := durable_literals(t) - {v for _n2, v in tag_inventory(t)} - {v for hh in headers.values() for _n3, v in tag_inventory(hh)})},
    }


def survey_violations(base: dict, live: dict) -> list:
    """What the measured base -> head difference must satisfy (typed expectations; each phrase is a violation when untrue)."""
    v = []
    mb, ml = base["metrics"], live["metrics"]
    if ml["modbus_reads"] != mb["modbus_reads"] or ml["modbus_reads"] != 64:
        v.append(f"Modbus READ ops {mb['modbus_reads']} -> {ml['modbus_reads']} (want 64 -> 64)")
    if ml["modbus_writes"] != mb["modbus_writes"] or ml["modbus_writes"] != 52:
        v.append(f"Modbus WRITE ops {mb['modbus_writes']} -> {ml['modbus_writes']} (want 52 -> 52: ZERO write delta)")
    if live["modbus_text"] != base["modbus_text"]:
        v.append(f"modbus_client. text sites {base['modbus_text']} -> {live['modbus_text']}")
    added_paths = sorted(set(live["paths"]) - set(base["paths"]))
    removed = sorted(set(base["paths"]) - set(live["paths"]))
    changed = sorted(n for n in set(live["paths"]) & set(base["paths"]) if live["paths"][n] != base["paths"][n])
    if (len(base["paths"]), len(live["paths"])) != FBB2_PATHS or added_paths != ["fallback_profile_save"] or removed or changed:
        v.append(f"analyzer paths {len(base['paths'])} -> {len(live['paths'])}, added {added_paths}, removed {removed}, changed {changed}")
    elif live["paths"]["fallback_profile_save"] != ():
        v.append("the SAVE gate path has Modbus ops of its own")
    if live["paths"].get("fallback_profile_capture_dispatch") != tuple(("read", s_, n_) for s_, n_ in FBB1_READS):
        v.append(f"the capture dispatch op list is {live['paths'].get('fallback_profile_capture_dispatch')}")
    if live["bus_findings"] != 0 or live["unknown_extent"] != 0 or base["bus_findings"] != 0:
        v.append(f"analyzer findings: bus {base['bus_findings']} -> {live['bus_findings']}, unknown extent {live['unknown_extent']}")
    for m in ("commit_record", "load_record", "load_record_status", "durable_tag_strings"):
        if mb[m] != ml[m]:
            v.append(f"{m} {mb[m]} -> {ml[m]} (the legacy durable surface must not move)")
    if (ml["commit_record"], ml["load_record"], ml["load_record_status"], ml["durable_tag_strings"]) != (57, 7, 3, 13):
        v.append("durable surface is not 57 / 7 / 3 and 13 tag strings")
    if (base["commit_calls"], live["commit_calls"]) != (0, 2) or live["commit_sites"] != sorted(COMMIT_LAMBDAS):
        v.append(f"commit_transition_t call sites {base['commit_calls']} -> {live['commit_calls']} at {live['commit_sites']}")
    if live["nvs_set_blob"] != {DURABLE_ADAPTER: 1}:
        v.append(f"nvs_set_blob call sites {live['nvs_set_blob']} (want only the FB-B0 adapter, once)")
    if live["write_one_inst"] != {DURABLE_MODEL: 2} or live["write_targets"] != {DURABLE_MODEL: 2} or live["fbs_write_tokens"]:
        v.append(f"write_one_ instantiations {live['write_one_inst']} / WriteTarget specialisations {live['write_targets']} / FBS {live['fbs_write_tokens']}")
    if live["yaml_write_tokens"] or live["yaml_nvs_text"] != base["yaml_nvs_text"]:
        v.append(f"direct NVS / writer-template tokens in the YAML: {live['yaml_write_tokens']} (text sites {base['yaml_nvs_text']} -> {live['yaml_nvs_text']})")
    if set(live["key_use"]) != {"FALLBACK_PROFILE_KEY", "FAILBACK_PROVISION_KEY", "FAILBACK_STATE_KEY"} or live["key_literals"] != 0 \
            or live["key_use"]["FAILBACK_STATE_KEY"] != base["key_use"]["FAILBACK_STATE_KEY"] != 1:
        v.append(f"key constants named in the YAML {dict(live['key_use'])} (FBS must stay the FB-B1 boot read, once), literal keys {live['key_literals']}")
    if sorted(live["tags"].items()) != sorted(base["tags"].items()):
        v.append("the durable tag inventory of the headers changed")
    if live["unaccounted"]:
        v.append(f"durable-looking literals without a declaration: {live['unaccounted']}")
    if {n for n, _ in live["tags"].items()} & {NEW_HEADER}:
        v.append("the new header declares a durable tag")
    if (mb["banned_fw"], ml["banned_fw"]) != (27, 39) or sum(live["banned"].values()) - sum(base["banned"].values()) != FBB2_BANNED:
        v.append(f"banned tokens {mb['banned_fw']} -> {ml['banned_fw']}")
    if live["names"]["scripts"][:len(base["names"]["scripts"])] != base["names"]["scripts"] or live["names"]["scripts"][len(base["names"]["scripts"]):] != list(FBB2_SCRIPTS):
        v.append("the new scripts are not exactly the two FB-B2 scripts, appended")
    if live["names"]["includes"] != base["names"]["includes"] + [FBB2_NEW_INCLUDE]:
        v.append("the include list is not base + the SAVE header, appended last")
    for k in ("text_sensors", "buttons"):
        if live["names"][k] != base["names"][k]:
            v.append(f"{k} changed")
    if ml != {**{k: mb[k] + FBB2_DELTAS.get(k, 0) for k in mb if k != "banned_fw"}, "banned_fw": 39}:
        v.append("the 20 chain metrics are not base + the FB-B2 deltas")
    return v


def fmt_table(rows: list) -> str:
    head = ("quantity", "FB-B1 (main 65e4be5)", "FB-B2 (working tree)", "delta", "where / note")
    rows = [head] + [tuple(str(x) for x in r) for r in rows]
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    out = []
    for i, r in enumerate(rows):
        out.append("  | " + " | ".join(r[j].ljust(w[j]) for j in range(4)) + " | " + r[4])
        if i == 0:
            out.append("  |-" + "-|-".join("-" * w[j] for j in range(4)) + "-|-----")
    return "\n".join(out)


def delta(a, b) -> str:
    try:
        d = b - a
        return f"{d:+d}"
    except TypeError:
        return "="


# ---------------------------------------------------------------------------------------------------------------------------
# Detectors shared by the real run and the mutants
# ---------------------------------------------------------------------------------------------------------------------------
def load_scope_variant(src: str, tag: str):
    """Compile a (mutated) copy of _fbb2_scope.py as an isolated module (registered in sys.modules while it runs: dataclasses needs it)."""
    name = f"_fbb2_scope_variant_{tag}"
    mod = types.ModuleType(name)
    mod.__file__ = f"<{name}>"
    sys.modules[name] = mod
    try:
        exec(compile(src, mod.__file__, "exec"), mod.__dict__)  # noqa: S102 - a test-only mutant of the module under test
    finally:
        sys.modules.pop(name, None)
    return mod


def revert_violations(mod, fw_text: str) -> list:
    """D-REVERT: the scope module's reverter must reproduce the FB-B1 firmware byte-for-byte and round-trip."""
    v = []
    try:
        base = mod.pre_fbb2_firmware(fw_text)
    except AssertionError as ex:
        return [f"the reverter raised: {str(ex)[:90]}"]
    if sha(base) != FBB1_FW_SHA:
        v.append(f"revert sha {sha(base)[:12]} != the fbb1 checkpoint {FBB1_FW_SHA[:12]}")
    if mod.BASE_FW_SHA != FBB1_FW_SHA:
        v.append("BASE_FW_SHA is not the fbb1 checkpoint")
    try:
        if mod.add_fbb2_text(base) != fw_text:
            v.append("the round trip (revert then add) does not reproduce the firmware")
    except AssertionError as ex:
        v.append(f"add_fbb2_text raised: {str(ex)[:90]}")
    if len(mod.HUNKS) != 21:
        v.append(f"{len(mod.HUNKS)} hunks (want 21)")
    return v


def table_violations(mod, ctx: Ctx) -> list:
    """D-TABLES: the scope module's name tables against the parsed firmware."""
    v = []
    g = ctx.fw["globals"]
    new = g[len(g) - len(mod.GLOBALS):] if len(mod.GLOBALS) <= len(g) else []
    if [(x["id"], x["type"], (str(x["initial_value"]) if "initial_value" in x else None)) for x in new] != mod.GLOBALS:
        v.append("GLOBALS table != the appended firmware globals")
    if tuple(s["id"] for s in ctx.fw["script"][-2:]) != tuple(mod.SCRIPT_IDS):
        v.append("SCRIPT_IDS != the appended scripts")
    sw = ctx.fw["switch"][-1]
    if (sw.get("name"), sw.get("id"), sw.get("icon")) != (mod.SWITCH_NAME, mod.SWITCH_ID, mod.SWITCH_ICON):
        v.append("the switch constants != the firmware switch")
    if ctx.fw["api"]["actions"][-1].get("action") != mod.API_ACTION:
        v.append("API_ACTION != the appended api action")
    if ctx.fw["esphome"]["includes"][-1] != mod.ADDED_INCLUDES[-1] or list(mod.ADDED_INCLUDES) != [FBB2_NEW_INCLUDE]:
        v.append("ADDED_INCLUDES != the appended include")
    return v


def files_violations(declared, on_disk_named) -> list:
    """D-FILES: every FB-B2-named file on disk is declared, every declared path exists, exact POSIX paths."""
    v = []
    undeclared = sorted(set(on_disk_named) - set(declared))
    missing = sorted(f for f in declared if not (ROOT / f).is_file())
    if undeclared:
        v.append(f"undeclared FB-B2 files on disk: {undeclared}")
    if missing:
        v.append(f"declared files that do not exist: {missing}")
    if any("\\" in f or f.startswith("/") or ".." in f.split("/") or any(ch in f for ch in "*?[]{}") for f in declared):
        v.append("a declared path is not an exact repo-relative POSIX path")
    return v


def named_files_on_disk() -> set:
    pats = ("registry/tests/_fbb2_*.py", "registry/tests/test_fallback_save_*.py", "registry/tests/test_fallback_invalidate*.py",
            "registry/fallback_save.py", "firmware/include/ecco_fallback_save.h")
    return {p.relative_to(ROOT).as_posix() for pat in pats for p in ROOT.glob(pat) if "__pycache__" not in p.parts}


def main() -> int:
    CH = chain.CHAIN                                           # the WHOLE chain: a later PR appends entries after fbb2
    CH2 = chain.Chain(CH.upto("fbb2"))                         # the chain as of this PR (it ends at fbb2)
    E = CH2.entry("fbb2")
    LIVE = {p: chain.read_live(p) for p in chain.PINNED}       # every chain-pinned artifact, LF text, as it is on disk
    LIVE_FBB2 = CH.as_of_all("fbb2", LIVE)                     # identity while fbb2 is the newest entry
    FW_TEXT = LIVE_FBB2[chain.FIRMWARE]

    # -----------------------------------------------------------------------
    print("[0] The scope module: twenty-one hunks, each exactly once at its anchor; exact revert and round trip; order-independent")
    # -----------------------------------------------------------------------
    hunks = scope.HUNKS
    try:
        BASE_TEXT = scope.pre_fbb2_firmware(FW_TEXT)
        ok_rev = True
    except AssertionError as ex:
        ok_rev, BASE_TEXT = False, FW_TEXT
        print("   ", ex)
    check("every FB-B2 hunk occurs exactly once in the firmware, directly at its anchor, and every base anchor is unique again once "
          "the hunk is removed", ok_rev)
    check("twenty-one hunks: fourteen pure insertions and seven one-line replacements; unique names; seven at an FB-B1 block boundary and "
          "fourteen inside FB-B1's own text",
          len(hunks) == 21 and len(set(scope.HUNK_NAMES)) == 21 and sum(h.insertion for h in hunks) == 14
          and sorted(h.name for h in hunks if not h.insertion) == sorted(["boot_b2", "final_state_name", "final_b2", "final_ri_cls",
                                                                           "final_prior_class", "final_b3", "final_not_saveable"])
          and len(scope.BOUNDARY_HUNKS) == 7 and len(scope.INPLACE_FBB1_HUNKS) == 14
          and scope.HUNK_NAMES == ("include", "boot_b2", "api_action", "globals", "switch_arm", "review_arm_off", "dispatch_drain",
                                   "final_guard", "final_overlay", "final_state_name", "final_b2", "final_ri_cls", "final_arm_off",
                                   "final_prior_class", "final_b3", "final_not_saveable", "save_final", "release_ctx", "scripts",
                                   "breaker_ctx", "tick2"), str(scope.HUNK_NAMES))
    check("reverting exactly FB-B2's hunks reproduces the FB-B1 firmware byte-for-byte: sha256 == _fbb2_scope.BASE_FW_SHA == the chain's "
          "fbb1 checkpoint (main @ 65e4be5) == the sha typed in this suite, and equals the chain's as-of-fbb1 view of the live firmware",
          sha(BASE_TEXT) == scope.BASE_FW_SHA == CH2.checkpoint(chain.FIRMWARE, "fbb1") == FBB1_FW_SHA
          and BASE_TEXT == CH2.as_of(chain.FIRMWARE, "fbb1", FW_TEXT), sha(BASE_TEXT))
    check("applying FB-B2 to that base reproduces the firmware exactly (round trip), and reverting that again gives the base",
          scope.add_fbb2_text(BASE_TEXT) == FW_TEXT and scope.pre_fbb2_firmware(scope.add_fbb2_text(BASE_TEXT)) == BASE_TEXT)
    check("every hunk: base text (left + old + right) occurs exactly once in the base; FB-B2 text (left + new + right) exactly once in "
          "the firmware and NOWHERE in the base; a replaced text is nowhere in the firmware any more",
          all(BASE_TEXT.count(h.before) == 1 and FW_TEXT.count(h.after) == 1 and BASE_TEXT.count(h.after) == 0
              and (h.insertion or FW_TEXT.count(h.before) == 0) for h in hunks),
          str([h.name for h in hunks if not (BASE_TEXT.count(h.before) == 1 and FW_TEXT.count(h.after) == 1
                                             and BASE_TEXT.count(h.after) == 0 and (h.insertion or FW_TEXT.count(h.before) == 0))]))
    check("a pure insertion adds a block and removes nothing (old == '', before == left + right, after == left + new + right, the block "
          "ends with a newline); a replacement replaces exactly one whole line by one whole line",
          all(h.old == "" and h.before == h.left + h.right and h.after == h.left + h.new + h.right and h.new.endswith("\n")
              for h in hunks if h.insertion)
          and all(h.old.count("\n") == 1 == h.new.count("\n") and h.old.endswith("\n") and h.new.endswith("\n") for h in hunks if not h.insertion))

    # the hunks are independent: a changed span never lies inside another hunk's context window, and any revert order gives the base
    spans = []
    for h in hunks:
        i = FW_TEXT.index(h.after)
        spans.append((h.name, i, i + len(h.after), i + len(h.left), i + len(h.left) + len(h.new)))
    overlap = [(a[0], b[0]) for a in spans for b in spans if a[0] != b[0] and a[3] < b[2] and b[1] < a[4]]
    check("the hunks are disjoint: no hunk's CHANGED span lies inside another hunk's anchor window (so each revert leaves every other "
          "hunk's anchor intact)", not overlap, str(overlap[:4]))
    rnd = random.Random(0xFBB2)
    orders_ok = True
    for _ in range(6):
        order = list(hunks)
        rnd.shuffle(order)
        t = FW_TEXT
        for h in order:
            t = scope._swap(t, h.after, h.before, h.name, "present")
        orders_ok = orders_ok and t == BASE_TEXT
    check("six random revert orders (and so the file order the module uses) all reproduce the FB-B1 firmware byte-for-byte", orders_ok)

    def _revert_one(text: str, h) -> str:
        return mutate(text, h.after, h.before)

    missing = [h.name for h in hunks if not _raises(lambda: scope.pre_fbb2_firmware(_revert_one(FW_TEXT, h)))]
    check("negative: ANY one hunk missing from the firmware makes the reverter raise (all 21 refused, none skipped)", not missing, str(missing))
    duplicated = [h.name for h in hunks if not _raises(lambda: scope.pre_fbb2_firmware(FW_TEXT + "\n" + h.after))]
    check("negative: ANY one hunk present twice makes the reverter raise (all 21 refused)", not duplicated, str(duplicated))

    def _alter(text: str, h) -> str:
        i = text.index(h.after) + len(h.left) + max(0, len(h.new) // 2)
        return text[:i] + "#" + text[i:]

    altered = [h.name for h in hunks if not _raises(lambda: scope.pre_fbb2_firmware(_alter(FW_TEXT, h)))]
    check("negative: ANY one hunk altered by a single character makes the reverter raise (all 21 refused)", not altered, str(altered))
    check("negative: add_fbb2_text refuses a firmware that already carries FB-B2, and one that already carries any single hunk",
          _raises(lambda: scope.add_fbb2_text(FW_TEXT)) and all(_raises(lambda: scope.add_fbb2_text(mutate(BASE_TEXT, h.before, h.after))) for h in hunks))
    check("negative: the reverter refuses the firmware as of fbb1 (nothing to revert) and an unrelated text",
          _raises(lambda: scope.pre_fbb2_firmware(BASE_TEXT)) and _raises(lambda: scope.pre_fbb2_firmware("esphome:\n  name: x\n")))
    FB1_BASE = scope1.pre_fbb1_firmware(BASE_TEXT)
    check("ordering (newest first): fbb2 is undone BEFORE fbb1 - fbb1's reverter on the live text refuses (its anchors are no longer "
          "contiguous), and fbb2 -> fbb1 reproduces fbb0's checkpoint (a61709c3...)",
          _raises(lambda: scope1.pre_fbb1_firmware(FW_TEXT)) and sha(FB1_BASE) == CH.checkpoint(chain.FIRMWARE, "fbb0")
          == "a61709c3fe42a8da60e16652891888988d96254be9f37e844ab665543d8c5881"
          # FB-B3: the chain now has a newer entry, so the as-of walk starts from the LIVE text (FW_TEXT is already as of fbb2).
          and CH.as_of(chain.FIRMWARE, "fbb0", LIVE[chain.FIRMWARE]) == FB1_BASE)

    base_git = git_show(f"{BASE_COMMIT}:{FIRMWARE_REL}")
    if base_git is None:
        print("  SKIP  git cross-check: the base commit 65e4be5 (or git itself) is not available here; the sha256 proofs above stand alone")
    else:
        check("git cross-check: `git show 65e4be5:firmware/ecco_clock_dongle_stage3_4_free_power.yaml` (main when FB-B1 was merged) is "
              "byte-identical to the exact reverter's output, its sha256 is the fbb1 checkpoint, and it differs from the working tree",
              base_git == BASE_TEXT and sha(base_git) == FBB1_FW_SHA == scope.BASE_FW_SHA and base_git != FW_TEXT, sha(base_git))

    # -----------------------------------------------------------------------
    print("")
    print("[1] What FB-B2 edits in EXISTING code: only the declared hunks; the only modified pre-existing lines are seven one-line replacements")
    # -----------------------------------------------------------------------
    def line_diff(base: str, live: str) -> tuple:
        """(non-equal opcodes, inserted block sizes, (old, new) replaced line pairs) of a line diff - independent of the hunk anchors."""
        bl, ll = base.split("\n"), live.split("\n")
        o = [x for x in difflib.SequenceMatcher(None, bl, ll, autojunk=False).get_opcodes() if x[0] != "equal"]
        return (o, sorted(j2 - j1 for tag, i1, i2, j1, j2 in o if tag == "insert"),
                [(bl[i1:i2], ll[j1:j2]) for tag, i1, i2, j1, j2 in o if tag == "replace"])

    def diff_is_declared(base: str, live: str) -> bool:
        """True iff the ONLY differences are the fourteen declared insertions (sizes) and the seven declared one-line replacements."""
        o, ins, rep = line_diff(base, live)
        return (all(tag in ("insert", "replace") for tag, *_r in o) and len(o) == 21
                and ins == sorted(h.new.count("\n") for h in hunks if h.insertion)
                and sorted((a[0] + "\n", b[0] + "\n") for a, b in rep if len(a) == len(b) == 1) == sorted(scope.REPLACED_LINES.values())
                and len(rep) == 7)

    ops, inserts, replaces = line_diff(BASE_TEXT, FW_TEXT)
    check("line diff (independent of the hunk anchors): no base line is deleted; exactly seven base lines are replaced; every other "
          "difference is a pure insertion; 21 edit sites in all",
          all(tag in ("insert", "replace") for tag, *_r in ops) and len(replaces) == 7 and len(ops) == 21,
          str([(t, i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in ops]))
    hunk_sizes = sorted(h.new.count("\n") for h in hunks if h.insertion)
    by_name = {h.name: h.new.count("\n") for h in hunks if h.insertion}
    print(f"  (inserted block sizes, measured by the line diff: {inserts} = {sum(inserts)} lines; per hunk {by_name})")
    check("the measured inserted line counts are exactly the fourteen insertion hunks' sizes (derived from the scope module, not typed "
          "here): fourteen pure insertions + the seven one-line replacements; the include hunk is 1 line, the two arm-off hunks and the "
          "guard / overlay hunks are 2 lines each",
          len(inserts) == 14 == len(hunk_sizes) and len(replaces) == 7 and inserts == hunk_sizes and sum(inserts) == sum(by_name.values())
          and by_name["include"] == 1 and [by_name[n] for n in ("review_arm_off", "final_guard", "final_overlay", "final_arm_off")] == [2, 2, 2, 2],
          str(inserts))
    _victim = "Starting Free Power snapshot"
    check("self-test of that diff proof: it ACCEPTS the real firmware and REJECTS (a) an eighth modified pre-existing line, (b) a deleted "
          "pre-existing line, (c) one extra inserted line; and a changed character inside an inserted block is refused by the exact hunk revert",
          diff_is_declared(BASE_TEXT, FW_TEXT)
          and not diff_is_declared(BASE_TEXT, mutate(FW_TEXT, _victim, _victim + "X"))
          and not diff_is_declared(BASE_TEXT, mutate(FW_TEXT, "                ESP_LOGW(\"free_power\", \"Starting Free Power snapshot\");\n", ""))
          and not diff_is_declared(BASE_TEXT, mutate(FW_TEXT, "\nglobals:\n", "\nglobals:\n  # stray comment\n"))
          and _raises(lambda: scope.pre_fbb2_firmware(mutate(FW_TEXT, scope.GLOBALS_BLOCK, scope.GLOBALS_BLOCK.replace("'0'", "'1'", 1)))))
    rep_lines = [(o[0], n[0]) for o, n in replaces]
    cls_edits = [(o, n) for o, n in rep_lines if n == o.replace("e.cls", "eff_cls") and "e.cls" in o]
    ret_edits = [(o, n) for o, n in rep_lines if n == o.replace("e.why, 0, 0)", "e.why, id(fallback_durable_last_err), id(fallback_durable_last_us))")
                 and "e.why, 0, 0)" in o]
    check("the seven modified pre-existing lines are exactly: five `e.cls` -> `eff_cls` (the SAVE_UNCONFIRMED overlay in REVIEW_FINAL: B1 name, "
          "ReviewInputs.cls, cand_prior_class, the B3 text, the not-saveable text) and two `b2_text(..., 0, 0)` -> the retained last write "
          "error / time (boot lambda and REVIEW_FINAL); and they equal the scope module's REPLACED_LINES",
          len(cls_edits) == 5 and len(ret_edits) == 2 and sorted(n + "\n" for _o, n in rep_lines) == sorted(n for _o, n in scope.REPLACED_LINES.values())
          and sorted(o + "\n" for o, _n in rep_lines) == sorted(o for o, _n in scope.REPLACED_LINES.values()), str(rep_lines)[:200])
    print("  --- the seven replaced lines, from -> to ---")
    for o, n in rep_lines:
        print(f"      {o.strip()[:92]}")
        print(f"        ->{n.strip()[:96]}")
    check("each cls edit is within REVIEW_FINAL (indent >= 12) and none of the old lines survives anywhere in the firmware",
          all(FW_TEXT.count(o + "\n") == 0 or o.strip() == "ecco_fbcap::TextBuf t = ecco_fbcap::b2_text(lp, p, lw, w, e.why, 0, 0);" for o, _n in rep_lines)
          and all(o.startswith("            ") for o, _n in cls_edits))

    # parsed sections
    BASE = ds.load_firmware_text(BASE_TEXT)
    FW = ds.load_firmware_text(FW_TEXT)
    changed = sorted(k for k in set(BASE) | set(FW) if k != "_text" and BASE.get(k) != FW.get(k))
    check("only the esphome block, api, globals, switch, script and interval differ in the parsed firmware: no other section "
          "(substitutions, sensor, binary_sensor, text_sensor, number, select, button, wifi, ota, logger, debug, uart, modbus, time, ...) changed",
          changed == ["api", "esphome", "globals", "interval", "script", "switch"], str(changed))
    check("every pre-existing item of globals / switch / api actions is identical and in its original order (none removed, reordered or "
          "altered); the new ones are appended at the end (18 globals, 1 switch, 1 api action)",
          FW["globals"][:len(BASE["globals"])] == BASE["globals"] and len(FW["globals"]) == len(BASE["globals"]) + 18
          and FW["switch"][:len(BASE["switch"])] == BASE["switch"] and len(FW["switch"]) == len(BASE["switch"]) + 1
          and FW["api"]["actions"][:2] == BASE["api"]["actions"] and len(FW["api"]["actions"]) == 3
          and {k: v for k, v in FW["api"].items() if k != "actions"} == {k: v for k, v in BASE["api"].items() if k != "actions"})
    rs_b, rs_l = raw_scripts(BASE_TEXT), raw_scripts(FW_TEXT)
    last_pre = list(rs_b)[-1]
    banner = scope.SCRIPTS_BLOCK[:scope.SCRIPTS_BLOCK.index("  - id: fallback_profile_save" + chr(10))]
    touched = [k for k in rs_b if rs_b[k] != rs_l.get(k) and k != last_pre]
    check("every one of the 33 pre-existing scripts is in its original order; exactly two are changed as raw text - the FB-B1 review gate and "
          "the FB-B1 capture dispatch - every other one is byte-identical (the Free Power / Dump / Manual TOU / reg244 / clock writer scripts "
          "and the FB-B1 invalidate_candidate script included); the only other textual difference is that the last of them is followed by "
          "the new block's banner comment before the first new script; the two new scripts follow",
          len(rs_b) == 33 and last_pre == "fallback_profile_invalidate_candidate" and list(rs_l)[:33] == list(rs_b)
          and sorted(touched) == ["fallback_profile_capture_dispatch", "fallback_profile_review"] and rs_l[last_pre] == rs_b[last_pre] + banner
          and list(rs_l)[33:] == list(scope.SCRIPT_IDS), str(touched))
    h_rev = scope.hunk("review_arm_off")
    check("the review gate's only change is the one 2-line arm turn-off (a comment and `id(fallback_profile_arm).turn_off();`), nothing else",
          rs_l["fallback_profile_review"].replace(h_rev.new, "", 1) == rs_b["fallback_profile_review"]
          and h_rev.new.count("\n") == 2 and h_rev.new.rstrip().endswith("id(fallback_profile_arm).turn_off();"))
    disp_names = ("dispatch_drain", "final_guard", "final_overlay", "final_state_name", "final_b2", "final_ri_cls", "final_arm_off",
                  "final_prior_class", "final_b3", "final_not_saveable", "save_final", "release_ctx")
    part = FW_TEXT
    for h in reversed(hunks):
        if h.name in disp_names:
            part = scope._swap(part, h.after, h.before, h.name, "present")
    disp_back = raw_scripts(part)["fallback_profile_capture_dispatch"]
    check("the capture dispatch with exactly its twelve hunks reverted (drain, REVIEW_FINAL guard / overlay / arm-off, SAVE_FINAL parts, RELEASE "
          "clear; the five class / B2 replacements restored) is byte-identical to the FB-B1 dispatch: its four Modbus nodes and every other "
          "line did not move; the other nine hunks lie outside it", len(disp_names) == 12 and disp_back == rs_b["fallback_profile_capture_dispatch"])
    new_iv = [i for i in FW["interval"] if i not in BASE["interval"]]
    iv_at = FW["interval"].index(new_iv[0]) if len(new_iv) == 1 else -1
    check("parsed intervals: still 11, in the same order; exactly ONE differs (the FB-B1 housekeeping interval, still between the Free Power "
          "evidence-expiry interval and FB-C1's, not last) and the Manual TOU tick is still the last",
          len(FW["interval"]) == len(BASE["interval"]) == 11 and len(new_iv) == 1 and iv_at == len(BASE["interval"]) - 4
          and [i for i in FW["interval"] if i in BASE["interval"]] == [i for k, i in enumerate(BASE["interval"]) if k != iv_at]
          and "free_power_recovery_invalidate_evidence" in yaml.dump(FW["interval"][iv_at - 1])
          and "failback_shadow_ready" in yaml.dump(FW["interval"][iv_at + 1]) and FW["interval"][-1] == BASE["interval"][-1], f"at {iv_at}")
    old_iv = BASE["interval"][iv_at]

    def _undent(block: str) -> str:
        return "".join(ln[10:] if ln.strip() else ln for ln in block.splitlines(True))

    check("that interval is still `10s`, now with TWO lambda actions: the first is the FB-B1 lambda with exactly the breaker's SAVE-context "
          "clear added, the second (arm lifetime, IE8) is new and is the LAST action; no interval was added",
          new_iv[0]["interval"] == old_iv["interval"] == "10s" and item_kinds(old_iv["then"]) == ["lambda"] and item_kinds(new_iv[0]["then"]) == ["lambda", "lambda"]
          and mutate(new_iv[0]["then"][0]["lambda"], _undent(scope.hunk("breaker_ctx").new), "") == old_iv["then"][0]["lambda"]
          and new_iv[0]["then"][1]["lambda"].count("fallback_profile_arm).turn_off()") == 1
          and {k: v for k, v in new_iv[0].items() if k != "then"} == {k: v for k, v in old_iv.items() if k != "then"})
    esp_b, esp_l = BASE["esphome"], FW["esphome"]
    ob_b, ob_l = esp_b["on_boot"], esp_l["on_boot"]
    boot_old = ob_b["then"][-1]["lambda"]
    boot_new = ob_l["then"][-1]["lambda"]
    check("esphome: only the includes (one entry appended LAST) and on_boot item [3] differ; on_boot keeps its priority and its four items, "
          "items [0] .. [2] are untouched, and item [3] (the FB-B1 boot lambda) differs from FB-B1 only by its one B2 line",
          {k: v for k, v in esp_b.items() if k not in ("includes", "on_boot")} == {k: v for k, v in esp_l.items() if k not in ("includes", "on_boot")}
          and esp_l["includes"] == esp_b["includes"] + [FBB2_NEW_INCLUDE] and esp_b["includes"][-1] == "include/ecco_fallback_capture.h"
          and {k: v for k, v in ob_b.items() if k != "then"} == {k: v for k, v in ob_l.items() if k != "then"}
          and len(ob_l["then"]) == len(ob_b["then"]) == 4 and ob_l["then"][:3] == ob_b["then"][:3]
          and boot_new == boot_old.replace("e.why, 0, 0);", "e.why, id(fallback_durable_last_err), id(fallback_durable_last_us));"), str(len(ob_l["then"])))

    # -----------------------------------------------------------------------
    print("")
    print("[2] The inserted blocks against the parsed firmware and the scope tables; STATIC PINS")
    # -----------------------------------------------------------------------
    ctx = Ctx(FW_TEXT)
    new_g = FW["globals"][len(BASE["globals"]):]
    check("the 18 new globals are exactly _fbb2_scope.GLOBALS, in order, with their types and initial values, every one restore_value: no; "
          "ids are unique; the hand-over / context globals are fallback_profile_save_*, the write results fallback_durable_last_*",
          [(g["id"], g["type"], (str(g["initial_value"]) if "initial_value" in g else None)) for g in new_g] == scope.GLOBALS
          and len(new_g) == 18 == len(scope.NEW_GLOBAL_IDS) == len(set(scope.NEW_GLOBAL_IDS)) and all(g.get("restore_value") is False for g in new_g)
          and all(re.match(r"fallback_(profile_(exec|arm|save)|durable_last)_", g["id"]) for g in new_g)
          and sum("std::array" in g["type"] for g in new_g) == 1)
    check("no global is reused: every new id is absent from the FB-B1 firmware text (nothing shadows a pre-existing global)",
          all(f"- id: {g['id']}\n" not in BASE_TEXT and BASE_TEXT.count(g["id"]) == 0 for g in new_g))
    new_s = FW["script"][len(BASE["script"]):]
    check("the 2 new scripts are exactly _fbb2_scope.SCRIPT_IDS (the SAVE gate and the synchronous INVALIDATE), both mode: single, and the "
          "block starts with a banner comment", tuple(s["id"] for s in new_s) == scope.SCRIPT_IDS == FBB2_SCRIPTS
          and all(s.get("mode") == "single" for s in new_s) and scope.SCRIPTS_BLOCK.lstrip("\n").startswith("  # ====="))
    check("the arm switch's Home Assistant id is switch.ecco_clock_dongle_ecco_fallback_profile_arm (the id the card config and the "
          "dashboard test use)", scope.SWITCH_HA_ID == "switch.ecco_clock_dongle_ecco_fallback_profile_arm")
    check("the parsed scope tables agree with the firmware (the scope module's name tables are not stale)",
          not table_violations(scope, ctx), str(table_violations(scope, ctx)))
    for name, (label, fn) in STATIC.items():
        viol = fn(ctx)
        check(f"[{name}] {label}", not viol, "; ".join(viol)[:300])

    # -----------------------------------------------------------------------
    print("")
    print("[3] FB-T0 scope-chain registration (registry/tests/_scope_chain.py entry `fbb2`): exact, nothing by prefix")
    # -----------------------------------------------------------------------
    check("fbb2 is appended to the chain directly after fbb1 (merge order: ... fbc1 -> fbb0 -> fbb1 -> fbb2); later PRs append after it",
          CH.ids()[:7] == ["fba", "mtou1", "dump_v2", "fbc1", "fbb0", "fbb1", "fbb2"] and E.pr == "FB-B2"
          and (E.commit == "unmerged" or re.fullmatch(r"[0-9a-f]{7,40}", E.commit) is not None), str(CH.ids()))
    check("fbb2's reverter is _fbb2_scope.pre_fbb2_firmware (firmware YAML) and nothing else (no header, registry, capabilities or manifest edit)",
          dict(E.reverts) == {chain.FIRMWARE: scope.pre_fbb2_firmware} and set(E.checkpoints) == {chain.FIRMWARE})
    check("fbb2's checkpoint is the sha256 of the firmware AS OF fbb2 (the live LF text), and reverting fbb2 reproduces fbb1's firmware "
          "checkpoint (aa0d9f52...); the pinned manifest / headers / capabilities are untouched by fbb2",
          E.checkpoints[chain.FIRMWARE] == sha(FW_TEXT) == CH2.checkpoint(chain.FIRMWARE, "fbb2")
          and sha(scope.pre_fbb2_firmware(FW_TEXT)) == CH2.checkpoint(chain.FIRMWARE, "fbb1") == FBB1_FW_SHA
          and all(CH2.checkpoint(p, "fbb2") == CH2.checkpoint(p, "fbb1") for p in chain.PINNED if p != chain.FIRMWARE)
          and all(sha(LIVE_FBB2[p]) == CH2.checkpoint(p, "fbb2") for p in chain.PINNED))
    check("fbb2 declares EXACTLY +2 scripts, +18 globals, +1 api action, +1 switch, +1 include - and no other metric (Modbus reads / writes, "
          "commit / load / status sites, durable tag strings, sensors, binary sensors, text sensors, buttons, numbers, selects, intervals, "
          "substitutions all 0)",
          dict(E.deltas) == FBB2_DELTAS and dict(E.deltas) == {"scripts": len(scope.SCRIPT_IDS), "globals": len(scope.GLOBALS), "api_actions": 1,
                                                              "switches": 1, "includes": len(scope.ADDED_INCLUDES)}
          and E.subst_added == {} and E.subst_changed == {} and tuple(E.subst_removed) == (), str(dict(E.deltas)))
    check("fbb2 declares exactly ONE new op path (the SAVE gate: it only script.execute()s the existing dispatch; the INVALIDATE script is "
          "not an analyzer path), exactly the one new include (appended last), the 12 banned-token occurrences, no new banned FILE, no "
          "FB-A-header includer and no durable tag",
          E.op_paths_changed == FBB2_OP_PATHS and E.includes_added == (FBB2_NEW_INCLUDE,) == scope.ADDED_INCLUDES and E.banned_fw_added == FBB2_BANNED
          == scope.BANNED_FW_ADDED and E.banned_files == frozenset() and E.fbh_includers == frozenset()
          and E.tags_declared == frozenset() and E.tags_promoted == frozenset())
    _rows = [r for r in chain.integrity_report(CH2, LIVE_FBB2) if r[0].startswith("fbb2:")]
    check("the chain's own integrity report for fbb2 is all green (checkpoints, non-identity reverters, nothing else moved, declared "
          "deltas == measured, op paths, includes, substitutions) over the artifacts as of fbb2, and the whole (live) chain is green",
          len(_rows) == 8 and all(ok for _n, ok, _d in _rows) and all(ok for _n, ok, _d in chain.integrity_report(CH2, LIVE_FBB2))
          and all(ok for _n, ok, _d in chain.integrity_report(CH)), str([(n, d) for n, ok, d in _rows if not ok]))
    banned_by_hunk = {h.name: len(chain.BANNED.findall(h.new)) - len(chain.BANNED.findall(h.old)) for h in hunks}
    check("banned-token accounting: FB-B2 adds exactly 12 occurrences of the FB-A reserved tokens to the firmware YAML - 1 in the include "
          "line, 5 in SAVE_FINAL, 6 in the two scripts; none in the api action, globals, switch, the dispatch / review edits, the "
          "interval or the replacement lines; the declared total is 27 + 12",
          sum(banned_by_hunk.values()) == 12 == scope.BANNED_FW_ADDED == len(chain.BANNED.findall(FW_TEXT)) - len(chain.BANNED.findall(BASE_TEXT))
          and {k: v for k, v in banned_by_hunk.items() if v} == {"include": 1, "save_final": 5, "scripts": 6} and banned_by_hunk == scope.BANNED_FW_BY_HUNK
          and len(chain.BANNED.findall(FW_TEXT)) == CH2.declared_banned_fw() == 4 + 14 + 9 + 12, str(banned_by_hunk))
    check("the scope module restates the FB-A banned-token pattern identically to the chain (it cannot import the chain)",
          scope._BANNED.pattern == chain.BANNED.pattern)
    leaks = banned_leaks()
    check("no NEW banned file: the FB-A scan over home-assistant/ frontend/ deployment/ equals the chain's declared banned files; FB-B2 itself "
          "declares none (the dashboard YAML is FB-B1's); the card, its tests and README and every file no entry names spell no reserved token "
          "(FB-B3: its entry declares its own exact files, nothing else)",
          banned_files_agree(CH, leaks) and not CH.entry("fbb2").banned_files and CH.entry("fbb1").banned_files == {"home-assistant/dashboards/ecco_pro.yaml"}
          # FB-C3: its entry declares its own exact file (the HA suite that spells ecco_fallback entity ids), nothing else
          and set(leaks) == set(CH.entry("fbb1").banned_files) | set(CH.entry("fbb3").banned_files) | set(CH.entry("fbc3").banned_files), str(leaks))
    scan_dirs = ("firmware", "registry", "tools", "home-assistant", "frontend", "deployment", "health", "influxdb", ".github")
    suffixes = {".h", ".hpp", ".c", ".cpp", ".yaml", ".yml", ".py", ".ts", ".js", ".json", ".ps1", ".psm1", ".sh", ".jinja"}
    fb_a_tests = {"registry/tests/test_fallback_profile_schema.py", "registry/tests/test_fallback_profile_host_compile.py"}
    includers = sorted(p.relative_to(ROOT).as_posix() for d in scan_dirs if (ROOT / d).is_dir() for p in (ROOT / d).rglob("*")
                       if p.is_file() and p.suffix in suffixes and ".esphome" not in p.parts and "node_modules" not in p.parts
                       and p.relative_to(ROOT).as_posix() not in fb_a_tests
                       and re.search(r'#\s*include\s*[<"][^>"]*ecco_fallback_profile\.h|-\s*include/ecco_fallback_profile\.h',
                                     p.read_text(encoding="utf-8", errors="ignore")))
    check("no FB-B2 file includes the FB-A header: the includers are still exactly the chain's declared ones (the firmware YAML's own include "
          "list and the FB-B0 model header), so fbb2 declares none (the SAVE header includes only the model and capture headers)",
          set(includers) == set(CH.declared_includers()) - fb_a_tests and E.fbh_includers == frozenset() and not any(f in includers for f in E.added_files),
          str(includers))
    hdr_text = (INCLUDE_DIR / NEW_HEADER).read_text(encoding="utf-8")
    inc_lines = sorted(re.findall(r'#\s*include\s*([<"][^>"]+[>"])', hdr_text))
    check("the SAVE header includes exactly <array> <cstddef> <cstdint> <type_traits>, the FB-B0 model header and the capture header - no "
          "ESPHome / NVS / Modbus / FB-A include", inc_lines == sorted(['<array>', '<cstddef>', '<cstdint>', '<type_traits>',
                                                                          '"ecco_fallback_durable_model.h"', '"ecco_fallback_capture.h"']), str(inc_lines))
    check("the SAVE header declares NO durable tag and holds no durable-looking `ecco_<words>_v<N>` literal (tags_declared stays empty)",
          not [k for k in ti.all_declared_tags(INCLUDE_DIR) if k.startswith(f"{NEW_HEADER}:")]
          and not ti.unaccounted_literals(hdr_text, set(ti.all_declared_tags(INCLUDE_DIR).values())))
    declared_all = frozenset().union(*(e_.added_files for e_ in CH.entries))
    named = named_files_on_disk()
    check("added_files is the exact set of NEW repo files FB-B2 adds: every declared path exists, every FB-B2-named file on disk "
          "(_fbb2_*, test_fallback_save_*, test_fallback_invalidate*, the SAVE header, the mirror) is declared, all are exact POSIX paths "
          "(no glob / prefix), and the entry equals _fbb2_scope.ADDED_FILES",
          E.added_files == scope.ADDED_FILES and not files_violations(E.added_files, named) and named <= set(declared_all),
          "; ".join(files_violations(E.added_files, named)))
    check("added_files is disjoint from every other entry's added_files and from banned_files; none of them is a chain-pinned artifact; the "
          "ones FB-B1's glob pins police (_fbb1_*, test_fallback_capture_*, test_fallback_profile_capture, test_fallback_recovery_dashboard, "
          "fallback_capture.py, the capture header) are NOT redeclared here",
          all(not (E.added_files & other.added_files) for other in CH.entries if other.id != "fbb2") and not (E.added_files & E.banned_files)
          and not (E.added_files & set(chain.PINNED)) and not any(f.startswith("registry/tests/_fbb1_") or "test_fallback_capture_" in f for f in E.added_files)
          and "firmware/include/ecco_fallback_capture.h" not in E.added_files)
    check("the header directory is exactly the known headers plus FB-B2's one new header (a later PR declares its own in added_files)",
          sorted(p.name for p in INCLUDE_DIR.glob("*") if p.name not in {Path(f).name for e_ in CH.after("fbb2") for f in e_.added_files})
          == sorted(["ecco_durable_snapshot.h", "ecco_fallback_capture.h", "ecco_fallback_durable.h", "ecco_fallback_durable_model.h",
                     "ecco_fallback_profile.h", "ecco_fallback_save.h", "ecco_fallback_version_pins.h", "ecco_recovery_evidence.h"]))
    check("ordering: the chain reverts fbb2 first - fbb2's reverter needs no later entry; fbb0's include-list reverter on the live text "
          "refuses (the capture and save includes sit between its anchors), and fbb2 -> fbb1 -> fbb0 -> fbc1 reproduces every checkpoint",
          _raises(lambda: fbbs.pre_fbb0_firmware(FW_TEXT))
          and sha(fbbs.pre_fbb0_firmware(scope1.pre_fbb1_firmware(scope.pre_fbb2_firmware(FW_TEXT)))) == CH.checkpoint(chain.FIRMWARE, "fbc1")
          == "dd9bc59890d6d514c8e60f6a6c6a48615192429f414df2c244c26b9d9950d6d3"
          and scope.hunk("include").left.endswith("    - " + scope1.ADDED_INCLUDES[-1] + "\n") and scope.hunk("include").right.startswith("\n  on_boot:\n"))

    # -----------------------------------------------------------------------
    print("")
    print("[4] THE MEASUREMENT REPORT: base (FB-B1, main @ 65e4be5) versus the working tree, measured live")
    # -----------------------------------------------------------------------
    # Headers a LATER chain entry declares (FB-B3 ...) are not FB-B2's to measure: the table is the FB-B2 difference only.
    later_headers = {Path(f).name for e_ in CH.after("fbb2") for f in e_.added_files}
    live_headers = {p.name: p.read_text(encoding="utf-8") for p in sorted(INCLUDE_DIR.glob("*.h")) if p.name not in later_headers}
    git_headers = git_base_headers()
    base_headers = git_headers if git_headers is not None else {n: t for n, t in live_headers.items() if n != NEW_HEADER}
    base_src = "git 65e4be5" if git_headers is not None else "live headers minus the new one (git base not available)"
    S_BASE = survey(BASE_TEXT, base_headers)
    S_LIVE = survey(FW_TEXT, live_headers)
    mb, ml = S_BASE["metrics"], S_LIVE["metrics"]
    nb, nl = S_BASE["names"], S_LIVE["names"]
    new_names = {k: [x for x in nl[k] if x not in nb[k]] for k in nl}
    rows = [
        ("scripts", mb["scripts"], ml["scripts"], delta(mb["scripts"], ml["scripts"]), ", ".join(new_names["scripts"])),
        ("globals", mb["globals"], ml["globals"], delta(mb["globals"], ml["globals"]), f"{len(new_names['globals'])} new, all restore_value no, RAM only"),
        ("api actions", mb["api_actions"], ml["api_actions"], delta(mb["api_actions"], ml["api_actions"]), ", ".join(new_names["api_actions"])),
        ("switches", mb["switches"], ml["switches"], delta(mb["switches"], ml["switches"]), ", ".join(new_names["switches"])),
        ("text sensors / buttons", f"{mb['text_sensors']} / {mb['buttons']}", f"{ml['text_sensors']} / {ml['buttons']}", "+0 / +0", "no new text sensor, no new button"),
        ("sensors / binary / numbers / selects", f"{mb['sensors']} / {mb['binary_sensors']} / {mb['numbers']} / {mb['selects']}",
         f"{ml['sensors']} / {ml['binary_sensors']} / {ml['numbers']} / {ml['selects']}", "+0", "unchanged"),
        ("intervals", mb["intervals"], ml["intervals"], delta(mb["intervals"], ml["intervals"]), "the 10 s housekeeping interval gained a 2nd lambda"),
        ("substitutions", mb["substitutions"], ml["substitutions"], delta(mb["substitutions"], ml["substitutions"]), "none"),
        ("includes", mb["includes"], ml["includes"], delta(mb["includes"], ml["includes"]), ", ".join(new_names["includes"])),
        ("Modbus READ ops (analyzer)", mb["modbus_reads"], ml["modbus_reads"], delta(mb["modbus_reads"], ml["modbus_reads"]), "SAVE reuses the dispatch's 4 FC03 nodes"),
        ("Modbus WRITE ops (analyzer)", mb["modbus_writes"], ml["modbus_writes"], delta(mb["modbus_writes"], ml["modbus_writes"]), "MUST be zero: no inverter write"),
        ("modbus_client. text sites", S_BASE["modbus_text"], S_LIVE["modbus_text"], delta(S_BASE["modbus_text"], S_LIVE["modbus_text"]), "no new Modbus node of any kind"),
        ("analyzer write paths (total)", len(S_BASE["paths"]), len(S_LIVE["paths"]), delta(len(S_BASE["paths"]), len(S_LIVE["paths"])),
         ", ".join(sorted(set(S_LIVE["paths"]) - set(S_BASE["paths"]))) + " (no ops: it only script.execute()s the dispatch)"),
        ("analyzer bus_access_findings", S_BASE["bus_findings"], S_LIVE["bus_findings"], delta(S_BASE["bus_findings"], S_LIVE["bus_findings"]), "unknown-extent writes 0"),
        ("op path whose ops changed", "-", "-", "-", f"{sorted(set(S_LIVE['paths']) ^ set(S_BASE['paths']))} only; dispatch ops still {len(S_LIVE['paths']['fallback_profile_capture_dispatch'])} reads"),
        ("ecco_durable commit/load/status sites", f"{mb['commit_record']}/{mb['load_record']}/{mb['load_record_status']}",
         f"{ml['commit_record']}/{ml['load_record']}/{ml['load_record_status']}", "+0", "legacy durable surface untouched"),
        ("ecco_fbdurable::commit_transition_t(", S_BASE["commit_calls"], S_LIVE["commit_calls"], delta(S_BASE["commit_calls"], S_LIVE["commit_calls"]),
         " + ".join(f"{l}" for l in S_LIVE["commit_sites"])),
        ("nvs_set_blob call sites (headers)", sum(base_headers_sites := {n: len(re.findall(r"\bnvs_set_blob\s*\(", strip_cpp(t))) for n, t in base_headers.items()}.values()),
         sum(S_LIVE["nvs_set_blob"].values()), "+0", f"{DURABLE_ADAPTER} only ({base_src})"),
        ("write_one_<> instantiations", sum(len(re.findall(r"\bwrite_one_\s*<", strip_cpp(t))) for t in base_headers.values()), sum(S_LIVE["write_one_inst"].values()),
         "+0", "FBW then FBP in the model header; no third WriteTarget, no FBS write"),
        ("direct NVS tokens in YAML code", 0, len(S_LIVE["yaml_write_tokens"]), "+0", "nvs_set* / erase / commit / write_one_ / WriteTarget: none (1 comment mention)"),
        ("ecco_fbdurable::EspNvs locals", S_BASE["fbdur"]["EspNvs"], S_LIVE["fbdur"]["EspNvs"], delta(S_BASE["fbdur"]["EspNvs"], S_LIVE["fbdur"]["EspNvs"]), "reads + the two commit lambdas"),
        ("ecco_fbdurable::read_direct_t uses", S_BASE["fbdur"]["read_direct_t"], S_LIVE["fbdur"]["read_direct_t"], delta(S_BASE["fbdur"]["read_direct_t"], S_LIVE["fbdur"]["read_direct_t"]), "fresh reads in the final lambdas"),
        ("nvs_healthy / mirror_after / note_committed", f"{S_BASE['fbdur']['nvs_healthy']}/{S_BASE['fbdur']['mirror_after']}/{S_BASE['fbdur']['note_committed']}",
         f"{S_LIVE['fbdur']['nvs_healthy']}/{S_LIVE['fbdur']['mirror_after']}/{S_LIVE['fbdur']['note_committed']}", "-", "after-commit mirror / latch notes"),
        ("FBP key 1609458070 / 0x5FEE6196 (YAML uses)", S_BASE["key_use"]["FALLBACK_PROFILE_KEY"], S_LIVE["key_use"]["FALLBACK_PROFILE_KEY"],
         delta(S_BASE["key_use"]["FALLBACK_PROFILE_KEY"], S_LIVE["key_use"]["FALLBACK_PROFILE_KEY"]), "via ecco_fbdurable::FALLBACK_PROFILE_KEY; tag ecco_fallback_profile_v1 (FB-A header)"),
        ("FBW key 1000595297 / 0x3BA3DF61 (YAML uses)", S_BASE["key_use"]["FAILBACK_PROVISION_KEY"], S_LIVE["key_use"]["FAILBACK_PROVISION_KEY"],
         delta(S_BASE["key_use"]["FAILBACK_PROVISION_KEY"], S_LIVE["key_use"]["FAILBACK_PROVISION_KEY"]), "via ecco_fbdurable::FAILBACK_PROVISION_KEY; tag ecco_failback_provision_v1 (FB-B0 model)"),
        ("FBS key 2156168643 / 0x808485C3 (YAML uses)", S_BASE["key_use"]["FAILBACK_STATE_KEY"], S_LIVE["key_use"]["FAILBACK_STATE_KEY"], "+0",
         "READ-ONLY: named once, by the FB-B1 boot load; FB-B2 never names or writes it (tag ecco_failback_state_v1)"),
        ("durable tag strings / declared tags", f"{mb['durable_tag_strings']} / {sum(len(v) for v in S_BASE['tags'].values())}",
         f"{ml['durable_tag_strings']} / {sum(len(v) for v in S_LIVE['tags'].values())}", "+0 / +0", "the tag inventory is unchanged: no new tag, no new key"),
        ("banned tokens in firmware (FB-A)", mb["banned_fw"], ml["banned_fw"], delta(mb["banned_fw"], ml["banned_fw"]),
         "; ".join(f"{k}: {S_BASE['banned'].get(k, 0)}->{S_LIVE['banned'].get(k, 0)}" for k in sorted(set(S_LIVE['banned']) | set(S_BASE['banned'])))),
        ("  ... where (hunk)", "-", "-", "-", ", ".join(f"{k} +{v}" for k, v in banned_by_hunk.items() if v)),
        ("ESP_LOG sites (by tag)", sum(S_BASE["log_tags"].values()), sum(S_LIVE["log_tags"].values()), delta(sum(S_BASE["log_tags"].values()), sum(S_LIVE["log_tags"].values())),
         "new tag: " + ", ".join(f"{t} x{S_LIVE['log_tags'][t] - S_BASE['log_tags'].get(t, 0)}" for t in sorted(S_LIVE["log_tags"]) if S_LIVE["log_tags"][t] != S_BASE["log_tags"].get(t, 0)) + " (lambda text only)"),
        ("'supervision' mentions", S_BASE["sup"], S_LIVE["sup"], delta(S_BASE["sup"], S_LIVE["sup"]), "the heartbeat snapshot line of the api action (2) + the commit-time re-check of SAVE_FINAL part 2 (2)"),
        ("'ntp_' mentions", S_BASE["ntp"], S_LIVE["ntp"], delta(S_BASE["ntp"], S_LIVE["ntp"]), "SAVE gate (2) + SAVE_FINAL part 2 (3): trusted time"),
        ("firmware YAML lines", len(BASE_TEXT.split("\n")) - 1, len(FW_TEXT.split("\n")) - 1, delta(len(BASE_TEXT.split("\n")), len(FW_TEXT.split("\n"))),
         f"{sum(inserts)} lines inserted in 14 blocks, 7 lines replaced one for one, 0 deleted"),
        ("added repo files", "-", len(E.added_files), "-", f"{len(E.added_files)} declared by fbb2 (listed below)"),
    ]
    print(f"  (base = {base_src} for the headers; the FB-B1 firmware = the exact reverter output, sha-checked == git base when available)")
    print(fmt_table(rows))
    print("  new globals (" + str(len(new_names["globals"])) + "): " + ", ".join(new_names["globals"]))
    print("  new scripts: " + ", ".join(new_names["scripts"]) + "; new api action: " + ", ".join(new_names["api_actions"])
          + "; new switch: " + ", ".join(new_names["switches"]) + "; new include: " + ", ".join(new_names["includes"]))
    print("  added files (" + str(len(E.added_files)) + "): " + ", ".join(sorted(E.added_files)))
    print("  banned-token occurrences added: " + str([(h, n) for h, n in banned_by_hunk.items() if n]) + "; per token kind "
          + str({k: S_LIVE["banned"][k] - S_BASE["banned"].get(k, 0) for k in S_LIVE["banned"] if S_LIVE["banned"][k] != S_BASE["banned"].get(k, 0)}))
    banned_where = []
    for h in hunks:
        at = FW_TEXT.index(h.after) + len(h.left)
        for m in chain.BANNED.finditer(h.new):
            line_no = FW_TEXT.count("\n", 0, at + m.start()) + 1
            banned_where.append((line_no, h.name, m.group(0), FW_TEXT.split("\n")[line_no - 1].strip()[:70]))
    print("  banned tokens added (firmware line, hunk, token, line text):")
    for ln_, hn_, tok_, txt_ in sorted(banned_where):
        print(f"      {ln_:6d}  {hn_:10s} {tok_:16s} {txt_}")
    check("the measurement report's deltas equal the declared Entry for EVERY metric: scripts / globals / api actions / switches / includes as "
          "declared, every other of the 20 chain metrics 0, banned_fw == banned_fw_added, the new analyzer paths == op_paths_changed, the new "
          "includes == includes_added, and the 12 banned tokens listed above are exactly the per-hunk count",
          {k: ml[k] - mb[k] for k in ml if k != "banned_fw" and ml[k] != mb[k]} == dict(E.deltas)
          and ml["banned_fw"] - mb["banned_fw"] == E.banned_fw_added == len(banned_where)
          and frozenset(set(S_LIVE["paths"]) ^ set(S_BASE["paths"])) == E.op_paths_changed
          and tuple(new_names["includes"]) == E.includes_added and set(new_names["scripts"]) == set(scope.SCRIPT_IDS),
          str({k: (mb[k], ml[k]) for k in ml if mb[k] != ml[k]}))
    viol = survey_violations(S_BASE, S_LIVE)
    check("MEASURED, not declared: Modbus READ 64 -> 64 and WRITE 52 -> 52 (ZERO write delta, no new modbus_client node of any kind); analyzer "
          "paths 46 -> 47 with exactly fallback_profile_save added (no ops of its own), the capture dispatch's op list is still the four reads "
          "230/3, 241/53, 230/3, 241/53, and bus_access_findings 0",
          not [x for x in viol if "Modbus" in x or "modbus_client" in x or "analyzer" in x or "dispatch op list" in x or "SAVE gate path" in x], "; ".join(viol))
    check("MEASURED: the durable writer surface - commit_transition_t 0 -> 2 call sites (SAVE_FINAL part 2 and the INVALIDATE lambda, one each), "
          "nvs_set_blob call sites 1 -> 1 (the FB-B0 adapter), write_one_ instantiations 2 -> 2 and WriteTarget specialisations 2, no FBS write, no "
          "direct NVS token in any YAML lambda; the legacy durable surface 57 / 7 / 3 and 13 tag strings is identical",
          not [x for x in viol if "commit" in x or "nvs" in x or "write_one_" in x or "durable surface" in x or "load_record" in x or "NVS" in x], "; ".join(viol))
    check("MEASURED: exact key / tag usage - the YAML names only the FBP (1609458070 / 0x5FEE6196) and FBW (1000595297 / 0x3BA3DF61) constants "
          "(never a numeric key, never FBS 2156168643), the durable tag inventory of the headers is byte-for-byte the FB-B1 one, the new header "
          "declares none and holds no durable-looking literal",
          not [x for x in viol if "key" in x or "tag" in x or "literal" in x], "; ".join(viol))
    check("MEASURED: banned_fw 27 -> 39 (+12: include 1, SAVE_FINAL 5, scripts 6), the 20 chain metrics are base + the declared deltas, "
          "scripts / includes / text sensors / buttons are the declared ones",
          not [x for x in viol if "banned" in x or "metrics" in x or "scripts" in x or "include" in x or "text_sensors" in x or "buttons" in x], "; ".join(viol))
    check("the measured base equals the independently typed FB-B1 numbers (scripts 33, globals 510, api 2, switches 9, reads 64, writes 52, "
          "banned 27 ...) and the measured head equals base + the typed FB-B2 deltas", mb == FBB1_METRICS and ml == FBB2_METRICS,
          str({k: (mb[k], FBB1_METRICS[k], ml[k], FBB2_METRICS[k]) for k in FBB1_METRICS if mb[k] != FBB1_METRICS[k] or ml[k] != FBB2_METRICS[k]}))
    check("the whole measured difference is satisfied (no violation of any expectation)", not viol, "; ".join(viol))
    if git_headers is not None:
        check("git cross-check of the header side: the base headers (git 65e4be5) differ from the working tree only by the one new header and "
              "the additive capture-header / mirror edits - every other header is byte-identical, and the new header is not in the base",
              NEW_HEADER not in git_headers and {n for n in live_headers if n in git_headers and live_headers[n] != git_headers[n]} <= {"ecco_fallback_capture.h"}
              and set(live_headers) - set(git_headers) == {NEW_HEADER}, str({n for n in live_headers if n in git_headers and live_headers[n] != git_headers[n]}))
    del base_headers_sites

    # -----------------------------------------------------------------------
    print("")
    print("[5] Negative controls: a mis-declared fbb2 entry and every undeclared edit are refused by the chain, never absorbed")
    # -----------------------------------------------------------------------
    def _with(**kw) -> "chain.Chain":
        d = {f: getattr(E, f) for f in E.__dataclass_fields__}
        d.update(kw)
        return chain.Chain(CH.upto("fbb1") + (chain.Entry(**d),))

    def _fails(ch, live, needle) -> bool:
        return any((not ok) and needle in n for n, ok, _d in chain.integrity_report(ch, live))

    def _any_fail(ch, live) -> bool:
        return any(not ok for _n, ok, _d in chain.integrity_report(ch, live))

    _live = dict(LIVE_FBB2)
    check("control: the unmodified entry over the live artifacts is green (so each failure below is caused by its own change)",
          not _any_fail(_with(), _live))
    check("negative: a WRONG delta (3 scripts) and a MISSING delta (no globals / no api action / no switch) are detected",
          _fails(_with(deltas={**E.deltas, "scripts": 3}), _live, "declared deltas")
          and all(_fails(_with(deltas={k: v for k, v in E.deltas.items() if k != drop}), _live, "declared deltas") for drop in ("globals", "api_actions", "switches", "includes")))
    check("negative: a declared Modbus WRITE, a declared Modbus read, a declared commit / load site and a declared interval / text sensor / button "
          "the firmware does not add are detected (the zero-write / zero-legacy-durable delta is measured, not assumed)",
          all(_fails(_with(deltas={**E.deltas, m: 1}), _live, "declared deltas") for m in
              ("modbus_writes", "modbus_reads", "commit_record", "load_record", "load_record_status", "intervals", "text_sensors", "buttons", "substitutions",
               "durable_tag_strings")))
    check("negative: a wrong op path, a missing one and an extra one are detected",
          _fails(_with(op_paths_changed=frozenset({"fallback_profile_save", "fallback_profile_invalidate"})), _live, "op_paths_changed")
          and _fails(_with(op_paths_changed=frozenset()), _live, "op_paths_changed")
          and _fails(_with(op_paths_changed=frozenset({"fallback_profile_capture_dispatch"})), _live, "op_paths_changed")
          and _fails(_with(op_paths_changed=FBB2_OP_PATHS | {"free_power_start"}), _live, "op_paths_changed"))
    check("negative: an UNDECLARED include (includes_added empty), a wrong include, a wrong order / an extra declared include and a wrong "
          "includes delta are detected",
          _fails(_with(includes_added=()), _live, "esphome.includes")
          and _fails(_with(includes_added=("include/ecco_fallback_save_x.h",)), _live, "esphome.includes")
          and _fails(_with(includes_added=("include/ecco_other.h", FBB2_NEW_INCLUDE)), _live, "esphome.includes")
          and _fails(_with(deltas={**E.deltas, "includes": 2}), _live, "declared deltas"))
    check("negative: a declared substitution the firmware does not carry is detected; a prefix / glob substitution declaration is refused by "
          "Chain() itself", _fails(_with(subst_added={"ecco_fallback_save_ms": "1"}), _live, "substitutions added")
          and _raises(lambda: _with(subst_added={"ecco_fallback_*": "1"}), chain.ChainError))
    check("negative: a wrong banned-token count (11 and 13) and a declared banned FILE the scan does not find are detected",
          _fails(_with(banned_fw_added=11), _live, "declared deltas") and _fails(_with(banned_fw_added=13), _live, "declared deltas")
          and not banned_files_agree(_with(banned_files=frozenset({"home-assistant/dashboards/ecco_pro.yaml", "frontend/ecco-fallback-recovery-card/README.md"})), leaks))
    flip = lambda s: ("1" if s[0] != "1" else "2") + s[1:]  # noqa: E731
    check("negative: a WRONG firmware checkpoint is detected (no checkpoint is trusted by prefix)",
          _fails(_with(checkpoints={chain.FIRMWARE: flip(E.checkpoints[chain.FIRMWARE])}), _live, "recorded checkpoint"))
    _live_base = {**_live, chain.FIRMWARE: BASE_TEXT}
    check("negative: a reverter that is an IDENTITY (against a firmware without FB-B2) is detected by name - none is an identity; and the real "
          "entry's reverter is NOT an identity on the live firmware",
          _fails(_with(reverts={chain.FIRMWARE: lambda t: t}, checkpoints={chain.FIRMWARE: sha(BASE_TEXT)}), _live_base, "none is an identity")
          and not _fails(_with(), _live, "none is an identity") and scope.pre_fbb2_firmware(FW_TEXT) != FW_TEXT)
    check("negative: a firmware reverter that is an identity over the LIVE text is detected (fbb1's reverter then no longer applies behind "
          "it), and a reverter without a checkpoint / a checkpoint without a reverter is refused by Chain() itself",
          _any_fail(_with(reverts={chain.FIRMWARE: lambda t: t}), _live)
          and _raises(lambda: _with(checkpoints={}), chain.ChainError)
          and _raises(lambda: _with(checkpoints={chain.FIRMWARE: E.checkpoints[chain.FIRMWARE], chain.HA_MANIFEST: "0" * 64}), chain.ChainError)
          and _raises(lambda: _with(reverts={chain.FIRMWARE: scope.pre_fbb2_firmware, chain.HA_MANIFEST: lambda t: t}, checkpoints=E.checkpoints), chain.ChainError))
    check("negative: a glob / prefix added-file or banned-file declaration is refused by Chain() itself",
          _raises(lambda: _with(added_files=frozenset({"registry/tests/test_fallback_save_*.py"})), chain.ChainError)
          and _raises(lambda: _with(added_files=frozenset({"registry/tests/"})), chain.ChainError)
          and _raises(lambda: _with(banned_files=frozenset({"home-assistant/*.yaml"})), chain.ChainError)
          and _raises(lambda: _with(added_files=frozenset({"registry\\tests\\x.py"})), chain.ChainError))

    def _live_with(fw=None) -> dict:
        return {**_live, chain.FIRMWARE: fw if fw is not None else FW_TEXT}

    _rows_cache: dict = {}

    def _rows(fw: str) -> list:
        k = sha(fw)
        if k not in _rows_cache:
            _rows_cache[k] = chain.integrity_report(CH2, _live_with(fw))
        return _rows_cache[k]

    def _refused_fast(fw: str) -> bool:
        """Every reverter still applies (as_of does not raise) yet the revert no longer reproduces fbb1's checkpoint, and the live text is
        no longer fbb2's checkpoint."""
        return (sha(CH2.as_of(chain.FIRMWARE, "fbb1", fw)) != CH2.checkpoint(chain.FIRMWARE, "fbb1")
                and sha(CH2.as_of(chain.FIRMWARE, "dump_v2", fw)) != CH2.checkpoint(chain.FIRMWARE, "dump_v2") and sha(fw) != E.checkpoints[chain.FIRMWARE])

    def _measured(fw: str) -> dict:
        return chain.measure(CH2.as_of_all("fbb2", _live_with(fw)))

    check("control for the phantom checks below: the UNMODIFIED live firmware is not refused and measures exactly the chain's own numbers",
          not _refused_fast(FW_TEXT) and _measured(FW_TEXT) == ml and not any((not ok) for _n, ok, _d in _rows(FW_TEXT)))
    script_anchor = "\n  - id: restore_reg244_snapshot\n"
    phantom_head = ("\n  - id: fbb2_phantom_script\n    mode: single\n    then:\n      - modbus_client.{}:\n          modbus_id: inverter_modbus\n"
                    "          address: 0x01\n          start_address: 230\n")
    inject_read = mutate(FW_TEXT, script_anchor, phantom_head.format("read_holding_registers") + "          count: 3\n" + script_anchor[1:])
    inject_write = mutate(FW_TEXT, script_anchor, phantom_head.format("write_multiple_registers")
                          + "          values: !lambda 'return std::vector<uint16_t>{1};'\n" + script_anchor[1:])
    m_read, m_write = _measured(inject_read), _measured(inject_write)
    check("negative: a PHANTOM Modbus READ site (a fifth FC03 in a new script) is measured (+1 read, +1 script, a new op path) and refused",
          m_read["modbus_reads"] == ml["modbus_reads"] + 1 and m_read["scripts"] == ml["scripts"] + 1 and m_read["modbus_writes"] == ml["modbus_writes"]
          and "fbb2_phantom_script" in chain.per_path_ops(inject_read, chain._headers_of(LIVE_FBB2)) and _refused_fast(inject_read))
    check("negative: a PHANTOM Modbus WRITE site is measured (+1 write: zero writes is a measured fact, not an assumption) and refused",
          m_write["modbus_writes"] == ml["modbus_writes"] + 1 and m_write["modbus_reads"] == ml["modbus_reads"] and _refused_fast(inject_write))
    inject_commit = mutate(FW_TEXT, script_anchor, "\n  # ecco_durable::commit_record(key, rec) would be a durable write site\n" + script_anchor[1:])
    check("negative: a PHANTOM legacy durable commit site (even in a comment: the count is textual) is measured (+1) and refused",
          _measured(inject_commit)["commit_record"] == ml["commit_record"] + 1 and _refused_fast(inject_commit))
    inject_banned = mutate(FW_TEXT, script_anchor, "\n  # ecco_fallback_extra\n" + script_anchor[1:])
    check("negative: an undeclared extra banned token in the firmware is measured (+1: 40 against the declared 39) and refused",
          _measured(inject_banned)["banned_fw"] == ml["banned_fw"] + 1 and _refused_fast(inject_banned))
    inject_global = mutate(FW_TEXT, "\nnumber:\n", "\n  - id: fbb2_phantom_global\n    type: bool\n    restore_value: no\n    initial_value: 'false'\n\nnumber:\n")
    check("negative: an UNDECLARED extra global is MEASURED (+1: 19 new against the declared 18) and refused although every reverter still applies",
          _measured(inject_global)["globals"] == ml["globals"] + 1 and _any_fail(CH2, _live_with(inject_global)))
    inject_sub = mutate(FW_TEXT, '  ecco_supervision_stable_min_span_ms: "55000"\n', '  ecco_fbb2_extra_ms: "5"\n  ecco_supervision_stable_min_span_ms: "55000"\n')
    inject_inc = mutate(FW_TEXT, "    - include/ecco_durable_snapshot.h\n", "    - include/ecco_extra.h\n    - include/ecco_durable_snapshot.h\n")
    check("negative: an undeclared substitution and an undeclared extra include are each measured (+1) and refused",
          _measured(inject_sub)["substitutions"] == ml["substitutions"] + 1 and _refused_fast(inject_sub)
          and _measured(inject_inc)["includes"] == ml["includes"] + 1 and _refused_fast(inject_inc))
    check("negative: an undeclared edit INSIDE any of the FB-B2 blocks (api action, globals, switch, scripts, SAVE_FINAL, drain, tick) makes the "
          "exact reverter refuse (so the chain's exact-match row fails, never a skipped proof)",
          all(_fails(CH2, _live_with(mutated), "exact-match reverters apply") for mutated in (
              mutate(FW_TEXT, scope.API_ACTION_BLOCK, scope.API_ACTION_BLOCK.replace("- action: fallback_profile_execute", "- action: fallback_profile_execute2")),
              mutate(FW_TEXT, scope.GLOBALS_BLOCK, scope.GLOBALS_BLOCK.replace("initial_value: '0'", "initial_value: '1'", 1)),
              mutate(FW_TEXT, scope.SWITCH_ARM_BLOCK, scope.SWITCH_ARM_BLOCK.replace("ALWAYS_OFF", "RESTORE_DEFAULT_OFF")),
              mutate(FW_TEXT, scope.SCRIPTS_BLOCK, scope.SCRIPTS_BLOCK.replace("mode: single", "mode: restart", 1)),
              mutate(FW_TEXT, scope.SAVE_FINAL_BLOCK, scope.SAVE_FINAL_BLOCK.replace("go = false;", "go = true;", 1)),
              mutate(FW_TEXT, scope.DISPATCH_DRAIN_BLOCK, scope.DISPATCH_DRAIN_BLOCK.replace("timeout: 3000ms", "timeout: 30000ms")),
              mutate(FW_TEXT, scope.TICK2_BLOCK, scope.TICK2_BLOCK.replace("turn_off", "turn_on", 1)),
              mutate(FW_TEXT, "    - include/ecco_fallback_save.h\n", "    - include/ecco_fallback_save.h\n    - include/ecco_extra.h\n"))))
    check("negative: a changed replacement line (a wrong class variable, a wrong retained error) each makes the exact reverter refuse",
          _fails(CH2, _live_with(mutate(FW_TEXT, "ecco_fbcap::epc_name(eff_cls)", "ecco_fbcap::epc_name(e.cls)")), "exact-match reverters apply")
          and _fails(CH2, _live_with(mutate(FW_TEXT, "ri.cls = eff_cls;", "ri.cls = e.cls;")), "exact-match reverters apply")
          and all(_fails(CH2, _live_with(mutate(FW_TEXT, scope.hunk(n).after, scope.hunk(n).after.replace("id(fallback_durable_last_us));", "0);"))),
                          "exact-match reverters apply") for n in ("boot_b2", "final_b2")))
    check("negative: ANY undeclared edit to PRE-EXISTING code leaves the reverter applicable but breaks the checkpoint: the revert no longer "
          "reproduces fbb1's firmware byte-for-byte",
          _fails(CH2, _live_with(mutate(FW_TEXT, "Starting Free Power snapshot", "Starting Free Power snapshotX")), "recorded checkpoint")
          and _fails(CH2, _live_with(mutate(FW_TEXT, '                  ESP_LOGE("free_power", "RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data '
                                                     'record is unreadable; inverter writes locked");\n',
                                            '                  ESP_LOGE("free_power", "RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data '
                                            'record is unreadable; inverter writes locked");\n                  id(free_power_status).publish_state("x");\n')),
                     "recorded checkpoint"))
    check("negative: any one FB-B2 hunk missing from the live firmware (all twenty-one, one at a time) is a FAILED chain row, never a skipped proof",
          all(_fails(CH2, _live_with(_revert_one(FW_TEXT, h)), "exact-match reverters apply") for h in hunks))

    # -----------------------------------------------------------------------
    print("")
    print("[6] The ledger of OLDER pins and support modules this PR edited (each edit is commented `FB-B2:` / `FB-B2 (D8):`; no assertion was weakened or deleted)")
    # -----------------------------------------------------------------------
    nvs_src = (ROOT / "registry/tests/test_fallback_nvs_keyhash.py").read_text(encoding="utf-8")
    dur_src = (ROOT / "registry/tests/test_fallback_durable_harness.py").read_text(encoding="utf-8")
    check("test_fallback_nvs_keyhash.py: the entity-preference count pin is exactly `n_num == 6 and n_sw == 10` (was 9: the one new template switch) "
          "with an FB-B2 comment, and it still excludes selects", "n_num == 6 and n_sw == 10 and not any(p == \"select\" for p, _n in ENTITIES))" in nvs_src
          and "# FB-B2: n_sw 9 -> 10" in nvs_src and nvs_src.count("n_sw == ") == 1)
    arrays_pin = ('FBB1_ARRAY_GLOBALS = {"fallback_profile_bytes": ("uint8_t", 96), "fallback_witness_bytes": ("uint8_t", 48),\n'
                  '                      "fallback_profile_pass1": ("uint16_t", 31), "fallback_profile_pass2": ("uint16_t", 31),\n'
                  '                      "fallback_profile_cand_words": ("uint16_t", 31),\n'
                  '                      "fallback_profile_save_ctx_words": ("uint16_t", 31),\n'
                  '                      # FB-C2: the Failback Shadow\'s torn-snapshot latch of the 31 cached configuration words (RAM-only, shadow tick only)\n'
                  '                      "failback_shadow_live_regs": ("uint16_t", 31)}\n')
    check("test_fallback_durable_harness.py: the live std::array global set is pinned EXACTLY (the five FB-B1 arrays plus the one SAVE-context words "
          "array: 6, element type and size each) with an FB-B2 comment; the pin is `real.array_globals == FBB1_ARRAY_GLOBALS`, still an equality",
          arrays_pin in dur_src and "# FB-B2: the sixth is the SAVE context's candidate words copy" in dur_src and "real.array_globals == FBB1_ARRAY_GLOBALS" in dur_src
          and sum("std::array" in g["type"] for g in FW["globals"]) == 6)   # (FW here is the as-of-fbb2 view: the FB-C2 array is not part of it)
    # The D8 edits (the FB-B1 "review only" READY wording became false once a Save exists; CAPTURE_SAVING = 4 is appended) reach the capture
    # header and its Python mirror and the three FB-B1 capture suites that pin the READY text and the state table. Their comments are spelled
    # `FB-B2 (D8):` (the suites that carry them are listed here, each with an exact-content check, so none can be edited unseen).
    cap_src = (ROOT / "registry/tests/test_fallback_profile_capture.py").read_text(encoding="utf-8")
    capm_src = (ROOT / "registry/tests/test_fallback_capture_model.py").read_text(encoding="utf-8")
    caphc_src = (ROOT / "registry/tests/test_fallback_capture_host_compile.py").read_text(encoding="utf-8")
    dash_src = (ROOT / "registry/tests/test_fallback_recovery_dashboard.py").read_text(encoding="utf-8")
    cap_h = (ROOT / "firmware/include/ecco_fallback_capture.h").read_text(encoding="utf-8")
    cap_py = (ROOT / "registry/fallback_capture.py").read_text(encoding="utf-8")
    ready_new = "CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within 120 s"
    ready_old_head = "CANDIDATE READY - both read passes agree on all 31 registers; values are shown for review only"
    check("D8 source of the edits below: ecco_fallback_capture.h carries CAPTURE_SAVING = 4, its name SAVING (state 4; state 5 stays IDLE) and the "
          "reworded READY text; the Python mirror says the same (the older suites below are re-anchored to exactly this)",
          "  CAPTURE_SAVING = 4," in cap_h and '         : state == CAPTURE_SAVING                 ? "SAVING"\n' in cap_h
          and 'static_assert(str_is(capture_state_name(4), "SAVING"), "FB-B1 name: capture_state_name 4");' in cap_h
          and 'static_assert(str_is(capture_state_name(5), "IDLE"), "FB-B1 name: capture_state_name 5");' in cap_h
          and f'static_assert(text_is("{ready_new}", candidate_ready_text())' in cap_h and ready_old_head not in cap_h
          and "CAPTURE_CANDIDATE_NOT_SAVEABLE, CAPTURE_SAVING = 0, 1, 2, 3, 4" in cap_py and '3: "CANDIDATE_NOT_SAVEABLE", 4: "SAVING"}' in cap_py
          and '"CANDIDATE READY - both read passes agree on all 31 registers; check the values, then arm and save within "' in cap_py
          and ready_old_head not in cap_py)
    def _p_cap(s: str) -> bool:
        return (s.count("READY_B9 = ") == 1 and f'READY_B9 = "{ready_new}"\n' in s and "# FB-B2 (D8): a Save exists now" in s
                and ready_old_head + '"' not in s and s.count("FB-B2") == 1)

    check("test_fallback_profile_capture.py (D8): READY_B9 is exactly the new READY text under an `FB-B2 (D8):` comment; the old wording is no "
          "longer asserted anywhere in the suite (the one edit of this file; the pins that use READY_B9 are unchanged)", _p_cap(cap_src))
    def _p_capm(s: str) -> bool:
        return ('"CAPTURE_CANDIDATE_NOT_SAVEABLE", "CAPTURE_SAVING"),' in s and f'str(out["ready"]) == "{ready_new}"' in s
                and "CANDIDATE READY (FB-B2 wording: arm and save within 120 s)" in s
                and r'not re.search(r"\bArm\b|turn on|SAVE <|supervision|NTP|execute", alltext) and "Save within" not in alltext)' in s
                and "FB-B2: the CANDIDATE READY text names the arm and the Save within 120 s and nothing else of the Save flow" in s
                and ready_old_head + '"' not in s and s.count("FB-B2 (D8)") == 3 and s.count("FB-B2:") == 1)

    def _p_caphc(s: str) -> bool:
        return (f"""text_is("{ready_new}", candidate_ready_text())""" in s
                and f"""text_is("{ready_new.replace('120 s', '121 s')}", candidate_ready_text())""" in s
                and r"""'then arm and save within "\n         "120 s");'""" in s and r"""'then arm and save within "\n         "125 s");'""" in s
                and "the SAVING capture state loses its name" in s and '"FB-B1 name: capture_state_name 4"' in s
                and ready_old_head not in s and s.count("FB-B2 (D8)") == 2)

    check("test_fallback_capture_model.py (D8): the capture-state group gains exactly CAPTURE_SAVING, the exact-text check asserts the new READY "
          "text, the original `no B9 text names the Arm / SAVE < / turn on / Save within / execute` pin keeps its regex and its text set (only its label "
          "changed), and one new positive check (the READY text names the arm and the Save within 120 s) is added; every edit is commented FB-B2",
          _p_capm(capm_src))
    check("test_fallback_capture_host_compile.py (D8): mutants 04 / 05 (the golden READY text edited / the builder text edited) are re-anchored to the "
          "new READY text and still kill (their anchors are the live header's text), and ONE new mutant (the SAVING capture state loses its name) is "
          "added against capture_state_name 4; every edit is commented `FB-B2 (D8):`", _p_caphc(caphc_src))
    old_ready = ready_old_head + "; expires in 120 s"
    check("negative (ledger): each D8 exact-content check REFUSES a regressed copy of its suite: the old FB-B1 READY wording back, the `FB-B2 (D8):` "
          "comment dropped, the SAVING group / mutant removed (a marker-spelling accident cannot hide a missing or reverted edit)",
          _p_cap(cap_src) and _p_capm(capm_src) and _p_caphc(caphc_src)
          and not _p_cap(cap_src.replace(ready_new, old_ready)) and not _p_cap(cap_src.replace("# FB-B2 (D8): a Save exists now", "# a Save exists now"))
          and not _p_capm(capm_src.replace(ready_new, old_ready)) and not _p_capm(capm_src.replace('"CAPTURE_SAVING"),', '),'))
          and not _p_capm(capm_src.replace("FB-B2 (D8)", "D8"))
          and not _p_caphc(caphc_src.replace(ready_new, old_ready)) and not _p_caphc(caphc_src.replace("the SAVING capture state loses its name", "x")))
    check("test_fallback_recovery_dashboard.py: the card's write surface moved the following pins to their exact new truth, each under an `FB-B2:` comment "
          "(the reserved entity-id token count 10 -> 11 = the arm id; the B2 werr / us grammar from `-` / `-` to the real E<hex> / microseconds; the B3 "
          "state set gains SAVING; the config has nineteen entity keys; the switch domain is allowed as a CONFIG VALUE and the card's service domains are "
          "exactly button, input_boolean, switch, esphome; the 'Coming in FB-B2' placeholder needle is gone because the Save control is real; the node "
          "floor 120 -> 215). The firmware-surface check now REQUIRES the arm switch and the execute action (a hard presence check, not the vacuous "
          "'where already declared' form)",
          "DASH_RESERVED_TOKENS = 11\n" in dash_src and "# FB-B2: 11 = the ten FB-B1 ids plus `entities.arm`" in dash_src
          and r"werr=(?:-|E[0-9A-F]{1,8});us=(?:-|\d{1,10})$" in dash_src and "CANDIDATE_NOT_SAVEABLE|SAVING);prior=" in dash_src
          and "len(ENTITIES) == 19" in dash_src and "the nineteen entity keys" in dash_src
          and '# FB-B2: the "Coming in FB-B2" placeholder is gone (the Save control is real)' in dash_src
          and "FB-B2: the card's service domains are exactly button, input_boolean, switch and esphome" in dash_src
          and 'counts.get("tests", 0) >= 215' in dash_src and 'counts.get("tests", 0) >= 120' not in dash_src
          and "the firmware declares the arm switch name" in dash_src and "the firmware declares the fallback_profile_execute api action" in dash_src)
    sup_src = (ROOT / "registry/tests/test_supervision_heartbeat_observe_only.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    check("test_supervision_heartbeat_observe_only.py (final hardening): the PR-A pin 'no supervision logic lives in a script' is narrowed to EXACTLY one "
          "exception, the commit-time heartbeat re-check of fallback_profile_capture_dispatch (two reads); every other script still must be free of it, under an "
          "`FB-B2 hardening:` comment",
          "FB-B2 hardening: the ONE exception is the commit-time heartbeat re-check" in sup_src
          and '_sup_scripts in ({}, {"fallback_profile_capture_dispatch": 2})' in sup_src
          and 'check("no supervision logic lives in a script", not any(' not in sup_src)
    # The support modules the suites above use (additive FB-B2 work of the harness: the async api engine, template-switch model, std::array /
    # StringRef types, the write-allowing NVS-safety helpers). They are not pins; they are listed so that an unlisted edit is a red row.
    support = ("_fbb1_engine.py", "_fbb1_fbcap.py", "_fbb1_lambda_compile.py", "_fbb1_types.py", "_fbb1_xpile.py", "_fbb_harness.py", "_scope_chain.py")
    suites = ("test_fallback_capture_host_compile.py", "test_fallback_capture_model.py", "test_fallback_durable_harness.py", "test_fallback_nvs_keyhash.py",
              "test_fallback_profile_capture.py", "test_fallback_recovery_dashboard.py",
              "test_supervision_heartbeat_observe_only.py")   # FB-B2 hardening: the PR-A 'no supervision logic in a script' pin
    # FB-B3: files a LATER chain entry adds are new work, not pre-existing files edited by FB-B2.
    later_added = frozenset().union(*(e.added_files for e in CH.after("fbb2")))
    existing = sorted(p.name for p in HERE.glob("*.py") if f"registry/tests/{p.name}" not in scope.ADDED_FILES
                      and f"registry/tests/{p.name}" not in later_added and "FB-B2" in p.read_text(encoding="utf-8"))
    check("the ledger is COMPLETE: the pre-existing files under registry/tests that mention FB-B2 are exactly the seven older suites listed above plus "
          "the seven support modules (the FB-B1 engine / types / xpile / fbcap / lambda_compile, the FB-B0 harness, the chain); a new edit to any other "
          "older suite or support module has to be declared here",
          existing == sorted(suites + support), str(sorted(set(existing) ^ set(suites + support))))
    check("every firmware-count pin the FB-B2 YAML would move is either chain-anchored (declared by the fbb2 entry, not edited) or one of the seven "
          "older suites above: the chain-anchored suites that carry NO FB-B2 mention at all, in any spelling (capture_scope, durable_model, "
          "failback_shadow_core, sg01 phase 0 / 5, sg06, write-surface, profile_schema, scope_chain), were not edited",
          all("FB-B2" not in (ROOT / f).read_text(encoding="utf-8") for f in (
              "registry/tests/test_fallback_capture_scope.py", "registry/tests/test_fallback_durable_model.py",
              "registry/tests/test_failback_shadow_core.py",
              "registry/tests/test_sg01_phase5_hardening.py", "registry/tests/test_sg01_phase0_harness.py",
              "registry/tests/test_sg06_boot_durable_read_fail_closed.py", "registry/tests/test_write_surface_invariants.py",
              "registry/tests/test_fallback_profile_schema.py", "registry/tests/test_scope_chain.py")))

    # -----------------------------------------------------------------------
    print("")
    print("[7] MUTANTS: a broken copy of the thing under test per decision, each KILLED by a named check")
    # -----------------------------------------------------------------------
    src = (HERE / "_fbb2_scope.py").read_text(encoding="utf-8")
    hdr_live = dict(live_headers)

    def revert_det(old: str, new: str, count: int = 1) -> list:
        mutated = mutate(src, old, new, count)           # raises (the test errors) if the mutant would miss its target
        try:
            mod = load_scope_variant(mutated, f"v{abs(hash((old, new))) % 10**8}")
        except AssertionError as ex:                     # the module's own import-time guard refused the mutant
            return [f"the mutated scope module fails its own import-time guard: {str(ex)[:70] or 'assert'}"]
        return revert_violations(mod, FW_TEXT)

    def tables_det(old: str, new: str) -> list:
        return table_violations(load_scope_variant(mutate(src, old, new, 1), f"t{abs(hash((old, new))) % 10**8}"), ctx)

    def ctx_of(text: str) -> "Ctx":
        return Ctx(text)

    def static_det(name: str, text: str) -> list:
        try:
            return STATIC[name][1](ctx_of(text))
        except Exception as ex:  # noqa: BLE001 - a text the pin cannot even parse is a detected defect
            return [f"raised {type(ex).__name__}: {str(ex)[:60]}"]

    def survey_det(text: str, headers: dict) -> list:
        try:
            return survey_violations(S_BASE, survey(text, headers))
        except Exception as ex:  # noqa: BLE001
            return [f"raised {type(ex).__name__}: {str(ex)[:60]}"]

    _entry_cache: dict = {}

    def entry_det(**kw) -> list:
        key = repr(sorted(kw.items(), key=lambda kv: kv[0]))
        if key not in _entry_cache:
            rows = chain.integrity_report(_with(**kw), _live)
            _entry_cache[key] = [n for n, ok, _d in rows if not ok and n.startswith("fbb2:")]
        return _entry_cache[key]

    GATE_ANCHOR = "          // One-shot preamble (every call that passed G1): read the arm, turn it off, take a local copy of\n"
    INV_FRESH = "          // Fresh FBP + FBW read: two direct reads, ONE health check, then the latch notes, the same-boot\n"
    INV_RAM = "          // I2..I12 over the RAM mirror (cheap first: a refusal never costs a storage read).\n"
    INV_HEAD = "  - id: fallback_profile_invalidate\n    mode: single\n    then:\n      - lambda: |-\n"

    def inject(anchor: str, stmt: str) -> str:
        """The firmware with one statement inserted in front of an FB-B2 anchor line (an exact-once edit: a mutant never misses)."""
        return mutate(FW_TEXT, anchor, stmt + anchor)

    def first_only(text: str, old: str, new: str) -> str:
        i = text.index(old)
        return text[:i] + new + text[i + len(old):]

    save_header_mut = live_headers[NEW_HEADER]
    model_mut = live_headers[DURABLE_MODEL]
    third_target = "template<> struct WriteTarget<FailbackStateV1, FAILBACK_STATE_KEY> {\n  static constexpr bool allowed = true;\n};\n"
    inject_interval = FW_TEXT + "  - interval: 20s\n    then:\n      - lambda: |-\n          (void) 0;\n"
    MUTANTS = [
        # -- the scope module's reverter and tables (D-REVERT, D-TABLES) --
        ("M01", "the reverter is off by one byte (it keeps one character of the replaced block)", "D-REVERT",
         lambda: revert_det("text[i + len(find):]", "text[i + len(find) - 1:]")),
        ("M02", "a hunk is dropped from HUNKS (the dispatch drain stays in the reverted text)", "D-REVERT",
         lambda: revert_det('    _ins("dispatch_drain", "script fallback_profile_capture_dispatch: SAVE-only pre-commit poller drain, before REVIEW_FINAL",\n'
                            '         DISPATCH_DRAIN_BLOCK),\n', "")),
        ("M03", "a hunk's block is emptied (the final_arm_off insertion adds nothing, so the reverter leaves the live arm-off in place)", "D-REVERT",
         lambda: revert_det('_ins("final_arm_off", "dispatch REVIEW_FINAL: arm turned off before the candidate is published", FINAL_ARM_OFF_BLOCK)',
                            '_ins("final_arm_off", "dispatch REVIEW_FINAL: arm turned off before the candidate is published", "")')),
        ("M04", "BASE_FW_SHA is one hex digit off", "D-REVERT",
         lambda: revert_det(f'BASE_FW_SHA = "{FBB1_FW_SHA}"', f'BASE_FW_SHA = "{"b" if FBB1_FW_SHA[0] != "b" else "c"}{FBB1_FW_SHA[1:]}"')),
        ("M05", "one anchor context is altered by a character (FB-C1's comment line after the tick2 insertion)", "D-REVERT",
         lambda: revert_det("# Failback Shadow (FB-C1)", "# Failback Shadow (FB-C2)")),
        ("M06", "one replacement no longer swaps the class (the B3 text keeps e.cls in the FB-B2 text)", "D-REVERT",
         lambda: revert_det("ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, eff_cls,", "ecco_fbcap::b3_text(id(fallback_profile_capture_state), true, e.cls,")),
        ("M07", "a block literal carries a different character (the SAVE gate's mode)", "D-REVERT",
         lambda: revert_det("  - id: fallback_profile_save\n    mode: single\n", "  - id: fallback_profile_save\n    mode: restart\n")),
        ("M08", "the scope module's GLOBALS table names a global the firmware does not have", "D-TABLES",
         lambda: tables_det("('fallback_profile_save_ctx_id', 'uint64_t', '0'),", "('fallback_profile_save_ctx_idx', 'uint64_t', '0'),")),
        ("M09", "the scope module declares a script the firmware does not have", "D-TABLES",
         lambda: tables_det("SCRIPT_IDS = ('fallback_profile_save', 'fallback_profile_invalidate')", "SCRIPT_IDS = ('fallback_profile_save', 'fallback_profile_invalidate_x')")),
        # -- the chain entry (D-ENTRY) --
        ("M10", "a WRONG delta is declared (3 scripts)", "D-ENTRY", lambda: entry_det(deltas={**E.deltas, "scripts": 3})),
        ("M11", "a Modbus WRITE delta is declared (+1) that the firmware does not have", "D-ENTRY", lambda: entry_det(deltas={**E.deltas, "modbus_writes": 1})),
        ("M12", "a Modbus READ delta is declared (+4: a second set of read nodes) that the firmware does not have", "D-ENTRY",
         lambda: entry_det(deltas={**E.deltas, "modbus_reads": 4})),
        ("M13", "the api-action delta is not declared", "D-ENTRY", lambda: entry_det(deltas={k: v for k, v in E.deltas.items() if k != "api_actions"})),
        ("M14", "the op path is mis-declared (the INVALIDATE script instead of the SAVE gate)", "D-ENTRY",
         lambda: entry_det(op_paths_changed=frozenset({"fallback_profile_invalidate"}))),
        ("M15", "the banned-token count is wrong (11)", "D-ENTRY", lambda: entry_det(banned_fw_added=11)),
        ("M16", "the recorded checkpoint is one hex digit off", "D-ENTRY", lambda: entry_det(checkpoints={chain.FIRMWARE: flip(E.checkpoints[chain.FIRMWARE])})),
        ("M17", "the include is not declared", "D-ENTRY", lambda: entry_det(includes_added=())),
        # -- the added files (D-FILES) --
        ("M18", "an FB-B2 file exists on disk but is not declared (the scope suite itself is left out)", "D-FILES",
         lambda: files_violations(E.added_files - {"registry/tests/test_fallback_save_scope.py"}, named)),
        ("M19", "a declared file does not exist (a phantom path)", "D-FILES",
         lambda: files_violations(E.added_files | {"registry/tests/test_fallback_save_phantom.py"}, named)),
        ("M20", "a glob is used instead of an exact path", "D-FILES", lambda: files_violations(E.added_files | {"registry/tests/test_fallback_save_*.py"}, named)),
        # -- the measurement (D-SURVEY): Modbus, durable writer, keys / tags, counts --
        ("M21", "an extra Modbus READ node in a new script", "D-SURVEY", lambda: survey_det(inject_read, live_headers)),
        ("M22", "an extra Modbus WRITE node in a new script", "D-SURVEY", lambda: survey_det(inject_write, live_headers)),
        ("M23", "a THIRD commit_transition_t call site (in the SAVE gate lambda)", "D-SURVEY",
         lambda: survey_det(inject(GATE_ANCHOR, "          ecco_fbdurable::EspNvs nvs3;\n          ecco_fbdurable::TxnResult r3 = ecco_fbdurable::commit_transition_t(nvs3);\n"), live_headers)),
        ("M24", "a THIRD write target in the model header (an FBS WriteTarget and a write_one_ instantiation)", "D-SURVEY",
         lambda: survey_det(FW_TEXT, {**live_headers, DURABLE_MODEL: model_mut.replace("template<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {",
                                                                                      third_target + "template<> struct WriteTarget<FallbackProfileV1, FALLBACK_PROFILE_KEY> {", 1)
                                                      + "\nstatic const int fbs_w = (int) sizeof(write_one_<FailbackStateV1, FAILBACK_STATE_KEY>);\n"})),
        ("M25", "a second nvs_set_blob call site (in the new header)", "D-SURVEY",
         lambda: survey_det(FW_TEXT, {**live_headers, NEW_HEADER: save_header_mut + "\ninline int nvs_x(void *h) { return nvs_set_blob(h, \"k\", nullptr, 0); }\n"})),
        ("M26", "a new durable tag string in the new header", "D-SURVEY",
         lambda: survey_det(FW_TEXT, {**live_headers, NEW_HEADER: save_header_mut + '\nconstexpr char SAVE_TAG[] = "ecco_fallback_save_v1";\n'})),
        ("M27", "a direct nvs_set_blob call in the INVALIDATE lambda", "D-SURVEY",
         lambda: survey_det(inject(INV_FRESH, "          nvs_set_blob(0, \"x\", nullptr, 0);\n"), live_headers)),
        ("M28", "a legacy durable commit_record call site in a lambda", "D-SURVEY",
         lambda: survey_det(inject(GATE_ANCHOR, "          ecco_durable::commit_record(0u, 0);\n"), live_headers)),
        ("M29", "the FBS key is named by an FB-B2 lambda (a second FBS use)", "D-SURVEY",
         lambda: survey_det(inject(GATE_ANCHOR, "          const uint32_t kfbs = ecco_fbdurable::FAILBACK_STATE_KEY;\n"), live_headers)),
        ("M30", "an extra banned token in the firmware", "D-SURVEY", lambda: survey_det(inject_banned, live_headers)),
        ("M31", "an undeclared extra global", "D-SURVEY", lambda: survey_det(inject_global, live_headers)),
        ("M32", "an undeclared extra interval (the arm lifetime as a separate interval)", "D-SURVEY", lambda: survey_det(inject_interval, live_headers)),
        # -- the static pins (S-*): one defect per decision --
        ("M33", "the arm switch is restored from flash (RESTORE_DEFAULT_OFF)", "S-SWITCH",
         lambda: static_det("S-SWITCH", mutate(FW_TEXT, scope.SWITCH_ARM_BLOCK, scope.SWITCH_ARM_BLOCK.replace("ALWAYS_OFF", "RESTORE_DEFAULT_OFF")))),
        ("M34", "the arm switch name mentions supervision", "S-SWITCH",
         lambda: static_det("S-SWITCH", mutate(FW_TEXT, 'name: "ECCO Fallback Profile Arm"', 'name: "ECCO Fallback Profile Arm Supervision"'))),
        ("M35", "the arm switch gets an on_turn_on automation of its own", "S-SWITCH",
         lambda: static_det("S-SWITCH", mutate(FW_TEXT, '    icon: "mdi:shield-key-outline"\n    turn_on_action:\n', '    icon: "mdi:shield-key-outline"\n    on_turn_on:\n      - lambda: |-\n          (void) 0;\n    turn_on_action:\n'))),
        ("M36", "the firmware turns the arm ON (the review gate calls turn_on)", "S-ARM-FW",
         lambda: static_det("S-ARM-FW", mutate(FW_TEXT, scope.hunk("review_arm_off").new, scope.hunk("review_arm_off").new.replace("turn_off", "turn_on")))),
        ("M37", "one arm turn-off is missing (the review gate)", "S-ARM-FW", lambda: static_det("S-ARM-FW", mutate(FW_TEXT, scope.hunk("review_arm_off").new, ""))),
        ("M38", "the firmware publishes the arm's state itself", "S-ARM-FW",
         lambda: static_det("S-ARM-FW", inject(GATE_ANCHOR, "          id(fallback_profile_arm).publish_state(true);\n"))),
        ("M39", "a script (the SAVE gate) reads the supervision state directly", "S-SUP",
         lambda: static_det("S-SUP", inject(GATE_ANCHOR, "          const bool hb2 = id(supervision_stable);\n"))),
        ("M40", "INVALIDATE waits (a wait_until in front of its lambda)", "S-INV",
         lambda: static_det("S-INV", mutate(FW_TEXT, INV_HEAD, "  - id: fallback_profile_invalidate\n    mode: single\n    then:\n      - wait_until:\n          condition:\n"
                                                              "            lambda: 'return true;'\n      - lambda: |-\n"))),
        ("M41", "INVALIDATE takes the write mutex", "S-INV", lambda: static_det("S-INV", inject(INV_RAM, "          id(manual_write_in_progress) = true;\n"))),
        ("M42", "INVALIDATE takes the operation flag", "S-INV", lambda: static_det("S-INV", inject(INV_RAM, "          id(fallback_profile_op_in_progress) = true;\n"))),
        ("M43", "both commit calls are renamed (no durable write at all)", "S-COMMIT",
         lambda: static_det("S-COMMIT", mutate(FW_TEXT, "ecco_fbdurable::commit_transition_t(", "ecco_fbdurable::commit_transition_x(", count=2))),
        ("M44", "the SAVE_FINAL part 2 commit is renamed (only INVALIDATE commits)", "S-COMMIT",
         lambda: static_det("S-COMMIT", first_only(FW_TEXT, "ecco_fbdurable::commit_transition_t(", "ecco_fbdurable::commit_transition_x("))),
        ("M45", "a THIRD commit_transition_t lambda (the SAVE gate commits itself)", "S-COMMIT",
         lambda: static_det("S-COMMIT", inject(GATE_ANCHOR, "          ecco_fbdurable::EspNvs nvs3;\n          ecco_fbdurable::TxnResult r3 = ecco_fbdurable::commit_transition_t(nvs3);\n"))),
        ("M46", "a writer-template token in a lambda (write_one_)", "S-COMMIT", lambda: static_det("S-COMMIT", inject(GATE_ANCHOR, "          write_one_<int, 0>();\n"))),
        ("M47", "the api action routes the SAVE token straight to the dispatch (no gate)", "S-API",
         lambda: static_det("S-API", mutate(FW_TEXT, "            else:\n              - script.execute:\n                  id: fallback_profile_save\n",
                                            "            else:\n              - script.execute:\n                  id: fallback_profile_capture_dispatch\n"))),
        ("M48", "the api action answers the caller (api.respond)", "S-API",
         lambda: static_det("S-API", mutate(FW_TEXT, "                  id: fallback_profile_save\n\nota:\n", "                  id: fallback_profile_save\n        - api.respond:\n            success: true\n\nota:\n"))),
        ("M49", "the api action copies a variable without .str() (a StringRef assigned raw)", "S-API",
         lambda: static_det("S-API", mutate(FW_TEXT, "id(fallback_profile_exec_target_id) = target_id.str();", "id(fallback_profile_exec_target_id) = target_id;"))),
        ("M50", "the drain wait no longer matches PRECOMMIT_WAIT_MS (30000 ms)", "S-DISPATCH",
         lambda: static_det("S-DISPATCH", mutate(FW_TEXT, scope.DISPATCH_DRAIN_BLOCK, scope.DISPATCH_DRAIN_BLOCK.replace("timeout: 3000ms", "timeout: 30000ms")))),
        ("M51", "REVIEW_FINAL loses its SAVE purpose guard", "S-DISPATCH", lambda: static_det("S-DISPATCH", mutate(FW_TEXT, scope.hunk("final_guard").new, ""))),
        ("M52", "RELEASE no longer clears the SAVE context", "S-DISPATCH", lambda: static_det("S-DISPATCH", mutate(FW_TEXT, scope.hunk("release_ctx").new, ""))),
        ("M53", "SAVE_FINAL part 1 loses its purpose check", "S-DISPATCH",
         lambda: static_det("S-DISPATCH", mutate(FW_TEXT, "          if (id(fallback_profile_op_purpose) != ecco_fbsave::PURPOSE_SAVE) return;\n", ""))),
        ("M54", "a fifth Modbus node in the dispatch (a second set of reads)", "S-DISPATCH",
         lambda: static_det("S-DISPATCH", mutate(FW_TEXT, "      # FB-B2: SAVE only - the pre-commit poller drain",
                                                 "      - modbus_client.read_holding_registers:\n          modbus_id: inverter_modbus\n          address: 0x01\n          start_address: 230\n          count: 3\n"
                                                 "      # FB-B2: SAVE only - the pre-commit poller drain"))),
        ("M55", "a new Modbus node anywhere (a phantom script with an FC03 read)", "S-MODBUS", lambda: static_det("S-MODBUS", inject_read)),
        ("M56", "the SAVE gate calls a bus member other than the idle reads (inverter_modbus->send)", "S-MODBUS",
         lambda: static_det("S-MODBUS", inject(GATE_ANCHOR, "          id(inverter_modbus)->send(0);\n"))),
        ("M57", "the YAML names the FBP key as a numeric literal", "S-KEYS", lambda: static_det("S-KEYS", inject(GATE_ANCHOR, "          const uint32_t kp = 1609458070u;\n"))),
        ("M58", "a lambda reads the FBS key (a second FBS use outside the boot lambda)", "S-KEYS",
         lambda: static_det("S-KEYS", inject(GATE_ANCHOR, "          const uint32_t kfbs = ecco_fbdurable::FAILBACK_STATE_KEY;\n"))),
        ("M59", "a seventh log site with another tag in an FB-B2 lambda", "S-LOG", lambda: static_det("S-LOG", inject(GATE_ANCHOR, '          ESP_LOGI("other", "x");\n'))),
        ("M60", "a new global is restore_value: yes", "S-GLOBALS",
         lambda: static_det("S-GLOBALS", mutate(FW_TEXT, "  - id: fallback_profile_exec_action\n    type: std::string\n    restore_value: no\n",
                                                "  - id: fallback_profile_exec_action\n    type: std::string\n    restore_value: yes\n"))),
        ("M61", "a new global has a header-defined type", "S-GLOBALS",
         lambda: static_det("S-GLOBALS", mutate(FW_TEXT, "  - id: fallback_profile_save_ctx_id\n    type: uint64_t\n", "  - id: fallback_profile_save_ctx_id\n    type: ecco_fbdurable::PriorDesc\n"))),
        ("M62", "the INVALIDATE lambda reads NTP", "S-NTP", lambda: static_det("S-NTP", inject(INV_RAM, "          const bool nt = id(ntp_synced);\n"))),
        ("M63", "the SAVE gate lambda declares a storage handle (it must read no storage)", "S-SAVE",
         lambda: static_det("S-SAVE", inject(GATE_ANCHOR, "          ecco_fbdurable::EspNvs nvsx;\n"))),
        ("M64", "a script other than the api action executes the INVALIDATE script", "S-SAVE",
         lambda: static_det("S-SAVE", mutate(FW_TEXT, "\n  - id: restore_reg244_snapshot\n",
                                             "\n  - id: fbb2_phantom_exec\n    mode: single\n    then:\n      - script.execute:\n          id: fallback_profile_invalidate\n\n  - id: restore_reg244_snapshot\n"))),
        ("M65", "a forbidden symbol (nvs_set_blob) in the SAVE gate lambda", "S-FORBID",
         lambda: static_det("S-FORBID", inject(GATE_ANCHOR, "          nvs_set_blob(0, \"x\", nullptr, 0);\n"))),
        ("M66", "a reboot call (App.reboot) in an FB-B2 lambda", "S-FORBID", lambda: static_det("S-FORBID", inject(GATE_ANCHOR, "          App.reboot();\n"))),
    ]
    killed = 0
    for mid, desc, det, fn in MUTANTS:
        try:
            got = fn()
        except Exception as ex:  # noqa: BLE001 - a mutant the harness cannot even build is reported, never counted as killed
            got = None
            print(f"  (mutant {mid} could not be built: {type(ex).__name__}: {str(ex)[:140]})")
        ok = bool(got)
        killed += ok
        check(f"mutant {mid} [{det}] is KILLED: {desc}", ok, "" if ok else ("the mutant survived" if got is not None else "the mutant could not be built"))
    # controls: every detector is green on the real thing (so a kill is caused by the mutation, not by a broken detector)
    check("control: every mutant detector is green on the REAL artifacts (the reverter, the tables, the chain entry, the added files, the measurement and all "
          "static pins)", not revert_violations(scope, FW_TEXT) and not table_violations(scope, ctx) and not entry_det()
          and not files_violations(E.added_files, named) and not survey_violations(S_BASE, S_LIVE) and not any(fn(ctx) for _l, fn in STATIC.values()))
    check(f"{len(MUTANTS)} mutants defined (>= 60), {killed} killed: every one is rejected by the check named for it",
          len(MUTANTS) >= 60 and killed == len(MUTANTS), f"{killed}/{len(MUTANTS)}")

    print("")
    print(f"mutants killed: {killed}/{len(MUTANTS)}")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    print("(Chain-scope proofs only: they pin what FB-B2 adds and edits, and that each edit is exactly reversible, and they measure the Modbus /")
    print(" durable / tag surface. Behaviour is proven by the FB-B2 scenario suites; the native ESPHome compile is not an offline proof.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
