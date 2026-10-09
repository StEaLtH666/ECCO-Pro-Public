#!/usr/bin/env python3
"""Regression suite: the ECCO Advanced / Experimental Configuration card (Phase 1A, read-only) and its catalogue generator.

  [1] determinism: two generator runs are identical and equal the committed module; --check agrees; nothing site- or run-specific
  [2] read-only inputs: generating never changes the registry, the overlay or the firmware; the generator writes only its output
  [3] fail closed: malformed registry / overlay / firmware input and every overlay promotion are refused (GeneratorError; the CLI
      exits 2 and writes nothing; a stale module exits 1 and is left untouched)
  [4] status classification: derived from the registry's own fields, evidence mapped one-to-one, the overlay only restricts
  [5] Global Power: register 245 is the Export Limit record, read-only, with no assumed hardware maximum and no firmware write path
  [6] register mapping: every entity link agrees with the firmware's entity names and steady-poll decode
  [7] no write vocabulary in the card's source, generated catalogue or bundle; no reserved fallback / shadow token in any card file
  [8] the bundle embeds this catalogue, and the bundle and example render correctly for any site slug
  [9] integration (acfg1): the card is used once, alone in a full-width section of the Inverter / Advanced view, with a configuration it
      accepts; the manifest lists its bundle once (manual copy and registration); it arrived with dashboard 7.19.0; acfg1 declares it

The card's own behaviour (values, freshness, search, filters, the disabled Global Power controls, the DOM event handlers) is tested
by its Node suite: frontend/ecco-advanced-config-card/test (npm test).

Test-only, no network. I/O: reads repo files; writes only under a temp dir.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build_advanced_config_catalogue as G  # noqa: E402
import ecco_site_render as R  # noqa: E402
import yaml  # noqa: E402

CARD = ROOT / "frontend" / "ecco-advanced-config-card"
DIST = CARD / "dist" / "ecco-advanced-config-card.js"
EXAMPLE = CARD / "examples" / "advanced-config-example.yaml"
OUT = ROOT / G.OUTPUT_REL
INPUTS = (G.REGISTRY_REL, G.OVERLAY_REL, G.FIRMWARE_REL)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def refused(fn, match: str | None = None) -> bool:
    """True when fn() raises GeneratorError (and its message matches `match`, if given)."""
    try:
        fn()
    except G.GeneratorError as ex:
        return match is None or re.search(match, str(ex)) is not None
    except Exception:  # noqa: BLE001 - any other exception is a crash, not a refusal
        return False
    return False


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn()


def card_files() -> list[Path]:
    return sorted(p for p in CARD.rglob("*") if p.is_file() and "node_modules" not in p.parts)


REG_TEXT = (ROOT / G.REGISTRY_REL).read_text(encoding="utf-8")
OV_TEXT = (ROOT / G.OVERLAY_REL).read_text(encoding="utf-8")
FW_TEXT = (ROOT / G.FIRMWARE_REL).read_text(encoding="utf-8")
REGISTRY = G.load_registry(REG_TEXT)
REG = {r["id"]: r for r in REGISTRY}
IDS = set(REG)
OV_RAW = yaml.safe_load(OV_TEXT)
OV = G.load_overlay(OV_TEXT, IDS)
FW = yaml.load(FW_TEXT, Loader=G._firmware_loader())  # noqa: S506 - the generator's SafeLoader subclass
ENTS = G.firmware_entities(FW)
DECODED, WINDOWS = G.firmware_decode(FW)
CAT = G.build_catalogue(ROOT)
ITEMS = {i["id"]: i for i in CAT["items"]}
COMMITTED = OUT.read_text(encoding="utf-8")

# ===========================================================================
print("[1] determinism and drift")
# ===========================================================================
before = {rel: sha((ROOT / rel).read_bytes()) for rel in INPUTS}
text1 = G.generate(ROOT)
text2 = G.generate(ROOT)
check("the generator is deterministic (two runs give identical text)", text1 == text2)
check("the committed module is exactly the generator output (regenerate: python tools/build_advanced_config_catalogue.py)",
      COMMITTED == text1, f"{len(COMMITTED)} vs {len(text1)} characters")
check("--check reports the committed module up to date (exit 0)", quiet(lambda: G.main(["--check"])) == 0)
m = re.search(r'export const CATALOGUE_SHA256 = "([0-9a-f]{64})";', COMMITTED)
check("the module's CATALOGUE_SHA256 is the sha256 of the canonical catalogue JSON",
      bool(m) and m.group(1) == sha(G.canonical(CAT).encode("utf-8")))
check("the module records no input hash, no absolute path and no generation time",
      not any(h in COMMITTED for h in before.values()) and not re.search(r"[A-Za-z]:\\|/home/|/Users/|/tmp/", COMMITTED)
      and not re.search(r"\b20\d\d-\d\d-\d\dT\d\d:\d\d", COMMITTED))
check("the module is the declared schema, read-only, with every registry record",
      CAT["schema"] == "ecco-advanced-config-catalogue/1" and CAT["read_only"] is True and CAT["record_count"] == len(REGISTRY) == 165
      and [i["id"] for i in CAT["items"]] != [] and sorted(ITEMS) == sorted(IDS))
check("numbers are portable (an integral float becomes an int; an unportable float is refused)",
      G.portable_numbers({"a": [1.0, 0.1, 2]}) == {"a": [1, 0.1, 2]} and isinstance(G.portable_numbers(1.0), int)
      and refused(lambda: G.portable_numbers(1e-05), "portable") and refused(lambda: G.portable_numbers(float("nan")), "non-finite"))

# ===========================================================================
print("")
print("[2] the inputs are read-only")
# ===========================================================================
quiet(lambda: G.main(["--report"]))
quiet(lambda: G.main(["--check"]))
after = {rel: sha((ROOT / rel).read_bytes()) for rel in INPUTS}
check("generating, --check and --report leave the registry, the overlay and the firmware byte-identical", before == after,
      str([r for r in INPUTS if before[r] != after[r]]))
gen_src = (ROOT / "tools" / "build_advanced_config_catalogue.py").read_text(encoding="utf-8")
check("the generator has exactly one write call, to its output module (no open(), no write_bytes)",
      gen_src.count(".write_text(") == 1 and "out.write_text(text" in gen_src and "open(" not in gen_src
      and ".write_bytes(" not in gen_src and "shutil" not in gen_src)
check("the overlay is a presentation file: no write, service, entity-id or register-write key",
      not re.search(r"(?im)^\s*(write|service|action|entity_id|start_address|values)\s*:", OV_TEXT))
check("the capability registry still has 165 records and no record the overlay invented",
      len(REGISTRY) == 165 and set((OV_RAW.get("records") or {})) <= IDS and set((OV_RAW.get("entity_links") or {})) <= IDS)

# ===========================================================================
print("")
print("[3] fail closed")
# ===========================================================================


def ov_text(mutate) -> str:
    o = copy.deepcopy(OV_RAW)
    mutate(o)
    return yaml.safe_dump(o, sort_keys=False, allow_unicode=True)


def ov_refused(mutate, match: str | None = None) -> bool:
    return refused(lambda: G.load_overlay(ov_text(mutate), IDS), match)


def build_refused(mutate, match: str | None = None) -> bool:
    def run():
        ov = G.load_overlay(ov_text(mutate), IDS)
        G.build_global_power(ov, G.build_items(REGISTRY, ov, ENTS, DECODED))
    return refused(run, match)


def setk(path: str, value):
    def mutate(o):
        node = o
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        if value is KeyError:
            del node[keys[-1]]
        else:
            node[keys[-1]] = value
    return mutate


RO_ID = "day_battery_charge"            # READ_ONLY in the registry, no overlay entry
PROVEN_ID = "tou_slot_1_power"          # PROVEN (live_proven_write) elsewhere in ECCO
check("fixture records have the expected derived status",
      ITEMS[RO_ID]["status"] == ITEMS[RO_ID]["status_derived"] == "READ_ONLY" and RO_ID not in OV_RAW["records"]
      and ITEMS[PROVEN_ID]["status_derived"] == "PROVEN" and ITEMS["remote_lock"]["status_derived"] == "UNSUPPORTED")
check("the overlay can never promote: READ_ONLY -> PROVEN / EXPERIMENTAL, UNSUPPORTED -> READ_ONLY, LOCKED record -> PROVEN",
      build_refused(setk(f"records.{RO_ID}", {"restrict": "PROVEN", "lock_reason": "x"}), "PROMOTE")
      and build_refused(setk(f"records.{RO_ID}", {"restrict": "EXPERIMENTAL", "lock_reason": "x"}), "PROMOTE")
      and build_refused(setk("records.remote_lock", {"restrict": "READ_ONLY", "lock_reason": "x"}), "PROMOTE")
      and build_refused(setk("records.battery_capacity_ah", {"restrict": "PROVEN", "lock_reason": "x"}), "PROMOTE"))


def restricted(rid: str, status: str) -> dict:
    ov = G.load_overlay(ov_text(setk(f"records.{rid}", {"restrict": status, "lock_reason": "Synthetic lock."})), IDS)
    return {i["id"]: i for i in G.build_items(REGISTRY, ov, ENTS, DECODED)}[rid]


_lock_ro, _lock_pr = restricted(RO_ID, "LOCKED"), restricted(PROVEN_ID, "UNSUPPORTED")
check("restricting (moving DOWN the ladder) is accepted and keeps the derived status visible",
      (_lock_ro["status"], _lock_ro["status_derived"], _lock_ro["lock_reason"]) == ("LOCKED", "READ_ONLY", "Synthetic lock.")
      and (_lock_pr["status"], _lock_pr["status_derived"]) == ("UNSUPPORTED", "PROVEN"))
OVERLAY_BAD = {
    "an unknown top-level key": (setk("writable", True), "unknown top-level"),
    "a wrong schema": (setk("schema", "ecco-advanced-config-overlay/2"), "schema"),
    "eight sections": (lambda o: o["sections"].pop(), "exactly 9"),
    "a duplicate section id": (lambda o: o["sections"].__setitem__(1, dict(o["sections"][0])), "duplicate section"),
    "a section without a summary": (lambda o: o["sections"][0].pop("summary"), "bad section"),
    "a category mapped to no section": (setk("category_sections.battery", "nowhere"), "category_sections"),
    "an invalid section-rule pattern": (lambda o: o["section_rules"].append({"id_pattern": "(", "section": "experimental"}), "pattern"),
    "a danger class outside D0-D4": (setk("category_danger.battery", "D9"), "category_danger"),
    "a record the registry does not have": (setk("records.no_such_record", {"section": "experimental"}), "not a registry record"),
    "an unknown record key": (setk(f"records.{RO_ID}", {"writable": True}), "unknown key"),
    "a restriction without a lock reason": (setk(f"records.{RO_ID}", {"restrict": "LOCKED"}), "lock_reason"),
    "a restriction to an unknown status": (setk(f"records.{RO_ID}", {"restrict": "WRITABLE", "lock_reason": "x"}), "restrict must"),
    "an entity link to a malformed firmware id": (setk("entity_links.export_limit", "Bad-Id"), "bad firmware id"),
    "no global_power block": (setk("global_power", KeyError), "global_power must"),
    "a global_power key the schema lacks": (setk("global_power.allow_write", True), "unknown key"),
    "a hardware maximum without evidence": (setk("global_power.hardware_maximum_w", 8000), "never assumed"),
    "a boolean hardware maximum": (setk("global_power.hardware_maximum_w", True), "hardware_maximum_w"),
    "a negative hardware maximum": (setk("global_power.hardware_maximum_w", -5), "hardware_maximum_w"),
    "a text regulatory allowance": (setk("global_power.regulatory_allowance_w", "3680"), "regulatory_allowance_w"),
    "write_status 'enabled'": (setk("global_power.write_status", "enabled"), "write_status"),
    "a missing future control": (lambda o: o["global_power"]["future_controls"].pop("apply"), "future_controls"),
    "an extra future control": (setk("global_power.future_controls.write_now", "x"), "future_controls"),
    "an owner confirmation without a date": (lambda o: o["global_power"]["owner_confirmation"].pop("date"), "owner_confirmation"),
    "no write blockers": (setk("global_power.write_blockers", []), "write_blockers"),
    "empty notes": (setk("notes", "  "), "notes"),
}
for label, (mutate, match) in OVERLAY_BAD.items():
    check(f"overlay refused: {label}", ov_refused(mutate, match))
check("overlay refused: not YAML, not a mapping",
      refused(lambda: G.load_overlay("a: [", IDS), "not valid YAML") and refused(lambda: G.load_overlay("- a\n- b\n", IDS), "mapping"))
check("Global Power refused: a PROVEN record, a register other than its record's, a multi-register record",
      build_refused(lambda o: o["global_power"].update(record="grid_export_policy", register=244), "PROVEN")
      and build_refused(setk("global_power.register", 244), "not register 244")
      and build_refused(lambda o: o["global_power"].update(record="free_power_transaction", register=230), "not register 230"))
check("entity links refused: a firmware id that does not exist, an entity that decodes other registers",
      build_refused(setk("entity_links.export_limit", "no_such_entity"), "no firmware entity")
      and build_refused(setk("entity_links.export_limit", "ecco_cfg_gen_grid_signal_raw"), "decodes registers"))


def reg_refused(text: str, match: str) -> bool:
    return refused(lambda: G.load_registry(text), match)


_reg = yaml.safe_load(REG_TEXT)


def reg_text(mutate) -> str:
    r = copy.deepcopy(_reg)
    mutate(r)
    return yaml.safe_dump(r, sort_keys=False, allow_unicode=True)


check("registry refused: wrong schema version, no list, duplicate id, unknown proof / access / policy, missing name, not YAML",
      reg_refused(reg_text(lambda r: r.update(schema_version=1)), "schema_version 2")
      and reg_refused(reg_text(lambda r: r.update(capabilities={})), "schema_version 2")
      and reg_refused(reg_text(lambda r: r["capabilities"].append(dict(r["capabilities"][0]))), "duplicate")
      and reg_refused(reg_text(lambda r: r["capabilities"][0].update(live_proof_status="sort_of")), "live_proof_status")
      and reg_refused(reg_text(lambda r: r["capabilities"][0].update(current_access="anything")), "current_access")
      and reg_refused(reg_text(lambda r: r["capabilities"][0].update(write_policy="W9")), "write_policy")
      and reg_refused(reg_text(lambda r: r["capabilities"][0].pop("name")), "has no name")
      and reg_refused("capabilities: [", "not valid YAML"))
check("firmware refused: no named entity, a duplicate entity id, a missing steady read window",
      refused(lambda: G.firmware_entities({}), "no named entities")
      and refused(lambda: G.firmware_entities({"sensor": [{"id": "a", "name": "A"}], "text_sensor": [{"id": "a", "name": "B"}]}), "duplicate")
      and refused(lambda: G.steady_windows({"script": []}), "expected exactly one steady read"))

with tempfile.TemporaryDirectory(prefix="ecco_advcfg_") as td:
    tmp = Path(td)

    def seed(overlay: str = OV_TEXT, firmware: str = FW_TEXT) -> Path:
        for rel, text in ((G.REGISTRY_REL, REG_TEXT), (G.OVERLAY_REL, overlay), (G.FIRMWARE_REL, firmware)):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text(text, encoding="utf-8", newline="\n")
        (tmp / "tools").mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "tools" / "ecco_site_render.py", tmp / "tools" / "ecco_site_render.py")
        return tmp

    out_tmp = tmp / G.OUTPUT_REL
    seed()
    rc_ok = quiet(lambda: G.main(["--root", str(tmp)]))
    check("a copy of the inputs elsewhere generates the identical module (no path or site dependency), and --check passes there",
          rc_ok == 0 and out_tmp.read_text(encoding="utf-8") == COMMITTED and quiet(lambda: G.main(["--root", str(tmp), "--check"])) == 0)
    out_tmp.write_text(COMMITTED.replace("Battery and Charging", "Battery & Charging"), encoding="utf-8", newline="\n")
    stale = out_tmp.read_bytes()
    check("a stale module makes --check exit 1 and stay untouched",
          quiet(lambda: G.main(["--root", str(tmp), "--check"])) == 1 and out_tmp.read_bytes() == stale)
    out_tmp.unlink()
    seed(overlay=ov_text(setk(f"records.{RO_ID}", {"restrict": "PROVEN", "lock_reason": "x"})))
    check("a promoting overlay makes the CLI exit 2 and write nothing",
          quiet(lambda: G.main(["--root", str(tmp)])) == 2 and not out_tmp.exists())
    seed(overlay=ov_text(lambda o: [o["records"][r].update(section="comms_diagnostics") for r in o["records"]
                                     if o["records"][r].get("section") == "experimental"]))
    check("an overlay that would leave a section empty is refused", refused(lambda: G.build_catalogue(tmp), "would be empty"))
    seed(firmware=FW_TEXT.replace("id: telemetry_online\n", "id: telemetry_online_renamed\n", 1))
    check("a firmware without the telemetry freshness gate is refused", refused(lambda: G.build_catalogue(tmp), "freshness gates"))
    seed(firmware="- not\n- a mapping\n")
    check("a firmware YAML that is not a mapping is refused", refused(lambda: G.build_catalogue(tmp), "must be a mapping"))
    seed(firmware="esphome: [\n")
    check("a firmware that is not YAML is refused", refused(lambda: G.build_catalogue(tmp), "not valid YAML"))

# ===========================================================================
print("")
print("[4] status classification and evidence")
# ===========================================================================
RANK = {s: n for n, s in enumerate(G.STATUS_ORDER)}
counts = {s: sum(1 for i in CAT["items"] if i["status"] == s) for s in G.STATUS_ORDER}
check("distribution: 41 proven elsewhere, 1 experimental, 100 read-only, 16 locked, 7 unsupported",
      counts == {"PROVEN": 41, "EXPERIMENTAL": 1, "READ_ONLY": 100, "LOCKED": 16, "UNSUPPORTED": 7}, str(counts))
bad = [i["id"] for i in CAT["items"] if i["status_derived"] != G.derived_status(REG[i["id"]])
       or i["evidence"] != G.EVIDENCE_BY_PROOF[REG[i["id"]]["live_proof_status"]]
       or (i["live_proof_status"], i["write_policy"], i["current_access"])
       != (REG[i["id"]]["live_proof_status"], REG[i["id"]]["write_policy"], REG[i["id"]]["current_access"])]
check("every record's derived status, evidence code and policy fields come from its own registry record", not bad, str(bad[:5]))
check("derived status rules: unknown proof or WX -> UNSUPPORTED; writable + write-proven -> PROVEN; writable -> EXPERIMENTAL; else READ_ONLY",
      [G.derived_status(r) for r in (
          {"live_proof_status": "unknown", "write_policy": "W1", "current_access": "read_write"},
          {"live_proof_status": "live_proven_write", "write_policy": "WX", "current_access": "read_write"},
          {"live_proof_status": "live_proven_write", "write_policy": "W2", "current_access": "read_write"},
          {"live_proof_status": "documented_not_live_proven", "write_policy": "W2", "current_access": "read_write"},
          {"live_proof_status": "live_proven_write", "write_policy": "R0", "current_access": "read_only"})]
      == ["UNSUPPORTED", "UNSUPPORTED", "PROVEN", "EXPERIMENTAL", "READ_ONLY"])
promoted = [i["id"] for i in CAT["items"] if RANK[i["status"]] < RANK[i["status_derived"]]]
unexplained = [i["id"] for i in CAT["items"] if i["status"] != i["status_derived"]
               and (OV_RAW["records"].get(i["id"]) or {}).get("restrict") != i["status"]]
check("no record is above its derived status, and every change is an overlay restriction", not promoted and not unexplained,
      str(promoted + unexplained))
locked = sorted(i["id"] for i in CAT["items"] if i["status"] == "LOCKED")
check("the locked records are exactly the overlay's LOCKED restrictions, each D4 with its own reason",
      locked == sorted(k for k, v in OV_RAW["records"].items() if v.get("restrict") == "LOCKED")
      and all(ITEMS[r]["danger"] == "D4" and ITEMS[r]["lock_reason"] == OV_RAW["records"][r]["lock_reason"] for r in locked))
check("the grid protection thresholds (287-290) are LOCKED",
      [(ITEMS[r]["registers"][0]["address"], ITEMS[r]["status"]) for r in ("grid_max_voltage_threshold", "grid_min_voltage_threshold",
                                                                            "grid_max_frequency_threshold", "grid_min_frequency_threshold")]
      == [(287, "LOCKED"), (288, "LOCKED"), (289, "LOCKED"), (290, "LOCKED")])
check("records proven writable elsewhere say this page cannot change them; unsupported records are all in Experimental / Undocumented",
      all("This page is read-only" in i["lock_reason"] for i in CAT["items"] if i["status"] == "PROVEN")
      and {i["section"] for i in CAT["items"] if i["status"] == "UNSUPPORTED"} == {"experimental"})
check("the nine sections, in order, none empty",
      [s["id"] for s in CAT["sections"]] == ["battery_charging", "grid_export", "inverter_power", "time_of_use", "generator_aux",
                                             "solar_pv", "protection_safety", "comms_diagnostics", "experimental"]
      and all(any(i["section"] == s["id"] for i in CAT["items"]) for s in CAT["sections"]))

# ===========================================================================
print("")
print("[5] Global Power / Export Limit (register 245)")
# ===========================================================================
GP = CAT["global_power"]
EL = ITEMS["export_limit"]
check("Global Power is the Export Limit record on register 245, owner-confirmed",
      (GP["record"], GP["register"], GP["title"]) == ("export_limit", 245, "Global Power / Export Limit")
      and GP["owner_confirmation"]["date"] == "2026-10-08" and "245" in GP["owner_confirmation"]["statement"])
check("the registry record is register 245, read-only (R0), read-proven",
      [r["address"] for r in G.registers_of(REG["export_limit"])] == [245]
      and (REG["export_limit"]["write_policy"], REG["export_limit"]["current_access"], REG["export_limit"]["live_proof_status"])
      == ("R0", "read_only", "live_proven_read"))
check("the catalogue item is READ_ONLY in Inverter Power, D3, unit W, with no options or ceiling",
      (EL["status"], EL["section"], EL["danger"], EL["unit"], EL["options"]) == ("READ_ONLY", "inverter_power", "D3", "W", {}))
check("it reads the configuration poll's linear decode of register 245 through ECCO Export Limit",
      EL["entity"] == {"domain": "sensor", "object": "ecco_export_limit", "firmware_id": "ecco_cfg_export_limit",
                       "name": "ECCO Export Limit", "link": "registry"}
      and EL["decode"] == {"kind": "linear", "window": "241-293", "registers": [245], "signed": False, "scale": 1, "offset": 0}
      and EL["poll_class"] == "configuration"
      and sorted(f for f, d in DECODED.items() if 245 in d["registers"]) == ["ecco_cfg_export_limit"])
check("no hardware maximum is assumed and no regulatory allowance invented; writing is not implemented",
      GP["hardware_maximum_w"] is None and GP["hardware_maximum_evidence"] is None and GP["regulatory_allowance_w"] is None
      and GP["write_status"] == "not_implemented" and "8000" not in json.dumps(GP)
      and not re.search(r"\d{3,}", GP["hardware_maximum_note"] or "") and len(GP["write_blockers"]) >= 4)
check("the seven future controls are designed (descriptions only)",
      sorted(GP["future_controls"]) == sorted(G.FUTURE_CONTROL_KEYS) and len(G.FUTURE_CONTROL_KEYS) == 7)
writes = []


def _walk_writes(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.startswith("modbus_client.write") and isinstance(v, dict):
                writes.append(str(v.get("start_address")))
            _walk_writes(v)
    elif isinstance(node, list):
        for v in node:
            _walk_writes(v)


_walk_writes(FW)
check("no firmware write action starts at register 245 (the whole write surface is proven by registry/tests/test_write_surface_invariants.py)",
      len(writes) == 52 and all(w.isdigit() for w in writes) and "245" not in writes and "0x00F5" not in FW_TEXT, str(len(writes)))

# ===========================================================================
print("")
print("[6] register mapping")
# ===========================================================================
linked = [i for i in CAT["items"] if "entity" in i]
mismatch = [i["id"] for i in linked if i["entity"]["firmware_id"] not in ENTS
            or {k: ENTS[i["entity"]["firmware_id"]][k] for k in ("domain", "object", "name")}
            != {k: i["entity"][k] for k in ("domain", "object", "name")}]
check("every linked entity is a firmware entity with the same domain, object id and name", not mismatch, str(mismatch[:5]))
relink = [i["id"] for i in CAT["items"] if G.link_entity(REG[i["id"]], ENTS, DECODED, OV.get("entity_links") or {})
          != ((i["entity"]["firmware_id"], i["entity"]["link"]) if "entity" in i else (None, None))]
check("every link is reproduced from the registry, the overlay or a unique firmware decode", not relink, str(relink[:5]))
dec_bad = [i["id"] for i in CAT["items"] if "decode" in i and (
    DECODED[i["entity"]["firmware_id"]]["registers"] != i["decode"]["registers"]
    or not {r["address"] for r in i["registers"]} & set(i["decode"]["registers"]))]
check("every decode is the linked entity's own steady-poll decode and reads the record's registers", not dec_bad, str(dec_bad[:5]))
check("raw-word entities are the firmware's ' Raw' / ' Raw Flags' sensors",
      all(ENTS[i["raw_entity"]["firmware_id"]]["name"].endswith((" Raw", " Raw Flags")) for i in CAT["items"] if "raw_entity" in i))
check("158 of 165 records are linked (108 registry, 49 firmware decode, 1 overlay); the 7 unlinked have no ECCO entity",
      len(linked) == 158 and sorted(i["entity"]["link"] for i in linked).count("registry") == 108
      and sum(1 for i in linked if i["entity"]["link"] == "firmware_decode") == 49
      and sum(1 for i in linked if i["entity"]["link"] == "overlay") == 1)
check("the steady windows and the two freshness gates are the firmware's",
      CAT["steady_windows"] == ["22-24", "59-116", "150-196", "200-240", "241-293", "330-330"]
      and CAT["freshness_gates"] == {"telemetry": {"domain": "binary_sensor", "object": "telemetry_online"},
                                     "configuration": {"domain": "binary_sensor", "object": "configuration_online"}})
check("entity references carry no device slug (ids are built at run time from entity_prefix)",
      not any(ref["object"].startswith(G.DEFAULT_SLUG) for i in CAT["items"] for ref in (i.get("entity"), i.get("raw_entity")) if ref))
check("ESPHome text sensors are named in Home Assistant's sensor domain in the registry text",
      G.normalize_ha_text("text_sensor.ecco_clock_dongle_x and my_text_sensor.ecco_clock_dongle_y")
      == "sensor.ecco_clock_dongle_x and my_text_sensor.ecco_clock_dongle_y")

# ===========================================================================
print("")
print("[7] no write vocabulary, no reserved token")
# ===========================================================================
RESERVED = ("ecco_" + "fallback", "FALLBACK" + "_PROFILE", "FAILBACK" + "_STATE", "ecco_" + "failback", "failback" + "_shadow",
            "ecco_" + "shadow_", "Shadow" + " Recovery", "fbc" + "_raw_", "fallback_profile" + "_live_match")
check("the generator's reserved-token list covers the repository's frontend bans", set(G.RESERVED_TOKENS) <= set(RESERVED)
      and len(G.RESERVED_TOKENS) == 8)
hits = [(p.relative_to(ROOT).as_posix(), t) for p in card_files() + [ROOT / G.OVERLAY_REL, ROOT / "tools" / "build_advanced_config_catalogue.py"]
        for t in RESERVED if t in p.read_text(encoding="utf-8", errors="ignore")]
check("no card file (source, tests, README, example, bundle), the overlay or the generator spells a reserved token", not hits, str(hits))
WRITE_WORDS = G.WRITE_VOCABULARY + ("callApi", "fetchWithAuth", "subscribeEvents", "subscribeMessage", "EventSource", "sendBeacon",
                                    "localStorage", "button.press", "switch.turn_on", "switch.turn_off", "number.set_value",
                                    "select.select_option", "hass-action", "dispatchEvent")
shipped = sorted((CARD / "src").glob("*.ts")) + [DIST]
vocab = [(p.relative_to(ROOT).as_posix(), w) for p in shipped for w in WRITE_WORDS if w in p.read_text(encoding="utf-8")]
check("no service / websocket / API / network / storage / event-dispatch word in the card source, catalogue or bundle", not vocab, str(vocab))
card_ts = (CARD / "src" / "ecco-advanced-config-card.ts").read_text(encoding="utf-8")
check("the element keeps only hass.states (it never stores the Home Assistant object)",
      card_ts.count("set hass(") == 1 and "(hass as { states?: unknown }).states" in card_ts
      and not re.search(r"this\._?hass\s*=", card_ts) and "get hass(" not in card_ts)
check("the only events handled are input and click, and the only actions are the four local view actions",
      sorted(re.findall(r'addEventListener\("([a-z]+)"', card_ts)) == ["click", "input"]
      and sorted(set(re.findall(r'data-action="([a-z-]+)"', "".join(p.read_text(encoding="utf-8") for p in shipped[:-1]))))
      == ["clear-filters", "search", "toggle-filter", "toggle-item"])
gp_src = (CARD / "src" / "render.ts").read_text(encoding="utf-8")
gp_src = gp_src[gp_src.index("export function renderGlobalPower"):gp_src.index("export function renderShell")]
check("the Global Power controls are rendered disabled and without an action",
      "data-action" not in gp_src and gp_src.count("<button ") == 1 and gp_src.count("<input ") == 1
      and all(' disabled aria-disabled="true"' in t for t in re.findall(r"<(?:button|input) [^>]*>", gp_src)))

# ===========================================================================
print("")
print("[8] the bundle and the site renderer")
# ===========================================================================
dist = DIST.read_text(encoding="utf-8")
check("the committed bundle embeds this catalogue (rebuild: npm run build; the Node suite proves the rebuild is byte-identical)",
      bool(m) and m.group(1) in dist and '"0.1.0"' in dist)
check("the bundle is self-contained: no import, no require, no source map, no local path",
      not re.search(r"(?:^|[;\n])\s*import\s*[\s{*\"']", dist) and "require(" not in dist and "sourceMappingURL" not in dist
      and not re.search(r"[A-Za-z]:\\|/Users/|/home/|node_modules", dist))
rs = R.render_set(ROOT)
check("the site renderer renders the bundle and the example (and not the sources or tests)",
      {"frontend/ecco-advanced-config-card/dist/ecco-advanced-config-card.js",
       "frontend/ecco-advanced-config-card/examples/advanced-config-example.yaml"} <= set(rs)
      and not [r for r in rs if r.startswith("frontend/ecco-advanced-config-card/") and "/dist/" not in r and "/examples/" not in r])
actions = R.firmware_actions(ROOT)
for p in (DIST, EXAMPLE):
    rel = p.relative_to(ROOT).as_posix()
    text = p.read_text(encoding="utf-8")
    ident, _c0 = R.render_text(rel, text, R.Site(), actions)
    custom, _c1 = R.render_text(rel, text, R.Site(device_slug="site_b_dongle"), actions)
    check(f"{rel}: the default site renders the identity; a custom slug leaves no default-slug entity id and sets the slug",
          ident == text and not any(f"{d}.{G.DEFAULT_SLUG}_" in custom for d in R.DOMAINS)
          and '"site_b_dongle"' in custom and f'"{G.DEFAULT_SLUG}"' not in custom)

# ===========================================================================
print("")
print("[9] integration (acfg1): one card on the dashboard, one manifest stanza, declared by the acfg1 entry")
# ===========================================================================
TAG = "ecco-advanced-config-card"
DASH_REL, MAN_REL, VER_REL = "home-assistant/dashboards/ecco_pro.yaml", "deployment/ha-manifest.yaml", "VERSION.yaml"
CARD_KEYS = {"title", "entity_prefix", "max_age_telemetry_s", "max_age_configuration_s", "max_age_rtc_s"}
LAYOUT_KEYS = {"type", "view_layout", "grid_options", "visibility", "layout_options"}


class _TagLoader(yaml.SafeLoader):
    """SafeLoader that keeps Home Assistant's custom tags as plain values (the dashboard parses like the other suites read it)."""


_TagLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


dash_text = (ROOT / DASH_REL).read_text(encoding="utf-8")
dash = yaml.load(dash_text, Loader=_TagLoader)
uses = [n for n in _walk(dash) if isinstance(n, dict) and n.get("type") == f"custom:{TAG}"]
inv = next((v for v in dash["views"] if v.get("title") == "Inverter / Advanced"), {})
card = uses[0] if len(uses) == 1 else {}
home = [s for s in (inv.get("sections") or []) if any(c is card for c in (s.get("cards") or []))]
check("the dashboard uses the card exactly once, alone in a full-width grid section of the Inverter / Advanced view",
      len(uses) == 1 and dash_text.count(f"type: custom:{TAG}") == 1 and len(home) == 1 and home[0].get("type") == "grid"
      and home[0].get("column_span") == 4 and home[0].get("cards") == [card], str(len(uses)))
check("its configuration is one the card accepts: title, the quoted default device slug (site-rendered) and the grid layout only - no "
      "action, service or entity key",
      set(card) == {"type", "title", "entity_prefix", "grid_options"} and set(card) <= CARD_KEYS | LAYOUT_KEYS
      and card.get("entity_prefix") == G.DEFAULT_SLUG and f'entity_prefix: "{G.DEFAULT_SLUG}"' in dash_text
      and isinstance(card.get("title"), str) and 0 < len(card["title"]) <= 120 and card.get("grid_options") == {"columns": 48, "rows": "auto"})
