#!/usr/bin/env python3
"""tools/ecco_intel_drill.py: install / upgrade / rollback / uninstall drills on a tempfile MOCK configuration root only.

  * the full drill (install kit A, upgrade to kit B, roll back to A, uninstall) reproduces the expected trees and hashes at
    every step, and leaves the expected staging and backup trees (nothing is ever deleted);
  * staging is under ecco/staging/<stamp>/, never inside custom_components/; backups under ecco-backups/<stamp>/ verify;
  * ecco/intelligence/site.local.json, ecco/intelligence/state/ and every other integration are never touched;
  * a failed in-place verification puts the previous tree back;
  * refused: a root without the marker, a root that looks like a real HA configuration (.storage/), any argument naming the
    host alias 'ecco-ha' or a host:path remote spec, a tampered kit (nothing staged), a reused stamp, an install over an
    existing one, an upgrade or uninstall with nothing installed;
  * the runbook printer verifies the kit and marks every live step NOT AVAILABLE / PENDING; its step 8 reads PAUSED with
    the pause helper on, then STARTING and a computed status once the helper is off, as the runbook document does;
  * the runbook document (A42, RT4-1 (a); A45, RV9-1 and RV9-2; A47, RV10-1): section 7 has the go / no-go row R5
    (after the first next-day publication the status entity shows TARIFF_VERIFIED, the import table's own code; R5
    reads its presence as T11 does, and without it the table's own code stands in its place, the listed codes examples
    and none a cheap-run code; the cheap-run codes, exactly those intelligence/tariff.py's cheap_window emits, are named
    as a verified table's shape and do not fail it; TARIFF_VERIFIED implies the table fresh and input_ages is a live
    check, not recorded; the cause is the import table's own code, a runtime refusal also leaving a TABLE_* note),
    section 8 the 72 h row T11 (VERIFIED in every computed cycle from the next-day publication to local midnight, a
    documented tariff-feed outage excepted; a null status is not counted, STALE judged by T3 and SELF_TEST_FAILED by T2;
    the CHARGE_WINDOW_NOT_PRICED sentences kept), section 9's Q6 counts a computed cycle without TARIFF_VERIFIED (before
    the next-day publication, with neither it nor TARIFF_COVERAGE_SHORT) as an input fault, the cheap-run codes named
    and not counted, and says a refused, gapped or stale table shows CHARGE_WINDOW_NOT_PRICED wherever a TOU window
    stands (R10D-4 (a)); the readiness list maps the two day events [current, next] and names the same rule;
    INTELLIGENCE_HA_RUNTIME risk 8 cites R5, T11 and Q6 with the same rules, gives the recommended form as a site's
    mapping (never as what a site file holds) and no longer says the download redacts the source notes, and its
    section 2.2 says the diagnostics list each PV forecast observation by day and position only, never by its source
    name (A45, RV9-3); the guide's RT4-1 row reads the import table's own code (A47);
  * A47 (R10D-1), RR1-2: T7 keeps the recorded null rule and makes 'no number past valid_until' a live check of the
    entities (valid_until is not recorded, A17, and the download holds neither the items' states nor valid_until), R2
    likewise; A50, RR1-4: section 8 says cycle_stats keeps the last PROPOSED_CYCLE_STATS_N runs (the value in const.py,
    more than 72 h can start), so one download at the end of the 72 h holds a window whose wall-clock span is at most
    72 h, T1, T5 and T9 read from its runs rows (not by_kind), a restart or reload empties it (a download before each), a
    download at least once a day; RUN-1: an upstream outage pauses the clock while the cycles go on, so after a paused
    stretch the window's first hours come from the earlier downloads (the oldest-row rule), const.py's comment and
    INTELLIGENCE_HA_RUNTIME saying the same of one download at the end;
    A49 (AUD-12): R3 reads cadence.cpu_s_rolling_hour beside refresh_suppressed_cpu (at most 120 s once an hour has
    run), refresh_suspended_cpu and CPU_BUDGET, T9 takes the rolling hour's p95 from the downloads' cycle_stats, and
    INTELLIGENCE_HA_RUNTIME's CPU guard and risk 4 say so; A49 (P4), RR1-1: section 7 has the entity-id collision
    recovery (HA keeps a deleted entry's ids and gives them back, so never delete and re-add; find what holds the id,
    freeing it a separate owner decision recorded against R4, a no-go when declined; a registry entity in the UI, a
    state without a unique id by stopping its source and a restart or the REST delete-state call; the id free before
    the rename; rename, reload, verify; the 'output not recognised' notification and the recorder's 'cannot migrate'
    warning), and section 11 and INTELLIGENCE_HA_RUNTIME say HA keeps the deleted ids while it keeps their records
    (RR1-7); RR1-5: section 3 and the SITE_FILE row say the site file has no byte-order mark; RUN-2: section 3 names
    the editor setting and gives a cls-first Windows PowerShell 5.1 block that writes the file back without a mark,
    before site-check; RUN-3: the collision recovery's lead-in says steps 2 to 4 need no restart and step 1's freeing
    of a holder without a unique id may need a separately approved one;
  * A45 (R9D-3), A47 (RV10-2, R10D-2): no document published with the runtime (the runbook, INTELLIGENCE_HA_RUNTIME, the
    guide, UI_DESIGN, the card README, the integration README) carries owner-process narrative, a dated owner answer,
    decision or default (a decision word within 40 characters of a date), or a commit id; RR1-3: nor does the
    runtime's code and tests (the integration package, the drill), whose guard samples are fictional;
  * site-check (the owner's site file through the runtime's own loader): the example profile exits 0 with every published
    item BLOCKED (each gated item naming an OPEN decision it needs); a complete fictional file is not blocked by the file
    (the check can pass), and dropping one mapping or I-D6 limit blocks exactly the items that need it (the overlay, the
    clock offset, the supervision state, the event table's limit, house power); the raw SOC alone satisfies battery.soc;
    an INVALID decision (a malformed record_ref, a 140 % reserve), a placeholder left in the map (SITE_ENTITY_MAP FAIL),
    a configuration-poll liveness or online entity equal to the telemetry poll text (SITE_ENTITY_MAP FAIL, by field path),
    the two TOU enables, or a TOU enable and supervision.stable, on one entity (A36, RR-3; SITE_ENTITY_MAP FAIL), a
    boolean gate on the configuration-online entity or the raw SOC on the canonical SOC signal's entity (A39;
    SITE_ENTITY_MAP FAIL), a day event listed twice, four day events or a list for tariff.events (A38 Part B;
    SITE_ENTITY_MAP FAIL), one rate event (entity and attribute) under two of tariff.import_rates, tariff.export_rates
    and tariff.events, a day event of a list included (A42, RT4-2; SITE_ENTITY_MAP FAIL), a file over the runtime's cap
    and a mapped capacity source v0.1 leaves unmapped (A25) each exit 1; a complete fictional file with the import rates
    as the two day events [current, next] (the recommended form, A42) or as three day events (allowed, A38 Part B), and
    one with one entity holding the import and export rates under separate attributes, exit 0; sha256 and the runtime's
    config_hash; no entity id, record reference, placeholder or forecast source name in any output, text or JSON;
    INTELLIGENCE_HA_RUNTIME.md section 4.1's example loads as written, with fictional ids only and every input a
    published item needs, and maps the import rates in the recommended form, the current-day and next-day events in
    that order (A42);
  * no ssh / scp / subprocess / network use anywhere in the drill or the build tool (AST).
Plain script; exits 1 on any failure. Temporary directories are created and removed by this suite.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


PREFIX = "ecco_intel_drill_"
TOOL = REPO / "tools" / "ecco_intel_drill.py"
PKG = "custom_components/ecco_intelligence"
spec = importlib.util.spec_from_file_location("ecco_intel_drill", TOOL)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def run_tool(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-B", str(TOOL), *args], capture_output=True, text=True, timeout=300,
                          cwd=str(cwd or REPO), env=ENV)


def pkg_tree(kit: Path) -> dict[str, str]:
    return H.tree_hashes(kit / "custom_components" / "ecco_intelligence")


def files_only(t: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in t.items() if not k.endswith("/")}


def make_root(base: Path, name: str, *, marker: bool = True) -> Path:
    r = base / name
    (r / "ecco" / "intelligence" / "state").mkdir(parents=True)
    (r / "ecco" / "intelligence" / "site.local.json").write_text('{"_comment": "synthetic mock site file"}\n', encoding="utf-8")
    (r / "ecco" / "intelligence" / "state" / "scorecard.sqlite3").write_bytes(b"synthetic state bytes")
    (r / "custom_components" / "other_integration").mkdir(parents=True)
    (r / "custom_components" / "other_integration" / "__init__.py").write_text("# another integration\n", encoding="utf-8")
    (r / "configuration.yaml").write_text("# synthetic\n", encoding="utf-8")
    if marker:
        (r / D.MARKER).write_text("mock\n", encoding="utf-8")
    return r


def untouched(root: Path) -> dict[str, str]:
    t = H.tree_hashes(root)
    return {k: v for k, v in t.items() if k.startswith(("ecco/intelligence/", "custom_components/other_integration",
                                                         "configuration.yaml", D.MARKER))}


base = H.mktemp(PREFIX)
try:
    kit_a, kit_b = base / "kit_a", base / "kit_b"
    check("kit A builds", H.build_kit(kit_a).returncode == 0)
    shutil.copytree(kit_a, kit_b)
    f = kit_b / PKG / "runtime" / "selftest.py"
    f.write_bytes(f.read_bytes() + b"\n# kit B: a synthetic upgrade\n")
    sums = "".join(f"{hashlib.sha256((kit_b / rel).read_bytes()).hexdigest()}  {rel}\n"
                   for rel in sorted(k for k in files_only(H.tree_hashes(kit_b)) if k != "SHA256SUMS"))
    (kit_b / "SHA256SUMS").write_bytes(sums.encode("utf-8"))
    A, B = files_only(pkg_tree(kit_a)), files_only(pkg_tree(kit_b))
    check("kits A and B differ in exactly one file", sorted(k for k in A if A[k] != B.get(k)) == ["runtime/selftest.py"])

    print("== the full drill (command line)")
    root = make_root(base, "mock")
    keep = untouched(root)
    r = run_tool("drill", "--config-root", str(root), "--kit", str(kit_a), "--upgrade-kit", str(kit_b), "--stamp",
                 "20300115-120000")
    check("the drill exits 0", r.returncode == 0, (r.stdout + r.stderr)[-500:])
    s0, s1, s2, s3 = "20300115-120000", "20300115-120001", "20300115-120002", "20300115-120003"
    t = H.tree_hashes(root)

    def sub(prefix: str) -> dict[str, str]:
        return {k[len(prefix):]: v for k, v in t.items() if k.startswith(prefix) and not k.endswith("/")}
    check("after the full drill the integration is uninstalled", not (root / PKG).exists())
    check("upgrade moved kit A's tree aside (ecco/staging/<s1>/previous/)", sub(f"ecco/staging/{s1}/previous/ecco_intelligence/") == A)
    check("rollback moved kit B's tree aside (ecco/staging/<s2>/previous/)", sub(f"ecco/staging/{s2}/previous/ecco_intelligence/") == B)
    check("uninstall moved the rolled-back tree (kit A) aside, nothing deleted",
          sub(f"ecco/staging/{s3}/uninstalled/ecco_intelligence/") == A)
    check("backups: before upgrade = A, before rollback = B, before uninstall = A",
          sub(f"ecco-backups/{s1}/custom_components__ecco_intelligence/") == A
          and sub(f"ecco-backups/{s2}/custom_components__ecco_intelligence/") == B
          and sub(f"ecco-backups/{s3}/custom_components__ecco_intelligence/") == A)
    check("the first install had nothing to back up", not sub(f"ecco-backups/{s0}/"))
    check("every backup carries a verifying BACKUP_SHA256SUMS", all(
        D.read_sums(root / "ecco-backups" / s / "BACKUP_SHA256SUMS") == sub(f"ecco-backups/{s}/custom_components__ecco_intelligence/")
        for s in (s1, s2, s3)))
    inside_cc = sorted({k.split("/")[1] for k in t if k.startswith("custom_components/") and k.count("/") >= 2})
    check("nothing was ever staged inside custom_components/ (only the other integration remains)", inside_cc == ["other_integration"],
          str(inside_cc))
    check("site.local.json, state/ and the other integration are untouched", untouched(root) == keep)

    print("== step by step (expected trees after each operation)")
    root2 = make_root(base, "mock_steps")
    keep2 = untouched(root2)
    d = D.Drill(D.mock_root(str(root2)), log=lambda *_: None)
    d.install(kit_a, "20300115-130000")
    check("install: the installed tree equals kit A", files_only(H.tree_hashes(root2 / PKG)) == A)
    try:
        d.install(kit_a, "20300115-130001")
        check("a second install is refused", False)
    except D.DrillError:
        check("a second install is refused (use upgrade)", True)
    d.install(kit_b, "20300115-130002", upgrade=True)
    check("upgrade: the installed tree equals kit B", files_only(H.tree_hashes(root2 / PKG)) == B)
    d.rollback("20300115-130003", "20300115-130002")
    check("rollback: the installed tree equals kit A again", files_only(H.tree_hashes(root2 / PKG)) == A)
    try:
        d.rollback("20300115-130003")
        check("a reused stamp is refused", False)
    except D.DrillError:
        check("a reused stamp is refused (nothing is overwritten)", True)
    (root2 / PKG / "__pycache__").mkdir()
    (root2 / PKG / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"cache")
    d.install(kit_b, "20300115-130004", upgrade=True)
    check("an upgrade over a tree with an HA __pycache__ succeeds (caches are not part of the kit)",
          files_only(H.tree_hashes(root2 / PKG)) == B)
    d.uninstall("20300115-130005")
    check("uninstall: no integration directory left", not (root2 / PKG).exists())
    try:
        d.uninstall("20300115-130006")
        check("uninstall with nothing installed is refused", False)
    except D.DrillError:
        check("uninstall with nothing installed is refused", True)
    try:
        d.install(kit_a, "20300115-130007", upgrade=True)
        check("upgrade with nothing installed is refused", False)
    except D.DrillError:
        check("upgrade with nothing installed is refused", True)
    check("site.local.json, state/ and the other integration untouched by every step", untouched(root2) == keep2)
    fails = [s_[1] for s_ in d.steps if s_[0] == "FAIL"]
    check("the only FAIL steps are the three refusals asked for", len(fails) == 3 and len(d.steps) > 40, str(fails))

    print("== a failed in-place verification puts the previous tree back")
    root3 = make_root(base, "mock_fail")
    d3 = D.Drill(D.mock_root(str(root3)), log=lambda *_: None)
    d3.install(kit_a, "20300115-140000")
    real_tree = D.tree
    calls = {"n": 0}

    def lying_tree(path, ignore=()):
        out = real_tree(path, ignore)
        if Path(path).resolve() == (root3 / PKG).resolve() and out.get("runtime/selftest.py") == B["runtime/selftest.py"]:
            calls["n"] += 1                       # only after the swap: the new tree "fails" its in-place verification
            out = dict(out, **{"manifest.json": "0" * 64})
        return out
    D.tree = lying_tree
    try:
        d3.install(kit_b, "20300115-140001", upgrade=True)
        check("the failed verification is reported", False)
    except D.DrillError:
        check("the failed verification is reported", calls["n"] >= 1)
    finally:
        D.tree = real_tree
    check("... and the previous tree (kit A) is back in place", files_only(H.tree_hashes(root3 / PKG)) == A)
    check("... the failed tree is kept under ecco/staging/<stamp>/failed/ (nothing deleted)",
          files_only(H.tree_hashes(root3 / "ecco" / "staging" / "20300115-140001" / "failed" / "ecco_intelligence")) == B)

    print("== refusals")
    nomark = make_root(base, "no_marker", marker=False)
    before = H.tree_hashes(nomark)
    r = run_tool("install", "--config-root", str(nomark), "--kit", str(kit_a), "--stamp", "20300115-150000")
    check("a root without the marker is refused and left unchanged", r.returncode != 0 and H.tree_hashes(nomark) == before)
    real_like = make_root(base, "real_like")
    (real_like / ".storage").mkdir()
    r = run_tool("install", "--config-root", str(real_like), "--kit", str(kit_a))
    check("a root with .storage/ (a real HA configuration) is refused", r.returncode != 0 and not (real_like / PKG).exists())
    host_root = make_root(base, "mock_ecco-ha_root")
    for args, label in ((["install", "--config-root", str(host_root), "--kit", str(kit_a)], "a config root path naming ecco-ha"),
                        (["install", "--config-root", str(root), "--kit", "ecco-ha:/config"], "a kit given as ecco-ha:/config"),
                        (["runbook", "--kit", "ECCO-HA:/tmp/kit"], "the host alias in any case"),
                        (["install", "--config-root", "somehost:/config", "--kit", str(kit_a)], "a host:path remote spec")):
        r = run_tool(*args)
        check(f"refused: {label}", r.returncode != 0 and "REFUSED" in r.stderr, r.stderr[-200:])
    check("... and nothing was installed into the ecco-ha-named root", not (host_root / PKG).exists())
    bad_kit = base / "kit_bad"
    shutil.copytree(kit_a, bad_kit)
    (bad_kit / PKG / "sensor.py").write_bytes(b"# tampered\n")
    root4 = make_root(base, "mock_bad_kit")
    r = run_tool("install", "--config-root", str(root4), "--kit", str(bad_kit), "--stamp", "20300115-160000")
    check("a tampered kit is refused before anything is staged", r.returncode != 0 and not (root4 / "ecco" / "staging").exists()
          and not (root4 / PKG).exists())
    r = run_tool("install", "--config-root", str(root4), "--kit", str(kit_a), "--stamp", "2030-01-15")
    check("a malformed stamp is refused", r.returncode != 0)

    print("== the runbook printer")
    r = run_tool("runbook", "--kit", str(kit_a))
    check("runbook --kit verifies the kit and exits 0", r.returncode == 0 and "verified: yes" in r.stdout, r.stderr[-200:])
    check("every live step is NOT AVAILABLE / PENDING DP-4", r.stdout.count("NOT AVAILABLE") >= 3 and "PENDING DP-4" in r.stdout)
    check("the runbook names the ui package before the integration and the latch caveat",
          r.stdout.index("ui package") < r.stdout.index("stage, verify") and "SHADOW_WOULD_AWAIT_ACK" in r.stdout)
    check("the runbook never names the live host alias", "ecco-ha" not in r.stdout.lower())
    step8 = r.stdout[r.stdout.find(" 8. "):r.stdout.find(" 9. ")]
    flat8 = " ".join(step8.split())
    check("step 8 follows the runbook document (section 7): added with the pause helper on, the status reads PAUSED with "
          "pause_control ON, then STARTING and a computed status once the helper is off (A33, RT-5)",
          "pause helper still on" in flat8 and "status PAUSED and pause_control ON" in flat8
          and "turn the helper off: status STARTING, then a computed status" in flat8
          and flat8.index("PAUSED") < flat8.index("STARTING"), flat8)
    r = run_tool("runbook", "--kit", str(bad_kit))
    check("runbook on a tampered kit says it does not verify (exit 1)", r.returncode == 1 and "verified: NO" in r.stdout)

    print("== the runbook document")
    doc = (REPO / "docs" / "intelligence" / "INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md").read_text(encoding="utf-8")
    blocks = doc.split("```powershell\n")[1:]
    check(f"every PowerShell block starts with cls ({len(blocks)} blocks)", blocks and all(b.split("\n", 1)[0] == "cls" for b in blocks))
    check("the live steps are marked NOT AVAILABLE (PR-5, DP-4) and the status is PENDING DP-4",
          doc.count("NOT AVAILABLE") >= 5 and "install kit staged, PENDING DP-4" in doc)
    check("the ui package comes before the integration; the latch caveat and the supervised dongle reboot are stated",
          doc.index("Install the ui package first") < doc.index("Install the integration")
          and "SHADOW_WOULD_AWAIT_ACK" in doc and "supervised dongle reboot by the owner" in doc)
    check("the site file's sha256 is recorded offline (a placeholder folder only)", "<OFFLINE_EVIDENCE_DIR>" in doc)
    check("go / no-go names the supervision heartbeat age and SUPERVISED / stable across the first observed runs",
          "heartbeat age" in doc and "SUPERVISED / stable" in doc and "first observed runs" in doc)
    check("the runbook never names the live host alias and never claims a deployment",
          "ecco-ha" not in doc.lower() and "deployed" not in doc.lower().replace("not deployed", ""))
    guide = (REPO / "docs" / "intelligence" / "INTELLIGENCE_CONTINUATION_GUIDE.md").read_text(encoding="utf-8")
    rt_text = (REPO / "docs" / "intelligence" / "INTELLIGENCE_HA_RUNTIME.md").read_text(encoding="utf-8")
    dp_lines = {k: re.search(rf"^  - {re.escape(k)} \((OPEN|decided[^)]*)\): \S", guide, re.M)
                for k in ("DP-1", "DP-2", "DP-3", "DP-4a", "DP-4b", "DP-4c", "DP-4", "DP-5")}
    # A47 (RV10-2): every document published with the Home Assistant runtime, the card design and both READMEs included
    pr3_docs = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in (
        "docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md", "docs/intelligence/INTELLIGENCE_HA_RUNTIME.md",
        "docs/intelligence/INTELLIGENCE_CONTINUATION_GUIDE.md", "docs/intelligence/UI_DESIGN.md",
        "frontend/ecco-intelligence-card/README.md", "custom_components/ecco_intelligence/README.md")}
    _date = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4})"
    _dec = r"(?:decision|decided|decide|default|answer|approv|agree|ruling|packet|owner|chose|choice)"
    dated_decision = re.compile(rf"\b{_dec}\w*[^.\n|]{{0,40}}?{_date}|{_date}[^.\n|]{{0,40}}?\b{_dec}", re.I)
    a45_hits = {rel: re.findall(r"packet|owner'?s? decision of|decision of \d|(?:approved|answered|decided) on \d", t, re.I)
                + [m.group(0) for m in dated_decision.finditer(" ".join(t.split()))] for rel, t in pr3_docs.items()}
    check("A45 (R9D-3), A47 (RV10-2): no document published with the runtime (the runbook, INTELLIGENCE_HA_RUNTIME, the "
          "continuation guide, UI_DESIGN, the card README and the integration README) carries a narrative of the owner's "
          "decision process or a dated owner answer, decision or default (a decision word within 40 characters of a "
          "date); the guide defines DP-1 to DP-5 as opaque ids, each line saying what it decides and its status (OPEN, "
          "or decided)",
          not any(a45_hits.values()) and all(dp_lines.values()),
          str({k: v for k, v in a45_hits.items() if v}) + str([k for k, v in dp_lines.items() if not v]))
    sample_dated = "Dropped. The SHADOW v0.1 engineering defaults (1 Jan 2030) drop it"  # guard sample
    sample_commit = "its first version (`0a1b2c3`) kept"  # guard sample
    check("... the guard catches a dated decision phrase of the kind UI_DESIGN carried before A47 (non-vacuity, a "
          "fictional sample)", bool(dated_decision.search(sample_dated))
          and not dated_decision.search("the BST / GMT offsets either side of 25 Oct 2026 and 28 Mar 2027 are right"))
    commit_like = re.compile(r"(?<![0-9A-Za-z_])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
    commit_hits = {rel: commit_like.findall(t) for rel, t in pr3_docs.items()}
    check("A47 (R10D-2): no document published with the runtime cites a commit id (a 7- to 40-digit hex word of letters "
          "and digits): the integration branch's commits are never public, so the reference would dangle",
          not any(commit_hits.values()) and commit_like.findall(sample_commit) == [sample_commit.split("`")[1]],
          str({k: v for k, v in commit_hits.items() if v}))
    # RR1-3: the runtime's own code and tests (the integration package, its tests, the drill) carry neither; the guard's
    # two samples above are fictional and marked, and a marked line is the only one skipped
    pr3_code = sorted([pth for pth in (REPO / "custom_components" / "ecco_intelligence").rglob("*")
                       if pth.is_file() and pth.suffix in (".py", ".md", ".json") and "__pycache__" not in pth.parts]
                      + [REPO / "tools" / "ecco_intel_drill.py"])
    code_hits = {}
    for pth in pr3_code:
        for i_, line_ in enumerate(pth.read_text(encoding="utf-8").splitlines(), 1):
            if line_.rstrip().endswith("# guard sample"):
                continue
            found_ = commit_like.findall(line_) + [m_.group(0) for m_ in dated_decision.finditer(line_)]
            if found_:
                code_hits[f"{pth.relative_to(REPO).as_posix()}:{i_}"] = found_
    check(f"RR1-3: no commit id and no dated decision phrase in the runtime's code and tests ({len(pr3_code)} files: the "
          "integration package with its tests, the drill); the guard's samples are fictional and the only lines skipped",
          len(pr3_code) >= 30 and not code_hits, str(dict(list(code_hits.items())[:5])))

    def section(text: str, start: str, end: str) -> str:
        i = text.find(start)
        j = text.find(end, i + 1) if i >= 0 else -1
        return text[i:j] if i >= 0 and j > i else ""

    def row(text: str, label: str) -> str:
        m = re.search(rf"^\| {label} \|.*$", text, re.M)
        return m.group(0) if m else ""

    unusable = ("`TARIFF_MISSING`", "`TARIFF_NOT_FRESH`", "`TARIFF_GAP`", "`TARIFF_OVERLAP`", "`TARIFF_FUTURE_DATED`")
    engine_refusals = ("`TARIFF_RATE_INVALID`", "`TARIFF_SLOT_INVALID`")
    in_place = "the import table's own code in place of `TARIFF_VERIFIED`"
    before_place = "before the next-day publication, in place of `TARIFF_VERIFIED` and `TARIFF_COVERAGE_SHORT`"
    live_ages = "`TARIFF_VERIFIED` implies the table fresh within its limit; `input_ages` is a live check (it is not recorded)"
    runtime_note = "a refusal by the runtime also leaves a `TABLE_*` note in the diagnostics' `source_notes`"
    # A47 (RV10-1): the cheap-run analysis' codes, read from intelligence/tariff.py's cheap_window (its own guard codes
    # TARIFF_NOT_VERIFIED and TARIFF_COVERAGE_SHORT aside: the first never reaches a verified table, the second is then
    # the import table's own code), which stand beside TARIFF_VERIFIED on a verified table that names no cheap run
    _tariff_tree = ast.parse((REPO / "intelligence" / "tariff.py").read_text(encoding="utf-8"))
    _cw = next(n for n in ast.walk(_tariff_tree) if isinstance(n, ast.FunctionDef) and n.name == "cheap_window")
    shape_codes = {n.args[0].value for n in ast.walk(_cw) if isinstance(n, ast.Call)
                   and getattr(n.func, "id", None) == "finding" and n.args and isinstance(n.args[0], ast.Constant)
                   and str(n.args[0].value).startswith("TARIFF_")} - {"TARIFF_NOT_VERIFIED", "TARIFF_COVERAGE_SHORT"}

    def named_shape(text: str, start: str) -> set[str]:
        """The TARIFF_* codes a text names from `start` to the next 'describe', TARIFF_VERIFIED aside."""
        seg = section(text, start, "describe")
        return set(re.findall(r"`(TARIFF_[A-Z_]+)`", seg)) - {"TARIFF_VERIFIED"}

    check("A47 (RV10-1): cheap_window in intelligence/tariff.py names no run with exactly four codes, the ones the runbook "
          "and risk 8 name as the cheap-run codes (non-vacuity of the pins below)",
          shape_codes == {"TARIFF_NO_SLOTS_AHEAD", "TARIFF_NO_CHEAP_WINDOW", "TARIFF_CHEAP_RUN_TOO_LONG",
                          "TARIFF_NO_PRICE_SPREAD"}, str(sorted(shape_codes)))
    r5 = row(section(doc, "## 7. ", "## 8. "), "R5")
    r5_examples = set(re.findall(r"`(TARIFF_[A-Z_]+)`", section(r5, "stands in its place, for example", "(A45)")))
    check("A42 (RT4-1 (a)), A45 (RV9-1, RV9-2), A47 (RV10-1): the go / no-go list (section 7) has R5: after the first "
          "next-day publication the status entity shows TARIFF_VERIFIED, the import table's own code; R5 reads its "
          "presence as T11 does, and without it the table's own code stands in its place (the five codes, the engine's "
          "refusals and TARIFF_COVERAGE_SHORT as examples, none a cheap-run code); the cheap-run codes cheap_window emits "
          "are named, all of them, as the verified table's shape that does not fail R5; TARIFF_VERIFIED implies the "
          "table fresh and input_ages is a live check; the cause is the import table's own code, a runtime refusal also "
          "leaving a TABLE_* note; it fails while the cadence does not fit (fail closed)",
          "after the first next-day publication" in r5 and "`TARIFF_VERIFIED`, the import table's own code" in r5
          and "R5 reads that code's presence, as T11 does (A47): without it R5 fails" in r5
          and "any other import tariff code fails R5" not in r5
          and all(c in r5 for c in unusable + engine_refusals + ("`TARIFF_COVERAGE_SHORT`",))
          and r5_examples and not r5_examples & shape_codes
          and named_shape(r5, "The cheap-run codes") == shape_codes and "do not fail R5" in r5 and live_ages in r5
          and "cause is the import table's own code in the status entity's `reason_codes`" in r5 and runtime_note in r5
          and "`input_ages` shows" not in r5 and "or in `input_ages`" not in r5 and "intended fail-closed outcome" in r5, r5)
    t11 = row(section(doc, "## 8. ", "## 9. "), "T11")
    check("... the 72 h table (section 8) has T11: on each day, from the next-day publication to local midnight, the import "
          "rates VERIFIED in every computed cycle (the status entity's recorded reason_codes) except during a documented "
          "tariff-feed outage; A45 (RV9-1, option (a)): it counts computed cycles only, a null status (STALE, PAUSED, "
          "STARTING, SELF_TEST_FAILED) is not counted, STALE stays judged by T3 and SELF_TEST_FAILED by T2; "
          "TARIFF_VERIFIED implies the table fresh and input_ages is a live check (not recorded); the "
          "CHARGE_WINDOW_NOT_PRICED sentences stay",
          "from the next-day publication to local midnight" in t11 and "VERIFIED in every computed cycle" in t11
          and "status entity's recorded `reason_codes`" in t11 and "documented tariff-feed outage" in t11
          and "T11 counts computed cycles only" in t11
          and all(f"`{s_}`" in t11 for s_ in ("STALE", "PAUSED", "STARTING", "SELF_TEST_FAILED"))
          and "`STALE` stays judged by T3" in t11 and "`SELF_TEST_FAILED` by T2" in t11 and live_ages in t11
          and "in `input_ages`)" not in t11 and "VERIFIED in every cycle" not in t11
          and "the import table is not usable (missing, refused, gapped or not fresh) also shows INFO "
              "`CHARGE_WINDOW_NOT_PRICED` on the charge-window items wherever a TOU window stands" in t11
          and "(`TARIFF_COVERAGE_SHORT`) shows it only when the table does not price the whole TOU occurrence" in t11, t11)
    q6 = row(section(doc, "## 9. ", "## 10. "), "Q6")
    q6_examples = set(re.findall(r"`(TARIFF_[A-Z_]+)`", section(q6, "The import table's own codes listed here are "
                                                                    "examples", "A table that")))
    check("... and Q6 (section 9) counts, as an input fault although it blocks nothing, every computed cycle without "
          "TARIFF_VERIFIED (before the next-day publication, with neither it nor TARIFF_COVERAGE_SHORT) in the recorded "
          "reason_codes, reading the import table's own code as R5 and T11 do; the cheap-run codes cheap_window emits "
          "are named, all of them, and not counted (A47, RV10-1); the import table's own codes it lists (the five, the "
          "engine's refusals, TARIFF_COVERAGE_SHORT after the publication) are examples, none a cheap-run code (A42, A45 "
          "RV9-2); a refused, gapped or stale table shows CHARGE_WINDOW_NOT_PRICED wherever a TOU window stands, the "
          "import table's own code telling it apart from the residual before the publication (R10D-4 (a)); a runtime "
          "refusal also leaves a TABLE_* note",
          "zero computed cycles without `TARIFF_VERIFIED` (before the next-day publication, with neither "
          "`TARIFF_VERIFIED` nor `TARIFF_COVERAGE_SHORT`) in the status entity's recorded `reason_codes`" in q6
          and "any import tariff code other than" not in q6 and "reads the import table's own code as R5 and T11 do" in q6
          and named_shape(q6, "the cheap-run codes beside") == shape_codes and "are not counted" in q6
          and q6_examples and not q6_examples & shape_codes and all(c in q6 for c in unusable + engine_refusals)
          and "after the publication, `TARIFF_COVERAGE_SHORT`" in q6 and "refused, gapped or not fresh" in q6
          and "counts as an input fault" in q6 and "blocks nothing" in q6 and runtime_note in q6
          and "on the charge-window items wherever a TOU window stands" in q6
          and "the import table's own code is what tells them apart" in q6
          and "outside the hours before the next-day publication" not in q6 and "It shows as `TARIFF_MISSING`" not in q6, q6)
    ready = " ".join(section(doc, "## 1. ", "## 2. ").split())
    check("A45 (RV9-2), A47 (RV10-1): the readiness list says the status entity then shows the import table's own code in "
          "place of TARIFF_VERIFIED (before the next-day publication, in place of it and TARIFF_COVERAGE_SHORT), the "
          "engine's refusals among the examples, that a runtime refusal also leaves a TABLE_* note, and that the "
          "cheap-run codes beside TARIFF_VERIFIED are no fault",
          f"the status entity's reason codes then show {in_place} ({before_place})" in ready
          and all(c in ready for c in engine_refusals) and runtime_note in ready
          and "The cheap-run codes that can stand beside `TARIFF_VERIFIED` describe a verified table's shape and are no "
              "fault (R5)" in ready
          and "any import tariff code other than" not in ready
          and "or `TARIFF_GAP` in place of `TARIFF_VERIFIED`" not in ready, ready[ready.find("Events listed"):][:300])
    check("... the readiness list maps the import rates as the two day events of the recommended form (current, then "
          "next), a site adding the previous-day event only once its report cadence is known to stay within its I-D6 limit "
          "(A42, RT4-1 (c), NEW-2: guidance, never a production site file or a later decision); it names site-check's "
          "refusal of one rate event under two tariff tables (A42, RT4-2)",
          "maps the two day events of the recommended form (the current day, then the next day" in ready
          and "a site adds the previous-day event only once its report cadence is known to stay within its I-D6 limit"
          in ready and "production form" not in ready and "later decision" not in ready
          and "the three day events" not in ready and "`site-check` refuses (exit 1) the same entity and attribute" in ready,
          ready[:200])
    rt_doc = (REPO / "docs" / "intelligence" / "INTELLIGENCE_HA_RUNTIME.md").read_text(encoding="utf-8")
    risk8 = " ".join(section(rt_doc, "8. **Inputs that are not re-reported.**", "9. **Disabling one entity").split())
    check("INTELLIGENCE_HA_RUNTIME risk 8 cites R5, T11 and Q6, names CHARGE_WINDOW_NOT_PRICED and the recommended form "
          "[current day, next day] as a site's mapping, never as what a site file holds, and no longer says the download "
          "redacts the source notes (A42, A47, NEW-2)",
          all(f"**{r_}**" in risk8 for r_ in ("R5", "T11", "Q6")) and "`CHARGE_WINDOW_NOT_PRICED`" in risk8
          and "A site maps the import rates as the two day events [current day, next day], the recommended form" in risk8
          and "redact" not in risk8 and "production site file" not in risk8 and "readiness read" not in risk8
          and "production form" not in risk8, risk8[:200])
    check("A45 (RV9-1, RV9-2), A47 (RV10-1): risk 8 says the status entity shows the import table's own code in place of "
          "TARIFF_VERIFIED (before the next-day publication, in place of it and TARIFF_COVERAGE_SHORT), the engine's "
          "refusals among the examples, and input_ages is a live check that is not recorded; the cheap-run codes "
          "cheap_window emits are named, all of them, as no fault; R5 reads TARIFF_VERIFIED, which implies the table "
          "fresh; T11 counts computed cycles; Q6 counts a computed cycle without TARIFF_VERIFIED",
          f"the status entity's `reason_codes` show {in_place} ({before_place})" in risk8
          and all(c in risk8 for c in engine_refusals) and "a live check that is not recorded" in risk8
          and named_shape(risk8, "The cheap-run codes") == shape_codes
          and "not a fault, so the acceptance rows read only the import table's own code (A47)" in risk8
          and "`TARIFF_VERIFIED`, which implies the table fresh within its limit" in risk8
          and "VERIFIED in every computed cycle" in risk8 and "within its limit in `input_ages`" not in risk8
          and "**Q6** (a computed cycle without `TARIFF_VERIFIED`" in risk8 and "any import tariff code other than" not in risk8
          and "a mapped import table that is refused, gapped or not fresh counts" not in risk8,
          risk8[risk8.find("The case is visible"):][:300])
    rt41 = " ".join(section(rt_doc, "- **The import rates read the tariff integration's day events", "- **v0.1 leaves").split())
    guide_rt41 = row(guide, r"The merged import table refused or never fresh \(RT4-1\)")
    check("A47 (RV10-1, NEW-2 in the runtime's docs): the 4.1 notes and the guide's RT4-1 row give the recommended form as "
          "a site's mapping, never as what a private site file holds, and the RT4-1 row reads the import table's own code, "
          "the cheap-run codes being no fault",
          rt41 and "production site file" not in rt41 and "readiness read shows" not in rt41
          and "add the previous-day event only once its report cadence is known to stay within its I-D6 limit" in rt41
          and "in the recommended form" in rt41
          and "each reads the import table's own code" in guide_rt41 and "count as no fault (A47)" in guide_rt41
          and "(c) The recommended form maps the two day events [current day, next day]" in guide_rt41
          and "production site file" not in guide and "any import tariff code other than" not in guide_rt41,
          guide_rt41[:300])
    _prod = {rel: re.findall(r"production (?:form|site file|mapping)|readiness read", " ".join(t.split()), re.I)
             for rel, t in pr3_docs.items()}
    check("NEW-2 (A47, A50): no document published with the runtime calls the [current day, next day] mapping the "
          "production form or names a production site file or a readiness read: it is the recommended form, a site's "
          "guidance", not any(_prod.values()), str({k: v for k, v in _prod.items() if v}))
    # A47 (R10D-1): T7 and T1 claim only what is recorded; A49 (AUD-12): R3 and T9 track the CPU guard's headroom
    sec7 = section(doc, "## 7. ", "## 8. ")
    sec8 = section(doc, "## 8. ", "## 9. ")
    r2, r3 = row(sec7, "R2"), row(sec7, "R3")
    t1, t7, t9 = row(sec8, "T1"), row(sec8, "T7"), row(sec8, "T9")
    dl_rule = " ".join(section(sec8, "**The diagnostics downloads (A47, A50).**", "| # |").split())
    t5 = row(sec8, "T5")
    const_src = (REPO / "custom_components" / "ecco_intelligence" / "const.py").read_text(encoding="utf-8")
    n_stats = re.search(r"^PROPOSED_CYCLE_STATS_N = (\d+)", const_src, re.M)
    check("A47 (R10D-1): T7 keeps the recorded null rule and says valid_until is not recorded (A17), so 'no number past "
          "valid_until' is a live check at each diagnostics download and live read, the runtime half pinned by the L2 "
          "suites; R2 says the same of its valid_until clause",
          "in the recorded states no number in a null status or for an item whose decisions are OPEN" in t7
          and "`valid_until` is not recorded (A17" in t7 and "is a live check" in t7
          and "at each live read of the entities (each item's state and its `valid_until` attribute" in t7
          and "the download itself carries neither" in t7 and "at each diagnostics download and" not in t7
          and "L2 suites" in t7
          and "in the recorded states no number in a null status, past `valid_until`" not in t7
          and "none past `valid_until` (a live check" in r2, t7)
    check("A47 (R10D-1), A50, RR1-4: section 8 says the download keeps no history beyond cycle_stats, the last "
          "PROPOSED_CYCLE_STATS_N runs (the value const.py holds), more than 72 h can start, so one download at the end "
          "holds the window and T1, T5 and T9 are read from its runs rows (not by_kind); a restart or reload empties it, "
          "so a download before each; downloads kept offline, at least once a day; hours no kept row covers leave T1, T5 "
          "and T9 unproven; T1 and T5 read the runs rows",
          n_stats is not None and int(n_stats.group(1)) >= 4800
          and f"`PROPOSED_CYCLE_STATS_N` = {n_stats.group(1)} runs: more than the 72 h can start" in dl_rule
          and "One download taken at the end of the 72 h therefore holds every run of a window whose wall-clock span is "
              "at most 72 h" in dl_rule
          and "One download taken at the end of the 72 h therefore holds every run of the window," not in dl_rule
          and "T1, T5 and T9 are read from its `runs` rows that started inside the window (not from `by_kind`" in dl_rule
          and "a Home Assistant restart or a reload of the entry empties it" in dl_rule
          and "take a download before any approved restart or reload too" in dl_rule
          and "`<OFFLINE_EVIDENCE_DIR>`" in dl_rule and "at least once a day" in dl_rule
          and "leave T1, T5 and T9 unproven for those hours" in dl_rule and "1440" not in dl_rule
          and "read from the downloads' `runs` rows" in t1
          and "computed from the `total_s` of the downloads' `runs` rows that started inside the 72 h" in t5,
          dl_rule[:300])
    check("RUN-1: an upstream outage pauses the clock while the cycles go on, so a window with a paused stretch spans "
          "more than 72 h of wall time; its first hours are read from the earlier downloads (the oldest-row rule), and "
          "const.py's comment and INTELLIGENCE_HA_RUNTIME say the same of one download at the end",
          "An upstream outage pauses the clock while the cycles go on, so after a paused stretch the window spans more "
          "than 72 h of wall time and its first hours can fall before the end download's oldest kept run: read those "
          "hours from the earlier downloads (the oldest-row rule below)" in dl_rule
          and "the oldest row of the download that covers the clock's start must be at or before it" in dl_rule
          and "one download at the end of a window that spans at most 72 h" in " ".join(const_src.replace("#", " ").split())
          and "one at the end holds every run of a window that spans at most 72 h" in " ".join(rt_doc.split())
          and "holds every run of the 72 h" not in " ".join(rt_doc.split()),
          dl_rule[:600])
    check("A49 (AUD-12): R3 reads the CPU guard's headroom, not inferred from STALE: cadence.cpu_s_rolling_hour at most "
          "120 s (T9's bound, the guard 180 s) once an hour of refreshes has run, refresh_suspended_cpu false, no "
          "CPU_BUDGET WARN, refresh_suppressed_cpu 0; T9 takes the rolling hour's p95 over the 72 h from the downloads' "
          "cycle_stats (cpu_s summed over the hour before each run's start) and records each download's readings",
          "the counter `refresh_suppressed_cpu` stays 0 and, once an hour of refreshes has run, the diagnostics' "
          "`cadence.cpu_s_rolling_hour` beside it is at most 120 s (T9's bound; the guard is 180 s)" in " ".join(r3.split())
          and "`cadence.refresh_suspended_cpu` is false" in r3 and "`CPU_BUDGET` WARN" in r3
          and "not inferred from STALE (A49)" in r3 and "both readings are recorded offline" in r3
          and "`cadence.cpu_s_rolling_hour` p95 at most 120 s per hour (the guard is 180 s) and `refresh_suppressed_cpu` 0"
              in t9 and "from the downloads' `cycle_stats` rows" in t9
          and "the sum of `cpu_s` over the runs that started in the hour before it" in t9
          and "`cadence.refresh_suspended_cpu` are recorded beside it" in t9 and "`CPU_BUDGET` WARN" in t9, r3 + t9)
    cpu22 = " ".join(section(rt_doc, "- **CPU guard:**", "- **In the executor:**").split())
    risk4 = " ".join(section(rt_doc, "4. **CPU on the target host.**", "5. **Restart latch.**").split())
    check("A49 (AUD-12): INTELLIGENCE_HA_RUNTIME's CPU guard (2.2) and risk 4 say the headroom is tracked explicitly from "
          "the diagnostics (cpu_s_rolling_hour, refresh_suspended_cpu, the counter, cycle_stats' cpu_s), in R3 and T9",
          "tracked explicitly, never inferred from STALE (A49)" in cpu22 and "`cadence.cpu_s_rolling_hour`" in cpu22
          and "every `cycle_stats` row carries its run's `cpu_s` and `started_at`" in cpu22
          and "row R3 and its 72 h row T9" in cpu22
          and "the runbook's R3 reads `cadence.cpu_s_rolling_hour` beside `refresh_suppressed_cpu`" in risk4
          and "T5, T9" in risk4 and "twice-daily" not in risk4, cpu22[:300])
    # A49 (P4): the entity-id collision and the deleted entity ids Home Assistant keeps
    _ci = sec7.find("**An entity-id collision (a `_2` suffix).**")
    coll = " ".join(sec7[_ci:].split()) if _ci >= 0 else ""
    sec11 = " ".join(section(doc, "## 11. ", "Every command ends with").split())
    intro_rt = " ".join(section(rt_doc, "The integration reads Home Assistant states", "Related:").split())
    api5 = " ".join(section(rt_doc, "Explicit entity ids follow HA's behaviour", "## 6. ").split())
    check("A49 (P4): section 7 says how to recover from an entity-id collision: Home Assistant keeps a deleted entry's ids "
          "and gives them back (so never delete and re-add), find what holds the contract id, rename the suffixed "
          "entities, reload (not restart), verify; the recorder's 'cannot migrate' warning expected; step 2 points to it",
          "record of deleted entities (by unique id)" in coll and "deleting and re-adding the entry brings the suffix "
          "back" in coll and "find what holds the contract id" in coll
          and "rename each suffixed entity of the integration back to its contract id" in coll
          and "reload the ECCO Intelligence entry (a reload, not a restart)" in coll
          and "Never disable one of the integration's own entities" in coll
          and "cannot migrate the suffixed id's history to the contract id" in coll
          and "never by deleting and re-adding the entry" in " ".join(sec7.split()), coll[:300])
    check("RR1-1: the recovery is split by what holds the contract id (an entity of the entity registry in its settings; "
          "a state with no unique id, which the UI can neither remove nor rename, by stopping what sets it and the next "
          "owner-approved restart or the REST API's delete-state call); freeing it is a separate owner decision recorded "
          "against the R4 baseline, not covered by the install's approval, and a no-go when declined; the id must be free "
          "before the rename; the ui package's 'output not recognised' notification is named as a symptom",
          "**a separate owner decision**, recorded offline against the R4 baseline" in coll
          and "the install's approval does not cover it" in coll and "under the install's approval" not in coll
          and "this is a no-go (section 10, then section 11)" in coll
          and "an entity of the entity registry (it has a unique id)" in coll
          and "a state with no unique id (set by an API call, or a YAML entity without `unique_id`): the UI can neither "
              "remove nor rename it" in coll
          and "the next owner-approved restart, or the owner removes it with the REST API's delete-state call" in coll
          and "The contract id must be free before step 2" in coll and '"output not recognised" notification' in coll,
          coll[:400])
    check("RUN-3: the recovery's lead-in no longer forbids a restart outright: the pause helper stays on, steps 2 to 4 need "
          "no restart, and freeing a holder without a unique id may need a separately approved restart (step 1)",
          "Recover with the pause helper still on. Steps 2 to 4 need no restart; freeing a holder that has no unique id "
          "may need a separately approved restart (step 1):" in coll
          and "Recover with the pause helper still on and no restart" not in coll, coll[:900])
    check("A49 (P4): section 11 and INTELLIGENCE_HA_RUNTIME (the introduction and section 5) say Home Assistant keeps the "
          "eleven entity ids of a deleted entry and gives them back on a re-add, with no 'to confirm under L3' left",
          "keeps their ids in the registry's record of deleted entities (by unique id)" in sec11
          and "adding the entry again later gives the same eleven ids back" in sec11 and "to confirm under L3" not in sec11
          and "keeps the eleven entity ids in the entity registry's record of deleted entities" in intro_rt
          and "to confirm under L3" not in intro_rt and "never delete and re-add" in api5
          and "check it under L3 too" not in rt_doc, sec11[:200])
    check("RR1-7: section 11, the runbook's collision paragraph and INTELLIGENCE_HA_RUNTIME (the introduction and section 5) "
          "say the ids come back only for as long as Home Assistant keeps the deleted-entity record (it purges orphaned "
          "records after a retention period)",
          "for as long as Home Assistant keeps that record (it purges orphaned deleted-entity records after a retention "
          "period" in sec11 and "for as long as it keeps that record (it purges orphaned records after a retention "
          "period)" in coll and "for as long as it keeps that record (it purges orphaned deleted-entity records after a "
          "retention period" in intro_rt and "for as long as it keeps their deleted-entity records (it purges orphaned "
          "ones after a retention period)" in api5, sec11[:300])
    sec3 = " ".join(section(doc, "## 3. ", "## 4. ").split())
    site_row = row(rt_doc, "`SITE_FILE`")
    check("RR1-5: the runbook's section 3 and INTELLIGENCE_HA_RUNTIME's SITE_FILE row say the site file is UTF-8 without a "
          "byte-order mark (Windows PowerShell 5.1 writes one) and that SITE_FILE names the mark",
          "Save it as UTF-8 **without a byte-order mark**" in sec3 and "Windows PowerShell 5.1" in sec3
          and "`SITE_FILE` names the mark" in sec3 and "UTF-8 JSON without a byte-order mark" in site_row
          and '"a UTF-8 byte-order mark"' in site_row, sec3[:200])
    _bom_block = next((b for b in section(doc, "## 3. ", "## 4. ").split("```powershell\n")[1:]
                       if "UTF8Encoding" in b), "")
    check("RUN-2: section 3 names the editor setting (UTF-8, not UTF-8 with BOM) and gives a cls-first Windows PowerShell "
          "5.1 block that writes a UTF-8 site file back without a mark (WriteAllText with UTF8Encoding $false, on the "
          "resolved path) and reads it with a strict decoder, so a legacy code-page file stops with an error instead of "
          "being rewritten (REV-T-3), before site-check reads it and its sha256 is recorded",
          'choose the encoding "UTF-8", not "UTF-8 with BOM"' in sec3
          and "writes a UTF-8 file back without a mark, its text kept as it is" in sec3
          and "a file saved in a legacy code page stops with an error and is left as it was" in sec3
          and _bom_block.startswith("cls\n") and "(Resolve-Path -LiteralPath $SITE).ProviderPath" in _bom_block
          and "$text = [System.IO.File]::ReadAllText($full, (New-Object System.Text.UTF8Encoding $false, $true))" in _bom_block
          and "[System.IO.File]::WriteAllText($full, $text, (New-Object System.Text.UTF8Encoding $false))" in _bom_block
          and "-Encoding" not in _bom_block
          and sec3.find("New-Object System.Text.UTF8Encoding $false") < sec3.find("site-check --site $SITE"),
          _bom_block[:300])
    diag22 = " ".join(section(rt_doc, "### 2.2 ", "### 2.3 ").split())
    check("A45 (RV9-3): INTELLIGENCE_HA_RUNTIME 2.2 says the diagnostics' signals list each PV forecast observation by its "
          "day and position only, never by the site file's source name, signals_withheld counting any other name, and "
          "that a test pins it",
          "each PV forecast observation by its day and position only" in diag22
          and "never by the site file's source name" in diag22 and "`signals_withheld` counts any other name" in diag22
          and "a distinctive source name never appears in the download" in diag22, diag22[-500:])

    print("== site-check (the owner's site file, offline; no id, record reference, source name or value printed)")
    gates, store, sd, q, tt = D._engine()
    EXAMPLE = REPO / "intelligence" / "profiles" / "site_profile.example.json"
    RUNTIME_DOC = REPO / "docs" / "intelligence" / "INTELLIGENCE_HA_RUNTIME.md"
    GATED = [i for i in sd.PUBLISHED_ITEMS if sd.ITEM_GATES[i]]
    WINDOW_ITEMS = ["overnight_demand", "charge_target", "export_event", "dump_to_grid", "predicted_morning_soc"]

    def site_file(name: str, profile: dict | None = None, raw: bytes | None = None) -> Path:
        p = base / name
        p.write_bytes(raw if raw is not None else (json.dumps(profile, indent=1, sort_keys=True) + "\n").encode("utf-8"))
        return p

    def check_site(path: Path) -> tuple[int, str, dict, str]:
        """(exit code, text output, the JSON report, all output text): the command line, both renderings."""
        rt, rj = run_tool("site-check", "--site", str(path)), run_tool("site-check", "--site", str(path), "--json")
        try:
            rep = json.loads(rj.stdout)
        except ValueError:
            rep = {}
        check(f"{path.name}: the text and the JSON run give the same exit code", rt.returncode == rj.returncode,
              f"{rt.returncode} {rj.returncode} {rt.stderr[-200:]}")
        return rt.returncode, rt.stdout, rep, rt.stdout + rt.stderr + rj.stdout + rj.stderr

    def leaves(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from leaves(v)
        elif isinstance(node, list):
            for v in node:
                yield from leaves(v)
        elif isinstance(node, str):
            yield node

    def site_strings(profile: dict) -> set[str]:
        """Every entity id (or placeholder id), record reference and forecast source name in a site profile: none may be
        printed. Entity ids are the string values shaped domain.object_id; source names are the keys of `forecasts` and
        of each `pv_forecast_sources` day."""
        out = {s for s in leaves(profile)
               if re.fullmatch(r"[a-z_]+\.[a-z0-9_<>]+", s) or s.startswith("REC-") or re.fullmatch(r"\S*<\S+>\S*", s)}
        out |= {k for k in profile.get("forecasts", {}) if not k.startswith("_")}
        for day in profile.get("shadow_runtime", {}).get("pv_forecast_sources", {}).values():
            out |= {k for k in day if not k.startswith("_")}
        return out

    def leaked(text: str, profile: dict) -> list[str]:
        return sorted(s for s in site_strings(profile) if s in text)

    def items_of(rep: dict) -> dict:
        return rep.get("items", {})

    def blocked_set(rep: dict) -> set[str]:
        return {i for i, r in items_of(rep).items() if r.get("readiness") == "BLOCKED"}

    # the example profile: every I-D OPEN, no entity map
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    rc, text, rep, every = check_site(EXAMPLE)
    check("site-check on the example profile exits 0 (the file loads: no FAIL, no INVALID decision)",
          rc == 0 and rep.get("result") == "OK" and "Result      : OK" in text, text[-300:])
    check("... every published item is BLOCKED (text and JSON)",
          set(items_of(rep)) == set(sd.PUBLISHED_ITEMS) and blocked_set(rep) == set(sd.PUBLISHED_ITEMS)
          and all(f"  {i:<22} BLOCKED" in text for i in sd.PUBLISHED_ITEMS), str(sorted(blocked_set(rep))))
    check("... every gated item names an OPEN decision it needs (DECISION_D<n>_OPEN), and pv_tomorrow its unmapped forecast",
          all(any(b == f"DECISION_{d}_OPEN" for b in items_of(rep)[i]["blockers"]) for i in GATED for d in sd.ITEM_GATES[i])
          and "NOT_MAPPED:pv.forecast_tomorrow_kwh" in items_of(rep)["pv_tomorrow"]["blockers"])
    check("... every decision reads OPEN; the entity map is absent (SITE_ENTITY_MAP WARN)",
          rep.get("decisions") == {f"I-D{n}": {"status": "OPEN"} for n in range(1, 10)}
          and any(c["code"] == "SITE_ENTITY_MAP" and c["level"] == "WARN" for c in rep.get("checks", [])))
    raw_ex = EXAMPLE.read_bytes()
    check("... sha256 and config_hash: the file's sha256, and the runtime's own config_hash (its first 16 hex digits)",
          rep.get("file", {}).get("sha256") == hashlib.sha256(raw_ex).hexdigest()
          and rep["file"]["config_hash"] == gates.load_site(raw_ex).config_hash == hashlib.sha256(raw_ex).hexdigest()[:16]
          and rep["file"]["sha256"] in text and f"config_hash : {rep['file']['config_hash']}" in text)
    check("... no id or placeholder from the file in the output", not leaked(every, example), str(leaked(every, example)[:3]))

    # a complete fictional site file (owner-record test decisions, the harness map less the v0.1-unmapped capacity source)
    full_readings = {k: v for k, v in H.READING_MAP.items() if k not in D.V01_UNMAPPED_READINGS}
    full = H.site_profile(decisions=H.owner_decisions(), readings=full_readings)
    rc, text, rep, every = check_site(site_file("site_full.json", full))
    check("a complete fictional site file exits 0 and the file blocks no item (LIVE_INPUTS_DECIDE: the check can pass)",
          rc == 0 and not blocked_set(rep) and len(items_of(rep)) == len(sd.PUBLISHED_ITEMS)
          and text.count("LIVE_INPUTS_DECIDE") == len(sd.PUBLISHED_ITEMS), text[-400:])
    check("... each decision shows its status, provenance and acceptance, never its value or record reference",
          rep["decisions"]["I-D1"] == {"status": "RECORDED", "provenance": "OWNER_RECORD", "accepted": "yes",
                                       "record_ref": "present", "basis": "INTELLIGENCE_USER_RESERVE"}
          and rep["decisions"]["I-D7"] == {"status": "OPEN"} and "REC-" not in every and "30.0" not in every)
    names = site_strings(full)
    check(f"... no entity id, record reference or forecast source name of the file in any output ({len(names)} checked)",
          len(names) > 60 and not leaked(every, full) and "test_dongle" not in every, str(leaked(every, full)[:3]))
    no_soc_signal = H.site_profile(decisions=H.owner_decisions(), readings=full_readings,
                                   signals={k: v for k, v in H.SIGNAL_MAP.items() if k != "battery.soc"})
    rc, text, rep, every = check_site(site_file("site_raw_soc_only.json", no_soc_signal))
    check("... battery.soc is satisfied by the raw SOC reading alone (the runtime prefers it): still nothing BLOCKED",
          rc == 0 and not blocked_set(rep), str(sorted(blocked_set(rep))))

    def variant(name: str, *, readings_drop: tuple = (), limits_drop: tuple = (), signals_drop: tuple = (),
                no_kwp: bool = False, placeholder_history: bool = False) -> dict:
        dec = H.owner_decisions()
        for k in limits_drop:
            dec["I-D6"]["value"]["limits_s"].pop(k)
        prof = H.site_profile(decisions=dec, readings={k: v for k, v in full_readings.items() if k not in readings_drop},
                              signals={k: v for k, v in H.SIGNAL_MAP.items() if k not in signals_drop})
        if no_kwp:
            prof["site"].pop("pv_array_kwp")
        if placeholder_history:
            for src in prof["sources"]:
                src["entities"] = {f: {"id": "sensor.<slug>_" + f} for f in src["entities"]}
            prof["forecasts"] = {}
        return check_site(site_file(name, prof))[2]

    rep = variant("site_no_overlay.json", readings_drop=("tou.overlay_state",))
    check("an unmapped overlay BLOCKs exactly the charge-window items and overnight_demand (NOT_MAPPED:tou.overlay_state)",
          blocked_set(rep) == set(WINDOW_ITEMS)
          and all(items_of(rep)[i]["blockers"] == ["NOT_MAPPED:tou.overlay_state"] for i in WINDOW_ITEMS),
          str({i: items_of(rep)[i]["blockers"] for i in sorted(blocked_set(rep))}))
    rep = variant("site_no_clock.json", readings_drop=("inverter.clock_offset_s",))
    check("an unmapped clock offset BLOCKs exactly the four charge-window items (overnight_demand needs no clock offset)",
          blocked_set(rep) == {"charge_target", "export_event", "dump_to_grid", "predicted_morning_soc"},
          str(sorted(blocked_set(rep))))
    rep = variant("site_no_supervision.json", readings_drop=("supervision.state",))
    check("an unmapped supervision state BLOCKs exactly export and Dump",
          blocked_set(rep) == {"export_event", "dump_to_grid"}
          and items_of(rep)["export_event"]["blockers"] == ["NOT_MAPPED:supervision.state"], str(sorted(blocked_set(rep))))
    rep = variant("site_no_events_limit.json", limits_drop=("tariff.events",))
    check("no I-D6 limit for tariff.events BLOCKs exactly export_event (NO_I_D6_LIMIT: a gate reading is never fresh "
          "without one) and lists it as mapped without a limit",
          blocked_set(rep) == {"export_event"} and items_of(rep)["export_event"]["blockers"] == ["NO_I_D6_LIMIT:tariff.events"]
          and rep["entity_map"]["mapped_without_i_d6_limit"] == ["tariff.events"], str(items_of(rep).get("export_event")))
    rep = variant("site_no_house_power.json", signals_drop=("house.power",))
    check("an unmapped house.power signal BLOCKs exactly export and Dump (NOT_MAPPED:house.power)",
          blocked_set(rep) == {"export_event", "dump_to_grid"}
          and items_of(rep)["dump_to_grid"]["blockers"] == ["NOT_MAPPED:house.power"], str(sorted(blocked_set(rep))))
    rep = variant("site_no_health_limit.json", limits_drop=("inverter.healthy",))
    check("no I-D6 limit for the inverter.healthy signal (UNRESOLVED by default) BLOCKs exactly export and Dump",
          blocked_set(rep) == {"export_event", "dump_to_grid"}
          and items_of(rep)["export_event"]["blockers"] == ["NO_I_D6_LIMIT:inverter.healthy"], str(sorted(blocked_set(rep))))
    rep = variant("site_no_kwp.json", no_kwp=True)
    check("no pv_array_kwp in the site block BLOCKs exactly pv_tomorrow (SITE_FACT_MISSING:pv_array_kwp)",
          blocked_set(rep) == {"pv_tomorrow"} and items_of(rep)["pv_tomorrow"]["blockers"] == ["SITE_FACT_MISSING:pv_array_kwp"],
          str(sorted(blocked_set(rep))))
    rep = variant("site_no_history.json", placeholder_history=True)
    check("history sources with placeholder ids only BLOCK every item that needs the history (NO_HISTORY_SOURCE)",
          blocked_set(rep) == set(sd.PUBLISHED_ITEMS)
          and all(items_of(rep)[i]["blockers"] == ["NO_HISTORY_SOURCE"] for i in sd.PUBLISHED_ITEMS)
          and any(c["code"] == "SITE_HISTORY_SOURCES" and c["level"] == "WARN" for c in rep["checks"]),
          str({i: items_of(rep)[i]["blockers"] for i in sorted(blocked_set(rep))}))

    # amendment A25: the learned and the register-204 capacity stay unmapped in v0.1
    with_reg204 = H.site_profile(decisions=H.owner_decisions())
    rc, text, rep, every = check_site(site_file("site_reg204.json", with_reg204))
    check("a site file mapping capacity.reg204_ah exits 1 (V01_CAPACITY_SOURCES_UNMAPPED FAIL, A25)",
          rc == 1 and rep.get("result") == "PROBLEMS"
          and rep["v01_rules"] == [{"rule": "V01_CAPACITY_SOURCES_UNMAPPED", "result": "FAIL",
                                    "text": "mapped, but stays unmapped in v0.1 (A25): capacity.reg204_ah"}]
          and "V01_CAPACITY_SOURCES_UNMAPPED FAIL" in rep.get("problems", []), str(rep.get("v01_rules")))
    check("... and still prints no id or reference", not leaked(every, with_reg204), str(leaked(every, with_reg204)[:3]))

    # an INVALID decision exits non-zero
    bad_ref = H.owner_decisions()
    bad_ref["I-D1"]["record_ref"] = "REC-20300101-x"                     # the slug is too short: I-D1 is INVALID
    prof = H.site_profile(decisions=bad_ref, readings=full_readings)
    rc, text, rep, every = check_site(site_file("site_invalid_ref.json", prof))
    check("an INVALID decision (an OWNER_RECORD with a malformed record_ref) exits 1 and reads INVALID",
          rc == 1 and rep["decisions"]["I-D1"]["status"] == "INVALID" and "I-D1 INVALID" in rep["problems"]
          and "I-D1  INVALID" in text, text[-300:])
    check("... every item I-D1 gates is BLOCKED DECISION_D1_INVALID; the malformed reference is not printed",
          {i for i in sd.PUBLISHED_ITEMS if "DECISION_D1_INVALID" in items_of(rep)[i]["blockers"]}
          == {i for i in sd.PUBLISHED_ITEMS if i in sd.items_gated_by("D1")} and "REC-20300101-x" not in every)
    bad_val = H.owner_decisions()
    bad_val["I-D1"]["value"]["value_pct"] = 140.0
    rc, _t, rep, _e = check_site(site_file("site_invalid_value.json", H.site_profile(decisions=bad_val, readings=full_readings)))
    check("an INVALID decision value (a reserve of 140 %) exits 1", rc == 1 and rep["decisions"]["I-D1"]["status"] == "INVALID")

    # a refused entity map and an oversized file: the runtime would publish SELF_TEST_FAILED
    placeholder = dict(full_readings, **{"limits.max_grid_charge_w": {"entity": "sensor.<slug>_grid_charge_limit"}})
    prof = H.site_profile(decisions=H.owner_decisions(), readings=placeholder)
    rc, text, rep, every = check_site(site_file("site_placeholder.json", prof))
    check("a placeholder left in the entity map exits 1 (SITE_ENTITY_MAP FAIL, by field path only) and every item is "
          "BLOCKED SELF_TEST_FAILED:SITE_ENTITY_MAP",
          rc == 1 and any(c["code"] == "SITE_ENTITY_MAP" and c["level"] == "FAIL"
                          and "shadow_runtime.readings.limits.max_grid_charge_w" in c["text"] for c in rep["checks"])
          and all("SELF_TEST_FAILED:SITE_ENTITY_MAP" in items_of(rep)[i]["blockers"] for i in sd.PUBLISHED_ITEMS)
          and "<slug>" not in every, text[-300:])
    # A33 (RT-3): the configuration poll's liveness entity or online entity copied from the telemetry poll text
    tel_text = full_readings[sd.LIVENESS_KEY]["entity"]
    for field, label in (("entity", "liveness entity"), ("online_entity", "online entity")):
        cfg_spec = dict(full_readings[sd.CONFIG_LIVENESS_KEY], **{field: tel_text})
        prof = H.site_profile(decisions=H.owner_decisions(), readings=dict(full_readings, **{sd.CONFIG_LIVENESS_KEY: cfg_spec}))
        rc, text, rep, every = check_site(site_file(f"site_same_poll_text_{field}.json", prof))
        path = f"shadow_runtime.readings.{sd.CONFIG_LIVENESS_KEY}" + (".online_entity" if field == "online_entity" else "")
        check(f"the configuration-poll {label} equal to the telemetry poll text exits 1 (SITE_ENTITY_MAP FAIL naming "
              "the field path only) and every item is BLOCKED SELF_TEST_FAILED:SITE_ENTITY_MAP (A33, RT-3)",
              rc == 1 and rep.get("result") == "PROBLEMS"
              and any(c["code"] == "SITE_ENTITY_MAP" and c["level"] == "FAIL" and f"{path}: the same entity as "
                      f"shadow_runtime.readings.{sd.LIVENESS_KEY}" in c["text"] for c in rep["checks"])
              and all("SELF_TEST_FAILED:SITE_ENTITY_MAP" in items_of(rep)[i]["blockers"] for i in sd.PUBLISHED_ITEMS)
              and tel_text not in every and not leaked(every, prof), text[-400:])
    # A36 (RR-3): one TOU enable mapped to the other's entity (either direction), or to the supervision stable flag's
    rp = "shadow_runtime.readings."
    for later, earlier in (("tou.grid_charge_enabled", "tou.enabled"), ("tou.enabled", "supervision.stable")):
        for copy_from, copy_to in ((earlier, later), (later, earlier)):
            shared = full_readings[copy_from]["entity"]
            prof = H.site_profile(decisions=H.owner_decisions(),
                                  readings=dict(full_readings, **{copy_to: {"entity": shared}}))
            rc, text, rep, every = check_site(site_file(f"site_same_gate_{copy_from}_to_{copy_to}.json", prof))
            check(f"{later} and {earlier} on one entity ({copy_from}'s entity also mapped to {copy_to}) exit 1 "
                  f"(SITE_ENTITY_MAP FAIL naming the field paths only: {later} against {earlier}) and every item is BLOCKED "
                  "SELF_TEST_FAILED:SITE_ENTITY_MAP (A36, RR-3)",
                  rc == 1 and rep.get("result") == "PROBLEMS"
                  and any(c["code"] == "SITE_ENTITY_MAP" and c["level"] == "FAIL"
                          and f"{rp}{later}: the same entity as {rp}{earlier}" in c["text"] for c in rep["checks"])
                  and all("SELF_TEST_FAILED:SITE_ENTITY_MAP" in items_of(rep)[i]["blockers"] for i in sd.PUBLISHED_ITEMS)
                  and shared not in every and not leaked(every, prof), text[-400:])

    def refused_by_map(name: str, prof: dict, prefix: str) -> tuple[bool, str]:
        """(exit 1 with SITE_ENTITY_MAP FAIL whose text holds `prefix`, every item BLOCKED SELF_TEST_FAILED:SITE_ENTITY_MAP
        and no id of the file in any output; the text output's tail)."""
        rc, text, rep, every = check_site(site_file(name, prof))
        return (rc == 1 and rep.get("result") == "PROBLEMS"
                and any(c["code"] == "SITE_ENTITY_MAP" and c["level"] == "FAIL" and prefix in c["text"] for c in rep["checks"])
                and all("SELF_TEST_FAILED:SITE_ENTITY_MAP" in items_of(rep)[i]["blockers"] for i in sd.PUBLISHED_ITEMS)
                and not leaked(every, prof)), text[-400:]

    # A39 (RT3-1 / RT3B-1): a boolean gate reading mapped to the configuration poll's online entity
    online = full_readings[sd.CONFIG_LIVENESS_KEY]["online_entity"]
    for gate in ("supervision.stable", "tou.enabled", "tou.grid_charge_enabled"):
        prof = H.site_profile(decisions=H.owner_decisions(), readings=dict(full_readings, **{gate: {"entity": online}}))
        ok_, tail = refused_by_map(f"site_online_is_{gate}.json", prof,
                                   f"{rp}{gate}: the same entity as {rp}{sd.CONFIG_LIVENESS_KEY}.online_entity")
        check(f"{gate} mapped to the configuration-online entity exits 1 (SITE_ENTITY_MAP FAIL naming the field paths only) "
              "and every item is BLOCKED SELF_TEST_FAILED:SITE_ENTITY_MAP (A39, RT3-1 / RT3B-1)", ok_, tail)
    # A39 (RT3B-2): the raw SOC reading on the canonical SOC signal's entity
    canon = H.SIGNAL_MAP["battery.soc"]["entity"]
    prof = H.site_profile(decisions=H.owner_decisions(), readings=dict(full_readings, **{"battery.soc_raw_pct": {"entity": canon}}))
    ok_, tail = refused_by_map("site_raw_soc_is_canonical.json", prof,
                               f"{rp}battery.soc_raw_pct: the same entity as shadow_runtime.signals.battery.soc")
    check("battery.soc_raw_pct mapped to the battery.soc signal's entity exits 1 (SITE_ENTITY_MAP FAIL, field paths only) "
          "and every item is BLOCKED SELF_TEST_FAILED:SITE_ENTITY_MAP (A39, RT3B-2)", ok_, tail)
    # A38 Part B (CCR-RT-DAYS): the import rates from the day events; A42: the recommended form is [current, next]
    day_events = [{"entity": f"event.test_{d}_day_rates", "attribute": "rates"} for d in ("previous", "current", "next")]
    n_single = len(gates.load_site(json.dumps(full).encode("utf-8")).entity_map.entity_ids())
    prof = H.site_profile(decisions=H.owner_decisions(),
                          readings=dict(full_readings, **{"tariff.import_rates": day_events[1:]}))
    rc, text, rep, every = check_site(site_file("site_two_day_events.json", prof))
    check("a complete fictional file mapping tariff.import_rates to the two day events [current, next] (the production "
          "form, A42) exits 0, the file blocks no item, the two events count as mapped entities (one more than the single "
          "event) and no id is printed",
          rc == 0 and not blocked_set(rep) and rep["entity_map"]["entities"] == n_single + 1 and not leaked(every, prof),
          text[-400:])
    prof = H.site_profile(decisions=H.owner_decisions(), readings=dict(full_readings, **{"tariff.import_rates": day_events}))
    rc, text, rep, every = check_site(site_file("site_three_day_events.json", prof))
    check("a complete fictional file mapping tariff.import_rates to the three day events exits 0, the file blocks no item, "
          "the three events count as mapped entities (two more than the single event) and no id is printed (A38 Part B)",
          rc == 0 and not blocked_set(rep) and rep["entity_map"]["entities"] == n_single + 2 and not leaked(every, prof),
          text[-400:])
    for name, spec, prefix in (
            ("site_day_event_twice.json", [day_events[0], day_events[1], dict(day_events[0])],
             f"{rp}tariff.import_rates[3]: the same entity as {rp}tariff.import_rates[1]"),
            ("site_four_day_events.json", day_events + [{"entity": "event.test_fourth_day_rates", "attribute": "rates"}],
             f"{rp}tariff.import_rates must be one"),
            ("site_events_as_days.json", None, f"{rp}tariff.events: only a rate table")):
        readings = (dict(full_readings, **{"tariff.import_rates": spec}) if spec is not None else
                    dict(full_readings, **{"tariff.events": day_events[:2]}))
        prof = H.site_profile(decisions=H.owner_decisions(), readings=readings)
        ok_, tail = refused_by_map(name, prof, prefix)
        check(f"{name} exits 1 (SITE_ENTITY_MAP FAIL by field path only) and every item is BLOCKED "
              "SELF_TEST_FAILED:SITE_ENTITY_MAP (A38 Part B)", ok_, tail)
    # A42 (RT4-2): one rate event (entity and attribute) under two tariff tables, a day event of a list included
    two_days = day_events[1:]
    exp_own = {"entity": "event.test_export_current_day_rates", "attribute": "rates"}
    for name, changes, prefix in (
            ("site_export_is_import_day.json", {"tariff.import_rates": two_days, "tariff.export_rates": dict(two_days[0])},
             f"{rp}tariff.export_rates: the same entity and attribute as {rp}tariff.import_rates[1]"),
            ("site_export_list_with_import_day.json",
             {"tariff.import_rates": two_days, "tariff.export_rates": [exp_own, dict(two_days[1])]},
             f"{rp}tariff.export_rates[2]: the same entity and attribute as {rp}tariff.import_rates[2]"),
            ("site_events_is_import_day.json", {"tariff.import_rates": two_days, "tariff.events": dict(two_days[0])},
             f"{rp}tariff.events: the same entity and attribute as {rp}tariff.import_rates[1]"),
            ("site_export_is_import_single.json", {"tariff.export_rates": dict(full_readings["tariff.import_rates"])},
             f"{rp}tariff.export_rates: the same entity and attribute as {rp}tariff.import_rates")):
        prof = H.site_profile(decisions=H.owner_decisions(), readings=dict(full_readings, **changes))
        ok_, tail = refused_by_map(name, prof, prefix)
        check(f"{name}: one rate event under two tariff tables exits 1 (SITE_ENTITY_MAP FAIL by field path only, no id) "
              "and every item is BLOCKED SELF_TEST_FAILED:SITE_ENTITY_MAP (A42, RT4-2)", ok_, tail)
    shared = full_readings["tariff.import_rates"]["entity"]
    prof = H.site_profile(decisions=H.owner_decisions(), readings=dict(full_readings, **{
        "tariff.import_rates": {"entity": shared, "attribute": "import_rates"},
        "tariff.export_rates": {"entity": shared, "attribute": "export_rates"}}))
    rc, text, rep, every = check_site(site_file("site_one_entity_two_attributes.json", prof))
    check("... one entity holding the import and export rates under separate attributes exits 0 and blocks no item (the "
          "entity and attribute pair differs)", rc == 0 and not blocked_set(rep) and not leaked(every, prof), text[-400:])
    big = site_file("site_big.json", raw=b'{"_pad": "' + b"x" * (store.MAX_SITE_FILE_BYTES + 10) + b'"}')
    rc, text, rep, every = check_site(big)
    check("a file over the runtime's 256 KiB cap exits 1 (SITE_FILE FAIL) and every item is BLOCKED",
          rc == 1 and any(c["code"] == "SITE_FILE" and c["level"] == "FAIL" for c in rep["checks"])
          and blocked_set(rep) == set(sd.PUBLISHED_ITEMS))
    r = run_tool("site-check", "--site", str(base / "absent.json"))
    check("a site path that is not a file is refused (exit 1)", r.returncode == 1 and "REFUSED" in r.stderr, r.stderr[-200:])
    r = run_tool("site-check", "--site", "ecco-ha:/config/ecco/intelligence/site.local.json")
    check("a site path naming the live host alias is refused as such",
          r.returncode != 0 and "REFUSED" in r.stderr and "names the live host alias" in r.stderr, r.stderr[-200:])
    refused_dec = H.site_profile(decisions=dict(H.owner_decisions(), **{"I-D10": {"status": "OPEN"}}), readings=full_readings)
    rc, text, rep, every = check_site(site_file("site_refused_decisions.json", refused_dec))
    check("a decisions block the loader refuses (an unknown key) exits 1, reads REFUSED (never as OPEN decisions) and "
          "every item is BLOCKED SELF_TEST_FAILED:SITE_DECISIONS",
          rc == 1 and rep.get("decisions") == "REFUSED" and "REFUSED: the decisions block does not load" in text
          and all("SELF_TEST_FAILED:SITE_DECISIONS" in items_of(rep)[i]["blockers"] for i in sd.PUBLISHED_ITEMS)
          and "I-D10" not in every, text[-300:])

    # INTELLIGENCE_HA_RUNTIME.md section 4.1: the example loads as written and maps every input a published item needs
    sec4 = RUNTIME_DOC.read_text(encoding="utf-8")
    sec4 = sec4[sec4.index("## 4. "):sec4.index("## 5. ")]
    m_ = re.search(r"```json\n(.*?)\n```", sec4, re.S)
    doc_raw = (m_.group(1) + "\n").encode("utf-8") if m_ else b"{}"
    doc_prof = json.loads(doc_raw)
    rc, text, rep, every = check_site(site_file("runtime_doc_example.json", raw=doc_raw))
    check("RUNTIME section 4.1's example passes site-check (exit 0, SITE_ENTITY_MAP and SITE_HISTORY_SOURCES PASS, the A25 rule)",
          rc == 0 and all(c["level"] == "PASS" for c in rep["checks"] if c["code"] in ("SITE_ENTITY_MAP", "SITE_HISTORY_SOURCES"))
          and {"SITE_ENTITY_MAP", "SITE_HISTORY_SOURCES"} <= {c["code"] for c in rep["checks"]}, text[-400:])
    doc_blockers = {b for r_ in items_of(rep).values() for b in r_["blockers"]}
    check("... with every decision OPEN its items are blocked only by decisions and missing I-D6 limits (nothing a "
          "published item needs is unmapped)",
          doc_blockers and all(b.startswith(("DECISION_D", "NO_I_D6_LIMIT:")) for b in doc_blockers), str(sorted(doc_blockers)))
    doc_load = gates.load_site(doc_raw)
    doc_ids = list(doc_load.entity_map.entity_ids()) + list(doc_load.plan.statistic_ids)
    check("... it uses fictional example ids only, maps the v2 shapes (six six-entity slots, config liveness with "
          "online_entity, both enables, the overlay entities) and no capacity source v0.1 leaves unmapped",
          doc_ids and all(".example_" in e for e in doc_ids)
          and len(doc_load.entity_map.readings["tou.slot_table"]["slots"]) == 6
          and "online_entity" in doc_load.entity_map.readings[sd.CONFIG_LIVENESS_KEY]
          and {"tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state"} <= set(doc_load.entity_map.readings)
          and not set(D.V01_UNMAPPED_READINGS) & set(doc_load.entity_map.readings), str(doc_ids[:3]))
    doc_parts = doc_load.entity_map.readings.get("tariff.import_rates", {}).get("parts", ())
    check("... it maps tariff.import_rates in the recommended form (A42: the current-day and next-day events, in that "
          "order) and keeps the single form as an example (the export rates)",
          [p["entity"].split(".", 1)[1] for p in doc_parts] == ["example_current_day_rates", "example_next_day_rates"]
          and "entity" in doc_load.entity_map.readings.get("tariff.export_rates", {}), str(doc_parts))
    doc_full = dict(doc_prof, decisions=H.owner_decisions())
    rc, text, rep, every = check_site(site_file("runtime_doc_example_recorded.json", doc_full))
    check("... with the test owner-record decisions (I-D6 limits for every key) the file blocks no item",
          rc == 0 and not blocked_set(rep), str({i: items_of(rep)[i]["blockers"] for i in sorted(blocked_set(rep))}))

    print("== no ssh / scp / subprocess / network use (AST)")
    BAD_MODS = ("subprocess", "socket", "urllib", "http", "ftplib", "smtplib", "telnetlib", "paramiko", "asyncio", "ssl",
                "multiprocessing", "ctypes", "requests", "aiohttp", "webbrowser", "pty")
    for tool in (TOOL, REPO / "tools" / "build_ha_integration.py"):
        tree = ast.parse(tool.read_text(encoding="utf-8"))
        bad = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                bad += [a.name for a in n.names if a.name.split(".")[0] in BAD_MODS]
            elif isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in BAD_MODS:
                bad.append(n.module)
            elif isinstance(n, ast.Call):
                fn = n.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if name in ("system", "popen", "Popen", "run", "call", "check_output", "spawnl", "spawnv", "execv", "execl",
                            "startfile", "__import__", "exec", "eval"):
                    bad.append(f"call {name}()")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip().split(" ")[0] in ("ssh", "scp", "sftp"):
                bad.append(f"string {n.value[:20]!r}")
        check(f"{tool.name}: no process, network, ssh or scp use", not bad, str(bad[:5]))
finally:
    H.rmtree_own(base, PREFIX)


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in install drill:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all install drill checks passed")
