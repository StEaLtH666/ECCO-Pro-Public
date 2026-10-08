// Display-truthfulness helpers (FE-0). Pure functions only - no Lit, no DOM -
// so the node:test suite can exercise exactly the decisions the card's render
// path makes. The one rule every helper here follows: an unknown reading is
// shown as unknown ("--", or no fill), never as a plausible-looking real value
// such as 0 W, "Idle", 0% or "Disconnected". Deliberately free of runtime
// imports so the tests can load it directly under Node's type stripping.

export type BatteryStatusColour = "battery-idle" | "battery-charge" | "battery-discharge";

/**
 * The battery node's status word and colour. `batteryW` is already in the
 * card's internal convention (positive = discharging). An unknown reading
 * (null) is "--", not "Idle" - "Idle" is a claim that the battery is
 * confirmed quiet, which an unavailable sensor cannot support. Colour stays
 * the subdued idle colour for unknown, so no new styling is introduced.
 */
export function batteryStatus(batteryW: number | null, idleThresholdW: number): { label: string; colour: BatteryStatusColour } {
  if (batteryW === null) return { label: "--", colour: "battery-idle" };
  if (batteryW >= idleThresholdW) return { label: "Discharging", colour: "battery-discharge" };
  if (batteryW <= -idleThresholdW) return { label: "Charging", colour: "battery-charge" };
  return { label: "Idle", colour: "battery-idle" };
}

/**
 * Battery SOC presentation. `fillPct` drives both the ambient background fill
 * and the precise SOC bar; it is null whenever the SOC is unknown, so an
 * unavailable sensor never draws as a genuine empty (0%) battery. `text` is
 * "" when no SOC entity is configured at all (nothing to say), and "--" when
 * one is configured but currently unknown.
 */
export function socDisplay(soc: number | null, configured: boolean): { text: string; fillPct: number | null } {
  if (soc === null) return { text: configured ? "--" : "", fillPct: null };
  return { text: `${Math.round(soc)}%`, fillPct: Math.max(0, Math.min(100, soc)) };
}

export type GridConnection = "connected" | "disconnected" | "unknown";

/**
 * Classifies an `inverter_details.grid_connected` state string. Only an
 * explicit off/false is a disconnection; only an explicit on/true is a
 * connection. Anything else - "unavailable", "unknown", "", an unexpected
 * string, or a missing entity - is unknown and must never be presented as a
 * grid outage.
 */
export function classifyGridConnected(raw: string | undefined): GridConnection {
  if (raw === "on" || raw === "true") return "connected";
  if (raw === "off" || raw === "false") return "disconnected";
  return "unknown";
}

/** Quick-metrics tile and details-row presentation for a grid_connected classification. */
export function gridConnectedDisplay(connection: GridConnection): {
  value: string;
  detailValue: string;
  icon: string;
  variant?: "ok" | "fault";
} {
  if (connection === "connected") return { value: "Connected", detailValue: "Yes", icon: "mdi:check-circle-outline", variant: "ok" };
  if (connection === "disconnected") return { value: "Disconnected", detailValue: "No", icon: "mdi:alert-circle-outline", variant: "fault" };
  return { value: "Unknown", detailValue: "Unknown", icon: "mdi:help-circle-outline" };
}

// Duration units a time-to-reserve entity may report in, converted to
// minutes. A unit conversion only - the card never estimates a duration.
const MINUTES_PER_UNIT = new Map<unknown, number>([
  ["s", 1 / 60],
  ["min", 1],
  ["h", 60],
  ["d", 1440],
]);

/**
 * Optional `nodes.battery.time_to_reserve` hook. The card displays the
 * configured entity's own value and never calculates a reserve level or an
 * ETA itself. `value` is the entity state already parsed by `toNumber()`.
 * Returns undefined when no entity is configured (the hook is inert). When
 * configured, returns the duration in minutes, or null for an unknown/
 * unavailable/non-numeric state, a negative value, or a unit the card cannot
 * interpret; a missing unit is read as minutes. Format with
 * `formatDurationMinutes()`.
 */
export function resolveTimeToReserveMinutes(entityId: string | undefined, value: number | null, unit: unknown): number | null | undefined {
  if (!entityId) return undefined;
  const factor = unit === undefined || unit === null || unit === "" ? 1 : MINUTES_PER_UNIT.get(unit);
  return factor !== undefined && value !== null && value >= 0 ? value * factor : null;
}
