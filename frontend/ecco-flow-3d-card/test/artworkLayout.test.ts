// The V4 overlay layout: calibrated hardware anchors, information cards in
// the owner's zones that never cover equipment, and routes that touch their
// card AND their equipment and meet at the wall inverter.
import { test } from "node:test";
import assert from "node:assert/strict";
import { V4_ANCHORS, V4_LAYOUT, smoothPath, v4Layout, v4ScaleForWidth } from "../src/scene/iso.ts";
import { splitSolarFlows } from "../src/core/power.ts";

const L = V4_LAYOUT;
const A = V4_ANCHORS;

function nums(d: string): number[] {
  return d.match(/-?\d+(\.\d+)?/g)!.map(Number);
}
function endpoints(d: string): { start: [number, number]; end: [number, number] } {
  const n = nums(d);
  return { start: [n[0]!, n[1]!], end: [n[n.length - 2]!, n[n.length - 1]!] };
}
function passesThrough(d: string, p: { x: number; y: number }): boolean {
  return d.includes(`${p.x.toFixed(1)} ${p.y.toFixed(1)}`);
}
const at = (p: { x: number; y: number }): [number, number] => [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10];

test("calibrated anchors sit on the master plate's equipment (plate pixels)", () => {
  assert.deepEqual(at(A.inverter), [1000, 622]);
  assert.deepEqual(at(A.battery_cabinet), [150, 512]);
  assert.deepEqual(at(A.pylon), [1297, 290]);
  assert.deepEqual(at(A.main_pv), [610, 335]);
  assert.deepEqual(at(A.garage_pv), [1140, 500]);
  assert.deepEqual(at(A.house), [752, 600]);
  assert.deepEqual(at(A.ev_charger), [1048, 655]);
  assert.equal(L.width, 1448);
  assert.equal(L.height, 1086);
  assert.deepEqual(at(L.inverter), at(A.inverter));
});

test("information cards sit in the owner's zones at desktop scale", () => {
  const inZone = (p: { x: number; y: number; w: number; h: number }, z: [number, number, number, number], slack = 12) =>
    p.x >= z[0] - slack && p.y >= z[1] - slack && p.x + p.w <= z[2] + slack && p.y + p.h <= z[3] + slack;
  assert.ok(inZone(L.pills.solar, [35, 90, 330, 225]), "solar upper-left");
  assert.ok(inZone(L.pills.grid, [1110, 90, 1410, 225]), "grid upper-right");
  // The battery card is wider than its zone: it holds power, state, the FE-1 time and the SOC ring without collisions.
  assert.ok(inZone(L.pills.battery, [35, 715, 400, 875], 12), "battery lower-left");
  assert.ok(inZone(L.pills.home, [650, 875, 970, 1030]), "home lower centre-right");
});

test("at every overlay scale the cards stay inside the canvas, off every hardware anchor and off each other", () => {
  for (const k of [2.0, 2.3, 2.8, 3.2]) {
    const Lk = v4Layout(k);
    const list = Object.entries(Lk.pills);
    for (const [name, p] of list) {
      assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= Lk.width && p.y + p.h <= Lk.height, `${name} inside at k=${k}`);
      for (const [an, a] of Object.entries(A)) {
        const inside = a.x >= p.x - 6 && a.x <= p.x + p.w + 6 && a.y >= p.y - 6 && a.y <= p.y + p.h + 6;
        assert.equal(inside, false, `${name} covers ${an} at k=${k}`);
      }
      assert.ok(p.port.x >= p.x && p.port.x <= p.x + p.w && p.port.y >= p.y && p.port.y <= p.y + p.h, `${name} port on its own edge at k=${k}`);
    }
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const [na, a] = list[i]!;
        const [nb, b] = list[j]!;
        const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
        assert.equal(overlap, false, `${na} overlaps ${nb} at k=${k}`);
      }
    }
  }
  assert.equal(v4ScaleForWidth(390), 3.2);
  assert.equal(v4ScaleForWidth(768), 2.3);
  assert.equal(v4ScaleForWidth(1200), 2.0);
});

test("every system is card -> equipment -> inverter (or the reverse for home), touching both the card and the hardware", () => {
  const P = L.paths();
  assert.deepEqual(endpoints(P.solarCard).start, at(L.pills.solar.port));
  assert.deepEqual(endpoints(P.solarCard).end, at(A.main_pv));
  assert.deepEqual(endpoints(P.solarMain).start, at(A.main_pv));
  assert.deepEqual(endpoints(P.solarMain).end, at(A.inverter));
  assert.deepEqual(endpoints(P.solarGarage).start, at(A.garage_pv));
  assert.deepEqual(endpoints(P.solarGarage).end, at(A.inverter));
  assert.deepEqual(endpoints(P.battery).start, at(L.pills.battery.port));
  assert.ok(passesThrough(P.battery, A.battery_cabinet));
  assert.deepEqual(endpoints(P.battery).end, at(A.inverter));
  assert.deepEqual(endpoints(P.grid).start, at(L.pills.grid.port));
  assert.ok(passesThrough(P.grid, A.pylon));
  assert.deepEqual(endpoints(P.grid).end, at(A.inverter));
  assert.deepEqual(endpoints(P.home).start, at(A.inverter));
  assert.ok(passesThrough(P.home, A.house));
  assert.deepEqual(endpoints(P.home).end, at(L.pills.home.port));
  assert.deepEqual(L.paths(), L.paths(), "static geometry");
});

test("the grid route behind the garage stays clear of the car and the garage door", () => {
  const n = nums(L.paths().grid);
  const pts: Array<[number, number]> = [];
  for (let i = 0; i + 1 < n.length; i += 2) pts.push([n[i]!, n[i + 1]!]);
  for (const [x, y] of pts) {
    assert.ok(!(x > 1190 && y > 640), `grid route point ${x},${y} over the car`);
    assert.ok(!(x > 1130 && x < 1330 && y > 560 && y < 690), `grid route point ${x},${y} over the garage door`);
  }
});

test("solar split never double counts: card carries the total, branches carry their own arrays, else the total once", () => {
  const two = splitSolarFlows(6400, 3400, 3000, 2);
  assert.equal(two.card.magnitudeW, 6400);
  assert.equal(two.main.magnitudeW, 3400);
  assert.equal(two.garage?.magnitudeW, 3000);
  const uneven = splitSolarFlows(5100, 4200, 900, 2);
  assert.equal(uneven.main.magnitudeW, 4200);
  assert.equal(uneven.garage?.magnitudeW, 900);
  const oneArray = splitSolarFlows(2500, 2500, null, 1);
  assert.equal(oneArray.main.magnitudeW, 2500);
  assert.equal(oneArray.garage, null);
  const totalOnly = splitSolarFlows(2500, null, null, 2);
  assert.equal(totalOnly.main.magnitudeW, 2500, "no per-array readings: the main route carries the total once");
  assert.equal(totalOnly.garage, null);
  const partial = splitSolarFlows(3400, 3400, null, 2);
  assert.equal(partial.main.magnitudeW, 3400);
  assert.equal(partial.garage?.unknown, true, "a missing second array is unknown, not zero");
  const trickle = splitSolarFlows(4, 3, 1, 2);
  assert.ok(trickle.card.idle && trickle.main.idle && trickle.garage!.idle, "below the threshold every solar route is idle");
  const none = splitSolarFlows(null, null, null, 2);
  assert.ok(none.card.unknown && none.main.unknown && none.garage === null);
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
