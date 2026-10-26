// The isometric scene: one SVG, drawn from geometry in iso.ts. Everything
// here is presentation; the values it shows arrive already resolved in a
// SceneModel. No external image, font or CDN dependency.

import { svg, nothing, type TemplateResult } from "lit";
import type { FlowEdge, FlowId } from "../core/power.ts";
import type { MotionParams } from "../core/motion.ts";
import type { Daylight, Tone } from "../core/status.ts";
import { ICONS, type IconName } from "./icons.ts";
import {
  BATTERY,
  GARAGE,
  HOUSE,
  INVERTER,
  INVERTER_PORT,
  PILLS,
  PYLON_BASE,
  SCENE_H,
  SCENE_W,
  type ArtworkLayout,
  type RouteKey,
  V4_PAVING,
  BATTERY_WAYPOINTS,
  box,
  flowPaths,
  iso,
  pts,
  roofPoint,
  wallRectLeft,
  wallRectRight,
  type PillBox,
} from "./iso.ts";

export interface PillData {
  label: string;
  value: string;
  sub: string;
  tone: Tone;
  icon: IconName;
  clickable: boolean;
  /** Battery only: 0-100 or null (no ring fill when unknown). */
  soc?: number | null;
  /** Battery only: the FE-1 time-to-reserve line, shown on its own line under the state. */
  extra?: string;
}

export interface FlowView {
  edge: FlowEdge;
  motion: MotionParams;
}

export interface SceneModel {
  daylight: Daylight;
  flows: Record<FlowId, FlowView>;
  /** Artwork plates only: the solar system split into card->array (total), main array->inverter, garage array->inverter. */
  solarSplit?: { card: FlowView; main: FlowView; garage: FlowView | null };
  stale: boolean;
  /** False under prefers-reduced-motion or when animation is disabled: no movement, static direction chevrons instead. */
  animate: boolean;
  pills: Record<FlowId, PillData>;
  inverterLed: "ok" | "warn" | "off";
  onPill: (id: FlowId) => void;
  /**
   * Artwork plates: when set, the overlay layout is drawn over the scene
   * image instead of the vector scene. `layers` holds the current plate and,
   * during a crossfade, the previous one underneath it.
   */
  artwork?: { layers: Array<{ url: string; key: string; entering: boolean }>; layout: ArtworkLayout; onError: (url: string) => void; onLoad: (url: string) => void; debug?: boolean };
}

/** The packet dash cycle in vector-scene units (motion.DASH_PERIOD); the keyframe travel is twice this. */
const DASH_PERIOD_UNITS = 15;

const FLOW_COLOUR: Record<FlowId, string> = {
  solar: "#f7c948",
  battery: "#35e08a",
  grid: "#3ea6ff",
  home: "#22d3ee",
};

function icon(name: IconName, x: number, y: number, size: number, colour: string): TemplateResult {
  const s = size / 24;
  return svg`<g transform="translate(${x} ${y}) scale(${s})" fill="none" stroke=${colour} stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d=${ICONS[name]}></path></g>`;
}

// ---------------------------------------------------------------------------
// Static scenery

function ground(): TemplateResult {
  const top = [iso(-8, -6), iso(10, -6), iso(10, 10), iso(-8, 10)];
  const depth = 12;
  const left = [top[3]!, top[2]!, { x: top[2]!.x, y: top[2]!.y + depth }, { x: top[3]!.x, y: top[3]!.y + depth }];
  const right = [top[2]!, top[1]!, { x: top[1]!.x, y: top[1]!.y + depth }, { x: top[2]!.x, y: top[2]!.y + depth }];
  // Driveway from the garage front to the island's front edge.
  const drive = [iso(8.2, 3.05), iso(10.6, 3.05), iso(10.6, 10), iso(8.2, 10)];
  // Garden path from the door towards the battery.
  const path = [iso(2.2, 3.05), iso(3.2, 3.05), iso(3.2, 5.6), iso(-4.2, 5.6), iso(-4.2, 4.6), iso(2.2, 4.6)];
  return svg`
    <g class="ground">
      <polygon points=${pts(left)} class="ground-side"></polygon>
      <polygon points=${pts(right)} class="ground-side ground-side-r"></polygon>
      <polygon points=${pts(top)} class="ground-top"></polygon>
      <polygon points=${pts(top)} fill="url(#ef3d-ground-sheen)"></polygon>
      <polygon points=${pts(drive)} class="drive"></polygon>
      <polygon points=${pts(path)} class="drive path"></polygon>
      ${lawnStripes()}
    </g>`;
}

function lawnStripes(): TemplateResult[] {
  const out: TemplateResult[] = [];
  for (let i = 0; i < 6; i++) {
    const y = -5 + i * 2.6;
    out.push(svg`<polygon points=${pts([iso(-7.6, y), iso(-1.6, y), iso(-1.6, y + 1.3), iso(-7.6, y + 1.3)])} class="lawn-stripe"></polygon>`);
  }
  return out;
}

