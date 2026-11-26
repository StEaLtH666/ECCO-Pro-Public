#!/usr/bin/env python3
"""Static pin suite: the ECCO Mode Shell card (frontend/ecco-mode-shell/ecco-mode-shell.js, Production / Geek Mode), its Intelligence catalogue and
ledger, the example it is wrapped by, and the dashboard configuration generated from them (tools/geek_mode_dashboard_config.py).

CI runs no Node, so the card's twelve Node suites, its 518-mutant proof and its headless strip check (frontend/ecco-mode-shell/test, preview) are local
evidence. This suite is the one guard CI has: it pins the card as READ-ONLY by what its source may name, count and do, and it pins the exact bytes, so
that any change to the card, the catalogue or the generated configuration is a deliberate edit of this file in the same commit (the pins below are the
reviewed ones). Modelled on tools/tests/test_intelligence_card.py.

  [1] the bytes: the card, the catalogue, the ledger and the example exist and are pinned by size and sha256; ASCII, LF as stored by git, no BOM, no NUL;
      the ledger is bound to the catalogue by sha256; the folder's package.json (private, module, GPL-3.0-or-later, no dependency of any kind)
  [2] no write path and no network: the forbidden-API list (service calls, fetch, XMLHttpRequest, WebSocket, storage, eval, new Function, import(),
      cookies, postMessage, window.open, a location assignment, innerHTML and its two kin, deferred-work APIs), scanned on the whole text, comments included
  [3] the allowed surface, exactly: every code line that touches window, hass, the clipboard, a Blob URL, an event, a timer or an observer is on a list;
      so there is ONE setInterval (and its clear), ONE ResizeObserver, TWO window listeners (and their removal), the hass reads (states, locale.language,
      themes.darkMode, and the hand-over to child cards) at the known sites, and the three click-only actions (open an entity's dialog by the standard
      event, copy to the clipboard, download a Blob), each reached only from a click handler
  [4] the sets that keep it read-only: the entity domains whose dialog may open, the safe actions, the refusal key set, the write card types and
      writable domains, the card types allowed beside the Intelligence card; the card imports nothing; no computed member access on this, window,
      document, navigator or hass (or a global bound to a bare name), no member name built from string pieces, no call through a computed member;
      the redaction vocabulary (six word lists) and the reasons of its 23 value rules, pinned as written, so that a removed word is seen here
  [5] the export surface (41 names, listed) and the registration (customElements.define once, guarded; one window.customCards entry)
  [6] the catalogue: schema, view id, 17 sources, 344 attribute rows, 19 alerts, 361 ledger rows; no secret-looking string, URL, address, e-mail, token,
      private path or coordinate anywhere in it
  [7] the generated dashboard configuration: consistent with the committed catalogue and example, deterministic, and pinned by size and sha256
  [8] mutants (all in memory, on the bytes this suite pins): at least 25 deliberate breaks of the card, 8 of the catalogue and 4 of the configuration,
      each caught by the rule that exists for it; and a change of one comment letter is caught by the byte pin alone (a deliberate edit, nothing more)

DEFENCE IN DEPTH, said plainly: every rule below (the forbidden APIs, the exact surface, the read-only sets, the member-access rules, the redaction pins)
catches the careless and the obvious; none of them proves the card read-only, and an edit written to get past them can. The byte pin is the real guard: a
repin (a new size and sha256 in this file) needs a REVIEW OF THE FULL DIFF of the card, never only a green run of this suite.

A check that cannot run here (git or its index is not available, as in an archive without .git) prints SKIP and is counted apart from PASS.

Test-only, no network, no Node. I/O: reads repository files; runs `git ls-files --eol` (read-only).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import geek_mode_dashboard_config as G  # noqa: E402

SHELL = "frontend/ecco-mode-shell"
CARD_REL = f"{SHELL}/ecco-mode-shell.js"
CAT_REL = f"{SHELL}/catalogue/intelligence.catalogue.json"
LEDGER_REL = f"{SHELL}/catalogue/intelligence.ledger.json"
EXAMPLE_REL = f"{SHELL}/examples/intelligence-modes.yaml"
PKG_REL = f"{SHELL}/package.json"

# --- THE PINS: the reviewed bytes. Changing any of them is a deliberate edit of this file, in the same commit as the change it reviews. ---
CARD_SIZE = 155843
CARD_SHA256 = "17410163c016578f73428900087dc714f89336bbc55cc77ec5cbfc2e240d5775"
CAT_SIZE = 94420
CAT_SHA256 = "216176548250d3a8cc0f13fbd11e2dc31cce84c041a805955b081a3ead355a38"
LEDGER_SIZE = 228630
LEDGER_SHA256_PREFIX = "704407abd9f364eb"
EXAMPLE_SIZE = 6852
EXAMPLE_SHA256 = "c891e8fbf22d95eb9cf9a2e166629af84fdaeddfdc1532544aaf5b0308fa035c"
CONFIG_SIZE = 147801
CONFIG_SHA256 = "e961c119a076b1abd8f630d24ca9356dcd35dba54d4c4ad39e78a7f456288daa"
CAT_COUNTS = {"sources": 17, "attribute_rows": 344, "alerts": 19, "ledger_rows": 361}

FAILURES: list[str] = []
SKIPPED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def skip(name: str, why: str) -> None:
    """A check that could not run here. It is neither a PASS nor a FAIL: it is printed and counted apart."""
    SKIPPED.append(name)
    print(f"  SKIP  {name} - {why}")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_eol(rels: list[str], git: str = "git") -> dict[str, str] | None:
    try:
        r = subprocess.run([git, "-c", "gc.auto=0", "ls-files", "--eol", "--", *rels], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^(i/\S*)\s+(w/\S*)\s+\S+\s+(.+)$", line)
        if m:
            out[m.group(3)] = m.group(1)
    return out


# =====================================================================================================================
# the card's rules, as functions of the bytes, so the mutants of section [8] can be fed to them
# =====================================================================================================================
# [2] forbidden: scanned on the WHOLE text. The one comment sentence below is the card's own statement that it never uses the markup setters.
COMMENT_ALLOWED = "innerHTML, outerHTML and insertAdjacentHTML are never used."
FORBIDDEN = {
    "call_service": r"call_service", "callService": r"callService", "callWS / callApi": r"\bcallWS\b|\bcallApi\b", "fetch(": r"\bfetch\s*\(",
    "XMLHttpRequest": r"XMLHttpRequest", "WebSocket": r"WebSocket", "EventSource": r"EventSource", "sendBeacon": r"sendBeacon",
    "localStorage": r"localStorage", "sessionStorage": r"sessionStorage", "indexedDB": r"indexedDB", "eval(": r"\beval\s*\(",
    "new Function": r"\bnew\s+Function\b|\bFunction\s*\(", "import(": r"\bimport\s*\(", "import.meta": r"import\s*\.\s*meta",
    "document.cookie": r"document\s*\.\s*cookie", "postMessage": r"postMessage", "window.open": r"\bwindow\s*\.\s*open\b|(?<![\w.$])open\s*\(",
    "location assignment": r"\blocation\s*(?:\.\s*\w+\s*)?=(?!=)|\blocation\s*\.\s*(?:assign|replace|reload)\s*\(",
    "innerHTML": r"innerHTML", "outerHTML": r"outerHTML", "insertAdjacentHTML": r"insertAdjacentHTML", "document.write": r"document\s*\.\s*write",
    "srcdoc": r"srcdoc", "createContextualFragment": r"createContextualFragment", "importScripts / Worker": r"importScripts|\bWorker\b|ServiceWorker",
    "hass-action / call-service event": r"hass-action|show-dialog|\.press\s*\(", "URL scheme": r"[A-Za-z][A-Za-z0-9+.-]*://",
    "deferred work (setTimeout, rAF, microtask, Promise, async, await)": r"\bsetTimeout\b|requestAnimationFrame|queueMicrotask|\bPromise\b|\basync\b|\bawait\b",
    "observers other than ResizeObserver": r"MutationObserver|IntersectionObserver|PerformanceObserver",
    "dynamic reach (Reflect, Proxy, globalThis, with)": r"\bReflect\b|\bProxy\b|\bglobalThis\b|\bwith\s*\(",
}


def forbidden_findings(text: str) -> list[str]:
    t = text.replace(COMMENT_ALLOWED, "")
    return [f"forbidden: {name}" for name, rx in FORBIDDEN.items() if re.search(rx, t, re.M)]


# [3] the allowed surface: every code line that names one of these things, in file order. A comment-only line is not code; a trailing comment is cut.
SURFACE_TOKENS = re.compile(r"\b(?:window|hass|_hass|navigator|URL|Blob|dispatchEvent|CustomEvent|setInterval|clearInterval|ResizeObserver|addEventListener|"
                            r"removeEventListener|attachShadow|customElements|loadCardHelpers|performance)\b|\.click\(|\.then\(|\.catch\(")
EXPECTED_SURFACE = (
    "const on = (el, type, fn) => el.addEventListener(type, fn);",
    "this._hass = null;",
    "this._root = typeof this.attachShadow === 'function' ? this.attachShadow({ mode: 'open' }) : null;",
    "get hass() {",
    "return this._hass;",
    "set hass(hass) {",
    "this._hass = hass;",
    "for (const k of this._kids) k.hass = hass;",
    "if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {",
    "window.addEventListener('location-changed', this._onLocation);",
    "window.addEventListener('pagehide', this._onPageHide);",
    "if (typeof ResizeObserver !== 'undefined') {",
    "this._ro = new ResizeObserver((entries) => {",
    "if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {",
    "window.removeEventListener('location-changed', this._onLocation);",
    "window.removeEventListener('pagehide', this._onPageHide);",
    "this._timer = setInterval(() => this._onTimer(), ms);",
    "if (this._timer !== null) clearInterval(this._timer);",
    "const t = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now();",
    "return typeof window !== 'undefined' && window.location && isStr(window.location.pathname) ? window.location.pathname : '';",
    "const hass = this._hass;",
    "const s = hass && hass.states;",
    "const hass = this._hass;",
    "const lang = hass && hass.locale && isStr(hass.locale.language) ? hass.locale.language : undefined;",
    "if (this._hass !== null && this._hass !== undefined) el.hass = this._hass;",
    "const helpers = typeof window !== 'undefined' && typeof window.loadCardHelpers === 'function' ? window.loadCardHelpers : null;",
    "helpers().then((hp) => attach(hp.createCardElement(cfg))).catch((e) => fail(e && e.message ? e.message : 'unknown error'));",
    "const hass = this._hass;",
    "if (hass && hass.themes && typeof hass.themes.darkMode === 'boolean') ui.shell.setAttribute('data-theme', hass.themes.darkMode ? 'dark' : 'light');",
    "if (typeof CustomEvent !== 'function') return;",
    "this.dispatchEvent(new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId } }));",
    "const clip = typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function' ? navigator.clipboard : null;",
    "clip.writeText(text).then(() => say(`Copied ${what} (non-secret values only).`), () => say('The browser blocked the copy. Use the JSON or CSV button instead.'));",
    "const blob = new Blob([text], { type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8' });",
    "const url = URL.createObjectURL(blob);",
    "a.click();",
    "URL.revokeObjectURL(url);",
    "if (typeof customElements !== 'undefined' && typeof HTMLElement !== 'undefined') {",
    "if (!customElements.get(TAG)) customElements.define(TAG, EccoModeShell);",
    "if (typeof window !== 'undefined') {",
    "window.customCards = window.customCards || [];",
    "if (!window.customCards.some((c) => c && c.type === TAG)) {",
    "window.customCards.push({",
)


def code_lines(text: str):
    for s in (ln.strip() for ln in text.split("\n")):
        if s.startswith(("*", "/**", "//", "/*")):
            continue
        yield s.split(" // ")[0].rstrip()


def surface_lines(text: str) -> tuple[str, ...]:
    return tuple(s for s in code_lines(text) if SURFACE_TOKENS.search(s))


def count(text: str, rx: str) -> int:
    return len(re.findall(rx, "\n".join(code_lines(text))))


def surface_findings(text: str) -> list[str]:
    out = []
    got = surface_lines(text)
    if got != EXPECTED_SURFACE:
        added = [s for s in got if s not in EXPECTED_SURFACE][:3]
        gone = [s for s in EXPECTED_SURFACE if s not in got][:3]
        out.append(f"surface: the touching lines differ (new {added}; gone {gone}; {len(got)} vs {len(EXPECTED_SURFACE)})")
    # the same facts, said one by one (so a failure names what it is)
    for name, rx, want in (
        ("one setInterval", r"\bsetInterval\s*\(", 1), ("one clearInterval", r"\bclearInterval\s*\(", 1), ("one ResizeObserver", r"new\s+ResizeObserver\s*\(", 1),
        ("one observe", r"\.observe\s*\(", 1), ("one disconnect", r"\.disconnect\s*\(", 1),
        ("two window listeners", r"window\s*\.\s*addEventListener\s*\(", 2), ("two window listener removals", r"window\s*\.\s*removeEventListener\s*\(", 2),
        ("one element listener helper", r"=>\s*el\.addEventListener\s*\(", 1), ("one dispatchEvent", r"\bdispatchEvent\s*\(", 1),
        ("one CustomEvent", r"new\s+CustomEvent\s*\(", 1), ("one clipboard write", r"\.writeText\s*\(text\)", 1), ("one Blob", r"new\s+Blob\s*\(", 1),
        ("one object URL", r"URL\.createObjectURL\s*\(", 1), ("one object URL release", r"URL\.revokeObjectURL\s*\(", 1), ("one programmatic click", r"\.click\s*\(", 1),
        ("the card-helpers function named twice (the typeof guard and the one read)", r"window\.loadCardHelpers", 2), ("one open shadow root", r"attachShadow\s*\(\s*\{\s*mode:\s*'open'\s*\}\s*\)", 1),
    ):
        got_n = count(text, rx)
        if got_n != want:
            out.append(f"surface: {name} (found {got_n}, pinned {want})")
    if sorted(re.findall(r"window\.(?:add|remove)EventListener\('([a-z-]+)'", text)) != ["location-changed", "location-changed", "pagehide", "pagehide"]:
        out.append("surface: the window listeners are not location-changed and pagehide")
    if "'hass-more-info'" not in text or len(re.findall(r"'hass-[a-z-]+'", "\n".join(code_lines(text)))) != 1:
        out.append("surface: the one event the shell sends is not hass-more-info")
    events = sorted(re.findall(r"(?<![\w.])on\([^,\n]+,\s*'(\w+)'", text))
    if events != sorted(["change", "input", "keydown"] + ["click"] * 16):
        out.append(f"surface: element listeners are not 16 click, input, change and keydown ({sorted(set(events))})")
    # the three actions are reached from a click handler only
    lines = text.split("\n")
    sites = [i for i, ln in enumerate(lines) if re.search(r"\bo\.(?:onOpen|onCopy|onDownload)\(", ln) and not ln.strip().startswith(("*", "//"))]
    unguarded = []
    for i in sites:
        near = "\n".join(lines[max(0, i - 3): i + 1])
        if not re.search(r"\bon\([^,\n]+,\s*'click'", near):
            unguarded.append(lines[i].strip()[:80])
    if len(sites) != 6 or unguarded:
        out.append(f"surface: the open / copy / download actions are not exactly six sites in click handlers (sites {len(sites)}, unguarded {unguarded})")
    if len(re.findall(r"\bthis\._(?:openEntity|copy|download)\(", text)) != 3:
        out.append("surface: _openEntity, _copy and _download are not each called once (from the actions table)")
    return out


# [4] the read-only sets: the statements as written, whole
READ_ONLY_SETS = (
    "export const MORE_INFO_DOMAINS = Object.freeze(['sensor', 'binary_sensor', 'event']);",
    "const SAFE_ACTIONS = Object.freeze(['none', 'more-info', 'navigate']);",
    "const CALL_KEYS = new Set(['service', 'service_data', 'perform_action', 'call-service']);",
    "const DEFAULT_CUSTOM_CARDS = Object.freeze(['custom:ecco-intelligence-card']);",
    "const WRITE_CARD_TYPES = new Set(['button', 'entity-button', 'light', 'thermostat', 'humidifier', 'media-control', 'alarm-panel', 'shopping-list', 'todo-list',\n"
    "  'iframe', 'webpage']);",
    "const WRITABLE_DOMAINS = new Set(['switch', 'light', 'input_boolean', 'fan', 'cover', 'lock', 'climate', 'automation', 'script', 'scene', 'button', 'input_button',\n"
    "  'select', 'input_select', 'number', 'input_number', 'input_datetime', 'input_text', 'text', 'humidifier', 'valve', 'vacuum', 'water_heater', 'media_player',\n"
    "  'siren', 'update', 'remote', 'alarm_control_panel', 'lawn_mower', 'datetime', 'date', 'time', 'counter', 'timer', 'group']);",
    "const ALLOWED_CARD_TYPES = new Set(['markdown', 'entities', 'glance', HISTORY_GRAPH, 'statistics-graph', 'sensor', 'gauge', 'entity', 'heading', 'vertical-stack',\n"
    "  'horizontal-stack', 'grid', 'conditional', 'tile']);",
    "export const TAG = 'ecco-mode-shell';",
    "export const VERSION = '0.1.0';",
    "export const CATALOGUE_SCHEMA = 'ecco-geek-catalogue/1';",
    "export const EXPORT_SCHEMA = 'ecco-geek-export/1';",
    "export const MODES = Object.freeze(['production', 'geek']);",
    "export const DEFAULT_MODE = 'production';",
    "export const TICK_MS = 15000;",
)


def set_findings(text: str) -> list[str]:
    out = [f"read-only sets: statement changed or missing: {s.splitlines()[0][:70]}" for s in READ_ONLY_SETS if text.count(s) != 1]
    for tok in ("perform_action", "call-service", "service_data"):
        n = len(re.findall(re.escape(tok), "\n".join(code_lines(text))))
        if n != 1:
            out.append(f"read-only sets: {tok} appears {n} times in code (only the refusal set names it, once)")
    if re.search(r"^\s*import\b", text, re.M) or re.search(r"\brequire\s*\(", text):
        out.append("imports: the card imports something (it is one file with no dependency)")
    return out


# [5] the export surface and the registration
EXPECTED_EXPORTS = sorted([
    "BURST_ALLOWANCE", "BURST_WINDOW_MS", "CATALOGUE_SCHEMA", "DEFAULT_MODE", "EXPORT_SCHEMA", "EXTRA_FRAGMENTS_MAX", "EXTRA_FRAGMENT_MAX", "EccoModeShell", "FUTURE_SKEW_MS",
    "LIMITS", "MODES", "MORE_INFO_DOMAINS", "PALETTE", "SCAN_RULES", "STATS", "STATUSES", "STYLE", "TAG", "THUMB", "TICK_MS", "UNREAD_KEY", "VERSION", "WITHHELD",
    "buildSnapshot", "canOpenMoreInfo", "catalogueItemIds", "classifyRow", "cleanText", "countWithheld", "createModeController", "deriveAlerts", "exportRows",
    "formatAge", "redactAttributes", "redactValue", "searchRows", "summarise", "validateCatalogue", "validateChildCards", "validateConfig", "windowRows"])


def export_findings(text: str) -> list[str]:
    out = []
    names = re.findall(r"^export (?:const|function|class|let|var|async function) (\w+)", text, re.M)
    if len(re.findall(r"^export\b", text, re.M)) != len(names):
        out.append("exports: an export statement of another form (a list, a default, a re-export)")
    if sorted(names) != EXPECTED_EXPORTS or len(names) != 41:
        out.append(f"exports: not the 41 reviewed names (extra {sorted(set(names) - set(EXPECTED_EXPORTS))}, missing {sorted(set(EXPECTED_EXPORTS) - set(names))})")
    return out


def registration_findings(text: str) -> list[str]:
    out = []
    if text.count("customElements.define(") != 1 or "if (!customElements.get(TAG)) customElements.define(TAG, EccoModeShell);" not in text:
        out.append("registration: customElements.define is not exactly one guarded call of TAG")
    if text.count("window.customCards.push(") != 1 or "if (!window.customCards.some((c) => c && c.type === TAG)) {" not in text:
        out.append("registration: window.customCards is not exactly one guarded push")
    if text.count("class EccoModeShell extends Base") != 1:
        out.append("registration: the element class is not EccoModeShell extends Base, once")
    return out


# [4] member access that hides a name: the forbidden-API list reads names, so a name assembled at run time (this['_ha' + 'ss'], z['call' + 'Service']) would
# not be read by it. None of these shapes exists in the card; each is written to have no false positive on it. They do not make the list watertight (a name
# can be assembled in a variable first); the byte pin is the guard that is.
GLOBALS_RX = r"(?:this|window|document|globalThis|self|top|parent|navigator|hass|_hass)"
ACCESS_RULES = {
    "computed member access on this, window, document, navigator or hass": r"(?<![\w$.])" + GLOBALS_RX + r"\s*(?:\?\.)?\s*\[|\bthis\s*\.\s*_?hass\s*(?:\?\.)?\s*\[",
    "a member name built from string pieces inside brackets": r"\[\s*(?:'[^'\n]*'|\"[^\"\n]*\")\s*\+|\+\s*(?:'[^'\n]*'|\"[^\"\n]*\")\s*\]",
    "a template literal used as a member name": r"[\w$)\]]\s*\[\s*`",
    "this, window or another global bound to a bare name": r"\b(?:const|let|var)\s+[\w$]+\s*=\s*(?:this|window|document|globalThis|self|top|parent|navigator)\s*[;,)]"
                                                         r"|(?<![\w$.])[\w$]+\s*=\s*(?:this|window|document|globalThis|self|top|parent|navigator)\s*;",
    "a call through a computed member": r"[\w$)\]]\s*\[[^\]\n]*\]\s*(?:\?\.)?\s*\(",
}


def access_findings(text: str) -> list[str]:
    code = "\n".join(code_lines(text))
    return [f"access: {name}" for name, rx in ACCESS_RULES.items() if re.search(rx, code, re.M)]


# [4] the redaction vocabulary, pinned as written (the word lists of the card's key rules, and the reasons of its value rules). A word removed from one of
# them lets the value of such a key through to the screen, and CI runs no Node; the byte pin would catch it only until someone repins.
REDACTION_SETS = {
    "SECRET_TOKENS": (
        "token", "tokens", "password", "passwords", "passwd", "pwd", "passphrase", "passcode", "pincode", "secret", "secrets", "apikey", "apikeys",
        "authorization", "auth", "bearer", "credential", "credentials", "privatekey", "webhook", "webhooks", "cookie", "cookies", "session",
        "sessions", "psk", "pin", "dsn", "otp", "jwt", "signature", "accesskey", "secretkey", "signingkey", "clientsecret", "connectionstring",
        "connstr", "refreshtoken", "pw", "wifipass", "wifipw"),
    "KEY_WORDS": ("key", "keys"),
    "LOGIN_WORDS": ("user", "users", "usr", "login", "logins"),
    "PASS_WORDS": ("pass",),
    "PRIVATE_TOKENS": (
        "latitude", "longitude", "lat", "lon", "lng", "location", "locations", "gps", "coordinates", "coordinate", "address", "addresses", "email",
        "emails", "phone", "postcode", "postal", "ssid", "bssid", "mac", "ip", "hostname", "serial", "serialnumber", "mpan", "mprn", "imei",
        "username", "account", "accountid", "meterid"),
    "DIGEST_KEYS": ("gitsha", "commit", "commitsha", "gitcommit"),
}
RULE_REASONS = (
    "jwt", "key block", "url credentials", "connection string", "url token", "credential pair", "connection pairs", "pass pair", "wifi credentials",
    "bearer", "known token", "email address", "IPv4 address", "IPv6 address", "MAC address", "MAC address (dotted)", "MAC address (spaced)", "coordinates",
    "labelled coordinate", "hemisphere coordinates", "webhook path", "internal host name", "private host name")


def redaction_findings(text: str) -> list[str]:
    out = []
    for name, want in REDACTION_SETS.items():
        m = re.search(r"^const " + name + r" = new Set\(\[(.*?)\]\);", text, re.M | re.S)
        got = tuple(re.findall(r"'([^']*)'", m.group(1))) if m else None
        if got != want:
            gone = sorted(set(want) - set(got or ()))[:4]
            new = sorted(set(got or ()) - set(want))[:4]
            out.append(f"redaction: {name} is not the pinned word list (missing {gone}; new {new}; {len(got) if got is not None else 'not found'} vs {len(want)})")
    m = re.search(r"^const RULES = \[\n(.*?)^\];", text, re.M | re.S)
    reasons = tuple(re.findall(r"^  \['([^']+)',\s*(?:'[^']*'|null),\s*/", m.group(1), re.M)) if m else None
    if reasons != RULE_REASONS:
        out.append(f"redaction: the value rules are not the pinned {len(RULE_REASONS)} (missing {sorted(set(RULE_REASONS) - set(reasons or ()))[:4]}; "
                   f"new {sorted(set(reasons or ()) - set(RULE_REASONS))[:4]})")
    return out


def hygiene_findings(b: bytes) -> list[str]:
    out = []
    if not b.isascii():
        out.append("hygiene: not ASCII")
    if b"\r" in b:
        out.append("hygiene: a CR (not LF only)")
    if b"\x00" in b:
        out.append("hygiene: a NUL byte")
    if b.startswith(b"\xef\xbb\xbf"):
        out.append("hygiene: a byte order mark")
    if not b.endswith(b"\n") or b.endswith(b"\n\n"):
        out.append("hygiene: not exactly one final newline")
    return out


def byte_findings(b: bytes, size: int, digest: str, what: str) -> list[str]:
    return [] if len(b) == size and sha(b) == digest else [f"bytes: the {what} is not the pinned file ({len(b)} bytes, sha256 {sha(b)[:16]}; pinned {size}, {digest[:16]})"]


def card_findings(b: bytes, with_pin: bool = True) -> list[str]:
    """Every finding of every rule on these bytes. with_pin=False leaves the byte pin out: the rules alone, as they stand when someone has repinned."""
    pin = byte_findings(b, CARD_SIZE, CARD_SHA256, "card") if with_pin else []
    if not b.isascii():
        return hygiene_findings(b) + pin
    t = b.decode("ascii")
    return (pin + hygiene_findings(b) + forbidden_findings(t) + surface_findings(t) + set_findings(t)
            + export_findings(t) + registration_findings(t) + access_findings(t) + redaction_findings(t))


# [6] the catalogue
def catalogue_findings(b: bytes, with_pin: bool = True) -> list[str]:
    out = byte_findings(b, CAT_SIZE, CAT_SHA256, "catalogue") if with_pin else []
    out += [f.replace("hygiene", "catalogue hygiene") for f in hygiene_findings(b)]
    try:
        text = b.decode("utf-8")
        d = G.parse_json(text)
    except (UnicodeDecodeError, ValueError) as ex:
        return out + [f"catalogue: not strict JSON ({str(ex)[:60]})"]
    if not isinstance(d, dict) or d.get("schema") != "ecco-geek-catalogue/1" or d.get("view_id") != "intelligence":
        out.append("catalogue: not the Intelligence catalogue of schema ecco-geek-catalogue/1")
        return out
    sources = d.get("sources") if isinstance(d.get("sources"), list) else []
    rows = sum(len(s.get("attributes", [])) for s in sources if isinstance(s, dict))
    alerts = d.get("alerts") if isinstance(d.get("alerts"), list) else []
    if (len(sources), rows, len(alerts)) != (CAT_COUNTS["sources"], CAT_COUNTS["attribute_rows"], CAT_COUNTS["alerts"]):
        out.append(f"catalogue: counts are {len(sources)} sources, {rows} attribute rows, {len(alerts)} alerts (pinned 17, 344, 19)")
    ids = [s.get("id") for s in sources if isinstance(s, dict)]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        out.append("catalogue: source ids are not unique non-empty text")
    aids = [a.get("id") for a in alerts if isinstance(a, dict)]
    if len(set(aids)) != len(aids):
        out.append("catalogue: alert ids are not unique")
    for name, rx in G.PRIVACY.items():
        m = rx.search(text)
        if m:
            out.append(f"catalogue: {name}-like text at offset {m.start()}")
    return out


def config_findings(text: str, example_text: str, cat: bytes) -> list[str]:
    out = G.problems(text, example_text, cat)
    b = text.encode("utf-8", "replace")
    if len(b) != CONFIG_SIZE or sha(b) != CONFIG_SHA256:
        out.append(f"config bytes: not the pinned generation ({len(b)} bytes, sha256 {sha(b)[:16]}; pinned {CONFIG_SIZE}, {CONFIG_SHA256[:16]})")
    return out


# =====================================================================================================================
print("[1] the bytes")
# =====================================================================================================================
CARD_B = (ROOT / CARD_REL).read_bytes() if (ROOT / CARD_REL).is_file() else b""
CAT_B = (ROOT / CAT_REL).read_bytes() if (ROOT / CAT_REL).is_file() else b""
LEDGER_B = (ROOT / LEDGER_REL).read_bytes() if (ROOT / LEDGER_REL).is_file() else b""
EXAMPLE_B = (ROOT / EXAMPLE_REL).read_bytes() if (ROOT / EXAMPLE_REL).is_file() else b""
check("the card, the catalogue, the ledger and the example exist", all((CARD_B, CAT_B, LEDGER_B, EXAMPLE_B)))
check("the card is pinned: size and sha256 of the committed bytes", byte_findings(CARD_B, CARD_SIZE, CARD_SHA256, "card") == [], str(byte_findings(CARD_B, CARD_SIZE, CARD_SHA256, "card")))
check("the catalogue is pinned: size and sha256", byte_findings(CAT_B, CAT_SIZE, CAT_SHA256, "catalogue") == [])
check("the ledger and the example are pinned: size and sha256", len(LEDGER_B) == LEDGER_SIZE and sha(LEDGER_B).startswith(LEDGER_SHA256_PREFIX)
      and len(EXAMPLE_B) == EXAMPLE_SIZE and sha(EXAMPLE_B) == EXAMPLE_SHA256, f"{len(LEDGER_B)} {sha(LEDGER_B)[:16]} {len(EXAMPLE_B)} {sha(EXAMPLE_B)[:16]}")
for what, b in (("card", CARD_B), ("catalogue", CAT_B), ("ledger", LEDGER_B)):
    check(f"the {what}: ASCII, LF only (no CR), no BOM, no NUL, one final newline", hygiene_findings(b) == [], str(hygiene_findings(b)))
# the example holds one non-ASCII character (a middle dot in the text fallback's template): it must be UTF-8, LF only, no BOM, no NUL
check("the example: UTF-8, LF only (no CR), no BOM, no NUL, one final newline (its two middle dots are escaped in the generated configuration)",
      [f for f in hygiene_findings(EXAMPLE_B) if "ASCII" not in f] == [] and EXAMPLE_B.decode("utf-8") is not None
      and [c for c in EXAMPLE_B.decode("utf-8") if ord(c) > 127] == ["\u00b7", "\u00b7"], str(hygiene_findings(EXAMPLE_B)))
eol = git_eol([CARD_REL, CAT_REL, LEDGER_REL, EXAMPLE_REL, PKG_REL])
if eol is None:
    skip("LF as stored by git for the card, the catalogue, the ledger, the example and package.json (i/lf)",
         "git or its index is not available here (an archive without .git); the working-tree checks above (no CR) still ran")
else:
    check("LF as stored by git for the card, the catalogue, the ledger, the example and package.json (i/lf)", all(eol.get(r) == "i/lf" for r in (CARD_REL, CAT_REL, LEDGER_REL, EXAMPLE_REL, PKG_REL)), str(eol))
check("a missing git is reported as 'not available' (None): the check above prints SKIP for it and never PASS", git_eol([CARD_REL], git="no-such-git-for-this-test") is None)
ledger = json.loads(LEDGER_B) if LEDGER_B else {}
check("the ledger is bound to this catalogue (its catalogue_sha256) and lists 361 rows: one per source and attribute",
      ledger.get("catalogue_sha256") == sha(CAT_B) and len(ledger.get("rows", [])) == CAT_COUNTS["ledger_rows"] == CAT_COUNTS["sources"] + CAT_COUNTS["attribute_rows"],
      f"{ledger.get('catalogue_sha256', '')[:16]} {len(ledger.get('rows', []))}")
pkg = json.loads((ROOT / PKG_REL).read_text(encoding="utf-8")) if (ROOT / PKG_REL).is_file() else {}
check("package.json: the shell's name, private, an ES module, GPL-3.0-or-later, no dependency of any kind, the test script runs every test file",
      pkg.get("name") == "ecco-mode-shell" and pkg.get("private") is True and pkg.get("type") == "module" and pkg.get("license") == "GPL-3.0-or-later"
      and not [k for k in pkg if "ependencies" in k] and pkg.get("scripts", {}).get("test") == "node --test test/*.test.mjs", str(pkg)[:200])

# =====================================================================================================================
print("")
print("[2] no write path, no network, no dynamic code")
# =====================================================================================================================
CARD_T = CARD_B.decode("ascii", "replace")
check("none of the forbidden APIs is named anywhere in the card, comments included (service calls, fetch, XMLHttpRequest, WebSocket, storage, eval, "
      "new Function, import(), cookies, postMessage, window.open, a location assignment, innerHTML, deferred work)", forbidden_findings(CARD_T) == [], str(forbidden_findings(CARD_T)))
check("the one comment that names innerHTML says it is never used", COMMENT_ALLOWED in CARD_T and CARD_T.count("innerHTML") == 1)
check("no URL scheme anywhere in the card (the SVG namespace is assembled from pieces, so the file holds no URL at all)", not re.search(FORBIDDEN["URL scheme"], CARD_T))

# =====================================================================================================================
print("")
print("[3] the allowed surface, exactly")
# =====================================================================================================================
check("every code line that names window, hass, the clipboard, a Blob URL, an event, a timer or an observer is on the pinned list (43 lines, in order)",
      surface_lines(CARD_T) == EXPECTED_SURFACE and len(EXPECTED_SURFACE) == 43, str(surface_findings(CARD_T)[:1]))
check("the facts one by one: one setInterval and its clear, one ResizeObserver, two window listeners and their removal (location-changed, pagehide), "
      "one dispatchEvent of hass-more-info, one clipboard write, one Blob download, listeners on elements only click / input / change / keydown",
      surface_findings(CARD_T) == [], str(surface_findings(CARD_T)))
hass_props = sorted(set(re.findall(r"\bhass\s*\.\s*(\w+)", "\n".join(s for s in code_lines(CARD_T) if "get hass" not in s and "set hass" not in s))))
check("the properties read from a hass value are states, locale (language) and themes (darkMode) only", hass_props == ["locale", "states", "themes"], str(hass_props))
check("no call is made on a hass value and no hass property is assigned (hass is only handed to child cards)",
      not re.search(r"\bhass\s*\.\s*\w+\s*\(|\bhass\s*\.\s*\w+\s*=(?!=)|\bhass\s*\[", "\n".join(code_lines(CARD_T))))

# =====================================================================================================================
print("")
print("[4] the sets that keep it read-only")
# =====================================================================================================================
check("the more-info domains (sensor, binary_sensor, event), the safe actions (none, more-info, navigate), the service-call keys, the write card types, the writable "
      "domains, the allowed card types and the one default custom card are the reviewed statements, each present once", set_findings(CARD_T) == [], str(set_findings(CARD_T)))
check("the card imports nothing (no import statement, no require)", not re.search(r"^\s*import\b", CARD_T, re.M) and "require(" not in CARD_T)
check("no computed member access on this, window, document, navigator or hass, no member name built from string pieces or a template literal, no global bound "
      "to a bare name, no call through a computed member (defence in depth: the byte pin is the guard)", access_findings(CARD_T) == [], str(access_findings(CARD_T)))
check("the redaction vocabulary is the pinned one: six word lists (41 secret words, 2 key words, 5 login words, 1 pass word, 31 private words, 4 digest keys) "
      "and the 23 value rules by reason", redaction_findings(CARD_T) == [] and [len(v) for v in REDACTION_SETS.values()] == [41, 2, 5, 1, 31, 4] and len(RULE_REASONS) == 23,
      str(redaction_findings(CARD_T)))

# =====================================================================================================================
print("")
print("[5] the export surface and the registration")
# =====================================================================================================================
check("41 exports, the reviewed names, all `export const|function|class`", export_findings(CARD_T) == [], str(export_findings(CARD_T)))
check("customElements.define once and guarded; one guarded window.customCards entry; one element class", registration_findings(CARD_T) == [], str(registration_findings(CARD_T)))

# =====================================================================================================================
print("")
print("[6] the catalogue")
# =====================================================================================================================
check("the catalogue: schema ecco-geek-catalogue/1, view intelligence, 17 sources, 344 attribute rows, 19 alerts, unique ids; no URL, address, MAC, e-mail, token, "
      "credential pair, blob, private path or coordinate", catalogue_findings(CAT_B) == [], str(catalogue_findings(CAT_B)))
check("the pattern list of the scan is the reviewed one (11 kinds), so a weakened scan is seen here",
      sorted(G.PRIVACY) == sorted(["url", "ipv4", "mac", "email", "token", "bearer", "credential_pair", "hex_blob", "base64_blob", "user_path", "coordinates"]))

# =====================================================================================================================
print("")
print("[7] the generated dashboard configuration")
# =====================================================================================================================
EX_T, CAT_B2 = G.read_inputs(ROOT)
CFG_T = G.generate(ROOT)
check("it is consistent with the committed catalogue and example (inline catalogue equal, same cards, no !include, no new card type, no write action but the "
      "pause tile's toggle in production) and deterministic", G.problems(CFG_T, EX_T, CAT_B2) == [] and G.generate(ROOT) == CFG_T, str(G.problems(CFG_T, EX_T, CAT_B2)))
check("it is the pinned generation: size and sha256 of the text the owner pastes", config_findings(CFG_T, EX_T, CAT_B2) == [], str(config_findings(CFG_T, EX_T, CAT_B2)))
cfg = json.loads(CFG_T)
check("its card is the shell with the 17-source catalogue inline, and the card's own tag is the one the card registers",
      cfg["views"][0]["cards"][0]["type"] == "custom:" + "ecco-mode-shell" and len(cfg["views"][0]["cards"][0]["catalogue"]["sources"]) == 17)

# =====================================================================================================================
print("")
print("[8] mutants")
# =====================================================================================================================
check("the unmutated inputs have no finding of any rule (negative control)", card_findings(CARD_B) == [] and catalogue_findings(CAT_B) == []
      and config_findings(CFG_T, EX_T, CAT_B2) == [], str(card_findings(CARD_B)[:2]))


def swap(old: str, new: str, count_: int = 1):
    assert CARD_T.count(old) >= 1, old
    return CARD_T.replace(old, new, count_).encode("utf-8")


def append(line: str):
    return (CARD_T + line + "\n").encode("utf-8")


DEFINE = "if (!customElements.get(TAG)) customElements.define(TAG, EccoModeShell);"
MUTANTS: list[tuple[str, bytes, str]] = [
    ("C01 fetch() added", append("fetch('x');"), "forbidden: fetch("),
    ("C02 call_service named", append("// call_service"), "forbidden: call_service"),
    ("C03 callService on hass", append("hass.callService('a', 'b');"), "forbidden: callService"),
    ("C04 XMLHttpRequest", append("new XMLHttpRequest();"), "forbidden: XMLHttpRequest"),
    ("C05 a WebSocket", append("new WebSocket('x');"), "forbidden: WebSocket"),
    ("C06 localStorage", append("localStorage.setItem('a', 'b');"), "forbidden: localStorage"),
    ("C07 sessionStorage", append("sessionStorage.clear();"), "forbidden: sessionStorage"),
    ("C08 eval()", append("eval('1');"), "forbidden: eval("),
    ("C09 new Function", append("new Function('return 1')();"), "forbidden: new Function"),
    ("C10 a dynamic import()", append("import('x');"), "forbidden: import("),
    ("C11 document.cookie", append("const c = document.cookie;"), "forbidden: document.cookie"),
    ("C12 postMessage", append("window.postMessage('x', '*');"), "forbidden: postMessage"),
    ("C13 window.open", append("window.open('x');"), "forbidden: window.open"),
    ("C14 a location assignment", append("window.location.href = 'x';"), "forbidden: location assignment"),
    ("C15 innerHTML", append("el.innerHTML = x;"), "forbidden: innerHTML"),
    ("C16 a second setInterval", append("setInterval(() => 0, 1);"), "surface:"),
    ("C17 the clearInterval removed", swap("if (this._timer !== null) clearInterval(this._timer);", "if (this._timer !== null) this._timer = null;"), "surface:"),
    ("C18 a third window listener", swap("window.addEventListener('pagehide', this._onPageHide);", "window.addEventListener('pagehide', this._onPageHide);\n      window.addEventListener('resize', this._onPageHide);"), "surface:"),
    ("C19 a window listener never removed", swap("      window.removeEventListener('pagehide', this._onPageHide);\n", ""), "surface:"),
    ("C20 a hass property read (connection)", swap("const s = hass && hass.states;", "const s = hass && hass.states;\n    const k = hass.connection;"), "surface:"),
    ("C21 a second dispatchEvent", append("document.dispatchEvent(new Event('x'));"), "surface:"),
    ("C22 sendBeacon", append("navigator.sendBeacon('x');"), "forbidden: sendBeacon"),
    ("C23 a domain with controls may open its dialog", swap("Object.freeze(['sensor', 'binary_sensor', 'event'])", "Object.freeze(['sensor', 'binary_sensor', 'event', 'switch'])"), "read-only sets"),
    ("C24 toggle becomes a safe action", swap("Object.freeze(['none', 'more-info', 'navigate'])", "Object.freeze(['none', 'more-info', 'navigate', 'toggle'])"), "read-only sets"),
    ("C25 a second default custom card", swap("Object.freeze(['custom:ecco-intelligence-card'])", "Object.freeze(['custom:ecco-intelligence-card', 'custom:x-card'])"), "read-only sets"),
    ("C26 an export removed", swap("export function cleanText(", "function cleanText("), "exports:"),
    ("C27 an export added", append("export const EXTRA_THING = 1;"), "exports:"),
    ("C28 the element not registered", swap(DEFINE, ""), "registration:"),
    ("C29 the card-picker entry pushed twice", append("window.customCards.push({ type: TAG });"), "registration:"),
    ("C30 a non-ASCII letter in a comment", swap("A presentation toggle only", "A presentation toggle only \u00e9"), "hygiene: not ASCII"),
    ("C31 CRLF line ends", CARD_B.replace(b"\n", b"\r\n"), "hygiene: a CR"),
    ("C32 a byte order mark", b"\xef\xbb\xbf" + CARD_B, "hygiene: a byte order mark"),
    ("C33 an import statement", b"import x from './x.js';\n" + CARD_B, "imports:"),
    ("C34 a second programmatic click", append("a.click();"), "surface:"),
    ("C35 a second Blob", append("const b2 = new Blob(['x']);"), "surface:"),
    ("C36 a service key used in a card config", append("const o = { perform_action: 'x' };"), "read-only sets: perform_action"),
    ("C37 a setTimeout (deferred work)", append("setTimeout(() => 0, 1);"), "forbidden: deferred work"),
    ("C38 a Promise chain on a hass call", append("Promise.resolve(1).then(() => 0);"), "forbidden: deferred work"),
    ("C39 a copy action reachable without a click", swap("on(csv, 'click', () => this.o.onDownload('csv', this._exportText('csv')));", "this.o.onDownload('csv', this._exportText('csv'));"), "surface:"),
]
for name, b, want in MUTANTS:
    found = card_findings(b)
    hit = [f for f in found if want in f]
    check(f"{name}: caught by {want!r}", bool(hit), "; ".join(found)[:200] or "NOT CAUGHT")
check("at least 25 card mutants are run", len(MUTANTS) >= 25 and len({n for n, _b, _w in MUTANTS}) == len(MUTANTS), str(len(MUTANTS)))
cm = CARD_T.replace("A presentation toggle only", "A presentation toggle onlz", 1).encode()
fm = card_findings(cm)
check("C40 one comment letter changed: only the byte pin fires (a deliberate edit of this file's pins is what it takes)", len(fm) == 1 and fm[0].startswith("bytes:"), str(fm))
check("the byte pin fires for every mutant above too (nothing slips through by a rule that was never run)", all(any(f.startswith("bytes:") for f in card_findings(b)) for _n, b, _w in MUTANTS))

# The review's own mutants, run the way a careless repin would leave them: with the byte pin OFF, so the RULES alone must see them. Not covered, and said so:
# a member name assembled in a variable first (const k = 'call' + 'Service'; z[k]) is seen only as "a call through a computed member"; a determined edit can
# always be written to get past a text rule. The byte pin and the reviewer's reading of the diff are the guards.
REDACT_LINE = re.compile(r"^  \['credential pair'.*\n", re.M)
RULE_MUTANTS: list[tuple[str, bytes, str]] = [
    ("R01 a hass taken from this by a built name: this['_ha' + 'ss']", append("const z = this['_ha' + 'ss'];"), "access: computed member access on this"),
    ("R02 the same with a space before the bracket", append("const z = this ['_hass'];"), "access: computed member access on this"),
    ("R03 a network call by a built name: window['fe' + 'tch']('x')", append("window['fe' + 'tch']('x');"), "access: a member name built from string pieces"),
    ("R04 a service call by a built name on an alias: z['call' + 'Service'](...)", append("const z = this._hass; z['call' + 'Service']('a', 'b');"), "access: a member name built from string pieces"),
    ("R05 a template literal as the member name", append("const f = z[`call${s}`];"), "access: a template literal used as a member name"),
    ("R06 this bound to a bare name", append("const z = this;"), "access: this, window or another global bound to a bare name"),
    ("R07 window assigned to a bare name", append("z = window;"), "access: this, window or another global bound to a bare name"),
    ("R08 a call through a computed member: z[k]('a')", append("z[k]('a');"), "access: a call through a computed member"),
    ("R09 optional-chained computed access on hass", append("const v = hass?.['x'];"), "access: computed member access on this"),
    ("R10 'password' removed from the secret words", swap("'password', 'passwords', ", ""), "redaction: SECRET_TOKENS"),
    ("R11 the last secret word removed", swap(", 'wifipw']", "]"), "redaction: SECRET_TOKENS"),
    ("R12 'email' removed from the private words", swap("'email', 'emails', ", ""), "redaction: PRIVATE_TOKENS"),
    ("R13 'key' removed from the key words", swap("new Set(['key', 'keys'])", "new Set(['keys'])"), "redaction: KEY_WORDS"),
    ("R14 a login word removed", swap("'usr', ", ""), "redaction: LOGIN_WORDS"),
    ("R15 a word added to the digest keys (a 40-hex name would be shown under it)", swap("'commitsha', 'gitcommit'", "'commitsha', 'gitcommit', 'anykey'"), "redaction: DIGEST_KEYS"),
    ("R16 the 'credential pair' value rule removed", REDACT_LINE.sub("", CARD_T, count=1).encode("utf-8"), "redaction: the value rules"),
]
check("the rules alone find nothing on the unchanged card (negative control, byte pin off)", card_findings(CARD_B, with_pin=False) == [], str(card_findings(CARD_B, with_pin=False)[:2]))
check("the R16 edit really removed one line (the rule mutant is not a no-op)", len(RULE_MUTANTS[-1][1]) < len(CARD_B) and RULE_MUTANTS[-1][1] != CARD_B)
for name, b, want in RULE_MUTANTS:
    off = card_findings(b, with_pin=False)
    check(f"{name}: caught by {want!r} with the byte pin OFF", any(want in f for f in off), "; ".join(off)[:200] or "NOT CAUGHT")
check(f"all {len(RULE_MUTANTS)} rule mutants are run, and the byte pin fires for each of them too", len(RULE_MUTANTS) >= 16
      and all(any(f.startswith("bytes:") for f in card_findings(b)) for _n, b, _w in RULE_MUTANTS))

CAT_T = CAT_B.decode("utf-8")
cat_d = json.loads(CAT_T)


def cat_mut(fn) -> bytes:
    d = json.loads(CAT_T)
    fn(d)
    return (json.dumps(d, indent=1) + "\n").encode("utf-8")


CAT_MUTANTS = [
    ("K01 a source dropped", cat_mut(lambda d: d["sources"].pop()), "counts"),
    ("K02 an attribute row dropped", cat_mut(lambda d: d["sources"][0]["attributes"].pop()), "counts"),
    ("K03 an alert dropped", cat_mut(lambda d: d["alerts"].pop()), "counts"),
    ("K04 a URL in a description", cat_mut(lambda d: d["sources"][0].__setitem__("description", "see https://example.invalid/x")), "url-like"),
    ("K05 a private address in a title", cat_mut(lambda d: d["sources"][0].__setitem__("title", "host " + ".".join(("10", "1", "2", "3")))), "ipv4-like"),
    ("K06 a token in a text", cat_mut(lambda d: d["sources"][0].__setitem__("description", "ghp_" + "a" * 36)), "token-like"),
    ("K07 another schema", cat_mut(lambda d: d.__setitem__("schema", "ecco-geek-catalogue/2")), "not the Intelligence catalogue"),
    ("K08 a duplicate key", CAT_B.replace(b'"view_id": "intelligence",', b'"view_id": "intelligence", "view_id": "x",', 1), "not strict JSON"),
    ("K09 a duplicate source id", cat_mut(lambda d: d["sources"][1].__setitem__("id", d["sources"][0]["id"])), "source ids"),
]
for name, b, want in CAT_MUTANTS:
    found = catalogue_findings(b)
    check(f"{name}: caught ({want})", any(want in f for f in found), "; ".join(found)[:200] or "NOT CAUGHT")
check("the byte pin alone catches a reformatted but equal catalogue (a deliberate regeneration is the only way through)",
      any(f.startswith("bytes:") for f in catalogue_findings((json.dumps(cat_d, indent=2) + "\n").encode())))


def cfg_mut(fn) -> str:
    c = json.loads(CFG_T)
    fn(c)
    return G.render(c)


CFG_MUTANTS = [
    ("G01 the inline catalogue differs", cfg_mut(lambda c: c["views"][0]["cards"][0]["catalogue"]["sources"].pop()), "inline catalogue"),
    ("G02 a write action in the always list", cfg_mut(lambda c: c["views"][0]["cards"][0]["always"][1].__setitem__("tap_action", {"action": "toggle"})), "action 'toggle'"),
    ("G03 a new card type", cfg_mut(lambda c: c["views"][0]["cards"][0]["production"].append({"type": "button"})), "card type 'button'"),
    ("G04 an !include left in", cfg_mut(lambda c: c["views"][0]["cards"][0].__setitem__("catalogue", "!include x.json")), "!include"),
]
for name, text, want in CFG_MUTANTS:
    found = config_findings(text, EX_T, CAT_B2)
    check(f"{name}: caught ({want})", any(want in f for f in found), "; ".join(found)[:200] or "NOT CAUGHT")
found = config_findings(CFG_T, EX_T.replace("Watchdog and status", "Watchdog and statuz"), CAT_B2)
check("G05 the example edited after the configuration was generated: caught (the configuration no longer equals the generation)", bool(found), str(found))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
if SKIPPED:
    print(f"all checks that could run passed; {len(SKIPPED)} SKIPPED (counted apart from PASS):")
    for s in SKIPPED:
        print(f"  - {s}")
else:
    print("all checks passed")
