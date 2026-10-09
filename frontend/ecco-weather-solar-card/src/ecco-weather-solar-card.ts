// ECCO Weather & Solar card (read-only).
//
// Current weather, the hourly and five-day forecast, sun times, the ECCO blended solar forecast (today, remaining today,
// tomorrow) with its Solcast and Forecast.Solar inputs, an hourly solar chart (Solcast profile with P10-P90, actual PV,
// cloud cover and rain), forecast freshness, the existing ECCO day-ahead accuracy scorecard and explanatory insights.
//
// READ-ONLY GUARANTEE (structural): the `hass` setter keeps three things only - the states map, the time zone / location
// from hass.config, and a Reader (src/reader.ts) bound to the websocket connection that can send exactly two read-only
// messages (weather/subscribe_forecast and recorder/statistics_during_period). Neither the Home Assistant object nor its
// connection is ever stored, so no service / action call is reachable. The only event handled is the Today / Tomorrow chart switch, which
// changes local view state. No timers: the card re-renders from Home Assistant's own state updates.
//
// LAYOUTS: `full` (default, the dedicated view) sends both forecast subscriptions and the statistics query. The Overview's two
// compact instances send only what they show: `solar_strip` the statistics query alone (no forecast subscription at all),
// `daily_compact` the daily forecast subscription alone (no hourly subscription, no statistics query).
import {
  HOUR_MS,
  MINUTE_MS,
  accuracyView,
  buildDayPoints,
  dateKey,
  entityNum,
  forecastSolarFreshness,
  haTimeZone,
  insights,
  isAvailable,
  nextDateKey,
  normalizeConfig,
  solarTotals,
  solcastFreshness,
  solcastHourly,
  stateOf,
  statisticsByHour,
  sunView,
  toNum,
  upcomingDays,
  upcomingHours,
  weatherByHour,
  weatherFreshness,
} from "./model.ts";
import { readerFor } from "./reader.ts";
import type { Reader } from "./reader.ts";
import {
  renderAccuracy,
  renderChart,
  renderDaily,
  renderDailyCompact,
  renderFreshness,
  renderHourly,
  renderInsights,
  renderNow,
  renderShell,
  renderSolar,
  renderSolarStrip,
  renderStripChart,
  renderSun,
  unit,
} from "./render.ts";
import type { CurrentWeather } from "./render.ts";
import { COMPACT_STYLES, STYLES } from "./styles.ts";
import type { CardConfig, EntityLike, ForecastEntry, HaConfigLike, Layout, StatRow, StatesLike } from "./types.ts";

export const CARD_TAG = "ecco-weather-solar-card";
export const CARD_VERSION = "0.1.0";
/** Re-fetch hourly actual-PV statistics at most this often (the recorder writes hourly statistics; a new hour shows within
 *  this interval of its completion). */
export const STATS_REFRESH_MS = 10 * MINUTE_MS;
/** Re-render at least once a minute when Home Assistant pushes any update, so ages and daylight-left stay current. */
export const RENDER_BUCKET_MS = MINUTE_MS;

interface RegionLike {
  innerHTML: string;
}

interface RootLike {
  innerHTML: string;
  querySelector(selector: string): RegionLike | null;
  addEventListener(type: string, listener: (ev: Event) => void): void;
}

interface ActionElementLike {
  getAttribute(name: string): string | null;
}

type Kind = "hourly" | "daily";

interface ForecastSlot {
  entries: ForecastEntry[] | null;
  error: string | null;
  errorAt: number;
  unsub: (() => void) | null;
  pending: boolean;
}

/** A failed forecast subscription is retried no sooner than this (e.g. the weather entity appeared after start-up). */
export const FORECAST_RETRY_MS = 5 * MINUTE_MS;

const errText = (e: unknown): string => {
  const m = e !== null && typeof e === "object" ? (e as { message?: unknown; code?: unknown }) : null;
  const s = m && typeof m.message === "string" ? m.message : m && typeof m.code === "string" ? m.code : String(e);
  return s.slice(0, 160);
};

/** The forecast subscriptions a layout needs: the strip shows no weather at all, the compact daily list only the daily one. */
const kindsFor = (layout: Layout): Kind[] => (layout === "full" ? ["hourly", "daily"] : layout === "daily_compact" ? ["daily"] : []);

