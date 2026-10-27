// The V4 overlay layout, V2 geometry: every power route runs from its
// equipment along the plate's building axes (real-world right angles in
// perspective), clear of every surveyed obstacle, without loops, and rises
// vertically into the inverter's underside from below; information cards
// stay clear of the equipment and of each other at every overlay scale, and
// their connectors reach the right equipment.
import { test } from "node:test";
import assert from "node:assert/strict";
import { BEND_RADIUS, CARD_KEYS, INFO_ROUTES, POWER_ROUTES, V4_ANCHORS, V4_LAYOUT, V4_PERSPECTIVE, V4_ROUTING, mergeRouting, routePath, routeSpans, routeTracks, smoothPath, v4Layout, v4ScaleForWidth, type RouteKey } from "../src/scene/iso.ts";
import { axisCorner, axisError, classifySegment } from "../src/scene/perspective.ts";
import { splitSolarFlows } from "../src/core/power.ts";

type P = { x: number; y: number };
const L = V4_LAYOUT;
const A = V4_ANCHORS;
const VP = V4_PERSPECTIVE;
const SCALES = [2.0, 2.3, 2.8, 3.2];
/** Axis tolerance (degrees) for a route segment; segments shorter than MIN_SEG are fillet-sized and exempt. */
const AXIS_TOL = 3;
const MIN_SEG = 6;
const ROOF_AXES = ["X", "Y", "Z", "S_main", "S_garage"];
const GROUND_AXES = ["X", "Y", "Z"];
// The grid comes down the garage roof's verge, so it may use the roof slopes too.
const AXES: Record<string, string[]> = { solarMain: ROOF_AXES, solarGarage: ROOF_AXES, battery: GROUND_AXES, grid: ROOF_AXES, home: GROUND_AXES };

const len = (a: P, b: P) => Math.hypot(b.x - a.x, b.y - a.y);
const segs = (pts: P[]) => pts.slice(1).map((b, i) => [pts[i]!, b] as const);
/** Is segment i (vertex i to i + 1) of a power route inside one of its buried stretches? */
const buriedSeg = (key: string, i: number) => (L.buried[key as "battery"] ?? []).some(([a, b]) => i >= a && i < b);
/** Vertices where a route goes into or comes out of a buried stretch (straight pass-throughs, not bends). */
const buriedEnds = (key: string) => new Set((L.buried[key as "battery"] ?? []).flat());

function inPoly(p: P, poly: P[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i]!;
    const b = poly[j]!;
    if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

function cross(a: P, b: P, c: P, d: P): boolean {
  const o = (p: P, q: P, r: P) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x));
  return o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0;
}

function distToSeg(p: P, a: P, b: P): number {
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / ((b.x - a.x) ** 2 + (b.y - a.y) ** 2 || 1)));
  return Math.hypot(p.x - (a.x + t * (b.x - a.x)), p.y - (a.y + t * (b.y - a.y)));
}

