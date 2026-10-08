// Pure, DOM-free logic of the Advanced / Experimental Configuration card.
//
// READ-ONLY BY CONSTRUCTION: nothing in this module (or anywhere in this card) can change Home Assistant or the inverter.
// It only reads the `states` map it is handed, and it never receives the Home Assistant object itself.
import type {
  CardConfig,
  Catalogue,
  CatalogueItem,
  Evidence,
  FilterState,
  Freshness,
  FutureControl,
  GateRef,
  HassEntityLike,
  RawView,
  StatesLike,
  Status,
  ValueView,
} from "./types.ts";

export const DEFAULT_ENTITY_PREFIX = "ecco_clock_dongle";
export const DEFAULT_TITLE = "Advanced / Experimental Configuration";
export const HARDWARE_MAXIMUM_NOT_VERIFIED = "Hardware maximum not verified";
export const REGULATORY_ALLOWANCE_NOT_RECORDED = "Regulatory export allowance not recorded";

const PREFIX_RE = /^[a-z][a-z0-9_]*[a-z0-9]$/;
// Home Assistant reports numeric sensor states as plain decimal text. Anything else (hex, "Infinity", units) is unexpected.
const DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const WORD_RE = /^\d{1,5}$/;
const LAYOUT_KEYS = new Set(["type", "view_layout", "grid_options", "visibility", "layout_options"]);
const CONFIG_KEYS = new Set(["title", "entity_prefix", "max_age_telemetry_s", "max_age_configuration_s", "max_age_rtc_s"]);
const CLOCK_SKEW_TOLERANCE_S = 60;

export const STATUS_LABEL: Record<Status, string> = {
  PROVEN: "Proven (elsewhere in ECCO)",
  EXPERIMENTAL: "Experimental",
  READ_ONLY: "Read only",
  LOCKED: "Locked",
  UNSUPPORTED: "Unsupported",
};

export const STATUS_HELP: Record<Status, string> = {
  PROVEN: "A hardware-tested write path exists in ECCO's own guarded controls. This page cannot write it.",
  EXPERIMENTAL: "A firmware write path exists but is not hardware-proven. This page cannot write it.",
  READ_ONLY: "ECCO has no write path. Shown for inspection only.",
  LOCKED: "Safety-critical. Permanently read-only on this installation.",
  UNSUPPORTED: "Register or meaning not established. Never a control.",
};

export const EVIDENCE_LABEL: Record<Evidence, string> = {
  M3: "M3 write-proven",
  M2: "M2 read-proven",
  M1: "M1 documented",
  M0: "M0 inferred",
  MX: "MX unknown",
};

export const DANGER_LABEL: Record<string, string> = {
  D0: "D0 telemetry",
  D1: "D1 cost / tariff",
  D2: "D2 availability",
  D3: "D3 regulatory",
  D4: "D4 equipment / safety",
};

export const STATUS_ORDER: Status[] = ["PROVEN", "EXPERIMENTAL", "READ_ONLY", "LOCKED", "UNSUPPORTED"];
export const EVIDENCE_ORDER: Evidence[] = ["M3", "M2", "M1", "M0", "MX"];

// ---- Configuration ---------------------------------------------------------------------------------------------

function positiveSeconds(v: unknown, key: string, dflt: number): number {
  if (v === undefined) return dflt;
  if (typeof v !== "number" || !Number.isFinite(v) || v < 5 || v > 86400) {
    throw new Error(`${key} must be a number of seconds between 5 and 86400`);
  }
  return v;
}

/** Validate a Lovelace card config. Throws (Home Assistant shows the message) on anything malformed. */
export function normalizeConfig(raw: unknown): CardConfig {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("ecco-advanced-config-card: the configuration must be a mapping");
  }
  const cfg = raw as Record<string, unknown>;
  for (const key of Object.keys(cfg)) {
    if (!CONFIG_KEYS.has(key) && !LAYOUT_KEYS.has(key)) {
      throw new Error(`ecco-advanced-config-card: unknown option '${key}'`);
    }
  }
  const prefix = cfg.entity_prefix === undefined ? DEFAULT_ENTITY_PREFIX : cfg.entity_prefix;
  if (typeof prefix !== "string" || !PREFIX_RE.test(prefix) || prefix.includes("__")) {
    throw new Error("entity_prefix must be a Home Assistant device slug (lower-case letters, digits, single underscores)");
  }
  const title = cfg.title === undefined ? DEFAULT_TITLE : cfg.title;
  if (typeof title !== "string" || title.length > 120) {
    throw new Error("title must be text of at most 120 characters");
  }
  return {
    title,
    entity_prefix: prefix,
    max_age_telemetry_s: positiveSeconds(cfg.max_age_telemetry_s, "max_age_telemetry_s", 120),
    max_age_configuration_s: positiveSeconds(cfg.max_age_configuration_s, "max_age_configuration_s", 300),
    max_age_rtc_s: positiveSeconds(cfg.max_age_rtc_s, "max_age_rtc_s", 300),
  };
}

