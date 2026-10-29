// Motion model: how much a path moves for a given number of watts.
//
// The constants and the log/exponent intensity curve are the ones the
// approved ECCO Energy Flow card settled on after live tuning
// (frontend/ecco-energy-flow-card/src/ecco-energy-flow-card.ts): slow and
// sparse near idle, fast and dense at several kW, no movement at all when
// idle or unknown. Pure functions only, so the tests can pin the shape.

import { IDLE_THRESHOLD_W, type FlowEdge } from "./power.ts";

export const MAX_ANIMATION_MAGNITUDE_W = 6000;
export const INTENSITY_EXPONENT = 2.4;

// Packet (dash) layer.
export const MIN_DURATION_S = 0.45;
export const MAX_DURATION_S = 2.6;
export const DASH_PERIOD = 15;
export const PACKET_DASH_MIN = 4;
export const PACKET_DASH_MAX = 9;
export const MIN_PACKET_WIDTH_PX = 2.7;
export const MAX_PACKET_WIDTH_PX = 5.4;
export const MIN_LINE_WIDTH_PX = 2.6;
export const MAX_LINE_WIDTH_PX = 3.3;

// Energy-pulse layer.
export const MIN_BALL_DURATION_S = 0.6;
export const MAX_BALL_DURATION_S = 5.5;
export const MIN_BALL_RADIUS_PX = 3.1;
export const MAX_BALL_RADIUS_PX = 4.9;

/**
 * Magnitude -> [0, 1] intensity: logarithmic between IDLE_THRESHOLD_W and
 * MAX_ANIMATION_MAGNITUDE_W, then raised to INTENSITY_EXPONENT so the
 * everyday low/mid band stays calm while 6 kW+ is unchanged.
 */
export function magnitudeToIntensity(magnitudeW: number): number {
  if (!(magnitudeW > IDLE_THRESHOLD_W)) return 0;
  const raw = Math.log(magnitudeW / IDLE_THRESHOLD_W) / Math.log(MAX_ANIMATION_MAGNITUDE_W / IDLE_THRESHOLD_W);
  const clamped = Math.min(1, Math.max(0, raw));
  return Math.pow(clamped, INTENSITY_EXPONENT);
}

/** Pulse count bands (the maintainer's explicit thresholds). Idle/unknown is handled by the caller. */
export function ballCountForMagnitude(magnitudeW: number): number {
  if (magnitudeW < 750) return 1;
  if (magnitudeW < 3000) return 2;
  if (magnitudeW < 6000) return 3;
  return 4;
}

export interface MotionParams {
  /** 0 = no movement at all (idle or unknown). */
  intensity: number;
  moving: boolean;
  dashDurationS: number;
  dashLen: number;
  gapLen: number;
  packetWidthPx: number;
  baseWidthPx: number;
  packetOpacity: number;
  glowPx: number;
  ballCount: number;
  ballDurationS: number;
  ballRadiusPx: number;
}

const STILL: MotionParams = {
  intensity: 0,
  moving: false,
  dashDurationS: 0,
  dashLen: PACKET_DASH_MIN,
  gapLen: DASH_PERIOD - PACKET_DASH_MIN,
  packetWidthPx: MIN_PACKET_WIDTH_PX,
  baseWidthPx: MIN_LINE_WIDTH_PX,
  packetOpacity: 0,
  glowPx: 0,
  ballCount: 0,
  ballDurationS: 0,
  ballRadiusPx: MIN_BALL_RADIUS_PX,
};

/** Every visual parameter a flow path needs, from its edge state. Idle, unknown and stale edges never move. */
export function motionFor(edge: FlowEdge, stale: boolean): MotionParams {
  if (edge.unknown || edge.idle || stale || edge.magnitudeW === null) return STILL;
  const m = edge.magnitudeW;
  const t = magnitudeToIntensity(m);
  const tBase = Math.min(1, m / MAX_ANIMATION_MAGNITUDE_W);
  const dashLen = PACKET_DASH_MIN + t * (PACKET_DASH_MAX - PACKET_DASH_MIN);
  return {
    intensity: t,
    moving: true,
    dashDurationS: MAX_DURATION_S - t * (MAX_DURATION_S - MIN_DURATION_S),
    dashLen,
    gapLen: DASH_PERIOD - dashLen,
    packetWidthPx: MIN_PACKET_WIDTH_PX + t * (MAX_PACKET_WIDTH_PX - MIN_PACKET_WIDTH_PX),
    baseWidthPx: MIN_LINE_WIDTH_PX + tBase * (MAX_LINE_WIDTH_PX - MIN_LINE_WIDTH_PX),
    packetOpacity: 0.62 + t * 0.36,
    glowPx: 1.6 + t * 2.4,
    ballCount: ballCountForMagnitude(m),
    ballDurationS: MAX_BALL_DURATION_S - t * (MAX_BALL_DURATION_S - MIN_BALL_DURATION_S),
    ballRadiusPx: MIN_BALL_RADIUS_PX + t * (MAX_BALL_RADIUS_PX - MIN_BALL_RADIUS_PX),
  };
}

/** Artwork plates: plate px a particle covers per ball duration on every route and connector (a 1000 px route takes 1.6 ball durations, as in V1). */
export const PARTICLE_PACE_PX = 625;
/** Information connectors: particle spacing (plate px) at one pulse band. */
export const CONNECTOR_SPACING_PX = 300;

/** Artwork plates: seconds a particle takes to run a path `lengthPx` long, so short and long paths move at one pace (at most about three laps a second). */
export function particleLapS(m: MotionParams, lengthPx: number): number {
  return Math.max(0.35, (m.ballDurationS * lengthPx) / PARTICLE_PACE_PX);
}

/**
 * Particles on an information connector `lengthPx` plate px long: the routes' pace (`particleLapS`), and the pulse
 * bands set the density: one particle per CONNECTOR_SPACING_PX / ballCount, at least one and at most eight. Still flows get none.
 */
export function connectorPulses(m: MotionParams, lengthPx: number): { count: number; durationS: number } {
  if (!m.moving || !(lengthPx > 0)) return { count: 0, durationS: 0 };
  return {
    count: Math.max(1, Math.min(8, Math.round((lengthPx * m.ballCount) / CONNECTOR_SPACING_PX))),
    durationS: particleLapS(m, lengthPx),
  };
}

/** Card links (scene.links "pulse"): the period, in seconds, of the one slow, steady breath every active link and card border share. */
export const LINK_PULSE_PERIOD_S = 4.5;

/** The shared link pulse at time `tS` (seconds): a smooth sine from 0 (rest) to 1 (full) and back, so every card breathes in step. */
export function linkPulse(tS: number): number {
  return 0.5 - 0.5 * Math.cos((2 * Math.PI * tS) / LINK_PULSE_PERIOD_S);
}

/**
 * Pulse-mode opacities (the card CSS is built from them). An active link breathes from LINK_ACTIVE_MIN to 1 and an
 * active card border from BORDER_ACTIVE_MIN to 1; idle links and borders rest well below those floors (and idle links
 * turn grey), so at no point in the breath does a card without power outshine one with power.
 */
export const LINK_IDLE_OPACITY = 0.05;
export const LINK_ACTIVE_MIN = 0.16;
export const BORDER_IDLE_OPACITY = 0.2;
export const BORDER_ACTIVE_MIN = 0.42;
