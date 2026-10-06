// Configuration schema for the ECCO Energy Actions Card.
//
// Entity-id-free and brand-free, same portability rule as the sibling
// ecco-energy-flow-card: nothing here assumes a Deye/ECCO installation, and
// no entity id is ever hard-coded in the component itself - every id the
// card reads or calls a service on comes from `free_power:`/`dump_to_grid:`
// below.
//
// Dump to Grid V1 (2026-09-26): now a real, interactive tile - see
// docs/DUMP_TO_GRID_V1.md. `dump_to_grid:` is optional; omitting it keeps
// the original static "Coming Soon" preview shell, so existing dashboards
// that predate this feature keep rendering unchanged.

export interface FreePowerEntities {
  /** binary_sensor - true while a Free Power override is currently active on the inverter. */
  active: string;
  /** binary_sensor - true while the firmware is mid-transaction (starting/ending/retrying). */
  operation_in_progress: string;
  /** binary_sensor - true while a durable pre-Free-Power snapshot is held, pending restore. */
  snapshot_valid: string;
  /** sensor (text) - the firmware's own literal status string. Always shown verbatim somewhere. */
  status: string;
  /** sensor (text) - "YYYY-MM-DD HH:MM:SS" local end time while active, or "Inactive"/other prose otherwise. */
  ends_at: string;
  /** sensor (diagnostic, optional) - lifetime counters, shown only as a subtle diagnostics row. */
  failures?: string;
  start_attempts?: string;
  start_successes?: string;
  restore_successes?: string;
  /** switch - the two-step safety arm. Toggling this NEVER writes the inverter by itself. */
  write_enable: string;
  /** number - staged charge power in W. Editing is staging only, always safe. */
  max_charge_power: string;
  /** number - staged duration in minutes. Editing is staging only, always safe. */
  duration: string;
  /** button - the ONLY thing that actually starts Free Power. Requires write_enable on (enforced firmware-side). */
  start: string;
  /** button - ends Free Power and restores the saved snapshot. Safe direction; does not require the arm. */
  end_restore: string;
}

/**
 * Maps to the existing, authoritative home-assistant/packages/
 * ecco_free_power_schedule.yaml package - this card never duplicates that
 * package's validation/automation logic, it only presents and drives its
 * entities. Entirely optional: omitting `schedule:` simply hides the
 * NOW/LATER selector and leaves the manual Free Power experience unchanged.
 */
export interface ScheduleEntities {
  /** input_boolean - true only once Home Assistant's own validation automation has confirmed the arm. */
  armed: string;
  /** input_datetime (has_date + has_time). */
  start: string;
  /** input_number - scheduled duration in minutes. */
  duration: string;
  /** input_number - scheduled charge power in watts. */
  power: string;
  /** input_text - the validation automation's own literal last outcome (ARMED/REJECTED/CANCELLED/...), always shown verbatim. */
  last_result: string;
  /** sensor - ACTIVE/ARMED/IDLE, with schedule attributes (see README) including effective_power_limit_w when exposed. */
  status: string;
  /** script - cancels a pending schedule. Never stops an already-active Free Power run. */
  cancel: string;
}

/**
 * Scheduled Dump to Grid helpers - exactly the entities
 * home-assistant/packages/ecco_dump_to_grid_schedule.yaml defines and
 * consumes. Same shape as ScheduleEntities plus one extra staged value,
 * `stop_soc`. The card only stages these helpers and arms/cancels via the
 * package's own input_boolean/script - it never arms the firmware
 * write_enable switch or presses START itself for a schedule.
 */
