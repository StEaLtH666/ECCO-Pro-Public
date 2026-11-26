// Routing data for the approved V4 scene pack (V2 geometry): the plate's
// perspective model, hardware anchors, the inverter underside, the physical
// power routes (vertex lists, plate pixels), the information-card placements
// and their connectors, and the debug-only traces, obstacles and equipment
// boxes. This file holds numbers only; the renderer (scene.ts), the motion
// model and the telemetry never read it directly, and the card merges an
// optional `scene.routing` override from the Lovelace configuration over
// these defaults, so routes and cards can be revised without touching code,
// telemetry or animation.
//
// V2 (2026-10-26): every route segment follows one of the plate's building
// axes (`perspective`: a direction field fitted to the plate's measured
// edges, or a vanishing point): X along the inverter wall, Y along the
// house's side wall and the steps, Z vertical, S_main / S_garage up the roof
// slopes. Bends are therefore real-world right angles in perspective, not
// screen right angles. A route may run out of sight for a stretch (`buried`,
// a duct under beds and planters): that stretch is not drawn and its particles
// pass unseen, but it stays on the axes like the rest. test/artworkLayout.test.ts
// holds the geometry to all of that.

import type { AxisModel, AxisModels } from "./perspective.ts";

export interface Pt {
  x: number;
  y: number;
}
export interface AnchorPt extends Pt {
  label: string;
}

export type AnchorKey = "main_pv" | "garage_pv" | "battery_cabinet" | "inverter" | "pylon_light" | "house" | "chimney";

export type PowerRouteKey = "solarMain" | "solarGarage" | "battery" | "grid" | "home";
export type InfoRouteKey = "solarInfoMain" | "solarInfoGarage" | "batteryInfo" | "gridInfo" | "homeInfo";
export type RouteKey = PowerRouteKey | InfoRouteKey;
export type CardKey = "solar" | "grid" | "battery" | "home";
export type CardAlign = "top-left" | "top-right" | "bottom-left" | "bottom-right" | "top-center" | "bottom-center";

/** Where an information card sits: the card's `align` corner is pinned to `at`, so it grows away from that point as the overlay scale rises. */
export interface CardPlacement {
  at: Pt;
  align: CardAlign;
}

/** An information connector: from a port on the card's edge to its equipment. */
export interface InfoLink {
  card: CardKey;
  /**
   * The card edge the connector leaves from and the position along it (0 = left / top, 1 = right / bottom). `x` (top,
   * bottom) or `y` (left, right) pins the port to that plate coordinate instead, clamped to the edge, so the connector
   * stays on one line at every card size.
   */
  port: { side: "top" | "bottom" | "left" | "right"; at: number; x?: number; y?: number };
  /**
   * Optional first bend: the connector leaves the port along axis `elbow[0]`
   * and turns onto axis `elbow[1]` where that axis line through `points[0]`
   * meets it, so the bend stays a perspective right angle at every card size.
   * (A configuration override may set it to null for a straight connector; its two axes must differ.)
   */
  elbow?: [string, string];
  /** Fixed plate-px points after the port (and the elbow); the last one lies on the equipment. */
  points: Pt[];
}

export interface RoutingData {
  canvas: { width: number; height: number };
  /** Per building axis (X, Y, Z and the roof slopes): a vanishing point or a direction field fitted to the plate's measured edges. */
  perspective: AxisModels;
  anchors: Record<AnchorKey, AnchorPt>;
  /** The inverter's bottom edge (the line the cable glands sit on): the invisible connection bar. */
  underside: { from: Pt; to: Pt };
  /** Physical power routes as straight-segment vertex lists, equipment to gland (home: gland to house). */
  power: Record<PowerRouteKey, Pt[]>;
  /**
   * Out-of-sight stretches of a power route, as vertex index pairs [from, to]: the segments between them run in a
   * buried duct, so they are not drawn and the particles pass through unseen (their timing still follows the whole route).
   */
  buried: Partial<Record<PowerRouteKey, Array<[number, number]>>>;
  /** Information-card placements at desktop scale and from `compactFrom` (phones) up. */
  cards: Record<CardKey, CardPlacement>;
  cardsCompact: Partial<Record<CardKey, CardPlacement>>;
  compactFrom: number;
  info: Record<InfoRouteKey, InfoLink>;
  /** Fillet radius per route (plate px); routes not listed use BEND_RADIUS. */
  bend: Partial<Record<RouteKey, number>>;
  /** Debug overlay: the physical edges the routes follow. */
  traces: Array<{ label: string; points: Pt[] }>;
  /** Debug overlay and tests: things no drawn power route may cross; connectors avoid them too, except where the tests list a crossing. */
  obstacles: Array<{ label: string; points: Pt[] }>;
  /** Tests and debug overlay: equipment no information card may cover. */
  equipment: Array<{ label: string; x: number; y: number; w: number; h: number }>;
  /** Debug overlay: the name of every vertex, per power route. */
  nodes: Record<PowerRouteKey, string[]>;
}