test("the perspective model matches the plate's measured edges and corners computed from it are exact", () => {
  for (const axis of ["X", "Y", "Z", "S_main", "S_garage"]) assert.ok(VP[axis], `axis ${axis}`);
  // Measured on the plate (survey 2026-10-26): each must classify on its own axis within 2.5 degrees.
  const measured: Array<[string, P, P]> = [
    ["X", { x: 960, y: 665.8 }, { x: 1107, y: 725.3 }], // inverter wall plinth top
    ["X", { x: 297, y: 571.4 }, { x: 490, y: 643.8 }], // patio border / lawn junction
    ["X", { x: 480, y: 377.2 }, { x: 677, y: 442.4 }], // Array 1 bottom frame edge
    ["Y", { x: 841, y: 739.4 }, { x: 975, y: 699.1 }], // foot of the dining steps
    ["Y", { x: 1134, y: 596.3 }, { x: 1313, y: 547.3 }], // garage door lintel
    ["Y", { x: 130, y: 543 }, { x: 320, y: 501.8 }], // rear garden path, lawn edge
    ["Z", { x: 1109.5, y: 575.5 }, { x: 1109.5, y: 738.5 }], // garage front corner
    ["S_main", { x: 809.7, y: 306.8 }, { x: 691.5, y: 442 }], // Array 1 right frame edge
    ["S_garage", { x: 987.2, y: 481.9 }, { x: 1114.7, y: 544.6 }], // Array 2 left frame edge
  ];
  for (const [axis, a, b] of measured) {
    const c = classifySegment(a, b, VP);
    assert.equal(c.axis, axis, `${axis} edge ${a.x},${a.y} -> ${b.x},${b.y} classified ${c.axis}`);
    assert.ok(c.error <= 2.5, `${axis} edge within 2.5 deg (${c.error.toFixed(2)})`);
  }
  // axisCorner gives the point on both axis lines.
  const c = axisCorner({ x: 300, y: 600 }, "X", { x: 900, y: 400 }, "Z", VP);
  assert.ok(axisError({ x: 300, y: 600 }, c, VP.X!) < 0.05 && axisError({ x: 900, y: 400 }, c, VP.Z!) < 0.05);
  const c2 = axisCorner({ x: 845, y: 745 }, "Y", { x: 1105, y: 773 }, "X", VP);
  assert.ok(axisError({ x: 845, y: 745 }, c2, VP.Y!) < 0.05 && axisError({ x: 1105, y: 773 }, c2, VP.X!) < 0.05);
});

test("every power route segment follows a building axis (perspective right angles), with real bends only", () => {
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    assert.ok(pts.length >= 3, `${key} has a route`);
    const ends = buriedEnds(key);
    let prevAxis = "";
    segs(pts).forEach(([a, b], i) => {
      const c = classifySegment(a, b, VP, AXES[key]);
      if (len(a, b) < MIN_SEG) return;
      assert.ok(c.error <= AXIS_TOL, `${key} segment ${i + 1} (${a.x},${a.y} -> ${b.x},${b.y}) is ${c.error.toFixed(2)} deg off its best axis ${c.axis}`);
      if (ends.has(i) && c.axis === prevAxis) {
        // Going into or out of a duct: the cable runs straight on, so the vertex must be a pass-through on one line.
        assert.ok(distToSeg(a, pts[i - 1]!, b) <= 0.5, `${key} vertex ${i + 1} is a straight pass-through into or out of its duct`);
      } else {
        assert.notEqual(c.axis, prevAxis, `${key} segments ${i} and ${i + 1} run on the same axis: a redundant vertex, not a bend`);
      }
      prevAxis = c.axis;
    });
  }
  assert.ok(BEND_RADIUS <= 8, "small corner rounding");
});

test("every power route rises vertically into the inverter's underside from below, each through its own gland", () => {
  const u = L.underside;
  // The underside edge follows the unit's bottom surface: an X line.
  assert.ok(axisError(u.from, u.to, VP.X!) <= AXIS_TOL, "the connection bar follows the perspective of the inverter's bottom surface");
  const glands: number[] = [];
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    const [gland, below] = key === "home" ? [pts[0]!, pts[1]!] : [pts[pts.length - 1]!, pts[pts.length - 2]!];
    assert.ok(distToSeg(gland, u.from, u.to) <= 1.5, `${key} ends on the inverter underside (${gland.x},${gland.y})`);
    assert.ok(below.y > gland.y + 12, `${key} enters from below`);
    assert.ok(classifySegment(below, gland, VP).axis === "Z" && axisError(below, gland, VP.Z!) <= 1.5, `${key} riser is vertical`);
    glands.push(gland.x);
  }
  const sorted = [...glands].sort((a, b) => a - b);
  sorted.slice(1).forEach((x, i) => assert.ok(x - sorted[i]! >= 5, "glands at least 5 px apart: distinct tracks"));
});

