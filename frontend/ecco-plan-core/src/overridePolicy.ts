// Override policy (stage 3 preparation): the owner's expiry durations, caps and power-cut reserve, validated into the OverridePolicy
// that overrides.ts takes. Pure data in, data out; it cannot write anything.
//
// Rules (each has tests):
//   * Every number is checked: finite, whole, on its step, inside the bounds below. The bounds are ALSO the bounds of the proposed
//     Home Assistant helpers (proposals/ecco_plan_helpers.proposal.yaml), so a helper cannot hold a value this module refuses.
//   * HARD CEILINGS: no helper value can lift a cap above EXPIRY_CEILING_MIN, so no override is open-ended or longer than that.
//   * FAIL CLOSED: a missing, unconfirmed or invalid configuration returns reasons and NO configuration. Nothing here substitutes
//     the proposed defaults; they exist only as data for the owner to review (proposedOverrideConfig) and are never applied.
//   * The power-cut reserve is inside LIMITS.reserveMin..reserveMax and never below the current backup reserve (raise-only).
//   * "Until local time X" choices use the plan core's clock-change aware elapsed-minute arithmetic (23 h and 25 h days).
import { DAY_MIN, elapsedMinutes, fmt, span } from "./time.ts";
import type { ClockDay } from "./time.ts";
import { LIMITS } from "./settings.ts";
import { OVERRIDE_KINDS, startOverride } from "./overrides.ts";
import type { OverrideKind, OverridePolicy, StartResult } from "./overrides.ts";

// The bounds of every owner-set value, one place. The block between the markers is strict JSON (a Python test reads it and checks
// the proposed helpers against it), so it carries no comment and no trailing comma.
// BEGIN HELPER_BOUNDS_JSON
export const HELPER_BOUNDS = {
  "min_expiry": { "min": 5, "max": 60, "step": 5, "unit": "min" },
  "hold_default": { "min": 5, "max": 4320, "step": 5, "unit": "min" },
  "hold_cap": { "min": 5, "max": 4320, "step": 5, "unit": "min" },
  "skip_until": { "min": 180, "max": 1435, "step": 5, "unit": "minute of day" },
  "skip_cap": { "min": 5, "max": 2160, "step": 5, "unit": "min" },
  "cut_default": { "min": 5, "max": 10080, "step": 5, "unit": "min" },
  "cut_cap": { "min": 5, "max": 10080, "step": 5, "unit": "min" },
  "cut_reserve": { "min": 10, "max": 100, "step": 1, "unit": "%" },
  "revision": { "min": 0, "max": 1000000000, "step": 1, "unit": "" }
} as const;
// END HELPER_BOUNDS_JSON

/**
 * Absolute ceilings, minutes: the longest any override can ever last, whatever a helper holds.
 *   Hold battery 72 h: it only withholds export starts and discretionary rate edits; beyond three days the forecast it was held
 *     against is stale, so a longer hold must be started again on purpose.
 *   Skip tonight 36 h: it is a one-night action; 36 h covers "until the next morning" on a 25-hour clock-change day with slack.
 *   Prepare for power cut 7 days: a raised reserve costs only forgone export, so it may last longest, but never open-ended.
 */
export const EXPIRY_CEILING_MIN: Readonly<Record<OverrideKind, number>> = Object.freeze({
  hold_battery: HELPER_BOUNDS.hold_cap.max,
  skip_tonight: HELPER_BOUNDS.skip_cap.max,
  prepare_power_cut: HELPER_BOUNDS.cut_cap.max,
});

export const OVERRIDE_LABELS: Readonly<Record<OverrideKind, string>> = Object.freeze({
  hold_battery: "Hold battery",
  skip_tonight: "Skip tonight",
  prepare_power_cut: "Prepare for power cut",
});

