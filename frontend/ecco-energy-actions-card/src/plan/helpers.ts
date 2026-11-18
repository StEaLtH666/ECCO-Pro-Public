// Plan helper reader (READ ONLY): when the plan helper entities exist (home-assistant/packages/ecco_plan_helpers.yaml), turn them into
// the plan core's override policy, the stored plan revision and the active override records. When none of them exists the card behaves
// exactly as before (no policy, no records).
// Pure: no DOM, no Lit, no clock (the caller passes the minute), no service call. It cannot write anything.
//
// Honesty rules (each has a test):
//   * Helpers are configured when ANY of the proposed entities exists; then everything is judged, nothing is guessed. A missing,
//     unreadable or out-of-bounds value makes the policy unusable (reasons listed); the proposed defaults are never substituted.
//   * An override record is active only while its expiry is in the future, and only if it is well formed (start before expiry, not
//     longer than the hard ceiling, a power-cut reserve inside the reserve limits). A malformed one is reported, never trusted.
//   * Records are read from the entity's own timestamp (a real instant), so a clock change or a browser in another time zone cannot
//     move an expiry.
import { EXPIRY_CEILING_MIN, LIMITS, OVERRIDE_KINDS, OVERRIDE_LABELS, validateOverrideConfig } from "../../../ecco-plan-core/src/index.ts";
import type { ActiveOverride, OverrideConfigRaw, OverrideConfigResult } from "../../../ecco-plan-core/src/index.ts";
import { buildPlanSnapshot, stateNumber, stateText } from "./adapter.ts";
import type { PlanSnapshot, StatesLike } from "./adapter.ts";
import type { EccoEnergyActionsCardConfig } from "../config";

// Every entity the helper package defines for the plan, generic ecco_plan_* names with no site value. The block between the markers is
// strict JSON (a Python test reads it and checks the package defines exactly these entities).
// BEGIN HELPER_IDS_JSON
export const HELPER_IDS = {
  "confirmed": "input_boolean.ecco_plan_overrides_enabled",
  "revision": "input_number.ecco_plan_revision",
  "min_expiry": "input_number.ecco_plan_policy_min_expiry",
  "hold_default": "input_number.ecco_plan_policy_hold_default",
  "hold_cap": "input_number.ecco_plan_policy_hold_cap",
  "skip_until": "input_datetime.ecco_plan_policy_skip_until",
  "skip_cap": "input_number.ecco_plan_policy_skip_cap",
  "cut_default": "input_number.ecco_plan_policy_cut_default",
  "cut_cap": "input_number.ecco_plan_policy_cut_cap",
  "cut_reserve": "input_number.ecco_plan_policy_cut_reserve",
  "hold_battery_start": "input_datetime.ecco_plan_override_hold_battery_start",
  "hold_battery_expires": "input_datetime.ecco_plan_override_hold_battery_expires",
  "skip_tonight_start": "input_datetime.ecco_plan_override_skip_tonight_start",
  "skip_tonight_expires": "input_datetime.ecco_plan_override_skip_tonight_expires",
  "prepare_power_cut_start": "input_datetime.ecco_plan_override_prepare_power_cut_start",
  "prepare_power_cut_expires": "input_datetime.ecco_plan_override_prepare_power_cut_expires",
  "prepare_power_cut_reserve": "input_number.ecco_plan_override_prepare_power_cut_reserve"
} as const;
// END HELPER_IDS_JSON

export interface RevisionInfo {
  known: boolean;
  /** The stored counter (0 = nothing recorded yet), or null when unknown. */
  value: number | null;
  reason: string;
}

export interface ActiveOverrideRow {
  override: ActiveOverride;
  label: string;
  /** The expiry as the helper shows it, local time "YYYY-MM-DD HH:MM". */
  expiresText: string;
  /** Whole minutes left (at least 1). */
  remainingMin: number;
}

export interface HelperSnapshot {
  /** Proposed entities that do not exist (some existing and some missing means a half-built helper). */
  missing: string[];
  /** The owner's confirmation switch: true on, false off, null unreadable. */
  confirmed: boolean | null;
  /** Fail-closed: ok only with a complete, confirmed, in-bounds policy. Carries reasons otherwise and never a configuration. */
  policy: OverrideConfigResult;
  /**
   * The same limits validated WITHOUT the current reserve: what a start of Hold battery or Skip tonight needs. Only Prepare for power cut
   * is refused when its reserve is below the current one (that is checked when it starts), as the guarded script does.
   */
  startPolicy: OverrideConfigResult;
  /** The battery level, %, as the card reads it (null when unreadable). Only used to say plainly when a raised reserve is not reached. */
  socPct: number | null;
  revision: RevisionInfo;
  active: ActiveOverrideRow[];
  /** Stored records that cannot be read or are malformed, in plain words. They are not shown as active. */
  problems: string[];
  /** The minute (epoch minutes) the records were judged against, or null when the time was not given. */
  nowMin: number | null;
}

export type PlanSnapshotWithHelpers = PlanSnapshot & { helpers: HelperSnapshot | null };

const TIME_RE = /^(\d{2}):(\d{2})(?::(\d{2}))?$/;
const STAMP_RE = /^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2}$/;