test("power routes start on their equipment and the home route ends at the house connection", () => {
  const near = (p: P, q: P, r: number) => len(p, q) <= r;
  assert.ok(L.routing.obstacles.length >= 15, "the obstacle survey is loaded");
  const eq = (label: RegExp) => L.routing.equipment.find((e) => label.test(e.label))!;
  const inBox = (p: P, e: { x: number; y: number; w: number; h: number }, slack = 4) => p.x >= e.x - slack && p.x <= e.x + e.w + slack && p.y >= e.y - slack && p.y <= e.y + e.h + slack;
  assert.ok(inBox(L.routes.solarMain[0]!, eq(/Array 1/)), "Array 1 route starts on the Array 1 frame");
  assert.ok(inBox(L.routes.solarGarage[0]!, eq(/Array 2/)), "Array 2 route starts on the Array 2 frame");
  assert.ok(inBox(L.routes.battery[0]!, eq(/[Bb]attery/)), "battery route starts at the cabinet");
  assert.ok(near(L.routes.grid[0]!, A.pylon_light, 260) && inBox(L.routes.grid[0]!, eq(/[Pp]ylon/)), "grid route starts on the pylon");
  const h = L.routes.home;
  assert.ok(near(h[h.length - 1]!, A.house, 2), "home route ends at the house connection");
});

test("the home feed runs up beside the inverter, through the internal corner and along the house wall onto the wall light", () => {
  const s = segs(L.routes.home).map(([a, b]) => ({ a, b, axis: classifySegment(a, b, VP, GROUND_AXES).axis, len: len(a, b) }));
  const face = L.underside.from.x; // the inverter front face's left edge
  const up = s.findIndex((g) => g.axis === "Z" && g.b.y < g.a.y && g.len >= 80);
  assert.ok(up > 0 && s[up]!.a.x < face && face - s[up]!.a.x <= 6, "a long vertical run up the inverter's left side, just beside it");
  const wall = s.findIndex((g) => g.axis === "Y" && g.len >= 100);
  assert.ok(wall > up && s[wall]!.b.x < s[wall]!.a.x, "then a run along the house wall, heading away from the garage");
  const last = s[s.length - 1]!;
  assert.ok(last.axis === "Z" && last.b.y > last.a.y, "it drops onto the wall light");
  assert.ok(L.routing.obstacles.some((o) => /wall_light_gable_by_corner/.test(o.label) && inPoly({ x: A.house.x, y: A.house.y + 4 }, o.points)), "the house connection sits on the wall light");
  assert.ok(s.reduce((t, g) => t + g.len, 0) >= 300, "long enough to read as feeding the house");
});

test("no drawn power route crosses a surveyed obstacle, and no route loops on itself or crosses another route", () => {
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    for (const [i, [a, b]] of segs(pts).entries()) {
      // A buried duct runs under beds and planters out of sight; everything that is drawn must clear them.
      if (buriedSeg(key, i)) continue;
      const n = Math.max(2, Math.ceil(len(a, b) / 2));
      for (let i = 1; i < n; i++) {
        const p = { x: a.x + ((b.x - a.x) * i) / n, y: a.y + ((b.y - a.y) * i) / n };
        for (const o of L.routing.obstacles) assert.ok(!inPoly(p, o.points), `${key} crosses ${o.label} at ${p.x.toFixed(0)},${p.y.toFixed(0)}`);
      }
    }
    const s = segs(pts);
    for (let i = 0; i < s.length; i++) for (let j = i + 2; j < s.length; j++) assert.ok(!cross(s[i]![0], s[i]![1], s[j]![0], s[j]![1]), `${key} segments ${i + 1} and ${j + 1} cross: a loop`);
  }
  for (let i = 0; i < POWER_ROUTES.length; i++) {
    for (let j = i + 1; j < POWER_ROUTES.length; j++) {
      for (const [a, b] of segs(L.routes[POWER_ROUTES[i]!])) {
        for (const [c, d] of segs(L.routes[POWER_ROUTES[j]!])) assert.ok(!cross(a, b, c, d), `${POWER_ROUTES[i]} crosses ${POWER_ROUTES[j]}`);
      }
    }
  }
});

