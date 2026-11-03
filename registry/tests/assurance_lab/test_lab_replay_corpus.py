#!/usr/bin/env python3
"""Replay corpus and scenario catalogue suite: every corpus document under registry/tests/assurance_lab/corpus is validated
against the strict replay schema and replayed through the _lab_trace engine, SCENARIO_CATALOGUE.json is cross-checked against
the corpus, the lab suite sources and its recorded baseline, and the harness itself is checked by negative controls. Offline
assurance lab V0 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Baseline rule (V0.1, B1: the tiered drift rule; the tier table and the rule are _lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL /
TIER_SOURCES and _lab_trace.drift_report, published in the catalogue's baseline.tiers). The catalogue's baseline.sources
records the LF-normalised sha256 of every file it was generated from: every lab file (each registry/tests/assurance_lab/*.py,
this suite, run_lab.py and the maintenance tools included, and every corpus document; SCENARIO_CATALOGUE.json itself is
the one exemption, it cannot record its own digest), every BEHAVIOURAL non-lab file (one the lab imports,
executes, parses as data or derives an expectation from: the firmware, its durable-snapshot header, the four HA packages
the coupled world loads, the shared simulators and the registry / tools modules they import) and every NON-BEHAVIOURAL
file an exactly-once anchor reads (CHANGELOG.md, SAFETY.md, docs, tests and frontend sources cited by anchors). The rule:
  - a changed or unpinned LAB file is a FAIL that asks to re-generate the catalogue (the catalogue mirrors the suites);
  - a changed BEHAVIOURAL file is ONE named FAIL per file in [5] ('gen_catalogue drift rule (tiered): behavioural source
    changed: <path>') that lists the corpus documents replaying it and the re-record procedure (doc section 11);
  - a changed NON-BEHAVIOURAL file prints 'SOURCE DRIFT (non-behavioural): <path>' in [5] and is not a failure; every
    anchor in it is still checked exactly once ([3], [5] and the suites), so an edit that breaks an anchor still FAILS;
  - a pinned file that is missing fails in every tier;
  - ECCO_LAB_STRICT_BASELINE=1 (the environment value '1' exactly, or this suite's --strict-baseline argument) restores
    the whole-baseline rule (every pinned source exact, no drifted document at all; the [5] drift checks are then named
    'gen_catalogue drift rule (STRICT): ...') for recording and regenerating.
Every corpus document is judged against its own source_digests PLUS its tier's TIER_SOURCES (the files a replay of that
tier executes, found by an audit-hook trace) at the catalogue baseline's digests, so a document whose own pins omit an
executed file (the firmware for HF-02-a, say) still reports that file's drift.

Sections
  [0] the catalogue file: strict JSON (duplicate keys, NaN / Infinity refused), ASCII, LF (a CRLF working copy, as a
      core.autocrlf=true checkout writes it, is normalised first: git stores LF), the catalogue schema
      'ecco-assurance-lab-catalogue/v0' with its exact top-level keys, and spec 0.6: a 13-digit decimal run occurs only
      inside a 64-hex sha256 digest, never on a line that names a meter word (the repository privacy scan's rule).
  [1] corpus schema: every corpus/*.json loads through _lab_trace.load_corpus (strict JSON + validate_doc, file stem == id),
      is in the canonical _lab_trace.dumps_doc form (after the same CRLF normalisation), is synthetic and obeys the same
      13-digit rule.
  [2] replay: the run-time import guard mid-run (every repository module in this process's sys.modules outside the lab,
      i.e. what the three replay tiers, gen_catalogue, run_lab and rerecord_corpus imported at load time, is in the
      behavioural tier; _lab_trace.finish() repeats the guard at the end of this and every other suite, so a lazy import
      made later, in [5] say, is caught there; a data read is not an import: trace_inputs.py finds it); every
      TIER_SOURCES file is pinned in the catalogue baseline; every document pins its tier's TIER_SOURCES in its own
      source_digests (tier_pin_shortfalls); every document replays through
      _lab_trace.replay with its effective pins (its own source_digests plus its tier's TIER_SOURCES at the baseline's
      digests). Drift rule (spec 2.2): with every pinned digest unchanged the replay must be ok with digest == trace_digest
      and every anchor at its recorded line (two checks); a document whose pinned digest differs prints 'SOURCE DRIFT:
      <path>' and is judged on its expectations, plus a second check (the count of checks per document stays two): with
      non-behavioural drift only, digest == trace_digest and every anchor exactly once (a non-behavioural file cannot
      change a trace); with lab or behavioural drift, every anchor still exactly once ([5] names the file to re-record). A
      drifted document must be explained by a catalogue-baseline source that changed in this tree (on the recorded
      baseline no document is drifted; a document that records another tree's digest needs re-recording; strict mode: no
      drifted document at all). Quick mode replays ALL documents once (the list of skipped documents is printed and is
      empty); ECCO_LAB_EXTENDED=1 / --extended replays every document a second time and requires the identical digest and
      observations (determinism within one process), and prints its runtime.
  [3] catalogue cross-checks (static, nothing is run): the baseline rule above (lab files exact and all pinned; the changed
      files of this tree counted per tier, judged in [5]; baseline keys public_main, sources, tiers); every corpus
      document records exactly the catalogue's baseline digest of each file it pins; every corpus
      stem belongs to exactly one scenario and exists; a document listed by a finding carries that finding's
      classification, grade and confidence_level, a document listed by no finding is PASS; confidence_level is the
      high|medium|low enum and the first word of the confidence prose; every scenario / finding id and each finding's
      classification occur in its suite's source text (read as text, never imported); reported_as is FINDING for a counted
      finding (printed '  FINDING  <id>'), DUPLICATE for a printed duplicate (its suite names the owner) and MERGED for a
      variant merged into its owner after review (its suite records 'merged into <owner>' and prints no FINDING line); the
      counted findings per suite equal that suite's recorded LAB-SUMMARY 'finding' value (LAB_SUMMARY_FINDING, the
      quick-mode value at this baseline); duplicates and merged variants name a counted owner in the same root-cause
      group; every root-cause group is homogeneous and has a counted member; every invariant checker exists; every
      scenario and finding carries phase_sensitive (a bool) with a reason exactly when it is true; every negative control
      has same_mutation_as null (its own distinct mutation) or the id of another control whose same_mutation_as is null
      (the same mutation, counted once: B3.6); every negative control
      targets a catalogue invariant, a finding check or 'checks: <name>, ...' naming checks of a scenario of its suite, and
      its id occurs in the suite source unless it is an audit mutant row ('killed(audit)', an 'AUDIT-' id); every scenario
      anchor occurs exactly once; the known-risk ids are registered; the coverage matrix cites existing files and catalogue
      scenarios and lists the required high-risk intersections, flagged 'required': true exactly for REQUIRED_PAIRS; every
      harness limitation (HL-1, HL-2, ... in order) has the schema's keys, an anchor that occurs exactly once, workaround
      rows that name an existing lab suite, and a status; every quick runtime is <= 90 s.
  [4] harness negative controls NC-RC-1..16 (the replay controls use a copy of the document pinned to this tree, so they
      test the engine's rules on a drifted tree too): an altered expectation fails its replay; an altered action list
      changes the digest; a document with an unknown key is rejected by the schema; a drifted recorded digest prints SOURCE
      DRIFT and is flagged as unexplained drift and by the corpus / baseline digest cross-check; a catalogue entry pointing
      at a missing corpus file, a duplicated corpus owner, a wrong classification, a flipped counted flag and a changed
      lab-file baseline digest are each detected; a changed non-lab baseline digest is SOURCE DRIFT (a FAIL only in strict
      mode); a merged variant relabelled DUPLICATE and a confidence_level that contradicts its prose are detected; a CRLF
      working copy passes the LF / canonical checks while a lone CR or a non-canonical body fails; a planted 13-digit run
      and a meter word on a digest line are detected; a harness limitation with a moved anchor and a flipped 'required'
      flag are detected; NC-RC-38 / 39: a phase-sensitive scenario without its reason and a negative-control target
      naming a check of no scenario of its suite are detected; NC-RC-49: a same_mutation_as chain (a row naming a control
      that itself repeats another) is detected.
  [5] the generator and the tiered drift rule: gen_catalogue.py (imported, check mode, static) rebuilds the catalogue from
      the suite tables (static AST evaluation), the corpus, _catalogue_data.py, the tier table and this tree's files (read
      through a _lab_trace.TreeReader) and must report no build problem; gen_catalogue.compare() judges the baseline
      digests by the tiered drift rule (one shared function, _lab_trace.drift_report, also used by
      'gen_catalogue.py --check' and run_lab.py): it prints one 'SOURCE DRIFT (non-behavioural): <path>' line per changed
      non-behavioural file, emits ONE named FAIL per changed lab file ('re-generate the catalogue: lab file changed:
      <path>'), behavioural file ('behavioural source changed: <path>', with the corpus documents replaying it and the
      re-record procedure) or, in strict mode, non-behavioural file, and otherwise one PASS; everything else in the
      committed catalogue must equal the fresh build. STATIC ONLY, said in the output: running the other lab suites here
      would exceed this suite's 90 s budget, so the run-derived parts (negative-control outcomes, FINDING / DUPLICATE /
      merge lines, counted findings against LAB-SUMMARY, the quick runtimes, which are reused from the committed file) are
      not re-checked here; run_lab.py cross-checks counts and FINDING lines against a live run, and
      'gen_catalogue.py --check' does all of it. Controls: NC-RC-17 a changed catalogue entry is reported as a difference,
      a changed runtime value alone is not; NC-RC-40..45 run this section's real code path (generator_results) over an
      in-memory overlay of the tree (nothing is written; catalogued in NEGATIVE_CONTROLS): CHANGELOG.md plus one comment
      line adds exactly its SOURCE DRIFT line and no failure (strict mode: exactly one FAIL, named 'gen_catalogue drift
      rule (STRICT): ...'); the firmware YAML plus one comment line and registry/rtc_policy.py plus one comment line each
      add exactly one named FAIL whose detail names every corpus document that replays the file (the expected list is
      computed here from the corpus JSON and TIER_SOURCES, not by the functions under test), their count and the
      re-record target; NC-RC-43 a lab file no corpus document pins (run_lab.py) plus one comment line adds exactly one
      're-generate the catalogue: lab file changed' FAIL; NC-RC-44 a corpus document copy with one TIER_SOURCES pin
      removed is named by gen_catalogue's build ('does not pin 1 of its tier's TIER_SOURCES') and by the [2] short-list
      (tier_pin_shortfalls); NC-RC-45 a pinned file the tier table does not classify (SAFETY.md, taken out of the table
      for the control and restored) plus one comment line adds exactly one 'unclassified pinned source changed' FAIL.
  [6] runner negative self-tests (V0.1 suite output contract): synthetic suite outputs written with _lab_trace.finish /
      unsupported_line, then planted inconsistencies, are judged by run_lab.judge and gen_catalogue.suite_output (imported;
      both are command-line modules, never suites): a clean output (LF and CRLF) is accepted; an extra PASS line, an extra
      finding-pin line, a FAIL line at exit code 0, a hard-coded unsupported count, removed UNSUPPORTED lines, a wrong
      distinct-id count, a missing / misplaced FAILED line, a FAILED line without a failure, output after LAB-SUMMARY and
      garbled LAB-SUMMARY records are each rejected with their specific reason; the replay suite's own FAIL lines are not
      judged by the generator while its counts are; the 90 s budget is a problem only for sequential outputs; catalogued
      UNSUPPORTED ids are required in the mode they belong to (run_lab.unsupported_id_problems, run_lab.cross_check); the
      runner's LAB-SUMMARY key tuple equals _lab_trace's; rerecord_corpus.stale_report flags a stale pinned digest;
      NC-RC-46 a missing pinned file is a failure of _lab_trace.drift_report in every tier (lab, behavioural and
      unclassified under their tier's title, non-behavioural as 'pinned source missing'; strict mode too), so run_lab's
      baseline check fails like the generator, and the generator's compare() path (section [5]) names a deleted
      non-behavioural file as that failure, with no drift-rule PASS;
      NC-RC-47 gen_catalogue.tree_record_problems refuses suite outputs without a record of the tree they ran on and
      outputs whose recorded digest of a pinned source differs from the tree (--runs-from / --write); NC-RC-48
      _lab_trace.finish's end-of-suite import guard FAILS (one FAIL line naming the module, appended to the suite's
      FAILURES list, counted) with a planted unclassified repository module in sys.modules (removed afterwards), refuses
      a tuple instead of the FAILURES list, and adds nothing once the module is gone.

The catalogue is built by gen_catalogue.py in this directory (a command-line tool, not a suite) from the suites' tables, the
corpus, _catalogue_data.py and the suites' quick-run outputs; this suite never runs a scenario suite and never imports a
test_*.py file. A change to a lab file needs that regeneration; a change to a behavioural file needs the corpus re-recorded
(rerecord_corpus.py) and then the regeneration; a change to a non-behavioural file needs neither (strict mode aside).
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from pathlib import Path
HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # worktree root
for p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
FAILURES: list[str] = []
PASSES: list[str] = []
PINS: list[str] = []            # held 'finding-reproduces:' checks (this suite has none; counted apart from PASSES)
COUNTED: list[str] = []         # counted findings (this suite reproduces none: it replays the corpus the suites own)
UNSUPPORTED_POINTS: list[str] = []    # one id per printed UNSUPPORTED line (this suite prints none)
BLOCKED: list[str] = []         # blocked scenarios (this suite runs no scenario)
# Phase-sensitivity registry (B4 change 7; HL-10): check-name prefix -> why that check's verdict depends on the lab's
# scheduler phase. The lab runs every firmware interval first at its startup_delay (else one period) after power-on with
# zero offset and reschedules it at due+T; the coupled tier samples the polled template sensors on the uptime grid and
# the RTC rig starts its intervals at the rig boot with a fixed phase. ESPHome 2026.8.2 runs each interval first at
# setup + startup_delay + a random offset in [0, min(T/2, 5 s)) and reschedules it at now+T (scheduler.cpp:105-110,
# 181-184, 540; interval.h; component.cpp:381-391). The tags were found by running every suite under an in-memory
# ESPHome-like phase patch (scratch only, not shipped; quick mode: 8 seeds of the full patch and 3 seeds of each of 3
# narrower variants; extended mode: 3 seeds) plus the audit's list of timing-bound checks. LAB-SUMMARY 'phase_sensitive'
# counts the EXECUTED checks (held or failed) whose name starts with a registered prefix (detected per run, never a
# literal); check_phase_registry() FAILS on a stale prefix (no executed check matches it), a prefix without a reason, or
# an unregistered PHASE_SENSITIVE_EXTENDED_ONLY entry (the prefixes whose checks run only in extended mode: they are
# required to match only there).
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "replay ": (
        "every per-document replay check (digest == trace_digest, every expectation holds, the SOURCE DRIFT form, no "
        "harness exception) replays a recorded fixed action timeline on the lab scheduler (HL-10). The digest covers "
        "every scheduled job's events, so the digest checks fail at any other phase by construction (ESPHome "
        "2026.8.2: setup + startup_delay + a random offset in [0, min(T/2, 5 s)), then now+T); the expectations are "
        "timeline-bound: under the phase patch FW-03-b, FW-05-e, FW-06-a, FW-07-i, -i2, -i3, FW-08-c, -d, -e, "
        "HF-01-a..c, HF-03-a, HF-04-a, HF-05-b, HF-07-c, -e, PB-02-a, RT-01-a, -b and RT-03-a fail an expectation "
        "(FW-06-a, HF-07-c and HF-07-e through their 'writes' expectation, which pins the seq numbers of the V0.1 "
        "used-key prelude writes: they fail it at every patched configuration measured) and HF-04-a, HF-04-c, "
        "HF-06-a and PB-03-b raise (a refused interleaving, an action instant already passed) at some seeds"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []       # executed checks whose name starts with a tag


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (PINS if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def check_phase_registry() -> None:
    """The closing check of the phase-sensitivity registry (fail loud; run after every other check): every
    PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check executed in this run (a stale prefix
    FAILS); a PHASE_SENSITIVE_EXTENDED_ONLY prefix must be registered and is required to match only in extended mode."""
    executed = PASSES + PINS + FAILURES
    hits = {p: sum(1 for n in executed if n.startswith(p)) for p in PHASE_SENSITIVE_TAGS}
    stale = [p for p, n in hits.items() if not n and (EXTENDED or p not in PHASE_SENSITIVE_EXTENDED_ONLY)]
    bad = ([p for p in PHASE_SENSITIVE_EXTENDED_ONLY if p not in PHASE_SENSITIVE_TAGS]
           + [p for p, why in PHASE_SENSITIVE_TAGS.items() if not p.strip() or not isinstance(why, str)
              or not why.strip()])
    check("phase-sensitivity registry: every PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check "
          "executed in this run (no stale tag; LAB-SUMMARY phase_sensitive = the executed tagged checks)",
          not stale and not bad, f"stale {stale}; malformed {bad}")


import contextlib  # noqa: E402
import copy  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]
STRICT_BASELINE = os.environ.get("ECCO_LAB_STRICT_BASELINE") == "1" or "--strict-baseline" in sys.argv[1:]

import _lab_trace as T  # noqa: E402
import _lab_fw  # noqa: E402,F401   registers the replay tier 'firmware'
import _lab_ha  # noqa: E402,F401   registers the replay tier 'coupled'
import _lab_rtc  # noqa: E402,F401  registers the replay tier 'rtc'
import _ha_script_sim as S  # noqa: E402
import gen_catalogue as GC  # noqa: E402   the catalogue generator (a command-line tool, not a suite; runs nothing on import)
import run_lab as RL  # noqa: E402   the runner (a command-line tool, not a suite; runs nothing on import)
import rerecord_corpus as RR  # noqa: E402   the corpus re-record tool (a command-line tool; runs nothing on import)

SUITE = "test_lab_replay_corpus"
LAB_REL = "registry/tests/assurance_lab"
CORPUS_DIR = HERE / "corpus"
CATALOGUE = HERE / "SCENARIO_CATALOGUE.json"
PUBLIC_MAIN = "a7235433ce711e6a8fae5dab0fc8ca6c6f533de6"
CAT_SCHEMA = "ecco-assurance-lab-catalogue/v0"
# The quick-mode LAB-SUMMARY 'finding' value of each scenario suite at this baseline (each root cause counted once across
# the lab; a DUPLICATE is printed but not counted, a MERGED variant prints no FINDING line). A suite change is caught first
# by the lab-file baseline digests ([3]). V0.1 (brief B6.3): lifecycle 8 -> 7 (F-HF05-1 reclassified, a documented limit,
# not counted), phantom 2 -> 1 (F-HF07-2 merged into F-HF07-1).
LAB_SUMMARY_FINDING = {"test_lab_fw_obligations": 5, "test_lab_fw_durability": 8, "test_lab_fw_runtime": 6,
                       "test_lab_ha_lifecycle": 7, "test_lab_ha_phantom": 1, "test_lab_ha_schedules": 7,
                       "test_lab_dst_rtc": 3, "test_lab_property": 0}
TOP_KEYS = ["schema", "baseline", "tiers", "invariants", "known_risks_used", "scenarios", "findings", "root_causes",
            "negative_controls", "unsupported", "harness_limitations", "coverage_matrix", "runtime_quick_s"]
KEYS = {
    "tier": ["id", "engine", "real_source", "model_assumptions"],
    "invariant": ["id", "tier", "meaning", "checker"],
    "scenario": ["id", "title", "suite", "tier", "priority", "classification", "grade", "confidence", "confidence_level",
                 "invariant", "ownership", "anchors", "failure_outcome", "result_summary", "corpus", "phase_sensitive",
                 "phase_sensitive_reason"],
    # V0.1 (brief B6.4): the two-axis verdicts and the injected primitive after "reachability" (gen_catalogue.FIND_KEYS)
    "finding": ["fid", "scenario", "suite", "title", "classification", "root_cause_group", "counted", "duplicate_of",
                "reported_as", "severity", "confidence", "confidence_level", "grade", "reachability", "mechanism_verdict",
                "device_reachability", "injected_primitive", "needs_product_change", "needs_product_change_reason",
                "model_dependence", "repair_scope", "corpus", "verification", "phase_sensitive", "phase_sensitive_reason"],
    "verification": ["source_fidelity_check", "classification_check"],
    "root_cause": ["group", "title", "findings", "classification", "severity", "priority", "notes"],   # B6.5 notes
    # V0.1 (B3.6): same_mutation_as names the control whose mutation this row repeats (null: a distinct mutation)
    "negative_control": ["id", "suite", "mutation", "target_invariant_or_check", "outcome", "same_mutation_as"],
    "unsupported": ["id", "suite", "description"],
    "harness_limitation": ["id", "component", "anchor", "limitation", "effect_on_verdicts", "worked_around_in", "status"],
    "coverage": ["dimensions", "existing", "lab", "intersections"],
    "intersection": ["pair", "required", "existing", "lab", "gap"],
}
REPORTED_AS = ("FINDING", "DUPLICATE", "MERGED")
# baseline.tiers (B1): the tier table gen_catalogue publishes from _lab_trace (compared with a fresh build in [5])
BASELINE_TIER_KEYS = ["rule", "lab", "drift", "method", "behavioural", "non_behavioural", "tier_sources"]
DIMENSIONS = ["schedule start/retry", "lease acquisition", "durable snapshot", "commit false negative", "active lease",
              "HA restore obligation", "lock contention", "stale state", "clock policy (RTC/DST)", "terminal restoration",
              "human manual change", "HA restart", "dongle reboot / power cut", "Modbus faults"]
REQUIRED_PAIRS = [("schedule start/retry", "HA restart"), ("lease acquisition", "commit false negative"),
                  ("active lease", "dongle reboot / power cut"), ("HA restore obligation", "human manual change"),
                  ("lock contention", "terminal restoration"), ("stale state", "active lease"),
                  ("clock policy (RTC/DST)", "active lease"), ("durable snapshot", "dongle reboot / power cut"),
                  ("commit false negative", "HA restore obligation")]
# 'killed(audit)': an audit mutant the lab does not run itself (applied in memory outside the lab); its 'AUDIT-' row names
# the directed checks that failed under it ('checks: <name>, ...'), which gen_catalogue requires held in the plain run
NC_OUTCOMES = ("killed", "survived(expected)", "invalid", "killed(audit)")
CHECKS_TARGET = "checks: "      # a negative-control target naming suite checks: 'checks: <name prefix>, <name prefix>'

INV_RE = re.compile(r"\bINV-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
# spec 0.6 (no 13-digit number) and the repository privacy scan's MPAN rule
# (pattern from tools/tests/test_public_privacy.py:75-76)
THIRTEEN = re.compile(r"(?<![0-9])[0-9]{13}(?![0-9])")
MPAN_WORD = re.compile(r"mpan|meter|octopus|mprn", re.I)
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
# corpus documents the harness negative controls mutate (small, fast firmware documents)
NC_DOC = "FW-06-a"
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")
print("  info  baseline rule: " + ("STRICT (ECCO_LAB_STRICT_BASELINE=1): every catalogue-pinned source must be unchanged"
                                   if STRICT_BASELINE else
                                   "tiered (B1): lab and behavioural files pinned exactly (a changed one is a named FAIL "
                                   "in [5]); a changed non-behavioural file is SOURCE DRIFT, not a failure"))


# ===========================================================================================================================
# helpers (pure functions; nothing here writes anything)
# ===========================================================================================================================
def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _no_constant(name):
    raise ValueError(f"non-finite JSON constant {name}")


def strict_json(raw: bytes):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes, parse_constant=_no_constant)


def lf_bytes(raw: bytes) -> bytes:
    """git's CRLF -> LF normalisation (a core.autocrlf=true checkout writes CRLF; the repository stores LF)."""
    return raw.replace(b"\r\n", b"\n")


