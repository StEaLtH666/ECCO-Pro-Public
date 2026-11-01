#!/usr/bin/env python3
"""Fail-closed dashboard preservation gate: a deployment may never put a generic repository dashboard over a site's private layer.

A site can customise its live Home Assistant dashboard file (for example one card replaced by a private card, or settings that point
at private media). A deployment rendered from this repository would silently put the generic version back. This tool is the gate
tools/deploy-ha.ps1 runs before it backs up or uploads a dashboard file, and again after the install. It is generic: every site value
lives in a site-local policy file on the host (/config/ecco/site-local/dashboard-protection.json), never in this repository.

    python tools/ecco_dashboard_guard.py check --destination D --live L --candidate C [--policy P] [--resources R]
                                               [--accept-removed-type custom:T ...] [--allow-drift-recovery] [--json OUT]
    python tools/ecco_dashboard_guard.py apply --policy P --destination D --candidate C --out O
    python tools/ecco_dashboard_guard.py make-policy --gate NAME --destination D --base B --live L --pointer /json/pointer
                                                     [--require-resource URL ...] --out O
    python tools/ecco_dashboard_guard.py verify-live --policy P --destination D --live L
    python tools/ecco_dashboard_guard.py classify --destination D [--policy P]

OUTPUT. The first line is always "<GATE>: PASS" or "<GATE>: BLOCKED" (classify: "gate: <GATE>"), then one line per finding:
"  BLOCKED <rule>: ..." for each reason, "  WARNING <rule>: ..." (a drift recovery, below), "  ok <rule>: ..." and
"  info: ...". GATE is the policy's "gate" when the policy has an
entry for the destination, otherwise DASHBOARD_PRESERVE_GATE. Lines name JSON pointers, counts, sha256 prefixes (12 hex) of
subtrees and full sha256 values of whole files only: never a value of a dashboard, an overlay, a resource or a card type, which
may be private. A usage error names option names only, never an argument value.

EXIT. 0 = PASS. 3 = BLOCKED by a rule (apply / make-policy: refused). 2 = refused input: a usage error, an unreadable or malformed
file, a malformed policy, PyYAML missing or an internal error; the first line still says BLOCKED. classify: 0 = a dashboard
destination, 4 = not one (a code Python never uses for a crash, so a guard that cannot run is never read as "not a dashboard"),
2 = refused.

RULES of `check` (all evaluated; any failure blocks):
  R1 live and candidate are UTF-8 YAML documents whose top level is a mapping (a Lovelace dashboard). Home Assistant tags (!include,
     !secret, !input, ...) parse as opaque values and are never resolved. Duplicate keys: the last wins, as in Home Assistant.
  R2 (site layer: only when the policy has an entry for the destination) for every `protect` entry {pointer, sha256}: the live subtree
     at the pointer exists and its canonical hash is the policy's ("live protected layer differs from the site policy"), and the
     candidate subtree exists with the same hash ("candidate removes or replaces a protected layer"). Canonical hash: sha256 of
     json.dumps(subtree, sort_keys=True, separators=(",", ":"), ensure_ascii=False), UTF-8, with tagged values, non-string keys and
     other non-JSON YAML values encoded deterministically under NUL-prefixed marker keys (a plain dashboard needs none of them).
     Pointers are RFC 6901 over the parsed YAML, list indices as decimal integers.
     Drift recovery: with --allow-drift-recovery, live differing from the policy is a WARNING instead of BLOCKED, but only when the
     candidate carries every protected subtree with exactly the policy's hash (it restores the site layer); a candidate that does not
     carry the protected layer stays BLOCKED. Without the option such a candidate is BLOCKED with a line naming the option, because
     a live file that differs may hold newer site values than the policy (then make a new policy instead). The option waives
     nothing else (R3, R4 and the candidate half of R2 still apply).
  R3 (site layer) every `require_resources` {url} is the url of an item of the resources file (the Home Assistant
     .storage/lovelace_resources format, data.items[].url). Required but --resources missing: BLOCKED.
  R4 (generic layer: always) every Lovelace card type that starts with "custom:" and occurs in live occurs in the candidate, unless
     named by --accept-removed-type (repeatable, each value custom:<name> with name [A-Za-z0-9][A-Za-z0-9._-]*; it waives R4 for
     that type only, never R2 or R3). A dropped type is named by the pointer of its first use in live and its use count.
  R5 a policy file that is given is valid: schema ecco-dashboard-protection/1, a gate name, at least one dashboard entry, unique
     destinations, valid pointers and sha256 values, scalar overlay values under a protected pointer. Otherwise BLOCKED, never
     "no policy". The policy's absence (no --policy) means the generic layer only. A destination that matches a policy entry
     only when letter case is ignored is refused too (a mistyped policy must not silently drop to the generic layer).

`apply` writes the policy entry's overlay [{pointer, value}] into the candidate TEXT, so a fresh repository render carries the site
layer again: an existing single-line scalar's text span is replaced, or a missing key is inserted into an existing block mapping
at that mapping's indentation (spans come from yaml.compose() node marks; the file is never regex-edited). Values are written as
double-quoted strings or plain numbers / booleans. Before writing, the result must parse to the candidate with exactly those values
set and must match every protect hash of the entry; otherwise nothing is written (exit 3). It refuses a missing parent, a flow
mapping, a sequence parent, an anchor or alias on the path, a merge key, a tagged node and a target that is not a plain scalar.
`make-policy` builds a one-entry policy from a base render and the live file: overlay = the scalar leaves under --pointer that
differ or were added in live; protect = [{pointer, sha256 of live[pointer]}]. It refuses a difference outside the pointer (it prints
the pointers, not the values), a differing leaf that is not a scalar or sits in a sequence, and a removed key, and it proves the
policy (apply(base) parses to live) before writing it. The policy holds site values: keep it out of every repository.
`verify-live` is R2 on the live file only (after a deployment). `classify` says whether tools/deploy-ha.ps1 must gate a destination:
it is under /config/ecco/dashboards/ and ends .yaml / .yml, or the policy has an entry for it. With a policy it also lists every
destination the policy names ("policy destination: <path>"), so the caller can prove that each one exists on the host.

Standard library + PyYAML. No network, no subprocess. Writes only the --out / --json file the caller names (--out never overwrites).
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime
import hashlib
import json
import math
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:   # PyYAML missing: every YAML command refuses (exit 2, BLOCKED); classify still works
    yaml = None

DEFAULT_GATE = "DASHBOARD_PRESERVE_GATE"
SCHEMA = "ecco-dashboard-protection/1"
REPORT_SCHEMA = "ecco-dashboard-guard-report/1"
EXIT_PASS, EXIT_ERROR, EXIT_BLOCKED, EXIT_NOT_DASHBOARD = 0, 2, 3, 4   # never 1: Python's own exit code for a crash
DASHBOARD_PREFIX = "/config/ecco/dashboards/"
SITE_LOCAL_PREFIX = "/config/ecco/site-local/"
GATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
INDEX_RE = re.compile(r"^(0|[1-9][0-9]*)$")
PLAIN_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
CARD_TYPE_RE = re.compile(r"custom:[A-Za-z0-9][A-Za-z0-9._-]*")   # --accept-removed-type, always with fullmatch
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_CANON_NODES = 4_000_000
CORE_SCALAR_TAGS = {"tag:yaml.org,2002:str", "tag:yaml.org,2002:int", "tag:yaml.org,2002:float", "tag:yaml.org,2002:bool",
                    "tag:yaml.org,2002:null"}
STR_TAG, MAP_TAG, MERGE_TAG = "tag:yaml.org,2002:str", "tag:yaml.org,2002:map", "tag:yaml.org,2002:merge"
POLICY_KEYS = {"schema", "gate", "dashboards", "note"}
ENTRY_KEYS = {"destination", "protect", "overlay", "require_resources", "note"}


class GuardError(Exception):
    """Refused input (exit 2). The message names files by role, pointers and counts only, never a value."""


class Refusal(Exception):
    """A rule refused the operation (exit 3). Same message discipline."""


def safe(text: str) -> str:
    """Printable ASCII only: a pointer may carry any character of a YAML key."""
    out = []
    for ch in str(text):
        o = ord(ch)
        out.append(ch if 0x20 <= o < 0x7F else (f"\\x{o:02x}" if o < 0x100 else f"\\u{o:04x}" if o < 0x10000 else f"\\U{o:08x}"))
    return "".join(out)


# ------------------------------------------------------------------------------------------------------------------------------
# YAML: opaque Home Assistant tags, anchors recorded for apply
# ------------------------------------------------------------------------------------------------------------------------------
class Tagged:
    """A value carrying a local YAML tag (!include, !secret, !input, ...): kept opaque, never resolved."""

    __slots__ = ("tag", "value")

    def __init__(self, tag: str, value) -> None:
        self.tag, self.value = tag, value


_LOADER = None


def loader_class():
    global _LOADER
    if yaml is None:
        raise GuardError("PyYAML is not installed for this Python: the gate cannot read YAML (install PyYAML for the python on PATH)")
    if _LOADER is None:
        class GuardLoader(yaml.SafeLoader):
            ecco_anchored: frozenset = frozenset()

            def compose_document(self):   # PyYAML's own compose_document, plus the record of anchored nodes (aliases point at them)
                self.get_event()
                node = self.compose_node(None, None)
                self.get_event()
                self.ecco_anchor_nodes = list(self.anchors.values())
                self.ecco_anchored = frozenset(id(n) for n in self.ecco_anchor_nodes)
                self.anchors = {}
                return node

        def opaque(loader, suffix, node):
            if isinstance(node, yaml.ScalarNode):
                value = loader.construct_scalar(node)
            elif isinstance(node, yaml.SequenceNode):
                value = loader.construct_sequence(node, deep=True)
            else:
                value = loader.construct_mapping(node, deep=True)
            return Tagged("!" + suffix, value)

        GuardLoader.add_multi_constructor("!", opaque)
        _LOADER = GuardLoader
    return _LOADER


def read_text(path: str, role: str) -> str:
    p = Path(path)
    try:
        if not p.is_file():
            raise GuardError(f"{role}: not a readable file")
        if p.stat().st_size > MAX_INPUT_BYTES:
            raise GuardError(f"{role}: larger than {MAX_INPUT_BYTES} bytes")
        raw = p.read_bytes()
    except OSError as ex:
        raise GuardError(f"{role}: cannot be read ({type(ex).__name__})") from None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as ex:
        raise GuardError(f"{role}: not UTF-8 (byte {ex.start})") from None


def _yaml_error(role: str, ex: Exception) -> GuardError:
    mark = getattr(ex, "problem_mark", None) or getattr(ex, "context_mark", None)
    where = f" at line {mark.line + 1} column {mark.column + 1}" if mark is not None else ""
    pos = getattr(ex, "position", None)   # a ReaderError (a character YAML does not allow) has a position, no mark
    if not where and isinstance(pos, int):
        where = f" at character offset {pos}"
    return GuardError(f"{role}: not parseable YAML ({type(ex).__name__}{where})")   # never the message: it quotes the file


def parse_yaml(text: str, role: str, require_mapping: bool = True):
    cls, loader = loader_class(), None
    try:
        loader = cls(text)   # PyYAML checks for characters YAML does not allow inside the constructor (ReaderError)
        data = loader.get_single_data()
    except yaml.YAMLError as ex:
        raise _yaml_error(role, ex) from None
    finally:
        if loader is not None:
            loader.dispose()
    if require_mapping and not isinstance(data, dict):
        raise GuardError(f"{role}: the top level is not a mapping (a Lovelace dashboard is a mapping)")
    return data


def compose_yaml(text: str, role: str):
    cls, loader = loader_class(), None
    try:
        loader = cls(text)
        node = loader.get_single_node()
        anchored, keep = loader.ecco_anchored, getattr(loader, "ecco_anchor_nodes", [])
    except yaml.YAMLError as ex:
        raise _yaml_error(role, ex) from None
    finally:
        if loader is not None:
            loader.dispose()
    return node, anchored, keep


# ------------------------------------------------------------------------------------------------------------------------------
# Canonical form, hashes, pointers
# ------------------------------------------------------------------------------------------------------------------------------
def canon(obj, budget: list | None = None):
    """The JSON-ready canonical form. Identity for plain JSON data with string keys; marker keys start with NUL (a string key that
    itself starts with NUL gets one more), so no YAML input can collide with an encoded value."""
    if budget is None:
        budget = [MAX_CANON_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        raise GuardError(f"a document expands to more than {MAX_CANON_NODES} values (alias expansion?)")
    if obj is None or isinstance(obj, (bool, int, str, float)):
        return obj
    if isinstance(obj, Tagged):
        return {"\0tag": obj.tag, "\0value": canon(obj.value, budget)}
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str):
                ck = "\0" + k if k.startswith("\0") else k
            else:
                ck = "\0key:" + dumps(canon(k, budget))
            out[ck] = canon(v, budget)
        return out
    if isinstance(obj, (list, tuple)):
        return [canon(v, budget) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return {"\0timestamp": obj.isoformat()}
    if isinstance(obj, bytes):
        return {"\0binary": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, (set, frozenset)):
        return {"\0set": sorted(dumps(canon(v, budget)) for v in obj)}
    raise GuardError(f"unsupported YAML value type {type(obj).__name__}")


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canon_json(obj) -> str:
    return dumps(canon(obj))


def canon_hash(obj) -> str:
    return hashlib.sha256(canon_json(obj).encode("utf-8", "surrogatepass")).hexdigest()


def file_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def parse_pointer(p, what: str) -> list[str]:
    if not isinstance(p, str):
        raise GuardError(f"{what}: a pointer must be a string")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in p):
        raise GuardError(f"{what}: a pointer may not contain control characters")
    if p == "":
        return []
    if not p.startswith("/"):
        raise GuardError(f"{what}: pointer {safe(p)} does not start with /")
    tokens = []
    for t in p[1:].split("/"):
        if re.search(r"~(?![01])", t):
            raise GuardError(f"{what}: pointer {safe(p)} has an invalid ~ escape")
        tokens.append(t.replace("~1", "/").replace("~0", "~"))
    return tokens


def fmt_pointer(tokens) -> str:
    return "".join("/" + str(t).replace("~", "~0").replace("/", "~1") for t in tokens)


_MISSING = object()


def resolve(doc, tokens):
    cur = doc
    for t in tokens:
        if isinstance(cur, dict):
            if t not in cur:   # a str token only ever equals a str key
                return _MISSING
            cur = cur[t]
        elif isinstance(cur, list):
            if not INDEX_RE.match(t) or int(t) >= len(cur):
                return _MISSING
            cur = cur[int(t)]
        else:
            return _MISSING
    return cur


def is_scalar(v) -> bool:
    return type(v) in (str, int, float, bool)


def under(tokens, prefix) -> bool:
    return len(tokens) >= len(prefix) and list(tokens[:len(prefix)]) == list(prefix)


def validate_destination(d, what: str = "destination") -> str:
    if not isinstance(d, str) or not d:
        raise GuardError(f"{what}: must be a non-empty string")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in d) or "'" in d or '"' in d or "\\" in d:
        raise GuardError(f"{what}: control characters, quotes and backslashes are not allowed")
    parts = d.split("/")
    if not d.startswith("/config/") or d.endswith("/") or "//" in d or "." in parts or ".." in parts:
        raise GuardError(f"{what}: must be a normalised file path under /config/")
    if d.startswith(SITE_LOCAL_PREFIX):
        raise GuardError(f"{what}: {SITE_LOCAL_PREFIX} holds the site policy itself, never a dashboard")
    return d


def is_dashboard_path(d: str) -> bool:
    return d.startswith(DASHBOARD_PREFIX) and len(d) > len(DASHBOARD_PREFIX) and d.lower().endswith((".yaml", ".yml"))


# ------------------------------------------------------------------------------------------------------------------------------
# Policy (R5)
# ------------------------------------------------------------------------------------------------------------------------------
class Policy:
    def __init__(self, gate: str, entries: dict) -> None:
        self.gate, self.entries = gate, entries

    def entry(self, dest: str):
        """The entry for `dest`, or None. A destination that matches an entry only when letter case is ignored is refused: the
        host's paths are case-sensitive, so such a policy protects nothing and must not silently drop to the generic layer."""
        if dest in self.entries:
            return self.entries[dest]
        if any(d.lower() == dest.lower() for d in self.entries):
            raise GuardError("policy: names this destination only with a different letter case (a mistyped destination protects "
                             "nothing; correct the host policy)")
        return None


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise GuardError("policy: a JSON object repeats a key")
        out[k] = v
    return out


