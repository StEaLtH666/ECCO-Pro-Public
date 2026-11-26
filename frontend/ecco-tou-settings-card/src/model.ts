// Pure, DOM-free logic of the ECCO TOU Settings card.
//
// This module reads the `states` map it is handed and builds view models and service-call descriptions. It performs no
// call itself. Every safety decision stays in the ACS1 scripts (Review, Apply, Acknowledge): what this module computes is
// DISPLAY and ADVISORY ONLY - it can only make the card MORE restrictive than the scripts, never less. The Review's
// refusal text is the truth and is shown verbatim.
import type {
  Blocker,
  CardConfig,
  Draft,
  EditRecord,
  EditableSetting,
  EditorState,
  EditorView,
  Eligibility,
  HassEntityLike,
  Plan,
  ProgressStep,
  Result,
  ResultKind,
  ServiceCall,
  Setting,
  SlotView,
  StatesLike,
  Undo,
  ValueText,
} from "./types.ts";

export const DEFAULT_ENTITY_PREFIX = "ecco_clock_dongle";
export const DEFAULT_TITLE = "Time of Use Schedule";

// ---- The ACS1 contract (home-assistant/packages/ecco_tou_target_soc_edit.yaml) -----------------------------------
// The only three entities this card ever addresses with a service call, each through script.turn_on (see actions.ts).
export const SCRIPT_REVIEW = "script.ecco_cfg_review_tou_slot_setting";
export const SCRIPT_APPLY = "script.ecco_cfg_apply_tou_slot_setting";
export const SCRIPT_ACK = "script.ecco_cfg_acknowledge_edit_review";
// The editor's helpers (read only).
export const H_PLAN = "input_text.ecco_cfg_edit_review";
export const H_RESULT = "input_text.ecco_cfg_edit_last_result";
export const H_OWNER_EDIT = "input_text.ecco_cfg_last_owner_edit";
export const H_LOCK = "input_boolean.ecco_cfg_edit_review_required";
export const H_IN_FLIGHT = "input_boolean.ecco_cfg_edit_in_flight";
export const H_WRITE_SEEN = "input_boolean.ecco_cfg_edit_write_seen";
export const H_RESERVE = "input_number.ecco_minimum_reserve_soc";
export const H_FP_ARMED = "input_boolean.ecco_free_power_schedule_armed";
export const H_FP_START = "input_datetime.ecco_free_power_schedule_start";
export const H_DG_ARMED = "input_boolean.ecco_dump_to_grid_schedule_armed";
export const H_DG_START = "input_datetime.ecco_dump_to_grid_schedule_start";
// The saved-profile match, the fallback Review state and the failback shadow latch are NOT read here: their entity ids are reserved
// tokens that only declared Home Assistant files may spell, and the FB-C3 suite pins that no frontend file names the display decoders
// either. The Review script reads them and refuses with "supervision not stable or a failback episode is open"; the card shows that
// text verbatim (owner decision D3 of 2026-10-25 could not be implemented as approved; see the README).

export const ACK_PHRASE = "I HAVE CHECKED THE TOU SLOTS";
/** The Review's plan expires after this (the Apply script's own limit). */
export const PLAN_TTL_S = 600;
/** Provisional spacing between separate Applies (owner decision D5, 2026-10-25: fixed, not configurable, not a firmware rule). */
export const APPLY_SPACING_S = 300;
/** The gate's own freshness limits: the configuration read and the supervision heartbeat. */
export const CONFIG_CURRENT_S = 150;
export const HEARTBEAT_MAX_S = 60;
/** A slot value with its own report this recent is current for editing whatever the poll says (fixed; the display label uses the
 *  configurable max_age_configuration_s, eligibility never does: Window B O5). */
export const EDIT_FRESH_S = 300;
/** A scheduled Free Power / Dump start closer than this refuses an edit (the gate's rule). */
export const SCHEDULE_SOON_S = 900;
/** How long the card shows "sent" for a request whose result has not changed yet. */
export const REQUEST_TIMEOUT_S = 30;
export const POWER_MIN_W = 500;
export const POWER_MAX_W = 8000;
export const POWER_STEP_W = 100;

export const EDITABLE: EditableSetting[] = ["target_soc", "power", "charge_source"];
const SETTINGS: Setting[] = ["target_soc", "power", "charge_source", "start_time"];
export const SETTING_LABEL: Record<Setting, string> = {
  target_soc: "target SOC",
  power: "power",
  charge_source: "charge source",
  start_time: "start time",
};
export const SETTING_REGISTER_BASE: Record<Setting, number> = { target_soc: 267, power: 255, charge_source: 273, start_time: 249 };

export const START_TIME_LOCKED_TEXT =
  "Start times are not editable here. This site's slot layout wraps midnight, which the editor refuses as not strictly ascending " +
  "(L1); cyclic handling is a separate, reviewed development stream. Nothing in this card works around that refusal.";

const PREFIX_RE = /^[a-z][a-z0-9_]*[a-z0-9]$/;
const DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const HHMM_RE = /^(\d{2}):(\d{2})$/;
const LAYOUT_KEYS = new Set(["type", "view_layout", "grid_options", "visibility", "layout_options"]);
const CONFIG_KEYS = new Set(["title", "entity_prefix", "max_age_configuration_s"]);
const CLOCK_SKEW_TOLERANCE_S = 60;

// ---- Configuration ---------------------------------------------------------------------------------------------