/** What `scene.routing` may override. Every field is optional; lists replace, points and placements merge per key. */
export interface RoutingOverride {
  perspective?: Record<string, AxisModel>;
  anchors?: Partial<Record<AnchorKey, Partial<AnchorPt>>>;
  underside?: Partial<RoutingData["underside"]>;
  power?: Partial<Record<PowerRouteKey, Pt[]>>;
  buried?: Partial<Record<PowerRouteKey, Array<[number, number]>>>;
  cards?: Partial<Record<CardKey, Partial<CardPlacement>>>;
  cardsCompact?: Partial<Record<CardKey, Partial<CardPlacement>>>;
  compactFrom?: number;
  info?: Partial<Record<InfoRouteKey, Partial<InfoLink>>>;
  bend?: Partial<Record<RouteKey, number>>;
  traces?: Array<{ label: string; points: Pt[] }>;
  obstacles?: Array<{ label: string; points: Pt[] }>;
  equipment?: Array<{ label: string; x: number; y: number; w: number; h: number }>;
  nodes?: Partial<Record<PowerRouteKey, string[]>>;
}

/** Corner rounding (plate px): small, so nested bends and short kicks keep their shape. */
export const BEND_RADIUS = 3;

/** A polygon or polyline written as flat x, y pairs (keeps the long debug lists readable). */
const poly = (...xy: number[]): Pt[] => Array.from({ length: Math.floor(xy.length / 2) }, (_, i) => ({ x: xy[2 * i]!, y: xy[2 * i + 1]! }));

