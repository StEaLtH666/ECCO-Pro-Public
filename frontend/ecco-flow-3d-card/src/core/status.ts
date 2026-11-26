// ECCO status derivations. Pure functions over entity states: the card
// shows what the existing entities say and never invents a value, a
// countdown or a status. Unknown stays unknown.

import { formatApproxMinutes, formatClock, formatClockMinutes, formatDurationMinutes, toNumber } from "./format.ts";

// ---------------------------------------------------------------------------
// Minimal Home Assistant shapes

export interface HassEntity {
  state: string;
  attributes?: Record<string, unknown>;
  last_updated?: string;
  last_changed?: string;
}

export type States = Record<string, HassEntity | undefined>;

export function stateOf(states: States, id: string | undefined): string | undefined {
  return id ? states[id]?.state : undefined;
}

export function numberOf(states: States, id: string | undefined): number | null {
  return id ? toNumber(states[id]?.state) : null;
}

export function attrsOf(states: States, id: string | undefined): Record<string, unknown> | undefined {
  return id ? states[id]?.attributes : undefined;
}

export type OnOff = "on" | "off" | "unknown";

/** Only an explicit on/true is on and only an explicit off/false is off. */
export function classifyOnOff(raw: string | undefined): OnOff {
  if (raw === "on" || raw === "true" || raw === "True") return "on";
  if (raw === "off" || raw === "false" || raw === "False") return "off";
  return "unknown";
}

// ---------------------------------------------------------------------------
// FE-1 battery runtime (mirrors ecco-energy-flow-card/src/utils/display.ts)

const MINUTES_PER_UNIT = new Map<unknown, number>([
  ["s", 1 / 60],
  ["min", 1],
  ["h", 60],
  ["d", 1440],
]);

export function resolveTimeToReserveMinutes(entityId: string | undefined, value: number | null, unit: unknown): number | null | undefined {
  if (!entityId) return undefined;
  const factor = unit === undefined || unit === null || unit === "" ? 1 : MINUTES_PER_UNIT.get(unit);
  return factor !== undefined && value !== null && value >= 0 ? value * factor : null;
}

export const RESERVE_RUNTIME_STATUSES = ["discharging", "at_reserve", "charging", "holding", "insufficient_data", "stale"] as const;
export type ReserveRuntimeStatus = (typeof RESERVE_RUNTIME_STATUSES)[number];

export interface ReserveRuntime {
  status: ReserveRuntimeStatus;
  minutes: number | null;
  low: number | null;
  high: number | null;
  beyondHorizon: boolean;
  solarAssisted: boolean;
  summary: string | null;
}

function nonNegative(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
}

export function resolveReserveRuntime(
  entityId: string | undefined,
  minutes: number | null | undefined,
  attributes: Record<string, unknown> | undefined
): ReserveRuntime | undefined {
  if (!entityId || minutes === undefined) return undefined;
  const reported = attributes?.status;
  const known = (RESERVE_RUNTIME_STATUSES as readonly unknown[]).includes(reported);
  let status: ReserveRuntimeStatus = known ? (reported as ReserveRuntimeStatus) : minutes !== null ? "discharging" : "insufficient_data";
  if (status === "discharging" && minutes === null) status = "insufficient_data";
  const timed = status === "discharging" || status === "at_reserve";
  const summary = typeof attributes?.summary === "string" && attributes.summary.trim() !== "" ? attributes.summary : null;
  return {
    status,
    minutes: timed ? minutes : null,
    low: status === "discharging" ? nonNegative(attributes?.minutes_low) : null,
    high: status === "discharging" ? nonNegative(attributes?.minutes_high) : null,
    beyondHorizon: status === "discharging" && attributes?.beyond_horizon === true,
    solarAssisted: status === "discharging" && attributes?.solar_assisted === true,
    summary,
  };
}

const BEYOND_HORIZON_TEXT = "Over 3 days";

/** One-line runtime text for the status tile. Wording only. */
export function reserveRuntimeLine(rt: ReserveRuntime): string {
  switch (rt.status) {
    case "discharging":
      return rt.beyondHorizon ? BEYOND_HORIZON_TEXT : `${formatApproxMinutes(rt.minutes)} to reserve`;
    case "at_reserve":
      return "At reserve";
    case "charging":
      return "Charging";
    case "holding":
      return "Holding";
    case "stale":
      return "Telemetry stale";
    default:
      return "Insufficient data";
  }
}

