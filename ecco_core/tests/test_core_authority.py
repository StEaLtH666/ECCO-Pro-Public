#!/usr/bin/env python3
"""ecco_core.authority: the write-authority table equals the firmware's own write surface (tools/analyze_write_surface.py,
script by script), the capability registry's read_write records and the transaction model's conflict declarations; the
reference decision model fails closed and never authorises an advisory origin. Pure, synthetic, offline."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "registry"))

import analyze_write_surface as aws  # noqa: E402
import transaction_state_machine as tsm  # noqa: E402

from ecco_core import authority as au  # noqa: E402
from ecco_core.capability import DeviceProfile  # noqa: E402
from ecco_core.freshness import ADVISORY, CONTROL_GATE, FreshnessPolicy  # noqa: E402
from ecco_core.state import NORMALIZED, Observation, Snapshot  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


P = DeviceProfile.from_registry()
res = aws.analyze()
paths = {p.name: p for p in res["paths"]}
writers = {p.name: p for p in res["paths"] if p.kind == "script" and p.writes}

print("[1] the table equals the firmware's write surface, script by script")
check("the analyser is clean (no unknown extent, no unmodelled bus access) - the comparison is meaningful",
      not res["unknown_extent_writes"] and not res["bus_access_findings"])
claimed = [s for a in au.AUTHORITIES for s in a.scripts]
check("every writing script belongs to exactly one write path", sorted(claimed) == sorted(writers),
      f"unclaimed {sorted(set(writers) - set(claimed))}, phantom {sorted(set(claimed) - set(writers))}")
for a in au.AUTHORITIES:
    written = set().union(*(writers[s].written_addresses for s in a.scripts if s in writers))
    check(f"{a.feature}: declared registers == registers its scripts write", written == set(a.registers),
          f"declared-only {sorted(set(a.registers) - written)}, written-only {sorted(written - set(a.registers))}")
    acquired = set()
    for s in a.scripts:
        acquired |= set(writers[s].acquires)
        acquired |= {f for d in paths.values() if s in d.dispatches for f in d.acquires}   # a caller may take the lock
    check(f"{a.feature}: owner flags are flags the firmware actually takes", set(a.owner_flags) <= acquired,
          f"{sorted(set(a.owner_flags) - acquired)}")
    obl = set().union(*(set(writers[s].obligations_set) | set(writers[s].obligations_cleared) for s in a.scripts))
    check(f"{a.feature}: obligation flags == those its scripts open or close", obl == set(a.obligation_flags),
          f"{sorted(obl ^ set(a.obligation_flags))}")
    check(f"{a.feature}: owed-restore flags are a subset of its obligation flags", a.open_obligation_flags <= a.obligation_flags)
    if a.arm_switch is not None:
        check(f"{a.feature}: its arm switch is checked by a writing script",
              any(a.arm_switch in writers[s].arms_checked for s in a.scripts))
    else:
        check(f"{a.feature}: declared without an arm switch, and no writing script checks one",
              not any(writers[s].arms_checked for s in a.scripts))
    check(f"{a.feature}: its registers are inside its capability's registers",
          set(a.registers) <= set(P.registers(a.capability)), f"{sorted(set(a.registers) - set(P.registers(a.capability)))}")
union = frozenset().union(*(a.registers for a in au.AUTHORITIES))
surface = frozenset(aws.write_surface(res["paths"]))
check("the table's register union == the firmware write surface", union == surface, str(sorted(union ^ surface)))
check("== the capability registry's read_write records (closing an unchecked gap between the two)",
      union == frozenset().union(*P.read_write_records().values()))
check("the ownership flags are the analyser's", tuple(au.OWNERSHIP_FLAGS) == tuple(aws.OWNERSHIP_FLAGS))

print("[2] the table agrees with the transaction model's conflict declarations")
decl = tsm.ECCO_CONFLICT_DECLARATIONS          # name -> (owned_registers, conflict_domains)
for name, feature in (("rtc_clock", "clock_correction"), ("free_power_transaction", "free_power"),
                      ("grid_export_policy", "export_mode_policy"), ("dump_to_grid_transaction", "dump_to_grid")):
    check(f"{name} == {feature}", frozenset(decl[name][0]) == au.authority_for(feature).registers, str(sorted(decl[name][0])))
check("tou_slot_1 == what apply_manual_slot1 writes",
      frozenset(decl["tou_slot_1"][0]) == frozenset(writers["apply_manual_slot1"].written_addresses))

print("[3] the decision model fails closed")
NOW = datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc)


def ob(sig: str, v, age: float = 5.0) -> Observation:
    return Observation(sig, v, NOW - timedelta(seconds=age), "controller", NORMALIZED)


def good(**over) -> Snapshot:
    obs = {f"controller.owner.{f}": False for f in au.OWNERSHIP_FLAGS}
    obs.update({f"controller.obligation.{f}": False for a in au.AUTHORITIES for f in a.open_obligation_flags})
    obs.update({f"controller.arm.{a.arm_switch}": True for a in au.AUTHORITIES if a.arm_switch})
    obs.update({"battery.soc": 80.0, "grid.power": 50.0})
    obs.update(over)
    return Snapshot.of(NOW, [ob(k, v) for k, v in obs.items() if v is not ...])


# No catalogue limit exists for controller flag readings, so a usable decision needs the installation to resolve them.
GATE = FreshnessPolicy(CONTROL_GATE, {"controller.owner.*": 10.0, "controller.obligation.*": 10.0, "controller.arm.*": 10.0})


def ev(origin, capability, regs, snap=None, armed=True, variant="esp32_classic", policy=GATE):
    return au.evaluate(au.WriteIntent(origin, capability, frozenset(regs), armed), snap or good(), P,
                       controller_variant=variant, policy=policy)


ok = ev("export_mode_policy", "control.export_mode", {244})
check("a fully gated export-mode start is permitted by the reference model, with its obligations",
      ok.permitted and ok.executes_nothing and any("durable snapshot" in o for o in ok.obligations))
for origin in sorted(au.ADVISORY_ORIGINS):
    d = ev(origin, "control.export_mode", {244})
    check(f"advisory origin {origin!r} is refused even with a perfect snapshot", not d.permitted and "advisory" in d.reasons[0])
check("an undeclared origin is refused", not ev("my_new_feature", "control.export_mode", {244}).permitted)
check("a capability the feature does not hold is refused", not ev("export_mode_policy", "control.grid_charge", {244}).permitted)
check("a register outside the feature's authority is refused", not ev("export_mode_policy", "control.export_mode", {244, 245}).permitted)
check("naming no register is refused", not ev("export_mode_policy", "control.export_mode", set()).permitted)
check("not armed is refused", not ev("export_mode_policy", "control.export_mode", {244}, armed=False).permitted)
check("arm switch off or unknown is refused",
      not ev("export_mode_policy", "control.export_mode", {244}, good(**{"controller.arm.manual_config_write_enable": False})).permitted
      and not ev("export_mode_policy", "control.export_mode", {244}, good(**{"controller.arm.manual_config_write_enable": ...})).permitted)
check("another owner holding the bus is refused",
      not ev("export_mode_policy", "control.export_mode", {244}, good(**{"controller.owner.free_power_operation_in_progress": True})).permitted)
check("an ownership flag of UNKNOWN state is refused",
      not ev("export_mode_policy", "control.export_mode", {244}, good(**{"controller.owner.correction_in_progress": ...})).permitted)
check("an open restore obligation of ANY feature is refused",
      not ev("export_mode_policy", "control.export_mode", {244}, good(**{"controller.obligation.dump_snapshot_valid": True})).permitted)
check("an obligation of unknown state is refused",
      not ev("free_power", "control.grid_charge", {230}, good(**{"controller.obligation.free_power_restore_requested": ...})).permitted)
check("the ESP32-S3 (write features offline only) is refused", not ev("free_power", "control.grid_charge", {230}, variant="esp32s3").permitted)
check("Dump-to-Grid is refused while its capability is UNKNOWN in the registry",
      not ev("dump_to_grid", "control.dump_to_grid", {244, 256}).permitted)
check("a non-control-gate freshness policy is refused",
      not ev("export_mode_policy", "control.export_mode", {244}, policy=FreshnessPolicy(ADVISORY)).permitted)
dflt = au.evaluate(au.WriteIntent("export_mode_policy", "control.export_mode", frozenset({244}), True), good(), P,
                   controller_variant="esp32_classic")
check("with the default policy (controller flag limits UNRESOLVED) even a perfect snapshot is refused",
      not dflt.permitted and any("unknown or not fresh" in r for r in dflt.reasons))
old_flag = Snapshot.of(NOW, [o if o.signal != "controller.owner.free_power_operation_in_progress" else
                             ob("controller.owner.free_power_operation_in_progress", False, age=600.0)
                             for o in good().observations.values()])
check("an ownership flag read 10 minutes ago counts as unknown, not free",
      not ev("export_mode_policy", "control.export_mode", {244}, old_flag).permitted)
old_arm = Snapshot.of(NOW, [o if o.signal != "controller.arm.manual_config_write_enable" else
                            ob("controller.arm.manual_config_write_enable", True, age=600.0) for o in good().observations.values()])
check("a stale arm-switch reading does not count as armed", not ev("export_mode_policy", "control.export_mode", {244}, old_arm).permitted)
stale_soc = good(**{"battery.soc": ...})
check("Dump-to-Grid's gate readings must be fresh (no SOC reading -> refused, whatever else)",
      any("battery.soc" in r for r in ev("dump_to_grid", "control.dump_to_grid", {244}, stale_soc).reasons))
check("a refusal carries no obligations, a permission no reasons",
      ev("intelligence", "control.export_mode", {244}).obligations == () and ok.reasons == ())
bad = False
try:
    au.Decision(True, ("x",), ())
except ValueError:
    bad = True
try:
    au.Decision(False, (), (), executes_nothing=False)
except ValueError:
    bad = bad and True
check("a Decision cannot be built inconsistent or as something that executes", bad)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in ecco_core authority:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll ecco_core authority checks passed")
