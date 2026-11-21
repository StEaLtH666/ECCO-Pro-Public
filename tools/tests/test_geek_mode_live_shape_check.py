#!/usr/bin/env python3
"""Suite of the Geek Mode live shape check (tools/geek_mode_live_shape_check.py): the offline tool that compares ONE read of the live
Home Assistant states (the file block 3 of the U1 runbook writes) with the catalogue's code universe, without ever printing a value.

  [1] the tool's source: only the standard library, PyYAML and the repository's own tools are imported; no network or process module; the
      comparison is geek_mode_coverage.compare_live (imported and called, never a second copy); ASCII only
  [2] the verdicts (in-process, on states built from the repository's own fixtures): the healthy set exits 0; an undeclared attribute,
      an undeclared ecco_intel entity, a missing source entity, a missing non-conditional attribute and an undeclared nested key each
      exit 1 and are named; a null parent and an unrelated control entity do not; a helper outside the name filter is NOT_CHECKED_LIVE
      unless the read marked it absent
  [3] no value anywhere: a planted fake value, a planted entity-id-like string, a number, a state text, an unusual attribute name and an
      unusual dict key never appear in stdout, stderr or the written listing; the listing holds only names, types, sizes, dates and
      fixed texts (a walk over every string of it); the hostile fixture goes through the same way
  [4] the input: a bare list, a {"data": ...} envelope, the fixtures' mapping and a UTF-8 file with a byte order mark read the same;
      garbage, an empty list, a scalar, a duplicate, a state that is not a text and UTF-16 exit 2 and say nothing of what the file held
  [5] --write-shape: only the value-free listing, in the committed listing's own format; refuses an existing file without --overwrite,
      a folder that is missing and anything inside this repository's checkout (a tracked folder), by the real command line and by
      the function; --overwrite alone is a usage error
  [6] the real command line (python -I -B -X utf8): exit codes, stdout, stderr; the committed 14 Nov listing converted back into
      states gives the verdict geek_mode_coverage itself gives on that listing (16 present, 42 conditional, 1 not checked, exit 0)
  [7] mutants (all in memory): the exit-code logic (six), the conditional rule (two), the undeclared and missing checks (five), the value-free
      conversion leaking a value, a state, a name or a key (four), the scope (two), the overwrite and checkout guards (three), the
      capture date, the type order, the input rules (six) and the notes (three), and four of the static rules: each is killed by a
      running check

Usage: python tools/tests/test_geek_mode_live_shape_check.py
The environment variable ECCO_LIVE_SHAPE_TOOL names another tool (this is how the suite is shown to fail on a stub that always exits 0).

Test-only, no network. Scratch files live in the system temp directory and are removed. Reads repository files; writes nothing else.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import geek_mode_coverage as G  # noqa: E402

TOOL = Path(os.environ.get("ECCO_LIVE_SHAPE_TOOL") or ROOT / "tools" / "geek_mode_live_shape_check.py")
PY = [sys.executable, "-I", "-B", "-X", "utf8"]
FAILURES: list[str] = []
PASSED = [0]


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED[0] += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------------------------
# what the suite is made of (samples that would trip a scanner are assembled here, so this file holds none)
# ---------------------------------------------------------------------------------------------------------------------------------
DOM = "sen" + "sor"
NEEDLE = "ecco" + "_intel"
FAKE = "planted" + "-value-" + "4f2a9c1e"                  # a recognisable fake value
FAKE_ID = DOM + ".planted" + "_value_entity"                # an entity-id-like string used as a VALUE
FAKE_NUM = 918273645
FAKE_STATE = "planted" + "-state-" + "77b1d0"
FAKE_NAME = "planted name " + "with spaces/1b2"             # an attribute name that is not an identifier
FAKE_KEY = "planted key." + "3e9"                           # a first-level dict key that is not an identifier
FAKE_CTRL = "swi" + "tch.planted" + "_control_zz"           # an unrelated entity (never converted, never printed)
FAKE_BAD_ID = "PLANTED bad " + "id 5c1"                     # not an entity id at all
TOKENS = [FAKE, FAKE_ID, str(FAKE_NUM), FAKE_STATE, FAKE_NAME, FAKE_KEY, FAKE_CTRL, "planted_control_zz", FAKE_BAD_ID, "planted-garbage-3f9"]
UNDECLARED_ENTITY = f"{DOM}.{NEEDLE}_zz_extra"
CONTROL_ENTITY = "input_" + "boolean.some_unrelated" + "_control"
IPV4 = re.compile(r"(?<![0-9])(?<![0-9]\.)(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")
TOKEN_SHAPE = re.compile(r"-----BEGIN [A-Z ]*KEY-----|\bghp_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")
ENTITY_ID_LITERAL = re.compile(r"(?<![A-Za-z0-9_.\\/-])(?:sensor|binary_sensor|switch|input_boolean|input_number|automation|light)\.[a-z0-9]+_[a-z0-9_]+")
USER_PATH = re.compile(r"[A-Za-z]:\\" + "Us" + r"ers\\|/" + "Us" + r"ers/|/ho" + r"me/[a-z]")
TYPE_RE = re.compile(r"^(null|bool|int|float|str|list\[\d+\]|dict\[\d+\])$")
NAME_RE = re.compile(r"^([A-Za-z0-9_-]{1,80}|<unusual-name-\d+>)$")
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
ALLOWED_IMPORTS = STDLIB | {"yaml", "geek_mode_coverage"}
FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "ftplib", "smtplib", "ssl", "subprocess", "requests", "asyncio", "multiprocessing", "webbrowser"}

U = G.build_universe()
BY_KIND = {}
for _e in U.entities:
    BY_KIND.setdefault(_e.kind, []).append(_e)
STATUS = BY_KIND["status"][0].entity_id
RESERVE = BY_KIND["reserve_helper"][0].entity_id
FX_DIR = ROOT / G.FIXTURE_DIR_REL
COMMITTED_SHAPE_PATH = ROOT / G.SHAPE_REL
COMMITTED_SHAPE = json.loads(COMMITTED_SHAPE_PATH.read_bytes())


def fixture(name: str) -> dict:
    return json.loads((FX_DIR / f"intelligence.states.{name}.json").read_bytes())


def live_like(name: str = "healthy") -> list:
    """A states list as block 3 writes it, from a repository fixture. The fixtures' status entity carries a recorded self_test (a dict of check codes);
    the live listing of 14 Nov had it empty (null), so it is emptied here and the populated form is tested on its own."""
    out = []
    for k, v in fixture(name).items():
        st = copy.deepcopy(v)
        if k == STATUS and isinstance(st["attributes"].get("self_test"), dict):
            st["attributes"]["self_test"] = None
        out.append({"entity_id": k, **st})
    return out


def entity(states: list, eid: str) -> dict:
    return next(s for s in states if s["entity_id"] == eid)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------------
# running the tool: in memory (the tool's source executed as a module; the universe built once) and as a command line
# ---------------------------------------------------------------------------------------------------------------------------------
def load_module(src: str, repo: Path | None = None):
    mod = types.ModuleType("live_shape_under_test")
    mod.__file__ = str(TOOL)
    exec(compile(src, str(TOOL), "exec"), mod.__dict__)
    mod._universe = lambda: U
    if repo is not None:
        mod.REPO = repo
    return mod


def run_mod(mod, args: list) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = mod.main([str(a) for a in args])
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
    return rc, out.getvalue(), err.getvalue()


def run_cli(args: list, cwd: Path | None = None) -> tuple[int, str, str]:
    p = subprocess.run(PY + [str(TOOL), *[str(a) for a in args]], cwd=str(cwd or ROOT), capture_output=True, timeout=300,
                       env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    return p.returncode, p.stdout.decode("utf-8", "replace").replace("\r\n", "\n"), p.stderr.decode("utf-8", "replace").replace("\r\n", "\n")


def line_count(out: str, label: str) -> str:
    m = re.search(r"^" + re.escape(label) + r"\s*: (.*)$", out, re.M)
    return m.group(1) if m else ""


class Scratch:
    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="geek_live_shape_"))
        self.n = 0

    def put(self, obj, raw: bytes | None = None) -> Path:
        self.n += 1
        p = self.dir / f"states-{self.n}.json"
        p.write_bytes(raw if raw is not None else json.dumps(obj).encode("utf-8"))
        return p

    def out(self, name: str = "listing.json") -> Path:
        self.n += 1
        return self.dir / f"{self.n}-{name}"

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def listing_problems(listing: dict) -> list[str]:
    """A walk over every string of a written listing: it may hold names, types, sizes, one date and the fixed provenance texts, nothing else."""
    p = []
    committed_prov = COMMITTED_SHAPE["_provenance"]
    prov = listing.get("_provenance", {})
    if set(listing) != {"_provenance", "ecco_intel"}:
        p.append("top-level keys")
    if set(prov) != set(committed_prov):
        p.append("provenance keys")
    for k in ("what", "object_id_contains", "used_by"):
        if prov.get(k) != committed_prov.get(k):
            p.append(f"provenance {k}")
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(prov.get("captured"))) or prov.get("captured") == "unknown"):
        p.append("captured is not a date")
    if not (isinstance(prov.get("removed_from_the_raw_listing"), list) and all(isinstance(s, str) and len(s) < 120 and not re.search(r"[0-9a-f]{8}", s) for s in prov["removed_from_the_raw_listing"])):
        p.append("removed list")
    declared = {e.entity_id for e in U.entities}
    for row in listing.get("ecco_intel", []):
        if set(row) != {"entity_id", "state_type", "state_len", "attributes"}:
            p.append("row keys")
        if not G.ENTITY_ID_RE.match(str(row.get("entity_id"))) or not (row.get("entity_id") in declared or NEEDLE in str(row.get("entity_id"))):
            p.append("entity id out of scope")
        if row.get("state_type") != "str" or not isinstance(row.get("state_len"), int):
            p.append("state fields")
        for name, info in row.get("attributes", {}).items():
            if not NAME_RE.match(name):
                p.append("attribute name")
            if set(info) != {"type", "bytes", "top_keys"} or not TYPE_RE.match(str(info.get("type"))) or not isinstance(info.get("bytes"), int):
                p.append("attribute fields")
            tk = info.get("top_keys")
            if tk is not None and not (isinstance(tk, list) and all(NAME_RE.match(k) for k in tk)):
                p.append("top keys")
    return p


# ---------------------------------------------------------------------------------------------------------------------------------
# [1] the static rules (a function of the tool's source, so that mutants of it can be tried)
# ---------------------------------------------------------------------------------------------------------------------------------
def static_problems(src: str) -> list[str]:
    p = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ["the tool does not parse"]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    if names - ALLOWED_IMPORTS:
        p.append(f"imports beyond the standard library, PyYAML and the repository's tools: {sorted(names - ALLOWED_IMPORTS)}")
    if names & FORBIDDEN_IMPORTS:
        p.append(f"a network or process module: {sorted(names & FORBIDDEN_IMPORTS)}")
    defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for own in ("compare_live", "load_shape", "build_universe"):
        if own in defs:
            p.append(f"a second copy of {own}")
    for text in ("conditional: the live", "declared, absent from the live entity", "present live, declared by no code or package", "NOT_CHECKED_LIVE\"] = "):
        if text in src:
            p.append(f"the comparison's own text is copied: {text}")
    if "geek_mode_coverage" not in names or not re.search(r"\bG\.compare_live\(", src):
        p.append("compare_live of geek_mode_coverage is not called")
    if not src.isascii():
        p.append("non-ASCII text")
    return p


# ---------------------------------------------------------------------------------------------------------------------------------
# the scenarios: each is (name, a function of the module under test that returns True when the module behaves); the real module must pass
# all of them, and every mutant must fail at least one
# ---------------------------------------------------------------------------------------------------------------------------------
def make_scenarios(mod, sc: Scratch, fake_repo: Path):
    def go(states, *extra, raw: bytes | None = None):
        return run_mod(mod, [sc.put(states, raw), *extra])

    def counts(out: str) -> dict:
        return {"present": line_count(out, "PRESENT_LIVE"), "absent": line_count(out, "NOT_PRESENT_LIVE"), "undeclared": line_count(out, "UNDECLARED"),
                "notchecked": line_count(out, "NOT_CHECKED_LIVE")}

    base = live_like("healthy")
    out_list: list[tuple[str, object]] = []

    def scenario(name: str):
        def deco(fn):
            out_list.append((name, fn))
            return fn
        return deco

    @scenario("the healthy fixture set exits 0 and says MATCH")
    def _():
        rc, out, _err = go(base)
        return rc == 0 and "RESULT: MATCH (exit 0)" in out

    @scenario("the healthy set: every declared entity present, none missing, none undeclared, none unexplained, none not checked")
    def _():
        rc, out, _err = go(base)
        c = counts(out)
        return (c["present"].startswith(f"{len(U.entities)} of {len(U.entities)} declared entities") and c["absent"].startswith("0 declared entities missing")
                and ", 0 unexplained)" in c["absent"] and c["undeclared"] == "0 entities, 0 attributes" and c["notchecked"].startswith("0 declared entities"))

    @scenario("present and absent attribute rows add up to the declared attribute rows (nothing is lost between the universe and the verdict)")
    def _():
        rc, out, _err = go(base)
        c = counts(out)
        present = int(re.search(r"; (\d+) attribute rows", c["present"]).group(1))
        absent = int(re.search(r"; (\d+) attribute rows absent", c["absent"]).group(1))
        declared = int(re.search(r"(\d+) declared attribute rows", line_count(out, "code universe")).group(1))
        return present + absent == declared == sum(len(e.attrs) for e in U.entities)

    @scenario("the mixed, stale and paused fixtures (conditional shapes) exit 0 with every absent row conditional")
    def _():
        for name in ("mixed", "stale", "paused"):
            rc, out, _err = go(live_like(name))
            if rc != 0 or ", 0 unexplained)" not in counts(out)["absent"]:
                return False
        return True

    @scenario("an extra undeclared attribute exits 1 and is named, without its value")
    def _():
        s = copy.deepcopy(base)
        entity(s, STATUS)["attributes"]["zz_extra_probe"] = FAKE
        rc, out, err = go(s)
        return (rc == 1 and f"UNDECLARED attribute (present live, declared by no code): {STATUS} zz_extra_probe" in out
                and counts(out)["undeclared"] == "0 entities, 1 attributes" and FAKE not in out + err and "RESULT: DIFFERENT (exit 1)" in out)

    @scenario("an undeclared ecco_intel entity exits 1 and is named")
    def _():
        s = copy.deepcopy(base) + [{"entity_id": UNDECLARED_ENTITY, "state": "on", "attributes": {"friendly_name": "x"}}]
        rc, out, _err = go(s)
        return rc == 1 and f"UNDECLARED entity (present live, declared by no code): {UNDECLARED_ENTITY}" in out and counts(out)["undeclared"] == "1 entities, 0 attributes"

    @scenario("an unrelated control entity is not converted and not an UNDECLARED entity: exit 0, counted as ignored")
    def _():
        s = copy.deepcopy(base) + [{"entity_id": CONTROL_ENTITY, "state": "off", "attributes": {"friendly_name": "x", "zz_a": FAKE}}]
        rc, out, err = go(s)
        return rc == 0 and ", 1 others ignored" in line_count(out, "scope") and CONTROL_ENTITY not in out + err

    @scenario("a source entity missing from the read (named ecco_intel) exits 1 and is named as missing")
    def _():
        s = [x for x in copy.deepcopy(base) if x["entity_id"] != STATUS]
        rc, out, _err = go(s)
        return rc == 1 and f"MISSING entity (declared, not in Home Assistant): {STATUS}" in out and counts(out)["absent"].startswith("1 declared entities missing")

    @scenario("a source entity the read marked absent exits 1 as missing")
    def _():
        s = [x for x in copy.deepcopy(base) if x["entity_id"] != STATUS] + [{"entity_id": STATUS, "absent": True}]
        rc, out, _err = go(s)
        return rc == 1 and f"MISSING entity (declared, not in Home Assistant): {STATUS}" in out

    @scenario("the helper outside the name filter, marked absent by the read, is MISSING (exit 1) and not NOT_CHECKED")
    def _():
        s = [x for x in copy.deepcopy(base) if x["entity_id"] != RESERVE] + [{"entity_id": RESERVE, "absent": True}]
        rc, out, _err = go(s)
        return (rc == 1 and f"MISSING entity (declared, not in Home Assistant): {RESERVE}" in out and counts(out)["notchecked"].startswith("0 declared entities")
                and "NOT CHECKED entity" not in out)

    @scenario("the helper outside the name filter, simply not in the read, is NOT_CHECKED_LIVE (counted, named) and the exit is 0")
    def _():
        s = [x for x in copy.deepcopy(base) if x["entity_id"] != RESERVE]
        rc, out, _err = go(s)
        return rc == 0 and counts(out)["notchecked"].startswith("1 declared entities") and f"NOT CHECKED entity: {RESERVE}" in out and counts(out)["present"].startswith(f"{len(U.entities) - 1} of")

    @scenario("the helper outside the name filter, present in the read, is converted and PRESENT_LIVE (declared entities are in scope whatever their name)")
    def _():
        rc, out, _err = go(base)
        return rc == 0 and RESERVE not in out and counts(out)["present"].startswith(f"{len(U.entities)} of")

    @scenario("a missing non-conditional attribute exits 1 as an UNEXPLAINED absence, named")
    def _():
        s = copy.deepcopy(base)
        entity(s, STATUS)["attributes"].pop("mode")
        rc, out, _err = go(s)
        n = re.search(r"\((\d+) conditional", counts(out)["absent"]).group(1)
        n0 = re.search(r"\((\d+) conditional", counts(go(base)[1])["absent"]).group(1)
        return (rc == 1 and f"UNEXPLAINED absence (declared attribute, not on the live entity): {STATUS} mode" in out and ", 1 unexplained)" in counts(out)["absent"]
                and n == n0)

    @scenario("a null parent is conditional: exit 0, its keys counted as conditional (more than the healthy set has), none unexplained")
    def _():
        dotted = [(e.entity_id, p.split(".")[0]) for e in U.entities for p in e.attrs if "." in p and not p.startswith("advice.")]
        pick = next((eid, par) for eid, par in dotted if isinstance(entity(base, eid)["attributes"].get(par), dict))
        s = copy.deepcopy(base)
        entity(s, pick[0])["attributes"][pick[1]] = None
        rc, out, _err = go(s)
        _rc0, out0, _e0 = go(base)
        n = int(re.search(r"\((\d+) conditional", counts(out)["absent"]).group(1))
        n0 = int(re.search(r"\((\d+) conditional", counts(out0)["absent"]).group(1))
        return rc == 0 and n > n0 and ", 0 unexplained)" in counts(out)["absent"]

    @scenario("an undeclared first-level key inside a live dict is named as a dotted path (the advice block)")
    def _():
        eid = next(e.entity_id for e in U.entities if "advice" in e.attrs and isinstance(entity(base, e.entity_id)["attributes"].get("advice"), dict))
        s = copy.deepcopy(base)
        entity(s, eid)["attributes"]["advice"]["zz_nested"] = FAKE
        rc, out, err = go(s)
        return rc == 1 and f"{eid} advice.zz_nested" in out and FAKE not in out + err

    @scenario("a recorded self_test (its check codes are not declared) exits 1 with the hint; the same read with it empty exits 0")
    def _():
        s = copy.deepcopy(base)
        entity(s, STATUS)["attributes"]["self_test"] = {"CHECK_ONE": "PASS", "CHECK_TWO": "PASS"}
        rc, out, _err = go(s)
        return rc == 1 and f"{STATUS} self_test.CHECK_ONE" in out and "HINT: the keys of a recorded self_test" in out and go(base)[0] == 0

    @scenario("an entity that reads unavailable is counted in a NOTE (a count, no value)")
    def _():
        s = copy.deepcopy(base)
        entity(s, STATUS)["state"] = "unavailable"
        rc, out, _err = go(s)
        return line_count(out, "NOTE").startswith("1 converted entities read unavailable or unknown")

    @scenario("no value leaves the tool: a planted value, entity-id-like string, number, state, name and key are in no output and not in the listing")
    def _():
        s = copy.deepcopy(base)
        st = entity(s, STATUS)
        st["state"] = FAKE_STATE
        st["attributes"]["friendly_name"] = FAKE
        st["attributes"]["zz_probe_id"] = FAKE_ID
        st["attributes"][FAKE_NAME] = FAKE
        st["attributes"]["zz_probe_dict"] = {FAKE_KEY: FAKE, "plain_key": FAKE_ID, "n": FAKE_NUM}
        st["attributes"]["zz_probe_list"] = [FAKE, FAKE_NUM, FAKE_ID]
        st["attributes"]["zz_probe_num"] = FAKE_NUM
        s.append({"entity_id": FAKE_CTRL, "state": FAKE_STATE, "attributes": {"friendly_name": FAKE, "x": FAKE_ID, "n": FAKE_NUM}})
        listing = sc.out()
        rc, out, err = go(s, "--write-shape", listing)
        text = out + err + (listing.read_text(encoding="utf-8") if listing.exists() else "")
        low = text.lower()
        return rc == 1 and listing.exists() and not any(t.lower() in low for t in TOKENS) and "<unusual-name-" in out and "zz_probe_dict" in out

    @scenario("the written listing holds only names, types, sizes, one date and the fixed provenance texts (a walk over every string), even for a hostile read")
    def _():
        s = copy.deepcopy(base)
        st = entity(s, STATUS)
        st["attributes"][FAKE_NAME] = FAKE
        st["attributes"]["zz_probe_dict"] = {FAKE_KEY: FAKE, "plain_key": FAKE}
        hostile = {k: v for k, v in json.loads((FX_DIR / "hostile.states.json").read_bytes()).items() if not k.startswith("_")}
        s += [{"entity_id": k, "state": v["state"], "attributes": v["attributes"]} for k, v in hostile.items()]
        listing = sc.out()
        rc, out, err = go(s, "--write-shape", listing)
        if not listing.exists():
            return False
        text = listing.read_text(encoding="utf-8")
        doc = json.loads(text)
        hostile_text = json.dumps(hostile)
        leaked = [w for w in ("<script", "onerror", "javascript:", "__pwn", "<iframe") if w in (out + err + text)]
        return not listing_problems(doc) and not leaked and text.isascii() and "<unusual-name-" in text and hostile_text and len(doc["ecco_intel"]) > len(base) - 1

    @scenario("types and encoded sizes in the listing are the committed listing's vocabulary (bool before int, null, float, list[n], dict[n]; JSON size in UTF-8 bytes)")
    def _():
        s = copy.deepcopy(base)
        a = entity(s, STATUS)["attributes"]
        a.update({"zz_t_bool": True, "zz_t_int": 3, "zz_t_float": 1.5, "zz_t_null": None, "zz_t_str": "abc", "zz_t_list": [1, 2], "zz_t_dict": {"b": 1, "a": 2}, "zz_t_u": chr(0xE9)})
        listing = sc.out()
        go(s, "--write-shape", listing)
        row = next(r for r in json.loads(listing.read_text(encoding="utf-8"))["ecco_intel"] if r["entity_id"] == STATUS)["attributes"]
        got = {k: (row[k]["type"], row[k]["bytes"], row[k]["top_keys"]) for k in row if k.startswith("zz_t_")}
        want = {"zz_t_bool": ("bool", 4, None), "zz_t_int": ("int", 1, None), "zz_t_float": ("float", 3, None), "zz_t_null": ("null", 4, None), "zz_t_str": ("str", 5, None),
                "zz_t_list": ("list[2]", 6, None), "zz_t_dict": ("dict[2]", 16, ["a", "b"]), "zz_t_u": ("str", 4, None)}
        return got == want and list(row) == sorted(row)

    @scenario("the capture date is the newest date in the input (provenance and the printed line)")
    def _():
        s = copy.deepcopy(base)
        entity(s, STATUS)["last_updated"] = "2031-02-03T04:05:06+00:00"
        listing = sc.out()
        rc, out, _err = go(s, "--write-shape", listing)
        return "newest timestamp in it: 2031-02-03" in out and json.loads(listing.read_text(encoding="utf-8"))["_provenance"]["captured"] == "2031-02-03"

    @scenario("a {\"data\": [...]} envelope and the fixtures' mapping read exactly as the bare list does")
    def _():
        a = go(base)
        b = go({"data": base})
        mapping = {s["entity_id"]: {k: v for k, v in s.items() if k != "entity_id"} for s in base}
        c = go(mapping)
        norm = lambda r: (r[0], re.sub(r"^input .*$", "", r[1], flags=re.M), r[2])  # noqa: E731
        return a[0] == b[0] == c[0] == 0 and norm(a) == norm(b) == norm(c)

    @scenario("a UTF-8 file with a byte order mark (what Out-File -Encoding utf8 writes) is read")
    def _():
        rc, out, _err = go(None, raw=b"\xef\xbb\xbf" + json.dumps(base).encode("utf-8"))
        return rc == 0 and "RESULT: MATCH" in out

    @scenario("bad input exits 2 and names no content: garbage, an empty list, a scalar, a duplicate, a state that is not a text, a bad entity id")
    def _():
        cases = [
            go(None, raw=b'{"data": [ "planted-garbage-3f9" '),
            go(None, raw=b"not json planted-garbage-3f9"),
            go([]),
            go(7),
            go("planted-garbage-3f9"),
            go(copy.deepcopy(base) + [copy.deepcopy(base[0])]),
            go([{"entity_id": STATUS, "state": 5, "attributes": {"x": FAKE}}]),
            go([{"entity_id": FAKE_BAD_ID, "state": "on", "attributes": {"x": FAKE}}]),
            go([{"state": "on", "attributes": {"x": FAKE}}]),
            go([{"entity_id": STATUS, "state": "on", "attributes": FAKE}]),
            go({"planted-garbage-3f9": FAKE}),
        ]
        low = " ".join(c[1] + c[2] for c in cases).lower()
        return all(c[0] == 2 for c in cases) and not any(t.lower() in low for t in TOKENS) and all(c[1] == "" for c in cases)

    @scenario("a file that is not UTF-8 text exits 2; a UTF-16 file exits 2 and says UTF-16")
    def _():
        rc1, _o, e1 = go(None, raw=b"\x80\x81\x82")
        rc2, _o2, e2 = go(None, raw=json.dumps(base).encode("utf-16"))
        return rc1 == 2 and rc2 == 2 and "UTF-16" in e2

    @scenario("a missing states file and a missing argument exit 2")
    def _():
        return run_mod(mod, [sc.dir / "no-such-file.json"])[0] == 2 and run_mod(mod, [])[0] == 2

    @scenario("--overwrite without --write-shape is a usage error (exit 2)")
    def _():
        rc, _o, err = go(base, "--overwrite")
        return rc == 2 and "--write-shape" in err

    @scenario("--write-shape writes the value-free listing in the committed listing's format and exits with the verdict")
    def _():
        listing = sc.out()
        rc, out, _err = go(base, "--write-shape", listing)
        doc = json.loads(listing.read_text(encoding="utf-8"))
        return (rc == 0 and listing.read_bytes() == (json.dumps(doc, indent=1) + "\n").encode("ascii") and not listing_problems(doc)
                and [r["entity_id"] for r in doc["ecco_intel"]] == sorted(s["entity_id"] for s in base) and f"wrote the value-free listing: {listing.name}" in out)

    @scenario("--write-shape refuses an existing file (nothing changed) and --overwrite replaces it")
    def _():
        listing = sc.out()
        go(base, "--write-shape", listing)
        before = listing.read_bytes()
        marker = b"keep me"
        listing.write_bytes(marker)
        rc, _o, err = go(base, "--write-shape", listing)
        kept = listing.read_bytes() == marker
        rc2, _o2, _e2 = go(base, "--write-shape", listing, "--overwrite")
        return rc == 2 and "add --overwrite" in err and kept and rc2 == 0 and listing.read_bytes() == before

    @scenario("--write-shape refuses a folder that does not exist, and a folder as the path")
    def _():
        rc, _o, err = go(base, "--write-shape", sc.dir / "no-such-folder" / "x.json")
        rc2, _o2, err2 = go(base, "--write-shape", sc.dir)
        return rc == 2 and "folder does not exist" in err and rc2 == 2 and "folder" in err2

    @scenario("--write-shape refuses any path inside the repository's checkout: a tracked folder, a relative path into it; nothing is created")
    def _():
        inside = fake_repo / "frontend" / "catalogue"
        shutil.rmtree(fake_repo / "frontend", ignore_errors=True)   # a mutant that lost the guard leaves files behind: the next scenario starts clean
        inside.mkdir(parents=True, exist_ok=True)
        target = inside / "listing.json"
        rc, _o, err = go(base, "--write-shape", target)
        rc2, _o2, err2 = go(base, "--write-shape", inside / ".." / "catalogue" / "listing2.json")
        return (rc == 2 and "outside this repository" in err and not target.exists() and rc2 == 2 and "outside this repository" in err2
                and not (inside / "listing2.json").exists())

    @scenario("--write-shape outside the checkout is fine (the check is not a blanket refusal)")
    def _():
        listing = sc.out()
        return go(base, "--write-shape", listing)[0] == 0 and listing.exists()

    return out_list


# ---------------------------------------------------------------------------------------------------------------------------------
# mutants of the tool's source: (name, [(old, new), ...], "scenario" or "static")
# ---------------------------------------------------------------------------------------------------------------------------------
EXIT_LINE = 'return 1 if (rep["undeclared_entities"] or rep["undeclared_attrs"] or rep["missing"] or rep["unexplained"]) else 0'
MUTANTS = [
    ("X1 the exit code is always 0", [(EXIT_LINE, "return 0")]),
    ("X2 the exit code is inverted", [("return 1 if (rep[", "return 0 if (rep["), ('rep["unexplained"]) else 0', 'rep["unexplained"]) else 1')]),
    ("X3 an undeclared entity no longer fails the exit code", [('rep["undeclared_entities"] or ', "")]),
    ("X4 an undeclared attribute no longer fails the exit code", [('rep["undeclared_attrs"] or ', "")]),
    ("X5 a missing entity no longer fails the exit code", [('rep["missing"] or ', "")]),
    ("X6 an unexplained absence no longer fails the exit code", [(' or rep["unexplained"])', ")")]),
    ("C1 every absent attribute row is called conditional (the unexplained list is empty)", [('unexplained = [r for r in absent_rows if not r["why"].startswith("conditional:")]', "unexplained = []")]),
    ("C2 the conditional count takes every absent row", [('conditional = [r for r in absent_rows if r["why"].startswith("conditional:")]', "conditional = list(absent_rows)")]),
    ("U1 undeclared entities are never collected", [('undeclared_entities = sorted(r["entity_id"] for r in live["undeclared"] if r["path"] is None)', "undeclared_entities = []")]),
    ("U2 undeclared attributes are never collected", [('undeclared_attrs = sorted((r["entity_id"], r["path"]) for r in live["undeclared"] if r["path"] is not None)', "undeclared_attrs = []")]),
    ("U3 a declared entity marked absent by the read is no longer missing", [('    missing += sorted(eid for eid in live["not_checked_live"] if eid in absent_ids)\n', "    pass\n")]),
    ("U4 a declared entity marked absent is also counted as not checked", [('not_checked = [eid for eid in live["not_checked_live"] if eid not in absent_ids]', 'not_checked = list(live["not_checked_live"])')]),
    ("U5 the missing entities are never collected", [('missing = sorted({r["entity_id"] for r in live["not_present_live"] if r["path"] is None})', "missing = []")]),
    ("V1 the conversion keeps the value of an attribute", [('"top_keys": keys}', '"top_keys": keys, "value": v}')]),
    ("V2 the conversion keeps the state text", [('"state_len": len(entry["state"])', '"state_len": entry["state"]')]),
    ("V3 an attribute name that is not an identifier is kept as it is", [("    if isinstance(name, str) and IDENT_RE.fullmatch(name):", "    if True:")]),
    ("V4 the keys of a dict attribute are kept as they are (sanitising removed)", [("keys = sorted(safe_name(k, unusual) for k in v)", "keys = sorted(v)")]),
    ("V5 the input is echoed in an error message", [('raise InputError(f"object {i + 1} of the states file is not a state object with an entity id")',
                                                      'raise InputError(f"object {i + 1} ({e!r}) of the states file is not a state object with an entity id")')]),
    ("S1 every state is in scope (an unrelated control entity becomes UNDECLARED)", [('    return entity_id in declared or SCOPE_NEEDLE in entity_id.split(".", 1)[1]', "    return True")]),
    ("S2 a declared entity outside the name filter is out of scope", [('    return entity_id in declared or SCOPE_NEEDLE in entity_id.split(".", 1)[1]', '    return SCOPE_NEEDLE in entity_id.split(".", 1)[1]')]),
    ("W1 an existing output file is overwritten without --overwrite", [("    if path.exists() and not overwrite:", "    if False:")]),
    ("W1b the overwrite guard is gone in both places (the check and the exclusive open)", [("    if path.exists() and not overwrite:", "    if False:"), ('open(path, "wb" if overwrite else "xb")', 'open(path, "wb")')]),
    ("W2 the checkout guard is gone", [("    try:\n        path.resolve().relative_to(REPO.resolve())\n    except ValueError:\n        return False\n    return True", "    return False")]),
    ("W3 --overwrite alone is accepted", [("    if args.overwrite and args.write_shape is None:", "    if False:")]),
    ("W4 a missing output folder is not named", [("    if not path.parent.is_dir():", "    if False:")]),
    ("D1 the capture date is the oldest, not the newest", [("if m and m.group(0) > best:", "if m and m.group(0) < best:")]),
    ("D2 a bool is typed as an int", [('    if isinstance(v, bool):\n        return "bool"\n', "")]),
    ("I1 a duplicate entity id is accepted", [('        if e["entity_id"] in seen:', "        if False:")]),
    ("I2 the data envelope is not unwrapped", [('if isinstance(obj, dict) and "data" in obj:', "if False:")]),
    ("I3 UTF-16 is not recognised", [('if data[:2] in (b"\\xff\\xfe", b"\\xfe\\xff"):', "if False:")]),
    ("I4 an empty list is accepted", [("    if not obj:\n", "    if False:\n")]),
    ("N1 the self_test hint is gone", [('if any(p.startswith("self_test.") for _e, p in rep["undeclared_attrs"]):', 'if False and any(p.startswith("self_test.") for _e, p in rep["undeclared_attrs"]):')]),
    ("N2 the unavailable note is gone", [('if e["state"] in ("unavailable", "unknown"):', "if False:")]),
]
STATIC_MUTANTS = [
    ("T1 a second copy of compare_live is added", lambda s: s + "\n\ndef compare_live(u, shape):\n    return {}\n"),
    ("T2 a network module is imported", lambda s: s.replace("import argparse\n", "import argparse\nimport urllib.request\n", 1)),
    ("T3 a third-party module is imported", lambda s: s.replace("import argparse\n", "import argparse\nimport requests\n", 1)),
    ("T4 the comparison of geek_mode_coverage is no longer called", lambda s: s.replace("G.compare_live(", "G.compare_live_not(", 1)),
]


def main() -> int:
    print(f"tool: {TOOL.name}")
    if not TOOL.is_file():
        check("the tool exists", False, str(TOOL))
        return finish()
    src = TOOL.read_bytes().decode("utf-8", errors="replace")
    sc = Scratch()
    fake_repo = sc.dir / "fake_repo"
    fake_repo.mkdir()
    committed_before = sha(COMMITTED_SHAPE_PATH)
    catalogue_listing_before = sorted(p.name for p in COMMITTED_SHAPE_PATH.parent.iterdir())
    try:
        # [1] the static rules
        print("[1] the tool's source")
        sp = static_problems(src)
        check("only the standard library, PyYAML and the repository's own tools are imported; no network or process module; compare_live is called, not copied; ASCII", not sp, "; ".join(sp))

        # [2] to [5] in memory
        print("[2] to [5] verdicts, no value, input, --write-shape (in memory, on the tool's own source)")
        try:
            mod = load_module(src, fake_repo)
            scenarios = make_scenarios(mod, sc, fake_repo)
        except (Exception, SystemExit) as exc:  # a stub or a broken tool (even one that exits when it is loaded): every scenario below fails
            mod, scenarios = None, []
            check("the tool loads as a module with a main()", False, f"{type(exc).__name__}")
        if mod is not None:
            check("the tool loads as a module with a main()", hasattr(mod, "main"))
        for name, fn in scenarios:
            try:
                ok = bool(fn())
                detail = ""
            except (Exception, SystemExit) as exc:  # noqa: BLE001 - a broken tool fails the scenario, it does not stop the suite
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            check(name, ok, detail)
        check(f"the scenarios are run ({len(scenarios)}; 32 are expected)", len(scenarios) >= 32)

        # [6] the real command line
        print("[6] the real command line (python -I -B -X utf8)")
        healthy = sc.put(live_like("healthy"))
        rc, out, err = run_cli([healthy])
        check("healthy fixture states: exit 0, RESULT: MATCH, nothing on stderr, stdout is ASCII", rc == 0 and "RESULT: MATCH (exit 0)" in out and err == "" and out.isascii(), f"rc={rc} {err[:120]}")
        check("the counts are printed: PRESENT_LIVE, NOT_PRESENT_LIVE with conditional and unexplained, UNDECLARED, NOT_CHECKED_LIVE",
              all(re.search(r"^" + w + r"\s*: ", out, re.M) for w in ("PRESENT_LIVE", "NOT_PRESENT_LIVE", "UNDECLARED", "NOT_CHECKED_LIVE")) and " conditional, " in out and " unexplained)" in out)
        bad = live_like("healthy")
        entity(bad, STATUS)["attributes"]["zz_extra_probe"] = FAKE
        rc, out, err = run_cli([sc.put(bad)])
        check("an undeclared attribute: exit 1 and it is named", rc == 1 and "zz_extra_probe" in out and FAKE not in out + err, f"rc={rc}")
        rc, out, err = run_cli([sc.put(None, raw=b"planted-garbage-3f9")])
        check("garbage: exit 2, the message is on stderr and says nothing of the content", rc == 2 and out == "" and "planted-garbage-3f9" not in err and err.startswith("ERROR:"), f"rc={rc} {err[:120]}")
        rc, out, err = run_cli([])
        check("no argument: exit 2 (a usage error)", rc == 2 and "usage" in err.lower())
        rc, out, err = run_cli([sc.dir / "absent.json"])
        check("a missing file: exit 2", rc == 2 and out == "")
        tracked = ROOT / "frontend" / "ecco-mode-shell" / "catalogue" / "zz_live_shape_guard_test.json"
        rc, out, err = run_cli([healthy, "--write-shape", tracked])
        created = tracked.exists()
        if created:
            tracked.unlink()
        check("--write-shape into a tracked folder of the repository: refused (exit 2), nothing created", rc == 2 and "outside this repository" in err and not created, f"rc={rc}")
        rc, out, err = run_cli([healthy, "--write-shape", Path("frontend") / "ecco-mode-shell" / "catalogue" / "zz_live_shape_guard_test2.json"], cwd=ROOT)
        tracked2 = ROOT / "frontend" / "ecco-mode-shell" / "catalogue" / "zz_live_shape_guard_test2.json"
        created2 = tracked2.exists()
        if created2:
            tracked2.unlink()
        check("--write-shape with a relative path into a tracked folder: refused (exit 2), nothing created", rc == 2 and "outside this repository" in err and not created2, f"rc={rc}")
        listing = sc.out()
        rc, out, err = run_cli([healthy, "--write-shape", listing])
        rc2, out2, err2 = run_cli([healthy, "--write-shape", listing])
        rc3, out3, err3 = run_cli([healthy, "--write-shape", listing, "--overwrite"])
        check("--write-shape outside the checkout writes; a second run refuses to overwrite (exit 2); --overwrite replaces",
              rc == 0 and listing.exists() and rc2 == 2 and "exists" in err2 and rc3 == 0, f"{rc} {rc2} {rc3}")
        # the committed 14 Nov listing converted back into states
        back = []
        for r in COMMITTED_SHAPE["ecco_intel"]:
            attrs = {}
            for n, i in r["attributes"].items():
                t = i["type"]
                attrs[n] = (None if t == "null" else True if t == "bool" else 7 if t == "int" else 0.5 if t == "float" else "x" * max(0, i["bytes"] - 2) if t == "str"
                            else ["x"] * int(t[5:-1]) if t.startswith("list[") else {k: 0 for k in (i["top_keys"] or [])})
            back.append({"entity_id": r["entity_id"], "state": "y" * r["state_len"], "attributes": attrs, "last_updated": COMMITTED_SHAPE["_provenance"]["captured"] + "T10:00:00+00:00"})
        direct = G.compare_live(U, COMMITTED_SHAPE)
        direct_cond = [r for r in direct["not_present_live"] if r["path"] is not None]
        back_listing = sc.out()
        rc, out, err = run_cli([sc.put(back), "--write-shape", back_listing])
        got = json.loads(back_listing.read_text(encoding="utf-8")) if back_listing.exists() else {"ecco_intel": []}
        shape_of = lambda s: [(r["entity_id"], r["state_len"], {n: (i["type"], i["top_keys"]) for n, i in r["attributes"].items()}) for r in s["ecco_intel"]]  # noqa: E731
        parts = {
            "rc 0": rc == 0,
            "the comparison on the committed listing itself: 0 undeclared, 1 not checked, 42 conditional": len(direct["undeclared"]) == 0 and len(direct["not_checked_live"]) == 1 and len(direct_cond) == 42,
            "the same conditional count, none unexplained": re.search(r"\(%d conditional, 0 unexplained\)" % len(direct_cond), out) is not None,
            "none undeclared": line_count(out, "UNDECLARED") == "0 entities, 0 attributes",
            "one not checked": line_count(out, "NOT_CHECKED_LIVE").startswith("1 declared entities"),
            "present": line_count(out, "PRESENT_LIVE").startswith("%d of %d" % (len(COMMITTED_SHAPE["ecco_intel"]), len(direct["entities"]))),
        }
        check("the committed 14 Nov listing converted back into states: exit 0 and the verdict geek_mode_coverage itself gives on that listing "
              f"({len(direct['entities'])} declared, {len(direct_cond)} conditional absences, {len(direct['not_checked_live'])} not checked, {len(direct['undeclared'])} undeclared)",
              all(parts.values()), str([k for k, v in parts.items() if not v]))
        check("and the listing the tool writes from them equals the committed listing in entity ids, state lengths, attribute names, types and dict keys",
              shape_of(got) == shape_of(COMMITTED_SHAPE) and got.get("_provenance", {}).get("captured") == COMMITTED_SHAPE["_provenance"]["captured"])
        hostile = {k: v for k, v in json.loads((FX_DIR / "hostile.states.json").read_bytes()).items() if not k.startswith("_")}
        rc, out, err = run_cli([sc.put([{"entity_id": k, "state": v["state"], "attributes": v["attributes"]} for k, v in hostile.items()] + live_like("healthy"))])
        check("the hostile fixture goes through: exit 1 (undeclared entity), its markup, handlers and URLs are in no output",
              rc == 1 and not any(w in out + err for w in ("<script", "onerror", "javascript:", "__pwn", "<iframe", "<img")), f"rc={rc}")
        noise = json.loads((FX_DIR / "noise.states.json").read_bytes())
        rc, out, err = run_cli([sc.put(live_like("healthy") + [{"entity_id": k, **v} for k, v in noise.items() if NEEDLE not in k])])
        check(f"{len([k for k in noise if NEEDLE not in k])} unrelated noise entities are ignored (counted only): exit 0",
              rc == 0 and f", {len([k for k in noise if NEEDLE not in k])} others ignored" in line_count(out, "scope"), out[-300:])
        check("the suite changed nothing in the repository (the committed listing is byte-identical, the catalogue folder holds the same files)",
              sha(COMMITTED_SHAPE_PATH) == committed_before and sorted(p.name for p in COMMITTED_SHAPE_PATH.parent.iterdir()) == catalogue_listing_before)

        # [7] mutants
        print("[7] mutants of the tool's source (in memory)")
        n_ok = 0
        total = len(MUTANTS) + len(STATIC_MUTANTS)
        for name, edits in MUTANTS:
            msrc = src
            applied = True
            for old, new in edits:
                if src.count(old) != 1:
                    applied = False
                    break
                msrc = msrc.replace(old, new, 1)
            check(f"{name}: the mutation applies exactly once", applied and msrc != src)
            if not (applied and msrc != src):
                continue
            killed_by = ""
            try:
                mmod = load_module(msrc, fake_repo)
                for sname, fn in make_scenarios(mmod, sc, fake_repo):
                    try:
                        if not fn():
                            killed_by = sname
                            break
                    except (Exception, SystemExit):  # noqa: BLE001 - a mutant that breaks the tool is killed too
                        killed_by = sname + " (it raised)"
                        break
            except (Exception, SystemExit):  # noqa: BLE001
                killed_by = "the mutant does not load"
            n_ok += bool(killed_by)
            check(f"{name}: killed by a running check ({killed_by[:70] or 'NOT KILLED'})", bool(killed_by))
        for name, fn in STATIC_MUTANTS:
            msrc = fn(src)
            check(f"{name}: the mutation changes the source", msrc != src)
            hit = static_problems(msrc)
            n_ok += bool(hit)
            check(f"{name}: killed by the static rules ({'; '.join(hit)[:70] or 'NOT KILLED'})", bool(hit))
        check(f"at least twelve mutants are run and every one is killed ({n_ok} of {total})", total >= 12 and n_ok == total)

        own = Path(__file__).read_bytes()
        own_text = own.decode("utf-8", errors="replace")
        check("this suite's own source is ASCII and holds no address, token shape, entity id or user-profile path",
              own.isascii() and not IPV4.search(own_text) and not TOKEN_SHAPE.search(own_text) and not ENTITY_ID_LITERAL.search(own_text) and not USER_PATH.search(own_text))
    finally:
        sc.close()
    return finish()


def finish() -> int:
    print("")
    print(f"{PASSED[0]} PASS, {len(FAILURES)} FAIL")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
