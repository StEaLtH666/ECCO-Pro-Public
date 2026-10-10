import { LitElement, html, css, svg, nothing, type TemplateResult, type PropertyValues } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { ifDefined } from "lit/directives/if-defined.js";
import {
  DEFAULT_ICONS,
  DEFAULT_LABELS,
  normaliseBatteryPower,
  normaliseGridPower,
  normaliseSolarSources,
  resolveHomeW,
  type DiagramNodeKind,
  type EccoEnergyFlowCardConfig,
  type SolarNodeConfig,
} from "./config";
import { formatEnergy, formatPercent, formatPower, reserveRuntimeLine, reserveRuntimeTooltip, toNumber } from "./utils/format";
import {
  batteryStatus,
  classifyGridConnected,
  gridConnectedDisplay,
  resolveReserveRuntime,
  resolveTimeToReserveMinutes,
  socDisplay,
  type ReserveRuntime,
} from "./utils/display";

// Minimal shape of the pieces of `hass` this card actually reads. Avoids a
// dependency on the (large, versioned) full Home Assistant frontend types.
interface HassEntity {
  state: string;
  attributes?: Record<string, unknown>;
}
interface HomeAssistantLike {
  states: Record<string, HassEntity | undefined>;
  themes?: { darkMode?: boolean };
}

interface FlowNode {
  /** Which diagram node KIND this is - several solar nodes can share `kind: "solar"`. */
  kind: DiagramNodeKind;
  /** Stable per-render key for Lit's keyed rendering - unique even across multiple solar nodes. */
  id: string;
  label: string;
  icon: string;
  x: number;
  y: number;
}

/**
 * Which CSS custom property (see `:host` in `static styles`) colours a given
 * flow line/arrow/node border. Battery and grid each have three STATE
 * variants (rather than one static colour) so the line, the node border,
 * the node's subtle background tint, and its soft glow can all react to
 * the live direction of flow - see `_buildLines()`/`_renderBottomNode()`
 * for where each is chosen, and the `--ecco-line-*` custom properties in
 * `static styles` for the actual colours.
 */
type FlowColourKind =
  | "solar"
  | "home"
  | "grid-import"
  | "grid-export"
  // "grid-idle" now means SPECIFICALLY "connected, confirmed ~0W" - see
  // _gridState()'s own doc comment for the full 5-state model this round
  // introduced. Kept the existing name (not renamed to "grid-connected-
  // idle") since every other node's own "-idle" colour kind already means
  // "no flow right now, otherwise nothing wrong" - Grid's new refined
  // meaning is consistent with that, just more precisely defined.
  | "grid-idle"
  | "grid-disconnected"
  | "grid-unavailable"
  | "battery-charge"
  | "battery-discharge"
  | "battery-idle"
  | "generator";

interface FlowLine {
  id: string;
  /** SVG path `d` attribute - already oriented start-to-end in the direction of current flow, insets applied. */
  d: string;
  /** Absolute flow magnitude in watts, used for animation speed and line thickness. */
  magnitudeW: number;
  /** True when there is no meaningful flow to show (unavailable or ~0). */
  idle: boolean;
  colour: FlowColourKind;
  /** Arrowhead placement - a small triangle positioned/rotated at the line's receiving end via an SVG transform (no `<marker>`/`url(#id)` reference - see the class-level rendering note). */
  arrow: { x: number; y: number; angleDeg: number };
}

/**
 * The single most relevant configured entity for each diagram node, used
 * only to wire up "tap to open more-info" (see `_moreInfo()`). Built once
 * in `render()` from whatever the user actually configured under `nodes:`
 * - never a hard-coded/guessed entity id, and `undefined` for any node
 * with nothing suitable configured, which simply renders that node as
 * non-interactive.
 */
interface EntityIdMap {
  solar: (string | undefined)[];
  solarTotal: string | undefined;
  inverter: string | undefined;
  home: string | undefined;
  battery: string | undefined;
  grid: string | undefined;
  generator: string | undefined;
}

const MAX_ANIMATION_MAGNITUDE_W = 6000; // magnitude at/above which animation reaches its fastest speed
const MIN_DURATION_S = 0.45;
const MAX_DURATION_S = 2.6;
const IDLE_THRESHOLD_W = 5; // below this magnitude a flow is treated as idle/no-flow
// The BASE wire (the dim, always-solid stroke - see .flow-line-base) only
// scales a little, on purpose: the maintainer's explicit brief for this round is
// that the animated packet overlay, not the wire underneath it, should be
// what communicates how much power is moving. Deliberately a small range.
const MIN_LINE_WIDTH_PX = 2.6;
const MAX_LINE_WIDTH_PX = 3.3;
// The packet overlay's OWN thickness range - this is the one the maintainer wants
// genuinely obvious, so it gets a wider swing than the base wire, still
// short of "neon pipe" territory (see MAX_ANIMATION_MAGNITUDE_W's own
// dominant-hardware note elsewhere in this file).
const MIN_PACKET_WIDTH_PX = 2.7;
const MAX_PACKET_WIDTH_PX = 5.4;

// Energy-ball secondary layer (this round's addition - see _renderEnergyBalls()).
// An EARLIER round tried plain animateMotion circles here and the maintainer's own
// live-use feedback was that they "didn't read as visible flow at all" -
// see the comment on DASH_PERIOD below, which predates this round and is
// the reason this pass deliberately makes the balls bigger/brighter
// (bright white core + coloured glow halo, not a flat colour dot) rather
// than repeating that same under-sized attempt.
const MIN_BALL_RADIUS_PX = 3.1;
const MAX_BALL_RADIUS_PX = 4.9;
// Balls get their OWN duration range, wider and slower-at-the-low-end
// than the packet layer's own MIN/MAX_DURATION_S - a low-power ball
// should feel genuinely "occasional" (the maintainer's own word), not just a
// fraction of an already-fast dash cycle. Still always faster than the
// packet layer at the SAME magnitude (5.5s ball vs 2.6s-max packet at
// the slowest end, and 0.6s ball vs 0.45s-min packet at the fastest -
// see _renderEnergyBalls()).
const MIN_BALL_DURATION_S = 0.6;
const MAX_BALL_DURATION_S = 5.5;

/**
 * Magnitude -> normalized [0, 1] animation intensity, logarithmic rather
 * than linear. A linear `magnitude / MAX_ANIMATION_MAGNITUDE_W` (the
 * previous approach) compresses the entire everyday operating range - a
 * few tens of watts up to a few kW - into the bottom ~10-50% of the
 * curve, since MAX_ANIMATION_MAGNITUDE_W (6000W) has to stay large enough
 * to cover genuine high-power moments too. The visible result was the maintainer's
 * exact complaint: 25W, 250W, 500W, and 1kW all animated at nearly the
 * same speed/density, because they ARE nearly the same point on a linear
 * 0-6000W ruler. A log scale instead treats equal MULTIPLES of power
 * (25W -> 50W -> 100W is the same "distance" as 500W -> 1kW -> 2kW) as
 * equal visual steps, which is how the eye actually judges "twice as much
 * flow" - so the low/mid range most real households sit in most of the
 * time gets genuine, obvious separation, while the curve still tops out
 * exactly at MAX_ANIMATION_MAGNITUDE_W (no invented ceiling). Anchored at
 * IDLE_THRESHOLD_W, not 0 or 1W, so the slowest non-idle reading (just
 * above the idle cutoff) is also the slowest point on the curve - no
 * discontinuity between "idle" (no animation at all) and "just barely
 * flowing" (the animation's own minimum speed).
 *
 * SECOND pass (this round): the plain log curve above was still too
 * energetic in the everyday 20-750W band - the maintainer's exact complaint was
 * that a 20W trickle and a several-hundred-watt flow both already looked
 * fairly active, with the real visual "arrival" only happening well above
 * 1kW. Raising the log result to INTENSITY_EXPONENT (>1) pushes the WHOLE
 * low/mid range down further, disproportionately more at low t than high
 * t (e.g. 0.5 -> 0.5^2.4 ~= 0.19, a much bigger cut than 0.95 -> 0.95^2.4
 * ~= 0.88), which is exactly "compress the low end heavily, leave the
 * high end broadly alone": the curve still reaches exactly 1.0 at
 * MAX_ANIMATION_MAGNITUDE_W (t=1 is a fixed point of any power curve), so
 * 6kW+ behaviour is untouched, while 20-750W now sits much closer to the
 * curve's own floor than before.
 */
const INTENSITY_EXPONENT = 2.4;

function magnitudeToIntensity(magnitudeW: number): number {
  if (magnitudeW <= IDLE_THRESHOLD_W) return 0;
  const raw = Math.log(magnitudeW / IDLE_THRESHOLD_W) / Math.log(MAX_ANIMATION_MAGNITUDE_W / IDLE_THRESHOLD_W);
  const clamped = Math.min(1, Math.max(0, raw));
  return Math.pow(clamped, INTENSITY_EXPONENT);
}

/**
 * Energy-ball COUNT, separately from the continuous intensity curve above
 * - The maintainer described this as explicit bands ("~20-50W: one ball... ~750W-
 * 1.5kW: 1-2 balls... ~3-6kW: 3 balls... 6kW+: 3-4 balls"), which a smooth
 * curve fights to hit precisely at every one of several named thresholds
 * simultaneously. A direct threshold table hits his numbers exactly and
 * stays easy to re-tune band-by-band without disturbing the continuous
 * properties (dash speed/density, glow, ball speed) that DO still come
 * from `magnitudeToIntensity()`. Idle (0 balls) is handled by the caller
 * via `line.idle`, not here.
 */
function ballCountForMagnitude(magnitudeW: number): number {
  if (magnitudeW < 750) return 1;
  if (magnitudeW < 3000) return 2;
  if (magnitudeW < 6000) return 3;
  return 4;
}

// Pylon PULSE (this round's addition) - a smooth breathing brightness/glow
// animation on the pylon GRAPHIC ITSELF, not the whole Grid box (the maintainer's
// explicit distinction). Coherent with, but not literally phase-locked to,
// the route's own dash/ball speed: it reuses the SAME magnitudeToIntensity()
// relationship (faster/brighter at higher power) with its own tuned range,
// so the three cues (line, balls, pylon) read as one "this much power is
// moving" feeling rather than three unrelated animations. connected-idle and
// disconnected get their own FIXED durations instead, since there is no real
// magnitude to scale from at ~0W - deliberately two DIFFERENT fixed paces
// (not just two different colours) so disconnected reads as "alert" even at
// a glance: quicker than the idle heartbeat, but still explicitly NOT fast
// (the maintainer: "not frantic").
const MIN_PYLON_PULSE_S = 1.3; // fastest breathing - at/above MAX_ANIMATION_MAGNITUDE_W
const MAX_PYLON_PULSE_S = 6.5; // slowest breathing - just above IDLE_THRESHOLD_W
const PYLON_IDLE_PULSE_S = 7; // connected, ~0W - "still alive" heartbeat
const PYLON_DISCONNECTED_PULSE_S = 2.3; // a distinct, slightly quicker warning cadence - never as fast as a normal high-power pulse

/** Pylon pulse duration in seconds for a given Grid state. "unavailable" has no pulse at all - callers special-case it before calling this (see _renderBottomNode()). */
function pylonPulseDurationS(kind: "importing" | "exporting" | "connected-idle" | "disconnected", magnitudeW: number): number {
  if (kind === "connected-idle") return PYLON_IDLE_PULSE_S;
  if (kind === "disconnected") return PYLON_DISCONNECTED_PULSE_S;
  const t = magnitudeToIntensity(Math.abs(magnitudeW));
  return MAX_PYLON_PULSE_S - t * (MAX_PYLON_PULSE_S - MIN_PYLON_PULSE_S);
}

// UniFi-topology-style packet flow: the animated overlay stroke's own
// dash pattern is the "packets", not a separate SVG shape riding the path
// (an earlier round's animateMotion circles - technically present, but
// The maintainer's live-use feedback was they didn't read as visible flow at all).
// DASH_PERIOD is fixed so the existing @keyframes ecco-dash's `-30`
// stroke-dashoffset target (exactly 2x this period) stays a seamless loop
// at every magnitude - only the dash:gap RATIO within that fixed period
// changes with power, sparse short dashes near idle widening into a
// near-continuous stream at high power (see _renderLine()).
const DASH_PERIOD = 15;
const PACKET_DASH_MIN = 4; // sparse - short bright packets, long dim gaps
const PACKET_DASH_MAX = 9; // dense - a near-continuous bright stream

// ONE shared corner radius for every rounded bend in the diagram - the maintainer's
// explicit "consistent bend radius" request. `roundedCorner()` clamps this
// down per corner to at most half of whichever adjoining leg is shorter,
// so a short jog still naturally renders a tighter curve than a long
// elbow's much longer legs do, WITHOUT this being a second, differently-
// tuned number - one constant, organically different results per route.
const ROUTE_RADIUS = 20;

// TRUE PORT GEOMETRY (this round's architecture pass): every route
// endpoint used to be a *guessed* pullback from a node's LOGICAL (x, y) -
// a fixed "inset" tuned by hand against one reference card width. That
// approach was fundamentally unfixable: node sizes are real CSS pixels
// while the inset lived in a separate logical-unit space mapped onto a
// variable-width container, so the same inset was only ever exactly
// right at one scale - too small at some widths (lines hidden deep under
// a node) and too large at others (lines visibly floating disconnected
// from it), and every round spent fixing one case re-broke the other.
//
// This round removes the guesswork entirely. Every node that participates
// in the flow network now renders a real, tiny `[data-port]` marker
// element at its own actual connection point (see e.g. `.inverter-port`,
// `.solar-port`, `.battery-port`) - a real DOM element with a real
// rendered position. After every layout-affecting render, `_measurePorts()`
// reads each one's ACTUAL `getBoundingClientRect()` centre (see below) and
// stores it, in `.flow`-container-relative CSS pixels, in `this._ports`.
// `_buildLines()` then builds every route directly from those measured
// points - never from a guess. The SVG's own `viewBox` is set to `.flow`'s
// real measured pixel size too (not a fixed logical box), so a measured
// point maps into SVG-user-space with NO scale factor at all - the same
// number of pixels, always, at every card width. A route's endpoint is
// therefore the real port's centre, full stop; the only "inset" left
// anywhere is `PORT_UNDERLAP`, a deliberately tiny (not a guess - an
// anti-aliasing seam only) pull-in below.
const PORT_UNDERLAP = 0.4; // px pulled back UNDER the port's own rendered edge, purely to avoid a hairline antialiasing seam at the join - never used to "hide" imprecision; kept well under the 1.5px error budget verification targets

/** Which edge of a node a port sits on, i.e. which axis its connecting line leaves/arrives along - "h" = left/right (a horizontal first/last segment), "v" = top/bottom (a vertical one). Drives which of `buildRouteD()`'s orthogonal-bend families applies to a given connection. */
type PortAxis = "h" | "v";

// How far along a route (as a fraction of the from->to span, applied at
// the FROM end) an orthogonal bend's jog happens - see `buildRouteD()`.
// Small = "short lead-out near the source, long confident final approach"
// (Solar's own legs into the PV junction, the inverter's own load port
// into Home); ~middle = "both ends are equally real ports, no reason to
// favour either" (Battery/Grid, now at genuinely different heights than
// the inverter in this round's asymmetric composition, so they need a
// real bend where the old symmetric layout never did).
const BEND_FRACTION_EARLY = 0.3;
const BEND_FRACTION_MID = 0.52;
// Where the PV bus junction sits vertically, as a fraction of the span
// from the (measured) solar ports down to the (measured) inverter PV
// port - mathematically tied to the real ports per this round's brief,
// never a fixed canvas coordinate. Its X is simply the inverter PV
// port's own X (see `_buildLines()`) - that makes the trunk a clean
// straight run by construction, whatever the two solar legs' own (now
// asymmetric, possibly unequal) bends look like either side of it.
const JUNCTION_Y_FRACTION = 0.4;

const FAULT_KEYWORDS = ["fault", "alarm", "error"];
const WARNING_KEYWORDS = ["warning", "standby", "self-check", "self check"];

interface RoutePoint {
  x: number;
  y: number;
}

function fmtPoint(p: RoutePoint): string {
  return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
}

/**
 * Pulls a sharp corner into a radius-`radius` rounded curve - the one
 * shared building block every route buildRouteD() generates is made of.
 * Returns the
 * point where the curve begins (pulled back along the INCOMING leg,
 * toward `from`) and ends (pulled forward along the OUTGOING leg, toward
 * `to`) - draw a straight `L` to `enter`, a quadratic `Q corner exit`,
 * then continue with a straight `L` from `exit`. `r` is clamped to at
 * most half of the SHORTER adjoining leg so it can never overshoot into a
 * degenerate/self-overlapping curve on a short segment - callers should
 * treat `r < 1` as "too short for a visible curve" and fall back to a
 * plain sharp corner (an `L` straight through `corner`) instead of
 * emitting a Bezier so small it would render as an artefact.
 */
function roundedCorner(corner: RoutePoint, from: RoutePoint, to: RoutePoint, radius: number): { enter: RoutePoint; exit: RoutePoint; r: number } {
  const legIn = Math.hypot(corner.x - from.x, corner.y - from.y) || 1;
  const legOut = Math.hypot(to.x - corner.x, to.y - corner.y) || 1;
  const r = Math.max(0, Math.min(radius, legIn * 0.5, legOut * 0.5));
  return {
    enter: { x: corner.x - ((corner.x - from.x) / legIn) * r, y: corner.y - ((corner.y - from.y) / legIn) * r },
    exit: { x: corner.x + ((to.x - corner.x) / legOut) * r, y: corner.y + ((to.y - corner.y) / legOut) * r },
    r,
  };
}

/**
 * The one route-geometry engine every connection in the diagram now goes
 * through (this round's "single source of truth" architecture pass - see
 * the TRUE PORT GEOMETRY note above `PORT_UNDERLAP`). `from`/`to` are REAL
 * measured port centres (already `PORT_UNDERLAP`-adjusted by the caller,
 * see `_buildLines()`), never guessed coordinates. `fromAxis`/`toAxis` say
 * which edge each port sits on - that alone is enough to derive a clean
 * orthogonal wiring-style route with zero, one, or two rounded bends,
 * generically:
 *
 * - Both ports face the same axis AND already share the other coordinate
 *   (e.g. both "v" - top/bottom-facing - and already the same X): a plain
 *   straight run, no bend needed at all.
 * - Both face the same axis but DON'T share the other coordinate (e.g.
 *   both "v" but different X - exactly what an asymmetric layout
 *   produces): a two-corner jog - leave along the axis, one perpendicular
 *   shift at `bendFraction` of the way along, continue along the axis into
 *   the port. `bendFraction` near 0 reads as "short lead-out near the
 *   source, long confident final approach" (use for a small node feeding a
 *   dominant one); near 0.5 reads as "both ends are equally real ports"
 *   (use when neither end should visually dominate the bend).
 * - The two ports face DIFFERENT axes (one "h", one "v"): a single corner
 *   at the point sharing the "v" port's X and the "h" port's Y - the
 *   classic single-elbow "shared trunk, clean branch" join.
 *
 * Reversal stability (unchanged principle from earlier rounds): the
 * corner list is always computed from the FIXED, never-swapped `from`/`to`
 * first; `reversed` only changes which physical point the path is drawn
 * `M`-ing from (and, since `roundedCorner()` is recomputed per corner from
 * whichever point is now "prev"/"next" in that reversed list, its enter/
 * exit swap labels but land on the exact same physical curve points - see
 * DESIGN.md for the worked proof) - so a bidirectional line's physical
 * route never depends on which way current is currently flowing, only the
 * arrow and packet-animation direction do.
 */
