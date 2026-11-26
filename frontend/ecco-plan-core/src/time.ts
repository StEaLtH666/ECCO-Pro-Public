// Minute-of-day helpers. Pure; no clock, no Date. All "minutes" are wall-clock minutes since 00:00 unless named otherwise.

export const DAY_MIN = 1440;
export const GRID_MIN = 5;

export function norm(min: number): number {
  return ((Math.round(min) % DAY_MIN) + DAY_MIN) % DAY_MIN;
}

/** Forward distance in minutes from a to b around the 24-hour wall clock (0 when equal). */
export function span(a: number, b: number): number {
  return norm(b - a);
}

/** Parse "HH:MM" to minutes, or NaN. */
export function toMin(text: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(text));
  if (!m) return NaN;
  const h = Number(m[1]);
  const mm = Number(m[2]);
  return h > 23 || mm > 59 ? NaN : h * 60 + mm;
}

export function fmt(min: number): string {
  const m = norm(min);
  const p = (n: number) => (n < 10 ? "0" : "") + n;
  return p(Math.floor(m / 60)) + ":" + p(m % 60);
}

export function onGrid(min: number): boolean {
  return Number.isInteger(min) && min >= 0 && min < DAY_MIN && min % GRID_MIN === 0;
}

/**
 * A daylight-saving change on one night, in wall-clock terms. deltaMin +60 = spring forward (the wall clock skips an hour, the
 * day has 23 hours); -60 = autumn back (the wall clock repeats an hour, the day has 25 hours); 0 = an ordinary day.
 * atMin is the wall-clock minute at which the change happens (for example 120 for 02:00 -> 03:00).
 */
export interface ClockDay {
  readonly changeAtMin: number;
  readonly deltaMin: -60 | 0 | 60;
}

export const ORDINARY_DAY: ClockDay = Object.freeze({ changeAtMin: 0, deltaMin: 0 });

/** Real length of the day in minutes (1380, 1440 or 1500). */
export function dayLengthMin(day: ClockDay): number {
  return DAY_MIN - day.deltaMin;
}

export function isClockChangeNight(day: ClockDay): boolean {
  return day.deltaMin !== 0;
}

/**
 * Real elapsed minutes of a wall-clock interval that starts at startMin and spans wallMinutes of the wall clock. If the interval
 * crosses the change, a spring change removes an hour and an autumn change adds one.
 */
export function elapsedMinutes(startMin: number, wallMinutes: number, day: ClockDay): number {
  if (day.deltaMin === 0 || wallMinutes <= 0) return wallMinutes;
  const off = span(startMin, day.changeAtMin);
  const crosses = off > 0 && off < wallMinutes;
  return crosses ? wallMinutes - day.deltaMin : wallMinutes;
}

/** True when any minute of the wall-clock interval lies in [00:00, 03:00), where clock changes happen. */
export function touchesChangeHours(startMin: number, wallMinutes: number): boolean {
  for (let k = 0; k <= wallMinutes; k += GRID_MIN) if (norm(startMin + k) < 180) return true;
  return false;
}
