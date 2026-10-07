#!/usr/bin/env python3
"""The firmware YAML loader is a pure speed choice: `_dump_sim.load_firmware_text` parses with libyaml's safe parser when PyYAML
ships it, and it must build EXACTLY the tree the pure-Python safe loader `_dump_sim._Loader` builds.

yaml.CSafeLoader joins libyaml's scanner/parser to the very SafeConstructor and Resolver classes yaml.SafeLoader uses, so every
value, type and tag is still built by the same Python code; the registry suites parse the 1.28 MB firmware about 1,300 times per
run, and libyaml scans it about 9x faster. Nothing below relies on that argument: every case parses the same text with both
loaders and compares the two trees structurally - exact types (LambdaStr included), values, mapping key order and alias sharing.

  [1] selection     with libyaml the firmware loader is a CSafeLoader subclass (never Loader / FullLoader / UnsafeLoader) carrying
                    the same '!' multi-constructor as _Loader; without libyaml it IS _Loader
  [2] firmware      every tracked firmware/ecco_*.yaml parses identically, and load_firmware_text() returns that tree plus
                    _substitutions / _text exactly as before
  [3] mutants       firmware texts the mutation stages really build (a fixed sample of the SAVE-gates and INVALIDATE YAML
                    mutants) and synthetic edits (typed substitutions, a removed script, an appended comment) parse identically
  [4] edge corpus   YAML 1.1 bools / nulls / ints in every base / sexagesimal / floats incl. inf, nan, -0.0 / timestamps;
                    quoting and escapes; block scalars (| and > with - and +); anchors, aliases and merge keys; !!binary,
                    !!set, !!omap, !!pairs; duplicate and non-string keys; unicode; every '!' tag form (scalar, sequence,
                    mapping, empty); the same corpus again with CRLF line ends and with a BOM
  [5] errors        malformed documents fail in both loaders with the same error class (none parses in only one)
  [6] comparator    negative controls: a type-only, an order-only, a value-only, a sharing-only and a LambdaStr-only difference
                    are each reported, and nan / -0.0 are compared exactly, so [2]-[5] cannot pass vacuously

No I/O beyond reading repository files.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def tree_diff(a, b) -> str | None:
    """None when a and b are the same tree: identical types, equal values (nan equals nan; -0.0 is not 0.0), the same mapping key
    order, and the same sharing (a container reached twice in one tree is one container reached twice in the other)."""
    pair: dict[int, int] = {}
    back: dict[int, int] = {}
    stack = [(a, b, "$")]
    while stack:
        x, y, path = stack.pop()
        if type(x) is not type(y):
            return f"{path}: type {type(x).__name__} != {type(y).__name__}"
        if isinstance(x, (dict, list, tuple, set)):
            ix, iy = id(x), id(y)
            if ix in pair or iy in back:
                if pair.get(ix) != iy or back.get(iy) != ix:
                    return f"{path}: shared differently"
                continue
            pair[ix], back[iy] = iy, ix
            if isinstance(x, dict):
                kx, ky = list(x), list(y)
                if len(kx) != len(ky):
                    return f"{path}: {len(kx)} keys != {len(ky)} keys"
                for i, (k1, k2) in enumerate(zip(kx, ky)):
                    d = tree_diff(k1, k2)
                    if d:
                        return f"{path}: key #{i}: {d}"
                    stack.append((x[k1], y[k2], f"{path}[{k1!r}]"))
            elif isinstance(x, set):
                if x != y or sorted((type(e).__name__, repr(e)) for e in x) != sorted((type(e).__name__, repr(e)) for e in y):
                    return f"{path}: sets differ"
            else:
                if len(x) != len(y):
                    return f"{path}: length {len(x)} != {len(y)}"
                stack.extend((e1, e2, f"{path}[{i}]") for i, (e1, e2) in enumerate(zip(x, y)))
        elif isinstance(x, float):
            if not ((math.isnan(x) and math.isnan(y)) or (x == y and math.copysign(1.0, x) == math.copysign(1.0, y))):
                return f"{path}: {x!r} != {y!r}"
        elif x != y:
            return f"{path}: values differ"
    return None


def values_of(o):
    """Every value in a parsed tree (depth first)."""
    stack = [o]
    while stack:
        v = stack.pop()
        yield v
        if isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, (list, tuple)):
            stack.extend(v)


PURE = ds._Loader
FAST = ds.FIRMWARE_LOADER


def both(text: str):
    return yaml.load(text, Loader=PURE), yaml.load(text, Loader=FAST)


def same_parse(text: str) -> str | None:
    a, b = both(text)
    return tree_diff(a, b)


# ---------------------------------------------------------------------------
print("[1] selection")
# ---------------------------------------------------------------------------
UNSAFE = tuple(c for c in (yaml.Loader, yaml.FullLoader, yaml.UnsafeLoader, getattr(yaml, "CLoader", None),
                           getattr(yaml, "CFullLoader", None), getattr(yaml, "CUnsafeLoader", None)) if c is not None)
check("the pure-Python firmware loader is still a SafeLoader subclass with the '!' multi-constructor",
      issubclass(PURE, yaml.SafeLoader) and PURE.yaml_multi_constructors.get("!") is ds._tagged)
if getattr(yaml, "__with_libyaml__", False):
    check("libyaml is available: the firmware loader is a CSafeLoader subclass with the same '!' multi-constructor",
          issubclass(FAST, yaml.CSafeLoader) and FAST is not PURE and FAST.yaml_multi_constructors.get("!") is ds._tagged)
    check("...whose constructors and resolvers are yaml.SafeLoader's (only the scanner/parser differs)",
          issubclass(FAST, yaml.constructor.SafeConstructor) and issubclass(FAST, yaml.resolver.Resolver)
          and FAST.yaml_constructors == PURE.yaml_constructors and FAST.yaml_implicit_resolvers == PURE.yaml_implicit_resolvers)
    check("registering the '!' constructor on the firmware loader did not touch yaml.CSafeLoader itself",
          "!" not in yaml.CSafeLoader.yaml_multi_constructors)
else:
    check("libyaml is not available: the firmware loader IS the pure-Python _Loader", FAST is PURE)
check("the firmware loader is never an unsafe loader (Loader / FullLoader / UnsafeLoader or their C forms)",
      not any(issubclass(FAST, u) for u in UNSAFE), str([u.__name__ for u in UNSAFE if issubclass(FAST, u)]))

# ---------------------------------------------------------------------------
print("[2] firmware")
# ---------------------------------------------------------------------------
FW_FILES = sorted((ROOT / "firmware").glob("ecco_*.yaml"))
check("the firmware directory holds the four tracked firmware YAMLs this compares", len(FW_FILES) >= 4, str([p.name for p in FW_FILES]))
LIVE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
for p in FW_FILES:
    d = same_parse(p.read_text(encoding="utf-8"))
    check(f"{p.name}: identical tree from both loaders", d is None, d or "")
live = LIVE_PATH.read_text(encoding="utf-8")
got = ds.load_firmware_text(live)
want = yaml.load(live, Loader=PURE)
want["_substitutions"] = {k: str(v) for k, v in (want.get("substitutions") or {}).items()}
want["_text"] = live
d = tree_diff(want, got)
check("load_firmware_text(live firmware) == the pure loader's tree + _substitutions + _text (as before)", d is None, d or "")
check("...and the live firmware really exercises the '!' constructor (LambdaStr values are present)",
      any(isinstance(v, ds.LambdaStr) for v in values_of(got)))

# ---------------------------------------------------------------------------
print("[3] mutants")
# ---------------------------------------------------------------------------
import _fbb2_gates_lib as GL  # noqa: E402
import _fbb2_gates_mutants as GM  # noqa: E402
import _fbb2_invalidate_mut as IM  # noqa: E402


def gates_text(m) -> str:
    """The firmware text a SAVE-gates YAML mutant builds (exactly the edits Mutant.build() applies before it parses)."""
    text = GL.live_text()
    for e in m.yaml:
        if e[0] == "script":
            text = GL.edit_script(text, e[1], e[2], e[3], e[4] if len(e) > 4 else 1)
        else:
            text = GL.edit_text(text, e[1], e[2], e[3] if len(e) > 3 else 1)
    return text


gates_yaml = [m for m in GM.MUTANTS if m.yaml]
inv_yaml = [m for m in IM.yaml_mutants() if m.kind == "yaml" and m.text]
sample = [(f"gates {m.mid}", gates_text(m)) for m in gates_yaml[::max(1, len(gates_yaml) // 6)][:6]]
sample += [(f"invalidate {m.mid}", m.text) for m in inv_yaml[::max(1, len(inv_yaml) // 6)][:6]]
check(f"a fixed sample of 12 real YAML mutants ({len(gates_yaml)} gates, {len(inv_yaml)} INVALIDATE defined), each a changed text",
      len(sample) == 12 and all(t != live for _n, t in sample), str([n for n, t in sample if t == live]))
for name, text in sample:
    d = same_parse(text)
    check(f"mutant {name}: identical tree from both loaders", d is None, d or "")
synthetic = {
    "typed substitutions (hex, inf, quoted 'on', null, a list)": live.replace(
        "substitutions:\n", "substitutions:\n  ecco_ylt_hex: 0x1F\n  ecco_ylt_inf: .inf\n  ecco_ylt_on: 'on'\n  ecco_ylt_null: ~\n"
                            "  ecco_ylt_list: [1, two, 3.0]\n", 1),
    "the first script removed": live.replace("\n  - id: ", "\n  - removed_id: ", 1),
    "an appended comment and blank lines": live + "\n\n# appended\n",
}
check("each synthetic edit changed the text", all(t != live for t in synthetic.values()))
for name, text in synthetic.items():
    d = same_parse(text)
    check(f"synthetic mutant ({name}): identical tree from both loaders", d is None, d or "")
fw_syn = ds.load_firmware_text(synthetic["typed substitutions (hex, inf, quoted 'on', null, a list)"])
check("load_firmware_text keeps stringifying substitution values the old way (31, inf, on, None, the list)",
      [fw_syn["_substitutions"][k] for k in ("ecco_ylt_hex", "ecco_ylt_inf", "ecco_ylt_on", "ecco_ylt_null", "ecco_ylt_list")]
      == ["31", "inf", "on", "None", "[1, 'two', 3.0]"])

# ---------------------------------------------------------------------------
print("[4] edge corpus")
# ---------------------------------------------------------------------------
EDGE = """\
bools: [yes, no, on, off, true, false, True, FALSE, Yes, NO, y, n, Y, N]
nulls: [~, null, Null, NULL, "", '']
ints: [0, -17, +5, 0o17, 017, 0x1F, 0b101, 1_000, 190:20:30, 0xFF_FF]
floats: [1.5, -0.0, 0.0, .inf, -.Inf, +.INF, .NaN, 6.8523015e+5, 685.230_15e+03, 190:20:30.15, 1e3, 1.0e+3, .5]
strings: ['single', "double \\t \\u263A \\x41 \\\\ \\"", plain text, 'it''s', "multi
  line", "  padded  ", '#not a comment', "a: b", "0123", "1e3x"]
block_literal: |
  keep
    indent
  trailing
block_strip: |-
  strip
block_keep: |+
  keep

folded: >
  folded
  text

  para
folded_strip: >-
  a
  b
indent_indicator: |2
    two extra
timestamps: [2001-12-14t21:59:43.10-05:00, 2001-12-14, 2002-12-14 21:59:43.10 -5, 2001-12-15T02:59:43.1Z]
binary: !!binary "SGVsbG8sIFdvcmxkIQ=="
set: !!set {a, b, 1}
omap: !!omap [{a: 1}, {b: 2}]
pairs: !!pairs [{a: 1}, {a: 2}]
str_tag: !!str 123
int_tag: !!int "42"
float_tag: !!float "1"
anchors:
  base: &base {x: 1, y: [1, 2]}
  ref: *base
  merged: {<<: *base, y: 3}
  multi_merge: {<<: [*base, {z: 9}], w: 0}
  list: &lst [1, 2]
  again: *lst
  scalar: &s shared
  scalar_again: *s
tags:
  lam: !lambda "return 1;"
  lam_block: !lambda |-
    if (x) {
      return y;
    }
  lam_empty: !lambda ""
  secret: !secret wifi_password
  include_seq: !include [a, b]
  extend_map: !extend {id: x, n: 1}
  other: !remove
dup: 1
dup: 2
keys: {1: int, "1": str, true: bool, 1.5: float, null: none, [a, b]: seq_key_is_not_allowed_in_safe}
unicode: "\\u00e9 \\u00fc \\u4e2d \\U0001F642 e\\u0301"
raw_unicode: é ü 中 🙂
tabs: "a\\tb"
long_line: "%s"
nested: {a: {b: {c: {d: [1, [2, [3, {e: f}]]]}}}}
empty_map: {}
empty_seq: []
""" % ("x" * 5000)
EDGE_SAFE = EDGE.replace(", [a, b]: seq_key_is_not_allowed_in_safe", "")   # complex keys are an error in both: tested in [5]
for label, text in (("LF", EDGE_SAFE), ("CRLF", EDGE_SAFE.replace("\n", "\r\n")), ("BOM", "\ufeff" + EDGE_SAFE)):
    try:
        d = same_parse(text)
        check(f"edge corpus ({label}): identical tree from both loaders", d is None, d or "")
    except Exception as ex:  # noqa: BLE001 - a corpus that no longer parses is a failed check
        check(f"edge corpus ({label}): parses with both loaders", False, f"{type(ex).__name__}: {str(ex)[:200]}")
edge = yaml.load(EDGE_SAFE, Loader=FAST)
check("the edge corpus really builds the special values it is meant to cover (nan, -0.0, LambdaStr, bytes, set, alias, merge)",
      math.isnan(edge["floats"][6]) and math.copysign(1.0, edge["floats"][1]) == -1.0
      and type(edge["tags"]["lam"]) is ds.LambdaStr and type(edge["tags"]["secret"]) is str
      and isinstance(edge["binary"], bytes) and isinstance(edge["set"], set)
      and edge["anchors"]["ref"] is edge["anchors"]["base"] and edge["anchors"]["merged"] == {"x": 1, "y": 3}
      and edge["dup"] == 2 and edge["ints"][4] == 15 and edge["ints"][8] == 685230 and edge["bools"][2] is True)

# ---------------------------------------------------------------------------
print("[5] errors")
# ---------------------------------------------------------------------------
BAD = {
    "unclosed flow sequence": "a: [1, 2\n",
    "mapping value in a plain scalar": "a: b: c\n",
    "tab indentation": "a:\n\t- 1\n",
    "unterminated quote": "key: 'unterminated\n",
    "block end expected": "- a\nb: 1\n",
    "undefined alias": "a: *nope\n",
    "control character": "a: \x01\n",
    "complex mapping key (unhashable in safe construction)": "{[a, b]: c}\n",
    "complex keys in the edge corpus": EDGE,
}


def outcome(text: str, loader) -> str:
    try:
        yaml.load(text, Loader=loader)
        return "parsed"
    except yaml.YAMLError as ex:
        return f"YAMLError:{type(ex).__name__}"
    except Exception as ex:  # noqa: BLE001
        return f"other:{type(ex).__name__}"


for label, text in BAD.items():
    a, b = outcome(text, PURE), outcome(text, FAST)
    check(f"malformed ({label}): both loaders fail the same way ({a})", a == b and a != "parsed", f"pure {a}, firmware loader {b}")

# ---------------------------------------------------------------------------
print("[6] comparator negative controls")
# ---------------------------------------------------------------------------
shared = [1]
check("a type-only difference is reported (1 vs True)", tree_diff({"a": 1}, {"a": True}) is not None)
check("an order-only difference is reported", tree_diff({"a": 1, "b": 2}, {"b": 2, "a": 1}) is not None)
check("a value-only difference is reported", tree_diff([1.0, "x"], [1.5, "x"]) is not None)
check("a sharing-only difference is reported", tree_diff({"p": shared, "q": shared}, {"p": [1], "q": [1]}) is not None)
check("a LambdaStr-only difference is reported", tree_diff([ds.LambdaStr("x")], ["x"]) is not None)
check("nan equals nan, and -0.0 is not 0.0", tree_diff([float("nan")], [float("nan")]) is None and tree_diff([-0.0], [0.0]) is not None)
check("identical trees compare equal (control)", tree_diff({"a": [1, {"b": ds.LambdaStr("c")}]}, {"a": [1, {"b": ds.LambdaStr("c")}]}) is None)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All firmware YAML loader checks passed.")