/** Validate a Lovelace card config. Throws (Home Assistant shows the message) on anything malformed or unknown. */
export function normalizeConfig(raw: unknown): CardConfig {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("ecco-tou-settings-card: the configuration must be a mapping");
  }
  const cfg = raw as Record<string, unknown>;
  for (const key of Object.keys(cfg)) {
    if (!CONFIG_KEYS.has(key) && !LAYOUT_KEYS.has(key)) throw new Error(`ecco-tou-settings-card: unknown option '${key}'`);
  }
  const prefix = cfg.entity_prefix === undefined ? DEFAULT_ENTITY_PREFIX : cfg.entity_prefix;
  if (typeof prefix !== "string" || !PREFIX_RE.test(prefix) || prefix.includes("__")) {
    throw new Error("entity_prefix must be a Home Assistant device slug (lower-case letters, digits, single underscores)");
  }
  const title = cfg.title === undefined ? DEFAULT_TITLE : cfg.title;
  if (typeof title !== "string" || title.length > 120) throw new Error("title must be text of at most 120 characters");
  const age = cfg.max_age_configuration_s === undefined ? 300 : cfg.max_age_configuration_s;
  if (typeof age !== "number" || !Number.isFinite(age) || age < 5 || age > 86400) {
    throw new Error("max_age_configuration_s must be a number of seconds between 5 and 86400");
  }
  return { title, entity_prefix: prefix, max_age_configuration_s: age };
}

// ---- Entity ids ------------------------------------------------------------------------------------------------

export interface DongleIds {
  configUpdate: string;
  configOnline: string;
  telemetryOnline: string;
  cacheValid: string;
  fpActive: string;
  fpOp: string;
  fpSnapshot: string;
  dgActive: string;
  dgOp: string;
  dgSnapshot: string;
  writeInProgress: string;
  rtcInProgress: string;
  writeEnable: string;
  fpWriteEnable: string;
  fpRecoveryArm: string;
  dgWriteEnable: string;
  dgRecoveryArm: string;
  shutdownSoc: string;
  heartbeatAge: string;
  supervisionStable: string;
  manualLastResult: string;
  writeAttempts: string;
  loadLimit: string;
  touEnabled: string;
  inverterTime: string;
}

export function dongleIds(prefix: string): DongleIds {
  const p = prefix;
  return {
    configUpdate: `sensor.${p}_last_configuration_update`,
    configOnline: `binary_sensor.${p}_configuration_online`,
    telemetryOnline: `binary_sensor.${p}_telemetry_online`,
    cacheValid: `binary_sensor.${p}_manual_configuration_raw_cache_valid`,
    fpActive: `binary_sensor.${p}_free_power_active`,
    fpOp: `binary_sensor.${p}_free_power_operation_in_progress`,
    fpSnapshot: `binary_sensor.${p}_free_power_snapshot_valid`,
    dgActive: `binary_sensor.${p}_dump_to_grid_active`,
    dgOp: `binary_sensor.${p}_dump_to_grid_operation_in_progress`,
    dgSnapshot: `binary_sensor.${p}_dump_to_grid_snapshot_valid`,
    writeInProgress: `binary_sensor.${p}_manual_write_in_progress`,
    rtcInProgress: `binary_sensor.${p}_rtc_correction_in_progress`,
    writeEnable: `switch.${p}_manual_configuration_write_enable`,
    fpWriteEnable: `switch.${p}_free_power_write_enable`,
    fpRecoveryArm: `switch.${p}_free_power_recovery_arm`,
    dgWriteEnable: `switch.${p}_dump_to_grid_write_enable`,
    dgRecoveryArm: `switch.${p}_dump_to_grid_recovery_arm`,
    shutdownSoc: `sensor.${p}_ecco_battery_shutdown`,
    heartbeatAge: `sensor.${p}_ecco_supervision_heartbeat_age`,
    supervisionStable: `binary_sensor.${p}_ecco_supervision_stable`,
    manualLastResult: `sensor.${p}_manual_configuration_last_result`,
    writeAttempts: `sensor.${p}_manual_configuration_write_attempts_since_boot`,
    loadLimit: `sensor.${p}_ecco_load_limit_exp_ess_non_ess`,
    touEnabled: `binary_sensor.${p}_ecco_time_of_use_enabled`,
    inverterTime: `sensor.${p}_inverter_time`,
  };
}

export interface SlotIds {
  time: string;
  power: string;
  soc: string;
  charge: string;
  mode: string;
  flags: string;
}

export function slotIds(prefix: string, slot: number): SlotIds {
  const b = `sensor.${prefix}_ecco_timezone${slot}_`;
  return { time: `${b}time`, power: `${b}power`, soc: `${b}soc`, charge: `${b}charge`, mode: `${b}mode`, flags: `${b}raw_flags` };
}

/** Every entity id the card reads, for the element's change signature. */
export function referencedIds(prefix: string): string[] {
  const out: string[] = [
    SCRIPT_REVIEW, SCRIPT_APPLY, SCRIPT_ACK, H_PLAN, H_RESULT, H_OWNER_EDIT, H_LOCK, H_IN_FLIGHT, H_WRITE_SEEN, H_RESERVE,
    H_FP_ARMED, H_FP_START, H_DG_ARMED, H_DG_START,
    ...Object.values(dongleIds(prefix)),
  ];
  for (let n = 1; n <= 6; n++) out.push(...Object.values(slotIds(prefix, n)));
  return out;
}

// ---- Reading states --------------------------------------------------------------------------------------------

/** The state as text, or null when the entity is missing or has no value. */
export function stateText(states: StatesLike, id: string): string | null {
  const e = states[id];
  if (!e) return null;
  const s = e.state;
  if (typeof s !== "string" || s === "" || s === "unavailable" || s === "unknown") return null;
  return s;
}

