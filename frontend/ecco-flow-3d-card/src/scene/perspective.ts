// Perspective model of a scene plate: every real-world direction a cable may
// follow (along the inverter wall, along the garage-door wall, vertical, up a
// roof slope) is an axis whose on-screen direction is known at every point.
// An illustrated plate is not an exact two-point perspective, so an axis is
// either a vanishing point or a smooth direction field fitted to the plate's
// measured edges (a quadratic in the plate coordinates, degrees). A route
// segment follows axis A when it points along A's local direction; two
// segments on different axes meet at a real-world right angle however the
// corner looks on screen. Pure functions over numbers only, so the layout,
// the debug overlay and the tests share one definition.

export interface Pt {
  x: number;
  y: number;
}

/**
 * One axis: a vanishing point (plate px), or a direction field: the
 * on-screen angle in degrees (x right, y down) is
 * c0 + c1 u + c2 v + c3 u v + c4 u^2 + c5 v^2 with u = x / size[0], v = y / size[1].
 */
export type AxisModel = { vp: Pt } | { field: number[]; size: [number, number] };
export type AxisModels = Record<string, AxisModel>;

const DEG = Math.PI / 180;

/** The axis's on-screen direction at `p`, in degrees folded into (-90, 90]. */
export function axisAngle(model: AxisModel, p: Pt): number {
  let a: number;
  if ("vp" in model) {
    a = Math.atan2(model.vp.y - p.y, model.vp.x - p.x) / DEG;
  } else {
    const [c0 = 0, c1 = 0, c2 = 0, c3 = 0, c4 = 0, c5 = 0] = model.field;
    const u = p.x / model.size[0];
    const v = p.y / model.size[1];
    a = c0 + c1 * u + c2 * v + c3 * u * v + c4 * u * u + c5 * v * v;
  }
  while (a <= -90) a += 180;
  while (a > 90) a -= 180;
  return a;
}

const segAngle = (a: Pt, b: Pt): number => {
  let s = Math.atan2(b.y - a.y, b.x - a.x) / DEG;
  while (s <= -90) s += 180;
  while (s > 90) s -= 180;
  return s;
};

/** Angle in degrees (0..90) between segment a->b and the axis direction at the segment's midpoint. */
export function axisError(a: Pt, b: Pt, model: AxisModel): number {
  const d = Math.abs(segAngle(a, b) - axisAngle(model, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })) % 180;
  return Math.min(d, 180 - d);
}

/** The axis (among `axes`) that segment a->b follows best, with its error in degrees. */
export function classifySegment(a: Pt, b: Pt, models: AxisModels, axes: string[] = Object.keys(models)): { axis: string; error: number } {
  let best = { axis: "", error: 90 };
  for (const axis of axes) {
    const m = models[axis];
    if (!m) continue;
    const error = axisError(a, b, m);
    if (error < best.error) best = { axis, error };
  }
  return best;
}

function intersect(p: Pt, angP: number, q: Pt, angQ: number): Pt | null {
  const d1 = { x: Math.cos(angP * DEG), y: Math.sin(angP * DEG) };
  const d2 = { x: Math.cos(angQ * DEG), y: Math.sin(angQ * DEG) };
  const den = d1.x * d2.y - d1.y * d2.x;
  if (Math.abs(den) < 1e-9) return null;
  const t = ((q.x - p.x) * d2.y - (q.y - p.y) * d2.x) / den;
  return { x: p.x + d1.x * t, y: p.y + d1.y * t };
}

/**
 * The corner of a real-world right-angle bend from p's run (axis `axisP`)
 * onto q's run (axis `axisQ`): where the two axis lines meet, each taken at
 * its own segment's midpoint (a few fixed-point iterations for a field).
 * Falls back to `q` when the runs are parallel or an axis is unknown.
 */
export function axisCorner(p: Pt, axisP: string, q: Pt, axisQ: string, models: AxisModels): Pt {
  const mp = models[axisP];
  const mq = models[axisQ];
  if (!mp || !mq) return { x: q.x, y: q.y };
  let c = intersect(p, axisAngle(mp, p), q, axisAngle(mq, q));
  for (let i = 0; i < 8 && c; i++) {
    const next = intersect(p, axisAngle(mp, { x: (p.x + c.x) / 2, y: (p.y + c.y) / 2 }), q, axisAngle(mq, { x: (q.x + c.x) / 2, y: (q.y + c.y) / 2 }));
    if (!next) break;
    const moved = Math.hypot(next.x - c.x, next.y - c.y);
    c = next;
    if (moved < 0.01) break;
  }
  return c ?? { x: q.x, y: q.y };
}
