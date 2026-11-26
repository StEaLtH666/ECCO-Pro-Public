// Configuration schema for the ECCO 3D Energy Flow card.
//
// The card is READ-ONLY: it reads entity states and opens Home Assistant's
// own more-info dialogue. It never calls a service, writes a setting or
// starts an action. Every section below is independently optional; a
// missing entity is shown as unknown ("--"), never as a plausible value.
//
// The power model (sign conventions, Home resolution, PV aggregation) is
// the one established by frontend/ecco-energy-flow-card (see
// src/core/power.ts, which mirrors that card's pure helpers and is held to
// behavioural parity by test/parity.test.ts).

import type { RoutingOverride } from "./scene/routing-v4.ts";

export type BatteryPowerSign = "charge_positive" | "discharge_positive";
export type GridPowerSign = "import_positive" | "export_positive";
/** How the artwork scene ties each information card to its equipment (scene.links). */
export type LinkStyle = "pulse" | "particles" | "off";

export interface SolarArrayConfig {
  /** Display label, e.g. "Array 1". */
  label?: string;
  /** Entity reporting this array's current power (W). Assumed >= 0. */
  power?: string;
}

export interface InverterConfig {
  /** Entity reporting the inverter's AC output power (W). */
  power?: string;
  /** Short operating-state text entity (e.g. "Normal"). */
  state?: string;
}

export interface HomeConfig {
  /** Entity reporting whole-house consumption (W). */
  power?: string;
}

export interface BatteryConfig {
  /** Entity reporting signed battery power (W). */
  power?: string;
  /** Entity reporting state of charge, 0-100. */
  soc?: string;
  /** Sign convention of `power`. Default charge_positive; Deye/ECCO use discharge_positive. */
  power_sign?: BatteryPowerSign;
  /**
   * FE-1: entity reporting the time until the battery reaches its reserve
   * (minutes, with the `status`/`summary`/`minutes_low`/`minutes_high`/
   * `beyond_horizon`/`solar_assisted` attributes ECCO's package emits).
   * The card shows that entity's own value; it never estimates one.
   */
  time_to_reserve?: string;
  /**
   * OPTIONAL and normally absent: an entity reporting the time until the
   * battery reaches its charge target. ECCO currently provides no such
   * entity, so the card shows "Not available" unless one is configured.
   * The card never derives this from SOC, power or capacity.
   */
  time_to_target?: string;
}

export interface GridConfig {
  /** Entity reporting signed grid power (W). */
  power?: string;
  /** Sign convention of `power`. Default import_positive. */
  power_sign?: GridPowerSign;
  /** binary_sensor reporting grid connectivity (on/off). */
  connected?: string;
  /** Live grid voltage entity (V). */
  voltage?: string;
  /** Live grid frequency entity (Hz). */
  frequency?: string;
}

export interface NodesConfig {
  /** One entry per PV array/MPPT. Any count; never double-counted. */
  solar?: SolarArrayConfig[] | SolarArrayConfig;
  /** Combined PV power entity, used authoritatively when configured. */
  solar_total?: string;
  inverter?: InverterConfig;
  home?: HomeConfig;
  battery?: BatteryConfig;
  grid?: GridConfig;
}

/** A manual session feature (Free Power or Dump to Grid). All entities are the EXISTING ECCO ones. */
export interface SessionFeatureConfig {
  /** binary_sensor: the lease is active (dongle truth). */
  active?: string;
  /** Text status sensor published by the dongle's transaction scripts. */
  status?: string;
  /** Dongle "Ends At" text sensor: "YYYY-MM-DD HH:MM:SS", "Inactive" or "Active - end time unavailable". */
  ends_at?: string;
  /** HA schedule status sensor: ACTIVE / STARTING / ARMED / FAILED / COMPLETED / IDLE. */
  schedule_status?: string;
  /** Dump to Grid only: the active lease's export power sensor (W, unavailable while inactive). */
  export_power?: string;
  /** Dump to Grid only: the active lease's stop SOC sensor (%). */
  stop_soc?: string;
}

