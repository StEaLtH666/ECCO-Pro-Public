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
// one fixed-perspective house). Hardware anchors, the overlay safe zones and
// the five routes come from the pack's config/anchor-map.json; the overlays
// (pills, paths, pulses, junction) are drawn by the card on top of the plate,
// which carries no lines, labels or values of its own. Used when
// `scene.pack` is configured; the vector scene above is the no-asset fallback.

export interface ArtworkLayout {
  width: number;
  height: number;
  /** Overlay unit scale relative to the vector scene (strokes, pulses, pill internals, type). */
  scale: number;
  pills: Record<"solar" | "grid" | "home" | "battery", PillBox>;
  /** The inverter junction where every path meets. */
  inverter: Pt;
  /** Routes; `solar2` is the second PV array's own path (the garage roof). */
  paths: () => Record<"solar" | "solar2" | "battery" | "grid" | "home", string>;
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

/** Hardware anchors of the V4 plates (anchor-map.json "hardware"). */
export const V4_ANCHORS = {
  main_solar_array: { x: 684, y: 466 },
  garage_solar_array: { x: 1086, y: 582 },
  wall_inverter: { x: 1002, y: 698 },
  battery_cabinet: { x: 150, y: 622 },
  ev_charger: { x: 1090, y: 761 },
  house_energy_center: { x: 748, y: 694 },
  grid_pylon: { x: 1317, y: 452 },
} as const;

/** Overlay safe zones of the V4 plates (anchor-map.json "overlay_safe_zones"), for reference and tests. */
export const V4_SAFE_ZONES = {
  top_banner: { x: 44, y: 30, w: 1360, h: 122 },
  left_info_column: { x: 36, y: 170, w: 280, h: 705 },
  right_info_column: { x: 1128, y: 170, w: 284, h: 705 },
  bottom_strip: { x: 58, y: 920, w: 1330, h: 120 },
} as const;

/**
 * The V4 layout at overlay scale `k`. Pill boxes keep the vector scene's
 * proportions times k and stay anchored to the pack's safe zones (Solar and
 * Grid in the top banner's corners, Battery in the left column above the
 * hedge, Home in the bottom strip); the hardware anchors and the routes
 * between them never move. Phones use a larger k than desktops so the
 * figures stay legible when the whole 1448-unit canvas is 390 px wide.
 */
export function v4Layout(k: number): ArtworkLayout {
  const A = V4_ANCHORS;
  const Z = V4_SAFE_ZONES;
  const solarW = 150 * k;
  const solarH = 58 * k;
  const battW = 182 * k;
  const battH = 78 * k;
  const homeW = 140 * k;
  const homeH = 54 * k;
  const pills = {
    solar: { x: Z.top_banner.x, y: Z.top_banner.y, w: solarW, h: solarH, port: { x: Z.top_banner.x + solarW * 0.72, y: Z.top_banner.y + solarH } },
    grid: { x: Z.top_banner.x + Z.top_banner.w - solarW, y: Z.top_banner.y, w: solarW, h: solarH, port: { x: Z.top_banner.x + Z.top_banner.w - solarW * 0.28, y: Z.top_banner.y + solarH } },
    // Below the cabinet anchor (y 622), over the lawn and the left hedge; never over the patio or the house.
    battery: { x: Z.left_info_column.x, y: 672, w: battW, h: battH, port: A.battery_cabinet },
    // Bottom strip, right of the battery pill, under the front garden.
    home: { x: 930 - homeW / 2, y: Z.bottom_strip.y + Z.bottom_strip.h + 26 - homeH, w: homeW, h: homeH, port: { x: 930, y: Z.bottom_strip.y + Z.bottom_strip.h + 26 - homeH } },
  } satisfies Record<string, PillBox>;
  return {
    width: 1448,
    height: 1086,
    scale: k,
    pills,
    inverter: A.wall_inverter,
    paths: () => ({
      // Solar pill -> main array -> (anchor route) -> inverter
      solar: smoothPath([pills.solar.port, { x: 440, y: 290 }, { x: 570, y: 385 }, A.main_solar_array, { x: 758, y: 522 }, { x: 868, y: 610 }, { x: 975, y: 692 }, A.wall_inverter]),
      // Garage array -> inverter (the second PV array's own route)
      solar2: smoothPath([A.garage_solar_array, { x: 1068, y: 624 }, { x: 1042, y: 660 }, { x: 1016, y: 688 }, A.wall_inverter]),
      // Battery cabinet -> inverter (anchor route)
      battery: smoothPath([A.battery_cabinet, { x: 350, y: 622 }, { x: 560, y: 636 }, { x: 790, y: 670 }, A.wall_inverter]),
      // Grid pill -> pylon -> (anchor route) -> inverter
      grid: smoothPath([pills.grid.port, { x: 1314, y: 320 }, A.grid_pylon, { x: 1288, y: 550 }, { x: 1190, y: 626 }, { x: 1088, y: 682 }, A.wall_inverter]),
      // Inverter -> house energy centre (anchor route) -> Home pill
      home: smoothPath([A.wall_inverter, { x: 928, y: 704 }, { x: 846, y: 705 }, { x: 790, y: 700 }, A.house_energy_center, { x: 840, y: (A.house_energy_center.y + pills.home.port.y) / 2 + 10 }, pills.home.port]),
    }),
  };
}

/** Overlay scale for a given card width: larger on phones so the pills stay readable. */
export function v4ScaleForWidth(cardWidthPx: number): number {
  if (cardWidthPx < 520) return 3.4;
  if (cardWidthPx < 760) return 3.2;
  if (cardWidthPx < 1100) return 3.1;
  return 3.0;
}

export const V4_LAYOUT: ArtworkLayout = v4Layout(3.0);
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
