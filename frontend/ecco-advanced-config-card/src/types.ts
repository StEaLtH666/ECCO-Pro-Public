// Types of the generated catalogue (src/catalogue.generated.ts) and of the card's view models.
// Type-only module: it has no runtime code, so importing it with `import type` is erased everywhere.

export type Status = "PROVEN" | "EXPERIMENTAL" | "READ_ONLY" | "LOCKED" | "UNSUPPORTED";
export type Evidence = "M3" | "M2" | "M1" | "M0" | "MX";
export type Danger = "D0" | "D1" | "D2" | "D3" | "D4";
export type PollClass = "rtc" | "telemetry" | "configuration";

export interface RegisterRef {
  address: number;
  bits: string | null;
}

export interface EntityRef {
  domain: string;
  object: string;
  firmware_id: string;
  name: string;
  link?: string;
}

export interface Decode {
  kind: string;
  window: string;
  registers: number[];
  signed?: boolean;
  scale?: number;
  offset?: number;
  mask?: number;
  equals?: number;
  set_text?: string;
  clear_text?: string;
}

export interface EnumOption {
  raw: number;
  label: string;
}

export interface Options {
  enum?: EnumOption[];
  enum_source?: string;
  safe_min?: number;
  safe_max?: number;
  firmware_ceiling?: number;
  firmware_ceiling_note?: string;
  registry_limit?: number;
  hardware_maximum?: null;
  bounds_note?: string;
}

export interface Provenance {
  registry_record: string;
  firmware_evidence?: string | null;
  ha_evidence?: string | null;
  implementation_status?: string | null;
}

export interface CatalogueItem {
  id: string;
  name: string;
  category: string;
  section: string;
  registers: RegisterRef[];
  datatype?: string;
  unit?: string;
  status: Status;
  status_derived: Status;
  evidence: Evidence;
  live_proof_status: string;
  write_policy: string;
  current_access: string;
  danger: Danger;
  lock_reason: string;
  entity?: EntityRef;
  raw_entity?: EntityRef;
  decode?: Decode;
  poll_class?: PollClass;
  options: Options;
  description?: string;
  explanation?: string;
  safety_impact?: string;
  write_policy_reason?: string;
  notes?: string;
  interactions: string[];
  options_note?: string;
  provenance: Provenance;
}

export interface Section {
  id: string;
  title: string;
  summary: string;
}

export interface GateRef {
  domain: string;
  object: string;
}

export type FutureControl =
  | "unlock"
  | "staged_value"
  | "permitted_range"
  | "apply"
  | "verification"
  | "previous_value"
  | "history";

export interface GlobalPowerConfig {
  record: string;
  register: number;
  title: string;
  owner_confirmation: { date: string; statement: string };
  hardware_maximum_w: number | null;
  hardware_maximum_evidence: string | null;
  hardware_maximum_note: string | null;
  regulatory_allowance_w: number | null;
  regulatory_note: string | null;
  write_status: "not_implemented" | "disabled";
  write_blockers: string[];
  limitations: string[];
  future_controls: Record<FutureControl, string>;
}

export interface Catalogue {
  schema: string;
  generator: string;
  inputs: string[];
  read_only: true;
  default_entity_prefix_note: string;
  notes?: string;
  controller_note?: string;
  sections: Section[];
  freshness_gates: { telemetry: GateRef; configuration: GateRef };
  steady_windows: string[];
  record_count: number;
  items: CatalogueItem[];
  global_power: GlobalPowerConfig;
}

// ---- Home Assistant (read-only view) -------------------------------------------------------------------------

/** The only part of a Home Assistant state object this card reads. */
export interface HassEntityLike {
  state?: unknown;
  attributes?: Record<string, unknown>;
  last_changed?: unknown;
  last_updated?: unknown;
  last_reported?: unknown;
}

export type StatesLike = Record<string, HassEntityLike | undefined>;

// ---- Card configuration -----------------------------------------------------------------------------------------

export interface CardConfig {
  title: string;
  entity_prefix: string;
  max_age_telemetry_s: number;
  max_age_configuration_s: number;
  max_age_rtc_s: number;
}

// ---- View models ---------------------------------------------------------------------------------------------------

export type ValueState = "ok" | "unavailable" | "unknown" | "missing" | "unmapped" | "unexpected";
export type Freshness = "live" | "unchanged" | "stale" | "unverified" | "not_applicable";

export type RawView =
  | { kind: "reported" | "derived"; value: number; hex: string; note: string }
  | { kind: "unavailable"; note: string };

export interface ValueView {
  state: ValueState;
  entityId: string | null;
  display: string;
  numeric: number | null;
  unit: string | null;
  raw: RawView;
  freshness: Freshness;
  ageSeconds: number | null;
  freshnessNote: string;
  problem: string | null;
}

export interface FilterState {
  query: string;
  statuses: Set<Status>;
  evidence: Set<Evidence>;
  sections: Set<string>;
}