function tree(x: number, y: number, r: number, cls = ""): TemplateResult {
  const b = iso(x, y);
  return svg`
    <g class="tree ${cls}">
      <ellipse cx=${b.x} cy=${b.y + 2} rx=${r * 0.9} ry=${r * 0.38} class="tree-shadow"></ellipse>
      <rect x=${b.x - 1.4} y=${b.y - r * 1.1} width="2.8" height=${r * 1.1} class="trunk"></rect>
      <circle cx=${b.x - r * 0.35} cy=${b.y - r * 1.15} r=${r * 0.78} class="canopy c2"></circle>
      <circle cx=${b.x + r * 0.4} cy=${b.y - r * 1.25} r=${r * 0.82} class="canopy c3"></circle>
      <circle cx=${b.x} cy=${b.y - r * 1.7} r=${r * 0.86} class="canopy c1"></circle>
    </g>`;
}

function shrub(x: number, y: number, r: number): TemplateResult {
  const b = iso(x, y);
  return svg`<g class="shrub"><ellipse cx=${b.x} cy=${b.y} rx=${r} ry=${r * 0.62} class="canopy c2"></ellipse><ellipse cx=${b.x - r * 0.4} cy=${b.y - r * 0.25} rx=${r * 0.7} ry=${r * 0.45} class="canopy c1"></ellipse></g>`;
}

function lamp(x: number, y: number): TemplateResult {
  const b = iso(x, y);
  return svg`<g class="lamp"><line x1=${b.x} y1=${b.y} x2=${b.x} y2=${b.y - 9} class="lamp-post"></line><circle cx=${b.x} cy=${b.y - 10} r="2.2" class="lamp-light"></circle><circle cx=${b.x} cy=${b.y - 10} r="6" class="lamp-halo"></circle></g>`;
}

function house(): TemplateResult {
  const h = HOUSE;
  const b = box(h.x0, h.y0, h.x1, h.y1, 0, h.z);
  // Gable roof: ridge along x at y = ridgeY. Visible plane is the front one (y from ridge to y1).
  const roofFront = [iso(h.x0 - 0.5, h.y1 + 0.5, h.z - 0.25), iso(h.x1 + 0.5, h.y1 + 0.5, h.z - 0.25), iso(h.x1 + 0.5, h.ridgeY, h.ridgeZ), iso(h.x0 - 0.5, h.ridgeY, h.ridgeZ)];
  const roofBack = [iso(h.x0 - 0.5, h.y0 - 0.5, h.z - 0.25), iso(h.x1 + 0.5, h.y0 - 0.5, h.z - 0.25), iso(h.x1 + 0.5, h.ridgeY, h.ridgeZ), iso(h.x0 - 0.5, h.ridgeY, h.ridgeZ)];
  const gable = [iso(h.x1, h.y0, h.z), iso(h.x1, h.y1, h.z), iso(h.x1, h.ridgeY, h.ridgeZ)];
  const fascia = [iso(h.x1 + 0.5, h.y1 + 0.5, h.z - 0.25), iso(h.x1 + 0.5, h.y1 + 0.5, h.z - 0.55), iso(h.x1 + 0.5, h.ridgeY, h.ridgeZ - 0.3), iso(h.x1 + 0.5, h.ridgeY, h.ridgeZ)];
  const g = GARAGE;
  const gb = box(g.x0, g.y0, g.x1, g.y1, 0, g.z);
  const gRoofLip = box(g.x0 - 0.15, g.y0 - 0.15, g.x1 + 0.15, g.y1 + 0.15, g.z, g.z + 0.18);
  return svg`
    <g class="house">
      <!-- soft contact shadow -->
      <polygon points=${pts([iso(h.x0 - 0.6, h.y0 - 0.2), iso(g.x1 + 0.9, g.y0 - 0.2), iso(g.x1 + 0.9, g.y1 + 0.9), iso(h.x0 - 0.6, h.y1 + 0.9)])} class="contact-shadow"></polygon>
      <!-- garage (behind the house's right face order-wise it sits in front, draw after walls) -->
      <polygon points=${b.right} class="wall wall-r"></polygon>
      <polygon points=${pts(gable)} class="wall wall-r gable"></polygon>
      <polygon points=${b.left} class="wall wall-l"></polygon>
      <!-- windows and door on the front-left wall -->
      <polygon points=${wallRectLeft(h.y1 + 0.02, 0.2, 1.6, 1.5, 3.2)} class="window"></polygon>
      <polygon points=${wallRectLeft(h.y1 + 0.02, 2.0, 3.4, 1.5, 3.2)} class="window"></polygon>
      <polygon points=${wallRectLeft(h.y1 + 0.02, 0.2, 1.6, 0.4, 1.1)} class="window small"></polygon>
      <polygon points=${wallRectLeft(h.y1 + 0.02, 2.3, 3.1, 0, 1.15)} class="door"></polygon>
      <polygon points=${wallRectLeft(h.y1 + 0.02, 3.9, 4.8, 1.5, 3.2)} class="window"></polygon>
      <!-- windows on the right wall -->
      <polygon points=${wallRectRight(h.x1 + 0.02, -2.4, -1.2, 1.5, 3.2)} class="window"></polygon>
      <polygon points=${wallRectRight(h.x1 + 0.02, -2.4, -1.2, 0.3, 1.1)} class="window small"></polygon>
      <!-- garage -->
      <polygon points=${gb.right} class="wall wall-r"></polygon>
      <polygon points=${gb.left} class="wall wall-l"></polygon>
      <polygon points=${wallRectLeft(g.y1 + 0.02, 7.6, 10.4, 0, 1.9)} class="garage-door"></polygon>
      ${[0.45, 0.9, 1.35].map((z) => svg`<polyline points=${pts([iso(7.6, g.y1 + 0.03, z), iso(10.4, g.y1 + 0.03, z)])} class="garage-line"></polyline>`)}
      <polygon points=${gb.top} class="roof-flat"></polygon>
      <polygon points=${gRoofLip.left} class="roof-lip"></polygon>
      <polygon points=${gRoofLip.right} class="roof-lip"></polygon>
      <polygon points=${gRoofLip.top} class="roof-flat-top"></polygon>
      <!-- roof -->
      <polygon points=${pts(roofBack)} class="roof roof-back"></polygon>
      <polygon points=${pts(roofFront)} class="roof roof-front"></polygon>
      <polygon points=${pts(fascia)} class="fascia"></polygon>
      <polyline points=${pts([iso(h.x0 - 0.5, h.ridgeY, h.ridgeZ), iso(h.x1 + 0.5, h.ridgeY, h.ridgeZ)])} class="ridge"></polyline>
      ${pvPanels()}
      ${inverterBox()}
    </g>`;
}

