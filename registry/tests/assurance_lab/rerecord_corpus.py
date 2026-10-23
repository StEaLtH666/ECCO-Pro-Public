#!/usr/bin/env python3
"""Re-record replay corpus documents of the offline assurance lab after a pinned source changed (test-only: no network, no
Home Assistant, no hardware). This file is a command-line tool, not a suite: it is not named test_*.py, so neither
tools/run_offline_tests.py nor the exit-code meta-check collects it. It imports the lab helpers, which need the packages
pinned in requirements-ci.txt (PyYAML, Jinja2), as the suites do.

    python -B registry/tests/assurance_lab/rerecord_corpus.py --check                 # which documents are stale
    python -B registry/tests/assurance_lab/rerecord_corpus.py --check FW-01-a HF-04-b
    python -B registry/tests/assurance_lab/rerecord_corpus.py --all                   # re-record every document
    python -B registry/tests/assurance_lab/rerecord_corpus.py FW-01-a FW-01-b         # re-record these documents
    python -B registry/tests/assurance_lab/rerecord_corpus.py FW-06-a --allow-digest-change FW-06-a
    python -B registry/tests/assurance_lab/rerecord_corpus.py --all --pin-tier-sources  # B1 tier pins into the files

WHAT IT DOES
  Every corpus document pins the files it was recorded from (source_digests: LF-normalised sha256, the
  _lab_trace.source_digest rule) and its anchors' lines (source_anchors[].line_at_record). After a pinned file changes,
  test_lab_replay_corpus judges the document on its expectations only (SOURCE DRIFT) until it is re-recorded.
  RE-RECORD (default; --all or one or more corpus ids): each selected document is loaded strictly (_lab_trace.load_doc)
  and re-recorded FROM ITSELF with _lab_trace.record: its source_digests (its own keys plus every anchor path) and anchor
  lines are recomputed from this tree, it is replayed twice (both digests must agree and every expectation must hold,
  else that document fails) and trace_digest is set from the replay. Nothing else in the document changes. The firmware,
  coupled and rtc replay tiers are registered by importing _lab_fw, _lab_ha and _lab_rtc (as run_lab.py --replay and
  test_lab_replay_corpus do).
  --pin-tier-sources (B1 tier pins written into the documents): record also pins every file of the document tier's
  _lab_trace.TIER_SOURCES in its source_digests (record(..., tier_pins=True)). Every committed document carries its tier
  pins (gen_catalogue and test_lab_replay_corpus [2] fail a document that does not); a re-record without this option
  keeps the pins a document already has, so the option is needed only for a NEW document or after TIER_SOURCES grows.
  The suites that compare a corpus file's source_digests keys with their drafts (test_lab_fw_runtime, test_lab_fw_guards,
  test_lab_dst_rtc) expect the tier pins (draft keys plus anchor paths plus _lab_trace.tier_pins(tier)).
  REFUSAL: when a document's trace_digest would change, the tool prints old -> new and refuses, unless that id is passed
  in --allow-digest-change (then it prints 'ALLOWED old -> new'). An unchanged trace_digest means the re-record only
  updated provenance (digests / anchor lines). A changed one changes what the document pins; every allowed change must be
  explained by its mechanism.
  ALL OR NOTHING: every selected document is re-recorded in memory first; a document that fails (exception, expectation,
  non-determinism) or is refused means NOTHING is written (exit 1). Otherwise each changed document is written in the
  canonical _lab_trace.dumps_doc form (sorted keys, indent 2, ASCII, LF), through a temporary file in the corpus
  directory and os.replace; an unchanged document (compared after CRLF -> LF normalisation) is not rewritten.
  --check (no writing, no replay): lists the documents whose recorded source_digests differ from this tree (a missing
  pinned file counts as stale) and those whose anchors are no longer found exactly once at their recorded lines.
  Exit 1 when any is stale.
  Writes only <corpus>/<id>.json files that already exist (and their transient .tmp siblings); never anything else.

EXIT  0 ok (re-recorded, or nothing stale with --check); 1 a document failed, was refused or (--check) is stale;
      2 usage error.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # before any lab helper is imported

import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # repository root
CORPUS_DIR = HERE / "corpus"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
for p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import _lab_trace as T  # noqa: E402


def register_tiers() -> None:
    """Register the lab's replay tiers (importing the tier modules registers them)."""
    import _lab_fw  # noqa: F401   registers the replay tier 'firmware'
    import _lab_ha  # noqa: F401   registers the replay tier 'coupled'
    import _lab_rtc  # noqa: F401  registers the replay tier 'rtc'


def id_problem(doc_id: str) -> str | None:
    """Why `doc_id` does not name an existing corpus document (a path, a missing document), or None."""
    if not ID_RE.match(doc_id) or doc_id.endswith(".json"):
        return f"not a corpus document id: {doc_id!r} (use the id, e.g. FW-01-a)"
    f = CORPUS_DIR / f"{doc_id}.json"
    if not f.is_file() or f.resolve().parent != CORPUS_DIR.resolve():
        return f"no corpus document {doc_id!r} in {CORPUS_DIR.relative_to(ROOT).as_posix()}"
    return None


def corpus_path(doc_id: str) -> Path:
    """<corpus>/<id>.json for an existing document (main() has validated the id with id_problem)."""
    why = id_problem(doc_id)
    if why:
        raise ValueError(why)
    return CORPUS_DIR / f"{doc_id}.json"


def all_ids() -> list[str]:
    return [f.stem for f in sorted(CORPUS_DIR.glob("*.json"))]


