// Plan adapter (stage 2, READ ONLY): turns the entities this card and its sibling TOU card already read into the inputs of the
// pure plan core, and returns what the core derives. Pure: no DOM, no Lit, no clock, no service call. It cannot write anything;
// the only thing imported from the plan core is data-in/data-out functions.
//
// Honesty rules (each has a test):
//   * A setting is APPLIED_VERIFIED only where a read-back entity equals it (the dump session's latched export power / stop SOC while
//     a session runs, and the table's own grid-charge target). Nothing else is ever called verified.
//   * A value the card cannot read, or that the core would refuse, is listed as unknown with a reason and never shown as a number.
//   * Tomorrow's Plan comes only from the Intelligence advice entities; a missing figure is an explicit unknown.
//   * The six-slot table is compared with the six TOU slot entities exactly as the TOU settings card reads them.
import {
  FIELD_DEFS,
  FIELD_PATHS,
  buildTomorrowPlan,
  compileTou,
  createSettings,
  reduceSettings,
  validateField,
  validateTable,
} from "../../../ecco-plan-core/src/index.ts";
import type {
  ActiveOverride,
  CompileResult,
  DerivedInterval,
  FieldPath,
  IntelligenceAdvice,
  NativeSlot,
  PlanSettings,
  PlanValues,
  TomorrowPlan,
} from "../../../ecco-plan-core/src/index.ts";
import type { EccoEnergyActionsCardConfig, PlanConfig } from "../config";

export type StatesLike = Record<string, { state: string; attributes?: Record<string, unknown> } | undefined>;

/** The Intelligence contract's generic entity ids (public, device-slug free), used when `plan.advice` does not override them. */
export const DEFAULT_ADVICE_IDS = Object.freeze({
  status: "sensor.ecco_intel_status",
  charge_target: "sensor.ecco_intel_charge_target",
  export_event: "sensor.ecco_intel_export_event",
  pv_tomorrow: "sensor.ecco_intel_pv_tomorrow",
  fresh: "binary_sensor.ecco_intel_fresh",
  paused: "input_boolean.ecco_intel_paused",
});

export const SLOT_COUNT = 6;

// ---- state readers (same strictness as the TOU settings card: unavailable/unknown/blank is no value) ----------------------------
const DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const HHMM_RE = /^(\d{2}):(\d{2})$/;
const DATETIME_RE = /^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}$/;

export function stateText(states: StatesLike, id: string | undefined): string | null {
  if (!id) return null;
  const s = states[id]?.state;
  if (typeof s !== "string" || s === "" || s === "unavailable" || s === "unknown") return null;
  return s;
}

