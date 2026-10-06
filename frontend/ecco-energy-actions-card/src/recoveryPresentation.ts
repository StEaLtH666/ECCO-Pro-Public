// Pure refinement of HOW the "recovery_attention" body presents its End &
// Restore action - no Lit, no DOM. Deliberately separate from
// freePowerState.ts's classifyFreePower(), which stays exactly as-is (the
// top-level SAFE/ARMED/ACTIVE/.../RECOVERY ATTENTION classification is not
// weakened or second-guessed here). This module only refines what happens
// ONCE the tile is already in "recovery_attention": is End & Restore the
// dominant action, a secondary one, or not shown as actionable at all -
// using nothing but the two pieces of state the firmware itself already
// exposes (snapshot_valid, and its own literal status text).
//
// Every pattern below is matched directly against real strings this
// repository's firmware publishes (see the id(free_power_status).publish_
// state(...) call sites in firmware/ecco_clock_dongle_stage3_4_free_power.yaml
// - test/recoveryPresentation.test.ts pins each one against the literal
// text). Nothing here invents a corrective action the firmware didn't
// already name.

export interface RecoveryActionInput {
  statusText: string | undefined;
  /** binary_sensor.*_free_power_snapshot_valid - null when unavailable/unknown. */
  snapshotValid: boolean | null;
}

export interface RecoveryPresentation {
  /** Whether an End & Restore control should render as an actionable button at all. */
  actionable: boolean;
  /** Button label when actionable; null otherwise. */
  actionLabel: string | null;
  /** True when the action should be styled as a quiet secondary control rather than the dominant call-to-action. */
  secondary: boolean;
  /** A short, neutral, literal-firmware-grounded explanation - shown instead of (blocked/no-snapshot) or alongside the action. */
  explanation: string | null;
}

// Rule D: firmware explicitly says recovery/writes are blocked and requires
// a deliberate (out-of-UI) operator action - showing an actionable button
// here would contradict that. Matches every firmware variant that contains
// the phrase, plus the two ways it explains itself ("inverter writes
// locked", "deliberate recovery required") in case future wording varies
// but keeps the same meaning.
const RECOVERY_BLOCKED_PATTERN = /RECOVERY BLOCKED|inverter writes? (?:are |is )?locked|deliberate recovery required/i;

// Rule E: a start/activation attempt failed before any snapshot was held -
// there is nothing to restore.
const START_OR_ACTIVATION_FAILED_PATTERN = /START FAILED|ACTIVATION (?:VERIFY|WRITE) FAILED/i;

// Rule A: firmware names End Free Power itself as the retry step (e.g.
// "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Free
// Power; press End Free Power to retry").
const OPERATOR_DECISION_REQUIRED_PATTERN = /OPERATOR DECISION REQUIRED/i;
const NAMES_END_FREE_POWER_RETRY_PATTERN = /press End Free Power|retry(?:ing)? restore/i;

// Rule B: a snapshot survived (e.g. a reboot) and is waiting to be put back -
// "RECOVERY REQUIRED - saved snapshot found".
const RECOVERY_REQUIRED_PATTERN = /\bRECOVERY REQUIRED\b/i;

// Rule C: a restore verification step failed but firmware explicitly kept
// the snapshot for a retry (e.g. "RESTORE VERIFY FAILED - snapshot retained
// for retry", "RESTORE WRITE FAILED - snapshot retained; will retry
// automatically").
const SNAPSHOT_RETAINED_PATTERN = /snapshot retained/i;

// Rule F: "RESTORE BLOCKED - live inverter state matches neither the saved
// snapshot nor Free Power's intended state; operator decision required".
// Distinct from Rule D's RECOVERY BLOCKED (an outright "nothing to press"
// case): this is a live three-way disagreement between the inverter, the
// saved snapshot, and what Free Power expects - genuinely something an
// operator needs to look at themselves, not a routine retry. It must never
// read as the same inviting, primary "just press this" action as the other
// rules; pressing it is never guaranteed to resolve the drift, only ever
// offered as a quiet secondary option, and only when a snapshot is actually
// confirmed present to restore.
const RESTORE_BLOCKED_PATTERN = /RESTORE BLOCKED/i;

