#!/usr/bin/env python3
"""Render the prototype dashboard view to a static HTML page WITHOUT Home Assistant (local preview only).

It executes the dashboard's own button-card JavaScript templates in Node against a states dictionary built from
(a) the frozen mock sensor package and (b) a small SYNTHETIC sample of ECCO sensor values, lays the cards out on the
dashboard's 48-column grid with the production card styling, and draws the apexcharts SOC chart as inline SVG (an
approximation: in Home Assistant it is a real ApexCharts card). Needs Python + PyYAML + Node.

    python intelligence/tools/preview_dashboard.py [--out docs/intelligence/mockup/dashboard_prototype_preview.html]
    python intelligence/tools/preview_dashboard.py --check      # render + assert, write nothing
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROTO = ROOT / "home-assistant" / "prototypes" / "intelligence-v1"
DASH = PROTO / "ecco_intelligence_v1_prototype_dashboard.yaml"
PKG = PROTO / "ecco_intelligence_v1_mock_package.yaml"
SAMPLE = Path(__file__).resolve().parent / "preview_states.json"


def css(styles: list | None) -> str:
    out = []
    for item in styles or []:
        for k, v in item.items():
            out.append(f"{k}:{v}")
    return ";".join(out)


def build_states(sample: dict) -> dict:
    states: dict = {}
    pkg = yaml.safe_load(PKG.read_text(encoding="utf-8"))
    for s in pkg["template"][0]["sensor"]:
        states["sensor." + s["unique_id"]] = {"state": str(s["state"]), "attributes": s["attributes"]}
    for k, v in sample["states"].items():
        states[k] = {"state": str(v), "attributes": {}}
    return states


def run_templates(cards: list[dict], states: dict) -> list[dict]:
    """Evaluate every [[[ ]]] template of every card in Node. Returns, per card, {field: html}."""
    jobs = []
    for i, c in enumerate(cards):
        for fld, tpl in (c.get("custom_fields") or {}).items():
            t = str(tpl).strip()
            if t.startswith("[[[") and t.endswith("]]]"):
                jobs.append({"card": i, "field": fld, "code": t[3:-3]})
    js = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const states = input.states;
const out = [];
for (const j of input.jobs) {
  try {
    const fn = new Function('states', 'hass', 'entity', 'variables', 'user', j.code);
    const v = fn(states, {states}, {}, {}, {});
    out.push({card: j.card, field: j.field, html: String(v), error: null});
  } catch (e) { out.push({card: j.card, field: j.field, html: '', error: String(e && e.stack || e)}); }
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "run.js").write_text(js, encoding="utf-8")
        (Path(td) / "in.json").write_text(json.dumps({"states": states, "jobs": jobs}), encoding="utf-8")
        subprocess.run(["node", str(Path(td) / "run.js"), str(Path(td) / "in.json"), str(Path(td) / "out.json")], check=True)
        res = json.loads((Path(td) / "out.json").read_text(encoding="utf-8"))
    return res


def soc_svg(states: dict, sample: dict) -> str:
    traj = states["sensor.ecco_intelligence_trajectory"]["attributes"]["points"]
    st = states["sensor.ecco_intelligence_status"]["attributes"]
    gen = datetime.fromisoformat(st["generated_for"]).timestamp()
    floor, comfort = st["floor_pct"], st["desired_min_pct"]       # effective minimum and comfort line come from the report
    pts = [(datetime.fromisoformat(p[0]).timestamp() - gen, p[1], p[2], p[3]) for p in traj]      # seconds from "now"
    hist = [(-(len(sample["soc_history"]) - 1 - i) * 3600.0, v) for i, v in enumerate(sample["soc_history"])]
    t0, t1 = -12 * 3600.0, 36 * 3600.0
    W, H, L, R, T, B = 900, 300, 44, 12, 14, 30

    def x(t): return L + (t - t0) / (t1 - t0) * (W - L - R)
    def y(v): return T + (100 - v) / 100 * (H - T - B)
    def path(seq, idx=1): return " ".join(("M" if i == 0 else "L") + f"{x(p[0]):.1f},{y(p[idx]):.1f}" for i, p in enumerate(seq))
    grid = "".join(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="rgba(255,255,255,.08)"/>'
                   f'<text x="4" y="{y(v) + 4:.1f}" fill="rgba(255,255,255,.5)" font-size="10">{v}%</text>' for v in (0, 25, 50, 75, 100))
    ticks = "".join(f'<text x="{x(h * 3600):.1f}" y="{H - 10}" fill="rgba(255,255,255,.5)" font-size="10" text-anchor="middle">{"now" if h == 0 else f"{h:+d}h"}</text>'
                    for h in range(-12, 37, 12))
    ribbon = " ".join(f"{x(p[0]):.1f},{y(p[3]):.1f}" for p in pts) + " " + " ".join(f"{x(p[0]):.1f},{y(p[2]):.1f}" for p in reversed(pts))
    return f"""<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Battery SOC: actual history and predicted trajectory">
{grid}{ticks}
<polygon points="{ribbon}" fill="#b36cff" opacity="0.13"/>
<line x1="{L}" x2="{W - R}" y1="{y(floor):.1f}" y2="{y(floor):.1f}" stroke="#ff6376" stroke-width="1.6"/>
<text x="{W - R - 4}" y="{y(floor) - 4:.1f}" fill="#ff6376" font-size="10" text-anchor="end">Minimum battery reserve {floor:g}%</text>
<line x1="{L}" x2="{W - R}" y1="{y(comfort):.1f}" y2="{y(comfort):.1f}" stroke="#ffbd3d" stroke-width="1" stroke-dasharray="4 3"/>
<text x="{L + 4}" y="{y(comfort) - 4:.1f}" fill="#ffbd3d" font-size="10">Comfort margin {comfort:g}%</text>
<path d="{path(pts, 2)}" fill="none" stroke="#b36cff" stroke-width="1" stroke-opacity=".5" stroke-dasharray="5 4"/>
<path d="{path(pts, 3)}" fill="none" stroke="#b36cff" stroke-width="1" stroke-opacity=".5" stroke-dasharray="5 4"/>
<path d="{path(pts, 1)}" fill="none" stroke="#b36cff" stroke-width="3" stroke-dasharray="8 5"/>
<path d="{path(hist)}" fill="none" stroke="#42aaff" stroke-width="3"/>
<line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{T}" y2="{H - B}" stroke="rgba(255,255,255,.4)" stroke-dasharray="2 3"/>
</svg>
<div style="font-size:11px;color:rgba(255,255,255,.6);margin-top:4px;">
<span style="color:#42aaff">━ ACTUAL SOC (sample sensor history)</span> &nbsp; <span style="color:#b36cff">╍ PREDICTED median, thin dashed = pessimistic / optimistic band</span> &nbsp;
Preview approximation: in Home Assistant this is an apexcharts-card with the same series and annotations.</div>"""


def render(sample_path: Path = SAMPLE) -> tuple[str, list[str]]:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    dash = yaml.safe_load(DASH.read_text(encoding="utf-8"))
    templates = dash["button_card_templates"]
    states = build_states(sample)
    view = dash["views"][0]
    problems: list[str] = []
    body = []
    for sec in view["sections"]:
        cards = sec["cards"]
        results = run_templates(cards, states)
        by_card: dict[int, dict] = {}
        for r in results:
            if r["error"]:
                problems.append(f"{r['field']}: {r['error'][:200]}")
            by_card.setdefault(r["card"], {})[r["field"]] = r["html"]
        cells = []
        for i, c in enumerate(cards):
            cols = (c.get("grid_options") or {}).get("columns", 12)
            t = templates.get(c.get("template", ""), {})
            kind = c["type"].split(":")[-1]
            if kind == "heading":
                cells.append(f'<div class="cell" style="grid-column:span 48"><h2>{html.escape(c["heading"])}</h2></div>')
                continue
            if kind == "apexcharts-card":
                inner = soc_svg(states, sample)
                title = html.escape(c["header"]["title"])
                cells.append(f'<div class="cell" style="grid-column:span {cols}"><div class="card" style="{css((templates["ecco_stat"]["styles"]["card"]))}">'
                             f'<div class="ttl">{title}</div>{inner}</div></div>')
                continue
            card_css = css(t.get("styles", {}).get("card")) + ";" + css((c.get("styles") or {}).get("card"))
            fields = by_card.get(i, {})
            main = fields.get("body") or fields.get("detail") or fields.get("status") or ""
            icon = c.get("icon", "")
            cells.append(
                f'<div class="cell" style="grid-column:span {cols}"><div class="card" style="{card_css}">'
                f'<div class="ttl">{html.escape(c.get("name", ""))}</div><div class="fld">{main}</div></div></div>')
        body.append('<section class="grid">' + "".join(cells) + "</section>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ECCO Intelligence V1 - prototype dashboard preview</title>
<style>
body{{margin:0;background:#0b1120;color:#e8ecf5;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:18px}}
.note{{max-width:1180px;margin:0 auto 14px;padding:10px 14px;border:1px dashed rgba(255,255,255,.3);border-radius:12px;color:rgba(255,255,255,.75);font-size:12px}}
.grid{{max-width:1180px;margin:0 auto 14px;display:grid;grid-template-columns:repeat(48,minmax(0,1fr));gap:14px}}
.cell{{min-width:0;overflow-wrap:anywhere}} h2{{overflow-wrap:anywhere}} .card{{height:100%;box-sizing:border-box}} h2{{margin:6px 2px;font-size:22px}}
.ttl{{font-size:13px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;margin-bottom:8px;opacity:.9}}
.fld{{font-size:12px;line-height:1.55;color:rgba(255,255,255,.78)}}
table td,table th{{padding:2px 4px}}
@media (max-width:900px){{.cell{{grid-column:span 48 !important}}}}
</style></head><body>
<div class="note"><b>Static preview, rendered locally from the dashboard's own button-card JavaScript.</b> Not Home Assistant. Data: the frozen engine report in the mock
package (time-shifted to now) plus a small synthetic sample of sensor values (intelligence/tools/preview_states.json). Nothing here talks to any system.</div>
{''.join(body)}</body></html>"""
    return page, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    page, problems = render()
    if problems:
        print("TEMPLATE PROBLEMS:\n" + "\n".join(problems))
        return 1
    if a.check:
        print(f"render ok, {len(page)} bytes")
        return 0
    out = Path(a.out or ROOT / "docs" / "intelligence" / "mockup" / "dashboard_prototype_preview.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