export function stateNumber(states: StatesLike, id: string): number | null {
  const s = stateText(states, id);
  if (s === null) return null;
  const t = s.trim();
  if (!DECIMAL_RE.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function isOn(states: StatesLike, id: string): boolean {
  return stateText(states, id) === "on";
}

export function isOff(states: StatesLike, id: string): boolean {
  return stateText(states, id) === "off";
}

export function exists(states: StatesLike, id: string): boolean {
  return states[id] !== undefined;
}

export function timestampMs(e: HassEntityLike | undefined): number | null {
  if (!e) return null;
  for (const key of ["last_reported", "last_updated", "last_changed"] as const) {
    const v = e[key];
    if (typeof v === "string" && v) {
      const t = Date.parse(v);
      if (Number.isFinite(t)) return t;
    }
  }
  return null;
}

export function changedMs(e: HassEntityLike | undefined): number | null {
  if (!e) return null;
  const v = e.last_changed ?? e.last_updated;
  if (typeof v !== "string" || !v) return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : null;
}

/** Age in seconds, or null without a usable timestamp (a timestamp in the future beyond the skew tolerance is unusable). */
export function ageSeconds(e: HassEntityLike | undefined, nowMs: number): number | null {
  const ts = timestampMs(e);
  if (ts === null) return null;
  const age = (nowMs - ts) / 1000;
  if (age < -CLOCK_SKEW_TOLERANCE_S) return null;
  return Math.max(0, age);
}

// ---- The dongle's wall-clock timestamps ----------------------------------------------------------------------------------------
// The dongle publishes Last Configuration Update as a naive Europe/London wall time, `YYYY-MM-DD HH:MM:SS` (its SNTP clock has
// `timezone: Europe/London`; the firmware formats with strftime). Date.parse would read that as BROWSER-local time, which is right only
// in a London-time browser (Window B S-1). It is parsed here explicitly as Europe/London, through Intl with a fixed time zone, so the
// result is the same in every browser zone and across GMT / BST. Fail closed: an unparsable, impossible (spring-forward gap) or future
// text gives null; the ambiguous autumn fall-back hour resolves to the EARLIER instant (it reads older, never newer).
const WALL_RE = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;
const LONDON = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London", hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
});

/** The Europe/London wall time of a UTC instant, in the dongle's own `YYYY-MM-DD HH:MM:SS` form. */
export function formatLondonWall(ms: number): string {
  const parts = LONDON.formatToParts(new Date(ms));
  const g = (t: string): string => parts.find((p) => p.type === t)?.value ?? "";
  return `${g("year")}-${g("month")}-${g("day")} ${g("hour")}:${g("minute")}:${g("second")}`;
}

/** The Europe/London wall-clock fields of a UTC instant (weekday 0 = Sunday, as the gate's `now().weekday() == 6` means Sunday). */
export function londonParts(ms: number): { year: number; month: number; day: number; hour: number; minute: number; second: number; weekday: number } {
  const parts = LONDON.formatToParts(new Date(ms));
  const g = (t: string): number => Number(parts.find((p) => p.type === t)?.value ?? "0");
  const year = g("year"), month = g("month"), day = g("day");
  return { year, month, day, hour: g("hour"), minute: g("minute"), second: g("second"), weekday: new Date(Date.UTC(year, month - 1, day)).getUTCDay() };
}

/** Minutes since midnight, Europe/London, of a UTC instant: the slot clock the inverter and the gate use, not the browser's zone. */
export function londonMinutes(ms: number): number {
  const p = londonParts(ms);
  return p.hour * 60 + p.minute;
}

/** A Europe/London wall time -> UTC ms, independent of the browser's zone; null when the text is not EXACTLY of that form (no padding or
 *  suffix, as the backend's parser) or names no London instant. */
export function londonWallToUtcMs(text: string): number | null {
  const t = text;
  const m = WALL_RE.exec(t);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number) as [number, number, number, number, number, number];
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 59) return null;
  const base = Date.UTC(y, mo - 1, d, h, mi, s);
  const hits: number[] = [];
  for (const offsetMin of [0, 60]) {
    const utc = base - offsetMin * 60_000;
    if (formatLondonWall(utc) === t) hits.push(utc);
  }
  return hits.length ? Math.min(...hits) : null;
}

/** Seconds since the dongle's Last Configuration Update, or null when it is unavailable, unparsable or in the future. The state object's
 *  own UTC `last_changed` (new on every poll, since the text carries seconds) is a cross-check that can only make the age LARGER. */
export function configAgeSeconds(states: StatesLike, prefix: string, nowMs: number): number | null {
  const e = states[dongleIds(prefix).configUpdate];
  const s = stateText(states, dongleIds(prefix).configUpdate);
  if (s === null) return null;
  const wallMs = londonWallToUtcMs(s);
  if (wallMs === null) return null;
  let age = (nowMs - wallMs) / 1000;
  if (age < -CLOCK_SKEW_TOLERANCE_S) return null;
  const lc = changedMs(e);
  if (lc !== null) {
    const lcAge = (nowMs - lc) / 1000;
    if (lcAge >= -CLOCK_SKEW_TOLERANCE_S) age = Math.max(age, lcAge);
  }
  return Math.max(0, age);
}

export function formatAge(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
}

export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** "HH:MM" -> minutes since midnight, or null (the firmware publishes `?nnnn` for an out-of-range word). */
export function parseHHMM(text: string | null): number | null {
  if (text === null) return null;
  const m = HHMM_RE.exec(text.trim());
  if (!m || m[1] === undefined || m[2] === undefined) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  if (h > 23 || mi > 59) return null;
  return h * 60 + mi;
}

