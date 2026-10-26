// Routing data for the approved V4 scene pack: hardware anchors, the
// physical power routes (vertex lists, plate pixels), the riser bundle, the
// ground entry, the traced paving and the debug labels. This file holds
// numbers only; the renderer (scene.ts), the motion model and the telemetry
// never read it directly, and the card merges an optional `scene.routing`
// override from the Lovelace configuration over these defaults, so routes
// can be revised later without touching code, telemetry or animation.
//
// Geometry frozen 2026-10-26 (owner decision: move to integration; known
// visual follow-ups are listed in README.md).

export interface Pt {
  x: number;
  y: number;
}
export interface AnchorPt extends Pt {
  label: string;
}

export type AnchorKey =
  | "main_pv"
  | "main_pv_frame"
  | "main_pv_edge"
  | "garage_pv"
  | "garage_pv_frame"
  | "garage_pv_edge"
  | "battery_cabinet"
  | "inverter"
  | "ground_entry"
  | "downpipe"
  | "door_post"
  | "building_corner"
  | "chimney"
  | "fascia_start"
  | "lawn_transition"
  | "ev_charger"
  | "pylon"
  | "house";

export type PowerRouteKey = "solarMain" | "solarGarage" | "battery" | "grid" | "home";
export type InfoRouteKey = "solarInfo" | "batteryInfo" | "gridInfo" | "homeInfo";
export type RouteKey = PowerRouteKey | InfoRouteKey;

export interface RiserTrack {
  x: number;
  /** Ground level where the route turns up; the shallowest track on each side takes the outermost riser. */
  ground: number;
  side: "left" | "right";
}

export interface RoutingData {
  canvas: { width: number; height: number };
  anchors: Record<AnchorKey, AnchorPt>;
  /** The inverter underside: y where every riser ends. */
  riserTop: number;
  risers: Record<PowerRouteKey, RiserTrack>;
  /** The ground-level convergence corridor below the inverter. */
  entry: { x0: number; x1: number; y0: number; y1: number };
  /** Fillet radius per route (plate px); routes not listed use BEND_RADIUS. */
  bend: Partial<Record<RouteKey, number>>;
  /** Physical power routes as straight-segment vertex lists; each ends with its vertical riser (home starts with it). */
  power: Record<PowerRouteKey, Pt[]>;
  /** Intermediate points of the Solar card's information link (between the card port and the array). */
  solarInfoWaypoints: Pt[];
  /** Where the Home card's information link leaves the house connection. */
  homeInfoStart: Pt;
  /** Traced paving for the debug overlay. */
  paving: Array<{ label: string; points: Pt[] }>;
  /** Names of the battery route's vertices, in order, for the debug overlay. */
  batteryWaypoints: string[];
}

/** What `scene.routing` may override. Every field is optional; lists replace, points and tracks merge per key. */
export interface RoutingOverride {
  anchors?: Partial<Record<AnchorKey, Partial<AnchorPt>>>;
  riserTop?: number;
  risers?: Partial<Record<PowerRouteKey, Partial<RiserTrack>>>;
  entry?: Partial<RoutingData["entry"]>;
  bend?: Partial<Record<RouteKey, number>>;
  power?: Partial<Record<PowerRouteKey, Pt[]>>;
  solarInfoWaypoints?: Pt[];
  homeInfoStart?: Pt;
  paving?: Array<{ label: string; points: Pt[] }>;
  batteryWaypoints?: string[];
}

export const BEND_RADIUS = 12;