/** 2 x 5 PV modules on the front roof plane, as parallelograms following the slope. */
function pvPanels(): TemplateResult[] {
  const h = HOUSE;
  const out: TemplateResult[] = [];
  const cols = 5;
  const rows = 2;
  const x0 = h.x0 + 0.25;
  const x1 = h.x1 - 0.75;
  const gapX = 0.14;
  const w = (x1 - x0 - gapX * (cols - 1)) / cols;
  const t0 = 0.16;
  const t1 = 0.9;
  const gapT = 0.05;
  const th = (t1 - t0 - gapT * (rows - 1)) / rows;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const xa = x0 + c * (w + gapX);
      const xb = xa + w;
      const ta = t0 + r * (th + gapT);
      const tb = ta + th;
      const quad = [
        roofPoint(xa, ta, h.y1 + 0.5, h.z - 0.25, h.ridgeY, h.ridgeZ),
        roofPoint(xb, ta, h.y1 + 0.5, h.z - 0.25, h.ridgeY, h.ridgeZ),
        roofPoint(xb, tb, h.y1 + 0.5, h.z - 0.25, h.ridgeY, h.ridgeZ),
        roofPoint(xa, tb, h.y1 + 0.5, h.z - 0.25, h.ridgeY, h.ridgeZ),
      ];
      // Nudge each module up by 1.2 px so the frame sits proud of the slates.
      const lifted = quad.map((p) => ({ x: p.x, y: p.y - 1.2 }));
      out.push(svg`<polygon points=${pts(lifted)} class="pv"></polygon>`);
      out.push(svg`<polygon points=${pts(lifted)} fill="url(#ef3d-pv-glare)" class="pv-glare"></polygon>`);
      // Cell grid: two inner lines per module.
      const mid = (a: { x: number; y: number }, b: { x: number; y: number }, f: number) => ({ x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f });
      for (const f of [1 / 3, 2 / 3]) {
        out.push(svg`<line x1=${mid(lifted[0]!, lifted[3]!, f).x} y1=${mid(lifted[0]!, lifted[3]!, f).y} x2=${mid(lifted[1]!, lifted[2]!, f).x} y2=${mid(lifted[1]!, lifted[2]!, f).y} class="pv-line"></line>`);
        out.push(svg`<line x1=${mid(lifted[0]!, lifted[1]!, f).x} y1=${mid(lifted[0]!, lifted[1]!, f).y} x2=${mid(lifted[3]!, lifted[2]!, f).x} y2=${mid(lifted[3]!, lifted[2]!, f).y} class="pv-line"></line>`);
      }
    }
  }
  return out;
}

function inverterBox(): TemplateResult {
  const i = INVERTER;
  const face = wallRectLeft(i.y + 0.03, i.x0, i.x1, i.z0, i.z1);
  const led = iso(i.x1 - 0.18, i.y + 0.05, i.z1 - 0.22);
  const vent = (z: number) => pts([iso(i.x0 + 0.18, i.y + 0.05, z), iso(i.x1 - 0.18, i.y + 0.05, z)]);
  return svg`
    <g class="inverter">
      <polygon points=${face} class="inverter-face"></polygon>
      <polyline points=${vent(i.z0 + 0.3)} class="inverter-vent"></polyline>
      <polyline points=${vent(i.z0 + 0.5)} class="inverter-vent"></polyline>
      <circle cx=${led.x} cy=${led.y} r="1.6" class="inverter-led"></circle>
      <circle cx=${led.x} cy=${led.y} r="4" class="inverter-led-halo"></circle>
    </g>`;
}

