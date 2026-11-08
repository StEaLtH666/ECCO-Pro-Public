#!/usr/bin/env python3
"""Static pin suite: the ECCO Intelligence card (frontend/ecco-intelligence-card), its standalone dashboard
(home-assistant/dashboards/ecco_intelligence.yaml), its presentation package (home-assistant/packages/ecco_intelligence.yaml)
and the two companion packages the post-export entry isp1 adds with it (ecco_intelligence_prefs.yaml, the raise-only reserve
helper, and ecco_intelligence_dashboard.yaml, the dashboard's registration). The package's behaviour suite
(home-assistant/tests/test_ecco_intelligence_package.py) drives the package; this suite keeps the static pins and the scans
that suite does not hold.

CI runs no Node, so the card's Node suite (frontend/ecco-intelligence-card/test, local evidence) is pinned here statically:

  [1] the card folder: the expected files only, text only, LF as stored by git, package.json (private, module,
      GPL-3.0-or-later, no dependency of any kind), no MIT licence, no binary
  [2] no write path: no service, websocket, network, storage, timer-other-than-the-one-tick, event or dynamic-code API in the
      module; hass is read for `states` only, never through a computed key; no computed key and no string-literal
      concatenation that could assemble an API name; every `${...}` in the renderers is escaped or one fixed raw
      interpolation; no URL or external resource; the preview fetches only the fixtures, in place
  [3] the contract: the default entity ids equal ENTITY_IDS; the contract version, mode, statuses, items, units, tariff
      provenances, data-quality states and decision titles equal intelligence/advisory_contract.py / site_decisions.py; every
      attribute the card reads is a contract attribute (RECORDED_ATTRIBUTES | UNRECORDED_ATTRIBUTES), read through att() with
      a literal name; the block keys it reads are the contract's; the contract_version guard (a non-blank version) and the
      null rule are in place (itemView returns before any value for a non-OK item; figures withheld while expired, clock
      ahead or the watchdog reads off; the diagnostic entities only from the same publish)
  [4] the package: it parses; exactly the pause helper (no `initial:`), the watchdog and three automations whose keys are a
      fixed allowlist and whose `actions` are exactly one {action, data} node: persistent_notification.create with fixed
      ecco_intel_ ids; the triggers and conditions pinned (start triggers re-check their fault by a template condition); no
      dismiss, no recorder block, no other entity; the PROPOSED thresholds of gate G8; the two companion packages present
  [5] the dashboard: it parses; one view; the custom card once with the contract ids, the pause only as a core tile card, the
      watchdog in a core entities card, a core markdown fallback; no service call, script, navigation or URL; contract ids only
  [6] tokens: no reserved fallback / recovery token, no 3D-card literal, no vestigial automation-mode id, no device slug, no
      tariff placeholder or 13-digit number, no workstation path, e-mail, private address or MAC in any of these files (the
      card, the dashboard, the three packages and their two suites included)
  [7] the site render (tools/ecco_site_render.py) leaves the dashboard and the three packages byte-identical for any site
  [8] docs/intelligence/UI_DESIGN.md names the contract, its ids and the I-D labels, records the 3D Overview link as
      dropped for v0.1 (without the 3D card's literal name), and says the header names the next refresh (next_run_at)
  [9] scope: none of this is in the production dashboard; the manifest and VERSION.yaml name it only in isp1's stanzas and
      intelligence block
  [10] cross-stream: the real SHADOW cycle (synthetic inputs, a verified tariff) publishes its tariff, value and plan
      blocks in shapes the card reads; the card's readers are pinned verbatim, and a Python mirror of them reads the
      blocks as Home Assistant would hold them (CCR-INT-1)

Test-only, no network, no Node. I/O: reads repo files; runs `git ls-files --eol` (read-only); runs the pure SHADOW cycle
on the shared synthetic fixtures (intelligence/tests).
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import ecco_site_render as R  # noqa: E402
import yaml  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402

TAG = "ecco-intelligence-card"
CARD = ROOT / "frontend" / TAG
JS_REL = f"frontend/{TAG}/{TAG}.js"
PKG_REL = "home-assistant/packages/ecco_intelligence.yaml"
DASH_REL = "home-assistant/dashboards/ecco_intelligence.yaml"
HA_TEST_REL = "home-assistant/tests/test_ecco_intelligence_package.py"
REG_REL = "home-assistant/packages/ecco_intelligence_dashboard.yaml"
PREFS_REL = "home-assistant/packages/ecco_intelligence_prefs.yaml"
PREFS_TEST_REL = "home-assistant/tests/test_ecco_intelligence_prefs_package.py"
DOC_REL = "docs/intelligence/UI_DESIGN.md"
SELF_REL = "tools/tests/test_intelligence_card.py"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """JavaScript without comments (block comments, then line comments that are not inside a URL or a string start)."""
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"(^|[^:'\"`\\])//.*$", r"\1", text, flags=re.M)


def yaml_code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def git_eol(rels: list[str]) -> dict[str, str] | None:
    try:
        r = subprocess.run(["git", "-c", "gc.auto=0", "ls-files", "--eol", "--", *rels], cwd=str(ROOT), capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^(i/\S*)\s+(w/\S*)\s+\S+\s+(.+)$", line)
        if m:
            out[m.group(3)] = m.group(1)
    return out


def js_object(text: str, name: str) -> dict[str, str]:
    """`export const NAME = Object.freeze({ key: 'value', ... })` with string values, as a dict."""
    m = re.search(rf"export const {name} = Object\.freeze\(\{{(.*?)\}}\);", text, re.S)
    return dict(re.findall(r"""['"]?([\w-]+)['"]?\s*:\s*'([^']*)'""", m.group(1))) if m else {}


def js_list(text: str, name: str) -> list[str]:
    m = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", text, re.S)
    return re.findall(r"'([^']*)'", m.group(1)) if m else []


def js_function(text: str, name: str) -> str:
    """The body of a top-level `function name(` / `export function name(` (to the next top-level declaration)."""
    m = re.search(rf"^(?:export )?function {name}\([\s\S]*?^\}}", text, re.M)
    return m.group(0) if m else ""


# =====================================================================================================================
print("[1] the card folder")
# =====================================================================================================================
EXPECTED = {"README.md", f"{TAG}.js", "package.json", "preview/index.html", "test/core.test.mjs", "test/element.test.mjs",
            "test/helpers.mjs", "test/minidom.mjs", "test/render.test.mjs", "test/static.test.mjs"}