def catalogue_bytes_ok(raw: bytes) -> bool:
    """ASCII, LF line ends (after the CRLF normalisation: no lone CR) and a final newline."""
    b = lf_bytes(raw)
    return bool(b) and b.isascii() and b"\r" not in b and b.endswith(b"\n")


def canonical_ok(doc: dict, raw: bytes) -> bool:
    """The file is the canonical _lab_trace.dumps_doc form of its document (after the CRLF normalisation)."""
    return T.dumps_doc(doc).encode("ascii") == lf_bytes(raw)


def digit_run_problems(text: str) -> list[str]:
    """Spec 0.6: a 13-digit decimal run is accepted only inside a 64-hex sha256 digest (hash text, not a number), and no
    line with a 13-digit run names a meter word (the repository privacy scan's MPAN rule)."""
    out = []
    for i, ln in enumerate(text.splitlines(), 1):
        if THIRTEEN.search(HEX64.sub("-", ln)):
            out.append(f"line {i}: a 13-digit run outside a sha256 digest")
        if THIRTEEN.search(ln) and MPAN_WORD.search(ln):
            out.append(f"line {i}: a 13-digit run on a line that names a meter word")
    return out


_TEXT: dict[str, str | None] = {}


def repo_text(rel: str) -> str | None:
    """LF-normalised UTF-8 text of a repo file (cached), or None when it does not exist."""
    if rel not in _TEXT:
        f = ROOT / rel
        _TEXT[rel] = f.read_bytes().decode("utf-8").replace("\r\n", "\n") if f.is_file() else None
    return _TEXT[rel]


_SHA: dict[str, str | None] = {}


def repo_sha(rel: str) -> str | None:
    """LF-normalised sha256 of a repo file (cached; the tree does not change during a run), or None when it is missing."""
    if rel not in _SHA:
        _SHA[rel] = T.source_digest(rel) if (ROOT / rel).is_file() else None
    return _SHA[rel]


def is_lab(path: str) -> bool:
    """A lab-owned file (pinned exactly); anything else follows the spec 2.2 drift rule."""
    return path.startswith(f"{LAB_REL}/")


def pinned_sources(cat) -> dict:
    base = cat.get("baseline") if isinstance(cat, dict) else None
    src = base.get("sources") if isinstance(base, dict) else None
    return src if isinstance(src, dict) else {}


def baseline_drift(cat, sha_of=repo_sha) -> list[str]:
    """The catalogue-pinned paths whose current LF-normalised sha256 differs from the recorded one (or that are missing)."""
    return sorted(p for p, sha in pinned_sources(cat).items() if sha_of(p) != sha)


def unexplained_drift(results: dict, tree_drift, *, strict: bool = STRICT_BASELINE) -> list[str]:
    """The drifted corpus documents the catalogue baseline does not explain: one of its drifted paths is unchanged against
    the catalogue baseline (the document records another tree's digest: re-record it). Strict mode: every drifted one."""
    changed = set(tree_drift)
    return sorted(stem for stem, r in results.items()
                  if r is not None and r.drift and (strict or any(p not in changed for p in r.drifted_paths)))


def nc_in_source(nid: str, src: str) -> bool:
    """An NC id occurs in its suite's source, or is one variant of an f-string id (NC1a / NC1b from f"NC1{m}")."""
    return nid in src or re.sub(r"[a-z]$", "{", nid) in src


def checks_target_ok(target: str, scenario_ids) -> bool:
    """A negative-control target 'checks: <name>, <name>' whose every check-name prefix starts with one of the suite's
    scenario ids (followed by a space or a colon), e.g. 'checks: FW-09 a.1, FW-09 a.2'."""
    names = target[len(CHECKS_TARGET):].split(", ") if target.startswith(CHECKS_TARGET) else []
    return bool(names) and all(n.strip() == n and any(n == sid or n.startswith((sid + " ", sid + ":"))
                                                       for sid in scenario_ids) for n in names)


def phase_fields_ok(entry: dict) -> bool:
    """phase_sensitive is a bool; its reason is a string, non-empty exactly when phase_sensitive is true."""
    flag, why = entry.get("phase_sensitive"), entry.get("phase_sensitive_reason")
    return isinstance(flag, bool) and isinstance(why, str) and (bool(why.strip()) == flag)


def first_word(text) -> str:
    return text.split()[0] if isinstance(text, str) and text.split() else ""


def classification_ok(text) -> bool:
    try:
        T.parse_classification(text)
    except T.LabTraceError:
        return False
    return True


