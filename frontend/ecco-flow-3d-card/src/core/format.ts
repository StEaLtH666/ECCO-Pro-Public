// Formatting helpers. Formatting only: nothing here estimates a value.

import type { FormatConfig } from "../config.ts";

/** Parses a Home Assistant state to a finite number, or null for unknown/unavailable/non-numeric. */
export function toNumber(state: string | undefined | null): number | null {
  if (state === undefined || state === null) return null;
  if (state === "unknown" || state === "unavailable" || state === "" || state === "none" || state === "None") return null;
  const n = Number(state);
  return Number.isFinite(n) ? n : null;
}

/** Formats watts as "640 W" / "6.40 kW"; unknown is "--". */
export function formatPower(watts: number | null | undefined, format?: FormatConfig): string {
  if (watts === null || watts === undefined || Number.isNaN(watts)) return "--";
  const unitMode = format?.power_unit ?? "auto";
  const abs = Math.abs(watts);
  const useKw = unitMode === "kw" || (unitMode === "auto" && abs >= 1000);
  if (useKw) return `${(watts / 1000).toFixed(format?.precision ?? 2)} kW`;
  return `${watts.toFixed(format?.precision ?? 0)} W`;
}

/** Compact power for the scene pills: "640 W", "6.4 kW" (one decimal), "--". */
export function formatPowerCompact(watts: number | null | undefined): string {
  if (watts === null || watts === undefined || Number.isNaN(watts)) return "--";
  const abs = Math.abs(watts);
  if (abs >= 10000) return `${(watts / 1000).toFixed(0)} kW`;
  if (abs >= 1000) return `${(watts / 1000).toFixed(1)} kW`;
  return `${Math.round(watts)} W`;
}

export function formatEnergy(kwh: number | null | undefined, format?: FormatConfig): string {
  if (kwh === null || kwh === undefined || Number.isNaN(kwh)) return "--";
  return `${kwh.toFixed(format?.energy_precision ?? 1)} kWh`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "--";
  return `${Math.round(value)}%`;
}

/** "45 min", "2 h 5 min", "1 d 3 h"; "<1 min" for a positive value under half a minute; "--" for unknown. */
export function formatDurationMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes < 0) return "--";
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

/** Compact, explicitly approximate duration: "≈45m", "≈5h 20m", "≈1d 3h". */
export function formatApproxMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes < 0) return "--";
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

/** Grid voltage, "243.8 V"; unknown is "--". */
export function formatVoltage(volts: number | null | undefined): string {
  if (volts === null || volts === undefined || !Number.isFinite(volts)) return "--";
  return `${volts.toFixed(1)} V`;
}

/** Grid frequency, "49.98 Hz"; unknown is "--". */
export function formatFrequency(hz: number | null | undefined): string {
  if (hz === null || hz === undefined || !Number.isFinite(hz)) return "--";
  return `${hz.toFixed(2)} Hz`;
}

/** Temperature, "41.2 °C"; unknown is "--". */
export function formatTemperature(celsius: number | null | undefined): string {
  if (celsius === null || celsius === undefined || !Number.isFinite(celsius)) return "--";
  return `${celsius.toFixed(1)} °C`;
}

/**
 * Solar Share: the production Overview's definition (ecco-energy-flow-card
 * `_solarShareText`, enabled there by `features.solar_contribution`), today's
 * solar energy over today's load energy, clamped to 0..1. Null when the load
 * is unknown or not positive. Unlike that card, an unknown solar reading
 * gives null here rather than 0 % (this card never shows a plausible value
 * for an unknown reading).
 */
export function solarShareFraction(solarKwh: number | null, loadKwh: number | null): number | null {
  if (solarKwh === null || loadKwh === null || !(loadKwh > 0)) return null;
  return Math.max(0, Math.min(1, solarKwh / loadKwh));
}

/** "HH:MM" from minutes after midnight (wrapping). */
export function formatClockMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "--:--";
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export function formatClock(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** "just now", "12 s ago", "3 min ago", "2 h ago"; null input is "--". */
export function formatAge(ageS: number | null): string {
  if (ageS === null || !Number.isFinite(ageS) || ageS < 0) return "--";
  if (ageS < 5) return "just now";
  if (ageS < 60) return `${Math.floor(ageS)} s ago`;
  if (ageS < 3600) return `${Math.floor(ageS / 60)} min ago`;
  if (ageS < 86400) return `${Math.floor(ageS / 3600)} h ago`;
  return `${Math.floor(ageS / 86400)} d ago`;
}
