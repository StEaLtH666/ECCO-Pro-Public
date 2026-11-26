// Canonical settings model shared by the two master actions (Charge Battery, Export to Grid).
//
// Pure data in, data out. Nothing here writes anything: the reducer returns a new settings object plus the dependent preview
// updates every other view should show. A field is labelled APPLIED_VERIFIED only when a read-back value equals it.
import { onGrid } from "./time.ts";

/** Who may set a field's INTENDED value. owner > intelligence (a proposal only, adopted by the owner) > native (observed only). */
export type Source = "owner" | "intelligence" | "native";
export const SOURCE_RANK: Readonly<Record<Source, number>> = Object.freeze({ owner: 3, intelligence: 2, native: 1 });

export type FieldState = "PROPOSED" | "ARMED" | "EXECUTING" | "APPLIED_VERIFIED" | "MISMATCH";
/** Weakest first: a view built from several fields shows the weakest of their states. */
export const STATE_ORDER: readonly FieldState[] = ["MISMATCH", "PROPOSED", "ARMED", "EXECUTING", "APPLIED_VERIFIED"];

export type ViewId = "charge-card" | "export-card" | "tou-table" | "tomorrow-plan" | "reserve-summary";

export interface FieldDef {
  readonly label: string;
  readonly unit: string;
  readonly min: number;
  readonly max: number;
  readonly step: number;
  /** minute-of-day field: must sit on the 5-minute grid instead of using min/max/step. */
  readonly time?: true;
  readonly views: readonly ViewId[];
}

export const LIMITS = Object.freeze({
  slots: 6,
  minSlotMin: 5,
  bufferMin: 0,
  bufferMax: 120,
  stopSocMin: 10,
  stopSocMax: 90,
  chargeTargetMin: 20,
  chargeTargetMax: 100,
  chargePowerMin: 500,
  chargePowerMax: 8000,
  exportPowerMin: 500,
  /** Hardware-tested export ceiling; a higher value needs separate evidence and an owner decision. */
  exportPowerMax: 3000,
  exportDurationMin: 10,
  exportDurationMax: 240,
  reserveMin: 10,
  reserveMax: 100,
});

export const FIELD_DEFS = {
  "charge.targetSoc": { label: "Charge target", unit: "%", min: LIMITS.chargeTargetMin, max: LIMITS.chargeTargetMax, step: 1, views: ["charge-card", "tou-table", "tomorrow-plan"] },
  "charge.bufferMin": { label: "Finish before the window ends", unit: "min", min: LIMITS.bufferMin, max: LIMITS.bufferMax, step: 5, views: ["charge-card", "tomorrow-plan"] },
  "charge.powerW": { label: "Maximum charge power", unit: "W", min: LIMITS.chargePowerMin, max: LIMITS.chargePowerMax, step: 100, views: ["charge-card", "tou-table", "tomorrow-plan"] },
  "charge.windowStartMin": { label: "Charge window start", unit: "", min: 0, max: 1439, step: 5, time: true, views: ["charge-card", "export-card", "tou-table", "tomorrow-plan"] },
  "charge.windowEndMin": { label: "Charge window end", unit: "", min: 0, max: 1439, step: 5, time: true, views: ["charge-card", "export-card", "tou-table", "tomorrow-plan"] },
  "export.stopSoc": { label: "Export down to (Stop SOC)", unit: "%", min: LIMITS.stopSocMin, max: LIMITS.stopSocMax, step: 1, views: ["export-card", "tou-table", "tomorrow-plan", "reserve-summary"] },
  "export.powerW": { label: "Export power", unit: "W", min: LIMITS.exportPowerMin, max: LIMITS.exportPowerMax, step: 100, views: ["export-card", "tou-table", "tomorrow-plan"] },
  "export.startMin": { label: "Export start", unit: "", min: 0, max: 1439, step: 5, time: true, views: ["export-card", "charge-card", "tou-table", "tomorrow-plan"] },
  "export.durationMin": { label: "Export duration", unit: "min", min: LIMITS.exportDurationMin, max: LIMITS.exportDurationMax, step: 5, views: ["export-card", "charge-card", "tou-table", "tomorrow-plan"] },
  "reserve.backupPct": { label: "Backup reserve (enforced)", unit: "%", min: LIMITS.reserveMin, max: LIMITS.reserveMax, step: 1, views: ["charge-card", "export-card", "reserve-summary", "tomorrow-plan"] },
  "reserve.planningPct": { label: "Planning reserve (advice)", unit: "%", min: LIMITS.reserveMin, max: LIMITS.reserveMax, step: 1, views: ["reserve-summary", "tomorrow-plan"] },
} as const satisfies Record<string, FieldDef>;