def _no_constants(name):
    raise GuardError(f"policy: {name} is not valid JSON")


def best_effort_gate(path: str) -> str:
    """The gate name of a policy that failed validation, when it can still be read safely; else the default."""
    try:
        obj = json.loads(Path(path).read_bytes().decode("utf-8-sig"))
        g = obj.get("gate") if isinstance(obj, dict) else None
        return g if isinstance(g, str) and GATE_RE.match(g) else DEFAULT_GATE
    except Exception:   # noqa: BLE001 - only used to name the gate in a refusal
        return DEFAULT_GATE


def load_policy(path: str) -> Policy:
    p = Path(path)
    try:
        if not p.is_file():
            raise GuardError("policy: not a readable file")
        if p.stat().st_size > MAX_INPUT_BYTES:
            raise GuardError("policy: too large")
        raw = p.read_bytes()
    except OSError as ex:
        raise GuardError(f"policy: cannot be read ({type(ex).__name__})") from None
    try:
        obj = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_no_dupes, parse_constant=_no_constants)
    except UnicodeDecodeError:
        raise GuardError("policy: not UTF-8") from None
    except json.JSONDecodeError as ex:
        raise GuardError(f"policy: not valid JSON ({ex.msg} at line {ex.lineno} column {ex.colno})") from None
    return validate_policy(obj)


