// Pure model of the ECCO Weather & Solar card: configuration, parsing, time-zone handling, freshness, sun times, the hourly
// solar series and the explanatory insights. No DOM, no Home Assistant object, no network: everything here is a function of
// its arguments, so the node:test suites drive it directly.
//
// The ECCO blend is READ, never recomputed: sensor.ecco_solar_forecast_* (home-assistant/packages/ecco_pro.yaml) is the one
// 50/50 mean with single-source fallback, and its forecast_solar_kwh / solcast_kwh attributes are the source values it used.
import type {
  CardConfig,
  EntityConfig,
  EntityLike,
  ForecastEntry,
  Freshness,
  FreshnessView,
  HaConfigLike,
  HourPoint,
  Layout,
  Num,
  SolarTotals,
  StaleConfig,
  StatRow,
  StatesLike,
  SunView,
} from "./types.ts";

export const DEFAULT_ENTITIES: EntityConfig = {
  weather: "weather.forecast_home",
  sun: "sun.sun",
  blend_today: "sensor.ecco_solar_forecast_today",
  blend_remaining: "sensor.ecco_solar_forecast_remaining",
  blend_tomorrow: "sensor.ecco_solar_forecast_tomorrow",
  solcast_today: "sensor.solcast_pv_forecast_forecast_today",
  solcast_tomorrow: "sensor.solcast_pv_forecast_forecast_tomorrow",
  solcast_remaining: "sensor.solcast_pv_forecast_forecast_remaining_today",
  solcast_last_polled: "sensor.solcast_pv_forecast_api_last_polled",
  forecast_solar_today: "sensor.energy_production_today",
  forecast_solar_remaining: "sensor.energy_production_today_remaining",
  forecast_solar_tomorrow: "sensor.energy_production_tomorrow",
  forecast_solar_current_hour: "sensor.energy_current_hour",
  forecast_solar_next_hour: "sensor.energy_next_hour",
  pv_power: "sensor.ecco_pv_power",
  pv_today: "sensor.ecco_clock_dongle_ecco_day_pv_energy",
  pv_energy_statistic: "sensor.ecco_clock_dongle_ecco_total_pv_energy",
  blend_mae: "sensor.ecco_blend_mae",
  solcast_mae: "sensor.ecco_solcast_mae",
  forecast_solar_mae: "sensor.ecco_forecast_solar_mae",
  blend_error: "sensor.ecco_blend_error",
  solcast_error: "sensor.ecco_solcast_error",
  forecast_solar_error: "sensor.ecco_forecast_solar_error",
  best_source: "sensor.ecco_forecast_best_source",
  learning_days: "sensor.ecco_forecast_learning_days",
};

export const DEFAULT_STALE: StaleConfig = { weather_hours: 3, solcast_hours: 24, forecast_solar_hours: 6 };

export const LAYOUTS: readonly Layout[] = ["full", "solar_strip", "daily_compact"];
/** The title each layout shows when the configuration gives none (an empty `title` hides it in the compact layouts). */
export const DEFAULT_TITLES: Record<Layout, string> = { full: "Weather & Solar", solar_strip: "Solar forecast", daily_compact: "Next days" };

export const HOUR_MS = 3600000;
export const MINUTE_MS = 60000;
const ENTITY_RE = /^[a-z_]+\.[a-z0-9_]+$/;
const UNAVAILABLE = new Set(["", "unknown", "unavailable", "none", "null", "nan"]);

