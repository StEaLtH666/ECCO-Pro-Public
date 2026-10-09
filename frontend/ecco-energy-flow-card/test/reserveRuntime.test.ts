// FE-1: the battery node's time-to-reserve line and tooltip. The card shows the
// configured entity's own value and status; these tests pin that it neither
// estimates nor invents anything, and that every status ECCO's Home Assistant
// package emits has wording.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { RESERVE_RUNTIME_STATUSES, resolveReserveRuntime, resolveTimeToReserveMinutes, type ReserveRuntime } from "../src/utils/display.ts";
import { formatApproxMinutes, reserveRuntimeLine, reserveRuntimeTooltip } from "../src/utils/format.ts";

const ID = "sensor.ecco_battery_time_to_reserve";

function rt(minutes: number | null, attributes: Record<string, unknown> | undefined): ReserveRuntime {
  const r = resolveReserveRuntime(ID, minutes, attributes);
  assert.ok(r !== undefined);
  return r;
}

test("no entity configured -> nothing at all (the hook stays inert)", () => {
  assert.equal(resolveReserveRuntime(undefined, undefined, { status: "discharging" }), undefined);
  assert.equal(resolveReserveRuntime("", 120, { status: "discharging" }), undefined);
  assert.equal(resolveReserveRuntime(ID, undefined, { status: "discharging" }), undefined);
});

test("discharging: the entity's own minutes as an approximate duration, its range and solar flag in the tooltip", () => {
  const r = rt(320, { status: "discharging", minutes_low: 280, minutes_high: 370, solar_assisted: true, beyond_horizon: false });
  assert.deepEqual([r.status, r.minutes, r.low, r.high, r.solarAssisted], ["discharging", 320, 280, 370, true]);
  assert.equal(reserveRuntimeLine(r), "≈5h 20m to reserve");
  assert.equal(
    reserveRuntimeTooltip(r),
    "Time to reserve: Approximately 5 h 20 min until the batteries reach the configured reserve at recent usage; " +
      "likely 4 h 40 min to 6 h 10 min; solar-assisted, so it shortens as solar output falls; an estimate, not a guarantee"
  );
});

test("the tooltip always says it is an estimate, never a guarantee", () => {
  for (const attrs of [{ status: "discharging" }, { status: "discharging", beyond_horizon: true }, {}]) {
    assert.match(reserveRuntimeTooltip(rt(90, attrs)), /an estimate, not a guarantee$/);
  }
});

test("a value the entity marks beyond its horizon is shown as 'Over 3 days', without a range", () => {
  const r = rt(4320, { status: "discharging", beyond_horizon: true, minutes_low: 4000, minutes_high: 4320 });
  assert.equal(reserveRuntimeLine(r), "Over 3 days");
  assert.doesNotMatch(reserveRuntimeTooltip(r), /likely/);
});

test("every status the package emits has its own wording; non-discharging statuses carry no duration", () => {
  const words: Record<string, string> = {
    discharging: "≈2h to reserve",
    at_reserve: "At reserve",
    charging: "Charging",
    holding: "Holding",
    insufficient_data: "Insufficient data",
    stale: "Telemetry stale",
  };
  assert.deepEqual([...RESERVE_RUNTIME_STATUSES].sort(), Object.keys(words).sort());
  for (const status of RESERVE_RUNTIME_STATUSES) {
    const r = rt(status === "at_reserve" ? 0 : 120, { status });
    assert.equal(reserveRuntimeLine(r), words[status], status);
    if (status !== "discharging" && status !== "at_reserve") assert.equal(r.minutes, null, status);
  }
});

test("the entity's own summary is the tooltip for non-discharging statuses", () => {
  const r = rt(null, { status: "insufficient_data", summary: "Insufficient data: collecting recent usage (3 of 10 minutes)" });
  assert.equal(reserveRuntimeTooltip(r), "Time to reserve: Insufficient data: collecting recent usage (3 of 10 minutes)");
  assert.equal(reserveRuntimeTooltip(rt(null, { status: "stale" })), "Time to reserve: Telemetry stale");
});

test("a 'discharging' status without a value is insufficient data, never a guessed time", () => {
  const r = rt(null, { status: "discharging", minutes_low: 100, minutes_high: 200 });
  assert.equal(r.status, "insufficient_data");
  assert.equal(reserveRuntimeLine(r), "Insufficient data");
  assert.equal(r.low, null);
});

test("a plain duration sensor without a status still works (FE-0 compatibility): value -> discharging, none -> insufficient", () => {
  const minutes = resolveTimeToReserveMinutes(ID, 2.5, "h");
  assert.equal(reserveRuntimeLine(rt(minutes ?? null, { unit_of_measurement: "h" })), "≈2h 30m to reserve");
  assert.equal(reserveRuntimeLine(rt(null, {})), "Insufficient data");
  assert.equal(reserveRuntimeLine(rt(null, undefined)), "Insufficient data");
});

test("an unknown status string is not trusted: the value decides, as for a plain sensor", () => {
  assert.equal(rt(60, { status: "maybe" }).status, "discharging");
  assert.equal(rt(null, { status: "maybe" }).status, "insufficient_data");
});

test("malformed range attributes are ignored, never shown", () => {
  const r = rt(90, { status: "discharging", minutes_low: -5, minutes_high: "200" });
  assert.deepEqual([r.low, r.high], [null, null]);
  assert.doesNotMatch(reserveRuntimeTooltip(r), /likely/);
});

test("formatApproxMinutes: approximate, compact and honest about unknown values", () => {
  assert.equal(formatApproxMinutes(45), "≈45m");
  assert.equal(formatApproxMinutes(60), "≈1h");
  assert.equal(formatApproxMinutes(320), "≈5h 20m");
  assert.equal(formatApproxMinutes(1440), "≈1d");
  assert.equal(formatApproxMinutes(1620), "≈1d 3h");
  assert.equal(formatApproxMinutes(0), "0m");
  assert.equal(formatApproxMinutes(0.2), "<1m");
  for (const bad of [null, undefined, -1, Number.NaN, Number.POSITIVE_INFINITY]) assert.equal(formatApproxMinutes(bad), "--");
});

test("the card source estimates nothing: the runtime helpers never read SOC, power, capacity or a reserve level", () => {
  const display = readFileSync(new URL("../src/utils/display.ts", import.meta.url), "utf-8");
  const format = readFileSync(new URL("../src/utils/format.ts", import.meta.url), "utf-8");
  const resolver = display.slice(display.indexOf("export function resolveReserveRuntime"));
  const helpers = format.slice(format.indexOf("export function formatApproxMinutes"), format.indexOf("export function toNumber"));
  for (const src of [resolver, helpers]) {
    assert.doesNotMatch(src, /\bsoc\b|batteryW|capacity|reserve_soc|\* 60|\/ 60 \*/i);
  }
});

test("the runtime line is static: no animation or transition is added for it", () => {
  const card = readFileSync(new URL("../src/ecco-energy-flow-card.ts", import.meta.url), "utf-8");
  const rules = card.slice(card.indexOf(".battery-box .node-runtime {"), card.indexOf("font-style: italic;"));
  assert.ok(rules.length > 0);
  assert.doesNotMatch(rules, /animation|transition|@keyframes/);
  assert.equal((card.match(/node-runtime runtime-/g) ?? []).length, 1);
});
