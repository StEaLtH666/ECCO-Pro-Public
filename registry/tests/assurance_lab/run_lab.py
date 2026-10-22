#!/usr/bin/env python3
"""Runner and plain-text summary of the offline assurance lab V0.1 (test-only: no network, no Home Assistant, no hardware).
The runner itself (run, --list, the report) needs the standard library only: its catalogue baseline check imports the
lab helpers _lab_trace and _lab_clock, which use the standard library only; --replay imports every lab helper, which need
the packages pinned in requirements-ci.txt (PyYAML, Jinja2), as the suites do. This file is a command-line runner, not a
suite: it is not named test_*.py, so neither tools/run_offline_tests.py nor the exit-code meta-check collects it.

    python registry/tests/assurance_lab/run_lab.py                      # every lab suite, quick mode, one at a time
    python registry/tests/assurance_lab/run_lab.py --parallel 4         # four suites at once
    python registry/tests/assurance_lab/run_lab.py --extended           # ECCO_LAB_EXTENDED=1: the suites' deeper sweeps
    python registry/tests/assurance_lab/run_lab.py --suite test_lab_property --suite test_lab_fw_runtime
    python registry/tests/assurance_lab/run_lab.py --list               # the suites and their catalogue scenario ids
    python registry/tests/assurance_lab/run_lab.py --replay FW-01-a registry/tests/assurance_lab/corpus/HF-08-a.json
    python registry/tests/assurance_lab/run_lab.py --parallel 4 --write-summary docs/dev/assurance-lab-v0/LAB_SUMMARY.txt

RUN (default mode)
  Every registry/tests/assurance_lab/test_lab_*.py is run as its own subprocess the way tools/run_offline_tests.py runs a
  suite (sys.executable, cwd = repository root, output captured in a temporary file, the process group killed after
  --timeout seconds), with -B and PYTHONDONTWRITEBYTECODE=1 added; --extended sets ECCO_LAB_EXTENDED=1, otherwise the
  variable is removed from the child environment. A suite is ok only when ALL of these hold, else it is FAIL (the reason
  and the tail of its output are printed):
    - it exits 0 within --timeout;
    - it prints exactly one 'LAB-SUMMARY {...}' line (the V0.1 suite output contract, _lab_trace.finish): strict JSON
      with exactly the keys suite, pass, fail, finding, finding_pins, unsupported_ids, unsupported_points, blocked,
      zoneinfo, phase_sensitive, runtime_s (in that order), naming the suite itself, non-negative integer counts,
      zoneinfo a bool, unsupported_ids <= unsupported_points (both 0 or both > 0), fail == 0;
    - the LAB-SUMMARY numbers agree with the printed lines: pass == '  PASS  ' lines minus the finding-pin lines
      ('  PASS  finding-reproduces:...'), finding_pins == those pin lines, fail == '  FAIL  ' lines,
      unsupported_points == '  UNSUPPORTED  <id> ...' lines and unsupported_ids == the distinct ids on them;
    - it prints no '  FAIL  ' line at all (any FAIL line fails the suite, even at exit code 0);
    - the output ends with the LAB-SUMMARY line, preceded by exactly one 'FAILED: <fail> check(s): <names>' line when
      a check failed and by no FAILED line otherwise (so a CI log tail always shows the failing names);
    - its '  info  mode: quick|EXTENDED' line, when printed, matches the requested mode.
  Then SCENARIO_CATALOGUE.json (read as data, never executed) is cross-checked against the run: the baseline.sources
  sha256 digests by the tiered drift rule (baseline_status: a changed lab or behavioural file is a named failure, a
  changed non-behavioural file a 'SOURCE DRIFT (non-behavioural)' note, a missing pinned file of any tier a failure
  (a non-behavioural one as 'pinned source missing: <path>'), ECCO_LAB_STRICT_BASELINE=1 the whole-baseline rule: the
  switch is the environment value '1' exactly, this runner has no command-line switch for it), every lab .py
  (test_lab_replay_corpus.py included: _lab_trace.LAB_RULE) and every corpus document is pinned there, the
  discovered suites equal the catalogued suites, each suite's LAB-SUMMARY
  'finding' value equals its number of counted catalogue findings, every counted finding was printed as reproduced
  ('  FINDING  <id>') in this run while every FINDING line names a catalogue finding of that suite (a reclassified id
  prints none), every counted catalogue finding carries its two-axis verdict fields with known values, and every
  catalogued UNSUPPORTED id is printed in the mode it belongs to (an entry
  whose description starts 'extended mode only' is extended-only: printed in an extended run and never in a quick run;
  every other entry is printed in both modes) while no suite prints an UNSUPPORTED id the catalogue does not list for
  it. A cross-check problem is a FAIL of the run.

REPORT
  A concise plain-text report on stdout: invocation (canonical form, run from the repository root), baseline commit, a
  generic machine description, the extended-mode line (in a quick run the RECORDED measurement EXTENDED_RECORD of one full
  '--extended --parallel 4' run, labelled as such: a quick run does not re-measure it), a table (suite, result, rc, pass,
  fail, finding, finding pins, unsupported ids, unsupported points, blocked, phase-sensitive checks, zoneinfo, runtime_s,
  wall_s) with totals, the catalogue's root causes (the groups per priority; per group its priority, classification,
  counted findings, printed duplicates and merged variants as the catalogue's reported_as records them, severity and the
  tags of its uncounted notes), the two-axis verdict distribution of the counted findings (mechanism verdict, device
  reachability with VERIFIED always printed, the findings that need no product change, the findings resting on an
  injected NVS primitive and on any injected fault primitive: counted from the catalogue fields, never literals), its
  UNSUPPORTED entries and its section counts (the negative controls as '<rows> control rows over <n> distinct
  mutations', B3.6: rows whose same_mutation_as is null are the distinct mutations; the outcomes counted, the audit
  mutant rows, outcome 'killed(audit)', named). Findings and finding pins are never counted as passes. The report is
  built only from the suite names, the
  LAB-SUMMARY numbers, fixed text, EXTENDED_RECORD and catalogue fields, plus (for a failing suite only) up to three of
  its FAIL check names, cut at ' - ' and made ASCII; no other suite output and no local path is copied into it. The 90 s
  per-suite quick budget is a sequential-run limit: it is noted only in a quick --parallel 1 run.
  --write-summary PATH also writes exactly that report to PATH (ASCII, LF). Nothing is written without it. Before writing,
  a privacy guard refuses the report (exit 1) if it holds a non-ASCII character, a 13-digit run, a dotted quad, an '@', a
  user-profile, drive or home path, six joined 2-character groups or a secret shape.

LIST / REPLAY
  --list prints the suites with their catalogue scenario ids ([n] = replay corpus documents of that scenario).
  --replay FILE [FILE ...] replays corpus documents through _lab_trace.replay (each FILE is a path or a corpus id such as
  FW-01-a) and prints ok, drift, digest vs trace_digest, anchor problems and every failed expectation. For a FINDING
  document 'ok' means the recorded deviation still reproduces exactly. --replay is DIAGNOSTIC: it applies only the
  per-document rule of the replay engine (a document whose own pinned digest differs from this tree prints SOURCE
  DRIFT and is judged on its expectations only, 'OK on its expectations only'), not the tiered drift rule. It does not
  add the tier's TIER_SOURCES pins, does not tell a behavioural change from a non-behavioural one and never fails a
  drifted document for the drift itself; the gates are test_lab_replay_corpus [2] / [5], 'gen_catalogue.py --check'
  and the runner's baseline check above.

EXIT  0 everything ok; 1 a suite failed or timed out, a catalogue cross-check failed, a replay failed or the summary was
      refused; 2 usage error or no suite found.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # before any lab helper is imported (--replay)

import argparse  # noqa: E402
import concurrent.futures as cf  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import textwrap  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # repository root
LAB_REL = "registry/tests/assurance_lab"
SELF_REL = f"{LAB_REL}/run_lab.py"
CATALOGUE = HERE / "SCENARIO_CATALOGUE.json"
CORPUS_DIR = HERE / "corpus"
CAT_SCHEMA = "ecco-assurance-lab-catalogue/v0"
CAT_KEYS = ("baseline", "invariants", "known_risks_used", "scenarios", "findings", "root_causes", "negative_controls",
            "unsupported", "runtime_quick_s")
# The V0.1 LAB-SUMMARY keys, in order (the same tuple as _lab_trace.SUMMARY_KEYS; this runner parses a suite's output
# without any lab helper, and test_lab_replay_corpus checks that the two agree).
SUMMARY_KEYS = ("suite", "pass", "fail", "finding", "finding_pins", "unsupported_ids", "unsupported_points", "blocked",
                "zoneinfo", "phase_sensitive", "runtime_s")
COUNT_KEYS = ("pass", "fail", "finding", "finding_pins", "unsupported_ids", "unsupported_points", "blocked",
              "phase_sensitive")
PIN_PREFIX = "finding-reproduces:"
DEFAULT_TIMEOUT = 1800
QUICK_BUDGET_S = 90
WIDTH = 126
TAIL_LINES = 60
PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}
# The two-axis verdict fields of a catalogue finding (V0.1): a counted finding carries every one with a known value; a
# DUPLICATE / MERGED entry has injected_primitive only (the others null: it is graded through its owner). The value sets
# are _catalogue_data.MECHANISM_VERDICTS / DEVICE_REACHABILITY / PRODUCT_CHANGE (gen_catalogue refuses any other value);
# this runner keeps the same values in its report order and gen_catalogue checks that the two agree.
VERDICT_FIELDS = ("mechanism_verdict", "device_reachability", "injected_primitive", "needs_product_change",
                  "needs_product_change_reason")
MECHANISM_VERDICTS = ("CONFIRMED-IN-SIMULATION", "PLAUSIBLE-UNDER-ASSUMPTIONS", "NOT-CONFIRMED")
DEVICE_REACHABILITY = ("VERIFIED", "PLAUSIBLE-UNDER-ASSUMPTIONS", "UNKNOWN", "UNVERIFIABLE-OFFLINE", "NOT-APPLICABLE")
PRODUCT_CHANGE = ("yes", "no")
# The extended-mode figures that a quick-mode report prints. A RECORDED measurement, never re-measured by a quick run: one
# full 'run_lab.py --extended --parallel 4' run (rc 0, every suite ok) on the Windows PC that produced V0. wall_s is that
# run's whole-run wall clock and runtime_sum_s the sum of the suites' own LAB-SUMMARY runtimes in it. Those runtimes were
# measured while four suites shared the CPU, so runtime_sum_s is NOT a sequential measurement (no sequential --extended
# run was measured); it only bounds the CPU time spent. Re-measure and update every value (measured_at names the lab
# version measured) after a change that alters the extended sweeps. V0 measured 527 s wall / 1062 s runtime sum; V0.1
# altered the sweeps (the fw_guards suite, the NVS used-key preludes, the coupled-tier guards, the B1 drift controls) and
# was re-measured on the same PC, otherwise idle, from the V0.1 commit-4 tree (14 of 14 suites ok, rc 0; 569.8 s wall,
# 1174.8 s runtime sum), and again after the per-slot FW-09 b3 scenarios (W6-1) on the otherwise idle PC (14 of 14 ok,
# rc 0; 553.0 s wall, 1150.3 s runtime sum), and after the containment, below-lease and distinct-originals scenarios
# (W6-1b) on the otherwise idle PC (14 of 14 ok, rc 0; 554.5 s wall, 1161.6 s runtime sum), and after the failed-
# readback, two-attempt and all-FOREIGN containment scenarios (W6-1c) on the otherwise idle PC (14 of 14 ok, rc 0;
# 533.6 s wall, 1122.0 s runtime sum).
EXTENDED_RECORD = {"measured_at": "V0.1", "parallel": 4, "wall_s": 534, "runtime_sum_s": 1122}
# the lab version a re-measured EXTENDED_RECORD must name for the report to drop its 'not re-measured' caveat
LAB_VERSION = "V0.1"

SUMMARY_RE = re.compile(r"^LAB-SUMMARY (\{.*\})\s*$")
FINDING_RE = re.compile(r"^  FINDING  (\S+)")
FAIL_RE = re.compile(r"^  FAIL  (.+?)(?: - .*)?$")
UNSUPPORTED_RE = re.compile(r"^  UNSUPPORTED  (\S*)")
FAILED_RE = re.compile(r"^FAILED: (\d+) check\(s\)(?:: |$)")
EXTENDED_ONLY_RE = re.compile(r"^extended mode only\b", re.I)
MODE_RE = re.compile(r"^  info  mode: (quick|EXTENDED)\b")
STEM_RE = re.compile(r"^test_lab_[a-z0-9_]+$")
REL_RE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")
DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# The report is public text: refuse it if any of these shapes appears (the repository privacy scan is stricter only in
# that it also knows the private literal patterns, which this runner never spells).
GUARDS = (
    ("non-ASCII or control character", re.compile(r"[^\n\x20-\x7e]")),
    ("13-digit number run", re.compile(r"[0-9]{13}")),
    ("dotted quad", re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")),
    ("an '@' (e-mail shape)", re.compile(r"@")),
    ("user-profile path", re.compile(r"Users[\\/]")),
    ("drive path", re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")),
    ("home path", re.compile(r"(?<![A-Za-z0-9_])/home/")),
    ("six joined 2-character groups", re.compile(r"[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}")),
    ("secret shape", re.compile(r"-----BEGIN|\bghp_[A-Za-z0-9]{20}|\bgithub_pat_|\bAKIA[0-9A-Z]{16}\b|\bxox[abprs]-"
                                r"|\bsk-[A-Za-z0-9_-]{20}|eyJ[A-Za-z0-9_-]{20}")),
)


# ---------------------------------------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------------------------------------
def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _no_constant(name):
    raise ValueError(f"non-finite JSON constant {name}")


def strict_json(text: str):
    """json.loads that refuses duplicate keys and NaN / Infinity."""
    return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_constant)


def lf_digest(path: Path) -> str:
    """sha256 of the LF-normalised bytes (the _lab_trace.source_digest rule)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def wrap(text: str, first: str = "", rest: str = "    ") -> list[str]:
    return textwrap.wrap(text, width=WIDTH, initial_indent=first, subsequent_indent=rest, break_long_words=False,
                         break_on_hyphens=False) or [first.rstrip()]


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def minutes(seconds: float) -> str:
    """Seconds as minutes, rounded to the nearest half minute ('17 min', '8.5 min')."""
    return f"{round(seconds / 30) / 2:g} min"