test("hidden stretches are left out of the drawn route, while the particles still follow the whole centreline", () => {
  const S = L.spans();
  const P = L.paths();
  assert.ok((L.buried.battery ?? []).length >= 3, "the battery is hidden behind the patio-corner planting, the front bed and the planters");
  for (const key of POWER_ROUTES) {
    const spans = L.buried[key] ?? [];
    if (!spans.length) {
      assert.equal(S[key].drawn, P[key], `${key} is drawn whole`);
      assert.equal(S[key].buried, "", `${key} has no duct`);
      continue;
    }
    const pts = L.routes[key];
    for (const [a, b] of spans) {
      assert.ok(a > 0 && b < pts.length - 1, `${key} duct ${a}..${b} starts and ends inside the route: both ends are drawn`);
      assert.ok(S[key].buried.includes(`M ${pts[a]!.x.toFixed(1)} ${pts[a]!.y.toFixed(1)}`), `${key} duct starts at vertex ${a + 1}`);
    }
    // Drawn: one run before and one after each duct, joined end to end with the duct (nothing lost, nothing doubled).
    const runs = S[key].drawn.split("M ").filter(Boolean);
    assert.equal(runs.length, spans.length + 1, `${key} drawn runs`);
    assert.ok(P[key].startsWith(`M ${pts[0]!.x.toFixed(1)}`) && P[key].endsWith(`${pts[pts.length - 1]!.x.toFixed(1)} ${pts[pts.length - 1]!.y.toFixed(1)}`), `${key} particle path runs end to end`);
  }
  // A route is hidden only where it passes behind a surveyed obstacle (each hidden stretch runs through one), and every
  // stretch between them is drawn and long enough not to vanish under its own fillets.
  for (const key of POWER_ROUTES) {
    const pts = L.routes[key];
    const spans = [...(L.buried[key] ?? [])].sort((p, q) => p[0] - q[0]);
    const runLen = (from: number, to: number) => segs(pts.slice(from, to + 1)).reduce((s, [p, q]) => s + len(p, q), 0);
    let at = 0;
    for (const [a, b] of spans) {
      assert.ok(runLen(at, a) >= MIN_SEG, `${key} drawn run ${at + 1}..${a + 1} is ${runLen(at, a).toFixed(1)} px`);
      const mid = segs(pts.slice(a, b + 1)).flatMap(([p, q]) => [0.25, 0.5, 0.75].map((f) => ({ x: p.x + (q.x - p.x) * f, y: p.y + (q.y - p.y) * f })));
      assert.ok(mid.some((m) => L.routing.obstacles.some((o) => inPoly(m, o.points))), `${key} hidden stretch ${a + 1}..${b + 1} is behind an obstacle`);
      at = b;
    }
    assert.ok(runLen(at, pts.length - 1) >= MIN_SEG, `${key} last drawn run`);
  }
  // What the renderer is handed: particles on the whole centreline, strokes and chevrons on the drawn part, the mask on the duct.
  for (const key of POWER_ROUTES) {
    const t = routeTracks(L, key);
    assert.equal(t.track, P[key], `${key} particles follow the whole route`);
    assert.equal(t.drawn, S[key].buried ? S[key].drawn : P[key], `${key} draws its visible part`);
    assert.equal(t.duct, S[key].buried, `${key} masks exactly its duct`);
  }
  assert.ok(routeTracks(L, "battery").duct && routeTracks(L, "battery").drawn !== routeTracks(L, "battery").track);
});

