// Isometric projection and geometry helpers for the scene. Pure functions
// so the layout can be unit-tested without a DOM.

export const SCENE_W = 400;
export const SCENE_H = 470;

/** One iso unit in pixels. */
export const UNIT = 13;
const COS = 0.866 * UNIT;
const SIN = 0.5 * UNIT;
export const ORIGIN_X = 205;
export const ORIGIN_Y = 262;

export interface Pt {
  x: number;
  y: number;
}

/** Projects an iso-space point (x right-down, y left-down, z up) to scene pixels. */
export function iso(x: number, y: number, z = 0): Pt {
  return { x: ORIGIN_X + (x - y) * COS, y: ORIGIN_Y + (x + y) * SIN - z * UNIT };
}

export function pts(points: Pt[]): string {
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

/** Polygon point strings for the three visible faces of an axis-aligned iso box. */
export interface BoxFaces {
  top: string;
  /** The face at y = y1 (faces the viewer's left-front). */
  left: string;
  /** The face at x = x1 (faces the viewer's right-front). */
  right: string;
}

export function box(x0: number, y0: number, x1: number, y1: number, z0: number, z1: number): BoxFaces {
  return {
    top: pts([iso(x0, y0, z1), iso(x1, y0, z1), iso(x1, y1, z1), iso(x0, y1, z1)]),
    left: pts([iso(x0, y1, z0), iso(x1, y1, z0), iso(x1, y1, z1), iso(x0, y1, z1)]),
    right: pts([iso(x1, y0, z0), iso(x1, y1, z0), iso(x1, y1, z1), iso(x1, y0, z1)]),
  };
}

/** A parallelogram on the y = y1 wall plane (front-left wall): x from xa..xb, z from za..zb. */
export function wallRectLeft(y: number, xa: number, xb: number, za: number, zb: number): string {
  return pts([iso(xa, y, za), iso(xb, y, za), iso(xb, y, zb), iso(xa, y, zb)]);
}

/** A parallelogram on the x = x1 wall plane (front-right wall): y from ya..yb, z from za..zb. */
export function wallRectRight(x: number, ya: number, yb: number, za: number, zb: number): string {
  return pts([iso(x, ya, za), iso(x, yb, za), iso(x, yb, zb), iso(x, ya, zb)]);
}

/**
 * A point on the gable roof plane that rises from the eave at y = yEave,
 * z = zEave to the ridge at y = yRidge, z = zRidge; `t` in [0, 1] walks
 * from eave to ridge.
 */
export function roofPoint(x: number, t: number, yEave: number, zEave: number, yRidge: number, zRidge: number): Pt {
  return iso(x, yEave + (yRidge - yEave) * t, zEave + (zRidge - zEave) * t);
}

/** Cubic path string through the given control points: "M p0 C p1 p2 p3 [C ...]". */
export function cubic(points: Pt[]): string {
  if (points.length < 4) return "";
  let d = `M ${points[0]!.x.toFixed(1)} ${points[0]!.y.toFixed(1)}`;
  for (let i = 1; i + 2 < points.length; i += 3) {
    const a = points[i]!;
    const b = points[i + 1]!;
    const c = points[i + 2]!;
    d += ` C ${a.x.toFixed(1)} ${a.y.toFixed(1)}, ${b.x.toFixed(1)} ${b.y.toFixed(1)}, ${c.x.toFixed(1)} ${c.y.toFixed(1)}`;
  }
  return d;
}

/** Scene constants shared by the geometry and the flow paths. */
export const HOUSE = { x0: -1, y0: -3, x1: 7, y1: 3, z: 4.2, ridgeZ: 6.6, ridgeY: 0 };
export const GARAGE = { x0: 7, y0: -1, x1: 11, y1: 3, z: 2.5 };
export const BATTERY = { x0: -6.2, y0: 4.2, x1: -4.6, y1: 5.4, z: 2.4 };
/** The inverter: a wall box on the house's front-left wall. */
export const INVERTER = { x0: 5.3, x1: 6.3, z0: 1.25, z1: 2.45, y: HOUSE.y1 };
/** Pylon base (2-D drawing anchored here). */
export const PYLON_BASE = iso(10.6, -4.8);

/** Where every flow path meets the inverter (scene pixels). */
export const INVERTER_PORT: Pt = (() => {
  const p = iso((INVERTER.x0 + INVERTER.x1) / 2, INVERTER.y, (INVERTER.z0 + INVERTER.z1) / 2);
  return { x: p.x + 1, y: p.y + 2 };
})();

/** Pill boxes (scene pixels). Each line starts or ends at the pill's `port`. */
export interface PillBox {
  x: number;
  y: number;
  w: number;
  h: number;
  port: Pt;
}

export const PILLS = {
  solar: { x: 8, y: 10, w: 150, h: 58, port: { x: 58, y: 68 } },
  grid: { x: 246, y: 22, w: 146, h: 58, port: { x: 330, y: 80 } },
  home: { x: 214, y: 176, w: 140, h: 54, port: { x: 236, y: 230 } },
  battery: { x: 8, y: 388, w: 184, h: 70, port: { x: 108, y: 388 } },
} satisfies Record<string, PillBox>;

// ---------------------------------------------------------------------------
// Artwork layout for the approved V4 scene pack (ten 1448 x 1086 variants of
// one fixed-perspective house). The overlays (cards, routes, particles) are
// drawn by the card on top of the plate, which carries no lines, labels or
// values. Every anchor, route, card placement, connector and debug trace is
// DATA in ./routing-v4.ts (overridable from the configuration); this file only
// turns that data into card boxes, SVG paths and the information links.

import {
  BEND_RADIUS,
  V4_ROUTING,
  mergeRouting,
  type AnchorPt,
  type AnchorKey,
  type CardKey,
  type CardPlacement,
  type InfoLink,
  type InfoRouteKey,
  type PowerRouteKey,
  type RouteKey,
  type RoutingData,
  type RoutingOverride,
} from "./routing-v4.ts";
import { axisCorner } from "./perspective.ts";

export { BEND_RADIUS, V4_ROUTING, mergeRouting, type CardKey, type InfoRouteKey, type RouteKey, type PowerRouteKey, type RoutingData, type RoutingOverride };

/** Power links carry particles; info links are fine static connectors from a card to its equipment. */
export const POWER_ROUTES: PowerRouteKey[] = ["solarMain", "solarGarage", "battery", "grid", "home"];
export const INFO_ROUTES: InfoRouteKey[] = ["solarInfoMain", "solarInfoGarage", "batteryInfo", "gridInfo", "homeInfo"];
export const CARD_KEYS: CardKey[] = ["solar", "grid", "battery", "home"];

/** Information-card sizes at overlay scale 1 (plate px; multiplied by the scale k). */
export const CARD_SIZE: Record<CardKey, { w: number; h: number }> = {
  solar: { w: 150, h: 58 },
  grid: { w: 150, h: 58 },
  battery: { w: 192, h: 72 }, // wide enough that "≈6h 24m to reserve" clears the SOC ring
  home: { w: 140, h: 54 },
};

/** Cards keep at least this distance (plate px) from the canvas edge at every scale. */
export const CARD_MARGIN = 10;

export interface ArtworkLayout {
  width: number;
  height: number;
  /** Overlay unit scale (strokes, particles, pill internals, type); about one CSS pixel at the rendered size. */
  scale: number;
  pills: Record<CardKey, PillBox>;
  /** Centre of the inverter's underside, where the risers enter. */
  inverter: Pt;
  /** The inverter's bottom edge: the (invisible) connection bar the risers end on. */
  underside: { from: Pt; to: Pt };
  anchors: Record<AnchorKey, AnchorPt>;
  /** Route vertices (straight segments between them; the renderer fillets the bends). */
  routes: Record<RouteKey, Pt[]>;
  /** Fillet radius per route (plate px); routes not listed use the default. */
  bend: Partial<Record<RouteKey, number>>;
  /** Per power route, the vertex ranges that run out of sight (buried ducts). */
  buried: Partial<Record<PowerRouteKey, Array<[number, number]>>>;
  /** The same routes as SVG path strings (whole centrelines: the path the particles follow). */
  paths: () => Record<RouteKey, string>;
  /** Each power route split into its drawn and its buried stretches (SVG paths; either may be empty). */
  spans: () => Record<PowerRouteKey, { drawn: string; buried: string }>;
  /** The routing data this layout was built from (defaults merged with any override). */
  routing: RoutingData;
}

/**
 * Straight segments through the vertices with a small rounded corner at
 * every bend: "L" runs with a quadratic fillet of at most `radius` and at
 * most 0.3 of either adjacent segment, so short legs keep a straight middle.
 * Start and end are hit exactly.
 */
export function routePath(points: Pt[], radius = BEND_RADIUS): string {
  if (points.length < 2) return "";
  const f = (p: Pt) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
  const dist = (p: Pt, q: Pt) => Math.hypot(q.x - p.x, q.y - p.y);
  const towards = (from: Pt, to: Pt, len: number) => {
    const d = dist(from, to) || 1;
    return { x: from.x + ((to.x - from.x) * len) / d, y: from.y + ((to.y - from.y) * len) / d };
  };
  let d = `M ${f(points[0]!)}`;
  for (let i = 1; i < points.length - 1; i++) {
    const p0 = points[i - 1]!;
    const p1 = points[i]!;
    const p2 = points[i + 1]!;
    const r = Math.min(radius, dist(p0, p1) * 0.3, dist(p1, p2) * 0.3);
    d += ` L ${f(towards(p1, p0, r))} Q ${f(p1)} ${f(towards(p1, p2, r))}`;
  }
  d += ` L ${f(points[points.length - 1]!)}`;
  return d;
}

/**
 * A route split at its buried stretches (vertex index pairs): the drawn runs and the buried runs as SVG paths, each
 * run filleted on its own. Spans outside the route or overlapping an earlier one are ignored.
 */
export function routeSpans(points: Pt[], buried: Array<[number, number]> = [], radius = BEND_RADIUS): { drawn: string; buried: string } {
  const last = points.length - 1;
  const drawn: string[] = [];
  const under: string[] = [];
  let at = 0;
  for (const [a, b] of [...buried].sort((p, q) => p[0] - q[0])) {
    if (a < at || b > last || a >= b) continue;
    if (a > at) drawn.push(routePath(points.slice(at, a + 1), radius));
    under.push(routePath(points.slice(a, b + 1), radius));
    at = b;
  }
  if (at < last) drawn.push(routePath(points.slice(at), radius));
  return { drawn: drawn.join(" "), buried: under.join(" ") };
}

/** Kept for the vector scene's tests and any smooth connector; routes on the artwork use routePath. */
export function smoothPath(points: Pt[], tension = 0.5): string {
  if (points.length < 2) return "";
  if (points.length === 2) return `M ${points[0]!.x.toFixed(1)} ${points[0]!.y.toFixed(1)} L ${points[1]!.x.toFixed(1)} ${points[1]!.y.toFixed(1)}`;
  let d = `M ${points[0]!.x.toFixed(1)} ${points[0]!.y.toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)]!;
    const p1 = points[i]!;
    const p2 = points[i + 1]!;
    const p3 = points[Math.min(points.length - 1, i + 2)]!;
    const c1 = { x: p1.x + ((p2.x - p0.x) / 6) * tension * 2, y: p1.y + ((p2.y - p0.y) / 6) * tension * 2 };
    const c2 = { x: p2.x - ((p3.x - p1.x) / 6) * tension * 2, y: p2.y - ((p3.y - p1.y) / 6) * tension * 2 };
    d += ` C ${c1.x.toFixed(1)} ${c1.y.toFixed(1)}, ${c2.x.toFixed(1)} ${c2.y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return d;
}

/** Default routing data, re-exported under the names the tests and the debug overlay use. */
export const V4_ANCHORS = V4_ROUTING.anchors;
export const V4_PERSPECTIVE = V4_ROUTING.perspective;

/** The card box for a placement: its `align` corner on `at`, kept CARD_MARGIN inside the canvas. */
export function placeCard(p: CardPlacement, w: number, h: number, canvas: { width: number; height: number }): { x: number; y: number } {
  const x = p.align.endsWith("left") ? p.at.x : p.align.endsWith("right") ? p.at.x - w : p.at.x - w / 2;
  const y = p.align.startsWith("top") ? p.at.y : p.at.y - h;
  return {
    x: Math.max(CARD_MARGIN, Math.min(canvas.width - CARD_MARGIN - w, x)),
    y: Math.max(CARD_MARGIN, Math.min(canvas.height - CARD_MARGIN - h, y)),
  };
}

/** A connector's port on its card's edge: at the fraction `at`, or at the plate coordinate `x` / `y` clamped to the edge. */
export function portOf(box: { x: number; y: number; w: number; h: number }, port: InfoLink["port"]): Pt {
  const t = Math.max(0, Math.min(1, port.at));
  const clamp = (v: number | undefined, lo: number, len: number) => (Number.isFinite(v) ? Math.max(lo, Math.min(lo + len, v as number)) : lo + len * t);
  if (port.side === "top") return { x: clamp(port.x, box.x, box.w), y: box.y };
  if (port.side === "bottom") return { x: clamp(port.x, box.x, box.w), y: box.y + box.h };
  if (port.side === "left") return { x: box.x, y: clamp(port.y, box.y, box.h) };
  return { x: box.x + box.w, y: clamp(port.y, box.y, box.h) };
}

/**
 * The V4 layout at overlay scale `k`, from the routing data (defaults merged
 * with `override`, the configuration's `scene.routing`). Cards are pinned by
 * a corner so they grow away from the equipment on narrow cards (and take
 * their compact placement from `compactFrom` up). The physical routes come
 * from the data verbatim (`spans` leaves their buried stretches out of the
 * drawn path); each information link runs from its card port,
 * through an optional perspective right-angle elbow, along its fixed points
 * to the equipment.
 */
export function v4Layout(k: number, override?: RoutingOverride): ArtworkLayout {
  const D = mergeRouting(V4_ROUTING, override);
  const compact = k >= D.compactFrom;
  const pills = {} as Record<CardKey, PillBox>;
  for (const key of CARD_KEYS) {
    const w = CARD_SIZE[key].w * k;
    const h = CARD_SIZE[key].h * k;
    const { x, y } = placeCard((compact && D.cardsCompact[key]) || D.cards[key], w, h, D.canvas);
    pills[key] = { x, y, w, h, port: { x: x + w / 2, y: y + h / 2 } };
  }
  const routes = {} as Record<RouteKey, Pt[]>;
  const ported = new Set<CardKey>();
  for (const key of INFO_ROUTES) {
    const link = D.info[key];
    const box = pills[link.card];
    const port = portOf(box, link.port);
    if (!ported.has(link.card)) {
      box.port = port;
      ported.add(link.card);
    }
    const pts: Pt[] = [port];
    if (link.elbow && link.points.length) pts.push(axisCorner(port, link.elbow[0], link.points[0]!, link.elbow[1], D.perspective));
    pts.push(...link.points);
    routes[key] = pts;
  }
  for (const key of POWER_ROUTES) routes[key] = D.power[key];
  const u = D.underside;
  return {
    width: D.canvas.width,
    height: D.canvas.height,
    scale: k,
    pills,
    inverter: { x: (u.from.x + u.to.x) / 2, y: (u.from.y + u.to.y) / 2 },
    underside: u,
    anchors: D.anchors,
    routes,
    bend: D.bend,
    buried: D.buried,
    // Info connectors are drawn from the equipment back to the card, so their dot pattern starts on the equipment
    // and the last dot always lands on it whatever the card's size (the geometry is the same either way).
    paths: () =>
      Object.fromEntries(
        (Object.keys(routes) as RouteKey[]).map((key) => {
          const pts = (INFO_ROUTES as RouteKey[]).includes(key) ? [...routes[key]].reverse() : routes[key];
          return [key, routePath(pts, D.bend[key] ?? BEND_RADIUS)];
        }),
      ) as Record<RouteKey, string>,
    spans: () =>
      Object.fromEntries(POWER_ROUTES.map((key) => [key, routeSpans(routes[key], D.buried[key], D.bend[key] ?? BEND_RADIUS)])) as Record<
        PowerRouteKey,
        { drawn: string; buried: string }
      >,
    routing: D,
  };
}

/**
 * What the renderer draws for one power route: `track` is the whole centreline (the particles' path, so their timing
 * runs through any duct), `drawn` the part in sight (stroked; the still-mode chevrons go along it), `duct` the buried
 * part (the particle mask; empty when the route is drawn whole, and then `drawn` equals `track`).
 */
export function routeTracks(L: ArtworkLayout, key: PowerRouteKey): { track: string; drawn: string; duct: string } {
  const track = L.paths()[key];
  const s = L.spans()[key];
  return s.buried ? { track, drawn: s.drawn, duct: s.buried } : { track, drawn: track, duct: "" };
}

/** Overlay scale for a given card width (about one CSS pixel per unit at the rendered size); larger on phones so the cards stay readable. */
export function v4ScaleForWidth(cardWidthPx: number): number {
  if (cardWidthPx < 520) return 3.2;
  if (cardWidthPx < 760) return 2.8;
  if (cardWidthPx < 1100) return 2.3;
  return 2.0;
}

export const V4_LAYOUT: ArtworkLayout = v4Layout(2.0);
export const ARTWORK_LAYOUTS: Record<string, ArtworkLayout> = { v4: V4_LAYOUT };

/** Canonical path geometry per flow; direction reversal never changes it. */
export function flowPaths(): Record<"solar" | "battery" | "grid" | "home", string> {
  const inv = INVERTER_PORT;
  const eave = roofPoint(0.2, 0.08, HOUSE.y1, HOUSE.z, HOUSE.ridgeY, HOUSE.ridgeZ);
  const solar = cubic([
    PILLS.solar.port,
    { x: 58, y: 120 },
    { x: 150, y: 150 },
    eave,
    { x: eave.x + 16, y: eave.y + 20 },
    { x: inv.x - 24, y: inv.y - 26 },
    inv,
  ]);
  const batTop = iso(BATTERY.x1, (BATTERY.y0 + BATTERY.y1) / 2, BATTERY.z * 0.72);
  const battery = cubic([
    { x: batTop.x + 2, y: batTop.y },
    { x: batTop.x + 40, y: batTop.y - 2 },
    { x: inv.x - 60, y: inv.y + 28 },
    { x: inv.x - 24, y: inv.y + 24 },
    { x: inv.x - 10, y: inv.y + 22 },
    { x: inv.x - 4, y: inv.y + 12 },
    inv,
  ]);
  const pylonTop = { x: PYLON_BASE.x - 4, y: PYLON_BASE.y - 118 };
  const grid = cubic([
    PILLS.grid.port,
    { x: 330, y: 112 },
    { x: pylonTop.x - 30, y: pylonTop.y + 10 },
    { x: pylonTop.x - 22, y: pylonTop.y + 44 },
    { x: pylonTop.x - 14, y: PYLON_BASE.y - 6 },
    { x: PYLON_BASE.x - 30, y: PYLON_BASE.y + 30 },
    { x: 300, y: PYLON_BASE.y + 40 },
    { x: 272, y: PYLON_BASE.y + 36 },
    { x: inv.x + 10, y: inv.y + 24 },
    inv,
  ]);
  const home = cubic([inv, { x: inv.x + 10, y: inv.y - 24 }, { x: inv.x - 12, y: inv.y - 48 }, PILLS.home.port]);
  return { solar, battery, grid, home };
}
