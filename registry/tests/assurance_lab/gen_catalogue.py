#!/usr/bin/env python3
"""Generator and checker of registry/tests/assurance_lab/SCENARIO_CATALOGUE.json (the tool itself uses the standard library
only; the suites it runs as subprocesses need the CI packages; test-only: no network, no Home Assistant, no hardware). This
file is a command-line tool, not a suite: it is not named test_*.py, so neither tools/run_offline_tests.py nor the exit-code
meta-check collects it. It never imports a test_*.py file.

    python -B registry/tests/assurance_lab/gen_catalogue.py                  # run every lab suite (quick), build, report
    python -B registry/tests/assurance_lab/gen_catalogue.py --check          # ... and compare with the committed catalogue
    python -B registry/tests/assurance_lab/gen_catalogue.py --write          # ... and write the catalogue
    python -B registry/tests/assurance_lab/gen_catalogue.py --runs-from DIR --write    # outputs saved by --save-runs DIR
    python -B registry/tests/assurance_lab/gen_catalogue.py --static --check # no suite run: the static parts only
    python -B registry/tests/assurance_lab/gen_catalogue.py --save-runs DIR  # also keep each suite's output (outside the repo)
    python -B registry/tests/assurance_lab/gen_catalogue.py --check --parallel 4       # faster; runtimes are not judged

SOURCES OF THE CATALOGUE
  - the scenario suites' tables (SCENARIOS, FINDINGS, ANCHORS, ...), evaluated statically from their source with
    _catalogue_ast (the suites run their scenarios on import, so they are never imported or executed here);
  - the corpus documents (strict JSON);
  - the hand-written fields in _catalogue_data.py (tiers, invariants, result summaries, verification summaries, the
    two-axis verdicts and injected primitives of the findings, reclassification records, root causes with their tagged
    notes, negative controls, UNSUPPORTED items, harness limitations, coverage matrix);
  - the suites' quick-run outputs: every lab suite's LAB-SUMMARY line (its counts and runtime_s) and the lines that show
    a negative control's outcome, a FINDING line, an UNSUPPORTED line or a merge record. By default the generator runs
    every lab suite itself through run_lab.py's runner (run_lab.run_suites: one subprocess per suite with -B and
    PYTHONDONTWRITEBYTECODE=1, quick mode, --parallel 1 by default so each runtime is an uncontended quick runtime) and
    keeps the outputs in memory; --runs-from DIR reads saved outputs instead (DIR/<suite>.txt or .out for every lab
    suite, with the saved-runs record DIR/_runs.json that --save-runs writes).
  THE TREE THE SUITES RAN ON (V0.1, B1): before the suites run, the generator records the LF-normalised sha256 of every
  file a catalogue baseline can pin (tree_sources: every lab .py and corpus document, every file the tier table pins,
  every corpus pin); --save-runs keeps that record in DIR/_runs.json ('sources'). build() refuses suite outputs that
  carry no such record and outputs whose recorded digest of a baseline source differs from the tree it builds from
  (tree_record_problems: 'the suite outputs carry no record of the tree they ran on ...' / 'the suite outputs were made
  on another tree: <n> pinned source(s) differ ...'), so --write never takes runtimes, counts or FINDING lines from
  suites that ran on another tree (a changed behavioural file that no corpus document pins, say). --runs-from refuses a
  directory without a saved-runs record, or with a record that has no 'sources' (an older v1 record), before building.
  Every scenario / selftest suite must have passed (exit 0 when run here; one valid LAB-SUMMARY with fail 0 and no FAIL
  line). Every suite output, the replay suite's included, must obey the V0.1 suite output contract that run_lab.judge
  enforces (run_lab.output_problems: pass == PASS lines minus finding-pin lines, finding_pins == pin lines, fail == FAIL
  lines, unsupported_points == UNSUPPORTED lines, unsupported_ids == distinct ids, the FAILED line / LAB-SUMMARY order).
  The replay suite test_lab_replay_corpus checks the catalogue being generated, so its result (exit code, fail, FAIL
  lines) is not judged: only its runtime_s is taken from its LAB-SUMMARY.

SEQUENTIAL RUNS, RUNTIMES AND THE 90 s BUDGET
  runtime_quick_s records sequential quick runtimes only, and the 90 s per-suite quick budget is a sequential-run limit
  (as in run_lab.py). Outputs are SEQUENTIAL when they come from a run made here with --parallel 1, or from --runs-from
  DIR whose saved-runs record (DIR/_runs.json, written by --save-runs: the --parallel value, each suite's exit code and
  the tree digests) says parallel 1 (--runs-sequential asserts it: a record that says otherwise is refused).
  Sequential outputs: every quick runtime must be within (0, 90] s (else a problem) and runtime_quick_s is taken from
  them. Other outputs (--parallel N > 1): a runtime over 90 s is a printed WARNING, never a problem, and
  runtime_quick_s keeps the committed catalogue's values (a suite without a committed runtime is a problem: generate it
  with a sequential run).

WHAT IS CHECKED (a problem is printed and nothing is written)
  Static (always): public-text rules on every prose field (no review-process wording, no overclaim, no event date outside
  a cited file path, no day-month date, the run_lab.py privacy shapes; PUBLIC_TEXT_REPLACEMENTS first rewrites the exact
  suite phrases listed there, and an entry that no longer matches is a problem), every anchor '<path>: <snippet>' occurs exactly
  once, lab vocabulary (tiers, grades, confidences, priorities, classifications), confidence_level = the first word of the
  confidence prose, every corpus document owned by exactly one scenario and a finding's documents carrying its
  classification / grade / confidence_level, every corpus document's scenario_priority equal to its scenario's priority
  and its finding_priority equal to the highest root-cause priority of the findings that list it (null when none does;
  the V0 key 'priority' is refused), root-cause groups homogeneous with a counted member, duplicates pointing at
  a counted owner in the same group, every root-cause note starting with a _catalogue_data.NOTE_TAGS tag, the two-axis
  verdicts (B6.4: every counted finding has mechanism_verdict / device_reachability / needs_product_change from the
  _catalogue_data vocabularies, NOT-CONFIRMED never counted, and a reason; an uncounted entry has them null; every entry
  has an injected_primitive whose class agrees with run_lab.primitive_kind; _catalogue_data.VERDICTS / PRIMITIVES hold
  exactly the counted / all ledger ids), the NVS reachability-text rule (B5.5 / B6.3: an entry whose primitive is an
  NVS primitive has a reachability starting 'trigger: <primitive>; device reachability: <its, or its owner's, grade>'
  as _catalogue_data.NVS_REACHABILITY_TEXT spells it, the grade UNKNOWN unless its group is in
  NVS_REACHABILITY_GROUPS), the reclassification records (_catalogue_data.RECLASSIFIED against each suite's RECLASSIFIED
  table; a PASS-reclassified id is no catalogue finding), no stale key in the per-finding tables (VERIFICATION,
  MODEL_DEPENDENCE, FINDING_CORPUS, DST_RTC_TITLES), every invariant referenced is catalogued and its checker exists,
  every known risk
  registered in _lab_trace, every negative control id in its suite source (an audit mutant row, outcome 'killed(audit)',
  carries a catalogue 'AUDIT-' id instead), the distinct-mutation table (B3.6: _catalogue_data.SAME_MUTATION {control
  id: the id of the control whose identical mutation it repeats}; a missing table is empty; every key and value a
  catalogued control id, no key mapped to itself, no value that is itself a key, i.e. no chain; each catalogue row
  carries 'same_mutation_as', that id or null, and the build prints '<rows> control rows over <n> distinct mutations',
  n = the rows whose same_mutation_as is null), every negative-control target a catalogue invariant, a finding check or
  'checks: <name>, ...' whose names each start with a scenario id of its suite, the phase sensitivity (phase_pass:
  every _catalogue_data.PHASE_SENSITIVE prefix is a PHASE_SENSITIVE_TAGS prefix of the entry's suite and every tag of a
  scenario suite is listed there or is a pure corpus trace-digest pin), the coverage matrix (existing files,
  scenario ids, the nine required intersections flagged 'required': true), every harness limitation anchored and its
  workaround suites existing, the B1 tier table (_lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL / TIER_SOURCES:
  _lab_trace.tier_table_problems - every pinned non-lab file classified, no file in both tiers, every tier set inside
  the behavioural tier, every behavioural and anchor-read file pinned, every existence-only file unpinned, every corpus
  document's tier known), every corpus document recording this tree's digest of each file it pins (or, outside --write,
  the committed catalogue's: then the tree changed and the tiered drift rule judges it; one problem per path, naming the
  documents and the re-record procedure), the 13-digit / dotted-quad / six-group shapes over the whole file.
  baseline.sources pins every lab file (every lab .py, test_lab_replay_corpus.py included, and every corpus document;
  SCENARIO_CATALOGUE.json is the one exemption: _lab_trace.LAB_RULE), every anchored or corpus-pinned file and every
  file the tier table requires (_lab_trace.pinned_by_table); baseline.tiers publishes the tier table (rule, lab, drift,
  method, behavioural, non_behavioural with the pinned flag, tier_sources).
  Run-derived (skipped with --static, which says so): each suite output obeys the V0.1 suite output contract (above),
  each counted finding printed '  FINDING  <id>', each DUPLICATE printed with its owner, each MERGED variant printing no
  FINDING line and its merge record, no FINDING line for an id that is no catalogue finding of that suite (a
  reclassified id prints none), counted findings per suite = the suite's LAB-SUMMARY 'finding', every catalogued
  in-suite negative control's outcome seen in its suite's output (the lab does not run an audit mutant: no outcome line)
  and every check a 'checks: ...' target names held in that output, every negative control the scenario suites print
  (killed / survived) catalogued, every catalogued UNSUPPORTED id printed in this quick run unless it is extended-only (its
  description starts 'extended mode only'; then it must not be printed) and no suite printing an UNSUPPORTED id the
  catalogue does not list for it (run_lab.unsupported_id_problems), every quick runtime <= 90 s in a sequential run.

CHECK (--check)
  Compares a fresh build with the committed file. runtime_quick_s values are wall-clock measurements, so they are
  excluded from the comparison (the keys must match; the differences are printed as info). The baseline digests of the
  pinned sources are judged by the TIERED DRIFT RULE (B1; the one shared function _lab_trace.drift_report, also used by
  test_lab_replay_corpus [5] and run_lab.py): a changed non-behavioural file prints '  SOURCE DRIFT (non-behavioural):
  <path>' and is not a difference; a changed lab file ('re-generate the catalogue: lab file changed: <path>'),
  behavioural file ('behavioural source changed: <path>', naming the corpus documents that replay it and the re-record
  procedure) or unclassified file is one failure per file under 'TIERED DRIFT RULE'; ECCO_LAB_STRICT_BASELINE=1 (read
  from the environment, the value '1' exactly; this tool has no command-line switch for it) makes a changed
  non-behavioural file a failure too, and the heading reads 'STRICT DRIFT RULE'. A pinned file that has gone is a
  problem of the build ('pinned sources missing', and its anchors are not found). Everything else must be
  byte-identical (after the CRLF -> LF normalisation of a core.autocrlf=true checkout). With --static the run-derived
  checks are skipped and the committed
  runtimes are reused; test_lab_replay_corpus [5] runs this static build and comparison (build() and compare()).

WRITE (--write)
  Writes SCENARIO_CATALOGUE.json (ASCII, LF) only when no problem was found and the outputs came from a run or
  --runs-from (never with --static) on THIS tree (their recorded tree digests equal it; see above); a corpus document
  that records a digest other than this tree's is a problem here (re-record it first: rerecord_corpus.py). Nothing else
  is ever written; --save-runs refuses a directory inside the repository.

EXIT  0 built (and written / up to date); 1 a problem, or --check found the committed file out of date; 2 usage error.

OUTPUT  besides the problems: '  info  built: <counts>' (with 'negative controls: <rows> control rows over <n> distinct
  mutations') and '  info  two-axis verdicts: <distribution>' (the counted findings by mechanism verdict and device
  reachability, VERIFIED always printed, those needing no product change and those resting on an injected NVS / any
  injected fault primitive: run_lab.verdict_text over the built catalogue).

API (for test_lab_replay_corpus): build(runs=None, committed=None, *, reader=None, for_write=False, run_tree=None) ->
Build(cat, text, problems, notes, skipped, warnings, docs); runs maps each suite to {"text", "rc", "parallel"} (parallel
1 = a sequential run); run_tree is the {path: sha256} record of the tree the suites ran on (required with runs);
reader is a _lab_trace.TreeReader (default: this tree; an in-memory overlay for the drift controls; the corpus
documents are read through it too); suite_output(suite, run, sequential) -> (LAB-SUMMARY record or None, problems,
warnings): the per-suite output checks of build(); static_check(committed_text, *, strict=False, reader=None) ->
(problems, differences including the drift-rule failures, notes including the SOURCE DRIFT lines);
compare(committed_text, build, *, strict=False) -> (differences, notes, drift: a _lab_trace.DriftReport or None);
dumps(cat) -> str; load_runs(dir, assert_sequential=False) -> (runs, run_tree) / save_runs(runs, dir, parallel,
run_tree); tree_sources(reader=None) -> {path: sha256}; tree_record_problems(record, pinned, sha_of) -> [problem];
REPLAY_CHECK_PREFIXES (the check-name prefixes a replay-suite control may target: the drift-rule checks of [5] and the
tier-pin checks of [2]).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # before any lab helper is imported

import argparse  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # repository root
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _catalogue_ast as A  # noqa: E402
import _catalogue_data as G  # noqa: E402
import _lab_trace as T  # noqa: E402
import run_lab  # noqa: E402   (a runner module, not a suite: importing it runs nothing)

LAB_REL = "registry/tests/assurance_lab"
CORPUS = HERE / "corpus"
OUT = HERE / "SCENARIO_CATALOGUE.json"
PUBLIC_MAIN = "a7235433ce711e6a8fae5dab0fc8ca6c6f533de6"
SCHEMA = "ecco-assurance-lab-catalogue/v0"
REPLAY_SUITE = "test_lab_replay_corpus"
SCENARIO_SUITES = ["test_lab_fw_obligations", "test_lab_fw_durability", "test_lab_fw_runtime", "test_lab_fw_guards",
                   "test_lab_ha_lifecycle", "test_lab_ha_phantom", "test_lab_ha_schedules", "test_lab_dst_rtc",
                   "test_lab_property"]
SELFTEST_SUITES = ["test_lab_selftest_core", "test_lab_selftest_firmware", "test_lab_selftest_rtc",
                   "test_lab_selftest_coupling"]
ALL_SUITES = SCENARIO_SUITES + SELFTEST_SUITES + [REPLAY_SUITE]
HELPERS = ["_lab_clock", "_lab_trace", "_lab_fw", "_lab_ha", "_lab_rtc"]
TOP_KEYS = ["schema", "baseline", "tiers", "invariants", "known_risks_used", "scenarios", "findings", "root_causes",
            "negative_controls", "unsupported", "harness_limitations", "coverage_matrix", "runtime_quick_s"]
SCEN_KEYS = ["id", "title", "suite", "tier", "priority", "classification", "grade", "confidence", "confidence_level",
             "invariant", "ownership", "anchors", "failure_outcome", "result_summary", "corpus", "phase_sensitive",
             "phase_sensitive_reason"]
FIND_KEYS = ["fid", "scenario", "suite", "title", "classification", "root_cause_group", "counted", "duplicate_of",
             "reported_as", "severity", "confidence", "confidence_level", "grade", "reachability", "mechanism_verdict",
             "device_reachability", "injected_primitive", "needs_product_change", "needs_product_change_reason",
             "model_dependence", "repair_scope", "corpus", "verification", "phase_sensitive", "phase_sensitive_reason"]
ROOT_KEYS = ["group", "title", "findings", "classification", "severity", "priority", "notes"]
# V0.1 (B3.6): same_mutation_as names the control whose identical mutation the row repeats (null: a distinct mutation)
NC_KEYS = ["id", "suite", "mutation", "target_invariant_or_check", "outcome", "same_mutation_as"]
# the corpus document keys of the two priorities (V0.1; the V0 key 'priority' carried neither consistently)
CORPUS_PRIORITY_KEYS = ("scenario_priority", "finding_priority")
VERIFICATION_KEYS = ["source_fidelity_check", "classification_check"]
HL_KEYS = ["id", "component", "anchor", "limitation", "effect_on_verdicts", "worked_around_in", "status"]
INTERSECTION_KEYS = ["pair", "required", "existing", "lab", "gap"]
REPORTED_AS = ("FINDING", "DUPLICATE", "MERGED")
# negative-control outcomes: an in-suite control the suite runs and prints ('killed', 'survived(expected)'), or an audit
# mutant the lab does not run itself ('killed(audit)': applied in memory to every firmware parse of every suite outside the
# lab; its row names directed checks that failed under it, and those checks must hold in the plain run)
NC_OUTCOMES = ("killed", "survived(expected)", "killed(audit)")
CHECKS_TARGET = "checks: "        # a negative-control target naming suite checks: 'checks: <name prefix>, <name prefix>'
QUICK_BUDGET_S = 90

# ---------------------------------------------------------------------------------------------------------------------------
# public-text rules (every prose field of the catalogue is public)
# ---------------------------------------------------------------------------------------------------------------------------
PROCESS_WORDS = re.compile(r"\b(?:verifiers?|critics?|lens|lenses|reviewers?|hardening pass|two-lens)\b", re.I)
OVERCLAIMS = re.compile(r"\b(?:proves|proved|guarantees|guaranteed)\b|\b(?:is|are|stays|remains) safe\b|safe and complete",
                        re.I)
DECISION = re.compile(r"\bowner(?:'s)? decision\b", re.I)
SYNTHETIC_DATES = {"2026-10-21", "2026-10-22", "2026-10-24", "2026-10-25", "2027-03-28", "2026-11-04", "2026-01-01",
                   "2027-12-31"}
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PATH_WITH_DATE = re.compile(r"[\w./-]*/\d{4}-\d{2}-\d{2}[\w./-]*")
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
DAY_MONTH = re.compile(rf"\b(\d{{1,2}}) ({MONTHS})\b")
SYNTHETIC_DAY_MONTH = {("25", "Oct"), ("28", "Mar")}
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
THIRTEEN = re.compile(r"(?<![0-9])[0-9]{13}(?![0-9])")
METER_WORD = re.compile(r"mpan|meter|octopus|mprn", re.I)
DOTTED_QUAD = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
SIX_GROUPS = re.compile(r"\b\d{2}([-:])\d{2}\1\d{2}\1\d{2}\1\d{2}\1\d{2}\b")
INV_RE = re.compile(r"\bINV-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
NC_TOKEN = re.compile(r"(?<![\w-])(NC-?[0-9A-Z][\w-]*)")

# Public-text replacements applied to every prose field copied from a suite table (exact phrases still present in suite
# texts; the catalogue text is public, the suite keeps its own wording until it is reworded). A replacement that no longer
# matches anything is reported, so a reworded suite makes its entry here obsolete loudly.
PUBLIC_TEXT_REPLACEMENTS = [
    ("so it is an owner design decision", "so it is a design decision"),
    ("and is an owner decision that trades against N17", "and is a design decision that trades against N17"),
    ("under an owner decision", "under a design decision"),
    ("an open S4 / FB-D owner decision", "an open S4 / FB-D design decision"),
    ("any firmware change needs owner design review", "any firmware change needs its own design review"),
    ("the measured bus gives the same end state", "the recorded-busy-window bus gives the same end state"),
    ("above the measured HF-01 lease-tail overrun", "above the simulated HF-01 lease-tail overrun"),
]


class Problems(list):
    def need(self, ok: bool, msg: str) -> None:
        if not ok:
            self.append(msg)


def shape_problems(text: str) -> list[str]:
    """run_lab.py's privacy shapes (the report guard) on one prose or anchor text."""
    return [label for label, rx in run_lab.GUARDS if rx.search(text)]