/** Validates a Lovelace config; throws (Home Assistant then shows its error card) on anything it cannot honour. */
export function normalizeConfig(raw: unknown): CardConfig {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) throw new Error("ecco-weather-solar-card: the configuration must be a mapping");
  const c = raw as Record<string, unknown>;
  const entities: EntityConfig = { ...DEFAULT_ENTITIES };
  const given = c.entities;
  if (given !== undefined) {
    if (given === null || typeof given !== "object" || Array.isArray(given)) throw new Error("ecco-weather-solar-card: `entities` must be a mapping");
    for (const [k, v] of Object.entries(given as Record<string, unknown>)) {
      if (!(k in DEFAULT_ENTITIES)) throw new Error(`ecco-weather-solar-card: unknown entities key \`${k}\``);
      if (typeof v !== "string" || !ENTITY_RE.test(v)) throw new Error(`ecco-weather-solar-card: entities.${k} must be an entity id`);
      (entities as unknown as Record<string, string>)[k] = v;
    }
  }
  if (!entities.weather.startsWith("weather.")) throw new Error("ecco-weather-solar-card: entities.weather must be a weather entity");
  const stale: StaleConfig = { ...DEFAULT_STALE };
  if (c.stale !== undefined) {
    if (c.stale === null || typeof c.stale !== "object" || Array.isArray(c.stale)) throw new Error("ecco-weather-solar-card: `stale` must be a mapping");
    for (const [k, v] of Object.entries(c.stale as Record<string, unknown>)) {
      if (!(k in DEFAULT_STALE)) throw new Error(`ecco-weather-solar-card: unknown stale key \`${k}\``);
      if (typeof v !== "number" || !Number.isFinite(v) || v <= 0 || v > 168) throw new Error(`ecco-weather-solar-card: stale.${k} must be 0-168 hours`);
      (stale as unknown as Record<string, number>)[k] = v;
    }
  }
  const int = (key: string, dflt: number, lo: number, hi: number): number => {
    const v = c[key];
    if (v === undefined) return dflt;
    if (typeof v !== "number" || !Number.isInteger(v) || v < lo || v > hi) throw new Error(`ecco-weather-solar-card: ${key} must be an integer ${lo}-${hi}`);
    return v;
  };
  const bool = (key: string, dflt: boolean): boolean => {
    const v = c[key];
    if (v === undefined) return dflt;
    if (typeof v !== "boolean") throw new Error(`ecco-weather-solar-card: ${key} must be true or false`);
    return v;
  };
  const layout: Layout | null = c.layout === undefined ? "full" : (LAYOUTS as readonly unknown[]).includes(c.layout) ? (c.layout as Layout) : null;
  if (layout === null) throw new Error(`ecco-weather-solar-card: layout must be one of ${LAYOUTS.join(", ")}`);
  const title = c.title === undefined ? DEFAULT_TITLES[layout] : String(c.title).slice(0, 80);
  const known = new Set(["type", "title", "layout", "entities", "hourly_hours", "daily_days", "show_accuracy", "show_insights", "stale",
    "grid_options", "view_layout", "visibility"]);
  for (const k of Object.keys(c)) if (!known.has(k)) throw new Error(`ecco-weather-solar-card: unknown option \`${k}\``);
  return {
    title,
    layout,
    entities,
    hourly_hours: int("hourly_hours", 12, 1, 48),
    daily_days: int("daily_days", 5, 1, 7),
    show_accuracy: bool("show_accuracy", true),
    show_insights: bool("show_insights", true),
    stale,
  };
}

// ---------------------------------------------------------------------------------------------------------------- numbers
/** A finite number from a state or attribute value, or null for anything unknown / unavailable / non-numeric. */
export function toNum(v: unknown): Num {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  const s = v.trim();
  if (UNAVAILABLE.has(s.toLowerCase()) || !/^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function stateOf(states: StatesLike, id: string): EntityLike | undefined {
  const e = states[id];
  return e && typeof e === "object" && typeof e.state === "string" ? e : undefined;
}

export function entityNum(states: StatesLike, id: string): Num {
  const e = stateOf(states, id);
  return e ? toNum(e.state) : null;
}

export function isAvailable(e: EntityLike | undefined): boolean {
  return !!e && !UNAVAILABLE.has(e.state.trim().toLowerCase());
}

/** Epoch ms of an ISO timestamp / epoch-ms number, or null. */
export function parseTime(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) && v > 0 ? v : null;
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(v)) return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : null;
}

export function fmtNum(v: Num, digits = 1): string {
  return v === null ? "--" : v.toFixed(digits);
}

