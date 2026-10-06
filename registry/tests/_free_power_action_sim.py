"""Shared ESPHome action-tree extraction + restricted lambda interpreter for
Free Power firmware behavioural tests.

Factored out of registry/tests/test_free_power_tou_power_ownership_2026_09_23.py
(2026-09-24, independent-review fix round R2) so that
test_free_power_reg244_context_v4.py can reuse the SAME proven machinery for
the register-244 context-gate behavioural tests, rather than either
duplicating it or - the thing the review specifically flagged - stripping
the gates out of the action tree before simulation. Extended in this pass to
understand the new statement/condition shapes the register-244 context
gates introduced (integer comparisons, `id(x) = <int literal>;`,
`id(x) = values[N];`).

No I/O, no hardware, no ESPHome/C++ toolchain. This is a small, explicitly
restricted interpreter over the REAL extracted firmware action tree: it
raises `UnsupportedLambda` on any construct it does not recognise, rather
than guessing - a firmware change that introduces new control flow into
whatever it is pointed at should fail this loudly, not silently pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WRITE = "modbus_client.write_multiple_registers"
READ = "modbus_client.read_holding_registers"


# ---------------------------------------------------------------------------
# YAML -> real ESPHome action tree (unknown tags such as !lambda / !secret
# are kept as plain values).
# ---------------------------------------------------------------------------
class _FirmwareLoader(yaml.SafeLoader):
    pass


def _tagged(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_FirmwareLoader.add_multi_constructor("!", _tagged)


def load_scripts(firmware_path: Path) -> tuple[str, dict]:
    """Returns (raw_text, {script_id: script_node})."""
    text = firmware_path.read_text(encoding="utf-8")
    doc = yaml.load(text, Loader=_FirmwareLoader)
    return text, {s["id"]: s for s in doc["script"]}


def script_body(fw_text: str, script_id: str) -> str:
    """Extract one `- id: <script_id>` script's RAW TEXT body (for
    structural/regex checks - separate from the parsed action tree above)."""
    marker = f"\n  - id: {script_id}\n"
    start = fw_text.index(marker)
    rest = fw_text[start + 1:]
    m = re.search(r"\n  - id: (?!" + re.escape(script_id) + r"\b)\w+\n|\n[a-z_]+:\n", rest)
    end = m.start() if m else len(rest)
    return rest[:end]


def _norm(code: str) -> str:
    return " ".join(str(code).split())


def _cond_text(if_body: dict) -> str:
    """A condition `if:` node's normalised lambda text. `//` line comments
    are stripped BEFORE whitespace-normalising (2026-09-24, independent-
    review final cleanup round) - some real condition lambdas (e.g. the
    final-verify/comms-backoff gate) have an explanatory comment block
    ahead of their `return ...;`, and stripping AFTER `_norm` would be too
    late: `_norm` collapses every newline, so a `//` comment's own
    end-of-line boundary (the only thing that bounds it) would already be
    gone, making it impossible to tell where the comment ends and the
    real condition code begins."""
    cond = if_body.get("condition")
    if isinstance(cond, dict) and "lambda" in cond:
        return _norm(re.sub(r"//[^\n]*", "", cond["lambda"]))
    return _norm(repr(cond))


def _single(action: dict) -> tuple[str, object]:
    if not isinstance(action, dict) or len(action) != 1:
        raise AssertionError(f"not a single-key ESPHome action: {action!r}")
    return next(iter(action.items()))


def flatten(actions, gates=()):
    """Document-order list of (kind, gates, body). `gates` is the tuple of
    (normalised condition lambda, 'then'|'else') of every enclosing `if:`."""
    out = []
    for action in actions or []:
        kind, body = _single(action)
        out.append((kind, gates, body))
        if kind == "if":
            cond = _cond_text(body)
            out.extend(flatten(body.get("then"), gates + ((cond, "then"),)))
            out.extend(flatten(body.get("else"), gates + ((cond, "else"),)))
    return out


def find_if(actions, predicate):
    """First `if:` body (depth-first, document order) whose condition text
    satisfies `predicate`."""
    for action in actions or []:
        kind, body = _single(action)
        if kind == "if":
            if predicate(_cond_text(body)):
                return body
            for branch in ("then", "else"):
                hit = find_if(body.get(branch), predicate)
                if hit is not None:
                    return hit
    return None


def writes_in(flat):
    return [(i, body["start_address"], gates) for i, (kind, gates, body) in enumerate(flat) if kind == WRITE]


# ---------------------------------------------------------------------------
# Restricted lambda interpreter for the control-flow and comparison
# statements these write/readback/context-gate sequences actually use. Each
# lambda is compiled ONCE into a small op list and then executed against a
# state dict (the firmware's id(...) globals) and, for read handlers, the
# `values` delivered by the (simulated) Modbus response. Anything it does
# not recognise raises instead of being guessed at.
#
# Supported statement forms (nothing else):
#   if (!?id(X)) return;          if (!?id(X)) { ... }       if (!?name) { ... }
#   id(X) = true|false;           id(X) = name;
#   id(X) = <int literal>;        id(X) = values[N];
#   bool name = true|false;       uint16_t name[N] = { expr, ... };
#   uint16_t name = expr;         (write-value lambdas only)
#   for (int i=A;i<B;i++) name = name && values[i] == arr[i];
#   return std::vector<uint16_t>{ expr, ... };   (write-value lambdas only)
# where expr uses only integer literals, id(X), local names, (uint16_t)
# casts, &, | and parentheses.
#
# Supported condition forms (a bare `return ... ;` of `&&`-joined terms):
#   (!?)id(X)                     id(X) >= <int literal>
#   id(X) == id(Y)                id(X) != id(Y)
#   ((!?)id(X) || (!?)id(Y))      - one parenthesised two-term OR (SG-01
#                                   Phase 4: the restore write gate's
#                                   `(matches_intended || live_self_partial)`)
# ---------------------------------------------------------------------------
class UnsupportedLambda(Exception):
    pass


# ---------------------------------------------------------------------------
# SG-01 fail-closed guard: the Free Power START journal.
#
# LENIENT mode (see `_parse_ops`) silently skips - and merely records - any
# top-level `lambda:` statement it cannot interpret, and a durable
# `ecco_durable::commit_record(...)` is exactly such a statement: this
# interpreter has no durable store. Since SG-01 Phase 2 the firmware commits
# the START journal BEFORE each START write, so a test built on this
# simulator would still PASS if such a commit were deleted, moved after the
# write, or never executed at all. To make that impossible, ANY statement,
# condition, write-value lambda, handler or script id that mentions the
# journal raises `JournalNotModelled` here, in strict AND lenient mode.
#
# The ONLY way past it is `simulate(..., journal_sim=<_dump_sim.Sim>)`: a
# top-level `lambda:` action that mentions the journal is then EXECUTED in
# full by registry/tests/_dump_sim.py's transpiler against that Sim's
# durable store (with its commit/load failure injection), reading and
# writing the simulation's own `id(...)` state - never skipped. Every other
# journal mention (conditions, write values, handlers, script ids) still
# raises. `//` and `/* */` comments are ignored so an explanatory firmware
# comment cannot trip it.
#
# Matches every spelling the journal can take: FREE_POWER_START_JOURNAL_TAG,
# ecco_free_power_start_journal_v1, FreePowerStartJournal, a
# `fp_start_journal_*` global, ...
# ---------------------------------------------------------------------------
class JournalNotModelled(UnsupportedLambda):
    pass


JOURNAL_GUARD_PATTERN = re.compile(r"start_?journal", re.IGNORECASE)
_JOURNAL_GUARD_CLEARED: set[str] = set()


def _without_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def guard_against_unmodelled_journal(code, where: str = "statement") -> None:
    """Raises JournalNotModelled if `code` mentions the SG-01 START journal."""
    code = str(code)
    if code in _JOURNAL_GUARD_CLEARED:
        return
    m = JOURNAL_GUARD_PATTERN.search(_without_comments(code))
    if m:
        raise JournalNotModelled(
            f"{where} references the SG-01 START journal ({m.group(0)!r}), which this interpreter does not "
            "model - refusing to skip it silently. Model the journal operation before simulating it."
        )
    _JOURNAL_GUARD_CLEARED.add(code)


def mentions_journal(code) -> bool:
    return bool(JOURNAL_GUARD_PATTERN.search(_without_comments(str(code))))


# ---------------------------------------------------------------------------
# FB-B0 fail-closed guard (S6 BLK-43): the Fallback Profile durable code.
#
# Same hazard as the journal: LENIENT mode would silently skip an FB
# commit_transition / read lambda, so a test built on this simulator could
# pass with the witness-first transaction deleted or reordered. ANY statement,
# condition, write-value lambda, handler or script id that names the FB
# durable code, records, tags, keys or globals raises FallbackNotModelled -
# in strict AND lenient mode, with no bypass: FB lambdas are simulated only by
# registry/tests/_fbb_harness.py's FbbSim. Comments are ignored.
# ---------------------------------------------------------------------------
class FallbackNotModelled(UnsupportedLambda):
    pass


FALLBACK_GUARD_PATTERN = re.compile(
    r"ecco_fbdurable|ecco_fbcap|ecco_fallback|ecco_failback|commit_transition|read_direct|read_pair_t|"
    r"fallback_profile_|FallbackProfileV1|FailbackProvisionV1|FailbackStateV1|"
    r"(?:FALLBACK_PROFILE|FAILBACK_PROVISION|FAILBACK_STATE)_(?:TAG|KEY)|1609458070|1000595297|2156168643",
    re.IGNORECASE)
_FALLBACK_GUARD_CLEARED: set[str] = set()


def guard_against_unmodelled_fallback(code, where: str = "statement") -> None:
    """Raises FallbackNotModelled if `code` names the FB durable code."""
    code = str(code)
    if code in _FALLBACK_GUARD_CLEARED:
        return
    m = FALLBACK_GUARD_PATTERN.search(_without_comments(code))
    if m:
        raise FallbackNotModelled(
            f"{where} references the Fallback Profile durable code ({m.group(0)!r}), which this interpreter does "
            "not model - refusing to skip it silently. Simulate it with registry/tests/_fbb_harness.py's FbbSim."
        )
    _FALLBACK_GUARD_CLEARED.add(code)


def mentions_fallback(code) -> bool:
    return bool(FALLBACK_GUARD_PATTERN.search(_without_comments(str(code))))


def run_journal_lambda(journal_sim, code: str, state: dict) -> None:
    """Executes a journal-referencing top-level lambda action IN FULL through
    registry/tests/_dump_sim.py's transpiler (strict: an unsupported
    construct raises), against `journal_sim`'s durable store. `id(...)`
    globals are read from and written to `state` itself (the simulation's
    RAM), so a missing global raises KeyError rather than defaulting."""
    journal_sim.g = state
    journal_sim.run_lambda(code)


def _strip_code(code: str) -> str:
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)  # string literal contents
    code = re.sub(r"//[^\n]*", "", code)  # line comments
    code = re.sub(r"\bESP_LOG\w*\s*\([^;]*\)\s*;", "", code)  # log calls
    return code


def _match_brace(code: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise UnsupportedLambda("unbalanced braces")


_EXPR_SAFE = re.compile(r"^[\sSLV\[\]\"'\w()&|=!+*/-]+$")


def _compile_expr(expr: str):
    """Compiles a restricted C++-ish expression to a Python code object.
    Extended (2026-09-24, independent-review final cleanup round, R1/R2) to
    also support `values[N]` (via a `V` alias - exactly like `id(X)` -> `S`
    and a bare local -> `L`) and the boolean operators `!`, `&&`, `||`
    (translated to Python `not`/`and`/`or` - C++ `&&`/`||` are not valid
    Python and would otherwise fail to compile) and `==`/`!=` comparisons,
    so the restricted-value verify/classifier lambdas' boolean expressions
    (e.g. `bool ok = !id(x) && id(y) == id(z);`) can be genuinely evaluated
    instead of only the narrower bitwise `&`/`|` write-value expressions
    this compiler originally supported."""
    py = re.sub(r"\(\s*(?:uint16_t|int|unsigned)\s*\)", "", expr)
    py = re.sub(r"\bid\((\w+)\)", r'S["\1"]', py)
    py = re.sub(r"\bvalues\[", "V[", py)
    py = re.sub(r"(?<![\w\"])([A-Za-z_]\w*)(?![\w\"(\[])", r'L["\1"]', py)
    py = py.replace('L["S"]', "S")
    py = re.sub(r"&&", " and ", py)
    py = re.sub(r"\|\|", " or ", py)
    py = re.sub(r"!(?!=)", " not ", py)
    py = py.strip()  # compile(..., "eval") raises IndentationError on leading whitespace
    if not _EXPR_SAFE.match(py) or re.search(r"[A-Za-z_]\w*\s*\(", py.replace('S["', "").replace('L["', "")):
        raise UnsupportedLambda(f"unsupported expression: {expr!r}")
    return compile(py, "<firmware-expr>", "eval")


def _eval_expr(code_obj, state, local, values=None):
    return eval(code_obj, {"__builtins__": {}}, {"S": state, "L": local, "V": values if values is not None else []})  # noqa: S307 - restricted, see _compile_expr


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


def _skip_one_statement(s: str) -> int:
    """Given `s` starting at a statement this interpreter's grammar does
    not recognise (e.g. `char reason[64];`, a `snprintf(...);` call, a
    struct-literal declaration/member assignment, or a full C++
    `if (<non-bool-flag expr>) { ... } else { ... }` this interpreter does
    not itself evaluate), returns how many leading characters make up that
    ONE statement, so LENIENT parsing (see `_parse_ops`) can skip it and
    keep parsing whatever comes after - e.g. the ownership-flag releases
    that follow a hold/failure branch's status-message bookkeeping.
    Depth-aware: a `;` inside any bracket/paren/brace nesting does not
    count, and a top-level `{...}` block (an if/for body) is skipped as one
    unit, including one immediately following `else {...}`."""
    depth = 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == ";" and depth == 0:
            return i + 1
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
            if depth == 0 and ch == "}":
                j = i + 1
                m = re.match(r"\s*else\s*\{", s[j:])
                if m:
                    close2 = _match_brace(s[j:], m.end() - 1)
                    return j + close2 + 1
                return j
        i += 1
    raise UnsupportedLambda("unterminated statement while skipping an unsupported construct")


def excise_statement(code: str, start_marker: str) -> str:
    """Returns `code` with the ONE compile-time statement that begins at
    `start_marker` (a literal substring, first occurrence) removed
    entirely, using the SAME depth-aware `_skip_one_statement` scanner
    LENIENT parsing itself uses internally - so `if (cond) {...} else
    {...}` is removed as a single unit.

    For deliberately excising a large, out-of-scope compound statement
    (e.g. a durable-storage-commit/status-publish branch this restricted
    interpreter was never meant to fully re-implement - already covered
    by its own dedicated tests elsewhere) from an otherwise fully
    interpretable handler lambda, BEFORE strict parsing - rather than
    relying on lenient skip-and-continue at parse time, which cannot help
    here: `if (ok) {...}` DOES syntactically match the supported bare-
    local `if_block` pattern (see `_parse_ops`), so lenient parsing would
    try - and fail AT RUN TIME with a KeyError, not a graceful skip - to
    evaluate a condition/body this interpreter cannot fully understand,
    instead of skipping it. See registry/tests/test_free_power_reg244_context_v4.py
    section [P] for the one caller that needs this."""
    idx = code.index(start_marker)
    skip_len = _skip_one_statement(code[idx:])
    return code[:idx] + code[idx + skip_len:]


def _parse_ops(code: str, *, lenient: bool = False) -> tuple[list, list[str]]:
    """Returns (ops, skipped). In STRICT mode (lenient=False - the default,
    used for handler/value/condition lambdas, which decide `bank` state or
    a gate outcome and must never be partially understood), the first
    unrecognised statement raises `UnsupportedLambda` immediately, exactly
    as before this pass - `skipped` is always `[]` in this mode.

    In LENIENT mode (used ONLY for plain top-level `lambda:` ACTIONS - see
    `exec_lambda` / module docstring for why that is safe), an unrecognised
    statement is instead skipped via `_skip_one_statement` and recorded in
    `skipped`, and parsing CONTINUES with whatever follows - so e.g. a
    context-hold branch's snprintf/char-buffer status-message bookkeeping
    is skipped without losing the ownership-flag releases that follow it
    in the same lambda body."""
    ops, skipped, pos = [], [], 0
    while True:
        rest = code[pos:]
        s = rest.lstrip()
        if not s:
            return ops, skipped
        pos += len(rest) - len(s)
        m = re.match(r"if\s*\(\s*(!?)(id\((\w+)\)|(\w+))\s*\)\s*return\s*;", s)
        if m:
            ops.append(("ret_if", bool(m.group(1)), "id" if m.group(3) else "local", m.group(3) or m.group(4)))
            pos += m.end()
            continue
        # A two-term `&&`-joined if block - e.g. a bounded-wait fallback's
        # `if (!id(op_terminal) && id(operation_in_progress)) { ... }`,
        # which can itself contain the ownership-lock release lines. Tried
        # BEFORE the single-term pattern below so a two-term condition is
        # never partially matched as a malformed single-term one (in
        # practice the single-term pattern cannot match it anyway, since it
        # requires `)` immediately after the first term - this ordering is
        # for clarity/robustness, not correctness).
        m = re.match(
            r"if\s*\(\s*(!?)(id\((\w+)\)|(\w+))\s*&&\s*(!?)(id\((\w+)\)|(\w+))\s*\)\s*\{", s)
        if m:
            close = _match_brace(s, m.end() - 1)
            inner_ops, inner_skipped = _parse_ops(s[m.end():close], lenient=lenient)
            skipped.extend(inner_skipped)
            ops.append((
                "if_block2",
                bool(m.group(1)), "id" if m.group(3) else "local", m.group(3) or m.group(4),
                bool(m.group(5)), "id" if m.group(7) else "local", m.group(7) or m.group(8),
                inner_ops,
            ))
            pos += close + 1
            continue
        m = re.match(r"if\s*\(\s*(!?)(id\((\w+)\)|(\w+))\s*\)\s*\{", s)
        if m:
            close = _match_brace(s, m.end() - 1)
            inner_ops, inner_skipped = _parse_ops(s[m.end():close], lenient=lenient)
            skipped.extend(inner_skipped)
            ops.append(("if_block", bool(m.group(1)), "id" if m.group(3) else "local", m.group(3) or m.group(4),
                        inner_ops))
            pos += close + 1
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*(true|false)\s*;", s)
        if m:
            ops.append(("set_id_const", m.group(1), m.group(2) == "true"))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*values\[(\d+)\]\s*;", s)
        if m:
            ops.append(("set_id_from_values", m.group(1), int(m.group(2))))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*\(int\)\s*\(\s*(-?\d+)\s*\)\s*;", s)
        if m:
            ops.append(("set_id_int", m.group(1), int(m.group(2))))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*(-?\d+)\s*;", s)
        if m:
            ops.append(("set_id_int", m.group(1), int(m.group(2))))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*\(int\)\s*id\((\w+)\)\s*;", s)
        if m:
            ops.append(("set_id_id", m.group(1), m.group(2)))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*id\((\w+)\)\s*;", s)
        if m:
            ops.append(("set_id_id", m.group(1), m.group(2)))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*=\s*([A-Za-z_]\w*)\s*;", s)
        if m:
            ops.append(("set_id_local", m.group(1), m.group(2)))
            pos += m.end()
            continue
        # id(X) = <general expression>; - e.g. `id(x) = values[0] == id(y);`
        # (a comparison, not a plain literal/values[N]/id()/local copy, all
        # of which the more specific patterns above already handle and
        # therefore always match first). Only reached when nothing more
        # specific did. `_compile_expr` itself rejects anything containing
        # a genuine function/namespaced call (e.g. `ecco_durable::...(...)`,
        # `millis()`) - in LENIENT mode that rejection is treated exactly
        # like any other unrecognised statement (skip-and-record); in
        # STRICT mode it still raises, unchanged from every other pattern here.
        m = re.match(r"id\((\w+)\)\s*=\s*([^;]+);", s)
        if m:
            try:
                compiled = _compile_expr(m.group(2))
            except UnsupportedLambda:
                if not lenient:
                    raise
                skip_len = _skip_one_statement(s)
                skipped.append(s[:skip_len].strip()[:120])
                pos += skip_len
                continue
            ops.append(("set_id_expr", m.group(1), compiled))
            pos += m.end()
            continue
        m = re.match(r"bool\s+(\w+)\s*=\s*(true|false)\s*;", s)
        if m:
            ops.append(("bool", m.group(1), m.group(2) == "true"))
            pos += m.end()
            continue
        # bool NAME = <general expression>; - same rationale/fallback as
        # id(X) = <general expression>; above, for a local boolean (e.g. the
        # restore-verify handler's `bool ok = !id(write_failed) && ... ;`).
        m = re.match(r"bool\s+(\w+)\s*=\s*([^;]+);", s)
        if m:
            try:
                compiled = _compile_expr(m.group(2))
            except UnsupportedLambda:
                if not lenient:
                    raise
                skip_len = _skip_one_statement(s)
                skipped.append(s[:skip_len].strip()[:120])
                pos += skip_len
                continue
            ops.append(("bool_expr", m.group(1), compiled))
            pos += m.end()
            continue
        m = re.match(r"uint16_t\s+(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\{", s)
        if m:
            close = _match_brace(s, m.end() - 1)
            elems = _split_top(s[m.end():close])
            if len(elems) != int(m.group(2)):
                raise UnsupportedLambda(f"array {m.group(1)} declares {m.group(2)} elements, has {len(elems)}")
            end = re.match(r"\s*;", s[close + 1:])
            if not end:
                raise UnsupportedLambda("array initialiser not terminated")
            ops.append(("arr", m.group(1), [_compile_expr(e) for e in elems]))
            pos += close + 1 + end.end()
            continue
        m = re.match(r"uint16_t\s+(\w+)\s*=\s*([^;]+);", s)
        if m:
            ops.append(("local_expr", m.group(1), _compile_expr(m.group(2))))
            pos += m.end()
            continue
        # for (int i=A;i<B;i++) name = name && values[i] == arr[i];
        # - or, with an additive offset into `values` (e.g. `values[12+i]`,
        # used by a readback that packs several logical fields into one
        # wider Modbus response) - `values[OFFSET+i]`.
        m = re.match(
            r"for\s*\(\s*int\s+i\s*=\s*(\d+)\s*;\s*i\s*<\s*(\d+)\s*;\s*i\+\+\s*\)\s*"
            r"(\w+)\s*=\s*(\w+)\s*&&\s*values\[(?:(\d+)\+)?i\]\s*==\s*(\w+)\[i\]\s*;", s)
        if m and m.group(3) == m.group(4):
            offset = int(m.group(5)) if m.group(5) else 0
            ops.append(("for_eq", m.group(3), int(m.group(1)), int(m.group(2)), m.group(6), offset))
            pos += m.end()
            continue
        # for (int i=A;i<B;i++) name = name && values[i] == <int literal>;
        # - e.g. start_free_power_override's activation-verify SOC check
        # (`soc_ok = soc_ok && values[i] == 100;`).
        m = re.match(
            r"for\s*\(\s*int\s+i\s*=\s*(\d+)\s*;\s*i\s*<\s*(\d+)\s*;\s*i\+\+\s*\)\s*"
            r"(\w+)\s*=\s*(\w+)\s*&&\s*values\[(?:(\d+)\+)?i\]\s*==\s*(\d+)\s*;", s)
        if m and m.group(3) == m.group(4):
            offset = int(m.group(5)) if m.group(5) else 0
            ops.append(("for_eq_const", m.group(3), int(m.group(1)), int(m.group(2)), int(m.group(6)), offset))
            pos += m.end()
            continue
        m = re.match(r"id\((\w+)\)\s*\+\+\s*;", s)
        if m:
            ops.append(("incr_id", m.group(1)))
            pos += m.end()
            continue
        # A bare `return;` (as opposed to `return std::vector<uint16_t>{...};`
        # below, or the single-line `if (cond) return;` form already handled
        # as `ret_if` above) - e.g. a stale-callback guard's block body:
        # `if (!id(x)) { ESP_LOGW(...); return; }`.
        m = re.match(r"return\s*;", s)
        if m:
            ops.append(("ret_now",))
            pos += m.end()
            continue
        m = re.match(r"return\s+std::vector<uint16_t>\s*\{", s)
        if m:
            close = _match_brace(s, m.end() - 1)
            end = re.match(r"\s*;", s[close + 1:])
            if not end:
                raise UnsupportedLambda("return vector not terminated")
            ops.append(("ret_vec", [_compile_expr(e) for e in _split_top(s[m.end():close])]))
            pos += close + 1 + end.end()
            continue
        # Genuinely unrecognised construct.
        if not lenient:
            raise UnsupportedLambda(f"unsupported statement: {s[:80]!r}")
        skip_len = _skip_one_statement(s)
        skipped.append(s[:skip_len].strip()[:120])
        pos += skip_len


_OPS_CACHE: dict[tuple[str, bool], tuple[list, list[str]]] = {}


def _ops_for(code: str, *, lenient: bool = False) -> tuple[list, list[str]]:
    guard_against_unmodelled_journal(code, "lambda")
    guard_against_unmodelled_fallback(code, "lambda")
    key = (code, lenient)
    cached = _OPS_CACHE.get(key)
    if cached is None:
        cached = _OPS_CACHE[key] = _parse_ops(_strip_code(code), lenient=lenient)
    return cached


def _run_ops(ops, state, local, values):
    """Returns ('return', vector|None) on a return statement, else None."""
    for op in ops:
        kind = op[0]
        if kind in ("ret_if", "if_block"):
            _, neg, src, name = op[:4]
            value = state[name] if src == "id" else local[name]
            taken = (not value) if neg else bool(value)
            if kind == "ret_if":
                if taken:
                    return ("return", None)
            elif taken:
                result = _run_ops(op[4], state, local, values)
                if result:
                    return result
        elif kind == "if_block2":
            _, neg1, src1, name1, neg2, src2, name2, inner = op
            v1 = state[name1] if src1 == "id" else local[name1]
            v2 = state[name2] if src2 == "id" else local[name2]
            t1 = (not v1) if neg1 else bool(v1)
            t2 = (not v2) if neg2 else bool(v2)
            if t1 and t2:
                result = _run_ops(inner, state, local, values)
                if result:
                    return result
        elif kind == "set_id_const":
            state[op[1]] = op[2]
        elif kind == "set_id_int":
            state[op[1]] = op[2]
        elif kind == "set_id_from_values":
            if values is None:
                raise UnsupportedLambda("values[] used outside a read response")
            state[op[1]] = values[op[2]]
        elif kind == "set_id_id":
            state[op[1]] = state[op[2]]
        elif kind == "set_id_local":
            # Tolerant even in STRICT mode: `op[2]` names a local that, in
            # lenient parsing, may have been computed by a SKIPPED
            # statement (e.g. `char reason[64]; ...snprintf(reason,...);`)
            # - see _skip_one_statement. Never crashes; simply leaves
            # `state[op[1]]` unset/unchanged, which is safe because no
            # gate condition ever reads a diagnostic-only field populated
            # this way (context_hold_reason, status message locals).
            if op[2] in local:
                state[op[1]] = local[op[2]]
        elif kind == "incr_id":
            state[op[1]] = state.get(op[1], 0) + 1
        elif kind == "bool":
            local[op[1]] = op[2]
        elif kind == "bool_expr":
            local[op[1]] = _eval_expr(op[2], state, local, values)
        elif kind == "set_id_expr":
            state[op[1]] = _eval_expr(op[2], state, local, values)
        elif kind == "arr":
            local[op[1]] = [_eval_expr(c, state, local, values) for c in op[2]]
        elif kind == "local_expr":
            local[op[1]] = _eval_expr(op[2], state, local, values)
        elif kind == "for_eq":
            _, name, lo, hi, arr, offset = op
            if values is None:
                raise UnsupportedLambda("values[] used outside a read response")
            for i in range(lo, hi):
                local[name] = local[name] and values[offset + i] == local[arr][i]
        elif kind == "for_eq_const":
            _, name, lo, hi, literal, offset = op
            if values is None:
                raise UnsupportedLambda("values[] used outside a read response")
            for i in range(lo, hi):
                local[name] = local[name] and values[offset + i] == literal
        elif kind == "ret_now":
            return ("return", None)
        elif kind == "ret_vec":
            return ("return", [_eval_expr(c, state, local, values) for c in op[1]])
    return None


def exec_lambda(code: str, state: dict, values=None, *, lenient: bool = False) -> list[str]:
    """Executes `code` against `state`. Returns the list of skipped
    statement descriptions (always `[]` in strict mode, and always `[]` in
    lenient mode too for a fully-understood lambda). See `_parse_ops` for
    what STRICT vs LENIENT means and why only plain top-level `lambda:`
    ACTIONS may safely use lenient=True."""
    ops, skipped = _ops_for(code, lenient=lenient)
    _run_ops(ops, state, {}, values)
    return skipped


def eval_write_values(code: str, state: dict) -> list[int]:
    ops, _skipped = _ops_for(code)  # strict: a write-value lambda must be fully understood
    result = _run_ops(ops, state, {}, None)
    if not result or result[1] is None:
        raise UnsupportedLambda("write values lambda did not return a vector")
    return result[1]


_COND_CACHE: dict[str, list] = {}


def eval_condition(cond: str, state: dict) -> bool:
    guard_against_unmodelled_journal(cond, "condition")
    guard_against_unmodelled_fallback(cond, "condition")
    terms = _COND_CACHE.get(cond)
    if terms is None:
        m = re.fullmatch(r"return (.+);", cond)
        if not m:
            raise UnsupportedLambda(f"unsupported condition: {cond!r}")
        terms = []
        for term in m.group(1).split("&&"):
            term = term.strip()
            t = re.fullmatch(r"(!?)id\((\w+)\)", term)
            if t:
                terms.append(("bool", bool(t.group(1)), t.group(2)))
                continue
            t = re.fullmatch(r"id\((\w+)\)\s*>=\s*(-?\d+)", term)
            if t:
                terms.append(("ge", t.group(1), int(t.group(2))))
                continue
            t = re.fullmatch(r"id\((\w+)\)\s*==\s*id\((\w+)\)", term)
            if t:
                terms.append(("eq", t.group(1), t.group(2)))
                continue
            t = re.fullmatch(r"id\((\w+)\)\s*!=\s*id\((\w+)\)", term)
            if t:
                terms.append(("ne", t.group(1), t.group(2)))
                continue
            t = re.fullmatch(r"\(\s*(!?)id\((\w+)\)\s*\|\|\s*(!?)id\((\w+)\)\s*\)", term)
            if t:
                terms.append(("or2", bool(t.group(1)), t.group(2), bool(t.group(3)), t.group(4)))
                continue
            raise UnsupportedLambda(f"unsupported condition term: {term!r}")
        _COND_CACHE[cond] = terms
    for entry in terms:
        kind = entry[0]
        if kind == "bool":
            _, neg, name = entry
            value = state[name]
            satisfied = (not value) if neg else bool(value)
            if not satisfied:
                return False
        elif kind == "ge":
            _, name, lit = entry
            if not (state[name] >= lit):
                return False
        elif kind == "eq":
            _, name1, name2 = entry
            if not (state[name1] == state[name2]):
                return False
        elif kind == "ne":
            _, name1, name2 = entry
            if not (state[name1] != state[name2]):
                return False
        elif kind == "or2":
            # Both operands are read (a missing global raises KeyError
            # instead of silently short-circuiting past it).
            _, neg1, name1, neg2, name2 = entry
            v1, v2 = state[name1], state[name2]
            if not (((not v1) if neg1 else bool(v1)) or ((not v2) if neg2 else bool(v2))):
                return False
    return True


# ---------------------------------------------------------------------------
# Generic action-tree walker/simulator over a CONCRETE register bank.
# Executes a real extracted action list end to end: writes (their real
# `values:` lambdas evaluated against state, with an injected outcome each),
# reads (returning the bank's actual contents unless overridden by
# `read_value_overrides`, with an injected outcome each), every real on_*
# handler lambda, every real bounded-wait timeout lambda and every real
# `if:` gate (including nested ones - e.g. the register-244 context gates
# nested inside the owned-register write gate).
#
# `write_outcomes`/`read_outcomes` are keyed by (start_address, count) -
# NOT by address alone - because a single sequence can legitimately contain
# more than one read at the SAME address with DIFFERENT counts (e.g.
# restore_free_power_snapshot_dispatch's pre-write 244x12 context read and
# its separate pre-floor 244x1 context recheck) that must be independently
# controllable.
#
# A plain top-level `lambda:` ACTION (never a read/write node's own
# condition/value/handler lambda, all of which remain STRICTLY interpreted)
# that raises UnsupportedLambda is tolerated and recorded in
# `skipped_lambdas` rather than aborting the whole simulation: a lambda
# ACTION can never itself contain a modbus_client.* node (the YAML schema
# makes that structurally impossible), so failing to fully interpret one -
# e.g. the snprintf/char-buffer status-message bookkeeping inside a
# context-hold branch - cannot hide a missed read/write. Read/write nodes
# and everything that decides whether/what they read or write remain
# strictly interpreted with no such leniency.
# ---------------------------------------------------------------------------
WRITE_OUTCOMES = (
    "ok",                                   # acknowledged and applied
    "ack_not_applied",                      # acknowledged but NOT applied (the ack-vs-readback concern)
    "error", "not_sent",
    "no_response_landed", "no_response_lost",
    "timeout_landed", "timeout_lost",
)
READ_OUTCOMES = (
    "ok",                                   # returns the bank's actual contents (or the override, if any)
    "ok_changed",                           # conformant reply, but one value differs (e.g. third-party change)
    "error", "not_sent", "no_response", "timeout",
)
_WRITE_HANDLER = {
    "ok": "on_response", "ack_not_applied": "on_response", "error": "on_error", "not_sent": "on_not_sent",
    "no_response_landed": "on_no_response", "no_response_lost": "on_no_response",
    "timeout_landed": None, "timeout_lost": None,
}
_WRITE_LANDS = {"ok", "no_response_landed", "timeout_landed"}
_READ_HANDLER = {
    "ok": "on_response", "ok_changed": "on_response", "error": "on_error",
    "not_sent": "on_not_sent", "no_response": "on_no_response", "timeout": None,
}


def _run_handler(body, handler, state, values=None):
    for handler_action in body[handler]["then"]:
        hkind, hbody = _single(handler_action)
        if hkind != "lambda":
            raise UnsupportedLambda(f"unsupported handler action {hkind}")
        exec_lambda(hbody, state, values)


def simulate(
    actions,
    write_outcomes: dict,
    read_outcomes: dict,
    start_bank: dict,
    base_state: dict,
    *,
    read_value_overrides: dict | None = None,
    invariant_fn=None,
    executed_scripts: list | None = None,
    journal_sim=None,
):
    """Returns (final bank, final state, attempted [(kind, addr, count,
    bank-snapshot-before)], first invariant violation or None,
    skipped_lambdas [str]).

    `base_state` is the caller's starting `id(...)` globals dict (copied,
    never mutated in place) - see the per-test `base_state()` builders.
    `read_value_overrides`, keyed by (address, count) exactly like
    `read_outcomes`, replaces what a specific read returns (e.g. "the live
    register-244 value this read should see") instead of reading it from
    `bank` (register 244 is not an owned/written register and is not
    tracked in `bank` at all).
    `invariant_fn(bank) -> str | None` is checked after every write, exactly
    like the ceiling/floor invariant; omit for tests that do not need one.
    `executed_scripts`, if given, has the id of every `script.execute:`
    action actually reached appended to it, in order (the executed script
    itself is still NOT run - see the `script.execute` branch below).
    `journal_sim`, if given, is a registry/tests/_dump_sim.Sim that EXECUTES
    every top-level lambda action referencing the SG-01 START journal (see
    run_journal_lambda); every Modbus operation simulated here is also
    appended to its `events` timeline, so commit-before-write order is
    observable. Without it such a lambda raises JournalNotModelled.
    """
    bank = dict(start_bank)
    state = dict(base_state)
    attempted: list = []
    skipped_lambdas: list = []
    violation = invariant_fn(bank) if invariant_fn else None
    read_value_overrides = read_value_overrides or {}

    def run(action_list):
        nonlocal violation
        for action in action_list or []:
            kind, body = _single(action)
            if kind == "lambda":
                if journal_sim is not None and mentions_journal(body):
                    run_journal_lambda(journal_sim, body, state)
                else:
                    skipped_lambdas.extend(exec_lambda(body, state, lenient=True))
            elif kind == "wait_until":
                pass  # ends via the terminal flag or the bounded timeout; the next lambda decides
            elif kind == "script.execute":
                guard_against_unmodelled_journal(body["id"] if isinstance(body, dict) else body, "script.execute")
                guard_against_unmodelled_fallback(body["id"] if isinstance(body, dict) else body, "script.execute")
                if executed_scripts is not None:
                    executed_scripts.append(body["id"] if isinstance(body, dict) else body)
                # fire-and-forget trigger of a SEPARATE script, asynchronously - this
                # simulator's job is the CALLING script's own state/bank, not to chase
                # into another script's independent execution (e.g. the final-verify
                # success path's trailing `script.execute: poll_inverter_configuration`).
            elif kind == "if":
                branch = "then" if eval_condition(_cond_text(body), state) else "else"
                run(body.get(branch))
            elif kind == WRITE:
                addr = body["start_address"]
                attempted.append(("write", addr, None, dict(bank)))
                outcome = write_outcomes[addr]
                if journal_sim is not None:
                    journal_sim._log_event(("write", addr, None, outcome))
                if outcome in _WRITE_LANDS:
                    for i, v in enumerate(eval_write_values(body["values"], state)):
                        bank[addr + i] = v
                if _WRITE_HANDLER[outcome]:
                    _run_handler(body, _WRITE_HANDLER[outcome], state)
                if violation is None and invariant_fn:
                    violation = invariant_fn(bank)
            elif kind == READ:
                addr, count = body["start_address"], body["count"]
                key = (addr, count)
                attempted.append(("read", addr, count, dict(bank)))
                outcome = read_outcomes[key]
                if journal_sim is not None:
                    journal_sim._log_event(("read", addr, count, outcome))
                if key in read_value_overrides:
                    values = list(read_value_overrides[key])
                else:
                    values = [bank[addr + i] for i in range(count)]
                if outcome == "ok_changed":
                    values[0] ^= 0x0001
                if _READ_HANDLER[outcome]:
                    _run_handler(body, _READ_HANDLER[outcome], state,
                                 values if _READ_HANDLER[outcome] == "on_response" else None)
            else:
                raise UnsupportedLambda(f"unsupported action in write sequence: {kind}")

    run(actions)
    return bank, state, attempted, violation, skipped_lambdas