/** The tile's headline value and its sub-line. */
export function reserveRuntimeTile(rt: ReserveRuntime | undefined): { value: string; sub: string; tone: Tone } {
  if (!rt) return { value: "--", sub: "No runtime entity", tone: "muted" };
  switch (rt.status) {
    case "discharging":
      return {
        value: rt.beyondHorizon ? ">3 d" : formatApproxMinutes(rt.minutes),
        sub: rt.beyondHorizon
          ? "to reserve (estimate)"
          : rt.low !== null && rt.high !== null
            ? `to reserve · likely ${formatDurationMinutes(rt.low)} to ${formatDurationMinutes(rt.high)}`
            : "to reserve (estimate)",
        tone: "ok",
      };
    case "at_reserve":
      return { value: "At reserve", sub: rt.summary ?? "At or below the reserve", tone: "warn" };
    case "charging":
      return { value: "Charging", sub: "No discharge estimate while charging", tone: "ok" };
    case "holding":
      return { value: "Holding", sub: "Neither charging nor discharging", tone: "muted" };
    case "stale":
      return { value: "Stale", sub: "Estimate paused: telemetry stale", tone: "warn" };
    default:
      return { value: "--", sub: rt.summary ?? "Insufficient data", tone: "muted" };
  }
}

export function reserveRuntimeTooltip(rt: ReserveRuntime): string {
  if (rt.status !== "discharging") return `Time to reserve: ${rt.summary ?? reserveRuntimeLine(rt)}`;
  const parts = [
    rt.beyondHorizon
      ? `${BEYOND_HORIZON_TEXT} until the batteries reach the configured reserve at recent usage`
      : `Approximately ${formatDurationMinutes(rt.minutes)} until the batteries reach the configured reserve at recent usage`,
  ];
  if (!rt.beyondHorizon && rt.low !== null && rt.high !== null) parts.push(`likely ${formatDurationMinutes(rt.low)} to ${formatDurationMinutes(rt.high)}`);
  if (rt.solarAssisted) parts.push("solar-assisted, so it shortens as solar output falls");
  parts.push("an estimate, not a guarantee");
  return `Time to reserve: ${parts.join("; ")}`;
}

/**
 * Battery time to charge target: shown ONLY from a configured entity.
 * Without one (ECCO today) the result says so explicitly.
 */
export function resolveTimeToTarget(entityId: string | undefined, states: States): { value: string; sub: string; tone: Tone } {
  if (!entityId) return { value: "Not available", sub: "No ECCO entity provides a time to charge target", tone: "muted" };
  const minutes = resolveTimeToReserveMinutes(entityId, numberOf(states, entityId), attrsOf(states, entityId)?.unit_of_measurement);
  if (minutes === null || minutes === undefined) return { value: "--", sub: "Entity has no value", tone: "muted" };
  return { value: formatApproxMinutes(minutes), sub: "to charge target (entity value)", tone: "ok" };
}

// ---------------------------------------------------------------------------
// Tone

export type Tone = "ok" | "warn" | "alert" | "muted" | "accent";

// ---------------------------------------------------------------------------
// Free Power / Dump to Grid sessions

const LOCAL_TIMESTAMP_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;

/** Parses the dongle's "YYYY-MM-DD HH:MM:SS" (local time) text. Anything else is null. */
export function parseLocalTimestamp(text: string | undefined): Date | null {
  if (!text) return null;
  const m = LOCAL_TIMESTAMP_RE.exec(text.trim());
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6]));
  return Number.isNaN(d.getTime()) ? null : d;
}

export type SessionPhase = "active" | "starting" | "armed" | "failed" | "completed" | "standby" | "unknown";

export interface SessionView {
  phase: SessionPhase;
  /** Tile headline. */
  value: string;
  /** Tile sub-line. Honest about an unavailable end time. */
  sub: string;
  tone: Tone;
  /** Remaining minutes derived from the entity's own end time; null when it has none. */
  remainingMin: number | null;
  endsAt: Date | null;
  endTimeUnavailable: boolean;
}

export interface SessionInputs {
  active: OnOff;
  endsAtText: string | undefined;
  scheduleStatus: string | undefined;
  statusText: string | undefined;
  /** Dump only. */
  exportPowerW?: number | null;
  stopSoc?: number | null;
  /** Schedule attributes (scheduled_start, duration_minutes, requested_power_w). */
  scheduleAttrs?: Record<string, unknown>;
  anyConfigured: boolean;
}

function remainingText(remainingMin: number | null, endsAt: Date | null, unavailable: boolean): string {
  if (unavailable) return "Active · end time unavailable";
  if (endsAt === null) return "Active";
  if (remainingMin === null || remainingMin <= 0) return `Ends ${formatClock(endsAt)} · ending`;
  return `Ends ${formatClock(endsAt)} · ${formatDurationMinutes(remainingMin)} left`;
}

