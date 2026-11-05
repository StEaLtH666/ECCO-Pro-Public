#!/usr/bin/env python3
"""tools/build_ha_integration.py, the kit builder (frozen command line: --out <abs-dir> [--git-sha S]).

  * two builds of one tree are byte-identical (every file, SHA256SUMS included);
  * VENDOR_MANIFEST.json: every vendored module's source sha256 (LF) matches the repository file, every output sha256 matches
    the kit file; the integration files likewise; the git sha is recorded only when given; the in-package copy is identical;
  * the vendored set is exactly the AST import closure (module AND function level) of intelligence.shadow_cycle,
    intelligence.scorecard, intelligence.history and ecco_core.bridge plus the package __init__ files (recomputed here
    independently);
  * no absolute intelligence / ecco_core import remains at any depth, in _vendor or in the integration files (AST);
    ecco_core/bridge.py's function-level import is rewritten; apart from imports every vendored module is unchanged (AST);
  * from the built tree, in a fresh -I interpreter with ONLY the build directory on sys.path, ecco_core.bridge
    .advisory_live_inputs and shadow_cycle.run_cycle execute on the shared fixture snapshot, and give exactly what the
    repository's own modules give;
  * exclusions: no tests, README, cache, compiled file, ecco_autonomy, ecco_core/authority.py or capability.py, tools,
    prototypes or profiles; no builtin exec / eval / compile call in _vendor;
  * refusals: --out inside the repository (nothing created), an existing non-empty --out, a relative --out, a bad --git-sha;
  * nothing generated is tracked by git or present in the source tree.
Plain script; exits 1 on any failure. Temporary directories are created and removed by this suite.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
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


PREFIX = "ecco_intel_build_"
PKG_REL = "custom_components/ecco_intelligence"
ROOTS = ("intelligence.shadow_cycle", "intelligence.scorecard", "intelligence.history", "ecco_core.bridge")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def lf(p: Path) -> bytes:
    return p.read_bytes().replace(b"\r\n", b"\n")


def closure() -> set[str]:
    """An independent AST closure: every intelligence / ecco_core module imported at any depth, plus parent packages."""
    def mfile(mod: str) -> Path | None:
        p = REPO.joinpath(*mod.split("."))
        return p / "__init__.py" if (p / "__init__.py").is_file() else (p.with_suffix(".py") if p.with_suffix(".py").is_file() else None)
    seen: set[str] = set()
    todo = list(ROOTS)
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        f = mfile(m)
        seen.add(m)
        parts = m.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]
        pkg = m if f.name == "__init__.py" else m.rpartition(".")[0]
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            targets = []
            if isinstance(n, ast.Import):
                targets = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    pp = pkg.split(".")
                    base = ".".join(pp[: len(pp) - n.level + 1] + ([n.module] if n.module else []))
                targets = [base] + [f"{base}.{a.name}" for a in n.names]
            for t in targets:
                if t.split(".")[0] in ("intelligence", "ecco_core") and mfile(t) is not None:
                    todo.append(t)
    return seen


def strip_imports(tree: ast.AST) -> str:
    class S(ast.NodeTransformer):
        def visit_Import(self, node):
            return ast.Pass()

        def visit_ImportFrom(self, node):
            return ast.Pass()
    return ast.dump(S().visit(tree), include_attributes=False)


root = H.mktemp(PREFIX)
try:
    a, b, c = root / "a", root / "b", root / "c"
    ra, rb = H.build_kit(a), H.build_kit(b)
    rc = H.build_kit(c, git_sha=None)
    check("the frozen command line exits 0 (three builds)", ra.returncode == rb.returncode == rc.returncode == 0,
          (ra.stderr + rb.stderr + rc.stderr)[-400:])
    check("the build says the kit is staged, PENDING DP-4", "PENDING DP-4" in ra.stdout and "deployed" not in ra.stdout.replace(
        "nothing is installed or deployed", ""))
    ta, tb = H.tree_hashes(a), H.tree_hashes(b)
    check(f"two builds are byte-identical ({len(ta)} entries)", ta == tb and len(ta) > 30)
    tc = H.tree_hashes(c)
    diff_c = sorted(k for k in set(ta) | set(tc) if ta.get(k) != tc.get(k))
    check("without --git-sha only the manifests (and their sums) differ", set(diff_c) <= {
        "VENDOR_MANIFEST.json", f"{PKG_REL}/VENDOR_MANIFEST.json", "SHA256SUMS"}, str(diff_c))

    pkg = a / "custom_components" / "ecco_intelligence"
    man = json.loads((a / "VENDOR_MANIFEST.json").read_text(encoding="utf-8"))
    print("== the manifest")
    check("the in-package manifest copy is identical", (pkg / "VENDOR_MANIFEST.json").read_bytes() == (a / "VENDOR_MANIFEST.json").read_bytes())
    check("schema, package, roots and git sha recorded", man["schema"] == "ecco-intel-vendor-manifest/1" and man["package"] == PKG_REL
          and tuple(man["roots"]) == ROOTS and man["git_sha"] == "0000000"
          and json.loads((c / "VENDOR_MANIFEST.json").read_text(encoding="utf-8"))["git_sha"] is None)
    bad_src = [m["source"] for m in man["modules"] if sha(lf(REPO / m["source"])) != m["source_sha256_lf"]]
    bad_out = [m["output"] for m in man["modules"] if sha((pkg / m["output"]).read_bytes()) != m["output_sha256"]]
    check(f"every vendored module's source sha256 matches the repository ({len(man['modules'])})", not bad_src, str(bad_src[:3]))
    check("every vendored module's output sha256 matches the kit", not bad_out, str(bad_out[:3]))
    bad_int = [f["path"] for f in man["integration_files"] if sha((pkg / f["path"]).read_bytes()) != f["output_sha256"]
               or (f["source_sha256_lf"] is not None and sha(lf(REPO / PKG_REL / f["path"])) != f["source_sha256_lf"])]
    check(f"every integration file's hashes match ({len(man['integration_files'])})", not bad_int, str(bad_int[:3]))
    sums = {}
    for line in (a / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        d, _s, rel = line.partition("  ")
        sums[rel] = d
    files = {k for k in ta if not k.endswith("/") and k != "SHA256SUMS"}
    check("SHA256SUMS lists every file and every listed hash verifies", set(sums) == files
          and all(sha((a / r).read_bytes()) == d for r, d in sums.items()))
    check("SHA256SUMS is sorted and LF-only", list(sums) == sorted(sums) and b"\r" not in (a / "SHA256SUMS").read_bytes())

    print("== the vendor closure")
    want = closure()
    got = {m["module"] for m in man["modules"]}
    check(f"the vendored set is exactly the AST import closure of the four roots ({len(want)} modules)", got == want,
          f"extra {sorted(got - want)} missing {sorted(want - got)}")
    check("the closure reaches the function-level import of ecco_core.bridge (intelligence.inputs)", "intelligence.inputs" in got)
    vend = sorted((pkg / "_vendor").rglob("*.py"))
    absolute, depth = [], []
    for p in vend:
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").split(".")[0] in ("intelligence", "ecco_core"):
                absolute.append(f"{p.name}:{n.lineno}")
            if isinstance(n, ast.Import) and any(x.name.split(".")[0] in ("intelligence", "ecco_core") for x in n.names):
                absolute.append(f"{p.name}:{n.lineno}")
    check(f"no absolute intelligence / ecco_core import at any depth in _vendor ({len(vend)} files)", not absolute, str(absolute[:3]))
    bridge = (pkg / "_vendor" / "ecco_core" / "bridge.py").read_text(encoding="utf-8")
    check("bridge.py's function-level import is rewritten to the package's copy",
          "    from ..intelligence.inputs import live_inputs_from_snapshot" in bridge and "from intelligence." not in bridge)
    changed = []
    for m in man["modules"]:
        src = ast.parse((REPO / m["source"]).read_text(encoding="utf-8"))
        out = ast.parse((pkg / m["output"]).read_text(encoding="utf-8"))
        if strip_imports(src) != strip_imports(out):
            changed.append(m["source"])
    check("apart from import statements every vendored module is unchanged (AST)", not changed, str(changed[:3]))
    integ_abs = []
    for p in sorted(pkg.rglob("*.py")):
        rel = p.relative_to(pkg).as_posix()
        if rel.startswith("_vendor/"):
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").split(".")[0] in ("intelligence", "ecco_core",
                                                                                                     "ecco_autonomy"):
                integ_abs.append(f"{rel}:{n.lineno}")
    check("the integration files import the engine only through _vendor (relative)", not integ_abs, str(integ_abs[:3]))
    calls = [f"{p.name}:{n.lineno}" for p in vend for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("exec", "eval", "compile", "__import__")]
    check("no builtin exec / eval / compile / __import__ call in _vendor", not calls, str(calls))
    re_compile = sorted({p.relative_to(pkg / "_vendor").as_posix() for p in vend for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "compile"})
    print(f"  INFO  attribute calls named 'compile' in _vendor (re.compile; see CCR-1): {re_compile}")

    print("== exclusions")
    rels = {k for k in ta if not k.endswith("/")}
    bad = sorted(r for r in rels if "/tests/" in r or r.endswith(("README.md", ".pyc")) or "__pycache__" in r
                 or "/ecco_autonomy/" in r or r.endswith(("ecco_core/authority.py", "ecco_core/capability.py"))
                 or any(f"/{x}/" in r for x in ("tools", "prototypes", "profiles")))
    check("no tests, README, cache, ecco_autonomy, authority / capability, tools, prototypes or profiles in the kit", not bad, str(bad[:3]))
    src_files = sorted(p.relative_to(REPO / PKG_REL).as_posix() for p in (REPO / PKG_REL).rglob("*")
                       if p.is_file() and p.relative_to(REPO / PKG_REL).parts[0] not in ("tests",) and p.name != "README.md"
                       and "__pycache__" not in p.parts and p.suffix != ".pyc")
    kit_int = sorted(f["path"] for f in man["integration_files"] if not f["path"].startswith("_vendor/"))
    check("the kit carries exactly the integration sources (minus tests / README)", kit_int == src_files,
          f"{sorted(set(kit_int) ^ set(src_files))}")
    check("no hacs.json, services.yaml or services.py in the kit", not any(r.endswith(("hacs.json", "services.yaml", "services.py"))
                                                                          for r in rels))

    print("== the built tree runs on its own (fresh -I interpreter, only the build directory on sys.path)")
    FIXTURE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(1, sys.argv[2])
import _cycle_fixtures as F
ci = F.cycle_inputs()
snap = ci.snapshot.to_dict()
reads = [{"key": r.key, "value": (r.value.isoformat() if hasattr(r.value, "isoformat") else r.value), "unit": r.unit,
          "observed_at": r.observed_at.isoformat(), "source": r.source} for r in ci.site_readings]
from intelligence.shadow_cycle import run_cycle
from intelligence.advisory_contract import CycleInputs
from ecco_core.bridge import advisory_live_inputs
live, ass = advisory_live_inputs(ci.snapshot)
env = run_cycle(CycleInputs(now=ci.now, snapshot=ci.snapshot, live=live, caller_assessments=tuple((a.signal, a.fresh, a.age_s) for a in ass),
                            site_facts=ci.site_facts, decisions=ci.decisions, site_readings=ci.site_readings, base_cfg=ci.base_cfg,
                            paused=False, versions=ci.versions))
print(json.dumps({"now": ci.now.isoformat(), "snapshot": snap, "readings": reads, "env": env.to_dict(),
                  "live_soc": live.soc_pct}))
'''
    KIT = r'''
import json, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
d = json.loads(sys.stdin.read())
P = "custom_components.ecco_intelligence._vendor."
from custom_components.ecco_intelligence._vendor.ecco_core import bridge, state
from custom_components.ecco_intelligence._vendor.intelligence import advisory_contract as ac, shadow_cycle
from custom_components.ecco_intelligence._vendor.intelligence.config import SiteConfig
now = datetime.fromisoformat(d["now"])
obs = [state.Observation(o["signal"], o["value"], None if o["observed_at"] is None else datetime.fromisoformat(o["observed_at"]),
                         o["source"], o["kind"], o["unit"], o["raw"], tuple(o["derived_from"]), tuple(o["quality"]))
       for o in d["snapshot"]["observations"]]
snap = state.Snapshot.of(now, obs)
reads = tuple(ac.SiteReading(r["key"], datetime.fromisoformat(r["value"]) if r["key"] in ("liveness.dongle_poll_changed_at", "liveness.config_poll_changed_at") else r["value"],
                             r["unit"], datetime.fromisoformat(r["observed_at"]), r["source"]) for r in d["readings"])
live, ass = bridge.advisory_live_inputs(snap)
facts = ac.SiteFacts(pv_array_kwp=6.0, latitude=51.5, longitude=-0.1, tz="Europe/London")
env = shadow_cycle.run_cycle(ac.CycleInputs(now=now, snapshot=snap, live=live, caller_assessments=tuple((a.signal, a.fresh, a.age_s) for a in ass),
                                            site_facts=facts, site_readings=reads, base_cfg=SiteConfig(latitude=51.5, longitude=-0.1, tz="Europe/London", pv_array_kwp=6.0),
                                            paused=False, versions=ac.Versions("0.1.0-fixture", "intel-v1.1.0-foundation-shadow", "0000000", None)))
top = sorted(k for k in sys.modules if k.split(".")[0] in ("intelligence", "ecco_core", "homeassistant"))
print(json.dumps({"env": env.to_dict(), "live_soc": live.soc_pct, "top": top, "bridge_file": bridge.__file__}))
'''
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    pf = subprocess.run([sys.executable, "-I", "-B", "-c", FIXTURE, str(REPO), str(REPO / "intelligence" / "tests")],
                        capture_output=True, text=True, timeout=300, cwd=str(REPO), env=env)
    check("the repository's own run on the fixture snapshot", pf.returncode == 0, pf.stderr[-400:])
    src_doc = json.loads(pf.stdout.strip().splitlines()[-1]) if pf.returncode == 0 else {}
    pk = subprocess.run([sys.executable, "-I", "-B", "-c", KIT, str(a)], input=json.dumps(src_doc), capture_output=True, text=True,
                        timeout=300, cwd=str(root), env=env)
    check("advisory_live_inputs and run_cycle execute from the built tree", pk.returncode == 0, pk.stderr[-400:])
    kit_doc = json.loads(pk.stdout.strip().splitlines()[-1]) if pk.returncode == 0 else {}
    check("the built tree gives exactly the repository's envelope on the fixture snapshot",
          kit_doc.get("env") == src_doc.get("env") and kit_doc.get("live_soc") == src_doc.get("live_soc") == 55.0,
          str((kit_doc.get("env") or {}).get("status")) + " vs " + str((src_doc.get("env") or {}).get("status")))
    check("... with no top-level intelligence / ecco_core / homeassistant module loaded", kit_doc.get("top") == [], str(kit_doc.get("top")))
    check("... and the bridge loaded from inside the kit", str(a) in str(kit_doc.get("bridge_file", "")).replace("/", os.sep)
          or Path(kit_doc.get("bridge_file", "/")).resolve().is_relative_to(a.resolve()))

    print("== refusals")
    inside = REPO / "custom_components" / f"_build_refusal_{os.getpid()}"
    r_in = subprocess.run([sys.executable, "-I", "-B", str(H.BUILD_TOOL), "--out", str(inside)], capture_output=True, text=True,
                          timeout=120, cwd=str(REPO), env=env)
    check("an --out inside the repository is refused and nothing is created", r_in.returncode != 0 and not inside.exists())
    r_ex = H.build_kit(a)
    check("an existing non-empty --out is refused (nothing is overwritten or deleted)", r_ex.returncode != 0
          and H.tree_hashes(a) == ta)
    r_rel = subprocess.run([sys.executable, "-I", "-B", str(H.BUILD_TOOL), "--out", "relative_dir"], capture_output=True, text=True,
                           timeout=120, cwd=str(root), env=env)
    check("a relative --out is refused", r_rel.returncode != 0 and not (root / "relative_dir").exists())
    r_sha = H.build_kit(root / "d", git_sha="NOT-A-SHA")
    check("a malformed --git-sha is refused", r_sha.returncode != 0 and not (root / "d").exists())
    empty = root / "empty"
    empty.mkdir()
    check("an existing EMPTY --out is accepted", H.build_kit(empty).returncode == 0 and (empty / "SHA256SUMS").is_file())

    print("== nothing generated in the repository")
    tracked = subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "ls-files", "--", "custom_components"],
                             capture_output=True, text=True, timeout=60, cwd=str(REPO))
    if tracked.returncode == 0:
        check("no _vendor / VENDOR_MANIFEST / SHA256SUMS is tracked", not any(
            x in tracked.stdout for x in ("_vendor", "VENDOR_MANIFEST", "SHA256SUMS")))
    else:                                       # not a git checkout (a scratch copy): judge the files themselves
        check("no _vendor / VENDOR_MANIFEST / SHA256SUMS under custom_components/ (no git here)", not any(
            p.name in ("_vendor", "VENDOR_MANIFEST.json", "SHA256SUMS") for p in (REPO / "custom_components").rglob("*")))
    check("no _vendor / VENDOR_MANIFEST.json in the source tree", not (REPO / PKG_REL / "_vendor").exists()
          and not (REPO / PKG_REL / "VENDOR_MANIFEST.json").exists())
finally:
    H.rmtree_own(root, PREFIX)


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime build:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime build checks passed")
