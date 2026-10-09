// The pure model: configuration, parsing, time zones and DST, freshness, the blend (read, never recomputed), Solcast hourly
// detail, statistics bucketing, sun times (against the repository's Python NOAA implementation) and the insights.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DEFAULT_ENTITIES,
  HOUR_MS,
  accuracyView,
  actualSoFar,
  buildDayPoints,
  compass,
  condition,
  dateKey,
  daylightWeather,
  expectedSoFar,
  fmtAge,
  fmtDuration,
  fmtTime,
  forecastSolarFreshness,
  haTimeZone,
  hasRainProbability,
  hourKey,
  hourStartsOfDay,
  insights,
  nextDateKey,
  noaaSunTimes,
  normalizeConfig,
  parseTime,
  peakHour,
  solarTotals,
  solcastFreshness,
  solcastHourly,
  statisticsByHour,
  sunView,
  toNum,
  upcomingDays,
  upcomingHours,
  weatherByHour,
  weatherFreshness,
} from "../src/model.ts";
import { DEFAULT_STALE, DEFAULT_TITLES, LAYOUTS } from "../src/model.ts";
import { HA_CONFIG, NOW, TZ, bst, dailyForecast, hourlyForecast, solcastDay, statRows, states } from "./fixtures.ts";

const E = DEFAULT_ENTITIES;

describe("configuration", () => {
  it("defaults to the ECCO and integration default entity ids", () => {
    const c = normalizeConfig({ type: "custom:ecco-weather-solar-card" });
    assert.equal(c.entities.weather, "weather.forecast_home");
    assert.equal(c.entities.blend_today, "sensor.ecco_solar_forecast_today");
    assert.equal(c.entities.pv_energy_statistic, "sensor.ecco_clock_dongle_ecco_total_pv_energy");
    assert.equal(c.daily_days, 5);
    assert.equal(c.hourly_hours, 12);
    assert.deepEqual(c.stale, DEFAULT_STALE);
  });
  it("accepts entity overrides and refuses unknown keys or malformed ids", () => {
    const c = normalizeConfig({ entities: { weather: "weather.home", pv_power: "sensor.pv" }, daily_days: 3, stale: { solcast_hours: 30 } });
    assert.equal(c.entities.weather, "weather.home");
    assert.equal(c.entities.pv_power, "sensor.pv");
    assert.equal(c.daily_days, 3);
    assert.equal(c.stale.solcast_hours, 30);
    for (const bad of [null, [], "x", { entities: { nope: "sensor.x" } }, { entities: { weather: "sensor.x" } }, { entities: { pv_power: "Sensor X" } },
      { daily_days: 0 }, { daily_days: 8 }, { hourly_hours: 2.5 }, { show_accuracy: "yes" }, { stale: { weather_hours: -1 } }, { stale: { x: 1 } }, { colour: "red" }]) {
      assert.throws(() => normalizeConfig(bad), JSON.stringify(bad));
    }
  });
  it("layout: full by default; solar_strip and daily_compact are the two compact layouts; anything else is refused", () => {
    assert.deepEqual(LAYOUTS, ["full", "solar_strip", "daily_compact"]);
    assert.equal(normalizeConfig({ type: "custom:ecco-weather-solar-card" }).layout, "full");
    for (const l of LAYOUTS) assert.equal(normalizeConfig({ layout: l }).layout, l, "`layout` is a known key and every listed value is accepted");
    for (const bad of ["strip", "", "Full", "solar-strip", "compact", 1, null, true, ["full"], { full: true }]) {
      assert.throws(() => normalizeConfig({ layout: bad }), JSON.stringify(bad));
    }
    assert.throws(() => normalizeConfig({ layout: "solar_strip", colour: "red" }), "unknown keys are still refused beside a valid layout");
  });
  it("the default title follows the layout; a given title (even an empty one) is kept as is", () => {
    assert.deepEqual(DEFAULT_TITLES, { full: "Weather & Solar", solar_strip: "Solar forecast", daily_compact: "Next days" });
    assert.equal(normalizeConfig({}).title, "Weather & Solar");
    assert.equal(normalizeConfig({ layout: "full" }).title, "Weather & Solar");
    assert.equal(normalizeConfig({ layout: "solar_strip" }).title, "Solar forecast");
    assert.equal(normalizeConfig({ layout: "daily_compact" }).title, "Next days");
    assert.equal(normalizeConfig({ layout: "solar_strip", title: "" }).title, "");
    assert.equal(normalizeConfig({ layout: "daily_compact", title: "Week" }).title, "Week");
  });
  it("`layout: full` is the same configuration as no layout at all", () => {
    assert.deepEqual(normalizeConfig({ layout: "full", daily_days: 3 }), normalizeConfig({ daily_days: 3 }));
  });
});

