import type { FormatConfig } from "../config";

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

/** Parses a Home Assistant entity state to a finite number, or null if unavailable/unknown/non-numeric. */
export function toNumber(state: string | undefined | null): number | null {
  if (state === undefined || state === null) return null;
  if (state === "unknown" || state === "unavailable" || state === "") return null;
  const n = Number(state);
  return Number.isFinite(n) ? n : null;
}
