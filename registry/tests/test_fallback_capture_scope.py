#!/usr/bin/env python3
"""FB-B1 (Review Current Configuration) - change scope and FB-T0 scope-chain registration.

SCOPE: test infrastructure. FB-B1 is the READ-ONLY review of the inverter's fallback-profile registers (four FC03 reads,
zero Modbus writes, zero NVS writes, zero inverter authority). It necessarily ADDS to many regions of the firmware YAML that
older suites pin byte-for-byte (intervals, globals, text sensors, scripts, includes, the on_boot lambda), edits three
operator texts, and adds one `frontend_assets` stanza to the deployment manifest. Older suites are NOT re-hashed: they are
anchored at their own chain entry (registry/tests/_scope_chain.py) and the chain entry `fbb1` reverts FB-B1's declared edits
exactly. This suite proves that entry, and that the revert is exact, and proves what FB-B1 edits in EXISTING code.

Modelled on section [S] of test_failback_shadow_core.py (FB-C1) and test_fallback_durable_model.py [15] (FB-B0).

CHAIN-ANCHORED (FB-T0): the firmware and the manifest this suite proves things about are the artifacts AS OF fbb1 -
`CHAIN.as_of_all("fbb1", live)`, an identity while fbb1 is the newest entry - and every chain-level proof runs over the chain that
ends at fbb1 (`CH1`). A later PR that appends an entry (and edits the firmware or the manifest) therefore does not turn this
suite red; the inserted line counts are derived from `_fbb1_scope.HUNKS`, so a legitimate re-pin of a hunk needs no edit here.

  [0] The scope module: thirteen hunks, each present exactly once at its anchor; exact revert; round trip; every hunk
      individually missing / duplicated / altered is refused; the module holds the blocks as the single source of truth
  [1] What FB-B1 edits in EXISTING code: the line diff against the base consists ONLY of the declared hunks, the only
      modified pre-existing lines are the three operator texts (printed and pinned from -> to), the three BLK-11 retention
      lines are each the LAST statement of their marker block and read `marker_load`, and no other pre-existing section,
      script, button, interval, switch, number, select, sensor, binary sensor, API action or substitution changed
  [2] The inserted blocks against the parsed firmware and the scope tables (names, ids, counts, placement, read-only text)
  [3] The manifest stanza and its exact reverter
  [4] Chain registration of `fbb1`: exact declarations, measured zero-write / zero-durable delta, checkpoints, banned files,
      added files, and the newest-first reverter ordering against fbb0 / fbc1
  [5] Negative controls: every mis-declaration and every undeclared edit is refused (nothing is absorbed by a prefix / family rule)
"""

from __future__ import annotations

