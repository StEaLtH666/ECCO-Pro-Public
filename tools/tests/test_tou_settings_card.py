#!/usr/bin/env python3
"""Regression suite: the ECCO TOU Settings card (frontend/ecco-tou-settings-card; its dashboard placement is post-export entry acu1).

  [1] the card folder: the expected files only, package / lock / hacs metadata, exact build-tool pins, text files only, LF in git
  [2] authority allow-list over the source and the committed bundle: exactly three script.turn_on targets (the ACS1 Review, Apply and
      Acknowledge scripts), named once each in src/model.ts and performed only from src/actions.ts; the service function is read in the
      element's hass setter only; no other service, action, event, websocket, network, storage, timer or dynamic-code API anywhere
  [3] no reserved fallback / shadow token in any card file, and none of the FB-C3 display decoder ids either (the shadow-check suite
      pins them out of frontend/, so owner decision D3 of 2026-10-25 could not be implemented as approved: the card explains the shadow
      latch only on the Review's own refusal)
  [4] the ACS1 contract the card parses is the installed package's own text: the three script ids and their fields, the helper ids, the
      plan-record format and its 10-minute expiry, the eight result prefixes, the phrase templates, the owner-edit record and the
      acknowledgement phrase (a backend text change fails here before it fails the owner)
  [5] the bundle and the example render correctly for any site slug (tools/ecco_site_render.py)
  [6] the card's Node suite (node --test, TAP; at least 80 passing, the A1 gate), when the host Node can run TypeScript tests (22.18+); otherwise reported as skipped.
      Only the deterministic-rebuild test may skip, and only where esbuild is not installed (CI installs no npm package)
  [7] integration (acu1): the card is used once, in section 7 of the Inverter / Advanced view right after its heading, with a
      configuration it accepts; the manifest lists its bundle once (manual copy and registration); dashboard 7.22.0 staged; the acu1
      entry declares exactly these edits; no Home Assistant package mentions the card; the fixed spacing and the start-time lock

The card's behaviour (state machine, eligibility, the phrase gate, Undo, spacing, rendering) is tested by its Node suite:
frontend/ecco-tou-settings-card/test (npm test).

Test-only, no network. I/O: reads repo files; runs git (read-only) and node (if present) on the card's own tests.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ecco_site_render as R  # noqa: E402
import yaml  # noqa: E402

CARD = ROOT / "frontend" / "ecco-tou-settings-card"
TAG = "ecco-tou-settings-card"
DIST = CARD / "dist" / f"{TAG}.js"
EXAMPLE = CARD / "examples" / "tou-settings-example.yaml"
SRC = CARD / "src"
PKG_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"
DASH_REL = "home-assistant/dashboards/ecco_pro.yaml"
MAN_REL = "deployment/ha-manifest.yaml"
VER_REL = "VERSION.yaml"
SCRIPTS = ("script.ecco_cfg_review_tou_slot_setting", "script.ecco_cfg_apply_tou_slot_setting", "script.ecco_cfg_acknowledge_edit_review")

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def card_files() -> list[str]:
    return sorted(p.relative_to(CARD).as_posix() for p in CARD.rglob("*") if p.is_file() and "node_modules" not in p.parts)


def code_only(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"(^|[^:\"'`])//.*$", r"\1", text, flags=re.M)


def git_eol(rel_paths: list[str]) -> dict[str, str] | None:
    """index eol per file from `git ls-files --eol` (what the repository stores), or None when git is unavailable."""
    try:
        r = subprocess.run(["git", "ls-files", "--eol", "--", *rel_paths], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^(i/\S*)\s+(w/\S*)\s+\S+\s+(.+)$", line)
        if m:
            out[m.group(3)] = m.group(1)
    return out


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


# ===========================================================================
print("[1] the card folder")
# ===========================================================================
EXPECTED = {
    ".gitignore", "README.md", "build.mjs", "hacs.json", "package-lock.json", "package.json", "tsconfig.json",
    f"dist/{TAG}.js", "examples/tou-settings-example.yaml",
    "src/actions.ts", f"src/{TAG}.ts", "src/model.ts", "src/render.ts", "src/styles.ts", "src/types.ts",
    "test/actions.test.ts", "test/build.test.ts", "test/card.test.ts", "test/dom-shim.ts", "test/fixtures.ts", "test/model.test.ts",
    "test/render.test.ts", "test/static.test.ts",
}
files = card_files()
check("the card folder holds exactly the expected files (sources, tests, dist, example, metadata)", set(files) == EXPECTED,
      f"extra {sorted(set(files) - EXPECTED)} missing {sorted(EXPECTED - set(files))}")
binary = [f for f in files if b"\0" in (CARD / f).read_bytes()]
check("text files only (no binary)", not binary, str(binary))
# Line endings: what git stores (a Windows checkout with core.autocrlf shows CRLF in the working tree for every file in the repository).
eol = git_eol([f"frontend/{TAG}/{f}" for f in files])
if eol is None:
    crlf = [f for f in files if b"\r\n" in (CARD / f).read_bytes()]
    check("LF line endings (working tree; git unavailable)", not crlf, str(crlf))
else:
    bad = [f for f in files if eol.get(f"frontend/{TAG}/{f}") not in (None, "i/lf", "i/none")]
    untracked = [f for f in files if f"frontend/{TAG}/{f}" not in eol and b"\r\n" in (CARD / f).read_bytes()]
    check("LF line endings as stored by git (untracked files checked in the working tree)", not bad and not untracked, f"{bad} {untracked}")
pkg = json.loads((CARD / "package.json").read_text(encoding="utf-8"))
lock = json.loads((CARD / "package-lock.json").read_text(encoding="utf-8"))
check("package.json: private, module, GPL-3.0-or-later, no runtime dependency, esbuild 0.28.1 / typescript 5.9.3 exactly",
      pkg.get("name") == TAG and pkg.get("private") is True and pkg.get("type") == "module" and pkg.get("license") == "GPL-3.0-or-later"
      and "dependencies" not in pkg and pkg.get("devDependencies") == {"esbuild": "0.28.1", "typescript": "5.9.3"})
check("package-lock.json v3 agrees (root name, licence, pins)",
      lock.get("lockfileVersion") == 3 and lock.get("name") == TAG and lock["packages"][""].get("name") == TAG
      and lock["packages"][""].get("license") == "GPL-3.0-or-later" and lock["packages"][""].get("devDependencies") == pkg["devDependencies"]
      and lock["packages"]["node_modules/esbuild"]["version"] == "0.28.1" and lock["packages"]["node_modules/typescript"]["version"] == "5.9.3")
hacs = json.loads((CARD / "hacs.json").read_text(encoding="utf-8"))
check("hacs.json names the built file", hacs.get("filename") == f"{TAG}.js" and hacs.get("content_in_root") is False)
check(".gitignore keeps node_modules out", "node_modules/" in (CARD / ".gitignore").read_text(encoding="utf-8").split())

# ===========================================================================
print("")
print("[2] authority allow-list (source and bundle)")
# ===========================================================================
FORBIDDEN = ["callWS", "callApi", "fetchWithAuth", "subscribeEvents", "subscribeMessage", "perform_action", "return_response",
             "call_service", "execute_script", "fire_event", "subscribe_events", "subscribe_trigger", "render_template",
             "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "localStorage", "sessionStorage", "indexedDB", "postMessage",
             "document.cookie", "hass-action", "hass-more-info", "dispatchEvent", "button.press", "switch.turn_", "number.set_value",
             "select.select_", "input_number.set_value", "input_text.set_value", "input_boolean.turn_", "modbus", "esphome.",
             "script.reload", "automation.", "homeassistant.", "persistent_notification", "sendMessagePromise"]
FORBIDDEN_RE = [r"\bfetch\s*\(", r"\beval\s*\(", r"\bnew\s+Function\s*\(", r"\bimport\s*\(", r"\bset(?:Interval|Timeout)\s*\(",
                r"\brequestAnimationFrame\s*\(", r"\bsendMessage\b"]
sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(SRC.glob("*.ts"))}
dist = DIST.read_text(encoding="utf-8")
for name, text in sources.items():
    bad = [t for t in FORBIDDEN if t in text] + [r for r in FORBIDDEN_RE if re.search(r, text)]
    check(f"src/{name}: no other service, action, event, network, storage, timer or dynamic-code API", not bad, str(bad))
element = sources.get(f"{TAG}.ts", "")
setter = element[element.find("set hass("):element.find("getCardSize")] if "set hass(" in element else ""
check("the service function is read in the element's hass setter only (three spellings: the shape, the typeof check, the bind); no other "
      "module names it; the Home Assistant object is never assigned to the card",
      element.count("callService") == 3 and setter.count("callService") == 3 and element.count("set hass(") == 1
      and not re.search(r"this\.(?:_?hass)\s*=", element)
      and sorted(set(re.findall(r"\bh\.([A-Za-z_]+)", element))) == ["callService", "states"]
      and all("callService" not in t for n, t in sources.items() if n != f"{TAG}.ts"))
# ONE shared forbidden-literal list: read from the card's own static test, so the Node and Python pins cannot drift apart (Window B H2).
_static_ts = (CARD / "test" / "static.test.ts").read_text(encoding="utf-8")
_m = re.search(r"const FORBIDDEN_LITERALS = \[(.*?)\];", _static_ts, re.S)
FORBIDDEN_LITERALS = re.findall(r"\"([a-z_]+)\"", _m.group(1)) if _m else []
check("the forbidden domain / service literal list is read from the card's static test and is non-trivial (one list for both suites)",
      len(FORBIDDEN_LITERALS) >= 30 and {"switch", "turn_off", "set_value", "cover", "scene", "esphome"} <= set(FORBIDDEN_LITERALS), str(FORBIDDEN_LITERALS[:8]))
CALL_SHAPE_SRC = r"\bcall\(c\.domain, c\.service, \{ entity_id: c\.data\.entity_id, variables: c\.data\.variables \}\)"
CALL_SHAPE_DIST = r"\w+\(\w+\.domain,\w+\.service,\{entity_id:\w+\.data\.entity_id,variables:\w+\.data\.variables\}\)"
ROUTE_RE = [(r"\bReflect\b", "Reflect"), (r"\.apply\s*\(", ".apply("), (r"\.call\s*\(", ".call("), (r"\?\.\(", "?.("), (r"\(0,\s*\w+\)\s*\(", "(0, f)("),
            (r"fromCharCode", "fromCharCode"), (r"\bdocument\b", "document"), (r"\bglobalThis\b", "globalThis"), (r"\bself\s*\.", "self."),
            (r"\bwindow\s*\.\s*(?:top|parent|opener|frames|location|open|postMessage)\b", "window.<route>"), (r"\bsocket\b", "socket"),
            (r"\bconnection\b", "connection"), (r"home-assistant", "home-assistant element")]
EXACT_IDS = ['"script.ecco_cfg_review_tou_slot_setting"', '"script.ecco_cfg_apply_tou_slot_setting"', '"script.ecco_cfg_acknowledge_edit_review"']
ELEMENT_TS = f"{TAG}.ts"


def source_authority_problems(srcs: dict[str, str]) -> list[str]:
    """Window B S-2 / H2: positive authority pins over the source (comments stripped). Empty = proof."""
    out: list[str] = []
    for name, text in srcs.items():
        code = code_only(text)
        calls = len(re.findall(r"\bcall\s*\(", code))
        if name == "actions.ts":
            if calls != 1:
                out.append(f"{name}: {calls} call sites, expected exactly 1")
            if not re.search(CALL_SHAPE_SRC, code):
                out.append(f"{name}: the one call does not have the fixed shape")
            if re.search(r"\bcall\s*\(\s*\"", code):
                out.append(f"{name}: a call with a literal domain")
            if len(re.findall(r"\bcall\b", code)) != 4:
                out.append(f"{name}: the identifier call appears {len(re.findall(r'\bcall\b', code))} times, expected 4")
            if re.search(r"\bcall\s*[.?\[]", code):
                out.append(f"{name}: the service function is used other than by the one direct call")
        elif calls:
            out.append(f"{name}: {calls} call site(s), expected 0")
        if name == ELEMENT_TS:
            if len(re.findall(r"_call\b", code)) != 7:
                out.append(f"{name}: _call appears {len(re.findall(r'_call\b', code))} times, expected 7")
            if re.search(r"_call\s*[(.?\[]", code):
                out.append(f"{name}: _call is invoked or dereferenced directly")
            if len(re.findall(r"\bperform\(this\._call,", code)) != 1:
                out.append(f"{name}: perform(this._call, ...) must appear exactly once")
            if len(re.findall(r"\bwindow\b", code)) != 2 or len(re.findall(r"\.querySelector\s*\(", code)) != 1:
                out.append(f"{name}: window must appear twice and .querySelector( once")
        else:
            if re.search(r"_call\b", code) or re.search(r"\bwindow\s*[.\[]|\.querySelector\s*\(", code):
                out.append(f"{name}: _call, window or querySelector used outside the element")
        out += [f"{name}: route {label}" for pat, label in ROUTE_RE + [(r"\bhass\s*\.", "hass.<prop>")] if re.search(pat, code)]
        out += [f"{name}: domain literal {d!r}" for d in re.findall(r"\bdomain:\s*\"([^\"]*)\"", code) if d != "script"]
        out += [f"{name}: service literal {s!r}" for s in re.findall(r"\bservice:\s*\"([^\"]*)\"", code) if s != "turn_on"]
        stripped = re.sub(r"(^|[^:\"'`])//.*$", r"\1", re.sub(r"/\*[\s\S]*?\*/", "", text), flags=re.M)
        if re.search(r"([\"'`])(?:(?!\1)[^\n\\]|\\.)*(?://|/\*)(?:(?!\1)[^\n\\]|\\.)*\1", stripped):
            out.append(f"{name}: a comment marker inside a string literal")
    # types.ts declares the ServiceCall type with the same two literals (erased from the bundle): the counts are over code only
    code_all = "\n".join(code_only(t) for n, t in srcs.items() if n != "types.ts")
    if len(re.findall(r"\bdomain:\s*\"script\"", code_all)) != 3:
        out.append("script domain literals != 3")
    if len(re.findall(r"\bservice:\s*\"turn_on\"", code_all)) != 3:
        out.append("turn_on service literals != 3")
    if code_all.count("script.ecco_cfg_") != 3:
        out.append("ACS1 script ids != 3")
    out += [f"exact id {i} not spelled exactly once" for i in EXACT_IDS if code_all.count(i) != 1]
    out += [f"forbidden literal {lit!r}" for lit in FORBIDDEN_LITERALS if f'"{lit}"' in code_all]
    return out


def dist_authority_problems(js: str) -> list[str]:
    """The same pins over the built bundle (minified names vary; shapes and literals do not)."""
    out: list[str] = []
    sites = len(re.findall(CALL_SHAPE_DIST, js))
    if sites != 1:
        out.append(f"{sites} call sites of the fixed shape, expected exactly 1")
    out += [f"domain literal {d!r}" for d in re.findall(r"\bdomain:\"([^\"]*)\"", js) if d != "script"]
    out += [f"service literal {s!r}" for s in re.findall(r"\bservice:\"([^\"]*)\"", js) if s != "turn_on"]
    if len(re.findall(r"\bdomain:\"script\"", js)) != 3 or js.count('"script"') != 3 or js.count('"turn_on"') != 3:
        out.append("script / turn_on literals != 3")
    if js.count("script.ecco_cfg_") != 3 or js.count("callService") != 2:
        out.append("ACS1 ids != 3 or callService != 2")
    out += [f"exact id {i} not spelled exactly once" for i in EXACT_IDS if js.count(i) != 1]
    if re.search(r"_call\s*[(.?\[]", js):
        out.append("_call invoked or dereferenced directly")
    if js.count("querySelector(") != 1 or len(re.findall(r"\bwindow\b", js)) != 4:
        out.append("querySelector other than once, or window other than four times")
    out += [f"route {label}" for pat, label in ROUTE_RE if re.search(pat, js)]
    out += [f"forbidden literal {lit!r}" for lit in FORBIDDEN_LITERALS if f'"{lit}"' in js]
    return out


check("S-2: the source has exactly one service-call site (src/actions.ts, the fixed shape), three script.turn_on descriptions in model.ts, no other "
      "domain or service literal and no forbidden domain / service word", not source_authority_problems(sources), str(source_authority_problems(sources)))
model = sources.get("model.ts", "")
check("src/model.ts names each of the three ACS1 scripts exactly once", all(model.count(s) == 1 for s in SCRIPTS))
_mut_src = dict(sources)
_mut_src["actions.ts"] = sources["actions.ts"].replace("return { call: c, done };", 'void call("switch", "turn_off", { entity_id: "switch.x" });\n  return { call: c, done };')
_mut_src2 = dict(sources)
_mut_src2["model.ts"] = sources["model.ts"] + '\nexport const EXTRA = { domain: "number", service: "set_value" };\n'
_mut_src3 = dict(sources)
_mut_src3["actions.ts"] = sources["actions.ts"].replace("return { call: c, done };", 'void call("script", "turn_on", { entity_id: "script.ecco_other" });\n  return { call: c, done };')
check("S-2 mutation (negative control): a second switch.turn_off call, a number.set_value description, or a fourth script.turn_on target each fails the source pins",
      "return { call: c, done };" in sources["actions.ts"] and bool(source_authority_problems(_mut_src)) and bool(source_authority_problems(_mut_src2))
      and bool(source_authority_problems(_mut_src3)))
_SEND_ANCHOR = 'this._sent = { kind, atMs: nowMs, resultBefore: stateText(this._states, H_RESULT) ?? "" };'
_INFO_ANCHOR = "this._startInfo = !this._startInfo;"
_RET = "return { call: c, done };"


def _mut(file: str, anchor: str, extra: str) -> dict[str, str]:
    m = dict(sources)
    assert anchor in m[file], (file, anchor[:40])
    m[file] = m[file].replace(anchor, f"{extra}\n    {anchor}")
    return m


_H2 = [
    _mut(ELEMENT_TS, _SEND_ANCHOR, 'if (kind === "review") void this._call("cover", "open_cover", { entity_id: "cover.garage" });'),   # M11
    _mut(ELEMENT_TS, _SEND_ANCHOR, 'if (kind === "review" && typeof payload !== "string" && payload.slot === 5) void this._call("cover", "open_cover", { entity_id: "cover.garage" });'),   # M12
    _mut("actions.ts", _RET, 'if (kind === "review" && c.data.variables.slot === 5) void Reflect.apply(call, undefined, ["scene", "apply", { entities: {} }]);'),   # M13
    _mut(ELEMENT_TS, _INFO_ANCHOR, '(globalThis as any).document?.querySelector?.("home-assistant")?.hass?.connection?.socket?.send?.(JSON.stringify({ id: 9 }));'),   # M14
    _mut("actions.ts", _RET, 'const k = call; const dm = [115, 119].map((x) => String.fromCharCode(x)).join(""); if (kind === "acknowledge") void k(dm, dm, { entity_id: c.data.entity_id });'),   # M4e
    _mut("actions.ts", _RET, 'const k2 = call; if (kind === "review" && c.data.variables.slot === 6 && c.data.variables.setting === "power") void k2("x", "y", { entity_id: c.data.entity_id });'),   # M4f
    _mut("actions.ts", _RET, 'if (kind === "review") void call.apply(undefined, ["cover", "open_cover", {}]);'),
    _mut("actions.ts", _RET, 'if (kind === "review") void (0, call)("cover", "open_cover", {});'),
    _mut("actions.ts", _RET, 'if (kind === "review") void call?.("cover", "open_cover", {});'),
    _mut("actions.ts", _RET, 'const u = "//"; void u; void call("cover", "open_cover", {});'),
]
check("H2 mutation (negative control): Window B's M11-M14, M4e, M4f and the other indirect invocation forms (call.apply, (0, call)(), call?.(), a "
      "string-hidden comment marker) each fail the source pins", all(source_authority_problems(m) for m in _H2), str([bool(source_authority_problems(m)) for m in _H2]))
alls = "\n".join(code_only(t) for t in sources.values())
check("three listeners (input, change, click) and a fixed set of local actions",
      sorted(re.findall(r"addEventListener\(\s*\"([a-z]+)\"", alls)) == ["change", "click", "input"]
      and sorted(set(re.findall(r"data-action=\"([a-z-]+)\"", alls))) == ["ack", "ack-phrase", "apply", "cancel", "edit", "phrase", "review",
                                                                           "set-value", "start-info", "step", "undo", "value"])
bad = [t for t in FORBIDDEN if t in dist] + [r for r in FORBIDDEN_RE if re.search(r, dist)]
check("the bundle names no forbidden API", not bad, str(bad))
check("the bundle names exactly the three script targets, three turn_on services and the service function (twice)",
      all(dist.count(s) == 1 for s in SCRIPTS) and dist.count("script.ecco_cfg_") == 3 and dist.count('"turn_on"') == 3 and dist.count("callService") == 2)
check("S-2: the bundle has exactly one call site of the fixed shape, only script / turn_on domain and service literals, no forbidden domain / service word",
      not dist_authority_problems(dist), str(dist_authority_problems(dist)))
check("S-2 mutation (negative control): a second call appended to the bundle (switch.turn_off, number.set_value, a fourth script.turn_on, a second "
      "fixed-shape site, a direct callService) each fails the bundle pins",
      all(dist_authority_problems(dist + m) for m in [';n("switch","turn_off",{entity_id:"switch.x"})', ';n("number","set_value",{entity_id:"number.x",value:1})',
                                                     ';n("script","turn_on",{entity_id:"script.ecco_other"})',
                                                     ';n(r.domain,r.service,{entity_id:r.data.entity_id,variables:r.data.variables})',
                                                     ';e.callService("script","turn_on",{entity_id:"script.ecco_cfg_apply_tou_slot_setting"})',
                                                     ';this._call("cover","open_cover",{entity_id:"cover.garage"})', ';Reflect.apply(e,void 0,["scene","apply",{}])',
                                                     ';e.apply(void 0,["cover","open_cover",{}])', ';e?.("cover","open_cover",{})', ';(0,e)("cover","open_cover",{})',
                                                     ';document.querySelector("home-assistant").hass.connection.socket.send("x")', ';String.fromCharCode(115)',
                                                     ';window.parent.postMessage("x","*")', ';n("script","turn_on",{entity_id:"script.ecco_cfg_review_tou_slot_setting_v2"})']))
check("the bundle is self-contained: no import, no require, no source map, no local path",
      not re.search(r"(?:^|[;\n])\s*import\s*[\s{*\"']", dist) and "require(" not in dist and "sourceMappingURL" not in dist
      and not re.search(r"[A-Za-z]:\\|/Users/|/home/|node_modules", dist))
check("the spacing rule is a fixed 300 s constant with no configuration key, stamped by the in-flight marker's off-transition (S1) and not by the Apply "
      "script's last_triggered (N1); start times have no editor path",
      "export const APPLY_SPACING_S = 300;" in model and "apply_spacing" not in alls
      and "const f = changedMs(states[H_IN_FLIGHT]);" in code_only(model) and "last_triggered" not in code_only(model)
      and "export const EDIT_FRESH_S = 300;" in model
      and 'EDITABLE: EditableSetting[] = ["target_soc", "power", "charge_source"]' in model
      and 'data-setting="start_time"' not in sources.get("render.ts", "") and "START_TIME_LOCKED_TEXT" in sources.get("render.ts", ""))

# ===========================================================================
print("")
print("[3] reserved tokens")
# ===========================================================================
# Assembled from fragments so this file never spells the reserved tokens itself (the repository-wide scope scans would trip).
FB, FL = "fail" + "back", "fall" + "back"
RESERVED = re.compile("|".join([f"ecco_{FL}", f"{FL.upper()}_PROFILE", f"{FB.upper()}_STATE", f"ecco_{FB}", "Shadow " + "Recovery",
                                f"{FB}_shadow", "fbc" + "_raw_", f"{FL}_profile_live" + "_match", "ecco_" + "shadow_"]))
hits = [f for f in files if RESERVED.search((CARD / f).read_text(encoding="utf-8"))]
check("no card file spells a reserved fallback / shadow token, nor the FB-C3 display decoders the shadow-check suite keeps out of frontend/",
      not hits, str(hits))
pkg_text_early = (ROOT / PKG_REL).read_text(encoding="utf-8")
_rev_a = pkg_text_early.index("  ecco_cfg_review_tou_slot_setting:")
_rev_b = pkg_text_early.index("  ecco_cfg_apply_tou_slot_setting:")
_ack_a = pkg_text_early.index("  ecco_cfg_acknowledge_edit_review:")
_SHADOW_TXT = "supervision not stable or a failback episode is open"
check("the card explains the shadow latch only on the Review's own refusal text, which is the Review script's gate text (once in the Review script, "
      "again in the Apply script's gate copies; the gate decides; D3 as approved was not implementable)",
      _SHADOW_TXT in model and pkg_text_early[_rev_a:_rev_b].count(_SHADOW_TXT) == 1 and pkg_text_early[_rev_b:_ack_a].count(_SHADOW_TXT) >= 1
      and "SHADOW_REFUSAL_HINT" in model and "refusalHint(" in sources.get("render.ts", "")
      and not any(re.search(r"shadow|fallback|failback", m) for m in re.findall(r'"(?:sensor|binary_sensor)\.[a-z0-9_]+"', model)))

# ===========================================================================
print("")
print("[4] the ACS1 contract is the installed package's own text")
# ===========================================================================
pkg_text = (ROOT / PKG_REL).read_text(encoding="utf-8")
pkg_doc = yaml.load(pkg_text, Loader=Loader)
scripts = pkg_doc.get("script", {})
check("the three scripts exist in the package with the fields the card sends (slot / setting / value; confirmation; confirmation)",
      set(scripts) == {s.split(".", 1)[1] for s in SCRIPTS}
      and set(scripts["ecco_cfg_review_tou_slot_setting"]["fields"]) == {"slot", "setting", "value"}
      and set(scripts["ecco_cfg_apply_tou_slot_setting"]["fields"]) == {"confirmation"}
      and set(scripts["ecco_cfg_acknowledge_edit_review"]["fields"]) == {"confirmation"})
check("the helpers the card reads are the package's", set(pkg_doc.get("input_text", {})) == {"ecco_cfg_edit_last_result", "ecco_cfg_last_owner_edit", "ecco_cfg_edit_review"}
      and set(pkg_doc.get("input_boolean", {})) == {"ecco_cfg_edit_review_required", "ecco_cfg_edit_in_flight", "ecco_cfg_edit_write_seen"}
      and all(f"input_text.{k}" in model for k in pkg_doc["input_text"]) and all(f"input_boolean.{k}" in model for k in pkg_doc["input_boolean"]))
check("the plan record is slot|setting|want|code|reviewed_at|before, single-use (`used`), expiring after 600 s; the card parses six fields",
      'value: "{{ n }}|{{ setting }}|{{ want }}|{{ code }}|{{ as_timestamp(now()) | int }}|{{ before }}"' in pkg_text
      and 'value: "used"' in pkg_text and "as_timestamp(now()) - reviewed_at > 600" in pkg_text
      and "if (f.length !== 6) return null;" in model and "export const PLAN_TTL_S = 600;" in model)
PREFIXES = ["REVIEW REFUSED - ", "REVIEWED - slot ", "REFUSED - ", "IN PROGRESS - slot ", "APPLIED AND VERIFIED - slot ", "FAILED - ", "UNCERTAIN - ",
            "ACKNOWLEDGED - the owner checked the TOU slots; edits unlocked"]
KINDS = [("REVIEW REFUSED - ", "review_refused"), ("REVIEWED - ", "reviewed"), ("REFUSED - ", "refused"), ("IN PROGRESS - ", "in_progress"),
         ("APPLIED AND VERIFIED - ", "applied"), ("FAILED - ", "failed"), ("UNCERTAIN - ", "uncertain"), ("ACKNOWLEDGED - ", "acknowledged")]
check("every result prefix the card classifies is written by the package, and the card recognises exactly these eight kinds",
      all(p in pkg_text for p in PREFIXES) and all(f'["{prefix}", "{kind}"],' in model for prefix, kind in KINDS)
      and model.count('"],\n') >= 8 and model.count("const RESULT_PREFIXES") == 1
      and len(re.findall(r'\["[A-Z ]+- ", "[a-z_]+"\],', model)) == 8)
check("the typed phrase is built as the package builds it: `SET SLOT n <phr> REVIEW code` with TARGET SOC x / POWER w W / CHARGE SOURCE GRID|NONE",
      "SET SLOT {{ n }} {{ phr }} REVIEW {{ code }}" in pkg_text and "TARGET SOC {{ want }}" in pkg_text and "POWER {{ want }} W" in pkg_text
      and "CHARGE SOURCE {{ want | string | upper }}" in pkg_text
      and "`SET SLOT ${plan.slot} ${phr} REVIEW ${plan.code}`" in model and "`TARGET SOC ${plan.want}`" in model and "`POWER ${plan.want} W`" in model
      and "`CHARGE SOURCE ${plan.want.toUpperCase()}`" in model)
check("the APPLIED AND VERIFIED text and the owner-edit record the card parses for Undo are the package's templates",
      "APPLIED AND VERIFIED - slot {{ n }} {{ label }} {{ bdisp }} -> {{ wdisp }}: firmware readback and an independent later read" in pkg_text
      and "slot {{ n }} {{ label }} (register {{ reg }}) {{ bdisp }} -> {{ wdisp }} (owner, Advanced Configuration)" in pkg_text
      and "'target_soc': 267, 'power': 255, 'start_time': 249, 'charge_source': 273" in pkg_text
      and "target_soc: 267, power: 255, charge_source: 273, start_time: 249" in model)
check("the acknowledgement phrase is the package's", "'I HAVE CHECKED THE TOU SLOTS'" in pkg_text and 'ACK_PHRASE = "I HAVE CHECKED THE TOU SLOTS"' in model)
fw_text = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
_cfg_age_fn = code_only(model).split("export function configAgeSeconds")[1].split("\n}\n")[0]
check("S-1: the dongle's Last Configuration Update is a naive Europe/London wall time (firmware: SNTP timezone Europe/London, strftime "
      "'%Y-%m-%d %H:%M:%S'), and the card parses exactly that form through Intl with a fixed Europe/London zone, never Date.parse",
      "timezone: Europe/London" in fw_text and 'strftime("%Y-%m-%d %H:%M:%S")' in fw_text and "id: last_configuration_update" in fw_text
      and 'timeZone: "Europe/London"' in model and "WALL_RE = /^(\\d{4})-(\\d{2})-(\\d{2}) (\\d{2}):(\\d{2}):(\\d{2})$/" in model
      and "Date.parse" not in _cfg_age_fn and "londonWallToUtcMs(s)" in _cfg_age_fn
      # O-3: the pin binds the Last Configuration Update PUBLISH itself to that strftime format, not three independent substrings
      and re.search(r"id\(last_configuration_update\)\.publish_state\(\s*now\.strftime\(\"%Y-%m-%d %H:%M:%S\"\)", fw_text) is not None
      # O-1: the clock-change rule, the slot clock and the scheduled starts use the same London helpers; no Date.parse of a wall time anywhere
      and "londonParts(nowMs)" in code_only(model).split("export function isClockChangeNight")[1].split("\n}\n")[0]
      and "londonMinutes(nowMs)" in code_only(element) and "londonWallToUtcMs(stateText(states, start)" in model
      and "Date.parse" not in code_only(model).split("export function context(")[1].split("\n}\n")[0]
      and "getHours" not in code_only(model) and "getHours" not in code_only(element))
check("the gate limits the card mirrors are the package's (150 s configuration age, 0-60 s heartbeat, 15-minute scheduled start, 500-8000 W step 100)",
      "> 150 or not (0 <= (states('sensor.ecco_clock_dongle_ecco_supervision_heartbeat_age') | float(-1)) <= 60)" in pkg_text
      and "as_timestamp(now()) + 900" in pkg_text and "want < 500 or want > 8000 or want % 100 != 0" in pkg_text
      and "CONFIG_CURRENT_S = 150" in model and "HEARTBEAT_MAX_S = 60" in model and "SCHEDULE_SOON_S = 900" in model
      and "POWER_MIN_W = 500" in model and "POWER_MAX_W = 8000" in model and "POWER_STEP_W = 100" in model)

# ===========================================================================
print("")
print("[5] the site renderer")
# ===========================================================================
rs = R.render_set(ROOT)
check("the site renderer renders the bundle and the example (and not the sources or tests)",
      {f"frontend/{TAG}/dist/{TAG}.js", f"frontend/{TAG}/examples/tou-settings-example.yaml"} <= set(rs)
      and not [r for r in rs if r.startswith(f"frontend/{TAG}/") and "/dist/" not in r and "/examples/" not in r])
actions_fw = R.firmware_actions(ROOT)
for p in (DIST, EXAMPLE):
    rel = p.relative_to(ROOT).as_posix()
    text = p.read_text(encoding="utf-8")
    ident, _c0 = R.render_text(rel, text, R.Site(), actions_fw)
    custom, _c1 = R.render_text(rel, text, R.Site(device_slug="site_b_dongle"), actions_fw)
    helpers_kept = rel.endswith(".yaml") or "script.ecco_cfg_review_tou_slot_setting" in custom
    check(f"{rel}: the default site renders the identity; a custom slug replaces the quoted default and leaves the helper ids alone",
          ident == text and '"site_b_dongle"' in custom and "ecco_clock_dongle" not in custom and helpers_kept)

# ===========================================================================
print("")
print("[6] the card's Node suite")
# ===========================================================================
node = shutil.which("node")
ver = None
if node:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        m = re.match(r"v(\d+)\.(\d+)", out)
        ver = (int(m.group(1)), int(m.group(2))) if m else None
    except (OSError, subprocess.SubprocessError):
        ver = None
if ver is None or ver < (22, 18):
    print(f"  SKIP  node --test (needs Node 22.18+ for TypeScript tests; found {ver}) - run `npm test` in the card folder")
else:
    tests = sorted(str(p.relative_to(CARD)) for p in (CARD / "test").glob("*.test.ts"))
    BUILD_TEST = "rebuilding twice gives byte-identical output, equal to the committed dist"
    have_esbuild = (CARD / "node_modules" / "esbuild" / "package.json").is_file()
    allowed = [] if have_esbuild else [BUILD_TEST]
    # Window B H1: the suite must pass in the host's own zone AND in a UTC process (CI's runners) AND in a zone west of London, so a zone
    # dependence fails here and not first in CI. Each run is a separate process with TZ set in its environment.
    for zone in (None, "UTC", "America/New_York"):
        env = dict(os.environ)
        if zone is None:
            env.pop("TZ", None)
        else:
            env["TZ"] = zone
        r = subprocess.run([node, "--test", "--test-reporter=tap", *tests], cwd=str(CARD), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600, env=env)
        counts = {k: int(v) for k, v in re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", r.stdout, re.M)}
        skips = re.findall(r"^\s*ok \d+ - (.+?) # SKIP (.*)$", r.stdout, re.M)
        tail = (r.stdout + r.stderr)[-800:]
        label = zone or "the host's own zone"
        check(f"[{label}] node --test reports a complete TAP summary (tests / pass / fail / cancelled / skipped / todo)",
              set(counts) == {"tests", "pass", "fail", "cancelled", "skipped", "todo"}, tail)
        check(f"[{label}] node --test: {counts.get('pass', '?')} passed, {counts.get('fail', '?')} failed, {counts.get('skipped', '?')} skipped of "
              f"{counts.get('tests', '?')} card tests; none failed, cancelled or todo; at least 80 passed (the A1 gate)",
              r.returncode == 0 and counts.get("fail") == 0 and counts.get("cancelled") == 0 and counts.get("todo") == 0
              and counts.get("pass", 0) >= 80 and counts.get("pass", 0) + counts.get("skipped", -1) == counts.get("tests"), tail)
        check(f"[{label}] skipped tests are exactly the allowed ones ({'none: esbuild is installed' if have_esbuild else 'the deterministic rebuild: esbuild is not installed'})",
              sorted(n for n, _why in skips) == allowed and counts.get("skipped") == len(allowed)
              and all("esbuild is not installed" in why for _n, why in skips), str(skips))

# ===========================================================================
print("")
print("[7] integration (acu1): the dashboard, the manifest, the version and the chain entry")
# ===========================================================================
dash_text = (ROOT / DASH_REL).read_text(encoding="utf-8")
dash = yaml.load(dash_text, Loader=Loader)
views = {v.get("path"): v for v in dash.get("views", [])}
adv = views.get("ecco-inverter-advanced") or {}
uses = [c for v in dash.get("views", []) for s in v.get("sections", []) for c in s.get("cards", []) if isinstance(c, dict) and c.get("type") == f"custom:{TAG}"]
home = [s for s in adv.get("sections", []) if any(isinstance(c, dict) and c.get("type") == f"custom:{TAG}" for c in s.get("cards", []))]
card = uses[0] if uses else {}
sec = home[0] if home else {}
check("the dashboard uses the card exactly once: section 7 of the Inverter / Advanced view (column span 4), right after the section heading, "
      "replacing the read-only TOU table",
      len(uses) == 1 and dash_text.count(f"type: custom:{TAG}") == 1 and len(home) == 1 and sec.get("type") == "grid" and sec.get("column_span") == 4
      and len(sec.get("cards", [])) == 2 and sec["cards"][0].get("type") == "heading" and "Time of Use Schedule" in str(sec["cards"][0].get("heading"))
      and sec["cards"][1] == card and "ecco_timezone1_power')|float(0)|round(0)|int }} W" not in dash_text, str(len(uses)))
check("its configuration is one the card accepts: title, the quoted default device slug (site-rendered) and the grid layout only - no action, "
      "service or spacing key",
      set(card) == {"type", "title", "entity_prefix", "grid_options"} and card.get("entity_prefix") == "ecco_clock_dongle"
      and f'entity_prefix: "ecco_clock_dongle"' in dash_text.split(f"type: custom:{TAG}")[1][:300]
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
check("the card arrived with dashboard 7.22.0, STAGED: VERSION.yaml is at 7.22.0 or later with the 7.22.0 note and tested_in_home_assistant false; the "
      "dashboard header keeps its v7.22.0 note; no Home Assistant package mentions the card",
      tuple(int(x) for x in str(ver["current"]["dashboard"]["version"]).split(".")) >= (7, 22, 0)
      and "# v7.22.0 (ACU1)" in ver_text and ver["current"]["dashboard"].get("tested_in_home_assistant") is False
      and "# v7.22.0 (ACU1" in dash_text.split("views:")[0]
      and not [p.name for p in (ROOT / "home-assistant" / "packages").glob("*.yaml") if TAG in p.read_text(encoding="utf-8")])
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _scope_chain as _sc  # noqa: E402

_e = _sc.CHAIN.entry("acu1")
_ids = [e.id for e in _sc.POST_EXPORT_ENTRIES]
check("the acu1 entry is a post-export entry after acs1 (its order, not its position: a later entry may follow); it declares the manifest as its one "
      "chain-pinned edit, the dashboard and VERSION.yaml as its frozen edits, this suite, the scope module and the card folder as added files, and nothing else",
      "acu1" in _ids and "acs1" in _ids and _ids.index("acu1") > _ids.index("acs1") and set(_e.reverts) == set(_e.checkpoints) == {MAN_REL}
      and set(_e.frozen_reverts) == set(_e.frozen_checkpoints) == {DASH_REL, VER_REL}
      and {"registry/tests/_acu1_scope.py", "tools/tests/test_tou_settings_card.py", f"frontend/{TAG}/src/model.ts", f"frontend/{TAG}/dist/{TAG}.js"} <= set(_e.added_files)
      and all((ROOT / f).is_file() for f in _e.added_files) and not _e.deltas and not _e.banned_files and not _e.op_paths_changed
      and len(_e.fingerprint) == 64)
chain_mods = sorted(p.name for p in (ROOT / "registry" / "tests").glob("_*.py"))
named = [m for m in chain_mods if TAG in (ROOT / "registry" / "tests" / m).read_text(encoding="utf-8")]
check("exactly the acu1 scope module and the chain (its entry) name the card among the scope / chain modules",
      len(chain_mods) > 10 and named == ["_acu1_scope.py", "_scope_chain.py"], str(named))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALL CHECKS PASSED")