export interface DumpScheduleEntities {
  /** input_boolean - true only once the package's own arm-validation automation has left it ON. */
  armed: string;
  /** input_datetime (has_date + has_time). */
  start: string;
  /** input_number - scheduled duration in minutes. */
  duration: string;
  /** input_number - scheduled export power in watts. */
  power: string;
  /** input_number - scheduled Stop SOC in percent. */
  stop_soc: string;
  /** input_text - the package's literal last outcome (ARMED/REJECTED/STARTED OK/FAILED TO START/...). */
  last_result: string;
  /** sensor - ACTIVE/ARMED/IDLE. */
  status: string;
  /** script - cancels a pending schedule. Never stops an already-active Dump run. */
  cancel: string;
}

/**
 * Dump to Grid V1's own entity set - battery -> grid export sibling of
 * FreePowerEntities, with one extra staged value, `stop_soc`, that Free
 * Power has no analogue for. Optional `schedule` enables the same NOW/LATER
 * selector Free Power uses.
 */
export interface DumpToGridEntities {
  /** binary_sensor - true while a Dump-to-Grid override is currently active on the inverter. */
  active: string;
  /** binary_sensor - true while the firmware is mid-transaction (starting/ending/retrying). */
  operation_in_progress: string;
  /** binary_sensor - true while a durable pre-Dump snapshot is held, pending restore. */
  snapshot_valid: string;
  /** sensor (text) - the firmware's own literal status string. Always shown verbatim somewhere. */
  status: string;
  /** sensor (text) - "YYYY-MM-DD HH:MM:SS" local end time while active, or "Inactive"/other prose otherwise. */
  ends_at: string;
  /** sensor - the existing trusted battery SOC percentage. Read-only here; never written by this card. */
  battery_soc: string;
  /** sensor (diagnostic, optional) - lifetime counters, shown only as a subtle diagnostics row. */
  failures?: string;
  start_attempts?: string;
  start_successes?: string;
  restore_successes?: string;
  /** switch - the two-step safety arm. Toggling this NEVER writes the inverter by itself. */
  write_enable: string;
  /** number - staged export power in W. Editing is staging only, always safe. */
  export_power: string;
  /** number - staged Stop SOC floor in %. Editing is staging only, always safe. */
  stop_soc: string;
  /** number - staged duration in minutes. Editing is staging only, always safe. */
  duration: string;
  /** button - the ONLY thing that actually starts Dump to Grid. Requires write_enable on (enforced firmware-side). */
  start: string;
  /** button - ends Dump to Grid and restores the saved snapshot. Safe direction; does not require the arm. */
  end_restore: string;
  /** sensor (optional) - the Export Power LATCHED at START for the running lease (unknown when inactive). Shown instead of the staged number while ACTIVE. */
  active_export_power?: string;
  /** sensor (optional) - the Stop SOC LATCHED at START and enforced by the firmware watchdog (unknown when inactive). */
  active_stop_soc?: string;
  /** sensor (text, optional) - the first reason the current/last lease was ended. */
  last_end_reason?: string;
  /** switch (optional) - Dump to Grid Recovery Arm. Required by the firmware before either recovery button acts. */
  recovery_arm?: string;
  /** button (optional) - Force Restore Original (operator recovery; writes only the saved original snapshot). */
  recovery_force_restore?: string;
  /** button (optional) - Accept Current State (operator recovery; zero Modbus I/O, refused while Dump residue is live). */
  recovery_accept?: string;
  /** sensor (text, optional) - the firmware's recovery-state note. */
  recovery_state?: string;
  /** Optional - omit to hide the NOW/LATER scheduling UI for Dump to Grid. */
  schedule?: DumpScheduleEntities;
}

export interface EccoEnergyActionsCardConfig {
  type: string;
  /** Card/section title. Default "Energy Actions". */
  title?: string;
  free_power?: FreePowerEntities;
  /** Optional - omit to hide the NOW/LATER scheduling UI entirely. */
  schedule?: ScheduleEntities;
  /** Optional - omit to keep the static "Coming Soon" Dump to Grid preview shell. */
  dump_to_grid?: DumpToGridEntities;
}

export const DEFAULT_TITLE = "Energy Actions";