def stale_report(doc: dict) -> tuple[list[str], list[str]]:
    """(source paths whose recorded digest differs from this tree or that are missing, anchor problems)."""
    paths = []
    for path, sha in sorted(doc["source_digests"].items()):
        f = ROOT / path
        if not f.is_file() or T.source_digest(path) != sha:
            paths.append(path)
    anchors = []
    for a in doc["source_anchors"]:
        if not (ROOT / a["path"]).is_file():
            anchors.append(f"{a['path']}: file missing")
            continue
        n, line = T.anchor_count(a["path"], a["text"])
        if n != 1 or line != a["line_at_record"]:
            anchors.append(f"{a['path']}: found {n} time(s), line {line} (recorded {a['line_at_record']})")
    return paths, anchors


def check_main(ids: list[str]) -> int:
    n_stale = 0
    for doc_id in ids:
        doc = T.load_doc(corpus_path(doc_id))
        paths, anchors = stale_report(doc)
        if paths or anchors:
            n_stale += 1
            print(f"  STALE  {doc_id}: " + "; ".join(
                ([f"source_digests differ for {', '.join(paths)}"] if paths else [])
                + ([f"anchors {'; '.join(anchors)}"] if anchors else [])))
    print(f"checked {len(ids)} document(s): {n_stale} stale" + (" (re-record them with this tool)" if n_stale else ""))
    return 1 if n_stale else 0


def rerecord_main(ids: list[str], allowed: set[str], tier_pins: bool = False) -> int:
    register_tiers()
    planned: list[tuple[Path, str]] = []
    bad = 0
    for doc_id in ids:
        f = corpus_path(doc_id)
        try:
            doc = T.load_doc(f)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):     # record() replays; the engine prints nothing, kept quiet anyway
                new = T.record(doc, tier_pins=tier_pins)
            new_text = T.dumps_doc(new)
        except Exception as exc:   # a failure of this document: reported, nothing is written (fail loud, never a pass)
            print(f"  FAILED   {doc_id}: {type(exc).__name__}: {str(exc)[:300]}")
            bad += 1
            continue
        old_digest, new_digest = doc["trace_digest"], new["trace_digest"]
        changed_src = sorted(p for p in set(doc["source_digests"]) | set(new["source_digests"])
                             if doc["source_digests"].get(p) != new["source_digests"].get(p))
        moved = [f"{a['path']} {a['line_at_record']}->{b['line_at_record']}"
                 for a, b in zip(doc["source_anchors"], new["source_anchors"]) if a["line_at_record"] != b["line_at_record"]]
        what = "; ".join(([f"source_digests changed for {', '.join(changed_src)}"] if changed_src else [])
                         + ([f"anchor lines moved: {', '.join(moved)}"] if moved else []))
        if new_digest != old_digest:
            if doc_id not in allowed:
                print(f"  REFUSED  {doc_id}: trace_digest would change {old_digest} -> {new_digest} (pass "
                      f"--allow-digest-change {doc_id} if the change is intended and explained)")
                bad += 1
                continue
            print(f"  ALLOWED  {doc_id}: trace_digest {old_digest} -> {new_digest}" + (f"; {what}" if what else ""))
        if new_text.encode("ascii") == f.read_bytes().replace(b"\r\n", b"\n"):
            print(f"  same     {doc_id}: unchanged")
            continue
        if new_digest == old_digest:
            print(f"  update   {doc_id}: trace_digest unchanged" + (f"; {what}" if what else ""))
        planned.append((f, new_text))
    if bad:
        print(f"NOTHING WRITTEN: {bad} of {len(ids)} document(s) failed or were refused")
        return 1
    for f, text in planned:
        target = f.resolve()
        if target.parent != CORPUS_DIR.resolve() or not target.is_file():
            raise SystemExit(f"refusing to write outside the corpus directory: {target}")
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(text.encode("ascii"))
        os.replace(tmp, target)
    print(f"re-recorded {len(ids)} document(s): {len(planned)} written, {len(ids) - len(planned)} unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rerecord_corpus.py", description="Re-record assurance lab corpus documents from "
                                 "themselves after a pinned source changed (see the module docstring).")
    ap.add_argument("ids", nargs="*", metavar="ID", help="corpus document ids (e.g. FW-01-a)")
    ap.add_argument("--all", action="store_true", help="every corpus document")
    ap.add_argument("--allow-digest-change", nargs="+", default=[], metavar="ID",
                    help="ids whose trace_digest may change (printed old -> new)")
    ap.add_argument("--check", action="store_true", help="only report stale documents (no replay, nothing written)")
    ap.add_argument("--pin-tier-sources", action="store_true",
                    help="also pin the document tier's _lab_trace.TIER_SOURCES in source_digests (see the docstring)")
    args = ap.parse_args(argv)
    if args.all and args.ids:
        ap.error("give --all or document ids, not both")
    if not args.all and not args.ids and not args.check:
        ap.error("give --all, one or more document ids, or --check")
    if args.check and (args.allow_digest_change or args.pin_tier_sources):
        ap.error("--allow-digest-change and --pin-tier-sources apply to a re-record, not to --check")
    ids = all_ids() if (args.all or not args.ids) else list(dict.fromkeys(args.ids))
    for doc_id in ids + args.allow_digest_change:
        why = id_problem(doc_id)
        if why:
            ap.error(why)
    stray = sorted(set(args.allow_digest_change) - set(ids))
    if stray:
        ap.error(f"--allow-digest-change names document(s) that are not selected: {', '.join(stray)}")
    if args.check:
        return check_main(ids)
    return rerecord_main(ids, set(args.allow_digest_change), tier_pins=args.pin_tier_sources)


if __name__ == "__main__":
    sys.exit(main())
