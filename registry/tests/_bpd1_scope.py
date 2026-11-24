"""bpd1 (the start bypass detector: DETECT AND ALERT ONLY, option O2 of the R9 / Stage 3 integration plan; offline, nothing installed). ADDED: the detector package and its
suite. CHAIN-PINNED edit: the deployment manifest (one stanza with its comment block). ZERO firmware, registry data, Intelligence, ecco_core or VERSION.yaml byte; ZERO Modbus
operation; the package calls only persistent_notification.create and the setters of its own helpers (input_text, input_number, input_datetime), never a dongle, inverter,
TOU or ECCO control service.

Same technique as the earlier post-export scope modules: the verbatim manifest edit is held HERE as an exact (before, after) pair, round-trip-checked, and the reverter raises
unless the edit is present exactly once. The post-export chain entry `bpd1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries it; its
fingerprint is sealed with _pex.sealed and must be sealed again if another entry merges first.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'bpd1'

ADDED_FILES = frozenset({
    'home-assistant/packages/ecco_start_bypass_detector.yaml',
    'home-assistant/tests/test_ecco_start_bypass_detector.py',
    'registry/tests/_bpd1_scope.py',
})

import hashlib


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"{ID} scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"{ID} scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"{ID} scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (chain-pinned edit) deployment/ha-manifest.yaml -------------------------------------------------------------
MANIFEST_REL = 'deployment/ha-manifest.yaml'
MANIFEST_EDITS = (
    (_blk(r"""


dashboard:
"""),
     _blk(r"""


  # Start bypass detector - bpd1 (detect and alert only; NOT installed, NOT live-proven). Notices a Dump to Grid or Charge Battery session that turned active
  # without ECCO's own record of the start (the scheduled run's STARTED OK, or the guarded start), always records an incident in its own helpers and raises a
  # persistent notification (Dump to Grid on every such start; Charge Battery only when an export hold is active or a plan reading is unreadable). It writes
  # nothing but those helpers and the notification (no dongle, inverter, TOU or ECCO control), PREVENTS NOTHING and is blind while
  # Home Assistant is down. It reads the plan sensors, the two schedule packages' result texts and the guarded start script: install it in the SAME deployment as,
  # or after, ecco_plan_helpers.yaml, ecco_dump_to_grid_guarded_start.yaml and the two schedule packages (the ONE full Home Assistant restart covers it; installed
  # alone later it needs no restart: reload the four helper domains and automations, never "reload all").
  - source: home-assistant/packages/ecco_start_bypass_detector.yaml
    destination: /config/packages/ecco_start_bypass_detector.yaml
    method: ssh_file_copy
    restart_required: true

dashboard:
""")),
)


def pre_bpd1_manifest(text: str) -> str:
    """deployment/ha-manifest.yaml with exactly bpd1's edit undone (a reverter of chain entry bpd1, PEX): its text as of the entry before."""
    return _revert(text, MANIFEST_EDITS, MANIFEST_REL)


pre_bpd1_manifest.edits = MANIFEST_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_bpd1_manifest(text: str) -> str:
    """Applies bpd1's edit to deployment/ha-manifest.yaml as of the entry before (the round trip)."""
    return _apply(text, MANIFEST_EDITS, MANIFEST_REL)


# The chain-pinned file this entry edits, with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_bpd1_manifest,
}


