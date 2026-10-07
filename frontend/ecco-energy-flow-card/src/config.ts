// Configuration schema for the ECCO Energy Flow Card.
//
// Deliberately entity-id-free and brand-free: nothing here assumes a Deye/
// SmartDeye/ECCO installation. Every node and every "today" total is
// independently optional so the card degrades gracefully for a user who
// does not expose every counter this schema supports.

/** Which raw sign convention a bidirectional power sensor uses. */
export type BatteryPowerSign = "charge_positive" | "discharge_positive";
export type GridPowerSign = "import_positive" | "export_positive";

export interface NodeCommonConfig {
  /** Overrides the built-in label (e.g. "Solar" -> "Roof Array"). */
  label?: string;
  /** Overrides the built-in mdi icon. */
  icon?: string;
}

export interface SolarNodeConfig extends NodeCommonConfig {
  /** Entity reporting current solar generation power. Assumed >= 0. */
  power?: string;
}

/**
 * `nodes.solar` accepts EITHER shape:
 *   - a single object (backwards compatible with the original one-array
 *     schema): `solar: { power: sensor.x }`
 *   - an array, one entry per independent solar source/array/MPPT:
 *     `solar: [{ label: "Array 1", power: sensor.a }, { label: "Array 2", power: sensor.b }]`
 * 1..N sources are supported - nothing assumes exactly one or exactly two.
 * See `normaliseSolarSources()` below, the single place this polymorphism
 * is resolved into a plain array for the rest of the card to consume.
 */
export type SolarSourcesConfig = SolarNodeConfig | SolarNodeConfig[];

export interface InverterNodeConfig extends NodeCommonConfig {
  /**
   * Entity reporting the inverter's own current throughput power.
   * This is the one entity that makes the centre node meaningful - without
   * it the card still renders (solar/home/battery/grid can flow through an
   * unlabelled centre point), but the inverter will not show a live figure.
   */
  power?: string;
  /** Optional short operating-state text (e.g. "Normal", "Standby", "Fault"). */
  state?: string;
  /** Optional free-text status entity (distinct from `state` - e.g. a fuller status string). */
  status?: string;
}

export interface HomeNodeConfig extends NodeCommonConfig {
  /** Entity reporting current household/load consumption power. Assumed >= 0. */
  power?: string;
}

export interface BatteryNodeConfig extends NodeCommonConfig {
  /** Entity reporting current battery power (signed, bidirectional). */
  power?: string;
  /** Entity reporting battery state of charge, 0-100. */
  soc?: string;
  /**
   * Which sign this specific installation's `power` entity uses.
   * Default: "charge_positive" (positive = energy flowing INTO the
   * battery). Deye/ECCO-family inverters commonly report the opposite
   * ("discharge_positive") - set this explicitly rather than relying on
   * the default for those.
   */
  power_sign?: BatteryPowerSign;
  /**
   * Optional entity reporting the time until the battery reaches its
   * reserve, as a duration (minutes by default; a `unit_of_measurement` of
   * s/min/h/d is honoured, any other unit shows "--"). Shown as the battery
   * node's tooltip. The card only displays this entity's own value - it
   * never calculates a reserve level or an ETA. Inert when not configured.
   */
  time_to_reserve?: string;
}

export interface GridNodeConfig extends NodeCommonConfig {
  /** Entity reporting current grid power (signed, bidirectional). */
  power?: string;
  /**
   * Which sign this specific installation's `power` entity uses.
   * Default: "import_positive" (positive = energy flowing FROM the grid).
   */
  power_sign?: GridPowerSign;
}

export interface GeneratorNodeConfig extends NodeCommonConfig {
  /** Entity reporting current generator/AUX output power. Presence of this key enables the node. Assumed >= 0. */
  power?: string;
}

export interface NodesConfig {
  solar?: SolarSourcesConfig;
  /**
   * Optional entity reporting COMBINED solar generation across every
   * source. When there are 2+ solar sources, the card renders a small
   * "Solar Total" combiner node between the array row and the inverter -
   * every array feeds into it, and exactly one line then runs from it to
   * the inverter (never one line per array all the way to the inverter -
   * that would double-count the generation visually). If `solar_total` is
   * configured, its live value is shown on that node AUTHORITATIVELY
   * (used as-is, not recalculated). If it is NOT configured, the combiner
   * node instead shows the sum of the configured array power readings,
   * derived client-side - still never fabricated from nothing, always a
   * real sum of real configured entities. With exactly one solar source,
   * no combiner node is created at all (there is nothing to combine) -
   * this field is simply unused in that case.
   */
  solar_total?: string;
  inverter?: InverterNodeConfig;
  home?: HomeNodeConfig;
  battery?: BatteryNodeConfig;
  grid?: GridNodeConfig;
  generator?: GeneratorNodeConfig;
}

