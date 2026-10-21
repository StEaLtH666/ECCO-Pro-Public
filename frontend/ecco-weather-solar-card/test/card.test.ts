// The custom element through a recording DOM / Home Assistant stand-in: registration, the exact websocket messages it sends
// (two forecast subscriptions and one throttled statistics query - nothing else), subscription lifecycle, refresh, errors
// and fallbacks, the Today / Tomorrow switch, the compact list's day breakdown (its hourly subscription exists only while a
// day is open), no timers, and that neither the hass object nor its connection is kept.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { fakeConnection, installDomShim, makeEl, newRecorder, recordingHass } from "./dom-shim.ts";
import type { FakeRoot, Recorder } from "./dom-shim.ts";
import { HA_CONFIG, HOUR, NOW, dailyFor, dailyForecast, hourlyForecast, statRows, states } from "./fixtures.ts";
import type { StatesLike } from "../src/types.ts";

const shim = installDomShim();
const mod = await import("../src/ecco-weather-solar-card.ts");
const { CARD_TAG, EccoWeatherSolarCard, STATS_REFRESH_MS, FORECAST_RETRY_MS } = mod;
const STAT_ID = "sensor.ecco_clock_dongle_ecco_total_pv_energy";

const flush = async (): Promise<void> => {
  for (let i = 0; i < 8; i++) await Promise.resolve();
};

interface Rig {
  card: InstanceType<typeof EccoWeatherSolarCard>;
  root: FakeRoot;
  rec: Recorder;
  clock: { t: number };
  push(st?: StatesLike): unknown;
  conn: ReturnType<typeof fakeConnection>;
}

function rig(opts: Parameters<typeof fakeConnection>[1] = { statistics: { [STAT_ID]: statRows() } }, config: Record<string, unknown> = {}): Rig {
  const rec = newRecorder();
  const conn = fakeConnection(rec, opts);
  const card = new EccoWeatherSolarCard();
  const clock = { t: NOW };
  card.now = () => clock.t;
  card.setConfig({ type: `custom:${CARD_TAG}`, ...config });
  const push = (st: StatesLike = states()): unknown => {
    const h = recordingHass(st, rec, conn, HA_CONFIG);
    (card as unknown as { hass: unknown }).hass = h;
    return h;
  };
  return { card, root: card.shadowRoot as unknown as FakeRoot, rec, clock, push, conn };
}

const forecastMsgs = (rec: Recorder) => rec.messages.filter((m) => m.type === "weather/subscribe_forecast");
const statMsgs = (rec: Recorder) => rec.messages.filter((m) => m.type === "recorder/statistics_during_period");

describe("registration", () => {
  it("defines the element once and announces it to the card picker", () => {
    assert.equal(shim.defined.get(CARD_TAG), EccoWeatherSolarCard);
    assert.equal(shim.window.customCards?.filter((c) => c.type === CARD_TAG).length, 1);
    assert.deepEqual(EccoWeatherSolarCard.getStubConfig(), {});
    const c = new EccoWeatherSolarCard();
    assert.ok(c.getCardSize() > 0);
    assert.deepEqual(c.getGridOptions(), { columns: 12, rows: "auto", min_columns: 6 });
  });
  it("rejects a bad configuration (Home Assistant shows its error card)", () => {
    assert.throws(() => new EccoWeatherSolarCard().setConfig({ entities: { weather: "sensor.x" } }));
  });
});

describe("the websocket messages: exactly two subscriptions and one statistics query", () => {
  it("subscribes to the hourly and daily forecast and asks for hourly PV statistics, with the exact messages", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.deepEqual(forecastMsgs(r.rec), [
      { type: "weather/subscribe_forecast", entity_id: "weather.forecast_home", forecast_type: "hourly" },
      { type: "weather/subscribe_forecast", entity_id: "weather.forecast_home", forecast_type: "daily" },
    ]);
    const s = statMsgs(r.rec);
    assert.equal(s.length, 1);
    assert.deepEqual(Object.keys(s[0]!).sort(), ["end_time", "period", "start_time", "statistic_ids", "type", "types", "units"]);
    assert.deepEqual([s[0]!.statistic_ids, s[0]!.period, s[0]!.types, s[0]!.units], [[STAT_ID], "hour", ["change"], { energy: "kWh" }]);
    assert.equal(s[0]!.end_time, new Date(NOW).toISOString());
    assert.ok(Date.parse(s[0]!.start_time as string) <= NOW - 47 * HOUR);
    assert.equal(r.rec.messages.length, 3, "nothing else was sent");
    assert.deepEqual(r.rec.calls, [], "no service / API call, no write, no network");
  });
  it("works whichever comes first: hass or connectedCallback", async () => {
    const r = rig();
    r.push();
    r.card.connectedCallback();
    await flush();
    assert.equal(forecastMsgs(r.rec).length, 2);
    assert.equal(statMsgs(r.rec).length, 1);
  });
  it("attached before the first hass update: shows loading, not a connection error", async () => {
    const r = rig();
    r.card.connectedCallback();
    await flush();
    assert.ok(r.root.region("hourly").includes("Loading hourly forecast"), r.root.region("hourly"));
    r.push();
    await flush();
    assert.equal(forecastMsgs(r.rec).length, 2);
  });
  it("sends nothing until the card is on the page", async () => {
    const r = rig();
    r.push();
    await flush();
    assert.equal(r.rec.messages.length, 0);
  });
});

