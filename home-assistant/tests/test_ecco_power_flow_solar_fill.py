#!/usr/bin/env python3
"""ovw5: the Solar series of each Power Flow Today chart carries its own group_by (func avg, duration 5min, fill last) in the repository's
own dashboard (offline, stdlib + PyYAML).

THE DEFECT. The chart (custom:apexcharts-card, three copies: the Overview, Intelligence and System views) draws five series. apexcharts-card
shows its shared tooltip with every series only while all series have the same time points; when one series has fewer it shows only the
series nearest the cursor. `all_series_config.group_by` groups every series per 5 minutes and turns an EMPTY bucket into a null point
(`fill: 'null'`), and the card drops the trailing buckets of a series that hold no value (empty, or a single null point): whenever the PV
reading did not change inside the newest bucket (evening and night) the Solar series ended one bucket before the others and the tooltip
listed Solar alone (measured on the production Overview on 25 Nov 2026).
THE FIX. The Solar series of each chart gets its own `group_by` with `fill: last` (four lines per chart, twelve in all), as the SOC series
already has: an empty bucket takes the last known value, so Solar ends with the other series. Applied to the production Overview first; this
suite pins the same text in the repository's dashboard.
THE CARD (read from the installed apexcharts-card 2.2.3 source; a third-party HACS card, not part of this repository, and NOT run here).
group_by.fill accepts `last`, `zero` and `null` and has NO age limit. For an empty 5-minute bucket up to now, `last` takes the last value of the
previous non-empty bucket, `zero` takes 0 and `null` takes a null point; buckets after now are not filled. A state that is not a number (an
entity that was `unavailable`) is turned into a null point when the history is read, so its bucket is not empty, is not filled, and the empty
buckets after it inherit that null. The card then drops the trailing buckets of a series that are empty or a single null point.
THE TRADE-OFF (recorded in docs/dev/post-export-edit-layer.md, checked below). `fill: last` has no age limit: a reading that keeps its last
value (held, stale) is drawn flat, exactly as a steady reading would be. An entity that goes `unavailable` still draws a gap. A freshness
limit (a template sensor that is `unavailable` unless the dongle's telemetry is live, used as the Solar series entity) is NOT built.

The dashboard is read as ovw5 left it (as of ovw5, a later post-export entry undone), so a later entry that edits it again cannot break this suite.

Proves (display configuration only; nothing here proves behaviour on a real Home Assistant or in a browser, and the card is not run):
  1. the ONE pair of registry/tests/_ovw5_scope.py (the Solar series, and the same with its group_by) is found exactly three times before
     and made exactly three times; its three declared hunks (one per chart) are each unique, apply once, revert once and round-trip on the
     dashboard text; an edited-twice, partly edited, altered or edit-free text is refused;
  2. the dashboard has exactly three Power Flow Today charts and each one's Solar series (the repository's generic entity) has exactly the
     group_by {func avg, duration 5min, fill last}; no other Solar series exists;
  3. nothing else moved: the other four series, the chart's other keys, every other view and card are as before (the parsed difference is
     exactly three added keys), the SOC series keeps its own group_by, `all_series_config.group_by` keeps fill 'null', and the protected layer
     (the Overview's flow card, /views/0/sections/2/cards/0) is byte-identical;
  4. no site value in the new text; the text is LF only, tab free and ASCII;
  5. the documentation records the trade-off and the freshness limit that is not built;
  6. the chain: ovw5 follows ovw4, declares exactly this dashboard edit and its checkpoint is the file's hash; ptt1's reverter refuses the
     dashboard while ovw5 is applied (ovw5 edits text inside its anchors), so the chain order is what lets the earlier proofs read it.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "registry" / "tests"))
import _ovw4_scope as S4  # noqa: E402
import _ovw5_scope as S  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite pins the dashboard as ovw5 left it; a later post-export entry may edit the dashboard again)
import _ptt1_scope as P1  # noqa: E402
import _scope_chain as sc  # noqa: E402

FAILURES: list[str] = []

SOLAR_GROUP_BY = {"func": "avg", "duration": "5min", "fill": "last"}
SOC_GROUP_BY = {"func": "last", "duration": "5min", "fill": "last"}
ALL_SERIES_GROUP_BY = {"func": "avg", "duration": "5min", "fill": "null"}   # the string 'null' (quoted in the file), not YAML null
FLOW_CARD = "/views/0/sections/2/cards/0"   # the site policy's protected layer


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILURES.append(name)


def power_flow_charts(doc) -> list[tuple[str, dict]]:
    """Every Power Flow Today apexcharts-card: (pointer, card)."""
    found: list[tuple[str, dict]] = []

    def go(n, path):
        if isinstance(n, dict):
            if n.get("type") == "custom:apexcharts-card" and "Power Flow Today" in str((n.get("header") or {}).get("title", "")):
                found.append((path, n))
            for k, v in n.items():
                go(v, f"{path}/{k}")
        elif isinstance(n, list):
            for i, v in enumerate(n):
                go(v, f"{path}/{i}")
    go(doc, "")
    return found


def solar_series(doc) -> list[str]:
    """Pointers of every series named Solar in any apexcharts-card of the dashboard."""
    found: list[str] = []

    def go(n, path):
        if isinstance(n, dict):
            if n.get("type") == "custom:apexcharts-card":
                for i, s in enumerate(n.get("series") or []):
                    if isinstance(s, dict) and s.get("name") == "Solar":
                        found.append(f"{path}/series/{i}")
            for k, v in n.items():
                go(v, f"{path}/{k}")
        elif isinstance(n, list):
            for i, v in enumerate(n):
                go(v, f"{path}/{i}")
    go(doc, "")
    return found


def differences(a, b, path="", out=None) -> list[tuple[str, str]]:
    """The exact set of parsed differences (kind, pointer), as tools' structural comparison reports them."""
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append(("ADDED", f"{path}/{k}"))
            elif k not in b:
                out.append(("REMOVED", f"{path}/{k}"))
            else:
                differences(a[k], b[k], f"{path}/{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(("LISTLEN", path))
        for i, (x, y) in enumerate(zip(a, b)):
            differences(x, y, f"{path}/{i}", out)
    elif a != b:
        out.append(("CHANGED", path))
    return out


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def at(doc, pointer: str):
    node = doc
    for part in pointer.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def raises(fn, *args) -> bool:
    try:
        fn(*args)
    except AssertionError:
        return True
    return False


# PEX: the dashboard as ovw5 left it (every later post-export entry undone, exact and sha256-checked at every step; the identity while ovw5 is the newest)
live = _pex.as_of(S.DASHBOARD_REL, "ovw5", (REPO / S.DASHBOARD_REL).read_text(encoding="utf-8"))
try:
    pre = S.pre_ovw5_dashboard(live)
except AssertionError as exc:   # a failed proof, never a skipped one
    pre = ""
    print(f"  FAIL  the ovw5 reverter does not apply to the dashboard: {exc}")
    FAILURES.append("the ovw5 reverter applies to the dashboard")
BLOCK = S.SOLAR_GROUP_BY

# ===========================================================================
print("[1] the one pair and its three hunks")
# ===========================================================================
check("the reverter removes the edits and the round trip restores the text exactly",
      pre != "" and S.add_ovw5_dashboard(pre) == live)
check("the ONE pair is found exactly three times before ovw5 and its edited form exactly three times after (none before)",
      pre.count(S.SOLAR_BEFORE) == S.CHARTS == 3 and live.count(S.SOLAR_AFTER) == 3 and pre.count(S.SOLAR_AFTER) == 0
      and S.SOLAR_PAIR == (S.SOLAR_BEFORE, S.SOLAR_AFTER) and S.SOLAR_AFTER == S.SOLAR_BEFORE + BLOCK,
      f"{pre.count(S.SOLAR_BEFORE)} / {live.count(S.SOLAR_AFTER)}")
check("the inserted text is exactly three copies of the four-line block (twelve lines, nothing removed)",
      BLOCK.count("\n") == 4 and len(live) - len(pre) == 3 * len(BLOCK) and live.count("\n") - pre.count("\n") == 12)
check("the pair is declared as three hunks, each the pair reached through its own chart (title and series list), each unique in the earlier text",
      len(S.DASHBOARD_EDITS) == 3 and all(
          after == before + BLOCK and before.endswith("            series:\n" + S.SOLAR_BEFORE)
          and "title: Power Flow Today" in before and pre.count(before) == 1 and live.count(after) == 1
          for before, after in S.DASHBOARD_EDITS))
check("the hunks tell the three charts apart by their grid options (Overview 7 rows, Intelligence 10, System 11) and by nothing else",
      [b[:b.index("            header:")] for b, _ in S.DASHBOARD_EDITS] == list(S.GRID_OPTIONS)
      and len({b[b.index("            header:"):] for b, _ in S.DASHBOARD_EDITS}) == 1)
one_chart_unedited = live.replace(S.SOLAR_AFTER, S.SOLAR_BEFORE, 1)
one_block_altered = live.replace(S.SOLAR_AFTER, S.SOLAR_AFTER.replace("fill: last", "fill: null"), 1)
check("an edited-twice, partly edited, altered or edit-free text is refused, in both directions",
      raises(S.pre_ovw5_dashboard, pre) and raises(S.add_ovw5_dashboard, live)
      and raises(S.pre_ovw5_dashboard, one_chart_unedited) and raises(S.pre_ovw5_dashboard, one_block_altered)
      and raises(S.pre_ovw5_dashboard, live + S.SOLAR_AFTER) and raises(S.add_ovw5_dashboard, pre + S.SOLAR_BEFORE)
      and raises(S.add_ovw5_dashboard, one_chart_unedited))

# ===========================================================================
print("")
print("[2] the three charts and their Solar series")
# ===========================================================================
d = yaml.safe_load(live)
a = yaml.safe_load(pre) if pre else None
CH = power_flow_charts(d)
CH0 = power_flow_charts(a) if a else []
check("exactly three Power Flow Today charts: the Overview, Intelligence and System views",
      [p.split("/")[2] for p, _ in CH] == ["0", "2", "6"] and [d["views"][int(p.split("/")[2])]["path"] for p, _ in CH]
      == ["ecco-overview", "ecco-intelligence", "ecco-system"], str([p for p, _ in CH]))
check("each chart's first series is Solar (the repository's generic entity) with exactly the group_by func avg, duration 5min, fill last",
      len(CH) == 3 and all(c["series"][0].get("name") == "Solar" and c["series"][0].get("entity") == "sensor.ecco_clock_dongle_ecco_pv_power"
                           and c["series"][0].get("group_by") == SOLAR_GROUP_BY for _, c in CH))
check("fill last is the string last (the card's own value), not a YAML null, boolean or number",
      all(isinstance(c["series"][0]["group_by"]["fill"], str) for _, c in CH))
check("no other series named Solar exists in the dashboard: exactly the three, one in each Power Flow Today chart",
      sorted(solar_series(d)) == sorted(f"{p}/series/0" for p, _ in CH), str(solar_series(d)))
check("before ovw5 the Solar series had no group_by of its own (it took the chart's fill 'null')",
      len(CH0) == 3 and all("group_by" not in c["series"][0] for _, c in CH0))

# ===========================================================================
print("")
print("[3] nothing else moved")
# ===========================================================================
diff = differences(a, d) if a else []
check("the parsed difference before and after ovw5 is exactly three added keys: the group_by of each chart's Solar series",
      diff == [("ADDED", f"{p}/series/0/group_by") for p, _ in CH], str(diff[:6]))
check("the other four series of each chart (House, Battery, Grid, SOC) are exactly as before",
      len(CH) == len(CH0) == 3 and all(c["series"][1:] == c0["series"][1:] and [s["name"] for s in c["series"]] == ["Solar", "House", "Battery", "Grid", "SOC"]
                                       for (_, c), (_, c0) in zip(CH, CH0)))
check("the SOC series keeps its own group_by (func last, fill last) and no other series has one: House, Battery and Grid still take the chart's fill 'null'",
      all(c["series"][4].get("group_by") == SOC_GROUP_BY and all("group_by" not in s for s in c["series"][1:4]) for _, c in CH))
check("all_series_config.group_by is untouched: func avg, duration 5min, fill 'null' (the string)",
      all(c["all_series_config"]["group_by"] == ALL_SERIES_GROUP_BY and isinstance(c["all_series_config"]["group_by"]["fill"], str) for _, c in CH))


def without_solar_group(card):
    c = copy.deepcopy(card)
    del c["series"][0]["group_by"]
    return c


check("with the group_by removed from each Solar series every Power Flow Today chart equals its chart before ovw5, key for key",
      len(CH) == len(CH0) == 3 and all(without_solar_group(c) == c0 for (_, c), (_, c0) in zip(CH, CH0)))
check("the protected layer (the Overview's flow card) is byte-identical to its state before ovw5",
      a is not None and canon(at(a, FLOW_CARD)) == canon(at(d, FLOW_CARD)))
check("the dashboard has the same views and sections as before ovw5",
      a is not None and [len(v.get("sections", [])) for v in a["views"]] == [len(v.get("sections", [])) for v in d["views"]]
      and len(a["views"]) == len(d["views"]))

# ===========================================================================
print("")
print("[4] no site value, plain text")
# ===========================================================================
new_text = "".join(a_ + b_ for a_, b_ in S.DASHBOARD_EDITS)
check("the only entity the new text names is the repository's generic Solar entity, and every device slug in the hunks is the default one; no address or URL",
      re.findall(r"\b(?:sensor|binary_sensor|input_number|script)\.[a-z0-9_]+", S.SOLAR_AFTER) == ["sensor.ecco_clock_dongle_ecco_pv_power"]
      and set(re.findall(r"[a-z0-9_]*ecco_clock_dongle[a-z0-9_]*", new_text)) == {"ecco_clock_dongle_ecco_pv_power"}
      and not re.search(r"\d+\.\d+\.\d+\.\d+|://", new_text + BLOCK))
check("the inserted text is LF only, tab free and ASCII; the dashboard has no CR",
      "\r" not in live and "\t" not in BLOCK and BLOCK.isascii() and "\r" not in BLOCK)

# ===========================================================================
print("")
print("[5] the documentation records the trade-off")
# ===========================================================================
doc = (REPO / "docs" / "dev" / "post-export-edit-layer.md").read_text(encoding="utf-8")
sec = doc.split("## What ovw5 changed", 1)[1] if "## What ovw5 changed" in doc else ""
need = ("apexcharts-card", "fill: last", "no age limit", "unavailable", "held, stale", "freshness limit", "not built",
        "template sensor", "telemetry_online", "last_telemetry_update", "ONE exact (before, after) pair", "exactly three")
check("docs/dev/post-export-edit-layer.md has a What ovw5 changed section that records the fill-last trade-off, the unavailable gap and the freshness limit that is not built",
      bool(sec) and all(t in sec for t in need), str([t for t in need if t not in sec]))
log = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
check("the CHANGELOG records ovw5 and its trade-off",
      "post-export entry `ovw5`" in log and "`fill: last` has no age limit" in log and "not built" in log)

# ===========================================================================
print("")
print("[6] the chain")
# ===========================================================================
POST = sc.POST_EXPORT_ENTRIES
ids = [e.id for e in POST]
E = next((e for e in POST if e.id == "ovw5"), None)
E4 = next((e for e in POST if e.id == "ovw4"), None)
check("ovw5 is the post-export entry right after ovw4 and declares exactly the dashboard edit (frozen reverter = this module's, one file, no chain-pinned edit)",
      E is not None and E4 is not None and ids.index("ovw5") == ids.index("ovw4") + 1 and set(E.frozen_reverts) == {S.DASHBOARD_REL}
      and E.frozen_reverts[S.DASHBOARD_REL] is S.pre_ovw5_dashboard and not E.reverts and E.added_files == S.ADDED_FILES
      and all((REPO / f).is_file() for f in E.added_files), str(ids[-4:]))
check("its frozen checkpoint is the dashboard's sha256 (LF), and the text before it is exactly ovw4's checkpoint",
      E is not None and E4 is not None and E.frozen_checkpoints == {S.DASHBOARD_REL: S.sha(live)}
      and E4.frozen_checkpoints == {S4.DASHBOARD_REL: S.sha(pre)})
check("ovw5 declares no firmware, package, manifest, registry or Modbus change: no delta, op path, include, substitution or banned token",
      E is not None and not (E.deltas or E.op_paths_changed or E.includes_added or E.subst_added or E.subst_changed or E.subst_removed
                             or E.fbh_includers or E.banned_fw_added or E.banned_files or E.tags_declared or E.tags_promoted))
try:
    older = P1.pre_ptt1_dashboard(S4.pre_ovw4_dashboard(pre))
except AssertionError as exc:
    older = ""
    print(f"        the older reverters do not apply in chain order: {exc}")
check("the chain order is what lets the earlier proofs read the dashboard: ptt1's reverter refuses it while ovw5 is applied and applies once ovw5 and ovw4 are undone",
      raises(P1.pre_ptt1_dashboard, live) and older != "" and older != pre)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All ovw5 (Power Flow Today Solar fill) checks passed.")
print("These prove the dashboard text and its exact edits; they do not run apexcharts-card and prove nothing about a real Home Assistant or a browser.")
