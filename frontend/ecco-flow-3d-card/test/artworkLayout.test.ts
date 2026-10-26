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

test("solar routes start on the panel frames and reach the cable exits with a short stub", () => {
  // Main array lower-right frame edge: 640,442 -> 751,380 (y = 442 - 0.5586 (x - 640)); the attachment lies on it.
  const onMainFrame = 442 - 0.5586 * (A.main_pv_frame.x - 640);
  assert.ok(Math.abs(A.main_pv_frame.y - onMainFrame) <= 3, `main frame point sits on the frame edge (expected y ~${onMainFrame.toFixed(1)})`);
  // Garage array lower frame edge: 1045,507 -> 1130,557; the attachment is at its lower-left corner.
  assert.ok(Math.abs(A.garage_pv_frame.x - 1045) <= 4 && Math.abs(A.garage_pv_frame.y - 507) <= 4, "garage frame point at the lower-left frame corner");
  assert.ok(Math.hypot(A.main_pv_edge.x - A.main_pv_frame.x, A.main_pv_edge.y - A.main_pv_frame.y) <= 30, "main stub is short");
  assert.ok(Math.hypot(A.garage_pv_edge.x - A.garage_pv_frame.x, A.garage_pv_edge.y - A.garage_pv_frame.y) <= 45, "garage stub is short");
  assert.deepEqual(at(L.routes.solarMain[0]!), at(A.main_pv_frame));
  assert.deepEqual(at(L.routes.solarMain[1]!), at(A.main_pv_edge));
  assert.deepEqual(at(L.routes.solarGarage[0]!), at(A.garage_pv_frame));
  assert.deepEqual(at(L.routes.solarGarage[1]!), at(A.garage_pv_edge));
  assert.ok(A.main_pv.x > 420 && A.main_pv.x < 740 && A.main_pv.y > 250 && A.main_pv.y < 440, "info-link target on the main array");
  const solarInfoEnd = L.routes.solarInfo[L.routes.solarInfo.length - 1]!;
  assert.ok(solarInfoEnd.x > 420 && solarInfoEnd.x < 740 && solarInfoEnd.y > 250 && solarInfoEnd.y < 440, "solar info link ends on the array");
});

test("calibrated anchors sit on the master plate's equipment (plate pixels)", () => {
  assert.deepEqual(at(A.inverter), [1002, 624]);
  assert.deepEqual(at(A.ground_entry), [1002, 722]);
  assert.deepEqual(at(A.downpipe), [748, 620]);
  assert.deepEqual(at(A.door_post), [1104, 640]);
  assert.deepEqual(at(A.battery_cabinet), [150, 512]);
  assert.deepEqual(at(A.pylon), [1297, 290]);
  assert.deepEqual(at(A.main_pv), [610, 335]);
  assert.deepEqual(at(A.main_pv_frame), [700, 409]);
  assert.deepEqual(at(A.main_pv_edge), [716, 425]);
  assert.deepEqual(at(A.garage_pv), [1140, 500]);
  assert.deepEqual(at(A.garage_pv_frame), [1044, 508]);
  assert.deepEqual(at(A.garage_pv_edge), [1048, 545]);
  assert.deepEqual(at(A.building_corner), [948, 600]);
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
  assert.deepEqual(at(first("solarMain")), at(A.main_pv_frame));
  assert.deepEqual(at(first("solarGarage")), at(A.garage_pv_frame));
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
  // On each side the shallower ground track takes the outer riser, so no riser crosses a track that continues past it.
  const left = Object.values(RISERS).filter((r) => r.side === "left").sort((a, b) => a.ground - b.ground);
  const right = Object.values(RISERS).filter((r) => r.side === "right").sort((a, b) => a.ground - b.ground);
  for (let i = 1; i < left.length; i++) assert.ok(left[i]!.x > left[i - 1]!.x, "left tracks nest without crossing");
  for (let i = 1; i < right.length; i++) assert.ok(right[i]!.x < right[i - 1]!.x, "right tracks nest without crossing");
  assert.ok(Math.max(...left.map((r) => r.x)) < Math.min(...right.map((r) => r.x)), "left and right groups do not interleave");
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

test("every wall descent is on a real vertical feature (downpipe, building corner, garage wall) and never on the unit itself", () => {
  const unit = { x0: 958, x1: 1042 };
  for (const key of ["solarMain", "solarGarage", "battery", "grid", "home"] as const) {
    const pts = L.routes[key];
    const riserStart = key === "home" ? 0 : pts.length - 2;
    for (let i = 1; i < pts.length; i++) {
      if (i === riserStart + 1) continue; // the riser itself
      const a = pts[i - 1]!;
      const b = pts[i]!;
      const vertical = Math.abs(a.x - b.x) < 1 && Math.abs(a.y - b.y) > 40;
      if (!vertical) continue;
      const x = a.x;
      assert.ok(x < unit.x0 || x > unit.x1, `${key} descends at x=${x}, over the unit (${unit.x0}-${unit.x1})`);
      assert.ok(Math.abs(x - A.downpipe.x) <= 14 || Math.abs(x - A.door_post.x) <= 2 || Math.abs(x - A.building_corner.x) <= 2, `${key} descends on a real vertical feature, got x=${x}`);
    }
  }
});

test("the grid route follows the pylon, the hedge behind the garage roof and the building corner, clear of the car, the door, the panels and the windows", () => {
  const pts = L.routes.grid;
  assert.deepEqual(at(pts[1]!), [1300, 418], "down the pylon");
  assert.equal(pts[2]!.x, A.building_corner.x, "along the hedge to the building corner");
  assert.ok(pts[2]!.y < 445, "the hedge line stays above the garage panels");
  assert.equal(pts[3]!.x, A.building_corner.x, "straight down the corner");
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]!;
    const b = pts[i]!;
    for (const f of [0.25, 0.5, 0.75]) {
      const x = a.x + (b.x - a.x) * f;
      const y = a.y + (b.y - a.y) * f;
      assert.ok(!(x > 1010 && x < 1320 && y > 440 && y < 560), `grid segment ${i} crosses the garage panels at ${x.toFixed(0)},${y.toFixed(0)}`);
    }
  }
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
  assert.ok(slope > 0.1 && slope < 0.3 && slope2 > 0.1 && slope2 <= 0.5, "the patio and terrace front edges run at the plate's perspective slope");
  assert.ok(Math.abs(pts[4]!.x - A.downpipe.x) <= 20, "joins the house foundation at the service wall");
});