export interface TouConfig {
  /** Six entities reporting each slot's start as minutes after midnight (sensor.ecco_tou_slot_N_start_minute). */
  slot_start_minutes?: string[];
  /** Six entities reporting each slot's target SOC (%). */
  slot_target_soc?: string[];
  /** Six entities reporting each slot's charge source text ("Grid" / "None" / ...). */
  slot_charge_source?: string[];
  /** Six entities reporting each slot's power limit (W). */
  slot_power?: string[];
  /** binary_sensor: the six-slot schedule is contiguous and valid. */
  valid?: string;
}

export interface ForecastConfig {
  /** Blended solar forecast for today (kWh). */
  today?: string;
  /** Blended solar forecast for the rest of today (kWh). */
  remaining?: string;
  /** Blended solar forecast for tomorrow (kWh). */
  tomorrow?: string;
}

export interface HealthConfig {
  /** Subsystem health sensors whose state is HEALTHY / DEGRADED / FAILED / UNKNOWN. */
  sensors?: string[];
  /** binary_sensors that are "on" when something needs attention. */
  attention?: string[];
}

export interface EccoConfig {
  /** binary_sensor: dongle telemetry polling online. Drives the "System online" chip and stale handling. */
  telemetry_online?: string;
  /** sun.sun, for the scene's day/night ambience only. */
  sun?: string;
  /** weather entity (e.g. weather.forecast_home); its condition picks the scene variant. Ambience only. */
  weather?: string;
  free_power?: SessionFeatureConfig;
  dump_to_grid?: SessionFeatureConfig;
  tou?: TouConfig;
  forecast?: ForecastConfig;
  health?: HealthConfig;
}

export interface TodayConfig {
  solar?: string;
  load?: string;
  import?: string;
  export?: string;
  battery_charge?: string;
  battery_discharge?: string;
}

export interface InverterDetailsConfig {
  temperature?: string;
  ac_temperature?: string;
  dc_temperature?: string;
  battery_temperature?: string;
}

export interface FeaturesConfig {
  /** Animate the power paths. Default true; always off under prefers-reduced-motion. */
  animate_flow?: boolean;
  /** Show the ECCO status grid. Default true. */
  show_status_panel?: boolean;
  /** Show the collapsible details panel. Default true. */
  show_details_panel?: boolean;
  /**
   * Show the always-visible diagnostics strip (grid voltage, frequency and
   * connection, AC and DC transformer temperatures). Default true; the
   * details panel then leaves those rows out.
   */
  show_diagnostics_strip?: boolean;
  /**
   * Show the always-visible Today strip (the six `today` energies and Solar
   * Share). Default true when any `today` entity is configured; the details
   * panel then leaves its Today group out.
   */
  show_today_strip?: boolean;
  /**
   * Seconds after the newest power reading's `last_updated` at which the
   * live values are flagged stale. Default 180 (the same horizon ECCO's
   * FE-1 runtime model uses). 0 disables the age check (the
   * telemetry_online signal still applies).
   */
  stale_after_s?: number;
}

export type PowerUnitMode = "auto" | "w" | "kw";

export interface FormatConfig {
  precision?: number;
  energy_precision?: number;
  power_unit?: PowerUnitMode;
}

/**
 * Scene artwork. When `image` is set, the card draws that fixed-perspective
 * house illustration (a local Home Assistant resource such as
 * `/local/ecco/ecco-house-night.png`; never a CDN) as the scene plate, with
 * the live pills and the animated power paths overlaid in the approved
 * composition. The artwork must not contain energy lines or figures of its
 * own: every value and every moving element comes from the overlays. Without
 * `image` the card falls back to its built-in vector scene.
 */