def prose_problems(text: str) -> list[str]:
    out = [f"shape: {s}" for s in shape_problems(text)]
    for rx, what in ((PROCESS_WORDS, "review-process wording"), (OVERCLAIMS, "overclaim"), (DECISION, "'owner decision'")):
        m = rx.search(text)
        if m:
            out.append(f"{what} {m.group(0)!r}")
    bare = PATH_WITH_DATE.sub("<path>", text)
    for d in DATE.findall(bare):
        if d not in SYNTHETIC_DATES:
            out.append(f"date {d} outside a cited file path (not a synthetic date)")
    for m in DAY_MONTH.finditer(bare):
        if (m.group(1), m.group(2)[:3]) not in SYNTHETIC_DAY_MONTH:
            out.append(f"day-month date {m.group(0)!r}")
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------------
#   (repository files are read through a _lab_trace.TreeReader: build(reader=...); its text() / sha() apply the CRLF -> LF
#   normalisation of a core.autocrlf=true checkout)


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
    return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_constant)


def dumps(cat: dict) -> str:
    return json.dumps(cat, indent=1, ensure_ascii=True, allow_nan=False) + "\n"


def first_word(text) -> str:
    return text.split()[0] if isinstance(text, str) and text.split() else ""


def nc_in_source(nid: str, src: str) -> bool:
    """An NC id occurs in its suite's source, or is one variant of an f-string id (NC1a / NC1b from f"NC1{m}")."""
    return nid in src or re.sub(r"[a-z]$", "{", nid) in src


def checks_target(target: str) -> list[str]:
    """The check-name prefixes of a negative-control target 'checks: <name>, <name>' ([] for any other target)."""
    return target[len(CHECKS_TARGET):].split(", ") if target.startswith(CHECKS_TARGET) else []


def checks_target_ok(target: str, scenario_ids) -> bool:
    """A 'checks: ...' target whose every check-name prefix starts with one of the suite's scenario ids (followed by a
    space or a colon), e.g. 'checks: FW-09 a.1, FW-09 a.2'."""
    names = checks_target(target)
    return bool(names) and all(n.strip() == n and any(n == sid or n.startswith((sid + " ", sid + ":"))
                                                       for sid in scenario_ids) for n in names)


def classification_ok(text) -> bool:
    try:
        T.parse_classification(text)
    except T.LabTraceError:
        return False
    return True


# ---------------------------------------------------------------------------------------------------------------------------
# suite outputs
# ---------------------------------------------------------------------------------------------------------------------------
RUNS_RECORD = "_runs.json"
# v2 (V0.1, B1): the record also holds 'sources', the LF sha256 of every baseline source as the suites ran on it
RUNS_SCHEMA = "ecco-assurance-lab-saved-runs/v2"
HEX64_FULL = re.compile(r"^[0-9a-f]{64}$")


def tree_sources(reader: T.TreeReader | None = None) -> dict[str, str]:
    """{path: LF-normalised sha256} of every file a catalogue baseline can pin, as the tree holds it now: every lab .py
    and corpus document (_lab_trace.LAB_RULE), every file the tier table pins (_lab_trace.pinned_by_table) and every
    path a corpus document pins (missing files are left out). On a tree whose build has no problem this is a superset
    of baseline.sources (an anchored file outside the table is already a build problem). Taken BEFORE the suites run
    (run_all / --save-runs), it records the tree the outputs belong to."""
    R = reader if reader is not None else T.TreeReader(ROOT)
    paths = {f"{LAB_REL}/{p.name}" for p in HERE.glob("*.py")} | set(T.pinned_by_table())
    for p in CORPUS.glob("*.json"):
        rel = f"{LAB_REL}/corpus/{p.name}"
        paths.add(rel)
        try:
            doc = strict_json((R.read_bytes(rel) or b"").decode("utf-8"))
        except ValueError:
            continue                  # not strict JSON: a build problem of its own
        if isinstance(doc, dict) and isinstance(doc.get("source_digests"), dict):
            paths |= {q for q in doc["source_digests"] if T._path_ok(q)}
    return {p: R.sha(p) for p in sorted(paths) if R.exists(p)}


def tree_record_problems(record, pinned: dict, sha_of) -> list[str]:
    """Why suite outputs recorded on the tree `record` ({path: sha256}, None = no record) may not build a catalogue of
    this tree, whose baseline sources are `pinned` ({path: sha256}) and whose current digests sha_of(path) gives (None
    for a missing file): no record at all, or a pinned source whose recorded digest differs (changed since the run,
    added since, or no longer there). [] when the outputs belong to this tree."""
    if not isinstance(record, dict) or not record:
        return ["the suite outputs carry no record of the tree they ran on (the 'sources' digests of a saved-runs record "
                f"{RUNS_RECORD}, written by gen_catalogue.py --save-runs DIR): re-run the suites (gen_catalogue.py "
                "--write runs them)"]
    differ = sorted(p for p in set(pinned) | set(record)
                    if record.get(p) != (pinned[p] if p in pinned else sha_of(p)))
    if differ:
        return [f"the suite outputs were made on another tree: {len(differ)} pinned source(s) differ from their saved-runs "
                f"record ({', '.join(differ[:6])}{' ...' if len(differ) > 6 else ''}): re-run the suites on this tree "
                "(gen_catalogue.py --write runs them; or --save-runs DIR, then --runs-from DIR)"]
    return []