/** Why a day has no Solcast hourly profile, or null when it has one (the same message in every layout). */
const solcastNoteFor = (entity: EntityLike | undefined, id: string, hours: Map<string, unknown>): string | null =>
  !entity || !isAvailable(entity) ? `Solcast sensor ${id} not found or unavailable.`
    : hours.size === 0 ? "Solcast hourly detail is not available (enable the detailed forecast attributes in the Solcast integration options)." : null;

export class EccoWeatherSolarCard extends HTMLElement {
  /** Clock; replaceable in tests. */
  now: () => number = () => Date.now();

  private _config: CardConfig | null = null;
  private _states: StatesLike = {};
  private _haConfig: HaConfigLike | null = null;
  private _reader: Reader | null = null;
  private _hassSeen = false;
  private _root: RootLike | null = null;
  private _listening = false;
  private _connected = false;
  private _gen = 0;
  private _forecast: Record<Kind, ForecastSlot> = { hourly: emptySlot(), daily: emptySlot() };
  private _forecastFor = "";
  private _stats: StatRow[] | null = null;
  private _statsError: string | null = null;
  private _statsAt = 0;
  private _statsFor = "";
  private _statsInFlight = false;
  private _day: "today" | "tomorrow" = "today";
  private _signature = "";
  private _version = 0;

  setConfig(config: unknown): void {
    const next = normalizeConfig(config);
    const weatherChanged = !this._config || this._config.entities.weather !== next.entities.weather;
    const layoutChanged = !this._config || this._config.layout !== next.layout;
    this._config = next;
    this._buildShell();
    if (weatherChanged || layoutChanged) this._resubscribe();
    if (this._statsFor !== next.entities.pv_energy_statistic) this._statsAt = 0;
    // A layout or statistic change on a live card is served now rather than on the next hass update; before the first
    // hass update there is no reader yet, and the usual throttle still applies.
    this._maybeFetchStats();
    this._render(true);
  }

  set hass(hass: unknown) {
    const h = hass !== null && typeof hass === "object" ? (hass as { states?: unknown; config?: unknown; connection?: unknown }) : {};
    // Keep ONLY the states map, the time zone / location and a two-message reader; never the Home Assistant object.
    this._states = h.states !== null && typeof h.states === "object" ? (h.states as StatesLike) : {};
    const cfg = h.config !== null && typeof h.config === "object" ? (h.config as Record<string, unknown>) : null;
    this._haConfig = cfg ? {
      time_zone: typeof cfg.time_zone === "string" ? cfg.time_zone : undefined,
      latitude: typeof cfg.latitude === "number" ? cfg.latitude : undefined,
      longitude: typeof cfg.longitude === "number" ? cfg.longitude : undefined,
    } : null;
    this._hassSeen = true;
    const reader = readerFor(h.connection);
    if (reader !== this._reader) {
      this._reader = reader;
      this._resubscribe();
    } else {
      this._ensureSubscribed();
    }
    this._maybeFetchStats();
    this._render(false);
  }

  connectedCallback(): void {
    this._connected = true;
    this._ensureSubscribed();
    this._maybeFetchStats();
    this._render(true);
  }

  disconnectedCallback(): void {
    this._connected = false;
    this._unsubscribeAll();
  }

  getCardSize(): number {
    const layout = this._config ? this._config.layout : "full";
    return layout === "solar_strip" ? 2 : layout === "daily_compact" ? 5 : 14;
  }

  getGridOptions(): Record<string, unknown> {
    return { columns: 12, rows: "auto", min_columns: 6 };
  }

  static getStubConfig(): Record<string, unknown> {
    return {};
  }

  // -------------------------------------------------------------------------------------------------------- forecast data
  private _unsubscribeAll(): void {
    this._gen++;
    for (const kind of ["hourly", "daily"] as Kind[]) {
      const s = this._forecast[kind];
      if (s.unsub) s.unsub();
      s.unsub = null;
      s.pending = false;
    }
  }

  private _resubscribe(): void {
    this._unsubscribeAll();
    this._forecast = { hourly: emptySlot(), daily: emptySlot() };
    this._forecastFor = "";
    this._ensureSubscribed();
  }