files = sorted(p.relative_to(CARD).as_posix() for p in CARD.rglob("*") if p.is_file())
check("the card folder holds exactly the module, README, package.json, the preview and the Node suite (no build, lockfile or hacs file)",
      set(files) == EXPECTED, f"extra {sorted(set(files) - EXPECTED)} missing {sorted(EXPECTED - set(files))}")
raw = {f: (CARD / f).read_bytes() for f in files}
check("text files only (no NUL byte, no binary extension)", not [f for f, b in raw.items() if b"\0" in b]
      and not [f for f in files if re.search(r"\.(png|jpe?g|gif|webp|ico|bmp|woff2?|ttf|otf|wasm|map|zip|gz)$", f, re.I)])
eol = git_eol([f"frontend/{TAG}/{f}" for f in files])
if eol is None:
    check("LF line endings (working tree; git unavailable)", not [f for f, b in raw.items() if b"\r" in b])
else:
    bad = [f for f in files if eol.get(f"frontend/{TAG}/{f}") not in (None, "i/lf")]
    untracked_crlf = [f for f in files if f"frontend/{TAG}/{f}" not in eol and b"\r" in raw[f]]
    check("LF line endings as stored by git (untracked files checked in the working tree)", not bad and not untracked_crlf, f"{bad} {untracked_crlf}")
pkg = json.loads(raw["package.json"]) if "package.json" in raw else {}
check("package.json: the card's name, private, an ES module, GPL-3.0-or-later, no dependency of any kind",
      pkg.get("name") == TAG and pkg.get("private") is True and pkg.get("type") == "module" and pkg.get("license") == "GPL-3.0-or-later"
      and not [k for k in pkg if "ependencies" in k], str({k: pkg.get(k) for k in ("name", "private", "type", "license")}))
all_card_text = {f: b.decode("utf-8") for f, b in raw.items()}
check("the README states GPL-3.0-or-later; no file declares an MIT licence",
      "GPL-3.0-or-later" in all_card_text.get("README.md", "")
      and not [f for f, t in all_card_text.items() if re.search(r"\bMIT\b", t)])

# =====================================================================================================================
print("")
print("[2] no write path")
# =====================================================================================================================
js = all_card_text.get(f"{TAG}.js", "")
code = code_only(js)
FORBIDDEN = ["callService", "callWS", "callApi", "sendMessage", "subscribeEvents", "subscribeMessage", "fetchWithAuth", "XMLHttpRequest",
             "WebSocket", "EventSource", "sendBeacon", "localStorage", "sessionStorage", "indexedDB", "postMessage", "document.cookie",
             "perform_action", "call_service", "call-service", "hass-action", "hass-more-info", "dispatchEvent", "button.press",
             "persistent_notification", "turn_on", "turn_off", "toggle", "set_value", "select_option", "connection", "Reflect",
             "globalThis", "document", "navigator", "location", "history.", "open(", "execCommand"]
FORBIDDEN_RE = [r"\bfetch\s*\(", r"\beval\s*\(", r"\bnew\s+Function\b", r"\bimport\s*\(", r"\.press\s*\(", r"\bsetTimeout\s*\(",
                r"\brequestAnimationFrame\s*\(", r"\bFunction\s*\(", r"\bwindow\s*\.\s*(?!customCards\b)\w+"]
hits = [t for t in FORBIDDEN if t in code] + [r for r in FORBIDDEN_RE if re.search(r, code)]
check("the module (comments stripped) names no service, websocket, network, storage, event, navigation or dynamic-code API", not hits, str(hits))
check("exactly one timer: the re-render tick (setInterval once, cleared on disconnect)",
      len(re.findall(r"\bsetInterval\s*\(", code)) == 1 and len(re.findall(r"\bclearInterval\s*\(", code)) == 1)
check("hass is read for `states` only, in one place, and never replaced by a connection",
      sorted(set(re.findall(r"\bh\.(\w+)", code))) == ["states"] and code.count("const h = this._hass;") == 1
      and not re.search(r"hass\??\.(?!states\b)\w", code) and len(re.findall(r"this\._hass\b", code)) == 4)
_STATES_BODY = "  _states() {\n    const h = this._hass;\n    return h && h.states && typeof h.states === 'object' ? h.states : {};\n  }\n"
_hass_lines = [code[code.rfind("\n", 0, m.start()) + 1:code.find("\n", m.end())].strip()
               for m in re.finditer(r"\bhass\b|this\._hass\b|this\.hass\b", code)]
check("the hass object is named only in the constructor, the getter, the setter and _states(), which reads `states` alone (no alias "
      "of it can reach anything else)",
      _hass_lines == ["this._hass = null;", "get hass() {", "return this._hass;", "set hass(hass) {", "set hass(hass) {",
                      "this._hass = hass;", "this._hass = hass;", "const h = this._hass;"]
      and code.count(_STATES_BODY) == 1 and code.count("  set hass(hass) {\n    this._hass = hass;\n    if (!this._config) return;\n") == 1
      and not re.search(r"\bh\s*(?:\?\.|[.\[(])", code.replace(_STATES_BODY, "")),
      str(_hass_lines))
check("no computed member access on the hass object (h[...], hass[...], this._hass[...]): an API name cannot be reached by a "
      "computed key", not re.search(r"\b(?:h|hass|_hass)\s*\??\.?\s*\[", code), str(re.findall(r"\b(?:h|hass|_hass)\s*\??\.?\s*\[.{0,30}", code)))
_member_keys = re.findall(r"[\w)\]}]\s*\[([^\]\n]*)\]", code)
check("no computed member key anywhere is a string literal or a string concatenation (so no API name is assembled from pieces)",
      not [k for k in _member_keys if re.search(r"['\"`]|\w\s*\+\s*\w", k)], str([k for k in _member_keys if re.search(r"['\"`]|\w\s*\+\s*\w", k)]))
check("no string literal is concatenated with another string literal anywhere in the module ('call' + 'Service' and the like)",
      not re.search(r"'[^'\n]*'\s*\+\s*['\"`]|\"[^\"\n]*\"\s*\+\s*['\"`]", code))


def _scan_code(t: str, i: int, out: list) -> int:
    """Skip JavaScript code from i to the `}` that closes the current `${` (strings and nested templates skipped)."""
    depth = 0
    while i < len(t):
        c = t[i]
        if c in "'\"":
            j = i + 1
            while t[j] != c:
                j += 2 if t[j] == "\\" else 1
            i = j + 1
            continue
        if c == "`":
            i = _scan_tpl(t, i + 1, out)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0:
                return i
            depth -= 1
        i += 1
    return i


def _scan_tpl(t: str, i: int, out: list) -> int:
    while True:
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if t.startswith("${", i):
            j = _scan_code(t, i + 2, out)
            out.append(t[i + 2:j])
            i = j + 1
            continue
        i += 1


