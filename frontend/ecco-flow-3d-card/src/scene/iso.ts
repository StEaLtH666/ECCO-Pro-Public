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
// one fixed-perspective house). The hardware anchors below were calibrated by
// eye against scenes/00_bright_summer_day.png at native resolution (pixel-
// gridded zoom crops, 2026-10-26) and audited against every other plate: the
// equipment sits at the same pixels in all ten, so one anchor set serves the
// whole pack. The overlays (pills, routes, particles, junction) are drawn by
// the card on top of the plate, which carries no lines, labels or values.

export interface ArtworkLayout {
  width: number;
  height: number;
  /** Overlay unit scale (strokes, particles, pill internals, type); about one CSS pixel at the rendered size. */
  scale: number;
  pills: Record<"solar" | "grid" | "home" | "battery", PillBox>;
  /** The inverter junction where every system meets (the wall unit's cable exit). */
  inverter: Pt;
  /** Hardware points every route touches; also the debug overlay's dots. */
  anchors: typeof V4_ANCHORS;
  /** Route geometry: see the comments in v4Layout. */
  paths: () => Record<"solarCard" | "solarMain" | "solarGarage" | "battery" | "grid" | "home", string>;
}

/** Catmull-Rom spline through the points, emitted as cubic Beziers: a smooth route that passes through every anchor. */
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
 * pixels). `label` is what the debug overlay prints.
 */
export const V4_ANCHORS = {
  /** Centre of the main rooftop array (the seam between its middle modules). */
  main_pv: { x: 610, y: 335, label: "Main PV array" },
  /** Centre of the garage rooftop array. */
  garage_pv: { x: 1140, y: 500, label: "Garage PV array" },
  /** Foot of the white battery cabinet (where a cable would leave it). */
  battery_cabinet: { x: 150, y: 512, label: "Battery cabinet" },
  /** The wall inverter's cable exit under the unit (the unit body spans about 958-1042 x 505-620). */
  inverter: { x: 1000, y: 622, label: "Wall inverter" },
  /** The EV charger on the garage wall (drawn for reference; no ECCO entity feeds it). */
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
 * The V4 layout at overlay scale `k`. The four information cards sit in the
 * owner's zones (Solar upper-left, Grid upper-right, Battery lower-left,
 * Home lower centre-right), grow with k on narrow cards, and never cover a
 * hardware anchor (tested). Every system is one continuous route so a
 * direction change reverses the whole route:
 *   solarCard   Solar card (lower-right edge) -> main array           total generation
 *   solarMain   main array -> along the roof edge -> inverter         array 1
 *   solarGarage garage array -> down the wall -> inverter             array 2
 *   battery     Battery card -> cabinet -> garden edge -> inverter    reverses when charging
 *   grid        Grid card -> pylon -> behind the garage -> inverter   reverses when exporting
 *   home        inverter -> house entry -> Home card                  consumption
 */
export function v4Layout(k: number): ArtworkLayout {
  const A = V4_ANCHORS;
  const solarW = 150 * k;
  const solarH = 58 * k;
  const battW = 178 * k;
  const battH = 72 * k;
  const homeW = 140 * k;
  const homeH = 54 * k;
  const pills = {
    solar: { x: 35, y: 95, w: solarW, h: solarH, port: { x: 35 + solarW * 0.82, y: 95 + solarH } },
    grid: { x: 1410 - solarW, y: 95, w: solarW, h: solarH, port: { x: 1410 - solarW * 0.3, y: 95 + solarH } },
    battery: { x: 35, y: 718, w: battW, h: battH, port: { x: 35 + Math.min(battW * 0.36, 150 - 35 + 2), y: 718 } },
    home: { x: 690, y: 884, w: homeW, h: homeH, port: { x: 690 + homeW * 0.42, y: 884 } },
  } satisfies Record<string, PillBox>;
  return {
    width: 1448,
    height: 1086,
    scale: k,
    pills,
    inverter: A.inverter,
    anchors: A,
    paths: () => ({
      // Solar card -> over the garden -> the main array's upper-left modules -> array centre.
      solarCard: smoothPath([pills.solar.port, { x: 400, y: 262 }, { x: 500, y: 288 }, A.main_pv]),
      // Array centre -> down the array to its lower-right corner -> along the main roof's lower edge -> the gable wall -> inverter.
      solarMain: smoothPath([A.main_pv, { x: 680, y: 400 }, { x: 735, y: 442 }, { x: 830, y: 480 }, { x: 905, y: 512 }, { x: 962, y: 560 }, { x: 985, y: 600 }, A.inverter]),
      // Garage array centre -> its lower-left corner -> down the wall left of the unit -> inverter.
      solarGarage: smoothPath([A.garage_pv, { x: 1070, y: 545 }, { x: 1040, y: 585 }, { x: 1018, y: 612 }, A.inverter]),
      // Battery card (top edge) -> up to the cabinet foot -> the garden path -> the patio's lower edge -> under the front beds -> up to the inverter.
      battery: smoothPath([pills.battery.port, { x: 150, y: 640 }, { x: 148, y: 560 }, A.battery_cabinet, { x: 250, y: 530 }, { x: 335, y: 548 }, { x: 470, y: 612 }, { x: 600, y: 662 }, { x: 740, y: 700 }, { x: 880, y: 690 }, { x: 960, y: 655 }, A.inverter]),
      // Grid card (bottom edge) -> down onto the pylon lattice -> down the pylon to its foot -> left along the hedge behind the garage roof -> down the house / garage seam -> inverter.
      grid: smoothPath([pills.grid.port, { x: 1300, y: 250 }, A.pylon, { x: 1300, y: 370 }, { x: 1290, y: 425 }, { x: 1180, y: 418 }, { x: 1040, y: 428 }, { x: 975, y: 468 }, { x: 968, y: 540 }, { x: 980, y: 596 }, A.inverter]),
      // Inverter -> along the front wall past the entrance -> house entry beside the downpipe -> down the front garden -> Home card (top edge).
      home: smoothPath([A.inverter, { x: 950, y: 636 }, { x: 880, y: 622 }, { x: 810, y: 610 }, A.house, { x: 748, y: 690 }, { x: 770, y: 790 }, pills.home.port]),
    }),
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