// ---- The plan record, the result text and the typed phrase ------------------------------------------------------

export function parsePlan(text: string | null): Plan | null {
  if (text === null || text === "used") return null;
  const f = text.split("|");
  if (f.length !== 6) return null;
  const slot = Number(f[0]);
  const setting = f[1] as Setting;
  const reviewedAt = Number(f[4]);
  if (!Number.isInteger(slot) || slot < 1 || slot > 6) return null;
  if (!SETTINGS.includes(setting)) return null;
  if (!/^\d{4}$/.test(f[3] ?? "")) return null;
  if (!Number.isInteger(reviewedAt) || reviewedAt <= 0) return null;
  const want = f[2] ?? "";
  const before = f[5] ?? "";
  if (setting === "charge_source" ? !/^(Grid|None)$/.test(want) : !/^-?\d+$/.test(want)) return null;
  return { slot, setting, want, code: f[3] ?? "", reviewedAt, before };
}

const RESULT_PREFIXES: [string, ResultKind][] = [
  ["REVIEW REFUSED - ", "review_refused"],
  ["REVIEWED - ", "reviewed"],
  ["REFUSED - ", "refused"],
  ["IN PROGRESS - ", "in_progress"],
  ["APPLIED AND VERIFIED - ", "applied"],
  ["FAILED - ", "failed"],
  ["UNCERTAIN - ", "uncertain"],
  ["ACKNOWLEDGED - ", "acknowledged"],
];

/** The editor's last result, by its exact prefix. Anything unrecognised is `unknown` (the card then fails closed). */
export function classifyResult(text: string | null): Result {
  if (text === null) return { kind: "none", text: "" };
  for (const [prefix, kind] of RESULT_PREFIXES) if (text.startsWith(prefix)) return { kind, text };
  return { kind: "unknown", text };
}

/** The setting's display form as the package spells it: `x %`, `w W`, `HH:MM`, or the source word. */
export function displayValue(setting: Setting, raw: string): string {
  if (setting === "target_soc") return `${raw} %`;
  if (setting === "power") return `${raw} W`;
  if (setting === "start_time") {
    const n = Number(raw);
    return Number.isInteger(n) && n >= 0 ? `${String(Math.floor(n / 100)).padStart(2, "0")}:${String(n % 100).padStart(2, "0")}` : raw;
  }
  return raw;
}

/** The exact confirmation phrase the Apply script expects for a plan (the package's `SET SLOT n <phr> REVIEW code`). */
export function phraseFor(plan: Plan): string {
  let phr: string;
  if (plan.setting === "target_soc") phr = `TARGET SOC ${plan.want}`;
  else if (plan.setting === "power") phr = `POWER ${plan.want} W`;
  else if (plan.setting === "start_time") phr = `START ${displayValue("start_time", plan.want)}`;
  else phr = `CHARGE SOURCE ${plan.want.toUpperCase()}`;
  return `SET SLOT ${plan.slot} ${phr} REVIEW ${plan.code}`;
}

export function phraseMatches(typed: string, plan: Plan): boolean {
  return typed === phraseFor(plan);
}

const LABEL_TO_SETTING: Record<string, Setting> = {
  "target SOC": "target_soc",
  power: "power",
  "start time": "start_time",
  "charge source": "charge_source",
};

/** Undo the package's display form back to the record's raw value. */
export function rawFromDisplay(setting: Setting, disp: string): string | null {
  const d = disp.trim();
  if (setting === "target_soc") {
    const m = /^(-?\d+) %$/.exec(d);
    return m && m[1] !== undefined ? m[1] : null;
  }
  if (setting === "power") {
    const m = /^(-?\d+) W$/.exec(d);
    return m && m[1] !== undefined ? m[1] : null;
  }
  if (setting === "start_time") {
    const mins = parseHHMM(d);
    return mins === null ? null : String(Math.floor(mins / 60) * 100 + (mins % 60));
  }
  return /^(Grid|None)$/.test(d) ? d : null;
}

const APPLIED_RE = /^APPLIED AND VERIFIED - slot ([1-6]) (target SOC|power|start time|charge source) (.+?) -> (.+?): /;
const OWNER_EDIT_RE = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} slot ([1-6]) (target SOC|power|start time|charge source) \(register (\d+)\) (.+?) -> (.+?) \(owner, Advanced Configuration\)$/;

function record(slotText: string, label: string, beforeDisp: string, afterDisp: string): EditRecord | null {
  const setting = LABEL_TO_SETTING[label];
  if (!setting) return null;
  const before = rawFromDisplay(setting, beforeDisp);
  const after = rawFromDisplay(setting, afterDisp);
  if (before === null || after === null) return null;
  return { slot: Number(slotText), setting, before, after };
}

export function parseApplied(text: string): EditRecord | null {
  const m = APPLIED_RE.exec(text);
  if (!m || m[1] === undefined || m[2] === undefined || m[3] === undefined || m[4] === undefined) return null;
  return record(m[1], m[2], m[3], m[4]);
}

export function parseOwnerEdit(text: string | null): EditRecord | null {
  if (text === null) return null;
  const m = OWNER_EDIT_RE.exec(text);
  if (!m || m[1] === undefined || m[2] === undefined || m[3] === undefined || m[4] === undefined || m[5] === undefined) return null;
  const rec = record(m[1], m[2], m[4], m[5]);
  if (!rec) return null;
  if (Number(m[3]) !== SETTING_REGISTER_BASE[rec.setting] + rec.slot) return null;
  return rec;
}