export function entityId(ref: { domain: string; object: string }, prefix: string): string {
  return `${ref.domain}.${prefix}_${ref.object}`;
}

// ---- Formatting ------------------------------------------------------------------------------------------------

export function formatNumber(v: number, maxDecimals = 3): string {
  if (Number.isInteger(v)) return String(v);
  const fixed = v.toFixed(maxDecimals);
  return fixed.replace(/\.?0+$/, "");
}

export function formatAge(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
}

export function hex16(v: number): string {
  return "0x" + (v & 0xffff).toString(16).toUpperCase().padStart(4, "0");
}

export function registerLabel(item: CatalogueItem): string {
  if (!item.registers.length) return "no register";
  return item.registers.map((r) => (r.bits !== null && r.bits !== undefined ? `${r.address} bits ${r.bits}` : String(r.address))).join(", ");
}

// ---- Values ----------------------------------------------------------------------------------------------------

function timestampMs(e: HassEntityLike): number | null {
  for (const key of ["last_reported", "last_updated", "last_changed"] as const) {
    const v = e[key];
    if (typeof v === "string" && v) {
      const t = Date.parse(v);
      if (Number.isFinite(t)) return t;
    }
  }
  return null;
}

function maxAgeFor(item: CatalogueItem, config: CardConfig): number {
  if (item.poll_class === "telemetry") return config.max_age_telemetry_s;
  if (item.poll_class === "rtc") return config.max_age_rtc_s;
  return config.max_age_configuration_s;
}

function gateFor(item: CatalogueItem, catalogue: Catalogue): GateRef | null {
  if (item.poll_class === "telemetry") return catalogue.freshness_gates.telemetry;
  if (item.poll_class === "configuration") return catalogue.freshness_gates.configuration;
  return null;
}

/** Freshness of one entity: live only if its own timestamp is recent; never assumed. */
export function freshnessOf(
  e: HassEntityLike,
  maxAge: number,
  gate: HassEntityLike | undefined,
  nowMs: number,
): { freshness: Freshness; age: number | null; note: string } {
  const ts = timestampMs(e);
  if (ts === null) return { freshness: "unverified", age: null, note: "No valid timestamp: freshness cannot be verified." };
  const age = (nowMs - ts) / 1000;
  if (age < -CLOCK_SKEW_TOLERANCE_S) {
    return { freshness: "unverified", age: null, note: "The timestamp is in the future (clock skew): freshness cannot be verified." };
  }
  const a = Math.max(0, age);
  if (a <= maxAge) return { freshness: "live", age: a, note: `Reported ${formatAge(a)} ago.` };
  if (gate && gate.state === "on") {
    const gts = timestampMs(gate);
    const gAge = gts === null ? null : (nowMs - gts) / 1000;
    if (gAge !== null && gAge >= -CLOCK_SKEW_TOLERANCE_S && gAge <= maxAge) {
      return {
        freshness: "unchanged",
        age: a,
        note: `Unchanged for ${formatAge(a)}; the controller's poll for this block is online, but this entity has no recent report.`,
      };
    }
  }
  return { freshness: "stale", age: a, note: `Last reported ${formatAge(a)} ago, older than ${formatAge(maxAge)}: not live.` };
}

