// The INDEPENDENT truth battery for the Gentle night planner tests (review item M6: a test must not confirm the controller with the controller's own model).
//
// This file imports NOTHING from src/ (not even a type or a constant) and nothing from the older test simulator. It is written from the saved-night shape and
// from physics, in different terms from the planner: continuous energy in kWh integrated in half-minute sub-steps, the sensor anchored at FULL (not at an
// offset), the setpoint unit drawn at random (AC grid watts or DC battery watts), a random knee and tail inside or outside the planner's declared envelope,
// a tail anchored to the power at the knee, a fall of 1 to 5 minutes, reading noise and quantisation, and its own seeded generator.
//
// Two families: IN_ENVELOPE (capacity +-6 %, efficiency 0.90 to 0.97, scale +-3 %, knee 91 to 99, tail 1/8 to 1/3 of the plateau at the knee): the planner's declared
// bands cover these, so a plan called feasible must make the deadline. STRESS (knee from 85, tail from 0, a slow trickle decay after the fall): outside the
// declared bands, used only to check the safety invariants and honest reporting, never to claim the deadline.

export type TruthFamily = "IN_ENVELOPE" | "STRESS";

export interface TruthParams {
  seed: number;
  family: TruthFamily;
  /** The trusted capacity figure the planner is given, kWh. */
  helperKwh: number;
  /** The real capacity, kWh. */
  capKwh: number;
  unit: "AC" | "DC";
  /** Battery power as a fraction of the setpoint when the unit is AC (the conversion loss). */
  effAc: number;
  /** Battery power as a multiple of the setpoint when the unit is DC (the observed overshoot). */
  dcOver: number;
  /** Sensor slope error against truth, anchored at 100 % (reading = 100 - (100 - true) * (1 + err)). */
  sensorErr: number;
  /** The true SOC at which the charge power falls. */
  kneeTrue: number;
  /** Tail power as a fraction of the plateau power at the knee. */
  tailFrac: number;
  dropMin: number;
  /** Slow decay of the tail after the fall, fraction per hour (STRESS only). */
  trickleDecayPerHour: number;
  noiseAmp: number;
  startTrueSoc: number;
  windowMin: number;
  bufferMin: number;
  targetPct: number;
  ownerLimitW: number;
  profile: "UNCONSTRAINED" | "FREE_POWER_LEASE" | "TOU_SLOT_EDITOR" | "RATE_CONTROLLER_PROPOSED";
}

/** A small seeded generator (xorshift-style), separate from the one in fixtures.ts. */
function makeGen(seed: number): () => number {
  let s = (seed ^ 0x9e3779b9) >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 4294967296;
  };
}

export function drawTruth(seed: number, family: TruthFamily): TruthParams {
  const g = makeGen(seed * 7919 + (family === "STRESS" ? 104729 : 1));
  for (let i = 0; i < 4; i++) g();
  const u = (a: number, b: number): number => a + (b - a) * g();
  const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(g() * xs.length) % xs.length] as T;
  const helperKwh = Math.round(u(20, 40) * 10) / 10;
  const inEnv = family === "IN_ENVELOPE";
  const windowMin = 5 * Math.round(u(150, 300) / 5);
  const targets = [50, 60, 70, 75, 80, 80, 85, 90, 90, 93, 95, 100];
  return {
    seed, family, helperKwh, capKwh: helperKwh * u(0.94, 1.06), unit: g() < 0.5 ? "AC" : "DC", effAc: u(0.9, 0.97), dcOver: u(1, 1.08), sensorErr: u(-0.03, 0.03),
    kneeTrue: inEnv ? u(91, 99) : u(85, 99), tailFrac: inEnv ? u(0.125, 0.35) : u(0, 0.2), dropMin: u(1, 5), trickleDecayPerHour: inEnv ? 0 : u(0, 0.6),
    noiseAmp: u(0.1, 0.45), startTrueSoc: u(5, 80), windowMin, bufferMin: pick([0, 15, 30, 45, 60, 60, 90, 120]), targetPct: pick(targets),
    ownerLimitW: pick([8000, 8000, 8000, 6000, 4000]),
    profile: pick(["UNCONSTRAINED", "FREE_POWER_LEASE", "TOU_SLOT_EDITOR", "RATE_CONTROLLER_PROPOSED"] as const),
  };
}

export interface Truth {
  params: TruthParams;
  /** Real minutes since the window opened. */
  now(): number;
  /** The noise-free reading on the sensor's scale (what the inverter compares with the slot target). */
  cleanReading(): number;
  /** The displayed reading: noise added, rounded to a whole point, clipped to 0..100. */
  reading(): number;
  /** The true SOC in percent of the real capacity. */
  trueSoc(): number;
  /** Runs the battery with a constant commanded setpoint until the given minute. The inverter stops grid charging once the clean reading reaches the target. */
  runTo(untilMin: number, setpointW: number): void;
  /** The first minute at which the clean reading was at or above the target, or null. */
  reachedAt(): number | null;
  /** The highest battery-side power seen and the highest commanded setpoint, for the ceiling checks. */
  peakBatteryW(): number;
}

export function createTruth(p: TruthParams): Truth {
  const g = makeGen(p.seed * 31 + 17);
  for (let i = 0; i < 3; i++) g();
  let t = 0;
  let kwh = (p.startTrueSoc / 100) * p.capKwh;
  let kneeAt: number | null = null;
  let kneeW = 0;
  let reached: number | null = null;
  let peak = 0;
  const trueSoc = (): number => Math.min(100, (kwh / p.capKwh) * 100);
  const clean = (): number => Math.max(0, Math.min(100, 100 - (100 - trueSoc()) * (1 + p.sensorErr)));
  const plateauW = (cmd: number): number => (p.unit === "AC" ? cmd * p.effAc : cmd * p.dcOver);
  const batteryW = (cmd: number): number => {
    const pl = plateauW(cmd);
    if (kneeAt === null) return pl;
    const tailW = Math.min(pl, p.tailFrac * kneeW);
    const since = t - kneeAt;
    const ramp = Math.min(1, since / p.dropMin);
    let w = pl - (pl - tailW) * ramp;
    if (p.trickleDecayPerHour > 0 && since > p.dropMin) w *= Math.exp((-p.trickleDecayPerHour * (since - p.dropMin)) / 60);
    return w;
  };
  if (clean() >= p.targetPct) reached = 0;
  return {
    params: p,
    now: () => t,
    cleanReading: clean,
    trueSoc,
    reading: () => Math.max(0, Math.min(100, Math.round(clean() + (g() * 2 - 1) * p.noiseAmp))),
    reachedAt: () => reached,
    peakBatteryW: () => peak,
    runTo(untilMin: number, setpointW: number) {
      const dt = 0.5;
      while (t < untilMin - 1e-9) {
        const before = clean();
        const stopped = clean() >= p.targetPct - 1e-9 || trueSoc() >= 100 - 1e-9;
        if (!stopped) {
          if (kneeAt === null && trueSoc() >= p.kneeTrue) {
            kneeAt = t;
            kneeW = plateauW(setpointW);
          }
          const w = batteryW(setpointW);
          peak = Math.max(peak, w);
          kwh += (w / 1000) * (dt / 60);
        }
        t += dt;
        const after = clean();
        if (reached === null && after >= p.targetPct - 1e-9) reached = after > before ? t - dt + (dt * (p.targetPct - before)) / (after - before) : t;
      }
    },
  };
}
