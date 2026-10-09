// Synthetic Home Assistant data shaped like the real integrations (Met.no weather, Sun, Solcast, Forecast.Solar, the ECCO
// blend / scorecard template sensors and the ECCO controller's PV sensors). Public London coordinates; no site data.
import type { EntityLike, ForecastEntry, HaConfigLike, StatRow, StatesLike } from "../src/types.ts";

export const TZ = "Europe/London";
export const HA_CONFIG: HaConfigLike = { time_zone: TZ, latitude: 51.5072, longitude: -0.1276 };
/** 2026-10-08 13:30 BST (12:30 UTC): mid-afternoon, sun up. */
export const NOW = Date.parse("2026-10-08T12:30:00Z");
export const HOUR = 3600000;

const iso = (ms: number): string => new Date(ms).toISOString();
/** Local-offset ISO string as Solcast writes it (BST = +01:00 in October before the 25th). */
export const bst = (y: number, mo: number, d: number, h: number, m = 0): string =>
  `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00+01:00`;

/** A bell-shaped Solcast day: zero outside 07-18 local, peak at 13:00, totalling about `total` kWh. */
export function solcastDay(y: number, mo: number, d: number, total: number): Array<Record<string, unknown>> {
  const shape = [0, 0, 0, 0, 0, 0, 0, 0.1, 0.4, 0.8, 1.3, 1.7, 1.95, 2, 1.9, 1.6, 1.15, 0.6, 0.2, 0, 0, 0, 0, 0];
  const sum = shape.reduce((a, b) => a + b, 0);
  return shape.map((s, h) => {
    const est = Math.round((s / sum) * total * 10000) / 10000;
    return { period_start: bst(y, mo, d, h), pv_estimate: est, pv_estimate10: Math.round(est * 0.8 * 10000) / 10000, pv_estimate90: Math.round(est * 1.2 * 10000) / 10000 };
  });
}

export function states(over: Partial<Record<string, EntityLike | undefined>> = {}): StatesLike {
  const upd = iso(NOW - 20 * 60000);
  const base: StatesLike = {
    "weather.forecast_home": {
      state: "partlycloudy",
      last_updated: upd,
      attributes: {
        temperature: 14.2, temperature_unit: "°C", humidity: 71, cloud_coverage: 48.5, pressure: 1018.4, pressure_unit: "hPa",
        wind_bearing: 247.8, wind_speed: 12.6, wind_speed_unit: "km/h", precipitation_unit: "mm", uv_index: 2.1, supported_features: 3,
      },
    },
    "sun.sun": {
      state: "above_horizon",
      last_updated: upd,
      attributes: { next_rising: "2026-10-09T06:14:30+00:00", next_setting: "2026-10-08T17:22:40+00:00", elevation: 27.1, rising: false },
    },
    "sensor.ecco_solar_forecast_today": { state: "20.5", last_updated: iso(NOW - 2 * 60000), attributes: { forecast_solar_kwh: 18.0, solcast_kwh: 23.0, blend_method: "50/50 mean when both sources valid; single-source fallback", unit_of_measurement: "kWh" } },
    "sensor.ecco_solar_forecast_remaining": { state: "8.25", last_updated: iso(NOW - 2 * 60000), attributes: { forecast_solar_kwh: 7.5, solcast_kwh: 9.0, unit_of_measurement: "kWh" } },
    "sensor.ecco_solar_forecast_tomorrow": { state: "11.0", last_updated: iso(NOW - 2 * 60000), attributes: { forecast_solar_kwh: 12.0, solcast_kwh: 10.0, unit_of_measurement: "kWh" } },
    "sensor.solcast_pv_forecast_forecast_today": { state: "23.0", last_updated: iso(NOW - 2 * HOUR), attributes: { estimate: 23.0, detailedHourly: solcastDay(2026, 10, 8, 23) } },
    "sensor.solcast_pv_forecast_forecast_tomorrow": { state: "10.0", last_updated: iso(NOW - 2 * HOUR), attributes: { estimate: 10.0, detailedHourly: solcastDay(2026, 10, 9, 10) } },
    "sensor.solcast_pv_forecast_forecast_remaining_today": { state: "9.0", last_updated: iso(NOW - 5 * 60000) },
    "sensor.solcast_pv_forecast_api_last_polled": { state: iso(NOW - 2 * HOUR), last_updated: iso(NOW - 2 * HOUR) },
    "sensor.energy_production_today": { state: "18.0", last_updated: iso(NOW - 25 * 60000) },
    "sensor.energy_production_today_remaining": { state: "7.5", last_updated: iso(NOW - 25 * 60000) },
    "sensor.energy_production_tomorrow": { state: "12.0", last_updated: iso(NOW - 25 * 60000) },
    "sensor.energy_current_hour": { state: "2.1", last_updated: iso(NOW - 25 * 60000) },
    "sensor.energy_next_hour": { state: "1.8", last_updated: iso(NOW - 25 * 60000) },
    "sensor.ecco_pv_power": { state: "2350.0", last_updated: iso(NOW - 10000) },
    "sensor.ecco_clock_dongle_ecco_day_pv_energy": { state: "9.8", last_updated: iso(NOW - 60000) },
    "sensor.ecco_blend_mae": { state: "9.344", attributes: {} },
    "sensor.ecco_solcast_mae": { state: "13.359", attributes: {} },
    "sensor.ecco_forecast_solar_mae": { state: "6.951", attributes: {} },
    "sensor.ecco_blend_error": { state: "5.646", attributes: { error_percent: 125.5, scored_date: "2026-10-07" } },
    "sensor.ecco_solcast_error": { state: "2.686", attributes: { error_percent: 59.7, scored_date: "2026-10-07" } },
    "sensor.ecco_forecast_solar_error": { state: "8.606", attributes: { error_percent: 191.2, scored_date: "2026-10-07" } },
    "sensor.ecco_forecast_best_source": { state: "Forecast.Solar", attributes: { completed_days: 23 } },
    "sensor.ecco_forecast_learning_days": { state: "23", attributes: {} },
  };
  for (const [k, v] of Object.entries(over)) {
    if (v === undefined) delete base[k];
    else base[k] = v;
  }
  return base;
}