function deriveRaw(item: CatalogueItem, numeric: number | null, text: string | null): RawView {
  const d = item.decode;
  if (!d) return { kind: "unavailable", note: "No firmware decode is linked to this record." };
  if (d.kind === "linear" && numeric !== null && d.registers.length === 1) {
    const scale = d.scale ?? 1;
    const offset = d.offset ?? 0;
    const exact = numeric / scale;
    const raw = Math.round(exact) + offset;
    if (Math.abs(exact - Math.round(exact)) > 0.01) {
      return { kind: "unavailable", note: "The value is not an exact multiple of the register scale; no raw value is derived." };
    }
    const signed = d.signed === true;
    if ((signed && (raw < -32768 || raw > 32767)) || (!signed && (raw < 0 || raw > 65535))) {
      return { kind: "unavailable", note: "The value is outside the register's range; no raw value is derived." };
    }
    const how = scale === 1 && !offset ? "from the value" : `as value / ${formatNumber(scale)}${offset ? ` + ${offset}` : ""}`;
    return { kind: "derived", value: raw, hex: hex16(raw), note: `${how}${signed ? " (signed 16-bit)" : ""}` };
  }
  if (d.kind === "enum" && text !== null && item.options.enum) {
    const hit = item.options.enum.filter((o) => o.label === text);
    if (hit.length === 1 && hit[0]) {
      return { kind: "derived", value: hit[0].raw, hex: hex16(hit[0].raw), note: "from the firmware's enum decode" };
    }
    return { kind: "unavailable", note: "The text is not one of the decoded options; no raw value is derived." };
  }
  if (d.kind === "hhmm" && text !== null) {
    const m = /^(\d{1,2}):(\d{2})$/.exec(text.trim());
    if (m && m[1] !== undefined && m[2] !== undefined) {
      const raw = Number(m[1]) * 100 + Number(m[2]);
      return { kind: "derived", value: raw, hex: hex16(raw), note: "from HH:MM as the register's HHMM number" };
    }
    return { kind: "unavailable", note: "The time text is not HH:MM; no raw value is derived." };
  }
  if (d.kind === "bit" || d.kind === "bit_equals" || d.kind === "bit_text" || d.kind === "tou_charge" || d.kind === "tou_mode") {
    return { kind: "unavailable", note: "Only some bits of this register are decoded here; the full raw word is not exposed by this entity." };
  }
  return { kind: "unavailable", note: "The firmware decode is not a plain scaling, so no raw value is derived." };
}

function rawFromEntity(e: HassEntityLike | undefined): RawView | null {
  if (!e) return { kind: "unavailable", note: "The raw-word entity was not found." };
  const s = e.state;
  if (typeof s !== "string" || s === "unavailable" || s === "unknown" || s === "") {
    return { kind: "unavailable", note: "The raw-word entity is unavailable." };
  }
  const n = WORD_RE.test(s.trim()) ? Number(s.trim()) : NaN;
  if (!Number.isInteger(n) || n < 0 || n > 65535) {
    return { kind: "unavailable", note: "The raw-word entity reported an unexpected value." };
  }
  return { kind: "reported", value: n, hex: hex16(n), note: "by the controller's raw-word entity" };
}

const NUMERIC_KINDS = new Set(["linear"]);