describe("rendering the data", () => {
  it("forecast events fill the hourly and daily lists; statistics fill the chart", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.ok(r.root.region("hourly").includes("Loading hourly forecast"));
    const [hourly, daily] = r.rec.subscriptions;
    hourly!.callback({ type: "hourly", forecast: hourlyForecast(NOW, 48) });
    daily!.callback({ type: "daily", forecast: dailyForecast() });
    assert.equal((r.root.region("hourly").match(/class="hc"/g) ?? []).length, 12);
    assert.equal((r.root.region("daily").match(/class="dr"/g) ?? []).length, 5);
    assert.ok(r.root.region("chart").includes("12:00 actual 2.10 kWh"));
    assert.ok(r.root.region("solar").includes("20.5 kWh"));
    assert.ok(r.root.region("now").includes("Partly cloudy"));
    assert.ok(r.root.region("sun").includes("Daylight left"));
    assert.ok(r.root.region("accuracy").includes("Forecast.Solar"));
    assert.ok(r.root.region("insights").includes("So far today"));
    assert.ok(r.root.region("fresh").includes("Solcast: 2 h ago"));
  });
  it("an identical update within the same minute rewrites nothing", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    const before = r.root.region("solar");
    const writes = (r.root.regions.get("solar") as unknown as { writes: number }).writes;
    r.push();
    r.push();
    assert.equal((r.root.regions.get("solar") as unknown as { writes: number }).writes, writes);
    assert.equal(r.root.region("solar"), before);
  });
  it("the Today / Tomorrow switch changes only the chart view; anything else is ignored", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    r.root.dispatch("click", makeEl({ "data-action": "chart-day", "data-day": "tomorrow" }));
    assert.ok(r.root.region("chart").includes('aria-selected="true" class="on">Tomorrow'));
    r.root.dispatch("click", makeEl({ "data-action": "chart-day", "data-day": "yesterday" }));
    r.root.dispatch("click", makeEl({ "data-action": "something-else" }));
    r.root.dispatch("click", makeEl({}));
    assert.ok(r.root.region("chart").includes('aria-selected="true" class="on">Tomorrow'));
    assert.equal(r.rec.messages.length, 3, "a click never sends anything");
    assert.deepEqual(r.rec.calls, []);
  });
});

describe("refresh and lifecycle", () => {
  it("statistics are re-queried at most every 10 minutes, however often Home Assistant updates", async () => {
    const r = rig();
    r.card.connectedCallback();
    for (let i = 0; i < 50; i++) {
      r.clock.t = NOW + i * 1000;
      r.push();
      await flush();
    }
    assert.equal(statMsgs(r.rec).length, 1);
    r.clock.t = NOW + STATS_REFRESH_MS + 1;
    r.push();
    await flush();
    assert.equal(statMsgs(r.rec).length, 2);
    assert.equal(forecastMsgs(r.rec).length, 2, "subscriptions are not repeated");
  });
  it("leaving the page unsubscribes; returning subscribes again", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    r.card.disconnectedCallback();
    assert.deepEqual(r.rec.subscriptions.map((s) => s.unsubscribed), [true, true]);
    r.push();
    await flush();
    assert.equal(forecastMsgs(r.rec).length, 2, "nothing while detached");
    r.card.connectedCallback();
    await flush();
    assert.equal(forecastMsgs(r.rec).length, 4);
    assert.deepEqual(r.rec.subscriptions.slice(2).map((s) => s.unsubscribed), [false, false]);
  });
  it("detaching before a subscription is confirmed unsubscribes it as soon as it arrives", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    r.card.disconnectedCallback();
    await flush();
    assert.deepEqual(r.rec.subscriptions.map((s) => s.unsubscribed), [true, true]);
  });
  it("a new weather entity in the configuration moves both subscriptions", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    r.card.setConfig({ entities: { weather: "weather.home_hourly" } });
    await flush();
    assert.deepEqual(r.rec.subscriptions.map((s) => [s.message.entity_id, s.unsubscribed]), [
      ["weather.forecast_home", true], ["weather.forecast_home", true], ["weather.home_hourly", false], ["weather.home_hourly", false]]);
  });
  it("a late event from an old subscription is ignored", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    const old = r.rec.subscriptions[0]!;
    r.card.setConfig({ entities: { weather: "weather.other" } });
    await flush();
    old.callback({ forecast: hourlyForecast(NOW, 48) });
    assert.ok(r.root.region("hourly").includes("Loading hourly forecast"));
  });
  it("a new connection (Home Assistant reconnected) re-subscribes on it", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    const rec2 = newRecorder();
    const conn2 = fakeConnection(rec2, { statistics: {} });
    (r.card as unknown as { hass: unknown }).hass = recordingHass(states(), rec2, conn2, HA_CONFIG);
    await flush();
    assert.deepEqual(r.rec.subscriptions.map((s) => s.unsubscribed), [true, true]);
    assert.equal(forecastMsgs(rec2).length, 2);
  });
  it("uses no timer of any kind", async () => {
    const r = rig();
    shim.noTimers(() => {
      r.card.connectedCallback();
      r.push();
      r.push();
      r.root.dispatch("click", makeEl({ "data-action": "chart-day", "data-day": "tomorrow" }));
      r.card.disconnectedCallback();
    });
    await flush();
    assert.deepEqual(shim.rec.calls.filter((c) => /Timeout|Interval|AnimationFrame/.test(c)), []);
  });
});