test("each information connector stays clear of its own flow's power routes at every scale", () => {
  const own: Record<string, string[]> = { solarInfoMain: ["solarMain"], solarInfoGarage: ["solarGarage"], batteryInfo: ["battery"], gridInfo: ["grid"], homeInfo: ["home"] };
  for (const k of SCALES) {
    const Lk = v4Layout(k);
    for (const key of INFO_ROUTES) {
      for (const route of own[key]!) {
        for (const [a, b] of segs(Lk.routes[key])) {
          for (const [c, d] of segs(Lk.routes[route as RouteKey])) assert.ok(!cross(a, b, c, d), `${key} crosses ${route} at k=${k}`);
        }
      }
    }
    // The battery connector rises straight from its card to the cabinet's front corner at every card size.
    const bi = Lk.routes.batteryInfo;
    assert.ok(bi.every((p) => Math.abs(p.x - 127.5) < 0.01), `batteryInfo is one vertical at k=${k}`);
  }
});

test("information connectors stay off the surveyed obstacles; only the battery's rises through the foreground planting its card sits in", () => {
  const allowed: Record<string, string[]> = { batteryInfo: ["foreground:hedge_front_row", "lawn:hedge_lower_left", "lawn:flowerbed_lower_left"] };
  for (const k of SCALES) {
    const Lk = v4Layout(k);
    for (const key of INFO_ROUTES) {
      for (const [a, b] of segs(Lk.routes[key])) {
        const n = Math.max(2, Math.ceil(len(a, b) / 2));
        for (let i = 1; i < n; i++) {
          const p = { x: a.x + ((b.x - a.x) * i) / n, y: a.y + ((b.y - a.y) * i) / n };
          for (const o of Lk.routing.obstacles) {
            if ((allowed[key] ?? []).includes(o.label)) continue;
            assert.ok(!inPoly(p, o.points), `${key} crosses ${o.label} at ${p.x.toFixed(0)},${p.y.toFixed(0)} (k=${k})`);
          }
        }
      }
    }
  }
});

test("at every overlay scale the cards stay inside the canvas, off the equipment and off each other, with ports on their own edges", () => {
  for (const k of SCALES) {
    const Lk = v4Layout(k);
    const list = CARD_KEYS.map((n) => [n, Lk.pills[n]] as const);
    for (const [name, p] of list) {
      assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= Lk.width && p.y + p.h <= Lk.height, `${name} inside at k=${k}`);
      for (const e of Lk.routing.equipment) {
        const overlap = p.x < e.x + e.w && e.x < p.x + p.w && p.y < e.y + e.h && e.y < p.y + p.h;
        assert.equal(overlap, false, `${name} card covers ${e.label} at k=${k}`);
      }
      const onEdge = (Math.abs(p.port.x - p.x) < 0.01 || Math.abs(p.port.x - p.x - p.w) < 0.01 || Math.abs(p.port.y - p.y) < 0.01 || Math.abs(p.port.y - p.y - p.h) < 0.01) && p.port.x >= p.x && p.port.x <= p.x + p.w && p.port.y >= p.y && p.port.y <= p.y + p.h;
      assert.ok(onEdge, `${name} port on its own edge at k=${k}`);
    }
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const [na, a] = list[i]!;
        const [nb, b] = list[j]!;
        const gap = 6;
        const overlap = a.x < b.x + b.w + gap && b.x < a.x + a.w + gap && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap;
        assert.equal(overlap, false, `${na} overlaps ${nb} at k=${k}`);
      }
    }
  }
  assert.equal(v4ScaleForWidth(390), 3.2);
  assert.equal(v4ScaleForWidth(768), 2.3);
  assert.equal(v4ScaleForWidth(1200), 2.0);
});