def validate_policy(obj) -> Policy:
    if not isinstance(obj, dict):
        raise GuardError("policy: the top level is not a JSON object")
    if obj.get("schema") != SCHEMA:
        raise GuardError(f"policy: unknown or missing schema (expected {SCHEMA})")
    extra = set(obj) - POLICY_KEYS
    if extra:
        raise GuardError(f"policy: {len(extra)} unknown top-level key(s)")
    gate = obj.get("gate")
    if not isinstance(gate, str) or not GATE_RE.match(gate):
        raise GuardError("policy: gate must be an upper-case name ([A-Z][A-Z0-9_]{2,63})")
    if "note" in obj and not isinstance(obj["note"], str):
        raise GuardError("policy: note must be a string")
    dashboards = obj.get("dashboards")
    if not isinstance(dashboards, list) or not dashboards:
        raise GuardError("policy: dashboards must be a non-empty list (to retire protection, move the policy file aside)")
    entries: dict = {}
    for i, e in enumerate(dashboards, 1):
        what = f"policy dashboards[{i}]"
        if not isinstance(e, dict):
            raise GuardError(f"{what}: not an object")
        extra = set(e) - ENTRY_KEYS
        if extra:
            raise GuardError(f"{what}: {len(extra)} unknown key(s)")
        if "note" in e and not isinstance(e["note"], str):
            raise GuardError(f"{what}: note must be a string")
        dest = validate_destination(e.get("destination"), f"{what} destination")
        if dest in entries:
            raise GuardError(f"policy: duplicate destination {safe(dest)}")
        protect = e.get("protect")
        if not isinstance(protect, list) or not protect:
            raise GuardError(f"{what}: protect must be a non-empty list")
        prot = []
        for j, pr in enumerate(protect, 1):
            w = f"{what} protect[{j}]"
            if not isinstance(pr, dict) or set(pr) != {"pointer", "sha256"}:
                raise GuardError(f"{w}: must be exactly {{pointer, sha256}}")
            toks = parse_pointer(pr["pointer"], w)
            if not isinstance(pr["sha256"], str) or not SHA_RE.match(pr["sha256"]):
                raise GuardError(f"{w}: sha256 must be 64 lower-case hex digits")
            if any(t == toks for _p, t, _s in prot):
                raise GuardError(f"{w}: duplicate pointer")
            prot.append((pr["pointer"], toks, pr["sha256"]))
        overlay = e.get("overlay", [])
        if not isinstance(overlay, list):
            raise GuardError(f"{what}: overlay must be a list")
        ops = []
        for j, op in enumerate(overlay, 1):
            w = f"{what} overlay[{j}]"
            if not isinstance(op, dict) or set(op) != {"pointer", "value"}:
                raise GuardError(f"{w}: must be exactly {{pointer, value}}")
            toks = parse_pointer(op["pointer"], w)
            if not toks:
                raise GuardError(f"{w}: the whole document cannot be an overlay target")
            v = op["value"]
            if not is_scalar(v):
                raise GuardError(f"{w}: value must be a string, number or boolean")
            if isinstance(v, float) and not math.isfinite(v):
                raise GuardError(f"{w}: value must be finite")
            if isinstance(v, str):
                try:
                    v.encode("utf-8")
                except UnicodeEncodeError:
                    raise GuardError(f"{w}: value is not valid Unicode text") from None
            if not any(under(toks, t) for _p, t, _s in prot):
                raise GuardError(f"{w}: pointer is not inside a protected pointer")
            for _p, t2, _v in ops:
                if under(toks, t2) or under(t2, toks):
                    raise GuardError(f"{w}: pointer repeats or nests another overlay pointer")
            ops.append((op["pointer"], toks, v))
        reqs = e.get("require_resources", [])
        if not isinstance(reqs, list):
            raise GuardError(f"{what}: require_resources must be a list")
        urls = []
        for j, r in enumerate(reqs, 1):
            w = f"{what} require_resources[{j}]"
            if not isinstance(r, dict) or set(r) != {"url"} or not isinstance(r["url"], str) or not r["url"].strip():
                raise GuardError(f"{w}: must be exactly {{url}} with a non-empty string")
            if any(ord(c) < 0x20 or ord(c) == 0x7F for c in r["url"]):
                raise GuardError(f"{w}: url may not contain control characters")
            if r["url"] in urls:
                raise GuardError(f"{w}: duplicate url")
            urls.append(r["url"])
        entries[dest] = {"protect": prot, "overlay": ops, "require_resources": urls}
    return Policy(gate, entries)