def lab_files() -> list[str]:
    """Every lab suite / helper / runner / tool / corpus file the catalogue must pin, this suite included (V0.1, B1:
    _lab_trace.LAB_RULE; SCENARIO_CATALOGUE.json is the one exemption, it cannot pin its own digest)."""
    out = [f"{LAB_REL}/{p.name}" for p in sorted(HERE.glob("*.py"))]
    out += [f"{LAB_REL}/corpus/{p.name}" for p in sorted(CORPUS_DIR.glob("*.json"))]
    return out


def anchor_hits(path: str, snippet: str, text_of=repo_text) -> int:
    """How often `snippet` occurs in the repository file `path` (-1: the file is missing or the snippet is empty): the
    exactly-once anchor read of [3] (trace_inputs.py classifies a read through this helper as an anchor read)."""
    src = text_of(path)
    return src.count(snippet) if src is not None and snippet else -1


def cited(path: str, text_of=repo_text) -> bool:
    """The repository file `path` exists (a coverage-matrix citation; no content is used: trace_inputs.py classifies a
    read through this helper as an existence check)."""
    return text_of(path) is not None


CATEGORIES = ("schema", "baseline", "corpus", "sources", "counting", "root-causes", "invariants", "anchors",
              "known-risks", "negative-controls", "unsupported", "harness-limitations", "coverage", "runtime")


def catalogue_problems(cat: dict, docs: dict, *, text_of=repo_text, sha_of=repo_sha, files=None,
                       strict: bool = STRICT_BASELINE) -> dict[str, list[str]]:
    """Every cross-check of [3] as {category: [problem, ...]} (an empty list per category = clean)."""
    P = {c: [] for c in CATEGORIES}
    sch = P["schema"]

    def keys(where, obj, want):
        if not isinstance(obj, dict) or list(obj) != want:
            sch.append(f"{where}: keys {list(obj) if isinstance(obj, dict) else type(obj).__name__} != {want}")
            return False
        return True

    if not keys("catalogue", cat, TOP_KEYS):
        return P
    if cat["schema"] != CAT_SCHEMA:
        sch.append(f"schema {cat['schema']!r} != {CAT_SCHEMA!r}")
    tiers = {t.get("id") for t in cat["tiers"] if keys(f"tier {t.get('id')}", t, KEYS["tier"])}
    if tiers != set(T.TIERS):
        sch.append(f"tier ids {sorted(tiers)} != {sorted(T.TIERS)}")
    scen = {}
    for x in cat["scenarios"]:
        if not keys(f"scenario {x.get('id')}", x, KEYS["scenario"]):
            continue
        if x["id"] in scen:
            sch.append(f"scenario {x['id']} twice")
        scen[x["id"]] = x
        for fld, ok in (("tier", x["tier"] in T.TIERS), ("priority", x["priority"] in T.PRIORITIES),
                        ("classification", classification_ok(x["classification"])), ("grade", x["grade"] in T.GRADES),
                        ("confidence", first_word(x["confidence"]) in T.CONFIDENCES),
                        ("confidence_level", x["confidence_level"] in T.CONFIDENCES
                         and x["confidence_level"] == first_word(x["confidence"])),
                        ("corpus", isinstance(x["corpus"], list)), ("anchors", isinstance(x["anchors"], list)),
                        ("phase_sensitive", phase_fields_ok(x))):
            if not ok:
                sch.append(f"scenario {x['id']}: {fld} {x[fld]!r} is not lab vocabulary")
    fnd = {}
    for f in cat["findings"]:
        if not keys(f"finding {f.get('fid')}", f, KEYS["finding"]):
            continue
        if f["fid"] in fnd:
            sch.append(f"finding {f['fid']} twice")
        fnd[f["fid"]] = f
        keys(f"finding {f['fid']} verification", f["verification"], KEYS["verification"])
        for fld, ok in (("classification", classification_ok(f["classification"])), ("grade", f["grade"] in T.GRADES),
                        ("confidence", first_word(f["confidence"]) in T.CONFIDENCES),
                        ("confidence_level", f["confidence_level"] in T.CONFIDENCES
                         and f["confidence_level"] == first_word(f["confidence"])),
                        ("counted", isinstance(f["counted"], bool)),
                        ("duplicate_of", f["duplicate_of"] is None or isinstance(f["duplicate_of"], str)),
                        ("reported_as", f["reported_as"] in REPORTED_AS),
                        ("corpus", isinstance(f["corpus"], list)), ("phase_sensitive", phase_fields_ok(f))):
            if not ok:
                sch.append(f"finding {f['fid']}: {fld} {f[fld]!r} is not lab vocabulary")
    for r in cat["root_causes"]:
        if keys(f"root cause {r.get('group')}", r, KEYS["root_cause"]):
            if not classification_ok(r["classification"]) or r["priority"] not in T.PRIORITIES:
                sch.append(f"root cause {r['group']}: classification / priority not lab vocabulary")
    nc_shaped = [n for n in cat["negative_controls"] if keys(f"negative control {n.get('id')}", n,
                                                             KEYS["negative_control"])]
    canonical_nc = {n["id"] for n in nc_shaped if n["same_mutation_as"] is None}
    for n in nc_shaped:
        if n["outcome"] not in NC_OUTCOMES:
            sch.append(f"negative control {n['id']}: outcome {n['outcome']!r} not in {NC_OUTCOMES}")
        s = n["same_mutation_as"]
        if s is not None and (s == n["id"] or s not in canonical_nc):
            sch.append(f"negative control {n['id']}: same_mutation_as {s!r} is not another catalogue control whose own "
                       "same_mutation_as is null (no self reference, no chain)")
    for u in cat["unsupported"]:
        keys(f"unsupported {u.get('id')}", u, KEYS["unsupported"])
    hls = [h for h in cat["harness_limitations"] if keys(f"harness limitation {h.get('id') if isinstance(h, dict) else h}",
                                                          h, KEYS["harness_limitation"])]
    for i in cat["invariants"]:
        keys(f"invariant {i.get('id')}", i, KEYS["invariant"])
    keys("coverage_matrix", cat["coverage_matrix"], KEYS["coverage"])
    for i in cat["coverage_matrix"].get("intersections", []):
        keys(f"intersection {i.get('pair')}", i, KEYS["intersection"])
    for kind, ids in (("negative control", [n.get("id") for n in cat["negative_controls"]]),
                      ("invariant", [i.get("id") for i in cat["invariants"]]),
                      ("root cause", [r.get("group") for r in cat["root_causes"]]),
                      ("harness limitation", [h.get("id") for h in hls])):
        if len(ids) != len(set(ids)):
            sch.append(f"duplicate {kind} ids")

    # --- baseline: every lab file is pinned and unchanged; a non-lab file is drift-tolerant (spec 2.2) unless strict
    base = cat["baseline"]
    pinned = {}
    shaped = keys("baseline", base, ["public_main", "sources", "tiers"])
    if shaped:
        keys("baseline.tiers", base["tiers"], BASELINE_TIER_KEYS)
    elif isinstance(base, dict) and "tiers" not in base:
        sch.append("re-generate the catalogue: it has no baseline.tiers (the B1 tier table gen_catalogue publishes)")
    if shaped or (isinstance(base, dict) and {"public_main", "sources"} <= set(base)):   # judge the pins regardless
        if base["public_main"] != PUBLIC_MAIN:
            P["baseline"].append(f"public_main {base['public_main']} != the pinned {PUBLIC_MAIN}")
        pinned = base["sources"] if isinstance(base["sources"], dict) else {}
        for path, sha in sorted(pinned.items()):
            now = sha_of(path)
            if now != sha and (is_lab(path) or strict):
                P["baseline"].append(f"re-generate the catalogue: {path} sha256 {'missing' if now is None else now[:12]} "
                                     f"!= recorded {sha[:12]} ({'a lab file' if is_lab(path) else 'strict mode'})")
        for path in (files if files is not None else lab_files()):
            if path not in pinned:
                P["baseline"].append(f"re-generate the catalogue: {path} is not pinned in baseline.sources")

    # --- corpus ownership, classification and recorded digests
    cp = P["corpus"]
    for stem, d in sorted(docs.items()):
        for path, sha in sorted(d["source_digests"].items()):
            if pinned.get(path) != sha:
                cp.append(f"corpus {stem} records {path} sha256 {sha[:12]} != the catalogue baseline "
                          f"{(pinned.get(path) or 'unpinned')[:12]} (re-record the document or re-generate the catalogue)")
    owner = {}
    for x in scen.values():
        for c in x["corpus"]:
            if c in owner:
                cp.append(f"corpus {c} is listed by {owner[c]} and {x['id']}")
            owner[c] = x["id"]
            if c not in docs:
                cp.append(f"scenario {x['id']} lists corpus {c}, which has no file")
    for stem in docs:
        if stem not in owner:
            cp.append(f"corpus file {stem} belongs to no catalogue scenario")
    listed = {}
    for f in fnd.values():
        for c in f["corpus"]:
            if c not in docs:
                cp.append(f"finding {f['fid']} lists corpus {c}, which has no file")
                continue
            listed.setdefault(c, []).append(f)
            o = scen.get(owner.get(c))
            if o is not None and o["suite"] != f["suite"]:
                cp.append(f"finding {f['fid']} ({f['suite']}) lists corpus {c} of {o['id']} ({o['suite']})")
    for stem, d in docs.items():
        fs = listed.get(stem, [])
        for f in fs:
            if d["classification"] != f["classification"]:
                cp.append(f"corpus {stem} classification {d['classification']} != {f['fid']} {f['classification']}")
            if d["grade"] != f["grade"]:
                cp.append(f"corpus {stem} grade {d['grade']} != {f['fid']} {f['grade']}")
            if d["confidence"] != f["confidence_level"]:
                cp.append(f"corpus {stem} confidence {d['confidence']} != {f['fid']} {f['confidence_level']}")
        if not fs and d["classification"] != "PASS":
            cp.append(f"corpus {stem} is {d['classification']} but no catalogue finding lists it")

    # --- suite source texts (read as text, never imported)
    sp = P["sources"]
    suite_src = {}
    for suite in sorted({x["suite"] for x in scen.values()} | {f["suite"] for f in fnd.values()} |
                        {n["suite"] for n in cat["negative_controls"]} | {u["suite"] for u in cat["unsupported"]}):
        suite_src[suite] = text_of(f"{LAB_REL}/{suite}.py")
        if suite_src[suite] is None:
            sp.append(f"suite file {suite}.py does not exist")
    for x in scen.values():
        if x["id"] not in (suite_src.get(x["suite"]) or ""):
            sp.append(f"scenario {x['id']} does not occur in {x['suite']}.py")
    for f in fnd.values():
        src = suite_src.get(f["suite"]) or ""
        if f["fid"] not in src:
            sp.append(f"finding {f['fid']} does not occur in {f['suite']}.py")
        if f["classification"] not in src:
            sp.append(f"finding {f['fid']}: classification {f['classification']} does not occur in {f['suite']}.py")
        s = scen.get(f["scenario"])
        if s is None or s["suite"] != f["suite"]:
            sp.append(f"finding {f['fid']}: scenario {f['scenario']} is not a scenario of {f['suite']}")
        dup = f["duplicate_of"]
        merged = dup is not None and any(f["fid"] in ln and f"merged into {dup}" in ln for ln in src.splitlines())
        if (f["reported_as"] == "MERGED") != merged:
            sp.append(f"finding {f['fid']}: reported_as {f['reported_as']} but {f['suite']}.py "
                      f"{'records' if merged else 'has no'} 'merged into {dup}' for it")
        if f["reported_as"] == "DUPLICATE" and dup not in src:
            sp.append(f"finding {f['fid']}: a DUPLICATE but {f['suite']}.py never names its owner {dup}")
    for n in cat["negative_controls"]:
        if n["outcome"] == "killed(audit)":    # an audit mutant row: a catalogue id, never in a suite
            if not n["id"].startswith("AUDIT-"):
                sp.append(f"negative control {n['id']}: an audit mutant row needs an 'AUDIT-' id")
        elif not nc_in_source(n["id"], suite_src.get(n["suite"]) or ""):
            sp.append(f"negative control {n['id']} does not occur in {n['suite']}.py")

    # --- counting: one root cause counted once; per suite the LAB-SUMMARY 'finding' value
    ct = P["counting"]
    suites = sorted({f["suite"] for f in fnd.values()})
    if suites != sorted(LAB_SUMMARY_FINDING):
        ct.append(f"suites with findings {suites} != {sorted(LAB_SUMMARY_FINDING)}")
    for suite, want in sorted(LAB_SUMMARY_FINDING.items()):
        n = sum(1 for f in fnd.values() if f["suite"] == suite and f["counted"])
        if n != want:
            ct.append(f"{suite}: {n} counted catalogue findings != its LAB-SUMMARY finding {want}")
    for f in fnd.values():
        if f["counted"] != (f["reported_as"] == "FINDING"):
            ct.append(f"{f['fid']}: counted {f['counted']} disagrees with reported_as {f['reported_as']}")
        if f["counted"] and f["duplicate_of"] is not None:
            ct.append(f"{f['fid']} is counted but names duplicate_of {f['duplicate_of']}")
        if not f["counted"]:
            o = fnd.get(f["duplicate_of"])
            if o is None or not o["counted"]:
                ct.append(f"{f['fid']} is not counted but its duplicate_of {f['duplicate_of']} is not a counted finding")
            elif o["root_cause_group"] != f["root_cause_group"]:
                ct.append(f"{f['fid']} and its owner {o['fid']} are in different root-cause groups")

    # --- root causes: each finding in exactly one homogeneous group with a counted member
    rc = P["root-causes"]
    member_of = {}
    for r in cat["root_causes"]:
        classes = set()
        for m in r["findings"]:
            if m in member_of:
                rc.append(f"{m} is in {member_of[m]} and {r['group']}")
            member_of[m] = r["group"]
            f = fnd.get(m)
            if f is None:
                rc.append(f"{r['group']}: unknown finding {m}")
                continue
            classes.add(f["classification"])
            if f["root_cause_group"] != r["group"]:
                rc.append(f"{m}: root_cause_group {f['root_cause_group']} != {r['group']}")
        if classes and classes != {r["classification"]}:
            rc.append(f"{r['group']}: member classifications {sorted(classes)} != {r['classification']}")
        if not any(fnd.get(m, {}).get("counted") for m in r["findings"]):
            rc.append(f"{r['group']}: no counted member (a root cause is counted once)")
    for fid in fnd:
        if fid not in member_of:
            rc.append(f"{fid} is in no root-cause group")

    # --- invariants: checker exists; every referenced invariant is catalogued
    iv = P["invariants"]
    invs = {i["id"]: i for i in cat["invariants"]}
    for i in invs.values():
        mod, _, fn = i["checker"].partition(".")
        src = text_of(f"{LAB_REL}/{mod}.py")
        if i["tier"] not in T.TIERS or not fn or src is None or f"def {fn}(" not in src:
            iv.append(f"invariant {i['id']}: checker {i['checker']} / tier {i['tier']} not found")
    referenced = set()
    for x in scen.values():
        referenced |= {m for m in INV_RE.findall(x["invariant"]) if m != "INV-HF"}
    referenced |= {d["invariant"] for d in docs.values()}
    referenced |= {n["target_invariant_or_check"] for n in cat["negative_controls"]
                   if n["target_invariant_or_check"].startswith("INV-")}
    for m in sorted(referenced - set(invs)):
        iv.append(f"invariant {m} is referenced but has no catalogue entry")

    # --- anchors: '<path>: <exact snippet>' occurs exactly once
    for x in scen.values():
        for a in x["anchors"]:
            path, sep, snippet = a.partition(": ")
            n = anchor_hits(path, snippet, text_of) if sep else -1
            if n != 1:
                P["anchors"].append(f"{x['id']}: anchor found {n} time(s): {a[:90]!r}")

    # --- known risks: exactly the ids the classifications use, all registered
    used = set()
    for e in list(scen.values()) + list(fnd.values()) + list(docs.values()):
        kind = e["classification"]
        if kind.startswith("FINDING-KNOWN:"):
            used.add(kind.split(":", 1)[1])
    if cat["known_risks_used"] != sorted(used):
        P["known-risks"].append(f"known_risks_used {cat['known_risks_used']} != the ids in use {sorted(used)}")
    for r in cat["known_risks_used"]:
        if r not in T.KNOWN_RISKS:
            P["known-risks"].append(f"{r} is not a registered KNOWN_RISKS id")

    # --- negative controls / unsupported
    sids_of = {}
    for x in scen.values():
        sids_of.setdefault(x["suite"], []).append(x["id"])
    sids_of.setdefault(SUITE, []).extend(GC.REPLAY_CHECK_PREFIXES)   # this suite's own controls name its [5] checks
    for n in cat["negative_controls"]:
        t = n["target_invariant_or_check"]
        if not (t in invs or t.startswith("finding-reproduces:") and t.split(":", 1)[1] in fnd
                or checks_target_ok(t, sids_of.get(n["suite"], []))):
            P["negative-controls"].append(f"{n['id']}: target {t} is neither a catalogue invariant, a finding check nor "
                                          f"'{CHECKS_TARGET}' with check names that start with a {n['suite']} scenario id")
        if n["outcome"] == "killed(audit)" and not t.startswith(CHECKS_TARGET):
            P["negative-controls"].append(f"{n['id']}: an audit mutant row must name its killing checks "
                                          f"('{CHECKS_TARGET}...')")
    prefixes = {}
    for x in scen.values():
        prefixes.setdefault(x["suite"], set()).add(x["id"][:5])
    for u in cat["unsupported"]:
        if u["id"][:5] not in prefixes.get(u["suite"], set()) or not u["description"].strip():
            P["unsupported"].append(f"{u['id']}: not a {u['suite']} scenario item or empty description")

    # --- harness limitations: HL-1.. in order, anchored exactly once, workarounds naming existing lab suites, a status
    hl = P["harness-limitations"]
    if not hls:
        hl.append("no harness limitation is recorded")
    for n, h in enumerate(hls, 1):
        if h["id"] != f"HL-{n}":
            hl.append(f"{h['id']}: ids must run HL-1, HL-2, ... in order")
        path, sep, snippet = h["anchor"].partition(": ") if isinstance(h["anchor"], str) else ("", "", "")
        cnt = anchor_hits(path, snippet, text_of) if sep else -1
        if cnt != 1:
            hl.append(f"{h['id']}: anchor found {cnt} time(s): {str(h['anchor'])[:90]!r}")
        rows = h["worked_around_in"] if isinstance(h["worked_around_in"], list) else []
        if not rows:
            hl.append(f"{h['id']}: no workaround row")
        for row in rows:
            suite, sep, how = row.partition(": ") if isinstance(row, str) else ("", "", "")
            if not sep or not how.strip() or not (HERE / f"{suite}.py").is_file() or not suite.startswith("test_lab_"):
                hl.append(f"{h['id']}: workaround row {str(row)[:60]!r} does not name an existing lab suite")
        for fld in ("component", "limitation", "effect_on_verdicts", "status"):
            if not isinstance(h[fld], str) or not h[fld].strip():
                hl.append(f"{h['id']}: empty {fld}")

    # --- coverage matrix
    cv, cm = P["coverage"], cat["coverage_matrix"]
    if cm.get("dimensions") != DIMENSIONS:
        cv.append("dimensions differ from the requested 14")
    for part in ("existing", "lab"):
        if sorted(cm.get(part, {})) != sorted(DIMENSIONS):
            cv.append(f"{part}: keys are not the 14 dimensions")
    for dim, rows in cm.get("existing", {}).items():
        for row in rows:
            path, sep, what = row.partition(": ")
            if not sep or not what.strip() or not cited(path, text_of):
                cv.append(f"existing[{dim}]: {row[:80]!r} does not cite an existing suite file")
    for dim, ids in cm.get("lab", {}).items():
        for sid in ids:
            if sid not in scen:
                cv.append(f"lab[{dim}]: {sid} is not a catalogue scenario")
    pairs = set()
    for i in cm.get("intersections", []):
        pr = i.get("pair")
        a, b = pr if isinstance(pr, list) and len(pr) == 2 else (None, None)
        if a not in DIMENSIONS or b not in DIMENSIONS:
            cv.append(f"intersection {pr}: not a pair of dimensions")
        pairs.add((a, b))
        if i["existing"] != "none" and not cited(i["existing"], text_of):
            cv.append(f"intersection {i['pair']}: existing {i['existing']!r} is neither 'none' nor a suite file")
        for sid in i["lab"]:
            if sid not in scen:
                cv.append(f"intersection {i['pair']}: {sid} is not a catalogue scenario")
        if not isinstance(i["gap"], str):
            cv.append(f"intersection {i['pair']}: gap is not a string")
        if not isinstance(i.get("required"), bool) or i.get("required") != ((a, b) in REQUIRED_PAIRS):
            cv.append(f"intersection {i['pair']}: required flag {i.get('required')!r} != "
                      f"{(a, b) in REQUIRED_PAIRS} (REQUIRED_PAIRS)")
    for pr in REQUIRED_PAIRS:
        if pr not in pairs:
            cv.append(f"required intersection {pr} is missing")

    # --- runtime
    rt = cat["runtime_quick_s"]
    for p in sorted(HERE.glob("test_lab_*.py")):
        if p.stem != SUITE and p.stem not in rt:
            P["runtime"].append(f"{p.stem} has no quick runtime")
    for suite, v in rt.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 90:
            P["runtime"].append(f"{suite}: quick runtime {v!r} is not within (0, 90] s")
    return P