// ---- Service calls (descriptions only; actions.ts performs them) ------------------------------------------------

export function reviewCall(draft: Draft): ServiceCall {
  return {
    domain: "script",
    service: "turn_on",
    data: { entity_id: SCRIPT_REVIEW, variables: { slot: draft.slot, setting: draft.setting, value: draftValueForScript(draft) } },
  };
}

/** The value as the Review script's templates expect it: a whole number for SOC / power, the word for the source. */
export function draftValueForScript(draft: Draft): string | number {
  if (draft.setting === "charge_source") return draft.value;
  return Number(draft.value);
}

export function applyCall(confirmation: string): ServiceCall {
  return { domain: "script", service: "turn_on", data: { entity_id: SCRIPT_APPLY, variables: { confirmation } } };
}

export function acknowledgeCall(confirmation: string): ServiceCall {
  return { domain: "script", service: "turn_on", data: { entity_id: SCRIPT_ACK, variables: { confirmation } } };
}

// ---- Clock-change nights, active slot ---------------------------------------------------------------------------

/** 00:00-03:00 Europe/London on the last Sunday of March and of October (the gate's rule), read on the London clock whatever the
 *  browser's zone (Window B O-1): advisory, the gate decides. */
export function isClockChangeNight(nowMs: number): boolean {
  const p = londonParts(nowMs);
  return (p.month === 3 || p.month === 10) && p.weekday === 0 && p.day >= 25 && p.hour < 3;
}

/** Which slot holds the local time, given the six start minutes (null when any start is unreadable). Wrap-safe. */
export function activeSlot(starts: (number | null)[], nowMinutes: number): number | null {
  if (starts.length !== 6 || starts.some((s) => s === null)) return null;
  const t = starts as number[];
  for (let i = 0; i < 6; i++) {
    const start = t[i] ?? 0;
    const end = t[(i + 1) % 6] ?? 0;
    const len = (end - start + 1440) % 1440;
    if (len === 0) continue;
    if ((nowMinutes - start + 1440) % 1440 < len) return i + 1;
  }
  return null;
}

export function startsAscending(starts: (number | null)[]): boolean {
  if (starts.length !== 6 || starts.some((s) => s === null)) return false;
  const t = starts as number[];
  for (let i = 1; i < 6; i++) if ((t[i] ?? 0) <= (t[i - 1] ?? 0)) return false;
  return true;
}

// ---- Slot views ------------------------------------------------------------------------------------------------

function valueText(states: StatesLike, id: string, nowMs: number, unit: string | null, numeric: boolean): ValueText {
  const e = states[id];
  if (!e) return { text: "Entity not found", numeric: null, raw: null, ageSeconds: null };
  const raw = stateText(states, id);
  const age = ageSeconds(e, nowMs);
  if (raw === null) return { text: e.state === "unavailable" ? "Unavailable" : "Unknown", numeric: null, raw: null, ageSeconds: age };
  if (numeric) {
    const n = stateNumber(states, id);
    if (n === null) return { text: "Unexpected value", numeric: null, raw, ageSeconds: age };
    const shown = Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
    return { text: unit ? `${shown} ${unit}` : shown, numeric: n, raw, ageSeconds: age };
  }
  return { text: raw, numeric: null, raw, ageSeconds: age };
}

function timeText(states: StatesLike, id: string, nowMs: number): ValueText {
  const v = valueText(states, id, nowMs, null, false);
  if (v.raw !== null && parseHHMM(v.raw) === null) return { ...v, text: "Unexpected value" };
  return v;
}

export interface Context {
  /** Blockers that stop every edit (the status line), in priority order. */
  blockers: Blocker[];
  /** Set when the editor's last result text is one the card does not recognise (or a stale IN PROGRESS): every edit path is closed (O2). */
  resultProblem: string | null;
  configCurrent: boolean;
  shutdownSoc: number | null;
  reserveSoc: number | null;
  socFloor: number | null;
}