def interpolations(t: str) -> list[str]:
    """Every `${...}` expression of every template literal in t (nested ones included), as source text."""
    out: list[str] = []
    _scan_code(t, 0, out)
    return out


# the renderers: section 5 after esc() (its regex holds quote characters), to the stylesheet
_r0, _r1 = code.find("export function makeFormatters("), code.find("export const STYLE = `")
renderers = code[_r0:_r1] if 0 <= _r0 < _r1 else ""
# an interpolation is safe when it is an escaping or escaped-markup call (esc / fig / codeText / callout / a render* function, each
# pinned here or checked by these rules) or exactly one of these raw expressions: numbers, fixed class / tone words, markup already
# built from checked templates, list() over markup built from checked templates. Anything else (an engine string reaching the
# markup without esc, for example `${b.text || b.code}`) fails, and adding a raw interpolation is a reviewed change to this list.
SAFE_CALL = re.compile(r"^(?:esc|fig|codeText|callout|renderHeader|renderFooter|renderTariff|renderHistory|renderDrill|renderValue|"
                       r"renderQuality|renderChargeTarget)\(")
RAW_INTERPOLATIONS = {
    "m", "h", "m % 60", "Math.floor(h / 24)", "Math.round(value)", "(Math.round(value * 10) / 10).toFixed(1)", "value.toFixed(2)",
    "value.toFixed(1)", "cls", "cls ? ` ${cls}` : ''", "r", "rows.map((r) => `<li>${r}</li>`).join('')", "b.text ? ` ${esc(b.text)}` : ''",
    "copy.tone", "vm.nextMs !== null && vm.nextMs > vm.nowMs ? ` · next refresh ${esc(env.time(vm.nextMs))}` : ''", "badge", "pill",
    "age", "tone", "body ? `<p>${esc(body)}</p>` : ''", "v.blockers.map((b) => `<li>${esc(b.text || b.code)}</li>`).join('')",
    "extra.join(' · ')", "extra.length ? ` · ${extra.join(' · ')}` : ''", "body", "isForecast ? '~' : ''",
    "figure(v.value, v.unit)", "main", "conf", "band", "more", "val", "env.time(t.window[0])", "env.time(t.window[1])",
    "figure(t.price[0], 'p/kWh')", "figure(t.price[1], 'p/kWh')", "figure(lo, 'GBP')", "figure(hi, 'GBP')",
    "list(vm.value.assumptions.map(esc))", "Math.round(a.age)", "Math.round(a.limit)",
    "vm.numbersAllowed ? list(rows) : `<p class=\"muted\">${esc(TEXT.notCurrent)}</p>`",
    "v.reasons.map((c) => `<code>${esc(c)}</code>`).join(', ')", "Math.round(a.coverage * 100)", "parts.join(', ')",
    "parts.length ? `<p>${parts.join(', ')}</p>` : `<p class=\"muted\">${esc(TEXT.none)}</p>`",
    "vm.engineVersion ? ` · engine ${esc(vm.engineVersion)}` : ''", "open.has('drill') ? ' open' : ''", "list(reasons)",
    "list(conf)", "list(blocked)", "list(openDec)", "acc", "meta", "open.has('history') ? ' open' : ''", "list(rows)", "note", "hint",
    "banner", "list(vm.selfTest.map((c) => `<code>${esc(c.code)}</code> ${esc(c.result)}`))",
    "list(vm.blockers.map((b) => esc(b.text || b.code)))", "parts.join('')",
    "rows.filter((v) => ADVICE_ITEMS.includes(v.key)).map(itemRow).join('')",
    "rows.filter((v) => FORECAST_ITEMS.includes(v.key)).map(itemRow).join('')",
}
_interp = interpolations(renderers)
_unsafe = sorted({e for e in _interp if not SAFE_CALL.match(e) and e not in RAW_INTERPOLATIONS})
check("every ${...} in the renderers goes through esc / fig / codeText / callout / a render* function, or is one of the fixed raw "
      "interpolations (so removing an esc() is caught here, not only by the Node suite)",
      len(_interp) > 100 and not _unsafe, str(_unsafe[:6]))
_pushes = re.findall(r"\.push\(\s*(\S{0,12})", renderers)
check("every markup piece pushed by a renderer is a template literal, a callout() or a render* call (never a bare engine value)",
      _pushes and all(p.startswith(("`", "callout(", "render")) for p in _pushes), str(sorted(set(_pushes))))
check("fig() and codeText() escape everything they are given; list() is called only with pre-escaped markup (the raw list above)",
      "const fig = (key, text, cls = '') => `<span class=\"fig${cls ? ` ${cls}` : ''}\" data-fig=\"${esc(key)}\">${esc(text)}</span>`;" in renderers
      and "const codeText = (b) => `<code>${esc(b.code)}</code>${b.text ? ` ${esc(b.text)}` : ''}`;" in renderers)
check("no URL, @import, url(), font-face, image, link or script in the module", not re.search(r"https?://|@import|url\(|@font-face|<img|<link|<script", js, re.I))
check("the module registers the element once (guarded) and pushes one card-picker entry",
      code.count("customElements.define(TAG, EccoIntelligenceCard)") == 1 and "if (!customElements.get(TAG))" in code
      and code.count("window.customCards.push(") == 1)
prev = all_card_text.get("preview/index.html", "")
prev_code = re.sub(r"<!--[\s\S]*?-->", "", prev)
check("the preview loads the real module and fetches only the golden fixtures by relative path (no copy, no external URL)",
      "import { TAG, DEFAULT_ENTITIES } from '../ecco-intelligence-card.js';" in prev_code
      and len(re.findall(r"\bfetch\s*\(", prev_code)) == 1 and "fetch(`${FIXTURE_DIR}${name}.json`)" in prev_code
      and "const FIXTURE_DIR = '../../../intelligence/tests/fixtures/advisory_contract/';" in prev_code
      and not re.search(r"https?://|<link|@import|url\(|<script[^>]+src=", prev_code)
      and not [t for t in ("callService", "callWS", "XMLHttpRequest", "WebSocket", "localStorage") if t in prev_code])
tests_text = "\n".join(t for f, t in all_card_text.items() if f.startswith("test/"))
check("the Node suite reads the fixtures in place (path to intelligence/tests/fixtures/advisory_contract) and holds no copy",
      "'intelligence', 'tests', 'fixtures', 'advisory_contract'" in tests_text and '"entities"' not in tests_text
      and "fixture00000hash" not in tests_text)