import difflib
import hashlib
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _dump_sim as ds  # noqa: E402
import _fbb1_scope as scope  # noqa: E402
import _fbb_scope as fbbs  # noqa: E402
import _fbc_scope as fbcs  # noqa: E402
import _scope_chain as chain  # noqa: E402
import _tag_inventory as ti  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def _raises(fn, exc=AssertionError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    """Exact-count replace: raises if the anchor does not occur exactly `count` times (a mutant must hit what it aims at)."""
    found = text.count(old)
    if found != count:
        raise AssertionError(f"mutation anchor {old[:70]!r} found {found}x, expected {count}")
    return text.replace(old, new)


CH = chain.CHAIN                                                # the WHOLE chain: a later PR appends entries after fbb1
CH1 = chain.Chain(CH.upto("fbb1"))                              # the chain as of this PR (it ends at fbb1)
E = CH1.entry("fbb1")
LIVE = {p: chain.read_live(p) for p in chain.PINNED}            # every chain-pinned artifact, LF text, as it is on disk
# Chain-anchored (FB-T0): every pinned artifact AS OF fbb1 = the live text with every LATER entry reverted (an identity while
# fbb1 is the newest entry). The next PR that appends an entry and edits the firmware / manifest therefore cannot turn this
# suite red: it keeps proving exactly what FB-B1 added, against the artifacts as FB-B1 left them.
LIVE_FBB1 = CH.as_of_all("fbb1", LIVE)
FW_TEXT = LIVE_FBB1[chain.FIRMWARE]
MF_TEXT = LIVE_FBB1[chain.HA_MANIFEST]
FW_PATH = ROOT / chain.FIRMWARE

# The three operator texts FB-B1 rewords, typed out here independently of _fbb1_scope (the [1] checks pin all three against it).
TAIL_OLD = " - reboot to re-read"
TAIL_NEW = " - do NOT reboot: a reboot may make the record read as absent"
PREFIX = "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); "
TEXTS_OLD = {
    "dump": PREFIX + "an obligation cannot be ruled out; writes locked, export containment not armed" + TAIL_OLD,
    "free_power": PREFIX + "an obligation cannot be ruled out; inverter writes locked" + TAIL_OLD,
    "reg244": PREFIX + "inverter writes locked" + TAIL_OLD,
}
TEXTS_NEW = {k: v.replace(TAIL_OLD, TAIL_NEW) for k, v in TEXTS_OLD.items()}
RETENTION = {   # retention global -> the marker tag its block loads
    "free_power_marker_boot_load": "FREE_POWER_VALID_TAG",
    "dump_marker_boot_load": "DUMP_TO_GRID_VALID_TAG",
    "reg244_marker_boot_load": "REG244_VALID_TAG",
}
NEW_INCLUDE = "include/ecco_fallback_capture.h"
# Written out independently of _fbb1_scope / the chain entry ([2] and [4] check that all three agree).
FBB1_DELTAS = {"scripts": 3, "globals": 46, "text_sensors": 9, "buttons": 1, "intervals": 1, "modbus_reads": 4, "includes": 1}
FBB1_OP_PATHS = frozenset({"fallback_profile_capture_dispatch", "fallback_profile_review", "fallback_profile_review_button"})
FBB1_SCRIPTS = ("fallback_profile_review", "fallback_profile_capture_dispatch", "fallback_profile_invalidate_candidate")
FBB1_READS = [(230, 3), (241, 53), (230, 3), (241, 53)]
# Tokens no FB-B1 INSERTION may contain (a write side / authority / forbidden-feature symbol). The three reboot-text
# replacements are excluded from the scan (they legitimately say "do NOT reboot").
FORBIDDEN = re.compile(
    r"nvs_set|nvs_commit|nvs_erase|esp_restart|\bApp\.|global_preferences|make_preference|preference_for|commit_record|"
    r"load_record|write_one_|WriteTarget|commit_transition|upervision|self_partial|start_journal|modbus_client\.write|"
    r"write_multiple|write_single|uart\.write|queue_command|send_raw", re.IGNORECASE)


def banned_leaks() -> list[str]:
    """The FB-A scan (test_fallback_profile_schema.py [9]): every file under home-assistant/, frontend/, deployment/ that
    carries a banned token, exact repo-relative POSIX paths."""
    return sorted(p.relative_to(ROOT).as_posix() for d in ("home-assistant", "frontend", "deployment") if (ROOT / d).is_dir()
                  for p in (ROOT / d).rglob("*") if p.is_file() and chain.BANNED.search(p.read_text(encoding="utf-8", errors="ignore")))


def banned_files_agree(ch: "chain.Chain", leaks) -> bool:
    """The same equality [9] checks: the live leak set == the set the chain declares."""
    return set(leaks) == set(ch.declared_banned_files())


def main() -> int:
    # -----------------------------------------------------------------------
    print("[0] The scope module: thirteen hunks, each exactly once at its anchor; exact revert and round trip")
    # -----------------------------------------------------------------------
    hunks = scope.HUNKS
    try:
        BASE_TEXT = scope.pre_fbb1_firmware(FW_TEXT)
        ok_rev = True
    except AssertionError as ex:
        ok_rev, BASE_TEXT = False, FW_TEXT
        print("   ", ex)
    check("every FB-B1 hunk occurs exactly once in the firmware, directly at its anchor, and every base anchor is unique again "
          "once the hunk is removed", ok_rev)
    check("thirteen hunks: ten pure insertions (include, 3 BLK-11 retention, boot lambda, globals, text sensors, scripts, button, "
          "interval) and three in-place replacements (the three operator texts); unique names",
          len(hunks) == 13 and len(set(scope.HUNK_NAMES)) == 13 and sum(h.insertion for h in hunks) == 10
          and sorted(h.name for h in hunks if not h.insertion) == sorted(["reboot_text_dump", "reboot_text_free_power", "reboot_text_reg244"])
          and scope.HUNK_NAMES == ("include", "retention_fp", "retention_dump", "reboot_text_dump", "retention_r244",
                                   "reboot_text_free_power", "reboot_text_reg244", "boot_lambda", "globals", "text_sensors",
                                   "scripts", "button", "interval"), str(scope.HUNK_NAMES))
    check("reverting exactly FB-B1's hunks reproduces the FB-B1 base byte-for-byte: sha256 == _fbb1_scope.BASE_FW_SHA == the chain's "
          "fbb0 checkpoint (main @ 4649465), and equals the chain's as-of-fbb0 view of the live firmware",
          sha(BASE_TEXT) == scope.BASE_FW_SHA == CH1.checkpoint(chain.FIRMWARE, "fbb0") == "a61709c3fe42a8da60e16652891888988d96254be9f37e844ab665543d8c5881"
          and BASE_TEXT == CH1.as_of(chain.FIRMWARE, "fbb0", FW_TEXT), sha(BASE_TEXT))
    check("applying FB-B1 to that base reproduces the firmware exactly (round trip), and reverting that again gives the base",
          scope.add_fbb1_text(BASE_TEXT) == FW_TEXT and scope.pre_fbb1_firmware(scope.add_fbb1_text(BASE_TEXT)) == BASE_TEXT)
    check("every hunk: base text (left + old + right) occurs exactly once in the base; FB-B1 text (left + new + right) exactly once in "
          "the firmware and NOWHERE in the base; a replaced text is nowhere in the firmware any more",
          all(BASE_TEXT.count(h.before) == 1 and FW_TEXT.count(h.after) == 1 and BASE_TEXT.count(h.after) == 0
              and (h.insertion or FW_TEXT.count(h.before) == 0) for h in hunks),
          str([h.name for h in hunks if not (BASE_TEXT.count(h.before) == 1 and FW_TEXT.count(h.after) == 1
                                             and BASE_TEXT.count(h.after) == 0 and (h.insertion or FW_TEXT.count(h.before) == 0))]))
    check("a pure insertion adds a block and removes nothing (old == '', before == left + right, after == left + new + right)",
          all(h.old == "" and h.before == h.left + h.right and h.after == h.left + h.new + h.right and h.new.endswith("\n")
              for h in hunks if h.insertion))

    def _revert_one(text: str, h) -> str:
        return mutate(text, h.after, h.before)

    missing = [h.name for h in hunks if not _raises(lambda: scope.pre_fbb1_firmware(_revert_one(FW_TEXT, h)))]
    check("negative: ANY one hunk missing from the firmware makes the reverter raise (all 13 refused, none skipped)", not missing, str(missing))
    duplicated = [h.name for h in hunks if not _raises(lambda: scope.pre_fbb1_firmware(FW_TEXT + "\n" + h.after))]
    check("negative: ANY one hunk present twice makes the reverter raise (all 13 refused)", not duplicated, str(duplicated))

    def _alter(text: str, h) -> str:
        i = text.index(h.after) + len(h.left) + max(0, len(h.new) // 2)
        return text[:i] + "#" + text[i:]

    altered = [h.name for h in hunks if not _raises(lambda: scope.pre_fbb1_firmware(_alter(FW_TEXT, h)))]
    check("negative: ANY one hunk altered by a single character makes the reverter raise (all 13 refused)", not altered, str(altered))
    check("negative: add_fbb1_text refuses a firmware that already carries FB-B1, and one that already carries any single hunk",
          _raises(lambda: scope.add_fbb1_text(FW_TEXT))
          and all(_raises(lambda: scope.add_fbb1_text(mutate(BASE_TEXT, h.before, h.after))) for h in hunks))
    check("negative: the reverter refuses the firmware as of fbb0 (nothing to revert) and an unrelated text",
          _raises(lambda: scope.pre_fbb1_firmware(BASE_TEXT)) and _raises(lambda: scope.pre_fbb1_firmware("esphome:\n  name: x\n")))

    # -----------------------------------------------------------------------
    print("")
    print("[1] What FB-B1 edits in EXISTING code: only the declared hunks; the only modified pre-existing lines are three operator texts")
    # -----------------------------------------------------------------------
    def line_diff(base: str, live: str) -> tuple:
        """(non-equal opcodes, inserted block sizes, (old, new) replaced line pairs) of a line diff - independent of the hunk anchors."""
        bl, ll = base.split("\n"), live.split("\n")
        o = [x for x in difflib.SequenceMatcher(None, bl, ll, autojunk=False).get_opcodes() if x[0] != "equal"]
        return (o, sorted(j2 - j1 for tag, i1, i2, j1, j2 in o if tag == "insert"),
                [(bl[i1:i2], ll[j1:j2]) for tag, i1, i2, j1, j2 in o if tag == "replace"])

    def diff_is_declared(base: str, live: str) -> bool:
        """True iff the ONLY differences are the ten declared insertions (sizes) and the three declared operator-text replacements."""
        o, ins, rep = line_diff(base, live)
        return (all(tag in ("insert", "replace") for tag, *_r in o) and len(o) == 13
                and ins == sorted(h.new.count("\n") for h in hunks if h.insertion)
                and [(a[0], b[0]) for a, b in rep if len(a) == len(b) == 1] == [(a, b) for a, b in scope.REBOOT_TEXT_EDITS] and len(rep) == 3)

    ops, inserts, replaces = line_diff(BASE_TEXT, FW_TEXT)
    check("line diff (independent of the hunk anchors): no base line is deleted; exactly three base lines are replaced; every other "
          "difference is a pure insertion",
          all(tag in ("insert", "replace") for tag, *_r in ops) and len(replaces) == 3 and len(ops) == 13,
          str([(t, i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in ops]))
    # The sizes are DERIVED from _fbb1_scope.HUNKS. The line diff above is measured independently of the hunk anchors, so a
    # legitimate re-pin of a hunk (the scripts block grew by six lines with the review logging) needs no edit here. What stays
    # fixed: ten pure insertions and three one-line replacements; the include hunk is one line and each BLK-11 retention hunk is
    # three lines (comment, comment, assignment).
    hunk_sizes = sorted(h.new.count("\n") for h in hunks if h.insertion)
    by_name = {h.name: h.new.count("\n") for h in hunks if h.insertion}
    print(f"  (inserted block sizes, measured by the line diff: {inserts} = {sum(inserts)} lines; per hunk {by_name})")
    check("the measured inserted line counts are exactly the ten insertion hunks' sizes (derived from the scope module, not typed "
          "here): ten pure insertions + the three one-line operator-text replacements; the include hunk is 1 line and each of the "
          "three BLK-11 retention hunks is 3 lines",
          len(inserts) == 10 == len(hunk_sizes) and len(replaces) == 3 and inserts == hunk_sizes
          and sum(inserts) == sum(by_name.values()) and by_name["include"] == 1
          and [by_name[n] for n in ("retention_fp", "retention_dump", "retention_r244")] == [3, 3, 3], str(inserts))
    _victim = "Starting Free Power snapshot"
    check("self-test of that diff proof: it ACCEPTS the real firmware and REJECTS (a) a fourth modified pre-existing line, (b) a deleted "
          "pre-existing line, (c) one extra inserted line; and a changed character inside an inserted block "
          "is refused by the exact hunk revert",
          diff_is_declared(BASE_TEXT, FW_TEXT)
          and not diff_is_declared(BASE_TEXT, mutate(FW_TEXT, _victim, _victim + "X"))
          and not diff_is_declared(BASE_TEXT, mutate(FW_TEXT, "                ESP_LOGW(\"free_power\", \"Starting Free Power snapshot\");\n", ""))
          and not diff_is_declared(BASE_TEXT, mutate(FW_TEXT, "\nglobals:\n", "\nglobals:\n  # stray comment\n"))
          and _raises(lambda: scope.pre_fbb1_firmware(mutate(FW_TEXT, scope.GLOBALS_BLOCK, scope.GLOBALS_BLOCK.replace("'255'", "'254'", 1)))))
    check("the modified pre-existing lines are exactly the three operator texts, one line each, and nothing else",
          [(len(o), len(n)) for o, n in replaces] == [(1, 1)] * 3
          and [(o[0], n[0]) for o, n in replaces] == [(o, n) for o, n in scope.REBOOT_TEXT_EDITS], str(replaces)[:200])

    print("  --- the three operator texts, from -> to ---")
    for which, (old_line, new_line) in zip(("Dump", "Free Power", "Reg244"), scope.REBOOT_TEXT_EDITS):
        print(f"      {which}: ...{old_line.strip()[-62:]}")
        print(f"      {' ' * len(which)}  ->{new_line.strip()[-86:]}")
    n_dump, n_fp, n_r244 = (TEXTS_NEW[k] for k in ("dump", "free_power", "reg244"))
    check("pinned from -> to: the three unreadable-marker texts each lose ` - reboot to re-read` and gain ` - do NOT reboot: a reboot "
          "may make the record read as absent`; each old text is in the base exactly once and nowhere in the firmware, each new text "
          "in the firmware exactly once and nowhere in the base",
          all(BASE_TEXT.count(TEXTS_OLD[k]) == 1 and FW_TEXT.count(TEXTS_OLD[k]) == 0 and FW_TEXT.count(TEXTS_NEW[k]) == 1
              and BASE_TEXT.count(TEXTS_NEW[k]) == 0 for k in TEXTS_OLD)
          and scope.REBOOT_OLD_TAIL == TAIL_OLD and scope.REBOOT_NEW_TAIL == TAIL_NEW)
    check("the new texts sit where the old ones were: id(dump_status) / id(free_power_status) / id(reg244_last_result) publish_state",
          f'id(dump_status).publish_state("{n_dump}");' in FW_TEXT and f'id(free_power_status).publish_state("{n_fp}");' in FW_TEXT
          and re.search(r'id\(reg244_last_result\)\.publish_state\(\s*"' + re.escape(n_r244) + r'"\s*\);', FW_TEXT) is not None)
    check("each new text keeps the exact prefix `RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS "
          "at boot)` and the phrase `writes locked`, no longer advises a reboot, is <= 255 characters, and contains none of "
          "failed / deferred / press End Free Power / retry restore / snapshot retained",
          all(t.startswith(PREFIX[:-2]) and "writes locked" in t and "reboot to re-read" not in t and "do NOT reboot" in t
              and len(t) <= 255 and "UNKNOWN" in t
              and not re.search(r"failed|deferred|press End Free Power|retry restore|snapshot retained", t, re.IGNORECASE)
              for t in TEXTS_NEW.values()), str({k: len(v) for k, v in TEXTS_NEW.items()}))
    print(f"  (lengths of the new texts: { {k: len(v) for k, v in TEXTS_NEW.items()} } characters; HA state limit 255)")
    _published_unknown = [t for t in re.findall(r'publish_state\(\s*"([^"]*UNKNOWN[^"]*)"', FW_TEXT) if t.startswith("RECOVERY BLOCKED")]
    check("a published `RECOVERY BLOCKED` operator text contains UNKNOWN ONLY in the three unreadable-marker branches (the other branches "
          "are byte-identical, so they still do not contain it)",
          sorted(_published_unknown) == sorted(TEXTS_NEW.values()), str(_published_unknown))

    # BLK-11: each retention line is the last statement of its marker block and reads `marker_load`
    for var, tag in RETENTION.items():
        line = f"            id({var}) = marker_load;\n"
        i = FW_TEXT.find(line)
        opener = FW_TEXT.rfind("\n          {\n", 0, i)
        block = FW_TEXT[opener:i]
        check(f"BLK-11 {var}: assigned exactly once, `= marker_load;`, as the LAST statement of its marker block (the next line closes the "
              f"block at the same level), in the block that loads {tag} with load_record_status",
              FW_TEXT.count(f"id({var}) =") == 1 and i > 0 and FW_TEXT.startswith("          }\n", i + len(line))
              and "\n          }\n" not in block and "uint8_t marker_load = ecco_durable::load_record_status(" in block
              and f"ecco_durable::key_for(ecco_durable::{tag}), marker);" in block
              and FW_TEXT.count(f"ecco_durable::key_for(ecco_durable::{tag}), marker);") >= 1)
    check("the three retention lines are the only statements FB-B1 adds to on_boot lambda[0] besides the three texts: each hunk is "
          "exactly (comment, comment, assignment) and the retention globals are the three named in the scope module",
          scope.RETENTION_GLOBAL_IDS == tuple(RETENTION)
          and all(b.count("\n") == 3 and b.startswith("            // Review gate input") and b.rstrip().endswith("= marker_load;")
                  for b in scope.RETENTION_BLOCKS))

    # parsed sections
    BASE = ds.load_firmware_text(BASE_TEXT)
    FW = ds.load_firmware_text(FW_TEXT)
    changed = sorted(k for k in set(BASE) | set(FW) if k != "_text" and BASE.get(k) != FW.get(k))
    check("only the esphome block, globals, text_sensor, script, button and interval differ in the parsed firmware: no other section "
          "(substitutions, api, sensor, binary_sensor, switch, number, select, wifi, ota, logger, debug, ...) changed",
          changed == ["button", "esphome", "globals", "interval", "script", "text_sensor"], str(changed))
    check("every pre-existing item of globals / text_sensor / script / button is identical and in its original order (no base item removed, "
          "reordered or altered); the new ones are appended at the end",
          all(FW[sec][:len(BASE[sec])] == BASE[sec] and len(FW[sec]) > len(BASE[sec]) for sec in ("globals", "text_sensor", "script", "button")))
    new_iv = [i for i in FW["interval"] if i not in BASE["interval"]]
    iv_at = FW["interval"].index(new_iv[0]) if len(new_iv) == 1 else -1
    check("pre-existing intervals are identical and in order; the ONE new interval sits between the Free Power evidence-expiry interval and "
          "FB-C1's, and is NOT last (the Manual TOU staging tick stays the last interval)",
          len(new_iv) == 1 and FW["interval"][:iv_at] + FW["interval"][iv_at + 1:] == BASE["interval"] and 0 < iv_at < len(FW["interval"]) - 1
          and iv_at == len(BASE["interval"]) - 3
          and "free_power_recovery_invalidate_evidence" in yaml.dump(FW["interval"][iv_at - 1])
          and "failback_shadow_ready" in yaml.dump(FW["interval"][iv_at + 1])
          and FW["interval"][-1] == BASE["interval"][-1], f"at {iv_at} of {len(FW['interval'])}")
    esp_b, esp_l = BASE["esphome"], FW["esphome"]
    ob_b, ob_l = esp_b["on_boot"], esp_l["on_boot"]
    check("esphome: only the includes (one entry appended LAST) and on_boot differ; on_boot keeps its priority, items [1] and [2] are "
          "untouched, item [0] differs only in its lambda text, and ONE lambda item is appended",
          {k: v for k, v in esp_b.items() if k not in ("includes", "on_boot")} == {k: v for k, v in esp_l.items() if k not in ("includes", "on_boot")}
          and esp_l["includes"] == esp_b["includes"] + [NEW_INCLUDE] and esp_b["includes"][-1] == "include/ecco_fallback_durable.h"
          and {k: v for k, v in ob_b.items() if k != "then"} == {k: v for k, v in ob_l.items() if k != "then"}
          and len(ob_l["then"]) == len(ob_b["then"]) + 1 and ob_l["then"][1:len(ob_b["then"])] == ob_b["then"][1:]
          and {k: v for k, v in ob_l["then"][0].items() if k != "lambda"} == {k: v for k, v in ob_b["then"][0].items() if k != "lambda"}
          and list(ob_l["then"][-1]) == ["lambda"] and ob_l["then"][0]["lambda"] != ob_b["then"][0]["lambda"])

    def _undent(block: str) -> str:
        return "".join(ln[10:] if ln.strip() else ln for ln in block.splitlines(True))

    boot_back = ob_l["then"][0]["lambda"]
    for blk in scope.RETENTION_BLOCKS:
        boot_back = mutate(boot_back, _undent(blk), "")
    for old_line, new_line in scope.REBOOT_TEXT_EDITS:
        boot_back = mutate(boot_back, _undent(new_line + "\n"), _undent(old_line + "\n"))
    check("on_boot lambda[0] with exactly the three retention blocks removed and the three texts restored is byte-identical to the base "
          "lambda (nothing else in it moved)", boot_back == ob_b["then"][0]["lambda"])

    # raw scripts byte-identical
    def raw_scripts(text: str) -> dict:
        sec = text[text.index("\nscript:\n"):text.index("\nbutton:\n  - platform: restart\n")]
        parts = re.split(r"(?m)^(?=  - id: \w+$)", sec)
        return {re.match(r"  - id: (\w+)", p).group(1): p for p in parts[1:]}

    rs_b, rs_l = raw_scripts(BASE_TEXT), raw_scripts(FW_TEXT)
    last_pre = list(rs_b)[-1]
    banner = scope.SCRIPTS_BLOCK[:scope.SCRIPTS_BLOCK.index("  - id: fallback_profile_review\n")]
    check("every one of the pre-existing scripts is byte-identical as raw text (30 bodies); the only textual difference is that the last "
          "of them is followed by the new block's banner comment before the first new script",
          len(rs_b) == 30 and list(rs_l)[:30] == list(rs_b) and all(rs_l[k] == rs_b[k] for k in list(rs_b)[:-1])
          and rs_l[last_pre] == rs_b[last_pre] + "\n" + banner, f"{len(rs_b)} base scripts, last {last_pre}")
    check("no pre-existing script / button / interval / switch / number / select / sensor / binary_sensor / API action / substitution "
          "changed in the parsed firmware (compared against the base, item by item)",
          all(FW[sec][i] == BASE[sec][i] for sec in ("script", "button", "switch", "number", "select", "sensor", "binary_sensor", "text_sensor")
              for i in range(len(BASE.get(sec) or [])))
          and FW["api"] == BASE["api"] and FW["_substitutions"] == BASE["_substitutions"]
          and [i for i in FW["interval"] if i in BASE["interval"]] == BASE["interval"])

    # -----------------------------------------------------------------------
    print("")
    print("[2] The inserted blocks against the parsed firmware and the scope tables")
    # -----------------------------------------------------------------------
    new_g = FW["globals"][len(BASE["globals"]):]
    check("the 46 new globals are exactly _fbb1_scope.GLOBALS, in order, with their types and initial values, every one restore_value: no "
          "(the three BLK-11 retention globals first, then the review state)",
          [(g["id"], g["type"], (str(g["initial_value"]) if "initial_value" in g else None)) for g in new_g] == scope.GLOBALS
          and len(new_g) == 46 == len(scope.NEW_GLOBAL_IDS) == len(set(scope.NEW_GLOBAL_IDS))
          and all(g.get("restore_value") is False for g in new_g) and [g["id"] for g in new_g][:3] == list(RETENTION))
    check("no new global has a header-defined type (D1: esphome includes are emitted after all globals): scalars, std::string and "
          "std::array only; every id other than the retention three starts fallback_profile_ / fallback_witness_",
          all(re.fullmatch(r"bool|u?int(8|16|32|64)_t|std::string|std::array<uint(8|16)_t, \d+>", g["type"]) for g in new_g)
          and all(re.match(r"fallback_(profile|witness)_", g["id"]) for g in new_g[3:]))
    new_t = FW["text_sensor"][len(BASE["text_sensor"]):]
    check("the 9 new text sensors are exactly _fbb1_scope.TEXT_SENSORS (B1-B9, names and ids), all platform: template, update_interval: never, "
          "no lambda / filter / on_value; only the Summary is entity_category: diagnostic",
          [(t["name"], t["id"], t.get("entity_category") == "diagnostic") for t in new_t] == scope.TEXT_SENSORS and len(new_t) == 9
          and all(t["platform"] == "template" and t["update_interval"] == "never"
                  and set(t) <= {"platform", "name", "id", "update_interval", "entity_category"} for t in new_t)
          and [t["id"] for t in new_t if "entity_category" in t] == ["fallback_profile_summary_text"])
    new_s = FW["script"][len(BASE["script"]):]
    check("the 3 new scripts are exactly _fbb1_scope.SCRIPT_IDS (review gate, capture dispatch, RAM-only invalidate), all mode: single",
          tuple(s["id"] for s in new_s) == scope.SCRIPT_IDS == FBB1_SCRIPTS and all(s.get("mode") == "single" for s in new_s))
    new_b = FW["button"][len(BASE["button"]):]
    check("the 1 new button is the Review Current Configuration button; its only action is script.execute of the review gate",
          len(new_b) == 1 and new_b[0] == {"platform": "template", "name": scope.BUTTON_NAME, "id": scope.BUTTON_ID, "icon": scope.BUTTON_ICON,
                                           "on_press": [{"script.execute": {"id": "fallback_profile_review"}}]}
          and scope.BUTTON_NAME == "ECCO Fallback Profile: Review Current Configuration" and scope.BUTTON == scope.BUTTON_BLOCK)
    check("entity ids: B1-B9 and B11 map to the contract's Home Assistant ids (sensor.ecco_clock_dongle_ecco_fallback_profile_*; "
          "the button is button.ecco_clock_dongle_ecco_fallback_profile_review_current_configuration)",
          len(scope.ENTITY_NAMES) == 10 and scope.HA_ENTITY_IDS["fallback_profile_state_text"]
          == "sensor.ecco_clock_dongle_ecco_fallback_profile_state"
          and scope.HA_ENTITY_IDS["fallback_profile_last_result_text"] == "sensor.ecco_clock_dongle_ecco_fallback_profile_last_action_result"
          and scope.HA_ENTITY_IDS["fallback_profile_review_button"]
          == "button.ecco_clock_dongle_ecco_fallback_profile_review_current_configuration"
          and all(v.startswith(("sensor.ecco_clock_dongle_ecco_fallback_profile_", "button.ecco_clock_dongle_ecco_fallback_profile_"))
                  for v in scope.HA_ENTITY_IDS.values()))
    iv_text = yaml.dump(new_iv[0])
    check("the new interval is `interval: 10s` with ONE lambda action; it touches no Modbus, no NVS and no supervision symbol, and "
          "runs no script except fallback_profile_invalidate_candidate",
          new_iv[0]["interval"] == "10s" and [list(a) for a in new_iv[0]["then"]] == [["lambda"]]
          and "modbus_client" not in iv_text and "upervision" not in iv_text
          and not FORBIDDEN.search(new_iv[0]["then"][0]["lambda"])
          and set(re.findall(r"id\((\w+)\)\.execute\(\)", iv_text)) <= {"fallback_profile_invalidate_candidate"})
    boot_new = ob_l["then"][-1]["lambda"]
    check("the appended on_boot lambda is its own 4th item: no random_uint32, no static_assert, no supervision, and its LAST statement is "
          "`id(fallback_profile_boot_loaded) = true;`", len(ob_l["then"]) == 4 and "random_uint32" not in boot_new
          and "static_assert" not in boot_new and "upervision" not in boot_new
          and boot_new.rstrip().splitlines()[-1].strip() == "id(fallback_profile_boot_loaded) = true;")
    insertions = [h for h in hunks if h.insertion]
    reads = re.findall(r"modbus_client\.(\w+):\s*\n\s*modbus_id: \w+\s*\n\s*address: 0x01\s*\n\s*start_address: (\d+)\s*\n\s*count: (\d+)",
                       scope.SCRIPTS_BLOCK)
    check("FB-B1 adds exactly FOUR Modbus actions, all modbus_client.read_holding_registers, in the order 230/3, 241/53, 230/3, 241/53 "
          "(two distinct blocks read twice), all inside the capture dispatch script; no other hunk carries a modbus_client action",
          [(a, int(s_), int(c)) for a, s_, c in reads] == [("read_holding_registers", s_, c) for s_, c in FBB1_READS]
          and scope.SCRIPTS_BLOCK.count("modbus_client.") == 4
          and all("modbus_client" not in h.new for h in hunks if h.name != "scripts")
          and sorted(FW_TEXT.count(f"modbus_client.{a}") - BASE_TEXT.count(f"modbus_client.{a}")
                     for a in ("read_holding_registers", "write_multiple_registers")) == [0, 4])
    leaky = [h.name for h in insertions if FORBIDDEN.search(h.new)]
    check("no insertion hunk contains a write-side, durable-write, reboot, supervision, self-partial or start-journal symbol (nvs_set / "
          "commit_record / load_record / write_one_ / WriteTarget / modbus_client.write / App. / esp_restart / ...)", not leaky, str(leaky))
    check("self-test of that scan: each forbidden family fires on a synthetic line",
          all(FORBIDDEN.search(t) for t in ("nvs_set_blob(", "ecco_durable::commit_record(", "ecco_durable::load_record_status(",
                                           "write_one_<T>", "modbus_client.write_multiple_registers", "App.reboot();", "supervision_state",
                                           "SELF_PARTIAL", "start_journal")) and not FORBIDDEN.search("ecco_fbdurable::read_direct_t(nvs, key, p, d)"))
    banned_by_hunk = {h.name: len(chain.BANNED.findall(h.new)) - len(chain.BANNED.findall(h.old)) for h in hunks}
    check("banned-token accounting: FB-B1 adds exactly 9 occurrences of the FB-A reserved tokens to the firmware YAML - 1 in the include "
          "line, 5 in the appended boot lambda, 3 in the scripts; none in globals, text sensors, button, interval or the BLK-11 lines",
          sum(banned_by_hunk.values()) == 9 == scope.BANNED_FW_ADDED == len(chain.BANNED.findall(FW_TEXT)) - len(chain.BANNED.findall(BASE_TEXT))
          and {k: v for k, v in banned_by_hunk.items() if v} == {"include": 1, "boot_lambda": 5, "scripts": 3}
          and banned_by_hunk == scope.BANNED_FW_BY_HUNK, str(banned_by_hunk))
    check("the scope module restates the FB-A banned-token pattern identically to the chain (it cannot import the chain)",
          scope._BANNED.pattern == chain.BANNED.pattern)

    # -----------------------------------------------------------------------
    print("")
    print("[3] The deployment manifest stanza and its exact reverter")
    # -----------------------------------------------------------------------
    try:
        MF_BASE = scope.pre_fbb1_manifest(MF_TEXT)
        ok_m = True
    except AssertionError as ex:
        ok_m, MF_BASE = False, MF_TEXT
        print("   ", ex)
    left_m, right_m = scope.MANIFEST_ANCHORS
    check("the manifest stanza occurs exactly once, directly after the Energy Actions card's resource_url line and before the blank line "
          "and `firmware:`", ok_m and MF_TEXT.count(left_m + scope.MANIFEST_STANZA + right_m) == 1 and MF_BASE.count(left_m + right_m) == 1)
    check("reverting it reproduces the root manifest byte-for-byte: sha256 == BASE_MANIFEST_SHA == the chain's root manifest hash == the "
          "chain's fbb0 checkpoint for the manifest (no earlier entry edits it); the round trip is exact",
          sha(MF_BASE) == scope.BASE_MANIFEST_SHA == chain.ROOT_SHA[chain.HA_MANIFEST] == CH1.checkpoint(chain.HA_MANIFEST, "fbb0")
          == "d582beb6b3873109365c9d901f3c9dfe6c26033e7c11551814179c953412815f"
          and scope.add_fbb1_manifest(MF_BASE) == MF_TEXT and MF_BASE == CH1.as_of(chain.HA_MANIFEST, "fbb0", MF_TEXT))
    check("negative: the manifest reverter refuses a missing stanza, a duplicated one, an altered one, a stanza under a changed anchor, and "
          "the base manifest itself; add refuses a manifest that already has it",
          _raises(lambda: scope.pre_fbb1_manifest(MF_BASE)) and _raises(lambda: scope.pre_fbb1_manifest(MF_TEXT + left_m + scope.MANIFEST_STANZA + right_m))
          and _raises(lambda: scope.pre_fbb1_manifest(mutate(MF_TEXT, "method: ssh_file_copy\n    restart_required: false\n    resource_registration: manual\n"
                                                              "    resource_url: /local/ecco/ecco-fallback-recovery-card.js\n",
                                                              "method: ssh_file_copy\n    restart_required: true\n    resource_registration: manual\n"
                                                              "    resource_url: /local/ecco/ecco-fallback-recovery-card.js\n")))
          and _raises(lambda: scope.pre_fbb1_manifest(mutate(MF_TEXT, "\nfirmware:\n", "\n\nfirmware:\n")))
          and _raises(lambda: scope.pre_fbb1_manifest(mutate(MF_TEXT, left_m, left_m.replace("energy-actions-card", "energy-actions-card2"))))
          and _raises(lambda: scope.add_fbb1_manifest(MF_TEXT)))
    m_new, m_base = yaml.safe_load(MF_TEXT), yaml.safe_load(MF_BASE)
    assets_new, assets_base = m_new["frontend_assets"], m_base["frontend_assets"]
    stanza = assets_new[-1]
    check("parsed: exactly ONE frontend_assets entry is added (appended), every other manifest key and asset is identical; the entry is the "
          "Fallback / Recovery card, resource_registration: manual, restart_required: false, and its source file exists",
          assets_new[:-1] == assets_base and len(assets_new) == len(assets_base) + 1
          and {k: v for k, v in m_new.items() if k != "frontend_assets"} == {k: v for k, v in m_base.items() if k != "frontend_assets"}
          and stanza == {"source": "frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js",
                         "destination": "/config/www/ecco/ecco-fallback-recovery-card.js", "method": "ssh_file_copy",
                         "restart_required": False, "resource_registration": "manual",
                         "resource_url": "/local/ecco/ecco-fallback-recovery-card.js"} and (ROOT / stanza["source"]).is_file(), str(stanza))

    # -----------------------------------------------------------------------
    print("")
    print("[4] FB-T0 scope-chain registration (registry/tests/_scope_chain.py entry `fbb1`): exact, nothing by prefix")
    # -----------------------------------------------------------------------
    check("fbb1 is appended to the chain directly after fbb0 (merge order: ... dump_v2 -> fbc1 -> fbb0 -> fbb1); later PRs append after it",
          CH.ids()[:6] == ["fba", "mtou1", "dump_v2", "fbc1", "fbb0", "fbb1"] and E.pr == "FB-B1"
          and (E.commit == "unmerged" or re.fullmatch(r"[0-9a-f]{7,40}", E.commit) is not None),   # the lead records the merge commit later
          str(CH.ids()))
    check("fbb1's reverters are _fbb1_scope.pre_fbb1_firmware (firmware YAML) and pre_fbb1_manifest (ha-manifest) and nothing else (no header, "
          "registry or capabilities edit)",
          dict(E.reverts) == {chain.FIRMWARE: scope.pre_fbb1_firmware, chain.HA_MANIFEST: scope.pre_fbb1_manifest}
          and set(E.checkpoints) == {chain.FIRMWARE, chain.HA_MANIFEST})
    check("fbb1's checkpoints are the sha256 of the firmware / manifest AS OF fbb1 (the live LF text), and reverting fbb1 reproduces fbb0's "
          "firmware checkpoint (a61709c3...) and the root manifest hash",
          E.checkpoints[chain.FIRMWARE] == sha(FW_TEXT) == CH1.checkpoint(chain.FIRMWARE, "fbb1")
          and E.checkpoints[chain.HA_MANIFEST] == sha(MF_TEXT) == CH1.checkpoint(chain.HA_MANIFEST, "fbb1")
          and sha(scope.pre_fbb1_firmware(FW_TEXT)) == CH1.checkpoint(chain.FIRMWARE, "fbb0")
          and sha(scope.pre_fbb1_manifest(MF_TEXT)) == CH1.checkpoint(chain.HA_MANIFEST, "fbb0"))
    check("fbb1 declares EXACTLY +3 scripts, +46 globals, +9 text sensors, +1 button, +1 interval, +4 Modbus reads, +1 include - and no other "
          "metric (Modbus writes, commit/load/status sites, durable tag strings, sensors, switches, numbers, selects, API actions, "
          "substitutions all 0)",
          dict(E.deltas) == FBB1_DELTAS and dict(E.deltas) == {
              "scripts": len(scope.SCRIPT_IDS), "globals": len(scope.GLOBALS), "text_sensors": len(scope.TEXT_SENSORS), "buttons": 1,
              "intervals": 1, "modbus_reads": 4, "includes": len(scope.ADDED_INCLUDES)} and E.subst_added == {} and E.subst_changed == {}
          and tuple(E.subst_removed) == (), str(dict(E.deltas)))
    check("fbb1 declares exactly the three new op paths (capture dispatch with its four reads, the review gate and the review button), "
          "exactly the one new include (appended last), the 9 banned-token occurrences, the Dashboard view file as its ONE banned file, "
          "no FB-A-header includer and no durable tag",
          E.op_paths_changed == FBB1_OP_PATHS and E.includes_added == (NEW_INCLUDE,) == scope.ADDED_INCLUDES and E.banned_fw_added == 9
          and E.banned_files == frozenset({"home-assistant/dashboards/ecco_pro.yaml"}) and E.fbh_includers == frozenset()
          and E.tags_declared == frozenset() and E.tags_promoted == frozenset())
    _rows = [r for r in chain.integrity_report(CH1, LIVE_FBB1) if r[0].startswith("fbb1:")]
    check("the chain's own integrity report for fbb1 is all green (checkpoints, non-identity reverters, nothing else moved, declared "
          "deltas == measured, op paths, includes, substitutions) over the artifacts as of fbb1, and the whole (live) chain is green",
          len(_rows) == 8 and all(ok for _n, ok, _d in _rows) and all(ok for _n, ok, _d in chain.integrity_report(CH1, LIVE_FBB1))
          and all(ok for _n, ok, _d in chain.integrity_report(CH)),
          str([(n, d) for n, ok, d in _rows if not ok]))
    live_all = dict(LIVE_FBB1)         # the pinned artifacts as of fbb1 (the "live" text of the chain that ends at fbb1)
    M_PRE = chain.measure(CH1.as_of_all("fbb0", live_all))
    M_POST = chain.measure(CH1.as_of_all("fbb1", live_all))
    check("measured, not declared: Modbus WRITES 52 -> 52 (zero write delta), Modbus reads 60 -> 64 (+4), and the durable surface "
          "(commit_record / load_record / load_record_status 57 / 7 / 3, tag strings 13) is identical before and after - zero "
          "NVS write, zero durable delta",
          (M_PRE["modbus_writes"], M_POST["modbus_writes"], M_PRE["modbus_reads"], M_POST["modbus_reads"]) == (52, 52, 60, 64)
          and all(M_PRE[m] == M_POST[m] for m in ("commit_record", "load_record", "load_record_status", "durable_tag_strings"))
          and (M_POST["commit_record"], M_POST["load_record"], M_POST["load_record_status"], M_POST["durable_tag_strings"]) == (57, 7, 3, 13)
          and M_POST["banned_fw"] - M_PRE["banned_fw"] == 9, str(M_POST))
    H_PRE, H_POST = chain._headers_of(CH1.as_of_all("fbb0", live_all)), chain._headers_of(CH1.as_of_all("fbb1", live_all))
    ops_pre = chain.per_path_ops(CH1.as_of(chain.FIRMWARE, "fbb0", FW_TEXT), H_PRE)
    ops_post = chain.per_path_ops(FW_TEXT, H_POST)
    new_paths = {n: o for n, o in ops_post.items() if ops_pre.get(n) != o}
    check("measured: the ONLY analyzer paths that changed are the three new ones (every pre-existing path's ordered op list is identical), "
          "and the capture dispatch's op list is exactly the four reads",
          set(new_paths) == FBB1_OP_PATHS and all(n not in ops_pre for n in new_paths)
          and all(ops_pre[n] == ops_post[n] for n in ops_pre)
          and new_paths["fallback_profile_capture_dispatch"] == tuple(("read", s_, c) for s_, c in FBB1_READS)
          and new_paths["fallback_profile_review"] == () and new_paths["fallback_profile_review_button"] == (), str(new_paths))
    leaks = banned_leaks()
    check("fbb1's banned_files is EXACTLY the FB-A scan's result over home-assistant/ frontend/ deployment/ (only the dashboard YAML; the new "
          "frontend card, the manifest and every other file are free of the reserved tokens - nothing by prefix or family)",
          banned_files_agree(CH, leaks) and sorted(E.banned_files) == ["home-assistant/dashboards/ecco_pro.yaml"]
          and set(E.banned_files) <= set(leaks), str(leaks))
    check("the firmware as of fbb1 carries exactly the declared number of banned tokens (4 FB-B0 include lines + 14 FB-C1 + 9 FB-B1)",
          len(chain.BANNED.findall(FW_TEXT)) == CH1.declared_banned_fw() == 4 + 14 + 9, str(len(chain.BANNED.findall(FW_TEXT))))
    # the includer scan (FB-A [9]): no file other than the declared ones includes the FB-A header, so fbb1 declares no includer
    scan_dirs = ("firmware", "registry", "tools", "home-assistant", "frontend", "deployment", "health", "influxdb", ".github")
    suffixes = {".h", ".hpp", ".c", ".cpp", ".yaml", ".yml", ".py", ".ts", ".js", ".json", ".ps1", ".psm1", ".sh", ".jinja"}
    fb_a_tests = {"registry/tests/test_fallback_profile_schema.py", "registry/tests/test_fallback_profile_host_compile.py"}
    includers = sorted(p.relative_to(ROOT).as_posix() for d in scan_dirs if (ROOT / d).is_dir() for p in (ROOT / d).rglob("*")
                       if p.is_file() and p.suffix in suffixes and ".esphome" not in p.parts and "node_modules" not in p.parts
                       and p.relative_to(ROOT).as_posix() not in fb_a_tests
                       and re.search(r'#\s*include\s*[<"][^>"]*ecco_fallback_profile\.h|-\s*include/ecco_fallback_profile\.h',
                                     p.read_text(encoding="utf-8", errors="ignore")))
    check("no FB-B1 file includes the FB-A header: the includers are still exactly the chain's declared ones (the firmware YAML's own includes "
          "list and the FB-B0 model header), so fbb1 declares none (the capture header includes only the model header)",
          set(includers) == set(CH.declared_includers()) - fb_a_tests and E.fbh_includers == frozenset()
          and not any(f in includers for f in E.added_files), str(includers))
    inc_dir = ROOT / "firmware" / "include"
    check("the capture header declares NO durable tag and holds no durable-looking `ecco_<words>_v<N>` literal (tags_declared stays empty)",
          not [k for k in ti.all_declared_tags(inc_dir) if k.startswith("ecco_fallback_capture.h:")]
          and not ti.unaccounted_literals((inc_dir / "ecco_fallback_capture.h").read_text(encoding="utf-8"), set(ti.all_declared_tags(inc_dir).values())))
    # added files
    card_dir = ROOT / "frontend" / "ecco-fallback-recovery-card"
    on_disk_card = sorted(p.relative_to(ROOT).as_posix() for p in card_dir.rglob("*") if p.is_file() and "node_modules" not in p.parts
                          and "__pycache__" not in p.parts)
    declared_card = sorted(f for e_ in CH.entries for f in e_.added_files if f.startswith("frontend/ecco-fallback-recovery-card/"))
    added_all = frozenset().union(*(e_.added_files for e_ in CH.entries))      # a later PR may add files of its own
    named = {p.relative_to(ROOT).as_posix() for pat in ("registry/tests/_fbb1_*.py", "registry/tests/test_fallback_capture_*.py",
                                                        "registry/tests/test_fallback_profile_capture.py",
                                                        "registry/tests/test_fallback_recovery_dashboard.py",
                                                        "registry/fallback_capture.py", "firmware/include/ecco_fallback_capture.h")
             for p in ROOT.glob(pat)}
    check("added_files is the exact set of NEW repo files FB-B1 adds: every declared path exists, the frontend card directory on disk is "
          "exactly the declared frontend files, every FB-B1-named file on disk (_fbb1_*, test_fallback_capture_*, test_fallback_profile_capture, "
          "test_fallback_recovery_dashboard, the mirror, the header) is declared, and all are exact POSIX paths",
          E.added_files == scope.ADDED_FILES and all((ROOT / f).is_file() for f in E.added_files) and on_disk_card == declared_card
          and sorted(f for f in E.added_files if f.startswith("frontend/")) == sorted(scope.FRONTEND_CARD_FILES)
          and set(scope.FRONTEND_CARD_FILES) <= set(declared_card) and named <= set(added_all)
          and all("\\" not in f and not f.startswith("/") and ".." not in f.split("/") and not any(c in f for c in "*?[]{}") for f in E.added_files),
          str({"missing": sorted(f for f in E.added_files if not (ROOT / f).is_file()), "undeclared": sorted(named - set(E.added_files)),
               "card_disk_vs_declared": sorted(set(on_disk_card) ^ set(declared_card))}))
    check("added_files is disjoint from every other entry's added_files (FB-B0's 12 files, FB-C1's 3, FB-A's) and from banned_files; none of "
          "them is a chain-pinned artifact", all(not (E.added_files & other.added_files) for other in CH.entries if other.id != "fbb1")
          and not (E.added_files & E.banned_files) and not (E.added_files & set(chain.PINNED)))
    check("the three FB-B0 / FB-C1 scope modules this entry leans on are untouched in role: _fbb_scope.ADDED_FILES and _fbc_scope.ADDED_FILES "
          "are still declared by their own entries, and _fbb_scope.pre_fbb0_firmware is still the fbb0 reverter",
          CH.entry("fbb0").added_files == frozenset(fbbs.ADDED_FILES) and CH.entry("fbc1").added_files == fbcs.ADDED_FILES
          and CH.entry("fbb0").reverts[chain.FIRMWARE] is fbbs.pre_fbb0_firmware)

    # reverter ordering against fbb0 / fbc1 (the chain reverts newest first)
    fbb0_alone = lambda: fbbs.pre_fbb0_firmware(FW_TEXT)  # noqa: E731
    fbc1_after_fbb0 = fbcs.pre_fbc1_text(fbbs.pre_fbb0_firmware(scope.pre_fbb1_firmware(FW_TEXT)))
    check("ordering (newest first): fbb1 is undone BEFORE fbb0 and fbc1 - fbb0's reverter on the live text refuses (the capture include sits "
          "between its anchors), and fbb1 -> fbb0 -> fbc1 reproduces every checkpoint (fbb0 a61709c3..., fbc1 dd9bc598..., dump_v2)",
          _raises(fbb0_alone) and sha(fbbs.pre_fbb0_firmware(scope.pre_fbb1_firmware(FW_TEXT))) == CH.checkpoint(chain.FIRMWARE, "fbc1")
          == "dd9bc59890d6d514c8e60f6a6c6a48615192429f414df2c244c26b9d9950d6d3"
          and sha(fbc1_after_fbb0) == CH.checkpoint(chain.FIRMWARE, "dump_v2")
          and CH1.as_of(chain.FIRMWARE, "fbb0", FW_TEXT) == scope.pre_fbb1_firmware(FW_TEXT)
          and CH1.as_of(chain.FIRMWARE, "fbc1", FW_TEXT) == fbbs.pre_fbb0_firmware(scope.pre_fbb1_firmware(FW_TEXT)), sha(fbc1_after_fbb0))
    check("ordering: the interval hunk is anchored on FB-C1's own comment line, so fbc1's reverter must NOT run before fbb1's (the chain never "
          "does) - fbb1's reverter on the text with fbc1 already reverted refuses; the include hunk is anchored on fbb0's last include",
          _raises(lambda: scope.pre_fbb1_firmware(fbcs.pre_fbc1_text(FW_TEXT)))
          and scope.hunk("interval").right.startswith("  # Failback Shadow (FB-C1)")
          and scope.hunk("include").left == "    - " + fbbs.ADDED_INCLUDES[-1] + "\n")
    check("ordering: reverting fbb1 does not disturb fbb0's / fbc1's own edits - fbb0's include list is back to ending in ecco_fallback_durable.h "
          "and FB-C1's four blocks are all still present exactly once",
          all(scope.pre_fbb1_firmware(FW_TEXT).count(b) == 1 for _n, b, _w, _a in fbcs.EDITS)
          and scope.pre_fbb1_firmware(FW_TEXT).count(fbbs.FIRMWARE_TEXT_EDITS[1][1]) == 1)

    # -----------------------------------------------------------------------
    print("")
    print("[5] Negative controls: a mis-declared fbb1 entry and every undeclared edit are refused by the chain, never absorbed")
    # -----------------------------------------------------------------------
    def _with(**kw) -> "chain.Chain":
        d = {f: getattr(E, f) for f in E.__dataclass_fields__}
        d.update(kw)
        return chain.Chain(CH.upto("fbb0") + (chain.Entry(**d),))

    def _fails(ch, live, needle) -> bool:
        return any((not ok) and needle in n for n, ok, _d in chain.integrity_report(ch, live))

    def _any_fail(ch, live) -> bool:
        return any(not ok for _n, ok, _d in chain.integrity_report(ch, live))

    _live = dict(live_all)
    check("control: the unmodified entry over the live artifacts is green (so each failure below is caused by its own change)",
          not _any_fail(_with(), _live))
    check("negative: a WRONG delta (4 scripts) and a MISSING delta (no globals) are detected",
          _fails(_with(deltas={**E.deltas, "scripts": 4}), _live, "declared deltas") and _fails(_with(deltas={k: v for k, v in E.deltas.items() if k != "globals"}),
                                                                                              _live, "declared deltas"))
    check("negative: a wrong Modbus read count (5 and 0), a declared Modbus WRITE and a declared commit site the firmware does not add are detected "
          "(the zero-write / zero-durable delta is measured, not assumed)",
          _fails(_with(deltas={**E.deltas, "modbus_reads": 5}), _live, "declared deltas")
          and _fails(_with(deltas={k: v for k, v in E.deltas.items() if k != "modbus_reads"}), _live, "declared deltas")
          and _fails(_with(deltas={**E.deltas, "modbus_writes": 1}), _live, "declared deltas")
          and _fails(_with(deltas={**E.deltas, "commit_record": 1}), _live, "declared deltas")
          and _fails(_with(deltas={**E.deltas, "load_record_status": 1}), _live, "declared deltas"))
    check("negative: a wrong op path, a missing one and an extra one are detected",
          _fails(_with(op_paths_changed=frozenset({"fallback_profile_capture_dispatch", "fallback_profile_review", "fallback_profile_review_x"})),
                 _live, "op_paths_changed")
          and _fails(_with(op_paths_changed=frozenset({"fallback_profile_capture_dispatch", "fallback_profile_review"})), _live, "op_paths_changed")
          and _fails(_with(op_paths_changed=FBB1_OP_PATHS | {"free_power_start"}), _live, "op_paths_changed")
          and _fails(_with(op_paths_changed=frozenset()), _live, "op_paths_changed"))
    check("negative: an UNDECLARED include (includes_added empty), a wrong include, a wrong order / an extra declared include and a wrong "
          "includes delta are detected",
          _fails(_with(includes_added=()), _live, "esphome.includes")
          and _fails(_with(includes_added=("include/ecco_fallback_capture_x.h",)), _live, "esphome.includes")
          and _fails(_with(includes_added=("include/ecco_other.h", NEW_INCLUDE)), _live, "esphome.includes")
          and _fails(_with(deltas={**E.deltas, "includes": 2}), _live, "declared deltas"))
    check("negative: a declared substitution the firmware does not carry is detected; a prefix / glob substitution declaration is refused by "
          "Chain() itself", _fails(_with(subst_added={"ecco_fallback_capture_ms": "1"}), _live, "substitutions added")
          and _raises(lambda: _with(subst_added={"ecco_fallback_*": "1"}), chain.ChainError))
    check("negative: a wrong banned-token count (8 and 10) is detected",
          _fails(_with(banned_fw_added=8), _live, "declared deltas") and _fails(_with(banned_fw_added=10), _live, "declared deltas"))
    flip = lambda s: ("1" if s[0] != "1" else "2") + s[1:]  # noqa: E731
    check("negative: a WRONG firmware checkpoint and a WRONG manifest checkpoint are detected (no checkpoint is trusted by prefix)",
          _fails(_with(checkpoints={chain.FIRMWARE: flip(E.checkpoints[chain.FIRMWARE]), chain.HA_MANIFEST: E.checkpoints[chain.HA_MANIFEST]}),
                 _live, "recorded checkpoint")
          and _fails(_with(checkpoints={chain.FIRMWARE: E.checkpoints[chain.FIRMWARE], chain.HA_MANIFEST: flip(E.checkpoints[chain.HA_MANIFEST])}),
                     _live, "recorded checkpoint"))
    # An identity reverter is only meaningful against artifacts that do NOT carry FB-B1 (the as-of-fbb0 texts): there the entry's
    # reverters change nothing, and the chain must say so (a reverter that changes nothing proves nothing).
    _live_base = {**_live, chain.FIRMWARE: BASE_TEXT, chain.HA_MANIFEST: MF_BASE}
    _ident = {chain.FIRMWARE: lambda t: t, chain.HA_MANIFEST: lambda t: t}
    check("negative: reverters that are IDENTITIES (against artifacts without FB-B1) are detected by name - none is an identity; and the real "
          "entry's reverters are NOT identities on the live artifacts",
          _fails(_with(reverts=_ident, checkpoints={chain.FIRMWARE: sha(BASE_TEXT), chain.HA_MANIFEST: sha(MF_BASE)}), _live_base,
                 "none is an identity")
          and not _fails(_with(), _live, "none is an identity")
          and scope.pre_fbb1_firmware(FW_TEXT) != FW_TEXT and scope.pre_fbb1_manifest(MF_TEXT) != MF_TEXT)
    check("negative: a firmware reverter that is an identity over the LIVE text is detected (the older entries' reverters no longer apply "
          "behind it), and a reverter without a checkpoint is refused by Chain() itself",
          _any_fail(_with(reverts={chain.FIRMWARE: lambda t: t, chain.HA_MANIFEST: scope.pre_fbb1_manifest}), _live)
          and _raises(lambda: _with(checkpoints={chain.FIRMWARE: E.checkpoints[chain.FIRMWARE]}), chain.ChainError))
    check("negative: dropping the manifest reverter (an undeclared manifest edit) is detected - the live manifest no longer equals the "
          "recorded checkpoint and no longer reverts to the root hash",
          _fails(_with(reverts={chain.FIRMWARE: scope.pre_fbb1_firmware}, checkpoints={chain.FIRMWARE: E.checkpoints[chain.FIRMWARE]}),
                 _live, "live pinned artifacts")
          and _fails(_with(reverts={chain.FIRMWARE: scope.pre_fbb1_firmware}, checkpoints={chain.FIRMWARE: E.checkpoints[chain.FIRMWARE]}),
                     _live, "root: every pinned artifact"))
    check("negative: a glob / prefix banned-file or added-file declaration is refused by Chain() itself",
          _raises(lambda: _with(banned_files=frozenset({"home-assistant/*.yaml"})), chain.ChainError)
          and _raises(lambda: _with(added_files=frozenset({"frontend/ecco-fallback-recovery-card/"})), chain.ChainError)
          and _raises(lambda: _with(added_files=frozenset({"frontend\\card.js"})), chain.ChainError))
    # banned-file declaration: an undeclared extra banned file / a stale declared one are detected by the FB-A [9] equality
    check("negative: an UNDECLARED extra banned file (a new frontend file carrying a reserved token), a declared file that no longer carries "
          "one, and a missing declaration are each detected by the FB-A leak equality",
          not banned_files_agree(CH, leaks + ["frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js"])
          and not banned_files_agree(_with(banned_files=frozenset({"home-assistant/dashboards/ecco_pro.yaml",
                                                                    "home-assistant/dashboards/other.yaml"})), leaks)
          and not banned_files_agree(_with(banned_files=frozenset()), leaks) and banned_files_agree(CH, leaks))

    def _live_with(fw=None, mf=None) -> dict:
        return {**_live, chain.FIRMWARE: fw if fw is not None else FW_TEXT, chain.HA_MANIFEST: mf if mf is not None else MF_TEXT}

    # Undeclared edits to the LIVE text, entry intact. A phantom OUTSIDE FB-B1's own hunks leaves every reverter applicable, so it is
    # caught twice: the chain's counters / the analyzer MEASURE it (against the real firmware's numbers) and the checkpoint rows
    # refuse it (the revert no longer reproduces the recorded hashes).
    _rows_cache: dict = {}

    def _rows(fw: str) -> list:
        k = sha(fw)
        if k not in _rows_cache:
            _rows_cache[k] = chain.integrity_report(CH1, _live_with(fw))
        return _rows_cache[k]

    def _refused(fw: str) -> bool:
        rows = _rows(fw)
        return (any((not ok) and "recorded checkpoint" in n for n, ok, _d in rows)
                and any((not ok) and n.startswith("live pinned artifacts") for n, ok, _d in rows))

    def _refused_fast(fw: str) -> bool:
        """The same two facts as the checkpoint rows, without re-running the whole report (every reverter still applies - as_of does not
        raise - yet the revert no longer reproduces fbb0's checkpoint, and the live text is no longer fbb1's checkpoint)."""
        return (sha(CH1.as_of(chain.FIRMWARE, "fbb0", fw)) != CH1.checkpoint(chain.FIRMWARE, "fbb0")
                and sha(CH1.as_of(chain.FIRMWARE, "dump_v2", fw)) != CH1.checkpoint(chain.FIRMWARE, "dump_v2")
                and sha(fw) != E.checkpoints[chain.FIRMWARE])

    def _measured(fw: str) -> dict:
        return chain.measure(CH1.as_of_all("fbb1", _live_with(fw)))

    check("control for the phantom checks below: the UNMODIFIED live firmware is not refused (neither detector fires) and measures exactly "
          "the chain's own numbers", not _refused_fast(FW_TEXT) and _measured(FW_TEXT) == M_POST
          and not any((not ok) for _n, ok, _d in _rows(FW_TEXT)))

    inject_global = mutate(FW_TEXT, "\nglobals:\n", "\nglobals:\n  - id: fbb1_phantom_global\n    type: bool\n    restore_value: no\n"
                                                    "    initial_value: 'false'\n")
    check("negative: an UNDECLARED extra global is MEASURED (+1: 47 new against the declared 46) and refused by the checkpoint rows although every "
          "reverter still applies", _measured(inject_global)["globals"] == M_POST["globals"] + 1 and _refused(inject_global))
    script_anchor = "\n  - id: restore_reg244_snapshot\n"
    phantom_head = ("\n  - id: fbb1_phantom_script\n    mode: single\n    then:\n      - modbus_client.{}:\n          modbus_id: inverter_modbus\n"
                    "          address: 0x01\n          start_address: 230\n")
    inject_read = mutate(FW_TEXT, script_anchor, phantom_head.format("read_holding_registers") + "          count: 3\n" + script_anchor[1:])
    inject_write = mutate(FW_TEXT, script_anchor, phantom_head.format("write_multiple_registers")
                          + "          values: !lambda 'return std::vector<uint16_t>{1};'\n" + script_anchor[1:])
    m_read, m_write = _measured(inject_read), _measured(inject_write)
    check("negative: a PHANTOM Modbus READ site (a fifth FC03 in a new script) is measured (+1 read, +1 script, a new op path) and refused",
          m_read["modbus_reads"] == M_POST["modbus_reads"] + 1 and m_read["scripts"] == M_POST["scripts"] + 1
          and m_read["modbus_writes"] == M_POST["modbus_writes"]
          and "fbb1_phantom_script" in chain.per_path_ops(inject_read, H_POST) and _refused(inject_read))
    check("negative: a PHANTOM Modbus WRITE site is measured (+1 write: zero writes is a measured fact, not an assumption) and refused",
          m_write["modbus_writes"] == M_POST["modbus_writes"] + 1 and m_write["modbus_reads"] == M_POST["modbus_reads"]
          and _refused_fast(inject_write))
    inject_commit = mutate(FW_TEXT, script_anchor, "\n  # ecco_durable::commit_record(key, rec) would be a durable write site\n" + script_anchor[1:])
    inject_load = mutate(FW_TEXT, script_anchor, "\n  # ecco_durable::load_record_status(key, rec)\n" + script_anchor[1:])
    check("negative: a PHANTOM durable commit site and a phantom load_record_status site (even in a comment: the count is textual) are "
          "measured (+1 each) and refused", _measured(inject_commit)["commit_record"] == M_POST["commit_record"] + 1
          and _measured(inject_load)["load_record_status"] == M_POST["load_record_status"] + 1
          and _refused_fast(inject_commit) and _refused_fast(inject_load))
    inject_banned = mutate(FW_TEXT, script_anchor, "\n  # ecco_fallback_extra\n" + script_anchor[1:])
    check("negative: an undeclared extra banned token in the firmware (a stray ecco_fallback reference) is measured (+1) and refused",
          _measured(inject_banned)["banned_fw"] == M_POST["banned_fw"] + 1 and _refused_fast(inject_banned))
    inject_sub = mutate(FW_TEXT, '  ecco_supervision_stable_min_span_ms: "55000"\n',
                        '  ecco_fbb1_extra_ms: "5"\n  ecco_supervision_stable_min_span_ms: "55000"\n')
    check("negative: an undeclared substitution is measured (+1: FB-B1 adds none) and refused",
          _measured(inject_sub)["substitutions"] == M_POST["substitutions"] + 1 and _refused_fast(inject_sub))
    inject_inc = mutate(FW_TEXT, "    - include/ecco_durable_snapshot.h\n", "    - include/ecco_extra.h\n    - include/ecco_durable_snapshot.h\n")
    check("negative: an UNDECLARED extra include is measured (+1) and refused (the declared include is exactly the one capture header)",
          _measured(inject_inc)["includes"] == M_POST["includes"] + 1 and _refused_fast(inject_inc))
    check("negative: an undeclared edit INSIDE the FB-B1 interval, the appended boot lambda, the scripts, the globals, the text sensors, the "
          "button and the include list each make the exact reverter refuse (so the chain's exact-match row fails, never a skipped proof)",
          all(_fails(CH1, _live_with(mutated), "exact-match reverters apply") for mutated in (
              mutate(FW_TEXT, scope.INTERVAL_BLOCK, scope.INTERVAL_BLOCK.replace("  - interval: 10s\n", "  - interval: 11s\n")),
              mutate(FW_TEXT, scope.BOOT_BLOCK, scope.BOOT_BLOCK.replace("id(fallback_profile_boot_loaded) = true;", "id(fallback_profile_boot_loaded) = false;")),
              mutate(FW_TEXT, scope.SCRIPTS_BLOCK, scope.SCRIPTS_BLOCK.replace("  - id: fallback_profile_invalidate_candidate\n    mode: single\n",
                                                                               "  - id: fallback_profile_invalidate_candidate\n    mode: restart\n")),
              mutate(FW_TEXT, scope.GLOBALS_BLOCK, scope.GLOBALS_BLOCK.replace("'255'", "'254'", 1)),
              mutate(FW_TEXT, scope.TEXT_SENSORS_BLOCK, scope.TEXT_SENSORS_BLOCK.replace("update_interval: never", "update_interval: 60s", 1)),
              mutate(FW_TEXT, scope.BUTTON_BLOCK, scope.BUTTON_BLOCK.replace("mdi:file-search-outline", "mdi:play")),
              mutate(FW_TEXT, "    - include/ecco_fallback_capture.h\n", "    - include/ecco_fallback_capture.h\n    - include/ecco_extra.h\n"))))
    check("negative: a changed retention line (a wrong global assigned) and a changed operator text each make the exact reverter refuse",
          _fails(CH1, _live_with(mutate(FW_TEXT, "id(dump_marker_boot_load) = marker_load;", "id(dump_marker_boot_load) = 1;")), "exact-match reverters apply")
          and _fails(CH1, _live_with(mutate(FW_TEXT, TAIL_NEW + '");', TAIL_NEW + ' (v2)");', count=FW_TEXT.count(TAIL_NEW + '");'))),
                     "exact-match reverters apply"))
    check("negative: ANY undeclared edit to PRE-EXISTING code - inside on_boot lambda[0] or inside a script - leaves the reverter applicable "
          "but breaks the checkpoint: the revert no longer reproduces fbb0's firmware byte-for-byte",
          _fails(CH1, _live_with(mutate(FW_TEXT, '                  ESP_LOGE("free_power", "RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data '
                                                'record is unreadable; inverter writes locked");\n',
                                       '                  ESP_LOGE("free_power", "RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data '
                                       'record is unreadable; inverter writes locked");\n                  id(free_power_status).publish_state("x");\n')),
                 "recorded checkpoint")
          and _fails(CH1, _live_with(mutate(FW_TEXT, "Starting Free Power snapshot", "Starting Free Power snapshotX")), "recorded checkpoint"))
    check("negative: a manifest edit outside the stanza, and an extra / altered line inside it, are detected (checkpoint / exact reverter)",
          _fails(CH1, _live_with(mf=mutate(MF_TEXT, "firmware:\n", "firmware:\n  # x\n")), "recorded checkpoint")
          and _fails(CH1, _live_with(mf=mutate(MF_TEXT, "    method: ssh_file_copy\n    restart_required: false\n    resource_registration: manual\n"
                                                      "    resource_url: /local/ecco/ecco-fallback-recovery-card.js\n",
                                              "    method: ssh_file_copy\n    restart_required: false\n    resource_registration: manual\n"
                                              "    resource_url: /local/ecco/ecco-fallback-recovery-card.js\n    extra: 1\n")),
                     "exact-match reverters apply"))
    check("negative: any one FB-B1 hunk missing from the live firmware (all thirteen, one at a time) is a FAILED chain row, never a skipped proof",
          all(_fails(CH1, _live_with(_revert_one(FW_TEXT, h)), "exact-match reverters apply") for h in hunks))

    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    print("(Chain-scope proofs only: they pin what FB-B1 adds and edits, and that each edit is exactly reversible. Behaviour is")
    print(" proven by test_fallback_profile_capture.py; the native ESPHome compile is not an offline proof.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
