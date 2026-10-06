// Pure time helpers - no Lit, no DOM. See test/time.test.ts.

// Two independent sources happen to publish the exact same plain local-time
// string shape, "YYYY-MM-DD HH:MM:SS" - not an ISO timestamp and not tagged
// with a timezone:
//   - the firmware's free_power_ends_at, via strftime("%Y-%m-%d %H:%M:%S", ...)
//     (see firmware/ecco_clock_dongle_stage3_4_free_power.yaml, id: free_power_ends_at)
//   - Home Assistant's own input_datetime.ecco_free_power_schedule_start
//     entity state, when configured with has_date/has_time (its standard
//     string representation, with a space rather than a "T" separator)
// `new Date(string)` parsing of a non-ISO, non-timezone string is
// inconsistent across browser engines, so this parses it explicitly as
// LOCAL wall-clock time (matching how both sources actually mean it) rather
// than trusting the platform's generic Date parser. Accepts either a space
// or a "T" between date and time so it covers both sources unmodified.
const LOCAL_TIMESTAMP_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;

export function parseLocalTimestamp(text: string | undefined): Date | null {
  if (!text) return null;
  const match = LOCAL_TIMESTAMP_RE.exec(text.trim());
  if (!match) return null;
  const [, year, month, day, hour, minute, second] = match;
  const date = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second)
  );
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Formats a Date back into the same "YYYY-MM-DD HH:MM:SS" local-wall-clock shape parseLocalTimestamp() reads - what input_datetime.set_datetime expects as its `datetime` field. */
export function formatLocalTimestamp(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Formats a Date as "Tue 23 Sep • 02:00" - fixed English short names (not Intl) so the output is deterministic in tests and never silently varies with the viewer's locale. */
export function formatWeekdayDateTime(date: Date): string {
  const weekday = WEEKDAYS[date.getDay()];
  const day = date.getDate();
  const month = MONTHS[date.getMonth()];
  const hh = date.getHours().toString().padStart(2, "0");
  const mm = date.getMinutes().toString().padStart(2, "0");
  return `${weekday} ${day} ${month} • ${hh}:${mm}`;
}

/**
 * Formats the time remaining until `targetMs` as a short countdown string
 * ("1h 12m", "42m 03s", "17s"). Returns null once the target has passed -
 * callers should fall back to a static label ("Ending...") rather than show
 * a negative/zero countdown, since a real END DEFERRED condition can leave
 * the target time in the past for a while before the watchdog clears it.
 */
export function formatCountdown(targetMs: number, nowMs: number): string | null {
  const remainingMs = targetMs - nowMs;
  if (remainingMs <= 0) return null;

  const totalSeconds = Math.floor(remainingMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  return `${seconds}s`;
}
