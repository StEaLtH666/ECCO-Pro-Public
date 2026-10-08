// Rendering: every Home Assistant string is escaped, unknown values show "--" or a plain message (never 0), the chart
// shows what exists and says what is missing, and the only interactive element is the Today / Tomorrow switch.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DEFAULT_ENTITIES, accuracyView, buildDayPoints, solarTotals, solcastHourly, statisticsByHour, sunView, weatherByHour } from "../src/model.ts";
import {
  esc,
  niceAxis,
  renderAccuracy,
  renderChart,
  renderDaily,
  renderFreshness,
  renderHourly,
  renderInsights,
  renderNow,
  renderShell,
  renderSolar,
  renderSun,
} from "../src/render.ts";
import type { CurrentWeather } from "../src/render.ts";
import { HA_CONFIG, NOW, TZ, dailyForecast, hourlyForecast, statRows, states } from "./fixtures.ts";

const E = DEFAULT_ENTITIES;
const XSS = `<img src=x onerror="alert(1)">'&`;

const current = (over: Partial<CurrentWeather> = {}): CurrentWeather => ({
  found: true, entityId: E.weather, condition: "partlycloudy", temperature: 14.2, temperatureUnit: "°C", humidity: 71, windSpeed: 12.6,
  windUnit: "km/h", windBearing: 250, cloud: 48.5, pressure: 1018.4, pressureUnit: "hPa", rainThisHour: 0.2, rainUnit: "mm", uv: 2.1, ...over,
});

function points(day: "2026-10-08" | "2026-10-09", withActual = true) {
  const st = states();
  const sc = solcastHourly(st[day === "2026-10-08" ? E.solcast_today : E.solcast_tomorrow], TZ);
  const w = weatherByHour(hourlyForecast(Date.parse("2026-10-08T00:00:00Z"), 48), TZ);
  return buildDayPoints(day, TZ, sc, withActual ? statisticsByHour(statRows(), TZ) : new Map(), w);
}