export interface SceneConfig {
  /**
   * Base path of the V4 scene pack (ten PNGs named as in the pack, e.g.
   * `/local/ecco/scenes/`). A local Home Assistant resource path, never a CDN.
   * The card picks the variant from the date, the sun and the weather entity
   * (see core/scenes.ts) and crossfades between variants.
   */
  pack?: string;
  /** Per-scene file-name or URL overrides, keyed by scene key. */
  scenes?: Partial<Record<string, string>>;
  /** Pin one scene key (demos, previews); the rules are then ignored. */
  force?: string;
  /** Crossfade duration in ms when the scene changes. Default 900. */
  crossfade_ms?: number;
  /**
   * Debug overlay (calibration aid): numbered route nodes, anchors, the
   * inverter underside, card boxes and ports, the surveyed obstacles, the
   * equipment boxes and the traced edges. Default false.
   */
  debug_anchors?: boolean;
  /**
   * How each information card is tied to its equipment: "pulse" (default: the fine dotted connector; while that flow
   * carries power its dots and the card's border breathe together, slowly and in step with every other card),
   * "particles" (the dotted connector with travelling particles) or "off" (no connector). Visual only. A YAML-mode
   * dashboard reads an unquoted `off` as false, which also means "off".
   */
  links?: LinkStyle | boolean;
  /**
   * Overrides for the routing data (the perspective model, anchors, the
   * inverter underside, the physical power routes and their buried stretches,
   * the information-card placements and their connectors, bend radii and the
   * debug traces): see
   * scene/routing-v4.ts. Lists replace, points and placements merge per key,
   * malformed entries are ignored. Visual only: nothing here can change a
   * value, a direction or a service.
   */
  routing?: RoutingOverride;
}

export interface EccoFlow3dCardConfig {
  type: string;
  title?: string;
  subtitle?: string;
  /** Brand word shown above the title (default "ECCO"; "" hides it). */
  brand?: string;
  scene?: SceneConfig;
  nodes?: NodesConfig;
  ecco?: EccoConfig;
  today?: TodayConfig;
  inverter_details?: InverterDetailsConfig;
  features?: FeaturesConfig;
  format?: FormatConfig;
}

/** Resolves `nodes.solar` (object or array) into a plain array of configured arrays. */
export function normaliseSolarSources(solar: SolarArrayConfig[] | SolarArrayConfig | undefined): SolarArrayConfig[] {
  if (!solar) return [];
  const list = Array.isArray(solar) ? solar : [solar];
  return list.filter((s) => !!s && !!s.power);
}

export const DEFAULT_STALE_AFTER_S = 180;

/**
 * The link style a `scene.links` value names: "pulse", "particles" or "off" in any case; false (YAML's unquoted off) is
 * "off"; missing or true is the default, "pulse". Anything else is null (validateConfig rejects it).
 */
export function linkStyleOf(v: unknown): LinkStyle | null {
  if (v === undefined || v === null || v === true) return "pulse";
  if (v === false) return "off";
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    if (s === "pulse" || s === "particles" || s === "off") return s;
  }
  return null;
}

export function validateConfig(config: unknown): asserts config is EccoFlow3dCardConfig {
  if (!config || typeof config !== "object") throw new Error("ecco-flow-3d-card: invalid configuration");
  const c = config as EccoFlow3dCardConfig;
  if (!c.nodes || typeof c.nodes !== "object" || Object.keys(c.nodes).length === 0) {
    throw new Error("ecco-flow-3d-card: at least one entry under `nodes:` is required");
  }
  const tou = c.ecco?.tou;
  for (const key of ["slot_start_minutes", "slot_target_soc", "slot_charge_source", "slot_power"] as const) {
    const list = tou?.[key];
    if (list !== undefined && (!Array.isArray(list) || list.length !== 6)) {
      throw new Error(`ecco-flow-3d-card: ecco.tou.${key} must list exactly six entities (slot 1 to slot 6)`);
    }
  }
  if (linkStyleOf(c.scene?.links) === null) throw new Error("ecco-flow-3d-card: scene.links must be pulse, particles or off");
}
