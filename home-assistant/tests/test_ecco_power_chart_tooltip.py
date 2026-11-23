#!/usr/bin/env python3
"""Power Flow Today chart: the shared tooltip stays inside the card and the viewport (post-export entry ptt1; dashboard 7.23.0, unchanged
version): offline proofs of the dashboard change and of its JavaScript. Display only: nothing here connects to Home Assistant, ESPHome or
InfluxDB, nothing is deployed, no control is exercised. NODE (20 or newer) IS REQUIRED: the checks that need it fail with a clear message
when it is missing, they are never skipped.

THE DEFECT. The chart (custom:apexcharts-card, three identical copies in the Overview, Intelligence and System views) shows a shared tooltip
with five readings. ApexCharts positions it from the plot grid only and the card's ha-card clips it (overflow hidden), so on the Overview
chart (card height 7 rows) the last reading, SOC, is cut off. THE FIX. One key per chart, apex_config.chart.events.mounted, an EVAL string
(apexcharts-card runs every apex_config string that starts with EVAL:, as the chart's TOU annotation already does) that moves the tooltip the
shortest way inside the card and the viewport. Its geometry is ONE pure function, fit(); the rest is glue (a MutationObserver on the chart,
pointer tracking, window scroll / resize, cleanup).

  [1]  the three charts: exactly three Power Flow Today charts (Overview, Intelligence, System), each with the same EVAL string
  [2]  nothing else moved: with apex_config.chart.events removed, the whole dashboard equals the 7.23.0 dashboard that the exact ptt1
       reverter rebuilds; the added text is exactly three copies of the block; the version record and the header are untouched
  [3]  the code is display-only and touches only the tooltip's position: no network, storage, service, eval or HTML-writing construct
  [4]  fit(): an exhaustive grid of tooltip sizes, bounds, positions and pointers (null pointer, bounds smaller than the tooltip included)
       against an independently written oracle: containment, identity, shortest move, flip rules, idempotence, purity, finite results
  [5]  mutants of fit(): at least 10 deliberate defects, each killed by [4]
  [6]  the glue against a DOM stand-in: no tooltip, inactive tooltip, bottom overflow fixed once and never re-written (no loop), pointer
       and touch tracking, scroll / resize, a detached card, destroy and re-mount clean up, only style.left / style.top are written
  [7]  mutants of the glue: each killed by [6]
  [8]  the chain: ptt1 is the newest post-export entry and declares exactly this dashboard edit; the frozen checkpoint is the file's hash
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _ptt1_scope as P  # noqa: E402  (the exact reverter of ptt1's dashboard edits: rebuilds the 7.23.0 dashboard)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


DASH_REL = P.DASHBOARD_REL
NEW_TEXT = (ROOT / DASH_REL).read_text(encoding="utf-8")
try:
    OLD_TEXT = P.pre_ptt1_dashboard(NEW_TEXT)
except AssertionError as exc:   # a failed proof, never a skipped one
    OLD_TEXT = ""
    print(f"  FAIL  the ptt1 reverter does not apply to the dashboard: {exc}")
    FAILURES.append("the ptt1 reverter applies to the dashboard")
NEW = yaml.safe_load(NEW_TEXT)
OLD = yaml.safe_load(OLD_TEXT) if OLD_TEXT else None


def charts(doc) -> list[tuple[str, dict]]:
    """Every Power Flow Today apexcharts-card: (JSON-pointer-like path, card)."""
    found: list[tuple[str, dict]] = []

    def walk(n, path):
        if isinstance(n, dict):
            if n.get("type") == "custom:apexcharts-card" and "Power Flow Today" in str((n.get("header") or {}).get("title", "")):
                found.append((path, n))
            for k, v in n.items():
                walk(v, path + "/" + str(k))
        elif isinstance(n, list):
            for i, v in enumerate(n):
                walk(v, path + "/" + str(i))
    walk(doc, "")
    return found


# ===========================================================================
print("[1] the three charts")
# ===========================================================================
CH = charts(NEW)
check("exactly three Power Flow Today charts: the Overview, Intelligence and System views",
      [p.split("/")[2] for p, _ in CH] == ["0", "2", "6"] and [NEW["views"][int(p.split("/")[2])]["path"] for p, _ in CH]
      == ["ecco-overview", "ecco-intelligence", "ecco-system"], str([p for p, _ in CH]))


def mounted_of(card) -> str:
    return (((card.get("apex_config") or {}).get("chart") or {}).get("events") or {}).get("mounted", "")


CODES = [mounted_of(c) for _, c in CH]
check("each chart has apex_config.chart.events.mounted as an EVAL string, and it is the only events key",
      len(CODES) == 3 and all(isinstance(c, str) and c.strip().startswith("EVAL:") for c in CODES)
      and all(list(c["apex_config"]["chart"]["events"]) == ["mounted"] for _, c in CH))
check("the three EVAL strings are byte-identical", len(set(CODES)) == 1 and CODES[0] != "")
CODE = CODES[0] if CODES else ""


def shape(card):
    """A chart with the two values that legitimately differ between the views (grid_options and the chart height) dropped."""
    import copy
    c = copy.deepcopy(card)
    c.pop("grid_options", None)
    c["apex_config"]["chart"].pop("height", None)
    return c


check("the three charts differ from each other only in chart.height (365 / 490 / 490) and grid_options, as in 7.23.0",
      len(CH) == 3 and shape(CH[1][1]) == shape(CH[0][1]) == shape(CH[2][1])
      and [c["apex_config"]["chart"]["height"] for _, c in CH] == [365, 490, 490]
      and [c["grid_options"] for _, c in CH] == [{"columns": "full", "rows": 7}, {"columns": 48, "rows": 10}, {"columns": 28, "rows": 11}])

# ===========================================================================
print("")
print("[2] nothing else moved")
# ===========================================================================
check("the 7.23.0 dashboard rebuilt by the exact ptt1 reverter has no chart events key at all",
      OLD is not None and all("events" not in ((c.get("apex_config") or {}).get("chart") or {}) for _, c in charts(OLD)) and len(charts(OLD)) == 3)


def without_events(doc):
    import copy
    d = copy.deepcopy(doc)
    for _, c in charts(d):
        del c["apex_config"]["chart"]["events"]
    return d


check("with apex_config.chart.events removed from the three charts the dashboard equals the 7.23.0 dashboard (every other value of every view)",
      OLD is not None and without_events(NEW) == OLD)
BLOCK = P.TOOLTIP_BLOCK
check("the added text is exactly three copies of the block (length and count)",
      OLD_TEXT != "" and len(NEW_TEXT) - len(OLD_TEXT) == 3 * len(BLOCK) and NEW_TEXT.count(BLOCK) == 3)


def round_trip_ok() -> bool:
    try:
        return P.add_ptt1_dashboard(OLD_TEXT) == NEW_TEXT
    except AssertionError:   # a failed proof, never a crash
        return False


check("the three edits are the declared ones (one per chart anchor) and applying them to the 7.23.0 dashboard gives exactly the dashboard",
      len(P.DASHBOARD_EDITS) == 3 and all(after == before + BLOCK for before, after in P.DASHBOARD_EDITS) and round_trip_ok())
ver = yaml.safe_load((ROOT / "VERSION.yaml").read_text(encoding="utf-8"))
check("the dashboard version is not bumped: VERSION.yaml still records 7.23.0 (staged) and the header keeps its v7.23.0 note",
      ver["current"]["dashboard"]["version"] == "7.23.0" and ver["current"]["dashboard"]["tested_in_home_assistant"] is False
      and "# v7.23.0 (OVW3, STAGED / NOT LIVE-PROVEN)" in NEW_TEXT.split("views:")[0])
check("the new text is LF only, tab free and ASCII inside the block", "\r" not in NEW_TEXT and "\t" not in BLOCK and BLOCK.isascii())

# ===========================================================================
print("")
print("[3] the code is display-only")
# ===========================================================================
SRC = CODE.strip()[len("EVAL:"):] if CODE else ""
BANNED = ["fetch", "XMLHttpRequest", "WebSocket", "sendBeacon", "localStorage", "sessionStorage", "indexedDB", "document.cookie", "eval(",
          "Function(", "import(", "require(", "innerHTML", "outerHTML", "textContent", "insertAdjacent", "appendChild", "removeChild",
          "classList.add", "classList.remove", "classList.toggle", "setAttribute", "callService", "hass", "location", "postMessage"]
check("no network, storage, service, eval or content-writing construct", bool(SRC) and not [b for b in BANNED if b in SRC], str([b for b in BANNED if b in SRC]))
writes = sorted(set(re.findall(r"\.style\.(\w+)\s*=", SRC)))
check("the only element property it assigns is style.left and style.top (the tooltip's position)", writes == ["left", "top"], str(writes))
check("it reads the tooltip only through .apexcharts-tooltip, never changes its class or content",
      "'.apexcharts-tooltip'" in SRC and "classList.contains('apexcharts-active')" in SRC)
check("it can be cleaned up: AbortController, MutationObserver.disconnect and a destroy wrapper are present",
      all(t in SRC for t in ("AbortController", "seen.disconnect()", "chart.destroy = function", "ac.abort()")))
check("it is small: under 60 lines and 3500 bytes", 0 < SRC.count("\n") < 60 and 0 < len(SRC) < 3500, f"{SRC.count(chr(10))} lines, {len(SRC)} bytes")

# ===========================================================================
print("")
print("[4]-[7] fit() and the glue under node")
# ===========================================================================
NODE = shutil.which("node")
check("node is available (required, never skipped)", NODE is not None, "install Node 20 or newer")

FIT_MUTANTS = [   # (name, old, new): each `old` is present exactly once in the code
    ("clamp order swapped (bottom-right alignment when the bounds are too small)", "Math.max(lo, Math.min(v, hi - n))", "Math.min(hi - n, Math.max(lo, v))"),
    ("clamp ignores the tooltip size at the far edge", "Math.min(v, hi - n)", "Math.min(v, hi)"),
    ("clamp has no lower bound", "Math.max(lo, Math.min(v, hi - n))", "Math.min(v, hi - n)"),
    ("clamp has no upper bound", "Math.max(lo, Math.min(v, hi - n))", "Math.max(lo, v)"),
    ("vertical clamp uses the horizontal bounds", "y = lim(r.y, r.h, b.t, b.b)", "y = lim(r.y, r.h, b.l, b.r)"),
    ("hit test is exclusive at the left edge", "p.x >= x &&", "p.x > x &&"),
    ("hit test is exclusive at the bottom edge", "p.y <= y + r.h", "p.y < y + r.h"),
    ("flips even when the tooltip already covered the pointer", "if (hit(x, y) && !hit(r.x, r.y)) {", "if (hit(x, y)) {"),
    ("never flips (the clamp alone)", "if (hit(x, y) && !hit(r.x, r.y)) {", "if (false) {"),
    ("flips both axes", "else if (y !== r.y && lift.length)", "if (y !== r.y && lift.length)"),
    ("gap ignored on the left flip", "p.x - g - r.w, p.x + g]", "p.x - r.w, p.x + g]"),
    ("gap ignored on the upward flip", "p.y - g - r.h, p.y + g]", "p.y - r.h, p.y + g]"),
    ("side preference inverted", "r.x > p.x ? 1 : 0", "r.x > p.x ? 0 : 1"),
    ("vertical preference inverted", "r.y > p.y ? 1 : 0", "r.y > p.y ? 0 : 1"),
    ("side candidates not checked against the right bound", "v >= b.l && v + r.w <= b.r", "v >= b.l"),
    ("lift candidates not checked against the top bound", "v >= b.t && v + r.h <= b.b", "v + r.h <= b.b"),
    ("flips x although x was not moved", "if (x !== r.x && side.length)", "if (side.length)"),
    ("null pointer not guarded", "p && p.x >= x", "p.x >= x"),
    ("result axes swapped", "return { x, y };", "return { x: y, y: x };"),
]
GLUE_MUTANTS = [
    ("destroy is not wrapped (no clean-up on destroy)", "chart.destroy = function () { ac.abort(); return drop.apply(this, arguments); };", ""),
    ("the observer is never disconnected", "seen.disconnect(); ", ""),
    ("a re-mount does not replace the previous instance", "if (el.__eccoTip) el.__eccoTip.abort();", ""),
    ("every observation rewrites the position (a feedback loop)", "Math.abs(q.x - r.x) > 0.5 || Math.abs(q.y - r.y) > 0.5", "true"),
    ("an inactive tooltip is moved too", " || !t.classList.contains('apexcharts-active')", ""),
    ("a detached card keeps its window listeners", "else off();", ";"),
    ("the viewport is ignored (the card alone)", "Math.min(k.bottom, v.offsetTop + v.height) - m", "k.bottom - m"),
    ("touch is not tracked", "['mousemove', 'touchstart', 'touchmove']", "['mousemove']"),
    ("scroll is not tracked", "window.addEventListener('scroll', win, true);", ""),
    ("the host offset is ignored (viewport coordinates written as card coordinates)", "t.style.left = q.x - ox + 'px';", "t.style.left = q.x + 'px';"),
]

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function load(code, sandbox) {
  const src = code.trim().replace(/^EVAL:/, '');
  return vm.runInNewContext('(' + src + ')', sandbox || Object.create(null), { timeout: 5000 });
}
// ---------------------------------------------------------------- [4] the pure function against an independent oracle
const EPS = 1e-9;
class Stop extends Error {}
function battery(fit, quick) {
  const bad = {}; const count = {};
  const note = (k, detail) => { count[k] = (count[k] || 0) + 1; if (!bad[k]) bad[k] = typeof detail === 'function' ? detail() : detail; if (quick) throw new Stop(); };
  const sizes = [[80, 40], [145, 193], [220, 120], [160, 330]];
  const boundsList = [
    { l: 0, t: 0, r: 400, b: 300 }, { l: 10, t: 20, r: 900, b: 700 }, { l: -50, t: -30, r: 120, b: 90 },
    { l: 5, t: 5, r: 150, b: 200 }, { l: 0, t: 0, r: 60, b: 30 }, { l: 100, t: 100, r: 100, b: 100 } ];
  const cl = (v, n, lo, hi) => (hi - lo >= n ? Math.min(Math.max(v, lo), hi - n) : lo);   // oracle: the tooltip fits -> clamp; else top / left aligned
  const gaps = [12, 6];
  let cases = 0;
  try {
  for (const [w, h] of sizes) for (const b of boundsList) {
    const fitsX = b.r - b.l >= w, fitsY = b.b - b.t >= h;
    const xs = [], ys = [];
    for (let i = 0; i <= 12; i++) { xs.push(b.l - 60 + (b.r - b.l + 120) * i / 12); ys.push(b.t - 60 + (b.b - b.t + 120) * i / 12); }
    xs.push(b.r - w, b.l, b.r - w + 0.25, b.l - 0.25); ys.push(b.b - h, b.t, b.b - h + 0.25, b.t - 0.25);
    for (const rx of xs) for (const ry of ys) {
      const r = { x: rx, y: ry, w, h };
      const cx = cl(rx, w, b.l, b.r), cy = cl(ry, h, b.t, b.b);
      const ptrs = [null];
      for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) ptrs.push({ x: b.l - 20 + (b.r - b.l + 40) * i / 4, y: b.t - 20 + (b.b - b.t + 40) * j / 4 });
      for (const [bx, by] of [[rx, ry], [cx, cy]]) for (const dx of [-1, 0, w / 2, w, w + 1]) for (const dy of [-1, 0, h / 2, h, h + 1]) ptrs.push({ x: bx + dx, y: by + dy });
      for (const p of ptrs) for (const g of gaps) {
        cases++;
        const rIn = { toString: () => JSON.stringify([r, p, b, g]) };
        const snap = [r.x, r.y, r.w, r.h, p && p.x, p && p.y, b.l, b.t, b.r, b.b, g];
        let res, res2;
        try { res = fit(r, p, b, g); } catch (e) { note('A throws', () => rIn + ' ' + e); continue; }
        if (snap.join() !== [r.x, r.y, r.w, r.h, p && p.x, p && p.y, b.l, b.t, b.r, b.b, g].join()) note('H inputs mutated', () => String(rIn));
        try { res2 = fit(r, p, b, g); } catch (e) { note('A throws', () => String(rIn)); continue; }
        if (res.x !== res2.x || res.y !== res2.y) note('H not deterministic', () => String(rIn));
        if (!Number.isFinite(res.x) || !Number.isFinite(res.y)) { note('A finite', () => rIn + JSON.stringify(res)); continue; }
        const inside = (x, y) => x >= b.l - EPS && y >= b.t - EPS && x + w <= b.r + EPS && y + h <= b.b + EPS;
        const hit = (x, y) => p !== null && p.x >= x && p.x <= x + w && p.y >= y && p.y <= y + h;
        // B containment when the bounds can hold the tooltip
        if (fitsX && fitsY && !inside(res.x, res.y)) note('B containment', () => rIn + JSON.stringify(res));
        if (fitsX && (res.x < b.l - EPS || res.x + w > b.r + EPS)) note('B containment x', () => String(rIn));
        if (fitsY && (res.y < b.t - EPS || res.y + h > b.b + EPS)) note('B containment y', () => String(rIn));
        // C identity when already inside
        if (inside(rx, ry) && (res.x !== rx || res.y !== ry)) note('C identity', () => rIn + JSON.stringify(res));
        // D too small: aligned to the top left
        if (!fitsX && Math.abs(res.x - b.l) > EPS) note('D left aligned', () => String(rIn));
        if (!fitsY && Math.abs(res.y - b.t) > EPS) note('D top aligned', () => String(rIn));
        // E idempotent
        let again; try { again = fit({ x: res.x, y: res.y, w, h }, p, b, g); } catch (e) { note('E throws', () => String(rIn)); continue; }
        if (Math.abs(again.x - res.x) > EPS || Math.abs(again.y - res.y) > EPS) note('E idempotent', () => rIn + JSON.stringify([res, again]));
        // I null pointer: the clamp alone
        if (p === null && (Math.abs(res.x - cx) > EPS || Math.abs(res.y - cy) > EPS)) note('I null pointer', () => String(rIn));
        // F shortest move unless flipped; G a flip is made whenever it is allowed and needed
        const sideC = [p && p.x - g - w, p && p.x + g].filter((v) => p && v >= b.l - EPS && v + w <= b.r + EPS);
        const liftC = [p && p.y - g - h, p && p.y + g].filter((v) => p && v >= b.t - EPS && v + h <= b.b + EPS);
        const needFlip = p !== null && hit(cx, cy) && !hit(rx, ry);
        const flipX = needFlip && cx !== rx && sideC.length > 0;
        const flipY = needFlip && !flipX && cy !== ry && liftC.length > 0;
        const wantX = flipX ? (sideC.length > 1 ? (rx > p.x ? p.x + g : p.x - g - w) : sideC[0]) : cx;
        const wantY = flipY ? (liftC.length > 1 ? (ry > p.y ? p.y + g : p.y - g - h) : liftC[0]) : cy;
        if (Math.abs(res.x - wantX) > EPS || Math.abs(res.y - wantY) > EPS) note('F/G expected position', () => rIn + ' got ' + JSON.stringify(res) + ' want ' + JSON.stringify([wantX, wantY]));
        if (flipX || flipY) { if (hit(res.x, res.y)) note('G flip leaves the pointer covered', () => String(rIn)); }
      }
    }
  }
  } catch (e) { if (!(e instanceof Stop)) throw e; }
  return { cases, bad, count };
}
const out = { original: null, mutants: {}, glue: null, glueMutants: {} };
const fit0 = load(spec.code).fit;
out.original = battery(fit0);
for (const m of spec.fitMutants) {
  let f; try { f = load(m.code).fit; } catch (e) { out.mutants[m.name] = { error: String(e) }; continue; }
  const r = battery(f, true); out.mutants[m.name] = { killedBy: Object.keys(r.bad) };
}
// ---------------------------------------------------------------- [6] the glue against a DOM stand-in
function glueRun(code) {   // an exception inside the run (a missing listener, a broken glue) is itself a failed check, never a crash of the proof
  const res = {};
  try { return glueRun0(code, res); } catch (e) { res['the glue run completes without an exception'] = false; res['the glue run completes without an exception detail'] = String(e); return res; }
}
function glueRun0(code, res) {
  const ok = (k, v, d) => { res[k] = !!v; if (!v) res[k + ' detail'] = d || ''; };
  const win = { winL: [], addEventListener(t, f, o) { this.winL.push([t, f, o]); }, removeEventListener(t, f, o) { this.winL = this.winL.filter(([a, b]) => !(a === t && b === f)); },
                visualViewport: null, innerWidth: 1000, innerHeight: 700 };
  let observers = [];
  class MO { constructor(cb) { this.cb = cb; this.live = false; observers.push(this); } observe() { this.live = true; } disconnect() { this.live = false; } }
  const sandbox = { window: win, MutationObserver: MO, AbortController, innerWidth: 1000, innerHeight: 700, Math, isFinite, parseFloat };
  const mounted = load(code, sandbox);
  const sets = [];           // every property write on the tooltip
  const card = { rect: { left: 100, top: 50, right: 700, bottom: 450 }, getBoundingClientRect() { return { ...this.rect }; } };
  const host = { clientLeft: 0, clientTop: 0, rect: { left: 100, top: 50 }, getBoundingClientRect() { return { ...this.rect }; } };
  const tipState = { active: true, left: 300, top: 300, w: 140, h: 190 };
  const style = new Proxy({}, { get: (_, k) => (k === 'left' ? tipState.left + 'px' : k === 'top' ? tipState.top + 'px' : undefined),
    set: (_, k, v) => { sets.push(k); if (k === 'left') tipState.left = parseFloat(v); else if (k === 'top') tipState.top = parseFloat(v); return true; } });
  const tip = new Proxy({ style, offsetParent: host, classList: { contains: (c) => c === 'apexcharts-active' && tipState.active }, closest: (s) => (s === 'ha-card' ? card : null),
    getBoundingClientRect: () => ({ left: host.rect.left + tipState.left, top: host.rect.top + tipState.top, width: tipState.w, height: tipState.h, right: host.rect.left + tipState.left + tipState.w, bottom: host.rect.top + tipState.top + tipState.h }) },
    { set: (_, k) => { sets.push('!' + String(k)); return true; } });
  const elL = [];
  const el = { isConnected: true, tipPresent: true, querySelector: (s) => (s === '.apexcharts-tooltip' && el.tipPresent ? tip : null),
    addEventListener(t, f, o) { const rec = { t, f, o }; elL.push(rec); if (o && o.signal) o.signal.addEventListener('abort', () => { const i = elL.indexOf(rec); if (i >= 0) elL.splice(i, 1); }); } };
  let destroyed = 0;
  const chart = { el, destroy() { destroyed++; return 'done'; } };
  const fire = (obs) => { for (const o of observers.filter((x) => x.live)) o.cb([]); };
  let t1 = null;
  try { mounted(chart); } catch (e) { ok('mounted() does not throw', false, String(e)); return res; }
  ok('mounted() does not throw', true);
  ok('one observer and mouse, touchstart, touchmove, scroll and resize are registered',
     observers.filter((o) => o.live).length === 1 && ['mousemove', 'touchstart', 'touchmove'].every((n) => elL.some((l) => l.t === n)) && win.winL.map((x) => x[0]).sort().join() === 'resize,scroll', JSON.stringify([observers.length, elL.map((l) => l.t), win.winL.map((x) => x[0])]));
  // T1 no tooltip element: nothing throws, nothing is written
  el.tipPresent = false; try { fire(); ok('T1 absent tooltip: no throw', true); } catch (e) { ok('T1 absent tooltip: no throw', false, String(e)); }
  el.tipPresent = true; ok('T1 absent tooltip: nothing written', sets.length === 0, sets.join());
  // T2 inactive tooltip is left alone even when outside
  tipState.active = false; tipState.top = 400; fire(); ok('T2 inactive tooltip: not moved', sets.length === 0 && tipState.top === 400, sets.join());
  tipState.active = true;
  // T3 bottom overflow (card bottom 450 -> inset 446): tooltip 190 high at host top 50 + 300 = 350 .. 540: moved up by 94; left unchanged; written once
  tipState.left = 200; tipState.top = 300; sets.length = 0; fire();
  const bottom = host.rect.top + tipState.top + tipState.h;
  ok('T3 bottom overflow: the tooltip ends inside the card (4 px inset)', Math.abs(bottom - 446) < 1e-6 && tipState.left === 200, JSON.stringify({ bottom, left: tipState.left }));
  ok('T3 only style.left / style.top are written', sets.length > 0 && sets.every((k) => k === 'left' || k === 'top'), sets.join());
  const n3 = sets.length; fire(); fire(); ok('T3 no loop: observing the corrected tooltip again writes nothing', sets.length === n3, sets.join());
  // T4 right overflow (card right 700, inset 696): the tooltip starts at host 100 + 560 = 660 (to 800); the pointer is 20 px to its left, so the
  // shortest move (to 556..696) would put it under the pointer: it is put to the left of the pointer instead (x = 640 - 12 - 140 = 488)
  const mm = elL.find((l) => l.t === 'mousemove');
  const rectNow = () => ({ l: host.rect.left + tipState.left, t: host.rect.top + tipState.top, r: host.rect.left + tipState.left + tipState.w, b: host.rect.top + tipState.top + tipState.h });
  const covers = (x, y) => { const q = rectNow(); return x >= q.l && x <= q.r && y >= q.t && y <= q.b; };
  tipState.left = 560; tipState.top = 100; sets.length = 0; mm.f({ clientX: 640, clientY: 210 }); fire();
  ok('T4 right overflow: inside the card, beside (not under) the pointer, y unchanged', rectNow().r <= 696 + 1e-6 && !covers(640, 210) && Math.abs(rectNow().l - 488) < 1e-6 && tipState.top === 100, JSON.stringify([rectNow(), tipState]));
  // T5 touch drives the pointer too
  const ts = elL.find((l) => l.t === 'touchstart');
  tipState.left = 560; tipState.top = 100; ts.f({ touches: [{ clientX: 640, clientY: 210 }] }); fire();
  ok('T5 touch: the same result as the mouse', rectNow().r <= 696 + 1e-6 && !covers(640, 210) && Math.abs(rectNow().l - 488) < 1e-6, JSON.stringify(rectNow()));
  // T6 the viewport bounds too: a short viewport (card bottom 450, viewport bottom 300)
  win.visualViewport = { offsetLeft: 0, offsetTop: 0, width: 1000, height: 300 };
  tipState.left = 200; tipState.top = 100; fire(); ok('T6 viewport: ends inside the viewport (300 - 4)', host.rect.top + tipState.top + tipState.h <= 296 + 1e-6, JSON.stringify(tipState));
  win.visualViewport = null;
  // T7 scroll and resize re-place a visible tooltip without a pointer move
  const scroll = win.winL.find((x) => x[0] === 'scroll')[1];
  tipState.left = 200; tipState.top = 100; card.rect = { left: 100, top: 50, right: 700, bottom: 450 }; host.rect = { left: 100, top: 50 };
  card.rect = { left: 100, top: 20, right: 700, bottom: 300 }; host.rect = { left: 100, top: 20 }; scroll();
  ok('T7 scroll: re-placed inside the moved card', host.rect.top + tipState.top + tipState.h <= 296 + 1e-6, JSON.stringify(tipState));
  card.rect = { left: 100, top: 50, right: 700, bottom: 450 }; host.rect = { left: 100, top: 50 };
  // T8 a detached card: the window listeners remove themselves and nothing is written
  el.isConnected = false; sets.length = 0; tipState.top = 400; scroll();
  ok('T8 detached card: window listeners removed, nothing written', win.winL.length === 0 && sets.length === 0, JSON.stringify([win.winL.length, sets]));
  el.isConnected = true;
  // T9 re-mount on the same element replaces the previous instance (no stacking)
  const before = observers.length; const live1 = observers.filter((o) => o.live).length;
  const chart2 = { el, destroy() { return 2; } }; mounted(chart2);
  ok('T9 re-mount: the previous observer is disconnected and exactly one is live', observers.filter((o) => o.live).length === 1 && observers.length === before + 1 && live1 === 1, JSON.stringify([live1, observers.filter((o) => o.live).length]));
  ok('T9 re-mount: the element listeners are not stacked', ['mousemove', 'touchstart', 'touchmove'].every((n) => elL.filter((l) => l.t === n).length === 1), elL.map((l) => l.t).join());
  // T10 destroy cleans up and still calls the chart's own destroy
  const rv = chart2.destroy();
  ok('T10 destroy: the chart\'s own destroy still runs and its value is kept', rv === 2);
  ok('T10 destroy: observer disconnected, element and window listeners removed', observers.filter((o) => o.live).length === 0 && elL.length === 0 && win.winL.length === 0, JSON.stringify([observers.filter((o) => o.live).length, elL.length, win.winL.length]));
  return res;
}
out.glue = glueRun(spec.code);
for (const m of spec.glueMutants) {
  let r; try { r = glueRun(m.code); } catch (e) { out.glueMutants[m.name] = { error: String(e) }; continue; }
  out.glueMutants[m.name] = { failed: Object.keys(r).filter((k) => !k.endsWith(' detail') && r[k] === false) };
}
console.log(JSON.stringify(out));
"""

