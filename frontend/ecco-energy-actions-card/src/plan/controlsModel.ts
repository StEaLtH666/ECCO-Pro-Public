// The view model of the plan controls: what the start and cancel buttons offer, and why one is not offered. Pure data in, data out; it
// builds the service calls (planActions.ts) but never sends one.
//
// The validator (frontend/ecco-plan-core) decides what is OFFERED: the owner's default, the chips inside the minimum and the cap, and
// "until HH:MM" when it fits. The guarded script decides what is ALLOWED, with the same rules, on the server. A button that the
// validator would refuse is shown disabled with the reason; a button the server refuses answers with the server's reason, which the
// card shows from the last-result helper.
//
// Owner decision r15 (19 Nov 2026, known limitation 23): a Cancel is offered for every kind that Home Assistant holds or may hold: a running
// row (placed by the later of the backend's two expiry sources, helpers.ts) and a kind it cannot read or trust (held by Home Assistant). It is
// the same guarded cancel call with the stored revision, and nothing else. After a cancel the card does not assume success: `cancelReadback`
// reads back the plan revision, the guarded script's own answer and BOTH records and says confirmed, still pending, or NOT confirmed.
import { OVERRIDE_KINDS, OVERRIDE_LABELS, expiryChoices, formatDurationMin, startConfiguredOverride } from "../../../ecco-plan-core/src/index.ts";
import type { ClockContext, OverrideConfig, OverrideKind } from "../../../ecco-plan-core/src/index.ts";
import { stateText } from "./adapter.ts";
import type { StatesLike } from "./adapter.ts";
import type { KindRecord, PlanSnapshotWithHelpers } from "./helpers.ts";
import { PLAN_CONTROL_IDS, cancelOverrideCall, startOverrideCall } from "./planActions.ts";
import { belowReserveSentence, heldText } from "./present.ts";
import type { PlanServiceCall } from "./planActions.ts";

export interface ChoiceVM {
  id: string;
  label: string;
  isDefault: boolean;
  call: PlanServiceCall;
}

/** The card's reading of one Cancel, read back from the states: still waiting, confirmed (both records ended) or NOT confirmed. */
export interface CancelReadbackVM {
  outcome: "pending" | "confirmed" | "not_confirmed";
  text: string;
}

/** What the card remembers of an owner's Cancel click: the revision and the script's answer it had seen, so that only a CHANGE is read as an answer. */
export interface CancelAttempt {
  readonly revision: number | null;
  readonly answer: string | null;
}
export type CancelLedger = { [K in OverrideKind]?: CancelAttempt };

export interface KindControlVM {
  kind: OverrideKind;
  label: string;
  active: boolean;
  /** "Active until 2026-11-18 07:00 (ends in 9 h 30 min)" while it runs, or "Held by Home Assistant ..." when it is held but not a trusted running row. */
  activeText: string | null;
  /** True when Home Assistant holds, or may hold, the kind but the card cannot show it as a trusted running override (a record it cannot read, or a malformed one). */
  held: boolean;
  /** Plain words about where the record stands (the absolute epoch record alone holds it; a record cannot be read), or null. */
  note: string | null;
  /** The readback of the owner's last Cancel of this kind (pending, confirmed, NOT confirmed), or null when there is nothing to say. */
  readback: CancelReadbackVM | null;
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
  /** The Cancel clicks the card remembers (controls.ts keeps them for the page); absent means none. */
  cancels?: CancelLedger;
}

const CANCEL_REFUSALS = ["NOT_ACTIVE", "REVISION_CONFLICT", "REVISION_UNREADABLE", "UNKNOWN_KIND"];
const KEEPS = " Home Assistant keeps the hold, and any raised reserve, until a cancel is confirmed.";

/**
 * Note a click that is about to be sent: a Cancel is remembered with the plan revision it carries and the last answer the card had seen; a Start of the
 * same kind forgets it (the revision then moves for another reason); any other call changes nothing. Pure: it only edits the ledger it is given.
 */
