#!/usr/bin/env python3
"""The start-up gates and the self-test (runtime/gates.py, runtime/selftest.py, coordinator start-up).

Pure gates (source tree):
  * mode: only the constant SHADOW passes; anything else on the entry refuses setup;
  * ZoneInfo('Europe/London') loads and the 25 h / 23 h days come out right; an unknown zone FAILs (never raises);
  * the site file: missing / not JSON / NaN / not an object / an invalid decisions block / a placeholder in the entity map
    FAIL; P2: the SITE_FILE text says which rule refused the file, value-free and within the 80 published characters:
    'not a JSON object' with the top level's JSON type (an array, a string, null, a number, true or false), 'a non-finite
    number' for NaN, Infinity, -Infinity and a literal beyond the double range (1e999, an integer too large for a double
    or past the digit limit; a huge integer used to raise OverflowError out of the loader), 'not valid JSON' with the
    exception type for a syntax error, a non-UTF-8 byte and a nesting too deep to read (it used to raise RecursionError);
    RR1-5: a file that starts with a UTF-8 byte-order mark FAILs naming the mark, whatever follows it;
    the largest finite double still loads; no decisions block or no entity map WARN; INVALID decisions WARN (they BLOCK in the cycle); the reserve hints
    (non-default values) are ignored (INFO) and SiteConfig keeps its defaults; decisions load only as site_local;
  * a refused site file never echoes its values: an entity id, an unknown key or a record reference from the file appears in
    no check text (only in the debug detail);
  * the vendor manifest: missing / malformed FAIL; a changed file FAILs; the source tree is not a kit;
  * versions are recorded (HA version, HA's Python floor, a feature probe), never a gate.
Through the stand-in Home Assistant (L2):
  * the BUILT kit passes every gate; a tampered kit file -> SELF_TEST_FAILED (VENDOR_MANIFEST) and nothing is computed;
  * mode AUTONOMOUS on the entry -> setup refused (ConfigEntryError), no entity;
  * a missing site file / a broken one / an unwritable state store -> SELF_TEST_FAILED with exactly that reason, no cycle;
    a site file that is not a JSON object and one with a non-finite number each publish their own SITE_FILE text (P2);
  * a site-like entity id or key in a refused site file reaches no entity state or attribute, no recorder row and not the
    diagnostics download;
  * the SOURCE tree under the stand-in -> SELF_TEST_FAILED (VENDOR_MANIFEST: not a built kit).
Plain script; exits 1 on any failure. Temporary directories are created and removed by this suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
NOW = datetime(2030, 1, 15, 20, 30, tzinfo=UTC)
PREFIX = "ecco_intel_selftest_"

# ---------------------------------------------------------------------------------------------------------------------
# pure gates, in a child process on the source tree (this process runs the built kit below)
# ---------------------------------------------------------------------------------------------------------------------
PURE = r'''
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2])
import _harness as H
from custom_components.ecco_intelligence.runtime import gates, selftest, store
from custom_components.ecco_intelligence import const
from intelligence.config import SiteConfig
res = {}
res["mode_ok"] = gates.mode_gate("SHADOW").level
res["mode_entry_ok"] = gates.mode_gate("SHADOW", "SHADOW").level
res["mode_bad"] = [gates.mode_gate(m).level for m in ("AUTONOMOUS", "ASSISTED", "OFF", "shadow", None, 1)]
res["mode_entry_bad"] = gates.mode_gate("SHADOW", "AUTONOMOUS").level
res["const_mode"] = const.MODE
res["tz"] = gates.tz_gate().level
res["tz_bad"] = gates.tz_gate("Not/AZone").level
def lvl(raw, **kw):
    s = gates.load_site(raw, **kw)
    return {c.code: c.level for c in s.checks}, s
good = json.dumps(H.site_profile(decisions=H.owner_decisions())).encode()
c, s = lvl(good, latitude=51.5, longitude=-0.1)
res["good"] = c
res["good_decisions_source"] = s.decisions.source
res["good_recorded"] = sorted(k for k, v in s.decisions.status_map().items() if v == "RECORDED")
res["facts"] = [s.site_facts.pv_array_kwp, s.site_facts.latitude, s.site_facts.tz, s.base_cfg.pv_array_kwp]
res["hint_ignored"] = [s.base_cfg.user_reserve_soc_pct, s.base_cfg.technical_min_soc_pct]
res["hint_defaults"] = [SiteConfig().user_reserve_soc_pct, SiteConfig().technical_min_soc_pct]
res["hint_given"] = [H.site_profile()["site"]["user_reserve_soc_pct"], H.site_profile()["site"]["technical_min_soc_pct"]]
SECRETS = ("sensor.Site_Private_Name_Soc", "sensor.site_private_unknown_key", "I-D77", "REC-20301231-private-note-x",
           "sensor.site_private_source", "site_private_source_name", "Site-Private-Source-Name")
leak = H.site_profile()
leak["shadow_runtime"]["signals"]["battery.soc"] = {"entity": "sensor.Site_Private_Name_Soc"}
leak["decisions"] = {"I-D1": {"status": "RECORDED", "provenance": "OWNER_RECORD", "record_ref": "REC-20301231-private-note-x",
                              "value": {"bogus": 1}}, "I-D77": {}}
leak2 = H.site_profile()
leak2["shadow_runtime"]["signals"]["sensor.site_private_unknown_key"] = {"entity": "sensor.test_a"}
leak2["decisions"] = {"sensor.site_private_source": {}}
leak3 = H.site_profile()
leak3["shadow_runtime"]["pv_forecast_sources"]["tomorrow"] = {"site_private_source_name": "sensor.Site_Private_Name_Soc"}
leak4 = H.site_profile()
leak4["shadow_runtime"]["pv_forecast_sources"]["tomorrow"] = {"Site-Private-Source-Name": "sensor.test_a"}
texts, details = [], []
for prof in (leak, leak2, leak3, leak4):
    sl = gates.load_site(json.dumps(prof).encode())
    texts += [c.text for c in sl.checks]
    details += [d for _code, d in sl.details]
res["leak_codes"] = sorted({c.code for c in gates.load_site(json.dumps(leak).encode()).checks if c.level == "FAIL"})
res["leak_in_texts"] = sorted({x for x in SECRETS if any(x in t for t in texts)})
res["leak_in_details"] = sorted({x for x in SECRETS if any(x in d for d in details)})
res["missing"] = lvl(None, read_problem="missing")[0]
res["not_json"] = lvl(b"{not json")[0]
res["nan"] = lvl(b'{"site": {"pv_array_kwp": NaN}}')[0]
res["array"] = lvl(b"[1, 2]")[0]
def site_file(raw):
    try:
        c = next(c for c in gates.load_site(raw).checks if c.code == "SITE_FILE")
        return [c.level, c.text]
    except Exception as exc:
        return ["RAISED", type(exc).__name__]
P2 = {"object_array": b"[1, 2]", "object_string": b'"site"', "object_null": b"null", "object_number": b"4.5",
      "object_bool": b"true", "object_secret": b'["sensor.site_private_listed"]',
      "finite_nan": b'{"site": {"pv_array_kwp": NaN}}', "finite_inf": b'{"site": {"pv_array_kwp": Infinity}}',
      "finite_neg_inf": b'{"site": {"pv_array_kwp": -Infinity}}',
      "finite_overflow": b'{"site": {"pv_array_kwp": 1e999}}', "finite_overflow_neg": b'{"site": {"pv_array_kwp": -1e999}}',
      "finite_big_int": b'{"site": {"pv_array_kwp": 1' + b"0" * 400 + b"}}",
      "finite_digit_limit": b'{"_pad": 1' + b"0" * 5000 + b"}",
      "finite_secret": b'{"sensor.site_private_key": {"site_private_inner": NaN}}',
      "json_syntax": b"{not json", "json_utf8": b"\xff\xfe{}", "json_deep": b"[" * 200000,
      "bom_object": b'\xef\xbb\xbf{"site": {}}', "bom_secret": b'\xef\xbb\xbf{"sensor.site_private_key": 1}',
      "bom_bad": b"\xef\xbb\xbf{not json",
      "ok_near_max": b'{"site": {"pv_array_kwp": 1e308}}', "ok_big_int": b'{"_pad": 12345678901234567890}'}
res["p2"] = {k: site_file(v) for k, v in P2.items()}
bad_dec = H.site_profile(); bad_dec["decisions"] = {"I-D1": {"status": "OPEN"}, "I-D99": {}}
res["bad_decisions"] = lvl(json.dumps(bad_dec).encode())[0]
inv = H.site_profile(); inv["decisions"] = {"I-D4": {"status": "RECORDED", "provenance": "OWNER_RECORD", "record_ref": "REC-1", "value": {"pct": 8}}}
res["invalid_decision"] = lvl(json.dumps(inv).encode())[0]
ph = H.site_profile(); ph["shadow_runtime"]["signals"]["battery.soc"] = {"entity": "sensor.<slug>_ecco_battery_soc"}
res["placeholder"] = lvl(json.dumps(ph).encode())[0]
nomap = H.site_profile(with_map=False); del nomap["decisions"]
res["nomap"] = lvl(json.dumps(nomap).encode())[0]
ex = (H.REPO / "intelligence" / "profiles" / "site_profile.example.json").read_bytes()
cx, sx = lvl(ex)
res["example"] = cx
res["example_all_open"] = sorted(set(sx.decisions.status_map().values()))
man, want, prob = gates.manifest_paths(store.read_package_manifest())
res["vendor_source"] = gates.vendor_gate(man, want, {}, prob).level
res["vendor_bad_json"] = gates.manifest_paths(b"{")[2] is not None
res["vendor_bad_schema"] = gates.manifest_paths(b'{"schema": "x"}')[2] is not None
m2 = {"schema": gates.MANIFEST_SCHEMA, "modules": [{"output": "_vendor/a.py", "output_sha256": "aa"}], "integration_files": [{"path": "b.py", "output_sha256": "bb"}]}
man2, want2, prob2 = gates.manifest_paths(json.dumps(m2).encode())
res["vendor_match"] = gates.vendor_gate(man2, want2, {"_vendor/a.py": "aa", "b.py": "bb"}, prob2).level
res["vendor_mismatch"] = gates.vendor_gate(man2, want2, {"_vendor/a.py": "aa", "b.py": "cc"}, prob2).level
res["vendor_missing_file"] = gates.vendor_gate(man2, want2, {"_vendor/a.py": "aa"}, prob2).level
v = gates.versions_check("2026.10.4", (3, 13, 2))
res["versions"] = [v.level, "2026.10.4" in v.text, "3.13.2" in v.text]
res["py_floor"] = gates.python_feature_floor()
t = selftest.SelfTest()
t.record("A_CHECK", "PASS").record("B_CHECK", "WARN", "w").record("C_CHECK", "FAIL", "f" * 400)
res["st"] = [t.failed, dict(t.failures()), dict(t.warnings()), t.as_dict()["A_CHECK"]]
try:
    selftest.Check("lower", "PASS"); res["code_case"] = "accepted"
except ValueError:
    res["code_case"] = "refused"
print(json.dumps(res))
'''

env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
p = subprocess.run([sys.executable, "-I", "-B", "-c", PURE, str(REPO), str(TESTS)], capture_output=True, text=True, timeout=300,
                   cwd=str(REPO), env=env)
check("the pure gate checks ran", p.returncode == 0, (p.stdout + p.stderr)[-600:])
r = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {}
print("== mode")
check("the constant SHADOW passes", r.get("mode_ok") == "PASS" and r.get("mode_entry_ok") == "PASS" and r.get("const_mode") == "SHADOW")
check("every other mode FAILs (setup refused)", r.get("mode_bad") == ["FAIL"] * 6 and r.get("mode_entry_bad") == "FAIL")
print("== zone")
check("Europe/London loads and its clock changes are right", r.get("tz") == "PASS")
check("an unknown zone FAILs and does not raise", r.get("tz_bad") == "FAIL")
print("== site file")
g = r.get("good", {})
check("a complete site file passes", all(g.get(k) == "PASS" for k in ("SITE_FILE", "SITE_DECISIONS", "SITE_ENTITY_MAP",
                                                                       "SITE_HISTORY_SOURCES")), str(g))
check("decisions load as site_local (owner records RECORDED)", r.get("good_decisions_source") == "site_local"
      and len(r.get("good_recorded", [])) == 8, str(r.get("good_recorded")))
check("site facts: PV array from the file, location from HA, the zone Europe/London",
      r.get("facts") == [6.0, 51.5, "Europe/London", 6.0], str(r.get("facts")))
check("the test profile's reserve hints are not the SiteConfig defaults (so 'ignored' is observable)",
      r.get("hint_given") is not None and r.get("hint_defaults") is not None
      and all(float(a) != float(b) for a, b in zip(r["hint_given"], r["hint_defaults"])),
      f"{r.get('hint_given')} {r.get('hint_defaults')}")
check("the reserve hints are ignored (INFO) and never reach SiteConfig (it keeps its defaults)",
      g.get("SITE_HINT_IGNORED_USER_RESERVE_SOC_PCT") == "INFO" and g.get("SITE_HINT_IGNORED_TECHNICAL_MIN_SOC_PCT") == "INFO"
      and r.get("hint_ignored") is not None and r.get("hint_ignored") == r.get("hint_defaults"),
      f"{r.get('hint_ignored')} {r.get('hint_defaults')}")
check("missing site file -> FAIL", r.get("missing", {}).get("SITE_FILE") == "FAIL")
check("not JSON -> FAIL", r.get("not_json", {}).get("SITE_FILE") == "FAIL")
check("NaN in the file -> FAIL", r.get("nan", {}).get("SITE_FILE") == "FAIL")
check("a JSON array -> FAIL", r.get("array", {}).get("SITE_FILE") == "FAIL")
p2 = r.get("p2", {})
NOT_OBJ, NON_FIN = "is JSON but not a JSON object", "holds a non-finite number (NaN, Infinity or out of range)"
_kinds = {"object_array": "an array", "object_string": "a string", "object_null": "null", "object_number": "a number",
          "object_bool": "true or false", "object_secret": "an array"}
_obj_bad = {k: v for k, v in p2.items() if k.startswith("object_") and not (
    v[0] == "FAIL" and NOT_OBJ in v[1] and v[1].endswith(f"(its top level is {_kinds[k]})") and NON_FIN not in v[1])}
check("P2: valid JSON whose top level is not an object FAILs SITE_FILE naming 'not a JSON object' and its JSON type "
      "(an array, a string, null, a number, true or false), never 'not valid JSON' or 'non-finite'",
      len([k for k in p2 if k.startswith("object_")]) == 6 and not _obj_bad
      and not any("not valid JSON" in v[1] for k, v in p2.items() if k.startswith("object_")), str(_obj_bad))
_fin_bad = {k: v for k, v in p2.items() if k.startswith("finite_") and not (
    v[0] == "FAIL" and v[1] == "the site file " + NON_FIN)}
check("P2: NaN, Infinity, -Infinity and a literal beyond the double range (1e999, -1e999, an integer too large for a "
      "double, an integer past Python's digit limit) FAIL SITE_FILE as 'a non-finite number', never 'not a JSON object' "
      "and never an exception (a huge integer used to raise OverflowError out of the loader)",
      len([k for k in p2 if k.startswith("finite_")]) == 8 and not _fin_bad, str(_fin_bad))
_json_bad = {k: v for k, v in p2.items() if k.startswith("json_") and not (
    v[0] == "FAIL" and v[1] == "the site file is not valid JSON: " + {"json_syntax": "JSONDecodeError",
                                                                      "json_utf8": "UnicodeDecodeError",
                                                                      "json_deep": "RecursionError"}[k])}
check("P2: a JSON syntax error, a non-UTF-8 byte and a nesting too deep to read FAIL SITE_FILE as 'not valid JSON' with "
      "the exception type only (the deep nesting used to escape the loader as RecursionError)", not _json_bad,
      str(_json_bad))
_bom_bad = {k: v for k, v in p2.items() if k.startswith("bom_") and v != [
    "FAIL", "the site file starts with a UTF-8 byte-order mark (save it without one)"]}
check("RR1-5: a site file that starts with a UTF-8 byte-order mark (what Windows PowerShell 5.1 writes for -Encoding "
      "utf8) FAILs SITE_FILE naming the mark, never 'not valid JSON: JSONDecodeError', whatever follows it (a JSON "
      "object, a site key, broken JSON)", len([k for k in p2 if k.startswith("bom_")]) == 3 and not _bom_bad,
      str(_bom_bad))
check("P2: the largest finite double and an integer a double holds still load (PASS)",
      p2.get("ok_near_max") == ["PASS", "the site file is a JSON object"]
      and p2.get("ok_big_int") == ["PASS", "the site file is a JSON object"], f"{p2.get('ok_near_max')} {p2.get('ok_big_int')}")
check("P2: every SITE_FILE text is value-free (no key, entity id or number from the file) and fits the 80 characters "
      "the status entity publishes",
      p2 and all(len(v[1]) <= 80 and "site_private" not in v[1] and "1e999" not in v[1] and "NaN" not in v[1].replace(
          "(NaN, Infinity or out of range)", "") for v in p2.values()), str({k: v for k, v in p2.items() if len(v[1]) > 80}))
check("an unknown decision key -> FAIL", r.get("bad_decisions", {}).get("SITE_DECISIONS") == "FAIL")
check("an INVALID decision (bad record_ref) -> WARN (it BLOCKs in the cycle)",
      r.get("invalid_decision", {}).get("SITE_DECISIONS") == "WARN")
check("a placeholder entity id in shadow_runtime -> FAIL", r.get("placeholder", {}).get("SITE_ENTITY_MAP") == "FAIL")
check("a site file with a bad entity id and a bad decisions block -> both FAIL",
      r.get("leak_codes") == ["SITE_DECISIONS", "SITE_ENTITY_MAP"], str(r.get("leak_codes")))
check("no check text echoes a value from the site file (entity id, unknown key, record reference, source name)",
      r.get("leak_in_texts") == [], str(r.get("leak_in_texts")))
check("... the offending values are kept in the debug details (for the owner's debug log only)",
      set(r.get("leak_in_details", [])) >= {"sensor.Site_Private_Name_Soc", "sensor.site_private_unknown_key",
                                            "sensor.site_private_source", "Site-Private-Source-Name"},
      str(r.get("leak_in_details")))
check("no decisions block / no entity map -> WARN", r.get("nomap", {}).get("SITE_DECISIONS") == "WARN"
      and r.get("nomap", {}).get("SITE_ENTITY_MAP") == "WARN")
check("the example profile as a site file: loads, every decision OPEN, no entity map (WARN), placeholders never queried",
      r.get("example", {}).get("SITE_FILE") == "PASS" and r.get("example_all_open") == ["OPEN"]
      and r.get("example", {}).get("SITE_ENTITY_MAP") == "WARN" and r.get("example", {}).get("SITE_HISTORY_SOURCES") == "WARN")
print("== vendor manifest")
check("the source tree is not a kit -> FAIL", r.get("vendor_source") == "FAIL")
check("malformed / unknown-schema manifests are refused", r.get("vendor_bad_json") and r.get("vendor_bad_schema"))
check("matching hashes PASS; a changed or missing file FAILs", r.get("vendor_match") == "PASS"
      and r.get("vendor_mismatch") == "FAIL" and r.get("vendor_missing_file") == "FAIL")
print("== versions and the record")
check("versions are recorded as INFO (HA version and HA's Python floor)", r.get("versions") == ["INFO", True, True])
check("the Python feature probe answers", r.get("py_floor") in (">=3.14", "3.13", "<3.13"))
st = r.get("st", [None, {}, {}, None])
check("SelfTest: FAIL makes it failed; failures / warnings / PASS rendering; long texts are cut",
      st[0] is True and list(st[1]) == ["C_CHECK"] and len(st[1]["C_CHECK"]) == 160 and st[2] == {"B_CHECK": "w"}
      and st[3] == "PASS")
check("a check code must be upper case", r.get("code_case") == "refused")

# ---------------------------------------------------------------------------------------------------------------------
# L2: the built kit (and a tampered copy) under the stand-in
# ---------------------------------------------------------------------------------------------------------------------
root = H.mktemp(PREFIX)
try:
    kit = root / "kit"
    b = H.build_kit(kit)
    check("the kit builds", b.returncode == 0, b.stderr[-300:])
    h = H.Harness(kit)

    def scenario(name: str, profile, *, data=None, prepare=None):
        cfg = root / name
        cfg.mkdir()
        hass = h.new_hass(cfg, NOW)
        H.write_site(cfg, profile)
        if prepare is not None:
            prepare(cfg)
        H.seed_fresh_states(hass.states, NOW)
        h.recorder().statistics = H.synthetic_statistics(NOW, days=10)
        entry = h.new_entry(data)
        return hass, entry

    print("== L2: the built kit passes every gate")
    hass, entry = scenario("good", H.site_profile())
    h.setup(entry)
    c = h.coordinator(entry)
    fails = {k: v for k, v in c.selftest.as_dict().items() if v.startswith("FAIL")}
    check("no FAIL in the built kit's self-test", not fails, str(fails))
    check("VENDOR_MANIFEST passes on the built kit", c.selftest.get("VENDOR_MANIFEST").level == "PASS")
    check("versions carry the build's git sha and the site file hash", c.versions.git_sha == "0000000"
          and isinstance(c.versions.config_hash, str) and len(c.versions.config_hash) == 16)
    check("the status starts at STARTING", h.state("status").state == "STARTING")
    h.unload(entry)

    print("== L2: mode refused")
    hass, entry = scenario("mode", H.site_profile(), data={"mode": "AUTONOMOUS"})
    try:
        h.setup(entry)
        check("mode AUTONOMOUS refuses setup", False, "set up")
    except h.mods["homeassistant.exceptions"].ConfigEntryError:
        check("mode AUTONOMOUS refuses setup (ConfigEntryError)", True)
    check("... and no entity exists", not any(e.startswith(("sensor.ecco_intel", "binary_sensor.ecco_intel"))
                                              for e in hass.states._states))

    def failed_case(name, profile, code, prepare=None, secret=None, expect_text=None):
        hass, entry = scenario(name, profile, prepare=prepare)
        h.setup(entry)
        c = h.coordinator(entry)
        c.grace_s = 0
        for _ in range(3):
            h.tick(60)
        st = h.state("status")
        check(f"{name}: SELF_TEST_FAILED naming {code}", st is not None and st.state == "SELF_TEST_FAILED"
              and code in (st.attributes.get("self_test") or {}), f"{st and st.state} {st and st.attributes.get('self_test')}")
        if expect_text is not None:
            shown = (st.attributes.get("self_test") or {}).get(code, "") if st is not None else ""
            check(f"{name}: the published text (cut at 80 characters) still names {expect_text!r}", expect_text in shown,
                  shown)
        fails = {k for k, v in c.selftest.as_dict().items() if v.startswith("FAIL")}
        check(f"{name}: the only failed check is {code} (no leftover failure from another scenario)", fails == {code},
              str(sorted(fails)))
        if secret is not None:
            diag = h.run(diag_mod.async_get_config_entry_diagnostics(hass, entry))
            hits = H.text_anywhere(hass, secret, diag)
            check(f"{name}: the site value appears in no state, attribute, recorder row or diagnostics download", not hits,
                  str(hits))
        check(f"{name}: nothing was computed", c.counters["runs_started"] == 0, str(c.counters))
        numeric = [k for k in ("charge_target", "pv_tomorrow", "predicted_day_load") if H.numeric_state(h.state(k))]
        check(f"{name}: every item state unknown", not numeric)
        check(f"{name}: no write attempt", not hass.write_attempts, str(hass.write_attempts))
        h.unload(entry)

    diag_mod = __import__("importlib").import_module("custom_components.ecco_intelligence.diagnostics")
    print("== L2: failed gates publish SELF_TEST_FAILED")
    failed_case("no_site_file", None, "SITE_FILE")

    def raw_site(raw: bytes):
        def put(cfg: Path) -> None:
            (cfg / "ecco" / "intelligence" / "site.local.json").write_bytes(raw)
        return put
    failed_case("site_file_not_object", None, "SITE_FILE", prepare=raw_site(b'["sensor.site_private_listed"]\n'),
                secret="site_private_listed", expect_text="is JSON but not a JSON object (its top level is an array)")
    failed_case("site_file_non_finite", None, "SITE_FILE",
                prepare=raw_site(b'{"site": {"pv_array_kwp": 1e999}, "sensor.site_private_key": NaN}\n'),
                secret="site_private_key", expect_text="holds a non-finite number (NaN, Infinity or out of range)")
    broken = H.site_profile()
    broken["decisions"] = {"I-D42": {}}
    failed_case("bad_decisions", broken, "SITE_DECISIONS")
    ph = H.site_profile()
    ph["shadow_runtime"]["readings"]["battery.soc_raw_pct"] = {"entity": "sensor.<slug>_battery_soc"}
    failed_case("placeholder_map", ph, "SITE_ENTITY_MAP")
    site_like = H.site_profile()
    site_like["shadow_runtime"]["signals"]["battery.soc"] = {"entity": "sensor.Site_Private_Name_Soc"}
    failed_case("site_value_in_map", site_like, "SITE_ENTITY_MAP", secret="Site_Private_Name_Soc",
                expect_text="shadow_runtime.signals.battery.soc: not a valid entity id")
    bad_key = H.site_profile()
    bad_key["shadow_runtime"]["readings"]["sensor.site_private_reading_key"] = {"entity": "sensor.test_a"}
    failed_case("site_key_in_map", bad_key, "SITE_ENTITY_MAP", secret="site_private_reading_key")
    bad_dec_key = H.site_profile()
    bad_dec_key["decisions"] = {"sensor.site_private_decision_key": {}}
    failed_case("site_key_in_decisions", bad_dec_key, "SITE_DECISIONS", secret="site_private_decision_key")

    def block_state(cfg: Path) -> None:
        (cfg / "ecco" / "intelligence" / "state").write_text("a file where state/ belongs\n", encoding="utf-8")
    failed_case("unwritable_store", H.site_profile(), "STORE_WRITABLE", prepare=block_state)

    print("== L2: a tampered kit fails its self-test")
    vfile = kit / "custom_components" / "ecco_intelligence" / "_vendor" / "intelligence" / "quality.py"
    original = vfile.read_bytes()
    vfile.write_bytes(original + b"\n# tampered\n")
    try:
        failed_case("tampered_kit", H.site_profile(), "VENDOR_MANIFEST")
    finally:
        vfile.write_bytes(original)

    print("== the SOURCE tree under the stand-in is not installable (child process)")
    SRC = r'''
import asyncio, json, sys
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2])
import _fake_ha, _harness as H
_fake_ha.install()
import custom_components.ecco_intelligence as integ
loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
_fake_ha.CLOCK.now = datetime(2030, 1, 15, 20, 30, tzinfo=timezone.utc)
hass = _fake_ha.HomeAssistant(loop, sys.argv[3])
H.write_site(H.Path(sys.argv[3]), H.site_profile())
entry = _fake_ha.ConfigEntry("ecco_intelligence", {})
hass.config_entries._add(entry)
loop.run_until_complete(integ.async_setup_entry(hass, entry))
st = hass.states._states["sensor.ecco_intel_status"]
print(json.dumps({"state": st.state, "self_test": dict(st.attributes.get("self_test") or {}), "writes": hass.write_attempts}))
loop.run_until_complete(integ.async_unload_entry(hass, entry))
'''
    srcdir = root / "source_cfg"
    srcdir.mkdir()
    p2 = subprocess.run([sys.executable, "-I", "-B", "-c", SRC, str(REPO), str(TESTS), str(srcdir)], capture_output=True,
                        text=True, timeout=300, cwd=str(REPO), env=env)
    out = json.loads(p2.stdout.strip().splitlines()[-1]) if p2.returncode == 0 and p2.stdout.strip() else {}
    check("the source tree publishes SELF_TEST_FAILED (VENDOR_MANIFEST: not a built kit)",
          out.get("state") == "SELF_TEST_FAILED" and "VENDOR_MANIFEST" in out.get("self_test", {}), (p2.stdout + p2.stderr)[-400:])
    check("... with no write attempt", out.get("writes") == [])
finally:
    H.rmtree_own(root, PREFIX)


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime self-test:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime self-test checks passed")