  private _ensureSubscribed(): void {
    if (!this._config || !this._connected) return;
    const entity = this._config.entities.weather;
    const kinds = kindsFor(this._config.layout);
    if (!this._reader) {
      // Before the first hass update there is simply nothing yet: only a hass without a connection is an error.
      if (!this._hassSeen) return;
      for (const kind of kinds) {
        const s = this._forecast[kind];
        if (!s.unsub && !s.pending) {
          s.error = "no Home Assistant websocket connection (the forecast needs Home Assistant 2023.9 or newer)";
          s.errorAt = this.now();
        }
      }
      return;
    }
    if (this._forecastFor !== entity) {
      this._unsubscribeAll();
      this._forecast = { hourly: emptySlot(), daily: emptySlot() };
      this._forecastFor = entity;
    }
    const gen = this._gen;
    for (const kind of kinds) {
      const slot = this._forecast[kind];
      if (slot.unsub || slot.pending) continue;
      if (slot.error && this.now() - slot.errorAt < FORECAST_RETRY_MS) continue;
      slot.pending = true;
      this._reader.subscribeForecast(entity, kind, (entries) => {
        if (gen !== this._gen) return;
        slot.entries = entries;
        slot.error = null;
        this._version++;
        this._render(false);
      }).then((unsub) => {
        if (gen !== this._gen) {
          unsub();
          return;
        }
        slot.pending = false;
        slot.unsub = unsub;
      }, (err: unknown) => {
        if (gen !== this._gen) return;
        slot.pending = false;
        slot.error = errText(err);
        slot.errorAt = this.now();
        this._version++;
        this._render(false);
      });
    }
  }

  private _maybeFetchStats(): void {
    if (!this._config || !this._connected || !this._reader || this._statsInFlight) return;
    // The compact daily list shows no PV at all, so it never queries the recorder.
    if (this._config.layout === "daily_compact") return;
    const id = this._config.entities.pv_energy_statistic;
    const now = this.now();
    if (this._statsFor === id && now - this._statsAt < STATS_REFRESH_MS) return;
    this._statsInFlight = true;
    this._statsAt = now;
    // From two days back (covers today in any time zone and DST) to now; bucketed by local hour afterwards.
    const start = Math.floor((now - 48 * HOUR_MS) / HOUR_MS) * HOUR_MS;
    this._reader.hourlyStatistics(id, start, now).then((rows) => {
      this._statsInFlight = false;
      this._statsFor = id;
      this._stats = rows;
      this._statsError = null;
      this._version++;
      this._render(false);
    }, (err: unknown) => {
      this._statsInFlight = false;
      this._statsFor = id;
      this._stats = null;
      this._statsError = errText(err);
      this._version++;
      this._render(false);
    });
  }

  // -------------------------------------------------------------------------------------------------------- rendering
  private _buildShell(): void {
    if (!this._config) return;
    const root = (this.shadowRoot ?? this.attachShadow({ mode: "open" })) as unknown as RootLike;
    const layout = this._config.layout;
    root.innerHTML = renderShell(this._config.title, layout === "full" ? STYLES : STYLES + COMPACT_STYLES, layout);
    if (!this._listening) {
      root.addEventListener("click", this._onClick);
      this._listening = true;
    }
    this._root = root;
    this._signature = "";
  }

  private _region(name: string): RegionLike | null {
    return this._root ? this._root.querySelector(`[data-region="${name}"]`) : null;
  }

  private _sig(now: number): string {
    if (!this._config) return "";
    const parts: string[] = [String(Math.floor(now / RENDER_BUCKET_MS)), String(this._version), this._day, haTimeZone(this._haConfig)];
    for (const id of Object.values(this._config.entities)) {
      const e = this._states[id];
      parts.push(e ? `${e.state}|${e.last_updated ?? ""}` : "-");
    }
    return parts.join("\u0002");
  }

  private _set(name: string, html: string): void {
    const r = this._region(name);
    if (r && r.innerHTML !== html) r.innerHTML = html;
  }

  /** Why today's actual-PV bars are missing, or null when they are not. */
  private _actualNote(actual: Map<string, number>): string | null {
    if (!this._config) return null;
    if (this._statsError) return `Actual PV history unavailable: ${this._statsError}`;
    if (!this._reader) return "Actual PV history needs the Home Assistant websocket connection.";
    if (this._stats && actual.size === 0) return `No hourly statistics for ${this._config.entities.pv_energy_statistic} yet (it needs a total_increasing energy sensor recorded in long-term statistics).`;
    return null;
  }