/** Resolves the Free Power / Dump to Grid tile from the existing entities. `nowMs` is injected for testability. */
export function resolveSession(input: SessionInputs, nowMs: number, kind: "free_power" | "dump"): SessionView {
  const none: SessionView = { phase: "unknown", value: "--", sub: "Not configured", tone: "muted", remainingMin: null, endsAt: null, endTimeUnavailable: false };
  if (!input.anyConfigured) return none;

  const schedule = (input.scheduleStatus ?? "").trim().toUpperCase();
  const endsAt = parseLocalTimestamp(input.endsAtText);
  const endTimeUnavailable = (input.endsAtText ?? "").toLowerCase().includes("unavailable");
  const remainingMin = endsAt ? (endsAt.getTime() - nowMs) / 60000 : null;

  if (input.active === "on") {
    let sub = remainingText(remainingMin, endsAt, endTimeUnavailable);
    if (kind === "dump" && input.exportPowerW !== null && input.exportPowerW !== undefined) {
      sub = `${sub} · ${Math.round(input.exportPowerW)} W export` + (input.stopSoc !== null && input.stopSoc !== undefined ? ` · stop ${Math.round(input.stopSoc)}%` : "");
    }
    return { phase: "active", value: "Active", sub, tone: "accent", remainingMin, endsAt, endTimeUnavailable };
  }
  if (schedule === "STARTING") return { phase: "starting", value: "Starting", sub: "Scheduled start in progress", tone: "accent", remainingMin: null, endsAt: null, endTimeUnavailable: false };
  if (schedule === "ARMED") {
    const start = typeof input.scheduleAttrs?.scheduled_start === "string" ? input.scheduleAttrs.scheduled_start : null;
    const dur = toNumber(String(input.scheduleAttrs?.duration_minutes ?? ""));
    const startText = start ? start.slice(0, 5) : "--:--";
    return {
      phase: "armed",
      value: "Armed",
      sub: `Scheduled ${startText}` + (dur !== null ? ` · ${formatDurationMinutes(dur)}` : ""),
      tone: "ok",
      remainingMin: null,
      endsAt: null,
      endTimeUnavailable: false,
    };
  }
  if (schedule === "FAILED") return { phase: "failed", value: "Failed", sub: "Last scheduled run failed · see Energy Actions", tone: "alert", remainingMin: null, endsAt: null, endTimeUnavailable: false };
  if (input.active === "off") {
    const completed = schedule === "COMPLETED";
    return {
      phase: completed ? "completed" : "standby",
      value: completed ? "Completed" : kind === "dump" ? "Ready" : "Standby",
      sub: completed ? "Last scheduled run completed" : "No session running",
      tone: "muted",
      remainingMin: null,
      endsAt: null,
      endTimeUnavailable: false,
    };
  }
  return { phase: "unknown", value: "--", sub: "Lease state unavailable", tone: "muted", remainingMin: null, endsAt: null, endTimeUnavailable: false };
}

// ---------------------------------------------------------------------------
// TOU: the current slot, derived from the six existing start-minute sensors

export interface TouView {
  /** 1..6, or null when unknown. */
  slot: number | null;
  startMin: number | null;
  endMin: number | null;
  /** Minutes until the next slot boundary. */
  minutesToChange: number | null;
  value: string;
  sub: string;
  tone: Tone;
}

/**
 * Finds the slot containing `nowMin` (minutes after local midnight) in a
 * six-slot cyclic table of start minutes. Slot i runs from start[i] to
 * start[i+1] (slot 6 wraps to slot 1). A table with any unknown start, or
 * one the schedule-valid sensor marks invalid, resolves to unknown.
 */
export function resolveTouSlot(startMin: Array<number | null>, nowMin: number, valid: OnOff): TouView {
  const unknown: TouView = { slot: null, startMin: null, endMin: null, minutesToChange: null, value: "--", sub: "Schedule unavailable", tone: "muted" };
  if (startMin.length !== 6 || startMin.some((m) => m === null)) return unknown;
  if (valid === "off") return { ...unknown, sub: "Schedule invalid", tone: "warn" };
  const starts = startMin as number[];
  const now = ((Math.floor(nowMin) % 1440) + 1440) % 1440;
  for (let i = 0; i < 6; i++) {
    const s = ((starts[i]! % 1440) + 1440) % 1440;
    const e = ((starts[(i + 1) % 6]! % 1440) + 1440) % 1440;
    const inside = s < e ? now >= s && now < e : now >= s || now < e; // wrap across midnight
    if (inside) {
      const toChange = (e - now + 1440) % 1440;
      return {
        slot: i + 1,
        startMin: s,
        endMin: e,
        minutesToChange: toChange,
        value: `Slot ${i + 1}`,
        sub: `${formatClockMinutes(s)}–${formatClockMinutes(e)} · ${formatDurationMinutes(toChange)} left`,
        tone: "accent",
      };
    }
  }
  return { ...unknown, sub: "No slot matches the current time", tone: "warn" };
}

export function minutesOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

// ---------------------------------------------------------------------------
// Health roll-up

