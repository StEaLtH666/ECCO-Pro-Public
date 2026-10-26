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