# =====================================================================================================================
print("")
print("[3] the contract")
# =====================================================================================================================
defaults = js_object(js, "DEFAULT_ENTITIES")
check("the default entity ids are exactly the contract's ENTITY_IDS", defaults == dict(ac.ENTITY_IDS),
      str(set(defaults.items()) ^ set(ac.ENTITY_IDS.items())))
consts = dict(re.findall(r"^export const (CONTRACT_VERSION|MODE) = '([^']*)';$", js, re.M))
check("CONTRACT_VERSION and MODE equal the contract's", consts == {"CONTRACT_VERSION": ac.CONTRACT_VERSION, "MODE": ac.MODE}, str(consts))
check("the status list (in precedence order), the null-rule statuses and the item statuses equal the contract's",
      js_list(js, "SYSTEM_STATUSES") == list(ac.SystemStatus.PRECEDENCE) and set(js_list(js, "NULL_STATUSES")) == set(ac.SystemStatus.NULL)
      and len(js_list(js, "NULL_STATUSES")) == len(ac.SystemStatus.NULL) and js_list(js, "ITEM_STATUSES") == list(ac.ItemStatus.ALL))
check("the advice items, forecasts and their units equal the contract's",
      js_list(js, "ADVICE_ITEMS") == list(ac.ADVICE_ITEMS) and js_list(js, "FORECAST_ITEMS") == list(ac.FORECAST_ITEMS)
      and js_object(js, "ITEM_UNITS") == dict(ac.ITEM_UNITS))
check("the verified tariff provenances and the data-quality states equal the contract's",
      set(js_list(js, "VERIFIED_TARIFF_PROVENANCES")) == set(ac.VERIFIED_TARIFF_PROVENANCES)
      and js_list(js, "DATA_QUALITY_STATES") == list(ac.DataQuality.ALL))
check("the decision titles are site_decisions.DECISION_TITLES under their I-D display labels",
      js_object(js, "DECISION_TITLES") == {sd.display_label(d): t for d, t in sd.DECISION_TITLES.items()})
read_attrs = js_list(js, "ATTRIBUTES_READ")
contract_attrs = set(ac.RECORDED_ATTRIBUTES) | set(ac.UNRECORDED_ATTRIBUTES)
check("every attribute the card reads is a contract attribute (RECORDED | UNRECORDED)", read_attrs and set(read_attrs) <= contract_attrs,
      str(sorted(set(read_attrs) - contract_attrs)))
used = re.findall(r"\batt\(\s*\w+\s*,\s*'([^']*)'\s*\)", code)
check("every att() call names a literal from ATTRIBUTES_READ, and every listed name is read",
      used and set(used) <= set(read_attrs) and set(read_attrs) == set(used) and not re.search(r"(?<!function )\batt\(\s*\w+\s*,\s*[^'\s]", code),
      str(sorted(set(used) ^ set(read_attrs))))
att_fn = js_function(code, "att")
outside_att = code.replace(att_fn, "")
check("`attributes` is read only inside att()",
      att_fn.count(".attributes") == 2 and re.findall(r"\.attributes\b", outside_att) == [])
m = re.search(r"export const BLOCK_KEYS_READ = Object\.freeze\(\{(.*?)\n\}\);", js, re.S)
blocks = {k: re.findall(r"'([^']*)'", v) for k, v in re.findall(r"(\w+): Object\.freeze\(\[([^\]]*)\]\)", m.group(1))} if m else {}
CONTRACT_BLOCKS = {**{k: set(v) for k, v in ac.BLOCK_KEYS.items()}, "input_ages": set(ac.INPUT_AGE_KEYS),
                   "last_good": {"generated_at", "values"}, "blockers": {"code", "text"}}
check("the keys read inside the blocks and rows are the contract's (BLOCK_KEYS, INPUT_AGE_KEYS, last_good, blockers)",
      blocks and all(k in CONTRACT_BLOCKS and set(v) <= CONTRACT_BLOCKS[k] for k, v in blocks.items()), str(blocks))
guard = js_function(code, "statusGuard")
cf = js_function(code, "contractFields")
check("the contract guard: contract_version, mode, applies_nothing === true, a non-blank (trimmed) integration_version, kind and a "
      "known status",
      "att(st, 'contract_version') === CONTRACT_VERSION" in cf and "att(st, 'mode') === MODE" in cf
      and "att(st, 'applies_nothing') === true" in cf and "if (!contractFields(st)) return 'not_recognised';" in guard
      and "if (!isNonBlank(att(st, 'integration_version'))) return 'not_recognised';" in guard
      and "const isNonBlank = (v) => typeof v === 'string' && v.trim().length > 0;" in code
      and "if (!SYSTEM_STATUSES.includes(st.state)) return 'not_recognised';" in guard)
dm = js_function(code, "deriveModel")
check("deriveModel applies the guard before anything is derived, and returns at once when it fails",
      dm.index("const why = statusGuard(st);") < dm.index("vm.status = st.state;")
      and re.search(r"if \(why\) \{\s*vm\.kind = why;\s*return vm;\s*\}", dm) is not None)
iv_fn = js_function(code, "itemView")
check("the null rule: the null-rule statuses return before any block, and an item figure needs numbers.allowed and its own validity",
      "vm.kind = NULL_STATUSES.includes(st.state) ? 'null' : 'live';" in dm
      and dm.index("if (vm.kind === 'null') {") < dm.index("const tariff = att(st, 'tariff');")
      and "numbers = { allowed: vm.kind === 'live' && vm.withheld === '' && vm.validMs !== null && vm.genMs !== null" in dm
      and "if (!numbers.allowed || att(st, 'generated_at') !== numbers.generatedAt)" in iv_fn
      and "if (value === null || valid === null || nowMs > valid)" in iv_fn)
_early = "  if (v.status !== 'OK') {\n    v.note = ITEM_STATUS_TEXT[v.status];\n    return v;\n  }\n"
check("itemView returns at once for every item that is not OK, before the state, a band or the advice is read (no figure for "
      "BLOCKED / INSUFFICIENT_DATA / NO_ADVICE / WITHHELD)",
      iv_fn.count(_early) == 1 and iv_fn.index(_early) < iv_fn.index("const value = finite(st.state);") < iv_fn.index("att(st, 'p10')")
      and iv_fn.index(_early) < iv_fn.index("att(st, 'advice')") and iv_fn.count("st.state") == 1)
