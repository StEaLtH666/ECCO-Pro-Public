"""ECCO safe-write transaction state machine - reference implementation.

DESIGN/TEST ARTIFACT ONLY. This module performs NO Modbus, network, or
file I/O of any kind. It exists solely so the state machine's rules
(the legal-transition table and invariants documented in
docs/SAFE_WRITE_TRANSACTION_ARCHITECTURE.md) can be exercised by real,
executable, offline tests - see registry/tests/test_transaction_state_machine.py.

This is NOT the code that would eventually run on the ESP32 or in Home
Assistant to perform a real inverter write. It performs no writes,
connects to nothing, and importing it has no side effects.

2026-09-21 audit extension
--------------------------
docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md audited this model
against the four write paths that are live-proven on hardware (RTC,
six-slot manual TOU, Free Power, register 244) and found six things the
original model could not express. They are added below as METADATA on
the existing ten states rather than as new states, because in every case
the live implementations' transition structure is already the modelled
one - what differs is the information carried alongside it:

  1. `TransactionKind` - PERMANENT vs TEMPORARY_OVERRIDE. The original
     model let a temporary override take `completed -> idle` and silently
     drop its restore obligation. A temporary override must not.
  2. `WriteOutcome` - CONFIRMED / UNCERTAIN / UNATTEMPTED. Register 244's
     live implementation already distinguishes "we know the write did not
     land" from "the inverter may have accepted it but we never found
     out"; the original model collapsed both into `failed`.
  3. Snapshot DURABILITY - a snapshot that has not reached flash cannot be
     relied on by a restart. The live firmware persists before writing and
     waits for a flush; the model had no notion of durability.
  4. Owned REGISTER SETS - the original registry keyed exclusive access on
     `capability_id` alone, so two capabilities touching the same register
     looked independent. Ownership is over registers, not names.
  5. Restore ATTEMPT BOUNDS - the live Free Power watchdog retries restore
     every 15s indefinitely. The model had no notion of a bounded retry.
  6. SEMANTIC CONFLICT DOMAINS - added in the 2026-09-21 correction pass
     after review. Register ownership alone is NOT sufficient: register
     244 writes only register 244, yet the live firmware deliberately
     blocks manual TOU and Free Power while a 244 snapshot is pending,
     because 244 decides whether TOU Power (256-261) means an export cap
     or a battery discharge cap. A model arbitrating on registers alone
     would permit a combination the hardware-proven design rejects - so
     a transaction declares the registers it WRITES and, separately, the
     semantic domains it affects or depends on. See `ConflictDomain`.

Everything added is additive: the pre-existing constructor signatures,
method names, transition table and exception types are unchanged, so
registry/tests/test_transaction_state_machine.py still exercises the
original contract untouched. The added semantics are covered by
registry/tests/test_transaction_engine_semantics.py.

2026-09-22 repo-only recovery-classifier v2 (design/test artifact only)
-------------------------------------------------------------------------
Everything from `SafeDirection` to the end of this module is a SEPARATE,
ADDITIVE design surface recommended by the Fable adversarial review of
the model above: a durable-record shape (`OwnerRecord`) and a total,
pure classifier (`classify_recovery_v2`) for how a FUTURE executor
should reason about recovery after a reboot or an uncertain write -
before any firmware, Modbus, or Home Assistant code is touched. It does
not replace, redesign, or get consulted by `classify_recovery()` above:
that function, `PersistedTransactionState`, and every existing test
continue to describe exactly the model the 2026-09-21 audit reasoned
about, unchanged. See registry/tests/test_recovery_classifier_v2.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TransactionKind(str, Enum):
    """What the transaction owes the system once it has completed.

    PERMANENT - a deliberate setting change the operator intends to keep
    (the six manual TOU slots, the RTC correction). Its snapshot exists
    only so a partial/failed write can be rolled back; a verified success
    ends the transaction and owes nothing.

    TEMPORARY_OVERRIDE - a lease over the registers it wrote (Free Power;
    register 244 as operated by the current proof harness; the proposed
    Battery Export control). A verified success does NOT end the
    transaction - it begins an obligation to restore the exact snapshot,
    and that obligation must survive a restart.
    """

    PERMANENT = "permanent"
    TEMPORARY_OVERRIDE = "temporary_override"


class WriteOutcome(str, Enum):
    """What is actually known about whether ECCO's write reached the inverter.

    UNATTEMPTED - no write has been issued for this transaction yet.

    CONFIRMED - a write was issued AND an exact reread verified the value.
    Only in this state may a drift guard meaningfully compare the live
    value against "what ECCO last wrote".

    UNCERTAIN - a write was issued and ECCO does not know the result: the
    Modbus request errored or timed out, or the verification reread never
    completed. The inverter may or may not have accepted it. This is NOT
    the same as "the write failed", and treating it as such is how a
    system silently diverges from the hardware. The live register 244
    implementation is the precedent: it clears its last-applied marker
    BEFORE issuing a write, so a power cut between the request and the
    reread leaves persisted evidence of uncertainty rather than a stale
    claim of knowledge.
    """

    UNATTEMPTED = "unattempted"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


class RecoveryAction(str, Enum):
    """What a restart should offer, given only persisted state.

    Deliberately an OFFER, never an action: nothing here authorises the
    engine to write. `AUTO_RESTORE_PERMITTED` means "an unattended
    watchdog may drive the restore", which is the single case where the
    live firmware already acts without a human (Free Power's 15s
    watchdog), and even that requires a verified snapshot and a known
    outcome.
    """

    NONE = "none"
    VERIFY_AND_CLEAR = "verify_and_clear"
    RESTORE_AVAILABLE = "restore_available"
    AUTO_RESTORE_PERMITTED = "auto_restore_permitted"
    OPERATOR_DECISION_REQUIRED = "operator_decision_required"


class ConflictDomain(str, Enum):
    """A higher-level inverter resource that two transactions can contend
    for **even when their register sets are disjoint**.

    Register ownership alone is not sufficient for ECCO, and the live
    firmware already proves it. A register 244 transaction writes only
    register {244}. A manual TOU slot write touches 232 / 250-261 /
    268-279. Those sets do not intersect - yet the production firmware
    deliberately refuses a TOU write while a register 244 snapshot is
    pending, because register 244 determines whether TOU Power (256-261)
    means an export cap or a battery discharge cap. The registers do not
    collide; the *meaning* does.

    A model that arbitrates on registers alone would therefore permit a
    combination the live, hardware-proven safety design intentionally
    rejects. These domains exist to close exactly that gap, and nothing
    else - they are NOT a second place to list registers. A transaction
    declares the registers it writes AND the domains whose semantics it
    affects or depends upon.

    Kept deliberately coarse. Every domain below corresponds to a
    distinction the current firmware actually enforces; none was invented
    to look complete.
    """

    #: The inverter's own real-time clock. Registers 22-24. Shares no
    #: semantics with the power path - which is why an RTC correction may
    #: proceed while a Free Power or register 244 lease is outstanding,
    #: provided nothing is mid-flight on the bus.
    INVERTER_CLOCK = "inverter_clock"

    #: The six-slot time-of-use schedule: its times, powers, target SOCs
    #: and charge-source/mode flags, and anything that changes what those
    #: fields mean.
    TOU_SCHEDULE = "tou_schedule"

    #: Grid-charge enablement and rate (registers 230, 232 bit 0).
    GRID_CHARGE = "grid_charge"

    #: The inverter's overall export / battery-discharge operating policy.
    #: Register 244 today; the proposed coordinated 244+245 Battery Export
    #: control in future. Declared ALONGSIDE `TOU_SCHEDULE` by any
    #: transaction that changes this policy, because changing it changes
    #: how the TOU power fields behave.
    INVERTER_POWER_POLICY = "inverter_power_policy"


class TransactionState(str, Enum):
    IDLE = "idle"
    SNAPSHOTTING = "snapshotting"
    STAGED = "staged"
    ARMED = "armed"
    WRITING = "writing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    RESTORING = "restoring"
    FAILED = "failed"
    RESTORE_FAILED = "restore_failed"


# The legal-transition table from docs/SAFE_WRITE_TRANSACTION_ARCHITECTURE.md.
# Keys are (from_state, event); values are the resulting state.
_TRANSITIONS: dict[tuple[TransactionState, str], TransactionState] = {
    (TransactionState.IDLE, "begin"): TransactionState.SNAPSHOTTING,
    (TransactionState.SNAPSHOTTING, "snapshot_ok"): TransactionState.STAGED,
    (TransactionState.SNAPSHOTTING, "snapshot_failed"): TransactionState.FAILED,
    (TransactionState.STAGED, "arm"): TransactionState.ARMED,
    (TransactionState.STAGED, "expire_or_cancel"): TransactionState.IDLE,
    (TransactionState.ARMED, "write_begin"): TransactionState.WRITING,
    (TransactionState.ARMED, "arm_expired"): TransactionState.STAGED,
    (TransactionState.WRITING, "writes_accepted"): TransactionState.VERIFYING,
    (TransactionState.WRITING, "write_failed"): TransactionState.FAILED,
    (TransactionState.VERIFYING, "verified"): TransactionState.COMPLETED,
    (TransactionState.VERIFYING, "verify_mismatch"): TransactionState.FAILED,
    (TransactionState.COMPLETED, "restore_requested"): TransactionState.RESTORING,
    (TransactionState.COMPLETED, "no_restore_needed"): TransactionState.IDLE,
    (TransactionState.FAILED, "restore_attempt"): TransactionState.RESTORING,
    (TransactionState.FAILED, "no_snapshot_or_not_applicable"): TransactionState.IDLE,
    (TransactionState.RESTORING, "restore_verified"): TransactionState.IDLE,
    (TransactionState.RESTORING, "restore_failed"): TransactionState.RESTORE_FAILED,
    (TransactionState.RESTORE_FAILED, "restore_attempt"): TransactionState.RESTORING,
}

# States other than these are considered "mid-transaction" for the
# restart-safety invariant: a restart while in one of these must never
# silently resume - see Transaction.mid_transaction().
_TERMINAL_OR_SAFE_STATES = {
    TransactionState.IDLE,
    TransactionState.COMPLETED,
    TransactionState.RESTORE_FAILED,
}


class IllegalTransition(Exception):
    """Raised when an event is not legal from the current state."""


class TransactionError(Exception):
    """Raised for invariant violations that are not simple illegal
    transitions (stale snapshot, missing arm, concurrent transaction)."""


class OwnershipConflict(TransactionError):
    """Raised when a transaction would touch registers that another
    transaction owns, or that an unreleased obligation still covers."""


@dataclass(frozen=True)
class TransactionPolicy:
    """The guards a transaction enforces, made explicit rather than implied.

    `legacy()` reproduces the 2026-09-20 model exactly, so
    registry/tests/test_transaction_state_machine.py continues to pin the
    original contract unchanged. `strict()` is what the audit recommends
    any real executor be built against.
    """

    require_durable_snapshot_before_write: bool = True
    forbid_permanent_exit_for_temporary_override: bool = True
    max_restore_attempts: int | None = 3
    #: A strict transaction must say which semantic domains it touches.
    #: Silence is not "no semantic conflict" - it is an undeclared claim,
    #: and an undeclared claim fails closed (see `blocking_obligation`).
    require_declared_conflict_domains: bool = True

    @classmethod
    def legacy(cls) -> "TransactionPolicy":
        return cls(
            require_durable_snapshot_before_write=False,
            forbid_permanent_exit_for_temporary_override=False,
            max_restore_attempts=None,
            require_declared_conflict_domains=False,
        )

    @classmethod
    def strict(cls) -> "TransactionPolicy":
        return cls()


@dataclass
class Snapshot:
    taken_at: float
    registers: dict[int, int]
    max_age_seconds: float = 30.0
    # Whether this snapshot has reached non-volatile storage. A snapshot
    # that exists only in RAM is worthless to the restart that needs it,
    # which is precisely the window the live firmware covers with its
    # "persist, then wait for the flash flush interval, THEN write"
    # ordering. Modelled explicitly so a test can cut power inside that
    # window - see registry/tests/test_transaction_engine_semantics.py.
    durable: bool = False

    def is_stale(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.taken_at) > self.max_age_seconds

    def mark_durable(self) -> None:
        self.durable = True


@dataclass
class ArmToken:
    armed_at: float
    expires_after_seconds: float = 20.0

    def is_expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.armed_at) > self.expires_after_seconds


@dataclass
class Transaction:
    """One capability's in-flight (or completed) write transaction.

    A real implementation would have exactly one of these active at a
    time per physical inverter connection - see TransactionRegistry for
    the concurrency guard that enforces that.
    """

    capability_id: str
    state: TransactionState = TransactionState.IDLE
    snapshot: Snapshot | None = None
    arm_token: ArmToken | None = None
    staged_value: object = None
    last_error: str | None = None
    history: list[str] = field(default_factory=list)

    # --- 2026-09-21 audit additions (all defaulted, all additive) -------
    kind: TransactionKind = TransactionKind.PERMANENT
    # The exact set of Modbus holding registers this transaction is
    # permitted to WRITE and restore. Ownership is over REGISTERS, not
    # capability names: two differently-named capabilities that share
    # register 232 are not independent, and a model keyed on names alone
    # cannot say so.
    #
    # `None` means UNDECLARED, which is not the same as "writes nothing"
    # (an explicit empty frozenset). Undeclared fails closed.
    #
    # Do NOT list registers here that the transaction never writes just to
    # express a semantic dependency - that is what `conflict_domains` is
    # for, and overloading this set would corrupt both restore scoping and
    # recovery.
    owned_registers: frozenset[int] | None = frozenset()
    # Higher-level resources whose semantics this transaction affects or
    # depends on, which can collide even when register sets are disjoint.
    # `None` means UNDECLARED and fails closed; an explicit empty
    # frozenset means "declares no semantic domain".
    conflict_domains: frozenset[ConflictDomain] | None = frozenset()
    outcome: WriteOutcome = WriteOutcome.UNATTEMPTED
    # The value ECCO last wrote AND verified, per register. Meaningful
    # only while `outcome is CONFIRMED`; any other outcome must leave this
    # empty so a drift guard cannot invent a comparison.
    last_applied: dict[int, int] = field(default_factory=dict)
    restore_attempts: int = 0
    policy: TransactionPolicy = field(default_factory=TransactionPolicy.legacy)

    def _transition(self, event: str) -> None:
        key = (self.state, event)
        if key not in _TRANSITIONS:
            raise IllegalTransition(
                f"'{event}' is not legal from state '{self.state.value}' "
                f"(capability={self.capability_id})"
            )
        new_state = _TRANSITIONS[key]
        self.history.append(f"{self.state.value} --{event}--> {new_state.value}")
        self.state = new_state

    # --- lifecycle steps -------------------------------------------------

    def begin(self) -> None:
        self._transition("begin")

    def snapshot_ok(self, registers: dict[int, int], now: float | None = None) -> None:
        self.snapshot = Snapshot(taken_at=time.time() if now is None else now, registers=dict(registers))
        self._transition("snapshot_ok")

    def snapshot_failed(self, error: str) -> None:
        self.last_error = error
        self._transition("snapshot_failed")

    def stage(self, value: object) -> None:
        # Staging itself does not change state past `staged` - this
        # method exists to record the value while in STAGED, and is a
        # no-op on state if already staged (re-staging before arming is
        # allowed, matching "UI staging must not write immediately").
        if self.state is not TransactionState.STAGED:
            raise TransactionError(
                f"Cannot stage a value outside the 'staged' state (capability={self.capability_id}, state={self.state.value})"
            )
        self.staged_value = value

    def arm(self, now: float | None = None) -> None:
        if self.snapshot is None:
            raise TransactionError(f"Cannot arm without a snapshot (capability={self.capability_id})")
        if self.snapshot.is_stale(now):
            raise TransactionError(
                f"Cannot arm against a stale snapshot (capability={self.capability_id}); re-snapshot first"
            )
        self.arm_token = ArmToken(armed_at=time.time() if now is None else now)
        self._transition("arm")

    def expire_or_cancel_staging(self) -> None:
        self.arm_token = None
        self._transition("expire_or_cancel")

    def begin_write(self, now: float | None = None) -> None:
        if self.arm_token is None:
            raise TransactionError(f"Cannot write without an arm token (capability={self.capability_id})")
        if self.arm_token.is_expired(now):
            # Expiry is itself a legal, distinct transition - the caller
            # is expected to check/handle this rather than treat it as
            # an exotic error; still raise so a caller that ignores the
            # return value cannot accidentally proceed to write.
            self._transition("arm_expired")
            raise TransactionError(
                f"Arm token expired before write began (capability={self.capability_id}); now in 'staged'"
            )
        if self.policy.require_durable_snapshot_before_write and not (
            self.snapshot is not None and self.snapshot.durable
        ):
            # Refusing here, rather than after the write, is the whole
            # point: a snapshot that has not reached flash cannot help the
            # restart that a mid-write power cut is about to cause.
            raise TransactionError(
                f"Cannot write before the snapshot is durable (capability={self.capability_id})"
            )
        # From this instant until an exact reread says otherwise, ECCO does
        # not know what value the inverter holds. Recording that BEFORE the
        # write - not after a failure is detected - is what makes a power
        # cut mid-write recoverable, and is exactly what the live register
        # 244 implementation does with reg244_last_applied_valid.
        self.outcome = WriteOutcome.UNCERTAIN
        self.last_applied = {}
        self._transition("write_begin")

    def writes_accepted(self) -> None:
        self._transition("writes_accepted")

    def write_failed(self, error: str) -> None:
        self.last_error = error
        self.arm_token = None
        # Deliberately NOT reset to UNATTEMPTED. A Modbus error or timeout
        # does not prove the inverter rejected the write.
        self.outcome = WriteOutcome.UNCERTAIN
        self._transition("write_failed")

    def verified(self, applied: dict[int, int] | None = None) -> None:
        self._transition("verified")
        self.outcome = WriteOutcome.CONFIRMED
        self.last_applied = dict(applied or {})

    def verify_mismatch(self, error: str) -> None:
        self.last_error = error
        self.arm_token = None
        # A mismatch tells us the live value is not what we asked for, but
        # not who put it there or whether our write landed at all.
        self.outcome = WriteOutcome.UNCERTAIN
        self.last_applied = {}
        self._transition("verify_mismatch")

    def restore_requested(self) -> None:
        cap = self.policy.max_restore_attempts
        if cap is not None and self.restore_attempts >= cap:
            raise TransactionError(
                f"Restore attempt limit ({cap}) reached (capability={self.capability_id}); "
                f"operator decision required"
            )
        self.restore_attempts += 1
        self.outcome = WriteOutcome.UNCERTAIN
        self.last_applied = {}
        self._transition("restore_requested")

    def no_restore_needed(self) -> None:
        if (
            self.policy.forbid_permanent_exit_for_temporary_override
            and self.kind is TransactionKind.TEMPORARY_OVERRIDE
        ):
            raise TransactionError(
                f"A temporary override cannot exit via 'no restore needed' "
                f"(capability={self.capability_id}); it owes an exact restore"
            )
        self._transition("no_restore_needed")

    def restore_attempt(self) -> None:
        if self.snapshot is None:
            raise TransactionError(
                f"Cannot attempt restore with no snapshot recorded (capability={self.capability_id})"
            )
        cap = self.policy.max_restore_attempts
        if cap is not None and self.restore_attempts >= cap:
            # An unbounded automatic retry is itself a hazard: it keeps
            # writing to the inverter forever on a condition that a human
            # has not seen. Exhaustion stops the machine, it does not
            # pretend the restore succeeded.
            raise TransactionError(
                f"Restore attempt limit ({cap}) reached (capability={self.capability_id}); "
                f"operator decision required"
            )
        self.restore_attempts += 1
        self.outcome = WriteOutcome.UNCERTAIN
        self.last_applied = {}
        # Legal from either FAILED or RESTORE_FAILED - both are encoded
        # in _TRANSITIONS, so a single dict-backed _transition() call
        # already dispatches correctly and rejects anywhere else.
        self._transition("restore_attempt")

    def no_snapshot_or_not_applicable(self) -> None:
        self._transition("no_snapshot_or_not_applicable")

    def restore_verified(self) -> None:
        self._transition("restore_verified")
        self.outcome = WriteOutcome.CONFIRMED
        self.last_applied = dict(self.snapshot.registers) if self.snapshot else {}

    def restore_failed(self, error: str) -> None:
        self.last_error = error
        self._transition("restore_failed")

    # --- invariant helpers -------------------------------------------

    def mid_transaction(self) -> bool:
        """True if a restart right now would need to NOT silently
        resume - i.e. the state is anything other than idle/completed/
        restore_failed."""
        return self.state not in _TERMINAL_OR_SAFE_STATES

    def is_armed_and_fresh(self, now: float | None = None) -> bool:
        return (
            self.state is TransactionState.ARMED
            and self.arm_token is not None
            and not self.arm_token.is_expired(now)
        )

    def owes_restore(self) -> bool:
        """True while this transaction still holds a lease over its registers.

        A temporary override owes a restore from the moment it has a
        durable snapshot until that snapshot has been verifiably written
        back. A permanent change never owes one - its snapshot is a
        rollback aid, not a lease.
        """
        if self.kind is not TransactionKind.TEMPORARY_OVERRIDE:
            return False
        if self.snapshot is None or not self.snapshot.durable:
            return False
        return self.state is not TransactionState.IDLE

    def drift_guard_available(self) -> bool:
        """Whether a 'did anything else change this register?' check is
        meaningful right now.

        Only when ECCO has a CONFIRMED record of what it last wrote. When
        the last outcome was uncertain there is nothing honest to compare
        against, and inventing a comparison is worse than admitting the
        gap - the live register 244 restore path takes exactly this
        position.
        """
        return self.outcome is WriteOutcome.CONFIRMED and bool(self.last_applied)

    def detect_drift(self, live: dict[int, int]) -> dict[int, tuple[int, int]]:
        """Registers where the live value differs from ECCO's last verified write.

        Returns {address: (expected, actual)}. Empty when no drift, and
        empty when no drift guard is available - callers must consult
        `drift_guard_available()` to tell those two apart.
        """
        if not self.drift_guard_available():
            return {}
        return {
            addr: (expected, live[addr])
            for addr, expected in self.last_applied.items()
            if addr in live and live[addr] != expected
        }


class TransactionRegistry:
    """Enforces 'cannot have two simultaneous write transactions' across
    every capability sharing one physical inverter connection."""

    def __init__(self) -> None:
        self._active: Transaction | None = None
        # Completed temporary overrides that still owe a restore. These
        # outlive the transaction's own in-flight state and, in a real
        # executor, outlive a reboot.
        self._obligations: list[Transaction] = []

    def start(self, capability_id: str) -> Transaction:
        """Legacy entry point - one transaction at a time, keyed on name only."""
        return self.start_transaction(capability_id)

    def start_transaction(
        self,
        capability_id: str,
        *,
        kind: TransactionKind = TransactionKind.PERMANENT,
        registers: frozenset[int] | set[int] | None = None,
        domains: frozenset[ConflictDomain] | set[ConflictDomain] | None = None,
        policy: TransactionPolicy | None = None,
    ) -> Transaction:
        # THREE separate rules. The original model had one boolean for all
        # of them, and a register-only model would still miss the third:
        #
        #   A. Bus exclusivity - only one transaction may be mid-flight,
        #      because there is one RS485 channel. A short critical
        #      section measured in seconds.
        #
        #   B. Register ownership - the exact registers a transaction
        #      writes and restores. Long-lived for a lease, and it must
        #      NOT block work on disjoint registers: an outstanding Free
        #      Power lease over 230/232/268-279 has no business blocking
        #      an RTC write to 22-24.
        #
        #   C. Semantic conflict domains - resources that collide even
        #      when register sets do not. Register 244 writes only {244},
        #      a TOU slot write touches none of it, and yet the live
        #      firmware refuses the TOU write while a 244 snapshot is
        #      pending, because 244 decides what TOU Power MEANS.
        #      Arbitrating on registers alone would permit exactly the
        #      combination the hardware-proven design rejects.
        #
        # Collapsing any two of these produces either false blocks or
        # missing blocks. They are enforced separately here.
        effective_policy = policy or (
            TransactionPolicy.legacy() if registers is None else TransactionPolicy.strict()
        )

        if effective_policy.require_declared_conflict_domains and domains is None:
            # Fail closed at declaration time. Silence must not be
            # readable as "this transaction has no semantic conflicts" -
            # that is the assumption this whole section exists to remove.
            raise TransactionError(
                f"Cannot start a strict transaction for '{capability_id}' without a "
                f"declared conflict-domain set. Pass an explicit frozenset (which may "
                f"be empty to declare no semantic domain); omitting it is an undeclared "
                f"claim, not an empty one."
            )

        declared_domains = None if domains is None else frozenset(domains)
        if declared_domains is not None:
            unknown = [d for d in declared_domains if not isinstance(d, ConflictDomain)]
            if unknown:
                # An unrecognised resource name must never silently behave
                # as "no conflict". Domains are a closed enum precisely so
                # a typo cannot become a permission.
                raise TransactionError(
                    f"Unknown conflict domain(s) {unknown!r} for '{capability_id}'; "
                    f"declare members of ConflictDomain only"
                )

        # Rule A.
        if self._active is not None and self._active.mid_transaction():
            raise TransactionError(
                f"Cannot start a transaction for '{capability_id}': "
                f"'{self._active.capability_id}' is already active in state "
                f"'{self._active.state.value}'"
            )

        owned = None if registers is None else frozenset(registers)

        # Rules B and C, evaluated together against every outstanding lease.
        blocker, reason = self.blocking_obligation(owned, declared_domains, explain=True)
        if blocker is not None:
            # This is the generalisation of the firmware's ad hoc
            # "REJECTED - Register 244 proof transaction awaiting
            # restoration" and "REJECTED - Free Power override/recovery
            # owns TOU settings" gates. Stated once, it applies in every
            # direction automatically instead of needing a hand-written
            # reciprocal check per feature pair.
            raise OwnershipConflict(
                f"Cannot start a transaction for '{capability_id}': "
                f"'{blocker.capability_id}' still owes a restore - {reason}"
            )

        txn = Transaction(
            capability_id=capability_id,
            kind=kind,
            owned_registers=owned,
            conflict_domains=declared_domains,
            policy=effective_policy,
        )
        txn.begin()
        self._active = txn
        if kind is TransactionKind.TEMPORARY_OVERRIDE:
            self._obligations.append(txn)
        return txn

    @property
    def active(self) -> Transaction | None:
        if self._active is not None and self._active.state is TransactionState.IDLE:
            return None
        return self._active

    def outstanding_obligations(self) -> list[Transaction]:
        """Temporary overrides that still hold a lease over their registers."""
        self._obligations = [t for t in self._obligations if t.owes_restore()]
        return list(self._obligations)

    @staticmethod
    def _conflict_reason(
        lease: Transaction,
        registers: frozenset[int] | None,
        domains: frozenset[ConflictDomain] | None,
    ) -> str | None:
        """Why `lease` conflicts with the given claim, or None if it does not.

        UNDECLARED (`None`) on either dimension conflicts with every lease.
        That is NOT the same as an explicitly empty set, which declares
        "this transaction touches nothing on that dimension" and therefore
        cannot collide on it. Conflating "unknown" with "none" is the same
        class of error as treating an unacknowledged write as a failed one.
        """
        if registers is None:
            return "the requested transaction did not declare which registers it writes"
        if domains is None:
            return "the requested transaction did not declare its conflict domains"

        overlap_registers = (lease.owned_registers or frozenset()) & registers
        if overlap_registers:
            return f"register overlap on {sorted(overlap_registers)}"

        overlap_domains = (lease.conflict_domains or frozenset()) & domains
        if overlap_domains:
            return (
                "semantic conflict on "
                f"{sorted(d.value for d in overlap_domains)} "
                "(register sets are disjoint, but the meaning collides)"
            )
        return None

    def blocking_obligation(
        self,
        registers: frozenset[int] | set[int] | None,
        domains: frozenset[ConflictDomain] | set[ConflictDomain] | None = None,
        *,
        explain: bool = False,
    ):
        """The outstanding obligation, if any, that conflicts with this claim.

        Checks BOTH dimensions: literal register overlap, and semantic
        conflict-domain overlap. A claim is blocked if either collides -
        which is what makes an outstanding register 244 lease block a
        manual TOU write whose registers it does not touch.

        Returns the blocking transaction, or `(transaction, reason)` when
        `explain=True`.
        """
        wanted_registers = None if registers is None else frozenset(registers)
        wanted_domains = None if domains is None else frozenset(domains)
        for txn in self.outstanding_obligations():
            reason = self._conflict_reason(txn, wanted_registers, wanted_domains)
            if reason is not None:
                return (txn, reason) if explain else txn
        return (None, "") if explain else None

    def obligation_conflicts(self) -> list[tuple[Transaction, Transaction, str]]:
        """Pairs of outstanding obligations that are mutually incompatible.

        In normal operation this is ALWAYS empty: `start_transaction`
        refuses to create a second lease that conflicts with an existing
        one, so two incompatible obligations cannot both be acquired.

        It is non-empty only if persisted state was corrupted, hand-edited,
        reconstructed by an older firmware version, or rehydrated from a
        source that did not enforce the rule. That is precisely when the
        engine must NOT quietly pick one and restore it - see
        `restore_path_for`.
        """
        out: list[tuple[Transaction, Transaction, str]] = []
        obligations = self.outstanding_obligations()
        for i, a in enumerate(obligations):
            for b in obligations[i + 1 :]:
                reason = self._conflict_reason(a, b.owned_registers, b.conflict_domains)
                if reason is not None:
                    out.append((a, b, reason))
        return out

    def restore_path_for(self, capability_id: str) -> Transaction | None:
        """The outstanding obligation a restore action would act on.

        Deliberately NOT filtered against other leases' claims. A restore
        is the one action that must stay reachable when normal writes are
        blocked - blocking the only path back to the original state is how
        a system ends up stuck in an override it cannot leave. An
        outstanding lease must never be able to close another owner's exit.

        The single exception is the state that should be impossible: if two
        outstanding obligations are mutually incompatible, the persisted
        picture is self-contradictory, and restoring either one could
        overwrite the other's registers or fight its semantics. There is no
        safe automatic choice, so this fails closed and hands the decision
        to an operator rather than guessing.
        """
        conflicts = self.obligation_conflicts()
        if conflicts:
            a, b, reason = conflicts[0]
            raise OwnershipConflict(
                f"Refusing to select a restore path for '{capability_id}': outstanding "
                f"obligations '{a.capability_id}' and '{b.capability_id}' are mutually "
                f"incompatible ({reason}). This should be unreachable in normal "
                f"operation and indicates corrupted or externally reconstructed "
                f"persisted state - operator decision required."
            )
        for txn in self.outstanding_obligations():
            if txn.capability_id == capability_id:
                return txn
        return None


# ---------------------------------------------------------------------------
# ECCO's actual conflict declarations
# ---------------------------------------------------------------------------
#
# Reference data, not executable configuration. Nothing in this repository
# reads this table to perform a write; it exists so the declarations the
# live firmware enforces by hand are written down in one auditable place,
# and so the model can be checked against them.
#
# Each entry is (owned_registers, conflict_domains). `owned_registers` is
# what the transaction WRITES - never what it merely depends on.

ECCO_CONFLICT_DECLARATIONS: dict[str, tuple[frozenset[int], frozenset[ConflictDomain]]] = {
    # RTC correction. Shares nothing with the power path, which is why an
    # RTC write may proceed while a power-path lease is outstanding - once
    # F1 (its missing bus arbitration) is fixed.
    "rtc_clock": (frozenset({22, 23, 24}), frozenset({ConflictDomain.INVERTER_CLOCK})),
    # One manual TOU slot. Writes register 232 (grid-charge enable bit)
    # plus its own slot's time/power/SOC/flags.
    "tou_slot_1": (
        frozenset({232, 250, 251, 256, 268, 274}),
        frozenset({ConflictDomain.TOU_SCHEDULE, ConflictDomain.GRID_CHARGE}),
    ),
    # Free Power: grid-charge rate and enable, all six slots' TOU Power
    # (2026-09-23: promoted from witnessed-only to owned - post-reboot live
    # characterisation proved TOU Power is the inverter's native battery
    # charge/discharge ceiling, so Free Power now overlays all six slots
    # with the requested/effective wattage rather than merely witnessing
    # them - see CURRENT_STATE.md and firmware/include/ecco_durable_snapshot.h),
    # and all six slots' SOC and source/mode flags.
    "free_power_transaction": (
        frozenset({230, 232}) | frozenset(range(256, 262)) | frozenset(range(268, 280)),
        frozenset({ConflictDomain.TOU_SCHEDULE, ConflictDomain.GRID_CHARGE}),
    ),
    # Register 244 Load/Export Mode. Writes ONE register, and declares
    # TOU_SCHEDULE anyway - not because it writes any TOU register, but
    # because it decides whether TOU Power (256-261) means an export cap or
    # a battery discharge cap. This single line is what makes the model
    # reproduce the live firmware's "REJECTED - Register 244 proof
    # transaction awaiting restoration" gate.
    "grid_export_policy": (
        frozenset({244}),
        frozenset({ConflictDomain.INVERTER_POWER_POLICY, ConflictDomain.TOU_SCHEDULE}),
    ),
    # Manual Dump-to-Grid V1 (2026-09-26) - IMPLEMENTED, offline-validated,
    # NOT yet live-proven. See docs/DUMP_TO_GRID_V1.md.
    #
    # This supersedes the earlier `battery_export_NOT_IMPLEMENTED`
    # shape-only placeholder (which declared {244, 245}). Register 245
    # turned out NOT to be needed: it remains exactly what
    # docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md left it - read-only,
    # unmeasured scaling, `write_policy: R0` - and V1 deliberately does not
    # add a write path for it. Dump-to-Grid instead
    # owns registers {244, 256, 257, 258, 259, 260, 261}: 244 (Load/Export
    # Mode) is flipped to Allow Export for the lease's duration, and
    # 256-261 (TOU Power) are overlaid to the requested export wattage on
    # all six slots, exactly like Free Power's own 256-261 overlay but for
    # the opposite (discharge/export) direction. Registers 268-279 (the
    # six per-slot charge-target SOC / charge-source-and-mode fields) are
    # deliberately NOT owned - see docs/DUMP_TO_GRID_V1.md "Why 268-279 is
    # untouched" for the register-model evidence. Stop SOC is a pure-
    # software floor enforced against the existing trusted battery SOC
    # sensor and is never written to any inverter register, so it has no
    # register representation here either.
    #
    # Declares both INVERTER_POWER_POLICY (244 is a policy register) and
    # TOU_SCHEDULE (256-261 collide with the six TOU slot writers and with
    # Free Power's own 256-261 overlay) for the same reason
    # `grid_export_policy` and `free_power_transaction` already declare
    # them - this is what makes the model reproduce the live firmware's
    # mutual-exclusion gates in both directions (see
    # firmware/ecco_clock_dongle_stage3_4_free_power.yaml's
    # start_dump_to_grid_override / start_free_power_override /
    # apply_reg244_settings / restore_reg244_snapshot / apply_manual_slotN
    # preconditions, all of which now cross-check Dump's
    # dump_active_persisted / dump_snapshot_valid flags).
    "dump_to_grid_transaction": (
        frozenset({244}) | frozenset(range(256, 262)),
        frozenset({ConflictDomain.INVERTER_POWER_POLICY, ConflictDomain.TOU_SCHEDULE}),
    ),
}


# ---------------------------------------------------------------------------
# Restart / power-loss recovery
# ---------------------------------------------------------------------------
#
# Everything above models a transaction that is still in memory. This
# section models the only thing that actually survives a power cut: the
# bytes that reached flash. A restart cannot consult `Transaction.state`
# - that object is gone - so recovery must be a pure function of the
# persisted record, and it must be total: every reachable combination of
# persisted fields has to map to exactly one safe offer.


@dataclass(frozen=True)
class PersistedTransactionState:
    """Exactly what a real executor would keep in non-volatile storage.

    Nothing volatile belongs here. In particular there is no `state`
    field: the in-memory lifecycle state is NOT recoverable and must not
    be reconstructed by guesswork - what is recoverable is the snapshot,
    whether it was durable, and what is known about the last write.
    """

    capability_id: str
    kind: TransactionKind
    owned_registers: frozenset[int] = frozenset()
    snapshot: dict[int, int] | None = None
    snapshot_durable: bool = False
    outcome: WriteOutcome = WriteOutcome.UNATTEMPTED
    last_applied: dict[int, int] = field(default_factory=dict)
    restore_deadline: float | None = None
    restore_attempts: int = 0
    max_restore_attempts: int | None = 3


@dataclass(frozen=True)
class RecoveryAssessment:
    action: RecoveryAction
    reason: str
    drift_guard_available: bool
    #: Registers whose current hardware value ECCO cannot vouch for.
    unknown_registers: frozenset[int] = frozenset()


def classify_recovery(
    persisted: PersistedTransactionState, now: float | None = None
) -> RecoveryAssessment:
    """Map a persisted record to the one safe action a restart may offer.

    This function never writes and never decides to write. It answers
    "what does ECCO actually know, and what is the most that may be
    offered on that basis" - the distinction the firmware's own
    "RECOVERY REQUIRED - saved snapshot found" boot message makes, made
    total and testable.
    """
    now = time.time() if now is None else now
    guard = persisted.outcome is WriteOutcome.CONFIRMED and bool(persisted.last_applied)

    # A snapshot that never reached flash is not a snapshot. If a write
    # had already been issued, the original values are simply gone and
    # only a human can decide what the correct state is.
    if persisted.snapshot is None or not persisted.snapshot_durable:
        if persisted.outcome is WriteOutcome.UNATTEMPTED:
            return RecoveryAssessment(
                RecoveryAction.NONE,
                "no durable snapshot and no write was ever issued - nothing was at risk",
                guard,
            )
        return RecoveryAssessment(
            RecoveryAction.OPERATOR_DECISION_REQUIRED,
            "a write may have been issued but no durable snapshot exists - "
            "ECCO cannot know the original values",
            guard,
            persisted.owned_registers,
        )

    # Retry exhaustion outranks everything below it. Continuing to write
    # to the inverter on a condition no human has seen is the hazard the
    # cap exists to stop.
    cap = persisted.max_restore_attempts
    if cap is not None and persisted.restore_attempts >= cap:
        return RecoveryAssessment(
            RecoveryAction.OPERATOR_DECISION_REQUIRED,
            f"restore has already been attempted {persisted.restore_attempts} time(s) "
            f"without success - automatic retry is exhausted",
            guard,
            persisted.owned_registers,
        )

    if persisted.outcome is WriteOutcome.UNATTEMPTED:
        # The snapshot is durable but nothing was written. The hardware
        # should still hold the snapshot values - but ECCO was not
        # watching while it was off, so it must confirm rather than
        # assume, and must not blind-write over a third party's change.
        return RecoveryAssessment(
            RecoveryAction.VERIFY_AND_CLEAR,
            "durable snapshot exists and no write was issued - reread and, if the live "
            "values still match the snapshot, clear it without writing",
            guard,
        )

    if persisted.outcome is WriteOutcome.UNCERTAIN:
        # The single most important case, and the one the original model
        # could not express: the inverter may or may not hold ECCO's
        # value. A restore is legitimate, but it must be preceded by a
        # fresh read and must NOT pretend a drift guard is meaningful.
        return RecoveryAssessment(
            RecoveryAction.OPERATOR_DECISION_REQUIRED,
            "the last write's outcome is unknown - the inverter may or may not have "
            "accepted it; restore is available but only on a deliberate, armed action "
            "after a fresh read, with no drift comparison invented",
            guard,
            persisted.owned_registers,
        )

    # outcome is CONFIRMED from here: ECCO knows what it wrote.
    if persisted.kind is TransactionKind.PERMANENT:
        return RecoveryAssessment(
            RecoveryAction.RESTORE_AVAILABLE,
            "a permanent change completed and was verified - the snapshot is retained "
            "for inspection but nothing is owed",
            guard,
        )

    # A verified temporary override: the lease is real and outlives the reboot.
    if persisted.restore_deadline is not None and now >= persisted.restore_deadline:
        return RecoveryAssessment(
            RecoveryAction.AUTO_RESTORE_PERMITTED,
            "a verified temporary override is past its restore deadline - an unattended "
            "watchdog may drive the exact restore",
            guard,
        )
    return RecoveryAssessment(
        RecoveryAction.RESTORE_AVAILABLE,
        "a verified temporary override is still within its lease - restore on request, "
        "or automatically once the deadline passes",
        guard,
    )


# ---------------------------------------------------------------------------
# 2026-09-22 recovery-classifier v2 (repo-only design/test artifact)
# ---------------------------------------------------------------------------
#
# Nothing below performs Modbus, network, Home Assistant, or file I/O, and
# nothing below is imported by anything that does. It is a proposal for the
# durable record a FUTURE executor would keep, and a total function from
# "what did boot observe" to "what may safely be offered" - the same shape
# as `classify_recovery()` above, extended with the inputs that function
# does not yet take (a durable MARKER separate from the data record, an
# explicit record-load-failure state, a live register read that may itself
# be unavailable, and wall-clock validity across a reboot).
#
# Two design rules apply to everything in this section:
#
#   1. Hardware truth always wins over intended command history. Nothing
#      here ever prefers "what ECCO meant to write" over a fresh live read
#      when both are available.
#
#   2. Nothing here AUTHORISES a write. Every function returns a
#      classification, a pure derived decision, or - for the operator
#      resolution model - a refusal or a marker transition / audit intent a
#      real executor would still have to persist. The single place that
#      distinguishes "may an UNATTENDED watchdog act on this" from "must
#      reach a human" is `authorizes_unattended_restore()`, so that answer
#      exists in exactly one place rather than being re-derived ad hoc by
#      every caller.


class SafeDirection(str, Enum):
    """Whether a capability has an independently established safe
    UNATTENDED restore direction - deliberately separate from
    `ECCO_CONFLICT_DECLARATIONS`, which only knows registers and semantic
    domains and says nothing about what is safe to do with them.

    RESTORE - an unattended watchdog may drive the exact restore once the
    classifier below reaches a RESTORE_DUE result. The live precedent is
    Free Power's existing 15s watchdog: it already restores without a
    human once its lease is verified and past deadline.

    NONE - the classifier may still tell you WHAT state the system is in,
    but nothing may act on that classification without a human. This is
    the default for anything that does not have an existing, hardware-
    proven unattended restore path - which, as of this writing, is
    everything except Free Power. In particular register 244's restore is
    real and live-proven, but it is driven by an operator button press
    today, not an unattended watchdog, so it is declared NONE here: this
    declaration is about UNATTENDED authority specifically, not about
    "does a restore path exist at all".

    A snapshot merely existing is NOT sufficient evidence of RESTORE - see
    ECCO_RECOVERY_DECLARATIONS below, which requires each capability to
    say so explicitly.
    """

    RESTORE = "restore"
    NONE = "none"


# Each entry is a value judgement, not something derivable from
# `ECCO_CONFLICT_DECLARATIONS` (which describes ownership, not safety).
# Deliberately a SEPARATE mapping, per the design brief: the shape of
# ECCO_CONFLICT_DECLARATIONS (capability -> (registers, domains)) must not
# be disturbed by adding recovery policy to it.
ECCO_RECOVERY_DECLARATIONS: dict[str, SafeDirection] = {
    # The one live-proven unattended restore path: the 15s watchdog
    # already restores Free Power's snapshot without a human once a
    # verified lease is past its deadline.
    "free_power_transaction": SafeDirection.RESTORE,
    # Register 244's restore is real and live-proven, but operator-button
    # driven, not unattended - so UNATTENDED restore is NOT established.
    "grid_export_policy": SafeDirection.NONE,
    # A manual TOU slot is a deliberate operator setting; there is no
    # notion of "restoring" it unattended, ever.
    "tou_slot_1": SafeDirection.NONE,
    # The RTC has no restore concept at all - a "wrong" clock value is
    # corrected by the same write path, not rolled back to a prior one.
    "rtc_clock": SafeDirection.NONE,
    # Manual Dump-to-Grid V1 (2026-09-26) - the same unattended-restore
    # watchdog pattern as free_power_transaction above (15s interval,
    # comms-backoff-paced retry, fail-closed operator lockout after a
    # second consecutive verify mismatch). See docs/DUMP_TO_GRID_V1.md.
    "dump_to_grid_transaction": SafeDirection.RESTORE,
}


def capability_safe_direction(capability_id: str) -> SafeDirection | None:
    """The declared safe direction for `capability_id`, or `None` if it
    cannot be derived.

    `None` is a distinct, fail-closed answer from `SafeDirection.NONE`:
    it means the capability (or its conflict-domain declaration, which
    this deliberately keys off of instead of duplicating a second list of
    known capabilities) is not recognised at all, which must lock the
    classifier out rather than silently default to "no unattended
    restore, but otherwise classify normally".
    """
    if capability_id not in ECCO_CONFLICT_DECLARATIONS:
        return None
    return ECCO_RECOVERY_DECLARATIONS.get(capability_id, SafeDirection.NONE)


class RetryCause(str, Enum):
    """Why the last attempt (write, restore, or durable commit) did not
    reach a confirmed good state - see `retry_policy()`."""

    #: A Modbus/transport-level failure: timeout, no response, bus error.
    COMMS = "comms"
    #: A write was accepted and a reread was performed, but the reread did
    #: not match what was expected.
    VERIFY_MISMATCH = "verify_mismatch"
    #: The durable MARKER or its companion record is malformed, corrupt,
    #: missing when required, or of an unsupported schema.
    METADATA = "metadata"
    #: A write to non-volatile storage (the durable record/marker itself)
    #: did not confirm - as distinct from a Modbus write to the inverter.
    DURABLE_COMMIT = "durable_commit"


class MarkerState(str, Enum):
    """What boot resolved the durable MARKER to.

    Mirrors `ecco_durable::MarkerState` (see
    firmware/include/ecco_durable_snapshot.h and
    registry/tests/test_recovery_marker_state_machine.py) with one
    addition: MALFORMED. The firmware's own boot logic already computes
    exactly this reduction - a genuinely absent marker record resolves to
    CLEAR (the only route to CLEAR), a present record with a bad magic
    number or an unrecognised state value resolves to a fail-closed
    lockout, and only a present, well-formed record's own state is used
    directly. This enum is that already-reduced result, so the classifier
    below never has to parse raw bytes or re-derive "missing vs bad magic
    vs bad state" itself.
    """

    CLEAR = "clear"
    RESTORE_REQUIRED = "restore_required"
    #: ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR - the hardware
    #: restore already verified; only the durable clear-commit is owed.
    PENDING_CLEAR = "pending_clear"
    #: Bad magic, or a state value this classifier does not recognise.
    #: NEVER coerced to CLEAR (would drop a real obligation) or to
    #: RESTORE_REQUIRED (would restore using a shape that was never
    #: validated) - see registry/tests/test_recovery_marker_state_machine.py
    #: section [D4] for the firmware precedent this mirrors.
    MALFORMED = "malformed"


class RecordLoadFailure(str, Enum):
    """Why the companion OwnerRecord (the larger snapshot/intent record a
    RESTORE_REQUIRED or PENDING_CLEAR marker promises exists) could not be
    reconstructed - distinct from a malformed MARKER, which is the much
    smaller magic+state struct and is caught by `MarkerState.MALFORMED`
    before this is ever consulted.

    A well-formed marker whose companion record fails to load is exactly
    the "valid RESTORE_REQUIRED marker whose snapshot data failed to load
    at boot" gap the 2026-09-21 durability follow-up fixed in firmware
    with `*_recovery_metadata_corrupt` - fail-closed here for the same
    reason, not because this repo's firmware currently has this specific
    gap for this specific field (it does not - see the tests in
    registry/tests/test_recovery_marker_state_machine.py section [D]).
    """

    #: A marker promised a record but none was found at all.
    MISSING = "missing"
    #: A record was found but its bytes are too short or fail to parse.
    CORRUPT = "corrupt"


#: The only schema version this classifier understands. A record claiming
#: any other value is treated exactly like a corrupt one - see
#: `classify_recovery_v2`. Bumping this without also updating the
#: classifier is itself the failure this guards against, so it is a
#: module constant, not a magic number repeated at each call site.
CURRENT_OWNER_RECORD_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class OwnerRecord:
    """The durable record a FUTURE executor would keep for one capability's
    outstanding recovery obligation - the companion data a RESTORE_REQUIRED
    or PENDING_CLEAR `MarkerState` promises exists.

    Deliberately does NOT carry `owned_registers` or `conflict_domains`:
    those are already declared, once, in `ECCO_CONFLICT_DECLARATIONS`, and
    a durable record must not disagree with that table about what it owns.
    Instead `capability_id` is looked up (see `capability_safe_direction`
    and its use in `classify_recovery_v2`), and an unrecognised
    `capability_id` fails closed rather than being trusted at face value.

    No CRC field: the model treats "did the record load and parse" as
    binary (see `RecordLoadFailure`) and does not attempt to model partial
    bit-level corruption a CRC would catch - that belongs to whatever real
    storage layer eventually implements this, not to the model of what it
    should decide once loaded.
    """

    #: See `CURRENT_OWNER_RECORD_SCHEMA_VERSION`. A record with any other
    #: value is treated as unloadable - see `classify_recovery_v2`.
    schema_version: int = CURRENT_OWNER_RECORD_SCHEMA_VERSION
    #: The durable transaction/obligation generation. Its ONLY job is to
    #: let an operator resolution (see `resolve_operator_action`) prove it
    #: is confirming/auditing THIS obligation and not a stale one the
    #: operator saw on an earlier screen. It is NOT a Modbus request/
    #: response callback token (that is a transport-layer concern this
    #: model does not touch) and it is NOT incremented by retries - only
    #: by a genuinely new obligation superseding the last one.
    generation: int = 1
    capability_id: str = ""
    kind: TransactionKind = TransactionKind.TEMPORARY_OVERRIDE
    #: What the registers held before ECCO's transaction began.
    snapshot: dict[int, int] | None = None
    #: What ECCO's transaction was trying to make the registers hold.
    #: Meaningful even while `outcome` is UNCERTAIN - it is what a
    #: cautious "did it actually land?" comparison checks live state
    #: against, alongside `snapshot`.
    intended: dict[int, int] | None = None
    outcome: WriteOutcome = WriteOutcome.UNATTEMPTED
    #: What ECCO last verified was actually written, per register.
    #: Meaningful only while `outcome` is CONFIRMED - see
    #: `classify_recovery_v2`, which never compares against this while
    #: outcome is anything else.
    last_verified: dict[int, int] = field(default_factory=dict)
    restore_attempts: int = 0
    last_failure_cause: RetryCause | None = None
    #: Epoch seconds the current lease began, for `lease_should_end`'s
    #: "wall clock cannot have gone backwards past this" sanity check.
    lease_start_epoch: float | None = None
    #: Epoch seconds the lease is due, or `None` if this record has no
    #: absolute deadline (see `lease_should_end`'s uptime fallback).
    lease_end_epoch: float | None = None
    #: A hard cap on lease lifetime that does not depend on the wall
    #: clock being trustworthy - see `lease_should_end`.
    max_duration_s: float | None = None
    #: Set durably by an operator resolution (or an executor's own logic)
    #: to mean "end this lease now, regardless of the clock" - checked
    #: first by `lease_should_end`.
    restore_requested: bool = False
    #: 2026-09-24 (PR-A: register-244 active-lease context). The register
    #: 244 (Load/Export Mode) value this lease started under, captured
    #: fresh immediately before the first inverter write - `None` means no
    #: usable context (not yet captured, or invalid/corrupt), matching the
    #: fail-closed intent of firmware's plus-one encoding in
    #: `FreePowerSnapshotData.reg244_lease_context_plus1` (there:
    #: 0=unknown/invalid, 1..3=raw 244 value 0..2, >3=corrupt; here modeled
    #: directly, `None` covering every "no usable context" case uniformly
    #: since this in-memory model has no wire-format collision to guard
    #: against - see `reg244_context_gate` and
    #: `authorizes_unattended_restore`). Meaningful only for
    #: `capability_id == "free_power_transaction"` today; no other
    #: declared capability's automatic-restore direction is gated by a
    #: register-244 context match. Not part of CURRENT_OWNER_RECORD_SCHEMA_VERSION:
    #: unlike the firmware struct, this in-memory dataclass has no
    #: sizeof/tag collision hazard, so adding an optional field needs no
    #: version bump here.
    reg244_lease_context: int | None = None


# ---------------------------------------------------------------------------
# Retry policy - cause-aware, pure, no scheduler
# ---------------------------------------------------------------------------


class RetryDecision(str, Enum):
    RETRY_PERMITTED = "retry_permitted"
    RETRY_EXHAUSTED = "retry_exhausted"
    #: Zero automatic hardware writes are ever authorised for this cause.
    NO_AUTOMATIC_RETRY = "no_automatic_retry"


@dataclass(frozen=True)
class RetryPolicyResult:
    decision: RetryDecision
    #: Seconds to wait before the NEXT attempt, when `decision` is
    #: RETRY_PERMITTED. `None` otherwise.
    next_backoff_s: float | None
    reason: str


#: COMMS backoff sequence: 15s, 30s, 60s, 120s, then holds at 300s. A pure
#: table, not a running timer - `comms_backoff_seconds` looks up into it by
#: a PERSISTED attempt count, which is what makes it survive a modelled
#: reboot: the count, not an in-memory clock, is the only state involved.
_COMMS_BACKOFF_SECONDS: tuple[float, ...] = (15.0, 30.0, 60.0, 120.0, 300.0)


def comms_backoff_seconds(attempt_number: int) -> float:
    """The backoff, in seconds, before COMMS retry attempt `attempt_number`
    (1-based: `attempt_number=1` is the delay before the FIRST retry).

    Pure function of the attempt count alone, so recomputing it after a
    modelled reboot - using only the persisted `restore_attempts`/attempt
    counter - reproduces the exact same value; there is no timer to lose.
    """
    if attempt_number < 1:
        raise ValueError(f"attempt_number must be >= 1, got {attempt_number}")
    index = min(attempt_number - 1, len(_COMMS_BACKOFF_SECONDS) - 1)
    return _COMMS_BACKOFF_SECONDS[index]


def retry_policy(cause: RetryCause, attempts_so_far: int) -> RetryPolicyResult:
    """What the next attempt (if any) is allowed to be, given only `cause`
    and how many automatic attempts have already been made.

    Pure and total: no scheduler, no timer, no I/O. `attempts_so_far` is
    expected to be read back from a durable record, which is exactly what
    makes the result reboot-safe - see
    registry/tests/test_recovery_classifier_v2.py "retry counts surviving
    a reconstructed record".
    """
    if attempts_so_far < 0:
        raise ValueError(f"attempts_so_far must be >= 0, got {attempts_so_far}")

    if cause is RetryCause.COMMS:
        return RetryPolicyResult(
            RetryDecision.RETRY_PERMITTED,
            comms_backoff_seconds(attempts_so_far + 1),
            "a comms failure (timeout/no response) retries indefinitely on the documented "
            f"backoff, holding at {_COMMS_BACKOFF_SECONDS[-1]:.0f}s - this authorises retrying "
            "the SAME attempted action, never a silent change of what is attempted",
        )

    if cause is RetryCause.VERIFY_MISMATCH:
        if attempts_so_far >= 1:
            return RetryPolicyResult(
                RetryDecision.RETRY_EXHAUSTED,
                None,
                "a verify mismatch has already been retried once automatically without "
                "success - a second mismatch is treated as drift, not a transient, and "
                "requires an operator decision",
            )
        return RetryPolicyResult(
            RetryDecision.RETRY_PERMITTED,
            0.0,
            "first verify mismatch: at most one automatic retry is permitted",
        )

    if cause is RetryCause.METADATA:
        return RetryPolicyResult(
            RetryDecision.NO_AUTOMATIC_RETRY,
            None,
            "metadata/marker corruption authorises zero automatic hardware writes - "
            "see MarkerState.MALFORMED and RecordLoadFailure in classify_recovery_v2",
        )

    if cause is RetryCause.DURABLE_COMMIT:
        return RetryPolicyResult(
            RetryDecision.RETRY_PERMITTED,
            0.0,
            "a failed durable commit may retry the persistence/clear step itself - this "
            "is the CLEAR_ONLY path and never authorises a Modbus write",
        )

    raise ValueError(f"unrecognised retry cause: {cause!r}")


# ---------------------------------------------------------------------------
# Lease-expiry decision - pure, deterministic, no timer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClockContext:
    """Exactly what a restart can know about time, made explicit so
    "wall clock unavailable" is a first-class input rather than an
    implicit `None`-means-something-else convention.

    `uptime_s` is seconds since THIS boot, always available and always
    monotonic from zero - the one clock source that cannot be wrong,
    which is why it is the fallback `lease_should_end` uses when the wall
    clock cannot be trusted.
    """

    wall_time_valid: bool
    wall_time_epoch: float | None
    uptime_s: float


#: How long, in uptime seconds after a reboot, an invalid wall clock gets
#: before an outstanding lease is treated as due anyway. Exists so NTP
#: never locking (or locking very slowly) cannot let a lease run forever -
#: see `lease_should_end` rule 4/5 in the design brief.
DEFAULT_INVALID_CLOCK_GRACE_S = 300.0


def lease_should_end(
    record: OwnerRecord,
    clock: ClockContext,
    *,
    invalid_clock_grace_s: float = DEFAULT_INVALID_CLOCK_GRACE_S,
) -> bool:
    """Whether `record`'s lease is due to end, given only deterministic
    inputs - no sleeping, no timer, no I/O.

    Rule order (first match wins):

      1. `record.restore_requested` - a durable "end this now" always
         wins, regardless of what the clock says.
      2. A wall clock that is trusted (see rule 3) AND `lease_end_epoch`
         is known: ends exactly when `now >= lease_end_epoch`.
      3. A wall-clock reading strictly BEFORE `lease_start_epoch` is
         itself proof the clock cannot be trusted right now (real time
         does not run backwards across a lease's own lifetime) - treated
         as invalid regardless of what `wall_time_valid` claims.
      4. Wall clock untrusted (invalid, or no `lease_end_epoch` to check
         it against): falls back to uptime. `max_duration_s`, if set, and
         a bounded grace period both apply - whichever is reached first
         ends the lease - so an unresolved NTP lock can never let a lease
         run indefinitely.
    """
    if record.restore_requested:
        return True

    wall_time_valid = clock.wall_time_valid
    if (
        wall_time_valid
        and record.lease_start_epoch is not None
        and clock.wall_time_epoch is not None
        and clock.wall_time_epoch < record.lease_start_epoch
    ):
        wall_time_valid = False

    if wall_time_valid and record.lease_end_epoch is not None:
        assert clock.wall_time_epoch is not None
        return clock.wall_time_epoch >= record.lease_end_epoch

    if record.max_duration_s is not None and clock.uptime_s >= record.max_duration_s:
        return True
    return clock.uptime_s >= invalid_clock_grace_s


# ---------------------------------------------------------------------------
# Recovery classifier v2
# ---------------------------------------------------------------------------


class RecoveryActionV2(str, Enum):
    #: Marker is CLEAR: nothing is owed, nothing to reason about.
    CLEAR = "clear"
    #: Marker is PENDING_CLEAR: the hardware restore already verified;
    #: only the durable clear-commit is owed. NEVER a hardware write.
    CLEAR_ONLY = "clear_only"
    #: Live state already matches what recovery would restore TO - reread
    #: confirmed it, so clear without ever writing.
    VERIFY_AND_CLEAR = "verify_and_clear"
    #: A verified lease is real, outstanding, and not yet due.
    LEASE_ACTIVE = "lease_active"
    #: A verified lease is outstanding and due - see
    #: `authorizes_unattended_restore` for whether that alone may drive an
    #: UNATTENDED watchdog.
    RESTORE_DUE = "restore_due"
    #: A CONFIRMED write's live value no longer matches what ECCO last
    #: verified - something else changed it.
    DRIFT = "drift"
    #: Outcome is UNCERTAIN and live state matches NEITHER the snapshot
    #: nor the intended value - there is no honest restore-vs-drift
    #: distinction available; never invented.
    MIXED_OR_DRIFT = "mixed_or_drift"
    #: The live register read failed/timed out - nothing that requires
    #: live truth may proceed.
    HARDWARE_UNREADABLE = "hardware_unreadable"
    #: The marker, the record, its schema, or the capability itself
    #: cannot be trusted or resolved. Fails closed; never a write.
    LOCKOUT_METADATA = "lockout_metadata"
    #: A human must decide - either because no automatic restore
    #: direction is established for this capability, or because the
    #: available evidence does not support any narrower classification.
    OPERATOR_DECISION = "operator_decision"


@dataclass(frozen=True)
class RecoveryAssessmentV2:
    action: RecoveryActionV2
    reason: str
    #: The capability's declared safe direction, when it was possible to
    #: derive one (`None` for LOCKOUT_METADATA on an unknown capability,
    #: and for CLEAR/CLEAR_ONLY, which never need it).
    safe_direction: SafeDirection | None = None


def classify_recovery_v2(
    marker: MarkerState,
    record: OwnerRecord | RecordLoadFailure | None,
    live: dict[int, int] | None,
    clock: ClockContext,
) -> RecoveryAssessmentV2:
    """Map what boot observed to the one safe classification a restart may
    reason from. Total and pure: every combination of the four inputs
    below produces exactly one `RecoveryAssessmentV2`, and nothing here
    performs or authorises a hardware write.

    Parameters
    ----------
    marker:
        The durable MARKER's resolved state - see `MarkerState`. Already
        reduced (missing-record-is-CLEAR, bad-magic-or-bad-state-is-
        MALFORMED) by whatever loaded it; this function does not parse
        raw bytes.
    record:
        The companion OwnerRecord, when `marker` promises one exists
        (RESTORE_REQUIRED). `None` or a `RecordLoadFailure` when it does
        not exist or could not be loaded - NEVER coerced into a fake
        all-zero OwnerRecord. Ignored when `marker` is CLEAR or
        PENDING_CLEAR, which do not need it.
    live:
        A fresh register read, or `None` if the read itself failed/timed
        out. An explicitly empty dict `{}` is a valid (if unusual)
        successful read of zero registers - only `None` means "could not
        read".
    clock:
        See `ClockContext`.

    `record.kind` matters and is NOT decorative: a PERMANENT change is
    intended to remain changed and never enters lease semantics
    (LEASE_ACTIVE/RESTORE_DUE) - a verified PERMANENT write that still
    matches live state is VERIFY_AND_CLEAR (succeeded, nothing owed but
    cleanup), an uncertain PERMANENT write is always OPERATOR_DECISION
    once live is readable (matching `intended` is not proof it landed),
    and a PERMANENT write's live value diverging from what was verified
    is DRIFT. Only TEMPORARY_OVERRIDE ever produces LEASE_ACTIVE or
    RESTORE_DUE - see the CONFIRMED and UNCERTAIN branches below.
    """
    if marker is MarkerState.MALFORMED:
        return RecoveryAssessmentV2(
            RecoveryActionV2.LOCKOUT_METADATA,
            "the durable marker itself is malformed (bad magic or an unrecognised state "
            "value) - never coerced to CLEAR or guessed as RESTORE_REQUIRED",
        )

    if marker is MarkerState.CLEAR:
        return RecoveryAssessmentV2(RecoveryActionV2.CLEAR, "marker is CLEAR - nothing is owed")

    if marker is MarkerState.PENDING_CLEAR:
        return RecoveryAssessmentV2(
            RecoveryActionV2.CLEAR_ONLY,
            "the hardware restore already verified (Phase C) - only the durable clear "
            "commit (Phase D) is owed, and it performs zero Modbus activity",
        )

    # marker is RESTORE_REQUIRED from here: a valid, current-schema
    # OwnerRecord for a KNOWN capability is mandatory to reason further.
    if not isinstance(record, OwnerRecord):
        detail = record.value if isinstance(record, RecordLoadFailure) else "no record"
        return RecoveryAssessmentV2(
            RecoveryActionV2.LOCKOUT_METADATA,
            f"marker is RESTORE_REQUIRED but its companion record could not be used ({detail}) "
            "- the obligation is not discarded, it is locked out pending investigation",
        )

    if record.schema_version != CURRENT_OWNER_RECORD_SCHEMA_VERSION:
        return RecoveryAssessmentV2(
            RecoveryActionV2.LOCKOUT_METADATA,
            f"the record's schema_version ({record.schema_version}) is not one this "
            f"classifier understands (expected {CURRENT_OWNER_RECORD_SCHEMA_VERSION})",
        )

    direction = capability_safe_direction(record.capability_id)
    if direction is None:
        return RecoveryAssessmentV2(
            RecoveryActionV2.LOCKOUT_METADATA,
            f"capability_id {record.capability_id!r} is not a recognised, declared "
            "capability - its recovery declaration cannot be derived",
        )

    if record.outcome is WriteOutcome.UNATTEMPTED:
        if live is None:
            return RecoveryAssessmentV2(
                RecoveryActionV2.HARDWARE_UNREADABLE,
                "no write was ever attempted, but the live register read failed - "
                "nothing may proceed without hardware truth",
                direction,
            )
        if record.snapshot is not None and live == record.snapshot:
            return RecoveryAssessmentV2(
                RecoveryActionV2.VERIFY_AND_CLEAR,
                "durable snapshot exists, nothing was ever written, and live state still "
                "matches the snapshot exactly - clear without writing",
                direction,
            )
        return RecoveryAssessmentV2(
            RecoveryActionV2.OPERATOR_DECISION,
            "nothing was attempted, yet live state no longer matches the snapshot - an "
            "unexplained change happened while ECCO believed nothing was at risk",
            direction,
        )

    if record.outcome is WriteOutcome.UNCERTAIN:
        if record.kind is TransactionKind.PERMANENT:
            # A PERMANENT change has no lease to compare against - whether
            # live happens to match the snapshot, the intended value, or
            # neither, ECCO does not KNOW whether its write landed, and a
            # permanent change's only two honest states are "definitely
            # didn't happen" (UNATTEMPTED, handled above) or "a human
            # decides". Matching `intended` here is NOT proof it landed -
            # it could be exactly what pre-existed for unrelated reasons -
            # so, unlike the RESTORE-direction TEMPORARY_OVERRIDE case
            # below, this must never be read as a verified success. A
            # fresh live read is still required as evidence for that
            # human decision, so an unreadable read is its own outcome.
            if live is None:
                return RecoveryAssessmentV2(
                    RecoveryActionV2.HARDWARE_UNREADABLE,
                    "a PERMANENT change's write outcome is unknown and the live register "
                    "read failed - nothing may proceed without hardware truth",
                    direction,
                )
            return RecoveryAssessmentV2(
                RecoveryActionV2.OPERATOR_DECISION,
                "a PERMANENT change's write outcome is unknown - a human must confirm "
                "whether it landed; snapshot/intended/live are evidence for that "
                "decision, never grounds to auto-clear or treat as a lease",
                direction,
            )
        # TEMPORARY_OVERRIDE from here. Hardware-read failure is checked
        # BEFORE safe_direction, for both directions uniformly: a failed
        # live read is a diagnostically distinct, more informative fact
        # ("we do not even know what the hardware holds") than "this
        # capability has no unattended restore direction", and losing
        # that distinction would make HARDWARE_UNREADABLE invisible for
        # every NONE-direction capability. This widens no authority -
        # HARDWARE_UNREADABLE and OPERATOR_DECISION both forbid every
        # unattended write identically; only the reported reason differs.
        if live is None:
            return RecoveryAssessmentV2(
                RecoveryActionV2.HARDWARE_UNREADABLE,
                "the write's outcome is unknown and the live register read failed - "
                "nothing may proceed without hardware truth",
                direction,
            )
        if direction is SafeDirection.NONE:
            return RecoveryAssessmentV2(
                RecoveryActionV2.OPERATOR_DECISION,
                "the write's outcome is unknown and this capability has no established "
                "unattended restore direction - never guessed, always a human decision",
                direction,
            )
        if record.snapshot is not None and live == record.snapshot:
            return RecoveryAssessmentV2(
                RecoveryActionV2.VERIFY_AND_CLEAR,
                "the write's outcome is unknown, but live state matches the ORIGINAL "
                "snapshot - the write evidently never reached the inverter",
                direction,
            )
        if record.intended is not None and live == record.intended:
            due = lease_should_end(record, clock)
            return RecoveryAssessmentV2(
                RecoveryActionV2.RESTORE_DUE if due else RecoveryActionV2.LEASE_ACTIVE,
                "the write's outcome is unknown, but live state matches what ECCO "
                "intended - the write evidently landed despite the uncertain response",
                direction,
            )
        return RecoveryAssessmentV2(
            RecoveryActionV2.MIXED_OR_DRIFT,
            "the write's outcome is unknown and live state matches NEITHER the snapshot "
            "nor the intended value - no honest restore-vs-drift distinction is available",
            direction,
        )

    # outcome is CONFIRMED from here: ECCO knows what it last verified.
    if live is None:
        return RecoveryAssessmentV2(
            RecoveryActionV2.HARDWARE_UNREADABLE,
            "the write was confirmed, but the live register read failed - nothing may "
            "proceed without hardware truth",
            direction,
        )
    if live == record.last_verified:
        if record.kind is TransactionKind.PERMANENT:
            # A verified PERMANENT change is intended to STAY changed - it
            # never becomes a lease. Matching its own last-verified value
            # means the desired write succeeded and remains live; nothing
            # is owed but the durable obligation's own stale cleanup.
            return RecoveryAssessmentV2(
                RecoveryActionV2.VERIFY_AND_CLEAR,
                "a PERMANENT change was verified and live state still matches exactly - "
                "the intended write succeeded and remains in effect; the durable "
                "obligation is now only stale cleanup, never a restore",
                direction,
            )
        due = lease_should_end(record, clock)
        return RecoveryAssessmentV2(
            RecoveryActionV2.RESTORE_DUE if due else RecoveryActionV2.LEASE_ACTIVE,
            "live state matches what ECCO last verified - the lease is real and its "
            "restore-due status follows the lease clock alone",
            direction,
        )
    return RecoveryAssessmentV2(
        RecoveryActionV2.DRIFT,
        "live state no longer matches what ECCO last verified - something else changed "
        "it; a human must decide, not an inferred restore",
        direction,
    )


def reg244_context_gate(lease_context: int | None, live_reg244: int | None) -> bool:
    """2026-09-24 (PR-A: register-244 active-lease context). Fail-closed
    match between a Free Power lease's captured register-244 context and a
    FRESH live read of it, mirroring
    `restore_free_power_snapshot_dispatch`'s pre-write and pre-floor
    context gates in the firmware exactly: acceptable ONLY when the lease
    context is known/valid AND a fresh live value was actually obtained AND
    they are equal. `None` for either argument (no usable lease context, or
    no fresh read - never conflated with "live happens to be 0") always
    fails closed. Orthogonal to `classify_recovery_v2`'s ORIGINAL/INTENDED/
    NEITHER owned-register classification - this checks a DIFFERENT
    register (244) against a DIFFERENT durable fact (the lease's own
    context), never the owned-register snapshot/intended comparison.
    """
    if lease_context is None or live_reg244 is None:
        return False
    return lease_context == live_reg244


def authorizes_unattended_restore(
    assessment: RecoveryAssessmentV2,
    *,
    record: OwnerRecord | None = None,
    live_reg244: int | None = None,
) -> bool:
    """Whether `assessment` ALONE may drive an UNATTENDED watchdog restore.

    True only when RESTORE_DUE with a RESTORE safe direction - the shape
    of the live Free Power 15s watchdog - AND, for
    `capability_id == "free_power_transaction"` specifically, a fresh
    register-244 active-lease context match (2026-09-24, PR-A - see
    `reg244_context_gate`). Every other action, including RESTORE_DUE for a
    capability whose safe direction is NONE, must be routed to a human via
    `resolve_operator_action` instead. Kept as a single function so this
    answer exists in exactly one place.

    `record`/`live_reg244` are keyword-only and default to `None`, which
    skips the register-244 context gate entirely - preserving this
    function's pre-PR-A behaviour for every existing caller that does not
    pass them (this model's reg244 context concept did not exist before
    PR-A, and no OTHER capability's unattended-restore eligibility is
    gated by it). A caller modelling Free Power's actual watchdog MUST
    pass both to get PR-A's real fail-closed behaviour.
    """
    base = (
        assessment.action is RecoveryActionV2.RESTORE_DUE
        and assessment.safe_direction is SafeDirection.RESTORE
    )
    if not base:
        return False
    if record is not None and record.capability_id == "free_power_transaction":
        return reg244_context_gate(record.reg244_lease_context, live_reg244)
    return True


# ---------------------------------------------------------------------------
# Operator resolution model - pure, never writes
# ---------------------------------------------------------------------------


class OperatorAction(str, Enum):
    #: Attempt the restore again against a fresh live read.
    RETRY_RESTORE = "retry_restore"
    #: Attempt the restore despite uncertainty/drift, having been shown
    #: the evidence - does not pretend the prior state was normal.
    FORCE_RESTORE = "force_restore"
    #: Treat the current live state as correct going forward; no restore.
    ACCEPT_LIVE_STATE = "accept_live_state"
    #: Give up on an obligation that is genuinely unreadable/corrupt.
    DISCARD_UNREADABLE = "discard_unreadable"


#: How many genuinely separate fresh live-read attempts must have failed
#: before DISCARD_UNREADABLE may treat HARDWARE (as opposed to a corrupt/
#: missing durable RECORD, which is its own concrete evidence - see
#: `resolve_operator_action`) as unreadable. A MODEL threshold only: one
#: transient failure must not be enough to let an operator discard a real
#: obligation, so a future executor must actually perform this many
#: distinct fresh read attempts (not reuse one cached failure) before
#: `consecutive_live_read_failures` may reach this value.
DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class OperatorResolutionRequest:
    action: OperatorAction
    #: An explicit arm, distinct from merely viewing the recovery state.
    armed: bool
    #: A fresh live register read, or `None` if it is not available.
    live: dict[int, int] | None
    #: The obligation generation the operator is confirming - must match
    #: `record.generation` for FORCE_RESTORE / ACCEPT_LIVE_STATE.
    confirmed_generation: int | None = None
    #: Whether the operator has been shown snapshot/live/last-verified
    #: evidence before arming - required for FORCE_RESTORE only.
    shown_evidence: bool = False
    #: How many genuinely separate fresh live-read attempts have failed in
    #: a row. Consulted only by DISCARD_UNREADABLE when the durable RECORD
    #: itself is otherwise valid (a valid `OwnerRecord`, not a
    #: `RecordLoadFailure`) - see `DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES`.
    consecutive_live_read_failures: int = 0


@dataclass(frozen=True)
class OperatorResolutionResult:
    permitted: bool
    reason: str
    #: The durable marker transition this resolution would ask a real
    #: executor to commit - NEVER performed here. `None` when refused.
    marker_transition: MarkerState | None = None
    #: A human-readable audit-intent string a real executor must persist
    #: BEFORE acting on `marker_transition` - modelling the same
    #: "audit/commit before clear" ordering as the two-phase durable
    #: marker (RESTORE_VERIFIED_PENDING_CLEAR -> CLEAR).
    audit_intent: str | None = None


def _restore_target_refusal(record: OwnerRecord | RecordLoadFailure | None) -> str | None:
    """`None` if `record` is a trustworthy restore TARGET; otherwise the
    refusal reason. RETRY_RESTORE / FORCE_RESTORE may only restore TO a
    snapshot ECCO actually has recorded - never a value manufactured from
    a missing, corrupt, or altogether absent durable record, and never
    for a capability whose declaration cannot be derived (see
    `capability_safe_direction`, which this deliberately reuses rather
    than re-deriving a second notion of "known capability")."""
    if not isinstance(record, OwnerRecord):
        detail = record.value if isinstance(record, RecordLoadFailure) else "no record"
        return f"the durable record could not be used ({detail}) - there is no trustworthy snapshot to restore to"
    if record.snapshot is None:
        return "the record carries no snapshot - there is nothing to restore to"
    if capability_safe_direction(record.capability_id) is None:
        return f"capability_id {record.capability_id!r} is not a recognised, declared capability"
    return None


def resolve_operator_action(
    request: OperatorResolutionRequest,
    record: OwnerRecord | RecordLoadFailure | None,
) -> OperatorResolutionResult:
    """Whether `request.action` is permitted, and if so, the marker
    transition / audit intent a real executor would still have to persist.

    Pure: never mutates `record`, never performs I/O, never itself clears
    or writes anything. A permitted result is a description of what would
    be safe to do next, not the doing of it.
    """
    if not request.armed:
        return OperatorResolutionResult(False, f"{request.action.value} refused: not armed")

    capability_id = record.capability_id if isinstance(record, OwnerRecord) else "<unresolved>"
    generation = record.generation if isinstance(record, OwnerRecord) else None

    def generation_confirmed() -> bool:
        return isinstance(record, OwnerRecord) and request.confirmed_generation == record.generation

    if request.action is OperatorAction.RETRY_RESTORE:
        target_refusal = _restore_target_refusal(record)
        if target_refusal is not None:
            return OperatorResolutionResult(False, f"RETRY_RESTORE refused: {target_refusal}")
        if request.live is None:
            return OperatorResolutionResult(
                False, "RETRY_RESTORE refused: live state is not freshly readable"
            )
        return OperatorResolutionResult(
            True,
            "operator armed a retry of the restore against a fresh live read",
            marker_transition=MarkerState.RESTORE_REQUIRED,
            audit_intent=f"operator retried restore for {capability_id!r} (generation {generation!r})",
        )

    if request.action is OperatorAction.FORCE_RESTORE:
        target_refusal = _restore_target_refusal(record)
        if target_refusal is not None:
            return OperatorResolutionResult(False, f"FORCE_RESTORE refused: {target_refusal}")
        if request.live is None:
            return OperatorResolutionResult(
                False, "FORCE_RESTORE refused: live state is not freshly readable"
            )
        if not generation_confirmed():
            return OperatorResolutionResult(
                False,
                "FORCE_RESTORE refused: the confirmed obligation generation does not match "
                "the current one - this would risk confirming a stale obligation",
            )
        if not request.shown_evidence:
            return OperatorResolutionResult(
                False,
                "FORCE_RESTORE refused: the operator has not been shown snapshot/live/"
                "last-verified evidence before arming",
            )
        return OperatorResolutionResult(
            True,
            "operator forced a restore after being shown the evidence - this does NOT "
            "silently reclassify the prior uncertainty/drift as normal",
            marker_transition=MarkerState.RESTORE_REQUIRED,
            audit_intent=(
                f"operator FORCED restore for {capability_id!r} (generation {generation!r}) "
                "over uncertain/drifted state, evidence shown"
            ),
        )

    if request.action is OperatorAction.ACCEPT_LIVE_STATE:
        if request.live is None:
            return OperatorResolutionResult(
                False, "ACCEPT_LIVE_STATE refused: live state is not freshly readable"
            )
        if not generation_confirmed():
            return OperatorResolutionResult(
                False,
                "ACCEPT_LIVE_STATE refused: the confirmed obligation generation does not "
                "match the current one",
            )
        return OperatorResolutionResult(
            True,
            "operator accepted the live state as authoritative going forward",
            marker_transition=MarkerState.PENDING_CLEAR,
            audit_intent=(
                f"operator ACCEPTED live state {request.live!r} for {capability_id!r} "
                f"(generation {generation!r}) in place of the outstanding obligation"
            ),
        )

    if request.action is OperatorAction.DISCARD_UNREADABLE:
        if request.live is not None:
            # Hardware truth always wins. A fresh read succeeding means
            # this is NOT genuinely unreadable, regardless of how the
            # durable record fared - never claim "hardware unreadable"
            # when only metadata is unreadable.
            return OperatorResolutionResult(
                False,
                "DISCARD_UNREADABLE refused: a fresh live read succeeded - use "
                "ACCEPT_LIVE_STATE or FORCE_RESTORE instead of discarding",
            )
        # `record is None` is NOT metadata-failure evidence - it means the
        # recovery metadata state has not been resolved/classified at
        # all, which is a different, weaker thing than an explicit,
        # concrete RecordLoadFailure. A bare `None` must first be
        # classified as MISSING or CORRUPT (see `classify_recovery_v2`'s
        # own LOCKOUT_METADATA handling of exactly this case) rather than
        # guessed to be discardable here.
        metadata_failed = isinstance(record, RecordLoadFailure)
        if record is None:
            return OperatorResolutionResult(
                False,
                "DISCARD_UNREADABLE refused: the recovery metadata state is unresolved "
                "(no record and no explicit RecordLoadFailure) - it must first be classified "
                "as MISSING or CORRUPT, not guessed to be discardable",
            )
        if not metadata_failed and request.consecutive_live_read_failures < DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES:
            # The durable RECORD is fine - only hardware reads are
            # failing. One transient failure is not concrete evidence;
            # require several genuinely separate fresh attempts first.
            return OperatorResolutionResult(
                False,
                f"DISCARD_UNREADABLE refused: only {request.consecutive_live_read_failures} "
                "consecutive fresh live-read failure(s) recorded against an otherwise valid "
                f"record - at least {DISCARD_UNREADABLE_MIN_CONSECUTIVE_FAILURES} are required "
                "before hardware is treated as genuinely unreadable",
            )
        reason = (
            "operator discarded an obligation whose durable record itself could not be "
            "loaded - the metadata failure is its own concrete evidence"
            if metadata_failed
            else (
                f"operator discarded an obligation after "
                f"{request.consecutive_live_read_failures} consecutive fresh live-read "
                "failures against an otherwise valid record"
            )
        )
        return OperatorResolutionResult(
            True,
            reason,
            marker_transition=MarkerState.PENDING_CLEAR,
            audit_intent=(
                f"operator DISCARDED unreadable obligation for {capability_id!r} "
                f"(generation {generation!r}); metadata_failed={metadata_failed}, "
                f"consecutive_live_read_failures={request.consecutive_live_read_failures}"
            ),
        )

    raise ValueError(f"unrecognised operator action: {request.action!r}")