function batteryCabinet(soc: number | null): TemplateResult {
  const b = BATTERY;
  const f = box(b.x0, b.y0, b.x1, b.y1, 0, b.z);
  // LED strip on the front-left face (y = y1): fills from the bottom with SOC.
  const stripX = b.x0 + 0.18;
  const stripW = 0.16;
  const z0 = 0.3;
  const z1 = b.z - 0.3;
  const fillZ = soc === null ? z0 : z0 + (Math.max(0, Math.min(100, soc)) / 100) * (z1 - z0);
  const label = iso((b.x0 + b.x1) / 2 + 0.15, b.y1 + 0.04, b.z * 0.56);
  return svg`
    <g class="battery-cabinet">
      <ellipse cx=${iso((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2).x} cy=${iso((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2).y + 3} rx="20" ry="7" class="contact-shadow soft"></ellipse>
      <polygon points=${f.right} class="cab cab-r"></polygon>
      <polygon points=${f.left} class="cab cab-l"></polygon>
      <polygon points=${f.top} class="cab cab-t"></polygon>
      <polygon points=${wallRectLeft(b.y1 + 0.03, stripX, stripX + stripW, z0, z1)} class="cab-strip-bg"></polygon>
      ${soc === null ? nothing : svg`<polygon points=${wallRectLeft(b.y1 + 0.04, stripX, stripX + stripW, z0, fillZ)} class="cab-strip"></polygon>`}
      <text x="0" y="0" class="cab-label" transform=${`matrix(0.866 0.5 0 1 ${label.x.toFixed(1)} ${label.y.toFixed(1)})`}>ECCO</text>
    </g>`;
}

function pylon(gridMoving: boolean, gridUnknown: boolean): TemplateResult {
  const b = PYLON_BASE;
  const H = 118;
  const top = { x: b.x - 4, y: b.y - H };
  const w = 18;
  const arm = (y: number, half: number) => svg`<line x1=${b.x - 4 - half} y1=${y} x2=${b.x - 4 + half} y2=${y} class="pylon-line"></line>`;
  const legs = svg`
    <line x1=${b.x - w} y1=${b.y} x2=${top.x - 2} y2=${top.y} class="pylon-line"></line>
    <line x1=${b.x + w - 8} y1=${b.y} x2=${top.x + 2} y2=${top.y} class="pylon-line"></line>
    <line x1=${b.x - w + 5} y1=${b.y - 2} x2=${top.x} y2=${top.y + 4} class="pylon-line thin"></line>
    <line x1=${b.x + w - 12} y1=${b.y - 2} x2=${top.x} y2=${top.y + 4} class="pylon-line thin"></line>`;
  const lattice: TemplateResult[] = [];
  for (let i = 1; i < 7; i++) {
    const y = b.y - (H / 7) * i;
    const half = (w - 8) * (1 - i / 8) + 3;
    lattice.push(svg`<line x1=${b.x - 4 - half} y1=${y} x2=${b.x - 4 + half} y2=${y - 6} class="pylon-line thin"></line>`);
    lattice.push(svg`<line x1=${b.x - 4 + half} y1=${y} x2=${b.x - 4 - half} y2=${y - 6} class="pylon-line thin"></line>`);
  }
  const wires = [top.y + 24, top.y + 44].map(
    (y) => svg`<path d=${`M ${(b.x - 4 - 26).toFixed(1)} ${y} Q ${(b.x + 30).toFixed(1)} ${y + 18} ${SCENE_W + 10} ${y - 12}`} class="wire"></path>`
  );
  return svg`
    <g class=${`pylon ${gridMoving ? "live" : ""} ${gridUnknown ? "unknown" : ""}`}>
      ${legs}${lattice}
      ${arm(top.y + 22, 26)}${arm(top.y + 42, 20)}
      ${wires}
      <circle cx=${top.x} cy=${top.y - 2} r="3" class="pylon-tip"></circle>
    </g>`;
}

// ---------------------------------------------------------------------------
// Flow paths

/**
 * One animated route. Vector scene (k = 1): the original dashed packet
 * texture. Artwork scene (k > 1): premium electricity styling, a very thin
 * low-opacity base line, a restrained soft glow, a crisp inner highlight and
 * individual bright travelling particles, with a soft light at each end.
 * `key` must be unique per route (it names the path element the particles
 * follow). Idle, unknown and stale routes never move.
 */
