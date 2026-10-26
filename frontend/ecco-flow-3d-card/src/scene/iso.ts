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
// values. Anchors were calibrated by eye on the master plate at native
// resolution and audited identical in all ten plates.

export type RouteKey = "solarInfo" | "solarMain" | "solarGarage" | "batteryInfo" | "battery" | "gridInfo" | "grid" | "home" | "homeInfo";
/** Power links carry particles; info links are fine static connectors from a card to its equipment. */
export const POWER_ROUTES: RouteKey[] = ["solarMain", "solarGarage", "battery", "grid", "home"];
export const INFO_ROUTES: RouteKey[] = ["solarInfo", "batteryInfo", "gridInfo", "homeInfo"];

export interface ArtworkLayout {
  width: number;
  height: number;
  /** Overlay unit scale (strokes, particles, pill internals, type); about one CSS pixel at the rendered size. */
  scale: number;
  pills: Record<"solar" | "grid" | "home" | "battery", PillBox>;
  /** The inverter: where the risers enter the unit's underside. */
  inverter: Pt;
  /** Hardware points every route touches; also the debug overlay's dots. */
  anchors: typeof V4_ANCHORS;
  /** The ground-level cable corridor under the inverter where every power route converges before its riser. */
  entry: { x0: number; x1: number; y0: number; y1: number };
  /** Route vertices (straight segments between them; the renderer fillets the bends). */
  routes: Record<RouteKey, Pt[]>;
  /** Fillet radius per route (plate px); routes not listed use the default. */
  bend: Partial<Record<RouteKey, number>>;
  /** The same routes as SVG path strings. */
  paths: () => Record<RouteKey, string>;
}

/** Fillet radius at route bends (plate pixels). */
export const BEND_RADIUS = 12;

/**
 * Straight segments through the vertices with a small rounded corner at
 * every bend: "L" runs with a quadratic fillet of at most BEND_RADIUS (less
 * when a segment is short). Start and end are hit exactly.
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
    const r = Math.min(radius, dist(p0, p1) / 2, dist(p1, p2) / 2);
    d += ` L ${f(towards(p1, p0, r))} Q ${f(p1)} ${f(towards(p1, p2, r))}`;
  }
  d += ` L ${f(points[points.length - 1]!)}`;
  return d;
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

/**
 * Hardware anchors of the V4 plates, calibrated on the master plate (plate
 * pixels, 2026-10-26) and audited identical in all ten plates. `label` is
 * what the debug overlay prints.
 */
export const V4_ANCHORS = {
  /** Centre of the main rooftop array (info-link target). */
  main_pv: { x: 610, y: 335, label: "Main PV array" },
  /** Main array: the attachment on the lower-right panel frame (the frame edge runs from 640,442 up to 751,380). */
  main_pv_frame: { x: 700, y: 409, label: "Main PV frame connection" },
  /** Main array: where the cable enters the roof, just below the frame at the porch-roof valley. */
  main_pv_edge: { x: 716, y: 425, label: "Main PV cable exit" },
  /** Centre of the garage rooftop array (info-link target). */
  garage_pv: { x: 1140, y: 500, label: "Garage PV array" },
  /** Garage array: the attachment at its lower-left frame corner (the lower frame edge runs from 1045,507 to 1130,557). */
  garage_pv_frame: { x: 1044, y: 508, label: "Garage PV frame connection" },
  /** Garage array: where the cable enters the roof at the fascia below the corner. */
  garage_pv_edge: { x: 1048, y: 545, label: "Garage PV cable exit" },
  /** Foot of the white battery cabinet (where its cable enters the ground). */
  battery_cabinet: { x: 150, y: 512, label: "Battery cabinet" },
  /** The wall inverter's underside: where the grouped riser enters the unit (unit body ≈ 958-1042 x 505-620). */
  inverter: { x: 1002, y: 624, label: "Inverter underside entry" },
  /** The common ground-level convergence point immediately below the inverter. */
  ground_entry: { x: 1002, y: 722, label: "Ground convergence" },
  /** The house / garage building corner: the main-array and grid descents run down it as two adjacent tracks (946, 952), beside the bush at its foot (907-945 x 615-675). */
  building_corner: { x: 948, y: 600, label: "Building corner" },
  /** The chimney's right face (stack 915-962 x 235-330): where the grid service drop lands on the house before following the corner down. */
  chimney: { x: 952, y: 300, label: "Chimney (service drop landing)" },
  /** The porch-roof apex where the main roof's fascia begins (758,452); the main-array cable reaches it from the frame. */
  fascia_start: { x: 758, y: 448, label: "Main roof fascia start" },
  /** The rear garden path ends at x 310 and the patio's left corner is 68 px below it across the lawn edge: a buried transition, not visible paving. */
  lawn_transition: { x: 310, y: 536, label: "Buried transition (rear path to patio)" },
  /** The downpipe on the front wall left of the entrance: the house's service wall (main-array descent, house connection). */
  downpipe: { x: 748, y: 620, label: "Downpipe / service wall" },
  /** The garage wall between the EV charger and the door frame: the garage array's descent. */
  door_post: { x: 1104, y: 640, label: "Garage wall (left of the door)" },
  /** The EV charger on the garage wall (reference only; no ECCO entity feeds it). */
  ev_charger: { x: 1048, y: 655, label: "EV charger" },
  /** The pylon's lattice at the height of the information card's connection. */
  pylon: { x: 1297, y: 290, label: "Grid pylon" },
  /** House electrical entry: the front wall beside the downpipe, left of the entrance. */
  house: { x: 752, y: 600, label: "House connection" },
} as const;

