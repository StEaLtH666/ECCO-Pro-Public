#!/usr/bin/env python3
"""The generator of the Mode Shell dashboard configuration (tools/geek_mode_dashboard_config.py) and the plan file it writes for the
existing resource read-back gate (tools/ecco_deploy_preflight.py verify-resource / verify-served).

  [1] the generation: deterministic (two runs, byte for byte), JSON that a YAML loader reads the same way, ASCII, LF, one final newline,
      under 400 KB, no !include and no file reference, no URL, address, e-mail, token or private path
  [2] the cards: the shell first and the text fallback second, exactly the cards of the repository's example (the `always` and `production`
      lists and the fallback EQUAL to the example's, key for key); no card type the example does not use; no service-call key; the only write
      action anywhere is the existing pause tile's toggle, and it is in `production`
  [3] the catalogue is inline and equals the committed catalogue after parsing (the same object Home Assistant's !include would hand the card)
  [4] the command line: --check (alone and against a file), --out (outside the repository or under dist/ only; never a symlink; no silent
      overwrite), --verify-storage (a raw storage file or a bare configuration; a changed card or catalogue is a difference), exit codes
  [5] the resource plan: written for the LF card file only (CRLF refused), content-addressed, and READ BY THE REAL preflight verify-resource: a
      correct switch is VERIFIED, and eleven wrong ones (not switched, wrong URL, wrong type, two resources, another resource changed, added or
      removed, a stale read-back, bytes served that differ, a malformed list) are refused or FAIL
  [6] mutants (24): each is caught, by the rule that exists for it where there is one

Test-only, no network (the one GET of verify-resource is replaced by a function), no Node. Scratch files live in the system temp directory and
are removed.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ecco_deploy_preflight as P  # noqa: E402
import geek_mode_dashboard_config as G  # noqa: E402
import yaml  # noqa: E402

FAILURES: list[str] = []
PY = [sys.executable, "-I", "-B", "-X", "utf8"]
TOOL = str(ROOT / "tools" / "geek_mode_dashboard_config.py")


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _raises(exc, fn) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def run_tool(*args: str) -> tuple[int, str]:
    r = subprocess.run([*PY, TOOL, *args], cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr)


EXAMPLE_TEXT, CATALOGUE_BYTES = G.read_inputs(ROOT)
TEXT = G.generate(ROOT)
CFG = json.loads(TEXT)


class _Keep(yaml.SafeLoader):
    pass


_Keep.add_constructor("!include", lambda loader, node: "!include " + loader.construct_scalar(node))
EXAMPLE = yaml.load(EXAMPLE_TEXT, Loader=_Keep)  # noqa: S506 - SafeLoader subclass

# ===========================================================================
print("[1] the generation")
# ===========================================================================
check("two generations are byte-identical", G.generate(ROOT) == TEXT and G.render(G.build_config(EXAMPLE_TEXT, CATALOGUE_BYTES)) == TEXT)
check("the text is ASCII with LF only and exactly one final newline, under 400 KB",
      TEXT.isascii() and "\r" not in TEXT and TEXT.endswith("}\n") and not TEXT.endswith("\n\n") and len(TEXT.encode()) < 400_000, f"{len(TEXT)} bytes")
check("it is strict JSON (no duplicate key, no NaN) and a YAML loader reads it exactly as JSON does (the raw editor takes YAML)",
      G.parse_json(TEXT) == CFG and yaml.safe_load(TEXT) == CFG)
check("no !include tag and no card setting names a catalogue file (the only string with 'catalogue' is the object's own text)",
      "!include" not in TEXT and not [p for p, v in G._walk(CFG) if isinstance(v, str) and v.endswith(".json")])
hits = {n: m.group(0)[:30] for n, rx in G.PRIVACY.items() if (m := rx.search(TEXT))}
check("no URL, address, MAC, e-mail, token, credential pair, blob, private path or coordinate in the text", not hits, str(hits))
check("the consistency check finds nothing wrong with the real generation", G.problems(TEXT, EXAMPLE_TEXT, CATALOGUE_BYTES) == [], str(G.problems(TEXT, EXAMPLE_TEXT, CATALOGUE_BYTES)))

# ===========================================================================
print("")
print("[2] the cards are the example's cards")
# ===========================================================================
check("the top level is exactly title and views, and the title is the example's",
      set(CFG) == {"title", "views"} and CFG["title"] == EXAMPLE["title"])
check("one view, with the example's title, path and icon", len(CFG["views"]) == 1 and {k: v for k, v in CFG["views"][0].items() if k != "cards"}
      == {k: v for k, v in EXAMPLE["views"][0].items() if k != "cards"})
cards, ex_cards = CFG["views"][0]["cards"], EXAMPLE["views"][0]["cards"]
shell, ex_shell = cards[0], ex_cards[0]
check("two cards: the shell, then the text fallback (outside the shell, as in the example)", len(cards) == 2 and shell["type"] == "custom:ecco-mode-shell"
      and cards[1] == ex_cards[1] and cards[1]["type"] == "markdown")
check("the shell's other settings equal the example's (view id, title, always, production)",
      {k: v for k, v in shell.items() if k != "catalogue"} == {k: v for k, v in ex_shell.items() if k != "catalogue"}
      and list(shell) == list(ex_shell))
check("the always list holds exactly the example's two cards and the production list its one card",
      shell["always"] == ex_shell["always"] and len(shell["always"]) == 2 and shell["production"] == ex_shell["production"] and len(shell["production"]) == 1)
types = {c["type"] for r in ("always", "production") for c in shell[r]} | {cards[1]["type"]}
check("every card type is one the example already uses (no new type)", types == {c["type"] for r in ("always", "production") for c in ex_shell[r]} | {ex_cards[1]["type"]}
      and types <= G.ALWAYS_ALLOWED_TYPES, str(types))
actions = [(p, v) for p, v in G._walk({k: v for k, v in shell.items() if k != "catalogue"}) if p.endswith("/action")]
check("the only write action is the pause tile's toggle (twice: tap and icon tap), in production; the always list has none but more-info",
      sorted(p for p, v in actions if v == "toggle") == ["/production/0/icon_tap_action/action", "/production/0/tap_action/action"]
      and all(v in G.SAFE_ACTIONS for p, v in actions if p.startswith("/always")), str(actions))
check("no service-call key anywhere outside the catalogue", not [p for p, _v in G._walk({k: v for k, v in shell.items() if k != "catalogue"})
                                                                if p.rsplit("/", 1)[-1] in G.CALL_KEYS])

# ===========================================================================
print("")
print("[3] the inline catalogue")
# ===========================================================================
committed = json.loads(CATALOGUE_BYTES)
check("the card's catalogue is the committed catalogue object, deep-equal, key order kept", shell["catalogue"] == committed
      and json.dumps(shell["catalogue"]) == json.dumps(committed))
check("canonical bytes equal (sorted keys, compact): the inline catalogue is the committed one byte for byte after parsing",
      json.dumps(shell["catalogue"], sort_keys=True, separators=(",", ":")).encode() == json.dumps(committed, sort_keys=True, separators=(",", ":")).encode())
check("it is the Intelligence catalogue of the shell's schema: 17 sources, 344 attribute rows, 19 alerts",
      shell["catalogue"]["schema"] == "ecco-geek-catalogue/1" and len(shell["catalogue"]["sources"]) == 17
      and sum(len(s.get("attributes", [])) for s in shell["catalogue"]["sources"]) == 344 and len(shell["catalogue"]["alerts"]) == 19)
check("the catalogue's view id is the shell's view id", shell["catalogue"]["view_id"] == shell["view_id"])

# ===========================================================================
print("")
print("[4] the command line")
# ===========================================================================
with tempfile.TemporaryDirectory(prefix="ecco-u1-cfg-") as tmp:
    tmpd = Path(tmp)
    rc, out = run_tool("--check")
    check("--check passes on the repository", rc == 0 and "OK:" in out and G.sha256(TEXT) in out, out[-300:])
    f = tmpd / "dash.json"
    rc, out = run_tool("--out", str(f))
    check("--out writes the text outside the repository (exit 0, size and sha256 printed)", rc == 0 and f.read_bytes() == TEXT.encode() and G.sha256(TEXT) in out, out[-300:])
    rc, out = run_tool("--check", str(f))
    check("--check FILE passes on the written file", rc == 0, out[-300:])
    f.write_bytes(TEXT.encode().replace(b"ECCO Intelligence", b"ECCO Intelligenxe", 1))
    rc, out = run_tool("--check", str(f))
    check("--check FILE fails (exit 1) on a file that differs by one letter", rc == 1 and "differs from a fresh generation" in out, out[-300:])
    rc, out = run_tool("--check", str(tmpd / "missing.json"))
    check("--check FILE fails on a missing file", rc == 1 and "no such file" in out, out[-300:])
    rc, out = run_tool("--out", str(f))
    check("--out refuses to replace a different file without --overwrite (exit 2), and replaces it with --overwrite", rc == 2 and f.read_bytes() != TEXT.encode()
          and run_tool("--out", str(f), "--overwrite")[0] == 0 and f.read_bytes() == TEXT.encode())
    check("--out of an identical file is quiet and fine (idempotent)", run_tool("--out", str(f))[0] == 0)
    rc, out = run_tool("--out", str(ROOT / "docs" / "x.json"))
    check("--out refuses a path inside the repository outside dist/ (exit 2, nothing written)", rc == 2 and not (ROOT / "docs" / "x.json").exists(), out[-200:])
    rc, out = run_tool("--out", str(tmpd / "no-such-folder" / "x.json"))
    check("--out refuses a folder that does not exist", rc == 2)
    # a scratch repository: the same relative inputs, so the dist/ rule can be tried without touching this tree
    fake = tmpd / "repo"
    for rel in (G.EXAMPLE_REL, G.CATALOGUE_REL, G.CARD_REL):
        (fake / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, fake / rel)
    (fake / "dist").mkdir()
    rc, _o = run_tool("--repo-root", str(fake), "--out", str(fake / "dist" / "dash.json"))
    check("--out under the repository's dist/ is allowed", rc == 0 and (fake / "dist" / "dash.json").read_bytes() == TEXT.encode())
    rc, _o = run_tool("--repo-root", str(fake), "--out", str(fake / "frontend" / "dash.json"))
    check("--out in any other folder of the repository is refused", rc == 2 and not (fake / "frontend" / "dash.json").exists())
    link = tmpd / "link.json"
    try:
        os.symlink(f, link)
        rc, _o = run_tool("--out", str(link), "--overwrite")
        check("--out through a symlink is refused", rc == 2)
    except (OSError, NotImplementedError):
        check("--out through a symlink is refused (no symlink on this host: checked by the code path only)", G.safe_out.__doc__ is not None and "symlink" in G.safe_out.__doc__)
    # --verify-storage
    wrapped = tmpd / "stored.json"
    wrapped.write_text(json.dumps({"version": 1, "minor_version": 1, "key": "lovelace.x", "data": {"config": CFG}}), encoding="utf-8")
    check("--verify-storage: a raw storage file whose data.config is the generated one is EQUAL", run_tool("--verify-storage", str(wrapped))[0] == 0)
    bare = tmpd / "bare.json"
    bare.write_text(json.dumps(CFG), encoding="utf-8")
    check("--verify-storage: a bare configuration is read too (the key order does not matter)", run_tool("--verify-storage", str(bare))[0] == 0)
    bad = copy.deepcopy(CFG)
    bad["views"][0]["cards"][0]["always"][1]["title"] = "Watchdog and statuz"
    wrapped.write_text(json.dumps({"data": {"config": bad}}), encoding="utf-8")
    rc, out = run_tool("--verify-storage", str(wrapped))
    check("--verify-storage: one changed letter in a card is a DIFFERENCE (exit 1)", rc == 1 and "DIFFERS" in out, out[-200:])
    bad = copy.deepcopy(CFG)
    bad["views"][0]["cards"][0]["catalogue"]["sources"].pop()
    bare.write_text(json.dumps(bad), encoding="utf-8")
    check("--verify-storage: a catalogue source missing is a DIFFERENCE", run_tool("--verify-storage", str(bare))[0] == 1)
    bare.write_text("not json", encoding="utf-8")
    check("--verify-storage: a file that is not JSON is refused (exit 2)", run_tool("--verify-storage", str(bare))[0] == 2)
    check("no mode given is a usage error (exit 2)", run_tool()[0] == 2)

# ===========================================================================
print("")
print("[5] the resource plan, read by the real verify-resource")
# ===========================================================================
CARD_BYTES = (ROOT / G.CARD_REL).read_bytes()
PLAN = G.resource_plan(CARD_BYTES)
card = PLAN["cards"][0]
check("the plan names one card: the shell's tag, the content-addressed file, its /local/ecco URL, a module, the full sha256 of the LF file",
      PLAN["schema"] == "ecco-geek-u1-resource-plan/1" and len(PLAN["cards"]) == 1 and card["tag"] == "ecco-mode-shell"
      and card["name"] == f"ecco-mode-shell.{G.sha256(CARD_BYTES)[:8]}.js" and card["resource_url"] == f"/local/ecco/{card['name']}"
      and card["resource_type"] == "module" and card["sha256"] == G.sha256(CARD_BYTES) and card["source"] == G.CARD_REL)
check("a CRLF card is refused (its hash would not be the content address)", _raises(G.Refused, lambda: G.resource_plan(CARD_BYTES.replace(b"\n", b"\r\n"))))


def res(i: int, url: str, typ: str = "module") -> dict:
    return {"id": f"{i:032x}", "url": url, "type": typ}


BEFORE = [res(1, "/local/ecco/ecco-energy-actions-card.aaaaaaaa.js"), res(2, "/local/ecco/ecco-intelligence-card.bbbbbbbb.js"), res(3, "/hacsfiles/other/other.js", "js")]
NEW = res(4, card["resource_url"])


def verify(before, now, served=None, extra=(), age_s=0.0, plan=PLAN):
    """Run the real `verify-resource` on files in a scratch folder: (exit code, stdout)."""
    with tempfile.TemporaryDirectory(prefix="ecco-u1-verify-") as tmp:
        d = Path(tmp)
        (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (d / "before.json").write_text(json.dumps({"version": 1, "key": "lovelace_resources", "data": {"items": before}}), encoding="utf-8")
        nowp = d / "now.json"
        nowp.write_text(json.dumps({"version": 1, "key": "lovelace_resources", "data": {"items": now}}) if not isinstance(now, str) else now, encoding="utf-8")
        t = time.time() - age_s
        os.utime(nowp, (t, t))
        args = ["verify-resource", "--plan", str(d / "plan.json"), "--resources", str(nowp), "--before", str(d / "before.json"), *extra]
        saved = P.fetch
        if served is not None:
            P.fetch = lambda url, timeout: (served, "text/javascript", "no-store")
            args += ["--base-url", "http://127.0.0.1:1"]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = P.main(args)
        finally:
            P.fetch = saved
        return rc, out.getvalue()


rc, out = verify(BEFORE, BEFORE + [NEW], served=CARD_BYTES)
check("a correct switch (one resource added, the others untouched, the served bytes the card's) is RESOURCE VERIFIED and exit 0",
      rc == 0 and f"RESOURCE VERIFIED ecco-mode-shell -> {card['resource_url']}" in out and "verify-resource PASSED" in out and "not checked: nothing" in out, out[-500:])
rc, out = verify(BEFORE, BEFORE)
check("no resource added: RESOURCE NOT SWITCHED, exit 1", rc == 1 and "RESOURCE NOT SWITCHED ecco-mode-shell" in out, out[-300:])
rc, out = verify(BEFORE, BEFORE + [res(4, "/local/ecco/ecco-mode-shell.deadbeef.js")])
check("a resource for another file of the card (a different hash): NOT SWITCHED, exit 1", rc == 1 and "NOT SWITCHED" in out, out[-300:])
rc, out = verify(BEFORE, BEFORE + [res(4, card["resource_url"], "js")])
check("the resource has the type js, not module: NOT VERIFIED, exit 1", rc == 1 and "RESOURCE NOT VERIFIED" in out, out[-300:])
rc, out = verify(BEFORE, BEFORE + [NEW, res(5, "/local/ecco/ecco-mode-shell.deadbeef.js")])
check("two resources load the card: NOT VERIFIED, exit 1", rc == 1 and "exactly one ECCO resource" in out and "RESOURCE NOT VERIFIED" in out, out[-300:])
changed = copy.deepcopy(BEFORE)
changed[0]["url"] = "/local/ecco/ecco-energy-actions-card.cccccccc.js"
rc, out = verify(BEFORE, changed + [NEW])
check("another resource was repointed at the same time: NOT VERIFIED, exit 1", rc == 1 and "no other resource changed" in out and "FAIL" in out, out[-400:])
rc, out = verify(BEFORE, BEFORE[:2] + [NEW])
check("another resource was removed at the same time: NOT VERIFIED, exit 1", rc == 1 and "removed" in out, out[-400:])
rc, out = verify(BEFORE, BEFORE + [NEW, res(9, "/local/ecco/something-else.dddddddd.js")])
check("a second, unrelated resource was added at the same time: NOT VERIFIED, exit 1", rc == 1 and "added" in out, out[-400:])
rc, out = verify(BEFORE, BEFORE + [NEW], age_s=3600)
check("a read-back older than 30 minutes is not fresh: NOT VERIFIED, exit 1", rc == 1 and "is fresh" in out and "FAIL" in out, out[-300:])
rc, out = verify(BEFORE, BEFORE + [NEW], served=CARD_BYTES + b"\n")
check("the bytes served at the URL differ from the card's: NOT VERIFIED, exit 1", rc == 1 and "DIFFERS from the plan" in out, out[-300:])
rc, out = verify(BEFORE, "{ not json")
check("a malformed read-back is refused (exit 2), never a pass", rc == 2)
rc, out = verify(BEFORE, BEFORE + [NEW, dict(NEW)])
check("duplicate resource ids are refused (exit 2)", rc == 2)
# verify-served reads the same plan
saved = P.fetch
try:
    P.fetch = lambda url, timeout: (CARD_BYTES, "text/javascript", "no-store")
    with tempfile.TemporaryDirectory(prefix="ecco-u1-served-") as tmp:
        (Path(tmp) / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            rc_ok = P.main(["verify-served", "--plan", str(Path(tmp) / "plan.json"), "--base-url", "http://127.0.0.1:1"])
        P.fetch = lambda url, timeout: (CARD_BYTES[:-1], "text/javascript", "no-store")
        with contextlib.redirect_stdout(io.StringIO()):
            rc_bad = P.main(["verify-served", "--plan", str(Path(tmp) / "plan.json"), "--base-url", "http://127.0.0.1:1"])
finally:
    P.fetch = saved
check("verify-served reads the same plan: the card's bytes PASS (exit 0), one byte short FAILS (exit 1)", rc_ok == 0 and rc_bad == 1)

# ===========================================================================
print("")
print("[6] mutants: each is caught")
# ===========================================================================
EQUALITY = ("differs from a fresh generation", "not equal to a fresh generation")


def remake(fn):
    c = copy.deepcopy(CFG)
    fn(c)
    return G.render(c)


def caught(text, ex=EXAMPLE_TEXT, cat=CATALOGUE_BYTES, want=None):
    found = G.problems(text, ex, cat)
    if not found:
        return False, "NOT CAUGHT"
    if want is not None:
        specific = [p for p in found if want in p]
        return bool(specific), "; ".join(found)[:160]
    return True, "; ".join(found)[:160]


def sh(c):
    return c["views"][0]["cards"][0]


MUTANTS = [
    ("M01 a catalogue source dropped", remake(lambda c: sh(c)["catalogue"]["sources"].pop()), "inline catalogue"),
    ("M02 one letter of a catalogue text changed", remake(lambda c: sh(c)["catalogue"]["sources"][0].__setitem__("title", sh(c)["catalogue"]["sources"][0]["title"] + "x")), "inline catalogue"),
    ("M03 an alert dropped from the catalogue", remake(lambda c: sh(c)["catalogue"]["alerts"].pop(0)), "inline catalogue"),
    ("M04 the catalogue replaced by an !include", remake(lambda c: sh(c).__setitem__("catalogue", "!include ../catalogue/intelligence.catalogue.json")), "!include"),
    ("M05 a URL in a card title", remake(lambda c: sh(c)["always"][0].__setitem__("title", "see https://example.invalid/x")), "url-like"),
    ("M06 a private address in a card title", remake(lambda c: sh(c).__setitem__("title", "host " + ".".join(("192", "168", "1", "20")))), "ipv4-like"),
    ("M07 an e-mail address in a card title", remake(lambda c: sh(c).__setitem__("title", "a.b@example.org")), "email-like"),
    ("M08 a token in a card title", remake(lambda c: sh(c).__setitem__("title", "ghp_" + "a" * 36)), "token-like"),
    ("M09 a write-capable card (button) in the always list", remake(lambda c: sh(c)["always"].append({"type": "button", "entity": "x.y"})), "card type 'button'"),
    ("M10 a card type the example does not use (picture-glance) in production", remake(lambda c: sh(c)["production"].append({"type": "picture-glance"})), "card type 'picture-glance'"),
    ("M11 another custom card in production", remake(lambda c: sh(c)["production"].append({"type": "custom:button-card"})), "custom card"),
    ("M12 a service call in the always entities card", remake(lambda c: sh(c)["always"][1].__setitem__("service", "x.y")), "service-call key"),
    ("M13 a perform_action in the pause tile", remake(lambda c: sh(c)["production"][0]["tap_action"].__setitem__("perform_action", "x.y")), "service-call key"),
    ("M14 the toggle action in the always list", remake(lambda c: sh(c)["always"][1].__setitem__("tap_action", {"action": "toggle"})), "action 'toggle'"),
    ("M15 the pause tile moved into the always list", remake(lambda c: (sh(c)["always"].append(sh(c)["production"].pop(0)))), "action 'toggle'"),
    ("M16 the text fallback dropped", remake(lambda c: c["views"][0]["cards"].pop()), "not [the shell, the text fallback]"),
    ("M17 the cards swapped", remake(lambda c: c["views"][0]["cards"].reverse()), "not [the shell, the text fallback]"),
    ("M18 a second view", remake(lambda c: c["views"].append(copy.deepcopy(c["views"][0]))), "not exactly one view"),
    ("M19 a strategy key at the top level", remake(lambda c: c.__setitem__("strategy", {"type": "original-states"})), "top level"),
    ("M20 a non-ASCII letter", TEXT.replace('"title": "ECCO Intelligence",', '"title": "ECCO Intelligenc\u00e9",', 1), "not ASCII"),
    ("M21 CRLF line ends", TEXT.replace("\n", "\r\n"), "CR"),
    ("M22 a duplicate JSON key", TEXT.replace('"view_id": "intelligence",\n          "title"', '"view_id": "intelligence",\n          "view_id": "x",\n          "title"', 1), "not strict JSON"),
    ("M23 a NaN", TEXT.replace('"title": "ECCO Intelligence",', '"title": NaN,', 1), "not strict JSON"),
    ("M24 padded past 400 KB", remake(lambda c: sh(c).__setitem__("title", "pad " * 100_000)), "larger than"),
]
for name, text, want in MUTANTS:
    ok, why = caught(text, want=want)
    check(f"{name}: caught", ok, why)
# the inputs are mutated too: the generator refuses them
two_includes = EXAMPLE_TEXT.replace("        always:\n", "        always:\n", 1).replace("title: \"ECCO Intelligence\"\n        catalogue", "title: \"ECCO Intelligence\"\n        extra: !include ../catalogue/x.json\n        catalogue", 1)
check("input mutant: a second !include in the example is refused", two_includes != EXAMPLE_TEXT and _raises(G.Refused, lambda: G.build_config(two_includes, CATALOGUE_BYTES)))
other_include = EXAMPLE_TEXT.replace("../catalogue/intelligence.catalogue.json", "../catalogue/other.json")
check("input mutant: an !include of another file is refused", other_include != EXAMPLE_TEXT and _raises(G.Refused, lambda: G.build_config(other_include, CATALOGUE_BYTES)))
check("input mutant: a catalogue of another schema is refused", _raises(G.Refused, lambda: G.build_config(EXAMPLE_TEXT, CATALOGUE_BYTES.replace(b"ecco-geek-catalogue/1", b"ecco-geek-catalogue/2", 1))))
check("input mutant: a catalogue with a duplicate key is refused", _raises(G.Refused, lambda: G.build_config(EXAMPLE_TEXT, CATALOGUE_BYTES.replace(b'"view_id": "intelligence",', b'"view_id": "intelligence", "view_id": "x",', 1))))
ok, why = caught(TEXT, ex=EXAMPLE_TEXT.replace("Watchdog and status", "Watchdog and statuz"))
check("input mutant: the example changed after the output was made (an output that no longer equals the generation) is caught", ok, why)
ok, why = caught(TEXT, cat=CATALOGUE_BYTES.replace(b"SHADOW", b"SHADOX", 1))
check("input mutant: the catalogue changed after the output was made is caught", ok, why)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