/** Raw numbers as read from the owner's helpers (minutes, minute of day, percent). Anything may be missing or malformed. */
export interface OverrideConfigRaw {
  /** The owner's switch that says the limits below were reviewed. Only the boolean true counts. */
  confirmed?: unknown;
  minExpiryMin?: unknown;
  holdDefaultMin?: unknown;
  holdCapMin?: unknown;
  /** Skip tonight's default end, as a local minute of day (for example 420 = 07:00). */
  skipUntilMin?: unknown;
  skipCapMin?: unknown;
  cutDefaultMin?: unknown;
  cutCapMin?: unknown;
  cutReservePct?: unknown;
}

/** A validated configuration. Only produced by validateOverrideConfig; frozen. */
export interface OverrideConfig {
  readonly minExpiryMin: number;
  readonly holdDefaultMin: number;
  readonly holdCapMin: number;
  readonly skipUntilMin: number;
  readonly skipCapMin: number;
  readonly cutDefaultMin: number;
  readonly cutCapMin: number;
  readonly cutReservePct: number;
}

export type OverrideConfigResult = { ok: true; config: OverrideConfig; warnings: string[] } | { ok: false; reasons: string[] };

interface FieldSpec {
  readonly key: Exclude<keyof OverrideConfigRaw, "confirmed">;
  readonly bound: keyof typeof HELPER_BOUNDS;
  readonly label: string;
}

const FIELD_SPECS: readonly FieldSpec[] = [
  { key: "minExpiryMin", bound: "min_expiry", label: "Shortest allowed override" },
  { key: "holdDefaultMin", bound: "hold_default", label: "Hold battery default" },
  { key: "holdCapMin", bound: "hold_cap", label: "Hold battery maximum" },
  { key: "skipUntilMin", bound: "skip_until", label: "Skip tonight ends at" },
  { key: "skipCapMin", bound: "skip_cap", label: "Skip tonight maximum" },
  { key: "cutDefaultMin", bound: "cut_default", label: "Prepare for power cut default" },
  { key: "cutCapMin", bound: "cut_cap", label: "Prepare for power cut maximum" },
  { key: "cutReservePct", bound: "cut_reserve", label: "Power-cut reserve" },
];

/** "30 min", "4 h", "1 day", "1 day 6 h". Unknown for anything that is not a non-negative finite number. */
export function formatDurationMin(min: number): string {
  if (typeof min !== "number" || !Number.isFinite(min) || min < 0) return "unknown";
  const m = Math.round(min);
  if (m < 60) return m + " min";
  const d = Math.floor(m / DAY_MIN);
  const h = Math.floor((m - d * DAY_MIN) / 60);
  const r = m % 60;
  const parts: string[] = [];
  if (d > 0) parts.push(d + (d === 1 ? " day" : " days"));
  if (h > 0) parts.push(h + " h");
  if (r > 0) parts.push(r + " min");
  return parts.join(" ");
}

function showBound(spec: FieldSpec, v: number): string {
  if (spec.bound === "skip_until") return fmt(v);
  const b = HELPER_BOUNDS[spec.bound];
  return b.unit === "min" ? formatDurationMin(v) : v + " " + b.unit;
}

function checkField(spec: FieldSpec, raw: unknown, reasons: string[]): number | null {
  const b = HELPER_BOUNDS[spec.bound];
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    reasons.push(spec.label + " is not set or cannot be read.");
    return null;
  }
  if (!Number.isInteger(raw)) {
    reasons.push(spec.label + " must be a whole number.");
    return null;
  }
  if (raw < b.min) {
    reasons.push(spec.label + " must be at least " + showBound(spec, b.min) + ".");
    return null;
  }
  if (raw > b.max) {
    reasons.push(spec.label + " can be at most " + showBound(spec, b.max) + ".");
    return null;
  }
  if ((raw - b.min) % b.step !== 0) {
    reasons.push(spec.label + " moves in steps of " + b.step + (b.unit === "%" ? " %" : " min") + ".");
    return null;
  }
  return raw;
}

export interface ConfigContext {
  /** The current backup reserve, %, if known. The power-cut reserve may never be below it. */
  currentReservePct?: number | null;
}

/**
 * Validate the owner's raw configuration. Fails closed: any problem returns every reason found and no configuration.
 * `raw` null or undefined means "nothing configured".
 */
