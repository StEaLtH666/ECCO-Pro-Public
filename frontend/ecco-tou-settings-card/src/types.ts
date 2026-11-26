// Types of the ECCO TOU Settings card's view models. Type-only module: it has no runtime code, so importing it with
// `import type` is erased everywhere.

export interface HassEntityLike {
  state: unknown;
  attributes?: Record<string, unknown>;
  last_changed?: string;
  last_updated?: string;
  last_reported?: string;
}

export type StatesLike = Record<string, HassEntityLike | undefined>;

export interface CardConfig {
  title: string;
  entity_prefix: string;
  /** A slot value older than this (seconds) is shown as stale. */
  max_age_configuration_s: number;
}

/** The ACS1 editor's settings. Only the first three are editable in this card; the start time is display-only (L1). */
export type Setting = "target_soc" | "power" | "charge_source" | "start_time";
export type EditableSetting = "target_soc" | "power" | "charge_source";

/** The plan record the Review script writes to input_text.ecco_cfg_edit_review: slot|setting|want|code|reviewed_at|before. */
export interface Plan {
  slot: number;
  setting: Setting;
  /** The requested value exactly as the record spells it (an integer for SOC / power / HHMM, Grid or None for the source). */
  want: string;
  code: string;
  /** Unix seconds of the review. */
  reviewedAt: number;
  before: string;
}

export type ResultKind =
  | "none"
  | "review_refused"
  | "reviewed"
  | "refused"
  | "in_progress"
  | "applied"
  | "failed"
  | "uncertain"
  | "acknowledged"
  | "unknown";

export interface Result {
  kind: ResultKind;
  text: string;
}

/** Parsed from an APPLIED AND VERIFIED result or the last-owner-edit record. */
export interface EditRecord {
  slot: number;
  setting: Setting;
  before: string;
  after: string;
}

export type EditorState = "UNAVAILABLE" | "LOCKED" | "BUSY" | "REVIEWED" | "OUTCOME" | "IDLE";

export interface Blocker {
  code: string;
  text: string;
}

export interface Eligibility {
  allowed: boolean;
  reason: string;
}

export interface ValueText {
  /** The display text; never a number for a missing value. */
  text: string;
  /** The parsed numeric value, when the setting is numeric and the state is a number. */
  numeric: number | null;
  /** The raw state text, or null when missing / unavailable / unknown. */
  raw: string | null;
  ageSeconds: number | null;
}

export interface SlotView {
  slot: number;
  start: ValueText;
  end: ValueText;
  power: ValueText;
  soc: ValueText;
  source: ValueText;
  mode: ValueText;
  flagsReadable: boolean;
  /** The oldest of the slot's own reports, in seconds, or null when any is missing. */
  ageSeconds: number | null;
  /** Display: every value reported within max_age_configuration_s. */
  fresh: boolean;
  /** Eligibility (B1): every value available and either reported within 300 s or unchanged while the configuration poll is current. */
  current: boolean;
  currentBy: "report" | "poll" | "none";
  /** The configuration poll is current (online, read within 150 s): what the labels may claim about the poll (O-5). */
  pollCurrent: boolean;
  /** Every one of the slot's five display values has a value. */
  available: boolean;
  active: boolean;
  eligibility: Record<EditableSetting, Eligibility>;
}

export interface Draft {
  slot: number;
  setting: EditableSetting;
  value: string;
}

export interface Undo {
  slot: number;
  setting: EditableSetting;
  value: string;
  from: string;
}

export interface ProgressStep {
  label: string;
  seen: boolean;
}

export interface EditorView {
  state: EditorState;
  result: Result;
  plan: Plan | null;
  /** The plan is valid (six fields, not used, not expired) and the result text names its code. */
  planLive: boolean;
  planExpiresInS: number | null;
  lock: boolean;
  inFlight: boolean;
  applyRunning: boolean;
  reviewRunning: boolean;
  blockers: Blocker[];
  spacingRemainingS: number;
  undo: Undo | null;
  progress: ProgressStep[];
  missing: string[];
}

export interface ServiceCall {
  domain: "script";
  service: "turn_on";
  data: { entity_id: string; variables: Record<string, string | number> };
}