export function noteCall(ledger: CancelLedger, call: PlanServiceCall, lastAnswer: string | null): void {
  const v = (call.data.variables ?? {}) as { kind?: unknown; expected_revision?: unknown };
  const kind = OVERRIDE_KINDS.find((k) => k === v.kind);
  if (kind === undefined) return;
  if (call.data.entity_id === PLAN_CONTROL_IDS.cancel_script) ledger[kind] = { revision: typeof v.expected_revision === "number" ? v.expected_revision : null, answer: lastAnswer };
  else if (call.data.entity_id === PLAN_CONTROL_IDS.start_script) delete ledger[kind];
}

/**
 * What the next states say about a Cancel: nothing is assumed from the click. CONFIRMED only when the plan revision moved by the cancel's own step and
 * both records read as ended (or the script refused because they had already ended); PENDING until the revision or the script's answer changes;
 * NOT confirmed while a record is still in the future or cannot be read, or when the script refused. null when another writer got in between (the
 * revision moved by more than one step, or the answer is not a cancel's), so no claim is made about this click.
 */
function cancelReadback(kind: OverrideKind, label: string, attempt: CancelAttempt | undefined, revision: number | null, answer: string | null, rec: KindRecord | undefined): CancelReadbackVM | null {
  if (!attempt) return null;
  const base = attempt.revision;
  if (base !== null && revision !== null && revision > base + 1) return null;
  const advanced = base !== null && revision !== null && revision > base;
  const answered = answer !== attempt.answer;
  const cancelled = answer === "CANCELLED " + kind + ".";
  const refusal = answer !== null && CANCEL_REFUSALS.some((c) => answer.startsWith("REFUSED " + c + " "));
  if (answered && !cancelled && !refusal) return null;
  if (!advanced && !answered) {
    return { outcome: "pending", text: "Cancel sent for " + label + ". Waiting for Home Assistant to answer: the plan revision and both records are read back before it is called cancelled." };
  }
  if (rec === undefined) return { outcome: "pending", text: "Cancel sent for " + label + ". The records cannot be read back because the current time is not known." };
  const ended = rec.read === "cleared";
  const both = rec.epochMissing ? "the date-and-time record reads as ended (the absolute record is not installed)" : "both records read as ended";
  if (ended && advanced) return { outcome: "confirmed", text: "Cancel confirmed for " + label + ": " + both + (revision !== null ? " (plan revision " + revision + ")" : "") + "." };
  if (ended && refusal) {
    return { outcome: "confirmed", text: "Nothing to cancel for " + label + ": " + (rec.epochMissing ? "the date-and-time record already reads as ended (the absolute record is not installed)" : "both records already read as ended") + "." };
  }
  if (ended) {
    return { outcome: "not_confirmed", text: "Cancel NOT confirmed for " + label + ": " + both + ", but the plan revision did not move as a cancel moves it (or cannot be read), so the answer is not taken on trust." };
  }
  const holds = rec.read === "active" ? "a record still holds it until " + (rec.endText ?? "an unknown time") : "a record cannot be read here";
  const lead = refusal && !advanced ? "Home Assistant did not carry it out. Its answer was: " + answer + " " + holds.charAt(0).toUpperCase() + holds.slice(1) : holds;
  return { outcome: "not_confirmed", text: "Cancel NOT confirmed for " + label + ": " + lead + "." + KEEPS };
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
    const held = h.held.find((r) => r.kind === kind) ?? null;
    const rem = row ? row : null;
    const belowReserve =
      kind === "prepare_power_cut" && rem && typeof rem.override.reservePct === "number" && h.socPct !== null && h.socPct < rem.override.reservePct
        ? belowReserveSentence(h.socPct, rem.override.reservePct)
        : null;
    return {
      kind,
      label: OVERRIDE_LABELS[kind],
      active: row !== null,
      activeText: row ? "Active until " + row.expiresText + " (ends in " + formatDurationMin(row.remainingMin) + ")" : held ? heldText(held, nowMin) : null,
      held: held !== null,
      note: (row ? row.note : held ? held.note : "") || null,
      readback: cancelReadback(kind, OVERRIDE_LABELS[kind], ctx.cancels?.[kind], revision, last, h.records.find((r) => r.kind === kind)),
      choices,
      blockedReason,
      cancel: row || held ? cancelOverrideCall(kind, revision) : null,
      belowReserve,
    };
  });
  return { kinds, lastResult: last, missingScripts };
}
