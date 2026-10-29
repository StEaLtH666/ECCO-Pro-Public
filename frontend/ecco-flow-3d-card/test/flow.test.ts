// Flow edges: direction, idle and unknown semantics, and PV aggregation
// without double counting.
import { test } from "node:test";
import assert from "node:assert/strict";
import { aggregateSolarW, batteryState, buildFlowEdges, connectorReversed, gridState, siteIsIdle, IDLE_THRESHOLD_W } from "../src/core/power.ts";

function edges(p: Parameters<typeof buildFlowEdges>[0]) {
  return Object.fromEntries(buildFlowEdges(p).map((e) => [e.id, e]));
}

test("two PV arrays are never double counted: the total entity wins, else the sum of known arrays", () => {
  assert.equal(aggregateSolarW(6400, [3350, 3050]), 6400);
  assert.equal(aggregateSolarW(6400, [null, null]), 6400);
  assert.equal(aggregateSolarW(null, [3350, 3050]), 6400);
  assert.equal(aggregateSolarW(null, [3350, null]), 3350);
  assert.equal(aggregateSolarW(null, [null, null]), null, "no reading at all is unknown, never 0");
  assert.equal(aggregateSolarW(null, []), null);
  assert.equal(aggregateSolarW(-3, [1, 2]), 0, "a negative total is clamped");
});

test("battery edge: discharging travels forward, charging reverses, the path is the same", () => {
  const dis = edges({ solarW: 0, batteryW: 930, gridW: 0, homeW: 920 });
  const chg = edges({ solarW: 6400, batteryW: -3100, gridW: -1000, homeW: 2300 });
  assert.equal(dis.battery!.reversed, false);
  assert.equal(chg.battery!.reversed, true);
  assert.equal(dis.battery!.magnitudeW, 930);
  assert.equal(chg.battery!.magnitudeW, 3100);
  assert.equal(batteryState(930), "discharging");
  assert.equal(batteryState(-3100), "charging");
});

test("grid edge: importing travels forward, exporting reverses", () => {
  const imp = edges({ solarW: 0, batteryW: -2950, gridW: 4180, homeW: 1180 });
  const exp = edges({ solarW: 230, batteryW: 3480, gridW: -2910, homeW: 760 });
  assert.equal(imp.grid!.reversed, false);
  assert.equal(exp.grid!.reversed, true);
  assert.equal(gridState(4180), "importing");
  assert.equal(gridState(-2910), "exporting");
});

test("connectors (drawn card -> equipment) run the way the energy travels", () => {
  const dis = edges({ solarW: 6400, batteryW: 930, gridW: 4180, homeW: 2300 });
  const chg = edges({ solarW: 6400, batteryW: -3100, gridW: -1000, homeW: 2300 });
  assert.equal(connectorReversed(dis.solar!), false, "sun (Solar card) -> array");
  assert.equal(connectorReversed(dis.battery!), false, "discharging: the battery's store (card) -> cabinet");
  assert.equal(connectorReversed(chg.battery!), true, "charging: cabinet -> card");
  assert.equal(connectorReversed(dis.grid!), false, "importing: grid (card) -> pylon");
  assert.equal(connectorReversed(chg.grid!), true, "exporting: pylon -> card");
  assert.equal(connectorReversed(dis.home!), true, "the house's draw: inverter -> Home card");
});

test("solar and home never reverse, even for a negative raw reading", () => {
  const e = edges({ solarW: -20, batteryW: 0, gridW: 0, homeW: -5 });
  assert.equal(e.solar!.reversed, false);
  assert.equal(e.home!.reversed, false);
  assert.equal(e.solar!.magnitudeW, 0);
  assert.equal(e.home!.magnitudeW, 0);
  assert.equal(e.solar!.idle, true);
});

test("below the idle threshold a known reading is idle (no movement), not unknown", () => {
  const e = edges({ solarW: 2, batteryW: -4, gridW: IDLE_THRESHOLD_W - 1, homeW: 3 });
  for (const id of ["solar", "battery", "grid", "home"] as const) {
    assert.equal(e[id]!.idle, true, id);
    assert.equal(e[id]!.unknown, false, id);
  }
  assert.equal(siteIsIdle(buildFlowEdges({ solarW: 2, batteryW: -4, gridW: 1, homeW: 3 })), true);
  assert.equal(batteryState(4), "idle");
  assert.equal(gridState(-4), "idle");
});

test("an unknown reading is unknown: not idle, not moving, no direction claimed", () => {
  const e = edges({ solarW: null, batteryW: null, gridW: null, homeW: null });
  for (const id of ["solar", "battery", "grid", "home"] as const) {
    assert.equal(e[id]!.unknown, true, id);
    assert.equal(e[id]!.idle, false, id);
    assert.equal(e[id]!.magnitudeW, null, id);
    assert.equal(e[id]!.reversed, false, id);
  }
  assert.equal(siteIsIdle(buildFlowEdges({ solarW: null, batteryW: null, gridW: null, homeW: null })), false, "all-unknown is not an idle site");
  assert.equal(batteryState(null), "unknown");
  assert.equal(gridState(null), "unknown");
});

test("a site with one unknown and the rest idle is idle only on what is known", () => {
  assert.equal(siteIsIdle(buildFlowEdges({ solarW: null, batteryW: 0, gridW: 0, homeW: 0 })), true);
  assert.equal(siteIsIdle(buildFlowEdges({ solarW: null, batteryW: 0, gridW: 900, homeW: 900 })), false);
});