export function validateOverrideConfig(raw: OverrideConfigRaw | null | undefined, ctx: ConfigContext = {}): OverrideConfigResult {
  if (raw === null || raw === undefined || typeof raw !== "object") {
    return { ok: false, reasons: ["No override limits are configured, so no override can be started."] };
  }
  const reasons: string[] = [];
  const warnings: string[] = [];
  if (raw.confirmed !== true) reasons.push("The owner has not confirmed the override limits (the switch is off or cannot be read), so no override can be started.");

  const v: Partial<Record<FieldSpec["key"], number>> = {};
  for (const spec of FIELD_SPECS) {
    const n = checkField(spec, raw[spec.key], reasons);
    if (n !== null) v[spec.key] = n;
  }
  // (Skip tonight's end time cannot fall between 00:00 and 03:00, where clock changes happen: its bound starts at 03:00.)

  const min = v.minExpiryMin;
  const order = (label: string, def: number | undefined, cap: number | undefined) => {
    if (min !== undefined && def !== undefined && def < min) reasons.push(label + " default is shorter than the shortest allowed override.");
    if (def !== undefined && cap !== undefined && def > cap) reasons.push(label + " default is longer than its maximum.");
  };
  order("Hold battery", v.holdDefaultMin, v.holdCapMin);
  order("Prepare for power cut", v.cutDefaultMin, v.cutCapMin);
  if (min !== undefined && v.skipCapMin !== undefined && v.skipCapMin < min) reasons.push("Skip tonight maximum is shorter than the shortest allowed override.");

  const r = v.cutReservePct;
  if (r !== undefined && (r < LIMITS.reserveMin || r > LIMITS.reserveMax)) reasons.push("The power-cut reserve must be " + LIMITS.reserveMin + "-" + LIMITS.reserveMax + " %.");
  const cur = ctx.currentReservePct;
  if (typeof cur === "number" && Number.isFinite(cur)) {
    if (r !== undefined && r < cur) reasons.push("The power-cut reserve (" + r + " %) is below the current backup reserve (" + cur + " %); it would not raise anything.");
  } else {
    warnings.push("The current backup reserve is not known, so the power-cut reserve cannot be compared with it here. An override can only raise a reserve.");
  }

  if (reasons.length > 0) return { ok: false, reasons };
  const config: OverrideConfig = Object.freeze({
    minExpiryMin: v.minExpiryMin as number,
    holdDefaultMin: v.holdDefaultMin as number,
    holdCapMin: v.holdCapMin as number,
    skipUntilMin: v.skipUntilMin as number,
    skipCapMin: v.skipCapMin as number,
    cutDefaultMin: v.cutDefaultMin as number,
    cutCapMin: v.cutCapMin as number,
    cutReservePct: v.cutReservePct as number,
  });
  return { ok: true, config, warnings };
}

// ---- local-time expiry (clock-change aware) --------------------------------------------------------------------------------------

/** Where "now" is on the wall clock, and the clock change (if any) that falls inside the next 24 hours. */
export interface ClockContext {
  readonly nowWallMin: number;
  readonly day: ClockDay;
}

export type UntilResult = { ok: true; wallMin: number; expiryMin: number } | { ok: false; error: string };

function validClockDay(day: ClockDay): boolean {
  return !!day && (day.deltaMin === 0 || day.deltaMin === 60 || day.deltaMin === -60) && Number.isInteger(day.changeAtMin) && day.changeAtMin >= 0 && day.changeAtMin < DAY_MIN;
}

/**
 * The real minutes from now until the NEXT occurrence of a local time of day (strictly later: the same minute means tomorrow).
 * A spring change in between makes the real interval an hour shorter than the wall clock shows, an autumn change an hour longer.
 */
