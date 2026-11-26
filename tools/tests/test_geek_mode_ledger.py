#!/usr/bin/env python3
"""Geek Mode information coverage ledger suite (ECCO Intelligence tab).

  [1] the committed ledger (Markdown and JSON), catalogue, fixtures presence and live comparison all equal a fresh regeneration
      (`tools/geek_mode_coverage.py --check`, run as the instructions say); the ledger is bound to the catalogue, the live shape
      and the fixtures by their sha256
  [2] the ledger is complete and honest: one row per catalogue source and attribute, every row COVERED, every exception justified
      with a reason from the fixed list, the totals add up, the Markdown names every source, exception and finding
  [3] the live comparison: the committed shape lists 16 entities; none is UNDECLARED, none declared is missing; the one entity the
      listing could not check is named; every declared-but-absent attribute is a conditional shape
  [4] the live comparison finds what it should (mutations of a scratch copy of the shape): an UNDECLARED live entity, an UNDECLARED
      live attribute, an UNDECLARED nested key, a declared entity missing live, a declared attribute missing live
  [5] the card-side coverage contract: every ledger row id is `<source id>` or `<source id>#<attribute>`; every declared path is
      exercised by at least one fixture (`seen_in`), so the card's coverage test can run against the same catalogue and fixtures

Test-only, no network. Scratch copies live in the system temp directory and are removed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geek_scratch import ROOT, cleanup, copy_outputs, copy_read_set, run_tool, scratch_dir  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import geek_mode_coverage as G  # noqa: E402

CAT_B = (ROOT / G.CATALOGUE_REL).read_bytes()
cat = json.loads(CAT_B)
LED_B = (ROOT / G.LEDGER_JSON_REL).read_bytes()
led = json.loads(LED_B)
MD = (ROOT / G.LEDGER_MD_REL).read_text(encoding="utf-8")
SHAPE_B = (ROOT / G.SHAPE_REL).read_bytes()
sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731

# ===========================================================================
print("[1] the ledger equals a regeneration and is bound to its inputs")
# ===========================================================================
rc, out = run_tool("geek_mode_coverage.py", "--check")
check("geek_mode_coverage.py --check passes on the committed catalogue, ledger (JSON and Markdown)", rc == 0, out[-400:])
check("the ledger names the catalogue it was built from (sha256)", led["catalogue_sha256"] == sha(CAT_B))
check("the ledger names the live shape it compared with (sha256)", led["live_shape_sha256"] == sha(SHAPE_B))
fx_dir = ROOT / G.FIXTURE_DIR_REL
check("the ledger names the fixtures it checked presence in (sha256 of each file)",
      set(led["fixtures_sha256"]) == set(G.FIXTURE_NAMES)
      and all(led["fixtures_sha256"][n] == sha((fx_dir / f"intelligence.states.{n}.json").read_bytes()) for n in G.FIXTURE_NAMES))
check("the Markdown shows the same hashes", f"`{led['catalogue_sha256']}`" in MD and f"`{led['live_shape_sha256']}`" in MD)
check("Markdown and JSON are plain ASCII with LF line ends", MD.isascii() and "\r" not in MD and LED_B.isascii() and b"\r" not in LED_B)
check("the ledger schema, view and contract", led["schema"] == "ecco-geek-ledger/1" and led["view_id"] == "intelligence" and led["contract"] == cat["contract"])
check("the vocabulary lists the coverage, live, honesty and exception words the card must use",
      led["vocabulary"]["coverage"] == ["COVERED", "EXCEPTION"] and "NOT_MEASURED" in led["vocabulary"]["honesty"]
      and "STALE" in led["vocabulary"]["honesty"] and led["vocabulary"]["exception_reasons"] == list(G.EXCEPTION_REASONS))

# ===========================================================================
print("")
print("[2] complete and honest")
# ===========================================================================
rows = {r["id"]: r for r in led["rows"]}
check("row ids are unique", len(rows) == len(led["rows"]))
expect_ids = set()
for s in cat["sources"]:
    expect_ids.add(s["id"])
    expect_ids.update(f"{s['id']}#{a['name']}" for a in s["attributes"])
check("there is exactly one ledger row per catalogue source and per catalogue attribute (nothing missing, nothing extra)", set(rows) == expect_ids,
      str(sorted(set(rows) ^ expect_ids)[:5]))
check("every row is COVERED (an exception is never an attribute row: it is information that is not a state)", all(r["coverage"] == "COVERED" for r in led["rows"]))
check("every source row names its entity; every attribute row names its entity and path",
      all(r["entity_id"] and (r["path"] is None) == (r["kind"] == "source") for r in led["rows"]))
check("rows carry origin, group, priority, the honesty states they can take and what declared them",
      all(r["origin"] in G.ORIGINS and r["group"] and r["priority"] in G.PRIORITIES and r["honesty"] and r["declared_by"] for r in led["rows"]))
check("only an age-judged source can be STALE; every row can be NOT_MEASURED and UNAVAILABLE or UNKNOWN is a source state",
      all(("STALE" in r["honesty"]) == (r["origin"] == "integration") for r in led["rows"])
      and all("NOT_MEASURED" in r["honesty"] for r in led["rows"]))
check("an attribute whose value the redaction patterns withhold is a row marked WITHHELD (git_sha and config_hash), nothing else is",
      {r["path"] for r in led["rows"] if r["value_policy"] == "withheld"} == {"config_hash", "git_sha"}
      and all(("WITHHELD" in r["honesty"]) == (r["value_policy"] == "withheld") for r in led["rows"] if r["kind"] == "attribute"))
check("the ledger's exceptions are the catalogue's, in the same order", led["exceptions"] == cat["exceptions"])
check("every exception has a reason from the fixed list and a note that justifies it",
      all(e["reason"] in G.EXCEPTION_REASONS and len(e["note"]) >= 40 for e in led["exceptions"]))
check("an exception is never justified by convenience: no note says 'too hard', 'later' or 'not needed'",
      not any(re.search(r"too hard|later|not needed|skip", e["note"], re.I) for e in led["exceptions"]))
t = led["totals"]
check("the totals add up", t["sources"] == len(cat["sources"]) and t["attributes"] == sum(len(s["attributes"]) for s in cat["sources"])
      and t["covered"] == t["sources"] + t["attributes"] and t["exceptions"] == len(cat["exceptions"])
      and sum(t["exceptions_by_reason"].values()) == t["exceptions"])
uni = G.build_universe()
by_status = next(s for s in cat["sources"] if s["entity_id"] == "sensor.ecco_intel_status")["attributes"]
check("the diagnostics download is accounted for section by section: every top-level section of coordinator.diagnostics is an exception or "
      "is covered by status attributes, never both, never neither",
      {e["id"] for e in led["exceptions"] if e["id"].startswith("diag.")} == {f"diag.{k}" for k in uni.diag_sections} - {f"diag.{k}" for k in led["diagnostics_covered"]}
      and set(led["diagnostics_covered"]) <= set(uni.diag_sections))
check("a covered section names status attributes that really have a row (the tool checks the claim; so does this test)",
      all(a in {x["name"] for x in by_status} for attrs in led["diagnostics_covered"].values() for a in attrs)
      and led["diagnostics_covered"]["versions"] == ["integration_version", "engine_version", "git_sha", "config_hash"]
      and "self_test" not in led["diagnostics_covered"] and any(e["id"] == "diag.self_test" and "INFO" in e["note"] for e in led["exceptions"]))
check("the privacy exceptions are the owner's site data (entities, site file, context, location)",
      {e["id"] for e in led["exceptions"] if e["reason"] == "privacy"} >= {"diag.entities", "site_file", "state_context"})
check("the Markdown names every source entity, every exception id and every finding",
      all(f"`{s['entity_id']}`" in MD for s in cat["sources"]) and all(f"`{e['id']}`" in MD for e in cat["exceptions"])
      and all(f in MD for f in led["findings"]))
check("the Markdown has the sections a reviewer expects",
      all(h in MD for h in ("## 1. Summary", "## 2. Findings the owner should see", "## 3. Vocabulary", "## 4. Sources and attributes",
                            "## 5. Live comparison detail", "## 6. Exceptions", "## 7. Dashboard check")))
check("the dashboard check lists 13 entities and none uncovered", len(led["dashboard"]["entities"]) == 13 and led["dashboard"]["uncovered"] == [])

# ===========================================================================
print("")
print("[3] the live comparison")
# ===========================================================================
lv = led["live"]
check("the live comparison is present and was made with the 16 entities of the committed listing", lv is not None and lv["live_entities"] == 16)
check("UNDECLARED: nothing present live is missing from the declarations", lv["undeclared"] == [])
check("NOT_CHECKED_LIVE: only the reserve helper (its name does not match the listing's 'ecco_intel' filter), and the findings say so",
      lv["not_checked_live"] == ["input_number.ecco_advisory_reserve_raise_pct"]
      and any("NOT_CHECKED_LIVE" in f and "ecco_advisory_reserve_raise_pct" in f for f in led["findings"]))
check("NOT_PRESENT_LIVE: no declared entity is absent live", not [r for r in lv["not_present_live"] if r["path"] is None])
absent = [r for r in lv["not_present_live"] if r["path"] is not None]
check("NOT_PRESENT_LIVE attributes: all 42 are conditional shapes (the live item is OK or not, or a null parent), each with its reason",
      len(absent) == 42 and all(r["why"].startswith("conditional:") for r in absent), str([r for r in absent if not r["why"].startswith("conditional:")][:2]))
check("the live rows carry the live type and size of what Home Assistant really holds",
      rows["intel.charge_target#advice"]["live_type"] == "dict[22]" and rows["intel.status#input_ages"]["live_type"] == "list[24]"
      and rows["intel.status#blockers"]["live_bytes"] == 2)
live_total = sum(1 for r in led["rows"] if r["live"] == "PRESENT_LIVE")
check("309 rows are present live, 42 absent live (conditional), 1 not checked; the totals say so",
      live_total == 309 and t["live"] == {"PRESENT_LIVE": 309, "NOT_PRESENT_LIVE": 42, "NOT_CHECKED_LIVE": 1, "UNDECLARED": 0}, str(t["live"]))
check("the status entity's 30 live attributes are 30 present-live rows",
      sum(1 for r in led["rows"] if r["entity_id"] == "sensor.ecco_intel_status" and r["kind"] == "attribute" and "." not in r["path"] and r["live"] == "PRESENT_LIVE") == 30)

# ===========================================================================
print("")
print("[4] the live comparison finds UNDECLARED and NOT_PRESENT_LIVE (mutations of the shape listing)")
# ===========================================================================
u = G.build_universe()
shape = json.loads(SHAPE_B)


def live_with(fn):
    s = copy.deepcopy(shape)
    fn(s)
    return G.compare_live(u, s)


def row(s, eid):
    return next(r for r in s["ecco_intel"] if r["entity_id"] == eid)


r = live_with(lambda s: s["ecco_intel"].append({"entity_id": "sensor.ecco_intel_zz_extra", "state_type": "str", "state_len": 2, "attributes": {}}))
check("an entity present live that no code declares is UNDECLARED", any(x["entity_id"] == "sensor.ecco_intel_zz_extra" and x["path"] is None for x in r["undeclared"]))
r = live_with(lambda s: row(s, "sensor.ecco_intel_status")["attributes"].__setitem__("zz_new_live", {"type": "str", "bytes": 5, "top_keys": None}))
check("an attribute present live that no code declares is UNDECLARED", any(x["path"] == "zz_new_live" for x in r["undeclared"]))
r = live_with(lambda s: row(s, "sensor.ecco_intel_charge_target")["attributes"]["advice"]["top_keys"].append("zz_nested_live"))
check("a first-level key inside a live dict that no code declares is UNDECLARED (as a dotted path)", any(x["path"] == "advice.zz_nested_live" for x in r["undeclared"]))
r = live_with(lambda s: s["ecco_intel"].remove(row(s, "binary_sensor.ecco_intel_watchdog_fresh")))
check("a declared entity absent from the live listing is NOT_PRESENT_LIVE", any(x["entity_id"] == "binary_sensor.ecco_intel_watchdog_fresh" and x["path"] is None for x in r["not_present_live"]))
r = live_with(lambda s: row(s, "sensor.ecco_intel_status")["attributes"].pop("pause_control"))
check("a declared attribute absent from a live entity is NOT_PRESENT_LIVE", any(x["path"] == "pause_control" for x in r["not_present_live"]))
r = live_with(lambda s: s["ecco_intel"].remove(row(s, "automation.ecco_intel_alert_self_test_failed")))
check("a declared automation absent live is NOT_PRESENT_LIVE", any(x["entity_id"] == "automation.ecco_intel_alert_self_test_failed" for x in r["not_present_live"]))
check("an entity the filter does not cover is never reported as missing live", not any(x["entity_id"] == "input_number.ecco_advisory_reserve_raise_pct" for x in r["not_present_live"]))
check("the unmodified shape stays clean (a negative control for the mutations above)", G.compare_live(u, shape)["undeclared"] == [])

so, ss = scratch_dir(), scratch_dir()
try:
    copy_outputs(so)
    bad = copy.deepcopy(shape)
    bad["ecco_intel"].append({"entity_id": "sensor.ecco_intel_zz_extra", "state_type": "str", "state_len": 2, "attributes": {}})
    sp = ss / "shape.json"
    sp.write_text(json.dumps(bad), encoding="utf-8")
    rc, out = run_tool("geek_mode_coverage.py", "--out-root", str(so), "--shape", str(sp))
    md = (so / G.LEDGER_MD_REL).read_text(encoding="utf-8")
    check("the tool, given a shape with an unknown live entity, writes a ledger that says UNDECLARED and names it",
          rc == 0 and "UNDECLARED live: sensor.ecco_intel_zz_extra" in md and "UNDECLARED (present live, declared nowhere)" in md, out[-300:])
    rc, out = run_tool("geek_mode_coverage.py", "--check", "--out-root", str(so), "--shape", str(sp))
    check("the same regenerated ledger then passes --check against that shape, and fails against the committed one",
          rc == 0 and run_tool("geek_mode_coverage.py", "--check", "--out-root", str(so))[0] == 1, out[-200:])
    rc, out = run_tool("geek_mode_coverage.py", "--no-shape", "--out-root", str(so))
    md = (so / G.LEDGER_MD_REL).read_text(encoding="utf-8")
    check("--no-shape leaves the live comparison out and says so", rc == 0 and "Not compared in this build" in md and json.loads((so / G.LEDGER_JSON_REL).read_text())["live"] is None)
    rc, out = run_tool("geek_mode_coverage.py", "--shape", str(ss / "missing.json"), "--out-root", str(so))
    check("a missing --shape file is a usage error (exit 2)", rc == 2, out[-200:])
    # a changed fixture changes the ledger's recorded fixture hash: --check notices
    copy_outputs(so)
    f = so / G.FIXTURE_DIR_REL / "intelligence.states.healthy.json"
    f.write_bytes(f.read_bytes().replace(b'"OK"', b'"BLOCKED"', 1))
    rc, out = run_tool("geek_mode_coverage.py", "--check", "--out-root", str(so))
    check("--check fails when a fixture changed after the ledger was written (the ledger binds to the fixtures)", rc == 1 and "LEDGER" in out.upper(), out[-300:])
finally:
    cleanup(so, ss)

# ===========================================================================
print("")
print("[5] the card-side coverage contract")
# ===========================================================================
check("every attribute row of the ledger is exercised by at least one fixture (seen_in), so no declared path is untestable",
      all(r["seen_in"] for r in led["rows"] if r["kind"] == "attribute"), str([r["id"] for r in led["rows"] if r["kind"] == "attribute" and not r["seen_in"]][:4]))
check("the richest fixture (healthy) carries every attribute the live entities carry (parity with the live shape)",
      all(rows[f"intel.{k}#{n}"]["seen_in"] and "healthy" in rows[f"intel.{k}#{n}"]["seen_in"]
          for k, n in (("status", "tariff"), ("status", "value"), ("status", "plan"), ("charge_target", "engine_comparison"), ("pv_tomorrow", "advice"))))
check("the non-OK advice shape is exercised by the stale, paused and self-test-failed fixtures",
      {"stale", "paused", "self-test-failed"} <= set(rows["intel.charge_target#advice.status"]["seen_in"]))
check("the OK advice keys of the export event are exercised only where the item is OK (healthy, watchdog-stale, extras, contract-breach: the last is the healthy result with one changed attribute)",
      set(rows["intel.export_event#advice.export_kwh"]["seen_in"]) == {"healthy", "watchdog-stale", "extras", "contract-breach"})
check("last_good is exercised by the stale fixture only (history under a null-rule status)", rows["intel.status#last_good.values"]["seen_in"] == ["stale"])
check("a row id is `<source id>` or `<source id>#<attribute name>` (the rule the card's coverage test uses)",
      all(r["id"] == (r["id"].split("#")[0] if r["kind"] == "source" else f"{r['id'].split('#')[0]}#{r['path']}") for r in led["rows"]))

# ===========================================================================
print("")
print("[6] review round 4: a package entity of a kind the tool does not model can no longer pass --check (reviewer mutants P3 and P5)")
# ===========================================================================
PKG_REL = "home-assistant/packages/ecco_intelligence.yaml"
P3_ADD = '\ninput_number:\n  ecco_intel_zz_probe:\n    name: "ECCO Intel zz probe"\n    min: 0\n    max: 1\n'
P5_ADD = '\n  - sensor:\n      - name: "ECCO Intel zz probe"\n        unique_id: "ecco_intel_zz_probe"\n        state: "1"\n\nautomation:\n'
for label, edit, expect in (
        ("P3 an input_number in the presentation package", lambda t: t + P3_ADD, "['input_number']"),
        ("P5 a template sensor 'ECCO Intel zz probe'", lambda t: t.replace("\nautomation:\n", P5_ADD, 1), "the template block key(s) ['sensor']")):
    sd, so = scratch_dir(), scratch_dir()
    try:
        copy_read_set(sd)
        copy_outputs(so)
        f = sd / PKG_REL
        before = f.read_text(encoding="utf-8")
        f.write_text(edit(before), encoding="utf-8", newline="\n")
        check(f"{label}: the mutation changed the scratch package", f.read_text(encoding="utf-8") != before)
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--repo-root", str(sd), "--out-root", str(so))
        check(f"{label}: --check exits 1, names the unmodelled kind, and no longer says the files match a fresh regeneration",
              rc == 1 and expect in out and "match a fresh regeneration" not in out and "FINDING" in out, out[-400:])
        rc, out = run_tool("geek_mode_coverage.py", "--repo-root", str(sd), "--out-root", str(so))
        check(f"{label}: writing the ledger is refused too (exit 1), so no ledger is produced from a package the tool cannot account for", rc == 1 and "FINDING" in out, out[-300:])
        f.write_text(before, encoding="utf-8", newline="\n")
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--repo-root", str(sd), "--out-root", str(so))
        check(f"{label}: with the package restored --check passes again (negative control)", rc == 0 and "match a fresh regeneration" in out, out[-300:])
    finally:
        cleanup(sd, so)

# ===========================================================================
print("")
print("[7] review round 5: an ecco_intel_ entity defined in ANY other Home Assistant YAML file can no longer pass --check (reviewer mutants L05 and L06)")
# ===========================================================================
import shutil  # noqa: E402

HA_PK = "home-assistant/packages/"
L05_REL = HA_PK + "ecco_dump_limits.yaml"
L06_REL = HA_PK + "ecco_zz_probe.yaml"
L05_ADD = "\n# probe\ninput_text:\n  ecco_intel_zz_probe:\n    name: probe\n"
L06_TEXT = "sensor:\n  - platform: template\n    sensors:\n      ecco_intel_zz_probe:\n        value_template: '1'\n"
for label, rel, make, expect in (
        ("L05 an input_text added to ecco_dump_limits.yaml", L05_REL, lambda p: (ROOT / L05_REL).read_text(encoding="utf-8") + L05_ADD, "ecco_dump_limits.yaml: input_text.ecco_intel_zz_probe"),
        ("L06 a new package file ecco_zz_probe.yaml with a legacy template sensor", L06_REL, lambda p: L06_TEXT, "ecco_zz_probe.yaml: sensor[0].sensors.ecco_intel_zz_probe")):
    sd, so = scratch_dir(), scratch_dir()
    try:
        copy_read_set(sd)
        copy_outputs(so)
        f = sd / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(make(f), encoding="utf-8", newline="\n")
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--repo-root", str(sd), "--out-root", str(so))
        check(f"{label}: --check exits 1, names the file and the key, and no longer says the files match a fresh regeneration",
              rc == 1 and expect in out and "match a fresh regeneration" not in out and "FINDING" in out, out[-500:])
        rc, out = run_tool("geek_mode_coverage.py", "--repo-root", str(sd), "--out-root", str(so))
        check(f"{label}: writing the ledger is refused too (exit 1)", rc == 1 and "FINDING" in out and expect in out, out[-300:])
        f.unlink()
        rc, out = run_tool("geek_mode_coverage.py", "--check", "--repo-root", str(sd), "--out-root", str(so))
        check(f"{label}: with the file removed --check passes again (negative control)", rc == 0 and "match a fresh regeneration" in out, out[-300:])
    finally:
        cleanup(sd, so)

# the negative control the other way: a scratch repository that holds EVERY YAML file of the real home-assistant/ tree (the packages, the dashboards, the prototypes) still passes
sd, so = scratch_dir(), scratch_dir()
try:
    copy_read_set(sd)
    copy_outputs(so)
    n = 0
    for p in (ROOT / "home-assistant").rglob("*"):
        if p.is_file() and p.suffix.lower() in (".yaml", ".yml"):
            dest = sd / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            n += 1
    check("the whole real home-assistant/ YAML tree is in the scratch repository (24 files at the time of writing)", n >= 20, str(n))
    rc, out = run_tool("geek_mode_coverage.py", "--check", "--repo-root", str(sd), "--out-root", str(so))
    check("--check passes on a scratch repository that holds every real YAML file: the scan finds nothing in the repository's own files", rc == 0 and "match a fresh regeneration" in out, out[-400:])
finally:
    cleanup(sd, so)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
