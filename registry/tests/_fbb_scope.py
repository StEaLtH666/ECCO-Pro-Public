"""FB-B0 change scope: the exact edits FB-B0 makes to the firmware YAML (the
esphome: block's min_version and includes list) as (before, after) text
pairs, plus the inventory of files FB-B0 adds.

Same technique as _dump_v2_scope.py / _sg06_scope.py / _mtou1_scope.py.
Earlier suites pin the firmware YAML (whole-file sha, the parsed esphome
block, the includes list) as change-scope proofs, and FB-B0 has to edit the
esphome: block (architecture section 12, FB-B0 row: "FW YAML esphome: block
only"). Those suites are not re-pinned to new hashes, which would silently
widen what they accept. Instead they hash the current text with exactly these
edits reverted. Every `after` must occur exactly once (else AssertionError),
so any OTHER change still breaks their pins.
registry/tests/test_fallback_durable_model.py pins that the revert reproduces
the firmware as of chain entry fbc1 byte for byte (and, through FB-C1's own
reverter, main @ b3fcdfc), and that the parsed documents differ only in
esphome.min_version and esphome.includes.

Integration with FB-T0 (the cumulative scope chain, registry/tests/_scope_chain.py,
merged as #56): FB-B0 is the chain entry "fbb0", appended after "fbc1"
(FB-C1, #57). Its reverter is `pre_fbb0_firmware` below, unchanged: it edits
only the esphome: block, so it commutes with FB-C1's reverter and, applied to
the current firmware, yields the recorded fbc1 checkpoint byte for byte. The
older suites need no edit - they anchor at fba / mtou1 / dump_v2 and the chain
reverts fbc1 and fbb0 for them. BASE_COMMIT / BASE_FIRMWARE_SHA below are the
PREP base (main @ b3fcdfc = the chain's dump_v2 state), not the state FB-B0 is
merged onto; the merged base is chain entry fbc1 (see test_fallback_durable_model.py
[13] and [15]). The allowlists at the end (FB-A includers, FB token lines) are
what the chain entry declares (`fbh_includers`, `banned_fw_added`).

Generated from the real diff against b3fcdfc and verified by round trip
(raw LF-newline file form). No I/O.
"""

from __future__ import annotations

import hashlib

BASE_COMMIT = "b3fcdfc175478491b32c21acfe643b0c3a972d85"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 of the LF text of the firmware YAML on main @ b3fcdfc: what
# pre_fbb0_firmware() must reproduce.
BASE_FIRMWARE_SHA = "9d09152744250623ec2f4e3e206a928f1251fb0b1dcf7b3ae1a858c5ae4ec314"

MIN_VERSION_BEFORE = "2026.4.0"
MIN_VERSION_AFTER = "2026.8.2"
BASE_INCLUDES = ("include/ecco_durable_snapshot.h", "include/ecco_recovery_evidence.h")
# Order matters only for readability: every header includes its own
# dependencies (#pragma once). ESPHome copies each listed file next to
# main.cpp, so the FB-A header MUST be listed: the model header includes it
# by name.
ADDED_INCLUDES = (
    "include/ecco_fallback_profile.h",
    "include/ecco_fallback_version_pins.h",
    "include/ecco_fallback_durable_model.h",
    "include/ecco_fallback_durable.h",
)

# The YAML includes lines are generated from the tuples above (never spelled out here), so no text scan for
# "- include/<header>" mistakes this module for a firmware file that includes a header.
_INCLUDE_LINE = "    - {}\n"
FIRMWARE_TEXT_EDITS = [
    (f"  min_version: {MIN_VERSION_BEFORE}\n  name_add_mac_suffix: false\n",
     f"  min_version: {MIN_VERSION_AFTER}\n  name_add_mac_suffix: false\n"),
    (_INCLUDE_LINE.format(BASE_INCLUDES[-1]) + "\n  on_boot:\n",
     "".join(_INCLUDE_LINE.format(i) for i in (BASE_INCLUDES[-1], *ADDED_INCLUDES)) + "\n  on_boot:\n"),
]

# Files FB-B0 adds (nothing else is added; the YAML edit above is the only
# modification of an existing file).
ADDED_FILES = (
    "firmware/include/ecco_fallback_version_pins.h",
    "firmware/include/ecco_fallback_durable_model.h",
    "firmware/include/ecco_fallback_durable.h",
    "registry/fallback_durable.py",
    "registry/tests/_fbb_harness.py",
    "registry/tests/_fbb_scope.py",
    "registry/tests/check_fbb_esphome_source_facts.py",
    "registry/tests/fixtures/fbb_nvs_keyhash_fixture.json",
    "registry/tests/test_fallback_durable_harness.py",
    "registry/tests/test_fallback_durable_host_compile.py",
    "registry/tests/test_fallback_durable_model.py",
    "registry/tests/test_fallback_nvs_keyhash.py",
)
MODIFIED_FILES = (FIRMWARE_REL, "registry/tests/_free_power_action_sim.py", "CHANGELOG.md", "CURRENT_STATE.md")

# Allowlists for the #54 [9] conversion (FB-A's production-reference scan):
# the ONLY production files that may include the FB-A header after FB-B0,
FBA_INCLUDERS = (FIRMWARE_REL, "firmware/include/ecco_fallback_durable_model.h")
# and the ONLY firmware-YAML lines that may name an ecco_fallback* /
# ecco_failback* token (the four includes entries - no lambda, no entity).
FW_FB_TOKEN_LINES = tuple(f"    - {inc}" for inc in ADDED_INCLUDES)


def _revert(text: str, edits, what: str) -> str:
    for before, after in edits:
        found = text.count(after)
        if found != 1:
            raise AssertionError(f"FB-B0 {what} edit found {found}x (expected exactly once): {after[:70]!r}")
        text = text.replace(after, before)
    return text


def pre_fbb0_firmware(fw_text: str) -> str:
    """The whole firmware YAML with exactly FB-B0's edits reverted: main @
    b3fcdfc byte for byte (BASE_FIRMWARE_SHA)."""
    return _revert(fw_text, FIRMWARE_TEXT_EDITS, "firmware")


def pre_fbb0_esphome(esphome: dict) -> dict:
    """The parsed esphome: block with exactly FB-B0's edits reverted
    (min_version, includes); raises unless they are present exactly."""
    out = dict(esphome)
    if str(out.get("min_version")) != MIN_VERSION_AFTER:
        raise AssertionError(f"FB-B0 esphome.min_version: expected {MIN_VERSION_AFTER}, found {out.get('min_version')!r}")
    includes = list(out.get("includes") or [])
    if includes != [*BASE_INCLUDES, *ADDED_INCLUDES]:
        raise AssertionError(f"FB-B0 esphome.includes: expected {[*BASE_INCLUDES, *ADDED_INCLUDES]}, found {includes}")
    out["min_version"] = MIN_VERSION_BEFORE
    out["includes"] = list(BASE_INCLUDES)
    return out


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