check("figures are withheld for a live result while it is expired, timed more than the PROPOSED 120 s ahead of the card's clock, or "
      "the package watchdog reads off (Home Assistant's clock); missing / unknown watchdog: the card's own checks",
      "export const CLOCK_AHEAD_MS = 120000;" in code
      and "vm.clockAhead = vm.kind === 'live' && vm.genMs !== null && vm.genMs > nowMs + CLOCK_AHEAD_MS;" in dm
      and "vm.withheld = vm.kind !== 'live' ? '' : vm.expired ? 'expired' : vm.clockAhead ? 'clock_ahead' : vm.watchdog === 'off' ? "
          "'watchdog_off' : '';" in dm
      and dm.index("vm.withheld = ") < dm.index("const numbers = "))
check("the accuracy and data-quality entities are used only from the same publish as the status (generated_at equal)",
      "att(acc, 'generated_at') === vm.generatedAt" in dm and "att(dq, 'generated_at') === vm.generatedAt" in dm)
check("the one fixed notice for an unrecognised output", "title: 'Intelligence output not recognised'," in js)
check("the pause is not offered by the card (no control, the helper's state only)", "<button" not in code and "addEventListener" not in code)

# =====================================================================================================================
print("")
print("[4] the package")
# =====================================================================================================================
# PR-6 (post-export entry isp1) restores the package and its behaviour suite, and with them these static pins (F9).
check("the package, its behaviour suite and the two companion packages with the prefs suite are in this tree (isp1)",
      all((ROOT / r).is_file() for r in (PKG_REL, HA_TEST_REL, REG_REL, PREFS_REL, PREFS_TEST_REL)),
      str([r for r in (PKG_REL, HA_TEST_REL, REG_REL, PREFS_REL, PREFS_TEST_REL) if not (ROOT / r).is_file()]))
pkg_text = read(PKG_REL)
pkg_code = yaml_code(pkg_text)
pdoc = yaml.safe_load(pkg_text)
check("the package parses with exactly input_boolean, template and automation", isinstance(pdoc, dict)
      and set(pdoc) == {"input_boolean", "template", "automation"})
check("one helper: input_boolean.ecco_intel_paused (the contract's pause entity), no `initial:`",
      list(pdoc["input_boolean"]) == [ac.object_id(ac.ENTITY_IDS["paused"])] and "initial" not in pdoc["input_boolean"][ac.object_id(ac.ENTITY_IDS["paused"])]
      and not re.search(r"^\s*initial\s*:", pkg_code, re.M))
wd = [e for blk in pdoc["template"] for kind, items in blk.items() for e in items]
check("one template entity: the watchdog binary_sensor with the contract's unique_id",
      len(pdoc["template"]) == 1 and list(pdoc["template"][0]) == ["binary_sensor"] and len(wd) == 1
      and wd[0].get("unique_id") == ac.object_id(ac.ENTITY_IDS["watchdog_fresh"]))
actions = [n for a in pdoc["automation"] for n in walk(a["actions"]) if isinstance(n, dict) and ({"action", "service"} & set(n))]
check("the only service is persistent_notification.create (three calls, one per automation)",
      len(pdoc["automation"]) == 3 and len(actions) == 3 and all(n.get("action") == "persistent_notification.create" and "service" not in n for n in actions))
_AUTO_KEYS = {"id", "alias", "description", "mode", "max_exceeded", "triggers", "actions"}
check("each automation's keys are a fixed allowlist, and its `actions` is exactly ONE node whose keys are exactly {action, data} "
      "(an event fire, a scene, a delay or any other step fails whatever key it uses)",
      [set(a) - {"conditions"} for a in pdoc["automation"]] == [_AUTO_KEYS] * 3
      and ["conditions" in a for a in pdoc["automation"]] == [False, True, True]
      and all(isinstance(a["actions"], list) and len(a["actions"]) == 1 and isinstance(a["actions"][0], dict)
              and set(a["actions"][0]) == {"action", "data"}
              and set(a["actions"][0]["data"]) == {"notification_id", "title", "message"} for a in pdoc["automation"]))
_START = {"trigger": "homeassistant", "event": "start"}
_a = pdoc["automation"]
check("triggers and conditions: the stale alert one template trigger; the two fault alerts also the Home Assistant start trigger, "
      "each re-checked by a TEMPLATE condition (the self-test one with is_state, so a start with no status entity logs no "
      "condition error; the mismatch one equal to its trigger's)",
      [t.get("trigger") for t in _a[0]["triggers"]] == ["template"] and set(_a[0]["triggers"][0]) == {"trigger", "value_template"}
      and _a[1]["triggers"] == [{"trigger": "state", "entity_id": ac.ENTITY_IDS["status"], "to": "SELF_TEST_FAILED"}, _START]
      and _a[1]["conditions"] == [{"condition": "template",
                                   "value_template": "{{ is_state('" + ac.ENTITY_IDS["status"] + "', 'SELF_TEST_FAILED') }}"}]
      and len(_a[2]["triggers"]) == 2 and _a[2]["triggers"][1] == _START and set(_a[2]["triggers"][0]) == {"trigger", "value_template"}
      and _a[2]["conditions"] == [{"condition": "template", "value_template": _a[2]["triggers"][0]["value_template"]}])
check("each notification_id is fixed and starts ecco_intel_", [n["data"]["notification_id"] for n in actions]
      == ["ecco_intel_watchdog_stale", "ecco_intel_self_test_failed", "ecco_intel_contract_mismatch"]
      and all(str(n["data"]["notification_id"]).startswith("ecco_intel_") for n in actions))
check("no dismiss / dismiss_all, no target, no recorder block", "dismiss" not in pkg_code and not [n for n in actions if "target" in n]
      and not any(isinstance(n, dict) and "recorder" in n for n in walk(pdoc)) and not re.search(r"^\s*recorder\s*:", pkg_code, re.M))
pkg_ids = set(re.findall(r"\b(?:sensor|binary_sensor|input_[a-z]+|switch|button|number|select|script|automation|scene|event|light|cover|"
                         r"climate|lock|fan|siren|valve|media_player|water_heater|timer|counter|text|date|time|datetime|notify|esphome)"
                         r"\.[a-z0-9_]+", pkg_code))
check("the package names only the status entity, the pause helper and the watchdog",
      pkg_ids == {ac.ENTITY_IDS["status"], ac.ENTITY_IDS["paused"], ac.ENTITY_IDS["watchdog_fresh"]}, str(sorted(pkg_ids)))
check("thresholds are labelled PROPOSED (the four of gate G8, in the header)",
      all(re.search(rf"^#\s+{n}\s+=\s+{v}\s+PROPOSED", pkg_text, re.M) for n, v in
          (("WATCHDOG_MAX_AGE_S", 1200), ("RESUME_GRACE_S", 130), ("CLOCK_AHEAD_S", 120), ("ALERT_AFTER_S", 1800))))
