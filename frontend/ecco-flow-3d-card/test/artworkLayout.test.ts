// The V4 overlay layout: calibrated anchors, cards in the owner's zones that
// never cover equipment, straight-segment routes that start at the equipment,
// run to the ground-level entry corridor and rise vertically into the
// inverter, and fine information links from each card to its equipment.
import { test } from "node:test";
import assert from "node:assert/strict";
import { BATTERY_WAYPOINTS, BEND_RADIUS, INFO_ROUTES, POWER_ROUTES, RISERS, RISER_TOP, V4_ANCHORS, V4_LAYOUT, V4_PAVING, routePath, smoothPath, v4Layout, v4ScaleForWidth, type RouteKey } from "../src/scene/iso.ts";
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
  assert.equal(L.routes.solarMain[1]!.x, A.main_pv_frame.x, "main: leaves the frame straight down");
  assert.deepEqual(at(L.routes.solarGarage[0]!), at(A.garage_pv_frame));
  assert.equal(L.routes.solarGarage[1]!.x, A.garage_pv_frame.x, "garage: leaves the frame straight down");
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
  assert.deepEqual(at(A.chimney), [952, 300]);
  assert.deepEqual(at(A.fascia_start), [758, 448]);
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
    assert.ok(pts.length <= (key === "battery" ? 12 : 7), `${key} has few vertices (${pts.length})`);
    for (let i = 1; i < pts.length; i++) {
      const dx = Math.abs(pts[i]!.x - pts[i - 1]!.x);
      const dy = Math.abs(pts[i]!.y - pts[i - 1]!.y);
      const slope = Math.min(dx, dy) / Math.max(dx, dy, 1);
      // Screen-axis runs (right-angle routing) or a run that follows a real sloped edge (fascia, patio border, terrace wall, lower path).
      const axisAligned = dx < 1 || dy < 1;
      assert.ok(axisAligned || slope <= 0.4 || Math.abs(slope - 1) < 0.25, `${key} segment ${i} is axis-aligned or follows a real edge (slope ${slope.toFixed(2)})`);
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

test("routing is deliberate right-angle routing: most turns are 90 degrees and no two consecutive segments are both sloped", () => {
  let turns = 0;
  let right = 0;
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    for (let i = 1; i < pts.length - 1; i++) {
      const a = pts[i - 1]!;
      const b = pts[i]!;
      const c = pts[i + 1]!;
      const v1 = { x: b.x - a.x, y: b.y - a.y };
      const v2 = { x: c.x - b.x, y: c.y - b.y };
      const dot = v1.x * v2.x + v1.y * v2.y;
      const cos = dot / (Math.hypot(v1.x, v1.y) * Math.hypot(v2.x, v2.y) || 1);
      turns++;
      if (Math.abs(cos) < 0.35) right++;
      const sloped = (v: { x: number; y: number }) => Math.abs(v.x) >= 1 && Math.abs(v.y) >= 1 && Math.min(Math.abs(v.x), Math.abs(v.y)) / Math.max(Math.abs(v.x), Math.abs(v.y)) > 0.05;
      assert.ok(!(sloped(v1) && sloped(v2) && key !== "battery"), `${key} bend ${i} joins two sloped runs`);
    }
  }
  assert.ok(right / turns >= 0.7, `at least 70% of turns are right angles (${right}/${turns})`);
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
      assert.ok(
        Math.abs(x - A.downpipe.x) <= 14 || Math.abs(x - A.door_post.x) <= 2 || Math.abs(x - A.building_corner.x) <= 6 || Math.abs(x - A.lawn_transition.x) <= 2,
        `${key} descends on a real vertical feature or the marked buried transition, got x=${x}`
      );
    }
  }
});