export type HealthGrade = "HEALTHY" | "DEGRADED" | "FAILED" | "UNKNOWN";

export interface HealthView {
  grade: HealthGrade;
  value: string;
  sub: string;
  tone: Tone;
  failed: string[];
  degraded: string[];
  unknown: string[];
  attention: string[];
}

function shortName(entityId: string): string {
  return entityId
    .replace(/^.*?\./, "")
    .replace(/^ecco_health_/, "")
    .replace(/^ecco_/, "")
    .replace(/_/g, " ");
}

/**
 * Worst-of roll-up over the configured subsystem sensors. Nothing is hidden:
 * a FAILED subsystem is "Attention", a DEGRADED one "Degraded", any unknown
 * one is named, and attention binary_sensors that are on are listed.
 */
export function resolveHealth(sensorIds: string[], attentionIds: string[], states: States): HealthView {
  const failed: string[] = [];
  const degraded: string[] = [];
  const unknown: string[] = [];
  for (const id of sensorIds) {
    const s = (stateOf(states, id) ?? "").trim().toUpperCase();
    if (s === "FAILED") failed.push(shortName(id));
    else if (s === "DEGRADED") degraded.push(shortName(id));
    else if (s !== "HEALTHY") unknown.push(shortName(id));
  }
  const attention = attentionIds.filter((id) => classifyOnOff(stateOf(states, id)) === "on").map(shortName);
  const total = sensorIds.length + attentionIds.length;
  if (total === 0) return { grade: "UNKNOWN", value: "--", sub: "No health entities configured", tone: "muted", failed, degraded, unknown, attention };
  const list = (xs: string[]) => xs.slice(0, 2).join(", ") + (xs.length > 2 ? ` +${xs.length - 2}` : "");
  if (failed.length > 0 || attention.length > 0) {
    const names = [...failed, ...attention];
    return { grade: "FAILED", value: "Attention", sub: list(names), tone: "alert", failed, degraded, unknown, attention };
  }
  if (degraded.length > 0) return { grade: "DEGRADED", value: "Degraded", sub: list(degraded), tone: "warn", failed, degraded, unknown, attention };
  if (unknown.length === sensorIds.length && sensorIds.length > 0) return { grade: "UNKNOWN", value: "Unknown", sub: "Health entities unavailable", tone: "muted", failed, degraded, unknown, attention };
  if (unknown.length > 0) return { grade: "HEALTHY", value: "Nominal", sub: `${unknown.length} unknown: ${list(unknown)}`, tone: "ok", failed, degraded, unknown, attention };
  return { grade: "HEALTHY", value: "Nominal", sub: `${sensorIds.length} subsystems healthy`, tone: "ok", failed, degraded, unknown, attention };
}

// ---------------------------------------------------------------------------
// Freshness

export interface Freshness {
  /** Seconds since the newest configured power reading updated; null when none has a timestamp. */
  ageS: number | null;
  stale: boolean;
  /** Why it is stale, for the chip. */
  reason: "telemetry_offline" | "age" | null;
  telemetry: OnOff;
}

export function resolveFreshness(entityIds: Array<string | undefined>, states: States, telemetry: OnOff, nowMs: number, staleAfterS: number): Freshness {
  let newest: number | null = null;
  for (const id of entityIds) {
    if (!id) continue;
    const ts = states[id]?.last_updated;
    if (!ts) continue;
    const t = Date.parse(ts);
    if (!Number.isFinite(t)) continue;
    if (newest === null || t > newest) newest = t;
  }
  const ageS = newest === null ? null : Math.max(0, (nowMs - newest) / 1000);
  if (telemetry === "off") return { ageS, stale: true, reason: "telemetry_offline", telemetry };
  if (staleAfterS > 0 && ageS !== null && ageS > staleAfterS) return { ageS, stale: true, reason: "age", telemetry };
  return { ageS, stale: false, reason: null, telemetry };
}

// ---------------------------------------------------------------------------
// Day / night ambience (cosmetic only, never telemetry)

export type Daylight = "day" | "dusk" | "night";

/**
 * From sun.sun when configured (state above/below_horizon, `elevation`
 * attribute); otherwise from the local clock. Ambience only: it changes the
 * scene's sky and lights, never a value.
 */
export function resolveDaylight(sun: HassEntity | undefined, now: Date): Daylight {
  if (sun) {
    const elev = typeof sun.attributes?.elevation === "number" ? sun.attributes.elevation : null;
    if (sun.state === "above_horizon") return elev !== null && elev < 8 ? "dusk" : "day";
    if (sun.state === "below_horizon") return elev !== null && elev > -6 ? "dusk" : "night";
  }
  const h = now.getHours();
  if (h >= 8 && h < 18) return "day";
  if (h >= 6 && h < 8) return "dusk";
  if (h >= 18 && h < 20) return "dusk";
  return "night";
}