describe("errors and fallbacks", () => {
  it("a failed forecast subscription is shown, and retried no sooner than 5 minutes", async () => {
    const r = rig({ subscribeError: { code: "not_found", message: "Entity not found: weather.forecast_home" }, statistics: {} });
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.ok(r.root.region("hourly").includes("Hourly forecast unavailable: Entity not found: weather.forecast_home"));
    assert.ok(r.root.region("daily").includes("Daily forecast unavailable: Entity not found"));
    const n = forecastMsgs(r.rec).length;
    r.clock.t = NOW + FORECAST_RETRY_MS - 1000;
    r.push();
    await flush();
    assert.equal(forecastMsgs(r.rec).length, n);
    r.clock.t = NOW + FORECAST_RETRY_MS + 1000;
    r.push();
    await flush();
    assert.equal(forecastMsgs(r.rec).length, n + 2);
  });
  it("failed statistics leave the forecast chart and say so", async () => {
    const r = rig({ statisticsError: { code: "unknown_statistic", message: "no such statistic" } });
    r.card.connectedCallback();
    r.push();
    await flush();
    const chart = r.root.region("chart");
    assert.ok(chart.includes("Actual PV history unavailable: no such statistic"));
    assert.ok(chart.includes('class="sc-l"'), "the Solcast profile is still drawn");
    assert.ok(!chart.includes('class="act"'));
  });
  it("without a websocket connection the card still shows everything from states, and explains the rest", async () => {
    const rec = newRecorder();
    const card = new EccoWeatherSolarCard();
    card.now = () => NOW;
    card.setConfig({});
    card.connectedCallback();
    (card as unknown as { hass: unknown }).hass = recordingHass(states(), rec, undefined, HA_CONFIG);
    await flush();
    const root = card.shadowRoot as unknown as FakeRoot;
    assert.ok(root.region("hourly").includes("no Home Assistant websocket connection"));
    assert.ok(root.region("chart").includes("Actual PV history needs the Home Assistant websocket connection"));
    assert.ok(root.region("solar").includes("20.5 kWh"));
    assert.deepEqual(rec.calls, []);
    assert.equal(rec.messages.length, 0);
  });
  it("with every entity missing nothing throws and nothing shows 0 for an unknown", async () => {
    const r = rig({ statistics: {} });
    r.card.connectedCallback();
    r.push({});
    await flush();
    r.rec.subscriptions[0]!.callback({ forecast: [] });
    r.rec.subscriptions[1]!.callback({ forecast: "garbage" });
    assert.ok(r.root.region("now").includes("not found or unavailable"));
    assert.ok(r.root.region("solar").includes('<div class="big blend">--</div>'));
    assert.ok(!r.root.region("solar").includes("0.0 kWh"));
    assert.ok(r.root.region("chart").includes("not found or unavailable"));
    assert.ok(r.root.region("hourly").includes("Hourly forecast unavailable."));
    assert.ok(r.root.region("sun").includes("Sun times") || r.root.region("sun").includes("Sunrise"));
    assert.ok(r.root.region("fresh").includes("update time unknown"));
  });
});

