// Small formatting helpers, intentionally duplicated (not imported) from
// the sibling ecco-energy-flow-card/src/utils/format.ts rather than shared:
// each card bundles to a single dependency-free dist file for HACS (see
// build.mjs), and there is no shared workspace/package between them - a
// cross-package source import would break that portability model for a
// handful of lines. See test/format.test.ts.

/** Formats a power value in watts as a human string, auto-switching W/kW by magnitude. */
export function formatPower(watts: number | null | undefined): string {
  if (watts === null || watts === undefined || Number.isNaN(watts)) {
    return "--";
  }
  const abs = Math.abs(watts);
  if (abs >= 1000) {
    return `${(watts / 1000).toFixed(2)} kW`;
  }
  return `${watts.toFixed(0)} W`;
}

/** Formats a duration given in minutes as a human string ("45 min", "1h 30m"). */
export function formatDurationMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) {
    return "--";
  }
  const total = Math.round(minutes);
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

/** Formats a whole-number percentage ("25%"), or "--" when unknown. */
export function formatPercent(percent: number | null | undefined): string {
  if (percent === null || percent === undefined || Number.isNaN(percent)) {
    return "--";
  }
  return `${Math.round(percent)}%`;
}

/** Parses a Home Assistant entity state to a finite number, or null if unavailable/unknown/non-numeric. */
export function toNumber(state: string | undefined | null): number | null {
  if (state === undefined || state === null) return null;
  if (state === "unknown" || state === "unavailable" || state === "") return null;
  const n = Number(state);
  return Number.isFinite(n) ? n : null;
}

/** Parses a Home Assistant boolean-like entity state ("on"/"off"), or null if unavailable/unknown. */
export function toBoolean(state: string | undefined | null): boolean | null {
  if (state === undefined || state === null) return null;
  if (state === "unknown" || state === "unavailable" || state === "") return null;
  return state === "on";
}