/** A time-of-day helper ("HH:MM:SS") as a minute of day; a stray seconds part leaves a fraction the validator then refuses. */
function timeOfDayMin(text: string | null): number | null {
  if (text === null) return null;
  const m = TIME_RE.exec(text.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  const s = m[3] === undefined ? 0 : Number(m[3]);
  if (h > 23 || mi > 59 || s > 59) return null;
  return h * 60 + mi + s / 60;
}

function switchState(states: StatesLike, id: string): boolean | null {
  const t = stateText(states, id);
  return t === "on" ? true : t === "off" ? false : null;
}

type Instant = { ok: true; min: number; text: string } | { ok: false; reason: string };

/** A date-and-time helper as an absolute minute (from its timestamp attribute) and its local display text. */
function readInstant(states: StatesLike, id: string, what: string): Instant {
  const text = stateText(states, id);
  if (text === null) return { ok: false, reason: what + " cannot be read." };
  const m = STAMP_RE.exec(text.trim());
  if (!m) return { ok: false, reason: what + " is not a date and time." };
  const ts = states[id]?.attributes?.["timestamp"];
  if (typeof ts !== "number" || !Number.isFinite(ts)) return { ok: false, reason: what + " has no timestamp, so its moment cannot be placed." };
  return { ok: true, min: Math.round(ts / 60), text: (m[1] as string) + " " + (m[2] as string) + ":" + (m[3] as string) };
}

function readRecords(states: StatesLike, nowMin: number | null, problems: string[]): ActiveOverrideRow[] {
  const rows: ActiveOverrideRow[] = [];
  if (nowMin === null) {
    problems.push("The current time is not known, so stored override records cannot be judged.");
    return rows;
  }
  for (const kind of OVERRIDE_KINDS) {
    const label = OVERRIDE_LABELS[kind];
    const startId = HELPER_IDS[(kind + "_start") as keyof typeof HELPER_IDS];
    const expiresId = HELPER_IDS[(kind + "_expires") as keyof typeof HELPER_IDS];
    const end = readInstant(states, expiresId, label + " expiry");
    if (!end.ok) {
      problems.push(end.reason);
      continue;
    }
    if (end.min <= nowMin) continue; // never started, cancelled or expired: nothing is active
    const start = readInstant(states, startId, label + " start");
    if (!start.ok) {
      problems.push(start.reason + " The record is not trusted.");
      continue;
    }
    const length = end.min - start.min;
    if (!(length > 0)) {
      problems.push(label + " starts at or after its expiry. The record is not trusted.");
      continue;
    }
    if (length > EXPIRY_CEILING_MIN[kind]) {
      problems.push(label + " lasts longer than its hard ceiling. The record is not trusted.");
      continue;
    }
    const o: ActiveOverride = { kind, startedAtMin: start.min, expiresAtMin: end.min };
    if (kind === "prepare_power_cut") {
      const r = stateNumber(states, HELPER_IDS.prepare_power_cut_reserve);
      if (r === null || !Number.isInteger(r) || r < LIMITS.reserveMin || r > LIMITS.reserveMax) {
        problems.push(label + " has no readable reserve inside " + LIMITS.reserveMin + "-" + LIMITS.reserveMax + " %. The record is not trusted.");
        continue;
      }
      o.reservePct = r;
    }
    rows.push({ override: o, label, expiresText: end.text, remainingMin: Math.max(1, end.min - nowMin) });
  }
  return rows;
}

function readRevision(states: StatesLike): RevisionInfo {
  const v = stateNumber(states, HELPER_IDS.revision);
  if (v === null) return { known: false, value: null, reason: "The stored plan revision cannot be read." };
  if (!Number.isInteger(v) || v < 0) return { known: false, value: null, reason: "The stored plan revision is not a whole number." };
  return { known: true, value: v, reason: "" };
}

/**
 * Read the proposed plan helpers. Returns null when none of them exists (the card then shows exactly what it showed before).
 * `nowMin` is the current instant in epoch minutes; `currentReservePct` the backup reserve the card already reads (or null).
 */
export function readOverrideHelpers(states: StatesLike, nowMin: number | null, currentReservePct: number | null, socPct: number | null = null): HelperSnapshot | null {
  const ids = Object.values(HELPER_IDS) as string[];
  const missing = ids.filter((id) => states[id] === undefined);
  if (missing.length === ids.length) return null;

  const confirmed = switchState(states, HELPER_IDS.confirmed);
  const raw: OverrideConfigRaw = {
    confirmed,
    minExpiryMin: stateNumber(states, HELPER_IDS.min_expiry),
    holdDefaultMin: stateNumber(states, HELPER_IDS.hold_default),
    holdCapMin: stateNumber(states, HELPER_IDS.hold_cap),
    skipUntilMin: timeOfDayMin(stateText(states, HELPER_IDS.skip_until)),
    skipCapMin: stateNumber(states, HELPER_IDS.skip_cap),
    cutDefaultMin: stateNumber(states, HELPER_IDS.cut_default),
    cutCapMin: stateNumber(states, HELPER_IDS.cut_cap),
    cutReservePct: stateNumber(states, HELPER_IDS.cut_reserve),
  };
  const policy = validateOverrideConfig(raw, { currentReservePct });
  const startPolicy = validateOverrideConfig(raw);
  const problems: string[] = [];
  const active = readRecords(states, nowMin, problems);
  return { missing, confirmed, policy, startPolicy, socPct, revision: readRevision(states), active, problems, nowMin };
}

/** The stage-2 snapshot plus, when the proposed helpers exist, the policy, the stored revision and the active overrides. */
export function buildPlanSnapshotWithHelpers(config: EccoEnergyActionsCardConfig, states: StatesLike, nowMin: number | null): PlanSnapshotWithHelpers {
  const snap = buildPlanSnapshot(config, states);
  const reserve = snap.fields.find((f) => f.path === "reserve.backupPct");
  const socId = config.plan?.battery_soc ?? config.dump_to_grid?.battery_soc;
  const soc = socId ? stateNumber(states, socId) : null;
  const helpers = readOverrideHelpers(states, nowMin, reserve && reserve.known ? reserve.value : null, soc);
  if (!helpers) return { ...snap, helpers: null };
  return { ...snap, overrides: helpers.active.map((r) => r.override), helpers };
}