describe("layouts: each compact instance sends only the message its section needs", () => {
  it("solar_strip: the statistics query only - no forecast subscription at all", async () => {
    const r = rig(undefined, { layout: "solar_strip" });
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.deepEqual(r.rec.messages.map((m) => m.type), ["recorder/statistics_during_period"]);
    assert.deepEqual(statMsgs(r.rec)[0]!.statistic_ids, [STAT_ID]);
    assert.deepEqual(r.rec.subscriptions, []);
    assert.deepEqual(r.rec.calls, []);
    assert.deepEqual([...r.root.regions.keys()], ["totals", "curve", "fresh"]);
    assert.ok(r.root.region("totals").includes('<div class="lbl">Today</div><div class="big blend">20.5 kWh</div>'));
    assert.ok(r.root.region("totals").includes("Solcast 23.0") && r.root.region("totals").includes("generated so far 9.8 kWh"));
    assert.ok(r.root.region("curve").includes('<svg class="spark"') && r.root.region("curve").includes("12:00 actual 2.10 kWh"), r.root.region("curve"));
    assert.ok(r.root.region("fresh").includes("Solcast: 2 h ago") && r.root.region("fresh").includes("Forecast.Solar: 25 min ago"));
    assert.ok(!r.root.region("fresh").includes("Met.no"), "no weather section, so no weather chip");
    assert.ok(r.root.innerHTML.includes('<div class="stitle">Solar forecast</div>'));
    assert.equal(r.card.getCardSize(), 2);
  });
  it("solar_strip: statistics are still re-queried at most every 10 minutes, and never a subscription", async () => {
    const r = rig(undefined, { layout: "solar_strip" });
    r.card.connectedCallback();
    for (let i = 0; i < 20; i++) {
      r.clock.t = NOW + i * 1000;
      r.push();
      await flush();
    }
    assert.equal(r.rec.messages.length, 1);
    r.clock.t = NOW + STATS_REFRESH_MS + 1;
    r.push();
    await flush();
    assert.deepEqual(r.rec.messages.map((m) => m.type), ["recorder/statistics_during_period", "recorder/statistics_during_period"]);
  });
  it("solar_strip: unknown totals show --, missing Solcast detail shows the plain message instead of a curve", async () => {
    const r = rig({ statistics: {} }, { layout: "solar_strip" });
    r.card.connectedCallback();
    r.push({});
    await flush();
    assert.equal((r.root.region("totals").match(/<div class="big blend">--<\/div>/g) ?? []).length, 3);
    assert.ok(!r.root.region("totals").includes("0.0 kWh"));
    assert.ok(r.root.region("totals").includes("generated so far --"));
    assert.ok(!r.root.region("curve").includes("<svg"));
    assert.ok(r.root.region("curve").includes("Solcast sensor sensor.solcast_pv_forecast_forecast_today not found or unavailable."));
    assert.ok(r.root.region("fresh").includes("Solcast: update time unknown"));
    const r2 = rig({ statistics: {} }, { layout: "solar_strip" });
    r2.card.connectedCallback();
    r2.push(states({ "sensor.solcast_pv_forecast_forecast_today": { state: "23.0", attributes: { estimate: 23.0 } } }));
    await flush();
    assert.ok(!r2.root.region("curve").includes("<svg"));
    assert.ok(r2.root.region("curve").includes("Solcast hourly detail is not available"));
  });
  it("solar_strip: failed statistics keep the Solcast curve, drop the bars and explain in the tooltip", async () => {
    const r = rig({ statisticsError: { code: "unknown_statistic", message: "no such statistic" } }, { layout: "solar_strip" });
    r.card.connectedCallback();
    r.push();
    await flush();
    const curve = r.root.region("curve");
    assert.ok(curve.includes('title="Actual PV history unavailable: no such statistic"'));
    assert.ok(curve.includes('class="sc-l"') && !curve.includes('class="act"'));
  });
  it("daily_compact: the daily forecast subscription only - no hourly subscription, no statistics query", async () => {
    const r = rig(undefined, { layout: "daily_compact", daily_days: 7 });
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.deepEqual(r.rec.messages, [{ type: "weather/subscribe_forecast", entity_id: "weather.forecast_home", forecast_type: "daily" }]);
    assert.deepEqual(r.rec.calls, []);
    assert.deepEqual([...r.root.regions.keys()], ["fresh", "daily"]);
    assert.ok(r.root.innerHTML.includes('<div class="title">Next days</div>'));
    assert.ok(r.root.region("fresh").includes("Met.no weather: 20 min ago"), r.root.region("fresh"));
    assert.ok(r.root.region("daily").includes("Loading daily forecast"));
    r.rec.subscriptions[0]!.callback({ type: "daily", forecast: dailyForecast() });
    const daily = r.root.region("daily");
    assert.equal((daily.match(/class="dc"/g) ?? []).length, 6, "six entries give six rows: daily_days 7 is never padded");
    assert.ok(daily.includes("15° / 8°") && daily.includes("4.2 mm"));
    assert.ok(!daily.includes('class="pp"'), "Met.no: no probability column");
    assert.equal(r.rec.messages.length, 1, "the forecast event sent nothing");
    assert.equal(r.card.getCardSize(), 5);
  });
  it("daily_compact: a failed subscription is shown and retried after 5 minutes, still daily only", async () => {
    const r = rig({ subscribeError: { code: "not_found", message: "Entity not found: weather.forecast_home" }, statistics: {} }, { layout: "daily_compact" });
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.ok(r.root.region("daily").includes("Daily forecast unavailable: Entity not found: weather.forecast_home"));
    r.clock.t = NOW + FORECAST_RETRY_MS + 1000;
    r.push();
    await flush();
    assert.deepEqual(r.rec.messages.map((m) => [m.type, m.forecast_type]), [["weather/subscribe_forecast", "daily"], ["weather/subscribe_forecast", "daily"]]);
  });
  it("daily_compact without a websocket connection explains itself and sends nothing", async () => {
    const rec = newRecorder();
    const card = new EccoWeatherSolarCard();
    card.now = () => NOW;
    card.setConfig({ layout: "daily_compact" });
    card.connectedCallback();
    (card as unknown as { hass: unknown }).hass = recordingHass(states(), rec, undefined, HA_CONFIG);
    await flush();
    const root = card.shadowRoot as unknown as FakeRoot;
    assert.ok(root.region("daily").includes("no Home Assistant websocket connection"));
    assert.equal(rec.messages.length, 0);
    assert.deepEqual(rec.calls, []);
  });
  it("full (explicit) is the unchanged set: two subscriptions and one statistics query, identical regions", async () => {
    const a = rig(undefined, { layout: "full" });
    const b = rig();
    for (const r of [a, b]) {
      r.card.connectedCallback();
      r.push();
      await flush();
      r.rec.subscriptions[0]!.callback({ forecast: hourlyForecast(NOW, 48) });
      r.rec.subscriptions[1]!.callback({ forecast: dailyForecast() });
    }
    assert.deepEqual(a.rec.messages, b.rec.messages);
    assert.equal(a.rec.messages.length, 3);
    assert.equal(a.root.innerHTML, b.root.innerHTML, "the same shell");
    assert.deepEqual([...a.root.regions.keys()], [...b.root.regions.keys()]);
    for (const name of a.root.regions.keys()) assert.equal(a.root.region(name), b.root.region(name), name);
    assert.equal(a.card.getCardSize(), 14);
  });
  it("changing the layout moves the subscriptions to exactly what the new layout needs", async () => {
    const r = rig();
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.equal(r.rec.messages.length, 3);
    r.card.setConfig({ layout: "solar_strip" });
    await flush();
    assert.deepEqual(r.rec.subscriptions.map((s) => s.unsubscribed), [true, true], "both forecast subscriptions are dropped");
    assert.equal(r.rec.messages.length, 3, "the strip re-uses the statistics already fetched; nothing new is sent");
    r.card.setConfig({ layout: "daily_compact" });
    await flush();
    assert.deepEqual(r.rec.messages.slice(3), [{ type: "weather/subscribe_forecast", entity_id: "weather.forecast_home", forecast_type: "daily" }]);
    assert.deepEqual(r.rec.subscriptions.map((s) => [s.message.forecast_type, s.unsubscribed]), [["hourly", true], ["daily", true], ["daily", false]]);
    r.card.disconnectedCallback();
    assert.deepEqual(r.rec.subscriptions.map((s) => s.unsubscribed), [true, true, true]);
  });
  it("daily_compact -> solar_strip on a live card queries the statistics at once, without waiting for the next hass update", async () => {
    const r = rig(undefined, { layout: "daily_compact" });
    r.card.connectedCallback();
    r.push();
    await flush();
    assert.deepEqual(r.rec.messages.map((m) => m.type), ["weather/subscribe_forecast"]);
    r.card.setConfig({ layout: "solar_strip" });
    await flush();
    assert.deepEqual(r.rec.messages.map((m) => m.type), ["weather/subscribe_forecast", "recorder/statistics_during_period"]);
    assert.deepEqual(r.rec.subscriptions.map((s) => s.unsubscribed), [true], "the daily subscription is dropped, none is added");
    assert.ok(r.root.region("curve").includes("12:00 actual 2.10 kWh"), "the actual bars are drawn before any further hass update");
    // The throttle still holds: the same configuration again sends nothing new.
    r.card.setConfig({ layout: "solar_strip" });
    await flush();
    assert.equal(r.rec.messages.length, 2);
    // A new statistic id is queried at once as well.
    r.card.setConfig({ layout: "solar_strip", entities: { pv_energy_statistic: "sensor.other_total_pv_energy" } });
    await flush();
    assert.deepEqual(statMsgs(r.rec).map((m) => m.statistic_ids), [[STAT_ID], ["sensor.other_total_pv_energy"]]);
    assert.deepEqual(r.rec.calls, []);
  });
  it("the compact layouts use no timer and keep neither hass nor its connection", async () => {
    for (const layout of ["solar_strip", "daily_compact"]) {
      const r = rig(undefined, { layout });
      shim.noTimers(() => {
        r.card.connectedCallback();
        r.push();
        r.push();
        r.card.disconnectedCallback();
      });
      await flush();
      assert.deepEqual(shim.rec.calls.filter((c) => /Timeout|Interval|AnimationFrame/.test(c)), [], layout);
      const held = Object.values(r.card as unknown as Record<string, unknown>);
      assert.ok(!held.includes(r.conn), layout);
      assert.deepEqual(r.rec.calls, [], layout);
    }
  });
});

