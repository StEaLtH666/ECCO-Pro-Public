// Types only (no runtime code): the Home Assistant shapes this card reads, its configuration and its view models.

/** One Home Assistant state object, as far as this card reads it. */
export interface EntityLike {
  state: string;
  attributes?: Record<string, unknown>;
  last_changed?: string;
  last_updated?: string;
}

export type StatesLike = Record<string, EntityLike | undefined>;

/** The parts of hass.config the card uses (time zone and location for sun times). */
export interface HaConfigLike {
  time_zone?: string;
  latitude?: number;
  longitude?: number;
}

/** One entry of a weather forecast as delivered by Home Assistant (`weather/subscribe_forecast`). */
export interface ForecastEntry {
  datetime: string;
  condition?: string;
  temperature?: number;
  templow?: number;
  precipitation?: number;
  precipitation_probability?: number;
  cloud_coverage?: number;
  humidity?: number;
  wind_speed?: number;
  wind_bearing?: number | string;
  uv_index?: number;
}

/** One hourly long-term statistics row (`recorder/statistics_during_period`, type `change`). */
export interface StatRow {
  start: number | string;
  end?: number | string;
  change?: number | null;
}

/** Every entity the card reads. All are configurable; the defaults are the ECCO / integration default ids. */
export interface EntityConfig {
  weather: string;
  sun: string;
  blend_today: string;
  blend_remaining: string;
  blend_tomorrow: string;
  solcast_today: string;
  solcast_tomorrow: string;
  solcast_remaining: string;
  solcast_last_polled: string;
  forecast_solar_today: string;
  forecast_solar_remaining: string;
  forecast_solar_tomorrow: string;
  forecast_solar_current_hour: string;
  forecast_solar_next_hour: string;
  pv_power: string;
  pv_today: string;
  /** statistic id (a total_increasing energy sensor) for hourly actual generation */
  pv_energy_statistic: string;
  blend_mae: string;
  solcast_mae: string;
  forecast_solar_mae: string;
  blend_error: string;
  solcast_error: string;
  forecast_solar_error: string;
  best_source: string;
  learning_days: string;
}

export interface StaleConfig {
  weather_hours: number;
  solcast_hours: number;
  forecast_solar_hours: number;
}

/** Which sections the card renders, and so which of its two read-only messages it sends: `full` is the dedicated view
 *  (both forecast subscriptions and the statistics query); `solar_strip` is the Overview's PV forecast strip (statistics
 *  only); `daily_compact` is the Overview's "Next days" block (the daily forecast subscription only). */
export type Layout = "full" | "solar_strip" | "daily_compact";

export interface CardConfig {
  title: string;
  layout: Layout;
  entities: EntityConfig;
  hourly_hours: number;
  daily_days: number;
  show_accuracy: boolean;
  show_insights: boolean;
  stale: StaleConfig;
}

/** A displayable number: `null` means unknown / unavailable (shown as "--", never as 0). */
export type Num = number | null;

export type Freshness = "fresh" | "stale" | "unknown";

export interface FreshnessView {
  label: string;
  status: Freshness;
  ageMs: number | null;
  detail: string;
}

export interface SolarTotals {
  blend: Num;
  solcast: Num;
  forecastSolar: Num;
  /** "both", "solcast", "forecast_solar" or "none": which sources the ECCO blend is using */
  basis: "both" | "solcast" | "forecast_solar" | "none";
}

export interface HourPoint {
  /** local hour key YYYY-MM-DDTHH in the Home Assistant time zone */
  key: string;
  /** epoch ms of the hour start */
  start: number;
  hour: number;
  solcast: Num;
  p10: Num;
  p90: Num;
  actual: Num;
  cloud: Num;
  rain: Num;
  rainProbability: Num;
}

export interface SunView {
  available: boolean;
  aboveHorizon: boolean | null;
  sunrise: number | null;
  sunset: number | null;
  sunriseSource: "home_assistant" | "calculated" | "none";
  sunsetSource: "home_assistant" | "calculated" | "none";
  daylightMs: number | null;
  remainingMs: number | null;
  nextSunrise: number | null;
  phase: "before_sunrise" | "day" | "after_sunset" | "unknown";
}