/** Met.no-shaped hourly forecast starting at the hour containing `from`: cloud cover and precipitation, no probability. */
export function hourlyForecast(from: number, n: number, withProbability = false): ForecastEntry[] {
  const start = Math.floor(from / HOUR) * HOUR;
  return Array.from({ length: n }, (_, i) => {
    const e: ForecastEntry = {
      datetime: iso(start + i * HOUR), condition: i % 5 === 3 ? "rainy" : "partlycloudy", temperature: 12 + (i % 6), humidity: 70,
      cloud_coverage: (i * 17) % 100, precipitation: i % 5 === 3 ? 0.6 : 0, wind_speed: 14, wind_bearing: 250, uv_index: 1,
    };
    if (withProbability) e.precipitation_probability = (i * 9) % 100;
    return e;
  });
}

/** Met.no-shaped daily forecast: six days from today, entries stamped 11:00 UTC. */
export function dailyForecast(): ForecastEntry[] {
  return [8, 9, 10, 11, 12, 13].map((d, i) => ({
    datetime: `2026-10-${String(d).padStart(2, "0")}T11:00:00+00:00`, condition: ["cloudy", "rainy", "sunny", "partlycloudy", "pouring", "cloudy"][i] as string,
    temperature: 15 + i, templow: 8 + i, precipitation: i === 1 ? 4.2 : 0.3, wind_speed: 20, wind_bearing: 225, humidity: 70,
  }));
}

/** Hourly `change` rows of the total PV energy counter for 2026-10-08 up to 13:00 BST (ms starts, as the recorder returns). */
export function statRows(): StatRow[] {
  const day = Date.parse("2026-10-07T23:00:00Z");
  const vals = [0, 0, 0, 0, 0, 0, 0, 0.1, 0.4, 0.9, 1.4, 1.8, 2.1];
  return vals.map((v, h) => ({ start: day + h * HOUR, end: day + (h + 1) * HOUR, change: v }));
}