def replay_quiet(doc):
    """T.replay with its stdout captured: (result, printed text). Exceptions propagate to the caller."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = T.replay(doc)
    return r, buf.getvalue()


def effective_doc(doc: dict, pinned: dict) -> dict:
    """The document as [2] replays it (B1 tier pins): its own source_digests plus each of its tier's TIER_SOURCES it does
    not pin itself, at the catalogue baseline's digest (a tier source the catalogue does not pin is left out: the [2]
    tier-pin check fails for it). The digest, the actions and the expectations are the document's own."""
    d = copy.deepcopy(doc)
    for p in T.tier_pins(doc["tier"]):
        if p not in d["source_digests"] and isinstance(pinned.get(p), str):
            d["source_digests"][p] = pinned[p]
    return d


def tier_pin_shortfalls(docs: dict) -> list[str]:
    """The corpus documents ({id: doc}) whose own source_digests lack a file of their tier's TIER_SOURCES ([2])."""
    return sorted(s for s, d in docs.items() if set(T.tier_pins(d["tier"])) - set(d["source_digests"]))


def anchors_not_once(doc: dict, text_of=repo_text) -> list[str]:
    """The document's source anchors that do not occur exactly once in this tree (their lines are not compared)."""
    out = []
    for a in doc["source_anchors"]:
        src = text_of(a["path"])
        n = src.count(a["text"]) if src is not None else -1
        if n != 1:
            out.append(f"{a['path']}: found {n} time(s): {a['text'][:60]!r}")
    return out


# ===========================================================================================================================
# [0] the catalogue file
# ===========================================================================================================================
def section_catalogue_file():
    print("[0] SCENARIO_CATALOGUE.json: strict JSON, ASCII, LF, catalogue schema and lab vocabulary, 13-digit rule")
    raw = CATALOGUE.read_bytes() if CATALOGUE.is_file() else b""
    check("the catalogue file exists", bool(raw))
    try:
        cat = strict_json(raw)
        parsed = True
    except ValueError as exc:   # a parse failure is a FAIL, never a pass
        cat, parsed = {}, False
        check("the catalogue parses as strict JSON (no duplicate key, no NaN / Infinity)", False, str(exc)[:200])
    if parsed:
        check("the catalogue parses as strict JSON (no duplicate key, no NaN / Infinity)", True)
    check("the catalogue is ASCII with LF line ends and a final newline (a CRLF working copy is normalised first)",
          catalogue_bytes_ok(raw))
    check("the catalogue has exactly the schema's top-level keys, in order", isinstance(cat, dict) and list(cat) == TOP_KEYS,
          str(list(cat) if isinstance(cat, dict) else type(cat)))
    probs = digit_run_problems(lf_bytes(raw).decode("utf-8", "replace"))
    check("spec 0.6: every 13-digit run in the catalogue lies inside a sha256 digest and no such line names a meter word",
          not probs, "; ".join(probs[:4]))
    return cat


CAT = section_catalogue_file()
TREE_DRIFT = baseline_drift(CAT)     # the catalogue-pinned sources that changed in this tree ([] on the recorded baseline)


# ===========================================================================================================================
# [1] corpus schema
# ===========================================================================================================================
def section_corpus_schema():
    print("[1] corpus schema: strict load + validate_doc + stem == id, canonical form, synthetic, 13-digit rule")
    docs = {}
    try:
        for d in T.load_corpus(CORPUS_DIR):
            docs[d["id"]] = d
        loaded = True
    except (T.LabTraceError, ValueError) as exc:   # a schema failure is a FAIL with its message, never a pass
        loaded = False
        check("every corpus file loads through _lab_trace.load_corpus (strict JSON, validate_doc, stem == id)", False,
              str(exc)[:300])
    files = sorted(CORPUS_DIR.glob("*.json"))
    if loaded:
        check(f"every corpus file loads through _lab_trace.load_corpus (strict JSON, validate_doc, stem == id): "
              f"{len(docs)} documents", len(docs) == len(files) and len(docs) > 0)
    noncanon = [f.stem for f in files if f.stem in docs and not canonical_ok(docs[f.stem], f.read_bytes())]
    check("every corpus file is in the canonical _lab_trace.dumps_doc form (sorted keys, indent 2, ASCII, LF; a CRLF "
          "working copy is normalised first)", not noncanon, str(noncanon))
    check("every corpus document is synthetic and names a registered tier",
          all(d["synthetic"] is True and d["tier"] in T.TIERS for d in docs.values()))
    runs = [f"{f.stem} {p}" for f in files for p in digit_run_problems(lf_bytes(f.read_bytes()).decode("utf-8", "replace"))]
    check("spec 0.6: every 13-digit run in a corpus file lies inside a sha256 digest and no such line names a meter word",
          not runs, "; ".join(runs[:4]))
    cat_stems = sorted({c for x in CAT.get("scenarios", []) for c in x.get("corpus", [])}) if isinstance(CAT, dict) else []
    check("the catalogue's scenario corpus lists name exactly the corpus files", cat_stems == sorted(docs),
          str(sorted(set(cat_stems) ^ set(docs))))
    return docs


DOCS = section_corpus_schema()