describe("parsing", () => {
  it("never turns unknown / unavailable / text into a number", () => {
    for (const v of ["unknown", "unavailable", "", "none", "abc", "1.2.3", "12 kWh", null, undefined, NaN, Infinity, {}]) assert.equal(toNum(v), null, String(v));
    assert.equal(toNum("38.281"), 38.281);
    assert.equal(toNum(" 0 "), 0);
    assert.equal(toNum(-2.5), -2.5);
    assert.equal(toNum("1e3"), 1000);
  });
  it("parses ISO timestamps (with offsets) and epoch ms, and nothing else", () => {
    assert.equal(parseTime("2026-10-08T00:00:00+01:00"), Date.parse("2026-10-07T23:00:00Z"));
    assert.equal(parseTime(1000), 1000);
    for (const v of ["yesterday", "", "unknown", 0, -5, null]) assert.equal(parseTime(v), null, String(v));
  });
});

describe("time zones and DST", () => {
  it("uses the Home Assistant time zone, else UTC", () => {
    assert.equal(haTimeZone(HA_CONFIG), TZ);
    assert.equal(haTimeZone({ time_zone: "Not/AZone" }), "UTC");
    assert.equal(haTimeZone(null), "UTC");
  });
  it("buckets by the local day and hour of the installation, not UTC", () => {
    const t = Date.parse("2026-10-08T23:30:00Z"); // 00:30 BST on the 9th
    assert.equal(dateKey(t, TZ), "2026-10-09");
    assert.equal(hourKey(t, TZ), "2026-10-09T00");
    assert.equal(dateKey(t, "UTC"), "2026-10-08");
    assert.equal(fmtTime(t, TZ), "00:30");
    assert.equal(fmtTime(t, "America/New_York"), "19:30");
  });
  it("a local day has 24 hours, 23 on the spring change and 25 on the autumn change", () => {
    assert.equal(hourStartsOfDay("2026-10-08", TZ).length, 24);
    assert.equal(hourStartsOfDay("2026-03-29", TZ).length, 23);
    const autumn = hourStartsOfDay("2026-10-25", TZ);
    assert.equal(autumn.length, 25);
    assert.deepEqual(autumn.slice(0, 4).map((t) => fmtTime(t, TZ)), ["00:00", "01:00", "01:00", "02:00"]);
    assert.equal(hourStartsOfDay("2026-10-08", "UTC").length, 24);
  });
  it("the next local date is found across both DST changes", () => {
    assert.equal(nextDateKey("2026-10-24", TZ), "2026-10-25");
    assert.equal(nextDateKey("2026-10-25", TZ), "2026-10-26");
    assert.equal(nextDateKey("2026-03-28", TZ), "2026-03-29");
    assert.equal(nextDateKey("2026-12-31", TZ), "2027-01-01");
  });
  it("formats durations and ages", () => {
    assert.equal(fmtDuration(11 * HOUR_MS + 9 * 60000), "11 h 09 min");
    assert.equal(fmtDuration(45 * 60000), "45 min");
    assert.equal(fmtDuration(null), "--");
    assert.equal(fmtAge(30000), "just now");
    assert.equal(fmtAge(5 * 60000), "5 min ago");
    assert.equal(fmtAge(3 * HOUR_MS), "3 h ago");
    assert.equal(fmtAge(null), "update time unknown");
  });
});

