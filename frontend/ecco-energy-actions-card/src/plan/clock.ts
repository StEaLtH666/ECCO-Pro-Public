// The local clock as the plan core's ClockContext: the wall-clock minute now and the clock change (if any) in the next 24 hours.
// It only feeds the choices the card OFFERS ("until 07:00" within the owner's limits). The guarded script works its minutes out again on
// Home Assistant's own clock and zone, so a browser in another time zone can mislead what is offered, never what is enforced.
// `clockContextFrom` is pure (the zone offset is a parameter, so a test can feed it a clock change); `localClockContext` is the one
// place of the plan section that asks the browser for its zone.
import type { ClockContext } from "../../../ecco-plan-core/src/index.ts";

const DAY_MS = 86_400_000;
const MIN_MS = 60_000;

/**
 * `offsetWestMin(ms)` is the zone's offset in minutes WEST of UTC at that instant (the browser's getTimezoneOffset): it falls by 60 when
 * the clocks go forward and rises by 60 when they go back. Returns null for any change that is not exactly an hour.
 */
export function clockContextFrom(nowMs: number, offsetWestMin: (ms: number) => number): ClockContext | null {
  if (typeof nowMs !== "number" || !Number.isFinite(nowMs)) return null;
  const wall = (ms: number): number => (((Math.floor(ms / MIN_MS) - offsetWestMin(ms)) % 1440) + 1440) % 1440;
  const nowWallMin = wall(nowMs);
  const before = offsetWestMin(nowMs);
  const delta = before - offsetWestMin(nowMs + DAY_MS);
  if (delta === 0) return { nowWallMin, day: { changeAtMin: 0, deltaMin: 0 } };
  if (delta !== 60 && delta !== -60) return null;
  let lo = nowMs;
  let hi = nowMs + DAY_MS;
  while (hi - lo > MIN_MS) {
    const mid = Math.floor((lo + hi) / 2);
    if (offsetWestMin(mid) === before) lo = mid;
    else hi = mid;
  }
  // The wall-clock minute, still on the old clock, at which the change happens.
  const changeAtMin = (((Math.floor(hi / MIN_MS) - before) % 1440) + 1440) % 1440;
  return { nowWallMin, day: { changeAtMin, deltaMin: delta } };
}

export function localClockContext(nowMs: number): ClockContext | null {
  return clockContextFrom(nowMs, (ms) => new Date(ms).getTimezoneOffset());
}