function flowPath(id: FlowId, key: string, d: string, view: FlowView, animate: boolean, k = 1, lengthUnits = 0, riserD = ""): TemplateResult {
  const { edge, motion } = view;
  const colour = FLOW_COLOUR[id];
  const artwork = k > 1;
  const cls = `flow flow-${id} route-${key} ${artwork ? "fine" : ""} ${edge.unknown ? "unknown" : ""} ${edge.idle ? "idle" : ""} ${motion.moving && animate ? "moving" : ""} ${edge.reversed ? "reversed" : ""}`;
  const pathId = `ef3d-path-${key}`;
  // Particle count: the ECCO bands (1-4), repeated along long routes so the spacing stays similar.
  const lengthFactor = artwork && lengthUnits > 0 ? Math.max(1, Math.round(lengthUnits / 520)) : 1;
  const n = motion.ballCount * lengthFactor;
  const t = motion.intensity;
  const particles: TemplateResult[] = [];
  if (motion.moving && animate) {
    const r = artwork ? (1.7 + t * 1.0) * k : motion.ballRadiusPx;
    for (let i = 0; i < n; i++) {
      particles.push(svg`
        <g class="pulse" data-path=${pathId} data-duration=${(motion.ballDurationS * (artwork ? 1.6 : 1)).toFixed(3)} data-phase=${(i / n).toFixed(3)} data-reversed=${edge.reversed ? "1" : "0"} style=${`--pulse-colour:${colour}`}>
          <circle r=${(r * (artwork ? 2.6 : 1.9)).toFixed(2)} class="pulse-halo"></circle>
          <circle r=${r.toFixed(2)} class="pulse-glow"></circle>
          <circle r=${(r * 0.45).toFixed(2)} class="pulse-core"></circle>
        </g>`);
    }
  }
  const chevrons: TemplateResult[] = [];
  if (motion.moving && !animate) {
    for (const phase of [0.3, 0.55, 0.8]) {
      chevrons.push(svg`<g class="chevron" data-path=${pathId} data-phase=${phase} data-reversed=${edge.reversed ? "1" : "0"} style=${`--pulse-colour:${colour}`}><path d="M -4 -4 L 2 0 L -4 4" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform=${`scale(${k})`}></path></g>`);
    }
  }
  if (artwork) {
    // Buried-cable look: a faint trace along the ground and the walls, the energy carried by the particles,
    // and the short riser into the inverter drawn brighter.
    const baseW = (0.95 + t * 0.35) * k;
    const glowW = (3.4 + t * 2.0) * k;
    const glowOp = motion.moving ? 0.1 + t * 0.16 : 0;
    const hiOp = motion.moving ? 0.3 + t * 0.3 : 0;
    const riserOp = motion.moving ? 0.45 + t * 0.3 : 0.25;
    return svg`
      <g class=${cls} style=${`--flow-colour:${colour}`}>
        <path d=${d} class="fine-base" style=${`stroke-width:${baseW.toFixed(2)}`}></path>
        <path d=${d} class="fine-glow" style=${`stroke-width:${glowW.toFixed(2)}; opacity:${glowOp.toFixed(2)}`}></path>
        <path id=${pathId} d=${d} class="fine-highlight" style=${`stroke-width:${(0.6 * k).toFixed(2)}; opacity:${hiOp.toFixed(2)}`}></path>
        ${riserD ? svg`<path d=${riserD} class="fine-riser" style=${`stroke-width:${(0.95 * k).toFixed(2)}; opacity:${riserOp.toFixed(2)}`}></path>` : nothing}
        ${particles}${chevrons}
      </g>`;
  }
  const dashStyle = motion.moving
    ? `stroke-dasharray:${motion.dashLen.toFixed(1)} ${motion.gapLen.toFixed(1)}; animation-duration:${motion.dashDurationS.toFixed(2)}s; stroke-width:${motion.packetWidthPx.toFixed(2)}; opacity:${motion.packetOpacity.toFixed(2)}; --dash-travel:${(-2 * DASH_PERIOD_UNITS).toFixed(1)}`
    : "";
  const glowStyle = motion.moving ? `stroke-width:${(motion.packetWidthPx * 2.6).toFixed(1)}; opacity:${(0.18 + motion.intensity * 0.3).toFixed(2)}` : "";
  return svg`
    <g class=${cls} style=${`--flow-colour:${colour}`}>
      <path d=${d} class="flow-base" style=${`stroke-width:${motion.baseWidthPx.toFixed(2)}`}></path>
      <path d=${d} class="flow-dots"></path>
      <path d=${d} class="flow-glow" style=${glowStyle}></path>
      <path id=${pathId} d=${d} class="flow-packets" style=${dashStyle}></path>
      ${particles}${chevrons}
    </g>`;
}

/** Fine information connector between a card and its equipment: no particles, a little brighter while the system is active. */
function infoLink(key: string, d: string, colour: string, active: boolean, k: number): TemplateResult {
  return svg`<g class=${`info-link info-${key} ${active ? "active" : ""}`} style=${`--flow-colour:${colour}`}>
    <path d=${d} class="info-glow" style=${`stroke-width:${(2.4 * k).toFixed(2)}`}></path>
    <path d=${d} class="info-line" style=${`stroke-width:${(0.7 * k).toFixed(2)}`}></path>
  </g>`;
}

/** The common ground-level cable entry under the inverter: a small buried pit the risers leave from. */
function cablePit(e: { x0: number; x1: number; y0: number; y1: number }, k: number): TemplateResult {
  return svg`<g class="cable-pit">
    <rect x=${e.x0} y=${e.y0} width=${e.x1 - e.x0} height=${e.y1 - e.y0} rx=${2 * k} class="pit-shadow"></rect>
    <rect x=${e.x0} y=${e.y0} width=${e.x1 - e.x0} height=${e.y1 - e.y0} rx=${2 * k} class="pit-face"></rect>
  </g>`;
}

/** Soft light at a physical connection point, in the route's colour; dim when the route is idle or unknown. */
function nodeLight(p: { x: number; y: number }, colour: string, active: boolean, k: number): TemplateResult {
  return svg`<g class=${`node-light ${active ? "active" : ""}`} style=${`--flow-colour:${colour}`}><circle cx=${p.x} cy=${p.y} r=${(5 * k).toFixed(1)} class="node-light-halo"></circle><circle cx=${p.x} cy=${p.y} r=${(1.6 * k).toFixed(1)} class="node-light-core"></circle></g>`;
}