describe("the ECCO blend is read, never recomputed", () => {
  it("shows the blend sensor's own value and the two source values it used", () => {
    const t = solarTotals(states(), E.blend_today, E.solcast_today, E.forecast_solar_today);
    assert.deepEqual(t, { blend: 20.5, solcast: 23, forecastSolar: 18, basis: "both" });
  });
  it("reports a single-source fallback from a null source attribute", () => {
    const s = states({ "sensor.ecco_solar_forecast_today": { state: "23.0", attributes: { forecast_solar_kwh: null, solcast_kwh: 23 } } });
    const t = solarTotals(s, E.blend_today, E.solcast_today, E.forecast_solar_today);
    assert.equal(t.basis, "solcast");
    assert.equal(t.forecastSolar, null);
    assert.equal(t.blend, 23);
  });
  it("an unavailable blend is null (never 0), whatever the sources say", () => {
    const s = states({ "sensor.ecco_solar_forecast_today": { state: "unavailable", attributes: {} } });
    const t = solarTotals(s, E.blend_today, E.solcast_today, E.forecast_solar_today);
    assert.equal(t.blend, null);
    assert.equal(t.basis, "none");
  });
  it("falls back to the provider sensors when the blend sensor carries no source attributes", () => {
    const s = states({ "sensor.ecco_solar_forecast_today": { state: "20.5", attributes: {} } });
    const t = solarTotals(s, E.blend_today, E.solcast_today, E.forecast_solar_today);
    assert.deepEqual([t.solcast, t.forecastSolar], [23, 18]);
    const missing = solarTotals({}, E.blend_today, E.solcast_today, E.forecast_solar_today);
    assert.deepEqual(missing, { blend: null, solcast: null, forecastSolar: null, basis: "none" });
  });
});

describe("Solcast hourly detail", () => {
  it("reads detailedHourly (kWh per hour) keyed by local hour; the hours sum to the daily total", () => {
    const m = solcastHourly(states()["sensor.solcast_pv_forecast_forecast_today"], TZ);
    assert.equal(m.size, 24);
    assert.ok(Math.abs([...m.values()].reduce((a, h) => a + h.estimate, 0) - 23) < 0.01);
    const one = m.get("2026-10-08T13")!;
    assert.equal(one.start, Date.parse("2026-10-08T12:00:00Z"));
    assert.ok(one.p10! < one.estimate && one.estimate < one.p90!);
  });
  it("folds half-hourly detailedForecast (kW averages) into hours when there is no hourly detail", () => {
    const e = { state: "2", attributes: { detailedForecast: [
      { period_start: bst(2026, 10, 8, 12, 0), pv_estimate: 2, pv_estimate10: 1, pv_estimate90: 3 },
      { period_start: bst(2026, 10, 8, 12, 30), pv_estimate: 4, pv_estimate10: 2, pv_estimate90: 6 },
    ] } };
    const h = solcastHourly(e, TZ).get("2026-10-08T12")!;
    assert.deepEqual([h.estimate, h.p10, h.p90], [3, 1.5, 4.5]);
    assert.equal(h.start, Date.parse("2026-10-08T11:00:00Z"));
  });
  it("skips malformed rows and copes with no attributes", () => {
    const e = { state: "1", attributes: { detailedHourly: [null, 5, { period_start: "x", pv_estimate: 1 }, { period_start: bst(2026, 10, 8, 9), pv_estimate: "n/a" },
      { period_start: bst(2026, 10, 8, 10), pv_estimate: -1 }, { period_start: bst(2026, 10, 8, 11), pv_estimate: 1.5 }] } };
    const m = solcastHourly(e, TZ);
    assert.deepEqual([...m.keys()], ["2026-10-08T11"]);
    assert.equal(m.get("2026-10-08T11")!.p10, null);
    assert.equal(solcastHourly(undefined, TZ).size, 0);
    assert.equal(solcastHourly({ state: "1" }, TZ).size, 0);
  });
});