# ===========================================================================================================================
# [2] replay
# ===========================================================================================================================
def section_replay():
    print("[2] replay every corpus document through _lab_trace.replay (drift rule; every drift explained by the baseline)")
    stems = sorted(DOCS)
    skipped: list[str] = []          # quick mode replays every document (measured well inside the 90 s budget)
    print(f"  info  replaying {len(stems) - len(skipped)} of {len(stems)} documents; skipped: "
          f"{', '.join(skipped) if skipped else 'none'}")
    local_before = S.LOCAL
    stray = T.unclassified_imports()
    imported = [p for p in T.imported_repo_files() if not T.is_lab_path(p)]
    check(f"B1 import guard (mid-run): every repository module in this process's sys.modules outside the lab "
          f"({len(imported)}: what the three replay tiers, gen_catalogue, run_lab and rerecord_corpus imported at load "
          "time) is in the behavioural tier (_lab_trace.finish repeats the guard at the end of every suite; a data read "
          "is found only by trace_inputs.py)", not stray, f"classify in _lab_trace.BEHAVIOURAL and pin: {stray}")
    pinned = pinned_sources(CAT)
    tier_files = sorted({p for srcs in T.TIER_SOURCES.values() for p in srcs})
    unpinned = [p for p in tier_files if not isinstance(pinned.get(p), str)]
    check(f"{T.TIER_PIN_CHECK}: every TIER_SOURCES file ({len(tier_files)}) is pinned in the catalogue baseline (each "
          "document is replayed against its own source_digests plus its tier's TIER_SOURCES at those digests)",
          not unpinned, f"re-generate the catalogue: not pinned {unpinned[:6]}"
          + (f" (+{len(unpinned) - 6})" if len(unpinned) > 6 else ""))
    short = tier_pin_shortfalls(DOCS)
    check(f"{T.TIER_PIN_CHECK}: every corpus document ({len(stems)}) pins its tier's TIER_SOURCES in its own "
          "source_digests", not short, f"re-record with rerecord_corpus.py <id> --pin-tier-sources: {short[:6]}"
          + (f" (+{len(short) - 6})" if len(short) > 6 else ""))
    results = {}
    for stem in stems:
        doc = DOCS[stem]
        try:
            r, printed = replay_quiet(effective_doc(doc, pinned))
        except Exception as exc:     # a harness exception is that document's FAIL (never a pass)
            results[stem] = None
            check(f"replay {stem}: no harness exception", False, f"{type(exc).__name__}: {str(exc)[:200]}")
            continue
        results[stem] = r
        for line in printed.splitlines():
            print(f"  {line}")       # SOURCE DRIFT / ANCHOR DRIFT lines of the engine
        if r.drift:
            check(f"replay {stem}: SOURCE DRIFT ({', '.join(r.drifted_paths)}) - judged on its expectations only",
                  not r.failed_expectations, str([f["detail"] for f in r.failed_expectations])[:300])
            # the second check of a drifted document (two checks per document, drifted or not)
            once = anchors_not_once(doc)
            if all(T.source_tier(p) == "non-behavioural" for p in r.drifted_paths):
                check(f"replay {stem}: non-behavioural SOURCE DRIFT only - digest == trace_digest and every anchor occurs "
                      "exactly once (a non-behavioural file cannot change a trace)",
                      r.digest == doc["trace_digest"] and not once,
                      f"digest {r.digest[:12]} vs {doc['trace_digest'][:12]}; {once[:2]}")
            else:
                check(f"replay {stem}: every anchor still occurs exactly once (lab or behavioural SOURCE DRIFT: the trace "
                      "digest is not compared; [5] names the changed file and the documents to re-record)", not once,
                      str(once[:2]))
        else:
            check(f"replay {stem}: every expectation holds", not r.failed_expectations,
                  str([f["detail"] for f in r.failed_expectations])[:300])
            check(f"replay {stem}: digest == trace_digest and every anchor at its recorded line",
                  r.ok and not r.digest_mismatch and not r.anchor_problems,
                  f"digest {r.digest[:12]} vs {doc['trace_digest'][:12]}; anchors {list(r.anchor_problems)[:2]}")
    bad = unexplained_drift(results, TREE_DRIFT)
    check("drift rule: every drifted corpus document is explained by a catalogue-baseline source changed in this tree (on "
          "the recorded baseline none is drifted" + ("; strict mode: none at all)" if STRICT_BASELINE else ")"), not bad,
          f"re-record: {bad}")
    check("the replays leave no process-global leftover (S.LOCAL is the same object)", S.LOCAL is local_before)
    if EXTENDED:
        t_ext = time.perf_counter()
        diff = []
        for stem in stems:
            r1 = results.get(stem)
            if r1 is None:
                continue
            r2, _ = replay_quiet(DOCS[stem])
            if r2.digest != r1.digest or T.canonical_json(r2.observations) != T.canonical_json(r1.observations):
                diff.append(stem)
        check("extended: a second replay of every document gives the identical digest and observations", not diff,
              str(diff))
        print(f"  info  extended second replay runtime_s {time.perf_counter() - t_ext:.1f}")
    return results


RESULTS = section_replay()


# ===========================================================================================================================
# [3] catalogue cross-checks
# ===========================================================================================================================
LABELS = {
    "schema": "every entry has the schema's exact keys and lab vocabulary (confidence_level, reported_as, "
              "phase_sensitive with its reason; baseline public_main / sources / tiers); ids are unique",
    "baseline": "every lab suite / helper / runner / corpus file is pinned and unchanged" +
                (" and so is every other pinned source (strict mode)" if STRICT_BASELINE else
                 " (else re-generate the catalogue); other sources follow the tiered drift rule ([5])"),
    "corpus": "every corpus document records the catalogue's baseline digests; every corpus stem belongs to exactly one "
              "scenario and exists; a finding's documents carry its classification / grade / confidence_level; a "
              "document no finding lists is PASS",
    "sources": "every scenario id, finding id, finding classification, merge record and negative-control id occurs in its "
               "suite's source text (read as text, never imported)",
    "counting": "counted findings per suite equal the recorded LAB-SUMMARY 'finding' value; reported_as FINDING iff "
                "counted; every duplicate or merged variant names a counted owner in its root-cause group",
    "root-causes": "every finding is in exactly one homogeneous root-cause group, each with a counted member",
    "invariants": "every invariant checker exists and every referenced invariant is catalogued",
    "anchors": "every scenario anchor '<path>: <snippet>' occurs exactly once",
    "known-risks": "known_risks_used is exactly the set of registered risk ids the classifications use",
    "negative-controls": "every negative control targets a catalogue invariant, a finding check or named checks of a "
                         "scenario of its suite (an audit mutant row names its killing checks)",
    "unsupported": "every unsupported item belongs to a scenario of its suite and is described",
    "harness-limitations": "every harness limitation (HL-1.. in order) is anchored exactly once, names its workaround "
                           "suites and states its effect and status",
    "coverage": "the coverage matrix has the 14 dimensions, cites existing suite files and catalogue scenarios, and lists "
                "the required high-risk intersections, flagged 'required' exactly for REQUIRED_PAIRS",
    "runtime": "every lab suite has a quick runtime within the 90 s budget",
}


def section_cross_checks():
    print("[3] catalogue cross-checks against the corpus, the suite sources and the recorded baseline (static)")
    if not isinstance(CAT, dict) or list(CAT) != TOP_KEYS:
        check("catalogue cross-checks: the catalogue has the schema's top-level keys", False)
        return {}
    n_pinned = len(pinned_sources(CAT))
    if not TREE_DRIFT:
        print(f"  info  recorded baseline: all {n_pinned} catalogue-pinned sources match this tree")
    else:
        rep = T.drift_report(pinned_sources(CAT), DOCS, sha_of=repo_sha, strict=STRICT_BASELINE)
        n = {t: len(rep.of_tier(t)) for t in ("lab", "behavioural", "non-behavioural", "unclassified")}
        gone = sum(1 for i in rep.items if i.now is None)
        print(f"  info  this tree differs from the recorded baseline (tiered drift rule, judged in [5]): {n['lab']} lab "
              f"file(s) (re-generate the catalogue), {n['behavioural']} behavioural file(s) (re-record the corpus "
              f"documents that replay them), {n['non-behavioural']} non-behavioural file(s) (" +
              ("a FAIL in strict mode" if STRICT_BASELINE else "SOURCE DRIFT, not a failure, unless missing") +
              f"), {n['unclassified']} unclassified file(s); {gone} pinned file(s) missing (a FAIL in every tier)")
    probs = catalogue_problems(CAT, DOCS)
    for cat_name in CATEGORIES:
        p = probs[cat_name]
        check(f"catalogue {cat_name}: {LABELS[cat_name]}", not p, "; ".join(p[:4]) + (f" (+{len(p) - 4})" if len(p) > 4
                                                                                      else ""))
    rep = {k: sum(1 for f in CAT["findings"] if f.get("reported_as") == k) for k in REPORTED_AS}
    print(f"  info  catalogue: {len(CAT['scenarios'])} scenarios, {len(CAT['findings'])} finding entries "
          f"({rep['FINDING']} counted, {rep['DUPLICATE']} printed duplicates, {rep['MERGED']} merged variant(s)), "
          f"{len(CAT['root_causes'])} root causes, negative controls: {RL.mutation_text(CAT['negative_controls'])}, "
          f"{len(CAT['unsupported'])} unsupported, {len(CAT['harness_limitations'])} harness limitations, {len(DOCS)} "
          f"corpus documents, {n_pinned} pinned sources")
    return probs


PROBS = section_cross_checks()


# ===========================================================================================================================
# [4] harness negative controls
# ===========================================================================================================================
def section_negative_controls():
    print("[4] harness negative controls: the replay engine and the cross-checker reject what they must")
    doc0, r0 = DOCS.get(NC_DOC), RESULTS.get(NC_DOC)
    now = {p: repo_sha(p) for p in doc0["source_digests"]} if doc0 is not None else {}
    check(f"the negative-control document {NC_DOC} exists, replayed and its pinned sources exist",
          doc0 is not None and r0 is not None and None not in now.values())
    if doc0 is None or r0 is None or None in now.values():
        return
    # The controls run on a copy of the document pinned to THIS tree (its current source digests, this tree's replay
    # digest and only the expectations that hold on this tree's replay), so they test the engine's own rules whether or
    # not the tree is the recorded baseline and whatever the scheduler phase (HL-10: FW-06-a's expectations are
    # timeline-bound since its V0.1 used-key prelude). On the recorded baseline the copy equals the document.
    base = copy.deepcopy(doc0)
    base["source_digests"], base["trace_digest"] = now, r0.digest
    unheld = {f["index"] for f in r0.failed_expectations}
    base["expect"] = [e for i, e in enumerate(base["expect"]) if i not in unheld]
    check(f"the negative-control copy of {NC_DOC} keeps at least one expectation that holds on this tree "
          f"({len(base['expect'])} of {len(doc0['expect'])})", bool(base["expect"]))
    if not base["expect"]:
        return
    # (a) an altered expectation FAILS its replay (exactly that expectation; the digest is unchanged)
    mut = copy.deepcopy(base)
    v = mut["expect"][0]["value"]
    mut["expect"][0]["value"] = (v + " (altered)") if isinstance(v, str) else ["altered", v]
    r, _ = replay_quiet(mut)
    check("NC-RC-1: an altered expectation makes the replay FAIL (only that expectation; digest still equal)",
          not r.ok and [f["index"] for f in r.failed_expectations] == [0] and r.digest == base["trace_digest"],
          f"ok={r.ok} failed={[f['index'] for f in r.failed_expectations]}")
    # (b) an altered action list changes the digest (and the replay FAILS its digest check)
    mut = copy.deepcopy(base)
    last = mut["actions"][-1]["at_s"]
    mut["actions"].append({"at_s": last, "do": "run_for", "args": {"seconds": 15}})
    r1, _ = replay_quiet(mut)
    mut2 = copy.deepcopy(base)
    arg_action = next(a for a in mut2["actions"] if "power_w" in a["args"])
    arg_action["args"]["power_w"] += 100
    r2, _ = replay_quiet(mut2)
    check("NC-RC-2: an altered action list changes the digest (an appended action, a changed argument) and the replay "
          "FAILS its digest check",
          r1.digest != base["trace_digest"] and r1.digest_mismatch and not r1.ok
          and r2.digest != base["trace_digest"] and r2.digest_mismatch and not r2.ok,
          f"{r1.digest[:12]} / {r2.digest[:12]} vs {base['trace_digest'][:12]}")
    # (c) a document with an unknown key is rejected by the schema
    mut = copy.deepcopy(base)
    mut["unknown_extra_key"] = 1
    try:
        T.validate_doc(mut)
        rejected, msg = False, "accepted"
    except T.CorpusSchemaError as exc:   # the expected outcome of this negative control
        rejected, msg = "unknown_extra_key" in str(exc), str(exc)[:160]
    check("NC-RC-3: a document with an unknown key is rejected by validate_doc", rejected, msg)
    # (d) a drifted recorded digest prints SOURCE DRIFT, is judged on expectations only, and is flagged as drift the
    #     catalogue baseline does not explain (and by the static corpus / baseline digest cross-check)
    mut = copy.deepcopy(base)
    path = sorted(mut["source_digests"])[0]
    mut["source_digests"][path] = "0" * 64
    r, printed = replay_quiet(mut)
    static = catalogue_problems(CAT, {**DOCS, NC_DOC: mut})["corpus"] if isinstance(CAT, dict) else []
    check("NC-RC-4: a changed recorded source digest prints SOURCE DRIFT, is judged on its expectations only, is "
          "unexplained drift on the recorded baseline (explained once that source changed in the tree; strict mode: "
          "always flagged) and fails the corpus / baseline digest cross-check",
          f"SOURCE DRIFT: {path}" in printed and r.drift and r.ok
          and unexplained_drift({NC_DOC: r}, [], strict=False) == [NC_DOC]
          and unexplained_drift({NC_DOC: r}, [path], strict=False) == []
          and unexplained_drift({NC_DOC: r}, [path], strict=True) == [NC_DOC]
          and any(p.startswith(f"corpus {NC_DOC} records {path}") for p in static),
          f"drift={r.drift} ok={r.ok} printed={printed[:120]!r} static={static[:1]}")
    # (e) the cross-checker detects broken catalogue entries (each mutant must produce its specific problem)
    if not isinstance(CAT, dict) or list(CAT) != TOP_KEYS:
        check("NC-RC-5..16: the catalogue is loadable for the cross-checker mutants", False)
        return
    clean = PROBS if PROBS else catalogue_problems(CAT, DOCS)

    def mutant(name, edit, category, needle, **kw):
        """The mutated catalogue must produce the specific problem, which the real catalogue does not have."""
        cat = copy.deepcopy(CAT)
        edit(cat)
        got = catalogue_problems(cat, DOCS, **kw)[category]
        check(name, any(needle in p for p in got) and not any(needle in p for p in clean[category]),
              f"{category}: {got[:3]}")

    mutant("NC-RC-5: a catalogue scenario pointing at a missing corpus file is detected",
           lambda c: c["scenarios"][0]["corpus"].append("ZZ-99-zz"), "corpus", "ZZ-99-zz")
    mutant("NC-RC-6: a corpus document owned by two scenarios is detected",
           lambda c: c["scenarios"][1]["corpus"].append(c["scenarios"][0]["corpus"][0]), "corpus",
           "is listed by")
    f0 = next(i for i, f in enumerate(CAT["findings"]) if f["corpus"])
    mutant("NC-RC-7: a finding whose classification differs from its corpus document is detected",
           lambda c: c["findings"][f0].update(classification="FINDING-NEW" if c["findings"][f0]["classification"]
                                              != "FINDING-NEW" else "FINDING-KNOWN:N15"), "corpus", "classification")
    fc = next(i for i, f in enumerate(CAT["findings"]) if f["counted"])
    mutant("NC-RC-8: a flipped counted flag breaks the per-suite LAB-SUMMARY count",
           lambda c: c["findings"][fc].update(counted=False), "counting", "LAB-SUMMARY finding")
    srcs = pinned_sources(CAT)
    lab_path = next((p for p in sorted(srcs) if is_lab(p) and p not in TREE_DRIFT), "")
    mutant("NC-RC-9: a changed lab-file baseline digest asks to re-generate the catalogue",
           lambda c: c["baseline"]["sources"].update({lab_path: "f" * 64}), "baseline",
           f"re-generate the catalogue: {lab_path} sha256")
    # (f) a changed NON-lab baseline digest is SOURCE DRIFT (the spec 2.2 rule), a baseline FAIL only in strict mode
    corpus_pinned = {p for d in DOCS.values() for p in d["source_digests"]}
    ext = next((p for p in sorted(srcs) if not is_lab(p) and p not in corpus_pinned and p not in TREE_DRIFT), "")
    cat = copy.deepcopy(CAT)
    cat["baseline"]["sources"][ext] = "f" * 64
    lax = catalogue_problems(cat, DOCS, strict=False)["baseline"]
    strict = catalogue_problems(cat, DOCS, strict=True)["baseline"]
    check(f"NC-RC-10: a changed non-lab baseline digest ({ext}) is reported as baseline drift and is not a baseline "
          "problem; in strict mode it asks to re-generate the catalogue",
          bool(ext) and ext in baseline_drift(cat) and not any(ext in p for p in lax)
          and any(p.startswith(f"re-generate the catalogue: {ext} sha256") for p in strict),
          f"lax={lax[:2]} strict={strict[:2]}")
    # (g) reported_as and confidence_level are cross-checked
    fm = next((i for i, f in enumerate(CAT["findings"]) if f["reported_as"] == "MERGED"), None)
    if fm is None:
        check("NC-RC-11: the catalogue has a MERGED finding entry to mutate", False)
    else:
        mutant(f"NC-RC-11: a merged variant ({CAT['findings'][fm]['fid']}) relabelled as a printed DUPLICATE is detected "
               "(its suite records the merge)", lambda c: c["findings"][fm].update(reported_as="DUPLICATE"), "sources",
               "reported_as DUPLICATE but")
    fl = next(i for i, f in enumerate(CAT["findings"]) if f["corpus"])
    other = next(lv for lv in T.CONFIDENCES if lv != CAT["findings"][fl]["confidence_level"])
    mutant("NC-RC-12: a confidence_level that contradicts its confidence prose is detected",
           lambda c: c["findings"][fl].update(confidence_level=other), "schema", "confidence_level")
    # (h) a CRLF working copy passes; a lone CR or a non-canonical body does not
    raw_cat = lf_bytes(CATALOGUE.read_bytes())
    raw_doc = lf_bytes((CORPUS_DIR / f"{NC_DOC}.json").read_bytes())
    check("NC-RC-13: a CRLF working copy of the catalogue and of a corpus file passes the LF / canonical checks; a lone CR "
          "in the catalogue and a non-canonical corpus body fail",
          catalogue_bytes_ok(raw_cat.replace(b"\n", b"\r\n")) and canonical_ok(doc0, raw_doc.replace(b"\n", b"\r\n"))
          and not catalogue_bytes_ok(raw_cat.replace(b"\n", b"\r", 1))
          and not canonical_ok(doc0, raw_doc.replace(b'\n  "', b'\n   "', 1)))
    # (i) the 13-digit rule: a planted run outside a digest and a meter word on a digest line are caught; a digest is not
    run = "7" * 13
    digest = "0" * 13 + "ab" * 25 + "c"
    check("NC-RC-14: a 13-digit run outside a sha256 digest and a meter word on a line whose digest holds a 13-digit run "
          "are detected; the same digest on a plain line is accepted",
          bool(digit_run_problems(f'{{"runtime_ms": {run}}}')) and bool(digit_run_problems(f'"meter.json": "{digest}"'))
          and not digit_run_problems(f'"docs/x.md": "{digest}"') and len(digest) == 64)
    # (j) harness limitations and the required-intersection flags are cross-checked
    if CAT.get("harness_limitations"):
        mutant("NC-RC-15: a harness limitation whose anchor no longer occurs in its file is detected",
               lambda c: c["harness_limitations"][0].update(anchor=c["harness_limitations"][0]["anchor"] + " (moved)"),
               "harness-limitations", "anchor found 0 time(s)")
    else:
        check("NC-RC-15: the catalogue has a harness limitation to mutate", False)
    ri = next((i for i, x in enumerate(CAT["coverage_matrix"]["intersections"]) if x.get("required") is True), None)
    if ri is None:
        check("NC-RC-16: the catalogue has a required intersection to mutate", False)
    else:
        mutant("NC-RC-16: a required intersection whose 'required' flag is cleared is detected",
               lambda c: c["coverage_matrix"]["intersections"][ri].update(required=False), "coverage", "required flag")
    # (k) the phase-sensitivity fields and the named-check negative-control targets are cross-checked
    ps = next((i for i, x in enumerate(CAT["scenarios"]) if x.get("phase_sensitive") is True), None)
    if ps is None:
        check("NC-RC-38: the catalogue has a phase-sensitive scenario to mutate", False)
    else:
        mutant("NC-RC-38: a phase-sensitive scenario whose reason is emptied is detected",
               lambda c: c["scenarios"][ps].update(phase_sensitive_reason=""), "schema",
               ": phase_sensitive True is not lab vocabulary")
    nt = next((i for i, n in enumerate(CAT["negative_controls"])
               if str(n.get("target_invariant_or_check", "")).startswith(CHECKS_TARGET)), None)
    if nt is None:
        check("NC-RC-39: the catalogue has a negative control with a named-check target to mutate", False)
    else:
        mutant("NC-RC-39: a negative-control target naming a check of no scenario of its suite is detected",
               lambda c: c["negative_controls"][nt].update(target_invariant_or_check=CHECKS_TARGET + "ZZ-99 planted"),
               "negative-controls", f"target {CHECKS_TARGET}ZZ-99 planted is neither")
    # (l) the distinct-mutation field (B3.6): a row naming a control that itself repeats another (a chain) is detected
    ncs = CAT["negative_controls"]
    if len(ncs) < 3:
        check("NC-RC-49: the catalogue has three negative controls to mutate", False)
    else:
        def chain(c):
            c["negative_controls"][0]["same_mutation_as"] = c["negative_controls"][1]["id"]
            c["negative_controls"][1]["same_mutation_as"] = c["negative_controls"][2]["id"]
        mutant("NC-RC-49: a same_mutation_as naming a control that itself repeats another control (a chain) is detected",
               chain, "schema", f"negative control {ncs[0]['id']}: same_mutation_as {ncs[1]['id']!r} is not another")