export function stateNumber(states: StatesLike, id: string | undefined): number | null {
  const s = stateText(states, id);
  if (s === null) return null;
  const t = s.trim();
  if (!DECIMAL_RE.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

const isOn = (states: StatesLike, id: string | undefined): boolean => stateText(states, id) === "on";

function parseHHMM(text: string | null): number | null {
  if (text === null) return null;
  const m = HHMM_RE.exec(text.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  return h > 23 || mi > 59 ? null : h * 60 + mi;
}

/** Minute of day of an input_datetime `YYYY-MM-DD HH:MM:SS` (Home Assistant's local wall time), or null. */
function minuteOfDatetime(text: string | null): number | null {
  if (text === null) return null;
  const m = DATETIME_RE.exec(text.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  return h > 23 || mi > 59 ? null : h * 60 + mi;
}

// ---- entity ids (the TOU settings card's own naming) --------------------------------------------------------------------------------
export function touSlotIds(prefix: string, slot: number) {
  const b = `sensor.${prefix}_ecco_timezone${slot}_`;
  return { time: `${b}time`, power: `${b}power`, soc: `${b}soc`, charge: `${b}charge` };
}

export function touOwnerIds(prefix: string) {
  return {
    fpActive: `binary_sensor.${prefix}_free_power_active`,
    fpOp: `binary_sensor.${prefix}_free_power_operation_in_progress`,
    fpSnapshot: `binary_sensor.${prefix}_free_power_snapshot_valid`,
    dgActive: `binary_sensor.${prefix}_dump_to_grid_active`,
    dgOp: `binary_sensor.${prefix}_dump_to_grid_operation_in_progress`,
    dgSnapshot: `binary_sensor.${prefix}_dump_to_grid_snapshot_valid`,
  };
}

// ---- output types ----------------------------------------------------------------------------------------------------------------
export type ChipState = "PROPOSED" | "ARMED" | "EXECUTING" | "APPLIED_VERIFIED" | "MISMATCH";

export interface FieldInfo {
  path: FieldPath;
  label: string;
  unit: string;
  /** false: the card cannot read this setting; `reason` says why and no number may be shown. */
  known: boolean;
  reason?: string;
  value: number;
  state: ChipState;
  source: string;
  observed: number | null;
  /** An Intelligence proposal that differs from the value, if any (never adopted here). */
  proposal: number | null;
  /** A plain-words remark the presenter shows beside a known value (for example why the plan's settings model holds no figure for it). */
  note?: string;
}

export interface TouSnapshot {
  /** All six slots were readable and the table is a valid six-slot day. */
  readable: boolean;
  /** Plain-words reason when not readable. */
  reason: string | null;
  observed: NativeSlot[] | null;
  /** null when not compiled (unreadable table). */
  compile: CompileResult | null;
  /** Why something was not placed in the table by this card, in plain words, beyond compile.reasons. */
  notes: string[];
}

export interface PlanSnapshot {
  settings: PlanSettings;
  fields: FieldInfo[];
  tomorrow: TomorrowPlan;
  tou: TouSnapshot;
  /** Always empty in stage 2: an override needs a plan helper that does not exist yet. */
  overrides: ActiveOverride[];
  /** The advice entities were readable and fresh. */
  adviceAvailable: boolean;
  adviceNote: string | null;
  /** The owner's CURRENT backup reserve as the installed backend reads it (a finite number from 0 to 100), never the plan's own 10 % floor. */
  currentReserve: CurrentReserve;
}

// ---- Tomorrow's Plan from the Intelligence advice entities ---------------------------------------------------------------
function attrs(states: StatesLike, id: string): Record<string, unknown> {
  const a = states[id]?.attributes;
  return a && typeof a === "object" ? a : {};
}

function finiteOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export interface AdviceRead {
  advice: IntelligenceAdvice | null;
  available: boolean;
  note: string | null;
  /** The advice's charge target proposal in %, if it states one. */
  chargeTargetPct: number | null;
}

export function readAdvice(states: StatesLike, ids: Record<keyof typeof DEFAULT_ADVICE_IDS, string>): AdviceRead {
  const none = (note: string): AdviceRead => ({ advice: null, available: false, note, chargeTargetPct: null });
  const status = stateText(states, ids.status);
  if (status === null) return none("The Intelligence advice is not available (its status cannot be read).");
  if (isOn(states, ids.paused)) return none("Intelligence is paused by the owner; it publishes no advice.");
  if (status !== "OK") return none("Intelligence status is " + status + "; it publishes no figures.");
  if (stateText(states, ids.fresh) !== "on") return none("The Intelligence advice is not fresh; it is not shown as a forecast.");

  const ct = ids.charge_target;
  const ctAdvice = attrs(states, ct)["advice"];
  const summary: Record<string, unknown> = ctAdvice && typeof ctAdvice === "object" && !Array.isArray(ctAdvice) ? (ctAdvice as Record<string, unknown>) : {};
  const confidence = attrs(states, ct)["confidence"];
  const why: string[] = [];
  const targetPct = stateNumber(states, ct);
  const binding = summary["binding_constraint"];
  if (targetPct !== null) why.push("Charge target advice " + targetPct + " %" + (typeof binding === "string" ? " (limited by " + binding.toLowerCase().replace(/_/g, " ") + ")" : "") + ".");
  if (summary["conservative_fallback"] === true) why.push("Not enough demand evidence yet, so Intelligence advises keeping the battery well charged.");
  const need = finiteOrNull(summary["net_need_kwh"]);
  if (need !== null) why.push("Net overnight need after solar credit: " + need.toFixed(1) + " kWh.");
  const blockers = attrs(states, ct)["blockers"];
  if (Array.isArray(blockers)) {
    for (const b of blockers.slice(0, 4)) {
      const t = b && typeof b === "object" ? (b as Record<string, unknown>)["text"] : null;
      if (typeof t === "string" && t.trim()) why.push("Blocked: " + t.trim());
    }
  }
  why.push("Import is the grid energy Intelligence plans for the overnight charge; it does not include daytime import.");

  const advice: IntelligenceAdvice = {
    expectedImportKwh: finiteOrNull(summary["grid_charge_kwh"]),
    expectedExportKwh: stateNumber(states, ids.export_event),
    expectedSolarKwh: stateNumber(states, ids.pv_tomorrow),
    // Intelligence publishes no finish time; the core then reports it unknown.
    chargeFinishMin: null,
    confidence: typeof confidence === "string" ? confidence : null,
    why,
  };
  return { advice, available: true, note: null, chargeTargetPct: targetPct };
}

// ---- the TOU table as the TOU settings card reads it ---------------------------------------------------------------------------
export function readTouTable(states: StatesLike, prefix: string): { table: NativeSlot[] | null; reason: string | null } {
  const slots: NativeSlot[] = [];
  const missing: string[] = [];
  for (let n = 1; n <= SLOT_COUNT; n++) {
    const ids = touSlotIds(prefix, n);
    const start = parseHHMM(stateText(states, ids.time));
    const power = stateNumber(states, ids.power);
    const soc = stateNumber(states, ids.soc);
    const src = stateText(states, ids.charge);
    const bad: string[] = [];
    if (start === null) bad.push("start time");
    if (power === null) bad.push("power");
    if (soc === null) bad.push("target SOC");
    if (src !== "Grid" && src !== "None") bad.push("charge source");
    if (bad.length) missing.push("slot " + n + " " + bad.join(", "));
    else slots.push({ startMin: start as number, powerW: power as number, targetSoc: soc as number, source: src as "Grid" | "None" });
  }
  if (missing.length) return { table: null, reason: "The six TOU slots cannot all be read (" + missing.join("; ") + "), so no comparison is possible." };
  const v = validateTable(slots);
  if (!v.ok) return { table: null, reason: "The inverter's six slots are not a valid six-slot day (" + (v as { why: string }).why + "), so no comparison is made." };
  return { table: slots, reason: null };
}

// ---- the owner's CURRENT backup reserve -----------------------------------------------------------------------------------------
/**
 * The owner's current backup reserve, read the way the installed backend reads it (home-assistant/packages/ecco_plan_helpers.yaml: the owner's
 * reserve helper is usable when it is a finite number from 0 to 100; the effective-reserve sensor rounds it up and takes the larger of it and
 * the running power-cut reserve). It is NOT the plan settings model's own reserve field (10 to 100, whole percents), which describes what the
 * planner may INTEND, and it is NOT the override's TARGET reserve (the policy value, 10 to 100): an override may only raise the current reserve
 * to its target, never lower it. A reserve of 5 % is a real, valid current reserve.
 */
export interface CurrentReserve {
  known: boolean;
  /** The reserve in percent when known, else null. */
  value: number | null;
  /** Why it is unknown, in plain words ("" when known). */
  reason: string;
}

export const CURRENT_RESERVE_MIN = 0;
export const CURRENT_RESERVE_MAX = 100;

export function readCurrentReserve(states: StatesLike, id: string | undefined): CurrentReserve {
  if (!id) return { known: false, value: null, reason: "No backup reserve entity is configured (plan.reserve)." };
  if (states[id] === undefined) return { known: false, value: null, reason: "The backup reserve entity was not found, so the reserve now is not known." };
  const text = stateText(states, id);
  if (text === null) return { known: false, value: null, reason: "The backup reserve cannot be read." };
  const n = stateNumber(states, id);
  if (n === null) return { known: false, value: null, reason: "The backup reserve (" + text.trim().slice(0, 24) + ") is not a number, so it is not used." };
  if (n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX) {
    return { known: false, value: null, reason: "The backup reserve reads " + n + ", which is not a percentage from " + CURRENT_RESERVE_MIN + " to " + CURRENT_RESERVE_MAX + ", so it is not used." };
  }
  return { known: true, value: n, reason: "" };
}

// ---- settings ---------------------------------------------------------------------------------------------------------------------
interface Raw {
  value: number | null;
  reason: string;
  observed: number | null;
}

function checked(path: FieldPath, raw: number | null, reason: string, observed: number | null = null): Raw {
  if (raw === null) return { value: null, reason, observed: null };
  const v = validateField(path, raw);
  if (!v.ok) return { value: null, reason: "The value " + raw + " is outside what ECCO accepts (" + v.error + ")", observed: null };
  return { value: v.value, reason: "", observed };
}

export function buildPlanSnapshot(config: EccoEnergyActionsCardConfig, states: StatesLike): PlanSnapshot {
  const plan: PlanConfig = config.plan ?? {};
  const fp = config.free_power;
  const fpSched = config.schedule;
  const dg = config.dump_to_grid;
  const dgSched = dg?.schedule;
  const prefix = plan.entity_prefix;
  const adviceIds = { ...DEFAULT_ADVICE_IDS, ...(plan.advice ?? {}) } as Record<keyof typeof DEFAULT_ADVICE_IDS, string>;

  const read = readAdvice(states, adviceIds);
  const touRead = prefix ? readTouTable(states, prefix) : { table: null, reason: "No TOU slot prefix is configured (plan.entity_prefix), so the six slots are not read." };
  const table = touRead.table;

  // The native grid-charge slot (exactly one, else its target SOC is not stated).
  const gridSlots = table ? table.filter((s) => s.source === "Grid") : [];
  const nativeCharge = gridSlots.length === 1 ? (gridSlots[0] as NativeSlot) : null;

  const raw = {} as Record<FieldPath, Raw>;
  for (const p of FIELD_PATHS) raw[p] = { value: null, reason: "This card has no entity for it.", observed: null };

  // Charge Battery action = the card's Free Power session and its schedule helpers.
  const fpStartMin = fpSched ? minuteOfDatetime(stateText(states, fpSched.start)) : null;
  const fpDur = fpSched ? stateNumber(states, fpSched.duration) : null;
  const chargePower = fpSched ? stateNumber(states, fpSched.power) : fp ? stateNumber(states, fp.max_charge_power) : null;
  raw["charge.powerW"] = checked("charge.powerW", chargePower, "The charge power cannot be read.");
  raw["charge.windowStartMin"] = checked("charge.windowStartMin", fpStartMin, fpSched ? "The scheduled charge start cannot be read." : "No schedule is configured, so there is no charge window.");
  let fpEnd: number | null = null;
  if (fpStartMin !== null && fpDur !== null && Number.isInteger(fpDur) && fpDur > 0 && fpDur < 1440) fpEnd = (fpStartMin + fpDur) % 1440;
  raw["charge.windowEndMin"] = checked("charge.windowEndMin", fpEnd, fpSched ? "The scheduled charge end cannot be worked out (start or duration unreadable, or not on the 5-minute grid)." : "No schedule is configured, so there is no charge window.");
  raw["charge.targetSoc"] = checked("charge.targetSoc", nativeCharge ? nativeCharge.targetSoc : null, "The charge target is not stated: the inverter table has no single grid-charge slot to read it from.", nativeCharge ? nativeCharge.targetSoc : null);
  raw["charge.bufferMin"] = { value: null, reason: "No finish-before-window-end buffer is set by any entity this card reads.", observed: null };

  // Export to Grid action = the card's Dump to Grid session and its schedule helpers.
  const dgActive = dg ? isOn(states, dg.active) : false;
  const exportPower = dgSched ? stateNumber(states, dgSched.power) : dg ? stateNumber(states, dg.export_power) : null;
  const exportStop = dgSched ? stateNumber(states, dgSched.stop_soc) : dg ? stateNumber(states, dg.stop_soc) : null;
  const latchedPower = dg && dgActive ? stateNumber(states, dg.active_export_power) : null;
  const latchedStop = dg && dgActive ? stateNumber(states, dg.active_stop_soc) : null;
  const dgStart = dgSched ? minuteOfDatetime(stateText(states, dgSched.start)) : null;
  const dgDur = dgSched ? stateNumber(states, dgSched.duration) : dg ? stateNumber(states, dg.duration) : null;
  raw["export.powerW"] = checked("export.powerW", exportPower, "The export power cannot be read.", latchedPower);
  raw["export.stopSoc"] = checked("export.stopSoc", exportStop, "The Stop SOC cannot be read.", latchedStop);
  raw["export.startMin"] = checked("export.startMin", dgStart, dgSched ? "The scheduled export start cannot be read." : "No export schedule is configured, so there is no export start time.");
  raw["export.durationMin"] = checked("export.durationMin", dgDur, "The export duration cannot be read.");

  // Reserve: the backup reserve helper has no read-back, so it is never called verified. The planning reserve has no entity here.
  // The CURRENT reserve is read by the backend's rule (0 to 100), not by the planner's own field rule (10 to 100, whole percents). The planner's
  // settings model can only hold a value its own field accepts; a current reserve outside that (for example 5 %) is kept apart in
  // `currentReserve`, shown as it is, and the model keeps its inert placeholder for it.
  const currentReserve = readCurrentReserve(states, plan.reserve);
  raw["reserve.backupPct"] = currentReserve.known
    ? checked("reserve.backupPct", currentReserve.value, currentReserve.reason)
    : { value: null, reason: currentReserve.reason, observed: null };
  raw["reserve.planningPct"] = { value: null, reason: "Intelligence's planning reserve is not read by this card.", observed: null };

  // Canonical settings. A field this card cannot read holds the field's minimum as an inert placeholder; `known` is authoritative
  // and nothing downstream reads a placeholder (the presenter and reconcileTomorrow both consult it).
  const values = {} as PlanValues;
  for (const p of FIELD_PATHS) values[p] = raw[p].value !== null ? (raw[p].value as number) : FIELD_DEFS[p].min;
  let settings = createSettings(values, "owner");

  const fpArmed = fpSched ? isOn(states, fpSched.armed) : false;
  const fpActive = fp ? isOn(states, fp.active) : false;
  const dgArmed = dgSched ? isOn(states, dgSched.armed) : false;
  const chargeFields: FieldPath[] = ["charge.targetSoc", "charge.bufferMin", "charge.powerW", "charge.windowStartMin", "charge.windowEndMin"];
  const exportFields: FieldPath[] = ["export.stopSoc", "export.powerW", "export.startMin", "export.durationMin"];
  const step = (path: FieldPath, type: "arm" | "begin") => {
    const r = reduceSettings(settings, { type, path });
    if (r.ok) settings = r.settings;
  };
  const walk = (paths: FieldPath[], armed: boolean, active: boolean) => {
    for (const p of paths) {
      if (raw[p].value === null) continue;
      if (active) {
        step(p, "arm");
        step(p, "begin");
      } else if (armed) {
        step(p, "arm");
      }
    }
  };
  walk(chargeFields, fpArmed, fpActive);
  walk(exportFields, dgArmed, dgActive);
  // Read-backs last: equal -> APPLIED_VERIFIED; different while EXECUTING -> MISMATCH.
  for (const p of FIELD_PATHS) {
    const r = raw[p];
    if (r.value === null || r.observed === null) continue;
    const res = reduceSettings(settings, { type: "readback", path: p, observed: r.observed });
    if (res.ok) settings = res.settings;
  }

  // An Intelligence charge target different from the table's is only ever a proposal, never adopted here.
  let proposalPct: number | null = null;
  if (read.chargeTargetPct !== null && raw["charge.targetSoc"].value !== null && read.chargeTargetPct !== raw["charge.targetSoc"].value) {
    const res = reduceSettings(settings, { type: "edit", path: "charge.targetSoc", value: read.chargeTargetPct, source: "intelligence" });
    if (res.ok) {
      settings = res.settings;
      proposalPct = settings.fields["charge.targetSoc"].proposal?.value ?? null;
    }
  }

  const fields: FieldInfo[] = FIELD_PATHS.map((p) => {
    const r = raw[p];
    const rec = settings.fields[p];
    const def = FIELD_DEFS[p];
    if (p === "reserve.backupPct" && r.value === null && currentReserve.known && currentReserve.value !== null) {
      return {
        path: p,
        label: def.label,
        unit: def.unit,
        known: true,
        value: currentReserve.value,
        state: rec.state,
        source: rec.source,
        observed: null,
        proposal: null,
        note: "Read from your backup reserve helper. The plan's own settings model holds whole percents from " + def.min + " to " + def.max + " only, so it keeps no figure for this value; the installed overrides accept any reserve from " + CURRENT_RESERVE_MIN + " to " + CURRENT_RESERVE_MAX + " %.",
      };
    }
    return {
      path: p,
      label: def.label,
      unit: def.unit,
      known: r.value !== null,
      ...(r.value === null ? { reason: r.reason } : {}),
      value: rec.value,
      state: rec.state,
      source: rec.source,
      observed: rec.observed,
      proposal: p === "charge.targetSoc" ? proposalPct : null,
    };
  });

  // ---- six-slot table ----------------------------------------------------------------------------------------------------------
  const notes: string[] = [];
  let compile: CompileResult | null = null;
  if (table) {
    const intervals: DerivedInterval[] = [];
    const val = (p: FieldPath) => raw[p].value;
    if (fpArmed || fpActive) {
      const s = val("charge.windowStartMin");
      const pw = val("charge.powerW");
      const ts = val("charge.targetSoc");
      if (s === null || fpDur === null || pw === null || ts === null) {
        notes.push("The armed charge could not be placed in the table: " + (ts === null ? "its target SOC is unknown." : "its start, duration or power is unreadable."));
      } else {
        intervals.push({ action: "charge", startMin: s, durationMin: fpDur, targetSoc: ts, powerW: pw });
      }
    }
    if (dgArmed || dgActive) {
      const s = val("export.startMin");
      const pw = val("export.powerW");
      const ts = val("export.stopSoc");
      const du = val("export.durationMin");
      if (s === null || pw === null || ts === null || du === null) notes.push("The armed export could not be placed in the table: a start, duration, power or Stop SOC is unreadable.");
      else intervals.push({ action: "export", startMin: s, durationMin: du, targetSoc: ts, powerW: pw });
    }
    // Single writer: any Free Power / Dump session, start or owed restore owns the inverter, so nothing is compiled.
    let owner: string | null = null;
    const o = prefix ? touOwnerIds(prefix) : null;
    if ((o && (isOn(states, o.fpActive) || isOn(states, o.fpOp) || isOn(states, o.fpSnapshot))) || fpActive || (fp && (isOn(states, fp.operation_in_progress) || isOn(states, fp.snapshot_valid)))) owner = "Free Power";
    else if ((o && (isOn(states, o.dgActive) || isOn(states, o.dgOp) || isOn(states, o.dgSnapshot))) || dgActive || (dg && (isOn(states, dg.operation_in_progress) || isOn(states, dg.snapshot_valid)))) owner = "Dump to Grid";
    // The grid-loss lock is fail-safe: only an explicit "off" on a configured lock entity counts as unlocked.
    const lockOff = plan.control_lock ? stateText(states, plan.control_lock) === "off" : false;
    if (!lockOff && intervals.some((i) => i.action === "export")) {
      notes.push(plan.control_lock ? "Control is locked or its state is unreadable, so the export is not placed in the table (fail-safe)." : "No grid-loss lock state is configured (plan.control_lock), so an export is not placed in the table (fail-safe).");
    }
    compile = compileTou({ baseline: table, intervals, observed: table, lastApplied: null, transactionOwner: owner, controlLocked: !lockOff });
  }

  const tomorrow = reconcileTomorrow(buildTomorrowPlan({ advice: read.advice, settings }), fields, read);

  return {
    settings,
    fields,
    tomorrow,
    tou: { readable: table !== null, reason: touRead.reason, observed: table, compile, notes },
    overrides: [],
    adviceAvailable: read.available,
    adviceNote: read.note,
    currentReserve,
  };
}

/**
 * The core builds Tomorrow's Plan from the settings object, in which a field this card cannot read holds an inert placeholder.
 * Remove everything that would show a placeholder (the settings lines, and the reserve item when unknown) and put the reason a
 * piece of advice is withheld into the unknown figures.
 */
function reconcileTomorrow(t: TomorrowPlan, fields: FieldInfo[], read: AdviceRead): TomorrowPlan {
  const known = (p: FieldPath) => fields.find((f) => f.path === p)?.known === true;
  const reserveField = fields.find((f) => f.path === "reserve.backupPct");
  // A current reserve the planner's model cannot hold (outside its own 10 to 100 whole-percent field) is carried by the field, not by the model.
  const reserveOutsideModel = reserveField !== undefined && reserveField.known && reserveField.note !== undefined;
  const why = t.why
    .filter((w) => {
      if (w.origin !== "settings") return true;
      if (w.text.startsWith("Charge target ")) return known("charge.targetSoc");
      if (w.text.startsWith("Export stops at ")) return known("export.stopSoc");
      if (w.text.startsWith("Backup reserve ")) return known("reserve.backupPct");
      return true;
    })
    .map((w) => (w.origin === "settings" && w.text.startsWith("Backup reserve ") && reserveOutsideModel ? { ...w, text: "Backup reserve " + (reserveField as FieldInfo).value + " % (owner's helper, no read-back)." } : w));
  if (!known("charge.targetSoc")) why.push({ origin: "settings", text: "Charge target: unknown (no single grid-charge slot to read it from)." });
  if (!known("export.stopSoc")) why.push({ origin: "settings", text: "Export Stop SOC: unknown (not readable)." });
  if (!known("reserve.backupPct")) why.push({ origin: "settings", text: "Backup reserve: unknown (no entity configured or readable)." });
  const withhold = (item: TomorrowPlan["importKwh"]): TomorrowPlan["importKwh"] => (!item.known && read.note ? { ...item, reason: read.note } : item);
  const reserve: TomorrowPlan["reservePct"] = t.reservePct.known && !known("reserve.backupPct")
    ? { known: false, reason: fields.find((f) => f.path === "reserve.backupPct")?.reason ?? "Unknown.", state: "PROPOSED" }
    : t.reservePct.known && reserveOutsideModel
      ? { ...t.reservePct, value: (reserveField as FieldInfo).value }
      : t.reservePct;
  return { ...t, why, importKwh: withhold(t.importKwh), exportKwh: withhold(t.exportKwh), solarKwh: withhold(t.solarKwh), chargeFinishMin: withhold(t.chargeFinishMin), reservePct: reserve };
}