man_text = (ROOT / MAN_REL).read_text(encoding="utf-8")
man = yaml.safe_load(man_text)
mine = [a for a in man["frontend_assets"] if TAG in a.get("source", "")]
ea = [a for a in man["frontend_assets"] if "ecco-energy-actions-card" in a.get("source", "")]
check("the manifest lists the bundle exactly once, in the Energy Actions stanza's shape (copy and resource registration stay manual)",
      len(mine) == 1 and len(ea) == 1 and set(mine[0]) == set(ea[0])
      and mine[0] == {"source": f"frontend/{TAG}/dist/{TAG}.js", "destination": f"/config/www/ecco/{TAG}.js", "method": "ssh_file_copy",
                      "restart_required": False, "resource_registration": "manual", "resource_url": f"/local/ecco/{TAG}.js"}
      and (ROOT / mine[0]["source"]).is_file() and man_text.count(TAG) == 4, str(mine))
ver_text = (ROOT / VER_REL).read_text(encoding="utf-8")
ver = yaml.safe_load(ver_text)
check("the card arrived with dashboard 7.19.0: VERSION.yaml is at 7.19.0 or later and keeps the 7.19.0 note, the dashboard header "
      "keeps its v7.19.0 note; no Home Assistant package mentions the card",
      tuple(int(x) for x in str(ver["current"]["dashboard"]["version"]).split(".")) >= (7, 19, 0)
      and "# v7.19.0 (ACFG1)" in ver_text and "# v7.19.0 (ACFG1" in dash_text.split("views:")[0]
      and not [p.name for p in (ROOT / "home-assistant" / "packages").glob("*.yaml") if TAG in p.read_text(encoding="utf-8")])
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _scope_chain as _sc  # noqa: E402