export const V4_ROUTING: RoutingData = {
  canvas: { width: 1448, height: 1086 },
  // Fitted 2026-10-26 to 158 measured plate edges (X rms 1.28 deg, Y 1.67, S_main 0.41; S_garage from 5 edges as a
  // vanishing point; verticals are exactly vertical on the plate).
  perspective: {
    X: { field: [12.105, -6.495, 14.665, 9.607, -3.853, 4.53], size: [1448, 1086] },
    Y: { field: [-8.448, -2.224, -7.895, 0.724, -1.106, 0.985], size: [1448, 1086] },
    Z: { field: [90, 0, 0, 0, 0, 0], size: [1448, 1086] },
    S_main: { field: [-38.14, -9.444, -5.991, -6.568, -9.7, -4.422], size: [1448, 1086] },
    S_garage: { vp: { x: -820.3, y: -370.7 } },
  },
  anchors: {
    main_pv: { x: 610, y: 335, label: "Array 1 (main roof)" },
    garage_pv: { x: 1140, y: 500, label: "Array 2 (garage roof)" },
    battery_cabinet: { x: 150, y: 512, label: "Battery cabinet" },
    inverter: { x: 1002, y: 624, label: "Inverter" },
    pylon_light: { x: 1319.5, y: 89.5, label: "Pylon top light" },
    house: { x: 784, y: 594.5, label: "House connection (wall light)" },
    chimney: { x: 952, y: 300, label: "Chimney" },
  },
  // The inverter's underside front edge as painted (y = 0.4009 x + 237.72, front face x 958-1010.5); the five
  // painted cables C1..C5 hang from glands on it.
  underside: { from: { x: 958, y: 621.8 }, to: { x: 1010.5, y: 642.8 } },
  // Routes (2026-10-26, judged and reviewed): Array 1 up its right frame edge to the ridge, along the ridge cap and
  // down the chimney's left edge, then the garage fascia; Array 2 along the eave gutter and down the corner downpipe;
  // the grid on painted wire W6 to the chimney, down its right edge, the garage verge and front corner. Those three
  // run on nested ground tracks in front of the pot and rise up painted cables C5, C3 and C4. The battery follows
  // the rear path, the lawn edge and the patio's riser foot, runs on along the terrace and the step paving (out of
  // sight wherever a plant, bed, path light or planter stands in front of it), comes out on the lower step's nosing
  // and rises up C2. The house feed (owner's design, 2026-10-27) leaves C1's gland downward, turns under the unit's
  // bottom-left corner, runs up the inverter's left side, along the garage wall into the internal corner with the
  // house, then along the house wall in the band between the upper window and the dining glazing, and drops onto the
  // wall light left of the glazing, where it ends.
  power: {
    solarMain: [{ x: 752.8, y: 375 }, { x: 825.4, y: 289.9 }, { x: 924, y: 312.3 }, { x: 924, y: 485.4 }, { x: 1100.5, y: 572 }, { x: 1100.5, y: 735.5 }, { x: 1050.8, y: 749.1 }, { x: 961, y: 712.6 }, { x: 1007, y: 699.3 }, { x: 1007, y: 641.4 }],
    solarGarage: [{ x: 1299.4, y: 503 }, { x: 1323.6, y: 513 }, { x: 1118.5, y: 566 }, { x: 1118.5, y: 735.5 }, { x: 1127.9, y: 739.3 }, { x: 1049.6, y: 760.8 }, { x: 926.9, y: 710.4 }, { x: 991.5, y: 691.9 }, { x: 991.5, y: 635.2 }],
    battery: [{ x: 136, y: 523.5 }, { x: 167.7, y: 535.1 }, { x: 197.7, y: 528.5 }, { x: 532, y: 654.7 }, { x: 546.6, y: 660.2 }, { x: 653.6, y: 700.6 }, { x: 702.4, y: 719 }, { x: 744.2, y: 734.8 }, { x: 775.1, y: 746.5 }, { x: 842.7, y: 727.2 }, { x: 985.5, y: 686.5 }, { x: 985.5, y: 632.8 }],
    grid: [{ x: 1259, y: 228.5 }, { x: 970.8, y: 290.5 }, { x: 970.8, y: 470 }, { x: 936.7, y: 478.1 }, { x: 1109.5, y: 561.6 }, { x: 1109.5, y: 738.5 }, { x: 1049.9, y: 754.8 }, { x: 943.8, y: 711.4 }, { x: 998.5, y: 695.7 }, { x: 998.5, y: 638 }],
    home: [{ x: 978.5, y: 630 }, { x: 978.5, y: 644 }, { x: 954.5, y: 635.2 }, { x: 954.5, y: 535.5 }, { x: 931.5, y: 528.2 }, { x: 784, y: 564 }, { x: 784, y: 594.5 }],
  },
  // The battery runs straight on from the patio corner to the lower step and is out of sight only where it passes
  // behind a surveyed obstacle: the lower-left bed, the raised bed's corner and path light PL6, the front bed and path
  // light PL7, and the tiered planters (no drawn route gets past them). Everything in between is drawn, the terrace
  // and step paving included.
  buried: { battery: [[3, 4], [5, 6], [7, 9]] },
  // Cards (2026-10-26): Solar in the open sky above the main roof, Grid in the sky left of the pylon, Battery on the
  // blurred foreground shrub, Home on the road below the driveway entrance. Phones (k >= compactFrom) put the two
  // sky cards side by side and pin Battery and Home to the canvas corners' least-intrusive fits.
  cards: {
    solar: { at: { x: 760, y: 10 }, align: "top-right" },
    grid: { at: { x: 1164.5, y: 10 }, align: "top-right" },
    battery: { at: { x: 381, y: 1076 }, align: "bottom-right" },
    home: { at: { x: 1040, y: 928 }, align: "top-left" },
  },
  cardsCompact: {
    solar: { at: { x: 757, y: 10 }, align: "top-right" },
    grid: { at: { x: 1248, y: 10 }, align: "top-right" },
    battery: { at: { x: 10, y: 1076 }, align: "bottom-left" },
    home: { at: { x: 1008, y: 926 }, align: "top-left" },
  },
  compactFrom: 2.8,
  // Connectors: a vertical drop or rise from the card, one perspective right angle, then onto the equipment
  // (Array 1 and Array 2 panel cells, the pylon's top light, the battery cabinet's face, the inverter body). Array 2's
  // drop runs down the white gable wall, not the dark glazing frame; the battery's and the house's are pinned to one
  // line at every card size (up the cabinet's front corner, and up the wall strip between the corner downpipe and the
  // garage door).
  info: {
    solarInfoMain: { card: "solar", port: { side: "bottom", at: 0.55 }, elbow: ["Z", "X"], points: [{ x: 625, y: 226 }, { x: 625, y: 296 }] },
    solarInfoGarage: { card: "solar", port: { side: "bottom", at: 0.925 }, elbow: ["Z", "X"], points: [{ x: 1045, y: 264.5 }, { x: 1045, y: 490 }] },
    batteryInfo: { card: "battery", port: { side: "top", at: 0.2875, x: 127.5 }, points: [{ x: 127.5, y: 502 }] },
    gridInfo: { card: "grid", port: { side: "right", at: 0.2725 }, elbow: ["X", "Z"], points: [{ x: 1319.5, y: 92.8 }] },
    homeInfo: { card: "home", port: { side: "top", at: 0.4, x: 1131 }, elbow: ["Z", "X"], points: [{ x: 1000, y: 571 }] },
  },
  bend: {},
  traces: [
    { label: "W6 painted service wire (pylon LL insulator -> chimney right edge), Y", points: poly(1259, 228.5, 1239, 233.3, 1215, 240.7, 1191, 247.7, 1167, 254.4, 1143, 260.6, 1127, 263.7, 1103, 267, 1079, 271.9, 1055, 275.6, 1031, 278.1, 1007, 282.2, 991, 285, 971, 286) },
    { label: "W8 painted wire into the chimney (the grid lands at its contact)", points: poly(1071, 280.4, 1047, 283.8, 1023, 286.2, 999, 288.2, 971, 291) },
    { label: "pylon LL insulator, Z", points: poly(1259, 199.5, 1259, 229) },
    { label: "chimney right (back) edge, Z", points: poly(970.6, 281, 970.6, 468.5) },
    { label: "chimney foot on garage roof, Y", points: poly(970.6, 468.5, 935.6, 475.5) },
    { label: "chimney left edge / gable-glazing frame junction, Z", points: poly(924, 312.3, 924, 485.4) },
    { label: "garage front-left verge tile edge, S_garage", points: poly(930, 475.5, 1108, 560) },
    { label: "garage front-left fascia bottom = top of inverter wall, S_garage", points: poly(924.4, 486.5, 1114.9, 577.6) },
    { label: "garage front corner, Z", points: poly(1109.5, 575.5, 1109.5, 738.5) },
    { label: "door-wall eave tile edge / gutter, Y", points: poly(1119.5, 565.4, 1349, 506.8) },
    { label: "corner downpipe (gooseneck + vertical), Z", points: poly(1130.3, 571.5, 1127.5, 580.8, 1119.5, 588, 1118.5, 592, 1118.5, 733, 1121.5, 736) },
    { label: "ridge-cap underside shadow line, X (Array 1 route to the chimney)", points: poly(815, 287.5, 924, 312.3) },
    { label: "Array 1 right frame edge, S_main", points: poly(809.7, 306.8, 688, 446) },
    { label: "Array 2 frame L-F-R-B", points: poly(987.2, 481.9, 1114.7, 544.6, 1298.9, 499.6, 1170.8, 445, 987.2, 481.9) },
    { label: "inverter wall plinth bottom / paving, X", points: poly(968, 682.5, 1109.5, 738.5) },
    { label: "door wall base (corner to door jamb), Y", points: poly(1109.5, 738.5, 1133, 730.8) },
    { label: "landing riser-1 foot Y3", points: poly(834, 719.9, 962, 682.1) },
    { label: "lower-step nosing Y4 (battery C2 track)", points: poly(841, 728.3, 972, 690.3) },
    { label: "step foot / gravel junction Y5", points: poly(841, 739.4, 975, 699.1) },
    { label: "pot + EV loop front clearance (inner X track reference)", points: poly(1009, 724, 1025, 731, 1054, 739, 1068, 738.5, 1078, 735) },
    { label: "inverter underside front edge = connection bar, X", points: poly(958, 621.8, 1010.5, 642.8) },
    { label: "painted cable C1", points: poly(978.5, 639, 978.5, 680, 977, 683, 974, 684.2, 967, 682.5) },
    { label: "painted cable C2", points: poly(985.5, 642, 985.5, 687, 984, 690.5, 980, 692.5, 975, 693.5) },
    { label: "painted cable C3", points: poly(991.5, 645, 991.5, 691, 989.5, 694.5, 984, 696, 977, 696.5) },
    { label: "painted cable C4", points: poly(998.5, 648, 998.5, 693, 996.5, 697.5, 990, 699, 978, 699) },
    { label: "painted cable C5", points: poly(1007, 650, 1007, 692, 1005, 697.5, 1000, 700.5, 991, 702.5, 979, 701.5) },
    { label: "inverter front face, left edge, Z (the home feed runs up beside it)", points: poly(957.5, 534, 957.5, 622) },
    { label: "internal corner, garage wall / house wall, Z (the home feed turns onto the house wall)", points: poly(931.5, 490, 931.5, 618) },
    { label: "upper window bottom edge, Y (top of the home feed's wall band)", points: poly(825, 538, 918, 515) },
    { label: "dining glazing top edge, Y (bottom of the home feed's wall band)", points: poly(795, 577.5, 916, 547.5) },
    { label: "wall light left of the dining glazing (the home feed ends on it)", points: poly(784, 595.5, 784, 609.5) },
    { label: "battery cabinet front-base ground line, Y (battery exit)", points: poly(119.5, 527, 203.5, 509) },
    { label: "rear path / lawn edge, Y (battery lawn turn)", points: poly(100, 549.5, 320, 502.5) },
    { label: "patio slab front riser foot, X (battery, to the patio corner)", points: poly(316, 573.5, 490, 638.8) },
    { label: "tiered planter box A right face (the battery comes out from behind it)", points: poly(842, 716, 842, 745) },
  ],
  obstacles: [
    { label: "lawn:flowerbed_lower_left", points: poly(47, 568, 55, 575, 82, 577, 112, 582, 130, 595, 150, 602, 175, 602, 200, 612, 250, 625, 265, 620, 290, 627.5, 315, 637.5, 340, 655, 365, 667.5, 385, 662.5, 415, 662.5, 440, 652.5, 457.5, 640, 470, 636, 490, 644, 503, 646, 512, 650, 518, 662, 532, 677, 525, 684, 334, 734.6, 325, 745, 245, 721, 145, 686, 100, 677, 67, 660, 33, 647, 0, 640, 0, 575, 12, 572, 28, 563, 42, 562) },
    { label: "foreground:hedge_front_row", points: poly(88, 668, 125, 683, 250, 722, 300, 747, 350, 757, 450, 787, 500, 804, 550, 818, 600, 835, 650, 855, 690, 866, 698, 880, 692, 935, 690, 992, 88, 775) },
    { label: "foreground:car", points: poly(1188, 700, 1190, 672, 1197, 660, 1215, 652, 1240, 645, 1300, 632, 1330, 630, 1360, 634, 1395, 645, 1420, 662, 1440, 680, 1448, 690, 1448, 763, 1430, 768, 1360, 780, 1340, 782, 1320, 780, 1305, 762, 1268, 752, 1235, 735, 1215, 730, 1197, 728, 1190, 715) },
    { label: "foreground:bedB_front_raised_bed_planting", points: poly(694, 862, 720, 856, 760, 850, 790, 856, 800, 866, 962, 820, 980, 840, 1015, 888, 706, 970, 692, 962, 690, 935, 692, 880) },
    { label: "front:flowerbed_front", points: poly(605, 750, 612, 720, 626, 700, 655, 701, 690, 698, 706, 727, 782, 760, 810, 752, 842, 756, 860, 766, 900, 768, 928, 790, 928, 800, 721, 800) },
    { label: "lawn:planting_bed_lower_right", points: poly(604, 752, 622, 712, 640, 704, 660, 702, 680, 705, 700, 722, 712, 730, 790, 761.5, 800, 775, 800, 838, 604, 754.8) },
    { label: "foreground:bedA_rear_bed_planting", points: poly(605, 748, 612, 712, 650, 710, 705, 725, 750, 742, 790, 760, 830, 768, 870, 772, 910, 782, 966, 800, 966, 806, 800, 852, 785, 852, 605, 752) },
    { label: "garage:Left pot + plant on top step", points: poly(906, 628, 912, 619, 922, 613, 935, 612, 946, 616, 953, 624, 952, 633, 945, 640, 945, 666, 936, 671, 915, 668, 914, 642, 907, 637) },
    { label: "garage:EV charger cable drop + ground loop", points: poly(1079, 679, 1085, 679, 1086, 720, 1084, 729, 1078, 735, 1068, 738.5, 1054, 739, 1046, 736.5, 1040.5, 731, 1041, 726, 1078, 726) },
    { label: "lawn:sofa", points: poly(389, 549, 394, 543, 430, 535, 472, 528, 540, 550, 548, 557, 525, 587, 470, 568, 440, 576, 415, 587, 390, 578) },
    { label: "lawn:hedge_lower_left", points: poly(0, 640, 33, 647, 67, 660, 100, 677, 267, 728, 345, 750, 362, 760, 0, 760) },
    { label: "lawn:planting_house_corner", points: poly(355, 515, 360, 500, 378, 491, 437, 479, 445, 485, 447, 530, 430, 532, 400, 540, 388, 548, 383, 556, 360, 548, 356, 535) },
    { label: "foreground:ev_charger_and_cable", points: poly(1072, 634, 1096, 634, 1096, 680, 1087, 684, 1087, 733, 1078, 739, 1045, 739, 1040, 731, 1048, 724, 1078, 726, 1078, 684, 1072, 680) },
    { label: "front:tiered_planters", points: poly(746, 700, 760, 692, 775, 700, 815, 695, 838, 712, 842, 722, 841, 748, 800, 750, 752, 750, 745, 735, 748, 715) },
    { label: "garage:Large pot + plant below-right of inverter", points: poly(1008, 690, 1011, 681, 1019, 674, 1030, 670, 1041, 672, 1050, 680, 1053, 690, 1051, 699, 1051, 725, 1025, 731, 1009, 724) },
    { label: "garage:Shrubs / trees right of and behind garage", points: poly(1339.5, 620.5, 1339.5, 521, 1356, 509, 1349, 505, 1300, 486, 1250, 462, 1200, 446, 1172, 435, 1165, 420, 1448, 420, 1448, 652) },
    { label: "lawn:shrub_left_of_cabinet", points: poly(0, 458, 20, 452, 38, 468, 52, 490, 70, 530, 70, 547, 28, 563, 12, 572, 0, 575) },
    { label: "front:plant_pot_porch_right", points: poly(660, 640, 668, 612, 690, 605, 712, 615, 726, 632, 712, 655, 703, 660, 703, 697, 672, 697, 671, 662, 658, 655) },
    { label: "front:plant_pots_by_downpipe", points: poly(702, 672, 712, 652, 732, 646, 752, 660, 758, 680, 752, 690, 750, 715, 718, 715, 717, 707, 703, 707) },
    { label: "garage:EV charger body", points: poly(1072, 640, 1074, 636, 1083, 634.5, 1093, 635, 1096, 638, 1096, 674, 1093, 679, 1076, 679, 1072, 675) },
    { label: "garage:Garage door", points: poly(1133.4, 596.3, 1313.7, 547, 1313, 628, 1290, 636, 1247, 641, 1215, 648, 1199, 657, 1192, 668, 1190, 702.3, 1134, 720.1) },
    { label: "garage:Raised flowerbed with planting", points: poly(840, 760, 900, 768, 924, 776, 944, 812, 967.5, 817.5, 967.5, 845, 985, 860, 995, 900, 840, 900) },
    { label: "front:plant_pot_under_dining", points: poly(775, 668, 783, 650, 800, 645, 820, 652, 827, 668, 816, 682, 815, 708, 788, 708, 787, 684) },
    { label: "garage:Path light 1", points: poly(929.5, 777, 935, 774.5, 940.5, 777, 940.5, 811, 944, 812, 944, 817.5, 924, 817.5, 924, 812, 929.5, 811) },
    { label: "lawn:rear_fence_bed", points: poly(204, 410, 225, 380, 440, 380, 440, 461, 320, 483, 318, 486.8, 205, 510.1) },
    { label: "lawn:pot_P3_conifer_by_house_corner", points: poly(380, 450, 385, 420, 398, 385, 410, 379, 425, 395, 430, 430, 428, 452, 415, 466, 396, 466) },
    { label: "lawn:pot_P4_patio", points: poly(311, 545, 318, 528, 335, 518, 352, 522, 360, 535, 356, 551, 354, 573, 328, 573, 325, 551) },
    { label: "lawn:pot_P6_by_porch", points: poly(515, 590, 522, 575, 540, 570, 558, 580, 560, 600, 547, 603, 546, 627, 523, 628, 521, 602) },
    { label: "lawn:pot_P7_by_porch", points: poly(543, 612, 548, 598, 560, 592, 575, 600, 577, 615, 573, 616, 573, 640, 549, 641, 547, 616) },
    { label: "front:porch_entrance_glazing", points: poly(597.5, 506, 617, 508, 664, 539, 665, 674, 597.5, 648) },
    { label: "garage:Small plant beside step", points: poly(949, 663, 950, 655, 954, 650, 959, 650, 963, 655, 963, 663, 960, 670, 951, 670) },
    { label: "lawn:pot_P2_right_of_cabinet", points: poly(205, 470, 212, 455, 228, 452, 245, 460, 244, 483, 241, 505, 211, 506) },
    { label: "lawn:pot_P5_patio", points: poly(357, 530, 365, 518, 380, 520, 386, 535, 381, 566, 361, 567) },
    { label: "roof:skylight", points: poly(790, 381.5, 825.5, 388.5, 776, 456.5, 740, 442.5) },
    { label: "roof:gable_glazing_upper", points: poly(824.5, 462.6, 915, 347.5, 915, 517, 824.5, 535.5) },
    { label: "roof:right_gable_glazing", points: poly(971, 332.5, 1014.5, 364.5, 1014.5, 460, 971, 468) },
    { label: "front:raised_bed_left", points: poly(520, 653, 530, 655, 545, 680, 561, 679, 561, 703, 520, 713) },
    { label: "lawn:pot_P1_left_of_cabinet", points: poly(74, 500, 82, 487, 98, 484, 112, 490, 112, 541, 80, 541) },
    { label: "foreground:hedge_left_end_top_corner", points: poly(0, 640, 20, 640, 32, 646, 30, 660, 20, 676, 0, 679) },
    { label: "front:dining_glazing", points: poly(795, 577.5, 916, 547.5, 916, 659.5, 795, 694) },
    { label: "front:bollard_left", points: poly(533, 642, 545, 642, 546, 670, 549, 679, 531, 680, 533, 670) },
    { label: "front:bollard_mid", points: poly(688, 686, 698, 686, 698, 712, 700, 718, 686, 718, 688, 712) },
    { label: "front:bollard_steps", points: poly(829, 734, 838, 734, 838, 750, 840, 756, 827, 756, 829, 750) },
    { label: "lawn:coffee_table", points: poly(430.5, 576, 466, 571.5, 494, 583, 493, 600, 465, 606, 431, 594) },
    { label: "roof:wall_light_front_left", points: poly(452, 464, 456, 463.5, 459, 465, 459, 473, 451.5, 473) },
    { label: "roof:wall_light_gable_by_corner", points: poly(780.5, 597, 784, 595.5, 787.5, 597, 787.5, 608, 784, 609.5, 780.5, 608) },
    { label: "front:first_floor_window", points: poly(825, 464, 853, 420, 916, 420, 918, 515, 825, 538) },
    { label: "garage:Path light on right garden wall", points: poly(1394.5, 615, 1398, 612, 1402, 614, 1402.5, 637, 1395, 637) },
    { label: "garage:Path light 2", points: poly(983, 854, 988.5, 852, 994, 854, 995, 895, 982, 895) },
    { label: "foreground:path_light_PL_a", points: poly(135, 666, 146, 666, 146, 691, 135, 691) },
    { label: "foreground:path_light_PL_b", points: poly(325, 724, 335, 724, 335, 749, 325, 749) },
    { label: "foreground:path_light_PL_g", points: poly(693, 864, 704, 864, 704, 897, 693, 897) },
    { label: "foreground:path_light_PL_h", points: poly(756, 925, 770, 925, 770, 956, 756, 956) },
    { label: "front:porch_lamp_left", points: poly(583, 552, 591, 552, 591, 568, 583, 568) },
    { label: "front:porch_lamp_right", points: poly(671, 575, 679, 575, 679, 591, 671, 591) },
    { label: "front:mini_downlight", points: poly(733.5, 626, 739.5, 626, 739.5, 632.5, 733.5, 632.5) },
    { label: "garage:Patio glazing, right part", points: poly(880, 557.2, 915.5, 548.5, 915.5, 661, 880, 668) },
    { label: "garage:Upper window, right part", points: poly(880, 427, 914.5, 420, 914.5, 517, 880, 523.5) },
    { label: "lawn:path_light_PL1", points: poly(74, 522, 83, 522, 83, 550, 74, 550) },
    { label: "lawn:path_light_PL2", points: poly(245, 467, 252.5, 467, 252.5, 500, 245, 500) },
    { label: "lawn:path_light_PL3", points: poly(358, 448, 364.5, 448, 364.5, 474, 358, 474) },
    { label: "lawn:path_light_PL6", points: poly(533, 642, 543, 642, 543, 679, 533, 679) },
    { label: "lawn:path_light_PL7", points: poly(689, 686, 697.5, 686, 697.5, 717.5, 689, 717.5) },
    { label: "lawn:patio_glazing_approx", points: poly(477, 452, 575, 497, 575, 585, 477, 548) },
    { label: "lawn:porch_door", points: poly(602, 508, 641, 525, 641, 664, 605, 649) },
    { label: "lawn:porch_side_glazing", points: poly(641, 525, 665, 538, 665, 674, 641, 664) },
    { label: "lawn:white_wall_glazing_approx", points: poly(795, 568, 820, 560, 820, 678, 795, 688) },
  ],
  equipment: [
    { label: "Array 1", x: 478, y: 256, w: 334, h: 192 },
    { label: "Array 2", x: 985, y: 443, w: 316, h: 112 },
    { label: "Battery cabinet", x: 93, y: 393, w: 114, h: 134 },
    { label: "Inverter", x: 954, y: 526, w: 72, h: 124 },
    { label: "Pylon", x: 1252, y: 84, w: 136, h: 348 },
    { label: "Chimney", x: 905, y: 256, w: 72, h: 222 },
    { label: "EV charger", x: 1066, y: 626, w: 34, h: 60 },
    { label: "Car", x: 1183, y: 622, w: 265, h: 165 },
  ],
  nodes: {
    solarMain: ["array1_right_frame_outer_side_at_row_divider_junction", "ridge_cap_underside_above_array1_TR_corner", "ridge_end_at_chimney_left_edge (roof top-right corner)", "garage_fascia_bottom_left_end", "garage_fascia_bottom_at_garage_outer_end", "inverter_wall_base_beside_garage_corner", "ground_turn_onto_inner_X_track", "bundle_turn_into_C5_track", "C5_riser_base", "C5_gland_on_underside_edge"],
    solarGarage: ["array2_frame_R_corner", "eave_gutter_below_R", "eave_gutter_at_downpipe_head_roof_front_corner", "downpipe_foot", "downpipe_shoe_kick", "ground_turn_onto_outer_X_track", "bundle_turn_into_C3_track_at_step_foot", "C3_riser_base", "C3_gland_on_underside_edge"],
    battery: ["cabinet_exit_front_base_below_status_strip", "rear_path_lawn_edge_turn", "patio_riser_foot_line_on_lawn_edge", "behind bollard_left, path_light_PL6 (hidden from here)", "open paving (drawn from here)", "behind bollard_mid, flowerbed_front, path_light_PL7, planting_bed_lower_right (hidden from here)", "open paving (drawn from here)", "behind tiered_planters (hidden from here)", "corner under the tiered planters (hidden)", "lower-step nosing past planter box A (drawn to the inverter)", "C2_riser_base", "C2_gland_on_underside_edge"],
    grid: ["pylon_LL_insulator_bottom (W6 attachment)", "chimney_right_edge_below_cap (W8 contact; W6 contact 4.5 px above)", "chimney_right_edge_foot_on_garage_roof", "chimney_front_foot_on_verge_tile_edge", "verge_tile_edge_above_garage_front_corner", "garage_front_corner_base", "ground_turn_onto_middle_X_track", "bundle_turn_into_C4_track_at_step_foot", "C4_riser_base", "C4_gland_on_underside_edge"],
    home: ["C1_gland_on_underside_edge", "C1_drop_below_gland", "turn_under_inverter_bottom_left_corner", "inverter_left_side_at_top (turn into the corner)", "internal_corner_garage_wall_house_wall", "house_wall_band_above_wall_light", "wall_light_top (home end)"],
  },
};