export function untilLocalTime(nowWallMin: number, targetWallMin: number, day: ClockDay): UntilResult {
  if (!Number.isInteger(nowWallMin) || nowWallMin < 0 || nowWallMin >= DAY_MIN) return { ok: false, error: "The local time is unknown." };
  if (!Number.isInteger(targetWallMin) || targetWallMin < 0 || targetWallMin >= DAY_MIN) return { ok: false, error: "The end time is not a time of day." };
  if (!validClockDay(day)) return { ok: false, error: "The clock-change information is not valid." };
  const gap = span(nowWallMin, targetWallMin);
  const wall = gap === 0 ? DAY_MIN : gap;
  const expiryMin = elapsedMinutes(nowWallMin, wall, day);
  if (!(expiryMin > 0)) return { ok: false, error: "The end time is not in the future." };
  return { ok: true, wallMin: wall, expiryMin };
}

/** The policy overrides.ts takes, for this moment. Skip tonight's default is "until its end time", worked out from the clock. */
export function overridePolicyAt(cfg: OverrideConfig, clock: ClockContext | null): OverridePolicy {
  let skipDefault = NaN;
  if (clock) {
    const u = untilLocalTime(clock.nowWallMin, cfg.skipUntilMin, clock.day);
    if (u.ok) skipDefault = u.expiryMin;
  }
  return {
    minExpiryMin: cfg.minExpiryMin,
    defaultExpiryMin: { hold_battery: cfg.holdDefaultMin, skip_tonight: skipDefault, prepare_power_cut: cfg.cutDefaultMin },
    maxExpiryMin: { hold_battery: cfg.holdCapMin, skip_tonight: cfg.skipCapMin, prepare_power_cut: cfg.cutCapMin },
    powerCutReservePct: cfg.cutReservePct,
  };
}

// ---- expiry choices for the UI -----------------------------------------------------------------------------------------------------

export interface ExpiryChoice {
  /** "d<minutes>" for a duration, "until" for the local-time choice. */
  id: string;
  label: string;
  expiryMin: number;
  /** For the local-time choice: the minute of day it ends at. */
  untilMin: number | null;
  isDefault: boolean;
}

const CANDIDATE_DURATIONS_MIN: readonly number[] = [30, 60, 120, 240, 480, 720, 1440, 2880, 4320, 10080];

/**
 * The expiry chips to offer for one override: short durations bounded by the owner's minimum and the kind's cap, the owner's default
 * and cap themselves, and for Hold battery and Skip tonight "until HH:MM" (the Skip tonight end time) when it is within bounds.
 */
export function expiryChoices(kind: OverrideKind, cfg: OverrideConfig, clock: ClockContext | null): ExpiryChoice[] {
  const cap = kind === "hold_battery" ? cfg.holdCapMin : kind === "skip_tonight" ? cfg.skipCapMin : cfg.cutCapMin;
  const def = kind === "hold_battery" ? cfg.holdDefaultMin : kind === "prepare_power_cut" ? cfg.cutDefaultMin : null;
  const lengths = new Set<number>();
  for (const d of CANDIDATE_DURATIONS_MIN) if (d >= cfg.minExpiryMin && d <= cap) lengths.add(d);
  if (def !== null) lengths.add(def);
  lengths.add(cap);
  const out: ExpiryChoice[] = [...lengths]
    .filter((d) => d >= cfg.minExpiryMin && d <= cap)
    .map((d) => ({ id: "d" + d, label: formatDurationMin(d), expiryMin: d, untilMin: null, isDefault: def === d }));
  if ((kind === "hold_battery" || kind === "skip_tonight") && clock) {
    const u = untilLocalTime(clock.nowWallMin, cfg.skipUntilMin, clock.day);
    if (u.ok && u.expiryMin >= cfg.minExpiryMin && u.expiryMin <= cap) {
      out.push({ id: "until", label: "until " + fmt(cfg.skipUntilMin), expiryMin: u.expiryMin, untilMin: cfg.skipUntilMin, isDefault: kind === "skip_tonight" });
    }
  }
  return out.sort((a, b) => a.expiryMin - b.expiryMin || a.id.localeCompare(b.id));
}

// ---- starting an override under the validated policy ------------------------------------------------------------------------------

export interface StartContext {
  clock: ClockContext | null;
  /** The current backup reserve, %. Prepare for power cut is refused when it is unknown or above the power-cut reserve. */
  currentReservePct: number | null;
}