function buildRouteD(
  from: RoutePoint,
  to: RoutePoint,
  fromAxis: PortAxis,
  toAxis: PortAxis,
  bendFraction: number,
  radius: number,
  reversed: boolean
): { d: string; arrowTangentFrom: RoutePoint; end: RoutePoint } {
  const ALIGNED_EPS = 1.5;
  const dx = to.x - from.x;
  const dy = to.y - from.y;

  let corners: RoutePoint[];
  if (fromAxis === "v" && toAxis === "v" && Math.abs(dx) < ALIGNED_EPS) {
    corners = [];
  } else if (fromAxis === "h" && toAxis === "h" && Math.abs(dy) < ALIGNED_EPS) {
    corners = [];
  } else if (fromAxis === "v" && toAxis === "v") {
    const jogY = from.y + dy * bendFraction;
    corners = [
      { x: from.x, y: jogY },
      { x: to.x, y: jogY },
    ];
  } else if (fromAxis === "h" && toAxis === "h") {
    const jogX = from.x + dx * bendFraction;
    corners = [
      { x: jogX, y: from.y },
      { x: jogX, y: to.y },
    ];
  } else if (fromAxis === "v") {
    // "from" leaves vertically, "to" arrives horizontally - one corner
    // sharing from's X (the vertical run) and to's Y (the horizontal run).
    corners = [{ x: from.x, y: to.y }];
  } else {
    corners = [{ x: to.x, y: from.y }];
  }

  const points = [from, ...corners, to];
  const ordered = reversed ? [...points].reverse() : points;

  let d = `M ${fmtPoint(ordered[0]!)}`;
  let arrowTangentFrom = ordered[0]!;
  for (let i = 1; i < ordered.length - 1; i++) {
    const prev = ordered[i - 1]!;
    const corner = ordered[i]!;
    const next = ordered[i + 1]!;
    const rc = roundedCorner(corner, prev, next, radius);
    if (rc.r >= 1) {
      d += ` L ${fmtPoint(rc.enter)} Q ${fmtPoint(corner)} ${fmtPoint(rc.exit)}`;
      arrowTangentFrom = rc.exit;
    } else {
      d += ` L ${fmtPoint(corner)}`;
      arrowTangentFrom = corner;
    }
  }
  const end = ordered[ordered.length - 1]!;
  d += ` L ${fmtPoint(end)}`;

  return { d, arrowTangentFrom, end };
}