export type FieldPath = keyof typeof FIELD_DEFS;
export const FIELD_PATHS = Object.freeze(Object.keys(FIELD_DEFS) as FieldPath[]);

export interface FieldRecord {
  /** The INTENDED value. */
  value: number;
  source: Source;
  /** The settings-wide revision at which this field last changed. */
  revision: number;
  state: FieldState;
  /** The last read-back from the native side, or null if never read / unreadable. */
  observed: number | null;
  /** An Intelligence proposal waiting for the owner. Never becomes the value without an owner action. */
  proposal: { value: number; revision: number } | null;
  /** A native value that differs from the intended one after having been seen to change: held, never clobbered. */
  external: { value: number; revision: number } | null;
}

export interface PlanSettings {
  /** Durable, strictly increasing: bumped by every accepted change. */
  revision: number;
  fields: Record<FieldPath, FieldRecord>;
}

export type PlanValues = Record<FieldPath, number>;

export type ValidateResult = { ok: true; value: number } | { ok: false; error: string };

export function validateField(path: string, raw: unknown): ValidateResult {
  if (!Object.prototype.hasOwnProperty.call(FIELD_DEFS, path)) return { ok: false, error: "Unknown setting." };
  const def: FieldDef = FIELD_DEFS[path as FieldPath];
  if (typeof raw !== "number" || !Number.isFinite(raw)) return { ok: false, error: def.label + " needs a number." };
  if (def.time) {
    return onGrid(raw) ? { ok: true, value: raw } : { ok: false, error: def.label + " must be a time on the 5-minute grid." };
  }
  if (raw < def.min) {
    if (path === "export.stopSoc") return { ok: false, error: "Stop SOC below " + def.min + " % is not available and is refused, not clamped." };
    return { ok: false, error: def.label + " must be at least " + def.min + (def.unit ? " " + def.unit : "") + "." };
  }
  if (raw > def.max) {
    if (path === "export.stopSoc") return { ok: false, error: "Stop SOC above " + def.max + " % is not available and is refused, not clamped." };
    return { ok: false, error: def.label + " can be at most " + def.max + (def.unit ? " " + def.unit : "") + "." };
  }
  const steps = (raw - def.min) / def.step;
  if (Math.abs(steps - Math.round(steps)) > 1e-9) return { ok: false, error: def.label + " moves in steps of " + def.step + (def.unit ? " " + def.unit : "") + "." };
  return { ok: true, value: raw };
}

/** Build settings from explicit values (there are deliberately no site defaults in this package). Every value is validated. */
export function createSettings(values: PlanValues, source: Source = "owner"): PlanSettings {
  const fields = {} as Record<FieldPath, FieldRecord>;
  for (const path of FIELD_PATHS) {
    const v = validateField(path, values[path]);
    if (!v.ok) throw new Error(path + ": " + v.error);
    fields[path] = { value: v.value, source, revision: 1, state: "PROPOSED", observed: null, proposal: null, external: null };
  }
  return { revision: 1, fields };
}

export type SettingsAction =
  | { type: "edit"; path: FieldPath; value: number; source: "owner" | "intelligence"; expectedRevision?: number }
  | { type: "adopt-proposal"; path: FieldPath }
  | { type: "dismiss-proposal"; path: FieldPath }
  | { type: "arm"; path: FieldPath }
  | { type: "disarm"; path: FieldPath }
  | { type: "begin"; path: FieldPath }
  | { type: "fail"; path: FieldPath }
  | { type: "readback"; path: FieldPath; observed: number | null }
  | { type: "resolve-external"; path: FieldPath; choice: "adopt-native" | "keep-intended" };