/**
 * Start an override only under a valid policy. A missing or invalid policy refuses with its reasons (never the proposed defaults).
 * Layers the policy's own bounds (overrides.ts startOverride), a whole-minute check, the hard ceiling and the raise-only reserve.
 */
export function startConfiguredOverride(
  kind: OverrideKind,
  nowMin: number,
  expiryMin: number | null | undefined,
  result: OverrideConfigResult | null | undefined,
  ctx: StartContext,
): StartResult {
  if (!result || result.ok !== true || !result.config) {
    const why = result && result.ok === false && result.reasons.length ? " " + result.reasons.join(" ") : "";
    return { ok: false, error: "The override limits are not valid, so no override can be started." + why };
  }
  const cfg = result.config;
  if (!OVERRIDE_KINDS.includes(kind)) return { ok: false, error: "Unknown override." };
  if (expiryMin !== null && expiryMin !== undefined && (typeof expiryMin !== "number" || !Number.isInteger(expiryMin))) {
    return { ok: false, error: "The expiry must be a whole number of minutes." };
  }
  if (kind === "prepare_power_cut") {
    const cur = ctx.currentReservePct;
    if (typeof cur !== "number" || !Number.isFinite(cur)) return { ok: false, error: "The current backup reserve is not known, so it cannot be shown that the power-cut reserve raises it." };
    if (cfg.cutReservePct < cur) return { ok: false, error: "The power-cut reserve (" + cfg.cutReservePct + " %) is below the current backup reserve (" + cur + " %); an override never lowers a reserve." };
  }
  const r = startOverride(kind, nowMin, expiryMin, overridePolicyAt(cfg, ctx.clock));
  if (!r.ok) return r;
  const length = r.override.expiresAtMin - r.override.startedAtMin;
  if (!(length > 0) || !(length <= EXPIRY_CEILING_MIN[kind])) return { ok: false, error: "The expiry is beyond the hard ceiling of " + formatDurationMin(EXPIRY_CEILING_MIN[kind]) + "." };
  return r;
}

// ---- the PROPOSED defaults (owner decides; never applied by this package) -----------------------------------------------------------

export interface ProposedValue {
  readonly key: Exclude<keyof OverrideConfigRaw, "confirmed">;
  readonly value: number;
  readonly why: string;
}

// BEGIN PROPOSED DEFAULTS: proposals for the owner to review and set in the helpers. Not read by any validator or starter.
const PROPOSED_LIST: ProposedValue[] = [
  { key: "minExpiryMin", value: 15, why: "Under a quarter hour is almost certainly a mis-tap and would make the plan flicker." },
  { key: "holdDefaultMin", value: 240, why: "Covers an evening of extra use (cooking, guests) without outliving it." },
  { key: "holdCapMin", value: 1440, why: "A forgotten hold costs at most one night of export; two days needs a deliberate restart." },
  { key: "skipUntilMin", value: 420, why: "Skips tonight's export and the overnight charge, then planning resumes before the morning sun." },
  { key: "skipCapMin", value: 1440, why: "Skip is a one-night action; a day is the most it needs." },
  { key: "cutDefaultMin", value: 1440, why: "Most warnings and outages are shorter than a day; extending is a conscious step." },
  { key: "cutCapMin", value: 4320, why: "Matches the design example of 72 h; a raised reserve only costs forgone export." },
  { key: "cutReservePct", value: 80, why: "Hours of essential load while still leaving room for solar; the design example." },
];
export const PROPOSED_DEFAULTS: readonly ProposedValue[] = Object.freeze(PROPOSED_LIST.map((p) => Object.freeze({ ...p })));
// END PROPOSED DEFAULTS

/** The proposed defaults as a raw configuration for the card to SHOW. It is not confirmed, so validating it as it stands fails. */
export function proposedOverrideConfig(): OverrideConfigRaw {
  const out: Record<string, unknown> = { confirmed: false };
  for (const p of PROPOSED_DEFAULTS) out[p.key] = p.value;
  return out as OverrideConfigRaw;
}