const finitePt = (p: unknown): p is Pt => !!p && Number.isFinite((p as Pt).x) && Number.isFinite((p as Pt).y);
const ptList = (v: unknown, min: number): Pt[] | null => (Array.isArray(v) && v.length >= min && v.every(finitePt) ? v.map((p) => ({ x: p.x, y: p.y })) : null);
const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
/** Own keys only, so inherited names (`toString`, `__proto__`) never pass as a card, route, anchor or axis. */
const own = (o: object, k: unknown): boolean => typeof k === "string" && Object.prototype.hasOwnProperty.call(o, k);
const ALIGNS: readonly CardAlign[] = ["top-left", "top-right", "bottom-left", "bottom-right", "top-center", "bottom-center"];
const SIDES: ReadonlyArray<InfoLink["port"]["side"]> = ["top", "bottom", "left", "right"];
/** A replacement list of labelled polylines (traces, obstacles): every entry must have a label and enough points. */
const labelledList = (v: unknown, min: number): Array<{ label: string; points: Pt[] }> | null => {
  if (!Array.isArray(v)) return null;
  const out: Array<{ label: string; points: Pt[] }> = [];
  for (const e of v) {
    const points = isObject(e) && typeof e.label === "string" ? ptList(e.points, min) : null;
    if (!points) return null;
    out.push({ label: (e as { label: string }).label, points });
  }
  return out;
};

