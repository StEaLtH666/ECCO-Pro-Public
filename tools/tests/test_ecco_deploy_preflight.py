#!/usr/bin/env python3
"""Regression suite: tools/ecco_deploy_preflight.py plans a deployment offline, read-only, and fails closed.

  [1] pure helpers: content-addressed bundle names, the destination allow-list (as tools/EccoDeploy.psm1), entity-id extraction
      (comments and dynamic JavaScript-template ids skipped), snapshot shapes
  [2] the real tree for a synthetic site: the plan passes, stages exactly the three cards that changed (names carry their sha256),
      the dashboard and bundles are rendered for the site, the preview configuration is valid JSON under the websocket limit,
      nothing in the repository changes
  [3] negative controls: a snapshot missing an entity fails; with a baseline only NEW missing ids fail; a wrong expected git sha fails;
      an unparseable dashboard, a leftover default slug and an undefined custom card are flagged; an unknown --deploy card is refused
  [4] verify-staged and verify-served: pass on matching bytes; fail on a tampered staged file, a tampered served file and a 404
      (a local http.server on 127.0.0.1 serves the staged files)

Synthetic values only. Test-only; the only network use is 127.0.0.1. I/O: reads the repo, writes only under a temp dir.
"""

from __future__ import annotations

import codecs
import contextlib
import functools
import http.server
import io
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import ecco_deploy_preflight as F  # noqa: E402
import ecco_site_render as R  # noqa: E402
import _pub0_scope as P  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not P.EXPORTED:
    print("  info  this is the private development tree: the preflight is public-tree-only; nothing to check here")
    sys.exit(0)

TMP = Path(tempfile.mkdtemp(prefix="ecco-preflight-"))


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = F.main(argv)
        except SystemExit as ex:   # argparse refusals
            code = int(ex.code or 0)
    return code, buf.getvalue()


# --------------------------------------------------------------------------------------------------------------------------
print("[1] pure helpers")
b = b"hello"
check("a bundle's deployed name carries the first 8 hex of its sha256 and keeps the card's stem",
      F.artefact_name("frontend/x/dist/ecco-foo-card.js", b) == f"ecco-foo-card.{F.sha(b)[:8]}.js")
check("the destination allow-list is the deploy tooling's: packages, ecco and www/ecco only; no traversal, no sibling prefix",
      F.destination_allowed("/config/www/ecco/a.js") and F.destination_allowed("/config/ecco/dashboards/ecco_pro.yaml")
      and not F.destination_allowed("/config/www/a.js") and not F.destination_allowed("/config/www/ecco-evil/a.js")
      and not F.destination_allowed("/config/www/ecco/../secrets.yaml") and not F.destination_allowed("/etc/passwd"))
text = ("# sensor.in_a_comment\n"
        "x: sensor.alpha_one\n"
        "y: \"states['binary_sensor.beta_two']\"\n"
        "z: `sensor.gamma${i}_total`\n"
        "w: sensor.delta_ + 'x'\n"
        "v: sun.attributes\n")
check("entity ids: comments, dynamic template ids, trailing-underscore prefixes and property reads are skipped",
      set(F.entity_ids(text)) == {"sensor.alpha_one", "binary_sensor.beta_two"}, str(F.entity_ids(text)))
snap = TMP / "snaps"
snap.mkdir()
(snap / "list.json").write_text(json.dumps([{"entity_id": "sensor.a"}, {"entity_id": "sensor.b"}]), encoding="utf-8")
(snap / "wrapped.json").write_text(json.dumps({"result": "ok", "data": [{"entity_id": "sensor.a"}]}), encoding="utf-8")
(snap / "mapping.json").write_text(json.dumps({"states": {"sensor.a": {}, "sensor.c": {}}}), encoding="utf-8")
(snap / "bom.json").write_bytes(codecs.BOM_UTF8 + json.dumps([{"entity_id": "sensor.z"}]).encode("utf-8"))
(snap / "storage.json").write_text(json.dumps({"version": 1, "key": "lovelace_resources", "data": {"items": [
    {"id": "1", "url": "/local/ecco/x.js?v=1", "type": "module"}, {"id": "2", "url": "/hacsfiles/button-card/button-card.js", "type": "module"}]}}),
    encoding="utf-8")
check("a BOM-prefixed JSON file is read, and the raw lovelace_resources storage file yields its items",
      F.load_snapshot(snap / "bom.json") == {"sensor.z"}
      and [r["url"] for r in F.load_resources(snap / "storage.json")] == ["/local/ecco/x.js?v=1", "/hacsfiles/button-card/button-card.js"])
check("snapshots: a state list, the Supervisor wrapper and a {states: mapping} are all read",
      F.load_snapshot(snap / "list.json") == {"sensor.a", "sensor.b"} and F.load_snapshot(snap / "wrapped.json") == {"sensor.a"}
      and F.load_snapshot(snap / "mapping.json") == {"sensor.a", "sensor.c"})