check("no automation spells the mode word", not [a["id"] for a in pdoc["automation"] if "shadow" in yaml.dump(a).lower()])
reg_doc = yaml.safe_load(read(REG_REL))
prefs_doc = yaml.safe_load(read(PREFS_REL))
check("the companion packages: the registration holds only lovelace.dashboards.ecco-intelligence (YAML mode, administrators), "
      "the preferences only input_number.ecco_advisory_reserve_raise_pct (no initial)",
      reg_doc == {"lovelace": {"dashboards": {"ecco-intelligence": reg_doc["lovelace"]["dashboards"]["ecco-intelligence"]}}}
      and reg_doc["lovelace"]["dashboards"]["ecco-intelligence"].get("mode") == "yaml"
      and reg_doc["lovelace"]["dashboards"]["ecco-intelligence"].get("require_admin") is True
      and list(prefs_doc) == ["input_number"] and list(prefs_doc["input_number"]) == ["ecco_advisory_reserve_raise_pct"]
      and "initial" not in prefs_doc["input_number"]["ecco_advisory_reserve_raise_pct"])

# =====================================================================================================================
print("")
print("[5] the dashboard")
# =====================================================================================================================
dash_text = read(DASH_REL)
ddoc = yaml.safe_load(dash_text)
views = ddoc.get("views", []) if isinstance(ddoc, dict) else []
cards = views[0].get("cards", []) if len(views) == 1 else []
check("the dashboard parses: a title and exactly one view", isinstance(ddoc, dict) and isinstance(ddoc.get("title"), str) and len(views) == 1)
check("its cards: the custom card, a tile, an entities card and a markdown fallback (core cards otherwise)",
      [c.get("type") for c in cards] == [f"custom:{TAG}", "tile", "entities", "markdown"], str([c.get("type") for c in cards]))
cc = cards[0] if cards else {}
check("the custom card is used once, with the contract's thirteen ids, and its keys are the card's",
      dash_text.count(f"custom:{TAG}") == 1 and cc.get("entities") == dict(ac.ENTITY_IDS)
      and set(cc) == {"type", "title", "entities"} and set(cc["entities"]) <= set(js_object(js, "DEFAULT_ENTITIES")))
tile = cards[1] if len(cards) > 1 else {}
check("the pause is offered only by the core tile card on input_boolean.ecco_intel_paused (tap / icon tap toggle, hold more-info)",
      tile.get("entity") == ac.ENTITY_IDS["paused"] and tile.get("tap_action") == {"action": "toggle"}
      and tile.get("icon_tap_action") == {"action": "toggle"} and tile.get("hold_action") == {"action": "more-info"}
      and yaml_code(dash_text).count(ac.ENTITY_IDS["paused"]) == 3)
ent = cards[2] if len(cards) > 2 else {}
rows = [r.get("entity") if isinstance(r, dict) else r for r in ent.get("entities", [])]
check("the entities card shows the watchdog first, read-only rows only (no helper row)",
      rows and rows[0] == ac.ENTITY_IDS["watchdog_fresh"] and all(not r.startswith(("input_", "switch.", "button.", "script.")) for r in rows)
      and all(set(r) <= {"entity", "name"} for r in ent.get("entities", []) if isinstance(r, dict)))
md = cards[3].get("content", "") if len(cards) > 3 else ""
check("the markdown fallback applies the same guard and shows no figure",
      f"state_attr(s, 'contract_version') == '{ac.CONTRACT_VERSION}'" in md and "state_attr(s, 'mode') == 'SHADOW'" in md
      and "'applies_nothing') is sameas true" in md and "Intelligence output not recognised" in md
      and not re.search(r"states\('sensor\.ecco_intel_(?!status)", md) and "p10" not in md and "last_good" not in md)
actions_nodes = [n for n in walk(ddoc) if isinstance(n, dict) and isinstance(n.get("action"), str)]
check("no service call, script, navigation or URL anywhere in the dashboard (the only actions: toggle and more-info)",
      not re.search(r"perform_action|call-service|service:|script\.|navigation_path|url_path|https?://", yaml_code(dash_text))
      and {n["action"] for n in actions_nodes} == {"toggle", "more-info"})
dash_ids = set(re.findall(r"\b(?:sensor|binary_sensor|input_[a-z]+|switch|button|number|select|script|automation)\.[a-z0-9_]+", yaml_code(dash_text)))
check("every entity id on the dashboard is a contract id", dash_ids and dash_ids <= set(ac.ENTITY_IDS.values()), str(sorted(dash_ids - set(ac.ENTITY_IDS.values()))))
check("the one-time registration is documented as an owner step (package first, then the resource, the dashboard file and its "
      "registration package, configuration.yaml only as the fallback); no held-out note remains",
      "One-time registration (an OWNER step" in dash_text and dash_text.index("install home-assistant/packages/ecco_intelligence.yaml FIRST")
      < dash_text.index("add it as a Lovelace resource") < dash_text.index("install the registration package")
      < dash_text.index("added to configuration.yaml by hand") and "HELD OUT" not in dash_text and "ui-1" not in dash_text)
_reg_entry = (yaml.safe_load(read(REG_REL)) or {}).get("lovelace", {}).get("dashboards", {}).get("ecco-intelligence", {})
_hdr = yaml.safe_load("\n".join(ln[1:] for ln in dash_text.split("\n")
                                if ln.startswith("#        lovelace:") or ln.startswith("#          ")))
check("the entry the header documents is exactly the registration package's entry",
      isinstance(_hdr, dict) and bool(_reg_entry) and _hdr.get("lovelace", {}).get("dashboards", {}).get("ecco-intelligence") == _reg_entry,
      str(_hdr))

# =====================================================================================================================
print("")
print("[6] tokens")
# =====================================================================================================================
OWN = {**{f"frontend/{TAG}/{f}": t for f, t in all_card_text.items()}, PKG_REL: pkg_text, REG_REL: read(REG_REL),
       PREFS_REL: read(PREFS_REL), DASH_REL: dash_text, HA_TEST_REL: read(HA_TEST_REL), PREFS_TEST_REL: read(PREFS_TEST_REL),
       DOC_REL: read(DOC_REL), SELF_REL: read(SELF_REL)}
_PKG_COMMENTS = {f"{PKG_REL} (comments)": "\n".join(ln for ln in pkg_text.splitlines() if ln.strip().startswith("#"))}
FB, FL = "fail" + "back", "fall" + "back"
RESERVED = ["ecco_" + FL, FL.upper() + "_PROFILE", FB.upper() + "_STATE", "ecco_" + FB, "ecco_" + "shadow_", "Shadow " + "Recovery",
            FB + "_shadow", "fbc" + "_raw_", FL + "_profile_live" + "_match", FL + "_profile_arm", FL + "_profile_execute"]
