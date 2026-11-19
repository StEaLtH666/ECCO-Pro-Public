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
//   * Owner decision r15 (19 Nov 2026, known limitation 23): each kind's expiry is read from BOTH of the backend's sources, with the backend's own
//     raise-only rule (home-assistant/packages/ecco_plan_helpers.yaml): the date-and-time helper's timestamp attribute and the absolute epoch
//     record (an input_number in seconds). A kind is ACTIVE while any valid source is in the future (the later valid instant wins), UNREADABLE
//     when a source is invalid and none holds, and CLEARED only when every source is readable and none is in the future. An unreadable kind is
//     never shown as cleared: it is listed as held by Home Assistant, because the backend keeps the hold and any raised reserve until a cancel
//     settles it and allows that cancel. This card is never more lenient than the backend (a reading it cannot place is unreadable here), and
//     judges to the minute. An older package without the epoch records is judged by the date-and-time record only, and says so.
import { EXPIRY_CEILING_MIN, LIMITS, OVERRIDE_KINDS, OVERRIDE_LABELS, validateOverrideConfig } from "../../../ecco-plan-core/src/index.ts";
import type { ActiveOverride, OverrideConfigRaw, OverrideConfigResult, OverrideKind } from "../../../ecco-plan-core/src/index.ts";
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
  "prepare_power_cut_reserve": "input_number.ecco_plan_override_prepare_power_cut_reserve",
  "hold_battery_expires_epoch": "input_number.ecco_plan_override_hold_battery_expires_epoch",
  "skip_tonight_expires_epoch": "input_number.ecco_plan_override_skip_tonight_expires_epoch",
  "prepare_power_cut_expires_epoch": "input_number.ecco_plan_override_prepare_power_cut_expires_epoch"
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
  /** Plain words when the absolute epoch record alone carries the expiry ("" when nothing needs saying). */
  note: string;
}

/** What the card reads of one kind's stored records, by the backend's rule: active, cleared, or unreadable (never shown as cleared). */
export type KindRead = "active" | "cleared" | "unreadable";

