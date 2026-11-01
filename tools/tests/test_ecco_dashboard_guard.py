#!/usr/bin/env python3
"""Regression suite: tools/ecco_dashboard_guard.py, the fail-closed dashboard preservation gate, and its wiring into the deploy tools.

  [1] helpers: the canonical hash is the documented formula, key order does not matter, an int and a float differ, Home Assistant
      tags (!include, !secret, !input) parse as opaque, stable, distinct values and are never resolved; RFC 6901 pointers (escapes
      decoded ~1 before ~0, list indices, a format / parse round trip over keys with / and ~); emit_scalar's read-back check
  [2] check: every rule positively and negatively. The generic render over a privately overridden live file is BLOCKED (R2 and R4);
      live itself passes; a live file that drifted from the policy, a protected pointer missing in the candidate or in live, a
      missing required resource or resource list (R3) and a dropped custom card type (R4, nested too) block; --allow-drift-recovery
      passes a drifted live file only for a candidate that carries the policy's layer exactly (WARNING lines), never a candidate
      without it, and waives nothing else; --accept-removed-type
      waives R4 for the named type only, never another dropped type, R2 or R3, and takes only a strict custom:<name>; a policy
      without an entry for the destination is the generic layer under the default gate; a policy whose destination differs only
      in letter case is refused; a character YAML does not allow is a parse refusal, not an internal error
  [3] refused inputs (exit 2, first line still BLOCKED, never 0): malformed / unknown-schema / duplicate-destination / bad-pointer /
      bad-sha256 / empty / unknown-key / out-of-scope-overlay / non-scalar-overlay / duplicate-key / NaN policies; unparseable,
      non-mapping, multi-document, non-UTF-8 and missing YAML; a python object tag; usage errors (no -h, no abbreviations, never
      an argument value echoed); PyYAML missing (python -S)
  [4] apply: apply(base) passes, parses to live and passes check; only the overlay lines change; apply(live) is byte-identical;
      CRLF and a missing final line break are kept; the result does not depend on the order of the overlay operations; every
      refusal case (missing parent, flow mapping, sequence parent, anchor, alias, merge key, non-scalar target, tagged target,
      block scalar, post-condition, existing --out, no entry) writes nothing; the post-condition refuses a change outside the
      protected subtree
  [5] make-policy: three overlay operations from a fictional base / live pair, the protect hash of live; refuses a difference outside
      the pointer (pointers printed, never values), a removed key, a non-scalar difference, a difference in a sequence; a round
      trip over keys containing / and ~
  [6] verify-live and classify (exit 4 for "not a dashboard", never Python's crash code 1; the policy's destinations listed)
  [7] privacy: no overlay value (a fictional secret-looking value among them), no card type name and no hash of one appears in any
      stdout, stderr or --json report, not even when the YAML error is on its line or the value is a stray argument
  [8] static: the guard imports no network or subprocess module and writes only through its two writers; deploy-ha.ps1 runs the gate
      as a bare top-level statement before its first remote write, checks the gate pin right after it (read before the host is
      contacted), passes -AllowDriftRecovery, ties the uploaded bytes to the checked bytes, and runs verify-live after the
      post-install hash (rolling back on failure); the rollback restores with a plain cp and touch (never cp -p) and asks for a
      lovelace/config read-back for a dashboard; the pin file is git-ignored; EccoDeploy.psm1 refuses /config/ecco/site-local/ destinations, throws
      on every guard answer but PASS under the expected gate, refuses arguments the 5.1 command line would split, probes symlinks
      and unsearchable folders as unreadable; no PowerShell 7-only operators; the example policy is valid and fictional; the docs
      describe the gate, the plan --out location and the owner procedures

Fictional data only. Test-only, no network. I/O: reads repo files, writes only under a temp dir, runs the guard with `python -S` once.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ecco_dashboard_guard as G  # noqa: E402

FAILURES: list[str] = []
OUTPUTS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


TMP = Path(tempfile.mkdtemp(prefix="ecco-guard-suite-"))   # not the gate's own ecco-dashboard-* temp prefix
DEST = "/config/ecco/dashboards/ecco_pro.yaml"
PTR = "/views/0/sections/1/cards/0"
GATE = "EXAMPLE_PRESERVE_GATE"
SECRET = "zz-SECRET-VALUE-7f3a"                                    # fictional, secret-looking: must never be printed
SITE_TYPE = "custom:example-site-card"
SITE_PACK = "media-source://media_source/local/example/scene"
OVERLAY_VALUES = (SECRET, SITE_TYPE, SITE_PACK)
RES_URL = "/local/example/example-site-card.js"

BASE = """\
# Fictional generic dashboard for the preservation-gate suite
title: Example
button_card_templates: !include example_templates.yaml
views:
  - title: Overview
    path: overview
    sections:
      - type: grid
        cards:
          - type: custom:example-status-card
            entity: sensor.example_status
          - !include example_extra_card.yaml
      - type: grid
        cards:
          - type: custom:example-flow-card
            title: Energy Flow
            scene:
              pack: /local/example/scenes/
              crossfade_ms: 900
            nodes:
              home: sensor.example_home_power
            tags:
              - first
          - type: vertical-stack
            cards:
              - type: custom:example-nested-card
                password: !secret example_secret