/**
 * Resolves the `nodes.solar` polymorphism (single object OR array) into a
 * plain array, always - the single place the rest of the card needs to
 * reason about "one or more solar sources". `undefined`/missing `power`
 * entries are filtered out so a source with no entity configured never
 * becomes a rendered node with nothing to show.
 */
export function normaliseSolarSources(solar: SolarSourcesConfig | undefined): SolarNodeConfig[] {
  if (!solar) return [];
  const list = Array.isArray(solar) ? solar : [solar];
  return list.filter((source) => !!source && !!source.power);
}

/** Home Assistant's own "Today" energy counters - all independently optional. */
export interface TodayConfig {
  solar?: string;
  load?: string;
  import?: string;
  export?: string;
  battery_charge?: string;
  battery_discharge?: string;
}

/** Secondary inverter telemetry - never shown in the primary flow diagram. */
export interface InverterDetailsConfig {
  temperature?: string;
  ac_temperature?: string;
  dc_temperature?: string;
  /**
   * Entity reporting live grid voltage (e.g. L1 RMS volts). Independently
   * optional like every other field here. Unlike the rest of this
   * interface, this one is ALSO surfaced outside the collapsible details
   * panel: whichever of `grid_voltage`/`ac_temperature`/`dc_temperature`
   * are configured additionally render as a small always-visible compact
   * tile strip between the flow diagram and the "Today" totals (see
   * `_renderQuickMetrics()`) - the collapsible panel still shows the full
   * set of fields on this interface on demand, this is just a quick-glance
   * subset of the three most commonly wanted at-a-glance readings.
   */
  grid_voltage?: string;
  /** binary_sensor (or any entity whose state is 'on'/'off'/truthy) reporting grid connectivity. */
  grid_connected?: string;
  frequency?: string;
  /** Free-text operating/TOU mode entity. */
  mode?: string;
}

export interface FeaturesConfig {
  /**
   * Show a self-sufficiency % badge, computed as `1 - today.import /
   * today.load`. Auto-hidden if those aren't configured.
   *
   * CAVEAT, deliberately not "fixed" by inventing a different formula:
   * this simple calculation can be misleading on any installation with a
   * battery, because imported grid energy may have gone into charging the
   * battery rather than directly covering load - the naive ratio then
   * understates true self-sufficiency. It remains accurate for a
   * battery-less solar-only installation. Leave this off (the default)
   * for any battery-equipped site until a battery-aware formula is
   * designed; this field stays in the schema for that future work and for
   * installations where the simple formula is already correct.
   */
  self_sufficiency?: boolean;
  /** Show a solar-contribution % badge, computed from today.solar/today.load. Auto-hidden if those aren't configured. */
  solar_contribution?: boolean;
  /** Animate the flow lines. Automatically disabled when the browser/OS requests reduced motion. Default true. */
  animate_flow?: boolean;
  /** Render the "Today" strip in a tighter single-row layout. Default false (2-column grid). */
  compact_today?: boolean;
  /**
   * Show the collapsible "Inverter details" panel below the quick-metrics
   * strip. Default true (existing installs see no change). The
   * quick-metrics strip (see `_renderQuickMetrics()`) already shows all
   * five `InverterDetailsConfig` fields it supports whenever they're
   * configured, independently of this flag - set this to `false` only
   * once that makes the panel pure repetition for your own dashboard,
   * i.e. you don't rely on `temperature`/`mode`/`status` (the three
   * fields the panel can show that the quick-metrics strip cannot).
   */
  show_details_panel?: boolean;
}

export type PowerUnitMode = "auto" | "w" | "kw";

export interface FormatConfig {
  /** Decimal places for power values. Default 2 in kW, 0 in W (see format.ts). Explicit value overrides both. */
  precision?: number;
  /** Decimal places for the daily energy totals (kWh). Default 1. */
  energy_precision?: number;
  /** "auto" switches W/kW by magnitude (default). "w"/"kw" pins the unit. */
  power_unit?: PowerUnitMode;
}

export interface EccoEnergyFlowCardConfig {
  type: string;
  title?: string;
  nodes?: NodesConfig;
  today?: TodayConfig;
  inverter_details?: InverterDetailsConfig;
  features?: FeaturesConfig;
  format?: FormatConfig;
}

/**
 * The diagram's node kinds - deliberately a narrower type than
 * `keyof NodesConfig`. `solar_total` is the small PV-combiner node
 * rendered between the solar row and the inverter when there are 2+ solar
 * sources (see `NodesConfig.solar_total` and `_layout()`) - it is a real
 * diagram node like any other, just visually subtler than the inverter.
 */