test("information connectors leave their card, bend only at perspective right angles, never cross another card and reach the right equipment", () => {
  for (const k of SCALES) {
    const Lk = v4Layout(k);
    const box = (label: RegExp) => Lk.routing.equipment.find((e) => label.test(e.label))!;
    const target: Record<string, { x: number; y: number; w: number; h: number }> = {
      solarInfoMain: box(/^Array 1/),
      solarInfoGarage: box(/^Array 2/),
      batteryInfo: box(/[Bb]attery/),
      gridInfo: { x: A.pylon_light.x - 6, y: A.pylon_light.y - 6, w: 12, h: 12 },
      homeInfo: box(/^Inverter/),
    };
    const card: Record<string, string> = { solarInfoMain: "solar", solarInfoGarage: "solar", batteryInfo: "battery", gridInfo: "grid", homeInfo: "home" };
    for (const key of INFO_ROUTES) {
      const pts = Lk.routes[key];
      const pill = Lk.pills[card[key] as "solar"];
      const p0 = pts[0]!;
      assert.ok(p0.x >= pill.x - 0.01 && p0.x <= pill.x + pill.w + 0.01 && p0.y >= pill.y - 0.01 && p0.y <= pill.y + pill.h + 0.01, `${key} starts on its card at k=${k}`);
      const endPt = pts[pts.length - 1]!;
      const t = target[key]!;
      assert.ok(endPt.x >= t.x && endPt.x <= t.x + t.w && endPt.y >= t.y && endPt.y <= t.y + t.h, `${key} ends on its equipment at k=${k} (${endPt.x.toFixed(0)},${endPt.y.toFixed(0)})`);
      // The first leg leaves the card outward from its port side (never back across the card).
      if (pts.length > 1) {
        const side = Lk.routing.info[key].port.side;
        const q = pts[1]!;
        const out = side === "top" ? q.y <= p0.y + 0.5 : side === "bottom" ? q.y >= p0.y - 0.5 : side === "left" ? q.x <= p0.x + 0.5 : q.x >= p0.x - 0.5;
        assert.ok(out, `${key} leaves its card outward through the ${side} edge at k=${k}`);
      }
      let prev: { axis: string; a: P; b: P } | null = null;
      for (const [a, b] of segs(pts)) {
        if (len(a, b) < MIN_SEG) continue;
        const c = classifySegment(a, b, VP, GROUND_AXES);
        assert.ok(c.error <= AXIS_TOL, `${key} segment ${a.x.toFixed(0)},${a.y.toFixed(0)} -> ${b.x.toFixed(0)},${b.y.toFixed(0)} off-axis by ${c.error.toFixed(1)} at k=${k}`);
        // Two legs on one axis may only continue straight on (an elbow that collapsed to nothing): never a kink or a reversal.
        if (prev && c.axis === prev.axis) {
          const onward = (prev.b.x - prev.a.x) * (b.x - a.x) + (prev.b.y - prev.a.y) * (b.y - a.y) > 0;
          assert.ok(onward && distToSeg(a, prev.a, b) <= 0.5, `${key} turns between two legs on the ${c.axis} axis at k=${k}: a kink or a reversal, not a bend`);
        }
        prev = { axis: c.axis, a, b };
        // A connector must not run through any other card.
        for (const n of CARD_KEYS) {
          if (n === card[key]) continue;
          const q = Lk.pills[n];
          for (const f of [0.1, 0.3, 0.5, 0.7, 0.9]) {
            const x = a.x + (b.x - a.x) * f;
            const y = a.y + (b.y - a.y) * f;
            assert.ok(!(x > q.x && x < q.x + q.w && y > q.y && y < q.y + q.h), `${key} runs through the ${n} card at k=${k}`);
          }
        }
      }
    }
  }
});

test("the debug overlay names every vertex of every power route", () => {
  for (const key of POWER_ROUTES) assert.equal(L.routing.nodes[key].length, L.routes[key].length, `${key} node names`);
});