/** The pack's overlay safe zones (anchor-map.json), kept for reference and tests. */
export const V4_SAFE_ZONES = {
  top_banner: { x: 44, y: 30, w: 1360, h: 122 },
  left_info_column: { x: 36, y: 170, w: 280, h: 705 },
  right_info_column: { x: 1128, y: 170, w: 284, h: 705 },
  bottom_strip: { x: 58, y: 920, w: 1330, h: 120 },
} as const;

/**
 * Riser tracks: every power route ends with a short straight vertical riser
 * into the inverter's underside from its own ground track. Routes arrive at
 * ground level from the left (main array via the downpipe, house connection,
 * battery) or from the right (garage array and grid via the door post), and
 * the tracks nest so none crosses another: on each side the shallowest track
 * takes the outermost riser.
 */
export const RISERS = {
  grid: { x: 990, ground: 700, side: "left" },
  solarMain: { x: 996, ground: 704, side: "left" },
  home: { x: 1002, ground: 708, side: "left" },
  battery: { x: 1008, ground: 742, side: "left" },
  solarGarage: { x: 1014, ground: 746, side: "right" },
} as const;

/**
 * Paving traced on the master plate (plate pixels), for the debug overlay:
 * the rear garden path, the patio and terrace edges, the three garden step
 * edges, the lower path and the drive. The battery route follows these.
 */
export const V4_PAVING: Array<{ label: string; points: Pt[] }> = [
  { label: "rear garden path", points: [{ x: 110, y: 514 }, { x: 310, y: 502 }] },
  { label: "patio front edge", points: [{ x: 310, y: 570 }, { x: 520, y: 647 }] },
  { label: "terrace front wall", points: [{ x: 520, y: 647 }, { x: 548, y: 682 }] },
  { label: "upper landing edge", points: [{ x: 548, y: 682 }, { x: 700, y: 692 }] },
  { label: "step 1 riser", points: [{ x: 560, y: 694 }, { x: 700, y: 699 }] },
  { label: "step 2 riser", points: [{ x: 575, y: 707 }, { x: 690, y: 711 }] },
  { label: "lower path", points: [{ x: 575, y: 721 }, { x: 790, y: 742 }] },
  { label: "drive paving", points: [{ x: 790, y: 742 }, { x: 1022, y: 742 }] },
];

/** The battery route's waypoints with the paving each one sits on (the debug overlay numbers them). */
export const BATTERY_WAYPOINTS: string[] = [
  "cabinet base",
  "end of the rear path",
  "patio left corner (after the buried transition)",
  "patio front edge, lawn border",
  "terrace front wall foot",
  "across the upper landing",
  "down step 1 onto the tread",
  "along the tread",
  "down step 2 onto the lower paving",
  "lower path meets the drive",
  "drive paving, ground convergence",
  "riser into the inverter",
];
export const RISER_TOP = 624;

/**
 * The V4 layout at overlay scale `k`. Information cards sit in the owner's
 * zones and grow with k on narrow cards without covering a hardware anchor
 * (tested). Routes are straight segments with small fillets, following the
 * building and the garden in the plate's perspective, and every physical
 * route reaches the ground before the inverter (no entry from the sides or
 * the top, no descent beside the unit):
 *   solarInfo    Solar card (right edge) -> the main array's upper-left modules          info link
 *   solarMain    main array lower edge -> down the porch roof edge to the downpipe -> down the downpipe
 *                -> along the house foundation -> riser                                   array 1
 *   solarGarage  garage array lower-left corner -> along the garage eave -> down the door post
 *                -> along the garage foundation -> riser                                  array 2
 *   batteryInfo  Battery card (top edge) -> the cabinet                                   info link
 *   battery      cabinet foot -> the garden path -> the patio's left edge -> the patio and terrace front edge
 *                -> the house foundation -> riser                                          reverses when charging
 *   gridInfo     Grid card (bottom edge) -> the pylon lattice                              info link
 *   grid         pylon lattice -> down the pylon -> down the hedge beside the garage -> along the garage eave
 *                -> down the door post -> along the garage foundation -> riser            reverses when exporting
 *   home         riser -> along the house foundation -> up the service wall to the house entry   consumption
 *   homeInfo     the house entry -> Home card (top edge)                                   info link
 */
