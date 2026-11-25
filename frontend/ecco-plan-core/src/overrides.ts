// Quick overrides: Hold battery, Skip tonight, Prepare for power cut.
//
// Each is scheduling-only: it changes what ECCO may START, never the native TOU table, never a running lease, and never lowers
// any reserve (raise-only). Each has a mandatory, bounded expiry. The default expiry, the caps and the power-cut reserve are
// owner choices and are passed in as a policy; nothing here hard-codes them.
import { LIMITS } from "./settings.ts";

export type OverrideKind = "hold_battery" | "skip_tonight" | "prepare_power_cut";
export const OVERRIDE_KINDS: readonly OverrideKind[] = ["hold_battery", "skip_tonight", "prepare_power_cut"];

export interface OverridePolicy {
  /** No override shorter than this is accepted (there is no open-ended override and no near-zero one). */
  minExpiryMin: number;
  defaultExpiryMin: Readonly<Record<OverrideKind, number>>;
  maxExpiryMin: Readonly<Record<OverrideKind, number>>;
  /** The reserve Prepare for power cut raises to (never lowers). */
  powerCutReservePct: number;
}

export interface ActiveOverride {
  kind: OverrideKind;
  /** Absolute minutes on any monotonic scale the caller chooses (for example epoch minutes). */
  startedAtMin: number;
  expiresAtMin: number;
  /** Only for prepare_power_cut. */
  reservePct?: number;
}

/**
 * A stable reason for a refused start. The guarded Home Assistant scripts (home-assistant/packages/ecco_plan_helpers.yaml) answer with the
 * SAME codes, and a parity table (test/parity/override_parity_cases.json) proves both sides give the same answer for the same case.
 */
export type RefusalCode =
  | "POLICY_UNCONFIRMED"
  | "POLICY_INVALID"
  | "UNKNOWN_KIND"
  | "EXPIRY_NOT_WHOLE"
  | "RESERVE_UNKNOWN"
  | "RESERVE_BELOW_CURRENT"
  | "TIME_UNKNOWN"
  | "EXPIRY_MISSING"
  | "EXPIRY_BELOW_MIN"
  | "EXPIRY_ABOVE_CAP"
  | "POWER_CUT_RESERVE_RANGE"
  | "EXPIRY_ABOVE_CEILING";

export type StartResult = { ok: true; override: ActiveOverride } | { ok: false; error: string; code: RefusalCode };

export function startOverride(kind: OverrideKind, nowMin: number, expiryMin: number | null | undefined, policy: OverridePolicy): StartResult {
  if (!OVERRIDE_KINDS.includes(kind)) return { ok: false, error: "Unknown override.", code: "UNKNOWN_KIND" };
  if (!Number.isFinite(nowMin)) return { ok: false, error: "The current time is unknown; an override cannot be started without it.", code: "TIME_UNKNOWN" };
  const expiry = expiryMin ?? policy.defaultExpiryMin[kind];
  if (typeof expiry !== "number" || !Number.isFinite(expiry)) return { ok: false, error: "An override needs an expiry; there is no open-ended override.", code: "EXPIRY_MISSING" };
  if (expiry < policy.minExpiryMin) return { ok: false, error: "The expiry must be at least " + policy.minExpiryMin + " minutes.", code: "EXPIRY_BELOW_MIN" };
  const cap = policy.maxExpiryMin[kind];
  if (expiry > cap) return { ok: false, error: "The expiry can be at most " + cap + " minutes for this override.", code: "EXPIRY_ABOVE_CAP" };
  const o: ActiveOverride = { kind, startedAtMin: nowMin, expiresAtMin: nowMin + expiry };
  if (kind === "prepare_power_cut") {
    const r = policy.powerCutReservePct;
    if (!Number.isFinite(r) || r < LIMITS.reserveMin || r > LIMITS.reserveMax) return { ok: false, error: "The power-cut reserve must be " + LIMITS.reserveMin + "-" + LIMITS.reserveMax + " %.", code: "POWER_CUT_RESERVE_RANGE" };
    o.reservePct = r;
  }
  return { ok: true, override: o };
}

/** What the plan allows ECCO to start, and the reserve it must respect. */
export interface PlanView {
  startsAllowed: { charge: boolean; export: boolean };
  /** Discretionary charge-rate edits (the gentle planner's proposals). */
  discretionaryRateEdits: boolean;
  backupReservePct: number;
  exportStopSoc: number;
}

/** A lease that is already running. It is passed through untouched; overrides only affect future starts. */
export interface RunningLease {
  action: "charge" | "export";
  [k: string]: unknown;
}

export interface OverrideChange {
  field: "startsAllowed.export" | "discretionaryRateEdits" | "backupReservePct" | "exportStopSoc";
  from: boolean | number;
  to: boolean | number;
}

export interface OverrideReport {
  kind: OverrideKind;
  status: "active" | "expired";
  changes: OverrideChange[];
  notes: string[];
}

export interface OverrideOutcome {
  view: PlanView;
  /** The same reference that was passed in: an override never alters a running lease. */
  lease: RunningLease | null;
  reports: OverrideReport[];
}

export function applyOverrides(view: PlanView, active: readonly ActiveOverride[], nowMin: number, lease: RunningLease | null = null): OverrideOutcome {
  const out: PlanView = { startsAllowed: { ...view.startsAllowed }, discretionaryRateEdits: view.discretionaryRateEdits, backupReservePct: view.backupReservePct, exportStopSoc: view.exportStopSoc };
  const reports: OverrideReport[] = [];

  const setExportOff = (r: OverrideReport) => {
    if (out.startsAllowed.export) {
      r.changes.push({ field: "startsAllowed.export", from: true, to: false });
      out.startsAllowed.export = false;
    }
  };

  for (const o of active) {
    const r: OverrideReport = { kind: o.kind, status: "active", changes: [], notes: [] };
    if (!(nowMin < o.expiresAtMin)) {
      r.status = "expired";
      r.notes.push("Expired: ECCO planning resumes; nothing was changed by this override.");
      reports.push(r);
      continue;
    }
    if (o.kind === "hold_battery") {
      setExportOff(r);
      if (out.discretionaryRateEdits) {
        r.changes.push({ field: "discretionaryRateEdits", from: true, to: false });
        out.discretionaryRateEdits = false;
      }
      r.notes.push("Scheduling only: the native TOU table and self-consumption are untouched.");
    } else if (o.kind === "skip_tonight") {
      setExportOff(r);
      r.notes.push("Holds tonight's export only; charging continues.");
    } else {
      setExportOff(r);
      const target = o.reservePct;
      if (typeof target === "number" && Number.isFinite(target)) {
        // Raise-only: max(), never a plain assignment.
        if (target > out.backupReservePct) {
          r.changes.push({ field: "backupReservePct", from: out.backupReservePct, to: target });
          out.backupReservePct = target;
        } else {
          r.notes.push("The reserve is already at or above " + target + " %; it is left as it is (never lowered).");
        }
        if (out.exportStopSoc < out.backupReservePct) {
          r.changes.push({ field: "exportStopSoc", from: out.exportStopSoc, to: out.backupReservePct });
          out.exportStopSoc = out.backupReservePct;
        }
      }
      r.notes.push("This does not prove that backup works.");
    }
    if (lease) r.notes.push("A running " + lease.action + " lease is not stopped or changed; this applies from the next start.");
    reports.push(r);
  }
  return { view: out, lease, reports };
}