_e = _sc.CHAIN.entry("acfg1")
_ids = _sc.CHAIN.ids()
check("the acfg1 entry, a post-export entry after esb1, declares the manifest as its one chain-pinned edit, the dashboard, VERSION.yaml "
      "and the two routed suites as its frozen edits, and its scope module as its one added file",
      "esb1" in _ids and _ids.index("acfg1") > _ids.index("esb1") and set(_e.reverts) == set(_e.checkpoints) == {MAN_REL}
      and set(_e.frozen_reverts) == set(_e.frozen_checkpoints) == {DASH_REL, VER_REL, "home-assistant/tests/test_ecco_fallback_packages.py",
                                                                   "registry/tests/test_fallback_recovery_dashboard.py"}
      and _e.added_files == {"registry/tests/_acfg1_scope.py"} and not _e.deltas and not _e.banned_files)
chain_mods = sorted((ROOT / "registry" / "tests").glob("_*.py"))
named = [p.name for p in chain_mods if re.search(r"ecco-advanced-config-card|advanced_config", p.read_text(encoding="utf-8"))]
check("exactly the acfg1 scope module and the chain (its entry) name the card among the scope / chain modules",
      len(chain_mods) > 10 and named == ["_acfg1_scope.py", "_scope_chain.py"], str(named))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Advanced Configuration catalogue checks passed.")
