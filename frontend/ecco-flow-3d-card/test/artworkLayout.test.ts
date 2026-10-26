// The V4 overlay layout: calibrated anchors, cards in the owner's zones that
// never cover equipment, straight-segment routes that start at the equipment,
// run to the ground-level entry corridor and rise vertically into the
// inverter, and fine information links from each card to its equipment.
import { test } from "node:test";
import assert from "node:assert/strict";
import { BEND_RADIUS, INFO_ROUTES, POWER_ROUTES, RISERS, RISER_TOP, V4_ANCHORS, V4_LAYOUT, routePath, smoothPath, v4Layout, v4ScaleForWidth, type RouteKey } from "../src/scene/iso.ts";
import { splitSolarFlows } from "../src/core/power.ts";

const L = V4_LAYOUT;
const A = V4_ANCHORS;
const at = (p: { x: number; y: number }): [number, number] => [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10];
const first = (key: RouteKey) => L.routes[key][0]!;
const last = (key: RouteKey) => L.routes[key][L.routes[key].length - 1]!;

test("calibrated anchors sit on the master plate's equipment (plate pixels)", () => {
  assert.deepEqual(at(A.inverter), [1002, 624]);
  assert.deepEqual(at(A.ground_entry), [1002, 712]);
  assert.deepEqual(at(A.battery_cabinet), [150, 512]);
  assert.deepEqual(at(A.pylon), [1297, 290]);
  assert.deepEqual(at(A.main_pv), [610, 335]);
  assert.deepEqual(at(A.main_pv_edge), [735, 440]);
  assert.deepEqual(at(A.garage_pv), [1140, 500]);
  assert.deepEqual(at(A.garage_pv_edge), [1000, 548]);
  assert.deepEqual(at(A.house), [752, 600]);
  assert.deepEqual(at(A.ev_charger), [1048, 655]);
  assert.equal(L.width, 1448);
  assert.equal(L.height, 1086);
});