describe("hourly actual PV from long-term statistics", () => {
  it("buckets `change` rows by local hour; negative (counter reset) and non-numeric rows are dropped", () => {
    const rows = [...statRows(), { start: Date.parse("2026-10-08T13:00:00Z"), change: -11 }, { start: "2026-10-08T14:00:00+00:00", change: null },
      { start: "2026-10-08T15:00:00+00:00", change: 0.7 }];
    const m = statisticsByHour(rows, TZ);
    assert.equal(m.get("2026-10-08T12"), 2.1, "the 12:00-13:00 BST hour (the current 13:00 hour is not complete yet)");
    assert.equal(m.get("2026-10-08T00"), 0);
    assert.equal(m.has("2026-10-08T14"), false);
    assert.equal(m.has("2026-10-08T15"), false);
    assert.equal(m.get("2026-10-08T16"), 0.7);
    assert.equal(statisticsByHour(null, TZ).size, 0);
  });
});

describe("day points, progress and peak", () => {
  const sc = solcastHourly(states()["sensor.solcast_pv_forecast_forecast_today"], TZ);
  const actual = statisticsByHour(statRows(), TZ);
  const w = weatherByHour(hourlyForecast(Date.parse("2026-10-08T00:00:00Z"), 48), TZ);
  const pts = buildDayPoints("2026-10-08", TZ, sc, actual, w);
  it("one point per local hour with forecast, actual, cloud and rain", () => {
    assert.equal(pts.length, 24);
    const p = pts.find((x) => x.key === "2026-10-08T12")!;
    assert.equal(p.actual, 2.1);
    assert.equal(pts.find((x) => x.key === "2026-10-08T13")!.actual, null, "the current hour has no completed statistics row");
    assert.ok(p.solcast! > 2);
    assert.notEqual(p.cloud, null);
    assert.equal(pts.find((x) => x.key === "2026-10-08T20")!.actual, null, "no statistics row = unknown, not 0");
  });
  it("expected-so-far counts whole past hours and the current hour pro rata", () => {
    const exp = expectedSoFar(pts, NOW)!;
    const byHand = pts.filter((p) => p.start + HOUR_MS <= NOW).reduce((a, p) => a + (p.solcast ?? 0), 0) + pts.find((p) => p.key === "2026-10-08T13")!.solcast! * 0.5;
    assert.ok(Math.abs(exp - byHand) < 1e-9);
    assert.ok(Math.abs(actualSoFar(pts)! - 6.7) < 1e-9);
    assert.equal(expectedSoFar([], NOW), null);
  });
  it("finds the Solcast peak hour", () => {
    assert.equal(peakHour(pts)!.key, "2026-10-08T13");
  });
  it("daylight weather: mean cloud and total rain over hours Solcast expects generation", () => {
    const dw = daylightWeather(pts);
    assert.equal(dw.hours, 12);
    assert.ok(dw.cloud! >= 0 && dw.cloud! <= 100);
    assert.ok(dw.rain! > 0);
  });
});