/** Approximate length of a path string's control polygon (enough to scale particle counts). */
function approxLength(d: string): number {
  const nums = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
  let len = 0;
  for (let i = 2; i + 1 < nums.length; i += 2) len += Math.hypot(nums[i]! - nums[i - 2]!, nums[i + 1]! - nums[i - 1]!);
  return len / 1.9; // the control polygon of a cubic spline overshoots the curve
}

// ---------------------------------------------------------------------------
// Pills

function pill(id: FlowId, boxDef: PillBox, data: PillData, onPill: (id: FlowId) => void, flow: FlowView, k = 1): TemplateResult {
  const colour = FLOW_COLOUR[id];
  const r = 14 * k;
  const withRing = id === "battery";
  const ringR = 19 * k;
  const ringC = 2 * Math.PI * ringR;
  const soc = data.soc ?? null;
  const socDash = soc === null ? 0 : (Math.max(0, Math.min(100, soc)) / 100) * ringC;
  const valueX = boxDef.x + 52 * k;
  const ringCx = boxDef.x + boxDef.w - 30 * k;
  const ringCy = boxDef.y + boxDef.h / 2;
  const state = flow.edge.unknown ? "unknown" : flow.edge.idle ? "idle" : "active";
  return svg`
    <g class=${`pill pill-${id} tone-${data.tone} ${state} ${data.clickable ? "clickable" : ""}`}
       style=${`--pill-colour:${colour}`}
       role=${data.clickable ? "button" : "img"}
       tabindex=${data.clickable ? 0 : -1}
       aria-label=${`${data.label}: ${data.value}${data.sub ? ", " + data.sub : ""}`}
       @click=${() => onPill(id)}
       @keydown=${(e: KeyboardEvent) => {
         if (e.key === "Enter" || e.key === " ") {
           e.preventDefault();
           onPill(id);
        }
       }}>
      <rect x=${boxDef.x} y=${boxDef.y} width=${boxDef.w} height=${boxDef.h} rx=${r} class="pill-bg"></rect>
      <rect x=${boxDef.x} y=${boxDef.y} width=${boxDef.w} height=${boxDef.h} rx=${r} class="pill-border"></rect>
      <circle cx=${boxDef.x + 27 * k} cy=${boxDef.y + boxDef.h / 2} r=${15 * k} class="pill-icon-bg"></circle>
      ${icon(data.icon, boxDef.x + 16 * k, boxDef.y + boxDef.h / 2 - 11 * k, 22 * k, colour)}
      <text x=${valueX} y=${boxDef.y + 19 * k} class="pill-label">${data.label}</text>
      <text x=${valueX} y=${boxDef.y + (data.sub ? 39 : 42) * k} class="pill-value">${data.value}</text>
      ${data.sub ? svg`<text x=${valueX} y=${boxDef.y + (data.extra ? 52 : boxDef.h / k - 8) * k} class="pill-sub">${data.sub}</text>` : nothing}
      ${data.extra ? svg`<text x=${valueX} y=${boxDef.y + boxDef.h - 9 * k} class="pill-extra">${data.extra}</text>` : nothing}
      ${
        withRing
          ? svg`
            <circle cx=${ringCx} cy=${ringCy} r=${ringR} class="ring-track"></circle>
            ${soc === null ? nothing : svg`<circle cx=${ringCx} cy=${ringCy} r=${ringR} class="ring-fill" stroke-dasharray=${`${socDash.toFixed(1)} ${ringC.toFixed(1)}`} transform=${`rotate(-90 ${ringCx} ${ringCy})`}></circle>`}
            <text x=${ringCx} y=${ringCy + 4 * k} class="ring-value">${soc === null ? "--" : `${Math.round(soc)}%`}</text>
            <text x=${ringCx} y=${ringCy + 14 * k} class="ring-caption">SOC</text>`
          : data.clickable
            ? icon("chevron", boxDef.x + boxDef.w - 24 * k, boxDef.y + boxDef.h / 2 - 8 * k, 16 * k, "rgba(255,255,255,0.45)")
            : nothing
      }
    </g>`;
}

// ---------------------------------------------------------------------------
// Scene