export function fmtKwh(v: Num): string {
  return v === null ? "--" : `${v.toFixed(1)} kWh`;
}

// ---------------------------------------------------------------------------------------------------------------- time zone
const partsCache = new Map<string, Intl.DateTimeFormat>();

export function isValidTimeZone(tz: unknown): tz is string {
  if (typeof tz !== "string" || !tz) return false;
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** The Home Assistant server time zone (dates and hours follow the installation, not the browser), else UTC. */
export function haTimeZone(cfg: HaConfigLike | null): string {
  return cfg && isValidTimeZone(cfg.time_zone) ? cfg.time_zone : "UTC";
}

export interface ZonedParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  weekday: string;
}

export function zonedParts(ms: number, tz: string): ZonedParts {
  let f = partsCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short",
    });
    partsCache.set(tz, f);
  }
  const p: Record<string, string> = {};
  for (const x of f.formatToParts(new Date(ms))) p[x.type] = x.value;
  return {
    year: Number(p.year), month: Number(p.month), day: Number(p.day), hour: Number(p.hour) % 24, minute: Number(p.minute), weekday: p.weekday ?? "",
  };
}

const pad = (n: number): string => String(n).padStart(2, "0");

export function dateKey(ms: number, tz: string): string {
  const p = zonedParts(ms, tz);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

export function hourKey(ms: number, tz: string): string {
  const p = zonedParts(ms, tz);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}`;
}

export function fmtTime(ms: number | null, tz: string): string {
  if (ms === null) return "--";
  const p = zonedParts(ms, tz);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

export function fmtWeekday(ms: number, tz: string): string {
  return zonedParts(ms, tz).weekday;
}

/** The epoch-ms starts of every whole hour that falls on local date `key` (23, 24 or 25 of them across DST changes). */
export function hourStartsOfDay(key: string, tz: string): number[] {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!m) return [];
  const base = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const out: number[] = [];
  for (let h = -15; h <= 39; h++) {
    const t = base + h * HOUR_MS;
    if (dateKey(t, tz) === key && zonedParts(t, tz).minute === 0) out.push(t);
  }
  return out;
}

/** The local date key one calendar day after `key` (DST-safe: steps from local noon). */
export function nextDateKey(key: string, tz: string): string {
  const starts = hourStartsOfDay(key, tz);
  const noon = starts.find((t) => zonedParts(t, tz).hour === 12) ?? starts[12] ?? Date.UTC(2000, 0, 1);
  return dateKey(noon + 24 * HOUR_MS, tz);
}

export function fmtDuration(ms: number | null): string {
  if (ms === null || ms < 0) return "--";
  const min = Math.round(ms / MINUTE_MS);
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h} h ${pad(m)} min` : `${m} min`;
}