test("the grid route lands on the chimney and follows the building corner straight down to the floor, clear of the car, the door and the panels", () => {
  const pts = L.routes.grid;
  assert.deepEqual(at(pts[0]!), at(A.pylon));
  assert.equal(pts[1]!.y, A.pylon.y, "level service drop from the pylon");
  assert.equal(pts[1]!.x, A.chimney.x, "lands on the chimney's right face");
  assert.ok(A.chimney.x >= 915 && A.chimney.x <= 962, "the chimney stack spans 915-962");
  assert.equal(pts[2]!.x, pts[1]!.x, "straight down the chimney, the gable and the building corner");
  assert.ok(pts[2]!.y >= L.entry.y0 && pts[2]!.y <= L.entry.y1, "to the floor");
  assert.ok(pts[2]!.x > 945, "the corner track passes right of the bush at the corner's foot (907-945)");
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]!;
    const b = pts[i]!;
    for (const f of [0.25, 0.5, 0.75]) {
      const x = a.x + (b.x - a.x) * f;
      const y = a.y + (b.y - a.y) * f;
      assert.ok(!(x > 1010 && x < 1320 && y > 440 && y < 560), `grid segment ${i} crosses the garage panels at ${x.toFixed(0)},${y.toFixed(0)}`);
      assert.ok(!(x > 1190 && y > 640), `grid segment ${i} over the car`);
      assert.ok(!(x > 1130 && x < 1330 && y > 560 && y < 690), `grid segment ${i} over the garage door`);
    }
  }
});

test("the battery route follows the real paving: rear path, buried transition, patio edge, terrace wall, both steps, lower path, drive", () => {
  const pts = L.routes.battery;
  assert.equal(pts.length, BATTERY_WAYPOINTS.length, "every waypoint is named for the debug view");
  assert.deepEqual(at(pts[0]!), at(A.battery_cabinet));
  assert.deepEqual(at(pts[1]!), [310, 502], "end of the rear garden path");
  assert.equal(pts[2]!.x, pts[1]!.x, "buried transition straight across the lawn edge");
  assert.deepEqual(at(pts[2]!), [310, 570], "the patio's left corner");
  assert.ok(Math.abs(pts[1]!.x - A.lawn_transition.x) <= 1, "the transition is the marked anchor");
  const slopePatio = (pts[3]!.y - pts[2]!.y) / (pts[3]!.x - pts[2]!.x);
  assert.ok(slopePatio > 0.3 && slopePatio < 0.45, "patio front edge at the plate's perspective slope");
  // Steps: two short vertical drops between the upper landing (y ~694) and the lower paving (y ~721), separated by a tread.
  assert.equal(pts[5]!.y, pts[4]!.y, "across the upper landing on a level run");
  assert.ok(pts[6]!.x === pts[5]!.x && pts[6]!.y - pts[5]!.y >= 20 && pts[6]!.y - pts[5]!.y <= 28, "down step 1 (landing lip and riser) in one vertical");
  assert.ok(pts[7]!.y === pts[6]!.y && pts[7]!.x > pts[6]!.x, "along the tread on a level run");
  assert.ok(pts[8]!.x === pts[7]!.x && pts[8]!.y - pts[7]!.y >= 10 && pts[8]!.y - pts[7]!.y <= 16, "down step 2");
  assert.ok(pts[8]!.y >= 718 && pts[8]!.y <= 724, "onto the lower paving");
  const slopeLower = (pts[9]!.y - pts[8]!.y) / (pts[9]!.x - pts[8]!.x);
  assert.ok(slopeLower > 0.08 && slopeLower < 0.2, "lower path along the front bed to the drive");
  assert.equal(pts[10]!.y, pts[9]!.y, "drive paving run is level to the ground convergence");
  assert.ok(pts[10]!.x >= L.entry.x0 && pts[10]!.x <= L.entry.x1 && pts[10]!.y >= L.entry.y0 && pts[10]!.y <= L.entry.y1, "ends in the ground convergence");
  // The route never cuts across the lawn: between the rear path and the drive every vertex lies on a traced paving line (within 6 px).
  const onPaving = (p: { x: number; y: number }) =>
    V4_PAVING.some((e) => {
      const [a, b] = [e.points[0]!, e.points[1]!];
      const t = Math.max(0, Math.min(1, ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / ((b.x - a.x) ** 2 + (b.y - a.y) ** 2 || 1)));
      return Math.hypot(p.x - (a.x + t * (b.x - a.x)), p.y - (a.y + t * (b.y - a.y))) <= 6;
    });
  for (const i of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) assert.ok(onPaving(pts[i]!), `battery waypoint ${i + 1} (${pts[i]!.x},${pts[i]!.y}) lies on traced paving`);
});