/**
 * Refines the End & Restore action for the "recovery_attention" body only.
 * Callers elsewhere (e.g. the plain "active" state's End & Restore Now)
 * should NOT use this - it exists specifically for the ambiguity the task
 * called out: recovery_attention was previously treated as one uniform
 * "show End & Restore" bucket, which doesn't match what the firmware itself
 * is actually saying in each of these distinct cases. Fails closed by
 * default: an action is only ever actionable when a snapshot is CONFIRMED
 * present (`snapshotValid === true`) - null/unknown or false never offer a
 * restore action just because no specific rule matched the status text.
 */
export function classifyRecoveryAction(input: RecoveryActionInput): RecoveryPresentation {
  const text = input.statusText ?? "";
  const snapshotValid = input.snapshotValid;

  // D takes priority over everything else - an explicit "blocked, deliberate
  // recovery required" statement should never be paired with an actionable
  // button that implies a normal retry will help.
  if (RECOVERY_BLOCKED_PATTERN.test(text)) {
    return {
      actionable: false,
      actionLabel: null,
      secondary: false,
      explanation: "Deliberate recovery is required - this will not clear on its own.",
    };
  }

  // E - nothing was ever successfully snapshotted, so there is nothing an
  // End & Restore action could put back.
  if (START_OR_ACTIVATION_FAILED_PATTERN.test(text) && snapshotValid === false) {
    return {
      actionable: false,
      actionLabel: null,
      secondary: false,
      explanation: "No saved snapshot is held - there is nothing to restore.",
    };
  }

  // A - firmware names this exact action as the documented retry step.
  if (
    OPERATOR_DECISION_REQUIRED_PATTERN.test(text) &&
    NAMES_END_FREE_POWER_RETRY_PATTERN.test(text) &&
    snapshotValid === true
  ) {
    return { actionable: true, actionLabel: "Retry End & Restore", secondary: false, explanation: null };
  }

  // B - a snapshot survived and is simply waiting to be restored.
  if (RECOVERY_REQUIRED_PATTERN.test(text) && snapshotValid === true) {
    return { actionable: true, actionLabel: "Restore Saved Settings", secondary: false, explanation: null };
  }

  // C - a verification attempt failed but the snapshot is retained; keep
  // the action available, but quiet rather than the dominant CTA.
  if (SNAPSHOT_RETAINED_PATTERN.test(text) && snapshotValid === true) {
    return { actionable: true, actionLabel: "End & Restore Now", secondary: true, explanation: null };
  }

  // F - a live state mismatch requiring an operator's own judgement call,
  // not a routine retry (see the pattern's doc comment above). Never the
  // dominant CTA, and never offered at all when a snapshot isn't confirmed
  // present - there would be nothing to restore even if pressed.
  if (RESTORE_BLOCKED_PATTERN.test(text)) {
    if (snapshotValid === true) {
      return {
        actionable: true,
        actionLabel: "Attempt Restore",
        secondary: true,
        explanation:
          "Operator decision required - live inverter state matches neither the saved snapshot nor Free Power's intended state. Restoring is not guaranteed to resolve the mismatch.",
      };
    }
    return {
      actionable: false,
      actionLabel: null,
      secondary: false,
      explanation:
        "Operator decision required, and no confirmed snapshot is held to restore - review the inverter's live state directly.",
    };
  }

  // Default: an attention-worthy status this module doesn't have a more
  // specific rule for. Fail-closed on snapshot state: the plain dominant
  // action is only offered when a snapshot is CONFIRMED present - a
  // null/unknown snapshot_valid (the entity is unavailable) or an explicit
  // false must never silently fall through to an actionable button just
  // because no more specific rule matched this particular status text.
  if (snapshotValid === true) {
    return { actionable: true, actionLabel: "End & Restore Now", secondary: false, explanation: null };
  }
  return {
    actionable: false,
    actionLabel: null,
    secondary: false,
    explanation: "Unable to confirm a saved snapshot is held - review the firmware status directly before acting.",
  };
}
