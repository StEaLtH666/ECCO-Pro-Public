// Scene geometry: everything sits inside the viewBox and every power path
// starts and ends exactly at its port.
import { test } from "node:test";
import assert from "node:assert/strict";
import { INVERTER_PORT, PILLS, SCENE_H, SCENE_W, flowPaths, iso, box, cubic } from "../src/scene/iso.ts";

function endpoints(d: string): { start: [number, number]; end: [number, number] } {
  const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
  return { start: [nums[0]!, nums[1]!], end: [nums[nums.length - 2]!, nums[nums.length - 1]!] };
}

test("pills and the inverter port lie inside the scene", () => {
  for (const [name, p] of Object.entries(PILLS)) {
    assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= SCENE_W && p.y + p.h <= SCENE_H, name);
    assert.ok(p.port.x >= p.x && p.port.x <= p.x + p.w && p.port.y >= p.y && p.port.y <= p.y + p.h, `${name} port on its pill`);
  }
  assert.ok(INVERTER_PORT.x > 0 && INVERTER_PORT.x < SCENE_W && INVERTER_PORT.y > 0 && INVERTER_PORT.y < SCENE_H);
});

test("pills do not overlap each other", () => {
  const list = Object.entries(PILLS);
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const [na, a] = list[i]!;
      const [nb, b] = list[j]!;
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      assert.equal(overlap, false, `${na} overlaps ${nb}`);
    }
  }
});

test("each flow path runs between its pill (or the battery cabinet) and the inverter port", () => {
  const p = flowPaths();
  const close = (a: [number, number], b: { x: number; y: number }, tol = 1) => Math.hypot(a[0] - b.x, a[1] - b.y) <= tol;
  assert.ok(close(endpoints(p.solar).start, PILLS.solar.port));
  assert.ok(close(endpoints(p.solar).end, INVERTER_PORT));
  assert.ok(close(endpoints(p.grid).start, PILLS.grid.port));
  assert.ok(close(endpoints(p.grid).end, INVERTER_PORT));
  assert.ok(close(endpoints(p.home).start, INVERTER_PORT));
  assert.ok(close(endpoints(p.home).end, PILLS.home.port));
  assert.ok(close(endpoints(p.battery).end, INVERTER_PORT));
  const bStart = endpoints(p.battery).start;
  assert.ok(bStart[0] < PILLS.home.x && bStart[1] > 200 && bStart[1] < PILLS.battery.y, "battery path leaves the cabinet, left of the house, above its pill");
});

test("paths are static geometry: calling again yields the same strings (direction never reshapes a path)", () => {
  assert.deepEqual(flowPaths(), flowPaths());
});

test("the isometric projection is consistent", () => {
  const o = iso(0, 0, 0);
  const up = iso(0, 0, 1);
  assert.equal(up.x, o.x);
  assert.ok(up.y < o.y, "z goes up the screen");
  const right = iso(1, 0, 0);
  assert.ok(right.x > o.x && right.y > o.y, "+x goes right and down");
  const left = iso(0, 1, 0);
  assert.ok(left.x < o.x && left.y > o.y, "+y goes left and down");
  const faces = box(0, 0, 2, 2, 0, 1);
  assert.equal(faces.top.split(" ").length, 4);
  assert.equal(cubic([o, up, right, left]).startsWith("M "), true);
  assert.equal(cubic([o, up]), "");
});