export function context(states: StatesLike, config: CardConfig, nowMs: number, now: Date): Context {
  const d = dongleIds(config.entity_prefix);
  const blockers: Blocker[] = [];
  const configAge = configAgeSeconds(states, config.entity_prefix, nowMs);
  const configCurrent = configAge !== null && configAge <= CONFIG_CURRENT_S && isOn(states, d.configOnline);
  const heartbeat = stateNumber(states, d.heartbeatAge);
  if (isOn(states, H_LOCK)) blockers.push({ code: "locked", text: "Edits locked: an earlier edit's outcome needs your manual review" });
  if (!isOff(states, SCRIPT_APPLY) || !isOff(states, H_IN_FLIGHT)) {
    blockers.push({ code: "busy", text: exists(states, SCRIPT_APPLY) && exists(states, H_IN_FLIGHT) ? "An edit is being applied" : "The editor's state cannot be read" });
  }
  if (!isOff(states, d.fpActive) || !isOff(states, d.fpOp) || !isOff(states, d.fpSnapshot)) {
    blockers.push({ code: "free_power", text: "Owned by Free Power (active, starting or restore owed)" });
  }
  if (!isOff(states, d.dgActive) || !isOff(states, d.dgOp) || !isOff(states, d.dgSnapshot)) {
    blockers.push({ code: "dump_to_grid", text: "Owned by Dump to Grid (active, starting or restore owed)" });
  }
  if (!isOn(states, d.telemetryOnline) || !isOn(states, d.configOnline) || !isOn(states, d.cacheValid)) {
    blockers.push({ code: "offline", text: "Dongle offline or configuration cache not valid" });
  } else if (configAge === null || configAge > CONFIG_CURRENT_S) {
    blockers.push({ code: "config_stale", text: configAge === null ? "Configuration read time unreadable" : `Configuration not current (read ${formatAge(configAge)} ago; limit ${CONFIG_CURRENT_S} s)` });
  }
  if (heartbeat === null || heartbeat < 0 || heartbeat > HEARTBEAT_MAX_S) {
    blockers.push({ code: "heartbeat", text: heartbeat === null ? "Supervision heartbeat unreadable" : `Supervision heartbeat not current (${formatAge(heartbeat)}; limit ${HEARTBEAT_MAX_S} s)` });
  }
  if (!isOn(states, d.supervisionStable)) blockers.push({ code: "supervision", text: "Supervision not stable" });
  void now;
  if (isClockChangeNight(nowMs)) blockers.push({ code: "clock_change", text: "Clock-change night: no edits 00:00-03:00 local on the last Sunday of March and of October (Home Assistant decides)" });
  if (!isOff(states, d.writeInProgress)) blockers.push({ code: "write_in_progress", text: "Another inverter write or fallback operation is in progress" });
  if (!isOff(states, d.rtcInProgress)) blockers.push({ code: "rtc", text: "RTC correction in progress" });
  if ([d.writeEnable, d.fpWriteEnable, d.fpRecoveryArm, d.dgWriteEnable, d.dgRecoveryArm].some((id) => !isOff(states, id))) {
    blockers.push({ code: "armed", text: "A write or recovery arm is on" });
  }
  const soonMs = nowMs + SCHEDULE_SOON_S * 1000;
  for (const [armed, start, name] of [[H_FP_ARMED, H_FP_START, "Free Power"], [H_DG_ARMED, H_DG_START, "Dump to Grid"]] as const) {
    if (isOn(states, armed)) {
      // The input_datetime state is Home Assistant's local wall time, `YYYY-MM-DD HH:MM:SS` Europe/London: the London parser, not Date.parse (O-1).
      const t = londonWallToUtcMs(stateText(states, start) ?? "");
      if (t === null || t < soonMs) blockers.push({ code: "scheduled", text: `A scheduled ${name} starts within 15 minutes (or its start time is unreadable)` });
    }
  }
  const shutdownSoc = stateNumber(states, d.shutdownSoc);
  const reserveSoc = stateNumber(states, H_RESERVE);
  const socFloor = shutdownSoc !== null && reserveSoc !== null ? Math.max(shutdownSoc, reserveSoc) : null;
  const rk = classifyResult(stateText(states, H_RESULT)).kind;
  const resultProblem = rk === "unknown" || rk === "in_progress"
    ? "The editor's last result text is not one this card recognises (or an IN PROGRESS text with no Apply running): use the ECCO scripts directly, or wait for the editor"
    : null;
  return { blockers, resultProblem, configCurrent, shutdownSoc, reserveSoc, socFloor };
}

/** Why a refusal that names supervision or a failback episode means a supervised dongle reboot, shown beside the verbatim text. */
export const SHADOW_REFUSAL_HINT =
  "A Home Assistant outage of more than about five minutes can latch the failback shadow and block every edit until a separately " +
  "authorised, supervised dongle reboot clears it; the editor's own gate decides, and nothing in this card works around it.";

export function refusalHint(text: string): string | null {
  return /supervision not stable or a failback episode is open/.test(text) ? SHADOW_REFUSAL_HINT : null;
}

