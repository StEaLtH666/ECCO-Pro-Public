// The V4 overlay layout: pills inside the canvas and in the pack's safe
// zones, routes that pass through the pack's hardware anchors and end at the
// wall inverter, and smooth curves that start and end exactly on their points.
import { test } from "node:test";
import assert from "node:assert/strict";
import { V4_ANCHORS, V4_LAYOUT, V4_SAFE_ZONES, smoothPath, v4Layout, v4ScaleForWidth } from "../src/scene/iso.ts";

const L = V4_LAYOUT;

function nums(d: string): number[] {
  return d.match(/-?\d+(\.\d+)?/g)!.map(Number);
}
function endpoints(d: string): { start: [number, number]; end: [number, number] } {
  const n = nums(d);
  return { start: [n[0]!, n[1]!], end: [n[n.length - 2]!, n[n.length - 1]!] };
}
function passesThrough(d: string, p: { x: number; y: number }): boolean {
  // Every anchor is an on-curve point of the Catmull-Rom spline, so it appears verbatim as a segment end.
  return d.includes(`${p.x.toFixed(1)} ${p.y.toFixed(1)}`);
}

test("canvas matches the pack and pills stay inside it without overlapping", () => {
  assert.equal(L.width, 1448);
  assert.equal(L.height, 1086);
  const list = Object.entries(L.pills);
  for (const [name, p] of list) {
    assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= L.width && p.y + p.h <= L.height, name);
  }
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const [na, a] = list[i]!;
      const [nb, b] = list[j]!;
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      assert.equal(overlap, false, `${na} overlaps ${nb}`);
    }
  }
});

test("pills sit in the pack's overlay safe zones (top banner, left column, bottom strip), away from the house", () => {
  const within = (p: { x: number; y: number; w: number; h: number }, z: { x: number; y: number; w: number; h: number }, slackX = 0, slackY = 0) =>
    p.x >= z.x - slackX && p.y >= z.y - slackY && p.x + p.w <= z.x + z.w + slackX && p.y + p.h <= z.y + z.h + slackY;
  // The banner is 122 units tall; a pill may hang 60 units below it into the sky.
  assert.ok(within(L.pills.solar, V4_SAFE_ZONES.top_banner, 0, 60));
  assert.ok(within(L.pills.grid, V4_SAFE_ZONES.top_banner, 0, 60));
  assert.ok(within(L.pills.battery, V4_SAFE_ZONES.left_info_column, 300, 120), "battery pill may extend right of the column into the lawn and down into the hedge, never into the house");
  assert.ok(L.pills.battery.y > V4_ANCHORS.battery_cabinet.y + 40, "battery pill sits below the cabinet anchor");
  assert.ok(L.pills.battery.x + L.pills.battery.w < 600, "battery pill ends on the lawn, before the house");
  assert.ok(within(L.pills.home, V4_SAFE_ZONES.bottom_strip, 0, 70));
  // Nothing covers the hardware anchors.
  for (const [name, a] of Object.entries(V4_ANCHORS)) {
    for (const [pn, p] of Object.entries(L.pills)) {
      const inside = a.x >= p.x && a.x <= p.x + p.w && a.y >= p.y && a.y <= p.y + p.h;
      assert.equal(inside, false, `${pn} pill covers the ${name} anchor`);
    }
  }
});