export function renderScene(m: SceneModel): TemplateResult {
  if (m.artwork) return renderArtworkScene(m, m.artwork);
  const paths = flowPaths();
  const gridMoving = m.flows.grid.motion.moving;
  const inv = INVERTER_PORT;
  return svg`
    <svg class=${`scene ${m.daylight} ${m.stale ? "stale" : ""} ${m.animate ? "" : "still"}`} viewBox=${`0 0 ${SCENE_W} ${SCENE_H}`} preserveAspectRatio="xMidYMid meet" aria-label="Isometric energy flow scene">
      <defs>
        <radialGradient id="ef3d-sky" cx="30%" cy="12%" r="80%">
          <stop offset="0%" class="sky-a"></stop>
          <stop offset="100%" class="sky-b"></stop>
        </radialGradient>
        <linearGradient id="ef3d-ground-sheen" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.07"></stop>
          <stop offset="55%" stop-color="#ffffff" stop-opacity="0"></stop>
          <stop offset="100%" stop-color="#000000" stop-opacity="0.18"></stop>
        </linearGradient>
        <linearGradient id="ef3d-pv-glare" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.22"></stop>
          <stop offset="45%" stop-color="#ffffff" stop-opacity="0.02"></stop>
          <stop offset="100%" stop-color="#ffffff" stop-opacity="0"></stop>
        </linearGradient>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.4"></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5"></feGaussianBlur></filter>
      </defs>
      <rect x="0" y="0" width=${SCENE_W} height=${SCENE_H} fill="url(#ef3d-sky)" class="sky"></rect>
      <g class="celestial">
        <circle cx="300" cy="96" r="14" class="moon"></circle>
        <circle cx="300" cy="96" r="30" class="moon-halo"></circle>
        <circle cx="318" cy="128" r="17" class="sun-disc"></circle>
        <circle cx="318" cy="128" r="56" class="sun-halo"></circle>
        ${[
          [40, 92],
          [122, 46],
          [180, 112],
          [236, 70],
          [352, 150],
          [392, 60],
          [20, 160],
          [288, 20],
        ].map(([x, y]) => svg`<circle cx=${x} cy=${y} r="1.1" class="star"></circle>`)}
      </g>
      ${ground()}
      ${tree(-6.5, -4.6, 13, "back")}
      ${tree(-2.5, -5.2, 10, "back")}
      ${tree(9.5, -5.6, 11, "back")}
      ${shrub(-7.2, 1.2, 8)}
      ${shrub(-6.6, -1, 7)}
      ${shrub(5, 5.2, 7)}
      ${shrub(6.4, 6.4, 6)}
      ${shrub(-1.5, 7.2, 8)}
      ${lamp(-4.8, 6.6)}
      ${lamp(3.9, 5.2)}
      ${lamp(7.4, 8.6)}
      ${pylon(gridMoving, m.flows.grid.edge.unknown)}
      ${house()}
      ${batteryCabinet(m.pills.battery.soc ?? null)}
      ${tree(-7.6, 8.6, 12, "front")}
      ${shrub(1.2, 8.8, 7)}
      <g class="flows">
        ${flowPath("grid", "grid", paths.grid, m.flows.grid, m.animate)}
        ${flowPath("solar", "solar", paths.solar, m.flows.solar, m.animate)}
        ${flowPath("battery", "battery", paths.battery, m.flows.battery, m.animate)}
        ${flowPath("home", "home", paths.home, m.flows.home, m.animate)}
        <circle cx=${inv.x} cy=${inv.y} r="4.2" class=${`junction led-${m.inverterLed}`}></circle>
        <circle cx=${inv.x} cy=${inv.y} r="9" class=${`junction-halo led-${m.inverterLed}`}></circle>
      </g>
      ${pill("solar", PILLS.solar, m.pills.solar, m.onPill, m.flows.solar)}
      ${pill("grid", PILLS.grid, m.pills.grid, m.onPill, m.flows.grid)}
      ${pill("home", PILLS.home, m.pills.home, m.onPill, m.flows.home)}
      ${pill("battery", PILLS.battery, m.pills.battery, m.onPill, m.flows.battery)}
    </svg>`;
}

/**
 * Artwork plate + live overlays. The plate is a fixed-perspective illustration
 * with no lines, labels or figures of its own; every value and every moving
 * element is drawn here, so the picture can never contradict the telemetry.
 */