export function slotView(states: StatesLike, config: CardConfig, slot: number, nowMs: number, nowMinutes: number, ctx: Context): SlotView {
  const ids = slotIds(config.entity_prefix, slot);
  const next = slotIds(config.entity_prefix, slot === 6 ? 1 : slot + 1);
  const start = timeText(states, ids.time, nowMs);
  const end = timeText(states, next.time, nowMs);
  const power = valueText(states, ids.power, nowMs, "W", true);
  const soc = valueText(states, ids.soc, nowMs, "%", true);
  const source = valueText(states, ids.charge, nowMs, null, false);
  const mode = valueText(states, ids.mode, nowMs, null, false);
  const flagsReadable = stateNumber(states, ids.flags) !== null;
  const fields = [start, power, soc, source, mode];
  const ages = fields.map((v) => v.ageSeconds);
  const ageSecondsMax = ages.some((a) => a === null) ? null : Math.max(...(ages as number[]));
  const available = fields.every((v) => v.raw !== null);
  // "live" needs every value reported within the label window AND within the fixed 300 s (a wider window never makes a stale row "live": O-5)
  const fresh = available && ageSecondsMax !== null && ageSecondsMax <= Math.min(config.max_age_configuration_s, EDIT_FRESH_S);
  // B1: the dongle re-publishes a slot value only when it changes and the frontend's state objects carry no same-value re-report,
  // so an unchanged value keeps the time it last changed. It is current when its own report is recent, or when the configuration
  // poll that would have re-read it is itself current (the gate's own limit, ctx.configCurrent). Editing needs the current poll in
  // every case (common() checks it first); `currentBy` only tells the display which word is honest. A value with no usable timestamp
  // is "unverified" for display and counts only by the poll (the catalogue card shows such a value as unverified and never edits).
  const currentBy: SlotView["currentBy"] = !available ? "none" : ageSecondsMax !== null && ageSecondsMax <= EDIT_FRESH_S ? "report" : ctx.configCurrent ? "poll" : "none";
  const current = currentBy !== "none";
  const starts: (number | null)[] = [];
  for (let n = 1; n <= 6; n++) starts.push(parseHHMM(stateText(states, slotIds(config.entity_prefix, n).time)));
  const active = activeSlot(starts, nowMinutes) === slot;
  const common = (): Eligibility | null => {
    const b = ctx.blockers[0];
    if (b) return { allowed: false, reason: b.text };
    if (ctx.resultProblem) return { allowed: false, reason: ctx.resultProblem };
    if (!ctx.configCurrent) return { allowed: false, reason: "The configuration read is not current" };
    if (!current) return { allowed: false, reason: "This slot's values are not current (a value is unavailable, or it has no recent report and the configuration poll is not current)" };
    if (!flagsReadable) return { allowed: false, reason: "The slot's raw flags are unreadable (needed by every edit)" };
    return null;
  };
  const elig = (setting: EditableSetting): Eligibility => {
    const c = common();
    if (c) return c;
    if (setting === "target_soc") {
      if (soc.numeric === null) return { allowed: false, reason: "Live target SOC unavailable" };
      if (ctx.socFloor === null) return { allowed: false, reason: "Inverter shutdown SOC or ECCO reserve unavailable (the SOC bound's inputs)" };
      return { allowed: true, reason: "" };
    }
    if (setting === "power") {
      if (power.numeric === null) return { allowed: false, reason: "Live power unavailable" };
      if (power.numeric % POWER_STEP_W !== 0) return { allowed: false, reason: `The live power ${power.text} is not a multiple of 100 W; the undo would be refused - align it first in Manual Controls` };
      return { allowed: true, reason: "" };
    }
    if (source.raw === null) return { allowed: false, reason: "Live charge source unavailable" };
    if (source.raw !== "None" && source.raw !== "Grid") return { allowed: false, reason: `The live charge source is ${source.raw}: only None and Grid can be edited` };
    return { allowed: true, reason: "" };
  };
  return {
    slot, start, end, power, soc, source, mode, flagsReadable,
    ageSeconds: ageSecondsMax, fresh, current, currentBy, pollCurrent: ctx.configCurrent, available, active,
    eligibility: { target_soc: elig("target_soc"), power: elig("power"), charge_source: elig("charge_source") },
  };
}

// ---- Draft validation -------------------------------------------------------------------------------------------

export function validateDraft(draft: Draft, view: SlotView, ctx: Context): Eligibility {
  const e = view.eligibility[draft.setting];
  if (!e.allowed) return e;
  const v = draft.value.trim();
  if (draft.setting === "charge_source") {
    if (v !== "Grid" && v !== "None") return { allowed: false, reason: "Charge source must be None or Grid" };
    if (v === view.source.raw) return { allowed: false, reason: `No change (slot ${view.slot} is already ${v})` };
    return { allowed: true, reason: "" };
  }
  if (!/^-?\d+$/.test(v)) return { allowed: false, reason: "Enter a whole number" };
  const n = Number(v);
  if (draft.setting === "power") {
    if (n < POWER_MIN_W || n > POWER_MAX_W || n % POWER_STEP_W !== 0) return { allowed: false, reason: `Power must be ${POWER_MIN_W}-${POWER_MAX_W} W in steps of ${POWER_STEP_W} W` };
    if (n === view.power.numeric) return { allowed: false, reason: `No change (slot ${view.slot} is already ${n} W)` };
    return { allowed: true, reason: "" };
  }
  const lo = ctx.socFloor ?? 100;
  if (n < lo || n > 100) return { allowed: false, reason: `Target SOC must be ${lo}-100 % (the greater of the inverter shutdown SOC ${ctx.shutdownSoc ?? "?"} % and the ECCO reserve ${ctx.reserveSoc ?? "?"} %)` };
  if (n === view.soc.numeric) return { allowed: false, reason: `No change (slot ${view.slot} is already ${n} %)` };
  return { allowed: true, reason: "" };
}

/** True when the live plan is exactly the proposal reviewed in this card (slot, setting and value). */
export function planMatchesDraft(plan: Plan, draft: Draft): boolean {
  if (plan.slot !== draft.slot || plan.setting !== draft.setting) return false;
  return plan.setting === "charge_source" ? plan.want === draft.value.trim() : Number(plan.want) === Number(draft.value.trim());
}

// ---- The editor state ------------------------------------------------------------------------------------------

const REQUIRED = [SCRIPT_REVIEW, SCRIPT_APPLY, SCRIPT_ACK, H_PLAN, H_RESULT, H_OWNER_EDIT, H_LOCK, H_IN_FLIGHT, H_WRITE_SEEN];

export function editorView(states: StatesLike, config: CardConfig, nowMs: number, now: Date, ctx: Context, slots: SlotView[]): EditorView {
  const missing = REQUIRED.filter((id) => !exists(states, id));
  const result = classifyResult(stateText(states, H_RESULT));
  const plan = parsePlan(stateText(states, H_PLAN));
  const lock = isOn(states, H_LOCK);
  // not-off, as the scripts test it: an unavailable or unknown marker is treated as in flight (O-4)
  const inFlight = !isOff(states, H_IN_FLIGHT);
  const applyRunning = !isOff(states, SCRIPT_APPLY);
  const reviewRunning = !isOff(states, SCRIPT_REVIEW);
  const nowS = nowMs / 1000;
  const planAge = plan ? nowS - plan.reviewedAt : null;
  const planLive = plan !== null && planAge !== null && planAge >= -CLOCK_SKEW_TOLERANCE_S && planAge < PLAN_TTL_S
    && result.kind === "reviewed" && result.text.endsWith(` REVIEW ${plan.code}`);
  let state: EditorState;
  if (missing.length) state = "UNAVAILABLE";
  else if (lock) state = "LOCKED";
  else if (applyRunning || inFlight) state = "BUSY";
  else if (planLive) state = "REVIEWED";
  else if (result.kind === "none" || result.kind === "acknowledged") state = "IDLE";
  else state = "OUTCOME";
  return {
    state, result, plan, planLive,
    planExpiresInS: planLive && planAge !== null ? PLAN_TTL_S - planAge : null,
    lock, inFlight, applyRunning, reviewRunning,
    blockers: ctx.blockers,
    spacingRemainingS: spacingRemaining(states, result, nowMs),
    undo: state === "OUTCOME" ? undoFor(states, config, result, slots, ctx) : null,
    progress: state === "BUSY" ? progressSteps(states, config, result) : [],
    missing,
  };
}

