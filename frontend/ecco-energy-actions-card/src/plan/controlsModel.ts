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
import { CURRENT_RESERVE_MAX, CURRENT_RESERVE_MIN, stateNumber, stateText } from "./adapter.ts";
import type { StatesLike } from "./adapter.ts";
import { HELPER_IDS } from "./helpers.ts";
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

/**
 * What the installed backend looks like from the states: the plan scripts, the confirmation switch and the two plan sensors, and the guarded Dump to
 * Grid start when the card is configured with one. Derived from what EXISTS in Home Assistant, never from a static assumption: "not installed" is said
 * only when the entity is really absent.
 */
export interface InstallVM {
  startScript: boolean;
  cancelScript: boolean;
  confirmationSwitch: boolean;
  effectiveReserve: boolean;
  exportHold: boolean;
  guardedDump: "not_configured" | "installed" | "missing";
  /** Entity ids that were looked for and not found (the guarded Dump start only when the card names one). */
  missing: string[];
}

/**
 * The one short status line above the override controls. "ready" means everything the controls rely on was found and readable; "ready_with_gaps" means
 * a start can be sent but something the plan reads was not found; "revision_unreadable" means the stored plan revision cannot be read, which the installed
 * start script refuses every start for.
 */
export interface ReadinessVM {
  kind: "ready" | "ready_with_gaps" | "revision_unreadable" | "needs_confirmation" | "confirmation_unreadable" | "limits_unusable" | "partial" | "not_installed";
  text: string;
}

/** The reserve ECCO's plan uses now, as the installed effective-reserve sensor publishes it (a whole percent from 0 to 100), or why it cannot be read. */
export interface PlanReserveReading {
  known: boolean;
  value: number | null;
  /** Why it is unknown ("" when known). */
  reason: string;
}

/**
 * The reserves, kept apart: what the OWNER's backup reserve is now, what ECCO's plan uses now (only shown when it can differ from the owner's: an override
 * record is held, or the plan's own figure differs from the owner's), and what Prepare for power cut would raise it TO.
 */
export interface ReserveVM {
  nowPct: number | null;
  /** Why the reserve now is unknown ("" when known). */
  nowReason: string;
  targetPct: number | null;
  targetReason: string;
  /** The reserve ECCO's plan uses now (the effective-reserve sensor); null while it is not shown. */
  planPct: number | null;
  /** Why the plan's reserve is unknown while it is shown ("" otherwise). */
  planReason: string;
  /** "Reserve now 5 %" (or "Your reserve 5 %" while the plan's reserve is shown beside it) and "Power cut target 80 %" in the owner's words, or the honest reason when a figure is not known. */
  nowText: string;
  targetText: string;
  /** "Plan reserve now 80 %" or "Plan reserve now unknown (why)"; null while the plan's reserve is not shown. */
  planText: string | null;
  /** true: the target is above the reserve the plan will use for the owner's value (rounded up), so Prepare for power cut can raise it; false: it cannot; null: not known. */
  canRaise: boolean | null;
}

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
  /** Prepare for power cut only: the reserve now and the power cut target, side by side. null for the other kinds. */
  reserve: ReserveVM | null;
}