# --------------------------------------------------------------------------------------------------------------------------
print("")
print("[2] the real tree for a synthetic site")
SLUG = "lab_ecco_clock_dongle"
site = TMP / "site.yaml"
site.write_text(f"schema: ecco-site/1\ndevice_slug: {SLUG}\nkeep_default_slug_entities:\n  - sensor.ecco_clock_dongle_wifi_signal\nentity_map: {{}}\n",
                encoding="utf-8")
results, _ = R.render_tree(ROOT, R.load_site(site))
dash_text = results[F.DASHBOARD_REL][1].decode("utf-8")
ids = sorted(F.entity_ids(dash_text))
full_snapshot = TMP / "states.json"
full_snapshot.write_text(json.dumps([{"entity_id": e} for e in ids]), encoding="utf-8")
out = TMP / "out"
before = F.sha(b"".join((ROOT / r).read_bytes() for r in [F.DASHBOARD_REL, "VERSION.yaml"]))
code, log = run(["plan", "--site", str(site), "--snapshot", str(full_snapshot), "--out", str(out), "--allow-dirty"])
check("the plan passes for the synthetic site with a complete snapshot", code == 0, log[-600:])
plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
check("it plans exactly the three cards that changed, each with a content-addressed name, an allowed destination and a /local URL",
      [c["card"] for c in plan["cards"]] == ["energy-actions", "weather-solar", "advanced-config"]
      and all(c["name"] == f"{Path(c['source']).stem}.{c['sha256'][:8]}.js" and F.destination_allowed(c["destination"])
              and c["resource_url"] == "/local/ecco/" + c["name"] and c["resource_type"] == "module" for c in plan["cards"]))
check("the staged files are the rendered bytes (sha256 equals the plan), and the cards that need the slug are rendered for the site",
      all(F.sha((out / "stage" / c["name"]).read_bytes()) == c["sha256"] for c in plan["cards"])
      and {c["card"]: c["slug_substituted"] for c in plan["cards"]} == {"energy-actions": False, "weather-solar": True, "advanced-config": True}
      and SLUG.encode() in (out / "stage" / next(c["name"] for c in plan["cards"] if c["card"] == "weather-solar")).read_bytes())
check("the staged dashboard is the rendered dashboard: the site slug everywhere, no default slug but the kept entity",
      F.sha((out / "stage" / "ecco_pro.yaml").read_bytes()) == plan["dashboard"]["sha256_as_rendered"]
      and SLUG in dash_text and "sensor.ecco_clock_dongle_wifi_signal" in dash_text
      and not [e for e in F.entity_ids(dash_text) if e.split(".", 1)[1].startswith("ecco_clock_dongle_") and e != "sensor.ecco_clock_dongle_wifi_signal"])
cfg = json.loads((out / "ecco_pro_preview.json").read_text(encoding="utf-8"))
check("the preview configuration is the dashboard as JSON (views kept), well under the websocket limit",
      len(cfg["views"]) == len(plan["dashboard"]["views"]) and (out / "ecco_pro_preview.json").stat().st_size < F.MAX_PREVIEW_JSON)
check("the plan names the unchanged cards it does not deploy, requires no restart and lists one deploy command per file",
      set(plan["unchanged_cards_not_deployed"]) == {"energy-flow", "fallback-recovery"} and plan["restart_required"] is False
      and len(plan["deploy_commands"]) == 4 and plan["deploy_commands"][-1].endswith("-Destination " + F.DASHBOARD_DEST))
after = F.sha(b"".join((ROOT / r).read_bytes() for r in [F.DASHBOARD_REL, "VERSION.yaml"]))
check("the repository's own files are unchanged by planning", before == after)
(out2 := TMP / "out_res").mkdir()
res = TMP / "res.json"
res.write_text(json.dumps([{"url": "/local/ecco/ecco-energy-actions-card.js?v=aaa"}, {"url": "/hacsfiles/button-card/button-card.js"}]), encoding="utf-8")
code, log = run(["plan", "--site", str(site), "--snapshot", str(full_snapshot), "--resources", str(res), "--out", str(out2), "--allow-dirty"])
p2 = json.loads((out2 / "plan.json").read_text(encoding="utf-8"))
check("with a resource list the plan reports the current actions URL, the missing new cards, and warns about unregistered third-party cards",
      next(c for c in p2["cards"] if c["card"] == "energy-actions")["current_resource"] == "/local/ecco/ecco-energy-actions-card.js?v=aaa"
      and next(c for c in p2["cards"] if c["card"] == "weather-solar")["current_resource"] is None
      and "WARN  third-party card resources registered" in log, log[-400:])