describe("freshness", () => {
  const cfgStale = DEFAULT_STALE;
  it("Solcast uses its API-last-polled timestamp", () => {
    const f = solcastFreshness(states(), E, NOW, cfgStale);
    assert.equal(f.status, "fresh");
    assert.equal(f.ageMs, 2 * HOUR_MS);
    const old = solcastFreshness(states({ "sensor.solcast_pv_forecast_api_last_polled": { state: new Date(NOW - 30 * HOUR_MS).toISOString() } }), E, NOW, cfgStale);
    assert.equal(old.status, "stale");
  });
  it("falls back to the provider sensors' update time and is unknown when nothing is readable", () => {
    const s = states({ "sensor.solcast_pv_forecast_api_last_polled": undefined });
    assert.equal(solcastFreshness(s, E, NOW, cfgStale).detail, "newest sensor update");
    assert.equal(solcastFreshness({}, E, NOW, cfgStale).status, "unknown");
  });
  it("Forecast.Solar is judged by its own sensors, never by the 5-minute ECCO blend re-sample", () => {
    const f = forecastSolarFreshness(states(), E, NOW, cfgStale);
    assert.equal(f.ageMs, 25 * 60000);
    const s = states({
      "sensor.energy_production_today": { state: "18", last_updated: new Date(NOW - 9 * HOUR_MS).toISOString() },
      "sensor.energy_production_today_remaining": { state: "unavailable", last_updated: new Date(NOW).toISOString() },
      "sensor.energy_production_tomorrow": { state: "12", last_updated: new Date(NOW - 8 * HOUR_MS).toISOString() },
    });
    assert.equal(forecastSolarFreshness(s, E, NOW, cfgStale).status, "stale", "an unavailable sensor's fresh timestamp does not count");
  });
  it("the weather forecast is stale when its first hour is far in the past", () => {
    assert.equal(weatherFreshness(states(), E, hourlyForecast(NOW, 24), NOW, cfgStale).status, "fresh");
    assert.equal(weatherFreshness(states(), E, hourlyForecast(NOW - 6 * HOUR_MS, 24), NOW, cfgStale).status, "stale");
    assert.equal(weatherFreshness({}, E, null, NOW, cfgStale).status, "unknown");
  });
});

describe("sun times", () => {
  it("the NOAA port matches intelligence/timeutil.py sun_times() to the second", () => {
    // Reference values printed by intelligence/timeutil.py sun_times(date, 51.5072, -0.1276) (and New York for a western zone).
    const ref: Array<[string, number, number, string, string]> = [
      ["2026-10-08", 51.5072, -0.1276, "2026-10-08T06:12:51.750Z", "2026-10-08T17:22:50.611Z"],
      ["2026-06-21", 51.5072, -0.1276, "2026-06-21T03:43:07.516Z", "2026-06-21T20:21:29.905Z"],
      ["2026-12-21", 51.5072, -0.1276, "2026-12-21T08:03:57.729Z", "2026-12-21T15:53:26.580Z"],
      ["2026-03-29", 51.5072, -0.1276, "2026-03-29T05:41:58.932Z", "2026-03-29T18:28:10.233Z"],
      ["2026-10-25", 51.5072, -0.1276, "2026-10-25T06:41:56.304Z", "2026-10-25T16:46:55.916Z"],
      ["2026-10-08", 40.7128, -74.006, "2026-10-08T10:59:56.290Z", "2026-10-08T22:26:40.697Z"],
    ];
    for (const [d, lat, lon, rise, set] of ref) {
      const r = noaaSunTimes(d, lat, lon)!;
      assert.ok(Math.abs(r.rise - Date.parse(rise)) < 1000, `${d} rise`);
      assert.ok(Math.abs(r.set - Date.parse(set)) < 1000, `${d} set`);
    }
    assert.equal(noaaSunTimes("2026-06-21", 78.22, 15.65), null, "polar day");
    assert.equal(noaaSunTimes("bad", 51, 0), null);
  });
  it("daytime: sunset from the Sun integration, the already-passed sunrise calculated", () => {
    const s = sunView(states(), E.sun, HA_CONFIG, NOW, TZ);
    assert.equal(s.phase, "day");
    assert.equal(s.sunsetSource, "home_assistant");
    assert.equal(s.sunset, Date.parse("2026-10-08T17:22:40Z"));
    assert.equal(s.sunriseSource, "calculated");
    assert.ok(Math.abs(s.sunrise! - Date.parse("2026-10-08T06:12:51.750Z")) < 1000);
    assert.equal(s.remainingMs, Date.parse("2026-10-08T17:22:40Z") - NOW);
    assert.ok(s.daylightMs! > 11 * HOUR_MS && s.daylightMs! < 11.25 * HOUR_MS);
    assert.equal(s.aboveHorizon, true);
  });
  it("before sunrise both events come from the Sun integration", () => {
    const early = Date.parse("2026-10-08T04:00:00Z");
    const st = states({ "sun.sun": { state: "below_horizon", attributes: { next_rising: "2026-10-08T06:12:40+00:00", next_setting: "2026-10-08T17:22:40+00:00" } } });
    const s = sunView(st, E.sun, HA_CONFIG, early, TZ);
    assert.equal(s.phase, "before_sunrise");
    assert.deepEqual([s.sunriseSource, s.sunsetSource], ["home_assistant", "home_assistant"]);
    assert.equal(s.remainingMs, s.daylightMs);
  });
  it("after sunset: no daylight left, tomorrow's sunrise from the Sun integration", () => {
    const late = Date.parse("2026-10-08T20:00:00Z");
    const st = states({ "sun.sun": { state: "below_horizon", attributes: { next_rising: "2026-10-09T06:14:30+00:00", next_setting: "2026-10-09T17:20:30+00:00" } } });
    const s = sunView(st, E.sun, HA_CONFIG, late, TZ);
    assert.equal(s.phase, "after_sunset");
    assert.equal(s.remainingMs, 0);
    assert.equal(s.nextSunrise, Date.parse("2026-10-09T06:14:30Z"));
    assert.deepEqual([s.sunriseSource, s.sunsetSource], ["calculated", "calculated"]);
  });
  it("without location data only the Sun integration's events are shown; without either it is unavailable", () => {
    const s = sunView(states(), E.sun, null, NOW, TZ);
    assert.equal(s.sunrise, null);
    assert.equal(s.sunsetSource, "home_assistant");
    assert.equal(s.daylightMs, null);
    assert.equal(sunView({}, E.sun, null, NOW, TZ).available, false);
  });
});

