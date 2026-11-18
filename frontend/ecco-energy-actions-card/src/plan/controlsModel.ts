// The view model of the plan controls: what the start and cancel buttons offer, and why one is not offered. Pure data in, data out; it
// builds the service calls (planActions.ts) but never sends one.
//
// The validator (frontend/ecco-plan-core) decides what is OFFERED: the owner's default, the chips inside the minimum and the cap, and
// "until HH:MM" when it fits. The guarded script decides what is ALLOWED, with the same rules, on the server. A button that the
// validator would refuse is shown disabled with the reason; a button the server refuses answers with the server's reason, which the
// card shows from the last-result helper.
import { OVERRIDE_KINDS, OVERRIDE_LABELS, expiryChoices, formatDurationMin, startConfiguredOverride } from "../../../ecco-plan-core/src/index.ts";
import type { ClockContext, OverrideConfig, OverrideKind } from "../../../ecco-plan-core/src/index.ts";
import { stateText } from "./adapter.ts";
import type { StatesLike } from "./adapter.ts";
import type { PlanSnapshotWithHelpers } from "./helpers.ts";
import { PLAN_CONTROL_IDS, cancelOverrideCall, startOverrideCall } from "./planActions.ts";
import { belowReserveSentence } from "./present.ts";
import type { PlanServiceCall } from "./planActions.ts";

export interface ChoiceVM {
  id: string;
  label: string;
  isDefault: boolean;
  call: PlanServiceCall;
}

export interface KindControlVM {
  kind: OverrideKind;
  label: string;
  active: boolean;
  /** "Active until 2026-11-18 07:00 (ends in 9 h 30 min)" while it runs. */
  activeText: string | null;
  /** The choices to start it with; empty when starting is not offered. */
  choices: ChoiceVM[];
  /** Why starting is not offered (the validator's reason), or null. */
  blockedReason: string | null;
  cancel: PlanServiceCall | null;
  /** Prepare for power cut only: set while the battery is below the reserve it raised, in the owner's words. */
  belowReserve: string | null;
}

export interface ControlsVM {
  kinds: KindControlVM[];
  /** The scripts' own last answer ("STARTED ...", "REFUSED CODE - reason", "CANCELLED ..."), verbatim, or null. */
  lastResult: string | null;
  /** Guarded scripts the card cannot find: the controls are not offered until they exist. */
  missingScripts: string[];
}

export interface ControlsContext {
  snap: PlanSnapshotWithHelpers;
  states: StatesLike;
  nowMs: number;
  clock: ClockContext | null;
}

/** null when the plan helpers are not configured (no controls at all, the section stays exactly as it was). */
export function buildControlsVM(ctx: ControlsContext): ControlsVM | null {
  const h = ctx.snap.helpers;
  if (!h) return null;
  const nowMin = Math.floor(ctx.nowMs / 60000);
  const revision = h.revision.known ? h.revision.value : null;
  const missingScripts = [PLAN_CONTROL_IDS.start_script, PLAN_CONTROL_IDS.cancel_script].filter((id) => ctx.states[id] === undefined);
  const reserve = ctx.snap.fields.find((f) => f.path === "reserve.backupPct");
  const currentReservePct = reserve && reserve.known ? reserve.value : null;
  const startCfg: OverrideConfig | null = h.startPolicy.ok ? h.startPolicy.config : null;
  const last = stateText(ctx.states, PLAN_CONTROL_IDS.last_result);

  const kinds: KindControlVM[] = OVERRIDE_KINDS.map((kind) => {
    const row = h.active.find((r) => r.override.kind === kind) ?? null;
    let choices: ChoiceVM[] = [];
    let blockedReason: string | null = null;
    if (!startCfg) {
      blockedReason = h.startPolicy.ok ? null : (h.startPolicy.reasons[0] ?? "The override limits are not usable.");
    } else {
      const all = expiryChoices(kind, startCfg, ctx.clock);
      // Dry run with the first choice: a refusal that does not depend on the length (unknown or too-high reserve) blocks every choice.
      const probe = all.length ? all[0] : null;
      const verdict = startConfiguredOverride(kind, nowMin, probe ? probe.expiryMin : null, h.startPolicy, { clock: ctx.clock, currentReservePct });
      if (!verdict.ok && (verdict.code === "RESERVE_UNKNOWN" || verdict.code === "RESERVE_BELOW_CURRENT")) blockedReason = verdict.error;
      else if (all.length === 0) blockedReason = "No length fits the owner's limits.";
      else {
        choices = all.map((c) => ({
          id: c.id,
          label: c.label,
          isDefault: c.isDefault,
          call: c.untilMin !== null ? startOverrideCall(kind, { untilLocal: true }, revision) : startOverrideCall(kind, { expiryMin: c.expiryMin }, revision),
        }));
      }
    }
    const rem = row ? row : null;
    const belowReserve =
      kind === "prepare_power_cut" && rem && typeof rem.override.reservePct === "number" && h.socPct !== null && h.socPct < rem.override.reservePct
        ? belowReserveSentence(h.socPct, rem.override.reservePct)
        : null;
    return {
      kind,
      label: OVERRIDE_LABELS[kind],
      active: row !== null,
      activeText: row ? "Active until " + row.expiresText + " (ends in " + formatDurationMin(row.remainingMin) + ")" : null,
      choices,
      blockedReason,
      cancel: row ? cancelOverrideCall(kind, revision) : null,
      belowReserve,
    };
  });
  return { kinds, lastResult: last, missingScripts };
}
