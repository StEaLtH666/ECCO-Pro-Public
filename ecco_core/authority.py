"""Write authority: who may change what on the inverter, stated as data and checked against the firmware.

The controller firmware is the only writer, and it enforces its own gates (ownership flags, arm switches, fresh reads,
durable records, verify-after-write). Those rules are spread across 17 writing scripts; this module states them in ONE
reviewable table, per write path:

    who owns it            the feature, the controller ownership flags it takes, the arm switch that must be on
    what it may change     the control capability it needs and the exact registers it writes
    how it is undone       the durable obligation flags it opens and closes, and how the original state is restored

The table is not hand-waved: ecco_core/tests checks it against tools/analyze_write_surface.py (the firmware's own write
surface, script by script), against the capability registry's read_write records and against the conflict declarations
of registry/transaction_state_machine.py, so a firmware change that alters authority fails a test until this table and
its review are updated.

`evaluate()` is a pure REFERENCE decision model for review, simulation and any future write-capable feature: given an
intent and a snapshot it says whether the controller's rules would permit it and which obligations come with it. It
executes nothing, there is no host-side write transport for it to call, and it never authorises an advisory origin
(Intelligence, a dashboard, anything not a declared feature). Current authority is unchanged: nothing calls it to write.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capability import HARDWARE_TESTED, DeviceProfile
from .freshness import CONTROL_GATE, FreshnessPolicy
from .state import Snapshot

RESTORE_DURABLE = "durable snapshot, then verified restore (timer / watchdog / operator recovery)"
RESTORE_NONE_MANUAL = "none: a manual apply is owned by the person who applied it (SAFETY.md section 8)"
RESTORE_NOT_APPLICABLE = "not applicable: the corrected clock is the intended end state"


@dataclass(frozen=True)
class WriteAuthority:
    feature: str
    capability: str
    scripts: frozenset[str]            # the firmware scripts that write for this feature
    registers: frozenset[int]          # exactly the registers those scripts write
    owner_flags: frozenset[str]        # controller ownership flags the feature takes
    arm_switch: str | None             # write-enable switch its START path checks (None = no arm switch)
    obligation_flags: frozenset[str]   # durable obligation flags it opens / closes
    restore: str
    verify: str
    gate_signals: tuple[str, ...] = ()  # readings the controller requires fresh (CONTROL_GATE) before it starts
    open_obligation_flags: frozenset[str] = frozenset()   # the subset meaning "a restore is still owed"


def _r(a: int, b: int) -> frozenset[int]:
    return frozenset(range(a, b + 1))


_TOU_REGS = frozenset({232}) | _r(250, 261) | _r(268, 279)

AUTHORITIES: tuple[WriteAuthority, ...] = (
    WriteAuthority("clock_correction", "control.clock", frozenset({"write_inverter_rtc"}), _r(22, 24),
                   frozenset({"correction_in_progress"}), None, frozenset(), RESTORE_NOT_APPLICABLE,
                   "clock read back after the write is acknowledged"),
    WriteAuthority("manual_tou", "control.tou_schedule", frozenset(f"apply_manual_slot{n}" for n in range(1, 7)), _TOU_REGS,
                   frozenset({"manual_write_in_progress"}), "manual_config_write_enable", frozenset(), RESTORE_NONE_MANUAL,
                   "registers 232 and 250-279 read back after the apply"),
    WriteAuthority("export_mode_policy", "control.export_mode", frozenset({"apply_reg244_settings", "restore_reg244_snapshot"}),
                   frozenset({244}), frozenset({"manual_write_in_progress", "reg244_apply_in_progress"}),
                   "manual_config_write_enable", frozenset({"reg244_snapshot_valid", "reg244_last_applied_valid"}),
                   RESTORE_DURABLE, "register 244 read back after each write",
                   open_obligation_flags=frozenset({"reg244_snapshot_valid"})),
    WriteAuthority("free_power", "control.grid_charge",
                   frozenset({"start_free_power_override", "restore_free_power_snapshot_dispatch",
                              "free_power_recovery_force_restore_dispatch"}),
                   frozenset({230, 232}) | _r(256, 261) | _r(268, 279),
                   frozenset({"free_power_operation_in_progress", "manual_write_in_progress"}), "free_power_write_enable",
                   frozenset({"free_power_snapshot_valid", "free_power_active_persisted", "free_power_restore_requested"}),
                   RESTORE_DURABLE, "registers 230-232, 256-261 and 268-279 read back after each write",
                   open_obligation_flags=frozenset({"free_power_snapshot_valid", "free_power_active_persisted",
                                                    "free_power_restore_requested"})),
    WriteAuthority("dump_to_grid", "control.dump_to_grid",
                   frozenset({"start_dump_to_grid_override", "dump_controller_tick", "restore_dump_to_grid_snapshot",
                              "dump_lockout_containment"}),
                   frozenset({244}) | _r(256, 261),
                   frozenset({"dump_operation_in_progress", "manual_write_in_progress"}), "dump_write_enable",
                   frozenset({"dump_snapshot_valid", "dump_active_persisted", "dump_restore_requested"}),
                   RESTORE_DURABLE, "registers 244 and 256-261 read back after each write",
                   gate_signals=("battery.soc", "grid.power"),
                   open_obligation_flags=frozenset({"dump_snapshot_valid", "dump_active_persisted", "dump_restore_requested"})),
)
_BY_FEATURE = {a.feature: a for a in AUTHORITIES}

# Every controller ownership flag (tools/analyze_write_surface.py OWNERSHIP_FLAGS): a start is refused while ANOTHER
# is held, or while its state is unknown.
OWNERSHIP_FLAGS = ("manual_write_in_progress", "correction_in_progress", "free_power_operation_in_progress",
                   "reg244_apply_in_progress", "dump_operation_in_progress")
# Origins that can never hold write authority, whatever else an intent says.
ADVISORY_ORIGINS = frozenset({"intelligence", "advisory", "dashboard", "simulation_advice"})


@dataclass(frozen=True)
class WriteIntent:
    origin: str                      # a feature name from AUTHORITIES, or anything else (refused)
    capability: str
    registers: frozenset[int]
    armed: bool = False


@dataclass(frozen=True)
class Decision:
    permitted: bool
    reasons: tuple[str, ...]          # why it is refused (empty when permitted)
    obligations: tuple[str, ...]      # what the controller must do around the write if it went ahead
    executes_nothing: bool = True     # a Decision is information, never an action

    def __post_init__(self) -> None:
        if self.executes_nothing is not True:
            raise ValueError("a Decision never executes anything")
        if self.permitted == bool(self.reasons):
            raise ValueError("a permitted decision has no refusal reasons, and a refusal states at least one")


def authority_for(feature: str) -> WriteAuthority | None:
    return _BY_FEATURE.get(feature)


def evaluate(intent: WriteIntent, snapshot: Snapshot, profile: DeviceProfile, *, controller_variant: str,
             policy: FreshnessPolicy | None = None) -> Decision:
    """Would the controller's rules permit this write now? Pure; fail closed; collects every reason."""
    policy = policy or FreshnessPolicy(CONTROL_GATE)
    reasons: list[str] = []
    auth = _BY_FEATURE.get(intent.origin)
    if intent.origin in ADVISORY_ORIGINS:
        return Decision(False, (f"origin {intent.origin!r} is advisory: advisory code never holds write authority",), ())
    if auth is None:
        return Decision(False, (f"origin {intent.origin!r} is not a declared write path",), ())
    if policy.purpose != CONTROL_GATE:
        reasons.append("a write decision needs the control-gate freshness policy")
    if intent.capability != auth.capability:
        reasons.append(f"{auth.feature} holds {auth.capability}, not {intent.capability}")
    outside = sorted(set(intent.registers) - auth.registers)
    if not intent.registers or outside:
        reasons.append(f"registers outside {auth.feature}'s authority: {outside}" if outside else "no registers named")
    st = profile.status(auth.capability)
    if not st.supported:
        reasons.append(f"capability {auth.capability} is {st.status}")
    else:
        proof = profile.proof_on(auth.capability, controller_variant)
        if proof != HARDWARE_TESTED:
            reasons.append(f"{auth.capability} is {proof} on controller variant {controller_variant!r}")
    def known(signal: str):
        """The flag's value only when its reading is FRESH for a control gate; otherwise None (= unknown). No catalogue
        limit exists for controller flags, so they stay unknown unless the installation configures one."""
        a = policy.assess(snapshot, signal)
        return snapshot.value(signal) if a.fresh else None

    if auth.arm_switch is not None:
        arm = known(f"controller.arm.{auth.arm_switch}")
        if intent.armed is not True or arm is not True:
            reasons.append(f"write-enable switch {auth.arm_switch} is not known to be on")
    for flag in OWNERSHIP_FLAGS:
        held = known(f"controller.owner.{flag}")
        if held is not False:
            reasons.append(f"ownership flag {flag} is " + ("held" if held is True else "unknown or not fresh"))
    # Models STARTING a write action (restoring an owed obligation is the controller's own duty, not an intent). Fail
    # closed and stricter than per-register arbitration: ANY open or unknown restore obligation refuses a new start.
    for other in AUTHORITIES:
        for flag in sorted(other.open_obligation_flags):
            open_ = known(f"controller.obligation.{flag}")
            if open_ is not False:
                reasons.append(f"durable obligation {flag} is " + ("open" if open_ is True else "unknown or not fresh"))
    for a in policy.not_fresh(snapshot, auth.gate_signals):
        reasons.append(f"{a.signal} is {a.status} for a control gate ({a.reason})")
    obligations = [f"take ownership: {', '.join(sorted(auth.owner_flags))}", f"restore: {auth.restore}",
                   f"verify: {auth.verify}"]
    if auth.obligation_flags:
        obligations.insert(1, "commit the durable snapshot before the first write")
    return Decision(not reasons, tuple(reasons), tuple(obligations) if not reasons else ())
