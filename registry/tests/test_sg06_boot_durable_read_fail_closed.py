#!/usr/bin/env python3
"""SG-06 - a boot-time durable-read failure must not be read as "no obligation".

Defect (main @ 049c37e): every on_boot validity-marker load (Free Power,
Manual Dump-to-Grid, register-244 proof harness) was

    bool have_marker = ecco_durable::load_record(key, marker);
    ...
    uint8_t state = have_marker ? marker.state : MARKER_CLEAR;

and ecco_durable::load_record() returns ESPHome's bare
ESP32PreferenceBackend::load() bool, which is false for ESP_ERR_NVS_NOT_FOUND
(never written), for a stored-length mismatch, for ESP_ERR_NVS_INVALID_HANDLE
(ESP32Preferences::open() leaves nvs_handle 0 when its erase-and-retry
nvs_open also fails) and for any other nvs_get_blob() error (vendored
ESPHome 2026.8.2, esphome/components/esp32/preferences.cpp - recorded here,
not imported: this suite runs with pyyaml only). So "could not establish
whether an obligation exists" became MARKER_CLEAR: snapshot_valid=false,
status "Inactive"/"NONE", every START gate open. A new START would then
overwrite the durable snapshot with the still-overridden live registers as
its "ORIGINAL" - the true original is lost.

Fix: ecco_durable::load_record_status() - the same load, and only on failure
one read-only nvs_get_blob() length probe classifying it LOAD_ABSENT /
LOAD_WRONG_SIZE / LOAD_READ_ERROR. The three marker loads use it:
  LOAD_ABSENT      -> CLEAR (unchanged - the only route to CLEAR)
  LOAD_WRONG_SIZE  -> the existing malformed-marker lockout (rule 3)
  LOAD_READ_ERROR  -> UNKNOWN: the existing fail-closed lockout flags
                      (snapshot_valid + metadata_corrupt), a status that
                      says UNKNOWN, NO durable write, NO Modbus; for Dump,
                      SG-02 containment is parked in terminal state 8 (no
                      register write because storage is unreadable).
Data, retry and journal loads are unchanged (already fail-closed, or
deliberately fail-open pacing / "no journal evidence").

Everything behavioural EXECUTES the real on_boot lambda and real scripts /
watchdogs through registry/tests/_dump_sim.py against an in-memory NVS store
(load failures injected per key or globally) and register bank - no
hardware, no Modbus, no ESPHome toolchain. Source-level proof only.

Sections:
  [1] header primitive (structural pins of load_record_status)
  [2] change scope vs main @ 049c37e
  [3] boot fault injection A-H, every domain
  [4] runtime consequences of UNKNOWN (START / watchdogs / Force / Accept /
      containment / cross-domain), with positive controls
  [5] readable boots are identical to main @ 049c37e
  [6] mutations - each safeguard broken on purpose must be caught
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sg01_recovery_harness as h  # noqa: E402
import _sg06_scope as sg06  # noqa: E402
import _mtou1_scope as mtou1  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402 - Dump V2's own later edits, reverted before the pins below
import _scope_chain as chain  # noqa: E402 - FB-T0: the pins in [2] are evaluated as of chain entry "dump_v2"
from _sg01_recovery_harness import CLEAR, PENDING, RR, SNAP, START, VERIFIED, WRAPPER, D, ds, fpsim  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FW_TEXT, HEADER = h.FW_TEXT, h.HEADER
FW = ds.load_firmware_text(FW_TEXT)
BOOT = h.boot_lambda(FW)


def fw_with_boot(boot_text: str) -> dict:
    fw = ds.load_firmware_text(FW_TEXT)
    fw["esphome"]["on_boot"]["then"][0]["lambda"] = boot_text
    return fw


# main @ 049c37e's on_boot, everything else the current firmware (which [2]
# proves is otherwise identical) - the "return to old behaviour" mutant.
# FB-B1 (D14): SG-06's reverter is exact-match, and FB-B1 rewords the three
# unreadable-marker operator texts that sit INSIDE SG-06's own edit strings (they
# no longer advise a reboot), so it cannot be handed the LIVE on_boot lambda any
# more. It is handed the lambda AS OF chain entry "dump_v2" - exactly the text [2]
# below already pins (every later entry's declared edits undone by its own exact
# reverter, so any undeclared edit still raises here). The mutant is unchanged:
# main's old on_boot spliced into the otherwise live firmware.
OLD_FW = fw_with_boot(sg06.pre_sg06_boot(h.boot_lambda(
    ds.load_firmware_text(chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)))))

MAGIC = D.VALID_MARKER_MAGIC
DOMAINS = {
    "free_power": {"valid": D.FREE_POWER_VALID_TAG, "data": D.FREE_POWER_DATA_TAG, "retry": D.FREE_POWER_RETRY_TAG,
                   "status": "free_power_status"},
    "dump": {"valid": D.DUMP_TO_GRID_VALID_TAG, "data": D.DUMP_TO_GRID_DATA_TAG, "retry": D.DUMP_TO_GRID_RETRY_TAG,
             "status": "dump_status"},
    "reg244": {"valid": D.REG244_VALID_TAG, "data": D.REG244_DATA_TAG, "retry": None, "status": "reg244_last_result"},
}
DUMP_ORIGINAL = {244: 2, 256: 8000, 257: 8000, 258: 7000, 259: 8000, 260: 8000, 261: 5000}
DUMP_RESIDUE = {244: 0, 256: 1000, 257: 1000, 258: 1000, 259: 1000, 260: 1000, 261: 1000}
START_BANK = h.make_bank(h.live_for(h.states_of_row("OOOO"), SNAP))


def marker(state: int, magic: int = MAGIC) -> "ds.Record":
    return ds.Record("ValidMarker", magic, state)


def data_record(name: str) -> "ds.Record":
    if name == "free_power":
        return h.rec("FreePowerSnapshotData", **{k: SNAP[k] for k in ds._RECORD_FIELDS["FreePowerSnapshotData"]})
    if name == "dump":
        o = DUMP_ORIGINAL
        return ds.Record("DumpToGridSnapshotData", 0, 1, 0, o[244], o[256], o[257], o[258], o[259], o[260], o[261], 1000)
    return ds.Record("Reg244SnapshotData", 2)


def retry_record(name: str, needed: int) -> "ds.Record":
    return ds.Record("FreePowerRetryState" if name == "free_power" else "DumpToGridRetryState", needed)


def domain_nvs(name: str, state: int | None, *, retry: int | None = None) -> dict:
    """A durable image for ONE domain: marker `state` (None = never written)
    plus its data record (records are never erased, so a CLEAR marker next
    to a stale data record is the normal after-restore image)."""
    t = DOMAINS[name]
    nvs: dict = {}
    if state is not None:
        nvs[t["valid"]] = marker(state)
        nvs[t["data"]] = data_record(name)
    if retry is not None and t["retry"]:
        nvs[t["retry"]] = retry_record(name, retry)
    return nvs


def boot(nvs: dict, *, fw: dict = FW, fail=(), fail_all: bool = False, bank: dict | None = None) -> "ds.Sim":
    """A fresh ESP boot: new RAM, the given durable store (with the given
    loads failing as NVS READ ERRORS), the WHOLE real on_boot lambda."""
    sim = ds.Sim(fw)
    sim.nvs = {k: v.copy() for k, v in nvs.items()}
    sim.nvs_fail_load_tags = set(fail)
    sim.nvs_fail_load_all = fail_all
    sim.run_lambda(h.boot_lambda(fw))
    h.env(sim)
    sim.bank = dict(START_BANK if bank is None else bank)
    return sim


def flags(sim, name: str) -> tuple:
    return (sim.g[f"{name}_snapshot_valid"], sim.g[f"{name}_recovery_metadata_corrupt"], sim.g[f"{name}_marker_state"])


def status(sim, name: str) -> str:
    e = sim.entities.get(DOMAINS[name]["status"])
    return "" if e is None or not e.has_state() else str(e.state)


def containment(sim) -> str:
    e = sim.entities.get("dump_containment_state_sensor")
    return "" if e is None or not e.has_state() else str(e.state)


def nvs_fp(sim) -> dict:
    return {k: (v._kind, tuple(getattr(v, f) for f in ds._RECORD_FIELDS[v._kind])) for k, v in sim.nvs.items()}


# FB-B1 (D14): the three *_marker_boot_load globals keep each marker's boot load status (0 OK, 1 ABSENT, 2 WRONG_SIZE, 3 READ_ERROR)
# for the read-only Review gate. They exist only in the current firmware: main's on_boot never assigns them, so there they stay at
# their 255 power-on default. The "identical to main's on_boot" comparison in [5] therefore skips exactly these three names - every
# other RAM global and every entity publish is still compared, unchanged - and [5] pins their values separately.
FB_B1_RETENTION = ("free_power_marker_boot_load", "dump_marker_boot_load", "reg244_marker_boot_load")


def observable(sim, skip=()) -> tuple:
    """Everything a boot leaves behind: every RAM global and every entity
    publish, in order (`skip` names globals left out of the comparison)."""
    g = tuple(sorted((k, repr(v)) for k, v in sim.g.items() if k not in skip))
    ents = tuple(sorted((k, tuple(repr(p) for p in e.published)) for k, e in sim.entities.items() if hasattr(e, "published")))
    return g, ents


LOCKED_UNKNOWN = (True, True, CLEAR)  # snapshot_valid, corrupt, marker_state left at its power-on default


def function_body(name: str, text: str) -> str:
    m = re.search(r"\binline\s+[\w:<>&]+\s+" + re.escape(name) + r"\s*\(", text)
    if m is None:
        raise AssertionError(f"{name} not found")
    i = text.index("{", m.end())
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i + 1:j]
    raise AssertionError(f"unbalanced braces in {name}")


def statements(body: str) -> list[str]:
    code = re.sub(r"//[^\n]*", "", body)
    code = re.sub(r"\s+", " ", code).strip()
    return [s.strip() + ";" for s in code.split(";") if s.strip()]


# ===========================================================================
print("[1] header primitive: load_record_status() - same load, failure classified read-only")
# ===========================================================================
CLASSIFY = [
    "auto *prefs = esphome::global_preferences;",
    "if (prefs == nullptr || prefs->nvs_handle == 0) return LOAD_READ_ERROR;",
    "char key_str[esphome::UINT32_MAX_STR_SIZE];",
    "esphome::uint32_to_str(key_str, key);",
    "size_t stored_len = 0;",
    "esp_err_t err = nvs_get_blob(prefs->nvs_handle, key_str, nullptr, &stored_len);",
    "if (err == ESP_ERR_NVS_NOT_FOUND) return LOAD_ABSENT;",
    "if (err != ESP_OK) return LOAD_READ_ERROR;",
    "if (stored_len != expected_len) return LOAD_WRONG_SIZE;",
    "return LOAD_READ_ERROR;",
]
STATUS_LOAD = [
    "auto &pref = preference_for<T>(key);",
    "if (pref.load(&record)) return LOAD_OK;",
    "return classify_load_failure(key, sizeof(T));",
]


def header_ok(header: str) -> tuple[bool, str]:
    """The structural contract of the SG-06 primitive; (ok, reason)."""
    try:
        cls = statements(function_body("classify_load_failure", header))
        st = statements(function_body("load_record_status", header))
        lr = statements(function_body("load_record", header))
    except AssertionError as e:
        return False, str(e)
    if cls != CLASSIFY:
        return False, f"classify_load_failure = {cls}"
    if st != STATUS_LOAD:
        return False, f"load_record_status = {st}"
    if lr != ["auto &pref = preference_for<T>(key);", "return pref.load(&record);"]:
        return False, f"load_record = {lr}"
    enum = re.search(r"enum LoadStatus : uint8_t \{(.*?)\};", header, re.S)
    if enum is None or re.findall(r"(LOAD_\w+) = (\d+)", enum.group(1)) != [
            ("LOAD_OK", "0"), ("LOAD_ABSENT", "1"), ("LOAD_WRONG_SIZE", "2"), ("LOAD_READ_ERROR", "3")]:
        return False, "LoadStatus values"
    return True, ""


ok, why = header_ok(HEADER)
check("classify_load_failure(): exactly the pinned statement sequence - NVS unavailable -> READ_ERROR; "
      "ONLY ESP_ERR_NVS_NOT_FOUND -> ABSENT; any other error -> READ_ERROR; stored length != sizeof(T) -> "
      "WRONG_SIZE; length matches but the load failed -> READ_ERROR", ok, why)
cls_code = " ".join(statements(function_body("classify_load_failure", HEADER)))
check("LOAD_ABSENT is returned from exactly one place, guarded by err == ESP_ERR_NVS_NOT_FOUND",
      cls_code.count("return LOAD_ABSENT;") == 1 and "if (err == ESP_ERR_NVS_NOT_FOUND) return LOAD_ABSENT;" in cls_code)
new_code = cls_code + " ".join(statements(function_body("load_record_status", HEADER)))
check("the classifier is read-only: no nvs_set/erase/commit, no save()/sync(), no make_preference, no allocation",
      not re.search(r"nvs_set|nvs_erase|nvs_commit|nvs_open|nvs_close|\.save\(|sync\(|make_preference|\bnew\b|malloc",
                    new_code), new_code)
check("load_record_status() goes through the SAME cached preference object as load_record() (S2 cache kept; "
      "LOAD_OK exactly when load_record() would return true)",
      statements(function_body("load_record_status", HEADER))[:2] == STATUS_LOAD[:2])
check("load_record() itself is unchanged (data / retry / journal loads keep their semantics)",
      statements(function_body("load_record", HEADER)) == ["auto &pref = preference_for<T>(key);", "return pref.load(&record);"])
check("the simulator mirror uses the header's LoadStatus values",
      (D.LOAD_OK, D.LOAD_ABSENT, D.LOAD_WRONG_SIZE, D.LOAD_READ_ERROR) == (0, 1, 2, 3))
probe = ds.Sim(FW)
probe.nvs = {"k_ok": marker(CLEAR), "k_size": ds.Record("Reg244SnapshotData", 2)}
probe.nvs_fail_load_tags = {"k_io"}
probe.nvs["k_io"] = marker(RR)
check("simulator mirror: stored -> OK, nothing stored -> ABSENT, other-size record -> WRONG_SIZE, injected load "
      "failure -> READ_ERROR (even though a record IS stored)",
      [probe.D.load_record_status(k, probe.D.ValidMarker()) for k in ("k_ok", "k_none", "k_size", "k_io")]
      == [D.LOAD_OK, D.LOAD_ABSENT, D.LOAD_WRONG_SIZE, D.LOAD_READ_ERROR])

# ===========================================================================
print("")
print("[2] change scope vs main @ 049c37e")
# ===========================================================================
# FB-T0: every pin in this section is evaluated on the artifacts AS OF chain
# entry "dump_v2" (main @ ca7474e, the state these pins were written against):
# every LATER chain entry (registry/tests/_scope_chain.py) is undone first by its
# exact-match reverter, so a later PR's declared edits never need a re-hash here
# and any undeclared edit still breaks these pins. Today no entry follows
# "dump_v2", so these are byte-for-byte the same texts as before.
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_FW = ds.load_firmware_text(SCOPE_FW_TEXT)
SCOPE_BOOT = h.boot_lambda(SCOPE_FW)
SCOPE_HEADER = chain.CHAIN.as_of(chain.DURABLE_HEADER, "dump_v2", HEADER)
# Dump V2 (ownership evidence) later edited on_boot, the header, three Dump
# scripts and the globals; its exact edits are reverted first (see
# _dump_v2_scope.py), so these still prove byte-identity everywhere else.
check("on_boot with exactly SG-06's edits (and Dump V2's own later edits) reverted is byte-identical to main @ 049c37e",
      sg06.sha(sg06.pre_sg06_boot(dv2s.pre_dump_v2_boot(SCOPE_BOOT))) == sg06.BASE_BOOT_SHA)
check("durable header with exactly SG-06's edits (and Dump V2's own later edits) reverted is byte-identical to main @ 049c37e",
      sg06.sha(sg06.pre_sg06_header(dv2s.pre_dump_v2_header(SCOPE_HEADER))) == sg06.BASE_HEADER_SHA)
# Manual TOU Phase 1 later edited the six apply_manual_slotN scripts and the
# Load buttons, and added two RAM globals and one RAM-only interval; its exact
# edits are reverted first, so these pins still prove byte-identity everywhere
# else - see _mtou1_scope.py.
_PRE_MTOU1_TEXT = mtou1.pre_mtou1_text(SCOPE_FW_TEXT)
_PRE_MTOU1_FW = ds.load_firmware_text(_PRE_MTOU1_TEXT)
_bodies = {s["id"]: dv2s.pre_dump_v2_script(s["id"], fpsim.script_body(_PRE_MTOU1_TEXT, s["id"])) for s in SCOPE_FW["script"]}
check("every script body (all 30 - Force, Accept, Review, restore, START, every Dump script incl. #44 Accept "
      "gate and #46 containment, reg244, RTC, manual slots) is byte-identical to main @ 049c37e",
      len(_bodies) == 30 and sg06.sha("\n".join(f"== {k}\n{_bodies[k]}" for k in sorted(_bodies)))
      == "c5c32aa037479f1a1a9c1970a4afec580b5ef2972b69b463bde15220e51f87cc")
_rest = {k: v for k, v in _PRE_MTOU1_FW.items() if k not in ("esphome", "script", "_text", "_substitutions")}
_rest["globals"] = dv2s.pre_dump_v2_globals(_PRE_MTOU1_FW["globals"])
check("every other parsed section (globals - no new global -, intervals incl. watchdogs and PR41/S4 timers, "
      "sensors, buttons, API actions, substitutions) is identical to main @ 049c37e",
      sg06.sha(json.dumps(_rest, sort_keys=True, default=str))
      == "e5de3619882d23710bee8570e24a91fb67969ab437f9a8b7dc48f89ab1bca34e"
      and sg06.sha(json.dumps({k: v for k, v in SCOPE_FW["esphome"].items() if k != "on_boot"}, sort_keys=True, default=str))
      == "5b3bb6769ac5019479ef0c013bad035e0e247cba8eefa980614f1d556704e8e7"
      and sg06.sha(json.dumps(SCOPE_FW["esphome"]["on_boot"]["then"][1:], sort_keys=True, default=str))
      == "d9e9f34593af221c552f72a04f7cbc2c1632108eef345774e2791913f48bb4fe")
_loads = re.findall(r"ecco_durable::(load_record(?:_status)?)\(\s*ecco_durable::key_for\(ecco_durable::(\w+)\)", SCOPE_FW_TEXT)
check("exactly the three MARKER loads use load_record_status(); data, retry and journal loads still use "
      "load_record() (Dump V2 adds one: the diagnostic legacy-V1 probe in the fail-closed branch)",
      sorted(t for f, t in _loads if f == "load_record_status")
      == ["DUMP_TO_GRID_VALID_TAG", "FREE_POWER_VALID_TAG", "REG244_VALID_TAG"]
      and sorted(t for f, t in _loads if f == "load_record")
      == ["DUMP_TO_GRID_DATA_TAG", "DUMP_TO_GRID_DATA_TAG_V1", "DUMP_TO_GRID_RETRY_TAG", "FREE_POWER_DATA_TAG",
          "FREE_POWER_RETRY_TAG", "FREE_POWER_START_JOURNAL_TAG", "REG244_DATA_TAG"], str(_loads))
_boot_code = fpsim._strip_code(BOOT)
check("on_boot still commits nothing and performs no Modbus I/O",
      "commit_record" not in _boot_code and "modbus" not in _boot_code.lower())
for name, logtag in (("free_power", "free_power"), ("dump", "dump_to_grid"), ("reg244", "reg244_proof")):
    m = re.search(r"if \(" + name + r"_marker_unreadable\) \{(.*?)\} else if \(marker_malformed\)", BOOT, re.S)
    body = fpsim._strip_code(m.group(1)) if m else ""
    assigned = set(re.findall(r"id\((\w+)\)\s*=(?!=)", body))
    want = {f"{name}_snapshot_valid", f"{name}_recovery_metadata_corrupt"} | ({"dump_containment_state"} if name == "dump" else set())
    check(f"{name}: the UNKNOWN branch assigns exactly {sorted(want)} (all to true / state 8) - no marker state, no "
          "snapshot field, no commit, no clear",
          m is not None and assigned == want and "= false" not in body and "commit" not in body
          and all(f"id({g}) = true;" in body for g in want if g != "dump_containment_state"), str(assigned))

# ===========================================================================
print("")
print("[3] boot fault injection A-H, every domain (the real on_boot, whole lambda)")
# ===========================================================================
for name, t in DOMAINS.items():
    print(f"  -- {name} --")
    # A - genuinely absent
    s = boot({})
    check(f"{name} A: key genuinely absent -> CLEAR, no obligation", flags(s, name) == (False, False, CLEAR), str(flags(s, name)))
    # B - valid CLEAR marker
    s = boot(domain_nvs(name, CLEAR))
    check(f"{name} B: valid CLEAR marker -> CLEAR, no obligation", flags(s, name) == (False, False, CLEAR), str(flags(s, name)))
    # C - valid RESTORE_REQUIRED
    s = boot(domain_nvs(name, RR))
    check(f"{name} C: valid RESTORE_REQUIRED + data -> trusted obligation", flags(s, name) == (True, False, RR),
          str(flags(s, name)))
    check(f"{name} C: status is NOT the UNKNOWN wording", "UNKNOWN" not in status(s, name), status(s, name))
    # D - marker read fails, whatever is (or is not) stored
    for label, nvs in (("nothing stored", {}), ("CLEAR stored", domain_nvs(name, CLEAR)),
                       ("RESTORE_REQUIRED stored", domain_nvs(name, RR)),
                       ("PENDING_CLEAR stored", domain_nvs(name, PENDING))):
        s = boot(nvs, fail={t["valid"]})
        check(f"{name} D ({label}): marker read error -> UNKNOWN lockout (snapshot_valid AND metadata_corrupt, "
              "marker_state untouched) - never 'no obligation'", flags(s, name) == LOCKED_UNKNOWN, str(flags(s, name)))
        check(f"{name} D ({label}): status says RECOVERY BLOCKED + UNKNOWN, never claims a marker exists",
              status(s, name).startswith("RECOVERY BLOCKED") and "UNKNOWN" in status(s, name)
              and "marker exists" not in status(s, name), status(s, name))
        check(f"{name} D ({label}): zero durable commits, durable store byte-identical, zero Modbus",
              s.nvs_commits == [] and nvs_fp(s) == {k: (v._kind, tuple(getattr(v, f) for f in ds._RECORD_FIELDS[v._kind]))
                                                   for k, v in nvs.items()} and s.modbus_log == [])
    # E - data read fails with a RESTORE_REQUIRED marker (pre-existing fail-closed path)
    s = boot(domain_nvs(name, RR), fail={t["data"]})
    check(f"{name} E: marker RESTORE_REQUIRED + data read error -> the existing corrupt lockout (unchanged)",
          flags(s, name)[:2] == (True, True) and flags(s, name)[2] == RR, str(flags(s, name)))
    check(f"{name} E: ...with the existing 'marker exists' wording, not UNKNOWN",
          status(s, name).startswith("RECOVERY BLOCKED") and "UNKNOWN" not in status(s, name), status(s, name))
    # F - wrong-size / malformed marker record
    wrong = {**domain_nvs(name, RR), t["valid"]: ds.Record("Reg244SnapshotData", 1)}
    s = boot(wrong)
    check(f"{name} F: wrong-size marker record -> malformed lockout (never CLEAR, never RESTORE_REQUIRED)",
          flags(s, name) == LOCKED_UNKNOWN and "UNKNOWN" not in status(s, name) and s.nvs_commits == [],
          f"{flags(s, name)} {status(s, name)}")
    s = boot({**domain_nvs(name, RR), t["valid"]: marker(RR, magic=0x12345678)})
    check(f"{name} F: bad-magic marker -> malformed lockout (unchanged)", flags(s, name) == LOCKED_UNKNOWN)
    # G - retry-record read failure
    if t["retry"]:
        for needed in (0, 1):
            s = boot(domain_nvs(name, RR, retry=needed), fail={t["retry"]})
            check(f"{name} G (stored operator_needed={needed}): retry-record read error never changes the "
                  "obligation - marker/data still decide it (trusted RESTORE_REQUIRED, not corrupt)",
                  flags(s, name) == (True, False, RR), str(flags(s, name)))
            check(f"{name} G (stored operator_needed={needed}): retry pacing stays fail-OPEN exactly as on main "
                  "(deliberate, documented; not an obligation record)", s.g[f"{name}_operator_needed"] is False)
        s = boot(domain_nvs(name, None, retry=1), fail={t["retry"]})
        check(f"{name} G: retry read error with no marker -> still no obligation", flags(s, name) == (False, False, CLEAR))
    # H - transient failure, then a clean reboot
    for state in (CLEAR, RR):
        nvs = domain_nvs(name, state)
        first = boot(nvs, fail={t["valid"]})
        second = boot(first.nvs)
        clean = boot(nvs)
        check(f"{name} H ({'CLEAR' if state == CLEAR else 'RESTORE_REQUIRED'}): boot 1 UNKNOWN writes nothing; "
              "boot 2 (read succeeds) is exactly a clean boot - recovery is automatic, no operator action, no write loop",
              flags(first, name) == LOCKED_UNKNOWN and first.nvs_commits == [] and first.modbus_log == []
              and observable(second) == observable(clean))

print("  -- whole NVS unreadable (handle 0: every load fails) --")
full = {**domain_nvs("free_power", RR, retry=0)}
full[D.FREE_POWER_START_JOURNAL_TAG] = h.nvs_image(SNAP, journal=(15, VERIFIED))[D.FREE_POWER_START_JOURNAL_TAG]
s = boot(full, fail_all=True)
check("every domain UNKNOWN-locked", all(flags(s, n) == LOCKED_UNKNOWN for n in DOMAINS),
      str({n: flags(s, n) for n in DOMAINS}))
check("SG-01 journal NOT loaded (no evidence can be bound to an unknown obligation)",
      s.g["free_power_start_journal_valid"] is False and s.g["free_power_start_journal_mask"] == 0)
check("Dump containment parked in terminal state 8 with a NOT_ARMED diagnostic",
      s.g["dump_containment_state"] == 8 and containment(s).startswith("NOT_ARMED_OBLIGATION_UNKNOWN"), containment(s))
check("no durable commit, no Modbus", s.nvs_commits == [] and s.modbus_log == [])
check("the Recovery State sensors land on a locked value, never NONE",
      str(s.ent("dump_recovery_state").state).startswith("LOCKED")
      and str(s.ent("free_power_recovery_state").state) == "LOCKED_NEITHER",
      f"{s.ent('dump_recovery_state').state} / {s.ent('free_power_recovery_state').state}")
s_ok = boot(full)
check("...and the SAME store read cleanly: Free Power obligation + bound SG-01 journal load normally",
      flags(s_ok, "free_power") == (True, False, RR) and s_ok.g["free_power_start_journal_valid"] is True
      and s_ok.g["free_power_start_journal_mask"] == 15)

# ===========================================================================
print("")
print("[4] runtime consequences of UNKNOWN - nothing is written because storage is unreadable")
# ===========================================================================
_fp_watchdogs = [iv["then"] for iv in FW["interval"]
                 if any(a.get("if", {}).get("then") == [{"script.execute": {"id": WRAPPER}}] for a in iv["then"])]
check("exactly one Free Power watchdog interval", len(_fp_watchdogs) == 1)
DUMP_WATCHDOG = ds.find_interval(FW, "dump_overpower_samples")


def config_poll(sim) -> None:
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def fp_start(sim) -> list:
    n = len(sim.modbus_log)
    sim.execute(START)
    return [op for op in sim.modbus_log[n:] if op[0] == "write"]


def dump_start(sim) -> list:
    sim.bank.update(DUMP_ORIGINAL)
    sim.ent("dump_export_power").set(1000.0)
    sim.ent("dump_stop_soc").set(25.0)
    sim.ent("dump_duration_minutes").set(30.0)
    sim.ent("dump_write_enable").state = True
    sim.ent("dump_recovery_arm").state = False
    sim.ent("configuration_polling").state = True
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        sim.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        sim.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(sim)
    sim.ent("ecco_battery_soc").publish_state(70.0)
    sim.ent("ecco_grid_ct_power").publish_state(-1000.0)
    n = len(sim.modbus_log)
    sim.execute("start_dump_to_grid_override")
    return [op for op in sim.modbus_log[n:] if op[0] == "write"]


def dump_ticks(sim, n=6) -> None:
    for _ in range(n):
        sim.advance(15000)
        config_poll(sim)
        sim.run_actions(DUMP_WATCHDOG)


check("positive control: a clean empty boot lets Free Power START write", bool(fp_start(boot({}))))
check("positive control: a clean empty boot lets Dump START write", bool(dump_start(boot({}))))

# Every domain UNKNOWN (whole NVS unreadable) over a Free Power override left live on the inverter.
dev = boot(full, fail_all=True, bank=h.make_bank(h.live_for(h.states_of_row("IIII"), SNAP)))
nvs_before = nvs_fp(dev)
dev.epoch = SNAP["end_epoch"] + 3600
for _ in range(4):
    dev.advance(15000)
    dev.run_actions(_fp_watchdogs[0])
check("Free Power watchdog (lease long expired): zero Modbus I/O", dev.modbus_log == [], str(dev.modbus_log))
r = h.restore(dev)
check("automatic restore called directly: zero writes (no restore from an untrusted/unknown snapshot)", r.writes == [],
      str(r.writes))
check("Free Power START refused: zero writes", fp_start(dev) == [])
for action in ("FORCE_RESTORE_ORIGINAL", "ACCEPT_CURRENT_STATE"):
    run, _eid = h.operator_action(dev, h.FwCtx(FW_TEXT), action)
    check(f"{action}: cannot bypass the UNKNOWN lockout - zero writes, zero commits", run.writes == [] and run.commits == [],
          f"{run.writes} {run.commits}")
check("Dump START refused: zero writes", dump_start(dev) == [])
dev.bank.update(DUMP_RESIDUE)
dump_ticks(dev)
check("Dump watchdog x6 with live 244 = Allow Export: zero Modbus I/O - no restore, and NO containment write because "
      "storage is unreadable", dev.modbus_log == [], str(dev.modbus_log))
check("containment stays parked in terminal state 8", dev.g["dump_containment_state"] == 8)
dev.ent("dump_recovery_arm").state = True
dev.execute("dump_force_restore_original")
dev.execute("dump_accept_current_state")
check("Dump Force / Accept: zero Modbus writes", dev.writes() == [], str(dev.writes()))
dev.ent("manual_config_write_enable").state = True
dev.execute("restore_reg244_snapshot")
check("reg244 restore: zero Modbus writes", dev.writes() == [], str(dev.writes()))
# apply_reg244_settings reads a select entity the simulator does not model;
# its gate is pinned instead (the gate every START-like reg244 write passes).
_apply = fpsim._strip_code(fpsim.script_body(FW_TEXT, "apply_reg244_settings"))
check("reg244 apply is gated on !reg244_snapshot_valid AND !reg244_recovery_metadata_corrupt (both set by UNKNOWN)",
      "!id(reg244_snapshot_valid) &&" in _apply and "!id(reg244_recovery_metadata_corrupt) &&" in _apply)
check("after all of it: zero durable commits and the durable store is byte-identical (no marker/snapshot clearing)",
      dev.nvs_commits == [] and nvs_fp(dev) == nvs_before, str(dev.nvs_commits))

print("  -- one domain unreadable: the cross-domain START gates still see an obligation --")
check("Free Power marker UNKNOWN -> Dump START refused (shared 256-261)", dump_start(boot({}, fail={D.FREE_POWER_VALID_TAG})) == [])
check("Dump marker UNKNOWN -> Free Power START refused", fp_start(boot({}, fail={D.DUMP_TO_GRID_VALID_TAG})) == [])
check("reg244 marker UNKNOWN -> Free Power START refused", fp_start(boot({}, fail={D.REG244_VALID_TAG})) == [])
check("reg244 marker UNKNOWN -> Dump START refused (shared 244)", dump_start(boot({}, fail={D.REG244_VALID_TAG})) == [])

print("  -- #46 / SG-02 containment unchanged wherever a Dump obligation is KNOWN to exist --")
for label, nvs, fail in (("data record unreadable", domain_nvs("dump", RR), {D.DUMP_TO_GRID_DATA_TAG}),
                         ("malformed marker", {**domain_nvs("dump", RR), D.DUMP_TO_GRID_VALID_TAG: marker(RR, 0x12345678)}, ()),
                         ("wrong-size marker", {**domain_nvs("dump", RR),
                                                D.DUMP_TO_GRID_VALID_TAG: ds.Record("Reg244SnapshotData", 1)}, ())):
    s = boot(nvs, fail=fail, bank={**START_BANK, **DUMP_RESIDUE})
    dump_ticks(s, n=4)
    check(f"{label}: containment still writes exactly the literal 244 = 2", s.writes() == [(244, [2])], str(s.writes()))
s = boot(domain_nvs("dump", RR), bank={**START_BANK, **DUMP_RESIDUE})
dump_ticks(s, n=2)
check("trusted Dump obligation: normal restore unchanged",
      s.writes() == [(244, [2]), (256, [8000, 8000, 7000, 8000, 8000, 5000])], str(s.writes()))

print("  -- PR41 / S4 arbitration --")
s = boot({**domain_nvs("free_power", RR), **domain_nvs("dump", RR)})
check("readable Free Power + Dump RESTORE_REQUIRED: both still locked (PR41 unchanged)",
      flags(s, "free_power")[1] and flags(s, "dump")[1])
s = boot({**domain_nvs("dump", RR), **domain_nvs("reg244", RR)})
check("readable Dump + reg244 RESTORE_REQUIRED: both still locked (S4 unchanged)", flags(s, "dump")[1] and flags(s, "reg244")[1])
for fail_tag, other in ((D.FREE_POWER_VALID_TAG, "dump"), (D.DUMP_TO_GRID_VALID_TAG, "free_power"),
                        (D.REG244_VALID_TAG, "dump")):
    nvs = {**domain_nvs("free_power", RR), **domain_nvs("dump", RR), **domain_nvs("reg244", RR)}
    new, old = boot(nvs, fail={fail_tag}), boot(nvs, fail={fail_tag}, fw=OLD_FW)
    check(f"{fail_tag} unreadable: the other domain's arbitration outcome is exactly as on main (SG-06 never "
          "loosens it; whether UNKNOWN should also lock a trusted peer is an open decision)",
          flags(new, other) == flags(old, other), f"{flags(new, other)} vs {flags(old, other)}")

# ===========================================================================
print("")
print("[5] every readable boot is identical to main @ 049c37e")
# ===========================================================================
READABLE = {
    "empty store": ({}, ()),
    "all CLEAR": ({**domain_nvs("free_power", CLEAR), **domain_nvs("dump", CLEAR), **domain_nvs("reg244", CLEAR)}, ()),
    "Free Power RESTORE_REQUIRED + journal": (h.nvs_image(SNAP, journal=(7, 0)), ()),
    "Dump RESTORE_REQUIRED": (domain_nvs("dump", RR, retry=1), ()),
    "reg244 RESTORE_REQUIRED": (domain_nvs("reg244", RR), ()),
    "all PENDING_CLEAR": ({**domain_nvs("free_power", PENDING), **domain_nvs("dump", PENDING),
                           **domain_nvs("reg244", PENDING)}, ()),
    "PR41 dual": ({**domain_nvs("free_power", RR), **domain_nvs("dump", RR)}, ()),
    "S4 dual": ({**domain_nvs("dump", RR), **domain_nvs("reg244", RR)}, ()),
    "bad-magic markers": ({**{t["valid"]: marker(RR, 0x1) for t in DOMAINS.values()}}, ()),
    "data read errors": ({**domain_nvs("free_power", RR), **domain_nvs("dump", RR), **domain_nvs("reg244", RR)},
                         tuple(t["data"] for t in DOMAINS.values())),
    "retry + journal read errors": (h.nvs_image(SNAP, journal=(15, VERIFIED), operator_needed=1),
                                    (D.FREE_POWER_RETRY_TAG, D.FREE_POWER_START_JOURNAL_TAG)),
}
for label, (nvs, fail) in READABLE.items():
    check(f"{label}: every RAM global and every entity publish identical to main's on_boot",
          observable(boot(nvs, fail=fail), skip=FB_B1_RETENTION) == observable(boot(nvs, fail=fail, fw=OLD_FW), skip=FB_B1_RETENTION))
# FB-B1 (D14): what the skipped names hold. Each retains ITS marker's boot load status; nothing else in the boot depends on it.
_DOM = tuple(DOMAINS)


def _retained(sim) -> tuple:
    return tuple(sim.g[f"{n}_marker_boot_load"] for n in _DOM)


for label, (nvs, fail) in READABLE.items():
    check(f"{label}: FB-B1 retention - each *_marker_boot_load is its marker's load status (OK 0 if the marker is stored, else ABSENT 1)",
          _retained(boot(nvs, fail=fail)) == tuple(0 if DOMAINS[n]["valid"] in nvs else 1 for n in _DOM))
for _n, _t in DOMAINS.items():
    check(f"{_n} marker unreadable: FB-B1 retention - READ_ERROR 3 for that marker only, ABSENT 1 for the others",
          _retained(boot({}, fail={_t["valid"]})) == tuple(3 if n == _n else 1 for n in _DOM))
    check(f"{_n} marker of the wrong size: FB-B1 retention - WRONG_SIZE 2 for that marker only, ABSENT 1 for the others",
          _retained(boot({_t["valid"]: ds.Record("Reg244SnapshotData", 1)})) == tuple(2 if n == _n else 1 for n in _DOM))

# ===========================================================================
print("")
print("[6] mutations - each safeguard broken on purpose must be caught")
# ===========================================================================


def mutant(edits) -> dict:
    text = FW_TEXT
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            raise AssertionError(f"mutation anchor {old[:60]!r} found {found}x, expected {count}")
        text = text.replace(old, new)
    return ds.load_firmware_text(text)


def d_unknown_locked(fw) -> bool:
    for name, t in DOMAINS.items():
        for nvs in ({}, domain_nvs(name, CLEAR), domain_nvs(name, RR)):
            s = boot(nvs, fw=fw, fail={t["valid"]})
            if flags(s, name) != LOCKED_UNKNOWN or "UNKNOWN" not in status(s, name):
                return False
    return True


def d_wrong_size(fw) -> bool:
    return all(flags(boot({**domain_nvs(n, RR), t["valid"]: ds.Record("Reg244SnapshotData", 1)}, fw=fw), n)
               == LOCKED_UNKNOWN for n, t in DOMAINS.items())


def d_no_containment_write(fw) -> bool:
    s = boot({}, fw=fw, fail={D.DUMP_TO_GRID_VALID_TAG}, bank={**START_BANK, **DUMP_RESIDUE})
    dump_ticks(s)
    return s.modbus_log == []


def d_cross_domain(fw) -> bool:
    return dump_start(boot({}, fw=fw, fail={D.FREE_POWER_VALID_TAG})) == []


DETECTORS = {"unknown_locked": d_unknown_locked, "wrong_size": d_wrong_size,
             "no_containment_write": d_no_containment_write, "cross_domain": d_cross_domain}
for dname, det in DETECTORS.items():
    check(f"detector '{dname}' passes on the real firmware", det(FW))

MUTANTS = [
    ("return to main's on_boot (read error = CLEAR)", OLD_FW, "unknown_locked"),
    ("Free Power: read error treated as absent", mutant([(
        "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;",
        "free_power_marker_unreadable = false;", 1)]), "unknown_locked"),
    ("Dump: read error treated as absent", mutant([(
        "dump_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;", "dump_marker_unreadable = false;", 1)]),
     "unknown_locked"),
    ("reg244: read error treated as absent", mutant([(
        "reg244_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;", "reg244_marker_unreadable = false;", 1)]),
     "unknown_locked"),
    ("wrong-size marker no longer malformed", mutant([(
        "bool marker_malformed = marker_load == ecco_durable::LOAD_WRONG_SIZE || (have_marker && (",
        "bool marker_malformed = (have_marker && (", 3)]), "wrong_size"),
    ("Free Power UNKNOWN leaves metadata_corrupt clear", mutant([(
        "              id(free_power_recovery_metadata_corrupt) = true;\n"
        "              ESP_LOGE(\"free_power\", \"RECOVERY BLOCKED - durable recovery marker could not be read",
        "              ESP_LOGE(\"free_power\", \"RECOVERY BLOCKED - durable recovery marker could not be read", 1)]),
     "unknown_locked"),
    ("Free Power UNKNOWN leaves snapshot_valid clear (cross-domain gate open)", mutant([(
        "              id(free_power_snapshot_valid) = true;\n"
        "              id(free_power_recovery_metadata_corrupt) = true;\n"
        "              ESP_LOGE(\"free_power\", \"RECOVERY BLOCKED - durable recovery marker could not be read",
        "              id(free_power_recovery_metadata_corrupt) = true;\n"
        "              ESP_LOGE(\"free_power\", \"RECOVERY BLOCKED - durable recovery marker could not be read", 1)]),
     "cross_domain"),
    ("Dump UNKNOWN arms containment (state 8 not set)", mutant([(
        "              id(dump_containment_state) = 8;\n", "", 1)]), "no_containment_write"),
    ("containment seed ignores state 8", mutant([(
        "if (id(dump_containment_state) == 8) {", "if (false) {", 1)]), "no_containment_write"),
    ("Free Power status claims a marker exists", mutant([(
        "            if (free_power_marker_unreadable) {\n              // SG-06: the same lockout",
        "            if (false) {\n              // SG-06: the same lockout", 1)]), "unknown_locked"),
]
killed_all = True
for label, fw, aimed in MUTANTS:
    caught = [n for n, det in DETECTORS.items() if not det(fw)]
    ok = aimed in caught
    killed_all &= ok
    check(f"mutant killed by '{aimed}': {label}", ok, f"caught by {caught}")
hm = HEADER.replace("if (err == ESP_ERR_NVS_NOT_FOUND)\n    return LOAD_ABSENT;\n  if (err != ESP_OK)\n    return LOAD_READ_ERROR;",
                    "if (err != ESP_OK)\n    return LOAD_ABSENT;")
check("mutant killed by the header contract: every NVS error classified as ABSENT",
      hm != HEADER and not header_ok(hm)[0])
hm2 = HEADER.replace("  if (prefs == nullptr || prefs->nvs_handle == 0)\n    return LOAD_READ_ERROR;\n", "")
check("mutant killed by the header contract: NVS-unavailable guard removed", hm2 != HEADER and not header_ok(hm2)[0])
hm3 = HEADER.replace("  if (stored_len != expected_len)\n    return LOAD_WRONG_SIZE;\n  return LOAD_READ_ERROR;",
                     "  return LOAD_ABSENT;")
check("mutant killed by the header contract: size mismatch / failed read classified as ABSENT",
      hm3 != HEADER and not header_ok(hm3)[0])
check(f"every one of the {len(MUTANTS) + 3} mutants is killed (and by the detector aimed at it)", killed_all)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALL SG-06 CHECKS PASSED")