test("routing is isolated data: a configuration override changes geometry only, never the defaults; malformed entries are ignored", () => {
  const before = JSON.stringify(V4_ROUTING);
  const grid = [{ x: 1300, y: 290 }, { x: 1300, y: 700 }, { x: 990, y: 700 }];
  const over = v4Layout(2.0, { anchors: { pylon_light: { x: 1300 } }, power: { grid }, bend: { grid: 4 }, cards: { home: { at: { x: 800, y: 1000 } } }, info: { gridInfo: { port: { side: "left", at: 0.5 } } } });
  assert.equal(over.anchors.pylon_light.x, 1300);
  assert.equal(over.anchors.pylon_light.label, V4_ROUTING.anchors.pylon_light.label, "label kept when only x is overridden");
  assert.deepEqual(over.routes.grid, grid);
  assert.deepEqual(over.routes.battery, V4_ROUTING.power.battery, "other routes unchanged");
  assert.equal(over.bend.grid, 4);
  assert.equal(over.routing.cards.home.align, V4_ROUTING.cards.home.align, "placement merges per key");
  assert.equal(over.routing.info.gridInfo.port.side, "left");
  assert.deepEqual(over.routing.info.gridInfo.points, V4_ROUTING.info.gridInfo.points);
  assert.equal(JSON.stringify(V4_ROUTING), before, "defaults not mutated");
  const bad = mergeRouting(V4_ROUTING, { power: { grid: [{ x: 1, y: Number.NaN }] as never }, perspective: { X: { x: Number.NaN, y: 0 } } });
  assert.deepEqual(bad.power.grid, V4_ROUTING.power.grid);
  assert.deepEqual(bad.perspective.X, V4_ROUTING.perspective.X);
  // A replaced route is drawn whole unless the override buries part of it again; malformed spans are dropped.
  const battery = [{ x: 140, y: 520 }, { x: 600, y: 700 }, { x: 985.5, y: 686.5 }, { x: 985.5, y: 632.8 }];
  assert.deepEqual(mergeRouting(V4_ROUTING, { power: { battery } }).buried.battery, undefined);
  assert.deepEqual(mergeRouting(V4_ROUTING, { power: { battery }, buried: { battery: [[1, 2], [2, 1], [0.5, 2]] as never } }).buried.battery, [[1, 2]]);
  assert.deepEqual(mergeRouting(V4_ROUTING, { buried: { battery: [] } }).buried.battery, [], "the duct can be switched off (the whole route is then drawn)");
  assert.deepEqual(v4Layout(2.0, { anchors: { pylon_light: { x: 1300 } } }).buried, V4_ROUTING.buried, "other overrides keep the duct");
  // Hand-written YAML can hold anything: unknown keys, wrong types, half entries. None of it may break the card.
  const junk = [
    { cards: { Home: { at: { x: 1, y: 2 } } } },
    { cards: { home: { align: 7 } }, cardsCompact: { home: "x" } },
    { info: { homeInfo: { card: "garage", port: { side: "middle", at: "0.4" }, elbow: ["Q", 3] } } },
    { info: { gridInfo: { elbow: null } } },
    { traces: "none", obstacles: [{ label: 1 }], equipment: [{ label: "x" }], nodes: { grid: [1, 2] }, bend: { grid: -1, home: "4" } },
    { anchors: { house: "here" }, underside: { from: { x: "1" } }, compactFrom: "2", perspective: "flat", power: "none", buried: "yes" },
    { info: { homeInfo: { elbow: ["X", "X"] }, gridInfo: { elbow: ["toString", "Z"], card: "constructor" } }, cards: { toString: { at: { x: 1, y: 1 } } } },
    JSON.parse('{"perspective": {"__proto__": {"vp": {"x": 1, "y": 2}}}, "bend": {"__proto__": 3, "grid": 4}}'),
  ] as never[];
  for (const ov of junk) {
    for (const k of SCALES) assert.doesNotThrow(() => v4Layout(k, ov).paths(), `override ${JSON.stringify(ov)} at k=${k}`);
  }
  const ignored = mergeRouting(V4_ROUTING, junk[2]!);
  assert.deepEqual(ignored.info.homeInfo, V4_ROUTING.info.homeInfo, "a malformed connector override changes nothing");
  assert.deepEqual(mergeRouting(V4_ROUTING, junk[0]!).cards, V4_ROUTING.cards, "an unknown card key is ignored");
  const junk4 = mergeRouting(V4_ROUTING, junk[4]!);
  assert.equal(junk4.traces, V4_ROUTING.traces);
  assert.equal(junk4.obstacles, V4_ROUTING.obstacles);
  assert.equal(junk4.equipment, V4_ROUTING.equipment);
  assert.deepEqual(junk4.nodes, V4_ROUTING.nodes);
  assert.deepEqual(junk4.bend, V4_ROUTING.bend);
  assert.equal(mergeRouting(V4_ROUTING, junk[3]!).info.gridInfo.elbow, undefined, "elbow: null makes the connector straight");
  const junk6 = mergeRouting(V4_ROUTING, junk[6]!);
  assert.deepEqual(junk6.info, V4_ROUTING.info, "an elbow on one axis twice, or inherited names as axis or card, are ignored");
  assert.deepEqual(junk6.cards, V4_ROUTING.cards);
  const junk7 = mergeRouting(V4_ROUTING, junk[7]!);
  assert.equal(Object.getPrototypeOf(junk7.perspective), Object.prototype, "a __proto__ key cannot replace an object's prototype");
  assert.equal(junk7.bend.grid, 4);
  // Moving a pinned port by side or fraction drops the pin; x: null unpins; a new x pins again.
  const moved = mergeRouting(V4_ROUTING, { info: { homeInfo: { port: { side: "top", at: 0.9 } } } }).info.homeInfo.port;
  assert.equal(moved.x, undefined);
  assert.equal(moved.at, 0.9);
  assert.equal(mergeRouting(V4_ROUTING, { info: { batteryInfo: { port: { x: null } } } } as never).info.batteryInfo.port.x, undefined);
  assert.equal(mergeRouting(V4_ROUTING, { info: { homeInfo: { port: { x: 1140 } } } } as never).info.homeInfo.port.x, 1140);
  assert.equal(JSON.stringify(V4_ROUTING), before, "defaults still not mutated");
});