def run_all(parallel: int = 1, timeout: int = run_lab.DEFAULT_TIMEOUT) -> tuple[dict[str, dict], dict[str, str]]:
    """Run every lab suite through run_lab.run_suites (quick mode) and keep each output in memory: (runs, run_tree),
    run_tree the tree_sources() record taken just BEFORE the suites run."""
    run_tree = tree_sources()
    paths = [HERE / f"{s}.py" for s in ALL_SUITES]
    results, _wall = run_lab.run_suites(paths, parallel, timeout, False)
    return {r["stem"]: {"text": r["text"], "rc": r["rc"], "parallel": parallel} for r in results}, run_tree


def load_runs(directory: Path, assert_sequential: bool = False) -> tuple[dict[str, dict], dict[str, str]]:
    """Saved quick-run outputs: (runs, run_tree) from DIR/<suite>.txt (or .out) for every lab suite and the saved-runs
    record DIR/_runs.json written by save_runs: its 'parallel' value, each suite's exit code and 'sources', the tree the
    suites ran on (build() refuses outputs whose record differs from this tree). A missing record, a malformed one, a
    record without 'sources' (v1) or one that contradicts assert_sequential (--runs-sequential) raises SystemExit (usage
    error, nothing built): outputs that cannot be tied to a tree are refused."""
    rec_path = directory / RUNS_RECORD
    if not rec_path.is_file():
        raise SystemExit(f"--runs-from: {directory.name}/{RUNS_RECORD} is missing: saved outputs that carry no record of "
                         "the tree they ran on are refused (save them with gen_catalogue.py --save-runs DIR)")
    try:
        meta = strict_json(rec_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SystemExit(f"--runs-from: {RUNS_RECORD} is not strict JSON ({exc})") from None
    if isinstance(meta, dict) and meta.get("schema") == "ecco-assurance-lab-saved-runs/v1":
        raise SystemExit(f"--runs-from: {RUNS_RECORD} is a v1 record without the tree digests ('sources'): the outputs "
                         "cannot be tied to a tree; re-run the suites with gen_catalogue.py --save-runs DIR")
    ok = (isinstance(meta, dict) and meta.get("schema") == RUNS_SCHEMA and type(meta.get("parallel")) is int
          and meta["parallel"] >= 1 and isinstance(meta.get("rc"), dict) and isinstance(meta.get("sources"), dict)
          and meta["sources"] and all(isinstance(k, str) and T._path_ok(k) and isinstance(v, str) and HEX64_FULL.match(v)
                                      for k, v in meta["sources"].items()))
    if not ok:
        raise SystemExit(f"--runs-from: {RUNS_RECORD} is not a {RUNS_SCHEMA} record (schema, parallel, rc, sources)")
    if assert_sequential and meta["parallel"] != 1:
        raise SystemExit(f"--runs-sequential: {RUNS_RECORD} records --parallel {meta['parallel']}, not a sequential run")
    out = {}
    for s in ALL_SUITES:
        for ext in (".txt", ".out"):
            f = directory / f"{s}{ext}"
            if f.is_file():
                out[s] = {"text": f.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n"),
                          "rc": meta["rc"].get(s), "parallel": meta["parallel"]}
                break
    return out, dict(meta["sources"])


def inside_repo(directory: Path) -> bool:
    try:
        directory.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def save_runs(runs: dict[str, dict], directory: Path, parallel: int, run_tree: dict[str, str]) -> None:
    """Keep each suite's output as DIR/<suite>.txt and the saved-runs record DIR/_runs.json (the --parallel value, each
    suite's exit code and 'sources': run_tree, the LF sha256 of every baseline source as the suites ran on it), so a
    later --runs-from knows whether the runtimes are sequential and which tree the outputs belong to; refused inside the
    repository (nothing is written there)."""
    if inside_repo(directory):
        raise SystemExit(f"--save-runs: {directory} is inside the repository; choose a directory outside it")
    if not isinstance(run_tree, dict) or not run_tree:
        raise SystemExit("--save-runs: no record of the tree the suites ran on (internal error)")
    d = directory.resolve()
    d.mkdir(parents=True, exist_ok=True)
    for s, r in runs.items():
        (d / f"{s}.txt").write_bytes(r["text"].encode("utf-8"))
    record = {"schema": RUNS_SCHEMA, "parallel": parallel, "mode": "quick",
              "rc": {s: (r["rc"] if isinstance(r["rc"], int) else str(r["rc"])) for s, r in sorted(runs.items())},
              "sources": dict(sorted(run_tree.items()))}
    (d / RUNS_RECORD).write_bytes((json.dumps(record, indent=1, sort_keys=True) + "\n").encode("ascii"))


# ---------------------------------------------------------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class Build:
    cat: dict
    text: str
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    docs: dict = field(default_factory=dict)      # the corpus documents the build read ({id: document})
    missing: list = field(default_factory=list)   # pinned sources absent from this tree (left out of baseline.sources)


# The replay suite owns no scenario: a negative control of its own names checks of its drift rule (section [5]), whose
# names all start with _lab_trace.DRIFT_CHECK, or its tier-pin checks (section [2], _lab_trace.TIER_PIN_CHECK);
# gen_catalogue and test_lab_replay_corpus accept those prefixes for it.
REPLAY_CHECK_PREFIXES = (T.DRIFT_CHECK, T.TIER_PIN_CHECK)


def phase_pass(P: Problems, clean, scenarios: list[dict], findings: list[dict], docs: dict, mods: dict) -> None:
    """Set phase_sensitive / phase_sensitive_reason from _catalogue_data.PHASE_SENSITIVE ({scenario or finding id:
    (reason, [tag prefixes])}) and cross-check it against the scenario suites' PHASE_SENSITIVE_TAGS registries (static):
    every listed prefix is a registered tag of the entry's suite, and every registered tag of a scenario suite is either
    listed by some entry or a pure corpus trace-digest pin (its reason is that suite's _PS_DIGEST text and it names a
    corpus document of a scenario of that suite). A scenario or finding not listed keeps phase_sensitive false with an
    empty reason: none of its verdicts is phase-tagged beyond the trace-digest pins every corpus document carries."""
    entries = {x["id"]: x for x in scenarios}
    entries.update({f["fid"]: f for f in findings})
    owner = {c: x for x in scenarios for c in x["corpus"]}
    tags, listed = {}, {}
    for s in SCENARIO_SUITES:
        has = mods[s].has("PHASE_SENSITIVE_TAGS")
        tags[s] = A.jsonable(mods[s].get("PHASE_SENSITIVE_TAGS")) if has else {}
        P.need(has and isinstance(tags[s], dict), f"{s}: no PHASE_SENSITIVE_TAGS registry (a dict literal)")
        listed[s] = set()
    for eid, (reason, prefixes) in G.PHASE_SENSITIVE.items():
        e = entries.get(eid)
        if e is None:
            P.append(f"PHASE_SENSITIVE {eid}: not a catalogue scenario or finding")
            continue
        s = e["suite"]
        P.need(bool(prefixes), f"PHASE_SENSITIVE {eid}: no tag prefix")
        for p in prefixes:
            P.need(p in tags.get(s, {}), f"PHASE_SENSITIVE {eid}: {p!r} is not a PHASE_SENSITIVE_TAGS prefix of {s}")
            listed.setdefault(s, set()).add(p)
        e["phase_sensitive"] = True
        e["phase_sensitive_reason"] = clean(reason, f"{eid}.phase_sensitive_reason")
        P.need(bool(e["phase_sensitive_reason"]), f"PHASE_SENSITIVE {eid}: empty reason")
    stems = {stem: re.compile(rf"(?<![\w-]){re.escape(stem)}(?![\w-])") for stem in docs}
    for s in SCENARIO_SUITES:
        digest_reason = A.jsonable(mods[s].get("_PS_DIGEST")) if mods[s].has("_PS_DIGEST") else None
        for p, why in tags[s].items():
            if p in listed[s]:
                continue
            named = [stem for stem, rx in stems.items() if rx.search(p)]
            pure = (digest_reason is not None and why == digest_reason and len(named) == 1
                    and owner.get(named[0], {}).get("suite") == s)
            P.need(pure, f"{s}: phase-sensitivity tag {p!r} is neither listed by _catalogue_data.PHASE_SENSITIVE nor a "
                         "pure corpus trace-digest pin (reason _PS_DIGEST, naming one corpus document of this suite)")


def suite_output(s: str, r: dict, sequential: bool) -> tuple[dict | None, list[str], list[str]]:
    """(LAB-SUMMARY record or None, problems, warnings) of one suite's quick-run output r = {"text", "rc", ...}: the same
    checks as run_lab.judge (a strictly parsed V0.1 LAB-SUMMARY, its counts against the printed lines, the FAILED line /
    LAB-SUMMARY order, quick mode; for every suite but the replay suite also exit code 0 or unknown, fail 0 and no FAIL
    line at all), and the 90 s quick budget: a problem for sequential outputs, a warning otherwise."""
    problems: list[str] = []
    warnings: list[str] = []
    lines = r["text"].splitlines()
    rec, why = run_lab.parse_summary(s, lines)
    if rec is None:
        return None, [f"{s}: {why}"], []
    problems += [f"{s}: {p}" for p in run_lab.output_problems(lines, rec)]
    modes = [m.group(1) for m in (run_lab.MODE_RE.match(ln) for ln in lines) if m]
    if modes[:1] != ["quick"]:
        problems.append(f"{s}: the output is not a quick-mode run ({modes[:1]})")
    if s != REPLAY_SUITE:
        n_fail_lines = run_lab.scan_output(lines)["fail_lines"]
        if rec["fail"] != 0 or r.get("rc") not in (0, None):
            problems.append(f"{s}: the run failed (rc {r.get('rc')}, fail {rec['fail']})")
        if n_fail_lines:
            problems.append(f"{s}: {n_fail_lines} FAIL line(s) printed (a FAIL line fails the suite, whatever its exit "
                            "code)")
    rt = round(float(rec["runtime_s"]), 1)
    if not 0 < rt <= QUICK_BUDGET_S:
        msg = f"{s}: quick runtime {rt} s outside (0, {QUICK_BUDGET_S}] s"
        if sequential:
            problems.append(msg)
        else:
            warnings.append(msg + " in a run that is not sequential (not judged against the budget, not stored)")
    return rec, problems, warnings


def build(runs: dict[str, dict] | None = None, committed: dict | None = None, *, reader: T.TreeReader | None = None,
          for_write: bool = False, run_tree: dict[str, str] | None = None) -> Build:
    """The catalogue from the sources (and the suite outputs, unless runs is None: static mode, where the run-derived
    checks are skipped and runtime_quick_s is taken from `committed`). runs that are not all sequential (parallel 1)
    keep `committed`'s runtime_quick_s too, and their runtimes are only warned about (see the module docstring). With
    runs, run_tree must be the record of the tree they ran on and equal this tree's baseline sources
    (tree_record_problems), else that is a problem. Every anchored, pinned or cited repository file, and every corpus
    document, is read through `reader` (a _lab_trace.TreeReader of this tree by default; test_lab_replay_corpus passes
    one with an in-memory overlay for its end-to-end drift controls). A corpus document whose recorded digest differs
    from this tree is a problem when the committed catalogue does not hold that digest either (or always, for_write: a
    catalogue must not be written over a stale pin); when the committed catalogue holds it, the tree changed and
    compare() judges it by the tiered drift rule."""
    P, notes, warnings = Problems(), [], []
    R = reader if reader is not None else T.TreeReader(ROOT)
    static = runs is None
    sequential = not static and bool(runs) and all(r.get("parallel") == 1 for r in runs.values())
    skipped = (["negative-control outcomes in the suite outputs", "FINDING / DUPLICATE / merge lines in the suite outputs",
                "counted findings per suite against LAB-SUMMARY", "quick runtimes (reused from the committed catalogue)"]
               if static else [])

    used_replacements = set()

    def clean(text, where: str) -> str:
        if not isinstance(text, str):
            P.append(f"{where}: not a string: {text!r}"[:200])
            return ""
        text = " ".join(text.split())
        for old, new in PUBLIC_TEXT_REPLACEMENTS:
            if old in text:
                text = text.replace(old, new)
                used_replacements.add(old)
        for p in prose_problems(text):
            P.append(f"{where}: {p}")
        return text

    def anchor_str(path: str, snippet: str, where: str) -> str:
        for s in shape_problems(path + " " + snippet):
            P.append(f"{where}: anchor shape: {s}")
        src = R.text(path) if T._path_ok(path) else None
        n = src.count(snippet) if src is not None and snippet else -1
        P.need(n == 1, f"{where}: anchor found {n} time(s) in {path}: {snippet[:70]!r}")
        return f"{path}: {snippet}"

    # ---- sources (static evaluation, never imported)
    core = {n: A.Module(HERE / f"{n}.py") for n in HELPERS}
    aliases = {"C": core["_lab_clock"], "T": core["_lab_trace"], "L": core["_lab_fw"], "H": core["_lab_ha"],
               "R": core["_lab_rtc"]}
    mods = {s: A.Module(HERE / f"{s}.py", aliases=aliases) for s in SCENARIO_SUITES}
    src = {s: (HERE / f"{s}.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
           for s in SCENARIO_SUITES + SELFTEST_SUITES + HELPERS + [REPLAY_SUITE]}

    def tab(suite: str, name: str):
        return A.jsonable(mods[suite].get(name))

    docs = {}
    for p in sorted(CORPUS.glob("*.json")):
        try:
            docs[p.stem] = strict_json((R.read_bytes(f"{LAB_REL}/corpus/{p.name}") or b"").decode("utf-8"))
        except ValueError as exc:
            P.append(f"corpus {p.stem}: not strict JSON ({exc})")

    scenarios: list[dict] = []
    findings: list[dict] = []

    def level(confidence: str, where: str) -> str:
        lv = first_word(confidence)
        P.need(lv in T.CONFIDENCES, f"{where}: confidence {confidence!r} does not start with one of {T.CONFIDENCES}")
        return lv

    def scenario(suite, sid, *, title, tier, priority, classification, grade, confidence, invariant, ownership, anchors,
                 failure_outcome, corpus, result_summary=None):
        w = f"{suite}:{sid}"
        if result_summary is None:
            P.need(sid in G.RESULT_SUMMARY, f"{w}: no result summary in _catalogue_data.RESULT_SUMMARY")
            result_summary = G.RESULT_SUMMARY.get(sid, "")
        for fld, val, ok in (("tier", tier, tier in T.TIERS), ("priority", priority, priority in T.PRIORITIES),
                             ("classification", classification, classification_ok(classification)),
                             ("grade", grade, grade in T.GRADES)):
            P.need(ok, f"{w}: {fld} {val!r} is not lab vocabulary")
        scenarios.append({
            "id": sid, "title": clean(title, w + ".title"), "suite": suite, "tier": tier, "priority": priority,
            "classification": classification, "grade": grade, "confidence": clean(confidence, w + ".confidence"),
            "confidence_level": level(confidence, w),
            "invariant": clean(invariant, w + ".invariant"), "ownership": clean(ownership, w + ".ownership"),
            "anchors": [anchor_str(p, t, w) for p, t in anchors],
            "failure_outcome": clean(failure_outcome, w + ".failure_outcome"),
            "result_summary": clean(result_summary, w + ".result_summary"),
            "corpus": list(corpus), "phase_sensitive": False, "phase_sensitive_reason": ""})   # set by phase_pass()

    def finding(suite, fid, *, scenario_id, title, classification, duplicate_of, severity, confidence, grade, reachability,
                model_dependence, repair_scope, corpus, counted=None, merged=False):
        w = f"{suite}:{fid}"
        dup = duplicate_of or None
        P.need(fid in G.VERIFICATION, f"{w}: no verification summary in _catalogue_data.VERIFICATION")
        vsrc, vcls = G.VERIFICATION.get(fid, ("", ""))
        cnt = (dup is None) if counted is None else counted
        # FINDING: counted, printed '  FINDING  <fid>'; DUPLICATE: printed '  FINDING  <fid> ... DUPLICATE of <owner>',
        # not counted; MERGED: a variant recorded under its owner, the suite prints NO FINDING line for it
        reported = "MERGED" if merged else ("FINDING" if cnt else "DUPLICATE")
        P.need(classification_ok(classification) and grade in T.GRADES, f"{w}: classification / grade not lab vocabulary")
        # two-axis verdicts (B6.4): a counted finding is graded here; a DUPLICATE / MERGED entry through its owner (null)
        prim = G.PRIMITIVES.get(fid)
        P.need(isinstance(prim, tuple) and len(prim) == 2, f"{w}: no (class, text) injected primitive in "
                                                           "_catalogue_data.PRIMITIVES")
        verdict = G.VERDICTS.get(fid)
        if cnt:
            P.need(isinstance(verdict, tuple) and len(verdict) == 4, f"{w}: a counted finding without its two-axis "
                                                                      "verdicts in _catalogue_data.VERDICTS")
        else:
            P.need(verdict is None, f"{w}: two-axis verdicts in _catalogue_data.VERDICTS for a {reported} entry (it is "
                                    "graded through its owner)")
        mv, dr, npc, why = verdict if cnt and isinstance(verdict, tuple) and len(verdict) == 4 else (None,) * 4
        findings.append({
            "fid": fid, "scenario": scenario_id, "suite": suite, "title": clean(title, w + ".title"),
            "classification": classification, "root_cause_group": None,
            "counted": cnt, "duplicate_of": dup, "reported_as": reported,
            "severity": clean(severity, w + ".severity"), "confidence": clean(confidence, w + ".confidence"),
            "confidence_level": level(confidence, w),
            "grade": grade, "reachability": clean(reachability, w + ".reachability"),
            "mechanism_verdict": mv, "device_reachability": dr,
            "injected_primitive": clean(prim[1], w + ".injected_primitive") if isinstance(prim, tuple) and len(prim) == 2
            else "",
            "needs_product_change": npc,
            "needs_product_change_reason": clean(why, w + ".needs_product_change_reason") if why is not None else None,
            "model_dependence": clean(model_dependence, w + ".model_dependence"),
            "repair_scope": clean(repair_scope, w + ".repair_scope"), "corpus": list(corpus),
            "verification": {"source_fidelity_check": clean(vsrc, w + ".verification"),
                             "classification_check": clean(vcls, w + ".verification")},
            "phase_sensitive": False, "phase_sensitive_reason": ""})   # set by phase_pass()

    def tier_of(sid: str) -> str:
        if sid.startswith("FW-") or sid in ("PB-01", "PB-03"):
            return "firmware"
        if sid.startswith("HF-") or sid == "PB-02":
            return "coupled"
        return "rtc"

    # --- test_lab_fw_obligations ------------------------------------------------------------------------------------------
    s = "test_lab_fw_obligations"
    paths, anch = tab(s, "PATHS"), tab(s, "ANCHORS")
    for x in tab(s, "SCENARIOS"):
        scenario(s, x["id"], title=x["title"], tier="firmware", priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=[(paths[anch[k][0]], anch[k][1]) for k in x["anchors"]], failure_outcome=x["failure_outcome"],
                 corpus=x["corpus"])
    for f in tab(s, "FINDINGS"):
        finding(s, f["fid"], scenario_id=f["scenario"], title=f["title"], classification=f["classification"],
                duplicate_of=f["duplicate_of"], severity=f["severity"], confidence=f["confidence"], grade=f["grade"],
                reachability=f["reachability"], model_dependence=G.MODEL_DEPENDENCE.get(f["fid"], ""),
                repair_scope=f["repair_scope"], corpus=G.FINDING_CORPUS.get(f["fid"], []))

    # --- test_lab_fw_durability -------------------------------------------------------------------------------------------
    s = "test_lab_fw_durability"
    sc = {x["id"]: x for x in tab(s, "SCENARIOS")}
    for x in sc.values():
        scenario(s, x["id"], title=x["title"], tier="firmware", priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=x["anchors"], failure_outcome=x["failure_outcome"], corpus=x["corpus"])
    for fid, f in tab(s, "FINDINGS").items():
        finding(s, fid, scenario_id=f["scenario"], title=f["title"], classification=f["classification"],
                duplicate_of=f.get("duplicate_of"), severity=f["severity"], confidence=f["confidence"],
                grade=sc[f["scenario"]]["grade"], reachability=f["reachability"],
                model_dependence=G.MODEL_DEPENDENCE.get(fid, ""), repair_scope=f["repair"], corpus=[f["corpus"]])

    # --- test_lab_fw_runtime ----------------------------------------------------------------------------------------------
    s = "test_lab_fw_runtime"
    sc = tab(s, "SCENARIOS")
    dup_rt = tab(s, "DUPLICATE_OF")
    for sid, x in sc.items():
        scenario(s, sid, title=x["title"], tier="firmware", priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=x["anchors"], failure_outcome=x["failure_outcome"], corpus=x["corpus"])
    owned: dict[str, list] = {}
    for sid, x in sc.items():
        if x.get("finding"):
            owned.setdefault(x["finding"], []).append(sid)
    P.need(sorted(owned) == sorted(G.FW_RUNTIME_FINDINGS),
           f"{s}: scenario findings {sorted(owned)} != _catalogue_data.FW_RUNTIME_FINDINGS {sorted(G.FW_RUNTIME_FINDINGS)}")
    for fid, h in G.FW_RUNTIME_FINDINGS.items():
        x = sc.get(h["scenario"], {})
        P.need(h["scenario"] in owned.get(fid, []), f"{s}: {fid} is not a finding of {h['scenario']}")
        incidental = x.get("classification") == "PASS"   # a finding of a PASS scenario carries its own fields
        if incidental:
            P.need(all(k in h for k in ("classification", "grade", "confidence", "corpus")),
                   f"{s}: incidental {fid} of PASS scenario {h['scenario']} needs classification / grade / confidence / "
                   "corpus in _catalogue_data")
        corpus = h.get("corpus", x.get("corpus", []))
        repair = docs.get(corpus[0], {}).get("smallest_safe_repair_scope", "") if corpus else ""
        finding(s, fid, scenario_id=h["scenario"], title=h["title"],
                classification=h.get("classification", x.get("classification", "")), duplicate_of=dup_rt.get(fid),
                severity=h["severity"], confidence=h.get("confidence", x.get("confidence", "")),
                grade=h.get("grade", x.get("grade", "")), reachability=h["reachability"],
                model_dependence=h.get("model_dependence", x.get("model", "")), repair_scope=repair, corpus=corpus)

    # --- test_lab_fw_guards (FW-09..FW-11: every scenario is a PASS scenario; the suite keeps no finding table) -----------
    s = "test_lab_fw_guards"
    sc = tab(s, "SCENARIOS")
    P.need(all(x.get("finding") is None for x in sc.values()) and not tab(s, "FINDINGS") and not tab(s, "DUPLICATE_OF"),
           f"{s}: a scenario names a finding, or FINDINGS / DUPLICATE_OF is not empty (the catalogue reads no finding "
           "of this suite: add a reader for it first)")
    for sid, x in sc.items():
        scenario(s, sid, title=x["title"], tier="firmware", priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=x["anchors"], failure_outcome=x["failure_outcome"], corpus=x["corpus"])

    # --- test_lab_ha_lifecycle --------------------------------------------------------------------------------------------
    s = "test_lab_ha_lifecycle"
    for x in tab(s, "SCENARIOS"):
        scenario(s, x["id"], title=x["title"], tier="coupled", priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=x["anchors"], failure_outcome=x["failure_outcome"], corpus=x["corpus"])
    for fid, f in tab(s, "FINDINGS").items():
        finding(s, fid, scenario_id=f["scenario"], title=f["title"], classification=f["classification"], duplicate_of=None,
                severity=f["severity"], confidence=f["confidence"], grade=f["grade"], reachability=f["reachability"],
                model_dependence=G.MODEL_DEPENDENCE.get(fid, ""), repair_scope=f["repair"],
                corpus=G.FINDING_CORPUS.get(fid, []))

    # --- test_lab_ha_phantom ----------------------------------------------------------------------------------------------
    s = "test_lab_ha_phantom"
    anch = tab(s, "ANCHORS")
    x = tab(s, "SCENARIOS")[0]
    scenario(s, x["id"], title=x["title"], tier="coupled", priority=x["priority"], classification=x["classification"],
             grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
             anchors=[tuple(anch[k]) for k in x["anchors"]], failure_outcome=x["failure_outcome"], corpus=x["corpus"])
    # a MERGED variant (V0.1: F-HF07-2, the DGS1 mirror instance of F-HF07-1) names its owner in 'merged_into', is in
    # neither the scenario's counted list nor its duplicates, and is recorded in the scenario's 'merged' map and the
    # suite's MERGED table ('merged into <owner> ...'); it prints no FINDING line (checked on the run below)
    spec_ph = tab(s, "FINDINGS_SPEC")
    merged_ph = {fid: f.get("merged_into") for fid, f in spec_ph.items() if f.get("merged_into")}
    P.need((x.get("merged") or {}) == merged_ph, f"{s}: SCENARIOS[0]['merged'] {x.get('merged')} != the merged_into "
                                                  f"records of FINDINGS_SPEC {merged_ph}")
    table_ph = tab(s, "MERGED") if mods[s].has("MERGED") else {}
    P.need(sorted(table_ph) == sorted(merged_ph) and all(str(table_ph[f]).startswith(f"merged into {o} ")
                                                         for f, o in merged_ph.items() if f in table_ph),
           f"{s}: the MERGED table {sorted(table_ph)} does not record exactly the merged variants {sorted(merged_ph)} as "
           "'merged into <owner> ...'")
    for fid, f in spec_ph.items():
        owner = f.get("merged_into")
        P.need((fid in x["counted"]) == (f["duplicate_of"] is None and owner is None),
               f"{s}: counted list, duplicate_of and merged_into disagree for {fid}")
        P.need(f["duplicate_of"] is None or owner is None, f"{s}: {fid} is both a duplicate and a merged variant")
        finding(s, fid, scenario_id=x["id"], title=f["title"], classification=f["classification"],
                duplicate_of=f["duplicate_of"] or owner, severity=f["severity"], confidence=f["confidence"],
                grade=f["grade"], reachability=f["reachability"], model_dependence=f["model_dependence"],
                repair_scope=f["repair_scope"], corpus=[f["corpus"]], counted=fid in x["counted"],
                merged=owner is not None)

    # --- test_lab_ha_schedules --------------------------------------------------------------------------------------------
    s = "test_lab_ha_schedules"
    anch = tab(s, "ANCHORS")
    sc = {x["id"]: x for x in tab(s, "SCENARIOS")}
    dup_hs = tab(s, "DUPLICATE_OF")
    for x in sc.values():
        scenario(s, x["id"], title=x["title"], tier="coupled", priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=[tuple(anch[k]) for k in x["anchors"]], failure_outcome=x["failure_outcome"], corpus=x["corpus"],
                 result_summary=x["result"])
    for fid, f in tab(s, "FINDINGS").items():
        finding(s, fid, scenario_id=f["scenario"], title=f["title"], classification=f["classification"],
                duplicate_of=dup_hs.get(fid), severity=f["severity"], confidence=f["confidence"],
                grade=sc[f["scenario"]]["grade"], reachability=f["reachability"], model_dependence=f["model_dependence"],
                repair_scope=f["repair"], corpus=f["corpus"])

    # --- test_lab_dst_rtc -------------------------------------------------------------------------------------------------
    s = "test_lab_dst_rtc"
    sc = {x["id"]: x for x in tab(s, "SCENARIOS")}
    for x in sc.values():
        scenario(s, x["id"], title=x["title"], tier=tier_of(x["id"]), priority=x["priority"],
                 classification=x["classification"], grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"],
                 ownership=x["ownership"], anchors=x["anchors"], failure_outcome=x["failure_outcome"], corpus=x["corpus"])
    for fid, f in tab(s, "FINDINGS_META").items():
        finding(s, fid, scenario_id="HF-08", title=G.DST_RTC_TITLES.get(fid, ""), classification=f["classification"],
                duplicate_of=None, severity=f["severity"], confidence=f["confidence"], grade=sc["HF-08"]["grade"],
                reachability=f["reachability"], model_dependence=G.MODEL_DEPENDENCE.get(fid, ""), repair_scope=f["repair"],
                corpus=G.FINDING_CORPUS.get(fid, []))
    h = G.F_RT03_1      # its record in the suite's RECLASSIFIED table is checked by the reclassification pass below
    finding(s, "F-RT03-1", scenario_id=h["scenario"], title=h["title"], classification=h["classification"],
            duplicate_of=h["duplicate_of"], severity=h["severity"], confidence=h["confidence"], grade=sc["RT-03"]["grade"],
            reachability=h["reachability"], model_dependence=G.MODEL_DEPENDENCE.get("F-RT03-1", ""),
            repair_scope=h["repair_scope"], corpus=G.FINDING_CORPUS.get("F-RT03-1", []), counted=False, merged=True)
    P.need(G.RECLASSIFIED.get("F-RT03-1") == (s, f"merged into {h['duplicate_of']}"),
           f"{s}: F-RT03-1 is no longer recorded in _catalogue_data.RECLASSIFIED as merged into {h['duplicate_of']}")

    # --- test_lab_property ------------------------------------------------------------------------------------------------
    s = "test_lab_property"
    sc = tab(s, "SCENARIOS")
    for sid, x in sc.items():
        scenario(s, sid, title=x["title"], tier=x["tier"], priority=x["priority"], classification=x["classification"],
                 grade=x["grade"], confidence=x["confidence"], invariant=x["invariant"], ownership=x["ownership"],
                 anchors=x["anchors"], failure_outcome=x["failure_outcome"], corpus=x["corpus"])
    for _sig, f in tab(s, "PB01_FINDINGS").items():
        fid = f["fid"] + (f":{f['variant']}" if f.get("variant") else "")
        finding(s, fid, scenario_id="PB-01", title=f["title"], classification=f["classification"],
                duplicate_of=f["duplicate_of"], severity=f["severity"], confidence=f["confidence"], grade=sc["PB-01"]["grade"],
                reachability=f["reachability"], model_dependence=G.MODEL_DEPENDENCE.get(fid, ""), repair_scope=f["repair"],
                corpus=[f["corpus"]])

    for f in findings:
        P.need(f["fid"] in G.MODEL_DEPENDENCE or f["model_dependence"], f"{f['fid']}: no model dependence text")

    # ---- reclassification records (_catalogue_data.RECLASSIFIED): each suite's own RECLASSIFIED table holds exactly the
    #      ids recorded for it, each text starting with the recorded verdict; a PASS-reclassified id (F-RT02-1, F-HF05-1)
    #      is no catalogue finding, a 'merged into <owner>' id (F-RT03-1) is that owner's MERGED ledger entry
    fby0 = {f["fid"]: f for f in findings}
    recl_suites = sorted({suite for suite, _v in G.RECLASSIFIED.values()})
    for s in recl_suites:
        want = {fid: v for fid, (suite, v) in G.RECLASSIFIED.items() if suite == s}
        have = tab(s, "RECLASSIFIED") if s in mods and mods[s].has("RECLASSIFIED") else None
        P.need(isinstance(have, dict) and sorted(have) == sorted(want),
               f"{s}: its RECLASSIFIED table {sorted(have) if isinstance(have, dict) else have} is not exactly the "
               f"reclassification records {sorted(want)} (_catalogue_data.RECLASSIFIED)")
        for fid, v in want.items():
            P.need(str((have or {}).get(fid, "")).startswith(v), f"{s}: RECLASSIFIED[{fid!r}] does not start with {v!r}")
            if v == "PASS":
                P.need(fid not in fby0, f"{fid}: reclassified PASS (documented, not counted) but still a catalogue finding")
            else:
                owner = v[len("merged into "):] if v.startswith("merged into ") else None
                f = fby0.get(fid)
                P.need(owner is not None and f is not None and f["reported_as"] == "MERGED" and f["duplicate_of"] == owner,
                       f"{fid}: reclassified {v!r} but not the MERGED ledger entry of that owner")
    for s in SCENARIO_SUITES:
        P.need(s in recl_suites or not mods[s].has("RECLASSIFIED"),
               f"{s}: a RECLASSIFIED table without _catalogue_data.RECLASSIFIED records")
    # no stale key in the hand-written per-finding tables (a reclassified or renamed id must leave them)
    for name in ("VERIFICATION", "MODEL_DEPENDENCE", "FINDING_CORPUS", "DST_RTC_TITLES", "PRIMITIVES", "VERDICTS"):
        stale_keys = sorted(set(getattr(G, name)) - set(fby0))
        P.need(not stale_keys, f"_catalogue_data.{name}: stale key(s) {stale_keys} (no catalogue finding)")

    # ---- phase sensitivity: phase_sensitive / phase_sensitive_reason of the scenarios and findings listed in
    #      _catalogue_data.PHASE_SENSITIVE, cross-checked against each scenario suite's PHASE_SENSITIVE_TAGS registry
    phase_pass(P, clean, scenarios, findings, docs, mods)

    # ---- root causes
    fby = {f["fid"]: f for f in findings}
    P.need(len(fby) == len(findings), "duplicate finding ids")
    roots = []
    for rc in G.ROOT_CAUSES:
        if not (isinstance(rc, tuple) and len(rc) == 6):
            P.append(f"root {rc[0] if rc else rc!r}: not a (group, title, members, severity, priority, notes) tuple")
            continue
        gid, title, members, severity, priority, notes = rc
        notes_out = []
        P.need(isinstance(notes, list), f"root {gid}: notes is not a list")
        for i, n in enumerate(notes if isinstance(notes, list) else []):
            P.need(isinstance(n, str) and any(n.startswith(t + " ") for t in G.NOTE_TAGS),
                   f"root {gid}: note {i + 1} does not start with a _catalogue_data.NOTE_TAGS tag and a space")
            notes_out.append(clean(n, f"{gid}.notes[{i + 1}]"))
        for m in members:
            P.need(m in fby, f"root {gid}: unknown finding {m}")
            if m in fby:
                P.need(fby[m]["root_cause_group"] is None, f"{m} is in two root-cause groups")
                fby[m]["root_cause_group"] = gid
        classes = {fby[m]["classification"] for m in members if m in fby}
        P.need(len(classes) == 1, f"root {gid}: members carry different classifications {classes}")
        P.need(any(fby[m]["counted"] for m in members if m in fby), f"root {gid}: no counted member")
        P.need(priority in T.PRIORITIES, f"root {gid}: priority {priority!r}")
        roots.append({"group": gid, "title": clean(title, gid), "findings": list(members),
                      "classification": sorted(classes)[0] if classes else "", "severity": clean(severity, gid),
                      "priority": priority, "notes": notes_out})
    for f in findings:
        P.need(f["root_cause_group"] is not None, f"{f['fid']} has no root-cause group")
        if f["duplicate_of"]:
            o = fby.get(f["duplicate_of"])
            P.need(o is not None and o["counted"], f"{f['fid']}: duplicate_of {f['duplicate_of']} is not a counted finding")
            P.need(o is not None and o["root_cause_group"] == f["root_cause_group"],
                   f"{f['fid']}: not in its owner's root-cause group")
    for t, meaning in G.NOTE_TAGS.items():
        P.need(re.fullmatch(r"\[[a-z0-9.,\- ]+\]", t) is not None, f"NOTE_TAGS: malformed tag {t!r}")
        clean(meaning, f"NOTE_TAGS {t}")

    # ---- two-axis verdicts (B6.4) and the NVS reachability-text rule (B5.5 / B6.3)
    for name in ("MECHANISM_VERDICTS", "DEVICE_REACHABILITY", "PRODUCT_CHANGE"):
        ours, theirs = tuple(getattr(G, name)), getattr(run_lab, name)
        P.need(ours == theirs, f"_catalogue_data.{name} {ours} != run_lab.{name} {theirs} (the report's vocabulary)")
        for v, meaning in getattr(G, name).items():
            clean(meaning, f"_catalogue_data.{name} {v}")
    for c, meaning in G.PRIMITIVE_CLASSES.items():
        clean(meaning, f"_catalogue_data.PRIMITIVE_CLASSES {c}")
    P.need(tuple(k for k in FIND_KEYS if k in run_lab.VERDICT_FIELDS) == run_lab.VERDICT_FIELDS
           and FIND_KEYS[FIND_KEYS.index("reachability") + 1:FIND_KEYS.index("reachability") + 6]
           == list(run_lab.VERDICT_FIELDS), "the two-axis finding keys are not run_lab.VERDICT_FIELDS after 'reachability'")
    P.need(set(G.NVS_REACHABILITY_TEXT) <= set(G.DEVICE_REACHABILITY)
           and all(t.startswith("trigger: {primitive}; device reachability: " + g) for g, t in
                   G.NVS_REACHABILITY_TEXT.items()), "_catalogue_data.NVS_REACHABILITY_TEXT: malformed")
    P.need(set(G.NVS_REACHABILITY_GROUPS) <= {r["group"] for r in roots}
           and set(G.NVS_REACHABILITY_GROUPS.values()) <= set(G.NVS_REACHABILITY_TEXT),
           "_catalogue_data.NVS_REACHABILITY_GROUPS names an unknown group or a grade without a reachability text")
    for f in findings:
        w = f"{f['suite']}:{f['fid']}"
        prim = G.PRIMITIVES.get(f["fid"])
        pcls = prim[0] if isinstance(prim, tuple) and len(prim) == 2 else None
        P.need(pcls in G.PRIMITIVE_CLASSES, f"{w}: primitive class {pcls!r} is not in _catalogue_data.PRIMITIVE_CLASSES")
        kind = run_lab.primitive_kind(f["injected_primitive"])
        want_kind = pcls if pcls in ("nvs", "none") else "other"
        P.need(bool(f["injected_primitive"]) and kind == want_kind,
               f"{w}: injected_primitive {f['injected_primitive'][:50]!r} reads as {kind!r} (run_lab.primitive_kind: 'nvs ' "
               f"/ 'boot ' -> nvs, 'none' -> none) but its class is {pcls!r}")
        if f["counted"]:
            for fld, vocab in (("mechanism_verdict", G.MECHANISM_VERDICTS), ("device_reachability", G.DEVICE_REACHABILITY),
                               ("needs_product_change", G.PRODUCT_CHANGE)):
                P.need(f[fld] in vocab, f"{w}: {fld} {f[fld]!r} is not in _catalogue_data vocabulary {list(vocab)}")
            P.need(f["mechanism_verdict"] != "NOT-CONFIRMED", f"{w}: counted with mechanism verdict NOT-CONFIRMED (a "
                                                              "finding that did not reproduce is reclassified, not counted)")
            P.need(bool(f["needs_product_change_reason"]), f"{w}: no needs_product_change_reason")
        else:
            P.need(all(f[k] is None for k in ("mechanism_verdict", "device_reachability", "needs_product_change",
                                              "needs_product_change_reason")),
                   f"{w}: an uncounted ({f['reported_as']}) entry carries two-axis verdicts")
        if pcls == "nvs":
            graded = f if f["counted"] else fby.get(f["duplicate_of"] or "")
            grade = graded.get("device_reachability") if graded else None
            if f["counted"]:
                rule = G.NVS_REACHABILITY_GROUPS.get(f["root_cause_group"], "UNKNOWN")
                P.need(grade == rule, f"{w}: an NVS-primitive finding graded {grade!r}; the NVS reachability rule gives "
                                      f"{rule!r} for its group {f['root_cause_group']}")
            tmpl = G.NVS_REACHABILITY_TEXT.get(grade)
            want_text = tmpl.format(primitive=f["injected_primitive"]) if tmpl else None
            P.need(want_text is not None and f["reachability"].startswith(want_text),
                   f"{w}: the reachability of an NVS-primitive entry must start {want_text!r} (B5.5 / B6.3; the grade "
                   + ("of this finding" if f["counted"] else f"of its owner {f['duplicate_of']}") + ")")

    # ---- negative controls, unsupported, harness limitations
    ncs = []
    for nid, suite, mut, target, outcome in G.NEGATIVE_CONTROLS:
        if outcome == "killed(audit)":     # not an in-suite control: its id is the catalogue's own, never in a suite
            P.need(nid.startswith("AUDIT-") and target.startswith(CHECKS_TARGET),
                   f"NC {nid}: an audit mutant row needs an 'AUDIT-' id and a '{CHECKS_TARGET}...' target (the killing "
                   "checks)")
        else:
            P.need(nc_in_source(nid, src.get(suite, "")), f"NC {nid} not in {suite} source")
        P.need(outcome in NC_OUTCOMES, f"NC {nid}: outcome {outcome!r}")
        ncs.append({"id": nid, "suite": suite, "mutation": clean(mut, nid), "target_invariant_or_check": target,
                    "outcome": outcome, "same_mutation_as": None})
    P.need(len({n["id"] for n in ncs}) == len(ncs), "duplicate negative-control ids")
    # distinct mutations (B3.6): SAME_MUTATION {id: canonical id} marks the rows that repeat another row's identical
    # mutation (a canonical id maps to itself implicitly and is not listed; no chains); a missing table is empty
    same = getattr(G, "SAME_MUTATION", {})
    P.need(isinstance(same, dict), "_catalogue_data.SAME_MUTATION is not a dict {control id: canonical control id}")
    same = same if isinstance(same, dict) else {}
    nc_ids = {n["id"] for n in ncs}
    for k, v in same.items():
        P.need(k in nc_ids, f"SAME_MUTATION: {k!r} is not a catalogued negative control")
        P.need(v in nc_ids, f"SAME_MUTATION[{k!r}]: {v!r} is not a catalogued negative control")
        P.need(k != v, f"SAME_MUTATION[{k!r}]: a canonical id maps to itself implicitly (do not list it)")
        P.need(k == v or v not in same, f"SAME_MUTATION[{k!r}] = {v!r}, which is itself mapped to {same.get(v)!r} (no "
                                        "chains: name the canonical control)")
    for n in ncs:
        v = same.get(n["id"])
        n["same_mutation_as"] = v if isinstance(v, str) and v in nc_ids and v != n["id"] and v not in same else None
    for n in ncs:
        P.need(list(n) == NC_KEYS, f"negative control {n['id']} keys")
    uns = [{"id": uid, "suite": suite, "description": clean(desc, uid)} for uid, suite, desc in G.UNSUPPORTED]
    hls = []
    lab_suites = {p.stem for p in HERE.glob("test_lab_*.py")}
    for i, h in enumerate(G.HARNESS_LIMITATIONS, 1):
        w = f"harness limitation {h.get('id')}"
        P.need(list(h) == HL_KEYS, f"{w}: keys {list(h)} != {HL_KEYS}")
        P.need(h.get("id") == f"HL-{i}", f"{w}: ids must run HL-1, HL-2, ... in order")
        rows = []
        for row in h.get("worked_around_in", []):
            suite, sep, how = row.partition(": ")
            P.need(bool(sep) and suite in lab_suites and how.strip(), f"{w}: workaround row {row[:60]!r} does not start "
                                                                        "with an existing lab suite name")
            rows.append(clean(row, w + ".worked_around_in"))
        P.need(bool(rows), f"{w}: no workaround row")
        path, snippet = h.get("anchor", ("", ""))
        hls.append({"id": h.get("id"), "component": clean(h.get("component"), w + ".component"),
                    "anchor": anchor_str(path, snippet, w), "limitation": clean(h.get("limitation"), w + ".limitation"),
                    "effect_on_verdicts": clean(h.get("effect_on_verdicts"), w + ".effect_on_verdicts"),
                    "worked_around_in": rows, "status": clean(h.get("status"), w + ".status")})

    # ---- coverage matrix
    scen_ids = {x["id"] for x in scenarios}
    P.need(len(scen_ids) == len(scenarios), "duplicate scenario ids")
    exist = {}
    for dim in G.DIMENSIONS:
        rows = []
        for e in G.EXISTING[dim]:
            path = e.split(": ", 1)[0]
            P.need(T._path_ok(path) and R.exists(path), f"coverage existing: missing file {path}")
            rows.append(clean(e, f"existing[{dim}]"))
        exist[dim] = rows
        for sid in G.LAB[dim]:
            P.need(sid in scen_ids, f"coverage lab[{dim}]: unknown scenario {sid}")
    inters = []
    required = {tuple(p) for p in G.REQUIRED_PAIRS}
    P.need(len(required) == 9, f"{len(required)} required intersection pairs, 9 expected")
    for (a, b), ex, lab, gap in G.INTERSECTIONS:
        P.need(a in G.DIMENSIONS and b in G.DIMENSIONS, f"intersection {a} x {b}: unknown dimension")
        P.need(ex == "none" or (T._path_ok(ex) and R.exists(ex)), f"intersection {a} x {b}: missing existing suite {ex}")
        for sid in lab:
            P.need(sid in scen_ids, f"intersection {a} x {b}: unknown scenario {sid}")
        inters.append({"pair": [a, b], "required": (a, b) in required, "existing": ex, "lab": list(lab),
                       "gap": clean(gap, f"gap {a} x {b}") if gap else ""})
    have = {tuple(i["pair"]) for i in inters}
    for p in sorted(required):
        P.need(p in have, f"required intersection {p} missing")
    P.need(len(have) == len(inters), "an intersection pair is listed twice")

    # ---- invariants referenced anywhere (scenario invariant texts, corpus documents, negative controls)
    referenced = set()
    for x in scenarios:
        referenced |= {m for m in INV_RE.findall(x["invariant"]) if m != "INV-HF"}
    for d in docs.values():
        referenced.add(d.get("invariant"))
    for nc in ncs:
        if nc["target_invariant_or_check"].startswith("INV-"):
            referenced.add(nc["target_invariant_or_check"])
    for iid in sorted(r for r in referenced if r):
        P.need(iid in G.INVARIANTS, f"invariant {iid} has no catalogue entry")
    invs = []
    for iid, (tier, meaning, checker) in G.INVARIANTS.items():
        mod, _, fn = checker.partition(".")
        P.need(tier in T.TIERS and f"def {fn}(" in src.get(mod, ""), f"invariant {iid}: checker {checker} not found")
        P.need(iid in referenced, f"invariant {iid} is not referenced by any scenario / corpus document / control")
        invs.append({"id": iid, "tier": tier, "meaning": clean(meaning, iid), "checker": checker})
    sids_of = {}
    for x in scenarios:
        sids_of.setdefault(x["suite"], []).append(x["id"])
    sids_of.setdefault(REPLAY_SUITE, []).extend(REPLAY_CHECK_PREFIXES)   # the replay suite's controls (no scenario)
    for nc in ncs:
        t = nc["target_invariant_or_check"]
        P.need(t in G.INVARIANTS or (t.startswith("finding-reproduces:") and t.split(":", 1)[1] in fby)
               or checks_target_ok(t, sids_of.get(nc["suite"], [])),
               f"NC {nc['id']}: target {t} is neither a catalogue invariant, a finding check nor '{CHECKS_TARGET}' with "
               f"check names that each start with a scenario id of {nc['suite']}")

    risks = set()
    for x in scenarios + findings + list(docs.values()):
        c = x.get("classification", "")
        if c.startswith("FINDING-KNOWN:"):
            risks.add(c.split(":", 1)[1])
    for r in sorted(risks):
        P.need(r in T.KNOWN_RISKS, f"known risk {r} not registered in _lab_trace.KNOWN_RISKS")

    # ---- corpus consistency (the rules test_lab_replay_corpus enforces)
    owner = {}
    for x in scenarios:
        for c in x["corpus"]:
            P.need(c not in owner, f"corpus {c} listed by two scenarios")
            owner[c] = x["id"]
    P.need(sorted(owner) == sorted(docs), f"corpus files vs scenario lists differ: {sorted(set(docs) ^ set(owner))}")
    by_stem: dict[str, list] = {}
    for f in findings:
        for c in f["corpus"]:
            P.need(c in docs, f"{f['fid']}: corpus {c} has no file")
            by_stem.setdefault(c, []).append(f)
    scen_by_id = {x["id"]: x for x in scenarios}
    group_priority = {r["group"]: r["priority"] for r in roots}
    for stem, d in docs.items():
        fs = by_stem.get(stem, [])
        for f in fs:
            P.need(d.get("classification") == f["classification"],
                   f"{stem}: doc {d.get('classification')} != {f['fid']} {f['classification']}")
            P.need(d.get("grade") == f["grade"], f"{stem}: grade {d.get('grade')} != {f['fid']} {f['grade']}")
            P.need(d.get("confidence") == f["confidence_level"],
                   f"{stem}: confidence {d.get('confidence')} != {f['fid']} {f['confidence_level']}")
        if not fs:
            P.need(d.get("classification") == "PASS", f"{stem}: {d.get('classification')} document listed by no finding")
        # the two priorities (B6.6): scenario_priority = the owning scenario's priority; finding_priority = the highest
        # root-cause priority of the catalogue findings that list the document (a DUPLICATE / MERGED entry is in its
        # owner's group), null when no finding lists it
        P.need("priority" not in d, f"corpus {stem}: the V0 key 'priority' (V0.1 records scenario_priority and "
                                    "finding_priority instead)")
        own = scen_by_id.get(owner.get(stem, ""))
        P.need(own is not None and d.get("scenario_priority") == own["priority"],
               f"corpus {stem}: scenario_priority {d.get('scenario_priority', '<missing>')!r} != its scenario "
               f"{owner.get(stem)} priority {own['priority'] if own else None!r}")
        prios = sorted({group_priority.get(f["root_cause_group"]) for f in fs} & set(T.PRIORITIES),
                       key=T.PRIORITIES.index)
        want_fp = prios[0] if prios else None
        P.need("finding_priority" in d and d["finding_priority"] == want_fp,
               f"corpus {stem}: finding_priority {d.get('finding_priority', '<missing>')!r} != {want_fp!r} (the highest "
               f"root-cause priority of the findings that list it: {', '.join(f['fid'] for f in fs) or 'none'})")
    for f in findings:
        P.need(f["fid"] in src[f["suite"]], f"{f['fid']} not in {f['suite']} source")
        P.need(f["classification"] in src[f["suite"]], f"{f['fid']}: classification text not in {f['suite']} source")
        P.need(f["reported_as"] in REPORTED_AS, f"{f['fid']}: reported_as {f['reported_as']!r}")
        P.need(f["counted"] == (f["reported_as"] == "FINDING"), f"{f['fid']}: counted and reported_as disagree")
        P.need((f["duplicate_of"] is None) == (f["reported_as"] == "FINDING"),
               f"{f['fid']}: duplicate_of and reported_as disagree")
    for x in scenarios:
        P.need(x["id"] in src[x["suite"]], f"scenario {x['id']} not in {x['suite']} source")

    # ---- run-derived checks
    runtime: dict[str, float] = {}
    if static or not sequential:
        old = committed.get("runtime_quick_s") if isinstance(committed, dict) else None
        if isinstance(old, dict):
            runtime = dict(old)
        why = "static mode" if static else "the suite outputs are not from a sequential (--parallel 1) run"
        P.need(sorted(runtime) == sorted(ALL_SUITES),
               f"{why}: runtime_quick_s is kept from the committed catalogue, whose keys {sorted(runtime)} are not the "
               "lab suites (generate it from a sequential run)")
        if not static:
            notes.append(f"runtime_quick_s: kept from the committed catalogue ({why}; sequential runtimes only are "
                         "stored)")
    if not static:
        summary, text, measured = {}, {}, {}
        for s in ALL_SUITES:
            r = runs.get(s)
            if r is None:
                P.append(f"no quick-run output for {s}")
                continue
            rec, probs, warns = suite_output(s, r, sequential)
            P.extend(probs)
            warnings.extend(warns)
            if rec is None:
                continue
            if s == REPLAY_SUITE:
                notes.append(f"{s}: runtime_s {rec['runtime_s']} taken from its LAB-SUMMARY (pass {rec['pass']}, fail "
                             f"{rec['fail']}; its result depends on the catalogue being generated)")
            summary[s], text[s] = rec, r["text"]
            measured[s] = round(float(rec["runtime_s"]), 1)
            if sequential:
                runtime[s] = measured[s]
        if not sequential and measured:
            notes.append("runtimes measured in this run (not sequential: not judged, not stored): "
                         + ", ".join(f"{s} {v}" for s, v in measured.items()))
        for s in ALL_SUITES:
            if s in text:
                printed = run_lab.scan_output(text[s].splitlines())["unsupported_ids"]
                P.extend(run_lab.unsupported_id_problems(s, printed, uns, extended=False))
        for nc in ncs:
            run = text.get(nc["suite"], "")
            replay = nc["suite"] == REPLAY_SUITE
            if nc["outcome"] != "killed(audit)":    # an audit mutant is not run by the lab: no outcome line to see
                lines = [ln for ln in run.splitlines() if re.search(rf"(?<![\w-]){re.escape(nc['id'])}(?![\w-])", ln)
                         and (not replay or ln.startswith("  PASS  "))]   # the replay suite's FAILs are not judged
                words = ("killed", "caught") if nc["outcome"] == "killed" else ("surviv",)
                P.need(any(w in ln.lower() for ln in lines for w in words),
                       f"NC {nc['id']}: outcome {nc['outcome']!r} not seen in the {nc['suite']} run output"
                       + (" (on a PASS line)" if replay else ""))
            t = nc["target_invariant_or_check"]
            names = checks_target(t)
            if names and replay:
                # the replay suite's drift-rule checks fail while the catalogue being generated is stale (its result is
                # not judged here): the named checks must have run (a PASS or FAIL line), the control itself held above
                ran = [ln for ln in run.splitlines() if ln.startswith(("  PASS  ", "  FAIL  "))]
                missing = [n for n in names if not any(ln[len("  PASS  "):].startswith(n) for ln in ran)]
                P.need(not missing, f"NC {nc['id']}: named check(s) {missing} not run in the {nc['suite']} run output")
                P.need(", ".join(names) in run, f"NC {nc['id']}: target check list not printed in the {nc['suite']} run "
                                                "output")
            elif names:
                # every named check exists and holds in this (plain) run; an in-suite control prints its own list
                held = [ln[len("  PASS  "):] for ln in run.splitlines() if ln.startswith("  PASS  ")]
                missing = [n for n in names if not any(h.startswith(n) for h in held)]
                P.need(not missing, f"NC {nc['id']}: named check(s) {missing} not held in the {nc['suite']} run output")
                P.need(nc["outcome"] == "killed(audit)" or ", ".join(names) in run,
                       f"NC {nc['id']}: target check list not printed in the {nc['suite']} run output")
            else:
                P.need(t in run or t in src[nc["suite"]], f"NC {nc['id']}: target {t} not in {nc['suite']}")
        known_nc = {n["id"] for n in ncs}
        for s in SCENARIO_SUITES:
            for ln in text.get(s, "").splitlines():
                if not ln.startswith("  PASS  ") or not re.search(r"killed|surviv", ln, re.I):
                    continue
                m = NC_TOKEN.search(ln)
                if m and m.group(1).startswith("NC") and not m.group(1).startswith("NC-RC"):
                    P.need(m.group(1) in known_nc, f"{s} prints negative control {m.group(1)} that the catalogue lacks")
        for f in findings:
            run = text.get(f["suite"], "")
            flines = [ln for ln in run.splitlines() if re.match(rf"  FINDING  {re.escape(f['fid'])}(?:\s|$)", ln)]
            if f["reported_as"] == "MERGED":
                P.need(not flines, f"{f['fid']}: MERGED but the {f['suite']} run printed a FINDING line for it")
                P.need(f"{f['fid']} -> merged into {f['duplicate_of']}" in run,
                       f"{f['fid']}: the {f['suite']} run does not report the merge into {f['duplicate_of']}")
            else:
                P.need(bool(flines), f"{f['fid']}: {f['reported_as']} but the {f['suite']} run printed no FINDING line")
            if f["reported_as"] == "DUPLICATE":
                P.need(all("DUPLICATE of " + f["duplicate_of"] in ln for ln in flines),
                       f"{f['fid']}: a FINDING line of the {f['suite']} run does not mark it DUPLICATE of {f['duplicate_of']}")
            if f["reported_as"] == "FINDING":
                P.need(not any("DUPLICATE" in ln for ln in flines), f"{f['fid']}: counted but printed as a DUPLICATE")
        for s in SCENARIO_SUITES:
            n = sum(1 for f in findings if f["suite"] == s and f["counted"])
            P.need(summary.get(s, {}).get("finding") == n, f"{s}: counted {n} != LAB-SUMMARY {summary.get(s)}")
            # every FINDING line names a catalogue finding of this suite (a reclassified id, F-HF05-1 or F-RT02-1, and a
            # merged variant print none)
            mine = {f["fid"] for f in findings if f["suite"] == s and f["reported_as"] != "MERGED"}
            stray = [fid for fid in run_lab.scan_output(text.get(s, "").splitlines())["findings"] if fid not in mine]
            P.need(not stray, f"{s}: FINDING line(s) for id(s) that are no printed catalogue finding of this suite: "
                              f"{', '.join(stray)}")

    # ---- baseline sources: every lab .py (the replay suite included: _lab_trace.LAB_RULE), every corpus document, every
    #      anchored file, every corpus-pinned file and (B1) every file the tier table requires: each behavioural file and
    #      each anchor-read non-behavioural file (_lab_trace.pinned_by_table)
    sources = set()
    lab_py = [p.name for p in sorted(HERE.glob("*.py"))]      # the replay suite included (_lab_trace.LAB_RULE)
    P.need({f"{n}.py" for n in ALL_SUITES + HELPERS} <= set(lab_py), "a known lab module is missing")
    for n in lab_py:
        sources.add(f"{LAB_REL}/{n}")
    for stem in docs:
        sources.add(f"{LAB_REL}/corpus/{stem}.json")
    for x in scenarios:
        for a in x["anchors"]:
            sources.add(a.split(": ", 1)[0])
    for h in hls:
        sources.add(h["anchor"].split(": ", 1)[0])
    for d in docs.values():
        sources |= set(d.get("source_digests", {}))
    sources |= set(T.pinned_by_table())
    bad_paths = sorted(p for p in sources if not T._path_ok(p))
    P.need(not bad_paths, f"pinned sources that are not repo-relative POSIX paths: {bad_paths[:4]}")
    sources -= set(bad_paths)
    missing = sorted(p for p in sources if not R.exists(p))
    P.need(not missing, f"pinned sources missing: {missing[:4]}")
    # B1 tier table: every pinned non-lab file classified, tier sets within the behavioural tier, no file in both tiers
    P.extend(T.tier_table_problems({p for p in sources if not T.is_lab_path(p)}, exists=R.exists))
    for stem, d in sorted(docs.items()):
        P.need(d.get("tier") in T.TIER_SOURCES, f"corpus {stem}: tier {d.get('tier')!r} has no TIER_SOURCES entry in the "
                                                "B1 tier table (_lab_trace.TIER_SOURCES): its replay inputs are unpinned")
        unpinned = sorted(set(T.tier_pins(d.get("tier"))) - set(d.get("source_digests") or {}))
        P.need(not unpinned, f"corpus {stem}: does not pin {len(unpinned)} of its tier's TIER_SOURCES in its own "
                             f"source_digests ({', '.join(unpinned[:3])}{' ...' if len(unpinned) > 3 else ''}); re-record "
                             f"it: python -B registry/tests/assurance_lab/rerecord_corpus.py {stem} --pin-tier-sources")
    tiers = {"rule": clean(T.TIER_RULE, "baseline.tiers.rule"), "lab": clean(T.LAB_RULE, "baseline.tiers.lab"),
             "drift": clean(T.DRIFT_RULE, "baseline.tiers.drift"), "method": clean(T.TIER_METHOD, "baseline.tiers.method"),
             "behavioural": [{"path": p, "reason": clean(T.BEHAVIOURAL[p], f"baseline.tiers.behavioural {p}")}
                             for p in sorted(T.BEHAVIOURAL)],
             "non_behavioural": [{"path": p, "pinned": T.NON_BEHAVIOURAL[p][0],
                                  "reason": clean(T.NON_BEHAVIOURAL[p][1], f"baseline.tiers.non_behavioural {p}")}
                                 for p in sorted(T.NON_BEHAVIOURAL)],
             "tier_sources": {t: list(T.TIER_SOURCES[t]) for t in T.TIERS if t in T.TIER_SOURCES}}
    base = {"public_main": PUBLIC_MAIN, "sources": {p: R.sha(p) for p in sorted(sources) if R.exists(p)},
            "tiers": tiers}
    # a corpus pin that differs from this tree: a problem unless the committed catalogue holds the recorded digest (the
    # tree changed: compare() judges it by the tiered drift rule); always a problem for --write (re-record first)
    old_base = committed.get("baseline") if isinstance(committed, dict) else None
    old_src = old_base.get("sources") if isinstance(old_base, dict) else None
    old_src = old_src if isinstance(old_src, dict) else {}
    stale: dict[str, list] = {}
    for stem, d in sorted(docs.items()):
        for path, sha in sorted(d.get("source_digests", {}).items()):
            if base["sources"].get(path) != sha and (for_write or old_src.get(path) != sha):
                stale.setdefault(path, []).append(stem)
    for path, stems in sorted(stale.items()):
        P.append(f"corpus document(s) record a {path} sha256 that is not this tree's"
                 + ("" if for_write else " nor the committed catalogue's") + f" ({len(stems)}: {T.compact_ids(stems)}): "
                 + T.rerecord_procedure(stems, len(docs)))
    # suite outputs belong to this tree only when their record of the tree they ran on equals it (B1: no re-baselining
    # from outputs of another tree, e.g. a behavioural file no corpus document pins changed after the run)
    if not static:
        P.extend(tree_record_problems(run_tree, base["sources"], R.sha))

    cat = {
        "schema": SCHEMA,
        "baseline": base,
        "tiers": [{"id": t["id"], "engine": clean(t["engine"], t["id"]), "real_source": clean(t["real_source"], t["id"]),
                   "model_assumptions": [clean(m, t["id"]) for m in t["model_assumptions"]]} for t in G.TIERS],
        "invariants": invs,
        "known_risks_used": sorted(risks),
        "scenarios": scenarios,
        "findings": findings,
        "root_causes": roots,
        "negative_controls": ncs,
        "unsupported": uns,
        "harness_limitations": hls,
        "coverage_matrix": {"dimensions": list(G.DIMENSIONS), "existing": exist, "lab": {k: list(v) for k, v in
                                                                                        G.LAB.items()},
                            "intersections": inters},
        "runtime_quick_s": {s: runtime[s] for s in ALL_SUITES if s in runtime},
    }
    P.need(list(cat) == TOP_KEYS, "top-level key order")
    P.need({t["id"] for t in cat["tiers"]} == set(T.TIERS), "tier ids")
    for x in scenarios:
        P.need(list(x) == SCEN_KEYS, f"scenario {x['id']} keys")
    for f in findings:
        P.need(list(f) == FIND_KEYS and list(f["verification"]) == VERIFICATION_KEYS, f"finding {f['fid']} keys")
    for r in roots:
        P.need(list(r) == ROOT_KEYS, f"root cause {r['group']} keys")

    for old, _new in PUBLIC_TEXT_REPLACEMENTS:
        P.need(old in used_replacements, f"PUBLIC_TEXT_REPLACEMENTS: {old!r} no longer occurs (remove it)")
    text = dumps(cat)
    # whole-file privacy shapes (a sha256 digest is hash text, not a number)
    for i, ln in enumerate(text.splitlines(), 1):
        P.need(not THIRTEEN.search(HEX64.sub("-", ln)), f"catalogue line {i}: a 13-digit run outside a sha256 digest")
        P.need(not (THIRTEEN.search(ln) and METER_WORD.search(ln)), f"catalogue line {i}: a meter word on a digest line")
    P.need(not DOTTED_QUAD.search(text), "a dotted quad in the catalogue")
    P.need(not SIX_GROUPS.search(text), "six joined 2-digit groups in the catalogue")
    P.need(text.isascii() and "\r" not in text, "the catalogue text is not ASCII / LF")
    return Build(cat=cat, text=text, problems=list(P), notes=notes, skipped=skipped, warnings=warnings, docs=docs,
                 missing=missing)


# ---------------------------------------------------------------------------------------------------------------------------
# comparison with the committed file
# ---------------------------------------------------------------------------------------------------------------------------
def compare(committed_text: str, b: Build, *,
            strict: bool = False) -> tuple[list[str], list[str], T.DriftReport | None]:
    """(differences, notes, drift) between the committed catalogue and a fresh build. runtime_quick_s values are
    excluded (wall-clock measurements: the keys must match, the value changes are notes). The baseline digests of the
    sources pinned in both are judged by the tiered drift rule (_lab_trace.drift_report over the committed digests and
    this tree's, i.e. the build's): `drift` holds that verdict (drift.failures(): one failure per changed lab or
    behavioural file, or per changed non-behavioural file in strict mode; drift.drift_lines(): the non-behavioural SOURCE
    DRIFT lines) and those digests are not compared again; everything else must be byte-identical. drift is None when
    the committed file is not a catalogue with baseline.sources."""
    committed_text = committed_text.replace("\r\n", "\n")
    try:
        old = strict_json(committed_text)
    except ValueError as exc:
        return [f"the committed catalogue is not strict JSON ({exc})"], [], None
    new = copy.deepcopy(b.cat)
    notes = []
    o_rt, n_rt = (old.get("runtime_quick_s") if isinstance(old, dict) else None), new.get("runtime_quick_s", {})
    if isinstance(o_rt, dict) and list(o_rt) == list(n_rt):
        for k in n_rt:
            if o_rt[k] != n_rt[k]:
                notes.append(f"runtime_quick_s {k}: committed {o_rt[k]} s, this run {n_rt[k]} s (not compared)")
        new["runtime_quick_s"] = dict(o_rt)
    o_base = old.get("baseline") if isinstance(old, dict) else None
    o_src = o_base.get("sources") if isinstance(o_base, dict) else None
    drift = None
    diffs = []
    if isinstance(o_src, dict):
        n_src = new["baseline"]["sources"]
        # a committed pin this tree lacks is judged too (sha None: 'pinned source missing' or its tier's failure), not
        # left out: the build drops a missing file from baseline.sources
        gone = set(b.missing)
        common = {p: sha for p, sha in o_src.items() if p in n_src or p in gone}
        drift = T.drift_report(common, b.docs, sha_of=n_src.get, strict=strict)
        for item in drift.items:          # judged by the tiered drift rule, not compared again
            n_src[item.path] = o_src[item.path]
        added, removed = sorted(set(n_src) - set(o_src)), sorted(set(o_src) - set(n_src))
        if added or removed:            # a changed pinned set is a lab-side change: reported once, by name
            diffs.append(f"baseline.sources: the pinned set differs (added {added[:6]}{' ...' if len(added) > 6 else ''}"
                         f", removed {removed[:6]}{' ...' if len(removed) > 6 else ''}): re-generate the catalogue")
            merged = {p: o_src.get(p, n_src.get(p)) for p in sorted(set(n_src) | set(o_src))}
            new["baseline"]["sources"] = merged
            old = copy.deepcopy(old)
            old["baseline"]["sources"] = dict(merged)
    if dumps(new) == committed_text or (diffs and old == new):
        return diffs, notes, drift
    if not isinstance(old, dict) or list(old) != list(new):
        diffs.append(f"top-level keys {list(old) if isinstance(old, dict) else type(old).__name__} != {list(new)}")
        return diffs, notes, drift
    for k in new:
        if old[k] == new[k]:
            continue
        if isinstance(new[k], list) and isinstance(old[k], list):
            def ident(e):
                return e.get("id") or e.get("fid") or e.get("group") or json.dumps(e.get("pair")) if isinstance(e, dict) \
                    else json.dumps(e)
            o_ids, n_ids = [ident(e) for e in old[k]], [ident(e) for e in new[k]]
            changed = [i for i, e in zip(n_ids, new[k]) if i in o_ids and old[k][o_ids.index(i)] != e]
            diffs.append(f"{k}: added {sorted(set(n_ids) - set(o_ids))[:6]}, removed {sorted(set(o_ids) - set(n_ids))[:6]}, "
                         f"changed {changed[:6]}" + (" (order differs)" if n_ids != o_ids and sorted(n_ids) ==
                                                      sorted(o_ids) else ""))
        elif isinstance(new[k], dict) and isinstance(old[k], dict):
            ch = sorted(x for x in set(old[k]) | set(new[k]) if old[k].get(x) != new[k].get(x))
            diffs.append(f"{k}: differs at {ch[:6]}" + (f" (+{len(ch) - 6})" if len(ch) > 6 else ""))
        else:
            diffs.append(f"{k}: differs")
    return diffs or ["the committed file differs from the canonical form (formatting)"], notes, drift


def static_check(committed_text: str, *, strict: bool = False,
                 reader: T.TreeReader | None = None) -> tuple[list[str], list[str], list[str]]:
    """The static parts of --check (no suite is run): (problems of the fresh build, differences to the committed file
    including the tiered drift rule's failures, notes naming what was skipped and the SOURCE DRIFT lines)."""
    try:
        committed = strict_json(committed_text.replace("\r\n", "\n"))
    except ValueError:
        committed = None
    b = build(None, committed=committed, reader=reader)
    diffs, notes, drift = compare(committed_text, b, strict=strict)
    return (b.problems, diffs + (drift.messages() if drift is not None else []),
            [f"skipped (static mode): {s}" for s in b.skipped] + notes + (drift.drift_lines() if drift is not None else []))


# ---------------------------------------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------------------------------------
def counts(cat: dict) -> str:
    f = cat["findings"]
    rep = {k: sum(1 for x in f if x["reported_as"] == k) for k in REPORTED_AS}
    by_pri = " / ".join(f"{p} {sum(1 for r in cat['root_causes'] if r['priority'] == p)}" for p in T.PRIORITIES)
    return (f"{len(cat['scenarios'])} scenarios, {len(f)} findings ({rep['FINDING']} counted, {rep['DUPLICATE']} printed "
            f"duplicates, {rep['MERGED']} merged), {len(cat['root_causes'])} root causes ({by_pri}), "
            f"negative controls: {run_lab.mutation_text(cat['negative_controls'])}, "
            f"{len(cat['unsupported'])} unsupported, {len(cat['harness_limitations'])} harness "
            f"limitations, {sum(len(x['corpus']) for x in cat['scenarios'])} corpus documents, "
            f"{len(cat['baseline']['sources'])} pinned sources")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build / check / write SCENARIO_CATALOGUE.json (see the module docstring).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the catalogue (only without problems)")
    mode.add_argument("--check", action="store_true", help="compare a fresh build with the committed catalogue")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--runs-from", metavar="DIR", help="read saved quick-run outputs DIR/<suite>.txt instead of running")
    src.add_argument("--static", action="store_true", help="no suite outputs: static parts only (not with --write)")
    ap.add_argument("--save-runs", metavar="DIR", help="also save each suite's output to DIR (outside the repository)")
    ap.add_argument("--runs-sequential", action="store_true",
                    help="with --runs-from: assert that the saved outputs come from a sequential run (refused when "
                         "their saved-runs record says otherwise)")
    ap.add_argument("--parallel", type=int, default=1,
                    help="suites run at once (default 1: sequential, uncontended runtimes; > 1: runtimes not judged, "
                         "not stored)")
    ap.add_argument("--timeout", type=int, default=run_lab.DEFAULT_TIMEOUT, help="seconds per suite")
    args = ap.parse_args(argv)
    if args.static and args.write:
        ap.error("--static cannot --write (the run-derived checks and the runtimes need suite outputs)")
    if args.save_runs and (args.static or args.runs_from):
        ap.error("--save-runs applies to a suite run")
    if args.save_runs and inside_repo(Path(args.save_runs)):
        ap.error("--save-runs: the directory must be outside the repository (nothing is written into it)")
    if args.runs_sequential and not args.runs_from:
        ap.error("--runs-sequential applies to --runs-from")
    if args.parallel < 1 or args.timeout < 1:
        ap.error("--parallel and --timeout must be >= 1")
    if args.runs_from and args.parallel != 1:
        ap.error("--parallel applies to a suite run, not to --runs-from (its saved-runs record says how it was run)")
    committed_text = OUT.read_bytes().decode("utf-8") if OUT.is_file() else ""
    try:
        committed = strict_json(committed_text.replace("\r\n", "\n"))
    except ValueError:
        committed = None
    run_tree = None
    if args.static:
        runs = None
    elif args.runs_from:
        runs, run_tree = load_runs(Path(args.runs_from), assert_sequential=args.runs_sequential)
    else:
        runs, run_tree = run_all(args.parallel, args.timeout)
        if args.save_runs:
            save_runs(runs, Path(args.save_runs), args.parallel, run_tree)
    b = build(runs, committed=committed, for_write=args.write, run_tree=run_tree)
    for n in b.notes:
        print(f"  info  {n}")
    for w in b.warnings:
        print(f"  WARNING  {w}")
    for s in b.skipped:
        print(f"  info  skipped (static mode): {s}")
    print(f"  info  built: {counts(b.cat)}")
    print(f"  info  two-axis verdicts: {run_lab.verdict_text(run_lab.verdict_distribution(b.cat['findings']))}")
    if b.problems:
        print(f"PROBLEMS ({len(b.problems)}):")
        for p in b.problems:
            print(f"  - {p}")
        return 1
    if args.check:
        strict = os.environ.get("ECCO_LAB_STRICT_BASELINE") == "1"
        diffs, notes, drift = compare(committed_text, b, strict=strict)
        for n in notes:
            print(f"  info  {n}")
        print("  info  drift rule: " + ("STRICT (ECCO_LAB_STRICT_BASELINE=1): every pinned source must be unchanged"
                                        if strict else "tiered (lab and behavioural files exact; a changed "
                                        "non-behavioural file is SOURCE DRIFT, not a failure)"))
        for line in (drift.drift_lines() if drift is not None else []):
            print(f"  {line}")
        fails = drift.failures() if drift is not None else []
        if fails:
            print(f"{'STRICT' if strict else 'TIERED'} DRIFT RULE: {len(fails)} failure(s) (one per changed file):")
            for title, detail in fails:
                print(f"  - {title} - {detail}")
        if diffs:
            print("catalogue OUT OF DATE (re-generate with --write):")
            for d in diffs:
                print(f"  - {d}")
        if diffs or fails:
            return 1
        print("catalogue up to date" + (" (static parts)" if args.static else "")
              + (f"; {len(drift.drift_lines())} non-behavioural SOURCE DRIFT line(s)" if drift and drift.drift_lines()
                 else ""))
        return 0
    if args.write:
        OUT.write_bytes(b.text.encode("ascii"))
        print(f"wrote {LAB_REL}/SCENARIO_CATALOGUE.json ({len(b.text)} bytes)")
        return 0
    print("built (nothing written; use --write or --check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