export type DiagramNodeKind = "solar" | "solar_total" | "inverter" | "home" | "battery" | "grid" | "generator";

export const DEFAULT_LABELS: Record<DiagramNodeKind, string> = {
  solar: "Solar",
  solar_total: "Solar Total",
  inverter: "Inverter",
  home: "Home",
  battery: "Battery",
  grid: "Grid",
  generator: "Generator",
};

export const DEFAULT_ICONS: Record<DiagramNodeKind, string> = {
  solar: "mdi:solar-power",
  solar_total: "mdi:solar-power-variant-outline",
  inverter: "mdi:power-plug-outline",
  home: "mdi:home-lightning-bolt-outline",
  battery: "mdi:battery-high",
  grid: "mdi:transmission-tower",
  generator: "mdi:engine-outline",
};

/**
 * Normalises a raw battery power reading to this card's internal
 * convention: positive = discharging (energy flowing OUT of the battery
 * towards the inverter/home).
 */
export function normaliseBatteryPower(raw: number, sign: BatteryPowerSign | undefined): number {
  // Default convention: charge_positive (positive = charging).
  // Internal convention: discharge_positive. Flip unless the source is
  // already discharge_positive.
  return sign === "discharge_positive" ? raw : -raw;
}

/**
 * Normalises a raw grid power reading to this card's internal convention:
 * positive = importing (energy flowing FROM the grid towards the
 * inverter/home).
 */
export function normaliseGridPower(raw: number, sign: GridPowerSign | undefined): number {
  // Default convention: import_positive - already matches internal convention.
  return sign === "export_positive" ? -raw : raw;
}

// 2026-09-26 (Dump-to-Grid V1.1 investigation): minimum derived-balance
// magnitude before a native Home reading of exactly 0W is treated as the
// known-unreliable case rather than a genuine idle site - see
// resolveHomeW()'s own doc comment. Deliberately a much larger margin than
// ordinary telemetry jitter around a truly quiet site, so a real 0W never
// triggers the fallback.
export const HOME_FALLBACK_MIN_W = 150;

/**
 * Home/load power resolution (2026-09-26, Dump-to-Grid V1.1 investigation -
 * see docs/DUMP_TO_GRID_V1.md "Home-power fallback"). The native load-power
 * register is documented as unreliable in some inverter states: it can read
 * a real 0W while the site is clearly under load (the same register that
 * reads 0W "while the battery supplied ~1.1kW and the grid 2.8kW" per the
 * measured-power runaway guard's own evidence, and again during an active
 * Dump-to-Grid lease: PV 763W, battery 632W discharging, inverter AC out
 * 1.24kW, grid 1.81kW importing, native Home 0W).
 *
 * Fallback formula: home ~= inverter AC output + grid power (import
 * positive, export negative, this card's internal convention) - everything
 * the inverter put onto the AC bus plus whatever the grid contributed (or
 * minus whatever was exported) is what the site's load must have consumed.
 * Evidenced from two DIFFERENT moments, not one (2026-09-26 documentation
 * correction - the two figures below were never the same live sample):
 * during the Dump-to-Grid lease, while native Home read a known-unreliable
 * 0W, the formula gave inverter (1.24kW) + grid import (1.81kW) = 3.05kW.
 * Once the lease ended and PV/battery/grid had settled to a different,
 * unrelated state, native Home itself recovered and read 3.05kW. The
 * formula's own output during the unreliable window matching what native
 * later reported once trustworthy again is the cross-check that shows the
 * formula holds - not a same-instant coincidence.
 *
 * The native reading is preferred whenever it is credible: only a
 * missing/unavailable native value, or an exact 0W reading that the
 * balance clearly contradicts (above HOME_FALLBACK_MIN_W, well past
 * ordinary telemetry jitter), triggers the fallback - a genuine quiet site
 * (both native and derived near zero) is never overridden. Both inverterW
 * and gridW must themselves be available to derive anything; without them
 * this simply returns the native reading. When neither the native reading
 * nor the derived balance is available, Home is unknown and this returns
 * null (FE-0: displayed as "--", never as a fabricated 0W). Never
 * negative, regardless of source.
 */
export function resolveHomeW(nativeW: number | null, inverterW: number | null, gridW: number | null): number | null {
  const derived = inverterW !== null && gridW !== null ? Math.max(0, inverterW + gridW) : null;
  if (nativeW === null) {
    return derived;
  }
  if (nativeW === 0 && derived !== null && derived > HOME_FALLBACK_MIN_W) {
    return derived;
  }
  return Math.max(0, nativeW);
}