export function v4Layout(k: number): ArtworkLayout {
  const A = V4_ANCHORS;
  const R = RISERS;
  const solarW = 150 * k;
  const solarH = 58 * k;
  const battW = 178 * k;
  const battH = 72 * k;
  const homeW = 140 * k;
  const homeH = 54 * k;
  const pills = {
    solar: { x: 35, y: 95, w: solarW, h: solarH, port: { x: 35 + solarW, y: 95 + solarH * 0.5 } },
    grid: { x: 1410 - solarW, y: 95, w: solarW, h: solarH, port: { x: A.pylon.x, y: 95 + solarH } },
    battery: { x: 35, y: 718, w: battW, h: battH, port: { x: A.battery_cabinet.x, y: 718 } },
    home: { x: 690, y: 884, w: homeW, h: homeH, port: { x: 745, y: 884 } },
  } satisfies Record<string, PillBox>;
  const riser = (key: keyof typeof R): Pt[] => [{ x: R[key].x, y: R[key].ground }, { x: R[key].x, y: RISER_TOP }];
  const routes: Record<RouteKey, Pt[]> = {
    solarInfo: [pills.solar.port, { x: 430, y: pills.solar.port.y }, { x: 545, y: 275 }],
    // Panel frame -> straight down to the roof junction at the porch apex -> along the porch ridge to the fascia start
    // -> along the main roof fascia to the building corner -> straight down the corner (track 946) -> floor -> riser.
    solarMain: [A.main_pv_frame, { x: A.main_pv_frame.x, y: 448 }, A.fascia_start, { x: 946, y: 505 }, { x: 946, y: R.solarMain.ground }, ...riser("solarMain")],
    // Frame corner -> straight down to the garage fascia -> along the fascia -> straight down the garage wall left of the
    // door -> deep floor run back to the convergence -> riser.
    solarGarage: [A.garage_pv_frame, { x: A.garage_pv_frame.x, y: 528 }, { x: A.door_post.x, y: 543 }, { x: A.door_post.x, y: R.solarGarage.ground }, ...riser("solarGarage")],
    batteryInfo: [pills.battery.port, A.battery_cabinet],
    // Cabinet base -> along the rear garden path -> buried transition across the lawn edge -> the patio's left corner -> along the
    // patio front edge -> down the terrace front wall -> across the upper landing -> down step 1 -> along the tread -> down step 2
    // -> along the lower path to the drive -> drive paving to the ground convergence -> riser.
    battery: [
      A.battery_cabinet,
      { x: 310, y: 502 },
      { x: 310, y: 570 },
      { x: 520, y: 647 },
      { x: 548, y: 682 },
      { x: 620, y: 682 },
      { x: 620, y: 707 },
      { x: 640, y: 707 },
      { x: 640, y: 723 },
      { x: 790, y: 742 },
      ...riser("battery"),
    ],
    gridInfo: [pills.grid.port, A.pylon],
    // Pylon lattice -> level service drop to the chimney's right face -> straight down the chimney, the gable and the
    // building corner (track 952, beside the bush) -> floor -> riser.
    grid: [A.pylon, { x: A.chimney.x, y: A.pylon.y }, { x: A.chimney.x, y: R.grid.ground }, ...riser("grid")],
    home: [{ x: R.home.x, y: RISER_TOP }, { x: R.home.x, y: R.home.ground }, { x: 760, y: R.home.ground }, { x: 760, y: A.house.y }],
    homeInfo: [{ x: 745, y: A.house.y + 6 }, pills.home.port],
  };
  return {
    width: 1448,
    height: 1086,
    scale: k,
    pills,
    inverter: A.inverter,
    anchors: A,
    entry: { x0: 964, x1: 1022, y0: 696, y1: 752 },
    routes,
    bend: { battery: 5, home: 8, solarMain: 8, solarGarage: 8, grid: 8 },
    paths: () => Object.fromEntries((Object.keys(routes) as RouteKey[]).map((key) => [key, routePath(routes[key], ({ battery: 5, home: 8, solarMain: 8, solarGarage: 8, grid: 8 } as Partial<Record<RouteKey, number>>)[key] ?? BEND_RADIUS)])) as Record<RouteKey, string>,
  };
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
