#!/usr/bin/env python3
"""Offline, read-only deployment preflight for the ECCO Lovelace dashboard and its card bundles.

It PLANS; it never deploys. It contacts no Home Assistant instance (the one optional network use is `verify-served`, which only GETs
the bundle files a browser would fetch), runs no ssh/scp/Home Assistant CLI command, never restarts anything, never edits Lovelace
resources or dashboards and never touches an inverter. Its only subprocesses are `git rev-parse` and `git status`. It writes only under
--out. The deploy commands it prints are text in plan.json for a human to run.

    python tools/ecco_deploy_preflight.py plan --site ecco_site.local.yaml [--snapshot states.json] [--baseline-dashboard live.yaml]
                                               [--resources resources.json] [--expect-sha <git sha>] [--out dist/deploy]
    python tools/ecco_deploy_preflight.py verify-staged --plan dist/deploy/plan.json
    python tools/ecco_deploy_preflight.py verify-served --plan dist/deploy/plan.json --base-url http://homeassistant.local:8123

`plan` renders the tree for the site in memory (the same exact rules as tools/ecco_site_render.py), then:
  - checks the git revision and, unless --allow-dirty, a clean working tree (dist/ is ignored);
  - parses the rendered dashboard, checks the views, that its header carries the VERSION.yaml dashboard version, that no default device
    slug is left when the site renamed it, and that every `custom:ecco-*` card it uses is defined by a bundle of this tree;
  - lists the third-party card types the dashboard needs and, with --resources (a plain list, a websocket result or the raw
    `lovelace_resources` storage file; BOM tolerated), whether each is registered, and for each card to deploy whether the resource
    change is an ADD or a REPLACE. **A resource is shared by every dashboard**: replacing the URL of a card the existing dashboard
    already uses changes that dashboard immediately, before any cut-over; the plan flags it (`affects_live_dashboard_before_cutover`)
    and records the URL to switch back to (`rollback_resource_url`);
  - with --snapshot (a Home Assistant `/api/states` dump; BOM tolerated) checks that the snapshot is readable, non-empty, well formed and
    fresh (--max-snapshot-age-hours from --now), then that every entity id the dashboard names exists; with --baseline-dashboard (for
    example a copy of the live dashboard) only ids that are NEW compared with it are failures. Named entities that exist but are
    unavailable/unknown are warnings;
  - checks that every card bundle it must deploy is present in the tree;
  - writes, under --out, the staged files (cards under content-addressed names `<card>.<sha8>.js`, so a deployed file is never
    overwritten and rollback is a resource-URL change), a storage-mode preview-dashboard configuration (YAML and JSON) and plan.json.
`--out` must be outside the repository or under dist/ (git-ignored), and must be empty or a previous preflight output.
plan.json and the staged files contain the site's entity ids and device slug: keep them local, never commit or publish them.
`verify-staged` re-hashes the staged files against plan.json. `verify-served` fetches each planned bundle over HTTP (GET only) and
compares its sha256. Both are refused cleanly (exit 2) on an unreadable or malformed plan.

Exit 0 only when no check FAILED; 2 when an input is refused. Standard library + PyYAML.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import ecco_site_render as R  # noqa: E402

DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_DEST = "/config/ecco/dashboards/ecco_pro.yaml"
CARDS = {   # card directory -> (source file, custom element tag)
    "energy-actions": ("frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js", "ecco-energy-actions-card"),
    "weather-solar": ("frontend/ecco-weather-solar-card/dist/ecco-weather-solar-card.js", "ecco-weather-solar-card"),
    "advanced-config": ("frontend/ecco-advanced-config-card/dist/ecco-advanced-config-card.js", "ecco-advanced-config-card"),
    "energy-flow": ("frontend/ecco-energy-flow-card/dist/ecco-energy-flow-card.js", "ecco-energy-flow-card"),
    "fallback-recovery": ("frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js", "ecco-fallback-recovery-card"),
}
DEFAULT_DEPLOY = ("energy-actions", "weather-solar", "advanced-config")
ALLOWED_DEST = ("/config/packages/", "/config/ecco/", "/config/www/ecco/")   # tools/EccoDeploy.psm1 Test-EccoDeploymentDestination
THIRD_PARTY = {"button-card": "button-card", "apexcharts-card": "apexcharts-card", "flex-horseshoe-card": "flex-horseshoe-card",
               "sunsynk-power-flow-card": "sunsynk-power-flow-card"}
DOMAINS = ("sensor|binary_sensor|switch|number|button|input_boolean|input_number|input_text|input_datetime|input_select|script|"
           "weather|sun|event|select|text|automation|update")
ENTITY_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:" + DOMAINS + r")\.[a-z0-9][a-z0-9_]*)(?![a-z0-9_]|\$\{)")   # maximal match only; a dynamic `${...}` tail is skipped
NOT_ENTITIES = {"sun.attributes", "sun.sun.attributes"}
MAX_PREVIEW_JSON = 3 * 1024 * 1024   # Home Assistant's websocket message limit is 4 MiB; keep headroom
MARKER = ".ecco-deploy-preflight"
LOCAL_ONLY_NOTE = ("LOCAL ONLY: contains the site's device slug and entity ids (and the staged dashboard); never commit, upload or "
                   "paste into an issue or a pull request")


class InputError(Exception):
    """An input is unreadable or malformed: refuse (exit 2) instead of crashing."""


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))

    @property
    def failed(self) -> int:
        return sum(1 for s, _n, _d in self.rows if s == "FAIL")

    def print(self) -> None:
        for s, n, d in self.rows:
            print(f"  {s:4s}  {n}" + (f" - {d}" if d else ""))


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def artefact_name(source_rel: str, data: bytes) -> str:
    """`<stem>.<sha8>.js`: the file name carries the content, so a deployed bundle is never overwritten."""
    stem = Path(source_rel).stem
    return f"{stem}.{sha(data)[:8]}.js"


def destination_allowed(dest: str) -> bool:
    return dest.startswith(ALLOWED_DEST) and ".." not in dest.split("/")


def read_json(path: Path, what: str):
    try:
        raw = path.read_text(encoding="utf-8-sig")   # tolerates a BOM (PowerShell redirection)
    except (OSError, UnicodeDecodeError) as ex:
        raise InputError(f"{what} {path.name}: cannot be read ({type(ex).__name__})") from None
    try:
        return json.loads(raw)
    except ValueError as ex:
        raise InputError(f"{what} {path.name}: not valid JSON ({str(ex)[:80]})") from None


def entity_ids(text: str) -> dict[str, int]:
    """Entity ids named in a dashboard (comment lines skipped; ids that continue as a JavaScript template are dynamic and skipped)."""
    out: dict[str, int] = {}
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if line.lstrip().startswith("#"):
            continue
        for m in ENTITY_RE.finditer(line):
            e = m.group(1)
            if e in NOT_ENTITIES or e.endswith("_"):
                continue
            out.setdefault(e, n)
    return out


@dataclass
class Snapshot:
    ids: set = field(default_factory=set)
    state: dict = field(default_factory=dict)     # entity id -> state string (when the dump carries it)
    newest: datetime | None = None                 # newest last_updated / last_changed in the dump (its capture time, in effect)
    malformed: int = 0                             # items without a usable entity_id


def _ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load_snapshot_full(path: Path) -> Snapshot:
    data = read_json(path, "snapshot")
    if isinstance(data, dict) and "data" in data and "result" in data:   # Supervisor proxy wrapper
        data = data["data"]
    if isinstance(data, dict) and "states" in data:
        data = data["states"]
    snap = Snapshot()
    if isinstance(data, dict):
        items = [(k, v) for k, v in data.items()]
    elif isinstance(data, list):
        items = [((s.get("entity_id") if isinstance(s, dict) else None), s) for s in data]
    else:
        raise InputError(f"snapshot {path.name}: expected a state list or a mapping, got {type(data).__name__}")
    for eid, obj in items:
        if not isinstance(eid, str) or not eid:
            snap.malformed += 1
            continue
        snap.ids.add(eid)
        if isinstance(obj, dict):
            if isinstance(obj.get("state"), str):
                snap.state[eid] = obj["state"]
            for key in ("last_updated", "last_changed"):
                t = _ts(obj.get(key))
                if t and (snap.newest is None or t > snap.newest):
                    snap.newest = t
    return snap


def load_snapshot(path: Path) -> set[str]:
    return load_snapshot_full(path).ids


def load_resources(path: Path) -> list[dict]:
    """The Lovelace resource list: a plain list of {url}, {resources: [...]}, the websocket result, or the raw
    `/config/.storage/lovelace_resources` file ({"data": {"items": [...]}})."""
    data = read_json(path, "resource list")
    if isinstance(data, dict):
        inner = data.get("data")
        data = data.get("resources") or (inner.get("items") if isinstance(inner, dict) else inner) or data.get("items") or []
    if not isinstance(data, list):
        raise InputError(f"resource list {path.name}: expected a list of resources")
    return [r for r in data if isinstance(r, dict)]


def check_dashboard(rep: Report, text: str, site: R.Site, version: str | None, bundles: dict[str, bytes]) -> dict | None:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as ex:
        rep.add("FAIL", "dashboard parses as YAML", str(ex)[:200])
        return None
    views = doc.get("views") if isinstance(doc, dict) else None
    if not isinstance(views, list) or not views:
        rep.add("FAIL", "dashboard has views", "no views list")
        return None
    titles = [v.get("title") for v in views]
    paths = [v.get("path") for v in views]
    rep.add("PASS" if len(set(paths)) == len(paths) and all(titles) else "FAIL", f"dashboard parses: {len(views)} views, unique paths",
            ", ".join(map(str, titles)))
    if version:
        rep.add("PASS" if f"v{version}" in text[:6000] else "FAIL", f"dashboard header carries the VERSION.yaml dashboard version v{version}")
    if site.device_slug != R.DEFAULT_SLUG:
        keep = set(site.keep_default_slug_entities)
        left = sorted({m.group(0) for m in re.finditer(r"\b(?:" + DOMAINS + r")\." + R.DEFAULT_SLUG + r"_[a-z0-9_]+", text)} - keep)
        rep.add("PASS" if not left else "FAIL", f"no default-slug entity left for device slug {site.device_slug!r}", ", ".join(left[:5]))
    used = sorted({m.group(1) for m in re.finditer(r"type:\s*custom:([a-z0-9-]+)", text)})
    own = [t for t in used if t.startswith("ecco-")]
    undefined = [t for t in own if not any(t.encode() in b for b in bundles.values())]
    rep.add("PASS" if not undefined else "FAIL", f"every custom:ecco-* card the dashboard uses is defined by a bundle of this tree ({len(own)})",
            ", ".join(undefined) or ", ".join(own))
    return {"views": titles, "custom_types": used}


def check_snapshot(rep: Report, snap: Snapshot, now: datetime, max_age_h: float) -> bool:
    """Is the snapshot usable at all? Returns False when the entity cross-check must be skipped."""
    if not snap.ids:
        rep.add("FAIL", "snapshot contains entities", "0 entity ids: an empty or wrong file")
        return False
    rep.add("PASS", f"snapshot is readable: {len(snap.ids)} entities")
    rep.add("PASS" if not snap.malformed else "FAIL", "every snapshot item has an entity_id", f"{snap.malformed} without" if snap.malformed else "")
    if snap.newest is None:
        rep.add("WARN", "snapshot age is unknown (no last_updated / last_changed in the file)", "capture a fresh /api/states dump")
    else:
        age = now - snap.newest
        limit = timedelta(hours=max_age_h)
        rep.add("PASS" if age <= limit else "FAIL", f"snapshot is fresh: newest state change {age.total_seconds() / 3600:.1f} h before {now:%Y-%m-%d %H:%M}Z",
                f"limit {max_age_h:g} h" if age > limit else "")
    return True


def check_entities(rep: Report, text: str, snap: Snapshot, baseline: str | None) -> None:
    ids = entity_ids(text)
    missing = sorted(e for e in ids if e not in snap.ids)
    if baseline is None:
        rep.add("PASS" if not missing else "FAIL", f"every entity id the dashboard names exists in the snapshot ({len(ids)} ids)",
                ", ".join(missing[:8]))
    else:
        old = set(entity_ids(baseline))
        new_missing = [e for e in missing if e not in old]
        old_missing = [e for e in missing if e in old]
        new_ids = [e for e in ids if e not in old]
        rep.add("PASS" if not new_missing else "FAIL", f"every NEW entity id exists in the snapshot ({len(new_ids)} new of {len(ids)} ids)",
                ", ".join(new_missing[:8]))
        if old_missing:
            rep.add("WARN", f"{len(old_missing)} entity ids the baseline dashboard already used are absent from the snapshot",
                    ", ".join(old_missing[:6]))
    down = sorted(e for e in ids if snap.state.get(e) in ("unavailable", "unknown"))
    if down:
        rep.add("WARN", f"{len(down)} entities the dashboard names exist but are unavailable/unknown in the snapshot", ", ".join(down[:6]))


def check_resources(rep: Report, used_types: list[str], resources: list[dict] | None, plan_cards: list[dict], baseline: str | None) -> None:
    third = sorted(t for t in used_types if not t.startswith("ecco-"))
    need = {t: THIRD_PARTY.get(t, t) for t in third}
    urls = [str(r.get("url", "")) for r in resources] if resources is not None else None
    if urls is None:
        rep.add("INFO", "third-party card types the dashboard uses (pass --resources to check registration)", ", ".join(third))
    else:
        gone = [t for t, frag in need.items() if not any(frag in u for u in urls)]
        rep.add("PASS" if not gone else "WARN", "third-party card resources registered (substring match on the resource URL)",
                ", ".join(gone) or ", ".join(third))
    for c in plan_cards:
        stem = Path(c["source"]).stem
        cur = next((u for u in urls if f"/{stem}" in u), None) if urls is not None else None
        c["current_resource"] = cur
        c["resource_action"] = ("REPLACE" if cur else "ADD") if urls is not None else "ADD or REPLACE (pass --resources)"
        used_by_baseline = None if baseline is None else (f"custom:{c['tag']}" in baseline)
        affects = used_by_baseline if used_by_baseline is not None else (True if cur else None)
        c["affects_live_dashboard_before_cutover"] = affects
        c["rollback_resource_url"] = cur if affects else None
        if affects:
            rep.add("WARN", f"RESOURCE SWITCH for {c['tag']} changes the card on the EXISTING dashboard before the cut-over (resources are shared)",
                    f"gate it separately; rollback = set the resource back to {cur or 'its current URL'}")
        elif urls is not None:
            rep.add("INFO", f"resource for {c['tag']}: {c['resource_action']}", f"current {cur}" if cur else "not registered: ADD; the existing dashboard does not use it")


def safe_out(out: Path, root: Path) -> Path:
    """Planning output may not land inside the repository outside dist/ (git-ignored), and may not be dumped into a foreign directory."""
    out, root = out.resolve(), root.resolve()
    if (out == root or root in out.parents) and not (out == root / "dist" or (root / "dist") in out.parents):
        raise InputError("--out is inside the repository but not under dist/ (git-ignored): refusing (the output holds site values)")
    if out.exists():
        if not out.is_dir() or out.is_symlink():
            raise InputError("--out exists and is not a plain directory")
        if any(out.iterdir()) and not (out / MARKER).is_file():
            raise InputError(f"--out is not empty and is not a previous preflight output (no {MARKER}): refusing to write into it")
    return out


def plan(args: argparse.Namespace) -> int:
    rep = Report()
    root = Path(args.root)
    out = safe_out(Path(args.out), root)
    now = _ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise InputError("--now must be an ISO timestamp")
    try:
        site = R.load_site(Path(args.site))
        results, _reports = R.render_tree(root, site)
    except R.RenderError as ex:
        print(f"refused: {ex}", file=sys.stderr)
        return 2
    if DASHBOARD_REL not in results:
        raise InputError(f"the tree has no {DASHBOARD_REL}")
    git_ok = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=str(root), capture_output=True, text=True).returncode == 0
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True).stdout.strip() if git_ok else ""
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(root), capture_output=True, text=True).stdout.strip() if git_ok else ""
    if not git_ok:
        rep.add("FAIL" if args.expect_sha else "WARN", "the tree is not a git work tree: its revision is unknown")
    else:
        rep.add("PASS" if (not args.expect_sha or head == args.expect_sha) else "FAIL", f"git HEAD {head[:12]}",
                f"expected {args.expect_sha[:12]}" if args.expect_sha and head != args.expect_sha else "")
        rep.add("PASS" if (not dirty or args.allow_dirty) else "FAIL", "working tree clean (dist/ is git-ignored)", f"{len(dirty.splitlines())} changed" if dirty else "")
    version = None
    vf = root / "VERSION.yaml"
    if vf.is_file():
        version = str(((yaml.safe_load(vf.read_text(encoding="utf-8")) or {}).get("current") or {}).get("dashboard", {}).get("version") or "") or None
    rep.add("INFO", f"site device slug {site.device_slug!r}; render set {len(results)} files; dashboard version {version}")

    dash_raw, dash = results[DASHBOARD_REL]
    dash_text = dash.decode("utf-8")
    bundles = {k: results[src][1] for k, (src, _t) in CARDS.items() if src in results}
    info = check_dashboard(rep, dash_text, site, version, bundles)

    deploy = [d.strip() for d in args.deploy.split(",") if d.strip()]
    bad = [d for d in deploy if d not in CARDS]
    if bad:
        print(f"refused: unknown card(s) {bad}; known {sorted(CARDS)}", file=sys.stderr)
        return 2
    plan_cards: list[dict] = []
    for key in deploy:
        src, tag = CARDS[key]
        if src not in results:
            rep.add("FAIL", f"bundle {key}: {src} is missing from the render set", "not built / not in this tree: nothing to deploy for this card")
            continue
        committed, rendered = results[src]
        name = artefact_name(src, rendered)
        dest = "/config/www/ecco/" + name
        problems = []
        if tag.encode() not in rendered:
            problems.append("element tag not found")
        if b"\r" in rendered:
            problems.append("contains CR")
        if not rendered.strip():
            problems.append("empty")
        rep.add("PASS" if not problems and destination_allowed(dest) else "FAIL", f"bundle {key}: {len(rendered)} B sha256 {sha(rendered)[:12]} -> {name}",
                "; ".join(problems) + (" (slug substituted from the committed file)" if rendered != committed else " (identical to the committed file)"))
        plan_cards.append({"card": key, "tag": tag, "source": src, "bytes": len(rendered), "sha256": sha(rendered),
                           "committed_sha256": sha(committed), "slug_substituted": rendered != committed, "name": name,
                           "destination": dest, "resource_url": "/local/ecco/" + name, "resource_type": "module"})
    unchanged = {k: {"source": s, "sha256": sha(results[s][1]), "bytes": len(results[s][1])} for k, (s, _t) in CARDS.items()
                 if k not in deploy and s in results}
    baseline = Path(args.baseline_dashboard).read_bytes().decode("utf-8-sig") if args.baseline_dashboard else None
    if args.snapshot:
        snap = load_snapshot_full(Path(args.snapshot))
        if check_snapshot(rep, snap, now, args.max_snapshot_age_hours):
            check_entities(rep, dash_text, snap, baseline)
    else:
        rep.add("INFO", "entity cross-check skipped (pass --snapshot with a /api/states dump)")
    resources = load_resources(Path(args.resources)) if args.resources else None
    check_resources(rep, (info or {}).get("custom_types", []), resources, plan_cards, baseline)

    blob = b""
    if info is not None:
        cfg = yaml.safe_load(dash_text)
        blob = json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        rep.add("PASS" if len(blob) <= MAX_PREVIEW_JSON else "FAIL", f"preview (storage-mode) dashboard configuration is {len(blob)} B as JSON",
                f"limit {MAX_PREVIEW_JSON} B")
    stage = out / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Written by tools/ecco_deploy_preflight.py. Contains site values: do not commit or publish.\n", encoding="utf-8")
    for c in plan_cards:
        (stage / c["name"]).write_bytes(results[c["source"]][1])
    (out / "ecco_pro_preview.yaml").write_bytes(dash)
    if info is not None:
        (out / "ecco_pro_preview.json").write_bytes(blob)
    (stage / "ecco_pro.yaml").write_bytes(dash)

    def rel(p: Path) -> str:
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(p)
    data = {
        "schema": "ecco-deploy-plan/1", "local_only": LOCAL_ONLY_NOTE, "git_head": head, "site_device_slug": site.device_slug,
        "dashboard_version": version,
        "dashboard": {"source": DASHBOARD_REL, "bytes": len(dash), "sha256_as_rendered": sha(dash), "sha256_lf": sha(lf(dash)),
                      "sha256_crlf": sha(lf(dash).replace(b"\n", b"\r\n")), "line_ending_as_rendered": "CRLF" if b"\r\n" in dash else "LF",
                      "destination": DASHBOARD_DEST, "staged": rel(stage / "ecco_pro.yaml"), "views": (info or {}).get("views"),
                      "preview_yaml": rel(out / "ecco_pro_preview.yaml")},
        "cards": plan_cards, "unchanged_cards_not_deployed": unchanged,
        "deploy_commands": [f".\\tools\\deploy-ha.ps1 -Source {rel(stage / c['name'])} -Destination {c['destination']}" for c in plan_cards]
                           + [f".\\tools\\deploy-ha.ps1 -Source {rel(stage / 'ecco_pro.yaml')} -Destination {DASHBOARD_DEST}"],
        "note_commands": "text only: this tool never runs them; resources are registered by hand, and a resource URL change is shared by every dashboard",
        "restart_required": False,
        "checks": [{"status": s, "name": n, "detail": d} for s, n, d in rep.rows],
    }
    (out / "plan.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    rep.print()
    print(f"\nplan written to {out / 'plan.json'} ({LOCAL_ONLY_NOTE}); {rep.failed} check(s) FAILED")
    return 1 if rep.failed else 0


def verify_staged(args: argparse.Namespace) -> int:
    rep = Report()
    p = Path(args.plan)
    data = read_json(p, "plan")
    base = p.parent
    try:
        for c in data["cards"]:
            f = base / "stage" / c["name"]
            ok = f.is_file() and sha(f.read_bytes()) == c["sha256"] and c["name"] == artefact_name(c["source"], f.read_bytes())
            rep.add("PASS" if ok else "FAIL", f"staged {c['name']} matches the plan (sha256 and content-addressed name)")
        f = base / "stage" / "ecco_pro.yaml"
        ok = f.is_file() and sha(f.read_bytes()) == data["dashboard"]["sha256_as_rendered"]
        rep.add("PASS" if ok else "FAIL", "staged ecco_pro.yaml matches the plan")
    except (KeyError, TypeError) as ex:
        raise InputError(f"plan {p.name}: not a preflight plan (missing {ex})") from None
    rep.print()
    return 1 if rep.failed else 0


def verify_served(args: argparse.Namespace) -> int:
    rep = Report()
    data = read_json(Path(args.plan), "plan")
    base = args.base_url.rstrip("/")
    try:
        cards = list(data["cards"])
    except (KeyError, TypeError) as ex:
        raise InputError(f"plan {Path(args.plan).name}: not a preflight plan (missing {ex})") from None
    for c in cards:
        url = base + c["resource_url"]
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=args.timeout) as r:   # nosec: read-only GET
                body = r.read()
                cache = r.headers.get("Cache-Control", "(none)")
                ctype = r.headers.get("Content-Type", "?")
        except (urllib.error.URLError, OSError) as ex:
            rep.add("FAIL", f"GET {c['resource_url']}", str(ex)[:160])
            continue
        ok = sha(body) == c["sha256"]
        rep.add("PASS" if ok else "FAIL", f"served {c['name']}: sha256 {'matches' if ok else 'DIFFERS'}", f"{ctype}; Cache-Control: {cache}")
    rep.print()
    return 1 if rep.failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="render for a site, run the checks, stage files and write plan.json (deploys nothing)")
    p.add_argument("--site", required=True)
    p.add_argument("--root", default=str(REPO))
    p.add_argument("--out", default=str(REPO / "dist" / "deploy"))
    p.add_argument("--snapshot")
    p.add_argument("--max-snapshot-age-hours", type=float, default=12.0)
    p.add_argument("--now", help="ISO timestamp used for the snapshot age (default: the current time)")
    p.add_argument("--baseline-dashboard")
    p.add_argument("--resources")
    p.add_argument("--deploy", default=",".join(DEFAULT_DEPLOY), help="card directories to deploy (default: %(default)s)")
    p.add_argument("--expect-sha")
    p.add_argument("--allow-dirty", action="store_true")
    q = sub.add_parser("verify-staged", help="re-hash the staged files against plan.json")
    q.add_argument("--plan", required=True)
    s = sub.add_parser("verify-served", help="GET each planned bundle from Home Assistant and compare its sha256")
    s.add_argument("--plan", required=True)
    s.add_argument("--base-url", required=True)
    s.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args(argv)
    try:
        return {"plan": plan, "verify-staged": verify_staged, "verify-served": verify_served}[a.cmd](a)
    except InputError as ex:
        print(f"refused: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