# ---- (PEX frozen edit) registry/tests/test_failback_shadow_evaluator.py: Z11 (vii) gains ONE declared READ-ONLY reader of the two schedule result helpers
# (the start bypass detector: it reads a helper inside Jinja states() reads only; reader_problems() proves it, with negative controls and a positive control).
SHADOW_EVALUATOR_TEST_REL = "registry/tests/test_failback_shadow_evaluator.py"
SHADOW_EVALUATOR_TEST_EDITS = (
    (_blk(r"""
#   (vii)  the only Home Assistant files that name the two helpers are the two schedule packages (their only writers) and the
#          dashboards, and the schedule packages name no shadow entity or decoder - so no shipped automation can route a shadow
#          string into the helpers;
"""),
     _blk(r"""
#   (vii)  the only Home Assistant files that name the two helpers are the two schedule packages (their only writers) and the
#          dashboards, and the schedule packages name no shadow entity or decoder - so no shipped automation can route a shadow
#          string into the helpers; the one other file allowed to name them is a DECLARED READ-ONLY READER (bpd1: the start bypass
#          detector reads a helper's state inside Jinja templates to see whether ECCO's own run recorded a start): reader_problems()
#          requires every occurrence of a helper id to be a states('<id>') / states.<id> read, no helper name to be partial or
#          constructed, and no shadow entity or decoder in the file, so a reader cannot write a helper or route a shadow string into it;
""")),
    (_blk(r"""
SCHEDULE_PACKAGES = ("home-assistant/packages/ecco_free_power_schedule.yaml", "home-assistant/packages/ecco_dump_to_grid_schedule.yaml")
"""),
     _blk(r"""
SCHEDULE_PACKAGES = ("home-assistant/packages/ecco_free_power_schedule.yaml", "home-assistant/packages/ecco_dump_to_grid_schedule.yaml")
# DECLARED READ-ONLY READERS of the two result helpers (any other file that names a helper and is not a schedule package or a dashboard is an
# undeclared writer / reader). bpd1: the start bypass detector. Declare a reader here only with reader_problems() clean and its own suite.
SCHEDULE_RESULT_READERS = ("home-assistant/packages/ecco_start_bypass_detector.yaml",)
# a minimal reader that only READS the helpers (the positive control and the base of the reader negative controls)
READER_CLEAN = ("template:\n  - sensor:\n      - name: probe\n        state: \"{{ states('" + SCHEDULE_RESULT_HELPERS[0] + "') }}\"\n"
                "      - name: probe_two\n        state: \"{% set o = states." + SCHEDULE_RESULT_HELPERS[1] + " %}{{ o.state }}\"\n")
""")),
    (_blk(r"""
def z11_card_scope(card: dict[str, str], ha: dict[str, str]) -> list[str]:
    bad = []
"""),
     _blk(r"""
def reader_problems(rel: str, text: str) -> list[str]:
    # A declared READ-ONLY reader of the schedule result helpers (bpd1). Every occurrence of a helper id must be a Jinja state read:
    # states('<id>') or states.<id>, never an entity_id, target, trigger or a constructed name, so the file cannot write a helper;
    # it must name no Failback Shadow entity or decoder; and every 'schedule_last_result' in the file must belong to a full helper id
    # (a partial or concatenated name could build a target the textual rule cannot see).
    bad = []
    n = 0
    for hid in SCHEDULE_RESULT_HELPERS:
        for m in re.finditer(re.escape(hid) + r"(?![A-Za-z0-9_])", text):
            n += 1
            if not re.search(r"states(?:\(\s*['\"]|\.)$", text[max(0, m.start() - 12):m.start()]):
                bad.append(f"{rel}: a schedule result helper is named outside a states('...') / states.<id> read: "
                           f"{text[max(0, m.start() - 30):m.end() + 12]!r}")
    if n == 0:
        bad.append(f"{rel}: a declared reader names no schedule result helper (declare a reader only if it reads one)")
    if text.count("schedule_last_result") != n:
        bad.append(f"{rel}: 'schedule_last_result' occurs {text.count('schedule_last_result')}x but only {n} full helper ids: a partial or constructed name")
    low = text.lower()
    hit = [t for t in SHADOW_TOKENS if t in low]
    if hit:
        bad.append(f"{rel} (a declared reader of the schedule result helpers) names a shadow entity / decoder {hit}")
    return bad


def z11_card_scope(card: dict[str, str], ha: dict[str, str]) -> list[str]:
    bad = []
""")),
    (_blk(r"""
        elif not rel.startswith("home-assistant/dashboards/"):
            bad.append(f"(vii) {rel} names a schedule result helper: an undeclared writer / reader")
"""),
     _blk(r"""
        elif rel in SCHEDULE_RESULT_READERS:
            bad.extend("(vii) " + p for p in reader_problems(rel, text))
        elif not rel.startswith("home-assistant/dashboards/"):
            bad.append(f"(vii) {rel} names a schedule result helper: an undeclared writer / reader")
""")),
    (_blk(r"""
          "and every committed dashboard) is one of the two schedule result helpers; their only writers are the two schedule packages; "
"""),
     _blk(r"""
          "and every committed dashboard) is one of the two schedule result helpers; their only writers are the two schedule packages "
          "(the one other file naming them is a declared read-only reader: states() reads only, no shadow token); "
""")),
    (_blk(r"""
    if not all(p in ha for p in SCHEDULE_PACKAGES):
        bad.append("(vii) a schedule package is missing from the scan")
    return bad
"""),
     _blk(r"""
    if not all(p in ha for p in SCHEDULE_PACKAGES):
        bad.append("(vii) a schedule package is missing from the scan")
    for rdr in SCHEDULE_RESULT_READERS:
        if rdr in ha and not any(hid in ha[rdr] for hid in SCHEDULE_RESULT_HELPERS):
            bad.append(f"(vii) {rdr} is declared a reader of the schedule result helpers but names none: remove the stale declaration")
    return bad
""")),
    (_blk(r"""
                                                              "        target:\n          entity_id: " + SCHEDULE_RESULT_HELPERS[0] + "\n"}))
    return out
"""),
     _blk(r"""
                                                              "        target:\n          entity_id: " + SCHEDULE_RESULT_HELPERS[0] + "\n"}))
    rdr = SCHEDULE_RESULT_READERS[0]
    run("an undeclared package only READS a schedule result helper (not a declared reader)",
        h=dict(ha, **{"home-assistant/packages/zz_probe_reader.yaml": READER_CLEAN}))
    run("a declared reader writes a schedule result helper (a service target)",
        h=dict(ha, **{rdr: READER_CLEAN + "\nscript:\n  zz:\n    sequence:\n      - action: input_text.set_value\n        target:\n          entity_id: " + SCHEDULE_RESULT_HELPERS[0] + "\n"}))
    run("a declared reader triggers on a schedule result helper as an entity_id",
        h=dict(ha, **{rdr: READER_CLEAN + "\nautomation:\n  - triggers:\n      - trigger: state\n        entity_id: " + SCHEDULE_RESULT_HELPERS[1] + "\n"}))
    run("a declared reader builds a helper name by concatenation",
        h=dict(ha, **{rdr: READER_CLEAN + "\n# x: \"{{ 'input_text.ecco_' ~ kind ~ '_schedule_last_result' }}\"\n"}))
    run("a declared reader names the HA shadow decoder",
        h=dict(ha, **{rdr: READER_CLEAN + "\n# x: \"{{ states('sensor.ecco_shadow_check') }}\"\n"}))
    run("a declared reader names no schedule result helper at all",
        h=dict(ha, **{rdr: "template:\n  - sensor:\n      - name: probe\n        state: \"{{ 1 }}\"\n"}))
    return out
""")),
    (_blk(r"""
    for what, found in z11_negative_controls():
        check(f"Z11 negative control caught: {what}", bool(found), "NOT DETECTED")
"""),
     _blk(r"""
    for what, found in z11_negative_controls():
        check(f"Z11 negative control caught: {what}", bool(found), "NOT DETECTED")
    check("Z11 positive control: a declared reader that only reads the helpers (states() forms) is accepted",
          not z11_card_scope(card_sources(), dict(ha_texts(), **{SCHEDULE_RESULT_READERS[0]: READER_CLEAN})))
""")),
)



def pre_bpd1_shadow_evaluator_test(text: str) -> str:
    """registry/tests/test_failback_shadow_evaluator.py with bpd1's edit undone (a frozen reverter of chain entry bpd1, PEX): its text as of the entry before."""
    return _revert(text, SHADOW_EVALUATOR_TEST_EDITS, SHADOW_EVALUATOR_TEST_REL)


pre_bpd1_shadow_evaluator_test.edits = SHADOW_EVALUATOR_TEST_EDITS   # the PEX contract: exact (before, after) pairs


def add_bpd1_shadow_evaluator_test(text: str) -> str:
    """Applies bpd1's edit to registry/tests/test_failback_shadow_evaluator.py as of the entry before (the round trip)."""
    return _apply(text, SHADOW_EVALUATOR_TEST_EDITS, SHADOW_EVALUATOR_TEST_REL)


# Every frozen file bpd1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    SHADOW_EVALUATOR_TEST_REL: pre_bpd1_shadow_evaluator_test,
}