export interface KindRecord {
  kind: OverrideKind;
  label: string;
  read: KindRead;
  /** The later valid expiry in whole epoch minutes when the kind is active or cleared, else null. */
  endMin: number | null;
  /** That expiry as text: the date-and-time helper's local text when it is the later source, else "YYYY-MM-DD HH:MM UTC" of the epoch record. */
  endText: string | null;
  /** Plain words about where the kind stands when it is held by Home Assistant without being a trusted running row ("" otherwise). */
  note: string;
  /** True when the absolute epoch record is not installed (an older package): the kind is judged by the date-and-time record only. */
  epochMissing: boolean;
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
  /** Per kind, the card's reading of its records (empty when the time was not given). */
  records: KindRecord[];
  /** The kinds Home Assistant holds, or may hold, that are not a trusted running row (a record that cannot be read, or a malformed one that is still in the future): shown with a Cancel. */
  held: KindRecord[];
  /** Stored records that cannot be read or are malformed, in plain words. They are not shown as running overrides. */
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

const EPOCH_MAX_SEC = 4102444800;
const NOTE_EPOCH_LED =
  "Held through the absolute epoch record: the date-and-time record does not show it running (it reads earlier, has ended or cannot be read). Home Assistant follows the later of the two.";
const NOTE_UNREADABLE =
  "A record of this override cannot be read here, so it is not shown as ended. Home Assistant keeps the hold, and any raised reserve, until a cancel settles it.";
const NOTE_UNTRUSTED =
  "This record is not trusted here (see the problem listed), but Home Assistant keeps the hold, and any raised reserve, while it runs. A cancel ends it.";

/** "YYYY-MM-DD HH:MM" (UTC) of an instant in whole epoch minutes. Integer arithmetic only: this module reads no clock and builds no date object. */
export function utcText(epochMin: number): string {
  const days = Math.floor(epochMin / 1440);
  const rem = epochMin - days * 1440;
  const z = days + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const day = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const month = mp < 10 ? mp + 3 : mp - 9;
  const year = yoe + era * 400 + (month <= 2 ? 1 : 0);
  const two = (n: number): string => (n < 10 ? "0" : "") + n;
  return year + "-" + two(month) + "-" + two(day) + " " + two(Math.floor(rem / 60)) + ":" + two(rem % 60);
}

type EpochRead = Instant | { ok: false; absent: true; reason: string };

/**
 * The absolute epoch record of a kind, as the backend reads it: a number from 0 to 4102444800 seconds (anything else is invalid). Rounded UP to the
 * minute, so it is never read earlier than the instant the backend reads. Missing entity: absent (an older package), never an invalid reading.
 */
function readEpoch(states: StatesLike, id: string, label: string): EpochRead {
  if (states[id] === undefined) return { ok: false, absent: true, reason: label + " absolute expiry record is not installed." };
  const v = stateNumber(states, id);
  if (v === null) return { ok: false, reason: label + " absolute expiry record cannot be read." };
  if (v < 0 || v > EPOCH_MAX_SEC) return { ok: false, reason: label + " absolute expiry record is not a time between 0 and " + EPOCH_MAX_SEC + " seconds." };
  const min = Math.ceil(v / 60);
  return { ok: true, min, text: utcText(min) + " UTC" };
}

interface Verdict {
  read: KindRead;
  endMin: number | null;
  endFrom: "datetime" | "epoch" | null;
}

/**
 * The backend's rule for one kind: when both sources are valid the later wins, and it holds while it is in the future; with one valid source, that
 * source holds only while it is in the future (otherwise the record is unreadable); with no valid source the record is unreadable. An absent epoch
 * record (an older package) leaves the date-and-time record alone to be judged.
 */
function judge(a: Instant, b: EpochRead, nowMin: number): Verdict {
  if (a.ok && b.ok) {
    const fromEpoch = b.min > a.min;
    const endMin = fromEpoch ? b.min : a.min;
    return { read: endMin > nowMin ? "active" : "cleared", endMin, endFrom: fromEpoch ? "epoch" : "datetime" };
  }
  if (a.ok && !b.ok && "absent" in b) return { read: a.min > nowMin ? "active" : "cleared", endMin: a.min, endFrom: "datetime" };
  if (a.ok && a.min > nowMin) return { read: "active", endMin: a.min, endFrom: "datetime" };
  if (b.ok && b.min > nowMin) return { read: "active", endMin: b.min, endFrom: "epoch" };
  return { read: "unreadable", endMin: null, endFrom: null };
}

function readRecords(states: StatesLike, nowMin: number | null, problems: string[]): { rows: ActiveOverrideRow[]; records: KindRecord[] } {
  const rows: ActiveOverrideRow[] = [];
  const records: KindRecord[] = [];
  if (nowMin === null) {
    problems.push("The current time is not known, so stored override records cannot be judged.");
    return { rows, records };
  }
  const noEpoch: string[] = [];
  for (const kind of OVERRIDE_KINDS) {
    const label = OVERRIDE_LABELS[kind];
    const startId = HELPER_IDS[(kind + "_start") as keyof typeof HELPER_IDS];
    const expiresId = HELPER_IDS[(kind + "_expires") as keyof typeof HELPER_IDS];
    const epochId = HELPER_IDS[(kind + "_expires_epoch") as keyof typeof HELPER_IDS];
    const end = readInstant(states, expiresId, label + " expiry");
    const epoch = readEpoch(states, epochId, label);
    if (!end.ok) problems.push(end.reason);
    if (!epoch.ok) {
      if ("absent" in epoch) noEpoch.push(label);
      else problems.push(epoch.reason);
    }
    const verdict = judge(end, epoch, nowMin);
    const endText = verdict.endFrom === "epoch" && epoch.ok ? epoch.text : end.ok ? end.text : null;
    let row: ActiveOverrideRow | null = null;
    if (verdict.read === "active" && verdict.endMin !== null) {
      const endMin = verdict.endMin;
      const start = readInstant(states, startId, label + " start");
      if (!start.ok) {
        problems.push(start.reason + " The record is not trusted.");
      } else {
        const length = endMin - start.min;
        if (!(length > 0)) {
          problems.push(label + " starts at or after its expiry. The record is not trusted.");
        } else if (length > EXPIRY_CEILING_MIN[kind]) {
          problems.push(label + " lasts longer than its hard ceiling. The record is not trusted.");
        } else {
          const o: ActiveOverride = { kind, startedAtMin: start.min, expiresAtMin: endMin };
          let trusted = true;
          if (kind === "prepare_power_cut") {
            const r = stateNumber(states, HELPER_IDS.prepare_power_cut_reserve);
            if (r === null || !Number.isInteger(r) || r < LIMITS.reserveMin || r > LIMITS.reserveMax) {
              problems.push(label + " has no readable reserve inside " + LIMITS.reserveMin + "-" + LIMITS.reserveMax + " %. The record is not trusted.");
              trusted = false;
            } else {
              o.reservePct = r;
            }
          }
          if (trusted) row = { override: o, label, expiresText: endText ?? "", remainingMin: Math.max(1, endMin - nowMin), note: verdict.endFrom === "epoch" ? NOTE_EPOCH_LED : "" };
        }
      }
    }
    if (row) rows.push(row);
    records.push({
      kind,
      label,
      read: verdict.read,
      endMin: verdict.endMin,
      endText: verdict.endMin === null ? null : endText,
      note: row ? row.note : verdict.read === "active" ? NOTE_UNTRUSTED : verdict.read === "unreadable" ? NOTE_UNREADABLE : "",
      epochMissing: !epoch.ok && "absent" in epoch,
    });
  }
  if (noEpoch.length > 0) {
    problems.push(
      "The absolute expiry record of " + noEpoch.join(", ") + " is not installed (an older helper package), so " + (noEpoch.length === 1 ? "it is" : "they are") + " judged by the date-and-time record only.",
    );
  }
  return { rows, records };
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
  const { rows: active, records } = readRecords(states, nowMin, problems);
  const held = records.filter((r) => r.read !== "cleared" && !active.some((a) => a.override.kind === r.kind));
  return { missing, confirmed, policy, startPolicy, socPct, revision: readRevision(states), active, records, held, problems, nowMin };
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