test("every route ends at the wall inverter and passes through its hardware anchors from the anchor map", () => {
  const p = L.paths();
  assert.deepEqual(L.inverter, V4_ANCHORS.wall_inverter);
  for (const id of ["solar", "solar2", "battery", "grid"] as const) {
    const e = endpoints(p[id]);
    assert.deepEqual(e.end, [V4_ANCHORS.wall_inverter.x, V4_ANCHORS.wall_inverter.y], `${id} ends at the inverter`);
  }
  assert.deepEqual(endpoints(p.home).start, [V4_ANCHORS.wall_inverter.x, V4_ANCHORS.wall_inverter.y]);
  assert.ok(passesThrough(p.solar, V4_ANCHORS.main_solar_array));
  assert.ok(passesThrough(p.solar2, V4_ANCHORS.garage_solar_array));
  assert.ok(passesThrough(p.battery, V4_ANCHORS.battery_cabinet));
  assert.ok(passesThrough(p.grid, V4_ANCHORS.grid_pylon));
  assert.ok(passesThrough(p.home, V4_ANCHORS.house_energy_center));
  // The anchor-map waypoints are honoured too.
  for (const [x, y] of [
    [758, 522],
    [868, 610],
    [975, 692],
  ]) assert.ok(passesThrough(p.solar, { x, y }), `solar via ${x},${y}`);
  for (const [x, y] of [
    [1288, 550],
    [1190, 626],
    [1088, 682],
  ]) assert.ok(passesThrough(p.grid, { x, y }), `grid via ${x},${y}`);
  for (const [x, y] of [
    [350, 622],
    [560, 636],
    [790, 670],
  ]) assert.ok(passesThrough(p.battery, { x, y }), `battery via ${x},${y}`);
});

test("routes start at their pill ports (solar, grid) or the hardware (battery, garage array) and the home route ends at its pill", () => {
  const p = L.paths();
  assert.deepEqual(endpoints(p.solar).start, [L.pills.solar.port.x, L.pills.solar.port.y]);
  assert.deepEqual(endpoints(p.grid).start, [L.pills.grid.port.x, L.pills.grid.port.y]);
  assert.deepEqual(endpoints(p.battery).start, [V4_ANCHORS.battery_cabinet.x, V4_ANCHORS.battery_cabinet.y]);
  assert.deepEqual(endpoints(p.solar2).start, [V4_ANCHORS.garage_solar_array.x, V4_ANCHORS.garage_solar_array.y]);
  assert.deepEqual(endpoints(p.home).end, [L.pills.home.port.x, L.pills.home.port.y]);
  assert.deepEqual(L.paths(), L.paths(), "static geometry");
});

test("at every overlay scale the pills stay inside the canvas, off the hardware anchors and off each other", () => {
  for (const k of [3.0, 3.1, 3.2, 3.4]) {
    const Lk = v4Layout(k);
    const list = Object.entries(Lk.pills);
    for (const [name, p] of list) {
      assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= Lk.width && p.y + p.h <= Lk.height, `${name} at k=${k}`);
      for (const [an, a] of Object.entries(V4_ANCHORS)) {
        const inside = a.x >= p.x && a.x <= p.x + p.w && a.y >= p.y && a.y <= p.y + p.h;
        assert.equal(inside, false, `${name} covers ${an} at k=${k}`);
      }
    }
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const [na, a] = list[i]!;
        const [nb, b] = list[j]!;
        const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
        assert.equal(overlap, false, `${na} overlaps ${nb} at k=${k}`);
      }
    }
    assert.ok(Lk.pills.battery.x + Lk.pills.battery.w < 760, `battery pill ends before the house at k=${k}`);
  }
  assert.equal(v4ScaleForWidth(390), 3.4);
  assert.equal(v4ScaleForWidth(700), 3.2);
  assert.equal(v4ScaleForWidth(1200), 3.0);
});

test("smoothPath passes through every point in order and degrades to a line for two points", () => {
  const pts = [
    { x: 0, y: 0 },
    { x: 10, y: 5 },
    { x: 20, y: 0 },
  ];
  const d = smoothPath(pts);
  assert.ok(d.startsWith("M 0.0 0.0 C"));
  assert.ok(d.endsWith("20.0 0.0"));
  assert.ok(d.includes(", 10.0 5.0 C"));
  assert.equal(smoothPath([pts[0]!, pts[2]!]), "M 0.0 0.0 L 20.0 0.0");
  assert.equal(smoothPath([pts[0]!]), "");
});