NODE_RESULT = None
if NODE and CODE:
    def mutate(old: str, new: str, tag: str) -> str:
        assert SRC.count(old) == 1, f"mutant {tag!r}: the anchor must occur exactly once, found {SRC.count(old)}x: {old[:50]!r}"
        return "EVAL:" + SRC.replace(old, new)
    spec = {"code": CODE,
            "fitMutants": [{"name": n, "code": mutate(o, w, n)} for n, o, w in FIT_MUTANTS],
            "glueMutants": [{"name": n, "code": mutate(o, w, n)} for n, o, w in GLUE_MUTANTS]}
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "run.js").write_text(RUNNER, encoding="utf-8")
        (Path(td) / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        try:
            proc = subprocess.run([NODE, "--max-old-space-size=1024", str(Path(td) / "run.js"), str(Path(td) / "spec.json")],
                                  capture_output=True, text=True, timeout=300, cwd=td)
            if proc.returncode == 0:
                NODE_RESULT = json.loads(proc.stdout.strip().splitlines()[-1])
            else:
                print(f"  node failed ({proc.returncode}): {proc.stderr[-600:]}")
        except (subprocess.TimeoutExpired, ValueError) as exc:
            print(f"  node run failed: {exc}")
check("the node run completed", NODE_RESULT is not None)

if NODE_RESULT:
    O = NODE_RESULT["original"]
    check(f"[4] fit(): {O['cases']} cases (sizes x bounds x positions x pointers x gaps) satisfy every property of the oracle: finite, contained when "
          "the bounds can hold the tooltip, identity when already inside, top-left aligned when the bounds are too small, idempotent, pure, "
          "null pointer = the clamp, shortest move, the declared flips and their preference",
          O["cases"] > 100000 and not O["bad"], json.dumps(O["bad"])[:700])
    check("[5] the mutant list has at least 10 distinct mutants", len({n for n, _, _ in FIT_MUTANTS}) >= 10 and len(FIT_MUTANTS) >= 10, str(len(FIT_MUTANTS)))
    survived = [n for n, r in NODE_RESULT["mutants"].items() if "error" in r or not r["killedBy"]]
    check(f"[5] every one of the {len(FIT_MUTANTS)} fit() mutants is killed", not survived and len(NODE_RESULT["mutants"]) == len(FIT_MUTANTS), str(survived))
    for n, r in NODE_RESULT["mutants"].items():
        print(f"        killed  {n}  by  {', '.join(r.get('killedBy', [])[:3])}")
    G = NODE_RESULT["glue"]
    gfail = [k for k, v in G.items() if v is False]
    check(f"[6] the glue against the DOM stand-in: all {sum(1 for k in G if not k.endswith(' detail'))} checks hold", not gfail and len(G) >= 12,
          json.dumps({k: G.get(k + ' detail') for k in gfail})[:700])
    gsurv = [n for n, r in NODE_RESULT["glueMutants"].items() if "error" in r or not r["failed"]]
    check(f"[7] every one of the {len(GLUE_MUTANTS)} glue mutants is killed", not gsurv and len(NODE_RESULT["glueMutants"]) == len(GLUE_MUTANTS), str(gsurv))
    for n, r in NODE_RESULT["glueMutants"].items():
        print(f"        killed  {n}  by  {', '.join(r.get('failed', [])[:2])}")

# ===========================================================================
print("")
print("[8] the chain")
# ===========================================================================
import _scope_chain as sc  # noqa: E402

POST = sc.POST_EXPORT_ENTRIES
ids = [e.id for e in POST]
E = next((e for e in POST if e.id == "ptt1"), None)
check("ptt1 is a post-export entry and declares exactly the dashboard edit (frozen reverter = this module's, one file, no chain-pinned edit)",
      E is not None and set(E.frozen_reverts) == {DASH_REL} and E.frozen_reverts[DASH_REL] is P.pre_ptt1_dashboard and not E.reverts
      and E.added_files == P.ADDED_FILES and all((ROOT / f).is_file() for f in E.added_files), str(ids[-3:]))
check("its frozen checkpoint is the dashboard's sha256 (LF)", E is not None and E.frozen_checkpoints == {DASH_REL: sha(NEW_TEXT)})
check("ptt1 declares no firmware, package, manifest, registry or Modbus change: no delta, op path, include, substitution or banned token",
      E is not None and not (E.deltas or E.op_paths_changed or E.includes_added or E.subst_added or E.subst_changed or E.subst_removed
                             or E.fbh_includers or E.banned_fw_added or E.banned_files or E.tags_declared or E.tags_promoted))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All Power Flow chart tooltip checks PASSED.")
print("NOTE: this proves the tooltip code's geometry and glue offline (and, with the harness of the change record, in headless Chrome); it does")
print("not prove how the production Home Assistant renders it. The dashboard remains STAGED / NOT LIVE-PROVEN.")