describe("daily_compact: a day's hourly breakdown in the same card", () => {
  const DAILY = { type: "weather/subscribe_forecast", entity_id: "weather.forecast_home", forecast_type: "daily" };
  const HOURLY = { type: "weather/subscribe_forecast", entity_id: "weather.forecast_home", forecast_type: "hourly" };
  const open = (r: Rig, date: string): void => r.root.dispatch("click", makeEl({ "data-action": "weather-hours", "data-date": date }));
  const back = (r: Rig): void => r.root.dispatch("click", makeEl({ "data-action": "weather-days", "data-date": "ignored" }));
  const rows = (r: Rig): number => (r.root.region("daily").match(/<button type="button" class="dc/g) ?? []).length;
  const cells = (r: Rig): number => (r.root.region("daily").match(/class="hc"/g) ?? []).length;
  const subs = (r: Rig) => r.rec.subscriptions.map((s) => [s.message.forecast_type, s.unsubscribed]);
  /** A connected compact card whose daily list has arrived (six days from Thu 8 Oct), at `now`. */
  async function compact(now = NOW, daily = dailyForecast(), opts?: Parameters<typeof rig>[0]): Promise<Rig> {
    const r = rig(opts ?? { statistics: {} }, { layout: "daily_compact", daily_days: 7 });
    r.clock.t = now;
    r.card.connectedCallback();
    r.push();
    await flush();
    r.rec.subscriptions[0]!.callback({ type: "daily", forecast: daily });
    return r;
  }

  it("the idle day list keeps only the daily subscription, however many updates arrive", async () => {
    const r = await compact();
    for (let i = 0; i < 30; i++) {
      r.clock.t = NOW + i * 30000;
      r.push();
      await flush();
    }
    assert.deepEqual(r.rec.messages, [DAILY]);
    assert.equal(rows(r), 6);
  });
  it("clicking a day subscribes to the hourly forecast once, shows that day's hours and moves focus to Back to days", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY], "exactly one more message: the hourly forecast subscription");
    assert.ok(r.root.region("daily").includes("Loading hourly forecast...") && r.root.region("daily").includes("Back to days"));
    assert.deepEqual(r.root.focused, [{ selector: '[data-action="weather-days"]', options: { preventScroll: true } }]);
    await flush();
    r.rec.subscriptions[1]!.callback({ type: "hourly", forecast: hourlyForecast(NOW, 72) });
    assert.equal(cells(r), 24);
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Fri 9 Oct') && r.root.region("daily").includes('<div class="dsum">'));
    assert.equal(rows(r), 0, "the list is replaced, in the same card");
    for (let i = 1; i < 10; i++) {
      r.clock.t = NOW + i * 60000;
      r.push();
      await flush();
    }
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY], "updates while open send nothing more");
    assert.deepEqual(r.rec.calls, []);
  });
  it("Back to days ends the hourly subscription, keeps the daily one, restores the list and returns focus to that day's row", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    back(r);
    assert.deepEqual(subs(r), [["daily", false], ["hourly", true]]);
    assert.equal(rows(r), 6);
    assert.equal(r.root.focused.at(-1)?.selector, '[data-action="weather-hours"][data-date="2026-10-09"]');
    assert.ok(r.root.activeElement?.tag.includes('data-date="2026-10-09"'));
    const focusCalls = r.root.focused.length;
    back(r);
    assert.equal(r.root.focused.length, focusCalls, "Back with nothing open does nothing");
    open(r, "2026-10-10");
    await flush();
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY, HOURLY], "re-opening subscribes afresh; nothing is kept running in between");
    assert.ok(r.root.region("daily").includes("Loading hourly forecast..."), "and shows no leftover hours of the earlier subscription");
  });
  it("Back before the subscription is confirmed unsubscribes it on arrival; its late events are ignored", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    back(r);
    await flush();
    assert.deepEqual(subs(r), [["daily", false], ["hourly", true]]);
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.equal(rows(r), 6);
    open(r, "2026-10-09");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.ok(r.root.region("daily").includes("Loading hourly forecast..."), "the dropped subscription cannot fill the new view");
    r.rec.subscriptions[2]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.equal(cells(r), 24);
  });
  it("ignores what it cannot honour: a date not in the list, a malformed one, a second open, and any other layout", async () => {
    const r = await compact();
    for (const d of ["2026-10-07", "2026-10-14", "2026-10-9", '"><img src=x onerror=alert(1)>', ""]) open(r, d);
    r.root.dispatch("click", makeEl({ "data-action": "weather-hours" }));
    assert.deepEqual(r.rec.messages, [DAILY]);
    assert.equal(rows(r), 6);
    open(r, "2026-10-09");
    open(r, "2026-10-10");
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY]);
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Fri 9 Oct'));
    const f = rig();
    f.card.connectedCallback();
    f.push();
    await flush();
    f.rec.subscriptions[1]!.callback({ forecast: dailyForecast() });
    const before = f.root.region("daily");
    open(f, "2026-10-09");
    f.root.dispatch("click", makeEl({ "data-action": "weather-days" }));
    assert.equal(f.rec.messages.length, 3, "the full layout has no day breakdown and sends nothing new");
    assert.equal(f.root.region("daily"), before);
    assert.deepEqual(f.root.focused, []);
  });
  it("a failed hourly subscription is shown with Back to days; the daily list is unaffected; re-opening retries at once", async () => {
    const r = await compact(NOW, dailyForecast(), { statistics: {}, subscribeErrorFor: { hourly: { code: "not_supported", message: "hourly forecast not supported" } } });
    open(r, "2026-10-09");
    await flush();
    const html = r.root.region("daily");
    assert.ok(html.includes("Hourly forecast unavailable: hourly forecast not supported") && html.includes("Back to days") && html.includes('<div class="dsum">'));
    back(r);
    assert.equal(rows(r), 6);
    open(r, "2026-10-09");
    await flush();
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY, HOURLY]);
  });
  it("a day the hourly forecast does not reach says so; nothing is filled in", async () => {
    const r = await compact();
    open(r, "2026-10-13");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 48) });
    const html = r.root.region("daily");
    assert.ok(html.includes("Hourly forecast not available for this day.") && html.includes("Back to days") && html.includes("Tue 13 Oct"));
    assert.equal(cells(r), 0);
    r.rec.subscriptions[1]!.callback({ forecast: "garbage" });
    assert.ok(r.root.region("daily").includes("Hourly forecast not available for this day."));
  });
  it("Home Assistant reconnects while a day is open: both subscriptions move to the new connection, the day stays open", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    await flush();
    const rec2 = newRecorder();
    (r.card as unknown as { hass: unknown }).hass = recordingHass(states(), rec2, fakeConnection(rec2, { statistics: {} }), HA_CONFIG);
    await flush();
    assert.deepEqual(subs(r), [["daily", true], ["hourly", true]]);
    assert.deepEqual(rec2.messages, [DAILY, HOURLY]);
    rec2.subscriptions[0]!.callback({ forecast: dailyForecast() });
    rec2.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.equal(cells(r), 24);
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Fri 9 Oct'));
  });
  it("leaving the page while a day is open ends both subscriptions; returning restores the same day with fresh ones", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    r.card.disconnectedCallback();
    assert.deepEqual(subs(r), [["daily", true], ["hourly", true]]);
    r.push();
    await flush();
    assert.equal(r.rec.messages.length, 2, "nothing while detached");
    r.card.connectedCallback();
    await flush();
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY, DAILY, HOURLY]);
    assert.deepEqual(subs(r).slice(2), [["daily", false], ["hourly", false]]);
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Fri 9 Oct'));
    back(r);
    r.card.disconnectedCallback();
    r.card.connectedCallback();
    await flush();
    assert.deepEqual(r.rec.messages.slice(4), [DAILY], "the idle list comes back with the daily subscription alone");
  });
  it("a new weather entity closes the day and subscribes to the daily forecast only", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    await flush();
    r.card.setConfig({ layout: "daily_compact", daily_days: 7, entities: { weather: "weather.other" } });
    await flush();
    assert.deepEqual(r.rec.subscriptions.map((s) => [s.message.entity_id, s.message.forecast_type, s.unsubscribed]), [
      ["weather.forecast_home", "daily", true], ["weather.forecast_home", "hourly", true], ["weather.other", "daily", false]]);
    assert.ok(r.root.region("daily").includes("Loading daily forecast"));
    r.card.setConfig({ layout: "full" });
    await flush();
    assert.deepEqual(forecastMsgs(r.rec).slice(3).map((m) => m.forecast_type), ["hourly", "daily"], "full: its usual two subscriptions");
    assert.equal(statMsgs(r.rec).length, 1, "and its statistics query");
  });
  it("an open day that becomes a past date (open over midnight) closes and its hourly subscription ends", async () => {
    const r = await compact();
    open(r, "2026-10-08");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.equal(cells(r), 11, "today from the current hour: 13:00 to 23:00");
    r.clock.t = Date.parse("2026-10-08T22:59:00Z");
    r.push();
    await flush();
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Thu 8 Oct') && rows(r) === 0, "still open: today at 23:59 BST");
    r.clock.t = Date.parse("2026-10-08T23:01:00Z"); // 00:01 BST on the 9th
    r.push();
    await flush();
    assert.deepEqual(subs(r), [["daily", false], ["hourly", true]]);
    assert.equal(rows(r), 5, "the list again, from the new today");
    assert.equal(r.rec.messages.length, 2);
  });
  it("while a day is open, the freshness chip also judges the hourly forecast (stale when it starts hours in the past)", async () => {
    const r = await compact();
    open(r, "2026-10-08");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW - 5 * HOUR, 72) });
    assert.ok(r.root.region("fresh").includes("(stale)"), r.root.region("fresh"));
    back(r);
    assert.ok(!r.root.region("fresh").includes("(stale)"));
  });
  it("Sun 25 Oct 2026 opened on the Saturday: 25 hourly cells with 01:00 BST and 01:00 GMT", async () => {
    const sat = Date.parse("2026-10-24T09:00:00Z");
    const r = await compact(sat, dailyFor(["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]));
    assert.equal(rows(r), 7);
    open(r, "2026-10-25");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(sat, 72) });
    const html = r.root.region("daily");
    assert.equal(cells(r), 25);
    assert.ok(html.includes('<div class="t">01:00 BST</div>') && html.includes('<div class="t">01:00 GMT</div>'));
    assert.ok(html.includes("Clocks go back on this day: it has 25 hours, and the times from 01:00 to 01:59 occur twice.") && html.includes("Sun 25 Oct"));
  });
  it("Sun 28 Mar 2027 opened on the Saturday: 23 hourly cells and no 01:00", async () => {
    const sat = Date.parse("2027-03-27T09:00:00Z");
    const r = await compact(sat, dailyFor(["2027-03-27", "2027-03-28", "2027-03-29"]));
    open(r, "2027-03-28");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(sat, 72) });
    const html = r.root.region("daily");
    assert.equal(cells(r), 23);
    assert.ok(!html.includes('<div class="t">01:00') && html.includes('<div class="t">02:00</div>'));
    assert.ok(html.includes("Clocks go forward on this day: it has 23 hours, and there are no times from 01:00 to 01:59.") && html.includes("Sun 28 Mar"));
  });
  it("focus stays on Back to days when the hourly data arrives just after opening (the view is rewritten)", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    assert.ok(r.root.activeElement?.tag.includes('data-action="weather-days"'));
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.equal(cells(r), 24, "the view was rewritten with the hours");
    assert.ok(r.root.activeElement?.tag.includes('data-action="weather-days"'), "and Back to days has focus again");
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW + HOUR, 72) });
    assert.ok(r.root.activeElement?.tag.includes('data-action="weather-days"'), "after a forecast update too");
  });
  it("a keyboard user keeps their place across forecast updates: on a day row, or on the hourly strip", async () => {
    const r = await compact();
    r.root.focusOn('data-date="2026-10-11"');
    r.rec.subscriptions[0]!.callback({ forecast: dailyForecast().map((f) => ({ ...f, temperature: 30 })) });
    assert.ok(r.root.region("daily").includes("30° /"), "the list was rewritten");
    assert.ok(r.root.activeElement?.tag.includes('data-date="2026-10-11"') && r.root.activeElement.tag.includes("weather-hours"));
    open(r, "2026-10-11");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 96) });
    r.root.focusOn('data-strip="2026-10-11"');
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW + HOUR, 96) });
    assert.equal(r.root.activeElement?.getAttribute("data-strip"), "2026-10-11");
  });
  it("a forecast update keeps the strip where the user scrolled it; another day starts at its beginning", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    const region = r.root.regions.get("daily")!;
    region.strip!.scrollLeft = 420;
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW + HOUR, 72) });
    assert.equal(region.strip!.scrollLeft, 420, "same day, new HTML: the scroll position carries over");
    back(r);
    open(r, "2026-10-10");
    await flush();
    r.rec.subscriptions[2]!.callback({ forecast: hourlyForecast(NOW, 72) });
    assert.equal(region.strip!.getAttribute("data-strip"), "2026-10-10");
    assert.equal(region.strip!.scrollLeft, 0);
  });
  it("a double click opens the day once: its second click (on Back to days, now where the row was) is not a choice", async () => {
    const r = await compact();
    r.root.dispatch("click", makeEl({ "data-action": "weather-hours", "data-date": "2026-10-08" }), 1);
    r.root.dispatch("click", makeEl({ "data-action": "weather-days", "data-date": "2026-10-08" }), 2);
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Thu 8 Oct'), "still open");
    assert.deepEqual(r.rec.messages, [DAILY, HOURLY]);
    r.root.dispatch("click", makeEl({ "data-action": "weather-days", "data-date": "2026-10-08" }), 1);
    r.root.dispatch("click", makeEl({ "data-action": "weather-hours", "data-date": "2026-10-08" }), 2);
    assert.equal(rows(r), 6, "a double click on Back closes once, too");
    r.root.dispatch("click", makeEl({ "data-action": "weather-hours", "data-date": "2026-10-09" }), 0);
    assert.ok(r.root.region("daily").includes('<h3 class="dtitle">Fri 9 Oct'), "keyboard activation (detail 0) opens");
  });
  it("focus is never dropped: when the open day closes at midnight, or its row is no longer listed after Back, the first row takes it", async () => {
    const r = await compact();
    open(r, "2026-10-08");
    await flush();
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    r.root.focusOn('data-strip="2026-10-08"');
    r.clock.t = Date.parse("2026-10-08T23:01:00Z"); // 00:01 BST on the 9th: the open day is in the past
    r.push();
    await flush();
    assert.equal(rows(r), 5);
    assert.equal(r.root.focused.at(-1)?.selector, '[data-action="weather-hours"]');
    assert.ok(r.root.activeElement?.tag.includes('data-date="2026-10-09"'), "the new first row");
    const s = await compact(NOW, dailyForecast().slice(1)); // a list without today's row
    s.card.setConfig({ layout: "daily_compact", daily_days: 7 });
    s.rec.subscriptions[0]!.callback({ forecast: dailyForecast() });
    open(s, "2026-10-08");
    s.rec.subscriptions[0]!.callback({ forecast: dailyForecast().slice(1) }); // the daily forecast drops the open day
    back(s);
    assert.equal(s.root.focused.at(-1)?.selector, '[data-action="weather-hours"]');
    assert.ok(s.root.activeElement?.tag.includes('data-date="2026-10-09"'));
  });
  it("never takes focus it did not have: with focus elsewhere on the page, updates move nothing", async () => {
    const r = await compact();
    open(r, "2026-10-09");
    await flush();
    r.root.focusOn(null);
    const n = r.root.focused.length;
    r.rec.subscriptions[1]!.callback({ forecast: hourlyForecast(NOW, 72) });
    r.rec.subscriptions[0]!.callback({ forecast: dailyForecast().map((f) => ({ ...f, templow: 1 })) });
    r.clock.t = NOW + 5 * 60000;
    r.push();
    assert.equal(r.root.focused.length, n);
    assert.equal(r.root.activeElement, null);
  });
  it("uses no timer, keeps neither hass nor its connection, and calls nothing while opening and closing days", async () => {
    const r = await compact();
    shim.noTimers(() => {
      open(r, "2026-10-09");
      back(r);
      open(r, "2026-10-10");
    });
    await flush();
    shim.noTimers(() => {
      r.rec.subscriptions[2]!.callback({ forecast: hourlyForecast(NOW, 72) });
      back(r);
      r.card.disconnectedCallback();
    });
    assert.deepEqual(shim.rec.calls.filter((c) => /Timeout|Interval|AnimationFrame/.test(c)), []);
    const held = Object.values(r.card as unknown as Record<string, unknown>);
    assert.ok(!held.includes(r.conn));
    assert.deepEqual(r.rec.calls, []);
    assert.deepEqual([...new Set(r.rec.messages.map((m) => m.type))], ["weather/subscribe_forecast"]);
    assert.deepEqual([...new Set(r.rec.reads)].sort(), ["config", "connection", "states"]);
  });
});

describe("read-only by construction", () => {
  it("keeps neither the hass object, its connection nor its config object", async () => {
    const r = rig();
    r.card.connectedCallback();
    const hass = r.push() as Record<string, unknown>;
    await flush();
    const held = Object.values(r.card as unknown as Record<string, unknown>);
    assert.ok(!held.includes(hass), "the hass object is not a field of the card");
    assert.ok(!held.includes(r.conn), "the connection is not a field of the card");
    assert.ok(!held.includes(HA_CONFIG), "hass.config is copied, not kept");
    assert.deepEqual(r.rec.calls, []);
    assert.deepEqual([...new Set(r.rec.reads)].sort(), ["config", "connection", "states"], "reads only states, config and connection");
  });
});