test("the solar routes: main array frame -> roof junction -> fascia -> building corner -> floor; garage frame -> fascia -> garage wall -> floor", () => {
  const m = L.routes.solarMain;
  assert.deepEqual(at(m[0]!), at(A.main_pv_frame), "main: starts on the panel frame");
  assert.equal(m[1]!.x, m[0]!.x, "main: straight down from the frame to the roof junction");
  assert.deepEqual(at(m[2]!), at(A.fascia_start), "main: along the porch ridge to the fascia start");
  assert.ok(Math.abs(m[3]!.x - A.building_corner.x) <= 6 && m[3]!.y > m[2]!.y, "main: along the main roof fascia to the building corner");
  assert.equal(m[3]!.x, m[4]!.x, "main: straight down the corner");
  assert.ok(m[4]!.y >= L.entry.y0 && m[4]!.y <= L.entry.y1, "main: to the floor");
  const g = L.routes.solarGarage;
  assert.deepEqual(at(g[0]!), at(A.garage_pv_frame), "garage: starts on the panel frame corner");
  assert.equal(g[1]!.x, g[0]!.x, "garage: straight down from the frame to the fascia");
  assert.equal(g[2]!.x, A.door_post.x, "garage: along the fascia to the garage wall");
  assert.ok(g[2]!.y > g[1]!.y && g[2]!.y - g[1]!.y < 30, "garage: the fascia's perspective slope");
  assert.equal(g[2]!.x, g[3]!.x, "garage: straight down the garage wall");
  assert.ok(g[3]!.y >= 740, "garage: a deep floor run before the convergence");
  const h = L.routes.home;
  assert.ok(Math.abs(h[2]!.x - A.downpipe.x) <= 14, "home: up the service wall beside the downpipe");
  assert.equal(h[2]!.y, h[1]!.y, "home: level foundation run");
  // The two corner descents are distinct adjacent tracks.
  assert.ok(Math.abs(m[3]!.x - L.routes.grid[1]!.x) >= 4 && Math.abs(m[3]!.x - L.routes.grid[1]!.x) <= 10, "main-array and grid corner tracks are adjacent but distinct");
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
      if (Math.abs(a.y - b.y) > 12 || Math.min(a.y, b.y) < 680) continue; // only near-horizontal ground-level runs
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
  // The battery's drive run is the deepest left track, below every other turn.
  const solarTurn = L.routes.solarMain[4]!;
  const homeTurn = L.routes.home[1]!;
  const gridTurn = L.routes.grid[2]!;
  const batteryGround = L.routes.battery[10]!.y;
  assert.ok(batteryGround > solarTurn.y && batteryGround > homeTurn.y && batteryGround > gridTurn.y, "battery passes under the other turns");
  // The grid's corner track turns to its riser above the main-array track's turn, which turns above the home run.
  assert.ok(gridTurn.y < solarTurn.y && solarTurn.y < homeTurn.y, "corner tracks nest: grid above main array above home");
  // The main-array corner run passes under the grid's turn (grid track is 6 px to its right).
  assert.ok(L.routes.solarMain[3]!.x < L.routes.grid[1]!.x, "main-array track is the left of the two corner tracks");
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