describe("escaping", () => {
  it("esc() neutralises markup", () => {
    assert.equal(esc(XSS), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&amp;");
  });
  it("no Home Assistant string reaches the HTML unescaped", () => {
    const html = [
      renderShell(XSS, ""),
      renderNow(current({ condition: XSS, temperatureUnit: XSS, windUnit: XSS })),
      renderNow(current({ found: false, entityId: XSS })),
      renderHourly({ entries: [{ datetime: "2026-10-08T12:00:00Z", condition: XSS }], tz: TZ, error: null, loading: false, tempUnit: "°C", windUnit: "km/h", rainUnit: "mm" }),
      renderHourly({ entries: [], tz: TZ, error: XSS, loading: false, tempUnit: "°C", windUnit: "km/h", rainUnit: "mm" }),
      renderInsights([XSS], true),
      renderFreshness([{ label: XSS, status: "stale", ageMs: 1, detail: XSS }]),
      renderChart({ day: "today", points: [], now: NOW, tz: TZ, solcastNote: XSS, actualNote: XSS, fsCurrentHour: null, fsNextHour: null, sunrise: null, sunset: null }),
    ].join("");
    assert.ok(!html.includes("<img"), "raw markup leaked");
    assert.ok(!html.includes('onerror="'), "raw attribute leaked");
  });
});

describe("unavailable data", () => {
  it("unknown weather values show --, a missing entity shows a message", () => {
    const html = renderNow(current({ temperature: null, humidity: null, windSpeed: null, cloud: null, pressure: null, rainThisHour: null, uv: null }));
    assert.ok(html.includes('<div class="temp">--</div>'));
    assert.equal((html.match(/<dd>--<\/dd>/g) ?? []).length, 6);
    assert.ok(renderNow(current({ found: false })).includes("weather.forecast_home not found or unavailable"));
  });
  it("blend totals: unknown is --, never 0, and a single-source fallback is labelled", () => {
    const html = renderSolar({
      today: { blend: null, solcast: null, forecastSolar: null, basis: "none" },
      remaining: { blend: 0, solcast: 0, forecastSolar: 0, basis: "both" },
      tomorrow: { blend: 10, solcast: 10, forecastSolar: null, basis: "solcast" },
      pvToday: null,
      pvNow: null,
    });
    assert.ok(html.includes('<div class="big blend">--</div>'));
    assert.ok(html.includes('<div class="big blend">0.0 kWh</div>'), "a real zero is shown as zero");
    assert.ok(html.includes("Solcast only"));
    assert.ok(html.includes("unavailable"));
    assert.ok(html.includes("Generated today -- - PV now --"));
  });
  it("forecast lists: loading, error and empty states", () => {
    const base = { tz: TZ, tempUnit: "°C", windUnit: "km/h", rainUnit: "mm" };
    assert.ok(renderHourly({ ...base, entries: [], error: null, loading: true }).includes("Loading hourly forecast"));
    assert.ok(renderHourly({ ...base, entries: [], error: "not_found", loading: false }).includes("Hourly forecast unavailable: not_found"));
    assert.ok(renderDaily({ ...base, entries: [], error: null, loading: false }).includes("Daily forecast unavailable."));
  });
  it("sun: unavailable without data; calculated events are marked", () => {
    assert.ok(renderSun(sunView({}, E.sun, null, NOW, TZ), NOW, TZ).includes("Sun times unavailable"));
    const html = renderSun(sunView(states(), E.sun, HA_CONFIG, NOW, TZ), NOW, TZ);
    assert.ok(html.includes("18:22"), "sunset 17:22 UTC shown in BST");
    assert.equal((html.match(/class="calc"/g) ?? []).length, 1, "the passed sunrise is calculated, the sunset is not");
    assert.ok(html.includes("Daylight left"));
  });
  it("accuracy and insights sections can be switched off and say when there is nothing", () => {
    assert.equal(renderAccuracy(accuracyView(states(), E), false), "");
    assert.ok(renderAccuracy(accuracyView({}, E), true).includes("No scored days yet"));
    assert.equal(renderInsights(["x"], false), "");
    assert.ok(renderInsights([], true).includes("Nothing notable"));
  });
});

describe("hourly solar chart", () => {
  it("today: actual bars, Solcast line and P10-P90 band, now marker, Forecast.Solar this / next hour, cloud and rain", () => {
    const html = renderChart({ day: "today", points: points("2026-10-08"), now: NOW, tz: TZ, solcastNote: null, actualNote: null, fsCurrentHour: 2.1, fsNextHour: 1.8, sunrise: null, sunset: null });
    assert.ok(html.includes("<svg"));
    assert.equal((html.match(/class="act"/g) ?? []).length, 7, "hours 06-12 have statistics rows (06 is a real 0 kWh, drawn as a zero bar)");
    assert.ok(html.includes("06:00 actual 0.00 kWh"), "a real zero is drawn, not omitted");
    assert.ok(html.includes('class="band"'));
    assert.ok(html.includes('class="sc-l"'));
    assert.ok(html.includes('class="nowl"'));
    assert.equal((html.match(/class="fs-m"/g) ?? []).length, 2);
    assert.ok(html.includes('class="cloud"'));
    assert.ok(html.includes('class="rain"'));
    assert.ok(html.includes("12:00 actual 2.10 kWh"));
    assert.ok(html.includes("Forecast.Solar and the ECCO blend are daily totals"));
    assert.ok(html.includes('aria-selected="true" class="on">Today'));
  });
  it("tomorrow: forecast only, no now marker and no Forecast.Solar hour markers", () => {
    const html = renderChart({ day: "tomorrow", points: points("2026-10-09", false), now: NOW, tz: TZ, solcastNote: null, actualNote: null, fsCurrentHour: 2.1, fsNextHour: 1.8, sunrise: null, sunset: null });
    assert.ok(!html.includes('class="act"'));
    assert.ok(!html.includes('class="nowl"'));
    assert.ok(!html.includes('class="fs-m"'));
    assert.ok(html.includes('aria-selected="true" class="on">Tomorrow'));
  });
  it("without data the chart says why instead of drawing zeros", () => {
    const empty = points("2026-10-08").map((p) => ({ ...p, solcast: null, p10: null, p90: null, actual: null }));
    const html = renderChart({ day: "today", points: empty, now: NOW, tz: TZ, solcastNote: "Solcast hourly detail is not available", actualNote: "Actual PV history unavailable: x", fsCurrentHour: null, fsNextHour: null, sunrise: null, sunset: null });
    assert.ok(!html.includes("<svg"));
    assert.ok(html.includes("Solcast hourly detail is not available"));
    assert.ok(html.includes("Actual PV history unavailable: x"));
  });
  it("axis ticks are round steps (1, 2, 2.5, 5 x 10^n) and cover the data", () => {
    for (const [v, step, max] of [[4.1, 2, 6], [5.25, 2, 6], [3.0, 1, 3], [7.3, 2, 8], [0.3, 0.1, 0.4], [14.7, 5, 15], [0, 0.1, 0.4]] as Array<[number, number, number]>) {
      const a = niceAxis(v);
      assert.ok(Math.abs(a.step - step) < 1e-9 && Math.abs(a.max - max) < 1e-9, `${v}: ${JSON.stringify(a)}`);
      assert.ok(a.max >= v);
    }
    const html = renderChart({ day: "today", points: points("2026-10-08"), now: NOW, tz: TZ, solcastNote: null, actualNote: null, fsCurrentHour: null, fsNextHour: null, sunrise: null, sunset: null });
    const labels = [...html.matchAll(/text-anchor="end">([\d.]+)<\/text>/g)].map((m) => Number(m[1]));
    assert.ok(labels.length >= 3 && labels.every((x) => Math.abs(x * 4 - Math.round(x * 4)) < 1e-9), `round ticks: ${labels}`);
  });
  it("the y axis scales to the data", () => {
    const pts = points("2026-10-08").map((p) => ({ ...p, solcast: p.solcast === null ? null : p.solcast * 4, p90: p.p90 === null ? null : p.p90 * 4 }));
    const html = renderChart({ day: "tomorrow", points: pts, now: NOW, tz: TZ, solcastNote: null, actualNote: null, fsCurrentHour: null, fsNextHour: null, sunrise: null, sunset: null });
    assert.ok(/>10<\/text>/.test(html), "axis reaches the scaled maximum");
  });
});

describe("weather lists", () => {
  it("hourly cells show time, temperature, rain, cloud and wind; the rain-probability column appears only when supplied", () => {
    const base = { tz: TZ, error: null, loading: false, tempUnit: "°C", windUnit: "km/h", rainUnit: "mm" };
    const metno = renderHourly({ ...base, entries: hourlyForecast(NOW, 12) });
    assert.equal((metno.match(/class="hc"/g) ?? []).length, 12);
    assert.ok(metno.includes("13:00"), "first cell is the current local hour");
    assert.ok(metno.includes("cloud"));
    assert.ok(metno.includes("provides no rain probability"));
    const withProb = renderHourly({ ...base, entries: hourlyForecast(NOW, 12, true) });
    assert.ok(!withProb.includes("provides no rain probability"));
    assert.ok(/\d+%<\/div>|<br>\d+%/.test(withProb));
  });
  it("daily rows: weekday in the installation's time zone, high / low, rain", () => {
    const html = renderDaily({ entries: dailyForecast().slice(0, 5), tz: TZ, error: null, loading: false, tempUnit: "°C", windUnit: "km/h", rainUnit: "mm" });
    assert.equal((html.match(/class="dr"/g) ?? []).length, 5);
    assert.ok(html.includes('<span class="d">Thu</span>'));
    assert.ok(html.includes("15°C / 8°C"));
    assert.ok(html.includes("4.2 mm"));
  });
});

describe("accuracy", () => {
  it("lists the three sources with MAE and the last scored day, highlighting the best", () => {
    const html = renderAccuracy(accuracyView(states(), E), true);
    assert.ok(html.includes('<tr class="best"><th scope="row">Forecast.Solar</th>'));
    assert.ok(html.includes("+5.6 kWh"));
    assert.ok(html.includes("(+126%)"));
    assert.ok(html.includes("2026-10-07"));
    assert.ok(html.includes("weighting is fixed at 50/50"));
  });
});

describe("the only interactive element", () => {
  it("is the Today / Tomorrow switch", () => {
    const all = [
      renderChart({ day: "today", points: points("2026-10-08"), now: NOW, tz: TZ, solcastNote: null, actualNote: null, fsCurrentHour: 1, fsNextHour: 1, sunrise: null, sunset: null }),
      renderNow(current()), renderSolar({ today: solarTotals(states(), E.blend_today, E.solcast_today, E.forecast_solar_today), remaining: solarTotals(states(), E.blend_remaining, E.solcast_remaining, E.forecast_solar_remaining), tomorrow: solarTotals(states(), E.blend_tomorrow, E.solcast_tomorrow, E.forecast_solar_tomorrow), pvToday: 9.8, pvNow: 2350 }),
      renderAccuracy(accuracyView(states(), E), true),
    ].join("");
    assert.deepEqual([...new Set([...all.matchAll(/data-action="([a-z-]+)"/g)].map((m) => m[1]))], ["chart-day"]);
    assert.equal((all.match(/<button /g) ?? []).length, 2);
    assert.ok(!/<(?:input|select|form|a )/.test(all));
  });
});