test("the solar routes follow the roofs and real walls: main array down the porch edge and the downpipe, garage array along its eave and down the garage wall", () => {
  const m = L.routes.solarMain;
  assert.ok(Math.abs(m[2]!.x - A.downpipe.x) <= 6 && m[2]!.y > m[1]!.y, "main: from the cable exit down the porch roof valley to the downpipe head");
  assert.equal(m[2]!.x, m[3]!.x, "main: straight down the downpipe");
  assert.ok(m[3]!.y >= L.entry.y0 - 10, "main: to ground level");
  const g = L.routes.solarGarage;
  assert.equal(g[2]!.x, A.door_post.x, "garage: along the eave to the wall left of the door");
  assert.ok(g[2]!.y > g[1]!.y && g[2]!.y - g[1]!.y < 40, "garage: the eave's perspective slope");
  assert.equal(g[2]!.x, g[3]!.x, "garage: straight down the garage wall");
  const h = L.routes.home;
  assert.ok(Math.abs(h[2]!.x - A.downpipe.x) <= 14 && h[2]!.x !== m[1]!.x, "home: up the service wall beside the downpipe on its own track");
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

test("no two routes cross in the entry area: tracks are ordered so a horizontal run passes below every riser it crosses", () => {
  // Horizontal ground runs and vertical risers only, in plate pixels.
  const vert = (key: RouteKey) => {
    const pts = L.routes[key];
    const [a, b] = key === "home" ? [pts[1]!, pts[0]!] : [pts[pts.length - 2]!, pts[pts.length - 1]!];
    return { x: a.x, yTop: Math.min(a.y, b.y), yBottom: Math.max(a.y, b.y) };
  };
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1]!;
      const b = pts[i]!;
      if (Math.abs(a.y - b.y) > 12) continue; // only near-horizontal runs
      const x0 = Math.min(a.x, b.x);
      const x1 = Math.max(a.x, b.x);
      for (const other of POWER_ROUTES) {
        if (other === key) continue;
        const r = vert(other);
        if (r.x <= x0 || r.x >= x1) continue;
        const yAt = a.y + ((b.y - a.y) * (r.x - a.x)) / (b.x - a.x || 1);
        assert.ok(yAt > r.yBottom - 0.5, `${key} ground run crosses the ${other} riser at x=${r.x} (run y ${yAt.toFixed(1)}, riser bottom ${r.yBottom})`);
      }
    }
  }
  // The battery's terrace run passes below the main-array descent on the downpipe wall, not through it.
  const solarTurn = L.routes.solarMain[3]!;
  const batteryAtWall = L.routes.battery[4]!;
  assert.ok(batteryAtWall.y > solarTurn.y, "battery passes under the main-array turn");
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