export const V4_ROUTING: RoutingData = {
  canvas: { width: 1448, height: 1086 },
  anchors: {
    main_pv: { x: 610, y: 335, label: "Array 1 (main roof)" },
    main_pv_frame: { x: 700, y: 409, label: "Array 1 frame connection" },
    main_pv_edge: { x: 751, y: 380, label: "Array 1 frame corner / cable exit" },
    garage_pv: { x: 1140, y: 500, label: "Array 2 (garage roof)" },
    garage_pv_frame: { x: 1044, y: 508, label: "Array 2 frame connection" },
    garage_pv_edge: { x: 1044, y: 537, label: "Array 2 cable exit (fascia)" },
    battery_cabinet: { x: 150, y: 512, label: "Battery cabinet" },
    inverter: { x: 1002, y: 624, label: "Inverter underside entry" },
    ground_entry: { x: 1002, y: 722, label: "Ground convergence" },
    downpipe: { x: 748, y: 620, label: "Downpipe / service wall" },
    door_post: { x: 1104, y: 640, label: "Garage wall line (left of the door)" },
    building_corner: { x: 948, y: 600, label: "Building corner" },
    chimney: { x: 952, y: 300, label: "Chimney (service drop landing)" },
    fascia_start: { x: 782, y: 455, label: "Fascia (right of the skylight)" },
    lawn_transition: { x: 230, y: 556, label: "Buried lawn crossing (level run)" },
    ev_charger: { x: 1048, y: 655, label: "EV charger" },
    pylon: { x: 1297, y: 290, label: "Grid pylon" },
    house: { x: 752, y: 600, label: "House connection" },
  },
  riserTop: 624,
  risers: {
    grid: { x: 990, ground: 700, side: "left" },
    solarMain: { x: 996, ground: 704, side: "left" },
    home: { x: 1002, ground: 708, side: "left" },
    battery: { x: 1008, ground: 742, side: "left" },
    solarGarage: { x: 1014, ground: 746, side: "right" },
  },
  entry: { x0: 964, x1: 1022, y0: 696, y1: 752 },
  bend: { battery: 5, home: 8, solarMain: 8, solarGarage: 8, grid: 8 },
  power: {
    // Array 1: frame attachment -> along the frame edge to its corner -> level jog past the skylight -> straight down beside
    // it to the fascia -> along the fascia to the building corner -> corner track 946 -> floor -> riser.
    solarMain: [
      { x: 700, y: 409 },
      { x: 751, y: 380 },
      { x: 782, y: 380 },
      { x: 782, y: 455 },
      { x: 946, y: 505 },
      { x: 946, y: 704 },
      { x: 996, y: 704 },
      { x: 996, y: 624 },
    ],
    // Array 2: frame corner -> straight down to the garage fascia -> along the fascia -> down the garage wall line -> deep
    // floor run -> riser.
    solarGarage: [
      { x: 1044, y: 508 },
      { x: 1044, y: 537 },
      { x: 1104, y: 554 },
      { x: 1104, y: 746 },
      { x: 1014, y: 746 },
      { x: 1014, y: 624 },
    ],
    // Battery: cabinet base -> out of the cabinet front -> level buried lawn crossing -> down to the patio corner -> patio
    // edge -> terrace wall -> landing -> step 1 -> tread -> step 2 -> lower path and drive -> riser.
    battery: [
      { x: 150, y: 512 },
      { x: 150, y: 556 },
      { x: 310, y: 556 },
      { x: 310, y: 570 },
      { x: 520, y: 647 },
      { x: 548, y: 682 },
      { x: 620, y: 682 },
      { x: 620, y: 707 },
      { x: 640, y: 707 },
      { x: 640, y: 723 },
      { x: 1008, y: 742 },
      { x: 1008, y: 624 },
    ],
    // Grid: pylon lattice -> level service drop to the chimney face -> straight down the chimney, gable and building corner
    // (beside the bush) -> floor -> riser.
    grid: [
      { x: 1297, y: 290 },
      { x: 952, y: 290 },
      { x: 952, y: 700 },
      { x: 990, y: 700 },
      { x: 990, y: 624 },
    ],
    // Home (drawn inverter -> house): riser -> level foundation run -> up the service wall beside the downpipe to the entry.
    home: [
      { x: 1002, y: 624 },
      { x: 1002, y: 708 },
      { x: 760, y: 708 },
      { x: 760, y: 600 },
    ],
  },
  solarInfoWaypoints: [{ x: 430, y: -1 }, { x: 545, y: 275 }],
  homeInfoStart: { x: 745, y: 606 },
  paving: [
    { label: "rear garden path", points: [{ x: 110, y: 514 }, { x: 310, y: 502 }] },
    { label: "lawn crossing (buried, level)", points: [{ x: 150, y: 556 }, { x: 310, y: 556 }] },
    { label: "patio left corner drop", points: [{ x: 310, y: 556 }, { x: 310, y: 570 }] },
    { label: "patio front edge", points: [{ x: 310, y: 570 }, { x: 520, y: 647 }] },
    { label: "terrace front wall", points: [{ x: 520, y: 647 }, { x: 548, y: 682 }] },
    { label: "upper landing edge", points: [{ x: 548, y: 682 }, { x: 700, y: 692 }] },
    { label: "step 1 riser", points: [{ x: 560, y: 694 }, { x: 700, y: 699 }] },
    { label: "step 2 riser", points: [{ x: 575, y: 707 }, { x: 690, y: 711 }] },
    { label: "lower path", points: [{ x: 575, y: 721 }, { x: 790, y: 742 }] },
    { label: "drive paving", points: [{ x: 790, y: 742 }, { x: 1022, y: 742 }] },
  ],
  batteryWaypoints: [
    "cabinet base",
    "out of the cabinet front onto the lawn",
    "end of the level buried crossing",
    "patio left corner",
    "patio front edge, lawn border",
    "terrace front wall foot",
    "across the upper landing",
    "down step 1 onto the tread",
    "along the tread",
    "down step 2 onto the lower paving",
    "lower path and drive paving to the ground convergence",
    "riser into the inverter",
  ],
};

/** Merges a configuration override over the defaults. Lists replace; points, tracks and the entry box merge per key. */
export function mergeRouting(base: RoutingData, override: RoutingOverride | undefined): RoutingData {
  if (!override) return base;
  const anchors = { ...base.anchors } as Record<AnchorKey, AnchorPt>;
  for (const [k, v] of Object.entries(override.anchors ?? {}) as Array<[AnchorKey, Partial<AnchorPt> | undefined]>) {
    if (v && anchors[k]) anchors[k] = { ...anchors[k], ...v };
  }
  const risers = { ...base.risers } as Record<PowerRouteKey, RiserTrack>;
  for (const [k, v] of Object.entries(override.risers ?? {}) as Array<[PowerRouteKey, Partial<RiserTrack> | undefined]>) {
    if (v && risers[k]) risers[k] = { ...risers[k], ...v };
  }
  const power = { ...base.power } as Record<PowerRouteKey, Pt[]>;
  for (const [k, v] of Object.entries(override.power ?? {}) as Array<[PowerRouteKey, Pt[] | undefined]>) {
    if (Array.isArray(v) && v.length >= 2 && v.every((p) => Number.isFinite(p?.x) && Number.isFinite(p?.y))) power[k] = v.map((p) => ({ x: p.x, y: p.y }));
  }
  return {
    canvas: base.canvas,
    anchors,
    riserTop: override.riserTop ?? base.riserTop,
    risers,
    entry: { ...base.entry, ...(override.entry ?? {}) },
    bend: { ...base.bend, ...(override.bend ?? {}) },
    power,
    solarInfoWaypoints: override.solarInfoWaypoints ?? base.solarInfoWaypoints,
    homeInfoStart: override.homeInfoStart ?? base.homeInfoStart,
    paving: override.paving ?? base.paving,
    batteryWaypoints: override.batteryWaypoints ?? base.batteryWaypoints,
  };
}
