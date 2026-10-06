#!/usr/bin/env python3
"""Support code of registry/tests/test_fallback_save_static_pins.py (the FB-B2 STATIC pin suite).

No test logic and no expectation about the firmware lives here: only text tools (comment / string stripping, bracket
matching, assignment / publish / literal / log-call extraction), the C++ POD struct parser, the firmware context `Ctx`
(one firmware text parsed once, every lambda located by a STABLE STRUCTURAL NAME), the pre-FB-B2 base derivation (git
base commit, hash-pinned to the FB-T0 fbb1 checkpoint, with the chain reverter as the git-less fallback) and the
exact-count mutation helpers.

Everything is text / parsed-YAML analysis. No firmware is compiled, no simulator is run, nothing is written outside
a TemporaryDirectory (the write-surface analyzer copy). The suite never reads firmware/secrets.yaml.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (HERE, HERE.parent, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _dump_sim as ds  # noqa: E402
import _scope_chain as chain  # noqa: E402

FW_REL = chain.FIRMWARE
FW_PATH = ROOT / FW_REL
INCLUDE_DIR = ROOT / "firmware" / "include"
SAVE_HEADER = INCLUDE_DIR / "ecco_fallback_save.h"
CAP_HEADER = INCLUDE_DIR / "ecco_fallback_capture.h"
DURABLE_HEADER = INCLUDE_DIR / "ecco_fallback_durable.h"
MODEL_HEADER = INCLUDE_DIR / "ecco_fallback_durable_model.h"


# ===========================================================================
# C++ text helpers (comment-stripped, bracket-matched)
# ===========================================================================
def strip_cpp(code: str) -> str:
    """Remove // and /* */ comments, keeping string / character literals intact."""
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c in "\"'":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            out.append(code[i:j + 1])
            i = j + 1
        elif code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def strip_code(text: str) -> str:
    """strip_cpp, and string / character literal CONTENT removed (an NVS name inside a message is not a call)."""
    s = strip_cpp(text)
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in "\"'":
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if s[j] == "\\" else 1
            out.append(c + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def norm(code: str) -> str:
    """Comment-free, whitespace-collapsed C++."""
    return " ".join(strip_cpp(code).split())


def sq(code: str) -> str:
    """Comment-free C++ with ALL whitespace removed: what an exact-shape `in` / order pin compares (both sides squashed)."""
    return re.sub(r"\s+", "", strip_cpp(code))


def has(code: str, expected: str) -> bool:
    return sq(expected) in sq(code)


def order_of(code: str, parts) -> list[int]:
    s = sq(code)
    return [s.find(sq(p)) for p in parts]


def in_order(code: str, parts) -> bool:
    pos = order_of(code, parts)
    return min(pos) >= 0 and pos == sorted(pos) and len(set(pos)) == len(pos)


def close_of(code: str, i: int) -> int:
    """Index of the bracket closing the one at code[i] (code is comment-stripped)."""
    op = code[i]
    cl = {"(": ")", "{": "}", "[": "]"}[op]
    depth, j, n = 0, i, len(code)
    while j < n:
        c = code[j]
        if c in "\"'":
            j += 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
        elif c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError(f"unbalanced {op!r} at {i}")


def block_after(code: str, marker: str) -> tuple[int, int]:
    """(start, end) indexes of the `{ ... }` that `marker` (ending in `{`) opens; ValueError if absent / not unique."""
    n = code.count(marker)
    if n != 1:
        raise ValueError(f"marker found {n}x: {marker[:60]!r}")
    i = code.index(marker) + len(marker) - 1
    return i, close_of(code, i)


def sq_block(code: str, marker: str) -> str:
    """The squashed text of the `{ ... }` block opened by the (squashed) marker, braces included."""
    s = sq(code)
    a, b = block_after(s, sq(marker))
    return s[a:b + 1]


def call_args(code: str, name_regex: str, nth: int = 0) -> list[str]:
    """The top-level arguments (squashed) of the nth call matching `name_regex(`, comments stripped."""
    s = strip_cpp(code)
    ms = list(re.finditer(name_regex + r"\s*\(", s))
    if len(ms) <= nth:
        raise ValueError(f"call {name_regex} #{nth} not found")
    o = ms[nth].end() - 1
    return [re.sub(r"\s+", "", a) for a in split_args(s[o + 1:close_of(s, o)])]


def split_args(text: str) -> list[str]:
    """Top-level comma split of a call's argument text (string / character literals, (), [] and {} respected)."""
    out, cur, depth, i, n = [], [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            cur.append(text[i:j + 1])
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [a.strip() for a in out]


ASSIGN = re.compile(r"(?<![\w.])id\(\s*(\w+)\s*\)\s*(?:\[[^\]\n]*\]\s*)?(?:=(?!=)|\+=|-=|\*=|/=|%=|\|=|&=|\^=|<<=|>>=|\+\+|--)")
PREINC = re.compile(r"(?:\+\+|--)\s*id\(\s*(\w+)\s*\)")
MUTATING_CALL = re.compile(r"\bid\(\s*(\w+)\s*\)\s*\.\s*(?:clear|append|push_back|pop_back|emplace_back|assign|resize|reserve|fill|swap|insert|erase|replace)\s*\(")


def assigned(code: str) -> set[str]:
    code = strip_cpp(code)
    return set(ASSIGN.findall(code)) | set(PREINC.findall(code)) | set(MUTATING_CALL.findall(code))


def rhs_of(code: str, name: str) -> list[str]:
    """Squashed right-hand sides of every plain `id(name) = <rhs>;` in the code."""
    return [re.sub(r"\s+", "", m.group(1)) for m in re.finditer(r"(?<![\w.])id\(\s*%s\s*\)\s*=(?!=)\s*([^;]+);" % re.escape(name), strip_cpp(code))]


def ids_of(code: str) -> set[str]:
    return set(re.findall(r"\bid\(\s*(\w+)\s*\)", strip_cpp(code)))


def publishes(code: str) -> set[str]:
    return set(re.findall(r"\bid\(\s*(\w+)\s*\)\s*\.\s*publish_state\s*\(", strip_cpp(code)))


def publish_args(code: str, entity: str) -> list[str]:
    """Squashed argument of every `id(<entity>).publish_state(<arg>)` call."""
    s = strip_cpp(code)
    out = []
    for m in re.finditer(r"\bid\(\s*%s\s*\)\s*\.\s*publish_state\s*\(" % re.escape(entity), s):
        o = m.end() - 1
        out.append(re.sub(r"\s+", "", s[o + 1:close_of(s, o)]))
    return out


def literals(code: str) -> list[str]:
    """Every string literal (double quotes) of the comment-free code."""
    return re.findall(r'"((?:[^"\\]|\\.)*)"', strip_cpp(code))


LOG_RX = re.compile(r"\bESP_LOG([A-Z])\s*\(")


def log_calls(code: str) -> list[dict]:
    """Every ESP_LOG* call (comments stripped): level letter, tag literal text (None if not a plain literal), format literal
    (None if not a plain literal), the remaining argument texts (squashed) and the [start, end) span in the comment-free text."""
    src = strip_cpp(code)
    out = []
    for m in LOG_RX.finditer(src):
        o = m.end() - 1
        e = close_of(src, o)
        args = split_args(src[o + 1:e])

        def lit(a):
            return a[1:-1] if len(a) >= 2 and a[0] == '"' and a[-1] == '"' else None

        out.append({"level": m.group(1), "tag": lit(args[0]) if args else None, "fmt": lit(args[1]) if len(args) > 1 else None,
                    "args": [re.sub(r"\s+", "", a) for a in args[2:]], "start": m.start(), "end": e + 1, "src": src})
    return out


def enclosing_headers(code: str, pos: int) -> list[str]:
    """The statement headers (the text before each `{`) of every block that encloses `pos` in comment-free code."""
    stack: list[str] = []
    last = 0
    i, paren = 0, 0
    while i < pos and i < len(code):
        c = code[i]
        if c in "\"'":
            j = i + 1
            while j < len(code) and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            i = j + 1
            continue
        if c == "(":
            paren += 1
        elif c == ")":
            paren -= 1
        elif c == "{":
            stack.append(" ".join(code[last:i].split()))
            last = i + 1
        elif c == "}":
            if stack:
                stack.pop()
            last = i + 1
        elif c == ";" and paren <= 0:
            last = i + 1
        i += 1
    return stack


# ===========================================================================
# C++ POD struct parser (field lists of the pinned input structs)
# ===========================================================================
def parse_structs(text: str) -> dict[str, list[tuple[str, str]]]:
    """name -> [(type, field)] of every `struct NAME { ... };` of the header text (one field per line, `//` comments removed)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for m in re.finditer(r"^struct (\w+) \{(.*?)^\};", text, re.S | re.M):
        fields = []
        for line in m.group(2).splitlines():
            line = line.split("//")[0].strip()
            fm = re.match(r"^([\w:<>, ]+?)\s+(\w+)\s*(?:=[^;]*|\{[^;]*\})?;$", line)
            if fm:
                fields.append((fm.group(1).strip().replace("ecco_fbcap::", "").replace("ecco_fallback::", "").replace("ecco_fbdurable::", ""), fm.group(2)))
        out[m.group(1)] = fields
    return out


def flat_fields(structs: dict, name: str, prefix: str = "") -> list[str]:
    """Every leaf field of struct `name` (nested structs flattened with dots)."""
    res = []
    for typ, field in structs[name]:
        if typ in structs:
            res += flat_fields(structs, typ, f"{prefix}{field}.")
        else:
            res.append(prefix + field)
    return res


def var_assignments(code: str, var: str) -> dict[str, str]:
    """`<var>.<field> = <rhs>;` statements of the comment-free code -> {field: squashed rhs} (a repeated field keeps the last)."""
    out = {}
    for m in re.finditer(r"\b%s\.([A-Za-z_][\w.]*)\s*=(?!=)\s*([^;]+);" % re.escape(var), strip_cpp(code)):
        out[m.group(1)] = re.sub(r"\s+", "", m.group(2))
    return out


def var_assignment_count(code: str, var: str) -> dict[str, int]:
    c: dict[str, int] = {}
    for m in re.finditer(r"\b%s\.([A-Za-z_][\w.]*)\s*=(?!=)" % re.escape(var), strip_cpp(code)):
        c[m.group(1)] = c.get(m.group(1), 0) + 1
    return c


# ===========================================================================
# Firmware text: raw regions, lambda enumeration
# ===========================================================================
def lam_of(action) -> str:
    return action["lambda"] if isinstance(action, dict) and isinstance(action.get("lambda"), str) else ""


def raw_script_span(text: str, sid: str) -> tuple[int, int]:
    """[start, end) of one script list item in the RAW text (from `  - id: <sid>` to the next item / top-level key)."""
    m = re.search(r"^  - id: %s\n" % re.escape(sid), text, re.M)
    if not m:
        raise ValueError(f"script {sid} not found in the raw text")
    nxt = re.search(r"^(?:  - id: |\S)", text[m.end():], re.M)
    return m.start(), m.end() + (nxt.start() if nxt else len(text) - m.end())


def raw_script_block(text: str, sid: str) -> str:
    a, b = raw_script_span(text, sid)
    return text[a:b]


def raw_api_action(text: str, name: str) -> str:
    """The RAW text of one api action (its leading comment block included) up to the next action / top-level key."""
    m = re.search(r"^    - action: %s\n" % re.escape(name), text, re.M)
    if not m:
        return ""
    start = m.start()
    # walk back over the comment lines that belong to it
    while True:
        prev = text.rfind("\n", 0, start - 1)
        line = text[prev + 1:start]
        if line.lstrip().startswith("#"):
            start = prev + 1
        else:
            break
    nxt = re.search(r"^(?:    - action: |\S)", text[m.end():], re.M)
    return text[start: m.end() + (nxt.start() if nxt else len(text) - m.end())]


def raw_switch_block(text: str, sid: str) -> str:
    """RAW text of one template switch (comment block above it included) up to the next list item / top-level key."""
    m = re.search(r"^  - platform: template\n(?:    [^\n]*\n)*?    id: %s\n" % re.escape(sid), text, re.M)
    if not m:
        return ""
    start = m.start()
    while True:
        prev = text.rfind("\n", 0, start - 1)
        line = text[prev + 1:start]
        if line.lstrip().startswith("#"):
            start = prev + 1
        else:
            break
    nxt = re.search(r"^(?:  - platform: |\S)", text[m.end():], re.M)
    return text[start: m.end() + (nxt.start() if nxt else len(text) - m.end())]


def walk_lambdas(fw: dict) -> list[tuple[str, str]]:
    """Every lambda of the parsed firmware with a STABLE structural name, document order. Names: `script:<id>.then[i]...`,
    `api:<action>...`, `switch:<id>...`, `interval[i]...`, `esphome.on_boot...`; other sections use `<section>[i]`."""
    out: list[tuple[str, str]] = []
    labelled = {"script": "id", "switch": "id", "globals": "id", "number": "id", "select": "id", "button": "id", "text_sensor": "id",
                "sensor": "id", "binary_sensor": "id"}

    def rec(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "lambda" and isinstance(v, str):
                    out.append((path or "<root>", v))
                else:
                    rec(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                rec(v, f"{path}[{i}]")

    for sect, body in fw.items():
        if sect.startswith("_"):
            continue
        if sect in labelled and isinstance(body, list):
            for i, item in enumerate(body):
                name = item.get(labelled[sect]) if isinstance(item, dict) else None
                rec(item, f"{sect}:{name}" if name else f"{sect}[{i}]")
        elif sect == "api" and isinstance(body, dict):
            for k, v in body.items():
                if k == "actions" and isinstance(v, list):
                    for i, item in enumerate(v):
                        rec(item, f"api:{item.get('action', i)}" if isinstance(item, dict) else f"api.actions[{i}]")
                else:
                    rec(v, f"api.{k}")
        else:
            rec(body, sect)
    return out


FB_SYMBOLS = re.compile(r"fallback_profile_|fallback_witness_|fallback_durable_|ecco_fbsave::|ecco_fbcap::|ecco_fbdurable::|ecco_fallback::")
FB_NAME = re.compile(r"^(?:script:fallback_profile_|api:fallback_profile_|switch:fallback_profile_)")


def is_fb_lambda(name: str, code: str) -> bool:
    return bool(FB_NAME.match(name)) or bool(FB_SYMBOLS.search(strip_cpp(code)))


class Ctx:
    """One firmware text parsed once with every FB-B lambda located by name. Locating NEVER raises on a damaged structure
    (a mutant): a missing role is an empty string / None and the detector that needs it reports the damage."""

    def __init__(self, text: str, overrides: dict | None = None):
        self.text = text
        self.overrides = dict(overrides or {})   # repo-relative path -> replacement text (header / mirror mutants)
        self.fw = ds.load_firmware_text(text)
        fw = self.fw
        self.sc = {s["id"]: s for s in fw["script"]}
        self.all_lams = walk_lambdas(fw)
        self.lams = dict(self.all_lams)
        self.fb = {n: c for n, c in self.all_lams if is_fb_lambda(n, c)}
        self.review = self.sc.get("fallback_profile_review", {})
        self.disp = self.sc.get("fallback_profile_capture_dispatch", {})
        self.inv_cand = self.sc.get("fallback_profile_invalidate_candidate", {})
        self.save = self.sc.get("fallback_profile_save", {})
        self.inv = self.sc.get("fallback_profile_invalidate", {})
        self.review_then = self.review.get("then") or []
        self.top = self.disp.get("then") or []
        self.save_then = self.save.get("then") or []
        self.inv_then = self.inv.get("then") or []
        self.review_lam = lam_of(self.review_then[0]) if self.review_then else ""
        self.save_lam = lam_of(self.save_then[0]) if self.save_then else ""
        self.inv_lam = lam_of(self.inv_then[0]) if self.inv_then else ""
        # dispatch tail: [drain if] [REVIEW_FINAL] [SAVE part 1] [SAVE part 2] [RELEASE]
        self.drain_if = self.top[-5] if len(self.top) >= 5 else {}
        self.review_final = lam_of(self.top[-4]) if len(self.top) >= 4 else ""
        self.save_p1 = lam_of(self.top[-3]) if len(self.top) >= 3 else ""
        self.save_p2 = lam_of(self.top[-2]) if len(self.top) >= 2 else ""
        self.release = lam_of(self.top[-1]) if self.top else ""
        ivs = [iv for iv in fw.get("interval") or [] if "fallback_profile_cand_valid" in repr(iv.get("then"))]
        self.interval = ivs[0] if len(ivs) == 1 else None
        self.n_marked_intervals = len(ivs)
        self.interval_index = (fw["interval"].index(self.interval) if self.interval is not None else -1)
        itl = (self.interval or {}).get("then") or []
        self.tick1 = lam_of(itl[0]) if len(itl) > 0 else ""
        self.tick2 = lam_of(itl[1]) if len(itl) > 1 else ""
        self.boot_then = ((fw.get("esphome") or {}).get("on_boot") or {}).get("then") or []
        self.boot = lam_of(self.boot_then[3]) if len(self.boot_then) > 3 else ""
        actions = (fw.get("api") or {}).get("actions") or []
        self.api_actions = actions
        self.api_act = actions[-1] if actions else {}
        api_then = self.api_act.get("then") or []
        self.api_lam = lam_of(api_then[0]) if api_then else ""
        self.api_if = (api_then[1].get("if") if len(api_then) > 1 and isinstance(api_then[1], dict) else None) or {}
        self.arm = next((s for s in fw.get("switch") or [] if s.get("id") == "fallback_profile_arm"), None)

    def file(self, rel: str) -> str:
        """A repo text file (LF) - the override of this context when there is one, else the disk copy."""
        if rel in self.overrides:
            return self.overrides[rel]
        return (ROOT / rel).read_text(encoding="utf-8")

    def name_of(self, code: str) -> str:
        for n, c in self.all_lams:
            if c == code and code:
                return n
        return "?"

    def fb_named(self, prefix: str) -> dict[str, str]:
        return {n: c for n, c in self.fb.items() if n.startswith(prefix)}


# ===========================================================================
# The pre-FB-B2 base (git base commit, hash-pinned; the chain reverter when git / the commit is not available)
# ===========================================================================
BASE_COMMIT = "65e4be5"   # main at the start of FB-B2 (FB-B1 merged): the chain's fbb1 checkpoint
FBB2_COMMIT = "87e6151fa04a2cada568ef6c36a871a8ffcc7303"  # FB-B2 merge on main: exact historical state under test


def base_checkpoint() -> str:
    return chain.CHAIN.checkpoint(FW_REL, "fbb1")


def base_text(fbb2_text: str) -> tuple[str | None, str, str]:
    """-> (text, source, why). Candidates in order: `git show <BASE_COMMIT>:<fw>`, `git show HEAD:<fw>`, the chain's fbb1 state of
    `fbb2_text` = the firmware AS OF fbb2 (what live_text() returns; only when a later chain entry exists). A candidate is ACCEPTED
    ONLY if its sha256 is the chain's pinned fbb1 checkpoint, so the base never depends on the edits it is compared with. The suite
    FAILS (never skips) when none matches.
    FRESH-HISTORY: the chain candidate undoes ONLY the entries after fbb1 up to fbb2 (the chain as it was when FB-B2 merged). The
    full chain would also apply the FB-C2 / FB-D1 / ... reverters to a text that never had those edits, and fail, in any clone
    without BASE_COMMIT (test_fresh_history_fallback.py)."""
    want = base_checkpoint()
    tried = []
    for ref in (BASE_COMMIT, "HEAD"):
        try:
            r = subprocess.run(["git", "show", f"{ref}:{FW_REL}"], capture_output=True, cwd=str(ROOT), timeout=60)
        except (OSError, subprocess.SubprocessError) as ex:
            tried.append(f"git show {ref}: {type(ex).__name__}")
            continue
        if r.returncode != 0:
            tried.append(f"git show {ref}: rc={r.returncode}")
            continue
        got = hashlib.sha256(r.stdout).hexdigest()
        if got == want:
            return r.stdout.decode("utf-8").replace("\r\n", "\n"), f"git {ref}", ""
        tried.append(f"git show {ref}: sha {got[:12]} != {want[:12]}")
    if "fbb2" in chain.CHAIN.ids():
        try:
            t = chain.Chain(chain.CHAIN.upto("fbb2")).as_of(FW_REL, "fbb1", fbb2_text)
            if chain.sha(t) == want:
                return t, "chain fbb1 reverter", ""
            tried.append("chain reverter: sha mismatch")
        except AssertionError as ex:
            tried.append(f"chain reverter: {str(ex)[:80]}")
    return None, "", "; ".join(tried) or "no source"


def live_text() -> str:
    """The firmware exactly as FB-B2 left it.

    Prefer the immutable FB-B2 merge commit and hash-check it against the scope
    chain checkpoint. This keeps the FB-B2 mutation/static suite historical even
    when later firmware legitimately changes the same anchors. Fall back to the
    chain reverter for git-less environments.
    """
    disk = FW_PATH.read_text(encoding="utf-8")
    if "fbb2" not in chain.CHAIN.ids():
        return disk

    want = chain.CHAIN.checkpoint(FW_REL, "fbb2")
    try:
        r = subprocess.run(["git", "show", f"{FBB2_COMMIT}:{FW_REL}"], capture_output=True, cwd=str(ROOT), timeout=60)
        if r.returncode == 0:
            got = hashlib.sha256(r.stdout).hexdigest()
            if got == want:
                return r.stdout.decode("utf-8").replace("\r\n", "\n")
    except (OSError, subprocess.SubprocessError):
        pass

    t = chain.CHAIN.as_of(FW_REL, "fbb2", disk)
    if chain.sha(t) != want:
        raise AssertionError("FB-B2 historical firmware does not match the pinned fbb2 checkpoint")
    return t


# ===========================================================================
# Mutation helpers: an anchor must occur EXACTLY `count` times, so a mutant can never be a silent no-op
# ===========================================================================
def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    n = text.count(old)
    if n != count:
        raise AssertionError(f"mutation anchor occurs {n}x (want {count}): {old[:80]!r}")
    return text.replace(old, new)


def mutate_in(text: str, span: tuple[int, int], old: str, new: str, count: int = 1) -> str:
    """Replace `old` -> `new` only inside text[span[0]:span[1]]; the anchor must occur exactly `count` times THERE."""
    a, b = span
    seg = text[a:b]
    n = seg.count(old)
    if n != count:
        raise AssertionError(f"mutation anchor occurs {n}x inside the region (want {count}): {old[:80]!r}")
    return text[:a] + seg.replace(old, new) + text[b:]


def mutate_script(text: str, sid: str, old: str, new: str, count: int = 1) -> str:
    return mutate_in(text, raw_script_span(text, sid), old, new, count)


def region(text: str, start_marker: str, end_marker: str) -> tuple[int, int]:
    """[start, end) of the raw text from the unique `start_marker` to the next `end_marker` after it."""
    if text.count(start_marker) != 1:
        raise AssertionError(f"region start occurs {text.count(start_marker)}x: {start_marker[:60]!r}")
    a = text.index(start_marker)
    b = text.index(end_marker, a + len(start_marker))
    return a, b