"""
LIVE = (BASE.replace("          - type: custom:example-flow-card\n",
                     "          # site override (fictional)\n          - type: custom:example-site-card\n")
        .replace("              pack: /local/example/scenes/\n", f"              pack: {SITE_PACK}\n")
        .replace("              crossfade_ms: 900\n", f"              crossfade_ms: 900\n              variant: {SECRET}\n"))
assert LIVE.count(SECRET) == 1 and LIVE.count(SITE_TYPE) == 1 and LIVE.count(SITE_PACK) == 1


def w(name: str, text: str | bytes) -> str:
    p = TMP / name
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_bytes(text.encode("utf-8"))
    return str(p)


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = G.main(argv)
        except SystemExit as ex:
            code = int(ex.code or 0)
    out = buf.getvalue()
    OUTPUTS.append(out)
    return code, out


def first(out: str) -> str:
    return out.splitlines()[0] if out.strip() else ""


def load(text: str):
    return G.parse_yaml(text, "fixture")


def policy_obj(live_text: str = LIVE, overlay=None, require=None, dest: str = DEST, ptr: str = PTR, gate: str = GATE) -> dict:
    live = load(live_text)
    entry = {"destination": dest, "protect": [{"pointer": ptr, "sha256": G.canon_hash(G.resolve(live, G.parse_pointer(ptr, "t")))}],
             "overlay": overlay if overlay is not None else [
                 {"pointer": PTR + "/type", "value": SITE_TYPE}, {"pointer": PTR + "/scene/pack", "value": SITE_PACK},
                 {"pointer": PTR + "/scene/variant", "value": SECRET}]}
    if require is not None:
        entry["require_resources"] = [{"url": u} for u in require]
    return {"schema": G.SCHEMA, "gate": gate, "dashboards": [entry]}


def wpolicy(name: str, obj) -> str:
    return w(name, obj if isinstance(obj, str) else json.dumps(obj, indent=2))


def resources(*urls: str) -> dict:
    return {"version": 1, "key": "lovelace_resources", "data": {"items": [{"id": str(i), "type": "module", "url": u} for i, u in enumerate(urls)]}}


base_f, live_f = w("base.yaml", BASE), w("live.yaml", LIVE)
pol_f = wpolicy("policy.json", policy_obj())
pol_res_f = wpolicy("policy-res.json", policy_obj(require=[RES_URL]))
res_ok_f = w("res-ok.json", json.dumps(resources("/hacsfiles/button-card/button-card.js", RES_URL)))
res_missing_f = w("res-missing.json", json.dumps(resources("/hacsfiles/button-card/button-card.js")))


def chk(candidate: str, *extra: str, live: str = live_f) -> tuple[int, str]:
    return run(["check", "--destination", DEST, "--live", live, "--candidate", candidate, *extra])


try:
    # ==========================================================================================================================
    print("[1] helpers: canonical hash, opaque tags, pointers")
    sub = {"b": [1, 2.5, True, None, "x"], "a": {"z": "\u00e9", "y": 0}}
    check("the canonical hash is sha256 of json.dumps(sort_keys, compact separators, ensure_ascii=False) for plain data",
          G.canon_hash(sub) == hashlib.sha256(json.dumps(sub, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
    check("key order does not change the hash; a value change does",
          G.canon_hash({"a": 1, "b": 2}) == G.canon_hash({"b": 2, "a": 1}) != G.canon_hash({"a": 1, "b": 3}))
    t1, t2 = load("a: !include x.yaml\nb: !secret s\nc: !input i\n"), load("a: !include x.yaml\nb: !secret s\nc: !input i\n")
    check("!include, !secret and !input parse as opaque tagged values (never resolved: x.yaml does not exist) with a stable hash",
          isinstance(t1["a"], G.Tagged) and t1["a"].tag == "!include" and t1["a"].value == "x.yaml" and t1["b"].tag == "!secret"
          and t1["c"].tag == "!input" and G.canon_hash(t1) == G.canon_hash(t2))
    check("tagged values hash differently from each other and from the plain string",
          len({G.canon_hash(load(s)) for s in ("a: !include x\n", "a: !secret x\n", "a: x\n", "a: !include y\n")}) == 4)
    check("a tagged mapping and sequence parse too (deep)",
          G.canon_hash(load("a: !include_dir_named {k: [1, 2]}\n")) == G.canon_hash(load("a: !include_dir_named {k: [1, 2]}\n")))
    check("RFC 6901: ~1 is /, ~0 is ~, the empty pointer is the document, a pointer must start with /",
          G.parse_pointer("/a~1b/~0c/0", "t") == ["a/b", "~c", "0"] and G.parse_pointer("", "t") == [])
    bad = []
    for p in ("a/b", "/a~2", "/a~", "/a\nb"):
        try:
            G.parse_pointer(p, "t")
            bad.append(p)
        except G.GuardError:
            pass
    check("invalid pointers are refused (no leading /, a bad ~ escape, a control character)", not bad, str(bad))
    check("an int and a float of the same value hash differently (1 is not 1.0)",
          G.canon_hash(load("a: 1\n")) != G.canon_hash(load("a: 1.0\n")) and G.canon_hash(1) != G.canon_hash(1.0))
    check("RFC 6901 decodes ~1 before ~0: /~01 is the key ~1, never /", G.parse_pointer("/~01", "t") == ["~1"])
    keys = ["a/b", "~", "~1", "x~0y", "/", "\u00e9/\u00fc~", "0"]
    def round_trip(tokens) -> bool:
        try:
            return G.parse_pointer(G.fmt_pointer(tokens), "t") == tokens
        except G.GuardError:   # an unescaped ~ is refused as a bad escape: the round trip failed
            return False

    check("fmt_pointer escapes ~ and / so that parse_pointer gives the keys back (keys with /, ~, ~1, ~0 and non-ASCII)",
          round_trip(keys) and G.fmt_pointer(["~1"]) == "/~01" and G.fmt_pointer(["a/b"]) == "/a~1b")
    real_emit_str = G.emit_str
    try:
        G.emit_str = lambda _s: "yes"   # a simulated emitter fault: plain `yes` reads back as a boolean
        try:
            G.emit_scalar("x")
            readback = False
        except G.Refusal:
            readback = True
    finally:
        G.emit_str = real_emit_str
    check("emit_scalar refuses a value whose YAML text does not read back identically (simulated emitter fault)", readback)
    doc = load("l: [a, b]\nm: {k: v}\n")
    check("list indices are decimal integers without leading zeros; a missing step is missing, never an error",
          G.resolve(doc, ["l", "1"]) == "b" and G.resolve(doc, ["l", "01"]) is G._MISSING and G.resolve(doc, ["l", "2"]) is G._MISSING
          and G.resolve(doc, ["m", "k", "x"]) is G._MISSING and G.resolve(doc, ["l", "-"]) is G._MISSING)

    # ==========================================================================================================================
    print("")
    print("[2] check: every rule, positively and negatively")
    code, out = chk(base_f, "--policy", pol_f)
    check("the generic repository render over the privately overridden live file is BLOCKED by R2 (candidate) and R4, exit 3",
          code == 3 and first(out) == f"{GATE}: BLOCKED" and "BLOCKED R2: candidate removes or replaces a protected layer: " + PTR in out
          and "BLOCKED R4: the candidate drops a custom card type" in out, out)
    check("... while live itself still matches the policy (R2 live ok)", f"ok R2: live matches the site policy at {PTR}" in out, out)
    code, out = chk(live_f, "--policy", pol_f)
    check("live itself as the candidate passes under the policy gate, exit 0", code == 0 and first(out) == f"{GATE}: PASS"
          and "BLOCKED" not in out, out)
    code, out = chk(base_f)
    check("no policy: the same generic render is BLOCKED by the generic layer alone (R4) under the default gate",
          code == 3 and first(out) == "DASHBOARD_PRESERVE_GATE: BLOCKED" and "R4" in out and "R2" not in out, out)
    code, out = chk(live_f)
    check("no policy: live as the candidate passes", code == 0 and first(out) == "DASHBOARD_PRESERVE_GATE: PASS", out)
    other_f = wpolicy("policy-other.json", policy_obj(dest="/config/ecco/dashboards/other.yaml"))
    code, out = chk(base_f, "--policy", other_f)
    check("a policy without an entry for the destination: generic layer only, default gate, still BLOCKED by R4",
          code == 3 and first(out) == "DASHBOARD_PRESERVE_GATE: BLOCKED" and "R2" not in out and "without an entry" in out, out)
    drift_f = w("live-drift.yaml", LIVE.replace("crossfade_ms: 900", "crossfade_ms: 1200"))
    nocard = BASE.split("      - type: grid\n        cards:\n          - type: custom:example-flow-card")[0]
    nocard_f = w("cand-nocard.yaml", nocard)
    code, out = chk(drift_f, "--policy", pol_f, live=drift_f)
    check("live changed against the policy is BLOCKED ('live protected layer differs from the site policy'), even with candidate = live",
          code == 3 and "BLOCKED R2: live protected layer differs from the site policy: " + PTR in out, out)
    code, out = chk(live_f, "--policy", pol_f, live=drift_f)
    check("drift without --allow-drift-recovery: a candidate that restores the policy's layer exactly is still BLOCKED (live may hold newer "
          "site values), with an info line naming the option", code == 3 and "BLOCKED R2: live protected layer differs from the site policy: "
          + PTR in out and "BLOCKED R2: candidate" not in out and "--allow-drift-recovery (deploy-ha.ps1 -AllowDriftRecovery) restores it" in out, out)
    code, out = chk(live_f, "--policy", pol_f, "--allow-drift-recovery", live=drift_f)
    lines = out.splitlines()
    check("drift recovery: with --allow-drift-recovery that candidate passes (exit 0) under the policy gate, the drift a loud WARNING "
          "right after the PASS line (the drifted pointer and both hashes), never an ok line for live",
          code == 0 and first(out) == f"{GATE}: PASS" and "BLOCKED" not in out and len(lines) > 2
          and lines[1].startswith(f"  WARNING R2 drift: live protected layer differs from the site policy: {PTR} (policy ")
          and lines[2].startswith("  WARNING drift recovery: 1 drifted protected pointer(s)")
          and f"ok R2: candidate keeps the protected layer at {PTR}" in out and "ok R2: live matches" not in out, out)
    code, out = chk(drift_f, "--policy", pol_f, "--allow-drift-recovery", live=drift_f)
    check("drift recovery never passes a candidate without the protected layer: the drifted live file itself is BLOCKED (live and "
          "candidate R2), with no WARNING", code == 3 and "BLOCKED R2: live protected layer differs" in out
          and "BLOCKED R2: candidate removes or replaces a protected layer" in out and "WARNING" not in out, out)
    code, out = chk(base_f, "--policy", pol_f, "--allow-drift-recovery", "--accept-removed-type", SITE_TYPE, live=drift_f)
    check("... nor the generic render, with every waiver given", code == 3 and "BLOCKED R2: candidate removes" in out, out)
    code, out = chk(live_f, "--policy", pol_f, "--allow-drift-recovery", live=nocard_f)
    check("drift recovery: a live file that lost the protected subtree is restored by a candidate that carries it (PASS, WARNING)",
          code == 0 and f"WARNING R2 drift: live protected layer differs from the site policy: {PTR} is missing in live" in out, out)
    code, out = chk(live_f, "--policy", pol_f, "--allow-drift-recovery", live=base_f)
    code2, out2 = chk(live_f, "--policy", pol_f, "--allow-drift-recovery", "--accept-removed-type", "custom:example-flow-card", live=base_f)
    check("drift recovery waives nothing else: a live file that fell back to the generic card still needs --accept-removed-type for the "
          "generic type the candidate drops (R4 BLOCKED), then passes", code == 3 and "BLOCKED R4" in out and "WARNING R2 drift" in out
          and "BLOCKED R2" not in out and code2 == 0 and "WARNING drift recovery" in out2, out + out2)
    code, out = chk(live_f, "--policy", pol_res_f, "--resources", res_missing_f, "--allow-drift-recovery", live=drift_f)
    check("drift recovery never waives R3", code == 3 and "BLOCKED R3" in out, out)
    code, out = chk(live_f, "--policy", pol_f, "--allow-drift-recovery")
    check("--allow-drift-recovery without drift changes nothing: PASS, 'nothing to recover', no WARNING",
          code == 0 and "live matches the site policy (nothing to recover)" in out and "WARNING" not in out, out)
    code, out = chk(base_f, "--allow-drift-recovery")
    check("--allow-drift-recovery without a site policy waives nothing: the generic render is still BLOCKED by R4",
          code == 3 and "BLOCKED R4" in out and "no site policy entry for this destination (nothing to recover)" in out, out)
    drift_rep = TMP / "report-drift.json"
    code, out = chk(live_f, "--policy", pol_f, "--allow-drift-recovery", "--json", str(drift_rep), live=drift_f)
    drift_data = json.loads(drift_rep.read_text(encoding="utf-8")) if drift_rep.exists() else {}
    OUTPUTS.append(json.dumps(drift_data))
    check("--json reports a drift recovery: PASS, the two warnings, nothing blocked", drift_data.get("result") == "PASS"
          and len(drift_data.get("warnings", [])) == 2 and drift_data.get("blocked") == [], str(drift_data)[:300])
    code, out = run(["verify-live", "--policy", pol_f, "--destination", DEST, "--live", drift_f])
    check("verify-live has no drift recovery: a drifted live file is BLOCKED", code == 3 and "live protected layer differs" in out, out)
    code, out = chk(nocard_f, "--policy", pol_f)
    check("a protected pointer missing in the candidate is BLOCKED", code == 3 and f"{PTR} is missing in the candidate" in out, out)
    code, out = chk(live_f, "--policy", pol_f, live=nocard_f)
    check("a protected pointer missing in live is BLOCKED", code == 3 and f"{PTR} is missing in live" in out, out)
    code, out = chk(live_f, "--policy", pol_res_f, "--resources", res_ok_f)
    check("R3: a registered required resource passes", code == 0 and "ok R3: all 1 required resource(s) are registered" in out, out)
    code, out = chk(live_f, "--policy", pol_res_f, "--resources", res_missing_f)
    check("R3: a required resource that is not registered is BLOCKED", code == 3 and "BLOCKED R3: required resource #1 of 1" in out, out)
    code, out = chk(live_f, "--policy", pol_res_f)
    check("R3: a required resource with no resources file is BLOCKED", code == 3 and "BLOCKED R3" in out and "no resources file" in out, out)
    code, out = chk(live_f, "--policy", pol_res_f, "--resources", w("res-bad.json", '{"data": {"items": "x"}}'))
    check("R3: a malformed resources file is refused (exit 2, BLOCKED)", code == 2 and first(out) == f"{GATE}: BLOCKED", out)
    code, out = chk(live_f, "--resources", w("res-trunc.json", '{"data": {"items": ['))
    check("a truncated resources file is refused even when no rule needs it (exit 2)", code == 2 and "BLOCKED" in first(out), out)
    code, out = chk(base_f, "--accept-removed-type", SITE_TYPE)
    check("--accept-removed-type waives R4 (no policy): PASS, the waiver reported by the pointer of the type's first use",
          code == 0 and f"R4 waived by --accept-removed-type for the type at {PTR}/type, 1 use(s) in live" in out, out)
    two_f = w("cand-two-dropped.yaml", BASE.replace("custom:example-flow-card", "entities").replace("custom:example-nested-card", "entities"))
    code, out = chk(two_f, "--accept-removed-type", SITE_TYPE)
    check("--accept-removed-type waives only the type it names: a second dropped custom type is still BLOCKED by R4",
          code == 3 and out.count("BLOCKED R4") == 1 and "/views/0/sections/1/cards/1/cards/0/type" in out and "R4 waived" in out, out)
    code, out = chk(base_f, "--accept-removed-type", "custom:example-unrelated-card")
    check("accepting a type the candidate does not drop waives nothing: still BLOCKED by R4",
          code == 3 and "BLOCKED R4" in out and "--accept-removed-type #1 is not dropped by the candidate" in out, out)
    crafted = []
    for value in (f'{SITE_TYPE}" --destination /config/ecco/dashboards/other.yaml "', f"{SITE_TYPE} --destination", f"{SITE_TYPE}\n",
                  "custom:", "custom:-x", "CUSTOM:example", "custom:a/b"):
        code, out = chk(base_f, "--policy", pol_f, "--accept-removed-type", value)
        crafted.append((value, code))
    check("--accept-removed-type takes only a strict custom:<name> (a quote, a space, a line break, a slash or an empty name is refused, "
          "exit 2)", all(c == 2 for _v, c in crafted), str(crafted))
    code, out = chk(base_f, "--policy", pol_f, "--accept-removed-type", SITE_TYPE)
    check("--accept-removed-type never waives R2: still BLOCKED by the protected layer",
          code == 3 and "BLOCKED R2: candidate removes" in out and "BLOCKED R4" not in out and "R4 waived" in out, out)
    code, out = chk(live_f, "--policy", pol_res_f, "--resources", res_missing_f, "--accept-removed-type", SITE_TYPE)
    check("--accept-removed-type never waives R3", code == 3 and "BLOCKED R3" in out, out)
    nested_f = w("cand-nonested.yaml", LIVE.replace("custom:example-nested-card", "entities"))
    code, out = chk(nested_f, "--policy", pol_f)
    check("R4 sees a custom card type nested in a stack (first use pointer named)",
          code == 3 and "BLOCKED R4" in out and "/views/0/sections/1/cards/1/cards/0/type" in out and "BLOCKED R2" not in out, out)
    code, out = chk(live_f, "--accept-removed-type", "button-card")
    check("--accept-removed-type refuses a value that is not custom:<name> (exit 2)", code == 2 and "BLOCKED" in first(out), out)
    type_only = BASE.replace("custom:example-flow-card", SITE_TYPE)   # the private type back, the generic scene still in place
    type_only_f = w("cand-type-only.yaml", type_only)
    code_exact, out_exact = chk(type_only_f, "--policy", pol_f)
    case_f = wpolicy("policy-case.json", policy_obj(dest=DEST.replace("ecco_pro", "Ecco_pro")))
    code_case, out_case = chk(type_only_f, "--policy", case_f)
    check("a policy whose destination differs from the deployed path only in letter case is refused (exit 2), never the generic layer; "
          "the exact policy blocks the same candidate by R2", code_exact == 3 and "BLOCKED R2" in out_exact and code_case == 2
          and first(out_case) == "DASHBOARD_PRESERVE_GATE: BLOCKED" and "different letter case" in out_case, out_exact + out_case)
    code, out = chk(w("cand-del.yaml", "title: Example\nx: \x7f\n"))
    check("a character YAML does not allow (DEL) is a parse refusal with its offset (exit 2), not an internal error",
          code == 2 and "not parseable YAML (ReaderError at character offset" in out and "internal error" not in out, out)
    rep = TMP / "report.json"
    code, out = chk(base_f, "--policy", pol_f, "--json", str(rep))
    data = json.loads(rep.read_text(encoding="utf-8"))
    OUTPUTS.append(rep.read_text(encoding="utf-8"))
    check("--json writes a report: gate, BLOCKED, exit code, the policy state and the reasons",
          data["gate"] == GATE and data["result"] == "BLOCKED" and data["exit_code"] == 3 and data["policy"] == "entry"
          and any("R2" in b for b in data["blocked"]), str(data)[:300])

    # ==========================================================================================================================
    print("")
    print("[3] refused inputs: exit 2, BLOCKED, never 0")
    good = policy_obj()
    variants = {
        "malformed JSON": '{"schema": "ecco-dashboard-protection/1", "gate": "EXAMPLE_PRESERVE_GATE", "dashboards": [',
        "unknown schema": {**good, "schema": "ecco-dashboard-protection/2"},
        "duplicate destinations": {**good, "dashboards": good["dashboards"] * 2},
        "a pointer without a leading slash": {**good, "dashboards": [{**good["dashboards"][0], "protect": [{"pointer": "views/0", "sha256": "0" * 64}]}]},
        "a bad ~ escape": {**good, "dashboards": [{**good["dashboards"][0], "protect": [{"pointer": "/views~2", "sha256": "0" * 64}]}]},
        "an upper-case sha256": {**good, "dashboards": [{**good["dashboards"][0], "protect": [{"pointer": PTR, "sha256": "A" * 64}]}]},
        "a short sha256": {**good, "dashboards": [{**good["dashboards"][0], "protect": [{"pointer": PTR, "sha256": "0" * 12}]}]},
        "no dashboards": {**good, "dashboards": []},
        "an unknown key": {**good, "extra": 1},
        "an unknown entry key": {**good, "dashboards": [{**good["dashboards"][0], "rules": []}]},
        "a bad gate name": {**good, "gate": "lower"},
        "an overlay outside the protected pointer": policy_obj(overlay=[{"pointer": "/title", "value": "x"}]),
        "a null overlay value": policy_obj(overlay=[{"pointer": PTR + "/title", "value": None}]),
        "a list overlay value": policy_obj(overlay=[{"pointer": PTR + "/title", "value": ["x"]}]),
        "nested overlay pointers": policy_obj(overlay=[{"pointer": PTR + "/scene", "value": "x"}, {"pointer": PTR + "/scene/pack", "value": "y"}]),
        "a repeated JSON key": '{"schema": "ecco-dashboard-protection/1", "gate": "A_GATE", "gate": "B_GATE", "dashboards": []}',
        "a NaN constant": json.dumps(good).replace('"protect"', '"nan": NaN, "protect"'),
        "a site-local destination": policy_obj(dest="/config/ecco/site-local/x.yaml"),
        "a traversal destination": policy_obj(dest="/config/ecco/../secrets.yaml"),
        "not an object": "[]",
    }
    bad_codes = {}
    for name, obj in variants.items():
        pf = wpolicy("bad-" + re.sub(r"\W+", "-", name) + ".json", obj)
        code, out = chk(live_f, "--policy", pf)
        bad_codes[name] = (code, first(out))
    check("every malformed policy is refused with exit 2 and a BLOCKED first line, never 0 and never 'no policy': "
          + ", ".join(variants), all(c == 2 and f.endswith(": BLOCKED") for c, f in bad_codes.values()), str(bad_codes))
    code, out = chk(live_f, "--policy", str(TMP / "does-not-exist.json"))
    check("a named policy file that does not exist is refused (exit 2), not treated as absent", code == 2 and "BLOCKED" in first(out), out)
    code, out = chk(live_f, "--policy", wpolicy("bad-gate-named.json", {**good, "schema": "nope"}))
    check("a malformed policy whose gate field is readable is reported under that gate", first(out) == f"{GATE}: BLOCKED", out)
    yaml_bad = {
        "unparseable YAML": "a: [1, 2\n",
        "a top-level list": "- a\n- b\n",
        "an empty document": "",
        "two documents": "a: 1\n---\nb: 2\n",
        "a python object tag": "a: !!python/object/apply:os.system ['echo x']\n",
    }
    ycodes = {}
    for name, text in yaml_bad.items():
        code, out = chk(w("bad-" + re.sub(r"\W+", "-", name) + ".yaml", text))
        ycodes[name] = (code, first(out))
    code, out = chk(w("bad-latin1.yaml", "a: caf\xe9\n".encode("latin-1")))
    ycodes["not UTF-8"] = (code, first(out))
    code, out = chk(str(TMP / "missing.yaml"))
    ycodes["a missing file"] = (code, first(out))
    check("R1: an unparseable, non-mapping, empty, multi-document, python-tagged, non-UTF-8 or missing candidate is refused (exit 2, BLOCKED)",
          all(c == 2 and f == "DASHBOARD_PRESERVE_GATE: BLOCKED" for c, f in ycodes.values()), str(ycodes))
    code, out = run(["check", "--destination", DEST, "--live", live_f])
    check("a usage error (no --candidate) is exit 2 with a BLOCKED first line, not argparse's own exit",
          code == 2 and first(out) == "DASHBOARD_PRESERVE_GATE: BLOCKED" and "usage error" in out, out)
    code, out = run([])
    check("no command at all is a usage error (exit 2, BLOCKED)", code == 2 and "BLOCKED" in first(out), out)
    code, out = run(["check", "--destination", DEST, "--live", live_f, "--candidate", live_f, SECRET])
    code2, out2 = run(["verify-live", "--policy", pol_f, "--destination", DEST, "--live", live_f, "--accept-removed-type", SITE_TYPE])
    code3, out3 = run(["make-policy", "--gate", GATE, "--destination", DEST, "--base", base_f, "--live", live_f, "--pointer", PTR,
                       "--out", str(TMP / "never.json"), "--require-resource"])
    check("a usage error never echoes an argument value (a stray value, an option the command does not take, a missing value): "
          "exit 2, option names only", code == code2 == code3 == 2 and SECRET not in out and SITE_TYPE not in out2
          and "--accept-removed-type" in out2 and "values not shown" in out and "argument --require-resource: expected one argument" in out3,
          out + out2 + out3)
    code, out = run(["check", "--destination", DEST, "--live", live_f, "--candidate", base_f, "-h"])
    code2, out2 = run(["check", "--dest", DEST, "--live", live_f, "--candidate", live_f])
    check("no -h (argparse's help would exit 0, which means PASS) and no abbreviated options: both exit 2",
          code == 2 and code2 == 2 and first(out) == first(out2) == "DASHBOARD_PRESERVE_GATE: BLOCKED", out + out2)
    code, out = run(["check", "--destination", "/etc/passwd", "--live", live_f, "--candidate", live_f])
    check("a destination outside /config/ is refused (exit 2)", code == 2 and "BLOCKED" in first(out), out)
    r = subprocess.run([sys.executable, "-I", "-S", "-B", str(ROOT / "tools" / "ecco_dashboard_guard.py"), "check", "--destination", DEST,
                        "--live", live_f, "--candidate", live_f], capture_output=True, text=True, timeout=120)
    OUTPUTS.append(r.stdout + r.stderr)
    check("PyYAML missing (python -S: no site-packages) blocks: exit 2, first line BLOCKED, the reason names PyYAML",
          r.returncode == 2 and first(r.stdout) == "DASHBOARD_PRESERVE_GATE: BLOCKED" and "PyYAML" in r.stdout, r.stdout + r.stderr)
    r = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tools" / "ecco_dashboard_guard.py"), "check", "--destination", DEST,
                        "--live", live_f, "--candidate", base_f, "--policy", pol_f], capture_output=True, text=True, timeout=120)
    OUTPUTS.append(r.stdout + r.stderr)
    check("as a process: BLOCKED is exit code 3 with the BLOCKED first line", r.returncode == 3 and first(r.stdout) == f"{GATE}: BLOCKED",
          r.stdout + r.stderr)

    # ==========================================================================================================================
    print("")
    print("[4] apply: the overlay written into the candidate text, or nothing at all")
    out_f = TMP / "applied.yaml"
    code, out = run(["apply", "--policy", pol_f, "--destination", DEST, "--candidate", base_f, "--out", str(out_f)])
    applied = out_f.read_text(encoding="utf-8") if out_f.exists() else ""
    check("apply(base) passes (exit 0) and writes the result", code == 0 and first(out) == f"{GATE}: PASS" and applied, out)
    check("apply(base) is structurally equal to live", applied and G.canon_json(load(applied)) == G.canon_json(load(LIVE)))
    code2, out2 = chk(str(out_f), "--policy", pol_f)
    check("apply(base) passes check against the policy", code2 == 0 and first(out2) == f"{GATE}: PASS", out2)
    bl, al = BASE.splitlines(), applied.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(bl, al)) if a != b]
    check("only the overlay lines change: two scalars replaced in place (comments and layout kept), one key inserted at the mapping's "
          "indentation", len(al) == len(bl) + 1 and al[bl.index("              crossfade_ms: 900") + 1] == f'              variant: "{SECRET}"'
          and f'          - type: "{SITE_TYPE}"' in al and f'              pack: "{SITE_PACK}"' in al
          and al[0] == bl[0] and al[-1] == bl[-1], str(changed))
    out_live = TMP / "applied-live.yaml"
    code, out = run(["apply", "--policy", pol_f, "--destination", DEST, "--candidate", live_f, "--out", str(out_live)])
    check("apply(live) is byte-identical to live (values already present are left exactly as they are)",
          code == 0 and out_live.read_bytes() == LIVE.encode("utf-8") and "0 changed the text" in out, out)
    crlf_f = w("base-crlf.yaml", BASE.replace("\n", "\r\n"))
    out_crlf = TMP / "applied-crlf.yaml"
    code, out = run(["apply", "--policy", pol_f, "--destination", DEST, "--candidate", crlf_f, "--out", str(out_crlf)])
    raw = out_crlf.read_bytes() if out_crlf.exists() else b""
    check("a CRLF candidate keeps CRLF everywhere, the inserted line too", code == 0 and raw.count(b"\r\n") == raw.count(b"\n") > 0
          and G.canon_json(load(raw.decode())) == G.canon_json(load(LIVE)), out)
    tail_base = "a: 1\ncard:\n  type: custom:example-flow-card\n  scene:\n    pack: /local/x/"
    tail_pol = wpolicy("policy-tail.json", policy_obj(live_text=tail_base.replace("/local/x/", "y") + "\n    variant: z\n", ptr="/card",
                                                      overlay=[{"pointer": "/card/scene/pack", "value": "y"},
                                                               {"pointer": "/card/scene/variant", "value": "z"}]))
    out_tail = TMP / "applied-tail.yaml"
    code, out = run(["apply", "--policy", tail_pol, "--destination", DEST, "--candidate", w("tail.yaml", tail_base), "--out", str(out_tail)])
    check("an insertion after the last line of a file without a final line break lands in the right mapping",
          code == 0 and load(out_tail.read_text(encoding="utf-8"))["card"]["scene"] == {"pack": "y", "variant": "z"}, out)
    empties = []
    for i, tail in enumerate(("", "   # set by the site")):
        ef = w(f"base-empty-{i}.yaml", BASE.replace("              crossfade_ms: 900\n", f"              crossfade_ms: 900\n              variant:{tail}\n"))
        eo = TMP / f"applied-empty-{i}.yaml"
        code, out = run(["apply", "--policy", pol_f, "--destination", DEST, "--candidate", ef, "--out", str(eo)])
        empties.append(code == 0 and eo.exists() and G.canon_json(load(eo.read_text(encoding="utf-8"))) == G.canon_json(load(LIVE)))
    check("an existing empty value (with and without a trailing comment) is replaced, with a space after the colon", all(empties), str(empties))

    order_cases = (
        ("parent first, nested mapping last", "p:\n  x: 1\n  q:\n    y: 2\n",
         {"p": {"x": 1, "q": {"y": 2, "newQ": "b"}, "newP": "a"}}, [("/p/newP", "a"), ("/p/q/newQ", "b")], "/p"),
        ("parent first, no final line break", "a:\n  b:\n    c: 1",
         {"a": {"b": {"c": 1, "d": "y"}, "e": "x"}}, [("/a/e", "x"), ("/a/b/d", "y")], "/a"),
        ("an insertion before an empty-value replacement at the end of a file without a final line break", "a:\n  b:\n    c:",
         {"a": {"b": {"c": "v"}, "e": "x"}}, [("/a/e", "x"), ("/a/b/c", "v")], "/a"),
    )
    order_results = []
    for idx, (label, cand_text, expected, ops, ptr) in enumerate(order_cases):
        for direction, seq in (("as listed", ops), ("reversed", list(reversed(ops)))):
            pol = {"schema": G.SCHEMA, "gate": GATE, "dashboards": [{"destination": DEST, "protect": [
                {"pointer": ptr, "sha256": G.canon_hash(G.resolve(expected, G.parse_pointer(ptr, "t")))}],
                "overlay": [{"pointer": p_, "value": v_} for p_, v_ in seq]}]}
            of = TMP / f"order-{idx}-{direction.replace(' ', '-')}.yaml"
            code, out = run(["apply", "--policy", wpolicy(f"order-{idx}-{direction.replace(' ', '-')}.json", pol), "--destination", DEST,
                             "--candidate", w(f"order-{idx}.yaml", cand_text), "--out", str(of)])
            ok = code == 0 and of.exists() and G.canon_json(load(of.read_text(encoding="utf-8"))) == G.canon_json(expected)
            order_results.append((label, direction, ok))
    check("apply does not depend on the order of the overlay operations: insertions at one position go deepest first, after a "
          "replacement (" + "; ".join(c[0] for c in order_cases) + ")", all(r[2] for r in order_results), str(order_results))
    entry = G.load_policy(pol_f).entries[DEST]
    tampered = applied.replace("title: Example", "title: Tampered", 1)
    reasons = G.overlay_postcondition(load(BASE), tampered, entry)
    check("the post-condition refuses a result that changes a key outside the protected subtree while every protect hash still matches",
          G.overlay_postcondition(load(BASE), applied, entry) == [] and "title: Tampered" in tampered
          and any("does not parse to the candidate with exactly the overlay values set" in r for r in reasons), str(reasons))

    def refused(name: str, candidate_text: str, policy: dict | None = None, expect: str = "") -> None:
        cf = w("ref-" + re.sub(r"\W+", "-", name) + ".yaml", candidate_text)
        pf = wpolicy("ref-" + re.sub(r"\W+", "-", name) + ".json", policy) if policy else pol_f
        of = TMP / ("ref-out-" + re.sub(r"\W+", "-", name) + ".yaml")
        code, out = run(["apply", "--policy", pf, "--destination", DEST, "--candidate", cf, "--out", str(of)])
        check(f"apply refuses {name} (exit 3) and writes nothing", code == 3 and not of.exists() and first(out) == f"{GATE}: BLOCKED"
              and expect in out, out)

    refused("a missing parent", BASE.replace("            scene:\n              pack: /local/example/scenes/\n              crossfade_ms: 900\n", ""),
            expect="parent is missing")
    refused("a flow-mapping parent", BASE.replace("            scene:\n              pack: /local/example/scenes/\n              crossfade_ms: 900\n",
                                                   "            scene: {pack: /local/example/scenes/, crossfade_ms: 900}\n"), expect="flow mapping")
    refused("a sequence parent", BASE, policy_obj(live_text=BASE.replace("              - first", "              - second"),
                                                   overlay=[{"pointer": PTR + "/tags/0", "value": "second"}]), expect="not a mapping")
    refused("an anchored parent", BASE.replace("            scene:\n", "            scene: &scene_defaults\n"), expect="anchor or alias")
    refused("an alias parent", "defaults: &d\n  pack: /local/example/scenes/\n  crossfade_ms: 900\n"
            + BASE.replace("            scene:\n              pack: /local/example/scenes/\n              crossfade_ms: 900\n", "            scene: *d\n"),
            expect="anchor or alias")
    refused("a merge key in the parent", "defaults: &d\n  crossfade_ms: 900\n"
            + BASE.replace("              crossfade_ms: 900\n", "              <<: *d\n"), expect="merge key")
    refused("a non-scalar target", BASE.replace("          - type: custom:example-flow-card\n",
                                                "          - type:\n              name: custom:example-flow-card\n"),
            expect="not a plain scalar")
    refused("a tagged target", BASE.replace("pack: /local/example/scenes/", "pack: !secret example_pack"), expect="not a plain scalar")
    refused("a block-scalar target", BASE.replace("pack: /local/example/scenes/", "pack: |\n                /local/example/scenes/"),
            expect="multi-line")
    refused("a candidate whose protected subtree changed elsewhere (post-condition)", BASE.replace("crossfade_ms: 900", "crossfade_ms: 1200"),
            expect="post-condition")
    exists_f = TMP / "exists.yaml"
    exists_f.write_text("keep\n", encoding="utf-8")
    code, out = run(["apply", "--policy", pol_f, "--destination", DEST, "--candidate", base_f, "--out", str(exists_f)])
    check("apply never overwrites an existing --out (exit 2, file untouched)", code == 2 and exists_f.read_text(encoding="utf-8") == "keep\n", out)
    no_out = TMP / "no-entry-out.yaml"
    code, out = run(["apply", "--policy", other_f, "--destination", DEST, "--candidate", base_f, "--out", str(no_out)])
    check("apply refuses a policy without an entry for the destination (exit 2) and writes nothing", code == 2 and not no_out.exists(), out)

    # ==========================================================================================================================
    print("")
    print("[5] make-policy")
    mp_f = TMP / "made-policy.json"
    code, out = run(["make-policy", "--gate", GATE, "--destination", DEST, "--base", base_f, "--live", live_f, "--pointer", PTR,
                     "--require-resource", RES_URL, "--out", str(mp_f)])
    made = json.loads(mp_f.read_text(encoding="utf-8")) if mp_f.exists() else {}
    e = (made.get("dashboards") or [{}])[0]
    check("make-policy succeeds with exactly three overlay operations (two replaced scalars, one added key) and the protect hash of live",
          code == 0 and made.get("schema") == G.SCHEMA and made.get("gate") == GATE and e.get("destination") == DEST
          and [o["pointer"] for o in e.get("overlay", [])] == [PTR + "/type", PTR + "/scene/pack", PTR + "/scene/variant"]
          and [o["value"] for o in e["overlay"]] == [SITE_TYPE, SITE_PACK, SECRET]
          and e.get("protect") == [{"pointer": PTR, "sha256": G.canon_hash(G.resolve(load(LIVE), G.parse_pointer(PTR, "t")))}]
          and e.get("require_resources") == [{"url": RES_URL}] and G.validate_policy(made).gate == GATE, out)
    code, out = chk(base_f, "--policy", str(mp_f), "--resources", res_ok_f)
    check("the made policy blocks the generic render", code == 3 and "BLOCKED R2" in out, out)
    outside_f = w("live-outside.yaml", LIVE.replace("entity: sensor.example_status", "entity: sensor.example_private_status"))

    def mp_refused(name: str, live_file: str, expect: str) -> None:
        of = TMP / ("mp-" + re.sub(r"\W+", "-", name) + ".json")
        code, out = run(["make-policy", "--gate", GATE, "--destination", DEST, "--base", base_f, "--live", live_file, "--pointer", PTR,
                         "--out", str(of)])
        check(f"make-policy refuses {name} (exit 3) and writes nothing", code == 3 and not of.exists() and expect in out, out)
        return out

    out = mp_refused("a difference outside the pointer", outside_f, "outside /views/0/sections/1/cards/0 at /views/0/sections/0/cards/0/entity")
    check("... and prints the differing pointer, not the value", "example_private_status" not in out, out)
    mp_refused("a removed key", w("live-removed.yaml", LIVE.replace("              crossfade_ms: 900\n", "")), "removes")
    mp_refused("a non-scalar difference", w("live-nonscalar.yaml", LIVE.replace("              crossfade_ms: 900\n",
                                                                                "              crossfade_ms: 900\n              extra:\n                a: 1\n")),
               "not a scalar leaf")
    mp_refused("a difference inside a sequence", w("live-seq.yaml", LIVE.replace("              - first", "              - second")), "sits in a sequence")
    esc_base = 'title: Example\ncard:\n  type: custom:example-flow-card\n  "a/b":\n    "c~d": old\n    keep: 1\n'
    esc_live = esc_base.replace('"c~d": old', '"c~d": new') + '    "e/f~1g": added\n'
    esc_pol = TMP / "mp-escaped.json"
    code, out = run(["make-policy", "--gate", GATE, "--destination", DEST, "--base", w("esc-base.yaml", esc_base), "--live",
                     w("esc-live.yaml", esc_live), "--pointer", "/card", "--out", str(esc_pol)])
    esc_made = json.loads(esc_pol.read_text(encoding="utf-8")) if esc_pol.exists() else {}
    esc_ptrs = [o["pointer"] for o in (esc_made.get("dashboards") or [{}])[0].get("overlay", [])]
    esc_out = TMP / "applied-escaped.yaml"
    code2, out2 = run(["apply", "--policy", str(esc_pol), "--destination", DEST, "--candidate", w("esc-base2.yaml", esc_base),
                       "--out", str(esc_out)])
    check("make-policy and apply round-trip keys that contain / and ~ (escaped as ~1 and ~0 in the overlay pointers)",
          code == 0 and esc_ptrs == ["/card/a~1b/c~0d", "/card/a~1b/e~1f~01g"] and code2 == 0
          and G.canon_json(load(esc_out.read_text(encoding="utf-8"))) == G.canon_json(load(esc_live)), out + out2)
    code, out = run(["make-policy", "--gate", "bad", "--destination", DEST, "--base", base_f, "--live", live_f, "--pointer", PTR,
                     "--out", str(TMP / "mp-badgate.json")])
    check("make-policy refuses a gate name that is not upper-case (exit 2)", code == 2 and not (TMP / "mp-badgate.json").exists(), out)

    # ==========================================================================================================================
    print("")
    print("[6] verify-live and classify")
    code, out = run(["verify-live", "--policy", pol_f, "--destination", DEST, "--live", live_f])
    check("verify-live passes on live", code == 0 and first(out) == f"{GATE}: PASS", out)
    code, out = run(["verify-live", "--policy", pol_f, "--destination", DEST, "--live", base_f])
    check("verify-live blocks a file without the protected layer (exit 3)", code == 3 and "live protected layer differs" in out, out)
    code, out = run(["verify-live", "--policy", other_f, "--destination", DEST, "--live", live_f])
    check("verify-live refuses a policy without an entry for the destination (exit 2)", code == 2 and "BLOCKED" in first(out), out)
    code, out = run(["classify", "--destination", DEST])
    check("classify: a /config/ecco/dashboards/*.yaml path is a dashboard destination (exit 0)", code == 0 and "yes" in out, out)
    code, out = run(["classify", "--destination", "/config/packages/ecco_pro.yaml"])
    check("classify: a package path is not (exit 4, never Python's crash code 1)", code == 4 and G.EXIT_NOT_DASHBOARD == 4
          and out.splitlines() == ["gate: DASHBOARD_PRESERVE_GATE", "dashboard destination: no"], out)
    code, out = run(["classify", "--destination", "/config/packages/ecco_pro.yaml", "--policy", pol_f])
    check("classify with a policy lists every destination it names (so the deploy tool can prove each exists on the host)",
          code == 4 and out.splitlines()[2:] == ["policy destinations: 1", f"policy destination: {DEST}"], out)
    code, out = run(["classify", "--destination", DEST, "--policy", case_f])
    check("classify: a policy destination that differs only in letter case is refused (exit 2)", code == 2 and "different letter case" in out, out)
    named_f = wpolicy("policy-named.json", policy_obj(dest="/config/ecco/custom_dashboard.yaml"))
    code, out = run(["classify", "--destination", "/config/ecco/custom_dashboard.yaml", "--policy", named_f])
    check("classify: a path the policy names is a dashboard destination, under the policy gate", code == 0 and "site policy entry" in out
          and first(out) == f"gate: {GATE}", out)
    code, out = run(["classify", "--destination", DEST, "--policy", w("cls-bad.json", "{")])
    check("classify: a malformed policy is refused (exit 2, BLOCKED)", code == 2 and "BLOCKED" in first(out), out)
    code, out = run(["classify", "--destination", "/config/ecco/site-local/dashboard-protection.json"])
    check("classify: a site-local destination is refused (exit 2)", code == 2, out)

    # ==========================================================================================================================
    print("")
    print("[7] privacy: no overlay value is ever printed")
    err_f = w("live-error.yaml", LIVE.replace(f"variant: {SECRET}", f"variant: [{SECRET}"))
    code, out = chk(err_f)
    check("a YAML error on the line of a private value names the line and column only", code == 2 and "line" in out and SECRET not in out, out)
    fixture_types = ("custom:example-status-card", "custom:example-flow-card", "custom:example-nested-card", SITE_TYPE)
    type_marks = [t for t in fixture_types] + [hashlib.sha256(t.encode()).hexdigest()[:12] for t in fixture_types]
    type_leaks = sorted({m for m in type_marks for o in OUTPUTS if m in o})
    check("no card type name and no hash of one appears in any output (R4 names a type by the pointer of its first use and a count)",
          not type_leaks, str(type_leaks))
    leaks = [v for v in OVERLAY_VALUES for o in OUTPUTS if v in o]
    check(f"no overlay value appears in any of the {len(OUTPUTS)} captured outputs and reports (stdout, stderr, --json)", not leaks,
          str(sorted(set(leaks))))

    # ==========================================================================================================================
    print("")
    print("[8] static: the guard's own imports, the deploy wiring, the docs")
    src = (ROOT / "tools" / "ecco_dashboard_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"socket", "http", "urllib", "requests", "subprocess", "os", "shutil", "ftplib", "smtplib", "asyncio", "ssl",
              "multiprocessing", "ctypes", "pty", "telnetlib", "xmlrpc", "webbrowser", "importlib"}
    check("the guard imports no network, process, shell or OS module (only the standard library it needs and PyYAML)",
          imported <= {"__future__", "argparse", "base64", "copy", "datetime", "hashlib", "json", "math", "re", "sys", "pathlib", "yaml"}
          and not (imported & banned), str(sorted(imported)))
    names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attrs = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    check("no eval / exec / compile / __import__ builtin call and no system / popen / spawn / exec* method call",
          not (names & {"eval", "exec", "compile", "__import__"}) and not {a for a in attrs if a in ("system", "popen", "spawn") or a.startswith("exec")},
          str(sorted(names & {"eval", "exec", "compile", "__import__"})))
    writers = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Name) and n.func.id == "open")
        or (isinstance(n.func, ast.Attribute) and n.func.attr in ("write_text", "write_bytes", "unlink", "rename", "mkdir", "rmdir", "touch",
                                                                  "symlink_to", "hardlink_to", "chmod"))
        or (isinstance(n.func, ast.Attribute) and n.func.attr == "replace" and len(n.args) == 1))]   # Path.replace(target); str.replace has 2
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    inside = [any(f.lineno <= wr.lineno <= f.end_lineno for f in (funcs["write_new"], funcs["write_report"])) for wr in writers]
    check("the guard writes only through write_new (exclusive create for --out) and write_report (--json)",
          len(writers) == 2 and all(inside) and '"xb"' in src, str([(wr.lineno, i) for wr, i in zip(writers, inside)]))

    def ps_code(rel: str) -> str:
        text = re.sub(r"<#.*?#>", "", (ROOT / rel).read_text(encoding="utf-8"), flags=re.S)
        return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    def depth_at(code: str, pos: int) -> int:
        """Brace depth at `pos` with string literals blanked (single-quoted, then double-quoted with backtick escapes)."""
        bare = re.sub(r"'(?:[^']|'')*'", "''", code[:pos])
        bare = re.sub(r'"(?:[^"`]|`.)*"', '""', bare)
        return bare.count("{") - bare.count("}")

    dha, mod, dd = ps_code("tools/deploy-ha.ps1"), ps_code("tools/EccoDeploy.psm1"), ps_code("tools/deploy-dashboard.ps1")
    gate_at = dha.find("Invoke-EccoDashboardPreservationGate")
    writes = [dha.find(s) for s in ("mkdir -p '", "cp -p '$Destination'", "& scp -q $sourceFull", "then cp -p '$lovelaceResourcesPath'")]
    before = dha[:gate_at] if gate_at > 0 else ""
    check("deploy-ha.ps1 runs the preservation gate before its first remote write (mkdir, backup, resource backup, upload), and nothing "
          "but the read-only ssh probe touches the host before it",
          gate_at > 0 and all(i > gate_at for i in writes) and "Invoke-EccoRemoteCommand" not in before and "scp" not in before
          and "-CandidatePath $sourceFull" in dha[gate_at:gate_at + 300], str((gate_at, writes)))
    gate_line = next((ln for ln in dha.splitlines() if "Invoke-EccoDashboardPreservationGate" in ln), "")
    first_write = min(i for i in writes if i > 0) if any(i > 0 for i in writes) else -1
    check("the gate call is a bare top-level statement that can stop the script: brace depth 0 (not inside try, if or a script block), "
          "no -ErrorAction on it, no trap anywhere, no catch between it and the first remote write, $ErrorActionPreference = 'Stop' before it",
          gate_at > 0 and depth_at(dha, gate_at) == 0 and gate_line.startswith("$dashboardGate = Invoke-EccoDashboardPreservationGate ")
          and "-ErrorAction" not in gate_line and not re.search(r"(?im)^\s*trap\b", dha) and first_write > gate_at
          and not re.search(r"(?i)\bcatch\b", dha[gate_at:first_write]) and 0 < dha.find("$ErrorActionPreference = 'Stop'") < gate_at,
          str((gate_at, depth_at(dha, gate_at) if gate_at > 0 else None, first_write)))
    mv_at = dha.find("-Command \"mv -f '$tempPath' '$Destination'\"")
    src_check = dha.find("if (-not $dashboardGate.CandidateSha256 -or $checkedSourceHash -ne $dashboardGate.CandidateSha256) {")
    up_check = dha.find("if ($dashboardGate.Applies -and $remoteHash -ne $dashboardGate.CandidateSha256) {")
    check("deploy-ha.ps1 installs only the bytes the gate checked: the source hash equals the gate's CandidateSha256 before the first "
          "remote write, and the uploaded copy's hash equals it before the move into place (both throw)",
          0 < gate_at < src_check < first_write and "throw " in dha[src_check:src_check + 400]
          and 0 < up_check < mv_at and "throw " in dha[up_check:up_check + 400] and "$checkedSourceHash = (Get-FileHash" in dha,
          str((gate_at, src_check, first_write, up_check, mv_at)))
    src_tie = re.search(r"(?m)^if \(\$dashboardGate\.Applies\) \{\n    \$checkedSourceHash = \(Get-FileHash -Algorithm SHA256 "
                        r"-LiteralPath \$sourceFull\)\.Hash\.ToLowerInvariant\(\)\n    if \(-not \$dashboardGate\.CandidateSha256 -or "
                        r"\$checkedSourceHash -ne \$dashboardGate\.CandidateSha256\) \{\n        throw ", dha)
    check("the source-hash tie runs whenever the gate applies: a top-level `if ($dashboardGate.Applies) {` whose first statements "
          "hash the source and throw on a mismatch, before the first remote write",
          bool(src_tie) and depth_at(dha, src_tie.start()) == 0 and gate_at < src_tie.start() < first_write,
          str(src_tie.start() if src_tie else None))
    post_at, core_at = dha.find('Write-Host "Post-install SHA256 verified: $postInstallHash"'), dha.find("-Command 'ha core check' -Capture")
    ver_at = dha.find("Invoke-EccoDashboardLiveVerification")
    block = dha[ver_at:core_at] if 0 < ver_at < core_at else ""
    check("deploy-ha.ps1 runs verify-live after the post-install hash and before `ha core check`, when the policy names the destination, "
          "and a failure goes through Invoke-EccoDeploymentRollback",
          0 < post_at < ver_at < core_at and "if ($dashboardGate.PolicyNamesDestination)" in dha[post_at:ver_at]
          and "if (-not $liveVerification.Passed)" in block and "Invoke-EccoDeploymentRollback" in block, str((post_at, ver_at, core_at)))
    check("deploy-ha.ps1 checks that the backed-up file is the file the gate read, and prints the gate in the PASSED block",
          "if ($backupHash -ne $dashboardGate.LiveSha256)" in dha and 'Write-Host "Dashboard   : $($dashboardGate.GateLine)"' in dha
          and dha.find("if ($backupHash -ne $dashboardGate.LiveSha256)") < dha.find("& scp -q $sourceFull")
          and dha.find("Write-Host 'ECCO DEPLOYMENT PASSED'") < dha.find('Write-Host "Dashboard   : $($dashboardGate.GateLine)"'))
    strict = "[ValidatePattern('^custom:[A-Za-z0-9][A-Za-z0-9._-]*\\z')]\n    [string[]]$AcceptRemovedCardType = @()"
    check("-AcceptRemovedCardType is a strictly validated deploy-ha.ps1 parameter passed to the gate, and deploy-dashboard.ps1 passes it "
          "through with the same validation", strict in dha and "-AcceptRemovedCardType $AcceptRemovedCardType" in dha
          and strict in dd and "$deployParams.AcceptRemovedCardType = $AcceptRemovedCardType" in dd)
    check("-Python names the guard's interpreter: a deploy-ha.ps1 parameter passed to the gate and to verify-live (with the expected "
          "gate), passed through by deploy-dashboard.ps1",
          "[string]$Python = 'python'" in dha and "-AcceptRemovedCardType $AcceptRemovedCardType -Python $Python" in dha
          and "-GuardPath $guardPath -Python $Python -ExpectedGate $dashboardGate.Gate" in dha and "$deployParams.Python = $Python" in dd)
    pin_at = dha.find("$gatePinLine = Assert-EccoDashboardGatePin -GateResult $dashboardGate -ExpectedGate $gatePin -PinSource $gatePinSource")
    pin_read = dha.find("$gatePin = Get-EccoDashboardGatePin -Path $gatePinFile")
    check("deploy-ha.ps1 reads the gate pin (-ExpectedSiteGate, else the local pin file) before it contacts the host, and checks it as a bare "
          "top-level statement right after the gate and before the first remote write",
          0 < pin_read < dha.find("& ssh -o BatchMode=yes $SshHost 'true'") and 0 < gate_at < pin_at < first_write
          and depth_at(dha, pin_at) == 0 and not re.search(r"(?i)\bcatch\b", dha[gate_at:first_write])
          and "if ($ExpectedSiteGate) {\n    $gatePin = $ExpectedSiteGate" in dha
          and "[ValidatePattern('(?-i)^[A-Z][A-Z0-9_]{2,63}\\z')]\n    [string]$ExpectedSiteGate" in dha, str((pin_read, gate_at, pin_at, first_write)))
    check("-AllowDriftRecovery is a deploy-ha.ps1 switch passed to the gate; deploy-dashboard.ps1 passes it and -ExpectedSiteGate through",
          "[switch]$AllowDriftRecovery" in dha and "-Python $Python -AllowDriftRecovery:$AllowDriftRecovery" in gate_line
          and "$deployParams.AllowDriftRecovery = $true" in dd and "$deployParams.ExpectedSiteGate = $ExpectedSiteGate" in dd
          and "if ($AllowDriftRecovery) {\n            $arguments += '--allow-drift-recovery'" in mod)
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    check("the local pin file is git-ignored under the name the module reads",
          "$script:EccoDashboardGatePinFile = 'ecco_dashboard_gate.local.txt'" in mod and "ecco_dashboard_gate.local.txt" in gitignore
          and "**/ecco_dashboard_gate.local.txt" in gitignore)
    rb = re.search(r"function Invoke-EccoDeploymentRollback \{(.*?)\n\}\n", mod, re.S)
    rbody = rb.group(1) if rb else ""
    check("the rollback restores with a plain cp then touch (never cp -p: Home Assistant keeps serving a cached YAML dashboard that is not "
          "newer than its cache) and asks for a lovelace/config read-back for a dashboard",
          "-Command \"cp '$BackupPath' '$Destination' && touch '$Destination'\"" in rbody and "cp -p" not in rbody
          and "-Dashboard $isDashboard" in rbody and "DASHBOARD READ-BACK REQUIRED" in mod and "websocket lovelace/config" in mod
          and dha.count("-Dashboard:($dashboardGate.Applies)") == 4)
    drift_line = re.search(r'\nif \(\$driftRecovery\) \{\n    Write-Host "(Drift       : RECOVERED - [^"]*)"\n\}\n', dha)
    check("a drift recovery is one flag in deploy-ha.ps1, set from the gate's WARNING lines: every rollback gets it (DRIFT RECOVERY ROLLED "
          "BACK), and the PASSED block prints the Drift line only under it",
          "\n$driftRecovery = @($dashboardGate.Warnings).Count -gt 0\n" in dha and dha.count("-DriftRecovery:$driftRecovery -Reason ") == 4
          and "-DriftRecovery ([bool]$DriftRecovery)" in rbody and "DRIFT RECOVERY ROLLED BACK" in mod and drift_line is not None
          and dha.find("$driftRecovery = ") < dha.find("Invoke-EccoDeploymentRollback "))
    m = re.search(r"function Test-EccoDeploymentDestination \{(.*?)\n\}", mod, re.S)
    body = m.group(1) if m else ""
    site_local_refusal = re.search(
        r"\n    if \(\$normalised\.StartsWith\(\$script:EccoSiteLocalPrefix, \[System\.StringComparison\]::Ordinal\) -or\s*\n\s*"
        r"\$normalised -eq \$script:EccoSiteLocalPrefix\.TrimEnd\('/'\)\) \{\s*\n\s*throw ", body)
    check("EccoDeploy.psm1 refuses every destination under /config/ecco/site-local/ (and the bare folder): exactly this condition, "
          "followed by throw, before it returns a destination",
          "$script:EccoSiteLocalPrefix = '/config/ecco/site-local/'" in mod and site_local_refusal is not None
          and body.find("EccoSiteLocalPrefix") < body.rfind("return $normalised"))
    g = re.search(r"function Invoke-EccoDashboardPreservationGate \{(.*?)\n\}\n", mod, re.S)
    gbody = g.group(1) if g else ""
    check("the module's gate runs the guard's check on its private candidate copy, throws on any exit code but 0 and on any first line "
          "but '<gate>: PASS' under the gate classify determined, and deletes its temp folder in finally",
          "@('check', '--destination', $Destination, '--live', $localLive, '--candidate', $localCandidate)" in gbody
          and re.search(r"if \(\$check\.ExitCode -ne 0\) \{\s*throw \(Format-EccoGateBlockedMessage", gbody) is not None
          and '$expectedPass = "$($result.Gate): PASS"' in gbody
          and re.search(r"if \(\$first -cne \$expectedPass\) \{\s*throw \(Format-EccoGateBlockedMessage", gbody) is not None
          and "Copy-Item -LiteralPath $CandidatePath -Destination $localCandidate -ErrorAction Stop" in gbody
          and "$result.CandidateSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $localCandidate)" in gbody
          and re.search(r"finally \{\s*try \{\s*Remove-Item -LiteralPath \$work -Recurse -Force", gbody) is not None
          and "$script:EccoDashboardPolicyPath = '/config/ecco/site-local/dashboard-protection.json'" in mod)
    check("the module reads classify strictly: exit 0 with one yes line or exit 4 with the no line, the gate line first and the policy's "
          "destination list; anything else throws (a crash exits 1 and is BLOCKED, never 'not a dashboard')",
          "$answeredYes = ($classify.ExitCode -eq 0) -and ($yesEntry -xor $yesPath) -and (-not $no)" in gbody
          and "$answeredNo = ($classify.ExitCode -eq 4) -and $no -and (-not $yesEntry) -and (-not $yesPath)" in gbody
          and re.search(r"if \(-not \(\$classifiedGate -and \$listed -and \(\$answeredYes -or \$answeredNo\)\)\) \{(?:(?!\n        \}).)*?"
                        r"throw \(Format-EccoGateBlockedMessage", gbody, re.S) is not None
          and "ExitCode -ne 1" not in gbody and "ExitCode -eq 1" not in gbody)
    check("the module proves every other destination the policy names exists on the host (a mistyped destination is BLOCKED)",
          "foreach ($policyDestination in $listedDestinations) {" in gbody
          and re.search(r"if \(\$policyDestinationState -ne 'present'\) \{\s*throw \(Format-EccoGateBlockedMessage", gbody) is not None)
    check("the module validates -AcceptRemovedCardType strictly, and its guard runner refuses an argument with a double quote or a "
          "trailing backslash (Windows PowerShell 5.1 would split it into several guard options)",
          "$t -cnotmatch '^custom:[A-Za-z0-9][A-Za-z0-9._-]*\\z'" in gbody
          and "if ($a.Contains('\"') -or $a.EndsWith('\\')) {" in mod)
    probe_fn = re.search(r"function Get-EccoGateProbeCommand \{(.*?)\n\}\n", mod, re.S)
    pbody = probe_fn.group(1) if probe_fn else ""
    check("the read-only host probe reports a symlink (dangling or not) and an unsearchable ancestor as unreadable, and absent only "
          "when the nearest existing ancestor is a searchable directory; Copy-EccoRemoteFileForGate uses it",
          '"if [ -L $q ]; then printf unreadable; elif [ -e $q ]' in pbody and "if [ -d $ancestor ] && [ -x $ancestor ]; then printf absent" in pbody
          and "`\"" not in pbody and "$q = \"'$RemotePath'\"" in pbody)   # the shell text has no double quote (5.1 would split it)
    check("... and Copy-EccoRemoteFileForGate runs exactly that probe", "-Command (Get-EccoGateProbeCommand -RemotePath $RemotePath) -Capture" in mod)
    check("the module's post-install check runs verify-live and the guard runner never trusts an exit code after a failed start",
          "@('verify-live', '--policy', $localPolicy, '--destination', $Destination, '--live', $localLive)" in mod
          and "the guard could not be started" in mod and "& $Python -I -B -X utf8 $GuardPath @Arguments 2>&1" in mod)
    check("the module still names no .storage path (the caller passes the resource list's path)", "/config/.storage" not in mod)
    ps7 = []
    for rel in ("tools/deploy-ha.ps1", "tools/EccoDeploy.psm1", "tools/deploy-dashboard.ps1", "tools/tests/Test-EccoDeploy.ps1"):
        for i, ln in enumerate(ps_code(rel).splitlines(), 1):
            bare = re.sub(r"'[^']*'|\"[^\"]*\"", "''", ln)
            if re.search(r"\?\?|\?\.|&&|\|\|", bare):
                ps7.append(f"{rel}:{i}")
    check("no PowerShell 7-only operator (??, ?., &&, ||) in the deploy scripts, the module or its test (Windows PowerShell 5.1)", not ps7, str(ps7))
    ex = json.loads((ROOT / "deployment" / "dashboard-protection.example.json").read_text(encoding="utf-8"))
    ex_text = json.dumps(ex)
    check("deployment/dashboard-protection.example.json is a valid policy with fictional values only",
          G.validate_policy(ex).gate.startswith("EXAMPLE") and "example" in ex_text and all(
              "example" in o["value"] for d in ex["dashboards"] for o in d["overlay"] if isinstance(o["value"], str)))
    site = (ROOT / "docs" / "user" / "site-render.md").read_text(encoding="utf-8")
    site_flat = " ".join(site.split())
    check("the deploy documentation has the 'Dashboard preservation gate' section: policy path, schema, example, make-policy, apply, "
          "-AcceptRemovedCardType and the deliberate retirement / rollback step",
          "### Dashboard preservation gate" in site and "/config/ecco/site-local/dashboard-protection.json" in site
          and G.SCHEMA in site and "deployment/dashboard-protection.example.json" in site and "make-policy" in site
          and "ecco_dashboard_guard.py apply" in site and "-AcceptRemovedCardType" in site and "rollback" in site.lower() and "move the host policy aside" in site)
    check("the docs name the interpreter (-Python, python -I ignores user site-packages), the site gate name as the acceptance line, the "
          "ordinary -AcceptRemovedCardType use for a card swap and its rollback, the owner procedure for a release that changes the "
          "protected card, and Test-EccoDeploy.ps1 as a local pre-push step",
          all(phrase in site_flat for phrase in ("-Python <python.exe>", "`-I` (isolated mode) ignores the user site-packages folder",
                                                 "accept a dashboard deployment only when that line names the site's gate",
                                                 "not `DASHBOARD_PRESERVE_GATE: PASS`", "replaces one custom card with another",
                                                 "A release that changes the protected card", "make-policy --base <new render>",
                                                 "Move the host policy aside", "Test-EccoDeploy.ps1 -Python", "required local pre-push step")))
    check("the docs describe the hardening: the rollback's plain cp and touch with the lovelace/config read-back, the gate pin (parameter, "
          "git-ignored file, the deliberate DASHBOARD_PRESERVE_GATE pin, the pinned owner procedure and retirement), drift recovery "
          "(exact layer only, warnings, waives nothing else) and plan --site-policy",
          all(phrase in site_flat for phrase in ("never `cp -p`", "websocket `lovelace/config`", "DASHBOARD READ-BACK REQUIRED",
                                                 "-ExpectedSiteGate <SITE_GATE_NAME>", "`ecco_dashboard_gate.local.txt`",
                                                 "`-ExpectedSiteGate DASHBOARD_PRESERVE_GATE`", "remove the local gate pin",
                                                 "**Drift recovery (`-AllowDriftRecovery`).**", "A candidate that does not carry the protected "
                                                 "layer exactly stays BLOCKED", "`verify-live` never accepts drift",
                                                 "plan --site-policy <local copy of the host policy>")))
    check("the docs quote deploy-ha.ps1's Drift line as it prints it (column-aligned), and say that a drift recovery's rollback restores the "
          "drifted file (DRIFT RECOVERY ROLLED BACK), never that the rollback keeps the protected layer",
          drift_line is not None and f"`{drift_line.group(1).split(' from the site policy')[0]} from the site policy ...`" in site
          and "the automatic rollback keeps the protected layer" not in site_flat
          and all(phrase in site_flat for phrase in ("except after a drift recovery, whose backup is the drifted file",
                                                     "`DRIFT RECOVERY ROLLED BACK`", "Do not report the site layer as intact")))
    check("the docs give -ExpectedSiteGate DASHBOARD_PRESERVE_GATE as the one-run override while the policy is aside (bundles and packages "
          "too) and say to keep the pin; only retiring protection removes it",
          all(phrase in site_flat for phrase in ("the one-run override while the policy is deliberately aside", "Keep the pin: removing it",
                                                 "every deployment made while the policy is aside (this one, and the release's card bundle or "
                                                 "a package deployed before step 5) needs `-ExpectedSiteGate DASHBOARD_PRESERVE_GATE`",
                                                 "Never remove it for this procedure"))
          and site_flat.count("remove the local gate pin") == 1 and "remove the pin" not in site_flat
          and "remove the pin" not in mod and "-ExpectedSiteGate $($script:EccoDefaultDashboardGate) for this deployment only, and keep the pin" in mod)
    inst = (ROOT / "frontend" / "ecco-flow-3d-card" / "INSTALL_PREVIEW.md").read_text(encoding="utf-8")
    inst_flat = " ".join(inst.split())
    check("INSTALL_PREVIEW.md section 7: the plan --out is inside the checkout (dist/deploy), never outside the repository",
          "--out dist/deploy" in inst and "--out <directory outside the repository>" not in inst)
    check("INSTALL_PREVIEW.md: the 7.22.0 -> 7.23.0 deployment and its rollback cross a custom card swap, so each needs "
          "-AcceptRemovedCardType with or without a site policy",
          "-AcceptRemovedCardType custom:ecco-energy-flow-card" in inst_flat and "-AcceptRemovedCardType custom:ecco-flow-3d-card" in inst_flat
          and inst_flat.count("whether or not the site has a protection policy") == 2)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All dashboard preservation gate checks passed.")
print("These prove the guard's rules and refusals on fictional data and the deploy tools' static wiring; the live ssh/scp reads and a "
      "real deployment are not exercised here.")