export function fmtAge(ms: number | null): string {
  if (ms === null) return "update time unknown";
  if (ms < 0) return "just now";
  const min = Math.floor(ms / MINUTE_MS);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} days ago`;
}

// ---------------------------------------------------------------------------------------------------------------- freshness
function freshnessOf(label: string, at: number | null, now: number, staleHours: number, detail: string): FreshnessView {
  if (at === null) return { label, status: "unknown", ageMs: null, detail };
  const age = now - at;
  const status: Freshness = age > staleHours * HOUR_MS ? "stale" : "fresh";
  return { label, status, ageMs: age, detail };
}

function latestUpdate(states: StatesLike, ids: string[]): number | null {
  let best: number | null = null;
  for (const id of ids) {
    const e = stateOf(states, id);
    if (!e || !isAvailable(e)) continue;
    const t = parseTime(e.last_updated) ?? parseTime(e.last_changed);
    if (t !== null && (best === null || t > best)) best = t;
  }
  return best;
}

/** Solcast: the integration's own "API last polled" timestamp; else the newest update of its forecast sensors. */
export function solcastFreshness(states: StatesLike, e: EntityConfig, now: number, stale: StaleConfig): FreshnessView {
  const polled = stateOf(states, e.solcast_last_polled);
  const at = polled && isAvailable(polled) ? parseTime(polled.state) : null;
  if (at !== null) return freshnessOf("Solcast", at, now, stale.solcast_hours, "last API poll");
  return freshnessOf("Solcast", latestUpdate(states, [e.solcast_today, e.solcast_tomorrow, e.solcast_remaining]), now, stale.solcast_hours,
    "newest sensor update");
}

/** Forecast.Solar: the newest update of its forecast sensors (the ECCO blend sensors re-sample every 5 minutes, so their own
 *  update time says nothing about the data). */
export function forecastSolarFreshness(states: StatesLike, e: EntityConfig, now: number, stale: StaleConfig): FreshnessView {
  return freshnessOf("Forecast.Solar", latestUpdate(states, [e.forecast_solar_today, e.forecast_solar_remaining, e.forecast_solar_tomorrow]), now,
    stale.forecast_solar_hours, "newest sensor update");
}

/** Weather: the current-conditions update time; the forecast is stale too when its first hour is already well past. */
export function weatherFreshness(states: StatesLike, e: EntityConfig, hourly: ForecastEntry[] | null, now: number, stale: StaleConfig): FreshnessView {
  const w = stateOf(states, e.weather);
  const at = w && isAvailable(w) ? (parseTime(w.last_updated) ?? parseTime(w.last_changed)) : null;
  const f = freshnessOf("Met.no weather", at, now, stale.weather_hours, "current conditions");
  const first = hourly && hourly.length ? parseTime(hourly[0]!.datetime) : null;
  if (first !== null && now - first > stale.weather_hours * HOUR_MS) return { ...f, status: "stale", detail: "hourly forecast starts in the past" };
  return f;
}

// ---------------------------------------------------------------------------------------------------------------- solar
/** The ECCO blend and the two source values it used (its own attributes), with the raw provider sensor as a fallback when an
 *  older blend sensor carries no attribute. `null` attribute = that source was invalid when the blend sampled. */
export function solarTotals(states: StatesLike, blendId: string, solcastId: string, fsId: string): SolarTotals {
  const b = stateOf(states, blendId);
  const blend = b ? toNum(b.state) : null;
  const attrs = (b && b.attributes) || {};
  const has = (k: string): boolean => Object.prototype.hasOwnProperty.call(attrs, k);
  const solcast = has("solcast_kwh") ? toNum(attrs.solcast_kwh) : entityNum(states, solcastId);
  const forecastSolar = has("forecast_solar_kwh") ? toNum(attrs.forecast_solar_kwh) : entityNum(states, fsId);
  const basis = blend === null ? "none" : solcast !== null && forecastSolar !== null ? "both" : solcast !== null ? "solcast" : forecastSolar !== null ? "forecast_solar" : "none";
  return { blend, solcast, forecastSolar, basis };
}

export interface SolcastHour {
  start: number;
  estimate: number;
  p10: Num;
  p90: Num;
}

/** Solcast's hourly detail (`detailedHourly`, kWh per hour = average kW over the hour), else its half-hourly
 *  `detailedForecast` (kW averages) folded into hours. Keyed by local hour. Malformed entries are skipped. */
export function solcastHourly(entity: EntityLike | undefined, tz: string): Map<string, SolcastHour> {
  const out = new Map<string, SolcastHour>();
  const a = (entity && entity.attributes) || {};
  const hourly = Array.isArray(a.detailedHourly) ? a.detailedHourly : null;
  const half = Array.isArray(a.detailedForecast) ? a.detailedForecast : null;
  const rows = hourly ?? half;
  if (!rows) return out;
  const factor = hourly ? 1 : 0.5;
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const o = r as Record<string, unknown>;
    const start = parseTime(o.period_start);
    const est = toNum(o.pv_estimate);
    if (start === null || est === null || est < 0) continue;
    const key = hourKey(start, tz);
    const p10 = toNum(o.pv_estimate10);
    const p90 = toNum(o.pv_estimate90);
    const prev = out.get(key);
    const hourStart = start - (zonedParts(start, tz).minute * MINUTE_MS);
    if (prev) {
      prev.estimate += est * factor;
      prev.p10 = prev.p10 !== null && p10 !== null ? prev.p10 + p10 * factor : null;
      prev.p90 = prev.p90 !== null && p90 !== null ? prev.p90 + p90 * factor : null;
    } else {
      out.set(key, { start: hourStart, estimate: est * factor, p10: p10 === null ? null : p10 * factor, p90: p90 === null ? null : p90 * factor });
    }
  }
  return out;
}

/** Hourly actual generation (kWh) from long-term statistics `change` rows, keyed by local hour. Negative changes (a counter
 *  reset) and non-numeric rows are dropped, never shown as generation. */
export function statisticsByHour(rows: StatRow[] | null, tz: string): Map<string, number> {
  const out = new Map<string, number>();
  if (!rows) return out;
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const start = typeof r.start === "number" ? r.start : parseTime(r.start);
    const ch = toNum(r.change);
    if (start === null || ch === null || ch < 0) continue;
    const key = hourKey(start, tz);
    out.set(key, (out.get(key) ?? 0) + ch);
  }
  return out;
}

export function weatherByHour(hourly: ForecastEntry[] | null, tz: string): Map<string, ForecastEntry> {
  const out = new Map<string, ForecastEntry>();
  for (const f of hourly ?? []) {
    const t = parseTime(f && f.datetime);
    if (t === null) continue;
    const key = hourKey(t, tz);
    if (!out.has(key)) out.set(key, f);
  }
  return out;
}

/** One point per local hour of `day`: Solcast estimate (and P10 / P90), actual PV, cloud cover and rain. */
export function buildDayPoints(day: string, tz: string, solcast: Map<string, SolcastHour>, actual: Map<string, number>,
  weather: Map<string, ForecastEntry>): HourPoint[] {
  return hourStartsOfDay(day, tz).map((start) => {
    const key = hourKey(start, tz);
    const s = solcast.get(key);
    const w = weather.get(key);
    return {
      key,
      start,
      hour: zonedParts(start, tz).hour,
      solcast: s ? s.estimate : null,
      p10: s ? s.p10 : null,
      p90: s ? s.p90 : null,
      actual: actual.has(key) ? (actual.get(key) as number) : null,
      cloud: w ? toNum(w.cloud_coverage) : null,
      rain: w ? toNum(w.precipitation) : null,
      rainProbability: w ? toNum(w.precipitation_probability) : null,
    };
  });
}

/** Solcast's expected energy from the start of `points` up to `now` (the current hour pro rata). Null without a profile. */
export function expectedSoFar(points: HourPoint[], now: number): Num {
  let any = false;
  let sum = 0;
  for (const p of points) {
    if (p.solcast === null) continue;
    any = true;
    if (now >= p.start + HOUR_MS) sum += p.solcast;
    else if (now > p.start) sum += p.solcast * ((now - p.start) / HOUR_MS);
  }
  return any ? sum : null;
}

export function actualSoFar(points: HourPoint[]): Num {
  let any = false;
  let sum = 0;
  for (const p of points) {
    if (p.actual === null) continue;
    any = true;
    sum += p.actual;
  }
  return any ? sum : null;
}

export function peakHour(points: HourPoint[]): HourPoint | null {
  let best: HourPoint | null = null;
  for (const p of points) if (p.solcast !== null && p.solcast > 0 && (!best || p.solcast > (best.solcast as number))) best = p;
  return best;
}

// ---------------------------------------------------------------------------------------------------------------- sun
/** Sunrise / sunset (epoch ms) on local date `key` at lat / lon: the NOAA algorithm, the same as intelligence/timeutil.py
 *  sun_times() (about a minute at UK latitudes). Null in polar day / night. */
export function noaaSunTimes(key: string, lat: number, lon: number): { rise: number; set: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!m || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const rad = Math.PI / 180;
  const n = (Date.UTC(y, mo - 1, d) - Date.UTC(2000, 0, 1)) / 86400000 + 0.5;
  const jdCycle = n - lon / 360;
  const meanAnomDeg = (((357.5291 + 0.98560028 * jdCycle) % 360) + 360) % 360;
  const M = meanAnomDeg * rad;
  const center = 1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M);
  const eclLon = ((((meanAnomDeg + center + 180 + 102.9372) % 360) + 360) % 360) * rad;
  const transit = 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * eclLon);
  const decl = Math.asin(Math.sin(eclLon) * Math.sin(23.44 * rad));
  const cosH = (Math.sin(-0.833 * rad) - Math.sin(lat * rad) * Math.sin(decl)) / (Math.cos(lat * rad) * Math.cos(decl));
  if (cosH > 1 || cosH < -1) return null;
  const hourAngleDays = (Math.acos(cosH) / rad) / 360;
  const noon = Date.UTC(y, mo - 1, d, 12) - (lon / 360 - transit) * 86400000;
  return { rise: noon - hourAngleDays * 86400000, set: noon + hourAngleDays * 86400000 };
}

/** Today's sun: Home Assistant's Sun integration is authoritative for every event still ahead (next_rising / next_setting
 *  on today's local date); an event already passed today (sun.sun only exposes the NEXT one) is calculated. */
export function sunView(states: StatesLike, sunId: string, cfg: HaConfigLike | null, now: number, tz: string): SunView {
  const s = stateOf(states, sunId);
  const a = (s && isAvailable(s) && s.attributes) || {};
  const nextRise = parseTime(a.next_rising);
  const nextSet = parseTime(a.next_setting);
  const today = dateKey(now, tz);
  const lat = cfg ? cfg.latitude : undefined;
  const lon = cfg ? cfg.longitude : undefined;
  const calc = typeof lat === "number" && typeof lon === "number" ? noaaSunTimes(today, lat, lon) : null;
  let sunrise: number | null = null;
  let sunset: number | null = null;
  let riseSrc: SunView["sunriseSource"] = "none";
  let setSrc: SunView["sunsetSource"] = "none";
  if (nextRise !== null && dateKey(nextRise, tz) === today) {
    sunrise = nextRise;
    riseSrc = "home_assistant";
  } else if (calc) {
    sunrise = calc.rise;
    riseSrc = "calculated";
  }
  if (nextSet !== null && dateKey(nextSet, tz) === today) {
    sunset = nextSet;
    setSrc = "home_assistant";
  } else if (calc) {
    sunset = calc.set;
    setSrc = "calculated";
  }
  const above = s && isAvailable(s) ? (s.state === "above_horizon" ? true : s.state === "below_horizon" ? false : null) : null;
  let phase: SunView["phase"] = "unknown";
  if (sunrise !== null && sunset !== null) phase = now < sunrise ? "before_sunrise" : now < sunset ? "day" : "after_sunset";
  const daylight = sunrise !== null && sunset !== null && sunset > sunrise ? sunset - sunrise : null;
  const remaining = phase === "day" && sunset !== null ? sunset - now : phase === "after_sunset" ? 0 : phase === "before_sunrise" ? daylight : null;
  const nextSunrise = nextRise ?? (phase === "before_sunrise" ? sunrise : null);
  return {
    available: sunrise !== null || sunset !== null,
    aboveHorizon: above,
    sunrise,
    sunset,
    sunriseSource: riseSrc,
    sunsetSource: setSrc,
    daylightMs: daylight,
    remainingMs: remaining,
    nextSunrise,
    phase,
  };
}

// ---------------------------------------------------------------------------------------------------------------- weather
export const CONDITIONS: Record<string, { label: string; icon: string }> = {
  "clear-night": { label: "Clear night", icon: "mdi:weather-night" },
  cloudy: { label: "Cloudy", icon: "mdi:weather-cloudy" },
  exceptional: { label: "Exceptional", icon: "mdi:alert-circle-outline" },
  fog: { label: "Fog", icon: "mdi:weather-fog" },
  hail: { label: "Hail", icon: "mdi:weather-hail" },
  lightning: { label: "Lightning", icon: "mdi:weather-lightning" },
  "lightning-rainy": { label: "Thunderstorm", icon: "mdi:weather-lightning-rainy" },
  partlycloudy: { label: "Partly cloudy", icon: "mdi:weather-partly-cloudy" },
  pouring: { label: "Heavy rain", icon: "mdi:weather-pouring" },
  rainy: { label: "Rain", icon: "mdi:weather-rainy" },
  snowy: { label: "Snow", icon: "mdi:weather-snowy" },
  "snowy-rainy": { label: "Sleet", icon: "mdi:weather-snowy-rainy" },
  sunny: { label: "Sunny", icon: "mdi:weather-sunny" },
  windy: { label: "Windy", icon: "mdi:weather-windy" },
  "windy-variant": { label: "Windy and cloudy", icon: "mdi:weather-windy-variant" },
};

export function condition(c: unknown): { label: string; icon: string } {
  return typeof c === "string" && CONDITIONS[c] ? (CONDITIONS[c] as { label: string; icon: string }) : { label: "Unknown", icon: "mdi:help-circle-outline" };
}

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

export function compass(bearing: unknown): string {
  if (typeof bearing === "string" && COMPASS.includes(bearing.toUpperCase())) return bearing.toUpperCase();
  const b = toNum(bearing);
  if (b === null) return "--";
  return COMPASS[Math.round((((b % 360) + 360) % 360) / 22.5) % 16] as string;
}

/** Forecast entries from the hour containing `now` onwards, at most `n`. */
export function upcomingHours(hourly: ForecastEntry[] | null, now: number, n: number): ForecastEntry[] {
  return (hourly ?? []).filter((f) => {
    const t = parseTime(f && f.datetime);
    return t !== null && t + HOUR_MS > now;
  }).slice(0, n);
}

/** Daily entries from today (local) onwards, at most `n`. */
export function upcomingDays(daily: ForecastEntry[] | null, now: number, n: number, tz: string): ForecastEntry[] {
  const today = dateKey(now, tz);
  return (daily ?? []).filter((f) => {
    const t = parseTime(f && f.datetime);
    return t !== null && dateKey(t, tz) >= today;
  }).slice(0, n);
}

/** True when any entry carries a rain probability (Met.no does not; other integrations may). */
export function hasRainProbability(entries: ForecastEntry[]): boolean {
  return entries.some((f) => toNum(f.precipitation_probability) !== null);
}

/** Mean cloud cover and total rain over the daylight hours of `points` (hours with a Solcast estimate above zero). */
export function daylightWeather(points: HourPoint[]): { cloud: Num; rain: Num; hours: number } {
  const day = points.filter((p) => p.solcast !== null && p.solcast > 0);
  const cl = day.map((p) => p.cloud).filter((v): v is number => v !== null);
  const rn = day.map((p) => p.rain).filter((v): v is number => v !== null);
  return {
    cloud: cl.length ? cl.reduce((x, y) => x + y, 0) / cl.length : null,
    rain: rn.length ? rn.reduce((x, y) => x + y, 0) : null,
    hours: cl.length,
  };
}

// ---------------------------------------------------------------------------------------------------------------- accuracy
export interface AccuracyRow {
  source: "Blend" | "Solcast" | "Forecast.Solar";
  mae: Num;
  error: Num;
  errorPct: Num;
}

export interface AccuracyView {
  rows: AccuracyRow[];
  bestSource: string | null;
  learningDays: Num;
  scoredDate: string | null;
  available: boolean;
}

/** The existing ECCO day-ahead scorecard (snapshot at 23:55, scored at 23:50 against day PV): read as is. */
export function accuracyView(states: StatesLike, e: EntityConfig): AccuracyView {
  const row = (source: AccuracyRow["source"], maeId: string, errId: string): AccuracyRow => {
    const err = stateOf(states, errId);
    return { source, mae: entityNum(states, maeId), error: err ? toNum(err.state) : null, errorPct: err ? toNum((err.attributes || {}).error_percent) : null };
  };
  const rows = [row("Blend", e.blend_mae, e.blend_error), row("Solcast", e.solcast_mae, e.solcast_error),
    row("Forecast.Solar", e.forecast_solar_mae, e.forecast_solar_error)];
  const best = stateOf(states, e.best_source);
  const scored = stateOf(states, e.blend_error);
  const sd = scored && scored.attributes ? scored.attributes.scored_date : undefined;
  return {
    rows,
    bestSource: best && isAvailable(best) ? best.state : null,
    learningDays: entityNum(states, e.learning_days),
    scoredDate: typeof sd === "string" && /^\d{4}-\d{2}-\d{2}$/.test(sd) ? sd : null,
    available: rows.some((r) => r.mae !== null || r.error !== null),
  };
}

// ---------------------------------------------------------------------------------------------------------------- insights
export interface InsightInputs {
  today: SolarTotals;
  tomorrow: SolarTotals;
  todayPoints: HourPoint[];
  tomorrowPoints: HourPoint[];
  now: number;
  tz: string;
  accuracy: AccuracyView;
  pvToday: Num;
}

/** Short, factual, explanatory notes. They describe the forecasts; ECCO does not act on them. */
export function insights(i: InsightInputs): string[] {
  const out: string[] = [];
  const disagreement = (label: string, t: SolarTotals): void => {
    if (t.solcast === null || t.forecastSolar === null) return;
    const mean = (t.solcast + t.forecastSolar) / 2;
    const diff = Math.abs(t.solcast - t.forecastSolar);
    if (mean >= 1 && diff / mean >= 0.3) {
      const hi = t.solcast > t.forecastSolar ? "Solcast" : "Forecast.Solar";
      out.push(`${label}: the two forecasts disagree by ${diff.toFixed(1)} kWh (${hi} is higher); the ECCO blend sits halfway at ${fmtKwh(t.blend)}.`);
    }
  };
  for (const [label, t] of [["Today", i.today], ["Tomorrow", i.tomorrow]] as Array<[string, SolarTotals]>) {
    if (t.basis === "solcast" || t.basis === "forecast_solar") {
      out.push(`${label}: the ECCO blend is using ${t.basis === "solcast" ? "Solcast" : "Forecast.Solar"} only (the other source is unavailable).`);
    }
  }
  disagreement("Today", i.today);
  disagreement("Tomorrow", i.tomorrow);
  const expected = expectedSoFar(i.todayPoints, i.now);
  const actual = i.pvToday ?? actualSoFar(i.todayPoints);
  if (expected !== null && actual !== null && expected >= 0.5) {
    const pct = Math.round((actual / expected) * 100);
    out.push(`So far today: ${actual.toFixed(1)} kWh generated against ${expected.toFixed(1)} kWh in Solcast's profile to this time (${pct}%).`);
  }
  const peak = peakHour(i.tomorrowPoints);
  if (peak) out.push(`Tomorrow's Solcast peak is ${peak.solcast!.toFixed(1)} kWh in the ${fmtTime(peak.start, i.tz)} hour.`);
  const dw = daylightWeather(i.tomorrowPoints);
  if (dw.cloud !== null && dw.hours >= 3) {
    out.push(`Tomorrow's daylight hours average ${Math.round(dw.cloud)}% cloud cover${dw.rain !== null ? ` with ${dw.rain.toFixed(1)} mm of rain` : ""} (Met.no, ${dw.hours} h covered).`);
  }
  const a = i.accuracy;
  if (a.bestSource && a.learningDays !== null && a.learningDays >= 7) {
    const best = a.rows.find((r) => r.source === a.bestSource);
    const blend = a.rows.find((r) => r.source === "Blend");
    if (best && best.mae !== null) {
      out.push(`Over ${Math.round(a.learningDays)} scored days ${a.bestSource} has been most accurate (mean error ${best.mae.toFixed(1)} kWh${blend && blend.mae !== null && a.bestSource !== "Blend" ? `; blend ${blend.mae.toFixed(1)} kWh` : ""}).`);
    }
  }
  return out;
}