/** Resolve one catalogue item against the Home Assistant states. Unknown values are never shown as zero. */
export function resolveValue(
  item: CatalogueItem,
  states: StatesLike,
  catalogue: Catalogue,
  config: CardConfig,
  nowMs: number,
): ValueView {
  const base = { numeric: null, ageSeconds: null, problem: null } as const;
  if (!item.entity) {
    return {
      ...base,
      state: "unmapped",
      entityId: null,
      display: "Not exposed by an ECCO entity",
      unit: null,
      raw: { kind: "unavailable", note: "No entity carries this record." },
      freshness: "not_applicable",
      freshnessNote: "No entity: nothing to read.",
    };
  }
  const eid = entityId(item.entity, config.entity_prefix);
  const e = states[eid];
  if (!e) {
    return {
      ...base,
      state: "missing",
      entityId: eid,
      display: "Entity not found in Home Assistant",
      unit: null,
      raw: { kind: "unavailable", note: "Entity not found." },
      freshness: "not_applicable",
      freshnessNote: "The entity does not exist in Home Assistant (check entity_prefix).",
    };
  }
  const attrs = e.attributes ?? {};
  const unitAttr = typeof attrs.unit_of_measurement === "string" ? attrs.unit_of_measurement : null;
  const unit = unitAttr ?? item.unit ?? null;
  const s = e.state;
  if (s === "unavailable" || s === "unknown" || s === "" || s === null || s === undefined) {
    const st = s === "unavailable" ? "unavailable" : "unknown";
    return {
      ...base,
      state: st,
      entityId: eid,
      display: st === "unavailable" ? "Unavailable" : "Unknown",
      unit,
      raw: { kind: "unavailable", note: "No value." },
      freshness: "not_applicable",
      freshnessNote: "The entity has no value: nothing is live.",
    };
  }
  const gateRef = gateFor(item, catalogue);
  const gate = gateRef ? states[entityId(gateRef, config.entity_prefix)] : undefined;
  const fresh = freshnessOf(e, maxAgeFor(item, config), gate, nowMs);
  if (typeof s !== "string") {
    return {
      ...base,
      state: "unexpected",
      entityId: eid,
      display: "Unexpected value",
      unit,
      raw: { kind: "unavailable", note: "Unexpected state type." },
      freshness: fresh.freshness,
      ageSeconds: fresh.age,
      freshnessNote: fresh.note,
      problem: `The entity state is a ${typeof s}, not text.`,
    };
  }
  const rawEntity = item.raw_entity ? states[entityId(item.raw_entity, config.entity_prefix)] : undefined;
  const reportedRaw = item.raw_entity ? rawFromEntity(rawEntity) : null;
  const numericExpected = item.entity.domain !== "binary_sensor" && (NUMERIC_KINDS.has(item.decode?.kind ?? "") || unitAttr !== null);
  if (item.entity.domain === "binary_sensor") {
    if (s !== "on" && s !== "off") {
      return {
        ...base,
        state: "unexpected",
        entityId: eid,
        display: "Unexpected value",
        unit: null,
        raw: reportedRaw ?? { kind: "unavailable", note: "Unexpected value." },
        freshness: fresh.freshness,
        ageSeconds: fresh.age,
        freshnessNote: fresh.note,
        problem: `A binary sensor reported '${s.slice(0, 40)}' instead of on / off.`,
      };
    }
    return {
      ...base,
      state: "ok",
      entityId: eid,
      display: s === "on" ? "On" : "Off",
      unit: null,
      raw: reportedRaw ?? deriveRaw(item, null, null),
      freshness: fresh.freshness,
      ageSeconds: fresh.age,
      freshnessNote: fresh.note,
    };
  }
  if (numericExpected) {
    const trimmed = s.trim();
    const n = DECIMAL_RE.test(trimmed) ? Number(trimmed) : NaN;
    if (!Number.isFinite(n)) {
      return {
        ...base,
        state: "unexpected",
        entityId: eid,
        display: "Unexpected value",
        unit,
        raw: reportedRaw ?? { kind: "unavailable", note: "The value is not a number." },
        freshness: fresh.freshness,
        ageSeconds: fresh.age,
        freshnessNote: fresh.note,
        problem: `Expected a number, got '${s.slice(0, 40)}'.`,
      };
    }
    return {
      ...base,
      state: "ok",
      entityId: eid,
      display: unit ? `${formatNumber(n)} ${unit}` : formatNumber(n),
      numeric: n,
      unit,
      raw: reportedRaw ?? deriveRaw(item, n, null),
      freshness: fresh.freshness,
      ageSeconds: fresh.age,
      freshnessNote: fresh.note,
    };
  }
  // Text decodes (enums, HH:MM times, charge source / mode, bit texts, flag words).
  let problem: string | null = null;
  if (item.decode?.kind === "enum" && item.options.enum) {
    const known = item.options.enum.some((o) => o.label === s);
    if (!known && !/^Unknown \(\d+\)$/.test(s)) problem = "The text is not one of the decoded options.";
  }
  return {
    ...base,
    state: "ok",
    entityId: eid,
    display: s,
    unit,
    raw: reportedRaw ?? deriveRaw(item, null, s),
    freshness: fresh.freshness,
    ageSeconds: fresh.age,
    freshnessNote: fresh.note,
    problem,
  };
}

// ---- Search and filters ----------------------------------------------------------------------------------------

export function emptyFilter(): FilterState {
  return { query: "", statuses: new Set(), evidence: new Set(), sections: new Set() };
}

function registerToken(tok: string): number | null {
  const m = /^(?:r|reg|register)?(\d{1,5})$/.exec(tok);
  return m && m[1] !== undefined ? Number(m[1]) : null;
}

export function searchText(item: CatalogueItem, sectionTitle: string): string {
  return [
    item.id,
    item.name,
    sectionTitle,
    item.description ?? "",
    item.explanation ?? "",
    item.entity?.object ?? "",
    item.entity?.firmware_id ?? "",
    item.entity?.name ?? "",
  ]
    .join(" \u0001 ")
    .toLowerCase();
}

/** Every whitespace-separated token must match: a number (or r245 / reg245) matches a register exactly, text matches
 *  the name, id, description, explanation, section or entity. */
export function matchesQuery(item: CatalogueItem, sectionTitle: string, query: string): boolean {
  const tokens = query.toLowerCase().split(/\s+/).filter((t) => t.length > 0);
  if (!tokens.length) return true;
  const text = searchText(item, sectionTitle);
  return tokens.every((tok) => {
    const reg = registerToken(tok);
    if (reg !== null) return item.registers.some((r) => r.address === reg);
    return text.includes(tok);
  });
}

