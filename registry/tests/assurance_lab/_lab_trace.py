"""Assurance lab V0: event log, deterministic digest, known-risk registry, classification vocabulary, replay DSL engine and the
ddmin shrinker (test-only helper: no network, no Home Assistant, no hardware; it reads repository files and writes nothing).

PUBLIC API
  ROOT                                   the worktree root (this file is registry/tests/assurance_lab/_lab_trace.py)
  errors   LabTraceError (base) > CorpusSchemaError (bad corpus document), ReplayDispatchError (unknown tier / action /
           observer, clock misuse, impure observer), AnchorError (anchor text not found exactly once)
  vocab    CLASSIFICATIONS = PASS, FAIL, FINDING-NEW, FINDING-KNOWN, UNSUPPORTED, BLOCKED (FINDING-KNOWN is always written
           'FINDING-KNOWN:<risk-id>' with a KNOWN_RISKS id); GRADES = VERIFIED, REPORTED, INFERRED, UNKNOWN;
           CONFIDENCES = high, medium, low; PRIORITIES = P1, P2, P3; TIERS = firmware, coupled, rtc; SOURCES = fw, ha, lab;
           RISK_CLASSES; OPS = ==, !=, startswith, contains, not_contains, <=, >=; SCHEMA = 'ecco-assurance-lab-replay/v0'
  classify(kind, risk_id=None) -> str     builds and validates a classification ('FINDING-KNOWN' needs a KNOWN_RISKS id)
  parse_classification(text) -> (kind, risk_id | None)       raises LabTraceError for anything outside the vocabulary
  canonical(value) -> JSON-able copy      dict keys must be str; tuple -> list; float rounded to 3 dp (-0.0 -> 0.0); NaN / inf,
                                          sets, bytes and other objects raise LabTraceError; str / int / float subclasses -> base
  canonical_json(value) -> str            sorted keys, separators (',', ':'), ASCII only
  digest_of(value) -> str                 sha256 hex of canonical_json(value)
  class EventLog                          append-only; events are stored as canonical JSON lines, so nothing a caller does to a
                                          returned dict can change the log
      append(*, t_utc, up_ms, boot, src, kind, data=None) -> dict (a copy of the stored event)
          event = {seq (0, 1, ...), t_utc (int or float epoch s), up_ms, boot, src ('fw'|'ha'|'lab'), kind, data ({} if None)}
          up_ms / boot: int >= 0, required for src 'fw'; None allowed for 'ha' and 'lab'
      len(log), iter(log), log[i] (copies); events(kind=None, src=None, boot=None) -> list; last(kind=None, src=None)
      canonical() -> str (== canonical_json(list(log))); digest() -> sha256 hex of canonical()
      utc_regressions() -> [seq, ...] of events whose t_utc is earlier than the previous event's
  KNOWN_RISKS: dict[id, {title, path, text, line_at_record, doc_anchor ('path:line'), class}]
      ids: SG-25, N10, N15, N16, N17, PR41-GHOST, NVS-PARTITION-ERASE, PLATFORM-ABSENT, FCP2-R1, FCP2-C1, FCP2-F2,
           FCP2-F3, FCP2-F6, FCP2-F7, FCP2-F8, SMR1-OWNER-STAGING, SMR1-OWNER-RESTORING, SMR1-UNCLEAN-SHUTDOWN,
           SMR1-STALE-24H
      `text` occurs exactly once in `path` (verified by test_lab_selftest_core); `line_at_record` is information only.
      N16 / N17 are ACCEPTED-RESIDUAL (their S4 rows say 'Accepted residual'); PR41-GHOST (DOCUMENTED-LIMIT) and
      NVS-PARTITION-ERASE (PLATFORM-LIMIT) anchor the S4 section 2.10 blind spots 1 and 3.
  KNOWN_RISK_REFS: dict[id, ((path, text), ...)]   secondary public references of a risk (each text occurs exactly once;
      verified by test_lab_selftest_core); PR41-GHOST names the firmware's on_boot dual-obligation arbitration comment.
  known_risk(risk_id) -> dict (copy); known_risk_status(root=ROOT) -> {id: {count, line, line_at_record}}
  read_source_text(path, root=ROOT) -> str (UTF-8, CRLF -> LF); source_digest(path, root=ROOT) -> sha256 hex of the
      LF-normalised bytes (a CRLF checkout of the same commit digests equal); anchor_count(path, text, root) -> (count, line);
      anchor_line(path, text, root) -> line (AnchorError unless the text occurs exactly once)
  eval_expectation(op, observed, value) -> (ok, detail)
      '==' / '!=' compare canonical JSON (so True != 1 and 1 != 1.0); 'startswith' needs two str; 'contains' /
      'not_contains': substring of a str, element of a list (canonical equality) or key of a dict; '<=' / '>=' need two
      numbers (bool is not a number). A type mismatch is a FAILED expectation (never a pass); an unknown op raises.
  register_tier(tier, factory)            factory(*, utc_start: int epoch s, seed: int, **world_kwargs) -> world
  register_actions(tier, {name: fn(world, **args)}) / register_observers(tier, {name: fn(world, **args) -> JSON-able})
      re-registering the same function is a no-op; a different function under a taken name raises ReplayDispatchError
  unregister_tier(tier); registered(tier) -> {"factory": bool, "actions": [...], "observers": [...]}
  WORLD PROTOCOL (what a factory must return): world.log (an EventLog, kept across reboots), world.t_utc (current UTC epoch
      s), world.advance_to(utc_s) (needed only when an action is due later than the clock; must land exactly on utc_s),
      optional world.close() (always called, also when an action raises).
  validate_doc(doc, *, tiers=None) -> doc     strict schema (every problem listed in one CorpusSchemaError); tiers defaults to
                                              TIERS plus every registered tier; optional keys (V0.1, brief B6.6; the V0
                                              key 'priority' is refused as unknown: it held the owning scenario's
                                              priority in 73 of the 85 V0 documents only, 6 of the other 12 carried the
                                              finding's V0 group priority): scenario_priority (PRIORITIES: the owning
                                              scenario's priority) and finding_priority (PRIORITIES or null: the
                                              highest root-cause priority among the counted owners of the catalogue
                                              findings that list the document), both or neither; notes (str)
  load_doc(path, *, tiers=None) -> dict       strict JSON (duplicate keys, NaN / Infinity raise) + validate_doc
  load_corpus(directory, *, tiers=None) -> [doc, ...]   every *.json in name order; the file stem must equal doc['id']
  dumps_doc(doc) -> str                       validated, sorted-key, indent-2, ASCII JSON + LF (the corpus file form)
  replay(doc, *, root=ROOT, tiers=None) -> ReplayResult(ok, failed_expectations, digest, drift, log, drifted_paths,
      digest_mismatch, anchor_problems, observations)
      1. validate; every action / observer name must be registered for the tier (checked BEFORE the world is built)
      2. drift: each source_digests entry vs source_digest(path); a mismatch or a missing file prints
         'SOURCE DRIFT: <path>' and sets drift=True; anchors are re-counted (problems printed as 'ANCHOR DRIFT: ...')
      3. world = factory(utc_start=parse_iso_utc(utc_start), seed=seed, **world); for each action (at_s non-decreasing):
         advance the world to utc_start + at_s (an action due BEFORE the world clock raises), log a src='lab'
         kind='replay.action' event {i, do, args}, call the action. Exceptions propagate (fail loud, never a pass).
      4. digest = log.digest() after the last action; then every expectation's observer is called; an observer that
         appends to the log raises ReplayDispatchError (observers must be read-only).
      5. ok = no failed expectation AND, when drift is False, digest == trace_digest and every anchor is still found
         exactly once at line_at_record. With drift=True only the expectations decide (the spec's drift rule).
  record(draft, *, root=ROOT, tiers=None, tier_pins=False) -> doc   fills source_digests (its keys plus every anchor path;
      with tier_pins=True also the document tier's TIER_SOURCES), every anchor's line_at_record and trace_digest from two
      replays (the two digests must agree and every expectation must hold, else LabTraceError); `trace_digest` may be
      absent and digest values may be placeholders in the draft
  B1 SOURCE TIERS AND THE TIERED DRIFT RULE (V0.1; the single source of truth for test_lab_replay_corpus [2] / [5],
  gen_catalogue (build, --check, the catalogue's baseline.tiers) and run_lab.baseline_status)
      LAB_PREFIX; prose TIER_RULE, LAB_RULE, DRIFT_RULE, TIER_METHOD (published in baseline.tiers)
      BEHAVIOURAL {path: evidence}: non-lab files the lab imports, executes or parses as data (pinned)
      NON_BEHAVIOURAL {path: (pinned, evidence)}: non-lab files read only by exactly-once anchors / digests (pinned) or
          existence checks (unpinned)
      TIER_SOURCES {tier: (path, ...)}: the behavioural files a replay of that tier executes
      source_tier(path) -> 'lab' | 'behavioural' | 'non-behavioural' | 'unclassified'; pinned_by_table() -> [path];
      imported_repo_files(root=ROOT) -> [path] (the repository modules in this process's sys.modules);
      unclassified_imports(root=ROOT) -> those outside the lab that BEHAVIOURAL does not list (the run-time import guard;
          finish() runs it at the end of every suite, see IMPORT_GUARD_CHECK); import_guard_failure(root=ROOT) ->
          (check name, detail) or None
      tier_table_problems(pinned_nonlab, exists=None) -> [problem]; tier_pins(tier) -> (path, ...);
      effective_pins(doc) -> its source_digests keys plus tier_pins(tier); affected_documents(path, docs) -> [id];
      compact_ids(ids) -> 'FW-01-a,b; HF-02-c'; rerecord_procedure(docs, n_all) -> text
      TreeReader(root=ROOT, overlay=None): read_bytes / text / sha / exists by repo path (cached; an overlay
          {path: bytes | None} edits the tree in memory, nothing is written)
      drift_report(pinned, docs, *, sha_of, strict=False) -> DriftReport(items, strict, n_documents) of DriftItem(path,
          tier, now, recorded, documents, stale_documents): drift_lines() ('SOURCE DRIFT (non-behavioural): <path>' plus
          ' (file missing)' for a missing file; none in strict mode),
          failures() -> [(title, detail)] one per failing file ('re-generate the catalogue: lab file changed: <path>',
          'behavioural source changed: <path>', 'unclassified pinned source changed: <path>', 'pinned source missing:
          <path>' for a missing non-behavioural file (in both modes), in strict mode also 'non-behavioural source
          changed (STRICT, ECCO_LAB_STRICT_BASELINE=1): <path>'; a missing file of the other tiers fails under its tier's
          title with the detail 'sha256 missing != recorded ...': a missing pinned file fails in EVERY tier),
          messages() -> ['<title> - <detail>']
      DRIFT_CHECK / DRIFT_CHECK_STRICT, drift_check(strict) -> the check-name prefix of the drift-rule checks of
          test_lab_replay_corpus [5] ('gen_catalogue drift rule (tiered)'; in strict mode 'gen_catalogue drift rule
          (STRICT)'); TIER_PIN_CHECK = 'B1 tier pins' (the prefix of the [2] tier-pin checks)
      ECCO_LAB_STRICT_BASELINE: the strict switch is the environment value '1' exactly (any other value, or none, is the
          tiered rule) for test_lab_replay_corpus, gen_catalogue.py --check and run_lab.py alike; only the replay suite
          also takes a --strict-baseline argument
  ddmin(items, still_fails, *, max_tests=10000) -> list   deterministic delta debugging (Zeller): an order-preserving,
      1-minimal failing sub-list; the full input must fail; still_fails must return a bool; results are cached per subset;
      more than max_tests predicate calls raise LabTraceError (never a silent non-minimal result)
  finish(suite, *, passes, failures, finding, finding_pins, unsupported_points, blocked, phase_sensitive, runtime_s)
      -> dict      prints a suite's final lines (the V0.1 output contract below) and returns the LAB-SUMMARY record:
      0. the B1 run-time import guard (V0.1): when unclassified_imports() is not empty (a repository module outside the
         lab that BEHAVIOURAL does not list is in sys.modules at the end of the suite, whoever imported it, at module
         level or lazily), it prints '  FAIL  <IMPORT_GUARD_CHECK> - <detail>' and APPENDS that name to the caller's
         `failures` list (which must then be a list: the suite's FAILURES, so its exit gate sees it; a tuple raises
         LabTraceError), so the FAILED line and the LAB-SUMMARY 'fail' count include it; when it is empty nothing is
         printed and every count is unchanged;
      1. only when `failures` is not empty: 'FAILED: <n> check(s): <name1>; <name2>; ...' (each name whitespace-collapsed,
         joined by '; '; the whole line at most FAILED_LINE_MAX = 4000 characters, cut at a name boundary and ended
         ' ... (+<k> more)', k = the names not shown);
      2. 'LAB-SUMMARY {json}' (json.dumps defaults; keys in this order; flushed):
           suite               the suite name (str)
           pass                len(passes): held checks EXCLUDING finding pins
           fail                len(failures): failed checks
           finding             len(finding): counted findings
           finding_pins        len(finding_pins): held 'finding-reproduces:' checks (printed as PASS, never in pass)
           unsupported_ids     number of distinct ids in unsupported_points
           unsupported_points  len(unsupported_points): one entry per printed UNSUPPORTED line
           blocked             len(blocked): blocked scenarios
           zoneinfo            _lab_clock.zoneinfo_available() (bool)
           phase_sensitive     len(phase_sensitive): executed checks tagged phase-sensitive
           runtime_s           round(runtime_s, 3)
      Arguments (keyword-only, all required): passes / failures / finding_pins: lists or tuples of check names (str);
      every finding_pins name starts with 'finding-reproduces:' and no passes name does; unsupported_points: a list or
      tuple of ids (str, no whitespace), one per printed UNSUPPORTED line, repeats allowed; finding / blocked /
      phase_sensitive: sized collections (list, tuple, set, frozenset, dict) whose len() is the count, never an int;
      runtime_s: a finite number >= 0. Anything else raises LabTraceError (a harness bug fails loud). Counts are always
      derived from these collections, never written as literals. After finish() a suite prints nothing more; its single
      exit gate follows ('if FAILURES: sys.exit(1)').
  failed_line(names) -> 'FAILED: <n> check(s): ...'      the line finish() prints first (names must not be empty)
  unsupported_line(uid, text) -> '  UNSUPPORTED  <uid> <one line>'   one line per unsupported POINT; uid is the catalogue
                                                          unsupported id (no whitespace); text whitespace-collapsed
  finding_line(finding_id, text) -> '  FINDING  <id> <one line>'
  PIN_PREFIX = 'finding-reproduces:'; SUMMARY_KEYS = the LAB-SUMMARY keys in order; FAILED_LINE_MAX = 4000

SUITE OUTPUT CONTRACT (V0.1; every lab suite, checked by run_lab.judge and gen_catalogue)
  Line formats, exactly two leading spaces, the tag, two spaces: '  PASS  <check name>' / '  FAIL  <check name>[ - detail]'
  for every check (a finding pin is a held check named 'finding-reproduces:...', printed as PASS, counted in
  finding_pins, not in pass); '  FINDING  <id> <text>' for a reproduced finding; '  UNSUPPORTED  <id> <text>' exactly
  once per unsupported point (several points may share one catalogue id). The output ends with the FAILED line (only if
  a check failed) and the LAB-SUMMARY line, in that order, printed by finish(); nothing follows them. The runners
  cross-check: pass == PASS lines - pin PASS lines; finding_pins == pin PASS lines; fail == FAIL lines;
  unsupported_points == UNSUPPORTED lines; unsupported_ids == distinct ids on them; any FAIL line fails the suite even
  at exit code 0; a missing or garbled LAB-SUMMARY fails.

MODEL ASSUMPTIONS
  - Digest canonicalisation: floats are rounded to 3 dp before hashing (ms resolution for float epochs), JSON is ASCII with
    sorted keys, so the digest is platform independent. Two runs that differ only below 1 ms in a float are equal.
  - Source digests hash LF-normalised bytes so that core.autocrlf checkouts (effective on the owner's PC) do not read as drift.
  - The replay engine's own src='lab' 'replay.action' events are part of the digested log.

NOT MODELLED
  - Nothing is simulated here: worlds, actions and observers come from _lab_fw / _lab_ha / _lab_rtc.
  - Expectations are evaluated once, at the end of a replay (no mid-run expectations).

SOURCE ANCHORS: the KNOWN_RISKS entries below (text snippet, path, line at writing); the self-test re-counts each one.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _lab_clock as C  # noqa: E402

SCHEMA = "ecco-assurance-lab-replay/v0"
CLASSIFICATIONS = ("PASS", "FAIL", "FINDING-NEW", "FINDING-KNOWN", "UNSUPPORTED", "BLOCKED")
GRADES = ("VERIFIED", "REPORTED", "INFERRED", "UNKNOWN")
CONFIDENCES = ("high", "medium", "low")
PRIORITIES = ("P1", "P2", "P3")
TIERS = ("firmware", "coupled", "rtc")
SOURCES = ("fw", "ha", "lab")
OPS = ("==", "!=", "startswith", "contains", "not_contains", "<=", ">=")
RISK_CLASSES = (
    "DEFERRED",           # known, deliberately deferred, with an operational restriction
    "OPEN-GAP",           # documented design gap with a later stage named to fix it
    "PLATFORM-LIMIT",     # a limit of the platform, acknowledged in the firmware's own status text or its design record
    "OUTSTANDING",        # audit finding still open (owner decision or optional work)
    "ACCEPTED-RESIDUAL",  # resolved or documented by design, with a named residual
    "DOCUMENTED-LIMIT",   # a documented limit or choice of an HA package or of the firmware's design record
)


class LabTraceError(Exception):
    """Base class of every error raised by this module."""


class CorpusSchemaError(LabTraceError):
    """A corpus / replay document does not match the schema."""


class ReplayDispatchError(LabTraceError):
    """Unknown tier, action or observer; world-protocol or clock misuse; an observer that is not read-only."""


class AnchorError(LabTraceError):
    """An anchor text does not occur exactly once in its file."""


# ---------------------------------------------------------------------------------------------------------------------------
# canonical JSON and digests
# ---------------------------------------------------------------------------------------------------------------------------
def canonical(value):
    """A JSON-able, deterministic copy of `value` (see the module docstring)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LabTraceError(f"non-finite float {value!r} cannot be canonicalised")
        r = round(float(value), 3)
        return 0.0 if r == 0 else r
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise LabTraceError(f"dict key {k!r} is not a str")
            out[str.__str__(k)] = canonical(v)
        return out
    raise LabTraceError(f"{type(value).__name__} is not canonical-JSON-able")


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_json(value) -> str:
    return _dumps(canonical(value))