  private _render(force: boolean): void {
    if (!this._config || !this._root) return;
    const now = this.now();
    const sig = this._sig(now);
    if (!force && sig === this._signature) return;
    this._signature = sig;
    const tz = haTimeZone(this._haConfig);
    if (this._config.layout === "solar_strip") {
      this._renderStrip(now, tz);
      return;
    }
    if (this._config.layout === "daily_compact") {
      this._renderCompact(now, tz);
      return;
    }
    const e = this._config.entities;
    const st = this._states;
    const hourly = this._forecast.hourly.entries;
    const daily = this._forecast.daily.entries;

    const w = stateOf(st, e.weather);
    const wa = (w && w.attributes) || {};
    const firstHour = upcomingHours(hourly, now, 1)[0];
    const current: CurrentWeather = {
      found: !!w && isAvailable(w),
      entityId: e.weather,
      condition: w ? w.state : undefined,
      temperature: toNum(wa.temperature),
      temperatureUnit: unit(wa.temperature_unit, "°C"),
      humidity: toNum(wa.humidity),
      windSpeed: toNum(wa.wind_speed),
      windUnit: unit(wa.wind_speed_unit, "km/h"),
      windBearing: wa.wind_bearing,
      cloud: toNum(wa.cloud_coverage),
      pressure: toNum(wa.pressure),
      pressureUnit: unit(wa.pressure_unit, "hPa"),
      rainThisHour: firstHour ? toNum(firstHour.precipitation) : null,
      rainUnit: unit(wa.precipitation_unit, "mm"),
      uv: toNum(wa.uv_index),
    };
    const sun = sunView(st, e.sun, this._haConfig, now, tz);

    const today = solarTotals(st, e.blend_today, e.solcast_today, e.forecast_solar_today);
    const remaining = solarTotals(st, e.blend_remaining, e.solcast_remaining, e.forecast_solar_remaining);
    const tomorrow = solarTotals(st, e.blend_tomorrow, e.solcast_tomorrow, e.forecast_solar_tomorrow);
    const pvToday = entityNum(st, e.pv_today);

    const todayKey = dateKey(now, tz);
    const tomorrowKey = nextDateKey(todayKey, tz);
    const wByHour = weatherByHour(hourly, tz);
    const actual = statisticsByHour(this._stats, tz);
    const scToday = solcastHourly(stateOf(st, e.solcast_today), tz);
    const scTomorrow = solcastHourly(stateOf(st, e.solcast_tomorrow), tz);
    const todayPoints = buildDayPoints(todayKey, tz, scToday, actual, wByHour);
    const tomorrowPoints = buildDayPoints(tomorrowKey, tz, scTomorrow, new Map(), wByHour);
    const dayEntity = this._day === "today" ? e.solcast_today : e.solcast_tomorrow;
    const solcastNote = solcastNoteFor(stateOf(st, dayEntity), dayEntity, this._day === "today" ? scToday : scTomorrow);
    const actualNote = this._day === "today" ? this._actualNote(actual) : null;

    const set = (name: string, html: string): void => this._set(name, html);
    const stale = this._config.stale;
    set("fresh", renderFreshness([
      weatherFreshness(st, e, hourly, now, stale),
      solcastFreshness(st, e, now, stale),
      forecastSolarFreshness(st, e, now, stale),
    ]));
    set("now", renderNow(current));
    set("sun", renderSun(sun, now, tz));
    set("solar", renderSolar({ today, remaining, tomorrow, pvToday, pvNow: entityNum(st, e.pv_power) }));
    set("chart", renderChart({
      day: this._day,
      points: this._day === "today" ? todayPoints : tomorrowPoints,
      now,
      tz,
      solcastNote,
      actualNote,
      fsCurrentHour: entityNum(st, e.forecast_solar_current_hour),
      fsNextHour: entityNum(st, e.forecast_solar_next_hour),
      sunrise: sun.sunrise,
      sunset: sun.sunset,
    }));
    const tempUnit = unit(wa.temperature_unit, "°C");
    const windUnit = unit(wa.wind_speed_unit, "km/h");
    const rainUnit = unit(wa.precipitation_unit, "mm");
    const fh = this._forecast.hourly;
    const fd = this._forecast.daily;
    set("hourly", renderHourly({ entries: upcomingHours(hourly, now, this._config.hourly_hours), tz, error: fh.error, loading: fh.entries === null && !fh.error, tempUnit, windUnit, rainUnit }));
    set("daily", renderDaily({ entries: upcomingDays(daily, now, this._config.daily_days, tz), tz, error: fd.error, loading: fd.entries === null && !fd.error, tempUnit, windUnit, rainUnit }));
    const acc = accuracyView(st, e);
    set("accuracy", renderAccuracy(acc, this._config.show_accuracy));
    set("insights", renderInsights(this._config.show_insights ? insights({ today, tomorrow, todayPoints, tomorrowPoints, now, tz, accuracy: acc, pvToday }) : [],
      this._config.show_insights));
  }