test("routePath draws straight runs with small fillets and hits both ends exactly", () => {
  const d = routePath([
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
  ]);
  assert.equal(d, `M 0.0 0.0 L ${(100 - BEND_RADIUS).toFixed(1)} 0.0 Q 100.0 0.0 100.0 ${BEND_RADIUS.toFixed(1)} L 100.0 100.0`);
  assert.equal(routePath([{ x: 1, y: 2 }, { x: 3, y: 4 }]), "M 1.0 2.0 L 3.0 4.0");
  assert.equal(routePath([{ x: 1, y: 2 }]), "");
  assert.ok(routePath([{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 100 }]).includes("L 2.8 0.0 Q 4.0 0.0 4.0 1.2"), "short segments shrink the fillet to 0.3 of the segment");
  const parts = routeSpans([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 0 }, { x: 30, y: 0 }, { x: 40, y: 0 }], [[1, 3]]);
  assert.equal(parts.drawn, "M 0.0 0.0 L 10.0 0.0 M 30.0 0.0 L 40.0 0.0");
  assert.equal(parts.buried, "M 10.0 0.0 L 17.0 0.0 Q 20.0 0.0 23.0 0.0 L 30.0 0.0");
  assert.deepEqual(routeSpans([{ x: 0, y: 0 }, { x: 10, y: 0 }], [[0, 5]]), { drawn: "M 0.0 0.0 L 10.0 0.0", buried: "" }, "a span past the end is ignored");
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

test("every route key has a layout: five power routes and five information connectors", () => {
  assert.deepEqual([...POWER_ROUTES, ...INFO_ROUTES].sort(), (Object.keys(L.routes) as RouteKey[]).sort());
});
