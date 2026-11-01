#!/usr/bin/env python3
"""Repeat the B1 audit-hook trace of the assurance lab's repository inputs and diff it against the tier table
(_lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL / TIER_SOURCES). A command-line maintenance tool, not a suite: it is not named
test_*.py, so neither tools/run_offline_tests.py nor the exit-code meta-check collects it. The tool itself uses the
standard library only (the suites and replays it starts need the CI packages, as always). Offline; it writes nothing
inside the repository: the hook module and its logs live in a temporary directory outside it, removed at the end.

    python -B registry/tests/assurance_lab/trace_inputs.py                 # every suite (quick) and every replay
    python -B registry/tests/assurance_lab/trace_inputs.py --extended      # ... and every suite in extended mode too
    python -B registry/tests/assurance_lab/trace_inputs.py --parallel 2    # processes at once (default 4)

METHOD (_lab_trace.TIER_METHOD)
  A generated sitecustomize module on PYTHONPATH (inherited by the suites' own child processes) installs
  sys.addaudithook and logs every 'open' of a file under the repository root: the path, read or write, whether the
  import machinery (a '<frozen importlib' frame) is on the stack, and the four innermost in-repository frames (file,
  function). Every lab suite runs from the repository root as 'python -B <file>' with PYTHONDONTWRITEBYTECODE=1 (CI
  runs 'python <file>'; the two switches only keep the trace from writing bytecode) in quick mode (ECCO_LAB_EXTENDED
  unset) and, with --extended, in extended mode too; every corpus document is replayed alone in its own process (this
  tool with --replay-one <id>) with only its tier module imported. Logged paths are case-folded on Windows and mapped
  back to the repository's own spelling. A read is classified by its innermost in-repository frames (HELPERS): an
  anchor read (_lab_trace.read_source_text under anchor_count; a TreeReader read under text under
  gen_catalogue.anchor_str; test_lab_replay_corpus.repo_text under anchor_hits or anchors_not_once), a digest read
  (_lab_trace.source_digest; TreeReader.read_bytes under sha; run_lab.lf_digest), the replay suite's in-memory overlay
  copy (comment_overlay) or an existence read (repo_text under cited) is non-behavioural; any other read, and any read
  with the import machinery on the stack, is behavioural.

CHECKS (each difference prints one 'MISMATCH' line; exit 1 when there is any)
  - every traced process exited 0 and the hook logged no error (otherwise the trace is incomplete), and nothing was
    opened for writing inside the repository;
  - every non-lab file read is in the table; a file with a behavioural read is in BEHAVIOURAL; a file with only
    non-behavioural reads is in NON_BEHAVIOURAL, its pinned flag False exactly when its only reads are existence reads;
  - every table entry was read by the traced runs (no stale entry);
  - each corpus document's behavioural reads equal its tier's TIER_SOURCES.

EXIT  0 the trace equals the table; 1 a mismatch; 2 usage error.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # before any lab helper is imported

import argparse  # noqa: E402
import concurrent.futures as cf  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # repository root
LAB_REL = "registry/tests/assurance_lab"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _lab_trace as T  # noqa: E402   (standard library only)

TIER_MODULES = {"firmware": "_lab_fw", "coupled": "_lab_ha", "rtc": "_lab_rtc"}
BEHAVIOURAL_KINDS = {"import", "data"}
# (innermost in-repository frames as (file name, function), ...) -> the kind of a read through that lab helper
HELPERS = (
    ((("_lab_trace.py", "read_source_text"), ("_lab_trace.py", "anchor_count")), "anchor"),
    ((("_lab_trace.py", "read_bytes"), ("_lab_trace.py", "text"), ("gen_catalogue.py", "anchor_str")), "anchor"),
    ((("test_lab_replay_corpus.py", "repo_text"), ("test_lab_replay_corpus.py", "anchor_hits")), "anchor"),
    ((("test_lab_replay_corpus.py", "repo_text"), ("test_lab_replay_corpus.py", "anchors_not_once")), "anchor"),
    ((("_lab_trace.py", "source_digest"),), "digest"),
    ((("_lab_trace.py", "read_bytes"), ("_lab_trace.py", "sha")), "digest"),
    ((("run_lab.py", "lf_digest"),), "digest"),
    ((("test_lab_replay_corpus.py", "comment_overlay"),), "overlay"),
    ((("test_lab_replay_corpus.py", "repo_text"), ("test_lab_replay_corpus.py", "cited")), "exist"),
)
HOOK = r'''import json, os, sys
_D, _R = os.environ.get("ECCO_TRACE_DIR"), os.environ.get("ECCO_TRACE_ROOT")
if _D and _R:
    _root = os.path.normcase(os.path.abspath(_R)) + os.sep
    _fh = open(os.path.join(_D, "%d.jsonl" % os.getpid()), "a", encoding="utf-8")
    _seen, _busy = set(), [False]
    _W = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def _hook(event, args):
        if event != "open" or _busy[0]:
            return
        _busy[0] = True
        try:
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            if path is None or isinstance(path, int):
                return
            ap = os.path.normcase(os.path.abspath(os.fsdecode(path)))
            if not ap.startswith(_root):
                return
            w = any(c in mode for c in "wax+") if isinstance(mode, str) else bool(isinstance(flags, int) and flags & _W)
            f, frames, imp = sys._getframe().f_back, [], False     # None for an open with no Python caller
            while f is not None:
                fn = f.f_code.co_filename
                if fn.startswith("<frozen importlib"):
                    imp = True
                elif len(frames) < 4 and not fn.startswith("<"):
                    nf = os.path.normcase(os.path.abspath(fn))
                    if nf.startswith(_root):
                        frames.append([nf[len(_root):].replace(os.sep, "/"), f.f_code.co_name])
                f = f.f_back
            key = (ap, w, imp, repr(frames))
            if key not in _seen:
                _seen.add(key)
                _fh.write(json.dumps({"p": ap[len(_root):].replace(os.sep, "/"), "w": w, "imp": imp, "fr": frames}) + "\n")
                _fh.flush()
        except Exception as exc:
            _fh.write(json.dumps({"err": repr(exc)}) + "\n")
            _fh.flush()
        finally:
            _busy[0] = False

    sys.addaudithook(_hook)
'''
_LISTED: dict = {}


def real_path(rel_folded: str) -> str | None:
    """The repository's own spelling of a case-folded repo-relative path (None: no such file)."""
    cur, out = ROOT, []
    for part in rel_folded.split("/"):
        if cur not in _LISTED:
            _LISTED[cur] = os.listdir(cur) if cur.is_dir() else []
        hit = [n for n in _LISTED[cur] if os.path.normcase(n) == part]
        if not hit:
            return None
        out.append(hit[0])
        cur = cur / hit[0]
    return "/".join(out) if cur.is_file() else None