# --------------------------------------------------------------------------------------------------------------------------
print("")
print("[3] negative controls")
victim = next(e for e in ids if e.startswith("sensor.") and "recovery_state" in e)
partial = TMP / "partial.json"
partial.write_text(json.dumps([{"entity_id": e} for e in ids if e != victim]), encoding="utf-8")
code, log = run(["plan", "--site", str(site), "--snapshot", str(partial), "--out", str(TMP / "o3"), "--allow-dirty"])
check("a snapshot missing a named entity fails (strict mode)", code == 1 and victim in log, log[-300:])
base_has = TMP / "base_has.yaml"
base_has.write_text(f"x: {victim}\n", encoding="utf-8")
code, log = run(["plan", "--site", str(site), "--snapshot", str(partial), "--baseline-dashboard", str(base_has), "--out", str(TMP / "o4"), "--allow-dirty"])
check("with a baseline that already used the missing id it is only a warning", code == 0 and "WARN" in log and "already used" in log, log[-300:])
base_not = TMP / "base_not.yaml"
base_not.write_text("x: sensor.unrelated_thing\n", encoding="utf-8")
code, log = run(["plan", "--site", str(site), "--snapshot", str(partial), "--baseline-dashboard", str(base_not), "--out", str(TMP / "o5"), "--allow-dirty"])
check("with a baseline that did not use it, a NEW missing id fails", code == 1 and "FAIL  every NEW entity id exists" in log, log[-300:])
code, log = run(["plan", "--site", str(site), "--expect-sha", "0" * 40, "--out", str(TMP / "o6"), "--allow-dirty"])
check("a wrong expected git sha fails", code == 1 and "FAIL  git HEAD" in log)
code, log = run(["plan", "--site", str(site), "--deploy", "energy-actions,nope", "--out", str(TMP / "o7"), "--allow-dirty"])
check("an unknown --deploy card is refused (exit 2)", code == 2)
rep = F.Report()
check("an unparseable dashboard is a FAIL row, not a crash", F.check_dashboard(rep, "views: [\n", R.Site(), None, {}) is None and rep.failed == 1)
rep = F.Report()
F.check_dashboard(rep, "views:\n  - title: A\n    path: a\n    cards: ['sensor.ecco_clock_dongle_x']\n", R.Site(device_slug=SLUG), None, {})
check("a default-slug entity left in a renamed site's dashboard is a FAIL row", any(s == "FAIL" and "no default-slug" in n for s, n, _d in rep.rows))
rep = F.Report()
F.check_dashboard(rep, "views:\n  - title: A\n    path: a\n    cards:\n      - type: custom:ecco-ghost-card\n", R.Site(), None, {"x": b"nothing"})
check("a custom:ecco-* card no bundle defines is a FAIL row", any(s == "FAIL" and "custom:ecco-*" in n for s, n, _d in rep.rows))
rep = F.Report()
F.check_dashboard(rep, "views:\n  - title: A\n    path: a\n  - title: B\n    path: a\n", R.Site(), None, {})
check("duplicate view paths are a FAIL row", any(s == "FAIL" and "unique paths" in n for s, n, _d in rep.rows))

# --------------------------------------------------------------------------------------------------------------------------
print("")
print("[4] verify-staged and verify-served")
code, log = run(["verify-staged", "--plan", str(out / "plan.json")])
check("verify-staged passes on the staged files", code == 0, log[-300:])
card = plan["cards"][1]
staged = out / "stage" / card["name"]
good = staged.read_bytes()

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):   # keep the test output clean
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(out / "stage")))
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}"
# the server root is stage/, the plan's resource_url is /local/ecco/<name>: serve it under that prefix
(out / "stage" / "local" / "ecco").mkdir(parents=True)
for c in plan["cards"]:
    (out / "stage" / "local" / "ecco" / c["name"]).write_bytes((out / "stage" / c["name"]).read_bytes())
code, log = run(["verify-served", "--plan", str(out / "plan.json"), "--base-url", url, "--timeout", "5"])
check("verify-served passes when the server hands out the planned bytes", code == 0 and log.count("PASS") == 3, log[-400:])
(out / "stage" / "local" / "ecco" / card["name"]).write_bytes(good + b"\n//x")
code, log = run(["verify-served", "--plan", str(out / "plan.json"), "--base-url", url, "--timeout", "5"])
check("verify-served fails when a served bundle differs by a byte", code == 1 and "DIFFERS" in log, log[-400:])
(out / "stage" / "local" / "ecco" / card["name"]).unlink()
code, log = run(["verify-served", "--plan", str(out / "plan.json"), "--base-url", url, "--timeout", "5"])
check("verify-served fails on a 404", code == 1 and "404" in log, log[-400:])
srv.shutdown()
code, log = run(["verify-served", "--plan", str(out / "plan.json"), "--base-url", "http://127.0.0.1:9", "--timeout", "1"])
check("verify-served fails when the server is unreachable", code == 1)
staged.write_bytes(good + b" ")
code, log = run(["verify-staged", "--plan", str(out / "plan.json")])
check("verify-staged fails on a tampered staged file", code == 1 and "FAIL" in log)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All deploy-preflight checks passed.")