section_negative_controls()


# ===========================================================================================================================
# [5] the generator in check mode (static parts)
# ===========================================================================================================================
BUILD_CHECK = ("gen_catalogue (static build): no problem in the suite tables, the corpus, _catalogue_data.py, the B1 tier "
               "table or the corpus pins (public-text rules, anchors exactly once, vocabulary, corpus ownership, root "
               "causes, coverage, harness limitations)")


def generator_results(reader: T.TreeReader | None = None, *, strict: bool = STRICT_BASELINE,
                      committed: dict | None = None) -> dict:
    """The section [5] verdicts over one view of the tree (the REAL path: the plain run calls it with this tree,
    NC-RC-40..45 with an in-memory overlay; nothing is written): gen_catalogue's static build read through `reader`,
    then gen_catalogue.compare() against `committed` (default: the committed SCENARIO_CATALOGUE.json), whose
    baseline-digest verdict is the shared tiered drift rule (_lab_trace.drift_report). Returns {"lines": the SOURCE DRIFT
    (non-behavioural) lines, "checks": [(name, ok, detail), ...], "build", "diffs", "notes"}: one check for the build,
    one per drift-rule failure (else one PASS), one for the rest of the comparison. The drift checks are named
    '<_lab_trace.drift_check(strict)>: <title>' ('gen_catalogue drift rule (tiered)', or '(STRICT)' in strict mode)."""
    if committed is None:
        committed, raw = CAT, lf_bytes(CATALOGUE.read_bytes()).decode("utf-8")
    else:
        raw = GC.dumps(committed)
    b = GC.build(None, committed=committed, reader=reader)
    diffs, notes, drift = GC.compare(raw, b, strict=strict)
    checks = [(BUILD_CHECK, not b.problems,
               "; ".join(b.problems[:4]) + (f" (+{len(b.problems) - 4})" if len(b.problems) > 4 else ""))]
    prefix = T.drift_check(strict)
    fails = drift.failures() if drift is not None else [
        ("the committed catalogue has no baseline.sources to judge", "re-generate the catalogue")]
    if fails:
        checks += [(f"{prefix}: {title}", False, detail) for title, detail in fails]
    elif strict:
        checks.append((f"{prefix}: no pinned source changed or missing in this tree (whole-baseline rule, "
                       "ECCO_LAB_STRICT_BASELINE=1)", True, ""))
    else:
        checks.append((f"{prefix}: no lab or behavioural pinned source changed and no pinned source missing in this "
                       f"tree ({len(drift.drift_lines())} non-behavioural SOURCE DRIFT line(s), not a failure)", True, ""))
    checks.append(("gen_catalogue --check (static parts): the committed catalogue equals a fresh build (runtime values "
                   "excluded; the baseline digests of changed sources are judged by the drift rule above)", not diffs,
                   "re-generate the catalogue: " + "; ".join(diffs[:3])))
    return {"lines": drift.drift_lines() if drift is not None else [], "checks": checks, "build": b, "diffs": diffs,
            "notes": notes}


def comment_overlay(path: str) -> T.TreeReader:
    """This tree with `path` plus one appended comment line, in memory (a TreeReader overlay; nothing is written)."""
    raw = (ROOT / path).read_bytes()
    comment = {".md": b"<!-- assurance lab negative control: one comment line -->\n", ".yaml": b"# assurance lab "
               b"negative control: one comment line\n", ".py": b"# assurance lab negative control: one comment line\n"}
    return T.TreeReader(ROOT, overlay={path: raw + (b"" if raw.endswith(b"\n") else b"\n") + comment[Path(path).suffix]})