function renderArtworkScene(m: SceneModel, art: NonNullable<SceneModel["artwork"]>): TemplateResult {
  const L = art.layout;
  const P = L.paths();
  const k = L.scale;
  const A = L.anchors;
  const split = m.solarSplit ?? { card: m.flows.solar, main: m.flows.solar, garage: null };
  const riserOf = (key: RouteKey): string => {
    const pts = L.routes[key];
    const [a, b] = key === "home" ? [pts[0]!, pts[1]!] : [pts[pts.length - 2]!, pts[pts.length - 1]!];
    return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
  };
  const power = (id: FlowId, key: RouteKey, view: FlowView) => flowPath(id, key, P[key], view, m.animate, k, approxLength(P[key]), riserOf(key));
  const lit = (v: FlowView | null) => !!v && v.motion.moving;
  const vertices = Object.entries(L.routes) as Array<[RouteKey, Array<{ x: number; y: number }>]>;
  const debug = art.debug
    ? svg`<g class="debug">
        ${V4_PAVING.map((e) => svg`<polyline points=${e.points.map((p) => `${p.x},${p.y}`).join(" ")} class="debug-paving"></polyline><text x=${e.points[0]!.x + 4 * k} y=${e.points[0]!.y - 4 * k} class="debug-paving-label">${e.label}</text>`)}
        ${L.routes.battery.map((p, i) => svg`<circle cx=${p.x} cy=${p.y} r=${5 * k} class="debug-waypoint"></circle><text x=${p.x + 7 * k} y=${p.y + 4 * k} class="debug-waypoint-label">${i + 1} ${BATTERY_WAYPOINTS[i] ?? ""}</text>`)}
        <line x1=${A.lawn_transition.x} y1=${L.routes.battery[1]!.y} x2=${A.lawn_transition.x} y2=${L.routes.battery[2]!.y} class="debug-buried"></line>
        ${vertices.map(([key, pts]) =>
          pts.map((p, i) => (i === 0 || i === pts.length - 1 ? nothing : svg`<rect x=${p.x - 3 * k} y=${p.y - 3 * k} width=${6 * k} height=${6 * k} class="debug-bend" data-route=${key}></rect>`))
        )}
        ${Object.values(A).map((a) => svg`<circle cx=${a.x} cy=${a.y} r=${4 * k} class="debug-dot"></circle><circle cx=${a.x} cy=${a.y} r=${9 * k} class="debug-ring"></circle><text x=${a.x + 11 * k} y=${a.y - 6 * k} class="debug-label">${a.label} ${a.x},${a.y}</text>`)}
        ${Object.entries(L.pills).map(([name, p]) => svg`<rect x=${p.x} y=${p.y} width=${p.w} height=${p.h} class="debug-zone"></rect><circle cx=${p.port.x} cy=${p.port.y} r=${3.5 * k} class="debug-port"></circle><text x=${p.port.x + 8 * k} y=${p.port.y + 4 * k} class="debug-label">${name} port</text>`)}
        <rect x=${L.entry.x0} y=${L.entry.y0} width=${L.entry.x1 - L.entry.x0} height=${L.entry.y1 - L.entry.y0} class="debug-zone"></rect>
        <text x=${L.entry.x1 + 6 * k} y=${L.entry.y1 + 4 * k} class="debug-label">ground convergence ${A.ground_entry.x},${A.ground_entry.y}</text>
        <rect x=${L.entry.x0 + 2} y=${L.inverter.y} width=${L.entry.x1 - L.entry.x0 - 4} height=${L.entry.y0 - L.inverter.y} class="debug-riser"></rect>
        <text x=${L.entry.x1 + 6 * k} y=${(L.inverter.y + L.entry.y0) / 2} class="debug-label">grouped riser (5 tracks)</text>
        <line x1=${L.inverter.x - 30} y1=${L.inverter.y} x2=${L.inverter.x + 30} y2=${L.inverter.y} class="debug-entry"></line>
      </g>`
    : nothing;
  return svg`
    <svg class=${`scene artwork ${m.daylight} ${m.stale ? "stale" : ""} ${m.animate ? "" : "still"}`} viewBox=${`0 0 ${L.width} ${L.height}`} preserveAspectRatio="xMidYMid meet" style=${`--k:${k}`} aria-label="Energy flow scene">
      <defs>
        <filter id="ef3d-blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation=${(1.6 * k).toFixed(1)}></feGaussianBlur></filter>
        <filter id="ef3d-blur-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${(3.5 * k).toFixed(1)}></feGaussianBlur></filter>
      </defs>
      ${art.layers.map(
        (layer) => svg`<image href=${layer.url} x="0" y="0" width=${L.width} height=${L.height} preserveAspectRatio="xMidYMid meet" class=${`plate ${layer.entering ? "entering" : ""}`} data-scene=${layer.key} @error=${() => art.onError(layer.url)} @load=${() => art.onLoad(layer.url)}></image>`
      )}
      ${cablePit(L.entry, k)}
      <g class="flows">
        ${infoLink("solar", P.solarInfo, FLOW_COLOUR.solar, lit(split.card), k)}
        ${infoLink("battery", P.batteryInfo, FLOW_COLOUR.battery, lit(m.flows.battery), k)}
        ${infoLink("grid", P.gridInfo, FLOW_COLOUR.grid, lit(m.flows.grid), k)}
        ${infoLink("home", P.homeInfo, FLOW_COLOUR.home, lit(m.flows.home), k)}
        ${power("grid", "grid", m.flows.grid)}
        ${power("battery", "battery", m.flows.battery)}
        ${power("solar", "solarMain", split.main)}
        ${split.garage ? power("solar", "solarGarage", split.garage) : nothing}
        ${power("home", "home", m.flows.home)}
        ${nodeLight(A.main_pv_frame, FLOW_COLOUR.solar, lit(split.main), k)}
        ${split.garage ? nodeLight(A.garage_pv_frame, FLOW_COLOUR.solar, lit(split.garage), k) : nothing}
        ${nodeLight(A.battery_cabinet, FLOW_COLOUR.battery, lit(m.flows.battery), k)}
        ${nodeLight(A.pylon, FLOW_COLOUR.grid, lit(m.flows.grid), k)}
        ${nodeLight(A.house, FLOW_COLOUR.home, lit(m.flows.home), k)}
        <rect x=${L.inverter.x - 12 * k} y=${L.inverter.y - 1.2 * k} width=${24 * k} height=${2.4 * k} rx=${1.2 * k} class=${`junction-bar led-${m.inverterLed}`}></rect>
        <circle cx=${L.inverter.x} cy=${L.inverter.y} r=${(7 * k).toFixed(1)} class=${`junction-halo led-${m.inverterLed}`}></circle>
      </g>
      ${debug}
      ${pill("solar", L.pills.solar, m.pills.solar, m.onPill, m.flows.solar, k)}
      ${pill("grid", L.pills.grid, m.pills.grid, m.onPill, m.flows.grid, k)}
      ${pill("home", L.pills.home, m.pills.home, m.onPill, m.flows.home, k)}
      ${pill("battery", L.pills.battery, m.pills.battery, m.onPill, m.flows.battery, k)}
    </svg>`;
}

export { FLOW_COLOUR };