check("no reserved fallback / recovery token (the FB-A and recovery ban lists) in any of these files",
      not [(f, t) for f, text in OWN.items() for t in RESERVED if t in text], str([(f, t) for f, text in OWN.items() for t in RESERVED if t in text][:4]))
FLOW3D = "ecco-flow-" + "3d-card"
check("no literal of the 3D card's name, and no `type: custom:` example of it, in any of these files",
      not [f for f, text in OWN.items() if FLOW3D in text or re.search(r"custom:ecco-flow-" + r"3d", text)])
VESTIGIAL = ["input_select.ecco_" + "automation_mode", "binary_sensor.ecco_" + "automatic_writes_armed", "ecco_" + "automation_mode",
             "ecco_" + "automatic_writes_armed"]
check("the vestigial automation-mode / writes-armed entities are neither reused nor named", not [f for f, text in OWN.items() for v in VESTIGIAL if v in text])
slug_hits = [f for f, text in OWN.items() if f not in (SELF_REL, HA_TEST_REL, PREFS_TEST_REL, DOC_REL)
             and re.search("ecco_clock_" + "dongle|your_" + r"(?:meter_serial|import_mpan|export_mpan)|octo" + "pus", text)]
proto_hits = [f for f, text in {**OWN, **_PKG_COMMENTS}.items() if re.search(r"(?:sensor|binary_sensor)\.ecco_intelligence_\w", text)
              and f not in (f"frontend/{TAG}/test/core.test.mjs", f"frontend/{TAG}/test/element.test.mjs", DOC_REL)]
check("no device slug or tariff placeholder in the card, the packages or the dashboard; a prototype id (also in the package's "
      "comments) only in the refusal tests and the doc",
      not slug_hits and not proto_hits, str(slug_hits + proto_hits))
# the workstation-path shapes are assembled from parts so this suite does not match the repository's own path greps
USR, APD, WS = "Us" + "ers", "App" + "Data", "EC" + "CO"
PRIVATE = [r"[A-Za-z]:[\\/](?:" + USR + "|" + WS + r")\b", "/" + USR + "/[A-Za-z]", APD, r"\b[\w.+-]+@[\w-]+\.[\w.]+\b",
           r"\b192\.168\.\d", r"\b10\.\d+\.\d+\.\d+\b", r"\b172\.(?:1[6-9]|2\d|3[01])\.\d", r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b",
           r"\b\d{13}\b"]
priv = [(f, p) for f, text in OWN.items() if f != SELF_REL for p in PRIVATE if re.search(p, text, re.I)]
check("no workstation path, e-mail, private address, MAC or 13-digit number in any of these files", not priv, str(priv[:4]))

# =====================================================================================================================
print("")
print("[7] site render")
# =====================================================================================================================
actions_fw = R.firmware_actions(ROOT)
sites = [R.Site(), R.parse_site({"schema": R.SCHEMA, "device_slug": "home_inverter_dongle"}),
         R.parse_site({"schema": R.SCHEMA, "device_slug": "ecco_clock_dongle",
                       "octopus": {"meter_serial": "abc123def4", "import_mpan": "1" * 13, "export_mpan": "2" * 13}})]
render_ok = True
RENDERED = (PKG_REL, REG_REL, PREFS_REL, DASH_REL)
for rel in RENDERED:
    for site in sites:
        try:
            out, counts = R.render_text(rel, read(rel), site, actions_fw)
        except R.RenderError as ex:
            out, counts = None, {"error": str(ex)}
        render_ok = render_ok and out == read(rel) and not any(counts.values())
check("the three packages and the dashboard render byte-identical for the default, a renamed-slug and an Octopus site (generic "
      "ids only)", render_ok)
check("the three packages and the dashboard are in the deployable render set (the site render sees them); the card module is not",
      all(rel in R.render_set(ROOT) for rel in RENDERED) and JS_REL not in R.render_set(ROOT))

# =====================================================================================================================
print("")
print("[8] the design document")
# =====================================================================================================================
doc = read(DOC_REL)
check("UI_DESIGN.md names the contract ecco-intel-entities/1, every contract entity id and every I-D label",
      ac.CONTRACT_VERSION in doc and all(i in doc for i in ac.ENTITY_IDS.values()) and all(f"I-D{n}" in doc for n in range(1, 10)))
_s14 = doc[doc.find("## 14."):]
check("UI_DESIGN.md records the 3D Overview card's link to this card as dropped for v0.1 (frozen ecco_pro.yaml untouched), "
      "without the 3D card's literal name, and never as a pending proposal",
      "## 14. Linking the 3D Overview card to this card: dropped for v0.1" in doc and "ecco_pro.yaml" in _s14
      and "untouched" in _s14 and FLOW3D not in doc and "## 14. Proposal" not in doc)
_nr = doc[doc.find("**The next refresh.**"):][:900]
check("UI_DESIGN.md says the header names the next refresh from next_run_at, the earliest moment the next cycle can start "
      "(the card's ' · next refresh HH:MM' text)",
      "**The next refresh.**" in doc and "next_run_at" in _nr and "earliest moment the next cycle can start" in _nr
      and "next refresh HH:MM" in _nr and "next refresh ${esc(env.time(vm.nextMs))}" in js)
check("UI_DESIGN.md no longer presents the superseded ecco_intelligence_* entities as the card's contract",
      "superseded" in doc and "## 7. Home Assistant entity contract (`ecco-intel-entities/1`)" in doc)

# =====================================================================================================================
print("")
print("[9] scope")
# =====================================================================================================================
_prod = read("home-assistant/dashboards/ecco_pro.yaml")
check("the card, the packages, the dashboard and the ecco_intel_ ids are not in the production dashboard",
      not (TAG in _prod or "ecco_intelligence" in _prod or "ecco_intel_" in _prod))
_man = yaml.safe_load(read("deployment/ha-manifest.yaml"))
_named = sorted(str(n.get("source")) for n in walk(_man) if isinstance(n, dict)
                and re.search(r"ecco_intel|ecco-intelligence", str(n.get("source")) + str(n.get("destination"))))
check("the manifest names the Intelligence files only in isp1's stanzas: the three packages, the standalone dashboard "
      "(intelligence_dashboard) and the card (frontend_assets); the production dashboard mapping is ecco_pro's",
      _named == sorted([PKG_REL, PREFS_REL, REG_REL, DASH_REL, JS_REL]) and _man["dashboard"]["source"].endswith("ecco_pro.yaml")
      and _man["intelligence_dashboard"]["source"] == DASH_REL
      and [a["source"] for a in _man["frontend_assets"] if TAG in a["source"]] == [JS_REL]
      and not re.search(r"ecco_intel_\w", read("deployment/ha-manifest.yaml")), str(_named))