  /** `solar_strip`: the three blend totals, today's Solcast / actual-PV sparkline and the two solar freshness chips. Reads the
   *  same sensors and attributes as the full layout; no weather section, so no forecast subscription and no Met.no chip. */
  private _renderStrip(now: number, tz: string): void {
    if (!this._config) return;
    const e = this._config.entities;
    const st = this._states;
    const stale = this._config.stale;
    const today = solarTotals(st, e.blend_today, e.solcast_today, e.forecast_solar_today);
    const remaining = solarTotals(st, e.blend_remaining, e.solcast_remaining, e.forecast_solar_remaining);
    const tomorrow = solarTotals(st, e.blend_tomorrow, e.solcast_tomorrow, e.forecast_solar_tomorrow);
    const actual = statisticsByHour(this._stats, tz);
    const scToday = solcastHourly(stateOf(st, e.solcast_today), tz);
    const points = buildDayPoints(dateKey(now, tz), tz, scToday, actual, new Map());
    const sun = sunView(st, e.sun, this._haConfig, now, tz);
    this._set("fresh", renderFreshness([solcastFreshness(st, e, now, stale), forecastSolarFreshness(st, e, now, stale)]));
    this._set("totals", renderSolarStrip({ today, remaining, tomorrow, pvToday: entityNum(st, e.pv_today) }));
    this._set("curve", renderStripChart({
      points,
      now,
      tz,
      solcastNote: solcastNoteFor(stateOf(st, e.solcast_today), e.solcast_today, scToday),
      actualNote: this._actualNote(actual),
      sunrise: sun.sunrise,
      sunset: sun.sunset,
    }));
  }

  /** `daily_compact`: the weather freshness chip in the header and one row per available day (never padded). */
  private _renderCompact(now: number, tz: string): void {
    if (!this._config) return;
    const e = this._config.entities;
    const st = this._states;
    const w = stateOf(st, e.weather);
    const wa = (w && w.attributes) || {};
    const fd = this._forecast.daily;
    this._set("fresh", renderFreshness([weatherFreshness(st, e, null, now, this._config.stale)]));
    this._set("daily", renderDailyCompact({
      entries: upcomingDays(fd.entries, now, this._config.daily_days, tz),
      tz,
      error: fd.error,
      loading: fd.entries === null && !fd.error,
      tempUnit: unit(wa.temperature_unit, "°C"),
      windUnit: unit(wa.wind_speed_unit, "km/h"),
      rainUnit: unit(wa.precipitation_unit, "mm"),
    }));
  }

  private _onClick = (ev: Event): void => {
    const target = ev.target as unknown as { closest?: (selector: string) => ActionElementLike | null } | null;
    const el = target && typeof target.closest === "function" ? target.closest("[data-action]") : null;
    if (!el) return;
    if (el.getAttribute("data-action") === "chart-day") {
      const d = el.getAttribute("data-day");
      if (d !== "today" && d !== "tomorrow") return;
      this._day = d;
      this._render(true);
    }
    // Any other action value is ignored: there is nothing else this card can do.
  };
}

function emptySlot(): ForecastSlot {
  return { entries: null, error: null, errorAt: 0, unsub: null, pending: false };
}

if (typeof customElements !== "undefined" && !customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, EccoWeatherSolarCard);
}

if (typeof window !== "undefined") {
  const w = window as unknown as { customCards?: Array<Record<string, unknown>> };
  w.customCards = w.customCards || [];
  if (!w.customCards.some((c) => c.type === CARD_TAG)) {
    w.customCards.push({
      type: CARD_TAG,
      name: "ECCO Weather & Solar",
      description: "Read-only weather, sun times and the ECCO blended solar forecast with an hourly solar chart.",
      preview: false,
    });
  }
}