def load_resources(path: str) -> list[str]:
    text = read_text(path, "resources")
    try:
        obj = json.loads(text.lstrip("\ufeff"))
    except json.JSONDecodeError as ex:
        raise GuardError(f"resources: not valid JSON ({ex.msg} at line {ex.lineno})") from None
    data = obj.get("data") if isinstance(obj, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise GuardError("resources: not a lovelace_resources storage file (no data.items list of objects)")
    return [i["url"] for i in items if isinstance(i.get("url"), str)]


# ------------------------------------------------------------------------------------------------------------------------------
# Rules
# ------------------------------------------------------------------------------------------------------------------------------
def custom_types(doc) -> dict:
    """{custom card type: [pointer of each `type` key that names it]} over the whole document (shared alias subtrees once)."""
    found: dict = {}
    seen: set = set()
    stack = [(doc, [])]
    while stack:
        cur, path = stack.pop()
        if isinstance(cur, (dict, list, Tagged)):
            if id(cur) in seen:
                continue
            seen.add(id(cur))
        if isinstance(cur, Tagged):
            stack.append((cur.value, path))
        elif isinstance(cur, dict):
            t = cur.get("type")
            if isinstance(t, str) and t.startswith("custom:"):
                found.setdefault(t, []).append(fmt_pointer(path + ["type"]))
            for k in reversed(list(cur)):
                stack.append((cur[k], path + [k if isinstance(k, str) else safe(repr(k))]))
        elif isinstance(cur, list):
            for i in range(len(cur) - 1, -1, -1):
                stack.append((cur[i], path + [str(i)]))
    return found


def short(h: str) -> str:
    return h[:12]


class Result:
    def __init__(self, gate: str) -> None:
        self.gate = gate
        self.blocked: list[str] = []
        self.warnings: list[str] = []
        self.ok: list[str] = []
        self.info: list[str] = []
        self.policy_state = "none"

    def lines(self) -> list[str]:
        head = f"{self.gate}: {'BLOCKED' if self.blocked else 'PASS'}"
        return ([head] + [f"  BLOCKED {safe(b)}" for b in self.blocked] + [f"  WARNING {safe(w)}" for w in self.warnings]
                + [f"  ok {safe(o)}" for o in self.ok] + [f"  info: {safe(i)}" for i in self.info])


def live_drift(res: Result, entry: dict, live) -> list[str]:
    """The R2 live findings: an ok line per protected pointer that matches the policy (added to res), and the drift of the others
    ("live protected layer differs from the site policy: ..."), returned for the caller to block or, in a drift recovery, warn."""
    drift = []
    for ptr, toks, sha in entry["protect"]:
        got = resolve(live, toks)
        if got is _MISSING:
            drift.append(f"live protected layer differs from the site policy: {ptr} is missing in live")
            continue
        h = canon_hash(got)
        if h != sha:
            drift.append(f"live protected layer differs from the site policy: {ptr} (policy {short(sha)}, live {short(h)})")
        else:
            res.ok.append(f"R2: live matches the site policy at {ptr} (sha256 {short(sha)})")
    return drift


def site_layer_live(res: Result, entry: dict, live) -> None:
    res.blocked += [f"R2: {d}" for d in live_drift(res, entry, live)]


def site_layer_candidate(res: Result, entry: dict, cand) -> None:
    for ptr, toks, sha in entry["protect"]:
        got = resolve(cand, toks)
        if got is _MISSING:
            res.blocked.append(f"R2: candidate removes or replaces a protected layer: {ptr} is missing in the candidate")
            continue
        h = canon_hash(got)
        if h != sha:
            res.blocked.append(f"R2: candidate removes or replaces a protected layer: {ptr} (policy {short(sha)}, candidate {short(h)})")
        else:
            res.ok.append(f"R2: candidate keeps the protected layer at {ptr} (sha256 {short(sha)})")


def resources_rule(res: Result, entry: dict, urls: list[str] | None) -> None:
    reqs = entry["require_resources"]
    if not reqs:
        return
    if urls is None:
        res.blocked.append(f"R3: the site policy requires {len(reqs)} resource(s) but no resources file was given")
        return
    missing = [i for i, u in enumerate(reqs, 1) if u not in urls]
    for i in missing:
        res.blocked.append(f"R3: required resource #{i} of {len(reqs)} is not registered in the resources file")
    if not missing:
        res.ok.append(f"R3: all {len(reqs)} required resource(s) are registered")


def generic_layer(res: Result, live, cand, accepted: list[str]) -> None:
    """R4. A type is named only by the pointer of its first use in live and its use count, never by its name or a hash of it (a
    short type name hashed without a salt can be confirmed by guessing); the operator reads the type in the live file."""
    lt, ct = custom_types(live), custom_types(cand)
    removed = sorted((t for t in lt if t not in ct), key=lambda t: lt[t][0])
    for t in removed:
        where = f"the type at {lt[t][0]}, {len(lt[t])} use(s) in live"
        if t in accepted:
            res.info.append(f"R4 waived by --accept-removed-type for {where}; generic layer only")
        else:
            res.blocked.append(f"R4: the candidate drops a custom card type the live dashboard uses: {where}")
    for i, t in enumerate(accepted, 1):
        if t not in removed:
            res.info.append(f"--accept-removed-type #{i} is not dropped by the candidate (nothing waived)")
    if not [t for t in removed if t not in accepted]:
        res.ok.append(f"R4: the candidate keeps every custom card type of live ({len(lt)} type(s), {len(removed)} waived)")


def run_check(args) -> tuple[Result, int]:
    dest = validate_destination(args.destination)
    accepted = list(args.accept_removed_type or [])
    for t in accepted:
        if not isinstance(t, str) or not CARD_TYPE_RE.fullmatch(t):
            raise GuardError("--accept-removed-type takes a custom card type: custom:<name>, name [A-Za-z0-9][A-Za-z0-9._-]*")
    policy = load_policy(args.policy) if args.policy else None
    entry = policy.entry(dest) if policy else None
    res = Result(policy.gate if entry else DEFAULT_GATE)
    res.policy_state = "entry" if entry else ("no-entry" if policy else "none")
    live_text, cand_text = read_text(args.live, "live"), read_text(args.candidate, "candidate")
    live, cand = parse_yaml(live_text, "live"), parse_yaml(cand_text, "candidate")
    res.ok.append(f"R1: live (sha256 {short(file_sha(live_text))}) and candidate (sha256 {short(file_sha(cand_text))}) parse as YAML mappings")
    urls = load_resources(args.resources) if args.resources else None   # a resources file that is given must be readable
    recover = bool(getattr(args, "allow_drift_recovery", False))
    if entry:
        res.info.append(f"site policy: {len(entry['protect'])} protected pointer(s), {len(entry['require_resources'])} required resource(s)")
        drift = live_drift(res, entry, live)
        at = len(res.blocked)
        site_layer_candidate(res, entry, cand)
        carries = len(res.blocked) == at   # every protected subtree of the candidate has exactly the policy's hash
        drift_rule(res, drift, carries, recover, at)
        resources_rule(res, entry, urls)
    elif policy:
        res.info.append("site policy present without an entry for this destination: generic layer only")
    else:
        res.info.append("no site policy: generic layer only")
    if recover and not entry:
        res.info.append("--allow-drift-recovery: no site policy entry for this destination (nothing to recover)")
    generic_layer(res, live, cand, accepted)
    return res, (EXIT_BLOCKED if res.blocked else EXIT_PASS)


def drift_rule(res: Result, drift: list[str], carries: bool, recover: bool, at: int) -> None:
    """R2's live half. Drift blocks (inserted before the candidate's R2 lines), unless --allow-drift-recovery was given AND the
    candidate carries the policy's protected layer exactly: then the deployment restores the site layer, and every drifted pointer
    is a WARNING. A candidate without the protected layer is never passed: its own R2 lines block it whatever the option says."""
    if not drift:
        if recover:
            res.info.append("--allow-drift-recovery: live matches the site policy (nothing to recover)")
        return
    if recover and carries:
        res.warnings += [f"R2 drift: {d}" for d in drift]
        res.warnings.append(f"drift recovery: {len(drift)} drifted protected pointer(s); the candidate restores the site policy's layer "
                            "exactly and replaces what live holds there (the live file is kept only in the deployment's backup)")
        return
    res.blocked[at:at] = [f"R2: {d}" for d in drift]
    if carries:
        res.info.append("the candidate carries the site policy's protected layer exactly: if live drifted and the policy is right, "
                        "--allow-drift-recovery (deploy-ha.ps1 -AllowDriftRecovery) restores it; if live holds newer site values, "
                        "make a new policy instead")


def run_verify_live(args) -> tuple[Result, int]:
    dest = validate_destination(args.destination)
    policy = load_policy(args.policy)
    entry = policy.entry(dest)
    if entry is None:
        raise GuardError("the site policy has no entry for this destination: nothing to verify")
    res = Result(policy.gate)
    res.policy_state = "entry"
    live_text = read_text(args.live, "live")
    live = parse_yaml(live_text, "live")
    res.ok.append(f"R1: live (sha256 {short(file_sha(live_text))}) parses as a YAML mapping")
    site_layer_live(res, entry, live)
    return res, (EXIT_BLOCKED if res.blocked else EXIT_PASS)


# ------------------------------------------------------------------------------------------------------------------------------
# apply: text edits from node marks
# ------------------------------------------------------------------------------------------------------------------------------
def emit_str(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif 0x20 <= o < 0x7F:
            out.append(ch)
        elif o <= 0xFFFF:
            out.append(f"\\u{o:04x}")
        else:
            out.append(f"\\U{o:08x}")
    out.append('"')
    return "".join(out)


def emit_scalar(v) -> str:
    if isinstance(v, bool):
        text = "true" if v else "false"
    elif isinstance(v, int):
        text = str(v)
    elif isinstance(v, float):
        text = repr(v)
        mant, _e, exp = text.partition("e")
        if _e and "." not in mant:
            text = f"{mant}.0e{exp}"
    else:
        text = emit_str(v)
    back = parse_yaml(text, "overlay value", require_mapping=False)
    if type(back) is not type(v) or canon_json(back) != canon_json(v):
        raise Refusal("an overlay value cannot be written as a YAML scalar that reads back identically")
    return text


def emit_key(k: str) -> str:
    if PLAIN_KEY_RE.match(k):
        back = parse_yaml(k, "overlay key", require_mapping=False)
        if isinstance(back, str) and back == k:
            return k
    return emit_str(k)


def _str_key_match(mapping_node, token: str, ptr: str):
    hits = [(k, v) for k, v in mapping_node.value if isinstance(k, yaml.ScalarNode) and k.tag == STR_TAG and k.value == token]
    if len(hits) > 1:
        raise Refusal(f"refuses {ptr}: a key on the path is repeated in its mapping")
    return hits[0] if hits else None


def _deep_end(node, anchored: frozenset, ptr: str) -> int:
    """The text index just after the last character of `node` (a block collection ends with its last child)."""
    while True:
        if id(node) in anchored:
            raise Refusal(f"refuses {ptr}: the last entry of the parent mapping holds an anchor or alias")
        if isinstance(node, yaml.ScalarNode):
            if node.style in ("|", ">"):
                raise Refusal(f"refuses {ptr}: the last entry of the parent mapping is a block scalar")
            return node.end_mark.index
        if node.flow_style or not node.value:
            return node.end_mark.index
        node = node.value[-1][1] if isinstance(node, yaml.MappingNode) else node.value[-1]


def apply_overlay(text: str, ops: list, doc=None) -> tuple[str, int]:
    """(new text, number of operations that changed the text). Raises Refusal; the caller verifies the post-condition."""
    if any(c in text for c in ("\x85", "\u2028", "\u2029")) or re.search(r"\r(?!\n)", text):
        raise Refusal("refuses the candidate: it uses line breaks other than LF / CRLF")
    newline = "\r\n" if "\r\n" in text else "\n"
    root, anchored, _keep = compose_yaml(text, "candidate")
    if not isinstance(root, yaml.MappingNode):
        raise Refusal("refuses the candidate: its top level is not a mapping")
    if doc is None:
        doc = parse_yaml(text, "candidate")
    edits = []
    for order, (ptr, toks, value) in enumerate(ops):
        node, chain = root, [root]
        for t in toks[:-1]:
            if isinstance(node, yaml.MappingNode):
                hit = _str_key_match(node, t, ptr)
                node = hit[1] if hit else None
            elif isinstance(node, yaml.SequenceNode) and INDEX_RE.match(t) and int(t) < len(node.value):
                node = node.value[int(t)]
            else:
                node = None
            if node is None:
                raise Refusal(f"refuses {ptr}: its parent is missing in the candidate")
            chain.append(node)
        parent = node
        if any(id(n) in anchored for n in chain):
            raise Refusal(f"refuses {ptr}: an anchor or alias is on its path")
        if not isinstance(parent, yaml.MappingNode):
            raise Refusal(f"refuses {ptr}: its parent is not a mapping (a sequence or a scalar)")
        if parent.flow_style:
            raise Refusal(f"refuses {ptr}: its parent is a flow mapping")
        if parent.tag != MAP_TAG:
            raise Refusal(f"refuses {ptr}: its parent mapping carries a tag")
        if any(k.tag == MERGE_TAG for k, _v in parent.value):
            raise Refusal(f"refuses {ptr}: its parent mapping uses a merge key")
        hit = _str_key_match(parent, toks[-1], ptr)
        if hit is not None:
            target = hit[1]
            if id(target) in anchored:
                raise Refusal(f"refuses {ptr}: the target is an anchor or alias")
            if not isinstance(target, yaml.ScalarNode) or target.tag not in CORE_SCALAR_TAGS:
                raise Refusal(f"refuses {ptr}: the target is not a plain scalar")
            if target.style in ("|", ">") or target.start_mark.line != target.end_mark.line:
                raise Refusal(f"refuses {ptr}: the target is a multi-line scalar")
            current = resolve(doc, toks)
            if current is not _MISSING and type(current) is type(value) and canon_json(current) == canon_json(value):
                continue   # already the overlay value: the text is left exactly as it is
            start, stop = target.start_mark.index, target.end_mark.index
            # An empty value (`key:` with nothing after it) has a zero-width span right after the colon: keep a space after it.
            edits.append((start, stop, (" " if start == stop else "") + emit_scalar(value), (0, 0, order)))
        else:
            if not parent.value:
                raise Refusal(f"refuses {ptr}: its parent mapping is empty")
            indent = parent.value[0][0].start_mark.column
            if any(k.start_mark.column != indent for k, _v in parent.value):
                raise Refusal(f"refuses {ptr}: the keys of its parent mapping are not aligned")
            end = _deep_end(parent.value[-1][1], anchored, ptr)
            nl = text.find("\n", end)
            line = " " * indent + emit_key(toks[-1]) + ": " + emit_scalar(value)
            # rank: at one text position a replacement comes first (it ends the line before), then insertions deepest first (an
            # insertion into a nested mapping must precede one into its parent), then the policy's order among equals.
            rank = (1, -indent, order)
            if nl < 0:   # the entry ends on the last line and the file has no final line break
                edits.append((len(text), len(text), newline + line, rank))
            else:
                edits.append((nl + 1, nl + 1, line + newline, rank))
    out = text
    # Applied from the end of the text backwards; at one position the highest rank goes in first, so the lowest ends up first.
    for start, end, repl, _rank in sorted(edits, key=lambda e: (e[0], e[3]), reverse=True):
        out = out[:start] + repl + out[end:]
    return out, len(edits)


def set_pointer(doc, toks, value) -> None:
    cur = doc
    for t in toks[:-1]:
        cur = cur[int(t)] if isinstance(cur, list) else cur[t]
    cur[toks[-1]] = value


def overlay_postcondition(cand_doc, out_text: str, entry: dict) -> list[str]:
    """[] when out_text parses to the candidate with exactly the overlay set and keeps every protect hash; else the reasons."""
    expected = copy.deepcopy(cand_doc)
    for _ptr, toks, value in entry["overlay"]:
        set_pointer(expected, toks, value)
    try:
        out_doc = parse_yaml(out_text, "result")
    except GuardError as ex:
        return [f"post-condition: the edited text is not a valid dashboard ({ex})"]
    reasons = []
    if canon_json(out_doc) != canon_json(expected):
        reasons.append("post-condition: the edited text does not parse to the candidate with exactly the overlay values set")
    probe = Result(DEFAULT_GATE)
    site_layer_candidate(probe, entry, out_doc)
    reasons += [b.replace("R2: candidate removes or replaces a protected layer",
                          "post-condition: the candidate with the overlay still differs from the protected layer") for b in probe.blocked]
    return reasons


def write_new(path: str, data: bytes, what: str) -> None:
    try:
        with open(path, "xb") as fh:
            fh.write(data)
    except FileExistsError:
        raise GuardError(f"{what}: already exists; refusing to overwrite (remove it or choose another path)") from None
    except OSError as ex:
        raise GuardError(f"{what}: cannot be written ({type(ex).__name__}; its folder must exist)") from None


def run_apply(args) -> tuple[Result, int]:
    dest = validate_destination(args.destination)
    policy = load_policy(args.policy)
    entry = policy.entry(dest)
    if entry is None:
        raise GuardError("the site policy has no entry for this destination: nothing to apply")
    if Path(args.out).exists():
        raise GuardError("--out: already exists; refusing to overwrite (remove it or choose another path)")
    res = Result(policy.gate)
    res.policy_state = "entry"
    text = read_text(args.candidate, "candidate")
    cand_doc = parse_yaml(text, "candidate")
    try:
        out, changed = apply_overlay(text, entry["overlay"], cand_doc)
    except Refusal as ex:
        res.blocked.append(f"apply {ex}")
        return res, EXIT_BLOCKED
    reasons = overlay_postcondition(cand_doc, out, entry)
    if reasons:
        res.blocked += reasons
        return res, EXIT_BLOCKED
    write_new(args.out, out.encode("utf-8", "surrogatepass"), "--out")
    res.ok.append(f"apply: {len(entry['overlay'])} overlay operation(s), {changed} changed the text; the result parses to the candidate "
                  f"plus the overlay and keeps {len(entry['protect'])} protected pointer(s)")
    res.info.append(f"written: sha256 {file_sha(out)} (candidate {file_sha(text)}); deploy this file, not the candidate")
    return res, EXIT_PASS


# ------------------------------------------------------------------------------------------------------------------------------
# make-policy
# ------------------------------------------------------------------------------------------------------------------------------
def diff(a, b, path: list, out: list) -> None:
    """Differences base `a` -> live `b`: (tokens, kind, parent_is_list); kind is value / added / removed / shape."""
    if is_scalar(a) and is_scalar(b):
        if type(a) is not type(b) or canon_json(a) != canon_json(b):
            out.append((path, "value"))
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            kt = k if isinstance(k, str) else safe(repr(k))
            if k not in b:
                out.append((path + [kt], "removed"))
            else:
                diff(a[k], b[k], path + [kt], out)
        for k in b:
            if k not in a:
                out.append((path + [k if isinstance(k, str) else safe(repr(k))], "added"))
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "shape"))
        for i in range(min(len(a), len(b))):
            diff(a[i], b[i], path + [str(i)], out)
        return
    if canon_json(a) != canon_json(b):
        out.append((path, "shape"))