_ver = yaml.safe_load(read("VERSION.yaml"))
_ver_rest = {k: v for k, v in _ver["current"].items() if k != "intelligence"}
check("VERSION.yaml names them only in current.intelligence and current.home_assistant.intelligence_package, and no ecco_intel_ id",
      _ver["current"]["intelligence"]["card"] == JS_REL and _ver["current"]["intelligence"]["dashboard"] == DASH_REL
      and _ver["current"]["home_assistant"]["intelligence_package"] == PKG_REL
      and "intelligence" not in yaml.safe_dump({**_ver_rest, "home_assistant": {k: v for k, v in _ver_rest["home_assistant"].items()
                                                                                if k != "intelligence_package"}})
      and "ecco_intel_" not in read("VERSION.yaml"))

# =====================================================================================================================
print("")
print("[10] the SHADOW cycle's blocks in the shapes the card reads (cross-stream pin, CCR-INT-1)")
# =====================================================================================================================
# The card's block readers, verbatim: the Python mirror below follows exactly these lines, so a change to either side
# fails here instead of leaving the card unable to read a block it is given.
READERS = (
    r"if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(v) || !/(?:Z|[+-]\d{2}:?\d{2})$/.test(v)) return null;",
    "const ends = Array.isArray(w) && w.length === 2 ? w : own(w, 'start') && own(w, 'end') ? [w.start, w.end] : null;",
    "if (ms && ms[0] !== null && ms[1] !== null && ms[0] < ms[1]) vm.tariff.window = ms;",
    "vm.tariff.price = own(tariff, 'price_range') ? range2(tariff.price_range) : null;",
    "if (Array.isArray(v) && v.length === 2) [a, b] = v;",
    "else if (own(v, 'min') && own(v, 'max')) [a, b] = [v.min, v.max];",
    "else if (own(v, 'low') && own(v, 'high')) [a, b] = [v.low, v.high];",
    "a = typeof a === 'number' ? finite(a) : null;",
    "return a !== null && b !== null && a <= b ? [a, b] : null;",
    "const gbp = own(value, 'range_gbp') ? range2(value.range_gbp) : null;",
    "const assumptions = own(value, 'assumptions') ? (isText(value.assumptions) ? [value.assumptions] : textList(value.assumptions)) : [];",
    "const pre = own(plan, 'precharge_by') ? parseTime(plan.precharge_by) : null;",
    "const head = own(plan, 'headroom_ceiling_pct') && typeof plan.headroom_ceiling_pct === 'number' ? finite(plan.headroom_ceiling_pct) : null;",
    "const run = own(plan, 'reserve_runout_at') ? parseTime(plan.reserve_runout_at) : null;",
)
missing_readers = [r for r in READERS if r not in code]
check("the card's tariff, range, value and plan readers are the ones this suite mirrors", not missing_readers, str(missing_readers[:2]))
TIME_HEAD, TIME_TAIL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"), re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def card_time(v):
    """parseTime: a text with a date, a time and an offset, else None."""
    if not isinstance(v, str) or not TIME_HEAD.search(v) or not TIME_TAIL.search(v):
        return None
    try:
        t = datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def card_number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def card_window(w):
    ends = (list(w) if isinstance(w, list) and len(w) == 2 else
            [w["start"], w["end"]] if isinstance(w, dict) and "start" in w and "end" in w else None)
    ms = [card_time(x) for x in ends] if ends else None
    return ms if ms and ms[0] is not None and ms[1] is not None and ms[0] < ms[1] else None


def card_range(v):
    a = b = None
    if isinstance(v, list) and len(v) == 2:
        a, b = v
    elif isinstance(v, dict) and "min" in v and "max" in v:
        a, b = v["min"], v["max"]
    elif isinstance(v, dict) and "low" in v and "high" in v:
        a, b = v["low"], v["high"]
    a, b = card_number(a), card_number(b)
    return [a, b] if a is not None and b is not None and a <= b else None


sys.path.insert(0, str(ROOT / "intelligence" / "tests"))
import _cycle_fixtures as cf  # noqa: E402
import _plan_helpers as ph  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402


def held_status(inputs):
    """The status entity's recorded attributes of a real cycle, as Home Assistant holds them (JSON)."""
    e = run_cycle(inputs)
    return e, json.loads(json.dumps(ac.to_entity_payloads(e)[ac.ENTITY_IDS["status"]][1], allow_nan=False))


ver_env, ver = held_status(ph.verified_inputs(synthetic_recorded=True))
check("the cycle under test: a VERIFIED tariff and an OK charge target (so the card would show its blocks)",
      ver_env.status == "OK" and ver_env.item("charge_target").status == "OK"
      and ver["tariff"]["provenance"] in js_list(js, "VERIFIED_TARIFF_PROVENANCES"), f"{ver_env.status} {ver['tariff']}")
win = card_window(ver["tariff"]["window"])
check("tariff.window is read by the card as the charge window the plan used ({start, end}, aware ISO-8601)",
      win is not None and [w.isoformat() for w in win] == list(ver_env.item("charge_target").summary["window"]),
      f"{ver['tariff']['window']} {ver_env.item('charge_target').summary.get('window')}")
check("tariff.price_range is read as a [low, high] range", card_range(ver["tariff"]["price_range"]) is not None, str(ver["tariff"]))
val = ver.get("value") or {}
asm = val.get("assumptions")
check("value.range_gbp is read as a range and value.assumptions as at least one text",
      card_range(val.get("range_gbp")) is not None
      and ((isinstance(asm, str) and asm != "") or (isinstance(asm, list) and any(isinstance(a, str) and a for a in asm))), str(val)[:200])
pl = ver.get("plan") or {}
plan_read = {"precharge_by": card_time(pl.get("precharge_by")), "headroom_ceiling_pct": card_number(pl.get("headroom_ceiling_pct")),
             "reserve_runout_at": card_time(pl.get("reserve_runout_at"))}
check("the plan block: at least one field the card reads, and every non-null field readable",
      any(v is not None for v in plan_read.values()) and all(plan_read[k] is not None for k, v in pl.items() if v is not None),
      str(pl))
tou_env, tou = held_status(cf.cycle_inputs(synthetic_recorded=True))
check("a window from the TOU slot table has the same shape (the card shows it only with a verified tariff)",
      tou["tariff"]["provenance"] not in js_list(js, "VERIFIED_TARIFF_PROVENANCES")
      and card_window(tou["tariff"]["window"]) is not None, str(tou["tariff"]))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
