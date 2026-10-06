#!/usr/bin/env python3
"""FB-T0: the cumulative change-scope chain (registry/tests/_scope_chain.py).

Test-only. No firmware, no Modbus, no hardware, no Home Assistant, no I/O beyond
reading repo files and a temporary directory for analyzer runs.

  [1] STRUCTURE: the chain is in merge order (fba, mtou1, dump_v2), fba declares
      no edits, every reverter has a recorded checkpoint, the root hashes are
      main @ 004040b's.
  [2] EXACT RECONSTRUCTION: for root and every entry, every pinned artifact
      (firmware YAML, durable header, evidence header, inverter_capabilities,
      transaction_state_machine, ha-manifest) reverted through the chain
      reproduces the recorded sha256 byte-for-byte (`git show <commit>:<path>`);
      declared deltas equal the measured differences; live == root + sum of
      declared deltas. Nothing here is a re-hash of the current tree: the
      hashes are the merged commits' contents, and the live tree must reach
      them through exact-match reverters.
  [3] THE OLDER SUITES' OWN REVERTERS agree with the chain (SG-06 still
      reproduces 049c37e's on_boot / header through it).
  [4] FUTURE PRs ARE REPRESENTABLE: three SYNTHETIC entries shaped like FB-C1
      (RAM-only globals / interval / text sensor / substitution), FB-B0 (an
      esphome include) and FB-B1 (a new script with four reads) are appended
      in memory to a copy of the chain, and the whole integrity report - plus
      the as-of views the older suites use - must hold. Nothing synthetic is
      registered in the real chain.
  [5] MUTATION: the chain rejects a misdeclared delta, an undeclared edit, a
      wrong checkpoint, a reverter whose edit is absent or duplicated, an
      identity reverter, an undeclared op path and an undeclared include.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import _scope_chain as sc  # noqa: E402
import _sg06_scope as sg06  # noqa: E402

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


FW = sc.FIRMWARE
LIVE = {p: sc.read_live(p) for p in sc.PINNED}
C = sc.CHAIN
# This suite must itself survive later PRs appending chain entries (it is never edited again): every "today" assertion is
# pinned as of the newest entry THIS suite knows, "dump_v2" (main @ ca7474e), via the chain; the integrity report in [2]
# covers every entry - present and future - against the live tree.
KNOWN = ["fba", "mtou1", "dump_v2"]
LIVE_DV2 = {p: C.as_of(p, "dump_v2", LIVE[p]) for p in sc.PINNED}
C_DV2 = sc.Chain(C.upto("dump_v2"))        # the chain as it was when FB-T0 merged

# ===========================================================================
print("[1] structure")
# ===========================================================================
check("chain starts in merge order on main: fba (#54) -> mtou1 (#53) -> dump_v2 (#52) (later PRs append after these)",
      C.ids()[:3] == KNOWN and [e.pr for e in C.entries][:3] == ["#54", "#53", "#52"]
      and [e.commit for e in C.entries][:3] == ["97450aa", "37f9958", "ca7474e"])
check("root is main @ 004040b and its hashes cover all six pinned artifacts",
      sc.ROOT_COMMIT.startswith("004040b") and set(sc.ROOT_SHA) == set(sc.PINNED) and len(sc.PINNED) == 6)
check("FB-A declares NO edit to any pinned artifact (no reverters, no checkpoints, zero deltas) - it is behaviour-free",
      C.entry("fba").reverts == {} and C.entry("fba").checkpoints == {} and C.entry("fba").deltas == {}
      and C.entry("fba").op_paths_changed == frozenset() and C.entry("fba").includes_added == () and C.entry("fba").banned_fw_added == 0)
check("every reverter has a checkpoint and vice versa (Chain() refuses otherwise)",
      all(set(e.reverts) == set(e.checkpoints) for e in C.entries))
check("Manual TOU Phase 1 and Dump V2 use their own exact-match reverter modules (kept, called - not replaced)",
      C.entry("mtou1").reverts[FW].__module__ == "_mtou1_scope" and C.entry("dump_v2").reverts[FW].__module__ == "_dump_v2_scope"
      and C.entry("dump_v2").reverts[sc.DURABLE_HEADER].__module__ == "_dump_v2_scope")
check("unknown entry ids are rejected", _raises(lambda: C.entry("nope"), sc.ChainError))
check("a reverter without a checkpoint is rejected",
      _raises(lambda: sc.Chain((sc.Entry(id="x", pr="#0", commit="0", reverts={FW: lambda t: t}),)), sc.ChainError))
check("an unknown delta metric is rejected",
      _raises(lambda: sc.Chain((sc.Entry(id="x", pr="#0", commit="0", deltas={"widgets": 1}),)), sc.ChainError))
check("a duplicate or 'root' entry id is rejected",
      _raises(lambda: sc.Chain((sc.Entry(id="root", pr="#0", commit="0"),)), sc.ChainError)
      and _raises(lambda: sc.Chain((sc.Entry(id="a", pr="#0", commit="0"), sc.Entry(id="a", pr="#1", commit="1"))), sc.ChainError))

# ===========================================================================
print("")
print("[2] exact reconstruction of every historical state, and live == root + declared deltas")
# ===========================================================================
for name, ok, detail in sc.integrity_report(C, LIVE):
    check(name, ok, detail)
_git_known = {
    "root": {FW: "934ba7ddd6806592", sc.DURABLE_HEADER: "36c764bce649755c"},   # git show 004040b:<path>
    "fba": {FW: "934ba7ddd6806592", sc.DURABLE_HEADER: "36c764bce649755c"},    # git show 97450aa:<path>
    "mtou1": {FW: "943856c4ca46f652", sc.DURABLE_HEADER: "36c764bce649755c"},  # git show 37f9958:<path>
    "dump_v2": {FW: "9d09152744250623", sc.DURABLE_HEADER: "d57cd3b5b951b97e"},  # git show ca7474e:<path>
}
check("recorded checkpoints match the hashes of each merge commit's files as read from git history (16-hex prefixes)",
      all(sc.sha(C.as_of(p, eid, LIVE[p])).startswith(pre) for eid, d in _git_known.items() for p, pre in d.items()))
check("the two reverts commute on the firmware as of dump_v2 (Dump V2 then Manual TOU, or the other order)",
      C.entry("mtou1").reverts[FW](C.entry("dump_v2").reverts[FW](LIVE_DV2[FW]))
      == C.entry("dump_v2").reverts[FW](C.entry("mtou1").reverts[FW](LIVE_DV2[FW])) == C.as_of(FW, "fba", LIVE[FW]))
check("as_of('root') == as_of('fba') for every pinned artifact (FB-A changed none)",
      all(C.as_of(p, "root", LIVE[p]) == C.as_of(p, "fba", LIVE[p]) for p in sc.PINNED))
_m_root, _m_fba = sc.measure(C.as_of_all("root", LIVE)), sc.measure(C.as_of_all("fba", LIVE))
check("root measurements (computed) are main @ 004040b's: 30 scripts, 418 globals, 8 intervals, 55/6/3 durable sites, 52 writes / 60 reads, "
      "12 durable tag strings, 2 includes, no FB-A token in the firmware",
      (_m_root["scripts"], _m_root["globals"], _m_root["intervals"], _m_root["commit_record"], _m_root["load_record"],
       _m_root["load_record_status"], _m_root["modbus_writes"], _m_root["modbus_reads"], _m_root["durable_tag_strings"],
       _m_root["includes"], _m_root["banned_fw"]) == (30, 418, 8, 55, 6, 3, 52, 60, 12, 2, 0) and _m_root == _m_fba, str(_m_root))
_m_live = sc.measure(LIVE_DV2)
check("main @ ca7474e (as of dump_v2) measurements: 30 scripts, 422 globals, 9 intervals, 57/7/3 durable sites, 52/60 Modbus ops, 13 durable tag strings",
      (_m_live["scripts"], _m_live["globals"], _m_live["intervals"], _m_live["commit_record"], _m_live["load_record"],
       _m_live["load_record_status"], _m_live["modbus_writes"], _m_live["modbus_reads"], _m_live["durable_tag_strings"])
      == (30, 422, 9, 57, 7, 3, 52, 60, 13), str(_m_live))
_ops_root = sc.per_path_ops(C.as_of(FW, "root", LIVE[FW]))
_ops_live = sc.per_path_ops(LIVE_DV2[FW], sc._headers_of(LIVE_DV2))
check("the write surface is identical between main @ 004040b and main @ ca7474e (as of dump_v2): every path's ordered Modbus "
      "op list, and its path set", _ops_root == _ops_live)
check("analyze_as_of() runs the write-surface analyzer on the reverted text and headers",
      len(C.analyze_as_of("root", LIVE[FW])["paths"]) == len(_ops_root)
      and C.analyze_as_of("dump_v2", LIVE[FW])["bus_access_findings"] == [])

# ===========================================================================
print("")
print("[3] the older suites' own reverters compose with the chain")
# ===========================================================================
import _dump_sim as ds  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402
import _free_power_action_sim as fpsim  # noqa: E402

_boot_root = ds.load_firmware_text(C.as_of(FW, "root", LIVE[FW]))["esphome"]["on_boot"]["then"][0]["lambda"]
check("SG-06's reverter applied to main @ 004040b's on_boot / durable header reproduces main @ 049c37e (its base) exactly",
      sg06.sha(sg06.pre_sg06_boot(_boot_root)) == sg06.BASE_BOOT_SHA
      and sg06.sha(sg06.pre_sg06_header(C.as_of(sc.DURABLE_HEADER, "root", LIVE[sc.DURABLE_HEADER]))) == sg06.BASE_HEADER_SHA)
check("Dump V2's base scripts / globals reproduce through the chain (its script pins hold at the root)",
      all(dv2s.sha(fpsim.script_body(C.as_of(FW, "root", LIVE[FW]), sid)) == want for sid, want in dv2s.BASE_SCRIPT_SHAS.items()))

# ===========================================================================
print("")
print("[4] future PRs are representable as declared deltas (SYNTHETIC entries, in memory only)")
# ===========================================================================
_C1 = [
    ('substitutions:\n  ecco_inverter_tou_power_ceiling_w: "8000"\n',
     'substitutions:\n  ecco_inverter_tou_power_ceiling_w: "8000"\n  ecco_failback_shadow_probe_ms: "1000"\n'),
    ("globals:\n  - id: ntp_synced\n",
     "globals:\n  - id: failback_shadow_state\n    type: int\n    restore_value: no\n    initial_value: '0'\n  - id: ntp_synced\n"),
    ('text_sensor:\n  - platform: template\n    name: "NTP Time"\n',
     'text_sensor:\n  - platform: template\n    name: "Failback Shadow State"\n    id: failback_shadow_state_text\n'
     '    lambda: |-\n      return std::string("X");\n  - platform: template\n    name: "NTP Time"\n'),
    ("  # HA supervision heartbeat - PR A, OBSERVE-ONLY evaluation tick.",
     "  - interval: 1s\n    then:\n      - lambda: |-\n          id(failback_shadow_state) = 1;\n\n"
     "  # HA supervision heartbeat - PR A, OBSERVE-ONLY evaluation tick."),
]
_B0 = [("    - include/ecco_recovery_evidence.h\n",
        "    - include/ecco_recovery_evidence.h\n    - include/ecco_fallback_durable_model.h\n")]
_B1 = [("script:\n  - id: write_inverter_rtc\n",
        "script:\n  - id: fallback_profile_review\n    mode: single\n    then:\n"
        + "".join(f"      - modbus_client.read_holding_registers:\n          modbus_id: inverter_modbus\n          address: 0x01\n"
                  f"          start_address: {a}\n          count: 1\n          on_response:\n            then:\n"
                  f"              - lambda: |-\n                  id(failback_shadow_state) = values[0];\n"
                  for a in (230, 243, 245, 248))
        + "  - id: write_inverter_rtc\n")]


def _apply(text: str, edits) -> str:
    for before, after in edits:
        assert text.count(before) == 1, before[:60]
        text = text.replace(before, after)
    return text


_t0 = LIVE_DV2[FW]          # the firmware as of the newest entry this suite knows (== live until a later PR lands)
_t1 = _apply(_t0, _C1)
_t2 = _apply(_t1, _B0)
_t3 = _apply(_t2, _B1)
_E_C1 = sc.Entry(id="synth_c1", pr="#FB-C1", commit="synthetic", reverts={FW: sc.exact_reverter(_C1, "synth_c1")},
                 checkpoints={FW: sc.sha(_t1)}, deltas={"globals": 1, "intervals": 1, "text_sensors": 1, "substitutions": 1},
                 subst_added={"ecco_failback_shadow_probe_ms": "1000"}, banned_fw_added=1)
_E_B0 = sc.Entry(id="synth_b0", pr="#FB-B0", commit="synthetic", reverts={FW: sc.exact_reverter(_B0, "synth_b0")},
                 checkpoints={FW: sc.sha(_t2)}, deltas={"includes": 1}, includes_added=("include/ecco_fallback_durable_model.h",),
                 banned_fw_added=1, fbh_includers=frozenset({"firmware/include/ecco_fallback_durable_model.h"}))
_E_B1 = sc.Entry(id="synth_b1", pr="#FB-B1", commit="synthetic", reverts={FW: sc.exact_reverter(_B1, "synth_b1")},
                 checkpoints={FW: sc.sha(_t3)}, deltas={"scripts": 1, "modbus_reads": 4},
                 op_paths_changed=frozenset({"fallback_profile_review"}))
C2 = sc.Chain(C_DV2.entries + (_E_C1, _E_B0, _E_B1))
LIVE2 = {**LIVE_DV2, FW: _t3}
_rows = sc.integrity_report(C2, LIVE2)
for name, ok, detail in _rows:
    check("[synthetic FB-C1/B0/B1 appended] " + name, ok, detail)
check("[synthetic] the extended chain reproduces every existing entry's checkpoint from the FUTURE live text - the older suites' "
      "anchors (fba / mtou1 / dump_v2 as-of views) are untouched by later PRs",
      all(sc.sha(C2.as_of(FW, eid, _t3)) == C.checkpoint(FW, eid) for eid in ("root", *KNOWN))
      and all(C2.as_of(FW, eid, _t3) == C.as_of(FW, eid, LIVE[FW]) for eid in ("root", *KNOWN)))
check("[synthetic] declared includers / includes / substitutions / banned-token counts accumulate per entry",
      C2.declared_includers() == C_DV2.declared_includers() | {"firmware/include/ecco_fallback_durable_model.h"}
      and C2.declared_includes() == ("include/ecco_fallback_durable_model.h",)
      and C2.declared_includes("synth_c1") == ("include/ecco_fallback_durable_model.h",)
      and C2.declared_subst() == {"ecco_failback_shadow_probe_ms": "1000"} and C2.declared_banned_fw() == 2
      and C2.declared_banned_fw("synth_c1") == 1 and C2.declared_banned_fw("dump_v2") == 0)
_a1 = C2.analyze_as_of("dump_v2", _t3, LIVE2)
check("[synthetic] the analyzer run as-of dump_v2 on the future text sees today's 52 write / 60 read ops (the +4 reads are declared by "
      "synth_b1 only)", sum(1 for p in _a1["paths"] for o in p.ops if o.kind == "write") == 52
      and sum(1 for p in _a1["paths"] for o in p.ops if o.kind == "read") == 60
      and sum(1 for p in sc.analyze_text(_t3, sc._headers_of(LIVE2))["paths"] for o in p.ops if o.kind == "read") == 64)

_a_all = {eid: C2.analyze_as_of(eid, _t3, LIVE2) for eid in ("root", *KNOWN)}
check("[synthetic] analyze_as_of() reports NO finding (bus access / unknown extent) at root and every known entry, and no "
      "'included file not found' (the as-of headers are materialised next to the as-of firmware)",
      all(a["bus_access_findings"] == [] and a["unknown_extent_writes"] == [] for a in _a_all.values()),
      str({k: v["bus_access_findings"] for k, v in _a_all.items() if v["bus_access_findings"]}))
# the analyzer must see the AS-OF header, not the live one: a LATER entry that edits the durable header with raw bus access
_INJ = "\nvoid fbt0_probe() { ModbusCommandItem x; }\n"
_E_DS = sc.Entry(id="synth_ds", pr="#X", commit="synthetic", reverts={sc.DURABLE_HEADER: sc.exact_reverter([("", _INJ)], "synth_ds")},
                 checkpoints={sc.DURABLE_HEADER: sc.sha(LIVE_DV2[sc.DURABLE_HEADER] + _INJ)})
_C_DS = sc.Chain(C_DV2.entries + (_E_DS,))
_LIVE_DS = {**LIVE_DV2, sc.DURABLE_HEADER: LIVE_DV2[sc.DURABLE_HEADER] + _INJ}
check("[synthetic] a LATER entry's header edit is reverted before the analyzer runs: as of dump_v2 the analyzer reports no finding, "
      "while the analyzer run on the live (edited) header DOES report the raw Modbus API - so the as-of header, not the live one, "
      "is what analyze_as_of() materialises",
      _C_DS.analyze_as_of("dump_v2", live=_LIVE_DS)["bus_access_findings"] == []
      and sc.analyze_text(_t0, sc._headers_of(_LIVE_DS))["bus_access_findings"] != [])

# ===========================================================================
print("")
print("[5] mutation sensitivity")
# ===========================================================================


def report_fails(chain, live, needle: str) -> bool:
    return any((not ok) and needle in name for name, ok, _d in sc.integrity_report(chain, live))


def chain_broken(chain, live) -> bool:
    """True when ANY integrity row fails (an exact-match reverter that no longer applies is itself a failure row)."""
    return any(not ok for _n, ok, _d in sc.integrity_report(chain, live))


def replace(entry: sc.Entry, **kw) -> sc.Entry:
    d = {f: getattr(entry, f) for f in entry.__dataclass_fields__}
    d.update(kw)
    return sc.Entry(**d)


check("mutation: a misdeclared delta (globals +2 -> +3 on synth_c1) is detected",
      report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1, deltas={**_E_C1.deltas, "globals": 3}), _E_B0, _E_B1)), LIVE2, "declared deltas"))
check("mutation: an omitted delta (synth_b1 without its +4 reads) is detected",
      report_fails(sc.Chain(C_DV2.entries + (_E_C1, _E_B0, replace(_E_B1, deltas={"scripts": 1}))), LIVE2, "declared deltas"))
check("mutation: an undeclared op path change is detected",
      report_fails(sc.Chain(C_DV2.entries + (_E_C1, _E_B0, replace(_E_B1, op_paths_changed=frozenset()))), LIVE2, "op_paths_changed"))
check("mutation: an undeclared include is detected",
      report_fails(sc.Chain(C_DV2.entries + (_E_C1, replace(_E_B0, includes_added=()), _E_B1)), LIVE2, "includes"))
# --- substitution key -> VALUE declarations (Cloud B red-team) ---
check("synthetic FB-C1 substitution: correct key AND value passes (the [4] report above is all-green)",
      all(ok for n, ok, _d in _rows if "synth_c1: substitutions" in n) and any("synth_c1: substitutions added" in n for n, _o, _d in _rows))
check("mutation: correct key with the WRONG value is detected",
      report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1, subst_added={"ecco_failback_shadow_probe_ms": "999"}), _E_B0, _E_B1)),
                   LIVE2, "substitutions added"))
check("mutation: an undeclared substitution is detected (key omitted from the declaration)",
      report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1, subst_added={}), _E_B0, _E_B1)), LIVE2, "substitutions added"))
_C1_EXTRA = _C1 + [('  ecco_failback_shadow_probe_ms: "1000"\n',
                    '  ecco_failback_shadow_probe_ms: "1000"\n  ecco_failback_shadow_extra_ms: "5"\n')]
_t1x = _apply(_t0, _C1[:1] + [_C1_EXTRA[-1]] + _C1[1:])
_E_C1X = replace(_E_C1, reverts={FW: sc.exact_reverter(_C1[:1] + [_C1_EXTRA[-1]] + _C1[1:], "synth_c1x")}, checkpoints={FW: sc.sha(_t1x)})
_t3x = _apply(_apply(_t1x, _B0), _B1)
_E_B0X = replace(_E_B0, checkpoints={FW: sc.sha(_apply(_t1x, _B0))})
_E_B1X = replace(_E_B1, checkpoints={FW: sc.sha(_t3x)})
_LIVE3 = {**LIVE_DV2, FW: _t3x}
check("mutation: an UNDECLARED extra `ecco_failback_shadow_*` substitution fails even though another key of the same family is "
      "declared (no prefix exemption)",
      report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1X, deltas={**_E_C1.deltas, "substitutions": 2}), _E_B0X, _E_B1X)), _LIVE3,
                   "substitutions added"))
check("...and declaring BOTH keys with their exact values passes",
      not any((not ok) and "substitutions" in n for n, ok, _d in sc.integrity_report(sc.Chain(C_DV2.entries + (replace(
          _E_C1X, deltas={**_E_C1.deltas, "substitutions": 2},
          subst_added={"ecco_failback_shadow_probe_ms": "1000", "ecco_failback_shadow_extra_ms": "5"}), _E_B0X, _E_B1X)), _LIVE3)))
# existing substitutions: neither removed nor silently changed unless an entry declares it
_SUBCHG = [('  ecco_dump_soc_stale_ms: "90000"\n', '  ecco_dump_soc_stale_ms: "91000"\n')]
_t_chg = _apply(_t3, _SUBCHG)
_E_CHG = sc.Entry(id="synth_chg", pr="#X", commit="synthetic", reverts={FW: sc.exact_reverter(_SUBCHG, "synth_chg")},
                  checkpoints={FW: sc.sha(_t_chg)})
_CH_CHG = sc.Chain(C2.entries + (_E_CHG,))
check("mutation: an existing substitution SILENTLY CHANGED (ecco_dump_soc_stale_ms 90000 -> 91000) is detected",
      report_fails(_CH_CHG, {**LIVE2, FW: _t_chg}, "removed / changed"))
check("...and passes once the entry declares the exact (old, new) change",
      not any(not ok for _n, ok, _d in sc.integrity_report(sc.Chain(C2.entries + (replace(
          _E_CHG, subst_changed={"ecco_dump_soc_stale_ms": ("90000", "91000")}),)), {**LIVE2, FW: _t_chg})))
_NEXT = "  # Maximum age of the last successful configuration block 241-293 read\n"
_REM = [('  ecco_dump_soc_stale_ms: "90000"\n' + _NEXT, _NEXT)]
_t_rem = _apply(_t3, _REM)
_E_REM = sc.Entry(id="synth_rem", pr="#X", commit="synthetic", reverts={FW: sc.exact_reverter(_REM, "synth_rem")},
                  checkpoints={FW: sc.sha(_t_rem)})
check("mutation: an existing substitution REMOVED without a declaration is detected",
      report_fails(sc.Chain(C2.entries + (_E_REM,)), {**LIVE2, FW: _t_rem}, "removed / changed"))
check("a substitution may not be declared both added and changed, and declarations must be exact string pairs (no globs)",
      _raises(lambda: sc.Chain((sc.Entry(id="x", pr="#0", commit="0", subst_added={"a": "1"}, subst_changed={"a": ("1", "2")}),)), sc.ChainError)
      and _raises(lambda: sc.Chain((sc.Entry(id="x", pr="#0", commit="0", subst_added={"ecco_failback_shadow_*": "1"}),)), sc.ChainError)
      and _raises(lambda: sc.Chain((sc.Entry(id="x", pr="#0", commit="0", subst_added={"a": 1}),)), sc.ChainError))
check("declared paths must be exact repo-relative POSIX paths: backslashes, absolute paths, '..' and globs are rejected (no "
      "prefix/glob exemptions)",
      all(_raises(lambda p=p: sc.Chain((sc.Entry(id="x", pr="#0", commit="0", banned_files=frozenset({p})),)), sc.ChainError)
          for p in ("home-assistant\\packages\\x.yaml", "/home-assistant/x.yaml", "C:/x.yaml", "home-assistant/*.yaml",
                    "home-assistant/../x.yaml", "home-assistant/packages/", "")))
check("mutation: a wrong checkpoint is detected",
      report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1, checkpoints={FW: "0" * 64}), _E_B0, _E_B1)), LIVE2, "checkpoint"))
check("mutation: ANY undeclared edit to the firmware (one extra comment line) breaks the chain",
      chain_broken(C2, {**LIVE2, FW: _t3 + "# undeclared\n"}))
check("mutation: ANY undeclared edit to the durable header breaks the chain",
      chain_broken(C, {**LIVE, sc.DURABLE_HEADER: LIVE[sc.DURABLE_HEADER] + "// undeclared\n"}))
check("mutation: an undeclared edit to ha-manifest / registry files breaks the chain",
      all(chain_broken(C, {**LIVE, p: LIVE[p] + "\n# undeclared\n"}) for p in (sc.HA_MANIFEST, sc.CAPABILITIES, sc.STATE_MACHINE)))
check("mutation: an identity reverter is refused as vacuous",
      report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1, reverts={FW: lambda t: t}), _E_B0, _E_B1)), LIVE2, "none is an identity")
      or report_fails(sc.Chain(C_DV2.entries + (replace(_E_C1, reverts={FW: lambda t: t}), _E_B0, _E_B1)), LIVE2, "reverters apply"))
_rev = sc.exact_reverter(_C1, "x")
check("mutation: a reverter whose edit is absent raises", _raises(lambda: _rev(_t0)))
check("mutation: a reverter whose edit is duplicated raises", _raises(lambda: _rev(_t1 + _C1[0][1])))
_mt, _dv = C.entry("mtou1").reverts[FW], C.entry("dump_v2").reverts[FW]
check("mutation: the real Manual TOU / Dump V2 reverters raise when one of their edits is absent or altered (any OTHER change "
      "still breaks the pins that use them)",
      _raises(lambda: _mt(_mt(LIVE_DV2[FW])))                   # edits already reverted -> absent
      and _raises(lambda: _dv(_dv(LIVE_DV2[FW])))
      and _raises(lambda: _dv(LIVE_DV2[FW].replace("dump_evidence_pending_ceiling", "dump_evidence_pending_ceilinX", 1))))

# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All scope-chain checks passed.")
print("These pin how the change-scope proofs are reconstructed; they prove nothing about hardware.")