def digest_of(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------
# event log
# ---------------------------------------------------------------------------------------------------------------------------
_KIND = re.compile(r"^[A-Za-z0-9_.:/-]+$")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class EventLog:
    """Append-only event log (see the module docstring)."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._t: list = []

    def append(self, *, t_utc, up_ms, boot, src, kind, data=None) -> dict:
        if not _is_num(t_utc) or not math.isfinite(t_utc):
            raise LabTraceError(f"t_utc must be a finite int/float epoch in seconds, got {t_utc!r}")
        if src not in SOURCES:
            raise LabTraceError(f"src must be one of {SOURCES}, got {src!r}")
        if not isinstance(kind, str) or not _KIND.match(kind):
            raise LabTraceError(f"kind must be a non-empty [A-Za-z0-9_.:/-] string, got {kind!r}")
        for name, v in (("up_ms", up_ms), ("boot", boot)):
            if v is None and src != "fw":
                continue
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise LabTraceError(f"{name} must be an int >= 0 for src={src!r} (None allowed only for ha/lab), got {v!r}")
        ev = {"seq": len(self._lines), "t_utc": canonical(t_utc), "up_ms": up_ms, "boot": boot, "src": src, "kind": kind,
              "data": canonical({} if data is None else data)}
        line = _dumps(ev)
        self._lines.append(line)
        self._t.append(ev["t_utc"])
        return json.loads(line)

    def __len__(self) -> int:
        return len(self._lines)

    def __iter__(self):
        return (json.loads(x) for x in list(self._lines))

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [json.loads(x) for x in self._lines[i]]
        return json.loads(self._lines[i])

    def events(self, kind: str | None = None, src: str | None = None, boot: int | None = None) -> list[dict]:
        return [e for e in self if (kind is None or e["kind"] == kind) and (src is None or e["src"] == src)
                and (boot is None or e["boot"] == boot)]

    def last(self, kind: str | None = None, src: str | None = None) -> dict | None:
        for x in reversed(self._lines):
            e = json.loads(x)
            if (kind is None or e["kind"] == kind) and (src is None or e["src"] == src):
                return e
        return None

    def canonical(self) -> str:
        return "[" + ",".join(self._lines) + "]"

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("ascii")).hexdigest()

    def utc_regressions(self) -> list[int]:
        return [i for i in range(1, len(self._t)) if self._t[i] < self._t[i - 1]]


# ---------------------------------------------------------------------------------------------------------------------------
# source files, anchors, digests
# ---------------------------------------------------------------------------------------------------------------------------
_SEG = re.compile(r"^[A-Za-z0-9_.-]+$")


def _path_ok(path) -> bool:
    return (isinstance(path, str) and bool(path) and all(_SEG.match(s) and s not in (".", "..") for s in path.split("/")))


def _file(path: str, root) -> Path:
    if not _path_ok(path):
        raise LabTraceError(f"not a repo-relative POSIX path: {path!r}")
    return Path(root) / path


def read_source_text(path: str, root=ROOT) -> str:
    return _file(path, root).read_bytes().decode("utf-8").replace("\r\n", "\n")


def source_digest(path: str, root=ROOT) -> str:
    return hashlib.sha256(_file(path, root).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def anchor_count(path: str, text: str, root=ROOT) -> tuple[int, int | None]:
    """(occurrences of `text` in the file, 1-based line of the first occurrence or None)."""
    if not isinstance(text, str) or not text:
        raise LabTraceError("anchor text must be a non-empty str")
    src = read_source_text(path, root)
    n = src.count(text)
    return n, (src[:src.find(text)].count("\n") + 1 if n else None)


def anchor_line(path: str, text: str, root=ROOT) -> int:
    n, line = anchor_count(path, text, root)
    if n != 1:
        raise AnchorError(f"anchor occurs {n} times (want exactly 1) in {path}: {text[:80]!r}")
    return line


# ---------------------------------------------------------------------------------------------------------------------------
# known-risk registry (classify against these; never report them as new)
# ---------------------------------------------------------------------------------------------------------------------------
_FCP2 = "docs/dev/dump-to-grid-safety-fcp2.md"
_S4 = "docs/architecture/fallback/design/S4_domains_decisions_final.md"
_SMR1 = "docs/dev/schedule-manual-restore.md"
_FW = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"


def _risk(title: str, path: str, text: str, line: int, cls: str) -> dict:
    return {"title": title, "path": path, "text": text, "line_at_record": line, "doc_anchor": f"{path}:{line}", "class": cls}


KNOWN_RISKS: dict[str, dict] = {
    "SG-25": _risk("Dump START TOU charge-slot gate walks the lease window in local minutes (DST-blind); operational "
                   "restriction on the clock-change nights", _FCP2,
                   "**SG-25, the DST-aware TOU charge-slot gate.**", 456, "DEFERRED"),
    "N10": _risk("No FP / reg244 dual-obligation arbitration at boot", _S4, "| N10 | No FP", 162, "OPEN-GAP"),
    "N15": _risk("No final-writer latch: a ghost FP/Dump marker makes the next boot restore a stale ORIGINAL", _S4,
                 "| N15 | P3 does not exist, so \"Fallback is the final writer\" is not enforced after a write |", 167,
                 "OPEN-GAP"),
    "N16": _risk("SG-02 containment (P0) can overlay a trusted reg244 obligation (no other-domain term in its gate)", _S4,
                 "| **N16** | P0 can overlay a **trusted** R244 obligation.", 168, "ACCEPTED-RESIDUAL"),
    "N17": _risk("P1 restores carry no cross-domain terms: with the other domain corrupt/unknown a trusted restore writes the "
                 "shared 256-261 over its unresolved obligation", _S4,
                 "| **N17** | P1 restores (FP and Dump) carry no cross-domain terms.", 169, "ACCEPTED-RESIDUAL"),
    "PR41-GHOST": _risk("Phase-B commit false negative ghost: the marker commit lands RESTORE_REQUIRED but reports failure, so "
                        "RAM stays clear and the OTHER domain's START admission gate is defeated until the next reboot, where "
                        "the boot dual-obligation arbitration (PR41) fails both domains closed; second reference: the "
                        "firmware on_boot comment 'Free Power<->Dump dual durable-obligation dead-end (256-261)' "
                        "(KNOWN_RISK_REFS)", _S4,
                        "A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear)", 445, "DOCUMENTED-LIMIT"),
    "NVS-PARTITION-ERASE": _risk("NVS partition erase (ESPHome erases the partition when nvs_open fails): every durable "
                                 "marker reads ABSENT, so an outstanding obligation is lost unless a retry record "
                                 "survived", _S4, "A partition erase (E04 P10; ESPHome erases the partition when", 447,
                                 "PLATFORM-LIMIT"),
    "PLATFORM-ABSENT": _risk("Platform limit: a marker unreadable at boot may read as ABSENT after a further reboot", _FW,
                             "export containment not armed - do NOT reboot: a reboot may make the record read as absent",
                             913, "PLATFORM-LIMIT"),
    "FCP2-R1": _risk("SG-04 residual: export can stay enabled if the inverter refuses every 244 write (ECCO settings bounded "
                     "by the 500 W containment, alarmed)", _FCP2,
                     "| R1 SG-04: block never restored when 244 fails; no supervision |", 434, "ACCEPTED-RESIDUAL"),
    "FCP2-C1": _risk("FOREIGN slots are not contained while 244 is unproven (never written by design; named in the status)",
                     _FCP2, "| C1 (re-audit) FOREIGN slots uncontained while 244 is unproven;", 450, "ACCEPTED-RESIDUAL"),
    "FCP2-F2": _risk("Backstop above physical capability at 8 kW; allowance extrapolated", _FCP2,
                     "| F2 backstop above physical capability at 8 kW; allowance extrapolated |", 439, "OUTSTANDING"),
    "FCP2-F3": _risk("Frozen-battery check: fixed 1500 Wh stays site-dependent", _FCP2,
                     "| F3 frozen battery at 0 W; SOC toggling |", 440, "OUTSTANDING"),
    "FCP2-F6": _risk("OTA not gated; default reboot timeouts; restart loop; build tag default", _FCP2,
                     "| F6 OTA not gated; default reboot timeouts; restart loop; build tag default |", 443, "OUTSTANDING"),
    "FCP2-F7": _risk("One arm for both Dump limits (owner decision)", _FCP2,
                     "| F7 target equal to the limit; one arm for both limits |", 444, "OUTSTANDING"),
    "FCP2-F8": _risk("START does not use the pre-read's 245-255 (optional)", _FCP2,
                     "| F8 use the pre-read's 245-255 |", 445, "OUTSTANDING"),
    "SMR1-OWNER-STAGING": _risk("SMR1: an owner change to exactly the schedule's value during a scheduled start's staging / "
                                "retry window is taken for the schedule's write", _SMR1,
                                "- **Owner change during a scheduled start.**", 69, "DOCUMENTED-LIMIT"),
    "SMR1-OWNER-RESTORING": _risk("SMR1: an owner change during RESTORING is not seen as the owner's (PARTIAL / FAILED)",
                                  _SMR1, "- **Owner change during the restore.**", 70, "DOCUMENTED-LIMIT"),
    "SMR1-UNCLEAN-SHUTDOWN": _risk("SMR1: a crash or power cut within 15 min of a scheduled start can lose the obligation",
                                   _SMR1, "- **Unclean shutdown.** Home Assistant saves restored helper states every 15 "
                                   "minutes and at a clean stop.", 71, "DOCUMENTED-LIMIT"),
    "SMR1-STALE-24H": _risk("SMR1: an obligation older than 24 h (or with an unreadable time) is STALE: nothing is written",
                            _SMR1, "`STALE`: the obligation is older than 24 h, or its time cannot be read.", 50,
                            "DOCUMENTED-LIMIT"),
}
# Secondary references of a known risk (information; test_lab_selftest_core verifies each text occurs exactly once). The
# registry entry itself keeps exactly one anchor; these name further public places that document the same risk.
KNOWN_RISK_REFS: dict[str, tuple] = {
    "PR41-GHOST": ((_FW, "Free Power<->Dump dual durable-obligation dead-end (256-261)"),
                   (_FW, "a Phase-B commit-helper sync() false negative")),
}


def known_risk(risk_id: str) -> dict:
    if risk_id not in KNOWN_RISKS:
        raise LabTraceError(f"unknown known-risk id {risk_id!r}")
    return copy.deepcopy(KNOWN_RISKS[risk_id])


def known_risk_status(root=ROOT) -> dict[str, dict]:
    out = {}
    for rid, r in KNOWN_RISKS.items():
        n, line = anchor_count(r["path"], r["text"], root)
        out[rid] = {"count": n, "line": line, "line_at_record": r["line_at_record"]}
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# classification vocabulary
# ---------------------------------------------------------------------------------------------------------------------------
def parse_classification(text: str) -> tuple[str, str | None]:
    if not isinstance(text, str):
        raise LabTraceError(f"classification must be a str, got {text!r}")
    if text.startswith("FINDING-KNOWN:"):
        rid = text[len("FINDING-KNOWN:"):]
        if rid not in KNOWN_RISKS:
            raise LabTraceError(f"FINDING-KNOWN names an unregistered risk {rid!r}")
        return "FINDING-KNOWN", rid
    if text in CLASSIFICATIONS and text != "FINDING-KNOWN":
        return text, None
    raise LabTraceError(f"not a classification: {text!r} (use {CLASSIFICATIONS}, FINDING-KNOWN as FINDING-KNOWN:<risk-id>)")


def classify(kind: str, risk_id: str | None = None) -> str:
    text = f"{kind}:{risk_id}" if risk_id is not None else kind
    if (kind == "FINDING-KNOWN") != (risk_id is not None):
        raise LabTraceError("a risk id goes with FINDING-KNOWN and only with it")
    parse_classification(text)
    return text


# ---------------------------------------------------------------------------------------------------------------------------
# expectations
# ---------------------------------------------------------------------------------------------------------------------------
def eval_expectation(op: str, observed, value) -> tuple[bool, str]:
    if op not in OPS:
        raise CorpusSchemaError(f"unknown expectation op {op!r}")
    obs, val = canonical(observed), canonical(value)
    js_o, js_v = _dumps(obs), _dumps(val)
    detail = f"observed {js_o[:300]} {op} {js_v[:300]}"
    if op in ("==", "!="):
        return (js_o == js_v) == (op == "=="), detail
    if op == "startswith":
        if not (isinstance(obs, str) and isinstance(val, str)):
            return False, "type mismatch (startswith needs two str): " + detail
        return obs.startswith(val), detail
    if op in ("contains", "not_contains"):
        if isinstance(obs, str) and isinstance(val, str):
            hit = val in obs
        elif isinstance(obs, list):
            hit = any(_dumps(x) == js_v for x in obs)
        elif isinstance(obs, dict) and isinstance(val, str):
            hit = val in obs
        else:
            return False, f"type mismatch ({op} needs str/str, list/any or dict/str): " + detail
        return hit == (op == "contains"), detail
    if not (_is_num(obs) and _is_num(val)):
        return False, f"type mismatch ({op} needs two numbers): " + detail
    return (obs <= val) if op == "<=" else (obs >= val), detail


# ---------------------------------------------------------------------------------------------------------------------------
# tier registries
# ---------------------------------------------------------------------------------------------------------------------------
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_TIERS: dict[str, dict] = {}


def _tier(tier: str) -> dict:
    if not isinstance(tier, str) or not _NAME.match(tier):
        raise ReplayDispatchError(f"bad tier name {tier!r}")
    return _TIERS.setdefault(tier, {"factory": None, "actions": {}, "observers": {}})


def register_tier(tier: str, factory) -> None:
    t = _tier(tier)
    if not callable(factory):
        raise ReplayDispatchError(f"tier {tier!r}: factory is not callable")
    if t["factory"] is not None and t["factory"] is not factory:
        raise ReplayDispatchError(f"tier {tier!r} already has a different factory")
    t["factory"] = factory


def _register(tier: str, slot: str, mapping: dict) -> None:
    t = _tier(tier)
    for name, fn in mapping.items():
        if not isinstance(name, str) or not _NAME.match(name):
            raise ReplayDispatchError(f"tier {tier!r}: bad {slot[:-1]} name {name!r}")
        if not callable(fn):
            raise ReplayDispatchError(f"tier {tier!r}: {slot[:-1]} {name!r} is not callable")
        old = t[slot].get(name)
        if old is not None and old is not fn:
            raise ReplayDispatchError(f"tier {tier!r}: {slot[:-1]} {name!r} is already registered to a different function")
        t[slot][name] = fn


def register_actions(tier: str, mapping: dict) -> None:
    _register(tier, "actions", mapping)


def register_observers(tier: str, mapping: dict) -> None:
    _register(tier, "observers", mapping)


def unregister_tier(tier: str) -> None:
    _TIERS.pop(tier, None)


def registered(tier: str) -> dict:
    t = _TIERS.get(tier)
    if t is None:
        return {"factory": False, "actions": [], "observers": []}
    return {"factory": t["factory"] is not None, "actions": sorted(t["actions"]), "observers": sorted(t["observers"])}


# ---------------------------------------------------------------------------------------------------------------------------
# corpus schema
# ---------------------------------------------------------------------------------------------------------------------------
REQUIRED_KEYS = ("schema", "id", "title", "tier", "seed", "utc_start", "synthetic", "ownership", "source_anchors",
                 "source_digests", "world", "actions", "expect", "classification", "invariant", "grade", "confidence",
                 "failure_outcome", "smallest_safe_repair_scope", "trace_digest")
# V0.1 (brief B6.6): the V0 'priority' key held the owning scenario's priority in 73 of the 85 V0 documents (6 of the
# other 12 carried the finding's V0 group priority, so its meaning was mixed); it is replaced by scenario_priority and
# finding_priority (null for a document no catalogue finding lists); both or neither
OPTIONAL_KEYS = ("scenario_priority", "finding_priority", "notes")
_ID = re.compile(r"^[A-Z]{2,4}-[0-9]{2}(-[A-Za-z0-9]+)+$")
_INV = re.compile(r"^INV-[A-Z0-9]+(-[A-Z0-9]+)*$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KWARG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _kwargs_problems(where: str, args) -> list[str]:
    if not isinstance(args, dict):
        return [f"{where}: args must be an object"]
    return [f"{where}: bad argument name {k!r}" for k in args if not (isinstance(k, str) and _KWARG.match(k))]


def _exact_keys(where: str, obj, keys: tuple) -> list[str]:
    if not isinstance(obj, dict):
        return [f"{where}: must be an object"]
    out = [f"{where}: missing key {k!r}" for k in keys if k not in obj]
    return out + [f"{where}: unknown key {k!r}" for k in obj if k not in keys]


def validate_doc(doc, *, tiers=None) -> dict:
    """Raise CorpusSchemaError listing every schema problem of a replay document; return the document unchanged."""
    if not isinstance(doc, dict):
        raise CorpusSchemaError("a replay document must be a JSON object")
    allowed_tiers = tuple(TIERS) + tuple(sorted(set(_TIERS) - set(TIERS))) if tiers is None else tuple(tiers)
    p = [f"missing required key {k!r}" for k in REQUIRED_KEYS if k not in doc]
    p += [f"unknown key {k!r}" for k in doc if k not in REQUIRED_KEYS + OPTIONAL_KEYS]
    g = doc.get
    if "schema" in doc and g("schema") != SCHEMA:
        p.append(f"schema must be {SCHEMA!r}")
    if "id" in doc and not (isinstance(g("id"), str) and _ID.match(g("id"))):
        p.append(f"id {g('id')!r} does not match {_ID.pattern}")
    for k in ("title", "ownership", "failure_outcome", "smallest_safe_repair_scope"):
        if k in doc and not _nonempty_str(g(k)):
            p.append(f"{k} must be a non-empty string")
    if "tier" in doc and g("tier") not in allowed_tiers:
        p.append(f"tier {g('tier')!r} is not one of {allowed_tiers}")
    if "seed" in doc and (isinstance(g("seed"), bool) or not isinstance(g("seed"), int) or g("seed") < 0):
        p.append("seed must be an int >= 0")
    if "utc_start" in doc:
        try:
            C.parse_iso_utc(g("utc_start"))
        except ValueError as exc:
            p.append(f"utc_start: {exc}")
    if "synthetic" in doc and g("synthetic") is not True:
        p.append("synthetic must be true (corpus files hold synthetic values only)")
    digests = g("source_digests")
    if "source_digests" in doc:
        if not isinstance(digests, dict) or not digests:
            p.append("source_digests must be a non-empty object")
            digests = {}
        for path, h in digests.items():
            if not _path_ok(path):
                p.append(f"source_digests: bad path {path!r}")
            if not (isinstance(h, str) and _HEX64.match(h)):
                p.append(f"source_digests[{path!r}] must be a lowercase sha256 hex digest")
    if "source_anchors" in doc:
        anchors = g("source_anchors")
        if not isinstance(anchors, list) or not anchors:
            p.append("source_anchors must be a non-empty list")
            anchors = []
        for i, a in enumerate(anchors):
            where = f"source_anchors[{i}]"
            probs = _exact_keys(where, a, ("path", "text", "line_at_record"))
            p += probs
            if probs:
                continue
            if not _path_ok(a["path"]):
                p.append(f"{where}: bad path {a['path']!r}")
            elif isinstance(digests, dict) and a["path"] not in digests:
                p.append(f"{where}: path {a['path']!r} has no source_digests entry")
            if not (isinstance(a["text"], str) and a["text"]):
                p.append(f"{where}: text must be a non-empty string")
            ln = a["line_at_record"]
            if isinstance(ln, bool) or not isinstance(ln, int) or ln < 1:
                p.append(f"{where}: line_at_record must be an int >= 1")
    if "world" in doc:
        w = g("world")
        p += _kwargs_problems("world", w)
        if isinstance(w, dict):
            p += [f"world: key {k!r} is reserved (the engine passes it)" for k in ("utc_start", "seed") if k in w]
    if "actions" in doc:
        acts = g("actions")
        if not isinstance(acts, list):
            p.append("actions must be a list")
            acts = []
        prev = 0
        for i, a in enumerate(acts):
            where = f"actions[{i}]"
            probs = _exact_keys(where, a, ("at_s", "do", "args"))
            p += probs
            if probs:
                continue
            at = a["at_s"]
            if not _is_num(at) or not math.isfinite(at) or at < 0:
                p.append(f"{where}: at_s must be a finite number >= 0")
            elif at < prev:
                p.append(f"{where}: at_s {at} is earlier than the previous action's {prev}")
            else:
                prev = at
            if not (isinstance(a["do"], str) and _NAME.match(a["do"])):
                p.append(f"{where}: bad action name {a['do']!r}")
            p += _kwargs_problems(where, a["args"])
    if "expect" in doc:
        exps = g("expect")
        if not isinstance(exps, list) or not exps:
            p.append("expect must be a non-empty list")
            exps = []
        for i, e in enumerate(exps):
            where = f"expect[{i}]"
            probs = _exact_keys(where, e, ("observe", "args", "op", "value"))
            p += probs
            if probs:
                continue
            if not (isinstance(e["observe"], str) and _NAME.match(e["observe"])):
                p.append(f"{where}: bad observer name {e['observe']!r}")
            if e["op"] not in OPS:
                p.append(f"{where}: unknown op {e['op']!r} (use {OPS})")
            p += _kwargs_problems(where, e["args"])
            try:
                canonical(e["value"])
            except LabTraceError as exc:
                p.append(f"{where}: value: {exc}")
    if "classification" in doc:
        try:
            parse_classification(g("classification"))
        except LabTraceError as exc:
            p.append(f"classification: {exc}")
    if "invariant" in doc and not (isinstance(g("invariant"), str) and _INV.match(g("invariant"))):
        p.append(f"invariant {g('invariant')!r} does not match {_INV.pattern}")
    if "grade" in doc and g("grade") not in GRADES:
        p.append(f"grade must be one of {GRADES}")
    if "confidence" in doc and g("confidence") not in CONFIDENCES:
        p.append(f"confidence must be one of {CONFIDENCES}")
    if "trace_digest" in doc and not (isinstance(g("trace_digest"), str) and _HEX64.match(g("trace_digest"))):
        p.append("trace_digest must be a lowercase sha256 hex digest")
    if "scenario_priority" in doc and g("scenario_priority") not in PRIORITIES:
        p.append(f"scenario_priority must be one of {PRIORITIES}")
    if "finding_priority" in doc and g("finding_priority") is not None and g("finding_priority") not in PRIORITIES:
        p.append(f"finding_priority must be null or one of {PRIORITIES}")
    if ("scenario_priority" in doc) != ("finding_priority" in doc):
        p.append("scenario_priority and finding_priority go together (both or neither)")
    if "notes" in doc and not isinstance(g("notes"), str):
        p.append("notes must be a string")
    if p:
        raise CorpusSchemaError(f"replay document {doc.get('id')!r}: " + "; ".join(p))
    return doc


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise CorpusSchemaError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _no_constant(name):
    raise CorpusSchemaError(f"non-finite JSON constant {name}")


def load_doc(path, *, tiers=None) -> dict:
    text = Path(path).read_bytes().decode("utf-8")
    doc = json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_constant)
    return validate_doc(doc, tiers=tiers)


def load_corpus(directory, *, tiers=None) -> list[dict]:
    d = Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {d}")
    docs = []
    for f in sorted(d.glob("*.json")):
        doc = load_doc(f, tiers=tiers)
        if doc["id"] != f.stem:
            raise CorpusSchemaError(f"{f.name}: file stem must equal the document id {doc['id']!r}")
        docs.append(doc)
    return docs


def dumps_doc(doc) -> str:
    validate_doc(doc)
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


# ---------------------------------------------------------------------------------------------------------------------------
# replay engine
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    failed_expectations: list
    digest: str
    drift: bool
    log: EventLog
    drifted_paths: tuple = ()
    digest_mismatch: bool = False
    anchor_problems: tuple = ()
    observations: list = field(default_factory=list)


def _execute(doc: dict) -> tuple[list, str, EventLog, list]:
    """Build the world, run the actions, evaluate the expectations: (failed, digest, log, observations)."""
    t = _TIERS.get(doc["tier"])
    if t is None or t["factory"] is None:
        raise ReplayDispatchError(f"tier {doc['tier']!r} has no registered factory")
    unknown = sorted({a["do"] for a in doc["actions"]} - set(t["actions"]))
    unknown_obs = sorted({e["observe"] for e in doc["expect"]} - set(t["observers"]))
    if unknown or unknown_obs:
        raise ReplayDispatchError(f"tier {doc['tier']!r}: unknown action(s) {unknown}, unknown observer(s) {unknown_obs}")
    utc0 = C.parse_iso_utc(doc["utc_start"])
    world = t["factory"](utc_start=utc0, seed=doc["seed"], **copy.deepcopy(doc["world"]))
    try:
        log = getattr(world, "log", None)
        if not isinstance(log, EventLog):
            raise ReplayDispatchError(f"tier {doc['tier']!r}: world.log is not an EventLog")
        for i, act in enumerate(doc["actions"]):
            due, now = utc0 + act["at_s"], world.t_utc
            if due > now:
                adv = getattr(world, "advance_to", None)
                if adv is None:
                    raise ReplayDispatchError(f"tier {doc['tier']!r}: world has no advance_to() (action {i} is due later)")
                adv(due)
                if abs(world.t_utc - due) > 1e-6:
                    raise ReplayDispatchError(f"advance_to({due}) left the world clock at {world.t_utc}")
            elif due < now - 1e-6:
                raise ReplayDispatchError(f"action {i} ({act['do']}) is due at +{act['at_s']} s but the world clock is "
                                          f"already at +{now - utc0} s")
            log.append(t_utc=world.t_utc, up_ms=None, boot=None, src="lab", kind="replay.action",
                       data={"i": i, "do": act["do"], "args": act["args"]})
            t["actions"][act["do"]](world, **copy.deepcopy(act["args"]))
        digest, n_events = log.digest(), len(log)
        failed, observations = [], []
        for j, e in enumerate(doc["expect"]):
            observed = canonical(t["observers"][e["observe"]](world, **copy.deepcopy(e["args"])))
            if len(log) != n_events:
                raise ReplayDispatchError(f"observer {e['observe']!r} appended to the event log (observers must be read-only)")
            ok, detail = eval_expectation(e["op"], observed, e["value"])
            observations.append(observed)
            if not ok:
                failed.append({"index": j, "observe": e["observe"], "args": e["args"], "op": e["op"], "value": e["value"],
                               "observed": observed, "detail": detail})
    finally:
        close = getattr(world, "close", None)
        if callable(close):
            close()
    return failed, digest, log, observations


def replay(doc, *, root=ROOT, tiers=None) -> ReplayResult:
    validate_doc(doc, tiers=tiers)
    drifted = []
    for path in sorted(doc["source_digests"]):
        f = _file(path, root)
        if not f.is_file() or source_digest(path, root) != doc["source_digests"][path]:
            drifted.append(path)
            print(f"SOURCE DRIFT: {path}")
    drift = bool(drifted)
    anchor_problems = []
    for a in doc["source_anchors"]:
        if not _file(a["path"], root).is_file():
            anchor_problems.append(f"{a['path']}: file missing")
            continue
        n, line = anchor_count(a["path"], a["text"], root)
        if n != 1 or line != a["line_at_record"]:
            anchor_problems.append(f"{a['path']}: anchor found {n} time(s), line {line} (recorded {a['line_at_record']}): "
                                   f"{a['text'][:60]!r}")
    if drift:
        for msg in anchor_problems:
            print(f"ANCHOR DRIFT: {msg}")
    failed, digest, log, observations = _execute(doc)
    mismatch = (not drift) and digest != doc["trace_digest"]
    ok = not failed and (drift or (not mismatch and not anchor_problems))
    return ReplayResult(ok=ok, failed_expectations=failed, digest=digest, drift=drift, log=log, drifted_paths=tuple(drifted),
                        digest_mismatch=mismatch, anchor_problems=tuple(anchor_problems), observations=observations)


def record(draft, *, root=ROOT, tiers=None, tier_pins: bool = False) -> dict:
    """A complete replay document from a draft (see the module docstring); tier_pins=True also pins the document
    tier's TIER_SOURCES in its source_digests (rerecord_corpus.py --pin-tier-sources)."""
    doc = copy.deepcopy(draft)
    anchors = doc.get("source_anchors")
    if not isinstance(anchors, list) or not all(isinstance(a, dict) and "path" in a and "text" in a for a in anchors):
        raise CorpusSchemaError("record: source_anchors must be a list of {path, text, ...} objects")
    paths = sorted(set(doc.get("source_digests") or {}) | {a["path"] for a in anchors}
                   | (set(TIER_SOURCES.get(doc.get("tier"), ())) if tier_pins else set()))
    doc["source_digests"] = {p: source_digest(p, root) for p in paths}
    for a in anchors:
        a["line_at_record"] = anchor_line(a["path"], a["text"], root)
    doc["trace_digest"] = "0" * 64
    validate_doc(doc, tiers=tiers)
    runs = [_execute(doc) for _ in range(2)]
    if runs[0][1] != runs[1][1]:
        raise LabTraceError(f"record {doc['id']}: two replays gave different digests (non-deterministic world)")
    if runs[0][0]:
        raise LabTraceError(f"record {doc['id']}: expectation(s) do not hold: {[f['detail'] for f in runs[0][0]]}")
    doc["trace_digest"] = runs[0][1]
    return doc


# ---------------------------------------------------------------------------------------------------------------------------
# B1 (V0.1): source tiers and the tiered drift rule - the single source of truth used by test_lab_replay_corpus [2] / [5],
# gen_catalogue (build, --check, baseline.tiers) and run_lab.baseline_status
# ---------------------------------------------------------------------------------------------------------------------------
LAB_PREFIX = "registry/tests/assurance_lab/"
TIER_RULE = ("a repository file outside registry/tests/assurance_lab/ is BEHAVIOURAL when lab code imports it, executes it, "
             "parses it as data or derives an expectation from any of its content other than an exactly-once anchor text; "
             "it is NON-BEHAVIOURAL when lab code reads it only through exactly-once anchor checks, its LF-normalised "
             "sha256 digest or an existence check. The catalogue pins every behavioural file and every anchor-read "
             "non-behavioural file (baseline.sources); an existence-only citation is listed unpinned")
LAB_RULE = ("every file under registry/tests/assurance_lab/ (the suites, test_lab_replay_corpus.py itself included, the "
            "helpers, the runner, the generator, the re-record and trace tools and the corpus documents) is a lab file and "
            "is pinned exactly: a changed or unpinned lab file is a FAIL until the catalogue is regenerated. The one "
            "exemption is SCENARIO_CATALOGUE.json, which cannot record its own digest: test_lab_replay_corpus checks it "
            "against the tree ([0], [3]) and against a fresh static build ([5]), and gen_catalogue.py --check against a "
            "fresh full build. The replay suite is pinned like every other lab file (it embeds nothing derived from its "
            "own digest, so there is no circularity), so an edit to that gate is a catalogue change too")
DRIFT_RULE = ("a changed lab file is a FAIL ('re-generate the catalogue'); a changed behavioural file is one named FAIL per "
              "file that lists the corpus documents replaying it and the re-record procedure; a changed pinned file in "
              "neither tier is a FAIL judged as behavioural until it is classified; a changed non-behavioural file prints "
              "'SOURCE DRIFT (non-behavioural): <path>' and is not a failure, while every anchor in it is still checked "
              "exactly once; a pinned file that is missing FAILS in every tier (a non-behavioural one as 'pinned source "
              "missing: <path>', the others under their tier's failure, 'sha256 missing'); "
              "ECCO_LAB_STRICT_BASELINE=1 (the environment value '1' exactly) keeps the whole-baseline rule (any pinned "
              "difference FAILS, under the check-name prefix 'gen_catalogue drift rule (STRICT)'). Every corpus document "
              "is judged against its own source_digests plus its tier's TIER_SOURCES (the tier pins, recorded in "
              "baseline.sources)")
TIER_METHOD = ("derived from an audit-hook trace, not by hand, and repeatable with registry/tests/assurance_lab/"
               "trace_inputs.py (a command-line tool, standard library only, not a suite; it exits 1 on any difference "
               "from this table): a sitecustomize module on PYTHONPATH (inherited by the suites' own child processes) "
               "installs sys.addaudithook and logs every 'open' of a repository file with the in-repository caller "
               "frames (innermost first) and whether the import machinery is on the stack; every lab suite runs from the "
               "repository root as 'python -B <file>' with PYTHONDONTWRITEBYTECODE=1 (the CI command line 'python "
               "<file>' plus the two switches that keep the trace from writing bytecode; CI adds neither) in quick mode "
               "and in extended mode (ECCO_LAB_EXTENDED=1), and every corpus document is replayed alone in its own "
               "process with only its tier module imported (the per-tier sets). Logged paths are case-folded on Windows "
               "and mapped back to the repository's own spelling. A read by the import machinery, or one whose innermost "
               "in-repository frames are not an anchor, digest, overlay or existence helper, is behavioural; reads only "
               "through _lab_trace.anchor_count (every call site checks exactly once or prints the line as information), "
               "_lab_trace.source_digest, a TreeReader digest, gen_catalogue's anchor count (anchor_str), "
               "run_lab.lf_digest, test_lab_replay_corpus's anchor helpers (anchor_hits, anchors_not_once), its "
               "existence helper (cited) or its drift-control overlay copy (comment_overlay: hashed and anchor-counted "
               "only) are non-behavioural, and a file read only by the existence helper is listed unpinned. Quick and "
               "extended runs read the same 75 non-lab files; the replays of the documents of one tier execute the same "
               "set. Between traces the run-time import guard catches a new import: _lab_trace.finish() checks "
               "sys.modules at the end of every suite and FAILS naming every repository module outside the lab that "
               "BEHAVIOURAL does not list, whether a suite, a lab helper, a shared simulator or the generator imported "
               "it, at module level or lazily (test_lab_replay_corpus [2] and test_lab_selftest_core also check it "
               "mid-run). The guard does not see a data read (an open of a file the lab does not import) or an import "
               "made only by a command-line tool outside the suites (run_lab.py, gen_catalogue.py, rerecord_corpus.py); "
               "those are found by re-running trace_inputs.py")
_EXISTENCE = ("existence only: a coverage-matrix citation (test_lab_replay_corpus [3] reads it to check that it exists, "
              "gen_catalogue checks the file exists); no content is used")
_ANCHORS = "exactly-once anchors only: "
_D_B1 = ("; the V0.1 brief lists this kind of file among the behavioural examples, but the trace shows anchor reads only, "
         "so it is non-behavioural")
# path -> evidence (who imports / executes / parses it)
BEHAVIOURAL: dict[str, str] = {
    "firmware/ecco_clock_dongle_stage3_4_free_power.yaml": (
        "executed: transpiled and run by every firmware and coupled world (_lab_fw.load_fw) and by the rtc rig "
        "(registry/tests/_fbd1_harness.py live_text); parsed at import by registry/tests/_sg01_recovery_harness.py; "
        "mutated in memory by the suites' negative controls"),
    "firmware/include/ecco_durable_snapshot.h": (
        "parsed as data: at import by registry/tests/_sg01_recovery_harness.py and at module load by test_lab_fw_runtime "
        "and test_lab_fw_guards, which derive constants from its text"),
    "home-assistant/packages/ecco_dump_to_grid_schedule.yaml": (
        "parsed and executed by the HA script interpreter in every coupled world (_lab_ha package_text)"),
    "home-assistant/packages/ecco_free_power_schedule.yaml": (
        "parsed and executed by the HA script interpreter in every coupled world (_lab_ha package_text)"),
    "home-assistant/packages/ecco_runtime_config.yaml": (
        "parsed and its effective-limit template rendered in every coupled world (_lab_ha check_packages / "
        "limit_template)"),
    "home-assistant/packages/ecco_schedule_manual_restore.yaml": (
        "parsed and executed by the HA script interpreter in every coupled world (_lab_ha package_text)"),
    "home-assistant/tests/_ha_dump_sim.py": "imported (by _lab_ha and the HA suites)",
    "home-assistant/tests/_ha_script_sim.py": "imported: the HA script interpreter (by _lab_ha and the HA suites)",
    "registry/fallback_durable.py": "imported (by registry/tests/_fbb1_engine.py)",
    "registry/fallback_profile.py": "imported (by registry/fallback_durable.py)",
    "registry/free_power_recovery_evidence.py": (
        "imported (by registry/tests/_dump_sim.py and registry/tests/_sg01_recovery_harness.py)"),
    "registry/free_power_self_partial.py": "imported (by registry/tests/_sg01_recovery_harness.py)",
    "registry/rtc_policy.py": (
        "imported (by registry/tests/_fbd1_harness.py); executed in the rtc tier as the Python mirror of ecco_rtc::"),
    "registry/tests/_dump_sim.py": (
        "imported: the firmware transpiler and simulator (by _lab_fw, _lab_rtc, registry/tests/_fbd1_harness.py and "
        "several suites)"),
    "registry/tests/_dump_v2_evidence_model.py": "imported (by registry/tests/_dump_sim.py)",
    "registry/tests/_fbb1_engine.py": "imported (by registry/tests/_fbd1_harness.py, _lab_rtc and test_lab_selftest_rtc)",
    "registry/tests/_fbb1_fbcap.py": "imported (by registry/tests/_fbb_harness.py)",
    "registry/tests/_fbb1_types.py": "imported (by registry/tests/_fbb1_engine.py)",
    "registry/tests/_fbb1_xpile.py": "imported (by registry/tests/_fbb_harness.py)",
    "registry/tests/_fbb_harness.py": "imported (by registry/tests/_fbd1_harness.py)",
    "registry/tests/_fbd1_harness.py": (
        "imported (by _lab_fw, _lab_rtc, test_lab_selftest_core and test_lab_selftest_rtc); its make_rig is the rtc "
        "tier's simulator"),
    "registry/tests/_fbd1_scope.py": "imported (by registry/tests/_fbd1_harness.py)",
    "registry/tests/_free_power_action_sim.py": "imported (by registry/tests/_sg01_recovery_harness.py)",
    "registry/tests/_sg01_journal_model.py": "imported (by registry/tests/_dump_sim.py)",
    "registry/tests/_sg01_recovery_harness.py": "imported (by _lab_fw)",
    "tools/fbd1_soak/__init__.py": (
        "imported: the package of tools/fbd1_soak/timeutil.py (by test_lab_property and test_lab_selftest_core)"),
    "tools/fbd1_soak/timeutil.py": (
        "imported: the third clock oracle (by test_lab_property and test_lab_selftest_core); test_lab_property also "
        "reads its text to build an in-memory mutant"),
}
# path -> (pinned in baseline.sources, evidence)
NON_BEHAVIOURAL: dict[str, tuple[bool, str]] = {
    "CHANGELOG.md": (True, _ANCHORS + "catalogue, test_lab_ha_lifecycle; its bytes are also copied into the in-memory "
                     "overlay of the replay suite's drift control NC-RC-40 (hashed and anchor-counted, not interpreted)"),
    "SAFETY.md": (True, _ANCHORS + "catalogue, test_lab_fw_obligations, test_lab_fw_runtime, test_lab_ha_schedules; its "
                  "bytes are also copied into the in-memory overlay of the replay suite's drift control NC-RC-45 (hashed "
                  "and anchor-counted, not interpreted)"),
    "docs/FAILED_START_HEALTH.md": (True, _ANCHORS + "catalogue, test_lab_fw_durability"),
    "docs/SYSTEM_HEALTH_ARCHITECTURE.md": (True, _ANCHORS + "catalogue, test_lab_dst_rtc, test_lab_ha_schedules"),
    "docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md": (True, _ANCHORS + "catalogue, test_lab_ha_lifecycle"),
    "docs/architecture/fallback/design/S4_domains_decisions_final.md": (
        True, _ANCHORS + "KNOWN_RISKS, catalogue, corpus source_anchors, test_lab_fw_obligations, test_lab_fw_runtime, "
        "test_lab_ha_phantom, test_lab_property, test_lab_selftest_core (V0.1: its known-risk row and section checks "
        "are exactly-once anchors of the full table rows, the two blind-spot items and the section 2.10 heading)"),
    "docs/dev/advanced-config/stage0-safety-case.md": (True, _ANCHORS + "catalogue, test_lab_dst_rtc"),
    "docs/dev/advanced-config/write-surface.md": (True, _ANCHORS + "catalogue, corpus source_anchors, test_lab_fw_runtime"),
    "docs/dev/dump-to-grid-safety-fcp2.md": (
        True, _ANCHORS + "KNOWN_RISKS, catalogue, corpus source_anchors, test_lab_dst_rtc, test_lab_fw_obligations, "
        "test_lab_fw_runtime"),
    "docs/dev/schedule-manual-restore.md": (
        True, _ANCHORS + "KNOWN_RISKS, catalogue, corpus source_anchors, test_lab_ha_lifecycle, test_lab_selftest_core "
        "(V0.1: the record() refusal control no longer counts a word in it)"),
    "docs/incidents/2026-10-11-scheduled-free-power-start.md": (
        True, _ANCHORS + "catalogue, corpus source_anchors, test_lab_ha_lifecycle, test_lab_ha_schedules"),
    "docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md": (
        True, _ANCHORS + "catalogue, test_lab_ha_lifecycle, test_lab_ha_schedules"),
    "firmware/include/ecco_rtc_policy.h": (
        True, _ANCHORS + "catalogue, corpus source_anchors, test_lab_dst_rtc; the rtc tier executes the Python mirror "
        "registry/rtc_policy.py, never the header" + _D_B1),
    "frontend/ecco-energy-actions-card/README.md": (
        True, _ANCHORS + "catalogue, test_lab_fw_obligations, test_lab_ha_schedules"),
    "frontend/ecco-energy-actions-card/src/dumpState.ts": (True, _ANCHORS + "catalogue, test_lab_ha_phantom" + _D_B1),
    "frontend/ecco-energy-actions-card/src/recoveryPresentation.ts": (
        True, _ANCHORS + "catalogue, test_lab_ha_phantom" + _D_B1),
    "frontend/ecco-energy-actions-card/src/schedule.ts": (True, _ANCHORS + "catalogue, test_lab_ha_lifecycle" + _D_B1),
    "home-assistant/dashboards/ecco_pro.yaml": (True, _ANCHORS + "catalogue, test_lab_ha_phantom"),
    "home-assistant/packages/ecco_system_health.yaml": (
        True, _ANCHORS + "catalogue, test_lab_dst_rtc; no coupled world loads this package" + _D_B1),
    "home-assistant/tests/test_ecco_dump_to_grid_schedule_reliability.py": (
        True, _ANCHORS + "catalogue, test_lab_ha_lifecycle, test_lab_ha_schedules"),
    "home-assistant/tests/test_ecco_free_power_schedule_reliability.py": (
        True, _ANCHORS + "catalogue, test_lab_ha_lifecycle, test_lab_ha_schedules, test_lab_selftest_coupling"),
    "home-assistant/tests/test_ecco_schedule_manual_restore.py": (
        True, _ANCHORS + "catalogue, test_lab_ha_lifecycle, test_lab_ha_schedules, test_lab_selftest_coupling"),
    "home-assistant/tests/test_ecco_start_failure_alert.py": (False, _EXISTENCE),
    "home-assistant/tests/test_ecco_tou_target_soc_edit.py": (False, _EXISTENCE),
    "registry/health_reason_codes.yaml": (True, _ANCHORS + "catalogue, test_lab_dst_rtc" + _D_B1),
    "registry/system_health_checks.yaml": (True, _ANCHORS + "catalogue, test_lab_ha_phantom" + _D_B1),
    "registry/tests/check_fbb_esphome_source_facts.py": (
        True, _ANCHORS + "catalogue, corpus source_anchors, test_lab_property"),
    "registry/tests/test_cross_domain_start_gates.py": (False, _EXISTENCE),
    "registry/tests/test_dump_lockout_containment_sg02.py": (False, _EXISTENCE),
    "registry/tests/test_dump_safety_fcp2.py": (False, _EXISTENCE),
    "registry/tests/test_dump_to_grid_behaviour.py": (False, _EXISTENCE),
    "registry/tests/test_dump_v2_ownership_evidence.py": (False, _EXISTENCE),
    "registry/tests/test_durable_obligation_arbitration.py": (False, _EXISTENCE),
    "registry/tests/test_fbd1_liveness.py": (
        True, _ANCHORS + "test_lab_selftest_rtc (pinned from V0.1 on), and a coverage-matrix existence citation"),
    "registry/tests/test_free_power_dump_obligation_arbitration.py": (False, _EXISTENCE),
    "registry/tests/test_free_power_reboot_behaviour.py": (False, _EXISTENCE),
    "registry/tests/test_free_power_recovery_force_restore.py": (False, _EXISTENCE),
    "registry/tests/test_free_power_reg244_context_v4.py": (False, _EXISTENCE),
    "registry/tests/test_free_power_write_sequencing_hardening.py": (False, _EXISTENCE),
    "registry/tests/test_manual_tou_phase1_ownership_gates.py": (False, _EXISTENCE),
    "registry/tests/test_recovery_marker_state_machine.py": (False, _EXISTENCE),
    "registry/tests/test_rtc_policy.py": (True, _ANCHORS + "catalogue, test_lab_dst_rtc, test_lab_selftest_rtc"),
    "registry/tests/test_rtc_verification_lock_leak.py": (False, _EXISTENCE),
    "registry/tests/test_sg01_journal_phase1_2.py": (True, _ANCHORS + "catalogue, test_lab_fw_durability"),
    "registry/tests/test_sg01_phase5_hardening.py": (False, _EXISTENCE),
    "registry/tests/test_sg01_self_partial_phase3_4.py": (False, _EXISTENCE),
    "registry/tests/test_sg06_boot_durable_read_fail_closed.py": (False, _EXISTENCE),
    "registry/tests/test_write_surface_invariants.py": (False, _EXISTENCE),
}
# the behavioural files the replay of a document of each tier executes (hooked per-document replays; identical within
# a tier): every corpus document is judged against its own source_digests plus these (effective_pins)
_RTC_SOURCES = ("firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "registry/fallback_durable.py",
                "registry/fallback_profile.py", "registry/free_power_recovery_evidence.py", "registry/rtc_policy.py",
                "registry/tests/_dump_sim.py", "registry/tests/_dump_v2_evidence_model.py", "registry/tests/_fbb1_engine.py",
                "registry/tests/_fbb1_fbcap.py", "registry/tests/_fbb1_types.py", "registry/tests/_fbb1_xpile.py",
                "registry/tests/_fbb_harness.py", "registry/tests/_fbd1_harness.py", "registry/tests/_fbd1_scope.py",
                "registry/tests/_sg01_journal_model.py")
_FW_SOURCES = tuple(sorted(_RTC_SOURCES + ("firmware/include/ecco_durable_snapshot.h", "registry/free_power_self_partial.py",
                                           "registry/tests/_free_power_action_sim.py",
                                           "registry/tests/_sg01_recovery_harness.py")))
TIER_SOURCES: dict[str, tuple[str, ...]] = {
    "firmware": _FW_SOURCES,
    "coupled": tuple(sorted(_FW_SOURCES + ("home-assistant/packages/ecco_dump_to_grid_schedule.yaml",
                                           "home-assistant/packages/ecco_free_power_schedule.yaml",
                                           "home-assistant/packages/ecco_runtime_config.yaml",
                                           "home-assistant/packages/ecco_schedule_manual_restore.yaml",
                                           "home-assistant/tests/_ha_dump_sim.py",
                                           "home-assistant/tests/_ha_script_sim.py"))),
    "rtc": tuple(sorted(_RTC_SOURCES)),
}
DRIFT_CHECK = "gen_catalogue drift rule (tiered)"     # the common name prefix of the drift-rule checks (replay suite [5])
DRIFT_CHECK_STRICT = "gen_catalogue drift rule (STRICT)"     # the same prefix in strict mode (ECCO_LAB_STRICT_BASELINE=1)
TIER_PIN_CHECK = "B1 tier pins"                       # the common name prefix of the replay suite's [2] tier-pin checks
# the check finish() adds (as a FAIL) only when the run-time import guard finds an unclassified repository module
IMPORT_GUARD_CHECK = ("B1 import guard (end of suite): every repository module in this process's sys.modules outside "
                      "registry/tests/assurance_lab/ is listed in _lab_trace.BEHAVIOURAL")
DRIFT_LINE = "SOURCE DRIFT (non-behavioural): "
RERECORD_CMD = "python -B registry/tests/assurance_lab/rerecord_corpus.py"
REGENERATE_CMD = "python -B registry/tests/assurance_lab/gen_catalogue.py --write --parallel 1"


def drift_check(strict: bool) -> str:
    """The check-name prefix of the drift-rule checks: DRIFT_CHECK, or DRIFT_CHECK_STRICT in strict mode."""
    return DRIFT_CHECK_STRICT if strict else DRIFT_CHECK


def is_lab_path(path: str) -> bool:
    return isinstance(path, str) and path.startswith(LAB_PREFIX)


def source_tier(path: str) -> str:
    """'lab', 'behavioural', 'non-behavioural' or 'unclassified' (a non-lab path in neither table)."""
    if is_lab_path(path):
        return "lab"
    if path in BEHAVIOURAL:
        return "behavioural"
    if path in NON_BEHAVIOURAL:
        return "non-behavioural"
    return "unclassified"


def pinned_by_table() -> list[str]:
    """The non-lab paths the tier table requires in baseline.sources: every behavioural file and every non-behavioural
    file marked pinned (anchor-read)."""
    return sorted(set(BEHAVIOURAL) | {p for p, (pinned, _why) in NON_BEHAVIOURAL.items() if pinned})


def tier_table_problems(pinned_nonlab, exists=None) -> list[str]:
    """Problems of the tier table against the non-lab paths baseline.sources pins (gen_catalogue): every pinned non-lab
    path is classified, no path is in both tiers or is a lab path, the tier sets are subsets of the behavioural tier and
    cover exactly TIERS, every entry has a reason, a pinned flag matches baseline.sources, every listed file exists."""
    out = []
    pinned_nonlab = set(pinned_nonlab)
    both = sorted(set(BEHAVIOURAL) & set(NON_BEHAVIOURAL))
    if both:
        out.append(f"tier table: in both tiers: {both}")
    listed = sorted(set(BEHAVIOURAL) | set(NON_BEHAVIOURAL))
    lab = [p for p in listed if is_lab_path(p) or not _path_ok(p)]
    if lab:
        out.append(f"tier table: lab or malformed paths listed: {lab}")
    if exists is not None:
        gone = [p for p in listed if not exists(p)]
        if gone:
            out.append(f"tier table: listed files that do not exist: {gone}")
    for p, why in BEHAVIOURAL.items():
        if not isinstance(why, str) or not why.strip():
            out.append(f"tier table: behavioural {p} has no evidence text")
    for p, val in NON_BEHAVIOURAL.items():
        if not (isinstance(val, tuple) and len(val) == 2 and isinstance(val[0], bool) and isinstance(val[1], str)
                and val[1].strip()):
            out.append(f"tier table: non-behavioural {p} is not (pinned bool, evidence text)")
    if sorted(TIER_SOURCES) != sorted(TIERS):
        out.append(f"tier table: TIER_SOURCES tiers {sorted(TIER_SOURCES)} != {sorted(TIERS)}")
    for tier, srcs in sorted(TIER_SOURCES.items()):
        extra = sorted(set(srcs) - set(BEHAVIOURAL))
        if extra:
            out.append(f"tier table: TIER_SOURCES[{tier}] is not a subset of the behavioural tier: {extra}")
        if len(set(srcs)) != len(srcs) or list(srcs) != sorted(srcs):
            out.append(f"tier table: TIER_SOURCES[{tier}] is not a sorted list of distinct paths")
    unclassified = sorted(p for p in pinned_nonlab if source_tier(p) == "unclassified")
    if unclassified:
        out.append(f"pinned source(s) in neither tier of the B1 tier table (_lab_trace.BEHAVIOURAL / NON_BEHAVIOURAL): "
                   f"{unclassified}: classify them")
    unpinned = sorted(set(pinned_by_table()) - pinned_nonlab)
    if unpinned:
        out.append(f"tier table: behavioural or anchor-read files not pinned in baseline.sources: {unpinned}")
    declared = sorted(p for p, (pinned, _w) in NON_BEHAVIOURAL.items() if not pinned and p in pinned_nonlab)
    if declared:
        out.append(f"tier table: marked unpinned (existence only) but pinned by an anchor or a corpus document: {declared}")
    return out


def imported_repo_files(root=ROOT) -> list[str]:
    """The repository files (repo-relative POSIX paths) of every module imported into this process so far."""
    base = Path(root).resolve()
    out = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not isinstance(f, str):
            continue
        try:
            out.add(Path(f).resolve().relative_to(base).as_posix())
        except (ValueError, OSError):
            continue
    return sorted(out)


def unclassified_imports(root=ROOT) -> list[str]:
    """The repository modules in this process's sys.modules, outside the lab, that the behavioural tier does not list
    (the run-time import guard of the tier table). It sees what has been imported so far in THIS process, by anyone
    (a suite, a lab helper, a shared simulator, the generator), at module level or lazily; finish() runs it at the end
    of every suite. It does not see a data read (an open of a file) or an import made only in another process; those
    need the hook trace (trace_inputs.py)."""
    return [p for p in imported_repo_files(root) if not is_lab_path(p) and p not in BEHAVIOURAL]


def import_guard_failure(root=ROOT) -> tuple[str, str] | None:
    """(IMPORT_GUARD_CHECK, detail) when unclassified_imports() is not empty, else None."""
    stray = unclassified_imports(root)
    if not stray:
        return None
    return IMPORT_GUARD_CHECK, (f"unclassified repository import(s) {stray}: classify each in _lab_trace.BEHAVIOURAL "
                                "(the trace evidence; trace_inputs.py repeats the trace), then regenerate the catalogue "
                                "so baseline.sources pins it")


def tier_pins(tier: str) -> tuple:
    """The behavioural files a replay of `tier` executes (TIER_SOURCES; () for a tier the table does not know)."""
    return TIER_SOURCES.get(tier, ())


def effective_pins(doc: dict) -> list[str]:
    """The paths a corpus document is judged against: its own source_digests plus its tier's TIER_SOURCES."""
    return sorted(set(doc.get("source_digests") or {}) | set(tier_pins(doc.get("tier"))))


def affected_documents(path: str, docs: dict) -> list[str]:
    """The corpus document ids (of {id: doc}) whose effective pins include `path`."""
    return sorted(stem for stem, d in docs.items() if isinstance(d, dict) and path in effective_pins(d))


def compact_ids(ids) -> str:
    """Corpus ids grouped by family: 'FW-01-a,b,c; FW-02-a; HF-07-b' ('none' when empty)."""
    groups: dict[str, list] = {}
    for i in sorted(set(ids)):
        head, _sep, tail = i.rpartition("-")
        groups.setdefault(head, []).append(tail)
    return "; ".join(f"{h}-{','.join(t)}" for h, t in groups.items()) or "none"


def rerecord_procedure(docs, n_all: int) -> str:
    """The re-record procedure (doc section 11) for the corpus documents `docs` of a corpus of n_all documents."""
    if not docs:
        return (f"no corpus document pins it: run the lab (python -B registry/tests/assurance_lab/run_lab.py), then "
                f"regenerate the catalogue: {REGENERATE_CMD}")
    target = "--all" if len(docs) == n_all or len(docs) > 12 else " ".join(sorted(docs))
    subset = (f"; --all because {len(docs)} of the {n_all} documents pin it: a re-record leaves the documents whose "
              "digests and anchors did not change byte-identical" if target == "--all" and len(docs) != n_all else "")
    return (f"re-record procedure (doc section 11): {RERECORD_CMD} {target} (it refuses a changed trace_digest unless "
            f"--allow-digest-change <id> names it: explain each{subset}), then {REGENERATE_CMD}")


class TreeReader:
    """Repository files by repo-relative POSIX path, read once and cached, with an optional in-memory overlay
    {path: bytes, or None for an absent file}. The tiered drift rule and gen_catalogue's static build read every
    anchored or pinned file through one of these, so a negative control runs the real code path over an edited tree
    without writing anything."""

    def __init__(self, root=ROOT, overlay: dict | None = None) -> None:
        self.root = Path(root)
        self.overlay = dict(overlay or {})
        self._bytes: dict[str, bytes | None] = {}

    def read_bytes(self, path: str) -> bytes | None:
        if path in self.overlay:
            return self.overlay[path]
        if path not in self._bytes:
            f = _file(path, self.root)
            self._bytes[path] = f.read_bytes() if f.is_file() else None
        return self._bytes[path]

    def text(self, path: str) -> str | None:
        b = self.read_bytes(path)
        return None if b is None else b.decode("utf-8").replace("\r\n", "\n")

    def sha(self, path: str) -> str | None:
        b = self.read_bytes(path)
        return None if b is None else hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()

    def exists(self, path: str) -> bool:
        if path in self.overlay:
            return self.overlay[path] is not None
        return _file(path, self.root).is_file()


@dataclass(frozen=True)
class DriftItem:
    path: str
    tier: str                    # lab | behavioural | non-behavioural | unclassified
    now: str | None              # this tree's LF-normalised sha256 (None: the file is missing)
    recorded: str                # the catalogue baseline's sha256
    documents: tuple = ()        # corpus documents whose effective pins include the path
    stale_documents: tuple = ()  # those whose own source_digests record the path at a digest other than this tree's

    def sha_text(self) -> str:
        return f"sha256 {'missing' if self.now is None else self.now[:12]} != recorded {str(self.recorded)[:12]}"


@dataclass(frozen=True)
class DriftReport:
    """The tiered drift rule over one tree (see DRIFT_RULE): drift_lines() are the non-failing SOURCE DRIFT lines,
    failures() one (title, detail) per failing file, in path order."""
    items: tuple
    strict: bool
    n_documents: int

    def of_tier(self, tier: str) -> list:
        return [i for i in self.items if i.tier == tier]

    def drift_lines(self) -> list[str]:
        """One display line per changed non-behavioural file (' (file missing)' added for a missing one, which is ALSO
        a failure); none in strict mode, where every difference is a failure."""
        if self.strict:
            return []
        return [DRIFT_LINE + i.path + (" (file missing)" if i.now is None else "") for i in self.of_tier("non-behavioural")]

    def failures(self) -> list[tuple[str, str]]:
        out = []
        for i in self.items:
            docs = list(i.documents)
            pinned_by = f"{len(docs)} corpus document(s) replay it ({compact_ids(docs)})"
            if i.tier == "lab":
                stale = list(i.stale_documents)
                out.append((f"re-generate the catalogue: lab file changed: {i.path}",
                            f"{i.sha_text()}; " + (f"{len(stale)} corpus document(s) still record the old digest "
                                                   f"({compact_ids(stale)}): {rerecord_procedure(stale, self.n_documents)}"
                                                   if stale else f"regenerate the catalogue: {REGENERATE_CMD}")))
            elif i.tier == "behavioural":
                out.append((f"behavioural source changed: {i.path}",
                            f"{i.sha_text()}; {pinned_by}; {rerecord_procedure(docs, self.n_documents)}"))
            elif i.tier == "unclassified":
                out.append((f"unclassified pinned source changed: {i.path}",
                            f"{i.sha_text()}; it is in neither tier of the B1 tier table (_lab_trace.BEHAVIOURAL / "
                            f"NON_BEHAVIOURAL): classify it (judged behavioural until then); {pinned_by}; "
                            f"{rerecord_procedure(docs, self.n_documents)}"))
            elif i.now is None:       # a missing non-behavioural file fails too (its anchors cannot hold), in both modes
                out.append((f"pinned source missing: {i.path}",
                            f"{i.sha_text()}; a non-behavioural file pinned in the catalogue baseline; {pinned_by}; "
                            "restore the file, or remove it from the lab (tier table, anchors, corpus pins) and "
                            f"regenerate the catalogue: {REGENERATE_CMD}"))
            elif self.strict:
                out.append((f"non-behavioural source changed (STRICT, ECCO_LAB_STRICT_BASELINE=1): {i.path}",
                            f"{i.sha_text()}; the whole-baseline rule: {len(docs)} corpus document(s) pin it "
                            f"({compact_ids(docs)}); {rerecord_procedure(docs, self.n_documents)}"))
        return out

    def messages(self) -> list[str]:
        return [f"{title} - {detail}" for title, detail in self.failures()]


def drift_report(pinned: dict, docs: dict, *, sha_of, strict: bool = False) -> DriftReport:
    """The tiered drift rule: every baseline.sources path (`pinned`: {path: recorded sha256}) whose current digest
    (sha_of(path); None = missing) differs, with its tier and the corpus documents ({id: doc}) that replay it."""
    items = []
    for path, rec in sorted(pinned.items()):
        now = sha_of(path)
        if now == rec:
            continue
        affected = affected_documents(path, docs)
        stale = [s for s in affected if (docs[s].get("source_digests") or {}).get(path) not in (None, now)]
        items.append(DriftItem(path=path, tier=source_tier(path), now=now, recorded=rec, documents=tuple(affected),
                               stale_documents=tuple(stale)))
    return DriftReport(items=tuple(items), strict=bool(strict), n_documents=len(docs))


# ---------------------------------------------------------------------------------------------------------------------------
# ddmin
# ---------------------------------------------------------------------------------------------------------------------------
def ddmin(items, still_fails, *, max_tests: int = 10000) -> list:
    """Deterministic delta debugging: a 1-minimal, order-preserving sub-list of `items` for which still_fails() is True."""
    items = list(items)
    cache: dict[tuple, bool] = {}

    def fails(idx: list) -> bool:
        key = tuple(idx)
        if key not in cache:
            if len(cache) >= max_tests:
                raise LabTraceError(f"ddmin: more than {max_tests} predicate calls")
            r = still_fails([items[i] for i in idx])
            if not isinstance(r, bool):
                raise LabTraceError(f"ddmin: still_fails must return a bool, got {type(r).__name__}")
            cache[key] = r
        return cache[key]

    idx = list(range(len(items)))
    if not fails(idx):
        raise LabTraceError("ddmin: the full input does not fail")
    if fails([]):
        return []
    n = 2
    while len(idx) >= 2:
        n = min(n, len(idx))
        chunks = [idx[len(idx) * k // n: len(idx) * (k + 1) // n] for k in range(n)]
        nxt = next((c for c in chunks if fails(c)), None)
        if nxt is not None:
            idx, n = nxt, 2
            continue
        if n > 2:                                     # for n == 2 the complements are the chunks themselves
            comps = ([i for j, c in enumerate(chunks) if j != k for i in c] for k in range(n))
            nxt = next((c for c in comps if fails(c)), None)
            if nxt is not None:
                idx, n = nxt, n - 1
                continue
        if n >= len(idx):
            break
        n = min(2 * n, len(idx))
    return [items[i] for i in idx]


# ---------------------------------------------------------------------------------------------------------------------------
# suite output helpers (the V0.1 suite output contract: see the module docstring)
# ---------------------------------------------------------------------------------------------------------------------------
PIN_PREFIX = "finding-reproduces:"
SUMMARY_KEYS = ("suite", "pass", "fail", "finding", "finding_pins", "unsupported_ids", "unsupported_points", "blocked",
                "zoneinfo", "phase_sensitive", "runtime_s")
FAILED_LINE_MAX = 4000


def _one_line(text) -> str:
    return " ".join(str(text).split())


def _name_list(value, what: str) -> list[str]:
    """A list or tuple of str (check names / ids); anything else is a harness bug."""
    if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) for x in value):
        raise LabTraceError(f"finish: {what} must be a list or tuple of str, got {type(value).__name__}")
    return list(value)


def _sized(value, what: str) -> int:
    """len() of a collection; an int (a literal count), a str or another type is a harness bug."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset, dict)):
        raise LabTraceError(f"finish: {what} must be a list, tuple, set, frozenset or dict (its len() is the count), got "
                            f"{type(value).__name__}")
    return len(value)


def failed_line(names) -> str:
    """'FAILED: <n> check(s): <name1>; <name2>; ...' cut at a name boundary to at most FAILED_LINE_MAX characters."""
    names = [_one_line(x) for x in _name_list(names, "failures")]
    if not names:
        raise LabTraceError("failed_line: no failed check")
    head = f"FAILED: {len(names)} check(s): "
    full = head + "; ".join(names)
    if len(full) <= FAILED_LINE_MAX:
        return full
    shown = []
    for name in names:
        more = f" ... (+{len(names) - len(shown) - 1} more)"
        if len(head + "; ".join(shown + [name]) + more) > FAILED_LINE_MAX:
            break
        shown.append(name)
    if not shown:                     # even the first name is too long: cut it
        more = f" ... (+{len(names) - 1} more)"
        return head + names[0][:FAILED_LINE_MAX - len(head) - len(more)] + more
    return head + "; ".join(shown) + f" ... (+{len(names) - len(shown)} more)"


def finish(suite: str, *, passes, failures, finding, finding_pins, unsupported_points, blocked, phase_sensitive,
           runtime_s) -> dict:
    """Print a suite's final lines (FAILED line if any check failed, then LAB-SUMMARY) and return the summary record."""
    if not isinstance(suite, str) or not suite:
        raise LabTraceError("finish: suite must be a non-empty str")
    failures_in = failures            # the caller's object: the import guard appends its failure to it (see step 0)
    passes = _name_list(passes, "passes")
    failures = _name_list(failures, "failures")
    pins = _name_list(finding_pins, "finding_pins")
    points = _name_list(unsupported_points, "unsupported_points")
    bad_pass = [p for p in passes if p.startswith(PIN_PREFIX)]
    bad_pin = [p for p in pins if not p.startswith(PIN_PREFIX)]
    if bad_pass or bad_pin:
        raise LabTraceError(f"finish: finding pins in passes {bad_pass[:2]} / non-pin names in finding_pins {bad_pin[:2]}")
    bad_id = [u for u in points if not u or u != _one_line(u) or " " in u]
    if bad_id:
        raise LabTraceError(f"finish: unsupported ids must be non-empty and contain no whitespace: {bad_id[:3]}")
    if isinstance(runtime_s, bool) or not isinstance(runtime_s, (int, float)) or not math.isfinite(runtime_s) \
            or runtime_s < 0:
        raise LabTraceError(f"finish: runtime_s must be a finite number >= 0, got {runtime_s!r}")
    guard = import_guard_failure()       # B1: the run-time import guard at the end of every suite (FAIL only when hit)
    if guard is not None:
        if not isinstance(failures_in, list):
            raise LabTraceError(f"finish: the import guard failed ({guard[1]}) but `failures` is a "
                                f"{type(failures_in).__name__}, not the suite's FAILURES list its exit gate reads")
        print(f"  FAIL  {guard[0]} - {guard[1]}")
        failures_in.append(guard[0])
        failures.append(guard[0])
    rec = dict(zip(SUMMARY_KEYS, (
        suite, len(passes), len(failures), _sized(finding, "finding"), len(pins), len(set(points)), len(points),
        _sized(blocked, "blocked"), bool(C.zoneinfo_available()), _sized(phase_sensitive, "phase_sensitive"),
        round(float(runtime_s), 3))))
    if failures:
        print(failed_line(failures))
    print("LAB-SUMMARY " + json.dumps(rec), flush=True)
    return rec


def unsupported_line(uid: str, text: str) -> str:
    """'  UNSUPPORTED  <uid> <text>' on one line (one line per unsupported point)."""
    if not isinstance(uid, str) or not uid or uid != _one_line(uid) or " " in uid:
        raise LabTraceError(f"unsupported_line: the id must be a non-empty str without whitespace, got {uid!r}")
    body = _one_line(text)
    return f"  UNSUPPORTED  {uid}" + (f" {body}" if body else "")


def finding_line(finding_id: str, text: str) -> str:
    return f"  FINDING  {finding_id} " + " ".join(str(text).split())