def read_kind(event: dict) -> str:
    frames = tuple((Path(f).name.lower(), fn) for f, fn in event["fr"])
    for pattern, kind in HELPERS:
        if frames[:len(pattern)] == tuple((f.lower(), fn) for f, fn in pattern):
            return kind
    return "import" if event["imp"] else "data"


def run_unit(cmd: list[str], logdir: Path, hookdir: Path, extended: bool) -> tuple[int, str]:
    logdir.mkdir(parents=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ECCO_TRACE_DIR=str(logdir), ECCO_TRACE_ROOT=str(ROOT))
    env["PYTHONPATH"] = str(hookdir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("ECCO_LAB_STRICT_BASELINE", None)
    env.pop("ECCO_LAB_EXTENDED", None)
    if extended:
        env["ECCO_LAB_EXTENDED"] = "1"
    r = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3600)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def load_unit(logdir: Path) -> tuple[dict, list, list]:
    """({real path: {kind, ...}} of the reads, [written paths], [hook errors]) of one traced unit."""
    reads: dict[str, set] = {}
    writes, errors = [], []
    for f in sorted(logdir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if "err" in ev:
                errors.append(ev["err"])
                continue
            if "__pycache__" in ev["p"].split("/"):
                continue
            rel = real_path(ev["p"])
            if rel is None:
                continue                      # an attempted open of a file that does not exist
            if ev["w"]:
                writes.append(rel)
            else:
                reads.setdefault(rel, set()).add(read_kind(ev))
    return reads, writes, errors


def replay_one(doc_id: str) -> int:
    """--replay-one (a traced child): replay one corpus document with only its tier module imported."""
    for p in (ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    doc = T.load_doc(HERE / "corpus" / f"{doc_id}.json")
    importlib.import_module(TIER_MODULES[doc["tier"]])
    r = T.replay(doc)
    print(json.dumps({"id": doc_id, "ok": r.ok, "drift": r.drift}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace_inputs.py", description="Trace the lab's repository inputs with an audit "
                                 "hook and diff them against the B1 tier table (see the module docstring).")
    ap.add_argument("--extended", action="store_true", help="also trace every suite in extended mode")
    ap.add_argument("--parallel", type=int, default=4, help="traced processes at once (default 4)")
    ap.add_argument("--replay-one", metavar="ID", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.replay_one:
        return replay_one(args.replay_one)
    if args.parallel < 1:
        ap.error("--parallel must be >= 1")
    suites = sorted(p.name for p in HERE.glob("test_lab_*.py"))
    docs = {p.stem: json.loads(p.read_text(encoding="utf-8"))["tier"] for p in sorted((HERE / "corpus").glob("*.json"))}
    work = Path(tempfile.mkdtemp(prefix="ecco-lab-trace-"))
    try:
        hookdir = work / "hook"
        hookdir.mkdir()
        (hookdir / "sitecustomize.py").write_text(HOOK, encoding="ascii", newline="\n")
        modes = ["quick"] + (["extended"] if args.extended else [])
        jobs = [(m, s[:-3], [sys.executable, "-B", f"{LAB_REL}/{s}"], m == "extended") for m in modes for s in suites]
        jobs += [("replay", d, [sys.executable, "-B", f"{LAB_REL}/trace_inputs.py", "--replay-one", d], False)
                 for d in docs]
        with cf.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = {pool.submit(run_unit, cmd, work / mode / unit, hookdir, ext): (mode, unit)
                    for mode, unit, cmd, ext in jobs}
            done = {futs[f]: f.result() for f in cf.as_completed(futs)}
        mismatches = []
        loaded = {key: load_unit(work / key[0] / key[1]) for key in sorted(done)}
        for (mode, unit), (rc, out) in sorted(done.items()):
            if rc != 0:
                tail = " | ".join(out.strip().splitlines()[-3:])[:300]
                mismatches.append(f"{mode} {unit}: exit code {rc}, so the trace is incomplete ({tail})")
            reads, writes, errors = loaded[(mode, unit)]
            if errors:
                mismatches.append(f"{mode} {unit}: the hook logged {len(errors)} error(s): {errors[:2]}")
            if writes:
                mismatches.append(f"{mode} {unit}: opened for writing inside the repository: {sorted(set(writes))[:4]}")
        per_mode: dict[str, dict[str, set]] = {}
        for (mode, _unit), (reads, _w, _e) in loaded.items():
            for p, kinds in reads.items():
                if not T.is_lab_path(p):
                    per_mode.setdefault(mode, {}).setdefault(p, set()).update(kinds)
        traced: dict[str, set] = {}
        for m in per_mode.values():
            for p, kinds in m.items():
                traced.setdefault(p, set()).update(kinds)
        for p, kinds in sorted(traced.items()):
            tier, beh = T.source_tier(p), bool(kinds & BEHAVIOURAL_KINDS)
            if tier == "unclassified":
                mismatches.append(f"{p}: read ({', '.join(sorted(kinds))}) but in neither tier of the table")
            elif beh and tier != "behavioural":
                mismatches.append(f"{p}: a behavioural read ({', '.join(sorted(kinds))}) but listed {tier}")
            elif not beh and tier == "behavioural":
                mismatches.append(f"{p}: listed behavioural but read only as {', '.join(sorted(kinds))}")
            elif tier == "non-behavioural" and T.NON_BEHAVIOURAL[p][0] == (kinds <= {"exist"}):
                mismatches.append(f"{p}: pinned flag {T.NON_BEHAVIOURAL[p][0]} but its reads are "
                                  f"{', '.join(sorted(kinds))} (existence-only files are unpinned, the others pinned)")
        stale = sorted((set(T.BEHAVIOURAL) | set(T.NON_BEHAVIOURAL)) - set(traced))
        if stale:
            mismatches.append(f"table entries the traced runs never read: {stale}")
        per_tier: dict[str, set] = {}
        for d, tier in sorted(docs.items()):
            reads = loaded[("replay", d)][0]
            beh = {p for p, kinds in reads.items() if not T.is_lab_path(p) and kinds & BEHAVIOURAL_KINDS}
            per_tier.setdefault(tier, set()).add(frozenset(beh))
            want = set(T.TIER_SOURCES.get(tier, ()))
            if beh != want:
                mismatches.append(f"replay {d} ({tier}): behavioural reads differ from TIER_SOURCES[{tier}]: extra "
                                  f"{sorted(beh - want)}, missing {sorted(want - beh)}")
        n_beh = sum(1 for kinds in traced.values() if kinds & BEHAVIOURAL_KINDS)
        n_exist = sum(1 for kinds in traced.values() if kinds <= {"exist"})
        print(f"trace_inputs: traced {len(suites)} suite(s) in {' and '.join(modes)} mode and {len(docs)} single-document "
              f"replay(s) ({len(done)} processes, each exit code checked)")
        for m in modes:
            print(f"trace_inputs: {m}: {len(per_mode.get(m, {}))} non-lab files read")
        if args.extended:
            q, e = set(per_mode.get("quick", {})), set(per_mode.get("extended", {}))
            print(f"trace_inputs: quick and extended read the same non-lab files: {q == e}"
                  + ("" if q == e else f" (only quick {sorted(q - e)}, only extended {sorted(e - q)})"))
        print(f"trace_inputs: {len(traced)} non-lab files read in all: {n_beh} behavioural, {len(traced) - n_beh} "
              f"non-behavioural ({n_exist} existence-only); table: {len(T.BEHAVIOURAL)} behavioural, "
              f"{len(T.NON_BEHAVIOURAL)} non-behavioural")
        for tier, sets in sorted(per_tier.items()):
            sizes = sorted({len(s) for s in sets})
            print(f"trace_inputs: replays of tier {tier}: {len(sets)} distinct behavioural read set(s) of size {sizes}; "
                  f"TIER_SOURCES[{tier}] holds {len(T.TIER_SOURCES.get(tier, ()))}")
        for m in mismatches:
            print(f"MISMATCH: {m}")
        print(f"trace_inputs: {len(mismatches)} mismatch(es) against _lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL / "
              "TIER_SOURCES")
        return 1 if mismatches else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