export interface DependentUpdate {
  readonly view: ViewId;
  readonly path: FieldPath;
  readonly kind: "value" | "proposal" | "external";
  readonly value: number;
  readonly state: FieldState;
  /** True until the value is APPLIED_VERIFIED: a view must label it a preview, never "applied". */
  readonly preview: boolean;
}

export interface ReduceResult {
  ok: boolean;
  settings: PlanSettings;
  error?: string;
  updates: DependentUpdate[];
}

function clone(s: PlanSettings): PlanSettings {
  return JSON.parse(JSON.stringify(s)) as PlanSettings;
}

function refuse(settings: PlanSettings, error: string): ReduceResult {
  return { ok: false, settings, error, updates: [] };
}

function updatesFor(path: FieldPath, rec: FieldRecord, kind: DependentUpdate["kind"]): DependentUpdate[] {
  const value = kind === "proposal" ? rec.proposal?.value : kind === "external" ? rec.external?.value : rec.value;
  if (value === undefined) return [];
  const def: FieldDef = FIELD_DEFS[path];
  return def.views.map((view) => ({ view, path, kind, value, state: rec.state, preview: rec.state !== "APPLIED_VERIFIED" }));
}

export function reduceSettings(settings: PlanSettings, action: SettingsAction): ReduceResult {
  if (!Object.prototype.hasOwnProperty.call(FIELD_DEFS, action.path)) return refuse(settings, "Unknown setting.");
  const next = clone(settings);
  const rec = next.fields[action.path];
  const bump = () => ++next.revision;

  switch (action.type) {
    case "edit": {
      if (action.expectedRevision !== undefined && action.expectedRevision !== settings.revision) {
        return refuse(settings, "The settings changed (revision " + settings.revision + ") since this edit was prepared; reload and review.");
      }
      const v = validateField(action.path, action.value);
      if (!v.ok) return refuse(settings, v.error);
      if (rec.state === "EXECUTING") return refuse(settings, "An apply is in progress for this setting; it cannot be edited until it ends.");
      if (rec.external) return refuse(settings, "The native side was changed outside ECCO; resolve that first (adopt it or keep the intended value).");
      if (action.source === "intelligence") {
        if (v.value === rec.value) return { ok: true, settings, updates: [] };
        rec.proposal = { value: v.value, revision: bump() };
        return { ok: true, settings: next, updates: updatesFor(action.path, rec, "proposal") };
      }
      if (v.value === rec.value && rec.source === "owner") return { ok: true, settings, updates: [] };
      rec.value = v.value;
      rec.source = "owner";
      rec.revision = bump();
      rec.state = rec.observed === v.value ? "APPLIED_VERIFIED" : "PROPOSED";
      if (rec.proposal && rec.proposal.value === v.value) rec.proposal = null;
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    case "adopt-proposal": {
      if (!rec.proposal) return refuse(settings, "There is no Intelligence proposal to adopt.");
      if (rec.state === "EXECUTING") return refuse(settings, "An apply is in progress for this setting.");
      if (rec.external) return refuse(settings, "Resolve the external native change first.");
      rec.value = rec.proposal.value;
      rec.source = "intelligence";
      rec.proposal = null;
      rec.revision = bump();
      rec.state = rec.observed === rec.value ? "APPLIED_VERIFIED" : "PROPOSED";
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    case "dismiss-proposal": {
      if (!rec.proposal) return refuse(settings, "There is no Intelligence proposal to dismiss.");
      rec.proposal = null;
      bump();
      return { ok: true, settings: next, updates: [] };
    }
    case "arm": {
      if (rec.external) return refuse(settings, "Resolve the external native change before arming.");
      if (rec.state !== "PROPOSED" && rec.state !== "MISMATCH") return refuse(settings, "Only a proposed or mismatched setting can be armed (it is " + rec.state + ").");
      rec.state = "ARMED";
      bump();
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    case "disarm": {
      if (rec.state !== "ARMED") return refuse(settings, "Only an armed setting can be disarmed.");
      rec.state = "PROPOSED";
      bump();
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    case "begin": {
      if (rec.external) return refuse(settings, "Resolve the external native change before executing.");
      if (rec.state !== "ARMED") return refuse(settings, "Only an armed setting can start executing.");
      rec.state = "EXECUTING";
      bump();
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    case "fail": {
      if (rec.state !== "EXECUTING") return refuse(settings, "Only an executing setting can fail.");
      rec.state = "MISMATCH";
      bump();
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    case "readback": {
      const prev = rec.observed;
      const obs = action.observed;
      if (obs !== null && !Number.isFinite(obs)) return refuse(settings, "A read-back must be a finite number or null.");
      if (obs === prev) return { ok: true, settings, updates: [] };
      rec.observed = obs;
      if (obs === null) {
        // Unreadable: it can no longer be claimed as applied.
        if (rec.state === "APPLIED_VERIFIED") rec.state = "PROPOSED";
      } else if (obs === rec.value) {
        rec.state = "APPLIED_VERIFIED";
        rec.external = null;
      } else if (rec.state === "EXECUTING") {
        rec.state = "MISMATCH";
      } else if (rec.state === "APPLIED_VERIFIED" || rec.state === "MISMATCH" || (prev !== null && prev !== obs)) {
        // Someone else changed the native side. Hold it; never clobber, never adopt silently.
        rec.external = { value: obs, revision: next.revision + 1 };
        if (rec.state === "APPLIED_VERIFIED") rec.state = "MISMATCH";
      }
      bump();
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, rec.external ? "external" : "value") };
    }
    case "resolve-external": {
      if (!rec.external) return refuse(settings, "There is no external change to resolve.");
      if (action.choice === "adopt-native") {
        const v = validateField(action.path, rec.external.value);
        if (!v.ok) return refuse(settings, "The native value is outside what ECCO accepts (" + v.error + ") and cannot be adopted; keep the intended value.");
        rec.value = rec.external.value;
        rec.source = "native";
        rec.observed = rec.external.value;
        rec.state = "APPLIED_VERIFIED";
      } else {
        rec.state = "PROPOSED";
      }
      rec.external = null;
      rec.revision = bump();
      return { ok: true, settings: next, updates: updatesFor(action.path, rec, "value") };
    }
    default:
      return refuse(settings, "Unknown action.");
  }
}

/** The weakest state among the named fields (what a view built from them may honestly claim). */
export function weakestState(settings: PlanSettings, paths: readonly FieldPath[]): FieldState {
  let worst = STATE_ORDER.length - 1;
  for (const p of paths) worst = Math.min(worst, STATE_ORDER.indexOf(settings.fields[p].state));
  return STATE_ORDER[worst] ?? "MISMATCH";
}

/** Intended values only (no state): the input the planners and compiler take. */
export function valuesOf(settings: PlanSettings): PlanValues {
  const out = {} as PlanValues;
  for (const p of FIELD_PATHS) out[p] = settings.fields[p].value;
  return out;
}

export function serializeSettings(settings: PlanSettings): string {
  return JSON.stringify(settings);
}

/** Parse and validate a stored copy. Throws on anything malformed: a corrupt record must not become a plan. */
export function parseSettings(text: string): PlanSettings {
  const raw = JSON.parse(text) as PlanSettings;
  if (!raw || typeof raw !== "object" || !Number.isInteger(raw.revision) || raw.revision < 1) throw new Error("bad revision");
  for (const p of FIELD_PATHS) {
    const f = raw.fields?.[p];
    if (!f) throw new Error("missing field " + p);
    const v = validateField(p, f.value);
    if (!v.ok) throw new Error(p + ": " + v.error);
    if (!STATE_ORDER.includes(f.state) || !(f.source in SOURCE_RANK)) throw new Error(p + ": bad state or source");
    if (!Number.isInteger(f.revision) || f.revision > raw.revision) throw new Error(p + ": bad revision");
    if (f.state === "APPLIED_VERIFIED" && f.observed !== f.value) throw new Error(p + ": APPLIED_VERIFIED without a matching read-back");
  }
  return raw;
}
