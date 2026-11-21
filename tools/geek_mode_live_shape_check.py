#!/usr/bin/env python3
"""Geek Mode live shape check: one read of the live Home Assistant states against the catalogue's code universe, offline.

    python tools/geek_mode_live_shape_check.py STATES.json
    python tools/geek_mode_live_shape_check.py STATES.json --write-shape OUT.json [--overwrite]

STATES.json is the file that block 3 of the U1 runbook (5.1) writes: a list of state objects, with their values, kept offline on the owner's
PC ({"data": [...]} and the repository fixtures' form {entity_id: {"state": ..., "attributes": ...}} are read as well). An object
`{"entity_id": ..., "absent": true}` is an entity the read looked for and Home Assistant did not have.

What it does:
  1. Converts the states IN MEMORY to the value-free shape listing that tools/geek_mode_coverage.py compares with (the format of
     frontend/ecco-mode-shell/catalogue/live-shape.intelligence.json): attribute names, value types, encoded sizes and the first-level keys of dict
     attributes. A value is read only to find its type and its size; it is never kept. Only entities that are declared by the code, or whose
     object id contains ecco_intel, are converted (the others are counted, nothing else).
  2. Compares that listing with the code universe by calling geek_mode_coverage.compare_live (imported, not copied).
  3. Prints counts and names (never a value): PRESENT_LIVE, NOT_PRESENT_LIVE (conditional / unexplained), UNDECLARED, NOT_CHECKED_LIVE.

Exit codes: 0 the shape matches (nothing UNDECLARED, no declared entity missing, every absent attribute row is conditional);
1 it does not (the lines say which); 2 bad input, bad usage or a refused write.

Writes nothing unless --write-shape is given; then only the value-free listing, to a path outside this repository's checkout, never over an existing
file without --overwrite. Offline: no network, no Home Assistant, standard library plus PyYAML (through geek_mode_coverage).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import geek_mode_coverage as G  # noqa: E402  (the comparison and the universe are that tool's: nothing of them is copied here)

SCOPE_NEEDLE = "ecco_intel"                       # the object-id filter of the 14 Nov listing
IDENT_RE = re.compile(r"[A-Za-z0-9_-]{1,80}")     # an attribute name or a first-level key that may be printed or listed as it is
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CAP = 50                                          # lines printed per kind of finding
SHAPE_WHAT = ("A read-only listing of the SHAPE of the ecco_intel entities in a running Home Assistant: entity ids, attribute names, value types and encoded sizes, "
              "the first-level keys of dict attributes. It holds no state value and no attribute value.")
SHAPE_USED_BY = "tools/geek_mode_coverage.py --shape (the live comparison of the ledger)"
SHAPE_REMOVED = [
    "every state value and attribute value (only names, types and sizes are kept)",
    "last_changed, last_updated, context and every other state field",
    "the entities that are neither declared by the code nor named ecco_intel (counted, not listed)",
]


class InputError(Exception):
    """The states file cannot be used. The message never holds anything read from the file."""


# ---------------------------------------------------------------------------------------------------------------------
# reading the states
# ---------------------------------------------------------------------------------------------------------------------

def read_json(path: Path):
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read the states file: {exc.strerror or type(exc).__name__}") from None
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise InputError("the states file is UTF-16 (a redirect did that): write it as UTF-8, as block 3 does")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("the states file is not UTF-8 text") from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise InputError(f"the states file is not JSON ({type(exc).__name__}: {getattr(exc, 'msg', 'invalid')} at line {getattr(exc, 'lineno', '?')})") from None


def normalise(obj) -> list[dict]:
    """The list of state objects, from a list, a {"data": list} envelope or a {entity_id: state object} mapping."""
    if isinstance(obj, dict) and "data" in obj:
        obj = obj["data"]
    if isinstance(obj, dict):
        entries = []
        for eid, st in obj.items():
            if not isinstance(st, dict):
                raise InputError("an object form of the states file holds a value that is not a state object")
            entries.append({**st, "entity_id": eid})
        obj = entries
    if not isinstance(obj, list):
        raise InputError("the states file is neither a list of state objects, nor a {\"data\": [...]} envelope, nor an {entity_id: state} mapping")
    if not obj:
        raise InputError("the states file holds no state object")
    seen: set[str] = set()
    for i, e in enumerate(obj):
        if not isinstance(e, dict) or not isinstance(e.get("entity_id"), str) or not G.ENTITY_ID_RE.match(e["entity_id"]):
            raise InputError(f"object {i + 1} of the states file is not a state object with an entity id")
        if e["entity_id"] in seen:
            raise InputError(f"two objects of the states file carry the same entity id (object {i + 1})")
        seen.add(e["entity_id"])
        if e.get("absent") is True:
            continue
        if not isinstance(e.get("state"), str):
            raise InputError(f"object {i + 1} of the states file has no state text (a state is always a text)")
        if not isinstance(e.get("attributes", {}), dict):
            raise InputError(f"object {i + 1} of the states file has attributes that are not an object")
    return obj


# ---------------------------------------------------------------------------------------------------------------------
# the value-free conversion (a value is read for its type and its size only)
# ---------------------------------------------------------------------------------------------------------------------

def type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return f"list[{len(v)}]"
    if isinstance(v, dict):
        return f"dict[{len(v)}]"
    return type(v).__name__


def encoded_size(v) -> int:
    return len(json.dumps(v, ensure_ascii=False).encode("utf-8"))


def safe_name(name, unusual: list) -> str:
    """An attribute name or key that is a plain identifier is kept; anything else is replaced by a numbered placeholder (a name can carry a value)."""
    if isinstance(name, str) and IDENT_RE.fullmatch(name):
        return name
    unusual.append(1)
    return f"<unusual-name-{len(unusual)}>"


def convert_entity(entry: dict) -> dict:
    unusual: list = []
    attrs = entry.get("attributes") or {}
    row_attrs = {}
    for name in sorted(attrs, key=str):
        v = attrs[name]
        keys = None
        if isinstance(v, dict):
            keys = sorted(safe_name(k, unusual) for k in v)
        row_attrs[safe_name(name, unusual)] = {"type": type_name(v), "bytes": encoded_size(v), "top_keys": keys}
    return {"entity_id": entry["entity_id"], "state_type": "str", "state_len": len(entry["state"]), "attributes": row_attrs}


def capture_date(entries: list) -> str:
    """The newest date among the timestamp fields of the states (only a text of the form YYYY-MM-DD is kept), or "unknown"."""
    best = ""
    for e in entries:
        for k in ("last_updated", "last_reported", "last_changed"):
            v = e.get(k)
            m = DATE_RE.match(v) if isinstance(v, str) else None
            if m and m.group(0) > best:
                best = m.group(0)
    return best or "unknown"


def in_scope(entity_id: str, declared: set) -> bool:
    return entity_id in declared or SCOPE_NEEDLE in entity_id.split(".", 1)[1]


def build_shape(entries: list, declared: set) -> tuple[dict, int, int]:
    """(the value-free listing, the number of states left out of it, the number of in-scope entities that read unavailable or unknown)."""
    rows, ignored, unavailable = [], 0, 0
    for e in entries:
        if e.get("absent") is True:
            continue
        if not in_scope(e["entity_id"], declared):
            ignored += 1
            continue
        if e["state"] in ("unavailable", "unknown"):
            unavailable += 1
        rows.append(convert_entity(e))
    rows.sort(key=lambda r: r["entity_id"])
    shape = {
        "_provenance": {
            "what": SHAPE_WHAT,
            "captured": capture_date(entries),
            "object_id_contains": SCOPE_NEEDLE,
            "removed_from_the_raw_listing": list(SHAPE_REMOVED),
            "used_by": SHAPE_USED_BY,
        },
        "ecco_intel": rows,
    }
    return shape, ignored, unavailable


# ---------------------------------------------------------------------------------------------------------------------
# the comparison and the verdict
# ---------------------------------------------------------------------------------------------------------------------

def assess(universe, shape: dict, absent_ids: set) -> dict:
    live = G.compare_live(universe, shape)
    missing = sorted({r["entity_id"] for r in live["not_present_live"] if r["path"] is None})
    # a declared entity outside the capture's name filter is NOT_CHECKED_LIVE for compare_live; when the read looked for it and Home Assistant did not have it, it is missing
    not_checked = [eid for eid in live["not_checked_live"] if eid not in absent_ids]
    missing += sorted(eid for eid in live["not_checked_live"] if eid in absent_ids)
    absent_rows = [r for r in live["not_present_live"] if r["path"] is not None]
    conditional = [r for r in absent_rows if r["why"].startswith("conditional:")]
    unexplained = [r for r in absent_rows if not r["why"].startswith("conditional:")]
    undeclared_entities = sorted(r["entity_id"] for r in live["undeclared"] if r["path"] is None)
    undeclared_attrs = sorted((r["entity_id"], r["path"]) for r in live["undeclared"] if r["path"] is not None)
    present_attrs = sum(1 for v in live["attributes"].values() if v["live"] == "PRESENT_LIVE")
    return {
        "declared_entities": len(live["entities"]),
        "present_entities": sum(1 for v in live["entities"].values() if v == "PRESENT_LIVE"),
        "present_attrs": present_attrs,
        "missing": missing,
        "conditional": conditional,
        "unexplained": unexplained,
        "undeclared_entities": undeclared_entities,
        "undeclared_attrs": undeclared_attrs,
        "not_checked": sorted(not_checked),
    }


def exit_code(rep: dict) -> int:
    """0 only when nothing is UNDECLARED, no declared entity is missing and no absent attribute row is unexplained."""
    return 1 if (rep["undeclared_entities"] or rep["undeclared_attrs"] or rep["missing"] or rep["unexplained"]) else 0


def render(rep: dict, name: str, n_objects: int, n_absent: int, date: str, ignored: int, unavailable: int, universe) -> list[str]:
    declared_rows = sum(len(e.attrs) for e in universe.entities)
    lines = [
        "ECCO Geek Mode live shape check: offline, one states file, names and counts only (never a value)",
        f"input             : {name} ({n_objects} objects, {n_absent} marked absent); newest timestamp in it: {date}",
        f"scope             : {n_objects - n_absent - ignored} states converted (declared by the code or named {SCOPE_NEEDLE}), {ignored} others ignored (counted only)",
        f"code universe     : {rep['declared_entities']} declared entities, {declared_rows} declared attribute rows (this checkout)",
        f"PRESENT_LIVE      : {rep['present_entities']} of {rep['declared_entities']} declared entities; {rep['present_attrs']} attribute rows",
        f"NOT_PRESENT_LIVE  : {len(rep['missing'])} declared entities missing; {len(rep['conditional']) + len(rep['unexplained'])} attribute rows absent "
        f"({len(rep['conditional'])} conditional, {len(rep['unexplained'])} unexplained)",
        f"UNDECLARED        : {len(rep['undeclared_entities'])} entities, {len(rep['undeclared_attrs'])} attributes",
        f"NOT_CHECKED_LIVE  : {len(rep['not_checked'])} declared entities (not in the capture and not marked absent; a capture made with block 3 has none)",
    ]
    if unavailable:
        lines.append(f"NOTE              : {unavailable} converted entities read unavailable or unknown; their attribute lists may be partial, so read an absence on them with care")

    def block(title: str, items: list[str]) -> None:
        for s in items[:CAP]:
            lines.append(f"  {title}: {s}")
        if len(items) > CAP:
            lines.append(f"  {title}: ... and {len(items) - CAP} more")

    block("MISSING entity (declared, not in Home Assistant)", rep["missing"])
    block("UNEXPLAINED absence (declared attribute, not on the live entity)", [f"{r['entity_id']} {r['path']}" for r in rep["unexplained"]])
    block("UNDECLARED entity (present live, declared by no code)", rep["undeclared_entities"])
    block("UNDECLARED attribute (present live, declared by no code)", [f"{e} {p}" for e, p in rep["undeclared_attrs"]])
    block("NOT CHECKED entity", rep["not_checked"])
    if any(p.startswith("self_test.") for _e, p in rep["undeclared_attrs"]):
        lines.append("  HINT: the keys of a recorded self_test are the self-test's check codes; the code universe declares the attribute, not those keys, and the 14 Nov "
                     "listing had it empty. Say so to the owner: it is a gap in the catalogue's nested declarations (Production is unaffected), still a difference")
    if exit_code(rep) == 0:
        lines.append("RESULT: MATCH (exit 0): every declared entity is present, nothing is undeclared and every absent attribute row is conditional")
    else:
        lines.append("RESULT: DIFFERENT (exit 1): the catalogue is out of date for this host, or the capture is not a healthy one; the lines above say which. Ask the owner")
    return lines


# ---------------------------------------------------------------------------------------------------------------------
# writing the listing (only on request, only value-free, never inside this checkout, never over an existing file by accident)
# ---------------------------------------------------------------------------------------------------------------------

def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return False
    return True


def write_refusal(path: Path, overwrite: bool) -> str | None:
    if inside_repo(path):
        return "refused: the listing of a real host is written outside this repository's checkout (the evidence folder), never inside a tracked folder"
    if path.is_dir():
        return "refused: the output path is a folder"
    if not path.parent.is_dir():
        return "refused: the output's folder does not exist"
    if path.exists() and not overwrite:
        return "refused: the output file exists (add --overwrite to replace it)"
    return None


def write_listing(path: Path, shape: dict, overwrite: bool) -> None:
    data = (json.dumps(shape, indent=1) + "\n").encode("ascii")
    with open(path, "wb" if overwrite else "xb") as fh:
        fh.write(data)


def _universe():
    return G.build_universe(REPO)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("states", type=Path, help="the states file that block 3 of the runbook wrote (states-before.json)")
    ap.add_argument("--write-shape", type=Path, default=None, metavar="PATH", help="also write the value-free listing to PATH (outside the checkout)")
    ap.add_argument("--overwrite", action="store_true", help="with --write-shape: replace an existing file")
    args = ap.parse_args(argv)
    if args.overwrite and args.write_shape is None:
        print("ERROR: --overwrite needs --write-shape", file=sys.stderr)
        return 2
    if args.write_shape is not None:
        why = write_refusal(args.write_shape, args.overwrite)
        if why:
            print(f"ERROR: {why}", file=sys.stderr)
            return 2
    try:
        entries = normalise(read_json(args.states))
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        universe = _universe()
    except (G.UniverseError, OSError, ValueError, SyntaxError, KeyError) as exc:
        print(f"ERROR: the code universe of this checkout could not be built ({type(exc).__name__})", file=sys.stderr)
        return 2
    declared = {e.entity_id for e in universe.entities}
    shape, ignored, unavailable = build_shape(entries, declared)
    absent_ids = {e["entity_id"] for e in entries if e.get("absent") is True}
    rep = assess(universe, shape, absent_ids)
    for line in render(rep, args.states.name, len(entries), len(absent_ids), shape["_provenance"]["captured"], ignored, unavailable, universe):
        print(line)
    if args.write_shape is not None:
        try:
            write_listing(args.write_shape, shape, args.overwrite)
        except OSError as exc:
            print(f"ERROR: the listing was not written ({exc.strerror or type(exc).__name__})", file=sys.stderr)
            return 2
        print(f"wrote the value-free listing: {args.write_shape.name} ({len(shape['ecco_intel'])} entities)")
    return exit_code(rep)


if __name__ == "__main__":
    sys.exit(main())