test("information cards sit in the owner's zones at desktop scale", () => {
  const inZone = (p: { x: number; y: number; w: number; h: number }, z: [number, number, number, number], slack = 12) =>
    p.x >= z[0] - slack && p.y >= z[1] - slack && p.x + p.w <= z[2] + slack && p.y + p.h <= z[3] + slack;
  assert.ok(inZone(L.pills.solar, [35, 90, 330, 225]), "solar upper-left");
  assert.ok(inZone(L.pills.grid, [1110, 90, 1410, 225]), "grid upper-right");
  assert.ok(inZone(L.pills.battery, [35, 715, 400, 875]), "battery lower-left (wider than the zone: power, state, FE-1 time and the ring)");
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

test("every power route starts at its equipment and ends with one straight vertical riser into the inverter's underside", () => {
  assert.deepEqual(at(first("solarMain")), at(A.main_pv_edge));
  assert.deepEqual(at(first("solarGarage")), at(A.garage_pv_edge));
  assert.deepEqual(at(first("battery")), at(A.battery_cabinet));
  assert.deepEqual(at(first("grid")), at(A.pylon));
  for (const key of ["solarMain", "solarGarage", "battery", "grid"] as const) {
    const pts = L.routes[key];
    const end = pts[pts.length - 1]!;
    const before = pts[pts.length - 2]!;
    assert.equal(end.y, RISER_TOP, `${key} ends at the inverter underside`);
    assert.equal(before.x, end.x, `${key} final segment is vertical`);
    assert.ok(before.y >= L.entry.y0 && before.y <= L.entry.y1, `${key} rises from the ground entry corridor`);
    assert.ok(end.x >= L.entry.x0 && end.x <= L.entry.x1, `${key} riser within the entry bundle`);
    assert.equal(RISERS[key].x, end.x);
  }
  // Home: drawn from the riser top to the house entry (forward = consumption).
  const home = L.routes.home;
  assert.equal(home[0]!.y, RISER_TOP);
  assert.equal(home[0]!.x, home[1]!.x, "home riser is vertical");
  assert.ok(home[1]!.y >= L.entry.y0 && home[1]!.y <= L.entry.y1);
  assert.equal(home[home.length - 1]!.y, A.house.y, "home route ends at the house entry height");
  assert.ok(Math.abs(home[home.length - 1]!.x - A.house.x) <= 8, "home route ends at the house entry (next to the downpipe)");
});

test("risers are distinct, closely spaced tracks and no route crosses another inside the entry corridor", () => {
  const xs = Object.values(RISERS).map((r) => r.x);
  assert.equal(new Set(xs).size, xs.length, "every riser has its own x");
  assert.ok(Math.max(...xs) - Math.min(...xs) <= 28, "the bundle stays within 28 plate px (inside the unit's 958-1042 footprint)");
  const gaps = [...xs].sort((a, b) => a - b).map((x, i, arr) => (i ? x - arr[i - 1]! : 99));
  assert.ok(Math.min(...gaps) >= 6, "risers are at least 6 plate px apart so they read as distinct tracks");
  // Shallower ground track -> riser further left, so no riser crosses a track that continues past it.
  const sorted = Object.values(RISERS).sort((a, b) => a.ground - b.ground);
  for (let i = 1; i < sorted.length; i++) assert.ok(sorted[i]!.x > sorted[i - 1]!.x, "tracks nest without crossing");
});

test("routes are structured: few vertices, axis-aligned or gently sloped segments, small fillets", () => {
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    assert.ok(pts.length <= 8, `${key} has at most 8 vertices (${pts.length})`);
    for (let i = 1; i < pts.length; i++) {
      const dx = Math.abs(pts[i]!.x - pts[i - 1]!.x);
      const dy = Math.abs(pts[i]!.y - pts[i - 1]!.y);
      const slope = Math.min(dx, dy) / Math.max(dx, dy, 1);
      assert.ok(slope <= 0.5 || Math.abs(slope - 1) < 0.25, `${key} segment ${i} is horizontal, vertical, a perspective slope (<= 27 deg) or ~45 deg (slope ${slope.toFixed(2)})`);
    }
  }
  assert.ok(BEND_RADIUS <= 14);
  const d = routePath([
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
  ]);
  assert.equal(d, "M 0.0 0.0 L 88.0 0.0 Q 100.0 0.0 100.0 12.0 L 100.0 100.0");
  assert.equal(routePath([{ x: 1, y: 2 }, { x: 3, y: 4 }]), "M 1.0 2.0 L 3.0 4.0");
  assert.equal(routePath([{ x: 1, y: 2 }]), "");
  // Short segments shrink the fillet rather than overshooting.
  assert.ok(routePath([{ x: 0, y: 0 }, { x: 6, y: 0 }, { x: 6, y: 100 }]).includes("L 3.0 0.0 Q 6.0 0.0 6.0 3.0"));
});

test("information links join each card's port to its equipment and never carry power", () => {
  assert.deepEqual(at(first("solarInfo")), at(L.pills.solar.port));
  assert.ok(last("solarInfo").x > 500 && last("solarInfo").x < 620 && last("solarInfo").y > 250 && last("solarInfo").y < 320, "solar info link ends on the main array's upper-left modules");
  assert.deepEqual(at(first("batteryInfo")), at(L.pills.battery.port));
  assert.deepEqual(at(last("batteryInfo")), at(A.battery_cabinet));
  assert.deepEqual(at(first("gridInfo")), at(L.pills.grid.port));
  assert.deepEqual(at(last("gridInfo")), at(A.pylon));
  assert.deepEqual(at(last("homeInfo")), at(L.pills.home.port));
  assert.ok(Math.abs(first("homeInfo").x - A.house.x) <= 8 && Math.abs(first("homeInfo").y - A.house.y) <= 8, "home info link starts at the house entry");
  assert.deepEqual([...POWER_ROUTES, ...INFO_ROUTES].sort(), Object.keys(L.routes).sort());
});

test("the grid route follows the pylon and the hedge behind the garage and stays clear of the car, the garage door and the windows", () => {
  const pts = L.routes.grid;
  assert.deepEqual(at(pts[1]!), [1300, 426], "down the pylon to its foot");
  assert.ok(pts[2]!.y < 460 && pts[2]!.x < 960, "along the hedge above the garage roof to the house / garage corner");
  for (const p of pts) {
    assert.ok(!(p.x > 1190 && p.y > 640), `grid vertex ${p.x},${p.y} over the car`);
    assert.ok(!(p.x > 1130 && p.x < 1330 && p.y > 560 && p.y < 690), `grid vertex ${p.x},${p.y} over the garage door`);
    assert.ok(!(p.x > 800 && p.x < 925 && p.y > 510 && p.y < 690), `grid vertex ${p.x},${p.y} over the front window`);
  }
});

test("the battery route follows the garden path, the patio edge and the terrace front, then the ground corridor", () => {
  const pts = L.routes.battery;
  assert.deepEqual(at(pts[1]!), [330, 478], "end of the garden path at the patio corner");
  assert.ok(Math.abs(pts[2]!.x - pts[1]!.x) < 20 && pts[2]!.y > pts[1]!.y + 100, "down the patio's left edge");
  const slope = (pts[3]!.y - pts[2]!.y) / (pts[3]!.x - pts[2]!.x);
  const slope2 = (pts[4]!.y - pts[3]!.y) / (pts[4]!.x - pts[3]!.x);
  assert.ok(slope > 0.1 && slope < 0.3 && slope2 > 0.1 && slope2 < 0.3, "the patio and terrace front edges run at the plate's perspective slope");
});

test("the solar routes follow the roofs: eave to the house / garage corner, garage roof edge to the same corner, then straight down", () => {
  const m = L.routes.solarMain;
  assert.ok(m[1]!.y > m[0]!.y && m[2]!.y > m[1]!.y && m[2]!.x > m[1]!.x && m[1]!.x > m[0]!.x, "main: along the eave towards the corner (perspective slope)");
  assert.equal(m[2]!.x, m[3]!.x, "main: straight down the corner");
  const g = L.routes.solarGarage;
  assert.ok(g[1]!.x < g[0]!.x && Math.abs(g[1]!.y - g[0]!.y) < 40, "garage: along the roof edge to the corner");
  assert.equal(g[1]!.x, g[2]!.x, "garage: straight down the corner");
  assert.ok(Math.abs(m[2]!.x - g[1]!.x) <= 12 && Math.abs(g[1]!.x - L.routes.grid[3]!.x) <= 12, "the three descents share the corner as closely spaced tracks");
});

test("solar split never double counts: card carries the total, branches carry their own arrays, else the total once", () => {
  const two = splitSolarFlows(6400, 3400, 3000, 2);
  assert.equal(two.card.magnitudeW, 6400);
  assert.equal(two.main.magnitudeW, 3400);
  assert.equal(two.garage?.magnitudeW, 3000);
  const totalOnly = splitSolarFlows(2500, null, null, 2);
  assert.equal(totalOnly.main.magnitudeW, 2500);
  assert.equal(totalOnly.garage, null);
  const trickle = splitSolarFlows(4, 3, 1, 2);
  assert.ok(trickle.card.idle && trickle.main.idle && trickle.garage!.idle);
});

test("smoothPath (vector scene helper) passes through every point in order", () => {
  const pts = [
    { x: 0, y: 0 },
    { x: 10, y: 5 },
    { x: 20, y: 0 },
  ];
  assert.ok(smoothPath(pts).startsWith("M 0.0 0.0 C"));
  assert.equal(smoothPath([pts[0]!, pts[2]!]), "M 0.0 0.0 L 20.0 0.0");
});
