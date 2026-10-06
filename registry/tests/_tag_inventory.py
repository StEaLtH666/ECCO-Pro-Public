"""Independent durable-tag inventory for firmware headers (FB-T0 hardening).

The FB-A collision suite used to find tags with ONE regex for ONE declaration style
(`constexpr [const] char [*]NAME_TAG[[]] = "...";`). A legitimate declaration in any other
C++ form - different spacing, `std::string_view`, a wrapped / concatenated literal, a `#define`,
a name that does not end `_TAG` - silently escaped the pre-existing / later / prospective
key-collision accounting, so a wrong or colliding FB-B0 tag (S2's planned FBW
`ecco_failback_provision_v1`) could land with the suite green.

Two INDEPENDENT detectors, cross-checked:

  1. DECLARATIONS (`declarations`/`inventory`): comment-stripped text is scanned for
     `NAME [ [..] ] ( = | { | = { ) [wrapper( | wrapper{] "lit" ["lit" ...]` (adjacent literals are
     concatenated, so a wrapped declaration is one value) and `#define NAME "lit"`. An entry is a durable
     tag when its NAME mentions `tag` (any case, any position) OR its VALUE follows the repo's
     durable-tag convention `ecco_<words>_v<N>` - the name does not have to end `_TAG`.
  2. LITERALS (`durable_literals`): EVERY string literal in the comment-stripped text (not only declared
     ones) whose value follows the convention. `unaccounted_literals` = those whose value is not the value
     of any inventoried declaration, i.e. a durable-looking literal that escaped collision accounting
     (used only as a call argument, built from a macro the scanner does not understand, ...).
     Such a literal FAILS the suite; it is never ignored.

Not modelled (and therefore never silently accepted): C++ raw string literals. They are not used in
firmware/include/ today and a durable literal inside one would only be caught if it is also spelled
as an ordinary literal.

`check_later_headers` is the one function the FB-A suite and this module's negative controls share.
No I/O except reading header files in `all_declared_tags`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Mapping

# The repo's durable preference-tag convention: lowercase `ecco_<words>_v<N>`.
DURABLE = re.compile(r"ecco_[a-z0-9]+(?:_[a-z0-9]+)*_v[0-9]+")

_STR = r'"(?:[^"\\\n]|\\.)*"'
_LIT = rf"(?P<lit>{_STR}(?:\s*{_STR})*)"
_DECL = re.compile(
    r"(?P<name>[A-Za-z_]\w*)"            # declared / assigned name (any name)
    r"\s*(?:\[[^\]]*\])?"                # optional array bound: [] or [27]
    r"\s*(?:=\s*\{?|\{)\s*"              # `=`, `= {` or brace-init `{`
    r"(?:[A-Za-z_][\w:]*\s*[({]\s*)?"    # optional wrapper: std::string_view( / std::string_view{
    + _LIT)
_DEFINE = re.compile(r"#\s*define\s+(?P<name>[A-Za-z_]\w*)\s+" + _LIT)
_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'"}


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments. String and character literals are respected, so a `//` inside
    a literal is kept and a quote inside a comment does not open a literal."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j            # keep the newline
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            out.append(" ")
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _decode(lit_group: str) -> str:
    """Concatenate adjacent literals `"a" "b"` and resolve simple escapes."""
    parts = re.findall(_STR, lit_group)
    return "".join(re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), m.group(1)), p[1:-1]) for p in parts)


def declarations(text: str) -> list[tuple[str, str]]:
    """Every (name, value) where a string literal (or a concatenation of adjacent ones) initialises or is
    assigned to NAME, in source order. Comments are ignored."""
    code = strip_comments(text)
    found = [(m.start(), m.group("name"), _decode(m.group("lit"))) for m in _DECL.finditer(code)]
    found += [(m.start(), m.group("name"), _decode(m.group("lit"))) for m in _DEFINE.finditer(code)]
    return [(n, v) for _s, n, v in sorted(found)]


def is_tag_entry(name: str, value: str) -> bool:
    return "tag" in name.lower() or bool(DURABLE.fullmatch(value))


def inventory(text: str) -> list[tuple[str, str]]:
    """The durable-tag declarations in one header: (name, value) whose name mentions `tag` or whose value
    follows the `ecco_*_vN` convention - declaration style and name are irrelevant."""
    return [(n, v) for n, v in declarations(text) if is_tag_entry(n, v)]


def durable_literals(text: str) -> set[str]:
    """Every string literal in the code (declared or not) that follows the durable-tag convention."""
    code = strip_comments(text)
    vals = {_decode(m.group(0)) for m in re.finditer(_STR, code)}
    vals |= {_decode(m.group("lit")) for m in re.finditer(rf"(?P<lit>{_STR}(?:\s*{_STR})+)", code)}
    return {v for v in vals if DURABLE.fullmatch(v)}


def unaccounted_literals(text: str, extra_accounted: Iterable[str] = (),
                         detector: Callable[[str], list] = inventory) -> set[str]:
    """Durable-looking literals that no inventoried declaration (in this header, or in `extra_accounted`,
    e.g. the other headers' inventory values) accounts for."""
    accounted = {v for _n, v in detector(text)} | set(extra_accounted)
    return durable_literals(text) - accounted


def all_declared_tags(include_dir: Path, detector: Callable[[str], list] = inventory) -> dict[str, str]:
    """{"<header>:<NAME>": value} for every header in `include_dir` (every namespace). A name declared more
    than once in a header gets `#2`, `#3` ... so no declaration is dropped."""
    out: dict[str, str] = {}
    for h in sorted(include_dir.glob("*.h")):
        seen: dict[str, int] = {}
        for name, value in detector(h.read_text(encoding="utf-8")):
            seen[name] = seen.get(name, 0) + 1
            out[f"{h.name}:{name}" + ("" if seen[name] == 1 else f"#{seen[name]}")] = value
    return out


def collision_problems(strings: list[str], key_fn: Callable[[str], int]) -> list[str]:
    """Duplicate strings and duplicate 32-bit preference keys among `strings`."""
    problems = []
    dup = sorted({s for s in strings if strings.count(s) > 1})
    if dup:
        problems.append(f"duplicate tag string(s): {dup}")
    by_key: dict[int, set[str]] = {}
    for s in set(strings):
        by_key.setdefault(key_fn(s), set()).add(s)
    clash = sorted(sorted(v) for v in by_key.values() if len(v) > 1)
    if clash:
        problems.append(f"32-bit preference-key collision(s): {clash}")
    return problems


def check_later_headers(later_headers: Mapping[str, str], declared: frozenset, promoted: frozenset,
                        existing: Iterable[str], prospective: Iterable[str], fba: Iterable[str],
                        key_fn: Callable[[str], int],
                        detector: Callable[[str], list] = inventory) -> list[str]:
    """Everything the tag accounting requires of headers a LATER chain entry added. Returns the list of
    problems (empty = accepted).

      * the tags the later headers declare are EXACTLY the set the chain entries declare (`declared`): a
        wrong string (e.g. `ecco_failback_provision_v2` where v1 was reserved), a missing one and an extra
        one all fail - and so does a detector that finds nothing;
      * every `promoted` tag (a FB-A PROSPECTIVE tag now declared for real) is among the declared ones;
      * no durable-looking literal in a later header escapes the inventory;
      * over existing + later + still-unpromoted prospective + FB-A tags: no duplicate string and no
        duplicate 32-bit key.
    """
    problems: list[str] = []
    later_values: list[str] = []
    for name, text in sorted(later_headers.items()):
        later_values += [v for _n, v in detector(text)]
    if set(later_values) != set(declared):
        problems.append(f"declared tags != inventoried tags (missing {sorted(set(declared) - set(later_values))}, "
                        f"undeclared {sorted(set(later_values) - set(declared))})")
    if not promoted <= declared:
        problems.append(f"promoted tag(s) not declared: {sorted(promoted - declared)}")
    accounted = set(later_values) | set(existing) | set(fba)
    for name, text in sorted(later_headers.items()):
        lost = unaccounted_literals(text, accounted, detector)
        if lost:
            problems.append(f"{name}: durable literal(s) escape the inventory: {sorted(lost)}")
    strings = list(existing) + later_values + [s for s in prospective if s not in promoted] + list(fba)
    problems += collision_problems(strings, key_fn)
    return problems