export function filterItems(catalogue: Catalogue, filter: FilterState): CatalogueItem[] {
  const titles = new Map(catalogue.sections.map((s) => [s.id, s.title]));
  return catalogue.items.filter(
    (it) =>
      (filter.statuses.size === 0 || filter.statuses.has(it.status)) &&
      (filter.evidence.size === 0 || filter.evidence.has(it.evidence)) &&
      (filter.sections.size === 0 || filter.sections.has(it.section)) &&
      matchesQuery(it, titles.get(it.section) ?? "", filter.query),
  );
}

export function groupBySection(catalogue: Catalogue, items: CatalogueItem[]): { id: string; title: string; summary: string; items: CatalogueItem[] }[] {
  return catalogue.sections.map((s) => ({ ...s, items: items.filter((i) => i.section === s.id) }));
}

// ---- Global Power ------------------------------------------------------------------------------------------------

export interface FutureControlView {
  key: FutureControl;
  label: string;
  description: string;
  enabled: false;
  reason: string;
}

export interface GlobalPowerView {
  title: string;
  register: number;
  item: CatalogueItem;
  value: ValueView;
  unit: "W";
  sourceEntityId: string | null;
  evidence: string;
  ownerConfirmation: { date: string; statement: string };
  status: Status;
  readOnlyText: string;
  hardwareMaximumText: string;
  regulatoryText: string;
  permittedRangeText: string;
  previousValueText: string;
  historyText: string;
  verificationText: string;
  blockers: string[];
  limitations: string[];
  controls: FutureControlView[];
}

const CONTROL_LABEL: Record<FutureControl, string> = {
  unlock: "Unlock",
  staged_value: "Staged value",
  permitted_range: "Permitted technical range",
  apply: "Apply",
  verification: "Verification status",
  previous_value: "Previous value",
  history: "History",
};

export function globalPowerItem(catalogue: Catalogue): CatalogueItem {
  const gp = catalogue.global_power;
  const hits = catalogue.items.filter((i) => i.id === gp.record);
  const item = hits[0];
  if (hits.length !== 1 || !item) throw new Error(`Global Power record ${gp.record} must appear exactly once in the catalogue`);
  if (item.registers.length !== 1 || item.registers[0]?.address !== gp.register) {
    throw new Error(`Global Power record ${gp.record} is not register ${gp.register}`);
  }
  return item;
}

export function buildGlobalPowerView(catalogue: Catalogue, states: StatesLike, config: CardConfig, nowMs: number): GlobalPowerView {
  const gp = catalogue.global_power;
  const item = globalPowerItem(catalogue);
  const value = resolveValue(item, states, catalogue, config, nowMs);
  const hwMax = gp.hardware_maximum_w;
  const hardwareMaximumText =
    hwMax !== null && gp.hardware_maximum_evidence ? `${hwMax} W (verified: ${gp.hardware_maximum_evidence})` : HARDWARE_MAXIMUM_NOT_VERIFIED;
  const regulatoryText = gp.regulatory_allowance_w !== null ? `${gp.regulatory_allowance_w} W` : REGULATORY_ALLOWANCE_NOT_RECORDED;
  const permittedRangeText =
    hwMax !== null && gp.hardware_maximum_evidence
      ? `Up to ${hwMax} W technical maximum${gp.regulatory_allowance_w !== null ? `, and at most ${gp.regulatory_allowance_w} W by the regulatory allowance` : " (regulatory allowance not recorded)"}`
      : `Unavailable: ${HARDWARE_MAXIMUM_NOT_VERIFIED.toLowerCase()}`;
  const reason = "Disabled: Global Power writing is not implemented in this release.";
  const controls: FutureControlView[] = (Object.keys(CONTROL_LABEL) as FutureControl[]).map((key) => ({
    key,
    label: CONTROL_LABEL[key],
    description: gp.future_controls[key],
    enabled: false,
    reason,
  }));
  return {
    title: gp.title,
    register: gp.register,
    item,
    value,
    unit: "W",
    sourceEntityId: value.entityId,
    evidence: `${EVIDENCE_LABEL[item.evidence]} (registry: ${item.live_proof_status}); owner-confirmed ${gp.owner_confirmation.date}`,
    ownerConfirmation: gp.owner_confirmation,
    status: item.status,
    readOnlyText: "Read only. This card cannot write to Home Assistant or the inverter.",
    hardwareMaximumText,
    regulatoryText,
    permittedRangeText,
    previousValueText: "No ECCO write has been made to this setting (ECCO has no write path for it).",
    historyText: "Change history appears after integration (Home Assistant history of the source entity).",
    verificationText: "No write path, so there is nothing to verify.",
    blockers: gp.write_blockers,
    limitations: gp.limitations,
    controls,
  };
}
