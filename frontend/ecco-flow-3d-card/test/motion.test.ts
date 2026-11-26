// Animation state: low wattage moves slowly and sparsely, high wattage
// faster and denser; idle, unknown and stale paths never move.
import { test } from "node:test";
import assert from "node:assert/strict";
import { connectorPulses, linkPulse, magnitudeToIntensity, motionFor, particleLapS, LINK_PULSE_PERIOD_S, PARTICLE_PACE_PX, MAX_ANIMATION_MAGNITUDE_W, MIN_DURATION_S, MAX_DURATION_S, MIN_BALL_DURATION_S, MAX_BALL_DURATION_S } from "../src/core/motion.ts";
import { buildFlowEdges, IDLE_THRESHOLD_W, type FlowEdge } from "../src/core/power.ts";

function edge(magnitudeW: number | null, reversed = false): FlowEdge {
  return buildFlowEdges({ solarW: magnitudeW, batteryW: null, gridW: null, homeW: null }).map((e) => ({ ...e, reversed }))[0]!;
}

test("intensity is 0 at or below idle, 1 at the ceiling, and strictly increasing between", () => {
  assert.equal(magnitudeToIntensity(0), 0);
  assert.equal(magnitudeToIntensity(IDLE_THRESHOLD_W), 0);
  assert.equal(magnitudeToIntensity(MAX_ANIMATION_MAGNITUDE_W), 1);
  assert.equal(magnitudeToIntensity(MAX_ANIMATION_MAGNITUDE_W * 3), 1, "no invented ceiling above the maximum");
  let prev = 0;
  for (const w of [6, 10, 20, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4500, 6000]) {
    const t = magnitudeToIntensity(w);
    assert.ok(t > prev, `${w} W is more intense than the previous step`);
    prev = t;
  }
});

test("the everyday low band stays calm: 20 W and 500 W sit far below the curve's midpoint", () => {
  assert.ok(magnitudeToIntensity(20) < 0.05);
  assert.ok(magnitudeToIntensity(500) < 0.4);
  assert.ok(magnitudeToIntensity(3000) > 0.5);
});

test("speed, density, thickness, glow and pulse count all rise with watts", () => {
  const steps = [20, 100, 500, 1000, 2500, 6000].map((w) => motionFor(edge(w), false));
  for (let i = 1; i < steps.length; i++) {
    const a = steps[i - 1]!;
    const b = steps[i]!;
    assert.ok(b.dashDurationS < a.dashDurationS, "dash cycle gets shorter (faster)");
    assert.ok(b.ballDurationS < a.ballDurationS, "pulses travel faster");
    assert.ok(b.dashLen >= a.dashLen, "packets get longer (denser)");
    assert.ok(b.packetWidthPx >= a.packetWidthPx, "packet stroke gets thicker");
    assert.ok(b.glowPx >= a.glowPx, "glow grows");
    assert.ok(b.ballCount >= a.ballCount, "pulse count never drops with more power");
    assert.ok(b.moving && a.moving);
  }
  assert.equal(steps[0]!.ballCount, 1);
  assert.equal(steps[steps.length - 1]!.ballCount, 4);
  assert.ok(Math.abs(steps[steps.length - 1]!.dashDurationS - MIN_DURATION_S) < 1e-9);
  assert.ok(Math.abs(steps[steps.length - 1]!.ballDurationS - MIN_BALL_DURATION_S) < 1e-9);
  assert.ok(steps[0]!.dashDurationS < MAX_DURATION_S && steps[0]!.dashDurationS > MAX_DURATION_S * 0.9, "20 W is near the slowest cycle");
  assert.ok(steps[0]!.ballDurationS > MAX_BALL_DURATION_S * 0.9);
});

test("idle, unknown and stale paths show no movement at all", () => {
  for (const [name, e, stale] of [
    ["idle", edge(3), false],
    ["unknown", edge(null), false],
    ["stale", edge(2500), true],
  ] as const) {
    const m = motionFor(e, stale);
    assert.equal(m.moving, false, name);
    assert.equal(m.ballCount, 0, name);
    assert.equal(m.intensity, 0, name);
    assert.equal(m.packetOpacity, 0, name);
  }
});

test("reversal changes direction only: the motion parameters are identical", () => {
  const fwd = motionFor(edge(2500, false), false);
  const rev = motionFor(edge(2500, true), false);
  assert.deepEqual(fwd, rev);
});

test("artwork particles keep one pace on every route and connector, whatever its length (a 1000 px route keeps V1's timing)", () => {
  for (const w of [20, 500, 2500, 6000]) {
    const m = motionFor(edge(w), false);
    assert.ok(Math.abs(particleLapS(m, 1000) - 1.6 * m.ballDurationS) < 1e-9, `${w} W: a 1000 px lap takes 1.6 ball durations`);
    for (const lengthPx of [100, 170, 440, 620, 954, 1169]) {
      const lap = particleLapS(m, lengthPx);
      assert.ok(lap === 0.35 || Math.abs(lengthPx / lap - PARTICLE_PACE_PX / m.ballDurationS) < 1e-6, `${w} W, ${lengthPx} px: one pace (or the shortest lap)`);
    }
  }
});

test("connector particles: the routes' pace, denser with more power, none when still", () => {
  for (const w of [20, 500, 2500, 6000]) {
    const m = motionFor(edge(w), false);
    for (const lengthPx of [100, 170, 450, 620]) {
      const c = connectorPulses(m, lengthPx);
      assert.ok(c.count >= 1 && c.count <= 8, `${w} W, ${lengthPx} px: ${c.count} particles`);
      assert.equal(c.durationS, particleLapS(m, lengthPx));
    }
  }
  assert.ok(connectorPulses(motionFor(edge(6000), false), 600).count > connectorPulses(motionFor(edge(100), false), 600).count, "more power, more particles");
  for (const m of [motionFor(edge(3), false), motionFor(edge(null), false), motionFor(edge(2500), true)]) assert.deepEqual(connectorPulses(m, 400), { count: 0, durationS: 0 });
  assert.deepEqual(connectorPulses(motionFor(edge(2500), false), 0), { count: 0, durationS: 0 });
});

test("card links breathe slowly and steadily: one smooth 0..1 pulse shared by every card", () => {
  assert.ok(LINK_PULSE_PERIOD_S >= 3.5 && LINK_PULSE_PERIOD_S <= 6, "a slow breath, not a blink");
  assert.ok(Math.abs(linkPulse(0)) < 1e-9, "rest at the start of each breath");
  assert.ok(Math.abs(linkPulse(LINK_PULSE_PERIOD_S / 2) - 1) < 1e-9, "full at mid-breath");
  for (let t = 0; t < 3 * LINK_PULSE_PERIOD_S; t += 0.05) {
    const v = linkPulse(t);
    assert.ok(v >= 0 && v <= 1, `in range at ${t.toFixed(2)} s`);
    assert.ok(Math.abs(linkPulse(t + LINK_PULSE_PERIOD_S) - v) < 1e-9, "periodic: every breath the same");
    assert.ok(Math.abs(linkPulse(t + 1 / 60) - v) < 0.02, "smooth: no visible step between two frames");
  }
});