/** Merges a configuration override over the defaults. Lists replace; points, placements and links merge per key; malformed entries are ignored. */
export function mergeRouting(base: RoutingData, override: RoutingOverride | undefined): RoutingData {
  if (!isObject(override)) return base;
  const anchors = { ...base.anchors } as Record<AnchorKey, AnchorPt>;
  for (const [k, v] of Object.entries(isObject(override.anchors) ? override.anchors : {}) as Array<[AnchorKey, unknown]>) {
    if (!isObject(v) || !own(anchors, k)) continue;
    anchors[k] = { x: finite(v.x) ? v.x : anchors[k].x, y: finite(v.y) ? v.y : anchors[k].y, label: typeof v.label === "string" ? v.label : anchors[k].label };
  }
  const perspective = { ...base.perspective };
  for (const [k, v] of Object.entries(isObject(override.perspective) ? override.perspective : {}) as Array<[string, unknown]>) {
    if (k === "__proto__") continue;
    const m = v as { vp?: unknown; field?: unknown; size?: unknown };
    if (m && finitePt(m.vp)) perspective[k] = { vp: { x: m.vp.x, y: m.vp.y } };
    else if (m && Array.isArray(m.field) && m.field.length === 6 && m.field.every(Number.isFinite) && Array.isArray(m.size) && m.size.length === 2 && m.size.every((n) => Number.isFinite(n) && n > 0))
      perspective[k] = { field: [...(m.field as number[])], size: [m.size[0] as number, m.size[1] as number] };
  }
  const power = { ...base.power } as Record<PowerRouteKey, Pt[]>;
  for (const [k, v] of Object.entries(isObject(override.power) ? override.power : {}) as Array<[PowerRouteKey, unknown]>) {
    const list = ptList(v, 2);
    if (list && own(power, k)) power[k] = list;
  }
  // A replaced route is drawn whole unless the override buries part of it again.
  const buried = { ...base.buried };
  for (const k of Object.keys(buried) as PowerRouteKey[]) if (power[k] !== base.power[k]) delete buried[k];
  const span = (s: unknown): s is [number, number] => Array.isArray(s) && s.length === 2 && s.every(Number.isInteger) && s[0] >= 0 && s[0] < s[1];
  for (const [k, v] of Object.entries(isObject(override.buried) ? override.buried : {}) as Array<[PowerRouteKey, unknown]>) {
    if (Array.isArray(v) && own(power, k)) buried[k] = v.filter(span).map(([a, b]) => [a, b] as [number, number]);
  }
  const placements = (into: Partial<Record<CardKey, CardPlacement>>, from: unknown) => {
    const out = { ...into };
    for (const [k, v] of Object.entries(isObject(from) ? from : {}) as Array<[CardKey, unknown]>) {
      if (!isObject(v) || !own(base.cards, k)) continue;
      const prev = out[k] ?? base.cards[k];
      out[k] = { at: finitePt(v.at) ? { x: v.at.x, y: v.at.y } : prev.at, align: ALIGNS.includes(v.align as CardAlign) ? (v.align as CardAlign) : prev.align };
    }
    return out;
  };
  const info = { ...base.info } as Record<InfoRouteKey, InfoLink>;
  for (const [k, v] of Object.entries(isObject(override.info) ? override.info : {}) as Array<[InfoRouteKey, unknown]>) {
    if (!isObject(v) || !own(info, k)) continue;
    const prev = info[k];
    const port = { ...prev.port };
    if (isObject(v.port)) {
      const side = SIDES.includes(v.port.side as InfoLink["port"]["side"]) ? (v.port.side as InfoLink["port"]["side"]) : prev.port.side;
      const moved = side !== prev.port.side || finite(v.port.at);
      port.side = side;
      if (finite(v.port.at)) port.at = v.port.at;
      // A new side or fraction replaces an inherited pin; `x: null` / `y: null` unpins explicitly.
      for (const axis of ["x", "y"] as const) {
        if (finite(v.port[axis])) port[axis] = v.port[axis] as number;
        else if (v.port[axis] === null || (moved && v.port[axis] === undefined)) delete port[axis];
      }
    }
    // `elbow: null` makes the connector straight; an elbow must name two axes of the perspective model.
    const elbow = Array.isArray(v.elbow) && v.elbow.length === 2 && v.elbow.every((a) => own(perspective, a)) && v.elbow[0] !== v.elbow[1] ? ([v.elbow[0], v.elbow[1]] as [string, string]) : null;
    const keepElbow = v.elbow === null ? undefined : (elbow ?? prev.elbow);
    info[k] = {
      card: own(base.cards, v.card) ? (v.card as CardKey) : prev.card,
      port,
      ...(keepElbow ? { elbow: keepElbow } : {}),
      points: v.points === undefined ? prev.points : ptList(v.points, 1) ?? prev.points,
    };
  }
  const bend = { ...base.bend };
  for (const [k, v] of Object.entries(isObject(override.bend) ? override.bend : {}) as Array<[RouteKey, unknown]>) if ((own(base.power, k) || own(base.info, k)) && finite(v) && v >= 0) bend[k] = v;
  const nodes = { ...base.nodes } as Record<PowerRouteKey, string[]>;
  for (const [k, v] of Object.entries(isObject(override.nodes) ? override.nodes : {}) as Array<[PowerRouteKey, unknown]>) {
    if (own(nodes, k) && Array.isArray(v) && v.every((n) => typeof n === "string")) nodes[k] = [...v];
  }
  const u = isObject(override.underside) ? override.underside : {};
  const equipment = Array.isArray(override.equipment) && override.equipment.every((e) => isObject(e) && typeof e.label === "string" && ["x", "y", "w", "h"].every((f) => finite(e[f])))
    ? override.equipment.map((e) => ({ label: e.label, x: e.x, y: e.y, w: e.w, h: e.h }))
    : base.equipment;
  return {
    canvas: base.canvas,
    perspective,
    anchors,
    underside: { from: finitePt(u.from) ? { x: u.from.x, y: u.from.y } : base.underside.from, to: finitePt(u.to) ? { x: u.to.x, y: u.to.y } : base.underside.to },
    power,
    buried,
    cards: placements(base.cards, override.cards) as Record<CardKey, CardPlacement>,
    cardsCompact: placements(base.cardsCompact, override.cardsCompact),
    compactFrom: finite(override.compactFrom) ? override.compactFrom : base.compactFrom,
    info,
    bend,
    traces: labelledList(override.traces, 2) ?? base.traces,
    obstacles: labelledList(override.obstacles, 3) ?? base.obstacles,
    equipment,
    nodes,
  };
}