def run_make_policy(args) -> tuple[Result, int]:
    gate = args.gate
    if not isinstance(gate, str) or not GATE_RE.match(gate):
        raise GuardError("--gate must be an upper-case name ([A-Z][A-Z0-9_]{2,63})")
    dest = validate_destination(args.destination)
    ptoks = parse_pointer(args.pointer, "--pointer")
    if not ptoks:
        raise GuardError("--pointer must name a subtree, not the whole document")
    if Path(args.out).exists():
        raise GuardError("--out: already exists; refusing to overwrite (remove it or choose another path)")
    res = Result(gate)
    base_text, live_text = read_text(args.base, "base"), read_text(args.live, "live")
    base, live = parse_yaml(base_text, "base"), parse_yaml(live_text, "live")
    if resolve(live, ptoks) is _MISSING or resolve(base, ptoks) is _MISSING:
        res.blocked.append(f"make-policy: {fmt_pointer(ptoks)} is missing in the base or in live")
        return res, EXIT_BLOCKED
    diffs: list = []
    diff(base, live, [], diffs)
    outside = [fmt_pointer(t) for t, _k in diffs if not under(t, ptoks)]
    for p in outside[:50]:
        res.blocked.append(f"make-policy: live differs from the base outside {fmt_pointer(ptoks)} at {p}")
    if len(outside) > 50:
        res.blocked.append(f"make-policy: ... {len(outside) - 50} more difference(s) outside the pointer")
    overlay = []
    for toks, kind in diffs:
        if not under(toks, ptoks):
            continue
        p = fmt_pointer(toks)
        parent = resolve(live, toks[:-1]) if toks else None
        value = resolve(live, toks)
        if kind == "removed":
            res.blocked.append(f"make-policy: live removes {p}, which an overlay cannot express")
        elif kind == "shape" or not is_scalar(value):
            res.blocked.append(f"make-policy: the difference at {p} is not a scalar leaf")
        elif not isinstance(parent, dict):
            res.blocked.append(f"make-policy: the differing leaf {p} sits in a sequence")
        elif isinstance(value, float) and not math.isfinite(value):
            res.blocked.append(f"make-policy: the value at {p} is not finite")
        else:
            overlay.append({"pointer": p, "value": value})
    if res.blocked:
        return res, EXIT_BLOCKED
    entry_obj = {"destination": dest, "protect": [{"pointer": fmt_pointer(ptoks), "sha256": canon_hash(resolve(live, ptoks))}],
                 "overlay": overlay}
    if args.require_resource:
        entry_obj["require_resources"] = [{"url": u} for u in args.require_resource]
    policy_obj = {"schema": SCHEMA, "gate": gate, "dashboards": [entry_obj]}
    policy = validate_policy(json.loads(json.dumps(policy_obj)))
    entry = policy.entries[dest]
    # Prove the policy before writing it: live passes R2, and apply(base) parses to live.
    probe = Result(gate)
    site_layer_live(probe, entry, live)
    try:
        out, _changed = apply_overlay(base_text, entry["overlay"], base)
        reasons = overlay_postcondition(base, out, entry)
        if not reasons and canon_json(parse_yaml(out, "result")) != canon_json(live):
            reasons.append("post-condition: apply(base) does not parse to live")
    except Refusal as ex:
        reasons = [f"apply(base) {ex}"]
    if probe.blocked or reasons:
        res.blocked += probe.blocked + [f"make-policy: the policy is not usable: {r}" for r in reasons]
        return res, EXIT_BLOCKED
    write_new(args.out, (json.dumps(policy_obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), "--out")
    res.ok.append(f"make-policy: protect {fmt_pointer(ptoks)} (sha256 {short(entry['protect'][0][2])}), {len(overlay)} overlay "
                  f"operation(s), {len(entry['require_resources'])} required resource(s); apply(base) parses to live")
    for op in overlay:
        res.info.append(f"overlay pointer {op['pointer']}")
    res.info.append("the policy holds site values: keep it local, never commit or publish it")
    return res, EXIT_PASS


def run_classify(args) -> tuple[list[str], int]:
    dest = validate_destination(args.destination)
    policy = load_policy(args.policy) if args.policy else None
    named = bool(policy and policy.entry(dest) is not None)
    gate = policy.gate if named else DEFAULT_GATE
    # Every destination the policy names (validated: no quote, backslash or control character), so the deploy tool can prove that
    # each exists on the host: a mistyped destination would otherwise protect nothing without a word.
    listing = ([f"policy destinations: {len(policy.entries)}"] + [f"policy destination: {d}" for d in policy.entries]) if policy else []
    if named:
        return [f"gate: {gate}", "dashboard destination: yes (site policy entry)"] + listing, EXIT_PASS
    if is_dashboard_path(dest):
        return [f"gate: {gate}", "dashboard destination: yes (under /config/ecco/dashboards/, .yaml / .yml)"] + listing, EXIT_PASS
    return [f"gate: {gate}", "dashboard destination: no"] + listing, EXIT_NOT_DASHBOARD


# ------------------------------------------------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------------------------------------------------
class UsageError(Exception):
    pass


KNOWN_OPTIONS: set = set()   # every option name the parser defines (filled by build_parser)
COMMANDS = ("check", "apply", "make-policy", "verify-live", "classify")


def redact_usage(message: str) -> str:
    """argparse's message without any argument value (a mistyped private URL or card type must never be echoed): option names
    this tool defines are kept, every other token is only counted."""
    if re.fullmatch(r"the following arguments are required: --[a-z-]+(, --[a-z-]+)*", message):
        return message
    m = re.match(r"argument (--[a-z][a-z-]*)(?:/[^:]*)?: ", message)
    if m and m.group(1) in KNOWN_OPTIONS:
        if message[m.end():] in ("expected one argument", "expected at least one argument"):
            return f"argument {m.group(1)}: {message[m.end():]}"
        return f"argument {m.group(1)}: invalid value (not shown)"
    if message.startswith("argument ") and "invalid choice" in message:
        return f"invalid command (not shown); the commands are {', '.join(COMMANDS)}"
    if message.startswith("unrecognized arguments: "):
        toks = message[len("unrecognized arguments: "):].split()
        known = [t for t in toks if t in KNOWN_OPTIONS]
        named = f"; option name(s) among them: {' '.join(known)}" if known else ""
        return f"{len(toks)} unrecognized argument token(s), values not shown{named}"
    return "malformed arguments (values not shown)"


class Parser(argparse.ArgumentParser):
    def error(self, message):   # never argparse's own exit: the first line must still say BLOCKED; never an argument value
        raise UsageError(redact_usage(message))


def build_parser() -> Parser:
    # No -h (argparse's help exits 0, and 0 means PASS) and no abbreviated options: an option is spelled out or it is refused.
    ap = Parser(prog="ecco_dashboard_guard.py", description="Fail-closed dashboard preservation gate (see the module docstring).",
                add_help=False, allow_abbrev=False)
    sub = ap.add_subparsers(dest="command", parser_class=Parser)

    def command(name: str) -> Parser:
        return sub.add_parser(name, add_help=False, allow_abbrev=False)

    c = command("check")
    c.add_argument("--destination", required=True)
    c.add_argument("--live", required=True)
    c.add_argument("--candidate", required=True)
    c.add_argument("--policy")
    c.add_argument("--resources")
    c.add_argument("--accept-removed-type", action="append", default=[])
    c.add_argument("--allow-drift-recovery", action="store_true")
    c.add_argument("--json")
    a = command("apply")
    a.add_argument("--policy", required=True)
    a.add_argument("--destination", required=True)
    a.add_argument("--candidate", required=True)
    a.add_argument("--out", required=True)
    m = command("make-policy")
    m.add_argument("--gate", required=True)
    m.add_argument("--destination", required=True)
    m.add_argument("--base", required=True)
    m.add_argument("--live", required=True)
    m.add_argument("--pointer", required=True)
    m.add_argument("--require-resource", action="append", default=[])
    m.add_argument("--out", required=True)
    v = command("verify-live")
    v.add_argument("--policy", required=True)
    v.add_argument("--destination", required=True)
    v.add_argument("--live", required=True)
    k = command("classify")
    k.add_argument("--destination", required=True)
    k.add_argument("--policy")
    for p in (c, a, m, v, k):
        KNOWN_OPTIONS.update(o for o in p._option_string_actions if o.startswith("--"))
    return ap


def _gate_for_error(args) -> str:
    """The gate a refusal is printed under: the policy's when it has an entry for the destination (best effort for a policy that
    failed validation), make-policy's --gate, else the default."""
    if args is None:
        return DEFAULT_GATE
    if getattr(args, "command", None) == "make-policy":
        g = getattr(args, "gate", None)
        return g if isinstance(g, str) and GATE_RE.match(g) else DEFAULT_GATE
    pol = getattr(args, "policy", None)
    if not pol:
        return DEFAULT_GATE
    try:
        policy = load_policy(pol)
    except Exception:   # noqa: BLE001 - a policy that failed validation: name its gate if it can be read safely
        return best_effort_gate(pol)
    return policy.gate if getattr(args, "destination", None) in policy.entries else DEFAULT_GATE


def write_report(path: str, command: str, gate: str, code: int, res: Result | None, error: str | None, dest: str | None) -> None:
    report = {"schema": REPORT_SCHEMA, "command": command, "gate": gate, "result": "PASS" if code == EXIT_PASS else "BLOCKED",
              "exit_code": code, "destination": dest, "policy": res.policy_state if res else None,
              "blocked": [safe(b) for b in res.blocked] if res else [], "warnings": [safe(w) for w in res.warnings] if res else [],
              "ok": [safe(o) for o in res.ok] if res else [],
              "info": [safe(i) for i in res.info] if res else [], "error": safe(error) if error else None}
    try:
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as ex:
        print(f"  info: the --json report could not be written ({type(ex).__name__})")


def main(argv: list[str] | None = None) -> int:
    args = None
    try:
        args = build_parser().parse_args(argv)
        if not args.command:
            raise UsageError("a command is required: check, apply, make-policy, verify-live or classify")
        if args.command == "classify":
            lines, code = run_classify(args)
            print("\n".join(safe(ln) for ln in lines))
            return code
        loader_class()
        runner = {"check": run_check, "apply": run_apply, "make-policy": run_make_policy, "verify-live": run_verify_live}[args.command]
        res, code = runner(args)
        print("\n".join(res.lines()))
        if getattr(args, "json", None):
            write_report(args.json, args.command, res.gate, code, res, None, args.destination)
        return code
    except (GuardError, UsageError) as ex:
        error = f"{'usage error' if isinstance(ex, UsageError) else 'refused'}: {ex}"
    except RecursionError:
        error = "refused: a document is nested too deeply"
    except Exception as ex:   # noqa: BLE001 - fail closed on anything unexpected; never echo its message (it may quote a file)
        error = f"internal error: {type(ex).__name__}"
    gate = _gate_for_error(args)
    print(f"{gate}: BLOCKED")
    print(f"  BLOCKED {safe(error)}")
    if args is not None and getattr(args, "json", None):
        write_report(args.json, args.command, gate, EXIT_ERROR, None, error, getattr(args, "destination", None))
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