export interface ControlsVM {
  kinds: KindControlVM[];
  /** What exists in Home Assistant (scripts, switch, sensors, guarded Dump start), from the states. */
  install: InstallVM;
  /** The short status above the controls: ready, needs the confirmation switch, or really not installed. */
  readiness: ReadinessVM;
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
  /** The card's `dump_to_grid.guarded_start` script id, if it names one (its existence is looked for in the states). */
  guardedStart?: string | null;
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

/** The two plan sensors the installed backend publishes (home-assistant/packages/ecco_plan_helpers.yaml); the guarded Dump to Grid start reads both. */
export const BACKEND_SENSOR_IDS = {
  effective_reserve: "sensor.ecco_plan_effective_reserve",
  export_hold: "sensor.ecco_plan_export_hold",
} as const;

/** What exists in the states. Pure: a missing entity is absent, whatever its value would have been. */
export function readInstall(states: StatesLike, guardedStart: string | null | undefined): InstallVM {
  const has = (id: string): boolean => states[id] !== undefined;
  const startScript = has(PLAN_CONTROL_IDS.start_script);
  const cancelScript = has(PLAN_CONTROL_IDS.cancel_script);
  const confirmationSwitch = has(HELPER_IDS.confirmed);
  const effectiveReserve = has(BACKEND_SENSOR_IDS.effective_reserve);
  const exportHold = has(BACKEND_SENSOR_IDS.export_hold);
  const guardedId = typeof guardedStart === "string" && guardedStart !== "" ? guardedStart : null;
  const guardedDump: InstallVM["guardedDump"] = guardedId === null ? "not_configured" : has(guardedId) ? "installed" : "missing";
  const missing: string[] = [];
  if (!startScript) missing.push(PLAN_CONTROL_IDS.start_script);
  if (!cancelScript) missing.push(PLAN_CONTROL_IDS.cancel_script);
  if (!confirmationSwitch) missing.push(HELPER_IDS.confirmed);
  if (!effectiveReserve) missing.push(BACKEND_SENSOR_IDS.effective_reserve);
  if (!exportHold) missing.push(BACKEND_SENSOR_IDS.export_hold);
  if (guardedDump === "missing" && guardedId !== null) missing.push(guardedId);
  return { startScript, cancelScript, confirmationSwitch, effectiveReserve, exportHold, guardedDump, missing };
}

export const READY_TEXT = "Overrides ready.";
export const READY_GAPS_LEAD = "Overrides only partly ready.";
export const CONFIRM_TEXT = "Turn on the confirmation switch: override limits reviewed and confirmed.";

/**
 * One short, truthful status line: say "not installed" only when BOTH guarded scripts are really absent, name the one that is missing when only one is, and say
 * "Overrides ready." only when nothing the controls rely on is missing or unreadable. `revisionReason` is why the stored plan revision cannot be read, or null when
 * it can be (the installed start script refuses every start while it cannot).
 */
export function readinessOf(install: InstallVM, confirmed: boolean | null, startPolicy: { ok: boolean; reasons?: readonly string[] }, revisionReason: string | null): ReadinessVM {
  if (!install.startScript && !install.cancelScript) {
    return { kind: "not_installed", text: "Overrides are not installed: the guarded scripts (" + PLAN_CONTROL_IDS.start_script + ", " + PLAN_CONTROL_IDS.cancel_script + ") were not found." };
  }
  if (!install.startScript || !install.cancelScript) {
    const gone = !install.startScript ? PLAN_CONTROL_IDS.start_script : PLAN_CONTROL_IDS.cancel_script;
    return { kind: "partial", text: "Only part of the override package is installed: " + gone + " was not found, so overrides cannot be started or cancelled here." };
  }
  if (confirmed === false) return { kind: "needs_confirmation", text: CONFIRM_TEXT };
  if (confirmed === null) return { kind: "confirmation_unreadable", text: "The confirmation switch (override limits reviewed and confirmed) cannot be read, so no override can be started." };
  if (!startPolicy.ok) return { kind: "limits_unusable", text: "The override limits are not usable: " + ((startPolicy.reasons && startPolicy.reasons[0]) || "see the limits below.") };
  if (revisionReason !== null) return { kind: "revision_unreadable", text: revisionReason.replace(/\.$/, "") + ", so no override can be started." };
  const gaps: string[] = [];
  if (!install.effectiveReserve) gaps.push("the effective-reserve sensor");
  if (!install.exportHold) gaps.push("the export-hold sensor");
  if (install.guardedDump === "missing") gaps.push("the guarded Dump to Grid start script");
  return gaps.length ? { kind: "ready_with_gaps", text: READY_GAPS_LEAD + " Not found: " + gaps.join(", ") + "." } : { kind: "ready", text: READY_TEXT };
}

/** The reserve ECCO's plan uses now, read from the installed effective-reserve sensor by its own rule (a whole percent from 0 to 100); anything else is unknown. */
export function readPlanReserve(states: StatesLike): PlanReserveReading {
  const id = BACKEND_SENSOR_IDS.effective_reserve;
  if (states[id] === undefined) return { known: false, value: null, reason: "the effective-reserve sensor was not found" };
  if (stateText(states, id) === null) return { known: false, value: null, reason: "the effective-reserve sensor cannot be read" };
  const n = stateNumber(states, id);
  if (n === null || n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX) return { known: false, value: null, reason: "the effective-reserve sensor does not read a percentage from " + CURRENT_RESERVE_MIN + " to " + CURRENT_RESERVE_MAX };
  return { known: true, value: n, reason: "" };
}

/**
 * The reserve now and the power cut target, kept apart. The target is the policy value (10 to 100); the reserve now is read by the backend's own rule (0 to 100).
 * `plan` is the reserve ECCO's plan uses now, passed only when it is to be shown beside the owner's (an override record is held, or it differs from the owner's):
 * the owner's figure is then labelled "Your reserve" so that the two cannot be mistaken for one another. The target must be above the owner's reserve ROUNDED UP,
 * because the installed effective-reserve sensor rounds the owner's value up (79.5 is published as 80), so a target of 80 over it raises nothing.
 */
export function reserveVM(nowPct: number | null, nowReason: string, targetPct: number | null, targetReason: string, plan: PlanReserveReading | null = null): ReserveVM {
  const canRaise = nowPct !== null && targetPct !== null ? targetPct > Math.ceil(nowPct) : null;
  const label = plan !== null ? "Your reserve" : "Reserve now";
  return {
    nowPct,
    nowReason,
    targetPct,
    targetReason,
    planPct: plan !== null && plan.known ? plan.value : null,
    planReason: plan !== null && !plan.known ? plan.reason : "",
    nowText: nowPct !== null ? label + " " + nowPct + " %" : label + " unknown (" + nowReason + ")",
    targetText: targetPct !== null ? "Power cut target " + targetPct + " %" : "Power cut target unknown (" + targetReason + ")",
    planText: plan === null ? null : plan.known ? "Plan reserve now " + plan.value + " %" : "Plan reserve now unknown (" + plan.reason + ")",
    canRaise,
  };
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
  const install = readInstall(ctx.states, ctx.guardedStart);
  const readiness = readinessOf(install, h.confirmed, h.startPolicy.ok ? { ok: true } : { ok: false, reasons: h.startPolicy.reasons }, h.revision.known ? null : h.revision.reason);
  const reserveNow = ctx.snap.currentReserve;
  // The reserve ECCO's plan uses is shown beside the owner's while any override record is held (it can then be above the owner's), or whenever the installed
  // sensor reads a figure that differs from the owner's (for example the owner's 79.5 rounded up to 80); otherwise the owner's reserve stands alone.
  const planRead = readPlanReserve(ctx.states);
  const showPlanReserve = h.active.length > 0 || h.held.length > 0 || (planRead.known && (currentReservePct === null || planRead.value !== currentReservePct));
  const reservePair = reserveVM(currentReservePct, reserveNow ? reserveNow.reason : "The backup reserve cannot be read.", startCfg ? startCfg.cutReservePct : null, "the override limits are not usable", showPlanReserve ? planRead : null);
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
      // The installed backend allows a target equal to the reserve now, or between the owner's value and that value rounded up (it raises nothing: the
      // effective-reserve sensor rounds the owner's reserve UP); the card offers only a start that RAISES it.
      else if (kind === "prepare_power_cut" && reservePair.canRaise === false) {
        const now = reservePair.nowPct as number;
        const used = Math.ceil(now);
        blockedReason = "The power cut target (" + reservePair.targetPct + " %) is not above the reserve now (" + now + " %" + (used === now ? "" : ", which the plan uses as " + used + " %") + "), so it cannot raise the reserve.";
      }
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
      reserve: kind === "prepare_power_cut" ? reservePair : null,
    };
  });
  return { kinds, install, readiness, lastResult: last, missingScripts };
}
