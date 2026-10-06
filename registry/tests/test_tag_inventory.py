#!/usr/bin/env python3
"""FB-T0 hardening (Cloud B red-team): the durable-tag inventory and its negative controls.

Test-only. No firmware, no hardware, no I/O beyond reading repo headers and the FB-A suite's own source.

The FB-A collision suite used to find durable tags with ONE regex for ONE declaration style. The planned
FB-B0 declaration is the same style today, but a legitimate rewrite (`std::string_view`, wrapped literal,
`#define`, a name not ending `_TAG`) would have escaped the collision accounting with the suite still green.
registry/tests/_tag_inventory.py now finds declarations independent of style AND cross-checks every
durable-looking string literal. This file proves that, with the planned FBW declaration
(`FAILBACK_PROVISION_TAG = "ecco_failback_provision_v1"`, S2 §2.2) as the test subject.

  [1] AGREEMENT: on today's headers the hardened inventory == the original single-style regex (two
      independent implementations); no header has an unaccounted durable literal.
  [2] COVERAGE: spacing, pointer / array / sized-array, string_view (brace, paren, = forms), wrapped and
      concatenated literals, #define, names that do not end `_TAG`, namespaces; comments and non-tag
      string constants are NOT inventoried.
  [3] ACCEPTANCE: the planned FBW header is accepted by the shared check.
  [4] NEGATIVE CONTROLS: wrong string `_v2`; exact duplicate of an existing tag; a DIFFERENT string that
      collides with an existing 32-bit preference key; FBW tag equal to the still-unpromoted prospective
      tag; a durable literal used only as a call argument; an extra undeclared tag; a missing declared tag.
  [5] BYPASS: with the detector removed the controls' specific diagnoses disappear, the verdict is still a
      FAILURE (declared tags missing), and the real FB-A suite fails a static check when its detector calls
      are removed.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry"))
import _tag_inventory as ti  # noqa: E402
import fallback_profile as fp  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


INCLUDE = ROOT / "firmware" / "include"
FBW = "ecco_failback_provision_v1"
KEY = fp.tag_key_fnv1_32
# A DIFFERENT string whose ESPHome preference key (32-bit FNV-1) equals that of the existing
# "ecco_free_power_retry_state_v1" (found by meet-in-the-middle; re-verified below, not trusted).
KEY_COLLIDER = "ecco_failback_provision_lcc8aby1_v1"
EXISTING_TAG = "ecco_free_power_retry_state_v1"
BYPASS = lambda _text: []  # noqa: E731 - "the detector was removed / bypassed"

# ===========================================================================
print("[1] the hardened inventory agrees with the original regex on today's headers; nothing escapes")
# ===========================================================================
import re  # noqa: E402

LEGACY = re.compile(r'constexpr (?:const )?char (?:\*\s*)?([A-Z0-9_]+_TAG(?:_V\d+)?)(?:\[\])? = "([^"]+)";')
# This suite must survive later PRs adding headers (it is never edited again): it is pinned to the three headers that exist on
# main @ ca7474e. Headers a later chain entry adds are accounted by the FB-A suite's check_later_headers() call instead.
PRE_HEADERS = ("ecco_durable_snapshot.h", "ecco_fallback_profile.h", "ecco_recovery_evidence.h")
texts = {n: (INCLUDE / n).read_text(encoding="utf-8") for n in PRE_HEADERS}
legacy = {f"{n}:{name}": v for n, tx in texts.items() for name, v in LEGACY.findall(tx)}
robust = {k: v for k, v in ti.all_declared_tags(INCLUDE).items() if k.split(":")[0] in PRE_HEADERS}
check("hardened inventory == the original single-style regex on every pre-existing firmware/include header (16 declarations)",
      legacy == robust and len(robust) == 16, str(set(legacy.items()) ^ set(robust.items())))
check("no pre-existing header has a durable-looking literal outside the inventory", all(
    not ti.unaccounted_literals(tx, set(robust.values())) for tx in texts.values()))
check("the durable header's 13 durable literals and the FB-A header's 2 are all inventoried",
      len(ti.durable_literals(texts["ecco_durable_snapshot.h"])) == 13 and len(ti.durable_literals(texts["ecco_fallback_profile.h"])) == 2)
check("FB-A's binding-domain constants (uppercase, not preference tags) are NOT inventoried",
      not any("BINDING_DOMAIN" in k for k in robust))
check("the planned FBW key collider really collides with an existing key but is a different, convention-following string",
      KEY(KEY_COLLIDER) == KEY(EXISTING_TAG) and KEY_COLLIDER != EXISTING_TAG and ti.DURABLE.fullmatch(KEY_COLLIDER) is not None)

# ===========================================================================
print("")
print("[2] declaration-style coverage")
# ===========================================================================
FORMS = {
    "planned S2 form": f'constexpr char     FAILBACK_PROVISION_TAG[] = "{FBW}";',
    "no spaces": f'constexpr const char*FAILBACK_PROVISION_TAG="{FBW}";',
    "pointer, const pointer": f'constexpr const char *const FAILBACK_PROVISION_TAG = "{FBW}";',
    "sized array": f'constexpr char FAILBACK_PROVISION_TAG[27] = "{FBW}";',
    "non-const array": f'static char FAILBACK_PROVISION_TAG[] = "{FBW}";',
    "string_view brace": f'inline constexpr std::string_view FAILBACK_PROVISION_TAG{{"{FBW}"}};',
    "string_view paren init": f'inline constexpr std::string_view FAILBACK_PROVISION_TAG = std::string_view("{FBW}");',
    "string_view brace init": f'inline constexpr std::string_view FAILBACK_PROVISION_TAG = std::string_view{{"{FBW}"}};',
    "auto": f'static constexpr auto FAILBACK_PROVISION_TAG = "{FBW}";',
    "wrapped declaration": f'constexpr char\n    FAILBACK_PROVISION_TAG[]\n        =\n        "{FBW}";',
    "wrapped / concatenated literal": 'constexpr char FAILBACK_PROVISION_TAG[] =\n    "ecco_failback_"\n    "provision_v1";',
    "#define": f'#define FAILBACK_PROVISION_TAG "{FBW}"',
    "#define spaced": f'#  define   FAILBACK_PROVISION_TAG    "{FBW}"',
    "name NOT ending _TAG (kFbwKey)": f'constexpr const char *kFbwKey = "{FBW}";',
    "name without tag at all": f'constexpr char PROVISION_KEY_NAME[] = "{FBW}";',
    "inside a namespace block": f'namespace ecco_fbdurable {{\nconstexpr char FAILBACK_PROVISION_TAG[] = "{FBW}";\n}}  // namespace',
    "trailing comment": f'constexpr char FAILBACK_PROVISION_TAG[] = "{FBW}";  // frozen v1',
}
for label, src in FORMS.items():
    check(f"inventoried, value exact: {label}", [v for _n, v in ti.inventory(src)] == [FBW], str(ti.inventory(src)))
check("the declared NAME is reported (not just the value)", [n for n, _v in ti.inventory(FORMS["name NOT ending _TAG (kFbwKey)"])] == ["kFbwKey"])
check("a declaration in a // comment or /* */ block is NOT inventoried",
      ti.inventory(f'// constexpr char X_TAG[] = "{FBW}";\n/* constexpr char Y_TAG[] = "ecco_fake_v1"; */\n') == [])
check("a `//` inside a string literal does not hide a following declaration",
      [v for _n, v in ti.inventory(f'constexpr char URL[] = "http://x";\nconstexpr char FAILBACK_PROVISION_TAG[] = "{FBW}";\n')] == [FBW])
check("a non-tag string constant is NOT inventoried",
      ti.inventory('constexpr char PROVISION_BINDING_DOMAIN[] = "ECCO-FAILBACK-PROVISION-v1";\nconstexpr char GREETING[] = "hello";') == [])
check("comparisons and calls are not declarations", ti.declarations('if (x == "ecco_a_v1") {}\nf("ecco_b_v1");') == [])
check("a durable literal used only as a call argument is reported as UNACCOUNTED (not silently ignored)",
      ti.unaccounted_literals('void f() { register_key("ecco_failback_provision_v1"); }') == {FBW})
check("a concatenated durable literal is reconstructed for the literal scan",
      ti.durable_literals('f("ecco_failback_" "provision_v1");') == {FBW})

# ===========================================================================
print("")
print("[3] the planned FBW header is accepted")
# ===========================================================================
EXISTING = [v for k, v in robust.items() if not k.startswith("ecco_fallback_profile.h:")]
FBA = (fp.FALLBACK_PROFILE_TAG, fp.FAILBACK_STATE_TAG)
PROSPECTIVE = (FBW,)    # FB-A's reservation; pinned here so this suite does not depend on the (later-amendable) model constant
# (no include of the FB-A header here: the FB-A includers scan would - rightly - flag this file as an undeclared includer)
OK_HEADER = f'#pragma once\nconstexpr char FAILBACK_PROVISION_TAG[] = "{FBW}";\n'


def verdict(header: str, declared=frozenset({FBW}), promoted=frozenset({FBW}), detector=ti.inventory) -> list[str]:
    return ti.check_later_headers({"ecco_fallback_durable_model.h": header}, frozenset(declared), frozenset(promoted),
                                  EXISTING, PROSPECTIVE, FBA, KEY, detector)


check("the planned FBW declaration (declared + promoted) is accepted", verdict(OK_HEADER) == [], str(verdict(OK_HEADER)))
for label, src in FORMS.items():
    check(f"accepted in an alternative style too: {label}", verdict(f"#pragma once\n{src}\n") == [], str(verdict(f"#pragma once\n{src}\n")))

# ===========================================================================
print("")
print("[4] negative controls (each mutant must be DETECTED, with the specific diagnosis)")
# ===========================================================================
WRONG = f'constexpr char FAILBACK_PROVISION_TAG[] = "ecco_failback_provision_v2";\n'
WRONG_SV = 'inline constexpr std::string_view kFbw{"ecco_failback_provision_v2"};\n'
DUP = f'constexpr char FAILBACK_PROVISION_TAG[] = "{EXISTING_TAG}";\n'
KEYC = f'constexpr char FAILBACK_PROVISION_TAG[] = "{KEY_COLLIDER}";\n'


def has(problems: list[str], needle: str) -> bool:
    return any(needle in p for p in problems)


pw = verdict("#pragma once\n" + WRONG)
check("FBW carrying the WRONG string ecco_failback_provision_v2 is detected: the reserved v1 is reported missing and v2 undeclared", has(pw, "declared tags != inventoried") and "ecco_failback_provision_v2" in pw[0]
      and "ecco_failback_provision_v1" in pw[0], str(pw))
pw2 = verdict("#pragma once\n" + WRONG_SV)
check("...also when the wrong string hides in a non-_TAG, string_view declaration", has(pw2, "declared tags != inventoried"), str(pw2))
pw3 = verdict("#pragma once\n" + WRONG, declared={"ecco_failback_provision_v2"}, promoted={FBW})
check("...and when the entry 'declares' v2 but still claims to promote the reserved v1 tag", has(pw3, "promoted tag(s) not declared"), str(pw3))
pd = verdict("#pragma once\n" + DUP, declared={EXISTING_TAG}, promoted=set())
check("an FBW string EQUAL to an existing preference tag is detected (duplicate string)", has(pd, "duplicate tag string"), str(pd))
pk = verdict("#pragma once\n" + KEYC, declared={KEY_COLLIDER}, promoted=set())
check("an FBW string that is DIFFERENT but collides with an existing 32-bit preference key is detected", has(pk, "32-bit preference-key collision")
      and EXISTING_TAG in str(pk) and KEY_COLLIDER in str(pk), str(pk))
pp = verdict(OK_HEADER, declared={FBW}, promoted=set())
check("declaring the reserved provision tag WITHOUT promoting it (counted twice) is detected", has(pp, "duplicate tag string"), str(pp))
pe = verdict(OK_HEADER + 'constexpr char EXTRA_TAG[] = "ecco_fbw_extra_v1";\n')
check("an EXTRA undeclared tag in a later header is detected", has(pe, "undeclared ['ecco_fbw_extra_v1']"), str(pe))
pm = verdict(OK_HEADER, declared={FBW, "ecco_fbw_other_v1"})
check("a declared tag that no header declares is detected", has(pm, "missing ['ecco_fbw_other_v1']"), str(pm))
pl = verdict(OK_HEADER + 'void reg() { register_key("ecco_fbw_hidden_v1"); }\n')
check("a durable literal used only as a call argument (no declaration) is detected as escaping the inventory",
      has(pl, "escape the inventory") and "ecco_fbw_hidden_v1" in str(pl), str(pl))

# ===========================================================================
print("")
print("[5] bypass: removing the detector is itself a failure, and the controls depend on it")
# ===========================================================================
bad = {"wrong v2": ("#pragma once\n" + WRONG, {FBW}, {FBW}), "duplicate": ("#pragma once\n" + DUP, {EXISTING_TAG}, set()),
       "key collision": ("#pragma once\n" + KEYC, {KEY_COLLIDER}, set())}
for label, (hdr, dec, pro) in bad.items():
    bp = verdict(hdr, dec, pro, detector=BYPASS)
    check(f"detector bypassed, control mutant '{label}': the verdict is still a FAILURE (declared tags are no longer inventoried)",
          bool(bp) and has(bp, "declared tags != inventoried"), str(bp))
check("detector bypassed: the specific collision / duplicate diagnoses are GONE (they need the detector) - so a suite that "
      "lost its detector call could not produce them",
      not has(verdict(bad["duplicate"][0], bad["duplicate"][1], bad["duplicate"][2], detector=BYPASS), "duplicate tag string")
      and not has(verdict(bad["key collision"][0], bad["key collision"][1], bad["key collision"][2], detector=BYPASS), "32-bit"))
check("detector bypassed, CLEAN planned header: still a failure (an empty inventory never passes a declared tag)",
      bool(verdict(OK_HEADER, detector=BYPASS)))
check("detector bypassed on today's headers: the inventory is empty and the 16-declaration agreement check above would fail",
      ti.all_declared_tags(INCLUDE, BYPASS) == {} != robust)
SUITE = (HERE / "test_fallback_profile_schema.py").read_text(encoding="utf-8")
NEEDED = ("ti.all_declared_tags(", "ti.check_later_headers(", "ti.unaccounted_literals(", "ti.collision_problems(")


def suite_uses_detector(src: str) -> bool:
    return all(n in src for n in NEEDED)


check("the real FB-A suite calls the inventory, the literal scan, the later-header check and the collision check",
      suite_uses_detector(SUITE))
check("mutant FB-A suite with the later-header check bypassed fails this static check",
      not suite_uses_detector(SUITE.replace("ti.check_later_headers(", "(lambda *a, **k: [])(")))
check("mutant FB-A suite with the inventory call replaced by the old regex only fails this static check",
      not suite_uses_detector(SUITE.replace("ti.all_declared_tags(", "dict(")))
check("mutant FB-A suite with the literal scan removed fails this static check",
      not suite_uses_detector(SUITE.replace("ti.unaccounted_literals(", "set(")))

# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All durable-tag inventory checks passed.")
print("These pin how tags are found and how collisions are accounted; they prove nothing about NVS or hardware.")