/** Seconds still to wait before the next Apply under the provisional spacing rule (0 when none). The stamps, the latest of which
 *  counts: the result text while it is still an outcome; the owner-edit record (success only); and the in-flight marker's last change
 *  while it is off (every Apply that passed its first gate turns it on and, when judged, off, so a FAILED or UNCERTAIN Apply stamps
 *  it too, and the stamp survives the next Review: Window B S1). A REFUSED Apply never reached the gate and adds no stamp (the Apply
 *  script's last_triggered is deliberately NOT used: Home Assistant sets it for a refused run too; Window B N1). */
export function spacingRemaining(states: StatesLike, result: Result, nowMs: number): number {
  const stamps: number[] = [];
  if (result.kind === "applied" || result.kind === "failed" || result.kind === "uncertain") {
    const t = changedMs(states[H_RESULT]);
    if (t !== null) stamps.push(t);
  }
  const o = changedMs(states[H_OWNER_EDIT]);
  if (o !== null) stamps.push(o);
  if (isOff(states, H_IN_FLIGHT)) {
    const f = changedMs(states[H_IN_FLIGHT]);
    if (f !== null) stamps.push(f);
  }
  if (!stamps.length) return 0;
  const since = (nowMs - Math.max(...stamps)) / 1000;
  if (since < -CLOCK_SKEW_TOLERANCE_S) return APPLY_SPACING_S;
  return Math.max(0, APPLY_SPACING_S - since);
}

/** Undo (owner decision D6): only after APPLIED AND VERIFIED, when the result and the owner-edit record agree on the slot,
 *  the setting and both values, the setting is editable here, and a fresh live read shows the edited field at the post-edit
 *  value. Otherwise null: the owner reviews by hand. */
export function undoFor(states: StatesLike, config: CardConfig, result: Result, slots: SlotView[], ctx: Context): Undo | null {
  if (result.kind !== "applied") return null;
  const a = parseApplied(result.text);
  const o = parseOwnerEdit(stateText(states, H_OWNER_EDIT));
  if (!a || !o) return null;
  if (a.slot !== o.slot || a.setting !== o.setting || a.before !== o.before || a.after !== o.after) return null;
  if (a.setting === "start_time") return null;
  if (a.before === a.after) return null;
  const view = slots[a.slot - 1];
  // B1: current by its own report or by the poll (the same rule as editing); S2: the slot must be eligible for that setting right now
  // (every advisory blocker clear), and the undo value must pass the same local validation a hand-typed Review would.
  if (!view || !view.current) return null;
  if (!view.eligibility[a.setting].allowed) return null;
  const live = a.setting === "target_soc" ? view.soc.numeric : a.setting === "power" ? view.power.numeric : view.source.raw;
  if (live === null) return null;
  const matches = a.setting === "charge_source" ? live === a.after : Number(live) === Number(a.after);
  if (!matches) return null;
  const ids = slotIds(config.entity_prefix, a.slot);
  if (!exists(states, ids.flags)) return null;
  const draft: Draft = { slot: a.slot, setting: a.setting, value: a.before };
  if (!validateDraft(draft, view, ctx).allowed) return null;
  return { slot: a.slot, setting: a.setting, value: a.before, from: a.after };
}

/** The derived progress strip while an Apply is in flight. Every step says only what its signal has shown right now. */
export function progressSteps(states: StatesLike, config: CardConfig, result: Result): ProgressStep[] {
  const d = dongleIds(config.entity_prefix);
  const m = /^IN PROGRESS - slot ([1-6]) /.exec(result.text);
  const slot = m && m[1] !== undefined ? m[1] : null;
  const fw = stateText(states, d.manualLastResult) ?? "";
  const armed = isOn(states, d.writeEnable);
  const writing = !isOff(states, d.writeInProgress) || fw.startsWith("Writing Slot");
  const loaded = slot !== null && fw.startsWith(`Manual staging loaded from current inverter Slot ${slot} `);
  const verified = slot !== null && fw.startsWith(`VERIFIED OK - manual Slot ${slot} `);
  const problem = fw.startsWith("VERIFY FAILED") || fw.startsWith("FAILED - one or more write transactions") || fw.startsWith("REJECTED");
  return [
    { label: "Requested (editor in flight)", seen: true },
    { label: "Staging loaded from the live slot", seen: loaded || armed || writing || verified },
    { label: "Write enable armed", seen: armed || writing || verified },
    { label: "Writing", seen: writing || verified },
    { label: verified ? "Firmware readback VERIFIED OK" : problem ? `Firmware reported: ${fw.slice(0, 60)}` : "Firmware readback", seen: verified || problem },
    { label: "Judging (later reads, gate counter)", seen: (verified || problem) && !armed && !writing },
  ];
}
