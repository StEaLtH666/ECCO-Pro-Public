// The custom element through a recording DOM / Home Assistant stand-in: registration, the exact websocket messages it sends
// (two forecast subscriptions and one throttled statistics query - nothing else), subscription lifecycle, refresh, errors
// and fallbacks, the Today / Tomorrow switch, no timers, and that neither the hass object nor its connection is kept.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { fakeConnection, installDomShim, makeEl, newRecorder, recordingHass } from "./dom-shim.ts";
import type { FakeRoot, Recorder } from "./dom-shim.ts";
import { HA_CONFIG, HOUR, NOW, dailyForecast, hourlyForecast, statRows, states } from "./fixtures.ts";
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