def discover() -> list[Path]:
    return sorted(p for p in HERE.glob("test_lab_*.py") if p.is_file() and STEM_RE.match(p.stem))


def machine() -> str:
    """Generic only: operating system and Python minor version (no host, user or path)."""
    system = platform.system() or "unknown OS"
    return f"{system}, Python {sys.version_info.major}.{sys.version_info.minor}"


def display_path(raw: str) -> str:
    """A path for the report: repository-relative POSIX when inside the repository, else a placeholder."""
    try:
        rel = Path(raw).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return "<a path outside the repository>"
    return rel if REL_RE.match(rel) else "<a path inside the repository>"


def load_catalogue() -> tuple[dict | None, str | None]:
    """(catalogue, None) or (None, reason). Read as data; never executed."""
    if not CATALOGUE.is_file():
        return None, f"{LAB_REL}/SCENARIO_CATALOGUE.json is missing"
    try:
        cat = strict_json(CATALOGUE.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "SCENARIO_CATALOGUE.json is not strict UTF-8 JSON"
    if not isinstance(cat, dict) or cat.get("schema") != CAT_SCHEMA:
        return None, f"SCENARIO_CATALOGUE.json is not a {CAT_SCHEMA} document"
    missing = [k for k in CAT_KEYS if k not in cat]
    if missing:
        return None, f"SCENARIO_CATALOGUE.json lacks {missing}"
    return cat, None


# ---------------------------------------------------------------------------------------------------------------------------
# running the suites
# ---------------------------------------------------------------------------------------------------------------------------
def child_env(extended: bool) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extended:
        env["ECCO_LAB_EXTENDED"] = "1"
    else:
        env.pop("ECCO_LAB_EXTENDED", None)
    return env


def _kill(proc: subprocess.Popen) -> None:
    # pattern from tools/run_offline_tests.py:96 (kill the whole process group on POSIX)
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass


def run_one(suite: Path, timeout: int, extended: bool) -> dict:
    """Run one suite as tools/run_offline_tests.py:run_one does, plus -B and PYTHONDONTWRITEBYTECODE=1."""
    rel = suite.relative_to(ROOT).as_posix()
    t0 = time.perf_counter()
    with tempfile.TemporaryFile() as out:   # a file, not a pipe: a surviving grandchild cannot wedge the runner
        proc = subprocess.Popen([sys.executable, "-B", rel], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                env=child_env(extended), start_new_session=(os.name == "posix"))
        try:
            rc: int | str = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.wait()
            rc = "TIMEOUT"
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    return {"stem": suite.stem, "rel": rel, "rc": rc, "wall_s": time.perf_counter() - t0, "text": text}


def parse_summary(stem: str, lines: list[str]) -> tuple[dict | None, str | None]:
    """The suite's one LAB-SUMMARY record, or a fixed-text reason (never raw output)."""
    found = [m.group(1) for m in (SUMMARY_RE.match(line) for line in lines) if m]
    if not found:
        return None, "no LAB-SUMMARY line"
    if len(found) > 1:
        return None, f"{len(found)} LAB-SUMMARY lines (exactly one is required)"
    try:
        rec = strict_json(found[0])
    except ValueError:
        return None, "the LAB-SUMMARY line is not strict JSON"
    if not isinstance(rec, dict) or tuple(rec) != SUMMARY_KEYS:
        return None, f"the LAB-SUMMARY keys differ from {', '.join(SUMMARY_KEYS)} (in that order)"
    if rec["suite"] != stem:
        return None, "the LAB-SUMMARY line names another suite"
    if not all(type(rec[k]) is int and rec[k] >= 0 for k in COUNT_KEYS):
        return None, "a LAB-SUMMARY count is not a non-negative integer"
    if type(rec["zoneinfo"]) is not bool:
        return None, "the LAB-SUMMARY zoneinfo value is not true / false"
    if rec["unsupported_ids"] > rec["unsupported_points"] or (rec["unsupported_ids"] == 0) != \
            (rec["unsupported_points"] == 0):
        return None, "the LAB-SUMMARY unsupported_ids / unsupported_points pair is impossible"
    rt = rec["runtime_s"]
    if type(rt) not in (int, float) or not (0 <= rt < 1e7):
        return None, "the LAB-SUMMARY runtime_s is not a plausible number of seconds"
    return rec, None


def scan_output(lines: list[str]) -> dict:
    """What a suite printed, by the V0.1 line formats (lines as from str.splitlines(), so CRLF output is fine)."""
    passes = [ln for ln in lines if ln.startswith("  PASS  ")]
    pins = [ln for ln in passes if ln.startswith("  PASS  " + PIN_PREFIX)]
    fails = [m.group(1) for m in (FAIL_RE.match(ln) for ln in lines if ln.startswith("  FAIL  ")) if m]
    n_fail_lines = sum(1 for ln in lines if ln.startswith("  FAIL  "))
    uns = [m.group(1) for m in (UNSUPPORTED_RE.match(ln) for ln in lines) if m]
    return {"pass_lines": len(passes), "pin_lines": len(pins), "fail_lines": n_fail_lines, "fail_names": fails,
            "unsupported_points": uns, "unsupported_ids": sorted(set(uns)),
            "findings": sorted({m.group(1) for m in (FINDING_RE.match(ln) for ln in lines) if m})}


def output_problems(lines: list[str], rec: dict) -> list[str]:
    """The V0.1 cross-checks of a parsed LAB-SUMMARY record against the printed lines (fixed text, never raw output):
    counts against the PASS / pin / FAIL / UNSUPPORTED lines, and the final-lines order (FAILED line, LAB-SUMMARY, nothing
    after it). The FAIL-line verdict itself (any FAIL line fails) is the caller's (judge(); gen_catalogue)."""
    s = scan_output(lines)
    out = []
    if rec["pass"] != s["pass_lines"] - s["pin_lines"]:
        out.append(f"LAB-SUMMARY pass {rec['pass']} != {s['pass_lines'] - s['pin_lines']} PASS lines excluding finding "
                   f"pins ({s['pass_lines']} PASS lines, {s['pin_lines']} pins)")
    if rec["finding_pins"] != s["pin_lines"]:
        out.append(f"LAB-SUMMARY finding_pins {rec['finding_pins']} != {s['pin_lines']} printed finding-pin PASS lines")
    if rec["fail"] != s["fail_lines"]:
        out.append(f"LAB-SUMMARY fail {rec['fail']} != {s['fail_lines']} printed FAIL lines")
    if rec["unsupported_points"] != len(s["unsupported_points"]):
        out.append(f"LAB-SUMMARY unsupported_points {rec['unsupported_points']} != {len(s['unsupported_points'])} "
                   "printed UNSUPPORTED lines")
    if rec["unsupported_ids"] != len(s["unsupported_ids"]):
        out.append(f"LAB-SUMMARY unsupported_ids {rec['unsupported_ids']} != {len(s['unsupported_ids'])} distinct ids on "
                   "the printed UNSUPPORTED lines")
    if "" in s["unsupported_points"]:
        out.append("an UNSUPPORTED line carries no id")
    body = [(i, ln) for i, ln in enumerate(lines) if ln.strip()]
    at = [k for k, (_i, ln) in enumerate(body) if SUMMARY_RE.match(ln)]
    if len(at) == 1:
        k = at[0]
        if k != len(body) - 1:
            out.append("output continues after the LAB-SUMMARY line (it must be the last line)")
        failed = [k2 for k2, (_i, ln) in enumerate(body) if ln.startswith("FAILED:")]
        if rec["fail"] or s["fail_lines"]:
            m = FAILED_RE.match(body[k - 1][1]) if k > 0 else None
            if m is None or failed != [k - 1]:
                out.append("a failing suite must print exactly one 'FAILED: <n> check(s): <names>' line, immediately "
                           "before LAB-SUMMARY")
            elif int(m.group(1)) != rec["fail"]:
                out.append(f"the FAILED line counts {m.group(1)} check(s), LAB-SUMMARY fail {rec['fail']}")
        elif failed:
            out.append("a FAILED line is printed although no check failed")
    return out


def unsupported_mode(entry: dict) -> str:
    """'extended' for a catalogue UNSUPPORTED entry whose description starts 'extended mode only', else 'quick' (an entry
    met in quick mode, and so in extended mode too)."""
    return "extended" if EXTENDED_ONLY_RE.match(str(entry.get("description", ""))) else "quick"


def unsupported_id_problems(stem: str, printed_ids, entries: list[dict], extended: bool) -> list[str]:
    """Every catalogued UNSUPPORTED id of `stem` printed in the mode it belongs to (quick ids in both modes, extended-only
    ids in an extended run and never in a quick run) and no printed id that the catalogue does not list for `stem`."""
    mine = {e.get("id"): unsupported_mode(e) for e in entries if isinstance(e, dict) and e.get("suite") == stem}
    printed = set(printed_ids)
    out = []
    want = sorted(i for i, mode in mine.items() if mode == "quick" or extended)
    missing = [i for i in want if i not in printed]
    if missing:
        out.append(f"{stem}: catalogued UNSUPPORTED id(s) not printed in this {'extended' if extended else 'quick'} run: "
                   f"{', '.join(map(str, missing))}")
    if not extended:
        early = sorted(i for i, mode in mine.items() if mode == "extended" and i in printed)
        if early:
            out.append(f"{stem}: extended-only UNSUPPORTED id(s) printed in a quick run: {', '.join(map(str, early))}")
    unknown = sorted(i for i in printed if i not in mine)
    if unknown:
        out.append(f"{stem}: printed UNSUPPORTED id(s) the catalogue does not list for this suite: "
                   f"{', '.join(map(str, unknown))}")
    return out


def _fail_name_reasons(fails: list[str]) -> list[str]:
    out = []
    for name in fails[:3]:
        name = re.sub(r"[^\x20-\x7e]", "?", name)
        out.append(f"FAIL check '{name if len(name) <= 110 else name[:107] + '...'}'")
    if len(fails) > 3:
        out.append(f"and {len(fails) - 3} more FAIL check(s)")
    return out


def judge(raw: dict, extended: bool, timeout: int, parallel: int) -> dict:
    lines = raw["text"].splitlines()
    rec, why = parse_summary(raw["stem"], lines)
    scan = scan_output(lines)
    reasons, notes = [], []
    rc = raw["rc"]
    if rc == "TIMEOUT":
        reasons.append(f"timed out after {timeout} s")
    elif rc != 0:
        reasons.append(f"exit code {rc}")
    if why:
        reasons.append(why)
    else:
        reasons += output_problems(lines, rec)
        if rec["fail"] != 0:
            reasons.append(f"LAB-SUMMARY fail {rec['fail']}" + (" with exit code 0 (inconsistent)" if rc == 0 else ""))
        if not rec["zoneinfo"]:
            notes.append(f"{raw['stem']}: zoneinfo (Europe/London) was not usable in this run: its zoneinfo cross-checks "
                         "were skipped")
    if scan["fail_lines"]:           # any FAIL line fails the suite, whatever the exit code and LAB-SUMMARY say
        reasons.append(f"{plural(scan['fail_lines'], 'FAIL line')} printed" + (" with exit code 0" if rc == 0 else ""))
    modes = [m.group(1) for m in (MODE_RE.match(line) for line in lines) if m]
    want = "EXTENDED" if extended else "quick"
    if not modes:
        if rc == 0:
            notes.append(f"{raw['stem']}: prints no 'info  mode:' line (mode not confirmed)")
    elif modes[0] != want:
        reasons.append(f"ran in {modes[0]} mode, {want} was requested")
    if rec and not extended and parallel == 1 and rec["runtime_s"] > QUICK_BUDGET_S:
        notes.append(f"{raw['stem']}: runtime_s {rec['runtime_s']:.1f} is over the {QUICK_BUDGET_S} s quick budget of a "
                     "sequential run")
    if reasons:
        reasons += _fail_name_reasons(scan["fail_names"])
    return {**raw, "summary": rec, "reasons": reasons, "notes": notes, "ok": not reasons,
            "printed_findings": scan["findings"], "printed_unsupported": scan["unsupported_ids"]}


def run_suites(suites: list[Path], parallel: int, timeout: int, extended: bool) -> tuple[list[dict], float]:
    t0 = time.perf_counter()
    results: dict[str, dict] = {}
    n = len(suites)
    print(f"Running {plural(n, 'lab suite')} ({'EXTENDED' if extended else 'quick'} mode, --parallel {parallel}, "
          f"timeout {timeout} s per suite)", flush=True)
    with cf.ThreadPoolExecutor(max_workers=min(parallel, n)) as pool:
        futures = {pool.submit(run_one, s, timeout, extended): s for s in suites}
        for k, fut in enumerate(cf.as_completed(futures), 1):
            res = judge(fut.result(), extended, timeout, parallel)
            results[res["stem"]] = res
            print(f"[{k:2d}/{n}] {'ok  ' if res['ok'] else 'FAIL'} {res['wall_s']:7.1f}s  {res['rel']}", flush=True)
            if not res["ok"]:
                tail = res["text"].splitlines()[-TAIL_LINES:]
                print(f"----- {res['stem']} FAILED: {'; '.join(res['reasons'])}; last {len(tail)} output lines:")
                for line in tail:
                    print(f"  | {line}")
                print(f"----- end of {res['stem']}", flush=True)
    return [results[s.stem] for s in suites], time.perf_counter() - t0


# ---------------------------------------------------------------------------------------------------------------------------
# catalogue cross-checks (static; the catalogue is data)
# ---------------------------------------------------------------------------------------------------------------------------
def baseline_status(cat: dict) -> tuple[int, int, list[str], list[str]]:
    """(matching, total, problems, drift_lines) for baseline.sources, by the tiered drift rule (B1) that
    test_lab_replay_corpus [5] and 'gen_catalogue.py --check' apply: the ONE shared function _lab_trace.drift_report
    (imported here; _lab_trace and _lab_clock use the standard library only) with the tier table _lab_trace.BEHAVIOURAL /
    NON_BEHAVIOURAL / TIER_SOURCES. A changed lab file ('re-generate the catalogue: lab file changed: <path>'), behavioural
    file ('behavioural source changed: <path>', with the corpus documents that replay it and the re-record procedure) or
    unclassified pinned file is one problem per file (a cross-check failure, exit 1); a missing pinned file of any tier
    is a problem too (a non-behavioural one as 'pinned source missing: <path>', the others under their tier's title),
    so a partial run cannot pass a tree with a pinned file deleted;
    a changed non-behavioural file is a 'SOURCE DRIFT (non-behavioural): <path>' line, printed as a note and named on the
    report's Baseline line, not a failure; with ECCO_LAB_STRICT_BASELINE=1 (the environment value '1' exactly) every
    pinned difference is a problem. The corpus documents are read as JSON data (their tier and source_digests) to name
    the affected ones."""
    sources = cat["baseline"].get("sources") if isinstance(cat["baseline"], dict) else None
    if not isinstance(sources, dict) or not sources:
        return 0, 0, ["the catalogue pins no baseline sources"], []
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import _lab_trace as T      # standard library only; registers no replay tier
    good = {rel: sha for rel, sha in sources.items()
            if isinstance(rel, str) and REL_RE.match(rel) and ".." not in rel.split("/")}
    problems = []
    if len(good) != len(sources):
        problems.append(f"{len(sources) - len(good)} malformed path(s) in the catalogue's baseline.sources: the catalogue "
                        "must be re-generated")
    docs = {}
    for q in sorted(CORPUS_DIR.glob("*.json")):
        try:
            d = strict_json(q.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            problems.append(f"corpus document {q.name} is not strict UTF-8 JSON")
            continue
        if isinstance(d, dict):
            docs[q.stem] = d

    def sha_of(rel: str) -> str | None:
        f = ROOT / rel
        return lf_digest(f) if f.is_file() else None

    strict = os.environ.get("ECCO_LAB_STRICT_BASELINE") == "1"
    rep = T.drift_report(good, docs, sha_of=sha_of, strict=strict)
    problems += rep.messages()
    # the non-failing drift lines only: a missing non-behavioural file ('... (file missing)') is a failure (a problem
    # above, 'pinned source missing: <path>'), never a note
    drift_lines = [ln for ln in rep.drift_lines() if not ln.endswith(" (file missing)")]
    for line in drift_lines:
        print(f"note: {line} (catalogue baseline; not a failure: ECCO_LAB_STRICT_BASELINE=1 makes it one)", flush=True)
    # the replay suite's rule (test_lab_replay_corpus.py lab_files; _lab_trace.LAB_RULE): every lab .py, that suite
    # included, and every corpus document must be pinned (SCENARIO_CATALOGUE.json cannot pin itself)
    lab = [f"{LAB_REL}/{q.name}" for q in sorted(HERE.glob("*.py"))]
    lab += [f"{LAB_REL}/corpus/{q.name}" for q in sorted(CORPUS_DIR.glob("*.json"))]
    unpinned = [rel for rel in lab if rel not in sources]
    if unpinned:
        problems.append(f"{len(unpinned)} lab file(s) not pinned in the catalogue baseline ({', '.join(unpinned[:5])}): "
                        "re-generate the catalogue")
    return len(good) - len(rep.items), len(sources), problems, drift_lines


def cross_check(cat: dict, results: list[dict], ran_all: bool, discovered: list[str], extended: bool = False) -> list[str]:
    problems: list[str] = []
    uns_entries = [u for u in cat["unsupported"] if isinstance(u, dict)] if isinstance(cat["unsupported"], list) else []
    cat_suites = set(cat["runtime_quick_s"]) if isinstance(cat["runtime_quick_s"], dict) else set()
    findings = [f for f in cat["findings"] if isinstance(f, dict)]
    for x in findings + [s for s in cat["scenarios"] if isinstance(s, dict)]:
        cat_suites.add(x.get("suite"))
    unknown_cat = sorted(s for s in cat_suites if s not in discovered)
    if unknown_cat:
        problems.append(f"catalogued suites not found in {LAB_REL}: {', '.join(map(str, unknown_cat))}")
    if ran_all:
        extra = sorted(set(discovered) - cat_suites)
        if extra:
            problems.append(f"lab suites missing from the catalogue: {', '.join(extra)}")
    # every counted finding carries its two-axis verdict fields with known values (V0.1; gen_catalogue writes them)
    problems += verdict_distribution(findings)["problems"]
    for r in results:
        rec = r["summary"]
        counted = [f["fid"] for f in findings if f.get("suite") == r["stem"] and f.get("counted") is True]
        if rec is None:
            continue   # already a FAIL of that suite
        if rec["finding"] != len(counted):
            problems.append(f"{r['stem']}: LAB-SUMMARY finding {rec['finding']} != {len(counted)} counted catalogue "
                            "findings")
        missing = [fid for fid in counted if fid not in r["printed_findings"]]
        if missing:
            problems.append(f"{r['stem']}: counted catalogue finding(s) not printed as reproduced: {', '.join(missing)}")
        # a FINDING line names a catalogue finding of this suite (a reclassified or merged id prints none)
        mine = {f.get("fid") for f in findings if f.get("suite") == r["stem"] and f.get("reported_as") != "MERGED"}
        unknown = [fid for fid in r["printed_findings"] if fid not in mine]
        if unknown:
            problems.append(f"{r['stem']}: FINDING line(s) for id(s) that are no catalogue finding of this suite (or a "
                            f"merged variant): {', '.join(unknown)}")
        problems += unsupported_id_problems(r["stem"], r.get("printed_unsupported", []), uns_entries, extended)
    return problems


# ---------------------------------------------------------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------------------------------------------------------
def invocation(args, selected: list[str]) -> str:
    parts = ["python", SELF_REL]
    if args.extended:
        parts.append("--extended")
    for s in selected:
        parts += ["--suite", s]
    if args.parallel != 1:
        parts += ["--parallel", str(args.parallel)]
    if args.timeout != DEFAULT_TIMEOUT:
        parts += ["--timeout", str(args.timeout)]
    if args.write_summary:
        parts += ["--write-summary", display_path(args.write_summary)]
    return " ".join(parts)


# table columns: (heading, LAB-SUMMARY key, width)
TABLE_COLS = (("pass", "pass", 6), ("fail", "fail", 5), ("finding", "finding", 8), ("pins", "finding_pins", 6),
              ("uns_ids", "unsupported_ids", 8), ("uns_pts", "unsupported_points", 8), ("blocked", "blocked", 8),
              ("phase", "phase_sensitive", 6))


def table(results: list[dict], total_wall: float) -> list[str]:
    head = (f"{'suite':<28}{'result':<7}{'rc':>5}" + "".join(f"{h:>{w}}" for h, _k, w in TABLE_COLS)
            + f"{'tz':>4}{'runtime_s':>10}{'wall_s':>8}")
    out = [head, "-" * len(head)]
    tot = dict.fromkeys(COUNT_KEYS, 0)
    rt_sum = wall_sum = 0.0
    n_tz = n_rec = 0
    for r in results:
        rec = r["summary"]
        rc = r["rc"] if r["rc"] != "TIMEOUT" else "TIME"
        if rec is not None:
            n_rec += 1
            n_tz += rec["zoneinfo"]
            for k in COUNT_KEYS:
                tot[k] += rec[k]
            rt_sum += rec["runtime_s"]
            nums = ("".join(f"{rec[k]:>{w}}" for _h, k, w in TABLE_COLS) + f"{'yes' if rec['zoneinfo'] else 'no':>4}"
                    + f"{rec['runtime_s']:>10.1f}")
        else:
            nums = "".join(f"{'-':>{w}}" for _h, _k, w in TABLE_COLS) + f"{'-':>4}{'-':>10}"
        wall_sum += r["wall_s"]
        out.append(f"{r['stem']:<28}{'ok' if r['ok'] else 'FAIL':<7}{rc!s:>5}{nums}{r['wall_s']:>8.1f}")
    n_ok = sum(r["ok"] for r in results)
    out.append("-" * len(head))
    out.append(f"{'total':<28}{f'{n_ok}/{len(results)} ok':<12}" + "".join(f"{tot[k]:>{w}}" for _h, k, w in TABLE_COLS)
               + f"{n_tz:>4}{rt_sum:>10.1f}{wall_sum:>8.1f}")
    out += wrap(f"Whole run: {total_wall:.1f} s wall clock; the sum of the suites' own runtimes is {rt_sum:.1f} s. "
                f"Totals: pass {tot['pass']} (checks held, excluding finding pins), finding pins {tot['finding_pins']}, "
                f"fail {tot['fail']}, counted findings {tot['finding']}, UNSUPPORTED {tot['unsupported_ids']} ids (the "
                f"sum of each suite's distinct ids) at {tot['unsupported_points']} points, blocked {tot['blocked']}, "
                f"phase-sensitive checks {tot['phase_sensitive']}; zoneinfo usable in {n_tz} of {n_rec} suites.",
                rest="  ")
    return out


def finding_kind(f: dict) -> str:
    """'counted', 'duplicate', 'merged' or 'other', from the catalogue's counted flag and reported_as: FINDING is a counted
    finding (printed '  FINDING  <id>'), DUPLICATE a printed duplicate of a counted finding, MERGED a variant recorded
    under its owner (its suite prints no FINDING line for it); anything else is 'other' and is shown as such."""
    rep = f.get("reported_as")
    if f.get("counted") is True:
        return "counted" if rep == "FINDING" else "other"
    return {"DUPLICATE": "duplicate", "MERGED": "merged"}.get(rep, "other")


KIND_WORDS = (("duplicate", "printed duplicate"), ("merged", "merged variant"), ("other", "other"))
NOTE_TAG_RE = re.compile(r"^(\[[^\]]+\]) ")


def note_tags(notes) -> list[str]:
    """The tags of a root-cause group's notes ('[audit-reported, uncounted]' ...), each with its count, in first-seen
    order; a note without a tag is shown as '[untagged]' (gen_catalogue refuses one)."""
    seen: dict[str, int] = {}
    for n in notes if isinstance(notes, list) else []:
        m = NOTE_TAG_RE.match(n) if isinstance(n, str) else None
        tag = m.group(1) if m else "[untagged]"
        seen[tag] = seen.get(tag, 0) + 1
    return [t if k == 1 else f"{k} x {t}" for t, k in seen.items()]


def root_cause_lines(cat: dict) -> list[str]:
    fids = {f["fid"]: f for f in cat["findings"] if isinstance(f, dict) and "fid" in f}
    groups = [g for g in cat["root_causes"] if isinstance(g, dict)]
    groups = sorted(groups, key=lambda g: PRIORITY_ORDER.get(g.get("priority"), 9))     # stable: catalogue order within
    kind = {fid: finding_kind(f) for fid, f in fids.items()}
    allk = list(kind.values())
    head = [f"{allk.count('counted')} counted"]
    if allk.count("duplicate"):
        head.append(f"{plural(allk.count('duplicate'), 'printed duplicate')} of a counted finding")
    if allk.count("merged"):
        head.append(f"{plural(allk.count('merged'), 'merged variant')} recorded under its owner")
    if allk.count("other"):
        head.append(f"{allk.count('other')} other (counted / reported_as not FINDING, DUPLICATE or MERGED)")
    by_pri = " / ".join(f"{p} {sum(1 for g in groups if g.get('priority') == p)}" for p in PRIORITY_ORDER)
    out = wrap(f"Root causes (SCENARIO_CATALOGUE.json): {plural(len(groups), 'group')} ({by_pri}), "
               f"{plural(len(fids), 'finding')} ({', '.join(head)})", rest="  ")
    out.append("  priority, group, classification, counted findings (+ printed duplicates, + merged variants), severity, "
               "uncounted notes (tags)")
    for g in groups:
        members = [m for m in g.get("findings", []) if m in fids]
        counted = [m for m in members if kind[m] == "counted"]
        extra = [f"+{plural(n, word)}" for k, word in KIND_WORDS
                 if (n := sum(1 for m in members if kind[m] == k))]
        tags = note_tags(g.get("notes"))
        text = (f"{g.get('priority')} {g.get('group')}  {g.get('classification')}  counted {', '.join(counted) or 'none'}"
                + (f" ({', '.join(extra)})" if extra else "") + f"; severity: {g.get('severity')}"
                + (f"; notes: {', '.join(tags)}" if tags else ""))
        out += wrap(text, first="  ", rest="      ")
    return out


def primitive_kind(text) -> str:
    """'nvs' for an injected-primitive text starting with 'nvs ' or 'boot ' (an injected NVS primitive), 'none' for one
    starting with 'none' (no injected fault), 'other' for any other injected fault primitive; the rule the catalogue's
    injected_primitive texts follow (gen_catalogue checks it against _catalogue_data.PRIMITIVES' classes)."""
    t = text if isinstance(text, str) else ""
    if t.startswith(("nvs ", "boot ")):
        return "nvs"
    if t == "none" or t.startswith("none "):
        return "none"
    return "other"


def verdict_distribution(findings) -> dict:
    """The two-axis verdict distribution of the counted catalogue findings, counted from their fields (never literals):
    {'counted', 'mechanism': {value: n}, 'reachability': {value: n}, 'no_product_change', 'nvs_primitive',
    'any_primitive', 'problems': [...]} where problems names a counted finding with a missing or unknown field."""
    counted = [f for f in findings if isinstance(f, dict) and f.get("counted") is True]
    lacking, unknown = [], []
    for f in counted:
        lacks = [k for k in VERDICT_FIELDS if not isinstance(f.get(k), str) or not f.get(k)]
        bad = [k for k, vocab in (("mechanism_verdict", MECHANISM_VERDICTS), ("device_reachability", DEVICE_REACHABILITY),
                                  ("needs_product_change", PRODUCT_CHANGE)) if k not in lacks and f.get(k) not in vocab]
        if lacks:
            lacking.append(str(f.get("fid")))
        if bad:
            unknown.append(f"{f.get('fid')} ({', '.join(bad)})")
    problems = []
    if lacking:
        problems.append(f"{plural(len(lacking), 'counted catalogue finding')} without every two-axis verdict field "
                        f"({', '.join(VERDICT_FIELDS)}): {', '.join(lacking[:6])}{' ...' if len(lacking) > 6 else ''}; "
                        "re-generate the catalogue")
    if unknown:
        problems.append(f"counted catalogue finding(s) with a two-axis value outside the vocabulary: {'; '.join(unknown)}")
    return {"counted": len(counted),
            "mechanism": {v: sum(1 for f in counted if f.get("mechanism_verdict") == v) for v in MECHANISM_VERDICTS},
            "reachability": {v: sum(1 for f in counted if f.get("device_reachability") == v) for v in DEVICE_REACHABILITY},
            "no_product_change": sum(1 for f in counted if f.get("needs_product_change") == "no"),
            "nvs_primitive": sum(1 for f in counted if primitive_kind(f.get("injected_primitive")) == "nvs"),
            "any_primitive": sum(1 for f in counted if primitive_kind(f.get("injected_primitive")) in ("nvs", "other")),
            "problems": problems}


def verdict_text(dist: dict) -> str:
    """One sentence of the distribution (the reserved NOT-CONFIRMED mechanism verdict only when it occurs; every device
    reachability value, VERIFIED included, always)."""
    n = dist["counted"]
    mech = " / ".join(f"{v} {k}" for v, k in dist["mechanism"].items() if k or v != "NOT-CONFIRMED")
    reach = " / ".join(f"{v} {k}" for v, k in dist["reachability"].items())
    return (f"{plural(n, 'counted finding')}: mechanism {mech}; device reachability {reach}; "
            f"{dist['no_product_change']} of {n} need no product change; {dist['nvs_primitive']} of {n} rest on an "
            f"injected NVS primitive and {dist['any_primitive']} of {n} on any injected fault primitive (the others "
            "need no injected fault).")


def verdict_lines(cat: dict) -> list[str]:
    dist = verdict_distribution([f for f in cat["findings"] if isinstance(f, dict)])
    if dist["problems"]:
        return wrap("Two-axis verdicts (SCENARIO_CATALOGUE.json): not available in this catalogue (re-generate it): "
                    + "; ".join(dist["problems"][:3]), rest="  ")
    return wrap("Two-axis verdicts (SCENARIO_CATALOGUE.json; per counted finding: mechanism_verdict, device_reachability, "
                "needs_product_change, injected_primitive): " + verdict_text(dist), rest="  ")


def unsupported_lines(cat: dict) -> list[str]:
    items = [u for u in cat["unsupported"] if isinstance(u, dict)]
    out = [f"UNSUPPORTED (not modelled by the lab, never counted as PASS): {plural(len(items), 'catalogue entry', 'catalogue entries')}"]
    for u in items:
        out += wrap(f"{u.get('id')} ({u.get('suite')}): {u.get('description')}", first="  ", rest="      ")
    return out


def mutation_counts(ncs) -> tuple[int, int | None]:
    """(control rows, distinct mutations) of the catalogue's negative controls (B3.6): a row whose same_mutation_as is
    null is a distinct mutation, a row naming another control repeats that control's identical mutation. distinct is
    None when a row has no same_mutation_as field (a catalogue older than V0.1's distinct-mutation table)."""
    rows = [n for n in ncs if isinstance(n, dict)] if isinstance(ncs, list) else []
    if any("same_mutation_as" not in n for n in rows):
        return len(rows), None
    return len(rows), sum(1 for n in rows if n.get("same_mutation_as") is None)


def mutation_text(ncs) -> str:
    """'<rows> control rows over <n> distinct mutations' (gen_catalogue prints the same text)."""
    rows, distinct = mutation_counts(ncs)
    if distinct is None:
        return f"{rows} control rows (distinct mutations not recorded in this catalogue: re-generate it)"
    return f"{rows} control rows over {distinct} distinct mutations"


def catalogue_lines(cat: dict) -> list[str]:
    ncs = [n for n in cat["negative_controls"] if isinstance(n, dict)]
    killed = sum(1 for n in ncs if n.get("outcome") == "killed")
    survived = sum(1 for n in ncs if n.get("outcome") == "survived(expected)")
    audit = [str(n.get("id")) for n in ncs if n.get("outcome") == "killed(audit)"]
    other = [f"{n.get('id')} ({n.get('outcome')})" for n in ncs
             if n.get("outcome") not in ("killed", "survived(expected)", "killed(audit)")]
    n_docs = sum(len(s.get("corpus", [])) for s in cat["scenarios"] if isinstance(s, dict))
    hls = [h for h in cat.get("harness_limitations") or [] if isinstance(h, dict)]
    n_open = sum(1 for h in hls if str(h.get("status", "")).startswith("open"))
    hl_text = (f", {plural(len(hls), 'harness limitation')} ({n_open} open; each records its effect on the verdicts and "
               "the suites that work around it)" if hls else "")
    nc_text = (f"negative controls: {mutation_text(cat['negative_controls'])} ({killed} killed, {survived} survived as "
               "expected"
               + (f", {len(audit)} killed by an audit mutant the lab does not run itself (killed(audit): "
                  f"{', '.join(audit)})" if audit else "")
               + (f", {len(other)} with another outcome: {', '.join(other)}" if other else "") + ")")
    text = (f"Catalogue: {plural(len(cat['scenarios']), 'scenario')}, {n_docs} replay corpus documents, "
            f"{plural(len(cat['invariants']), 'invariant')}, {nc_text}, {len(cat['known_risks_used'])} known "
            f"risks referenced{hl_text}. Full detail (titles, mechanisms, repair scopes, evidence) is in "
            f"{LAB_REL}/SCENARIO_CATALOGUE.json.")
    return wrap(text, rest="  ")


def build_report(args, selected, results, total_wall, cat, cat_err, base, problems, n_all) -> str:
    n = len(results)
    failed = [r for r in results if not r["ok"]]
    tot_find = sum(r["summary"]["finding"] for r in results if r["summary"])
    tot_uns = sum(r["summary"]["unsupported_ids"] for r in results if r["summary"])
    tot_pts = sum(r["summary"]["unsupported_points"] for r in results if r["summary"])
    tot_blk = sum(r["summary"]["blocked"] for r in results if r["summary"])
    mode = "EXTENDED (ECCO_LAB_EXTENDED=1)" if args.extended else "quick (ECCO_LAB_EXTENDED unset)"
    scope = f"all {n_all} lab suites" if not selected else f"{n} of the {n_all} lab suites (subset)"
    L = [f"ECCO Assurance Lab {LAB_VERSION} - run summary",
         f"Generated by {SELF_REL}; do not edit by hand, re-run the invocation below to refresh it.",
         "Offline and test-only: synthetic inputs, no network, no Home Assistant, no hardware. No number here is a live "
         "measurement.",
         ""]
    L.append("Invocation (from the repository root; each suite runs as its own subprocess with python -B and "
             "PYTHONDONTWRITEBYTECODE=1):")
    L.append(f"  {invocation(args, selected)}")
    if cat is not None:
        main_sha = cat["baseline"].get("public_main") if isinstance(cat["baseline"], dict) else None
        main_sha = main_sha if isinstance(main_sha, str) and re.fullmatch(r"[0-9a-f]{40}", main_sha) else "(not recorded)"
        drifted = [ln[len("SOURCE DRIFT (non-behavioural): "):] for ln in base[2]]
        L += wrap(f"Baseline:   public main {main_sha}; {base[0]} of {base[1]} catalogue-pinned sources match this tree"
                  + (f"; SOURCE DRIFT (non-behavioural, not a failure): {', '.join(drifted)}" if drifted else "")
                  + " (tiered drift rule: a changed lab or behavioural file fails; ECCO_LAB_STRICT_BASELINE=1: every "
                    "pinned file must match)", rest="            ")
    else:
        L.append(f"Baseline:   unknown ({cat_err})")
    L.append(f"Machine:    {machine()}")
    L.append(f"Mode:       {mode}; {scope}; --parallel {args.parallel}; timeout {args.timeout} s per suite")
    if args.extended:
        L += wrap("Extended:   this run is the extended mode; its measured times are in the table (runtime_s, wall_s and "
                  "the whole-run wall clock).", rest="            ")
    else:
        rec = EXTENDED_RECORD
        stale = rec["measured_at"] != LAB_VERSION
        L += wrap(f"Extended:   not run here. Recorded once, measured at {rec['measured_at']} on the PC that produced V0 "
                  f"(not by this run): one --extended (ECCO_LAB_EXTENDED=1) run with --parallel {rec['parallel']} took "
                  f"about {minutes(rec['wall_s'])} ({rec['wall_s']} s whole-run wall clock); the suites' own extended "
                  f"runtimes in that run add up to {rec['runtime_sum_s']} s (about {minutes(rec['runtime_sum_s'])}), "
                  f"measured while {rec['parallel']} suites shared the CPU, so that sum is not a sequential measurement "
                  "(none was made)."
                  + (f" {LAB_VERSION} changed the extended sweeps and this record was not re-measured since, so it is "
                     f"not a {LAB_VERSION} figure." if stale else ""), rest="            ")
    if not failed and not problems and cat is not None:
        verdict = (f"PASS: {n} of {n} suites ok and every catalogue cross-check holds. This is not a clean bill of "
                   f"health: {plural(tot_find, 'counted finding')} reproduce, {plural(tot_uns, 'UNSUPPORTED id')} "
                   f"(constructs not modelled) {'is' if tot_uns == 1 else 'are'} met at "
                   f"{plural(tot_pts, 'point')} and {tot_blk} blocked.")
    else:
        bits = []
        if failed:
            bits.append(f"{len(failed)} of {n} suites FAILED ({', '.join(r['stem'] for r in failed)})")
        if cat is None:
            bits.append("the catalogue could not be read")
        if problems:
            bits.append(f"{plural(len(problems), 'catalogue cross-check problem')}")
        verdict = "FAIL: " + "; ".join(bits) + "."
    L += wrap(f"Verdict:    {verdict}", rest="            ")
    L.append("")
    L += table(results, total_wall)
    for r in failed:
        L += wrap(f"FAIL {r['stem']}: {'; '.join(r['reasons'])}", first="  ", rest="      ")
    notes = [x for r in results for x in r["notes"]]
    for x in notes:
        L += wrap(f"note: {x}", first="  ", rest="      ")
    L.append("")
    L += ["Reading the table"]
    L += wrap("pass = checks held, excluding finding pins. A finding pin (pins) is a held check named "
              "'finding-reproduces:<id>' that confirms a recorded finding still reproduces exactly; it is printed as "
              "PASS but counted only under pins. A FINDING is a reproduced deviation from an invariant and is never a "
              "pass: a suite exits 0 when every check holds and each of its findings reproduces exactly as recorded.",
              first="- ", rest="  ")
    L += wrap("finding counts each finding once across the lab; a duplicate of another finding (in any suite) is counted "
              "under its owner only, and a merged variant prints no FINDING line and is recorded under its owner. "
              "UNSUPPORTED marks a construct the lab meets but does not model: uns_ids counts the distinct catalogue "
              "ids a suite printed, uns_pts the points (one printed line each; several points can share one id). "
              "blocked counts scenarios that could not run. phase counts executed checks tagged phase-sensitive. tz is "
              "yes when zoneinfo (Europe/London) was usable in that suite's process; when it is no, that suite's "
              "zoneinfo cross-checks were printed as skipped.", first="- ", rest="  ")
    if args.parallel == 1 and not args.extended:
        L += wrap(f"runtime_s is the suite's own LAB-SUMMARY runtime and wall_s the runner's view. This is a sequential "
                  f"quick run, so the {QUICK_BUDGET_S} s per-suite quick budget applies (a suite over it is noted).",
                  first="- ", rest="  ")
    else:
        L += wrap(f"runtime_s is the suite's own LAB-SUMMARY runtime and wall_s the runner's view"
                  + (f"; with --parallel {args.parallel} the suites shared the CPU, so these runtimes are contended and "
                     "are not judged against a per-suite budget." if args.parallel != 1 else
                     "; extended runtimes are not judged against a per-suite budget."), first="- ", rest="  ")
    L.append("")
    if cat is None:
        L.append(f"Catalogue: UNREADABLE ({cat_err}); the catalogue cross-checks did not run.")
    else:
        if problems:
            L.append(f"Catalogue cross-checks against this run: {plural(len(problems), 'PROBLEM')}")
            for p in problems:
                L += wrap(p, first="  ", rest="      ")
        else:
            L += wrap(f"Catalogue cross-checks against this run{' (for the suites run)' if selected else ''}: ok. "
                      f"{base[0]} of {base[1]} pinned source digests match"
                      + (f" ({len(base[2])} non-behavioural SOURCE DRIFT, not a failure)" if base[2] else "")
                      + "; the discovered suites are the catalogued ones; "
                      "each suite's LAB-SUMMARY finding value equals its counted catalogue findings, every counted "
                      "finding was printed as reproduced, every FINDING line names a catalogue finding of its suite, "
                      "every counted finding carries its two-axis verdicts and every catalogued UNSUPPORTED id was "
                      "printed in its mode.", rest="  ")
        L.append("")
        L += root_cause_lines(cat)
        L.append("")
        L += verdict_lines(cat)
        L.append("")
        L += unsupported_lines(cat)
        L.append("")
        L += catalogue_lines(cat)
    L += wrap(f"Replay one corpus document: python {SELF_REL} --replay FW-01-a (prints ok, drift, digest and any "
              "failed expectation).", rest="  ")
    return "\n".join(L) + "\n"


def guard_problems(text: str) -> list[str]:
    out = []
    lines = text.split("\n")
    for label, rx in GUARDS:
        hit = [i for i, line in enumerate(lines, 1) if rx.search(line)]
        if hit:
            out.append(f"{label} on line(s) {hit[:8]}")
    if "\r" in text:
        out.append("a carriage return")
    return out


def run_main(args, selected: list[str]) -> int:
    discovered = discover()
    if not discovered:
        print(f"ERROR: no test_lab_*.py found in {LAB_REL}", file=sys.stderr)
        return 2
    names = [p.stem for p in discovered]
    suites = [p for p in discovered if not selected or p.stem in selected]
    results, total_wall = run_suites(suites, args.parallel, args.timeout, args.extended)
    cat, cat_err = load_catalogue()
    base, problems = (0, 0, []), []
    if cat is not None:
        ok, total, base_problems, drift_lines = baseline_status(cat)
        base = (ok, total, drift_lines)
        problems = base_problems + cross_check(cat, results, not selected, names, args.extended)
    report = build_report(args, selected, results, total_wall, cat, cat_err, base, problems, len(discovered))
    print("")
    print(report, end="")
    rc = 0 if (all(r["ok"] for r in results) and cat is not None and not problems) else 1
    if args.write_summary:
        bad = guard_problems(report)
        if bad:
            print(f"REFUSED: the summary was NOT written: {'; '.join(bad)}", file=sys.stderr)
            return 1
        target = Path(args.write_summary)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="ascii", newline="\n") as fh:
            fh.write(report)
        print(f"summary written: {display_path(args.write_summary)} ({len(report.splitlines())} lines)")
    return rc


# ---------------------------------------------------------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------------------------------------------------------
def list_main() -> int:
    discovered = discover()
    if not discovered:
        print(f"ERROR: no test_lab_*.py found in {LAB_REL}", file=sys.stderr)
        return 2
    cat, cat_err = load_catalogue()
    by_suite: dict[str, list[str]] = {}
    if cat is not None:
        for s in cat["scenarios"]:
            if isinstance(s, dict):
                by_suite.setdefault(s.get("suite"), []).append(f"{s.get('id')}[{len(s.get('corpus', []))}]")
    print(f"{plural(len(discovered), 'lab suite')} in {LAB_REL} (scenario ids from SCENARIO_CATALOGUE.json; "
          "[n] = replay corpus documents of that scenario):")
    for p in discovered:
        ids = by_suite.pop(p.stem, None)
        text = ", ".join(ids) if ids else "(no catalogue scenario: harness self-tests or the replay / catalogue suite)"
        for line in wrap(text, first=f"  {p.stem:<28}", rest=" " * 30):
            print(line)
    rc = 0
    if cat is None:
        print(f"WARNING: {cat_err}")
        rc = 1
    elif by_suite:
        print(f"WARNING: catalogue scenarios name suites that do not exist: {sorted(map(str, by_suite))}")
        rc = 1
    n_docs = len(list(CORPUS_DIR.glob("*.json"))) if CORPUS_DIR.is_dir() else 0
    print(f"corpus: {n_docs} documents in {LAB_REL}/corpus; replay with --replay <file or id>, e.g. --replay FW-01-a")
    return rc


# ---------------------------------------------------------------------------------------------------------------------------
# --replay
# ---------------------------------------------------------------------------------------------------------------------------
def resolve_doc(item: str) -> Path | None:
    p = Path(item)
    if p.is_file():
        return p
    if DOC_ID_RE.match(item):
        c = CORPUS_DIR / (item if item.endswith(".json") else item + ".json")
        if c.is_file():
            return c
    return None


def _short(value, limit: int = 160) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def replay_main(items: list[str]) -> int:
    """--replay (diagnostic): each document through _lab_trace.replay with ONLY the engine's per-document rule (its own
    source_digests; a drifted document is judged on its expectations only). The tiered drift rule (tier pins, the
    behavioural / non-behavioural split, the named FAILs) is applied by test_lab_replay_corpus [2] / [5],
    'gen_catalogue.py --check' and the run's baseline check, never here."""
    for p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import _lab_trace as T
    import _lab_fw  # noqa: F401   registers the replay tier 'firmware'
    import _lab_ha  # noqa: F401   registers the replay tier 'coupled'
    import _lab_rtc  # noqa: F401  registers the replay tier 'rtc'

    n_ok = n_fail = 0
    for item in items:
        path = resolve_doc(item)
        if path is None:
            print(f"replay {item}: FAIL - no such file and no corpus document with that id")
            n_fail += 1
            continue
        try:
            doc = T.load_doc(path)
        except (T.LabTraceError, ValueError, OSError) as exc:
            print(f"replay {item}: FAIL - not a valid replay document: {type(exc).__name__}: {str(exc)[:300]}")
            n_fail += 1
            continue
        print(f"replay {doc['id']} (tier {doc['tier']}, classification {doc['classification']}, seed {doc['seed']})")
        buf = io.StringIO()
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(buf):
                r = T.replay(doc)
        except Exception as exc:   # reported as this document's FAIL (exit 1), never as a pass
            for line in buf.getvalue().splitlines():
                print(f"  | {line}")
            print(f"  result:  FAIL - harness exception {type(exc).__name__}: {str(exc)[:300]}")
            n_fail += 1
            continue
        secs = time.perf_counter() - t0
        for line in buf.getvalue().splitlines():
            print(f"  | {line}")
        if r.drift:
            print(f"  drift:   SOURCE DRIFT in {', '.join(r.drifted_paths)} (judged on its expectations only)")
        else:
            print("  drift:   none (every recorded source digest matches this tree)")
        match = "match" if r.digest == doc["trace_digest"] else ("DIFFERS" if not r.drift else "differs (drifted source)")
        print(f"  digest:  {r.digest}")
        print(f"  trace:   {doc['trace_digest']}  ({match})")
        n_anchor = len(doc["source_anchors"])
        if r.anchor_problems:
            print(f"  anchors: {len(r.anchor_problems)} of {n_anchor} problem(s)")
            for a in r.anchor_problems:
                print(f"    - {a}")
        else:
            print(f"  anchors: {n_anchor} of {n_anchor} found exactly once at their recorded lines")
        n_exp = len(doc["expect"])
        print(f"  expect:  {n_exp - len(r.failed_expectations)} of {n_exp} hold")
        for f in r.failed_expectations:
            print(f"    FAILED expect[{f['index']}] {f['observe']}({_short(f['args'], 80)}) {f['op']} {_short(f['value'])}")
            detail = " ".join(str(f["detail"]).split())
            print(f"      {detail if len(detail) <= 400 else detail[:397] + '...'}")
        if r.ok and r.drift:
            note = (" on its expectations only (SOURCE DRIFT: the document needs re-recording on this tree; --replay is "
                    "diagnostic and does not apply the tiered drift rule)")
        elif r.ok and doc["classification"].startswith("FINDING"):
            note = " (the recorded finding still reproduces exactly)"
        else:
            note = ""
        print(f"  result:  {'OK' if r.ok else 'FAIL'}{note}  [{secs:.1f} s]")
        n_ok += r.ok
        n_fail += not r.ok
    print(f"replayed {plural(len(items), 'document')}: {n_ok} ok, {n_fail} FAIL")
    return 0 if n_fail == 0 else 1


# ---------------------------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_lab.py", description="Run the offline assurance lab V0.1 suites and print a "
                                 "plain-text PASS / FAIL summary (see the module docstring).")
    ap.add_argument("--parallel", type=int, default=1, help="suites run at once (default 1)")
    ap.add_argument("--extended", action="store_true", help="set ECCO_LAB_EXTENDED=1 for every suite (deeper sweeps)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"seconds per suite (default {DEFAULT_TIMEOUT})")
    ap.add_argument("--suite", action="append", default=[], metavar="NAME", help="run only this suite (repeatable)")
    ap.add_argument("--list", action="store_true", help="print the suites and their catalogue scenario ids")
    ap.add_argument("--replay", nargs="+", metavar="FILE", help="replay corpus documents (paths or corpus ids)")
    ap.add_argument("--write-summary", metavar="PATH", help="also write the report to PATH (nothing is written otherwise)")
    args = ap.parse_args(argv)
    if args.parallel < 1 or args.timeout < 1:
        ap.error("--parallel and --timeout must be >= 1")
    if args.list and args.replay:
        ap.error("--list and --replay are separate modes")
    if (args.list or args.replay) and (args.write_summary or args.suite or args.extended):
        ap.error("--write-summary, --suite and --extended apply to a suite run, not to --list / --replay")
    if args.list:
        return list_main()
    if args.replay:
        return replay_main(args.replay)
    names = [p.stem for p in discover()]
    selected = []
    for s in args.suite:
        stem = s[:-3] if s.endswith(".py") else s
        stem = stem if stem.startswith("test_lab_") else "test_lab_" + stem
        if stem not in names:
            ap.error(f"unknown suite {s!r}; the lab suites are: {', '.join(names)}")
        if stem not in selected:
            selected.append(stem)
    return run_main(args, selected)


if __name__ == "__main__":
    sys.exit(main())