@customElement("ecco-energy-flow-card")
export class EccoEnergyFlowCard extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistantLike;

  @state() private _config?: EccoEnergyFlowCardConfig;
  @state() private _detailsOpen = false;

  // TRUE PORT GEOMETRY measurement state (see the class-level note above
  // `buildRouteD()`). `_ports` maps each rendered `[data-port]` element's
  // `data-port` value to its measured centre, in `.flow`-container-relative
  // CSS pixels. `_flowSize` is `.flow`'s own measured pixel size, fed
  // straight into the SVG's `viewBox` so a measured port coordinate needs
  // NO scale conversion to become a valid SVG-user-space coordinate - see
  // `_measurePorts()`. Both start empty/zero; `_buildLines()` renders no
  // routes until the first real measurement lands (one frame on initial
  // load, imperceptible - see `.flow-svg` transition in static styles), far
  // preferable to drawing from a guess.
  @state() private _ports: Record<string, RoutePoint> = {};
  @state() private _flowSize: { w: number; h: number } = { w: 0, h: 0 };
  private _resizeObserver?: ResizeObserver;
  private _measureRaf = 0;
  // Which `.node-html` elements the observer above is currently watching -
  // re-synced whenever `_config` changes (the only thing that can add/
  // remove nodes, e.g. configuring a Generator or changing solar source
  // count), so a newly-appeared node's own resizing is never silently
  // unobserved.
  private _observedNodeCount = -1;
  // Energy-ball layer (see _animateBalls()'s own doc comment for why this
  // is a rAF loop, not SMIL). `_ballPathLengthCache` is keyed by the real
  // path DOM node, not its id string, specifically so it's automatically
  // garbage-collected if Lit ever recreates that node (a dangling string
  // key would just leak forever instead).
  private _ballRaf = 0;
  private _ballPathLengthCache = new WeakMap<SVGPathElement, { d: string; length: number }>();

  public static getStubConfig(): EccoEnergyFlowCardConfig {
    return {
      type: "custom:ecco-energy-flow-card",
      title: "Energy Flow",
      nodes: {
        solar: { power: "sensor.solar_power" },
        inverter: { power: "sensor.inverter_power", state: "sensor.inverter_state" },
        home: { power: "sensor.home_power" },
        battery: { power: "sensor.battery_power", soc: "sensor.battery_soc", power_sign: "charge_positive" },
        grid: { power: "sensor.grid_power", power_sign: "import_positive" },
      },
      today: {
        solar: "sensor.solar_energy_today",
        load: "sensor.load_energy_today",
        import: "sensor.grid_import_today",
        export: "sensor.grid_export_today",
        battery_charge: "sensor.battery_charge_today",
        battery_discharge: "sensor.battery_discharge_today",
      },
    };
  }

  public setConfig(config: EccoEnergyFlowCardConfig): void {
    if (!config || typeof config !== "object") {
      throw new Error("ecco-energy-flow-card: invalid configuration");
    }
    if (!config.nodes || Object.keys(config.nodes).length === 0) {
      throw new Error("ecco-energy-flow-card: at least one entry under `nodes:` is required");
    }
    this._config = config;
  }

  public getCardSize(): number {
    return 5;
  }

  protected shouldUpdate(changed: PropertyValues): boolean {
    if (!this._config) return false;
    // `_ports`/`_flowSize` are set only by `_measurePorts()` below, never
    // guessed - a real geometry change (initial measurement landing, or a
    // resize) must always be allowed to re-render so the routes stay
    // exactly on the real ports.
    if (changed.has("_config") || changed.has("_detailsOpen") || changed.has("_ports") || changed.has("_flowSize")) return true;
    // Only re-render on hass changes when a state we actually use changed value.
    // (Kept intentionally simple for the prototype - a production version
    // would diff only the configured entity ids.)
    return changed.has("hass");
  }

  protected firstUpdated(): void {
    this._syncResizeObserver();
    this._scheduleMeasure();
    this._animateBalls();
  }

  protected updated(changed: PropertyValues): void {
    // Node count can only change when the config itself changes (a
    // different solar source count, Generator toggled on/off) - re-sync
    // which `.node-html` elements the observer watches so a newly-added
    // node's own resizing is never silently missed.
    if (changed.has("_config")) {
      this._syncResizeObserver();
    }
    // `_layout()` (called from `render()`) is itself a function of
    // `_flowSize.w` - the real measured width that picks its narrow/wide
    // tier (see `_layout()`'s own `isWide`) - so a render triggered BY a
    // `_flowSize` update can move every node to a brand new position
    // without `.flow`'s own box, or any individual node box, changing
    // SIZE at all, which is the one thing ResizeObserver actually reacts
    // to. That silent mismatch was the initial-wide-load bug: the FIRST
    // real measurement lands while the DOM is still sitting in its
    // fallback narrow-tier layout (`_flowSize` starts at `{0,0}`, and
    // `_layout()` falls back to the narrow tier for any width under the
    // breakpoint, including zero); committing that measurement flips
    // `_flowSize` to its real value, which immediately re-renders into
    // the WIDE tier - but nothing then re-measured the ports at THEIR
    // new positions, so `_ports` stayed stuck holding narrow-tier
    // coordinates until a genuine resize happened to nudge
    // ResizeObserver again. Scheduling one more measurement pass
    // whenever `_flowSize` itself just changed catches exactly that:
    // Lit's synchronous DOM patch has already run by the time `updated()`
    // fires, so the follow-up `_scheduleMeasure()`'s rAF reads the real,
    // final, post-layout positions once the browser has painted them.
    // This provably cannot loop: the follow-up measurement leaves
    // `_flowSize` itself unchanged (the container's own box didn't
    // resize, only its children moved), so it never re-enters this same
    // branch on its own re-render - only `_ports` can still change from
    // it, and a `_ports`-only update isn't gated here at all. The same
    // path also correctly handles a genuine resize that crosses the tier
    // boundary the other way (wide -> narrow), for the identical reason.
    if (changed.has("_config") || changed.has("_flowSize")) {
      this._scheduleMeasure();
    }
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    this._resizeObserver?.disconnect();
    if (this._measureRaf) cancelAnimationFrame(this._measureRaf);
    if (this._ballRaf) cancelAnimationFrame(this._ballRaf);
  }

  /**
   * (Re)points the ResizeObserver at `.flow` itself (catches overall
   * container-width changes - the primary responsive driver) plus every
   * current `.node-html` box (catches a single node's own content-driven
   * height change, e.g. a status word wrapping - `.flow`'s own height is
   * aspect-ratio-locked to its width, see static styles, so it would NOT
   * itself resize from that and a box-only observer would miss it).
   * ResizeObserver reports size changes of the observed element only, not
   * position changes from a sibling resizing, which is exactly why both
   * are observed here rather than just one.
   */
  private _syncResizeObserver(): void {
    const root = this.shadowRoot;
    if (!root) return;
    const flow = root.querySelector(".flow");
    const nodeBoxes = root.querySelectorAll(".node-html");
    if (!flow) return;
    if (this._observedNodeCount === nodeBoxes.length && this._resizeObserver) return;
    this._observedNodeCount = nodeBoxes.length;
    this._resizeObserver?.disconnect();
    this._resizeObserver = new ResizeObserver(() => this._scheduleMeasure());
    this._resizeObserver.observe(flow);
    nodeBoxes.forEach((el) => this._resizeObserver!.observe(el));
  }

  /** Batches potentially-many rapid ResizeObserver callbacks (a resize gesture fires repeatedly) into a single measurement on the next animation frame. */
  private _scheduleMeasure(): void {
    if (this._measureRaf) cancelAnimationFrame(this._measureRaf);
    this._measureRaf = requestAnimationFrame(() => {
      this._measureRaf = 0;
      this._measurePorts();
    });
  }

  /**
   * The measurement itself - reads every `[data-port]` element's REAL
   * rendered centre via `getBoundingClientRect()`, relative to `.flow`'s
   * own rect (so the result is independent of the card's position on the
   * page/dashboard). Only commits to `@state` when something actually
   * moved by more than a fraction of a pixel, so a resize event that
   * didn't actually change any measured position (e.g. a vertical-only
   * resize the ports don't care about) never triggers a redundant
   * re-render.
   */
  private _measurePorts(): void {
    const root = this.shadowRoot;
    const flow = root?.querySelector(".flow");
    if (!root || !flow) return;
    const flowRect = flow.getBoundingClientRect();
    if (flowRect.width < 1 || flowRect.height < 1) return; // not laid out yet (e.g. card hidden behind an unselected dashboard tab)

    const ports: Record<string, RoutePoint> = {};
    root.querySelectorAll<HTMLElement>("[data-port]").forEach((el) => {
      const id = el.dataset.port;
      if (!id) return;
      const r = el.getBoundingClientRect();
      ports[id] = { x: r.left + r.width / 2 - flowRect.left, y: r.top + r.height / 2 - flowRect.top };
    });

    const EPS = 0.1;
    const samePorts =
      Object.keys(ports).length === Object.keys(this._ports).length &&
      Object.entries(ports).every(([id, p]) => {
        const prev = this._ports[id];
        return prev && Math.abs(prev.x - p.x) < EPS && Math.abs(prev.y - p.y) < EPS;
      });
    if (!samePorts) this._ports = ports;
    if (Math.abs(this._flowSize.w - flowRect.width) > EPS || Math.abs(this._flowSize.h - flowRect.height) > EPS) {
      this._flowSize = { w: flowRect.width, h: flowRect.height };
    }
  }

  private _state(entityId: string | undefined): HassEntity | undefined {
    if (!entityId || !this.hass) return undefined;
    return this.hass.states[entityId];
  }

  private _numeric(entityId: string | undefined): number | null {
    return toNumber(this._state(entityId)?.state);
  }

  /**
   * The single source of truth for Grid's state this round - both the
   * route (`_buildLines()`) and the node+pylon (`_renderBottomNode()`)
   * call this and use its result, so the two surfaces can never drift out
   * of sync with each other the way two independently-written `gridIdle`
   * checks could. The maintainer's explicit brief: 0W flow is NOT a fault - it
   * only means "connected and quiet right now" - and red is reserved for
   * an ACTUAL disconnected/fault signal, never invented from the power
   * reading alone. `connectedRaw` is the existing `inverter_details.
   * grid_connected` binary_sensor's own state string (already read
   * elsewhere in this file for Quick Metrics/the details panel) - the
   * ONLY connectivity signal this card already has; nothing new is
   * fabricated. Five outcomes:
   *   - "disconnected": grid_connected is explicitly off/false - a real
   *     signal, not a guess. Red, no route motion.
   *   - "unavailable": grid_connected is configured but itself
   *     unavailable/unknown (can't trust its answer either way), OR the
   *     power reading itself is null (sensor missing/unavailable/
   *     unconfigured) - grey/neutral, no route motion, no pylon pulse.
   *     This is also what a card with NO grid_connected configured at
   *     all falls back to whenever the power reading is null - it simply
   *     never has enough information to claim "disconnected".
   *   - "connected-idle": a real, valid ~0W reading with no contrary
   *     connectivity signal - muted steel-blue, still visibly "alive"
   *     (a slow pylon heartbeat - see the pulse CSS), just quiet.
   *   - "importing" / "exporting": the existing sign convention,
   *     unchanged (positive = importing).
   */
  private _gridState(
    gridW: number | null,
    connectedRaw: string | undefined
  ): { kind: "importing" | "exporting" | "connected-idle" | "disconnected" | "unavailable"; colour: FlowColourKind; statusLabel: string } {
    const isOff = classifyGridConnected(connectedRaw) === "disconnected";
    const isUnknownSignal = connectedRaw === "unavailable" || connectedRaw === "unknown";
    if (isOff) {
      return { kind: "disconnected", colour: "grid-disconnected", statusLabel: "Disconnected" };
    }
    if (isUnknownSignal || gridW === null) {
      return { kind: "unavailable", colour: "grid-unavailable", statusLabel: "Unavailable" };
    }
    if (Math.abs(gridW) < IDLE_THRESHOLD_W) {
      return { kind: "connected-idle", colour: "grid-idle", statusLabel: "Idle" };
    }
    if (gridW > 0) {
      return { kind: "importing", colour: "grid-import", statusLabel: "Importing" };
    }
    return { kind: "exporting", colour: "grid-export", statusLabel: "Exporting" };
  }

  protected render(): TemplateResult {
    if (!this._config) return html``;
    const cfg = this._config;
    const nodes = cfg.nodes ?? {};

    const solarSources = normaliseSolarSources(nodes.solar);
    const solarPowers = solarSources.map((s) => this._numeric(s.power) ?? 0);

    const inverterW = this._numeric(nodes.inverter?.power);

    const rawBatteryW = this._numeric(nodes.battery?.power);
    const batteryW = rawBatteryW === null ? null : normaliseBatteryPower(rawBatteryW, nodes.battery?.power_sign);
    const batterySoc = this._numeric(nodes.battery?.soc);
    const batterySocConfigured = !!nodes.battery?.soc;
    const timeToReserveId = nodes.battery?.time_to_reserve;
    const timeToReserveMinutes = resolveTimeToReserveMinutes(
      timeToReserveId,
      this._numeric(timeToReserveId),
      this._state(timeToReserveId)?.attributes?.unit_of_measurement
    );
    // FE-1: the same entity's own status / range / summary attributes (display only).
    const reserveRuntime = resolveReserveRuntime(timeToReserveId, timeToReserveMinutes, this._state(timeToReserveId)?.attributes);

    const rawGridW = this._numeric(nodes.grid?.power);
    const gridW = rawGridW === null ? null : normaliseGridPower(rawGridW, nodes.grid?.power_sign);
    const gridConnectedRaw = this._state(cfg.inverter_details?.grid_connected)?.state;
    const gridState = this._gridState(gridW, gridConnectedRaw);

    const homeW = resolveHomeW(this._numeric(nodes.home?.power), inverterW, gridW);

    const generatorConfigured = !!nodes.generator?.power;
    const generatorW = generatorConfigured ? this._numeric(nodes.generator?.power) ?? 0 : null;

    const layout = this._layout(solarSources, generatorConfigured, this._flowSize.w || 360);

    // The one entity each node's "tap to open more-info" should target -
    // whatever the user actually configured, power preferred over a
    // secondary reading (state/SOC) where a node has both. Never a
    // hard-coded entity id; `undefined` just means that node stays
    // non-interactive (see `_moreInfo()`).
    const entityIds: EntityIdMap = {
      solar: solarSources.map((s) => s.power),
      solarTotal: nodes.solar_total,
      inverter: nodes.inverter?.power ?? nodes.inverter?.state,
      home: nodes.home?.power,
      battery: nodes.battery?.power ?? nodes.battery?.soc,
      grid: nodes.grid?.power,
      generator: nodes.generator?.power,
    };

    // Combined solar total value: the configured `solar_total` entity is
    // AUTHORITATIVE when present (used as-is, never recalculated); when
    // absent, derive it as the sum of the configured array readings - a
    // real sum of real entities, never fabricated. Only meaningful with 2+
    // sources. Unchanged logic from the previous "Solar Total" node this
    // value used to feed - it now feeds the inverter's own "PV IN" line
    // instead (2-source case) or the still-separate combiner node (3+
    // sources, untouched - see `_layout()`).
    const solarTotalEntityW = this._numeric(nodes.solar_total);
    const derivedSolarSumW = solarPowers.reduce((sum, w) => sum + w, 0);
    const combinerW = solarSources.length > 1 ? solarTotalEntityW ?? derivedSolarSumW : null;

    const lines = this._buildLines(layout, { solarPowers, homeW, batteryW, gridW, gridState, generatorW, combinerW });

    const inverterStateText = this._state(nodes.inverter?.state)?.state;
    const inverterSeverity = this._severityFor(inverterStateText);

    return html`
      <ha-card>
        ${cfg.title ? html`<h1 class="card-title">${cfg.title}</h1>` : nothing}
        <div class="content">
          ${this._renderFlow(
            layout,
            lines,
            {
              solarPowers,
              inverterW,
              homeW,
              batteryW,
              batterySoc,
              batterySocConfigured,
              reserveRuntime,
              gridW,
              gridState,
              generatorW,
              combinerW,
            },
            inverterStateText,
            inverterSeverity,
            entityIds
          )}
          ${this._renderQuickMetrics()}
          ${this._renderToday()}
          ${this._renderBadges()}
          ${this._renderDetailsToggle()}
        </div>
      </ha-card>
    `;
  }

  // ---------------------------------------------------------------------
  // Layout
  // ---------------------------------------------------------------------

  /** Evenly spaces `count` x-positions across the shared coordinate space. 1 source is centred; 2+ fan out with a fixed margin either side. Only used for the solar row now, at every source count (see `_layout()`) - Home/Battery/Grid each have their own fixed cross-shape position and no longer fan out together. */
  private _fanOut(count: number, width: number, margin = 40): number[] {
    if (count <= 0) return [];
    if (count === 1) return [width / 2];
    const usable = width - margin * 2;
    return Array.from({ length: count }, (_, i) => margin + (usable * i) / (count - 1));
  }

  /**
   * ASYMMETRIC COMPOSITION (this round's explicit brief - "everything
   * should be offset from everything else except the two Solar arrays").
   * The inverter is still the logical hub, but is deliberately NOT the
   * geometric centre of the canvas any more - it sits right of centre.
   * Battery/Grid/Home each occupy their own distinct height and distance
   * from it, rather than mirroring each other the way the previous
   * literal cross/plus shape had them do:
   *
   *       SOLAR 1        SOLAR 2      <- the one deliberate mirrored pair
   *             \          /
   *              \        /
   *               PV bus
   *                 |
   *                 |         GRID    <- its own height, not level with Battery
   *                 |        /
   *   BATTERY   INVERTER
   *      |
   *      |             HOME           <- off both the inverter's and Grid's axis
   *
   * (indicative only - exact positions below; see the live card for the
   * real composition.) These are POSITION choices ONLY now - see the
   * class-level TRUE PORT GEOMETRY note above `buildRouteD()`: every
   * ROUTE is drawn from each node's real measured port after render,
   * never computed from these x/y numbers directly, so this layout is
   * free to keep evolving without ever needing a parallel routing model
   * kept in sync by hand.
   */
  private _layout(
    solarSources: SolarNodeConfig[],
    generatorConfigured: boolean,
    containerWidthPx: number
  ): {
    inverter: FlowNode;
    solar: FlowNode[];
    solarTotal: FlowNode | null;
    home: FlowNode;
    battery: FlowNode;
    grid: FlowNode;
    generator: FlowNode | null;
  } {
    const width = 360;
    const hasSolar = solarSources.length > 0;

    // Composition polish pass: the offsets below now come in two tiers,
    // keyed off the SAME real rendered-width breakpoint the Battery/Grid
    // box-size @container query already uses (550px), rather than one
    // fixed set of numbers stretched thin across every width. Below that
    // breakpoint we keep the tight, already-verified-safe narrow offsets;
    // at/above it - where the maintainer actually reviews the card - the
    // composition can afford to be bolder. `containerWidthPx` is the real
    // measured `.flow` pixel width (`this._flowSize.w`), falling back to
    // the logical default before the first ResizeObserver measurement
    // lands (self-corrects within one frame - see `_measurePorts()`).
    const isWide = containerWidthPx >= 550;

    // The inverter: logical hub, deliberately off-centre (right of the
    // canvas's true 180 midpoint) - see the class doc above. On WIDE
    // layouts it's pushed further right still, off the Solar pair's own
    // centreline (190) too - the PV trunk used to drop almost straight
    // down into it, which quietly preserved a strong central axis despite
    // everything else being asymmetric. Every other node's position below
    // is expressed relative to IT, not to the canvas, so the whole
    // composition moves together if this ever needs to shift again.
    const inverterX = isWide ? 215 : 189;
    const inverterY = hasSolar ? 176 : 108;

    let solar: FlowNode[] = [];
    let solarTotal: FlowNode | null = null;

    if (hasSolar) {
      // Solar 1/Solar 2 keep their own deliberate mirrored pair, centred
      // a little left of the inverter's own X (not on the canvas centre,
      // not on the inverter's X either) - close enough that the PV trunk
      // reads as a short, confident final approach, offset enough that
      // the two solar legs visibly lean toward the inverter rather than
      // dropping straight down, echoing this round's asymmetric language
      // even within the one matched pair.
      const solarCenterX = 190;
      const solarY = 46;
      const solarXs = this._fanOut(solarSources.length, width, 96);
      const xs = solarSources.length === 2 ? [solarCenterX - 80, solarCenterX + 80] : solarXs;
      solar = solarSources.map((source, i) => ({
        kind: "solar",
        id: `solar-${i}`,
        label: source.label ?? (solarSources.length > 1 ? `${DEFAULT_LABELS.solar} ${i + 1}` : DEFAULT_LABELS.solar),
        icon: source.icon ?? DEFAULT_ICONS.solar,
        x: xs[i]!,
        y: solarY,
      }));

      if (solarSources.length > 2) {
        // 3+ sources: keep the existing labelled combiner node - a genuine
        // fan-in from more than two strings reads better with a real
        // junction node than a bare dot. Untouched by this round's
        // "2-source" brief.
        solarTotal = {
          kind: "solar_total",
          id: "solar-total",
          label: DEFAULT_LABELS.solar_total,
          icon: DEFAULT_ICONS.solar_total,
          x: 190,
          y: 108,
        };
      }
    }

    const inverter: FlowNode = {
      kind: "inverter",
      id: "inverter",
      label: DEFAULT_LABELS.inverter,
      icon: DEFAULT_ICONS.inverter,
      x: inverterX,
      y: inverterY,
    };

    // Home: a genuine destination in the topology, not hanging directly
    // under the inverter on its own centreline - off-axis (right, and
    // below the inverter, but no longer AS far below - the long vertical
    // run used to read as plumbing rather than a deliberate route; pulled
    // up so the final approach stays short and confident), and off Grid's
    // own axis too so the three arms all read as occupying their own
    // distinct territory. Generator (rare, optional) sits just beyond it
    // on the same row when configured, rather than on Home's own approach
    // line.
    const HOME_GENERATOR_GAP = 58;
    const home: FlowNode = {
      kind: "home",
      id: "home",
      label: DEFAULT_LABELS.home,
      icon: DEFAULT_ICONS.home,
      x: inverterX + (isWide ? 46 : 30),
      y: inverterY + 100,
    };
    const generator: FlowNode | null = generatorConfigured
      ? {
          kind: "generator",
          id: "generator",
          label: DEFAULT_LABELS.generator,
          icon: DEFAULT_ICONS.generator,
          x: home.x + HOME_GENERATOR_GAP,
          y: home.y,
        }
      : null;

    // Battery: lower-LEFT of the inverter - further left AND further down
    // than it, never sharing its Y (that "same row, opposite sides" shape
    // is exactly the mirrored-cross look this round moves away from).
    const battery: FlowNode = {
      kind: "battery",
      id: "battery",
      label: DEFAULT_LABELS.battery,
      icon: DEFAULT_ICONS.battery,
      x: inverterX - 140,
      y: inverterY + 74,
    };
    // Grid: its own distinct height and reach - closer to the inverter's
    // own Y than Battery sits (Grid reads as sitting almost beside the
    // hub; Battery reads as sitting below-left of it), and on the
    // opposite side, so neither the distance nor the vertical
    // relationship mirrors Battery's own. Reaches further on WIDE layouts
    // (more room to spare there), stays at the tighter, already-verified
    // offset below the breakpoint. See this round's Grid identity redesign
    // in static styles for the node itself.
    const grid: FlowNode = {
      kind: "grid",
      id: "grid",
      label: DEFAULT_LABELS.grid,
      icon: DEFAULT_ICONS.grid,
      x: inverterX + (isWide ? 95 : 123),
      y: inverterY - 26,
    };

    return { inverter, solar, solarTotal, home, battery, grid, generator };
  }

  private _buildLines(
    layout: {
      inverter: FlowNode;
      solar: FlowNode[];
      solarTotal: FlowNode | null;
      home: FlowNode;
      battery: FlowNode;
      grid: FlowNode;
      generator: FlowNode | null;
    },
    powers: {
      solarPowers: number[];
      homeW: number | null;
      batteryW: number | null;
      gridW: number | null;
      gridState: { kind: "importing" | "exporting" | "connected-idle" | "disconnected" | "unavailable"; colour: FlowColourKind; statusLabel: string };
      generatorW: number | null;
      combinerW: number | null;
    }
  ): FlowLine[] {
    const lines: FlowLine[] = [];
    const ports = this._ports;
    const port = (id: string): RoutePoint | null => ports[id] ?? null;

    // Nothing to draw until the first real measurement lands (see the
    // TRUE PORT GEOMETRY note above `buildRouteD()`) - the inverter's own
    // 4 ports are the minimum every configuration needs, so their absence
    // is the one universal "not measured yet" signal.
    const invPv = port("inverter-pv");
    const invBattery = port("inverter-battery");
    const invGrid = port("inverter-grid");
    const invHome = port("inverter-home");
    if (!invPv || !invBattery || !invGrid || !invHome) return lines;

    // Solar -> PV bus junction -> Inverter PV port. See BEND_FRACTION_EARLY
    // and JUNCTION_Y_FRACTION's own doc comments for the shape/position
    // reasoning; every point here is either a real measured port or
    // (the junction only) derived directly from two of them.
    if (layout.solarTotal) {
      // 3+ sources: unchanged "every array feeds the shared combiner node,
      // one line continues from it to the inverter" pattern - the combiner
      // is a real rendered node with its own measured port now too.
      const combinerPort = port("solar-total");
      if (combinerPort) {
        layout.solar.forEach((node, i) => {
          const p = port(node.id);
          if (p) lines.push(this._routeLine(node.id, p, combinerPort, "v", "v", BEND_FRACTION_EARLY, powers.solarPowers[i] ?? 0, false, false, "solar"));
        });
        lines.push(this._routeLine("solar-total", combinerPort, invPv, "v", "v", BEND_FRACTION_EARLY, powers.combinerW ?? 0, false, false, "solar"));
      }
    } else if (layout.solar.length >= 2) {
      const solarPorts = layout.solar.map((n) => port(n.id));
      if (solarPorts.every((p): p is RoutePoint => !!p)) {
        const avgY = solarPorts.reduce((sum, p) => sum + p!.y, 0) / solarPorts.length;
        const junction: RoutePoint = { x: invPv.x, y: avgY + (invPv.y - avgY) * JUNCTION_Y_FRACTION };
        layout.solar.forEach((node, i) => {
          lines.push(this._routeLine(node.id, solarPorts[i]!, junction, "v", "v", BEND_FRACTION_EARLY, powers.solarPowers[i] ?? 0, false, false, "solar"));
        });
        lines.push(this._routeLine("pv-trunk", junction, invPv, "v", "v", BEND_FRACTION_EARLY, powers.combinerW ?? 0, false, false, "solar"));
      }
    } else if (layout.solar.length === 1) {
      // Exactly one source - direct to the inverter's PV port, no junction.
      const p = port(layout.solar[0]!.id);
      if (p) lines.push(this._routeLine(layout.solar[0]!.id, p, invPv, "v", "v", BEND_FRACTION_EARLY, powers.solarPowers[0] ?? 0, false, false, "solar"));
    }

    // Home - flows away from the inverter's own load port. Bend sits close
    // to the inverter (BEND_FRACTION_EARLY): short drop out of its own
    // port, one clean lane shift, long confident final approach into
    // Home's own top port - never a jog parked right before the
    // destination.
    const homePort = port("home");
    if (homePort) {
      lines.push(this._routeLine("home", invHome, homePort, "v", "v", BEND_FRACTION_EARLY, powers.homeW ?? 0, powers.homeW === null, false, "home"));
    }

    // Battery - now genuinely off the inverter's own Y (see this round's
    // asymmetric _layout()), so this is a real 2-corner jog, not the
    // straight run it used to be. Bend sits near the MIDDLE
    // (BEND_FRACTION_MID) - both ends are equally "real" ports here, no
    // reason to favour either.
    const batteryPort = port("battery");
    if (batteryPort) {
      const w = powers.batteryW ?? 0;
      const batteryIdle = powers.batteryW === null || Math.abs(w) < IDLE_THRESHOLD_W;
      // Internal convention: positive = discharging (battery -> inverter).
      // `from`/`to` are given in that "value >= 0" default direction; a
      // negative (charging) value reverses it to inverter -> battery. The
      // LINE colour mirrors the same three states shown on the node card
      // itself (see _renderBottomNode) - one source of truth for "what
      // state is the battery in right now", not two independent guesses.
      const colour: FlowColourKind = batteryIdle ? "battery-idle" : w >= 0 ? "battery-discharge" : "battery-charge";
      lines.push(this._routeLine("battery", batteryPort, invBattery, "h", "h", BEND_FRACTION_MID, w, powers.batteryW === null, true, colour));
    }

    // Grid - its own distinct height (see _layout()), so its own distinct
    // bend length/shape from Battery's, even though both use the same
    // family/fraction.
    const gridPort = port("grid");
    if (gridPort) {
      const w = powers.gridW ?? 0;
      // Route colour/motion comes from the shared _gridState() result, not
      // an inline recomputation - "disconnected"/"unavailable" both force
      // no route motion regardless of any residual magnitude, matching
      // _renderBottomNode()'s pylon so the two surfaces never drift.
      const { kind, colour } = powers.gridState;
      const forceUnavailable = kind === "disconnected" || kind === "unavailable";
      lines.push(this._routeLine("grid", gridPort, invGrid, "h", "h", BEND_FRACTION_MID, w, forceUnavailable, true, colour));
    }

    if (layout.generator) {
      // Generator/AUX (rare, optional) always flows toward the inverter
      // when configured - reuses the Home port's own approach rather than
      // a dedicated 5th inverter port, since it sits right beside Home in
      // the layout and was never one of this round's 4 required ports.
      const genPort = port("generator");
      if (genPort) {
        lines.push(this._routeLine("generator", genPort, invHome, "v", "v", BEND_FRACTION_MID, powers.generatorW ?? 0, powers.generatorW === null, false, "generator"));
      }
    }

    return lines;
  }

  /**
   * Builds one `FlowLine` from two REAL measured port points (see the
   * class-level TRUE PORT GEOMETRY note above `buildRouteD()`) - the thin
   * wrapper around that pure geometry function that adds idle/reversal/
   * colour/arrow handling. `from`/`to` must already be given so
   * `from -> to` matches what `value >= 0` means under this card's
   * internal sign convention (unchanged from earlier rounds - for battery,
   * positive = discharging, so `from = batteryPort, to = inverterPort`;
   * for grid, positive = importing, so `from = gridPort, to =
   * inverterPort`). `fromAxis`/`toAxis` are which edge each port sits on
   * (see `PortAxis`); `bendFraction` is where along the run a two-corner
   * jog happens, when one is needed at all.
   */
  private _routeLine(
    id: string,
    from: RoutePoint,
    to: RoutePoint,
    fromAxis: PortAxis,
    toAxis: PortAxis,
    bendFraction: number,
    value: number,
    unavailable: boolean,
    bidirectional: boolean,
    colour: FlowColourKind
  ): FlowLine {
    const magnitude = Math.abs(value);
    const idle = unavailable || magnitude < IDLE_THRESHOLD_W;
    const reversed = bidirectional && value < 0;

    // PORT_UNDERLAP: see its own doc comment - a hairline pull-in along
    // the straight chord between the two ports, purely to avoid an
    // antialiasing seam right at each port's own centre. Negligible next
    // to any real route length, including on routes with a bend.
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const fromPt: RoutePoint = { x: from.x + ux * PORT_UNDERLAP, y: from.y + uy * PORT_UNDERLAP };
    const toPt: RoutePoint = { x: to.x - ux * PORT_UNDERLAP, y: to.y - uy * PORT_UNDERLAP };

    const { d, arrowTangentFrom, end } = buildRouteD(fromPt, toPt, fromAxis, toAxis, bendFraction, ROUTE_RADIUS, reversed);
    const angleDeg = (Math.atan2(end.y - arrowTangentFrom.y, end.x - arrowTangentFrom.x) * 180) / Math.PI;

    return {
      id,
      d,
      magnitudeW: magnitude,
      idle,
      colour,
      arrow: { x: end.x, y: end.y, angleDeg },
    };
  }

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------

  /**
   * The flow diagram is two overlaid layers sharing one logical coordinate
   * space (320 wide x `height` tall, the same numbers `_layout()` places
   * nodes in):
   *   1. An absolutely-positioned `<svg>` - ONLY flow lines/arrows,
   *      nothing else. It is given explicit `width`/`height` attributes
   *      (not just a `viewBox`) so it always has a real intrinsic size.
   *   2. Ordinary HTML `<div>` node cards, absolutely positioned by
   *      percentage (each node's logical x/y divided by the 320/`height`
   *      coordinate space) with `transform: translate(-50%, -50%)` to
   *      centre each card exactly on its point. No `<foreignObject>`
   *      anywhere - `ha-icon` and friends are now plain DOM children of a
   *      plain HTML element, not foreign content inside SVG.
   * Because both layers are positioned against the SAME percentage-of-
   * container coordinate space, they stay in sync at any card width -
   * responsive resizing does not require recomputing anything in JS.
   *
   * IMPORTANT Lit detail (this is the actual fix for "lines not visibly
   * rendering" - see DESIGN.md for the full account): every helper method
   * below that returns raw SVG content (`_renderLine`) uses Lit's `svg`
   * tagged-template function, NOT `html`. Each `${...}`-interpolated
   * TemplateResult is parsed by Lit independently of where it ends up
   * being inserted - a `<path>`/`<polygon>` returned from its OWN
   * `html\`...\`` template (as the previous version of this file did) gets
   * parsed via a plain, non-SVG `<template>`, creating inert
   * HTMLUnknownElement nodes instead of real SVGPathElement/
   * SVGPolygonElement nodes. They were structurally present in the DOM
   * (correctly nested inside the `<svg>`) but never painted, because they
   * were never actually SVG elements. This is a well-documented Lit
   * gotcha, not a CSS/stacking/marker issue - the `<svg>` wrapper markup
   * written directly in THIS method's own template string (`_renderFlow`
   * itself, which stays `html` since its content is otherwise normal HTML)
   * does not give surrounding context to separately-tagged-template
   * helper methods called from within it.
   */
  private _renderFlow(
    layout: {
      inverter: FlowNode;
      solar: FlowNode[];
      solarTotal: FlowNode | null;
      home: FlowNode;
      battery: FlowNode;
      grid: FlowNode;
      generator: FlowNode | null;
    },
    lines: FlowLine[],
    powers: {
      solarPowers: number[];
      inverterW: number | null;
      homeW: number | null;
      batteryW: number | null;
      batterySoc: number | null;
      batterySocConfigured: boolean;
      reserveRuntime: ReserveRuntime | undefined;
      gridW: number | null;
      gridState: { kind: "importing" | "exporting" | "connected-idle" | "disconnected" | "unavailable"; colour: FlowColourKind; statusLabel: string };
      generatorW: number | null;
      combinerW: number | null;
    },
    inverterStateText: string | undefined,
    inverterSeverity: "ok" | "warning" | "fault" | "neutral",
    entityIds: EntityIdMap
  ): TemplateResult {
    // Node HTML placement still uses the fixed 360-wide logical space (a
    // percentage-of-container coordinate system - see _positionStyle()) -
    // that part of the architecture already worked at any width and
    // nothing about the TRUE PORT GEOMETRY pass needed to change it. The
    // SVG's OWN coordinate system is different now: its viewBox is
    // `this._flowSize`, `.flow`'s real measured pixel size (see
    // `_measurePorts()`), so a measured port coordinate (also in `.flow`-
    // relative CSS pixels) needs zero scale conversion to be a valid
    // SVG-user-space point - see the class-level note above `buildRouteD()`.
    const width = 360;
    const height = layout.home.y + 60;
    const containerStyle = `aspect-ratio: ${width} / ${height};`;
    const cfg = this._config!;
    const denseSolar = layout.solar.length > 2;
    const svgW = this._flowSize.w || width;
    const svgH = this._flowSize.h || height;
    const junction = this._computeJunction(layout);
    const pvBusActive = !layout.solarTotal && layout.solar.length >= 2;

    return html`
      <div class="flow" style=${containerStyle}>
        <svg
          class="flow-svg"
          width=${svgW}
          height=${svgH}
          viewBox="0 0 ${svgW} ${svgH}"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Live energy flow"
        >
          ${lines.map((line) => this._renderLine(line))}
          ${junction ? this._renderJunction(junction, (powers.combinerW ?? 0) < IDLE_THRESHOLD_W) : nothing}
          ${lines.map((line) => this._renderEnergyBalls(line))}
        </svg>
        ${layout.solar.map((node, i) =>
          this._renderSolarNode(
            node,
            formatPower(powers.solarPowers[i] ?? 0, cfg.format),
            width,
            height,
            denseSolar,
            (powers.solarPowers[i] ?? 0) < IDLE_THRESHOLD_W,
            entityIds.solar[i]
          )
        )}
        ${layout.solarTotal
          ? this._renderSolarTotalNode(
              layout.solarTotal,
              formatPower(powers.combinerW ?? undefined, cfg.format),
              width,
              height,
              (powers.combinerW ?? 0) < IDLE_THRESHOLD_W,
              entityIds.solarTotal
            )
          : nothing}
        ${this._renderInverterNode(
          layout.inverter,
          powers.inverterW,
          pvBusActive ? powers.combinerW : null,
          inverterStateText,
          inverterSeverity,
          width,
          height,
          entityIds.inverter
        )}
        ${this._renderBottomNode(layout.home, powers, width, height, entityIds)}
        ${this._renderBottomNode(layout.battery, powers, width, height, entityIds)}
        ${this._renderBottomNode(layout.grid, powers, width, height, entityIds)}
        ${layout.generator ? this._renderBottomNode(layout.generator, powers, width, height, entityIds) : nothing}
      </div>
    `;
  }

  /**
   * The PV bus junction's position - shared by `_buildLines()` (which
   * routes through it) and `_renderFlow()` (which draws the dot marker at
   * it), computed identically both times from the same measured ports so
   * the two can never drift apart. `null` whenever there's no 2-source PV
   * bus to draw (0/1 source, or a 3+-source config which uses the labelled
   * combiner node instead - see `_layout()`).
   */
  private _computeJunction(layout: { solar: FlowNode[]; solarTotal: FlowNode | null }): RoutePoint | null {
    if (layout.solarTotal || layout.solar.length < 2) return null;
    const invPv = this._ports["inverter-pv"];
    const solarPorts = layout.solar.map((n) => this._ports[n.id]);
    if (!invPv || !solarPorts.every((p): p is RoutePoint => !!p)) return null;
    const avgY = solarPorts.reduce((sum, p) => sum + p.y, 0) / solarPorts.length;
    return { x: invPv.x, y: avgY + (invPv.y - avgY) * JUNCTION_Y_FRACTION };
  }

  /**
   * The PV bus junction (see `_computeJunction()`) - a real wiring-
   * diagram convention for "these conductors are genuinely joined here",
   * not a node: no label, no value, no click target, just a small solid
   * dot exactly where Solar 1/2's legs and the inverter's trunk visually
   * meet. Restrained per the maintainer's "elegant and restrained... merge/
   * junction" brief - a labelled box here would just repeat the combined
   * figure the inverter's own "PV IN" row already shows. Idle dims it in
   * step with the rest of the solar family instead of leaving a bright dot
   * sitting over a dark, sleeping bus.
   */
  private _renderJunction(point: RoutePoint, idle: boolean): TemplateResult {
    return svg`<circle class="flow-junction colour-solar${idle ? " idle" : ""}" cx=${point.x.toFixed(1)} cy=${point.y.toFixed(1)} r="3.2"></circle>`;
  }

  /**
   * Renders ONE flow line as three stacked SVG elements sharing the same
   * `d`, using Lit's `svg` tag (see the note on `_renderFlow`):
   *   1. An always-solid, DIM "base" stroke - the visible bus/wire itself,
   *      deliberately subdued so the packet overlay below reads as
   *      brighter than it, and guarantees a visible route even if, for
   *      any reason, the animated layer does not animate in a given
   *      environment.
   *   2. The packet stream - NOT a separate shape riding the path (an
   *      earlier round tried small glowing `<circle>` particles via
   *      `<animateMotion>`; technically present, correctly positioned and
   *      coloured, but the maintainer's live-use feedback was that they simply
   *      didn't read as visible flow at typical dashboard viewing
   *      conditions - "the last particles were effectively invisible").
   *      This round's approach instead makes the animated overlay
   *      stroke's own dash pattern BE the packets: short bright dashes
   *      with real dim gaps between them, moving via `stroke-dashoffset`
   *      (the exact UniFi-topology-link technique this round asked for -
   *      "the bus itself should visibly carry moving traffic"). This
   *      reuses machinery `.flow-line-anim` already had (the dash
   *      animation existed since round 2) - what changed is the pattern
   *      itself becoming magnitude-scaled and load-bearing as the PRIMARY
   *      indicator, not a secondary texture: `DASH_PERIOD` stays fixed (so
   *      the shared `@keyframes ecco-dash`'s `-30` offset - exactly 2x the
   *      period - keeps looping seamlessly at every magnitude) while the
   *      dash:gap ratio within that period shifts from sparse (short
   *      packets, long dim gaps, near idle) to a near-continuous dense
   *      stream (high power) - see `PACKET_DASH_MIN`/`_MAX`. Opacity and
   *      glow radius scale the same way, so a high-power route reads as
   *      visibly brighter, not merely faster. Colour-matched glow (not a
   *      generic accent tint) via `currentColor`, same technique as the
   *      arrow/particle colour rules already used elsewhere in this file.
   *   3. A small static `<polygon>` arrowhead at the receiving end -
   *      hidden by default now that the packet stream itself carries
   *      direction (showing both would just duplicate the same
   *      information); reappears for an idle line (nothing flowing to
   *      show direction with) and under `prefers-reduced-motion: reduce`
   *      (no travel animation to rely on there) - see `.flow-arrow` in
   *      `static styles`.
   */
  private _renderLine(line: FlowLine): TemplateResult {
    // `t` (log-scaled - see magnitudeToIntensity()'s own doc comment)
    // drives every PACKET property below: speed, thickness, dash density,
    // brightness, glow - everything the maintainer wants to visibly communicate
    // "how much power is moving right now". The base wire deliberately
    // does NOT use `t` - see `tBase` below.
    const t = magnitudeToIntensity(line.magnitudeW);
    const duration = MAX_DURATION_S - t * (MAX_DURATION_S - MIN_DURATION_S);
    // The dim base wire's own thickness stays on the OLD linear ratio
    // (not the new log curve) and a narrow px range - the maintainer's explicit
    // "base wire should only scale slightly, if at all" - so it stays a
    // quiet, mostly-static backdrop even as the packet overlay above
    // becomes dramatically more energetic. Set inline per path via the
    // `--ecco-line-w` custom property so `.flow-line-base`/`.flow-line-anim`
    // in `static styles` stay the single place the property itself lives.
    const tBase = Math.min(1, line.magnitudeW / MAX_ANIMATION_MAGNITUDE_W);
    const baseWidth = MIN_LINE_WIDTH_PX + tBase * (MAX_LINE_WIDTH_PX - MIN_LINE_WIDTH_PX);
    const animWidth = MIN_PACKET_WIDTH_PX + t * (MAX_PACKET_WIDTH_PX - MIN_PACKET_WIDTH_PX);
    const baseStyle = `--ecco-line-w:${baseWidth.toFixed(2)}`;
    const dashLen = PACKET_DASH_MIN + t * (PACKET_DASH_MAX - PACKET_DASH_MIN);
    const gapLen = DASH_PERIOD - dashLen;
    const animOpacity = (0.62 + t * 0.36).toFixed(2);
    const glowPx = (1.6 + t * 2.4).toFixed(1);
    const animStyle = `animation-duration:${duration.toFixed(2)}s; --ecco-line-w:${animWidth.toFixed(2)}; stroke-dasharray:${dashLen.toFixed(1)} ${gapLen.toFixed(1)}; opacity:${animOpacity}; --ecco-glow-px:${glowPx}px`;
    const idleClass = line.idle ? " idle" : "";
    const colourClass = `colour-${line.colour}`;
    const arrowTransform = `translate(${line.arrow.x.toFixed(1)},${line.arrow.y.toFixed(1)}) rotate(${line.arrow.angleDeg.toFixed(1)})`;

    // Arrowhead triangle, ~60% of its previous size (was 10x10, points
    // 0,-5 10,0 0,5) per an earlier live-review request that it read as a
    // dominant shape rather than a directional indicator. Positioned at
    // `arrow.x/y` - the route's own receiving end, already inset just
    // outside the node's box (see _routeLine()). `data-line-id` carries
    // `line.id` (e.g. "solar-0", "pv-trunk", "battery") straight from
    // `_routeLine()` onto the base path - a plain data attribute, no
    // visual effect, purely so route-to-port verification can identify a
    // route by its actual semantic identity instead of inferring it from
    // which port happens to sit nearest (several routes can legitimately
    // share a CSS colour class, e.g. both solar legs and the PV trunk are
    // all `colour-solar`). `id` is the same value, real this time (not
    // just a data attribute) - `_animateBalls()` needs a real element id
    // to look this exact path up every frame (see its own doc comment for
    // why that's a direct DOM query rather than SMIL `<mpath href>`).
    return svg`
      <path id="flow-path-${line.id}" class="flow-line-base ${colourClass}${idleClass}" data-line-id=${line.id} style=${baseStyle} d=${line.d}></path>
      <path class="flow-line-anim ${colourClass}${idleClass}" style=${animStyle} d=${line.d}></path>
      <polygon
        class="flow-arrow ${colourClass}${idleClass}"
        points="0,-3 6,0 0,3"
        transform=${arrowTransform}
      ></polygon>
    `;
  }

  /**
   * The secondary "energy ball" layer (this round's addition) - small
   * glowing packets riding the EXACT same path `d` every route already
   * uses. First implementation used native SVG `<animateMotion>` +
   * `<mpath href="#...">`, which is the more "declarative SVG" way to do
   * this - but live testing found the browser's SMIL engine simply never
   * resolves an `<mpath href>` fragment reference against an id that
   * lives inside a shadow root (confirmed directly: the referenced
   * `<path>` genuinely exists at that id, `getElementById` finds it fine,
   * `svg.getCurrentTime()` proves the SMIL clock itself is running, but
   * the ball's own `transform` never gets set - `numberOfItems: 0`,
   * forever). Since this card only ever renders inside a shadow root,
   * that isn't a workaround-able edge case here, so this is a
   * `requestAnimationFrame` loop instead - it still reads each ball's
   * position from the SAME real rendered path via `getPointAtLength()`
   * every frame (a real geometry query, not a value baked in at render
   * time), so it stays exactly as "the real path is the source of truth"
   * as the SMIL version would have been, just driven by JS timing rather
   * than the browser's own animation engine. See `_animateBalls()`.
   * Direction correctness needs no logic here or there either way: the
   * underlying path's own `d` already encodes the CURRENT flow direction
   * in its start->end order (see the class-level TRUE PORT GEOMETRY note
   * and _routeLine()'s reversal handling - charge/discharge and import/
   * export swap which physical point is the path's start, not a separate
   * "reverse" flag), so reading the path start->end at increasing
   * `getPointAtLength()` offsets is automatically correct for whatever
   * direction is live right now. Idle lines get zero balls (the early
   * return below); reduced-motion hides the whole `.energy-ball` layer
   * via CSS, the same pattern `.flow-line-anim` already uses - and
   * `_animateBalls()` also skips its own work in that case so it isn't
   * silently computing positions for invisible elements every frame.
   */
  private _renderEnergyBalls(line: FlowLine): TemplateResult[] {
    if (line.idle) return [];
    const t = magnitudeToIntensity(line.magnitudeW);
    const duration = MAX_BALL_DURATION_S - t * (MAX_BALL_DURATION_S - MIN_BALL_DURATION_S);
    const radius = MIN_BALL_RADIUS_PX + t * (MAX_BALL_RADIUS_PX - MIN_BALL_RADIUS_PX);
    const glowPx = (3.0 + t * 3.0).toFixed(1);
    const ballCount = ballCountForMagnitude(line.magnitudeW);
    const colourClass = `colour-${line.colour}`;
    const pathId = `flow-path-${line.id}`;
    return Array.from({ length: ballCount }, (_, i) => {
      return svg`
        <g
          class="energy-ball ${colourClass}"
          data-ball-path=${pathId}
          data-ball-duration=${duration.toFixed(3)}
          data-ball-phase=${(i / ballCount).toFixed(3)}
          style=${`--ecco-ball-glow:${glowPx}px`}
        >
          <circle class="ball-glow" r=${radius.toFixed(2)}></circle>
          <circle class="ball-core" r=${(radius * 0.42).toFixed(2)}></circle>
        </g>
      `;
    });
  }

  /**
   * Drives every `.energy-ball` group's position, once per animation
   * frame - see `_renderEnergyBalls()`'s doc comment for why this exists
   * instead of native SMIL. Reads each ball's own `data-ball-*`
   * attributes (set fresh by every render, so a magnitude change picking
   * a new duration/phase/ball-count is picked up automatically without
   * this loop needing to know anything changed) and looks its target
   * path up by id every frame via a plain DOM query - cheap, and immune
   * to the exact stale-reference/re-render-timing bugs a cached element
   * reference could hit if Lit ever recreates that path node. Path
   * LENGTH is cached per path element (keyed off its own `d` string, so
   * a genuine shape change - resize, reversal - invalidates it
   * automatically) since `getTotalLength()` is real geometry work and
   * this runs 60 times a second; re-reading `d` as a cheap string compare
   * to decide whether to recompute is far cheaper than calling it fresh
   * for every ball every frame. Reduced-motion and idle are both already
   * handled before a ball element even exists (CSS hides the layer;
   * `_renderEnergyBalls()` renders zero balls for an idle line), so the
   * only thing checked here is reduced-motion again specifically to skip
   * the per-frame position math too, not just the visual - no reason to
   * spend CPU animating something nobody can see.
   */
  private _animateBalls(): void {
    this._ballRaf = requestAnimationFrame(() => this._animateBalls());
    const root = this.shadowRoot;
    if (!root) return;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const balls = root.querySelectorAll<SVGGElement>(".energy-ball");
    if (!balls.length) return;
    const nowS = performance.now() / 1000;
    balls.forEach((ball) => {
      const pathId = ball.dataset.ballPath;
      const duration = parseFloat(ball.dataset.ballDuration ?? "");
      const phase = parseFloat(ball.dataset.ballPhase ?? "0");
      if (!pathId || !duration) return;
      const path = root.querySelector<SVGPathElement>(`#${CSS.escape(pathId)}`);
      if (!path) return;
      let cached = this._ballPathLengthCache.get(path);
      const d = path.getAttribute("d") ?? "";
      if (!cached || cached.d !== d) {
        cached = { d, length: path.getTotalLength() };
        this._ballPathLengthCache.set(path, cached);
      }
      if (!cached.length) return;
      const progress = ((nowS / duration + phase) % 1) * cached.length;
      const pt = path.getPointAtLength(progress);
      ball.setAttribute("transform", `translate(${pt.x.toFixed(2)},${pt.y.toFixed(2)})`);
    });
  }

  /** Converts a logical (x, y) point in the shared coordinate space into a `left/top` percentage style string. */
  private _positionStyle(node: FlowNode, width: number, height: number): string {
    const leftPct = ((node.x / width) * 100).toFixed(2);
    const topPct = ((node.y / height) * 100).toFixed(2);
    return `left:${leftPct}%; top:${topPct}%;`;
  }

  /**
   * Opens Home Assistant's standard "more info" dialog for a node's most
   * relevant configured entity (see `EntityIdMap`, built once in
   * `render()`) - `hass-more-info` is the conventional bubbling/composed
   * custom event HA's own frontend listens for, so this works without
   * importing any HA frontend helper/type. A no-op when the node has
   * nothing configured to show - such a node simply isn't clickable (see
   * the `clickable` checks at each call site).
   */
  private _moreInfo(entityId: string | undefined): void {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  private _renderNode(
    node: FlowNode,
    valueText: string,
    width: number,
    height: number,
    colour: FlowColourKind = "home",
    dense = false,
    idle = false,
    entityId?: string
  ): TemplateResult {
    const clickable = !!entityId;
    return html`
      <div class="node-html" style=${this._positionStyle(node, width, height)}>
        <div
          class="node-box colour-${colour}${dense ? " dense" : ""}${idle ? " idle" : ""}${clickable ? " clickable" : ""}"
          tabindex=${ifDefined(clickable ? 0 : undefined)}
          role=${ifDefined(clickable ? "button" : undefined)}
          @click=${() => this._moreInfo(entityId)}
          @keydown=${(e: KeyboardEvent) => {
            if (clickable && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              this._moreInfo(entityId);
            }
          }}
        >
          <ha-icon icon=${node.icon}></ha-icon>
          <div class="node-text">
            <div class="node-label">${node.label}</div>
            <div class="node-value">${valueText}</div>
          </div>
          <span class="node-port port-top" data-port=${node.id} aria-hidden="true"></span>
        </div>
      </div>
    `;
  }

  /**
   * A single solar-source hardware node - the maintainer's real installation is two
   * 11-panel strings, and this round's explicit brief puts them back as
   * two separate physical-looking boxes (an earlier round's shared 2x11
   * enclosure hid that reality behind one box). Used for EVERY solar
   * source at every source count (1, 2, 3+) - previously only the
   * fallback counts got any hardware framing while the 2-source case got
   * its own special two-row box; now every solar node shares one real
   * hardware design (chamfered frame, panel-cell strip, warm idle - never
   * grey, see .node-box.colour-solar's CSS notes) instead of the look
   * depending on how many strings happen to be configured.
   */
  private _renderSolarNode(
    node: FlowNode,
    valueText: string,
    width: number,
    height: number,
    dense = false,
    idle = false,
    entityId?: string
  ): TemplateResult {
    const clickable = !!entityId;
    const cells = Array.from({ length: dense ? 6 : 8 });
    return html`
      <div class="node-html" style=${this._positionStyle(node, width, height)}>
        <div
          class="node-box solar-node colour-solar${dense ? " dense" : ""}${idle ? " idle" : ""}${clickable ? " clickable" : ""}"
          tabindex=${ifDefined(clickable ? 0 : undefined)}
          role=${ifDefined(clickable ? "button" : undefined)}
          @click=${() => this._moreInfo(entityId)}
          @keydown=${(e: KeyboardEvent) => {
            if (clickable && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              this._moreInfo(entityId);
            }
          }}
        >
          <div class="solar-node-header">
            <span class="solar-node-title">
              <span class="solar-sun" aria-hidden="true"></span>
              <span class="node-label">${node.label}</span>
            </span>
            <span class="node-value">${valueText}</span>
          </div>
          <div class="panel-grid" aria-hidden="true">${cells.map(() => html`<span class="panel-cell"></span>`)}</div>
          <span class="node-port port-bottom" data-port=${node.id} aria-hidden="true"></span>
        </div>
      </div>
    `;
  }

  /**
   * The Solar Total / PV combiner node - only rendered when `layout.solarTotal`
   * exists (2+ solar sources, see `_layout()`). Deliberately reuses the
   * plain `node-box` shell (so it visually belongs to the same "solar"
   * family as the array nodes above it) but with the `combiner` size
   * modifier, which is smaller/subtler than both the regular node cards and
   * the inverter - the inverter must stay the visually dominant node. Gets
   * the same `idle` "sleeping" treatment as the array nodes (near-zero
   * total solar dims it back to neutral, including pausing its glow pulse)
   * and, when `nodes.solar_total` names a real entity, opens that entity's
   * more-info on tap.
   */
  private _renderSolarTotalNode(
    node: FlowNode,
    valueText: string,
    width: number,
    height: number,
    idle = false,
    entityId?: string
  ): TemplateResult {
    const clickable = !!entityId;
    return html`
      <div class="node-html" style=${this._positionStyle(node, width, height)}>
        <div
          class="node-box combiner colour-solar${idle ? " idle" : ""}${clickable ? " clickable" : ""}"
          tabindex=${ifDefined(clickable ? 0 : undefined)}
          role=${ifDefined(clickable ? "button" : undefined)}
          @click=${() => this._moreInfo(entityId)}
          @keydown=${(e: KeyboardEvent) => {
            if (clickable && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              this._moreInfo(entityId);
            }
          }}
        >
          <ha-icon icon=${node.icon}></ha-icon>
          <div class="node-text">
            <div class="node-label">${node.label}</div>
            <div class="node-value">${valueText}</div>
          </div>
          <span class="node-port port-bottom" data-port="solar-total" aria-hidden="true"></span>
        </div>
      </div>
    `;
  }

  /**
   * `pvInW` is the same combined-solar-total figure the now-removed Solar
   * Total node used to show (authoritative `solar_total` entity, falling
   * back to the summed array readings - see the `combinerW` computation in
   * `render()`) - `null` whenever that figure doesn't apply (0/1/3+ solar
   * sources, where the combiner, if any, still renders as its own node -
   * see `_layout()`), in which case this falls back to the original
   * single AC-output display so those configs look exactly as before.
   */
  private _renderInverterNode(
    node: FlowNode,
    powerW: number | null,
    pvInW: number | null,
    stateText: string | undefined,
    severity: "ok" | "warning" | "fault" | "neutral",
    width: number,
    height: number,
    entityId?: string
  ): TemplateResult {
    const cfg = this._config!;
    const clickable = !!entityId;
    return html`
      <div class="node-html inverter-node" style=${this._positionStyle(node, width, height)}>
        <div
          class="inverter-box severity-${severity}${clickable ? " clickable" : ""}"
          tabindex=${ifDefined(clickable ? 0 : undefined)}
          role=${ifDefined(clickable ? "button" : undefined)}
          @click=${() => this._moreInfo(entityId)}
          @keydown=${(e: KeyboardEvent) => {
            if (clickable && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              this._moreInfo(entityId);
            }
          }}
        >
          <span class="inverter-port port-pv" data-port="inverter-pv" aria-hidden="true"></span>
          <span class="inverter-port port-battery" data-port="inverter-battery" aria-hidden="true"></span>
          <span class="inverter-port port-grid" data-port="inverter-grid" aria-hidden="true"></span>
          <span class="inverter-port port-home" data-port="inverter-home" aria-hidden="true"></span>
          <ha-icon icon=${DEFAULT_ICONS.inverter}></ha-icon>
          <div class="node-label">${DEFAULT_LABELS.inverter}</div>
          ${pvInW !== null
            ? html`
                <div class="inverter-metrics">
                  <div class="inverter-metric-row">
                    <span class="inverter-metric-label">PV IN</span>
                    <span class="inverter-metric-value">${formatPower(pvInW ?? undefined, cfg.format)}</span>
                  </div>
                  <div class="inverter-metric-row">
                    <span class="inverter-metric-label">AC OUT</span>
                    <span class="inverter-metric-value">${formatPower(powerW ?? undefined, cfg.format)}</span>
                  </div>
                </div>
              `
            : html`
                <div class="node-value inverter-value">${formatPower(powerW ?? undefined, cfg.format)}</div>
                <div class="inverter-caption">AC Output</div>
              `}
          ${stateText ? html`<div class="state-pill severity-${severity}">${stateText}</div>` : nothing}
        </div>
      </div>
    `;
  }

  private _renderBottomNode(
    node: FlowNode,
    powers: {
      homeW: number | null;
      batteryW: number | null;
      batterySoc: number | null;
      batterySocConfigured: boolean;
      reserveRuntime: ReserveRuntime | undefined;
      gridW: number | null;
      gridState: { kind: "importing" | "exporting" | "connected-idle" | "disconnected" | "unavailable"; colour: FlowColourKind; statusLabel: string };
      generatorW: number | null;
    },
    width: number,
    height: number,
    entityIds: EntityIdMap
  ): TemplateResult {
    const cfg = this._config!;
    const posStyle = this._positionStyle(node, width, height);
    const dense = false; // home/battery/grid/generator each have their own dedicated cross-shape position now - never narrowed for crowding

    if (node.kind === "home") {
      return this._renderNode(node, formatPower(powers.homeW ?? undefined, cfg.format), width, height, "home", dense, false, entityIds.home);
    }
    if (node.kind === "battery") {
      // Unknown SOC has no fill at all (see socDisplay()) - never drawn as a
      // genuine empty battery.
      const { text: socText, fillPct: socPct } = socDisplay(powers.batterySoc, powers.batterySocConfigured);
      // Display-only: the Charging/Discharging/Idle status word already
      // conveys direction, so the number itself always reads as a plain
      // magnitude (never a signed "-197 W" for charging) - Math.abs() is
      // applied ONLY here, at formatting. `powers.batteryW` itself stays
      // the real signed value everywhere else (status/colour/line
      // direction/animation all still key off its sign, unchanged).
      const flowText = formatPower(powers.batteryW !== null ? Math.abs(powers.batteryW) : undefined, cfg.format);
      // Same "value >= 0 = discharging" convention as _buildLines() - one
      // source of truth for the battery's current state, never a second
      // independent guess. Idle gets its own subdued colour (see
      // .colour-battery-idle in static styles), not just a fallback bucket;
      // an unknown reading is "--", never "Idle" (see batteryStatus()).
      const { label: status, colour } = batteryStatus(powers.batteryW, IDLE_THRESHOLD_W);
      const entityId = entityIds.battery;
      const clickable = !!entityId;
      // `--ecco-soc` drives the card's own very subtle SOC-proportional
      // background fill (see `.battery-box::after`) - an ambient, low-
      // opacity second representation of charge level alongside (not a
      // replacement for) the precise `.soc-track`/`.soc-fill` bar below.
      const boxStyle = socPct !== null ? `--ecco-soc:${socPct}%` : "";
      // Optional time-to-reserve hook (FE-0 tooltip, FE-1 visible line): the
      // configured entity's own value, status and range, shown as given. The
      // card estimates nothing. Absent entity -> no tooltip and no line at all.
      const runtime = powers.reserveRuntime;
      const reserveTitle = runtime !== undefined ? reserveRuntimeTooltip(runtime) : undefined;
      return html`
        <div class="node-html" style=${posStyle}>
          <div class="battery-shell">
            <span class="battery-terminal colour-${colour}" aria-hidden="true"></span>
            <div
              class="node-box battery-box colour-${colour}${clickable ? " clickable" : ""}${socPct === null ? " soc-unknown" : ""}"
              style=${boxStyle}
              title=${ifDefined(reserveTitle)}
              tabindex=${ifDefined(clickable ? 0 : undefined)}
              role=${ifDefined(clickable ? "button" : undefined)}
              @click=${() => this._moreInfo(entityId)}
              @keydown=${(e: KeyboardEvent) => {
                if (clickable && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  this._moreInfo(entityId);
                }
              }}
            >
              <div class="node-text">
                <div class="node-label">${DEFAULT_LABELS.battery} ${socText}</div>
                <div class="node-value">${flowText}</div>
                <div class="node-sub">${status}</div>
                ${runtime !== undefined ? html`<div class="node-runtime runtime-${runtime.status}">${reserveRuntimeLine(runtime)}</div>` : nothing}
              </div>
              ${socPct !== null ? html`<div class="soc-track"><div class="soc-fill" style="width:${socPct}%"></div></div>` : nothing}
              <span class="node-port port-right" data-port="battery" aria-hidden="true"></span>
            </div>
          </div>
        </div>
      `;
    }
    if (node.kind === "grid") {
      const gw = powers.gridW;
      // Shared source of truth (see _gridState()'s own doc comment) - this
      // is the SAME result _buildLines() already used for the route, so the
      // pylon/box and the line it's attached to can never show conflicting
      // states.
      const { kind, colour, statusLabel } = powers.gridState;
      const entityId = entityIds.grid;
      const clickable = !!entityId;
      // No pulse at all for "unavailable" (nothing to breathe to - see
      // pylonPulseDurationS()'s own doc comment); every other state gets a
      // duration, magnitude-scaled for importing/exporting, fixed for the
      // two ~0W-ish states.
      const pulsing = kind !== "unavailable";
      const pulseStyle = pulsing ? `--ecco-pylon-pulse-duration:${pylonPulseDurationS(kind, gw ?? 0).toFixed(2)}s` : "";
      return html`
        <div class="node-html" style=${posStyle}>
          <div
            class="node-box grid-box colour-${colour}${clickable ? " clickable" : ""}"
            tabindex=${ifDefined(clickable ? 0 : undefined)}
            role=${ifDefined(clickable ? "button" : undefined)}
            @click=${() => this._moreInfo(entityId)}
            @keydown=${(e: KeyboardEvent) => {
              if (clickable && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                this._moreInfo(entityId);
              }
            }}
          >
            <div class="node-text grid-text">
              <div class="node-label">${DEFAULT_LABELS.grid}</div>
              <div class="node-value">${formatPower(gw ?? undefined, cfg.format)}</div>
              <div class="node-sub">${statusLabel}</div>
            </div>
            <div class="grid-graphic${pulsing ? " pylon-pulse" : ""}" style=${pulseStyle} aria-hidden="true">
              <span class="pylon-leg leg-left"></span>
              <span class="pylon-leg leg-right"></span>
              <span class="pylon-arm arm-top"></span>
              <span class="pylon-arm arm-mid"></span>
              <span class="pylon-arm arm-base"></span>
            </div>
            <span class="node-port port-left" data-port="grid" aria-hidden="true"></span>
          </div>
        </div>
      `;
    }
    // generator
    return this._renderNode(
      node,
      formatPower(powers.generatorW ?? undefined, cfg.format),
      width,
      height,
      "generator",
      dense,
      false,
      entityIds.generator
    );
  }

  /**
   * A compact, always-visible strip of up to three quick-glance live
   * readings - grid voltage, AC temperature, DC temperature - sitting
   * between the flow diagram and the "Today" totals. Distinct from (and in
   * addition to) the collapsible "Inverter details" panel below, which
   * shows the full `inverter_details` set including these same fields on
   * demand; this strip is just the three most commonly wanted numbers
   * surfaced without an extra click. Each tile is independently optional -
   * only entities actually configured (and currently available) render.
   */
  /**
   * Up to FIVE quick-glance tiles - the three original readings (Grid
   * Voltage/AC Temp/DC Temp) plus Grid Connected and Frequency, which
   * previously only appeared inside the collapsible "Inverter details"
   * panel below (see `_renderDetailsToggle()`) even though every other
   * field on `InverterDetailsConfig` this card can usefully show at a
   * glance already lived here - a genuine redundancy once both were
   * configured (the panel just repeated these three and added two more).
   * Portable and independently optional like every other field here;
   * whether the collapsible panel BELOW this strip still also renders is
   * a separate, explicit choice (`features.show_details_panel`) - this
   * strip's own five-field set is unconditional for anyone who configures
   * all five, not gated behind that flag.
   */
  private _renderQuickMetrics(): TemplateResult | typeof nothing {
    const d = this._config!.inverter_details;
    if (!d) return nothing;

    const items: { icon: string; label: string; value: string; variant?: "ok" | "fault" }[] = [];
    const gridVoltage = this._numeric(d.grid_voltage);
    if (gridVoltage !== null) {
      items.push({ icon: "mdi:sine-wave", label: "Grid Voltage", value: `${gridVoltage.toFixed(0)} V` });
    }
    const acTemp = this._numeric(d.ac_temperature);
    if (acTemp !== null) {
      items.push({ icon: "mdi:thermometer", label: "AC Temp", value: `${acTemp.toFixed(1)}°C` });
    }
    const dcTemp = this._numeric(d.dc_temperature);
    if (dcTemp !== null) {
      items.push({ icon: "mdi:thermometer-lines", label: "DC Temp", value: `${dcTemp.toFixed(1)}°C` });
    }
    // Reads the SAME configured binary_sensor `_renderDetails()` already
    // did - never invents state, just presents this one more prominently
    // (connected = quiet/healthy, disconnected = the card's existing
    // fault colour, matching every other state-aware surface here). Only an
    // explicit off/false is a disconnection; unavailable/unknown is shown as
    // "Unknown" with no fault styling (see classifyGridConnected()).
    if (d.grid_connected) {
      const s = this._state(d.grid_connected)?.state;
      if (s !== undefined) {
        const { value, icon, variant } = gridConnectedDisplay(classifyGridConnected(s));
        items.push({ icon, label: "Grid Connected", value, variant });
      }
    }
    const freq = this._numeric(d.frequency);
    if (freq !== null) {
      items.push({ icon: "mdi:waveform", label: "Frequency", value: `${freq.toFixed(2)} Hz` });
    }
    if (items.length === 0) return nothing;

    return html`
      <div class="quick-metrics">
        ${items.map(
          (item) => html`
            <div class="quick-metric${item.variant ? ` variant-${item.variant}` : ""}">
              <ha-icon icon=${item.icon}></ha-icon>
              <div class="quick-metric-text">
                <span class="quick-metric-label">${item.label}</span>
                <span class="quick-metric-value">${item.value}</span>
              </div>
            </div>
          `
        )}
      </div>
    `;
  }

  private _renderToday(): TemplateResult | typeof nothing {
    const cfg = this._config!;
    const today = cfg.today;
    if (!today) return nothing;

    // Category colour per tile (see .today-item.colour-* below) - these
    // are IDENTITY colours (which source/sink this total belongs to),
    // reusing the exact same --ecco-line-* family every other state-aware
    // surface in this card already keys off, never a good/bad judgement -
    // The maintainer's explicit "Today's values are subjective totals, NOT health
    // states... give each tile a consistent category colour" brief.
    const items: { label: string; value: string; colour: FlowColourKind }[] = [];
    const push = (label: string, entityId: string | undefined, colour: FlowColourKind) => {
      if (!entityId) return;
      const v = this._numeric(entityId);
      items.push({ label, value: formatEnergy(v, cfg.format), colour });
    };
    push("Solar", today.solar, "solar");
    push("Load", today.load, "home");
    push("Imported", today.import, "grid-import");
    push("Exported", today.export, "grid-export");
    push("Charged", today.battery_charge, "battery-charge");
    push("Discharged", today.battery_discharge, "battery-discharge");

    if (items.length === 0) return nothing;

    const compact = cfg.features?.compact_today ?? false;
    // Solar Share rides on the "Today" heading row itself (right-aligned)
    // rather than as its own badge row underneath - a standalone row with
    // only that one pill in it (self_sufficiency off, as in the ECCO
    // example) read as wasted space. Self-sufficiency, where still enabled,
    // remains its own badge row via `_renderBadges()` - it's a distinct
    // metric, not part of this fold-in.
    const solarShareText = this._solarShareText();
    return html`
      <div class="today ${compact ? "compact" : ""}">
        <div class="today-heading-row">
          <span class="today-heading">Today</span>
          ${solarShareText
            ? html`<span class="today-solar-share">Solar Share <strong>${solarShareText}</strong></span>`
            : nothing}
        </div>
        <div class="today-grid">
          ${items.map(
            (item) => html`
              <div class="today-item colour-${item.colour}">
                <span class="today-label">${item.label}</span>
                <span class="today-value">${item.value}</span>
              </div>
            `
          )}
        </div>
      </div>
    `;
  }

  private _solarShareText(): string | null {
    const cfg = this._config!;
    const today = cfg.today;
    const features = cfg.features;
    if (!today || !features?.solar_contribution) return null;
    const load = this._numeric(today.load);
    if (!load || load <= 0) return null;
    const solar = this._numeric(today.solar) ?? 0;
    return formatPercent(solar / load);
  }

  private _renderBadges(): TemplateResult | typeof nothing {
    const cfg = this._config!;
    const today = cfg.today;
    const features = cfg.features;
    if (!today || !features?.self_sufficiency) return nothing;

    const load = this._numeric(today.load);
    if (!load || load <= 0) return nothing;
    const imported = this._numeric(today.import) ?? 0;
    const selfSufficiency = 1 - imported / load;
    return html`<div class="badges"><div class="badge">Self-sufficiency <strong>${formatPercent(selfSufficiency)}</strong></div></div>`;
  }

  private _renderDetailsToggle(): TemplateResult | typeof nothing {
    const cfg = this._config!;
    // Portable opt-out (default true - existing installs keep today's
    // collapsible panel unchanged): once every field this panel can show
    // already has its own always-visible presentation (the five-tile
    // quick-metrics strip above), the panel is pure repetition for that
    // installation - see FeaturesConfig.show_details_panel.
    if (cfg.features?.show_details_panel === false) return nothing;
    const d = cfg.inverter_details;
    const inverterNode = cfg.nodes?.inverter;
    const hasAny =
      d &&
      (d.temperature || d.ac_temperature || d.dc_temperature || d.grid_voltage || d.grid_connected || d.frequency || d.mode);
    const hasStatus = inverterNode?.status;
    if (!hasAny && !hasStatus) return nothing;

    return html`
      <button
        class="details-toggle"
        @click=${() => (this._detailsOpen = !this._detailsOpen)}
        aria-expanded=${this._detailsOpen}
      >
        <span>Inverter details</span>
        <ha-icon icon=${this._detailsOpen ? "mdi:chevron-up" : "mdi:chevron-down"}></ha-icon>
      </button>
      ${this._detailsOpen ? this._renderDetails() : nothing}
    `;
  }

  private _renderDetails(): TemplateResult {
    const cfg = this._config!;
    const d = cfg.inverter_details ?? {};
    const inverterNode = cfg.nodes?.inverter;
    const rows: { label: string; value: string }[] = [];

    if (inverterNode?.status) {
      const v = this._state(inverterNode.status)?.state;
      if (v) rows.push({ label: "Status", value: v });
    }
    const temp = this._numeric(d.temperature);
    if (temp !== null) rows.push({ label: "Temperature", value: `${temp.toFixed(1)} °C` });
    const acTemp = this._numeric(d.ac_temperature);
    if (acTemp !== null) rows.push({ label: "AC Temperature", value: `${acTemp.toFixed(1)} °C` });
    const dcTemp = this._numeric(d.dc_temperature);
    if (dcTemp !== null) rows.push({ label: "DC Temperature", value: `${dcTemp.toFixed(1)} °C` });
    const gridVoltage = this._numeric(d.grid_voltage);
    if (gridVoltage !== null) rows.push({ label: "Grid Voltage", value: `${gridVoltage.toFixed(0)} V` });
    if (d.grid_connected) {
      const s = this._state(d.grid_connected)?.state;
      if (s !== undefined) rows.push({ label: "Grid Connected", value: gridConnectedDisplay(classifyGridConnected(s)).detailValue });
    }
    const freq = this._numeric(d.frequency);
    if (freq !== null) rows.push({ label: "Frequency", value: `${freq.toFixed(2)} Hz` });
    if (d.mode) {
      const s = this._state(d.mode)?.state;
      if (s) rows.push({ label: "Mode", value: s });
    }

    if (rows.length === 0) {
      return html`<div class="details"><div class="details-empty">No inverter detail entities configured.</div></div>`;
    }

    return html`
      <div class="details">
        ${rows.map(
          (row) => html`
            <div class="details-row">
              <span class="details-label">${row.label}</span>
              <span class="details-value">${row.value}</span>
            </div>
          `
        )}
      </div>
    `;
  }

  private _severityFor(text: string | undefined): "ok" | "warning" | "fault" | "neutral" {
    if (!text) return "neutral";
    const lower = text.toLowerCase();
    if (FAULT_KEYWORDS.some((k) => lower.includes(k))) return "fault";
    if (WARNING_KEYWORDS.some((k) => lower.includes(k))) return "warning";
    if (lower.includes("normal") || lower.includes("ok")) return "ok";
    return "neutral";
  }

  static styles = css`
    :host {
      /* Deliberately its own dedicated variable, --ecco-card-background,
         rather than reading the generic HA --card-background-color: a
         host theme frequently already claims that variable for its own
         purposes (e.g. a neutral charcoal/grey used across all cards
         uniformly), which silently overrides this card's own intended
         navy default with no way to opt back out short of fighting the
         theme with !important card_mod overrides from outside the
         card's shadow DOM - which do not reliably reach an internal
         custom property consumed this early in the cascade. A card-
         specific variable name means this card's own default (a real,
         complete navy look out of the box) is never accidentally
         inherited away, while remaining just as overridable as before
         for anyone who genuinely wants to re-theme it - set
         --ecco-card-background from outside instead. */
      --ecco-bg: var(--ecco-card-background, #141c2d);
      --ecco-surface: color-mix(in srgb, var(--ecco-bg) 82%, white 6%);
      --ecco-border: color-mix(in srgb, var(--ecco-bg) 70%, white 12%);
      --ecco-accent: var(--primary-color, #4fd1ff);
      --ecco-text: var(--primary-text-color, #eef2f7);
      --ecco-text-muted: var(--secondary-text-color, #9aa7b8);
      --ecco-ok: #38d996;
      --ecco-warning: #f4b942;
      --ecco-fault: #ff5c6c;
      --ecco-glow: color-mix(in srgb, var(--ecco-accent) 45%, transparent);

      /* Per-source/per-state flow line/icon/border colours. Plain literal
         fallbacks - no color-mix() or any other function in this specific
         chain - so the flow lines' critical paint path never depends on a
         CSS feature a given rendering context might not support. Override
         any of these from outside (a theme, or card-mod on this card) to
         match your own palette; nothing here is a colour baked directly
         into a selector without this variable indirection, and nothing
         here assumes an ECCO/Deye installation specifically.

         Battery and grid each have three STATE variants rather than one
         static colour (charge/discharge/idle, import/export/idle) - the
         line, the node's border, its subtle background tint, and its soft
         glow are all derived from whichever of these is currently active
         (see FlowColourKind/_buildLines()/_renderBottomNode()). Battery
         charge=green/discharge=orange matches the live "energy in vs
         energy out" convention the maintainer asked for; grid import=cyan/
         export=green-teal mirrors it without reusing the exact same hues. */
      --ecco-line-solar: #ffb454;
      --ecco-line-home: #7fb8ff;
      --ecco-line-grid-import: #45d9ff;
      --ecco-line-grid-export: #2dd4bf;
      /* Grid's 5-state model (this round): "idle" now specifically means
         connected + confirmed ~0W - genuinely alive, just quiet right now -
         so it moves to a muted steel-blue instead of the old flat grey.
         Grey is reserved for "unavailable" (no reliable signal either way).
         "disconnected" is a real fault signal only, never inferred from 0W
         power alone (see _gridState()'s own doc comment). */
      --ecco-line-grid-idle: #5b7a9e;
      --ecco-line-grid-disconnected: #e5484d;
      --ecco-line-grid-unavailable: #7c8a9e;
      --ecco-line-battery-charge: #43d17a;
      --ecco-line-battery-discharge: #ff8a3d;
      --ecco-line-battery-idle: #7c8a9e;
      --ecco-line-generator: #ffcf6b;
      display: block;
      /* Lets the narrow-card fix below (see .battery-box/.inverter-box/
         .grid-box's @container rule) query THIS element's own rendered
         width - the card's real width in whatever dashboard column it's
         placed in - rather than the browser viewport's width. A plain
         @media query would almost never fire correctly here: a narrow
         card commonly sits in a masonry/sidebar column on an otherwise
         wide desktop viewport, which is exactly the case that needs
         fixing. */
      container-type: inline-size;
    }

    ha-card {
      background: linear-gradient(160deg, var(--ecco-bg), color-mix(in srgb, var(--ecco-bg) 88%, black 8%));
      color: var(--ecco-text);
      border-radius: 20px;
      padding: 16px 16px 14px;
      overflow: hidden;
    }

    .card-title {
      font-size: 1.05rem;
      font-weight: 600;
      letter-spacing: 0.01em;
      margin: 2px 4px 10px;
      color: var(--ecco-text);
    }

    .content {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .flow {
      position: relative;
      /* Capped and centred rather than a plain 100% - on a normal-width
         card this is identical to before (min() just resolves to 100%),
         but on a much wider host (e.g. a full-width Home Assistant
         Sections column) it stops the diagram growing indefinitely. Since
         height is locked to width via aspect-ratio below, an uncapped
         100%-wide flow on a wide card grew tall enough to visually
         overlap the dashboard content beneath it - this is the actual fix
         for that, not a rows/grid_options change (which only affects how
         much space Home Assistant reserves, not how tall this SVG/HTML
         diagram wants to render). Raised 640 -> 840px (roughly +31%) per
         live-review feedback that the whole diagram still rendered too
         small, with too much unused space around it, on a normal-width
         card - node-box size/spacing (all still literal CSS px, untouched
         here) now render proportionally larger against the bigger canvas
         without needing every individual box resized to compensate.
         Quick Metrics/Today/badges/Details are siblings of .flow inside
         .content, not children of it, so this cap does not affect them -
         they still use the card's full available width. */
      width: min(100%, 840px);
      margin-inline: auto;
      /* aspect-ratio is also set inline per-render (it depends on whether
         solar/generator are configured) - this is just a safe fallback,
         matching the common case (solar configured, no generator). */
      aspect-ratio: 360 / 259;
      overflow: visible;
    }

    .flow-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      overflow: visible;
      /* Lines never need to receive pointer events; letting clicks pass
         through means a future tap-action on a node card is never blocked
         by the line layer sitting behind it. */
      pointer-events: none;
    }

    /* Every line is drawn as TWO stacked <path> elements sharing the same
       "d" plus one arrowhead <polygon> - see _renderLine()'s own comment
       for why (guaranteed base visibility + no <marker>/url(#id) reference). */
    .flow-line-base {
      fill: none;
      /* Power-scaled per line (see _renderLine()'s inline style) - these
         numbers are just the fallback for a line with no magnitude yet. */
      stroke-width: var(--ecco-line-w, 3);
      stroke-linecap: round;
      /* Deliberately dim - this is the passive "bus/wire", not the
         indicator - but nudged 0.22 -> 0.29 (plus MIN/MAX_LINE_WIDTH_PX
         both up slightly) this round so the topology still reads clearly
         even when the packet overlay's own motion is subtle at low power;
         still comfortably under the 0.62-0.98 range that layer runs at,
         per the UniFi-topology "dim wire + bright travelling packets"
         brief. */
      opacity: 0.29;
      /* Battery/grid swap colour class (e.g. import -> export) on the same
         persisted <path> element, so this fades rather than snaps too -
         "where practical" per the maintainer's smooth-transitions request. */
      transition: stroke 0.28s ease;
    }
    /* The packet stream - see _renderLine()'s own doc comment for the
       full "why" (this replaced a round of animateMotion circle particles
       that didn't read as visible in live use). stroke-dasharray/opacity/
       --ecco-glow-px are all set inline per render, magnitude-scaled -
       the values here are just pre-JS-render fallbacks. */
    .flow-line-anim {
      fill: none;
      stroke-width: var(--ecco-line-w, 2.8);
      stroke-linecap: round;
      stroke-dasharray: 4 11;
      animation-name: ecco-dash;
      animation-timing-function: linear;
      animation-iteration-count: infinite;
      opacity: 0.8;
      filter: drop-shadow(0 0 var(--ecco-glow-px, 2px) currentColor);
      transition: stroke 0.28s ease;
    }
    .flow-line-base.idle,
    .flow-line-anim.idle,
    .flow-arrow.idle {
      opacity: 0.12;
    }
    .flow-line-anim.idle {
      animation-play-state: paused;
      filter: none;
    }
    @keyframes ecco-dash {
      to {
        stroke-dashoffset: -30;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      /* The always-solid base layer is untouched - a static, correctly
         coloured/oriented line remains visible; only the moving-dash
         packet stream is turned off - and the static arrowhead (normally
         hidden once a line's own dash pattern carries direction instead -
         see .flow-arrow below) reappears so direction is never lost, only
         the motion conveying it. */
      .flow-line-anim {
        animation: none;
        stroke-dasharray: none;
        filter: none;
      }
      .flow-arrow {
        opacity: 0.95;
      }
      .flow-arrow.idle {
        opacity: 0.12;
      }
      /* The energy-ball layer is pure motion with no static equivalent
         (unlike the dash stream, which still has a meaningful "off"
         state via stroke-dasharray:none) - so it's hidden outright here
         rather than frozen in place, where a stationary glowing dot
         sitting mid-route would just read as a rendering glitch. The
         base line + reappeared arrowhead above already carry direction
         without it. */
      .energy-ball {
        display: none;
      }
      /* Every other animation added for state-aware polish (Solar Total's
         glow pulse, the battery card's glow pulse/shimmer, the SOC bar's
         sheen) is motion-only decoration layered on top of state that is
         otherwise conveyed purely by colour - border/background/box-shadow
         are all set unconditionally in the rules above and untouched here,
         so turning the animation off never removes any actual information,
         only the movement itself. The shimmer/sheen pseudo-elements are
         also hidden outright rather than left as a static diagonal streak,
         which would just look like a rendering glitch once motionless. */
      .node-box.combiner,
      .battery-box {
        animation: none;
      }
      .battery-box::before,
      .soc-fill::after {
        animation: none;
        opacity: 0;
      }
      /* Pylon pulse (this round): colour alone still carries every Grid
         state unambiguously (see the colour-grid-* rules above) - the
         breathing glow is motion-only reinforcement on top of that, so it
         is simply turned off here, same treatment as every other purely
         decorative animation in this block. */
      .grid-graphic.pylon-pulse {
        animation: none;
        filter: none;
      }
    }

    /* Hidden by default now - the packet stream (.flow-line-anim's own
       magnitude-scaled dash pattern - see _renderLine()) is the primary
       direction indicator for an active line, and showing both would just
       duplicate the same information. Reappears (see the reduced-motion
       block above) for an idle line (nothing moving to show direction
       with) or when the OS/browser requests reduced motion (no travel
       animation to rely on there either). */
    .flow-arrow {
      opacity: 0;
      transition: fill 0.28s ease;
    }

    /* Energy-ball layer (this round's addition - see _renderEnergyBalls()'s
       own doc comment for why it's built as a bright core + coloured glow
       rather than a flat dot). pointer-events:none throughout - purely
       decorative, riding on top of everything else in the SVG. */
    .energy-ball {
      pointer-events: none;
    }
    .ball-glow {
      fill: currentColor;
      filter: drop-shadow(0 0 var(--ecco-ball-glow, 3px) currentColor);
    }
    .ball-core {
      fill: #fff9ec;
    }

    .colour-solar.flow-line-base,
    .colour-solar.flow-line-anim {
      stroke: var(--ecco-line-solar);
    }
    .colour-solar.flow-line-anim {
      color: var(--ecco-line-solar);
    }
    .colour-solar.flow-arrow {
      fill: var(--ecco-line-solar);
    }
    .colour-solar.energy-ball {
      color: var(--ecco-line-solar);
    }
    /* The PV bus junction dot (see _renderJunction()) - a real wiring-
       diagram "conductors joined here" marker, solid and static (no
       dash/animation of its own - the legs/trunk either side of it
       already carry the moving packets). Idle dims it in step with the
       rest of the solar family instead of leaving a bright dot sitting
       over a dark, sleeping bus. */
    .flow-junction {
      fill: var(--ecco-line-solar);
      opacity: 0.85;
      transition: opacity 0.28s ease;
    }
    .flow-junction.idle {
      opacity: 0.18;
    }
    .colour-home.flow-line-base,
    .colour-home.flow-line-anim {
      stroke: var(--ecco-line-home);
    }
    .colour-home.flow-line-anim {
      color: var(--ecco-line-home);
    }
    .colour-home.flow-arrow {
      fill: var(--ecco-line-home);
    }
    .colour-home.energy-ball {
      color: var(--ecco-line-home);
    }
    .colour-grid-import.flow-line-base,
    .colour-grid-import.flow-line-anim {
      stroke: var(--ecco-line-grid-import);
    }
    .colour-grid-import.flow-line-anim {
      color: var(--ecco-line-grid-import);
    }
    .colour-grid-import.flow-arrow {
      fill: var(--ecco-line-grid-import);
    }
    .colour-grid-import.energy-ball {
      color: var(--ecco-line-grid-import);
    }
    .colour-grid-export.flow-line-base,
    .colour-grid-export.flow-line-anim {
      stroke: var(--ecco-line-grid-export);
    }
    .colour-grid-export.flow-line-anim {
      color: var(--ecco-line-grid-export);
    }
    .colour-grid-export.flow-arrow {
      fill: var(--ecco-line-grid-export);
    }
    .colour-grid-export.energy-ball {
      color: var(--ecco-line-grid-export);
    }
    .colour-grid-idle.flow-line-base,
    .colour-grid-idle.flow-line-anim {
      stroke: var(--ecco-line-grid-idle);
    }
    .colour-grid-idle.flow-line-anim {
      color: var(--ecco-line-grid-idle);
    }
    .colour-grid-idle.flow-arrow {
      fill: var(--ecco-line-grid-idle);
    }
    .colour-grid-idle.energy-ball {
      color: var(--ecco-line-grid-idle);
    }
    .colour-grid-disconnected.flow-line-base,
    .colour-grid-disconnected.flow-line-anim {
      stroke: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-disconnected.flow-line-anim {
      color: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-disconnected.flow-arrow {
      fill: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-disconnected.energy-ball {
      color: var(--ecco-line-grid-disconnected);
    }
    .colour-grid-unavailable.flow-line-base,
    .colour-grid-unavailable.flow-line-anim {
      stroke: var(--ecco-line-grid-unavailable);
    }
    .colour-grid-unavailable.flow-line-anim {
      color: var(--ecco-line-grid-unavailable);
    }
    .colour-grid-unavailable.flow-arrow {
      fill: var(--ecco-line-grid-unavailable);
    }
    .colour-grid-unavailable.energy-ball {
      color: var(--ecco-line-grid-unavailable);
    }
    .colour-battery-charge.flow-line-base,
    .colour-battery-charge.flow-line-anim {
      stroke: var(--ecco-line-battery-charge);
    }
    .colour-battery-charge.flow-line-anim {
      color: var(--ecco-line-battery-charge);
    }
    .colour-battery-charge.flow-arrow {
      fill: var(--ecco-line-battery-charge);
    }
    .colour-battery-charge.energy-ball {
      color: var(--ecco-line-battery-charge);
    }
    .colour-battery-discharge.flow-line-base,
    .colour-battery-discharge.flow-line-anim {
      stroke: var(--ecco-line-battery-discharge);
    }
    .colour-battery-discharge.flow-line-anim {
      color: var(--ecco-line-battery-discharge);
    }
    .colour-battery-discharge.flow-arrow {
      fill: var(--ecco-line-battery-discharge);
    }
    .colour-battery-discharge.energy-ball {
      color: var(--ecco-line-battery-discharge);
    }
    .colour-battery-idle.flow-line-base,
    .colour-battery-idle.flow-line-anim {
      stroke: var(--ecco-line-battery-idle);
    }
    .colour-battery-idle.flow-line-anim {
      color: var(--ecco-line-battery-idle);
    }
    .colour-battery-idle.flow-arrow {
      fill: var(--ecco-line-battery-idle);
    }
    .colour-battery-idle.energy-ball {
      color: var(--ecco-line-battery-idle);
    }
    .colour-generator.flow-line-base,
    .colour-generator.flow-line-anim {
      stroke: var(--ecco-line-generator);
    }
    .colour-generator.flow-line-anim {
      color: var(--ecco-line-generator);
    }
    .colour-generator.flow-arrow {
      fill: var(--ecco-line-generator);
    }
    .colour-generator.energy-ball {
      color: var(--ecco-line-generator);
    }

    .node-html {
      position: absolute;
      /* left/top are set inline per-node (percentage of the shared
         coordinate space) - this centres the card exactly on its point. */
      transform: translate(-50%, -50%);
      z-index: 1;
    }

    .node-box {
      display: flex;
      align-items: center;
      gap: 6px;
      width: 96px;
      padding: 6px 8px;
      border-radius: 12px;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      box-sizing: border-box;
      /* Anchors every node-box variant's own .node-port child (see its
         own CSS note) to ITS edges - variants that already set their own
         position (battery/grid/solar) simply repeat this, harmlessly. */
      position: relative;
      /* State changes (e.g. grid idle -> importing, solar sleeping ->
         active) fade in rather than snap - restrained, ~250-300ms, and
         never touches the live-data update itself, only how its colour
         change is painted. */
      transition:
        width 0.2s ease,
        border-color 0.28s ease,
        background 0.28s ease,
        box-shadow 0.28s ease;
    }
    /* Three or more solar arrays: a narrower card keeps the row from
       crowding/overlapping at typical card widths - see _fanOut()/the
       "dense" flag threaded through from _renderFlow(). */
    .node-box.dense {
      width: 74px;
      padding: 5px 6px;
      gap: 4px;
    }
    .node-box.dense ha-icon {
      --mdc-icon-size: 17px;
    }
    .node-box.dense .node-label,
    .node-box.dense .node-value {
      font-size: 0.6rem;
    }
    /* Home - compositional pass: previously wider (172px) than the
       inverter's own OLD width, which was part of why the inverter didn't
       read as the clear hub (see .inverter-box's own note). Brought down
       to sit in the same size family as Battery/Grid (132px) instead -
       still visually distinct via its own colour/glow/radius treatment,
       just no longer competing on sheer size. Keeps the same family
       treatment as .colour-solar (background/border/glow tint, using the
       existing --ecco-line-home blue, no new colour introduced).
       Hardware-identity FINAL pass: live review liked the house concept
       but found it still too shallow to read as one at a glance - taller
       now, with a genuinely bigger roof apex (12 -> 22px) over a taller
       body, and switched from an icon-left/text-right row to a stacked
       column (icon centred above the text, like the inverter's own hero
       treatment) so the silhouette reads as roof-over-body rather than a
       roof cut sitting oddly beside a horizontal row. clip-path only
       changes what's PAINTED, not the box's layout footprint, so this
       needed no markup change beyond the flex-direction switch below, and
       still doesn't disturb the port position above it (measured live off
       the real .node-port element - see the TRUE PORT GEOMETRY note above
       buildRouteD(), so a height change here needs no recalibration
       anywhere else). Its bottom two vertices sit exactly on the box's own
       bottom corners (not inset), so the existing 16px bottom rounding
       below still shows through untouched - only the top corners' 8px
       rounding is replaced by the roof cut. */
    .node-box.colour-home {
      width: 132px;
      padding: 20px 12px 13px;
      flex-direction: column;
      align-items: center;
      gap: 5px;
      text-align: center;
      border-radius: 8px 8px 16px 16px;
      background-color: color-mix(in srgb, var(--ecco-line-home) 14%, var(--ecco-surface));
      background-image: linear-gradient(to bottom, color-mix(in srgb, var(--ecco-line-home) 30%, transparent), transparent 22px);
      border-color: color-mix(in srgb, var(--ecco-line-home) 55%, var(--ecco-border));
      box-shadow: 0 0 14px -5px color-mix(in srgb, var(--ecco-line-home) 50%, transparent);
      clip-path: polygon(0 22px, 50% 0, 100% 22px, 100% 100%, 0 100%);
    }
    .node-box.colour-home ha-icon {
      --mdc-icon-size: 27px;
    }
    .node-box.colour-home .node-label {
      font-size: 0.74rem;
    }
    .node-box.colour-home .node-value {
      font-size: 1rem;
      font-weight: 700;
    }
    /* Solar Total / PV combiner node (see _renderSolarTotalNode): smaller
       and visually quieter than a regular node card, and much smaller than
       the inverter - it is a secondary "merge point", not another
       first-class node competing with the inverter for attention. The
       background is fully opaque (unlike an earlier pass that used a
       translucent fill) so the flow line's own arrival point, which is
       geometrically inset just under this box (see the line-routing
       method), is properly masked instead of visibly showing/bleeding
       through the label - the line should read as terminating AT the
       node, not running through it. Sized up again and given real warm-
       amber colour (border/background/glow, matching the solar family
       rather than a plain neutral box) per a later live-review pass, along
       with a slightly larger combiner->inverter gap in the layout method. */
    .node-box.combiner {
      width: 100px;
      padding: 7px 9px;
      gap: 4px;
      background: color-mix(in srgb, var(--ecco-line-solar) 14%, var(--ecco-surface));
      border: 1px dashed color-mix(in srgb, var(--ecco-line-solar) 60%, var(--ecco-border));
      box-shadow: 0 0 13px -5px color-mix(in srgb, var(--ecco-line-solar) 55%, transparent);
    }
    .node-box.combiner ha-icon {
      --mdc-icon-size: 19px;
    }
    .node-box.combiner .node-label {
      font-size: 0.66rem;
    }
    .node-box.combiner .node-value {
      font-size: 0.92rem;
      font-weight: 700;
    }
    /* A slow, restrained glow pulse while there is real solar generation
       flowing through the combiner - "while solar is active" per the maintainer's
       request. The :not(.idle) selector below ties this to the exact same
       near-zero check driving the node's own sleeping treatment, one
       condition, not two independent guesses. */
    @keyframes ecco-solar-pulse {
      0%,
      100% {
        box-shadow: 0 0 10px -6px color-mix(in srgb, var(--ecco-line-solar) 42%, transparent);
      }
      50% {
        box-shadow: 0 0 17px -4px color-mix(in srgb, var(--ecco-line-solar) 68%, transparent);
      }
    }
    .node-box.combiner:not(.idle) {
      animation: ecco-solar-pulse 4.5s ease-in-out infinite;
    }
    .node-box ha-icon {
      --mdc-icon-size: 22px;
      color: var(--ecco-accent);
      flex-shrink: 0;
      transition: color 0.28s ease;
    }
    /* Solar family (arrays + the Solar Total combiner, via the shared
       .colour-solar class) - a warm amber/gold accent: a stronger border,
       a very subtle warm background tint, and a soft glow, so generation
       reads as the visually "important" flow at a glance. Kept to a
       low-opacity tint/glow rather than a solid fill - still a dark,
       premium card, not a bright dashboard tile. */
    .node-box.colour-solar {
      border-color: color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-line-solar) 11%, var(--ecco-surface));
      box-shadow: 0 0 11px -5px color-mix(in srgb, var(--ecco-line-solar) 50%, transparent);
    }
    .node-box.colour-solar .node-value {
      font-weight: 700;
    }
    /* Solar Total combiner keeps its own deliberately smaller/subtler
       sizing above (see .node-box.combiner). Every OTHER solar node - one
       per string, at every source count now (see _renderSolarNode()) -
       shares this one hardware design: a compact chamfered panel
       enclosure with its own label+value header and a panel-cell strip
       beneath, reading as a real PV module rather than a generic tile.
       Sized to sit in the same size family as Battery/Grid/Home (roughly
       120-130px) so the whole network reads as one consistent set of
       hardware nodes around the inverter, not one oversized box and four
       small ones. The 3+-array "dense" variant stays narrower on purpose
       to avoid crowding a wider fan-out. */
    .node-box.colour-solar:not(.combiner) {
      width: 142px;
      padding: 9px 10px;
      border-radius: 10px;
      flex-direction: column;
      align-items: stretch;
      gap: 6px;
      background-image: linear-gradient(155deg, color-mix(in srgb, white 7%, transparent), transparent 65%);
      /* Panel-assembly treatment (hardware-identity pass): a chamfered,
         technical outline instead of a plain rounded rect - the same
         "clip the corner, keep the rest untouched" idea as a real PV
         module's frame corner. 6px stays well inside the padding, so it
         never touches the header/panel-strip content below. */
      position: relative;
      clip-path: polygon(6px 0, calc(100% - 6px) 0, 100% 6px, 100% calc(100% - 6px), calc(100% - 6px) 100%, 6px 100%, 0 calc(100% - 6px), 0 6px);
    }
    .node-box.colour-solar.dense {
      width: 92px;
      padding: 7px 8px;
    }
    /* Top/bottom "frame rail" cues - thin bars in a cooler, metallic tone
       (deliberately NOT the warm solar accent, so they read as aluminium
       framing rather than more amber glow) sitting flush on the chamfered
       top/bottom edges, like a module's own frame extrusion. */
    .node-box.colour-solar:not(.combiner)::before,
    .node-box.colour-solar:not(.combiner)::after {
      content: "";
      position: absolute;
      left: 6px;
      right: 6px;
      height: 2px;
      background: color-mix(in srgb, var(--ecco-text-muted) 55%, transparent);
      pointer-events: none;
    }
    .node-box.colour-solar:not(.combiner)::before {
      top: 0;
    }
    .node-box.colour-solar:not(.combiner)::after {
      bottom: 0;
    }
    .solar-node-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    /* Small sun-identity cue, grouped with the label rather than floating
       separately - subtle by design (the maintainer's explicit "not dominant"),
       just enough to reinforce "this is solar" at a glance alongside the
       panel-cell strip below. flex-shrink: 0 so it's never the thing that
       gives way if the row ever gets tight - the label/value text is. */
    .solar-node-title {
      display: flex;
      align-items: baseline;
      gap: 4px;
      min-width: 0;
    }
    .solar-sun {
      flex-shrink: 0;
      align-self: center;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: radial-gradient(circle at 35% 30%, #ffe9b8, var(--ecco-line-solar) 70%);
      box-shadow: 0 0 4px 0.5px color-mix(in srgb, var(--ecco-line-solar) 70%, transparent);
      transition:
        opacity 0.4s ease,
        box-shadow 0.4s ease;
    }
    /* Idle: dims like the rest of the solar family (see .colour-solar.idle
       .panel-cell above) - never fully off, matching the maintainer's "must not
       look dead/grey" brief for the node as a whole. */
    .node-box.colour-solar.idle .solar-sun {
      opacity: 0.55;
      box-shadow: none;
    }
    .solar-node .node-label {
      font-size: 0.7rem;
    }
    .solar-node .node-value {
      font-size: 0.82rem;
    }
    .panel-grid {
      display: flex;
      gap: 2px;
    }
    .panel-cell {
      /* Stretches to fill the header's own full width evenly, however
         many cells there are (8 regular, 6 dense) - adapts automatically
         to the box's width instead of assuming one fixed reference size. */
      flex: 1 1 0;
      min-width: 0;
      height: 13px;
      /* Tighter, near-rectangular corners than the default node-box
         radius scale - reads as an individual glazed PV cell, not a
         rounded UI chip. */
      border-radius: 1px;
      background:
        linear-gradient(155deg, color-mix(in srgb, white 14%, transparent) 0%, transparent 40%),
        color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-surface) 45%);
      border: 0.5px solid color-mix(in srgb, var(--ecco-line-solar) 70%, transparent);
      transition:
        background 0.28s ease,
        border-color 0.28s ease;
    }
    /* The maintainer's explicit "inactive solar must not turn dead grey" brief -
       previously fell back to the same neutral --ecco-surface/--ecco-border
       every OTHER idle node uses (see .node-box.idle below), which read as
       "disabled control", not "sleeping panel". A dim, desaturated AMBER
       instead - still visibly part of the solar family at night/near-zero
       output, just quiet. Placed after .node-box.idle below so it wins at
       equal specificity by appearing later, the same pattern every other
       state-override in this file already uses. */
    .node-box.colour-solar.idle {
      border-color: color-mix(in srgb, var(--ecco-line-solar) 22%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-line-solar) 4%, var(--ecco-surface));
    }
    .node-box.colour-solar.idle .panel-cell {
      background: color-mix(in srgb, var(--ecco-line-solar) 16%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-solar) 26%, transparent);
    }
    .node-box.colour-solar.idle ha-icon {
      opacity: 0.7;
    }
    /* "Sleeping" treatment for a near-zero flow on an otherwise state-
       coloured node - currently the solar family only (Array 1/2 and Solar
       Total dim back to neutral at night/near-zero PV, and the combiner's
       glow pulse above stops with it). Battery/grid express their own idle
       state through a dedicated colour-battery-idle/colour-grid-idle class
       instead of this modifier, since they already have a real three-way
       state machine. Placed after the coloured rules above so it wins at
       equal selector specificity by appearing later in the stylesheet. */
    .node-box.idle {
      border-color: var(--ecco-border);
      background: var(--ecco-surface);
      box-shadow: none;
    }
    .node-box.idle ha-icon {
      opacity: 0.55;
    }
    /* Any node with a configured entity for tap-to-more-info (see
       _moreInfo()/EntityIdMap) gets this affordance; a node with nothing
       configured never receives the "clickable" class at all, so it stays
       a plain, non-interactive card. A slightly snappier transition than
       the base state-colour one above (180ms vs 280ms) so the hover/press
       feedback itself feels immediate; :active is a normal touch-
       compatible pseudo-class (momentary on tap), and no JS touch handler
       is added, so this never interferes with Home Assistant's own touch
       handling. */
    .node-box.clickable,
    .inverter-box.clickable {
      cursor: pointer;
      transition:
        transform 0.18s ease,
        border-color 0.18s ease,
        box-shadow 0.18s ease;
    }
    .node-box.clickable:hover,
    .inverter-box.clickable:hover {
      border-color: color-mix(in srgb, var(--ecco-accent) 45%, var(--ecco-border));
      transform: translateY(-1px);
    }
    .node-box.clickable:active,
    .inverter-box.clickable:active {
      transform: translateY(0) scale(0.98);
    }
    .node-box.clickable:focus-visible,
    .inverter-box.clickable:focus-visible {
      outline: 2px solid var(--ecco-accent);
      outline-offset: 2px;
    }
    @media (prefers-reduced-motion: reduce) {
      /* The hover/press LIFT is motion; the border-colour/glow feedback it
         comes with is not, and stays. */
      .node-box.clickable:hover,
      .inverter-box.clickable:hover,
      .node-box.clickable:active,
      .inverter-box.clickable:active {
        transform: none;
      }
    }
    /* Icon tint matches this node's own flow-line colour - a small,
       cohesive link between each node and the line feeding it, without
       recolouring the whole card (keeps things premium, not gaudy). */
    .node-box.colour-solar ha-icon {
      color: var(--ecco-line-solar);
    }
    .node-box.colour-home ha-icon {
      color: var(--ecco-line-home);
    }
    .node-box.colour-generator ha-icon {
      color: var(--ecco-line-generator);
    }
    .node-text {
      display: flex;
      flex-direction: column;
      line-height: 1.15;
      min-width: 0;
      /* Small, consistent breathing room between label/value/status lines -
         previously only set on .battery-box specifically, which left the
         otherwise-identical three-line .grid-box inconsistent with it. */
      gap: 1px;
    }
    .node-label {
      font-size: 0.68rem;
      color: var(--ecco-text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .node-value {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--ecco-text);
      white-space: nowrap;
      /* Tabular numerals - each digit glyph takes the same width, so a
         live value cycling through its digits (or crossing a W/kW unit
         boundary) never visibly jitters the text within its fixed-width
         node box. Applied to every live numeric display in the card. */
      font-variant-numeric: tabular-nums;
    }
    .node-sub {
      font-size: 0.62rem;
      color: var(--ecco-text-muted);
    }

    /* Hardware-identity pass: a real terminal/cap protrusion, per the maintainer's
       explicit brief ("do not reject the battery terminal idea merely
       because the existing pseudo-elements are occupied"). .battery-box
       already spends both ::before/::after on the charge shimmer and the
       SOC sheen (below) and relies on its own overflow:hidden to keep
       those clipped to its rounded corners - reusing either pseudo-element
       for a cap that must protrude ABOVE the box, past that same
       overflow:hidden, would fight that existing clipping. Cleanest fix is
       the one the maintainer asked for: a thin non-clipping .battery-shell
       wrapper (no size/shape of its own - it only exists to host the
       terminal at a position .battery-box itself can't reach) with the
       terminal as its own sibling span before the untouched
       .battery-box. Zero changes to the shimmer/SOC-fill machinery. */
    .battery-shell {
      position: relative;
    }
    .battery-terminal {
      position: absolute;
      top: -8px;
      left: 50%;
      transform: translateX(-50%);
      width: 32px;
      height: 9px;
      border-radius: 3px 3px 0 0;
      border: 1px solid var(--ecco-border);
      border-bottom: none;
      background: var(--ecco-surface);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
      transition:
        background 0.4s ease,
        border-color 0.4s ease;
      pointer-events: none;
    }
    .battery-terminal.colour-battery-charge {
      background: color-mix(in srgb, var(--ecco-line-battery-charge) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-charge) 65%, var(--ecco-border));
    }
    .battery-terminal.colour-battery-discharge {
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 65%, var(--ecco-border));
    }
    .battery-terminal.colour-battery-idle {
      background: var(--ecco-surface);
      border-color: var(--ecco-border);
    }
    /* Icon-removal pass: the maintainer felt the internal battery icon was
       redundant once the enclosure shape, terminal cap, SOC gauge and
       state colouring already say "battery" on their own - removed
       entirely (see the render method), which also removes any reason to
       keep the two-column icon+text grid this box used to need. Every
       width now uses the same single centred column the narrow
       container-query breakpoint already proved out (label+SOC/value/
       status stacked, SOC gauge spanning the full row beneath) -
       promoted here to the base rule rather than kept as a narrow-only
       override. */
    .battery-box {
      display: grid;
      grid-template-columns: 1fr;
      justify-items: center;
      text-align: center;
      row-gap: 7px;
      /* Narrowed slightly (132 -> 116px) alongside this round's routing
         pass - keeps the port comfortably clear of the inverter at every
         width (see _layout()'s battery position note), which also suits a
         taller cell's own proportions better anyway. */
      width: 116px;
      padding: 14px 12px 13px;
      /* A slightly flatter base than the default 12px - a subtle nod to a
         battery cell's own blockier silhouette; still restrained, not a
         drawn battery shape. */
      border-radius: 10px 10px 8px 8px;
      position: relative;
      z-index: 0;
      overflow: hidden;
      /* Subtle top-down sheen - part of this round's "gradients throughout
         the hardware surfaces" brief - layered above the existing per-
         state colour-mix background (background-image paints over
         background-color, both still resolve from the one shorthand-free
         declaration order already used here). */
      background-image: linear-gradient(165deg, rgba(255, 255, 255, 0.06), transparent 55%);
      transition:
        border-color 0.4s ease,
        background 0.4s ease,
        box-shadow 0.4s ease;
    }
    /* Real breathing room between label/value/status now that the box has
       the height to spend on it (was the shared 1px default) - this is
       the "spacing, not padding" half of the taller redesign. */
    .battery-box .node-text {
      gap: 4px;
      align-items: center;
    }
    /* Label+SOC on one line, live power on its own (larger) line,
       Charging/Discharging/Idle status on its own line - all centred,
       stacked in the single text row above the SOC gauge. */
    .battery-box .node-value {
      font-size: 1rem;
    }
    /* justify-items: center above sizes every grid item to its own
       content width - correct for the label/value/status text, but the
       SOC track's only child is a percentage-width fill, which can't
       establish an intrinsic size for a shrink-to-fit ancestor, so the
       track itself would collapse to 0 width without this. */
    .battery-box .soc-track {
      justify-self: stretch;
      width: 100%;
    }
    .battery-box .node-sub {
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-size: 0.68rem;
      color: var(--ecco-text);
      opacity: 0.78;
    }
    /* FE-1 runtime line: the configured time-to-reserve entity's own value or
       status, small and static (no animation, no colour of its own: the
       battery's status colour and glow are unchanged). Wraps inside the box
       at the narrow breakpoint. Missing or stale data is visibly subdued. */
    .battery-box .node-runtime {
      font-size: 0.62rem;
      font-weight: 600;
      line-height: 1.2;
      color: var(--ecco-text);
      opacity: 0.88;
      font-variant-numeric: tabular-nums;
    }
    .battery-box .node-runtime.runtime-insufficient_data,
    .battery-box .node-runtime.runtime-stale {
      opacity: 0.55;
      font-style: italic;
    }
    /* Very subtle SOC-proportional background fill (bottom-up) - an
       ambient, low-opacity second representation of charge level, always
       behind the shimmer sweep and the card's own text/icon (negative
       z-index within the local stacking context .battery-box establishes
       via position:relative + z-index:0), so it never competes with
       readability. The --ecco-soc custom property is set inline per render. */
    .battery-box::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: var(--ecco-soc, 0%);
      z-index: -2;
      transition: height 0.8s ease;
      pointer-events: none;
    }
    .battery-box.colour-battery-charge::after {
      background: color-mix(in srgb, var(--ecco-line-battery-charge) 16%, transparent);
    }
    .battery-box.colour-battery-discharge::after {
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 16%, transparent);
    }
    .battery-box.colour-battery-idle::after {
      background: color-mix(in srgb, var(--ecco-line-battery-idle) 10%, transparent);
    }
    /* Unknown SOC: no ambient fill at all, rather than a genuine-looking 0%. */
    .battery-box.soc-unknown::after {
      display: none;
    }
    /* Diagonal shimmer sweep, only while actually charging/discharging -
       visually suggests energy flowing in/out. Sits above the SOC fill but
       below the card's own text/icon (see the z-index note above). Slow
       and gentle (3.6s linear) per the maintainer's explicit "no flashing, no fast
       pulsing" instruction; disabled entirely under reduced motion below. */
    .battery-box::before {
      content: "";
      position: absolute;
      inset: -40% -60%;
      z-index: -1;
      opacity: 0;
      pointer-events: none;
    }
    .battery-box.colour-battery-charge::before {
      opacity: 1;
      background: linear-gradient(
        120deg,
        transparent 40%,
        color-mix(in srgb, var(--ecco-line-battery-charge) 20%, transparent) 50%,
        transparent 60%
      );
      animation: ecco-battery-sheen-in 3.6s linear infinite;
    }
    .battery-box.colour-battery-discharge::before {
      opacity: 1;
      background: linear-gradient(
        120deg,
        transparent 40%,
        color-mix(in srgb, var(--ecco-line-battery-discharge) 20%, transparent) 50%,
        transparent 60%
      );
      animation: ecco-battery-sheen-out 3.6s linear infinite;
    }
    @keyframes ecco-battery-sheen-in {
      0% {
        transform: translateX(-60%);
      }
      100% {
        transform: translateX(60%);
      }
    }
    @keyframes ecco-battery-sheen-out {
      0% {
        transform: translateX(60%);
      }
      100% {
        transform: translateX(-60%);
      }
    }
    /* Border/glow per state - a slow pulse while charging/discharging
       (energy actively moving), fully static (no animation property at
       all) while idle, matching the maintainer's "remove motion... no pulsing
       emphasis" instruction for that state specifically. */
    .battery-box.colour-battery-charge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-charge) 65%, var(--ecco-border));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-battery-charge) 45%, transparent);
      animation: ecco-battery-glow-charge 3.4s ease-in-out infinite;
    }
    .battery-box.colour-battery-discharge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 65%, var(--ecco-border));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-battery-discharge) 45%, transparent);
      animation: ecco-battery-glow-discharge 3.4s ease-in-out infinite;
    }
    .battery-box.colour-battery-idle {
      border-color: var(--ecco-border);
      box-shadow: none;
    }
    @keyframes ecco-battery-glow-charge {
      0%,
      100% {
        box-shadow: 0 0 9px -6px color-mix(in srgb, var(--ecco-line-battery-charge) 36%, transparent);
      }
      50% {
        /* Peak intensity deliberately kept under the inverter's own glow
           (see .inverter-box) - the battery card should feel alive, but
           never read as more visually important than the centre node. */
        box-shadow: 0 0 14px -4px color-mix(in srgb, var(--ecco-line-battery-charge) 55%, transparent);
      }
    }
    @keyframes ecco-battery-glow-discharge {
      0%,
      100% {
        box-shadow: 0 0 9px -6px color-mix(in srgb, var(--ecco-line-battery-discharge) 36%, transparent);
      }
      50% {
        box-shadow: 0 0 14px -4px color-mix(in srgb, var(--ecco-line-battery-discharge) 55%, transparent);
      }
    }
    .soc-track {
      height: 4px;
      border-radius: 2px;
      background: var(--ecco-border);
      overflow: hidden;
    }
    /* Spans both grid columns (icon + text) so the bar runs the full
       width of the now wider battery card, on its own row beneath -
       .battery-box's own row-gap provides the spacing that a margin-top
       here previously had to (removed above to avoid doubling it up).
       Taller (4 -> 8px) as part of this round's "taller enclosure" pass -
       a real gauge now, not a thin accent line - with a 5-segment
       "cell" overlay reinforcing the physical battery-gauge read, visible
       over both the filled and unfilled portion of the bar. */
    .battery-box .soc-track {
      grid-column: 1 / -1;
      height: 8px;
      border-radius: 3px;
      position: relative;
    }
    .battery-box .soc-track::after {
      content: "";
      position: absolute;
      inset: 0;
      background-image: repeating-linear-gradient(
        90deg,
        transparent 0,
        transparent calc(20% - 1.5px),
        rgba(0, 0, 0, 0.35) calc(20% - 1.5px),
        rgba(0, 0, 0, 0.35) 20%
      );
      pointer-events: none;
    }
    .soc-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--ecco-accent), var(--ecco-ok));
      border-radius: 2px;
      transition: width 0.6s ease;
      position: relative;
      overflow: hidden;
    }
    /* Same modern "moving sheen" language as the battery card's own
       shimmer, scaled down onto the thin SOC bar - only while actually
       charging/discharging, same as the card-level shimmer above. */
    .soc-fill::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.4), transparent);
      transform: translateX(-100%);
    }
    .battery-box.colour-battery-charge .soc-fill::after,
    .battery-box.colour-battery-discharge .soc-fill::after {
      animation: ecco-soc-sheen 2.6s ease-in-out infinite;
    }
    @keyframes ecco-soc-sheen {
      0% {
        transform: translateX(-100%);
      }
      100% {
        transform: translateX(100%);
      }
    }

    /* Grid - sized and weighted to match the battery card (see
       .battery-box above) per the maintainer's "should feel approximately the same
       visual weight" request, plus the same three-state (import/export/
       idle) border/background tint/glow treatment as battery. No
       animation here - unlike battery, grid state isn't asked to feel
       "alive", just clearly coloured. Was 104px against battery's 132px -
       genuinely mismatched despite this comment's own intent; matched
       properly as part of this round's "Battery and Grid should feel like
       balanced lateral branches" pass. */
    /* Hardware-identity THIRD redesign: the twin-stack silhouette from the
       previous pass improved the read but stayed too small/decorative -
       "still the weakest visual element" in live review. The maintainer's explicit
       new direction: text on the LEFT, a genuinely LARGE utility graphic
       on the RIGHT, integrated into the node's own bounds (no more
       overflow-avoiding shell needed - the previous stack redesign had to
       protrude ABOVE the box because the box itself had no room; this one
       is simply tall enough to hold the graphic directly). The box is now
       a horizontal row instead of a vertical stack, and grew (both wider
       and taller) specifically to give that graphic real presence - the
       one exception this round's brief allows to the "freeze all node
       sizes" rule, and only for Grid. */
    .grid-box {
      width: 146px;
      min-height: 92px;
      padding: 14px 14px 14px 16px;
      border-radius: 10px;
      flex-direction: row;
      align-items: center;
      justify-content: space-between;
      column-gap: 8px;
      text-align: left;
      position: relative;
      background-image: linear-gradient(165deg, rgba(255, 255, 255, 0.05), transparent 55%);
      /* A small technical chamfer on the top-left/bottom-right corners
         only - an asymmetric "enclosure" cue distinct from Battery's own
         symmetric taper, restrained rather than a full taper. */
      clip-path: polygon(9px 0, 100% 0, 100% calc(100% - 9px), calc(100% - 9px) 100%, 0 100%, 0 9px);
    }
    .grid-text {
      align-items: flex-start;
      gap: 3px;
      flex: 1 1 auto;
      min-width: 0;
    }
    .grid-box .node-value {
      font-size: 1rem;
    }
    .grid-box .node-sub {
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-size: 0.68rem;
      color: var(--ecco-text);
      opacity: 0.78;
    }
    /* The graphic zone itself - a fixed-size stage the pylon silhouette
       sits inside, vertically centred in the row alongside the text
       column so both share the same breathing room above/below. */
    .grid-graphic {
      position: relative;
      width: 42px;
      height: 48px;
      flex: 0 0 auto;
    }
    /* THIRD Grid symbol pass: the flat-topped-trapezoid "tower" from the
       first attempt at this pass read as barely-visible background noise
       behind two floating pill-shaped arms - a single solid wedge shape
       just doesn't carry the "pylon" read at all, whatever its tint.
       Replaced with two EXPLICIT diagonal legs (real rotated elements,
       not a clip-path illusion) forming a genuine splayed A-frame -
       the actual distinguishing silhouette of a transmission tower -
       crossed by three arms that narrow with height to visually match
       how the legs converge (wide low arm, narrow high arm), so the
       whole thing reads as one coherent tapered structure rather than
       arms floating over an unrelated body. */
    .pylon-leg {
      position: absolute;
      bottom: 0;
      width: 3px;
      height: 44px;
      border-radius: 1.5px 1.5px 0 0;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      transform-origin: 50% 100%;
      transition:
        background 0.4s ease,
        border-color 0.4s ease;
    }
    .pylon-leg.leg-left {
      left: 13px;
      transform: rotate(6deg);
    }
    .pylon-leg.leg-right {
      left: 26px;
      transform: rotate(-6deg);
    }
    .pylon-arm {
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
      height: 3px;
      border-radius: 1.5px;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      transition:
        background 0.4s ease,
        border-color 0.4s ease;
    }
    /* Widths/positions matched to where the two 6deg-rotated legs above
       actually sit at each height (computed, not eyeballed - the legs
       pivot from their own bottom-anchored x, so the gap between them
       narrows predictably with height), each with a small overhang past
       the legs so the arm visibly crosses rather than stopping exactly
       at them. */
    .pylon-arm.arm-top {
      top: 10px;
      width: 9px;
    }
    .pylon-arm.arm-mid {
      top: 22px;
      width: 13px;
    }
    .pylon-arm.arm-base {
      top: 35px;
      width: 17px;
    }
    .pylon-leg,
    .pylon-arm {
      pointer-events: none;
    }
    .grid-box.colour-grid-import .pylon-leg,
    .grid-box.colour-grid-import .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-import) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 62%, var(--ecco-border));
    }
    .grid-box.colour-grid-export .pylon-leg,
    .grid-box.colour-grid-export .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-export) 22%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-export) 62%, var(--ecco-border));
    }
    /* "idle" now specifically means connected + confirmed ~0W (see
       _gridState()'s doc comment) - a subtle steel-blue tint so the pylon
       still visibly reads as "alive", not the flat neutral treatment that
       used to cover every idle-ish case. "unavailable" (below) keeps that
       flat neutral look instead, since IT is the genuinely "nothing to
       report" state. */
    .grid-box.colour-grid-idle .pylon-leg,
    .grid-box.colour-grid-idle .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-idle) 18%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-idle) 50%, var(--ecco-border));
    }
    .grid-box.colour-grid-disconnected .pylon-leg,
    .grid-box.colour-grid-disconnected .pylon-arm {
      background: color-mix(in srgb, var(--ecco-line-grid-disconnected) 26%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-disconnected) 65%, var(--ecco-border));
    }
    .grid-box.colour-grid-unavailable .pylon-leg,
    .grid-box.colour-grid-unavailable .pylon-arm {
      background: var(--ecco-surface);
      border-color: var(--ecco-border);
    }
    /* background-COLOR specifically (not the background shorthand) -
       the shorthand resets every unspecified longhand including
       background-image to none, which was silently clobbering
       .grid-box's own gradient (see its base rule above) in every state.
       .node-box.colour-home already avoids this same trap the same way. */
    .grid-box.colour-grid-import {
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 55%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-import) 10%, var(--ecco-surface));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-grid-import) 50%, transparent);
    }
    .grid-box.colour-grid-export {
      border-color: color-mix(in srgb, var(--ecco-line-grid-export) 55%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-export) 10%, var(--ecco-surface));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-grid-export) 50%, transparent);
    }
    .grid-box.colour-grid-idle {
      border-color: color-mix(in srgb, var(--ecco-line-grid-idle) 40%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-idle) 7%, var(--ecco-surface));
      box-shadow: none;
    }
    .grid-box.colour-grid-disconnected {
      border-color: color-mix(in srgb, var(--ecco-line-grid-disconnected) 60%, var(--ecco-border));
      background-color: color-mix(in srgb, var(--ecco-line-grid-disconnected) 12%, var(--ecco-surface));
      box-shadow: 0 0 12px -5px color-mix(in srgb, var(--ecco-line-grid-disconnected) 50%, transparent);
    }
    .grid-box.colour-grid-unavailable {
      border-color: var(--ecco-border);
      background-color: var(--ecco-surface);
      box-shadow: none;
    }
    /* Pylon PULSE (this round): a smooth breathing glow on the pylon
       GRAPHIC ITSELF - .grid-graphic, not the whole .grid-box - explicitly
       NOT a blink/flash (no visibility/display toggling, no hard 0-opacity
       step). filter: brightness()+drop-shadow() both animate continuously
       through the full keyframe, so the low point is still fully visible,
       just dimmer/glow-less than the peak. --ecco-pylon-pulse-duration is
       set inline per-render (see _renderBottomNode()) from
       pylonPulseDurationS() - magnitude-scaled for importing/exporting,
       fixed for the two ~0W-ish states. --ecco-pylon-glow-colour is set
       per colour class below so the SAME keyframes/animation rule works
       for every state without four near-duplicate @keyframes blocks. */
    @keyframes ecco-pylon-pulse {
      0%,
      100% {
        filter: brightness(1) drop-shadow(0 0 0 transparent);
      }
      50% {
        filter: brightness(1.4) drop-shadow(0 0 5px var(--ecco-pylon-glow-colour, transparent));
      }
    }
    .grid-graphic.pylon-pulse {
      animation: ecco-pylon-pulse var(--ecco-pylon-pulse-duration, 4s) ease-in-out infinite;
    }
    .grid-box.colour-grid-import .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-import) 65%, transparent);
    }
    .grid-box.colour-grid-export .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-export) 65%, transparent);
    }
    .grid-box.colour-grid-idle .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-idle) 55%, transparent);
    }
    .grid-box.colour-grid-disconnected .grid-graphic {
      --ecco-pylon-glow-colour: color-mix(in srgb, var(--ecco-line-grid-disconnected) 65%, transparent);
    }

    .inverter-box {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      /* Compositional pass: this is the ONE node every other node's size
         and glow must read as subordinate to (see this round's design
         note). Every arm's reach from the inverter (_layout()'s per-node
         x/y offsets) has to grow to keep
         clearance as this box WIDENS - already-tight at the original
         156px width around a typical card width - so width only grew a
         little (156 -> 160px); the actual size/prominence increase comes
         from taller padding (a real footprint gain that only costs
         vertical room, which had far more slack than horizontal) plus a
         visibly stronger glow/gradient/border, so the inverter reads as
         the hero through PRESENCE, not primarily through occupying more
         of the card's width than Battery/Grid can spare either side of
         it. Home/Battery/Grid were brought down closer to each other's
         own width instead of the inverter being widened further to
         "win" - see .node-box.colour-home and .grid-box. */
      width: 152px;
      padding: 14px 9px;
      border-radius: 18px;
      background: radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--ecco-accent) 20%, var(--ecco-surface)), var(--ecco-surface));
      border: 1px solid color-mix(in srgb, var(--ecco-accent) 35%, var(--ecco-border));
      /* A soft accent glow plus a quiet downward drop shadow for a touch
         more depth/lift - both strengthened so the inverter's presence
         scales with its height rather than needing more width to read as
         dominant. */
      box-shadow:
        0 0 28px -6px var(--ecco-glow),
        0 4px 14px -4px rgba(0, 0, 0, 0.4);
      box-sizing: border-box;
      gap: 3px;
      text-align: center;
      position: relative;
    }
    .inverter-box ha-icon {
      --mdc-icon-size: 26px;
      color: var(--ecco-accent);
    }
    /* Port cues (hardware-identity pass): a small physical connector nub
       at each of the inverter's four logical ports - TOP=PV/Solar,
       LEFT=Battery, RIGHT=Grid, BOTTOM=Home/Load, matching the layout
       the maintainer specified. Static tint per arm's own line colour (not
       state-driven - these identify WHICH port, not its current value).
       TRUE PORT GEOMETRY pass: these are no longer purely decorative -
       each one also carries a data-port attribute (see the render
       method) and IS the real, measured connection point every route now
       terminates on exactly (see the class-level note above
       buildRouteD()) - so their on-screen position is load-bearing, not
       just a visual cue. */
    .inverter-port {
      position: absolute;
      border-radius: 2px;
      border: 1px solid var(--ecco-border);
      background: color-mix(in srgb, var(--ecco-text-muted) 30%, var(--ecco-surface));
      pointer-events: none;
    }
    .inverter-port.port-pv {
      top: -3px;
      left: 50%;
      width: 12px;
      height: 5px;
      transform: translateX(-50%);
      background: color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-solar) 70%, var(--ecco-border));
    }
    .inverter-port.port-home {
      bottom: -3px;
      left: 50%;
      width: 12px;
      height: 5px;
      transform: translateX(-50%);
      background: color-mix(in srgb, var(--ecco-line-home) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-home) 70%, var(--ecco-border));
    }
    .inverter-port.port-battery {
      left: -3px;
      top: 50%;
      width: 5px;
      height: 12px;
      transform: translateY(-50%);
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 60%, var(--ecco-border));
    }
    .inverter-port.port-grid {
      right: -3px;
      top: 50%;
      width: 5px;
      height: 12px;
      transform: translateY(-50%);
      background: color-mix(in srgb, var(--ecco-line-grid-import) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 60%, var(--ecco-border));
    }
    /* Every OTHER node's own port marker - Solar 1/2, the 3+-source
       combiner, Home, Generator (all top-facing, .port-top/.port-
       bottom), Battery (right-facing) and Grid (left-facing). Same
       "real, measured connection point" role as .inverter-port above,
       just unthemed by default (each node's own colour-* family tints
       it via the rules below, matching that node's own line colour - the
       same "small cohesive link" language the icon tint already uses
       elsewhere in this file). Sits centred on its edge, mostly outside
       the box's own border so the route's final approach is genuinely
       visible arriving at it, not hidden under the node.
       IMPORTANT: pointer-events:none here matters beyond the usual
       "decorative, don't intercept clicks" reason - these are also
       [data-port] measurement targets (see _measurePorts()), and a
       port sitting exactly on a clickable node's own edge must never
       itself become the hit target for that node's tap/keyboard
       more-info handler. */
    .node-port {
      position: absolute;
      width: 10px;
      height: 6px;
      border-radius: 2px;
      border: 1px solid var(--ecco-border);
      background: color-mix(in srgb, var(--ecco-text-muted) 30%, var(--ecco-surface));
      pointer-events: none;
    }
    .node-port.port-top,
    .node-port.port-bottom {
      left: 50%;
      transform: translateX(-50%);
    }
    .node-port.port-top {
      top: -3px;
    }
    .node-port.port-bottom {
      bottom: -3px;
    }
    .node-port.port-left,
    .node-port.port-right {
      top: 50%;
      width: 6px;
      height: 10px;
      transform: translateY(-50%);
    }
    .node-port.port-left {
      left: -3px;
    }
    .node-port.port-right {
      right: -3px;
    }
    .colour-solar .node-port {
      background: color-mix(in srgb, var(--ecco-line-solar) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-solar) 70%, var(--ecco-border));
    }
    .colour-home .node-port {
      background: color-mix(in srgb, var(--ecco-line-home) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-home) 70%, var(--ecco-border));
    }
    .battery-box .node-port {
      background: color-mix(in srgb, var(--ecco-line-battery-discharge) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 60%, var(--ecco-border));
    }
    .grid-box .node-port {
      background: color-mix(in srgb, var(--ecco-line-grid-import) 45%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 60%, var(--ecco-border));
    }
    .colour-generator .node-port {
      background: color-mix(in srgb, var(--ecco-line-generator) 55%, var(--ecco-surface));
      border-color: color-mix(in srgb, var(--ecco-line-generator) 70%, var(--ecco-border));
    }
    /* Battery/Grid's fixed CSS-px width and their (also fixed) logical-unit
       centre position (see _layout()'s battery/grid x/y offsets) only
       agree at one reference card width - live verification this round
       found that below ~520px CARD
       width, Battery's own left edge (and Grid's own right edge) render
       PAST ha-card's own edge and get genuinely clipped by its
       overflow:hidden - not merely "a bit tight", an actual missing slice
       of the box, confirmed via elementFromPoint hit-testing at the
       claimed-clipped coordinates returning nothing. This affects the
       420px "default" width, not just the 380px "narrow" one.
       @container (not @media - see :host's container-type above) so this
       responds to the CARD's own rendered width. 82px keeps Battery's/
       Grid's own half-width within the smallest tested card's (380px)
       actual available room either side of centre - verified by direct
       measurement, not guessed. Battery switches to a single centred
       column (icon above text, matching Grid's own layout) rather than
       staying icon-left/text-right, so its longest status word
       ("Discharging"/"Charging") gets the full available width instead of
       splitting it with the icon - the icon+text ROW layout is otherwise
       kept exactly as the maintainer approved; this only applies below the
       breakpoint where the row genuinely no longer fits. */
    @container (max-width: 550px) {
      .battery-box {
        width: 82px;
        padding: 10px 8px;
      }
      .battery-terminal {
        width: 24px;
        height: 7px;
      }
      /* Grid keeps its own two-region (text + graphic) layout concept at
         narrow widths rather than reverting to a plain icon - just scaled
         down proportionally so it still comfortably clears the inverter
         and the card's own edge (see _layout()'s grid position note)
         without losing the identity this round's redesign is for.
         Live-review found the first pass here too tight: the text column
         (down to 45px) was narrower than "-1.40 kW"/"Exporting" actually
         need (measured ~63px/~54px at the unshrunk 1rem/0.68rem sizes),
         so the value visibly ran into the graphic rather than just
         truncating. Fixed with FOUR small levers together rather than one
         big one - a touch more box width, tighter padding/gap, a
         slightly smaller graphic, and a slightly smaller value font -
         so no single change has to do all the work (and the box still
         stays well short of the ~104px width that verified unsafe for
         inverter/edge clearance at this breakpoint). */
      .grid-box {
        width: 96px;
        min-height: 66px;
        padding: 8px 5px 8px 8px;
        column-gap: 3px;
      }
      .grid-box .node-value {
        font-size: 0.9rem;
      }
      .grid-box .node-sub {
        font-size: 0.6rem;
        letter-spacing: 0.03em;
      }
      .grid-graphic {
        width: 19px;
        height: 31px;
      }
      .pylon-leg {
        width: 2px;
        height: 27px;
      }
      .pylon-leg.leg-left {
        left: 6px;
      }
      .pylon-leg.leg-right {
        left: 11px;
      }
      .pylon-arm.arm-top {
        top: 6px;
        width: 6px;
      }
      .pylon-arm.arm-mid {
        top: 15px;
        width: 8px;
      }
      .pylon-arm.arm-base {
        display: none;
      }
    }
    .inverter-value {
      font-size: 0.95rem;
      font-variant-numeric: tabular-nums;
    }
    /* The inverter's centre figure is AC output specifically, not total
       system throughput (it will not simply sum against home/grid/battery
       figures) - this caption makes that explicit without changing the
       underlying entity/calculation. Only shown when PV IN isn't (see
       .inverter-metrics) - i.e. the 0/1/3+ solar-source configs that keep
       the original single-value display untouched. */
    .inverter-caption {
      font-size: 0.64rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: color-mix(in srgb, var(--ecco-text-muted) 55%, var(--ecco-text) 45%);
      margin-top: 1px;
    }
    /* PV IN / AC OUT pair - replaces the single AC-output value+caption
       above when the combined 2-array Solar Total figure is available
       (see the pvInW param on _renderInverterNode()). Labels use the same
       small-caps treatment as .inverter-caption; values match the row
       styling already established on the solar node's own header
       (.solar-node-header) for visual consistency across the two
       "labelled metric row" spots in this diagram. */
    .inverter-metrics {
      display: flex;
      flex-direction: column;
      gap: 3px;
      width: 100%;
      margin-top: 2px;
    }
    .inverter-metric-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    /* Bumped size/contrast from the previous pass (0.62rem, 55/45 muted-
       text mix) per live-review feedback that PV IN/AC OUT read too
       quietly next to their values - still clearly secondary to
       .inverter-metric-value below, just no longer easy to miss. */
    .inverter-metric-label {
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: color-mix(in srgb, var(--ecco-text-muted) 35%, var(--ecco-text) 65%);
    }
    .inverter-metric-value {
      font-size: 0.86rem;
      font-weight: 700;
      color: var(--ecco-text);
      font-variant-numeric: tabular-nums;
    }
    .state-pill {
      margin-top: 2px;
      font-size: 0.6rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 1px 7px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--ecco-text-muted) 20%, transparent);
      color: var(--ecco-text-muted);
    }
    .severity-ok .state-pill,
    .state-pill.severity-ok {
      background: color-mix(in srgb, var(--ecco-ok) 22%, transparent);
      color: var(--ecco-ok);
    }
    .severity-warning .state-pill,
    .state-pill.severity-warning {
      background: color-mix(in srgb, var(--ecco-warning) 24%, transparent);
      color: var(--ecco-warning);
    }
    .severity-fault .state-pill,
    .state-pill.severity-fault {
      background: color-mix(in srgb, var(--ecco-fault) 24%, transparent);
      color: var(--ecco-fault);
    }
    .inverter-box.severity-fault {
      box-shadow: 0 0 18px -4px color-mix(in srgb, var(--ecco-fault) 55%, transparent);
    }

    /* Compact always-visible strip (grid voltage / AC temp / DC temp) -
       sits between the flow diagram and the "Today" totals, filling space
       that would otherwise sit empty. Deliberately quieter than the
       today-item tiles below (no bold heading row, smaller everything) so
       it reads as a secondary at-a-glance strip, not a second headline
       section. */
    /* Grid, not flex: up to five tiles now (was three) - auto-fit lets
       them sit in one confident row at typical/wide card widths while
       wrapping to 2-3 per row on a narrow card without ever crushing a
       label/value below a readable width (min 92px per tile), and without
       needing a separate narrow-width breakpoint. */
    .quick-metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
      gap: 6px;
    }
    .quick-metric {
      display: flex;
      align-items: center;
      gap: 5px;
      min-width: 0;
      padding: 5px 7px;
      border-radius: 10px;
      background-color: color-mix(in srgb, var(--ecco-surface) 70%, transparent);
      background-image: linear-gradient(160deg, rgba(255, 255, 255, 0.035), transparent 65%);
      border: 1px solid var(--ecco-border);
      box-sizing: border-box;
    }
    .quick-metric ha-icon {
      --mdc-icon-size: 15px;
      color: var(--ecco-text-muted);
      flex-shrink: 0;
    }
    /* Grid Connected specifically (see _renderQuickMetrics()) - reuses the
       card's existing ok/fault severity colours rather than inventing new
       ones, matching every other state-aware surface here. Connected
       stays deliberately quiet (a subtle tint, not a celebratory green);
       disconnected is the one state on this whole strip that should read
       as a real problem at a glance. */
    .quick-metric.variant-ok {
      border-color: color-mix(in srgb, var(--ecco-ok) 40%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-ok) 8%, var(--ecco-surface));
    }
    .quick-metric.variant-ok ha-icon {
      color: var(--ecco-ok);
    }
    .quick-metric.variant-fault {
      border-color: color-mix(in srgb, var(--ecco-fault) 55%, var(--ecco-border));
      background: color-mix(in srgb, var(--ecco-fault) 14%, var(--ecco-surface));
    }
    .quick-metric.variant-fault ha-icon {
      color: var(--ecco-fault);
    }
    .quick-metric.variant-fault .quick-metric-value {
      color: var(--ecco-fault);
    }
    .quick-metric-text {
      display: flex;
      flex-direction: column;
      line-height: 1.1;
      min-width: 0;
    }
    .quick-metric-label {
      font-size: 0.56rem;
      color: var(--ecco-text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .quick-metric-value {
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--ecco-text);
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }

    .today {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 4px;
      border-top: 1px solid var(--ecco-border);
    }
    .today-heading-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    .today-heading {
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--ecco-text-muted);
    }
    /* Solar Share folded into the "Today" heading row instead of its own
       badge row below - see _renderToday()/_solarShareText(). */
    .today-solar-share {
      font-size: 0.68rem;
      color: var(--ecco-text-muted);
      white-space: nowrap;
    }
    .today-solar-share strong {
      color: var(--ecco-text);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .today-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px 10px;
    }
    .today.compact .today-grid {
      grid-template-columns: repeat(6, minmax(0, 1fr));
    }
    .today-item {
      display: flex;
      flex-direction: column;
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      border-radius: 10px;
      padding: 6px 8px;
      min-width: 0;
    }
    /* Category colour per tile - identity, not a health judgement (see
       _renderToday()'s own comment). A quiet tint/border only, the same
       restrained treatment the flow nodes themselves use, so the row
       reads as "these six totals belong to six different parts of the
       system" at a glance without turning into a row of bright chips. */
    .today-item.colour-solar {
      border-color: color-mix(in srgb, var(--ecco-line-solar) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-solar) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-home {
      border-color: color-mix(in srgb, var(--ecco-line-home) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-home) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-grid-import {
      border-color: color-mix(in srgb, var(--ecco-line-grid-import) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-grid-import) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-grid-export {
      border-color: color-mix(in srgb, var(--ecco-line-grid-export) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-grid-export) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-battery-charge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-charge) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-battery-charge) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-item.colour-battery-discharge {
      border-color: color-mix(in srgb, var(--ecco-line-battery-discharge) 40%, var(--ecco-border));
      background: linear-gradient(160deg, color-mix(in srgb, var(--ecco-line-battery-discharge) 12%, var(--ecco-surface)), var(--ecco-surface));
    }
    .today-label {
      font-size: 0.62rem;
      color: var(--ecco-text-muted);
    }
    .today-value {
      font-size: 0.8rem;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }

    .badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .badge {
      font-size: 0.7rem;
      color: var(--ecco-text-muted);
      background: var(--ecco-surface);
      border: 1px solid var(--ecco-border);
      border-radius: 999px;
      padding: 4px 10px;
    }
    .badge strong {
      color: var(--ecco-text);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }

    .details-toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      background: transparent;
      border: none;
      color: var(--ecco-text-muted);
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 4px 2px;
      cursor: pointer;
    }
    .details-toggle ha-icon {
      --mdc-icon-size: 18px;
    }

    .details {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 2px 2px 4px;
    }
    .details-row {
      display: flex;
      justify-content: space-between;
      font-size: 0.76rem;
      padding: 3px 0;
      border-bottom: 1px dashed var(--ecco-border);
    }
    .details-label {
      color: var(--ecco-text-muted);
    }
    .details-value {
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .details-empty {
      font-size: 0.76rem;
      color: var(--ecco-text-muted);
    }
  `;
}

declare global {
  interface HTMLElementTagNameMap {
    "ecco-energy-flow-card": EccoEnergyFlowCard;
  }
}

// HACS/Lovelace card-picker registration.
(window as unknown as { customCards?: unknown[] }).customCards = [
  ...(((window as unknown as { customCards?: unknown[] }).customCards) ?? []),
  {
    type: "ecco-energy-flow-card",
    name: "ECCO Energy Flow Card",
    description:
      "A live solar / inverter / battery / grid / home energy flow diagram with the inverter as a first-class centre node, plus daily energy totals.",
    preview: false,
  },
];