DRIFT_NC_NONBEHAVIOURAL = "CHANGELOG.md"
DRIFT_NC_BEHAVIOURAL = ("firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "registry/rtc_policy.py")


def section_generator():
    print("[5] gen_catalogue.py check mode, STATIC parts only (no suite is run here: the other lab suites together would "
          "exceed this suite's 90 s budget), and the tiered drift rule (B1)")
    if not isinstance(CAT, dict) or list(CAT) != TOP_KEYS:
        check("gen_catalogue: the committed catalogue is loadable for the comparison", False)
        return
    try:
        res = generator_results()
    except Exception as exc:     # a generator exception is a FAIL with its message, never a pass
        check("gen_catalogue: the static build runs without an exception", False, f"{type(exc).__name__}: {str(exc)[:200]}")
        return
    b, diffs = res["build"], res["diffs"]
    for s in b.skipped:
        print(f"  info  NOT re-checked here (static mode; 'gen_catalogue.py --check' runs the suites): {s}")
    for n in res["notes"]:
        print(f"  info  {n}")
    for line in res["lines"]:
        print(f"  {line}")
    for name, ok, detail in res["checks"]:
        check(name, ok, detail)
    # controls: a stale entry is a difference; a changed runtime value alone is not (wall-clock, excluded)
    stale = copy.deepcopy(CAT)
    stale["scenarios"][0]["title"] += " (stale)"
    d_stale, _n, _d = GC.compare(GC.dumps(stale), b)
    rt = copy.deepcopy(CAT)
    k0 = next(iter(rt["runtime_quick_s"]))
    rt["runtime_quick_s"][k0] = round(rt["runtime_quick_s"][k0] + 1.0, 1)
    d_rt, n_rt, _d = GC.compare(GC.dumps(rt), b)
    check("NC-RC-17: a committed catalogue with a stale scenario entry is reported out of date by the generator's check; "
          "a changed runtime value alone adds no difference (it is reported as a note)",
          any(d.startswith("scenarios:") and CAT["scenarios"][0]["id"] in d for d in d_stale)
          and d_rt == diffs and any(k0 in n and "not compared" in n for n in n_rt),
          f"stale={d_stale[:2]} runtime={d_rt[:2]} notes={n_rt[:1]}")
    drift_controls(res)


def expand_ids(text: str) -> list[str]:
    """The corpus ids of a compact list 'FW-01-a,b; HF-02-c' (written here, independently of _lab_trace.compact_ids, so
    the drift controls check the printed list against the corpus itself)."""
    out = []
    for grp in text.split("; "):
        head, sep, tails = grp.rpartition("-")
        out += [f"{head}-{t}" for t in tails.split(",")] if sep else [grp]
    return sorted(out)


REPLAYED_BY_RE = re.compile(r"(\d+) corpus document\(s\) replay it \(([^)]*)\)")
DRIFT_NC_LAB = f"{LAB_REL}/run_lab.py"           # NC-RC-43: a lab file no corpus document pins
DRIFT_NC_UNCLASSIFIED = "SAFETY.md"             # NC-RC-45: taken out of the tier table for the control (restored)


def drift_controls(plain: dict) -> None:
    """NC-RC-40..45 (B1 end-to-end negative controls, catalogued in NEGATIVE_CONTROLS): generator_results(), the real
    section [5] path, over this tree plus one edit (an in-memory overlay; nothing is written). The reference catalogue is
    the plain static build of THIS tree (the catalogue a regeneration would write; equal to the committed file on a
    regenerated tree), and each outcome is taken RELATIVE to the same path over the unedited tree (the reference run),
    so the controls depend neither on the committed file being current nor on this tree being clean: a non-behavioural
    edit adds exactly its SOURCE DRIFT line and no failure (and exactly one failure in strict mode); a behavioural edit
    adds exactly one failure, the named drift-rule check for that file, whose detail names every corpus document that
    replays it (expected list computed here from the corpus JSON and TIER_SOURCES), their count and the re-record target;
    a lab-file edit adds exactly one 're-generate the catalogue' failure; a document copy with one tier pin removed is
    named by the build and by the [2] short-list; an edit to a pinned file the tier table does not classify adds exactly
    one 'unclassified pinned source changed' failure."""
    fresh = plain["build"].cat                  # this tree's catalogue (static build: the committed runtimes)

    def outcome(res):
        return {n: d for n, ok, d in res["checks"] if not ok}, res["lines"]

    def added(reader, strict: bool):
        fails, lines = outcome(generator_results(reader, strict=strict, committed=fresh))
        ref_fails, ref_lines = ref[strict]
        return {n: d for n, d in fails.items() if n not in ref_fails}, [ln for ln in lines if ln not in ref_lines]

    nb = DRIFT_NC_NONBEHAVIOURAL
    anchored = sum(1 for x in CAT["scenarios"] for a in x["anchors"] if a.startswith(nb + ": "))
    strict_name = f"{T.DRIFT_CHECK_STRICT}: non-behavioural source changed (STRICT, ECCO_LAB_STRICT_BASELINE=1): {nb}"
    try:
        ref_res = {s: generator_results(strict=s, committed=fresh) for s in (False, True)}
        ref = {s: outcome(r) for s, r in ref_res.items()}
        fails, lines = added(comment_overlay(nb), False)
        s_fails, s_lines = added(comment_overlay(nb), True)
    except Exception as exc:     # a harness exception is the control's FAIL, never a pass
        check(f"NC-RC-40 ({nb} plus one comment line): no harness exception", False, f"{type(exc).__name__}: {exc}")
        return
    check(f"NC-RC-40 (non-behavioural edit: {nb} plus one comment line, in memory): {T.DRIFT_CHECK} survives as "
          f"expected - it adds exactly its '{T.DRIFT_LINE}{nb}' line and no failure, its {anchored} catalogue anchor(s) "
          f"still exactly once; in strict mode the same edit adds exactly one FAIL ('{T.DRIFT_CHECK_STRICT}: ...')",
          T.source_tier(nb) == "non-behavioural" and anchored > 0 and not fails and lines == [T.DRIFT_LINE + nb]
          and list(s_fails) == [strict_name] and not s_lines,
          f"added failures {sorted(fails)[:2]}; added lines {lines[:3]}; strict {sorted(s_fails)[:3]} {s_lines[:2]}")
    for nid, path in zip(("NC-RC-41", "NC-RC-42"), DRIFT_NC_BEHAVIOURAL):
        # the documents that replay `path`, from the corpus JSON and the tier table's data (not T.affected_documents)
        expected = sorted(stem for stem, d in DOCS.items()
                          if path in d["source_digests"] or path in T.TIER_SOURCES.get(d["tier"], ()))
        target = "--all" if len(expected) == len(DOCS) or len(expected) > 12 else " ".join(expected)
        want = f"{T.DRIFT_CHECK}: behavioural source changed: {path}"
        try:
            fails, lines = added(comment_overlay(path), False)
        except Exception as exc:     # a harness exception is the control's FAIL, never a pass
            check(f"{nid} ({path} plus one comment line): no harness exception", False, f"{type(exc).__name__}: {exc}")
            continue
        detail = fails.get(want, "")
        m = REPLAYED_BY_RE.search(detail)
        listed = expand_ids(m.group(2)) if m else []
        check(f"{nid} (behavioural edit: {path} plus one comment line, in memory): killed - {T.DRIFT_CHECK} fails with "
              f"exactly the one added check naming the file, all {len(expected)} corpus documents that replay it (every "
              f"tier's TIER_SOURCES holds it: the list and count are checked against the corpus) and the re-record "
              f"procedure ('{target}')",
              T.source_tier(path) == "behavioural" and len(expected) == len(DOCS) and list(fails) == [want]
              and not lines and m is not None and int(m.group(1)) == len(expected) and listed == expected
              and f"{T.RERECORD_CMD} {target} (" in detail and T.REGENERATE_CMD in detail,
              f"added failures {sorted(fails)}; added lines {lines}; listed {len(listed)} of {len(expected)}; "
              f"detail {detail[:200]!r}")
    # NC-RC-43: the lab-file branch of the shared rule (a lab file no corpus document pins)
    lab = DRIFT_NC_LAB
    want = f"{T.DRIFT_CHECK}: re-generate the catalogue: lab file changed: {lab}"
    pinned_by = sorted(s for s, d in DOCS.items() if lab in d["source_digests"])
    try:
        fails, lines = added(comment_overlay(lab), False)
    except Exception as exc:     # a harness exception is the control's FAIL, never a pass
        fails, lines = {"harness exception": f"{type(exc).__name__}: {exc}"}, []
    check(f"NC-RC-43 (lab-file edit: {lab} plus one comment line, in memory; no corpus document pins it): killed - "
          f"{T.DRIFT_CHECK} fails with exactly the one added check 're-generate the catalogue: lab file changed' naming "
          "it and the regeneration command",
          T.source_tier(lab) == "lab" and not pinned_by and list(fails) == [want] and not lines
          and T.REGENERATE_CMD in fails.get(want, ""), f"added failures {sorted(fails)}; added lines {lines}; "
          f"pinned by {pinned_by}")
    # NC-RC-44: per-document tier-pin completeness (the build and the [2] short-list name a document lacking a tier pin)
    doc0 = DOCS.get(NC_DOC)
    anchor_paths = {a["path"] for a in doc0["source_anchors"]} if doc0 else set()
    drop = next((p for p in T.tier_pins(doc0["tier"]) if p in doc0["source_digests"] and p not in anchor_paths),
                None) if doc0 else None
    rel = f"{LAB_REL}/corpus/{NC_DOC}.json"
    need = f"corpus {NC_DOC}: does not pin 1 of its tier's TIER_SOURCES in its own source_digests ({drop})"
    try:
        mut = copy.deepcopy(doc0)
        del mut["source_digests"][drop]
        res = generator_results(T.TreeReader(ROOT, overlay={rel: T.dumps_doc(mut).encode("ascii")}), strict=False,
                                committed=fresh)
        named = [p for p in res["build"].problems if p.startswith(need)]
        ref_named = [p for p in ref_res[False]["build"].problems if p.startswith(need)]
        fails = outcome(res)[0]          # the build check fails over the overlay (it may fail on the reference too)
        short, short0 = tier_pin_shortfalls({**DOCS, NC_DOC: mut}), tier_pin_shortfalls(DOCS)
        err = ""
    except Exception as exc:     # a harness exception is the control's FAIL, never a pass
        named, ref_named, fails, short, short0, err = [], [], {}, [], [], f"{type(exc).__name__}: {exc}"
    check(f"NC-RC-44 (a copy of {NC_DOC} with its tier pin of {drop} removed, in memory): killed - gen_catalogue's "
          f"build names it ('does not pin 1 of its tier's TIER_SOURCES') and the '{T.TIER_PIN_CHECK}' short-list of [2] "
          "names it",
          not err and drop is not None and len(named) == 1 and not ref_named and BUILD_CHECK in fails
          and NC_DOC in short and NC_DOC not in short0 and sorted(set(short) - set(short0)) == [NC_DOC],
          f"{err} named {named[:1]}; failures {sorted(fails)[:3]}; short-list {short[:4]} (clean {short0[:4]})")
    # NC-RC-45: the unclassified branch (a pinned file in neither tier is judged behavioural: a named failure)
    un = DRIFT_NC_UNCLASSIFIED
    want = f"{T.DRIFT_CHECK}: unclassified pinned source changed: {un}"
    saved = dict(T.NON_BEHAVIOURAL)
    try:
        del T.NON_BEHAVIOURAL[un]
        tier_u = T.source_tier(un)
        fresh_u = GC.build(None, committed=CAT).cat          # this tree's catalogue under the reduced table
        ref_u = outcome(generator_results(strict=False, committed=fresh_u))
        fails_u, lines_u = outcome(generator_results(comment_overlay(un), strict=False, committed=fresh_u))
        err = ""
    except Exception as exc:     # a harness exception is the control's FAIL, never a pass
        tier_u, ref_u, fails_u, lines_u, err = "", ({}, []), {}, [], f"{type(exc).__name__}: {exc}"
    finally:
        T.NON_BEHAVIOURAL.clear()
        T.NON_BEHAVIOURAL.update(saved)
    add = {n: d for n, d in fails_u.items() if n not in ref_u[0]}
    add_lines = [ln for ln in lines_u if ln not in ref_u[1]]
    check(f"NC-RC-45 (unclassified edit: {un} taken out of the tier table for this control, plus one comment line, in "
          f"memory): killed - {T.DRIFT_CHECK} fails with exactly the one added check 'unclassified pinned source "
          "changed' (judged behavioural until classified), no SOURCE DRIFT line; the table is restored",
          not err and tier_u == "unclassified" and T.source_tier(un) == "non-behavioural" and list(add) == [want]
          and not add_lines and "judged behavioural until then" in add.get(want, ""),
          f"{err} added failures {sorted(add)}; added lines {add_lines}")


section_generator()


# ===========================================================================================================================
# [6] runner negative self-tests: the V0.1 output contract cross-checks detect planted inconsistencies
# ===========================================================================================================================
SYN = "test_lab_synthetic"           # a suite name that exists nowhere (the judges only compare it with the LAB-SUMMARY)


def synthetic_output(*, passes=("held a", "held b"), pins=("finding-reproduces:F-SY01-1 (synthetic)",), fails=(),
                     unsupported=(("SY-01-U1", "point 1"), ("SY-01-U1", "point 2"), ("SY-01-U2", "point 3")),
                     mode="quick", suite=SYN, runtime_s=1.0) -> str:
    """A suite output written exactly as a V0.1 suite writes it (check lines, _lab_trace.unsupported_line, finish())."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"  info  mode: {mode}")
        for p in passes:
            print(f"  PASS  {p}")
        for p in pins:
            print(f"  PASS  {p}")
        for f in fails:
            print(f"  FAIL  {f} - planted detail")
        for uid, text in unsupported:
            print(T.unsupported_line(uid, text))
        print("")
        T.finish(suite, passes=list(passes), failures=list(fails), finding=[], finding_pins=list(pins),
                 unsupported_points=[u for u, _ in unsupported], blocked=[], phase_sensitive=[], runtime_s=runtime_s)
    return buf.getvalue()


def plant_before_summary(text: str, line: str) -> str:
    """`line` inserted just before the final FAILED / LAB-SUMMARY lines (where a suite's last check would print)."""
    lines = text.splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith(("FAILED:", "LAB-SUMMARY ")))
    return "\n".join(lines[:k] + [line] + lines[k:]) + "\n"


def edit_summary(text: str, **changes) -> str:
    """The LAB-SUMMARY line re-written with `changes` (a hand-edited or literal count), everything else untouched."""
    out = []
    for ln in text.splitlines():
        if ln.startswith("LAB-SUMMARY "):
            rec = json.loads(ln[len("LAB-SUMMARY "):])
            rec.update(changes)
            ln = "LAB-SUMMARY " + json.dumps(rec)
        out.append(ln)
    return "\n".join(out) + "\n"


def judged(text: str, rc=0, extended=False, stem=SYN) -> dict:
    return RL.judge({"stem": stem, "rel": f"{LAB_REL}/{stem}.py", "rc": rc, "wall_s": 1.0, "text": text}, extended, 1800, 1)


def has_reason(res: dict, needle: str) -> bool:
    return not res["ok"] and any(needle in r for r in res["reasons"])


def section_runner_controls():
    print("[6] runner negative self-tests: run_lab.judge / gen_catalogue.suite_output against planted suite outputs")
    check("NC-RC-18: run_lab.SUMMARY_KEYS and PIN_PREFIX equal _lab_trace's (the LAB-SUMMARY writer and its judges agree)",
          RL.SUMMARY_KEYS == T.SUMMARY_KEYS and RL.PIN_PREFIX == T.PIN_PREFIX
          and set(RL.COUNT_KEYS) == set(T.SUMMARY_KEYS) - {"suite", "zoneinfo", "runtime_s"},
          f"{RL.SUMMARY_KEYS} vs {T.SUMMARY_KEYS}")
    clean = synthetic_output()
    r_lf, r_crlf = judged(clean), judged(clean.replace("\n", "\r\n"))
    rec = r_lf["summary"] or {}
    check("NC-RC-19 (control): a clean synthetic V0.1 output is accepted (LF and CRLF) with the detected counts "
          "(pass 2, finding_pins 1, unsupported_ids 2, unsupported_points 3) and its UNSUPPORTED ids",
          r_lf["ok"] and r_crlf["ok"] and rec.get("pass") == 2 and rec.get("finding_pins") == 1
          and rec.get("unsupported_ids") == 2 and rec.get("unsupported_points") == 3
          and r_lf["printed_unsupported"] == ["SY-01-U1", "SY-01-U2"],
          f"{r_lf['reasons']} / {r_crlf['reasons']} / {rec}")
    plants = [
        ("NC-RC-20: an extra PASS line (pass no longer equals the PASS lines minus the pins) is rejected",
         judged(plant_before_summary(clean, "  PASS  planted extra check")), "LAB-SUMMARY pass 2 != 3"),
        ("NC-RC-21: an extra finding-pin PASS line is rejected (finding_pins != the pin lines)",
         judged(plant_before_summary(clean, "  PASS  finding-reproduces:F-SY01-9 planted")), "LAB-SUMMARY finding_pins"),
        ("NC-RC-22: a FAIL line at exit code 0 fails the suite (any FAIL line fails it, whatever rc and LAB-SUMMARY say)",
         judged(plant_before_summary(clean, "  FAIL  planted failing check - detail"), rc=0),
         "1 FAIL line printed with exit code 0"),
        ("NC-RC-23: a consistent failing output (FAIL line, FAILED line, LAB-SUMMARY fail 1) at exit code 0 is rejected",
         judged(synthetic_output(fails=("planted failing check",)), rc=0), "1 FAIL line printed with exit code 0"),
        ("NC-RC-24: a hard-coded unsupported count (unsupported_points 3 printed as 5) is rejected",
         judged(edit_summary(clean, unsupported_points=5)), "LAB-SUMMARY unsupported_points 5 != 3"),
        ("NC-RC-25: UNSUPPORTED lines removed while LAB-SUMMARY keeps its count (the ha_phantom literal) are rejected",
         judged("\n".join(ln for ln in clean.splitlines() if not ln.startswith("  UNSUPPORTED  ")) + "\n"),
         "printed UNSUPPORTED lines"),
        ("NC-RC-26: unsupported_ids that count points instead of distinct ids are rejected",
         judged(edit_summary(clean, unsupported_ids=3)), "LAB-SUMMARY unsupported_ids 3 != 2"),
        ("NC-RC-27: a failing suite without its FAILED line before LAB-SUMMARY is rejected",
         judged("\n".join(ln for ln in synthetic_output(fails=("x",)).splitlines() if not ln.startswith("FAILED:"))
                + "\n", rc=1), "'FAILED: <n> check(s): <names>' line"),
        ("NC-RC-28: the V0 order (FAILED line after LAB-SUMMARY) is rejected",
         judged("\n".join([ln for ln in synthetic_output(fails=("x",)).splitlines() if not ln.startswith("FAILED:")]
                          + ["FAILED: 1 check(s): x"]) + "\n", rc=1), "output continues after the LAB-SUMMARY line"),
        ("NC-RC-29: a FAILED line in a suite whose checks all held is rejected",
         judged(plant_before_summary(clean, "FAILED: 1 check(s): x")), "a FAILED line is printed although"),
        ("NC-RC-30: a V0 LAB-SUMMARY (old keys) is a garbled summary",
         judged("\n".join([ln for ln in clean.splitlines() if not ln.startswith("LAB-SUMMARY")]
                          + ["LAB-SUMMARY " + json.dumps({"suite": SYN, "pass": 2, "fail": 0, "finding": 0,
                                                          "unsupported": 2, "blocked": 0, "runtime_s": 1.0})]) + "\n"),
         "the LAB-SUMMARY keys differ"),
        ("NC-RC-31: a non-bool zoneinfo value is a garbled summary",
         judged(edit_summary(clean, zoneinfo=1)), "zoneinfo value is not true / false"),
        ("NC-RC-32: unsupported_ids above unsupported_points is an impossible summary",
         judged(edit_summary(clean, unsupported_ids=4)), "pair is impossible"),
    ]
    for name, res, needle in plants:
        check(name, has_reason(res, needle), f"ok={res['ok']} reasons={res['reasons'][:4]}")
    # the generator applies the same contract to the outputs it builds the catalogue from
    seq = {"rc": 0, "parallel": 1}
    gen = {
        "clean": GC.suite_output(SYN, {"text": clean, **seq}, True),
        "extra": GC.suite_output(SYN, {"text": plant_before_summary(clean, "  PASS  planted"), **seq}, True),
        "fail0": GC.suite_output(SYN, {"text": plant_before_summary(clean, "  FAIL  planted"), **seq}, True),
        "uns": GC.suite_output(SYN, {"text": edit_summary(clean, unsupported_points=5), **seq}, True),
        "replay_fail": GC.suite_output(GC.REPLAY_SUITE, {"text": synthetic_output(fails=("x",), suite=GC.REPLAY_SUITE),
                                                         "rc": 1, "parallel": 1}, True),
        "replay_extra": GC.suite_output(GC.REPLAY_SUITE, {"text": plant_before_summary(
            synthetic_output(suite=GC.REPLAY_SUITE), "  PASS  planted"), **seq}, True),
    }
    check("NC-RC-33: gen_catalogue.suite_output accepts the clean output and rejects an extra PASS line, a FAIL line at "
          "rc 0 and a hard-coded unsupported count; for the replay suite its own failure is not judged but its counts are",
          gen["clean"][0] is not None and not gen["clean"][1]
          and any("LAB-SUMMARY pass" in p for p in gen["extra"][1])
          and any("FAIL line(s) printed" in p for p in gen["fail0"][1])
          and any("unsupported_points 5" in p for p in gen["uns"][1])
          and gen["replay_fail"][0] is not None and not gen["replay_fail"][1]
          and any("LAB-SUMMARY pass" in p for p in gen["replay_extra"][1]),
          str({k: v[1][:2] for k, v in gen.items()}))
    slow = synthetic_output(runtime_s=96.7)
    s_seq = GC.suite_output(SYN, {"text": slow, **seq}, True)
    s_par = GC.suite_output(SYN, {"text": slow, "rc": 0, "parallel": 4}, False)
    check("NC-RC-34: a 96.7 s quick runtime is a problem for sequential outputs and only a warning otherwise (B7.1)",
          any("quick runtime 96.7 s" in p for p in s_seq[1]) and not s_par[1]
          and any("quick runtime 96.7 s" in w for w in s_par[2]), f"seq={s_seq[1:]} par={s_par[1:]}")
    # catalogued UNSUPPORTED ids in the mode they belong to
    entries = [{"id": "SY-01-U1", "suite": SYN, "description": "met in quick mode"},
               {"id": "SY-01-U2", "suite": SYN, "description": "met in quick mode too"},
               {"id": "SY-01-UEXT", "suite": SYN, "description": "extended mode only: deeper sweep points"}]
    up = RL.unsupported_id_problems
    check("NC-RC-35: unsupported_id_problems: quick ids are required in a quick run, an extended-only id is required in "
          "an extended run and refused in a quick run, an id the catalogue does not list for the suite is refused",
          up(SYN, ["SY-01-U1", "SY-01-U2"], entries, False) == []
          and up(SYN, ["SY-01-U1", "SY-01-U2", "SY-01-UEXT"], entries, True) == []
          and any("not printed" in p and "SY-01-U2" in p for p in up(SYN, ["SY-01-U1"], entries, False))
          and any("extended-only" in p for p in up(SYN, ["SY-01-U1", "SY-01-U2", "SY-01-UEXT"], entries, False))
          and any("not printed" in p and "SY-01-UEXT" in p for p in up(SYN, ["SY-01-U1", "SY-01-U2"], entries, True))
          and any("does not list" in p for p in up(SYN, ["SY-01-U1", "SY-01-U2", "SY-01-U9"], entries, False)))
    cat = {"runtime_quick_s": {SYN: 1.0}, "findings": [], "scenarios": [], "unsupported": entries}
    probs = RL.cross_check(cat, [judged(clean)], True, [SYN], extended=False)
    probs_ext = RL.cross_check(cat, [judged(synthetic_output(mode="EXTENDED"), extended=True)], True, [SYN],
                               extended=True)
    check("NC-RC-36: run_lab.cross_check applies the mode rule to a judged run (quick: ok; extended without the "
          "extended-only id: flagged)", probs == [] and any("SY-01-UEXT" in p for p in probs_ext), f"{probs} / {probs_ext}")
    modes = {u.get("id"): RL.unsupported_mode(u) for u in CAT.get("unsupported", []) if isinstance(u, dict)} \
        if isinstance(CAT, dict) else {}
    ext_ids = sorted(str(i) for i, m in modes.items() if m == "extended")
    print(f"  info  catalogued UNSUPPORTED ids: {len(modes)}; extended-only (description 'extended mode only'): "
          f"{', '.join(ext_ids) or 'none'}")
    # the shared drift rule: a missing pinned file fails in every tier (run_lab.baseline_status uses this function)
    gone = {p: "0" * 64 for p in (DRIFT_NC_LAB, DRIFT_NC_BEHAVIOURAL[1], DRIFT_NC_NONBEHAVIOURAL,
                                  "docs/zz-assurance-lab-unclassified-control.md")}
    reps = {s: T.drift_report(gone, DOCS, sha_of=lambda _p: None, strict=s) for s in (False, True)}
    want_missing = {DRIFT_NC_LAB: f"re-generate the catalogue: lab file changed: {DRIFT_NC_LAB}",
                    DRIFT_NC_BEHAVIOURAL[1]: f"behavioural source changed: {DRIFT_NC_BEHAVIOURAL[1]}",
                    DRIFT_NC_NONBEHAVIOURAL: f"pinned source missing: {DRIFT_NC_NONBEHAVIOURAL}",
                    "docs/zz-assurance-lab-unclassified-control.md": "unclassified pinned source changed: "
                                                                     "docs/zz-assurance-lab-unclassified-control.md"}
    want_titles = [want_missing[p] for p in sorted(gone)]
    # the same deletion through the generator's static build and compare() (the real section [5] path, an in-memory
    # overlay; relative to the same path over this tree, so a drifted tree does not matter)
    drift_fail = f"{T.drift_check(False)}: pinned source missing: {DRIFT_NC_NONBEHAVIOURAL}"
    try:
        ref_names = {n for n, ok, _d in generator_results(strict=False)["checks"] if not ok}
        res_gone = generator_results(T.TreeReader(ROOT, overlay={DRIFT_NC_NONBEHAVIOURAL: None}), strict=False)
        gone_added = sorted(n for n, ok, _d in res_gone["checks"] if not ok and n not in ref_names)
        gone_pass = [n for n, ok, _d in res_gone["checks"] if ok and n.startswith(T.drift_check(False))]
    except Exception as exc:     # a harness exception is the control's FAIL, never a pass
        gone_added, gone_pass = [f"harness exception {type(exc).__name__}: {exc}"], []
    check("NC-RC-46: a missing pinned file is a failure of the shared drift rule in every tier, one per file with the "
          "detail 'sha256 missing' (lab, behavioural and unclassified under their tier's title, non-behavioural as "
          "'pinned source missing'; strict mode alike; the non-behavioural one also prints its '(file missing)' SOURCE "
          "DRIFT line), so run_lab's baseline check fails a tree with a pinned file deleted, as the generator does; and "
          "the generator's compare() path (section [5]) names the deleted non-behavioural file as that failure, with no "
          "drift-rule PASS: killed",
          sorted(T.source_tier(p) for p in gone) == ["behavioural", "lab", "non-behavioural", "unclassified"]
          and all([t for t, _d in r.failures()] == want_titles
                  and all(d.startswith("sha256 missing != recorded") for _t, d in r.failures()) for r in reps.values())
          and reps[False].drift_lines() == [f"{T.DRIFT_LINE}{DRIFT_NC_NONBEHAVIOURAL} (file missing)"]
          and reps[True].drift_lines() == [] and drift_fail in gone_added and not gone_pass,
          str({s: [t for t, _d in r.failures()] for s, r in reps.items()}) + f"; compare path added {gone_added[:4]}, "
          f"drift PASS {gone_pass[:1]}")
    # gen_catalogue: suite outputs must carry the digests of the tree they ran on (--runs-from / --write)
    rec = {"docs/x-control.md": "1" * 64, "registry/y_control.py": "2" * 64}
    now = dict(rec)
    tr = GC.tree_record_problems
    p_none, p_same = tr(None, now, now.get), tr(dict(rec), now, now.get)
    p_diff = tr({**rec, "registry/y_control.py": "3" * 64}, now, now.get)
    p_gone = tr({**rec, "docs/z-control.md": "4" * 64}, now, now.get)
    check("NC-RC-47: gen_catalogue.tree_record_problems refuses suite outputs that carry no record of the tree they ran "
          "on and outputs whose recorded digest of a pinned source differs from the tree (changed, or no longer there), "
          "and accepts a matching record: killed",
          any("no record of the tree" in p for p in p_none) and p_same == []
          and any("registry/y_control.py" in p and "another tree" in p for p in p_diff)
          and any("docs/z-control.md" in p for p in p_gone), f"{p_none} / {p_same} / {p_diff} / {p_gone}")
    # the run-time import guard at the end of every suite (_lab_trace.finish): a module planted in sys.modules whose file
    # is a repository path outside the lab and outside BEHAVIOURAL (nothing is imported or written; removed afterwards)
    planted = "assurance_lab_import_guard_control"
    fake = type(sys)(planted)
    fake.__file__ = str(ROOT / "registry" / "zz_import_guard_control.py")
    fails_g: list[str] = []
    buf = io.StringIO()
    rec_g, tuple_refused = {}, False
    try:
        sys.modules[planted] = fake
        with contextlib.redirect_stdout(buf):
            rec_g = T.finish(SYN, passes=["held a"], failures=fails_g, finding=[], finding_pins=[], unsupported_points=[],
                             blocked=[], phase_sensitive=[], runtime_s=1.0)
            try:
                T.finish(SYN, passes=[], failures=(), finding=[], finding_pins=[], unsupported_points=[], blocked=[],
                         phase_sensitive=[], runtime_s=1.0)
            except T.LabTraceError:      # the expected outcome: a guard failure needs the suite's FAILURES list
                tuple_refused = True
    finally:
        del sys.modules[planted]
    out_g = buf.getvalue().splitlines()
    clean_g = T.import_guard_failure()
    check("NC-RC-48: _lab_trace.finish runs the import guard at the end of a suite: with a repository module outside the "
          "lab and outside BEHAVIOURAL in sys.modules it prints one '  FAIL  B1 import guard (end of suite): ...' line "
          "naming it, appends that check to the suite's FAILURES list (so the exit gate fails) and counts it in the "
          "FAILED line and LAB-SUMMARY fail; a tuple instead of the FAILURES list is refused; nothing once removed: killed",
          fails_g == [T.IMPORT_GUARD_CHECK] and rec_g.get("fail") == 1 and tuple_refused and clean_g is None
          and sum(1 for ln in out_g if ln.startswith(f"  FAIL  {T.IMPORT_GUARD_CHECK} - ")
                  and "registry/zz_import_guard_control.py" in ln) == 1
          and any(ln.startswith("FAILED: 1 check(s): B1 import guard") for ln in out_g),
          f"failures {fails_g}; record {rec_g}; tuple refused {tuple_refused}; after {clean_g}; output {out_g[:3]}")
    # rerecord_corpus: the stale report is clean for a document pinned to this tree and flags a stale digest
    doc0, r0 = DOCS.get(NC_DOC), RESULTS.get(NC_DOC)
    if doc0 is None or r0 is None:
        check(f"NC-RC-37: the negative-control document {NC_DOC} is available for the re-record tool control", False)
        return
    base = copy.deepcopy(doc0)
    base["source_digests"] = {p: repo_sha(p) for p in base["source_digests"]}
    stale = copy.deepcopy(base)
    path = sorted(stale["source_digests"])[0]
    stale["source_digests"][path] = "0" * 64
    check("NC-RC-37: rerecord_corpus.stale_report is clean for a document pinned to this tree and lists a stale pinned "
          "digest", RR.stale_report(base)[0] == [] and RR.stale_report(stale)[0] == [path],
          f"{RR.stale_report(base)} / {RR.stale_report(stale)}")


section_runner_controls()

RUNTIME_S = time.perf_counter() - T0
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=PINS, unsupported_points=UNSUPPORTED_POINTS,
         blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