describe("weather helpers", () => {
  it("maps every Home Assistant condition to a label and icon, unknown ones to Unknown", () => {
    assert.deepEqual(condition("partlycloudy"), { label: "Partly cloudy", icon: "mdi:weather-partly-cloudy" });
    assert.equal(condition("lava").label, "Unknown");
    assert.equal(condition(undefined).label, "Unknown");
  });
  it("compass points", () => {
    assert.equal(compass(0), "N");
    assert.equal(compass(247.8), "WSW");
    assert.equal(compass(359), "N");
    assert.equal(compass("sw"), "SW");
    assert.equal(compass("unknown"), "--");
  });
  it("upcoming hours start at the current hour; upcoming days at local today", () => {
    const h = upcomingHours(hourlyForecast(NOW - 3 * HOUR_MS, 30), NOW, 12);
    assert.equal(h.length, 12);
    assert.equal(h[0]!.datetime, new Date(Math.floor(NOW / HOUR_MS) * HOUR_MS).toISOString());
    const d = upcomingDays(dailyForecast(), NOW, 5, TZ);
    assert.equal(d.length, 5);
    assert.equal(d[0]!.datetime.slice(0, 10), "2026-10-08");
    assert.deepEqual(upcomingDays(dailyForecast(), Date.parse("2026-10-10T12:00:00Z"), 5, TZ).map((x) => x.datetime.slice(8, 10)), ["10", "11", "12", "13"]);
    assert.deepEqual(upcomingHours(null, NOW, 5), []);
  });
  it("rain probability is optional (Met.no has none)", () => {
    assert.equal(hasRainProbability(hourlyForecast(NOW, 5)), false);
    assert.equal(hasRainProbability(hourlyForecast(NOW, 5, true)), true);
  });
});

