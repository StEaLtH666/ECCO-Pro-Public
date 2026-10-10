import type { FormatConfig } from "../config";
import type { ReserveRuntime } from "./display";

/** Formats a power value in watts as a human string, auto-switching W/kW by magnitude unless pinned. */
export function formatPower(watts: number | null | undefined, format: FormatConfig | undefined): string {
  if (watts === null || watts === undefined || Number.isNaN(watts)) {
    return "--";
  }
  const unitMode = format?.power_unit ?? "auto";
  const abs = Math.abs(watts);
  const useKw = unitMode === "kw" || (unitMode === "auto" && abs >= 1000);

  if (useKw) {
    const precision = format?.precision ?? 2;
    return `${(watts / 1000).toFixed(precision)} kW`;
  }
  const precision = format?.precision ?? 0;
  return `${watts.toFixed(precision)} W`;
}

/** Formats a daily energy total in kWh. */
export function formatEnergy(kwh: number | null | undefined, format: FormatConfig | undefined): string {
  if (kwh === null || kwh === undefined || Number.isNaN(kwh)) {
    return "--";
  }
  const precision = format?.energy_precision ?? 1;
  return `${kwh.toFixed(precision)} kWh`;
}

/** Formats a 0-100 percentage with no decimals. */
export function formatPercent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) {
    return "--";
  }
  const clamped = Math.max(0, Math.min(1, fraction));
  return `${Math.round(clamped * 100)}%`;
}

/**
 * Formats a duration given in minutes: "45 min", "2 h", "2 h 5 min", "1 d 3 h"
 * (whole days drop the minutes). A positive value under half a minute is
 * "<1 min", never a misleading "0 min". Unknown, non-finite or negative
 * input is "--". Formatting only - it never estimates a duration.
 */
export function formatDurationMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes < 0) {
    return "--";
  }
  const total = Math.round(minutes);
  if (total === 0) return minutes > 0 ? "<1 min" : "0 min";
  if (total < 60) return `${total} min`;
  if (total < 1440) {
    const h = Math.floor(total / 60);
    const m = total % 60;
    return m === 0 ? `${h} h` : `${h} h ${m} min`;
  }
  const d = Math.floor(total / 1440);
  const h = Math.floor((total % 1440) / 60);
  return h === 0 ? `${d} d` : `${d} d ${h} h`;
}

/**
 * FE-1: a compact, explicitly approximate duration for the battery node:
 * "≈45m", "≈5h", "≈5h 20m", "≈1d 3h". Formatting only: the value is the
 * entity's own (Home Assistant already rounds it); unknown -> "--".
 */
export function formatApproxMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes < 0) {
    return "--";
  }
  const total = Math.round(minutes);
  if (total === 0) return minutes > 0 ? "<1m" : "0m";
  if (total < 60) return `≈${total}m`;
  if (total < 1440) {
    const h = Math.floor(total / 60);
    const m = total % 60;
    return m === 0 ? `≈${h}h` : `≈${h}h ${m}m`;
  }
  const d = Math.floor(total / 1440);
  const h = Math.floor((total % 1440) / 60);
  return h === 0 ? `≈${d}d` : `≈${d}d ${h}h`;
}

/** The capped wording for a value the entity marks as beyond its horizon. */
const BEYOND_HORIZON_TEXT = "Over 3 days";

/**
 * FE-1: the battery node's one-line runtime text for a resolved entity
 * (resolveReserveRuntime). Wording only - it never estimates anything.
 */
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

/**
 * FE-1: the battery node's tooltip for a resolved entity. While discharging it
 * says "Approximately", gives the entity's likely range when reported, flags a
 * solar-assisted discharge and states that it is an estimate. Otherwise it
 * shows the entity's own summary (or the one-line text).
 */
export function reserveRuntimeTooltip(rt: ReserveRuntime): string {
  if (rt.status !== "discharging") {
    return `Time to reserve: ${rt.summary ?? reserveRuntimeLine(rt)}`;
  }
  const parts = [
    rt.beyondHorizon
      ? `${BEYOND_HORIZON_TEXT} until the batteries reach the configured reserve at recent usage`
      : `Approximately ${formatDurationMinutes(rt.minutes)} until the batteries reach the configured reserve at recent usage`,
  ];
  if (!rt.beyondHorizon && rt.low !== null && rt.high !== null) {
    parts.push(`likely ${formatDurationMinutes(rt.low)} to ${formatDurationMinutes(rt.high)}`);
  }
  if (rt.solarAssisted) parts.push("solar-assisted, so it shortens as solar output falls");
  parts.push("an estimate, not a guarantee");
  return `Time to reserve: ${parts.join("; ")}`;
}

/** Parses a Home Assistant entity state to a finite number, or null if unavailable/unknown/non-numeric. */
export function toNumber(state: string | undefined | null): number | null {
  if (state === undefined || state === null) return null;
  if (state === "unknown" || state === "unavailable" || state === "") return null;
  const n = Number(state);
  return Number.isFinite(n) ? n : null;
}