describe("accuracy and insights", () => {
  it("reads the existing ECCO scorecard as is", () => {
    const a = accuracyView(states(), E);
    assert.equal(a.available, true);
    assert.equal(a.bestSource, "Forecast.Solar");
    assert.equal(a.learningDays, 23);
    assert.equal(a.scoredDate, "2026-10-07");
    assert.deepEqual(a.rows.map((r) => [r.source, r.mae, r.error, r.errorPct]), [
      ["Blend", 9.344, 5.646, 125.5], ["Solcast", 13.359, 2.686, 59.7], ["Forecast.Solar", 6.951, 8.606, 191.2]]);
    assert.equal(accuracyView({}, E).available, false);
  });
  it("produces factual notes: disagreement, progress, peak, tomorrow's cloud, the best source", () => {
    const st = states();
    const sc = solcastHourly(st["sensor.solcast_pv_forecast_forecast_today"], TZ);
    const sc2 = solcastHourly(st["sensor.solcast_pv_forecast_forecast_tomorrow"], TZ);
    const w = weatherByHour(hourlyForecast(Date.parse("2026-10-08T00:00:00Z"), 48), TZ);
    const today = solarTotals(st, E.blend_today, E.solcast_today, E.forecast_solar_today);
    const tomorrow = solarTotals(st, E.blend_tomorrow, E.solcast_tomorrow, E.forecast_solar_tomorrow);
    const out = insights({
      today, tomorrow, now: NOW, tz: TZ, accuracy: accuracyView(st, E), pvToday: 9.8,
      todayPoints: buildDayPoints("2026-10-08", TZ, sc, new Map(), w), tomorrowPoints: buildDayPoints("2026-10-09", TZ, sc2, new Map(), w),
    });
    assert.ok(out.some((s) => s.startsWith("So far today: 9.8 kWh generated")), out.join("\n"));
    assert.ok(out.some((s) => s.startsWith("Tomorrow's Solcast peak is")));
    assert.ok(out.some((s) => s.startsWith("Tomorrow's daylight hours average")));
    assert.ok(out.some((s) => s.startsWith("Over 23 scored days Forecast.Solar has been most accurate")));
    assert.ok(!out.some((s) => s.includes("disagree")), "18 vs 23 is within 30%");
    const far = { blend: 15, solcast: 25, forecastSolar: 5, basis: "both" as const };
    const out2 = insights({ today: far, tomorrow, now: NOW, tz: TZ, accuracy: accuracyView({}, E), pvToday: null, todayPoints: [], tomorrowPoints: [] });
    assert.ok(out2.some((s) => s.includes("disagree by 20.0 kWh (Solcast is higher)")));
    const single = { blend: 23, solcast: 23, forecastSolar: null, basis: "solcast" as const };
    const out3 = insights({ today: single, tomorrow: single, now: NOW, tz: TZ, accuracy: accuracyView({}, E), pvToday: null, todayPoints: [], tomorrowPoints: [] });
    assert.ok(out3.some((s) => s === "Today: the ECCO blend is using Solcast only (the other source is unavailable)."));
    for (const s of [...out, ...out2, ...out3]) assert.ok(!/\b(should|turn on|switch|charge now|export now)\b/i.test(s), `explanatory only: ${s}`);
  });
  it("never claims progress without both a profile and an actual", () => {
    const st = states();
    const t = solarTotals(st, E.blend_today, E.solcast_today, E.forecast_solar_today);
    const out = insights({ today: t, tomorrow: t, now: NOW, tz: TZ, accuracy: accuracyView({}, E), pvToday: null, todayPoints: [], tomorrowPoints: [] });
    assert.ok(!out.some((s) => s.startsWith("So far today")));
  });
});

describe("fixture sanity", () => {
  it("the synthetic Solcast day totals its state", () => {
    assert.ok(Math.abs(solcastDay(2026, 10, 9, 10).reduce((a, r) => a + (r.pv_estimate as number), 0) - 10) < 0.01);
  });
});
