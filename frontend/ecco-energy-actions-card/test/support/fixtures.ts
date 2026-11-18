// Shared fixtures: the example configuration's entity ids (all already public in examples/ecco-example.yaml) and state builders.
export const P = "ecco_clock_dongle";

export const BASE_CONFIG = {
  type: "custom:ecco-energy-actions-card",
  title: "Energy Actions",
  free_power: {
    active: `binary_sensor.${P}_free_power_active`,
    operation_in_progress: `binary_sensor.${P}_free_power_operation_in_progress`,
    snapshot_valid: `binary_sensor.${P}_free_power_snapshot_valid`,
    status: `sensor.${P}_free_power_status`,
    ends_at: `sensor.${P}_free_power_ends_at`,
    write_enable: `switch.${P}_free_power_write_enable`,
    max_charge_power: `number.${P}_free_power_max_charge_power`,
    duration: `number.${P}_free_power_duration`,
    start: `button.${P}_start_free_power_charge_now`,
    end_restore: `button.${P}_end_free_power_restore_now`,
  },
  schedule: {
    armed: "input_boolean.ecco_free_power_schedule_armed",
    start: "input_datetime.ecco_free_power_schedule_start",
    duration: "input_number.ecco_free_power_schedule_duration",
    power: "input_number.ecco_free_power_schedule_power",
    last_result: "input_text.ecco_free_power_schedule_last_result",
    status: "sensor.ecco_free_power_schedule_status",
    cancel: "script.ecco_free_power_cancel_schedule",
  },
  dump_to_grid: {
    active: `binary_sensor.${P}_dump_to_grid_active`,
    operation_in_progress: `binary_sensor.${P}_dump_to_grid_operation_in_progress`,
    snapshot_valid: `binary_sensor.${P}_dump_to_grid_snapshot_valid`,
    status: `sensor.${P}_dump_to_grid_status`,
    ends_at: `sensor.${P}_dump_to_grid_ends_at`,
    battery_soc: `sensor.${P}_ecco_battery_soc`,
    write_enable: `switch.${P}_dump_to_grid_write_enable`,
    export_power: `number.${P}_dump_to_grid_export_power`,
    stop_soc: `number.${P}_dump_to_grid_stop_soc`,
    duration: `number.${P}_dump_to_grid_duration`,
    start: `button.${P}_start_dump_to_grid_now`,
    end_restore: `button.${P}_end_dump_to_grid_restore_now`,
    schedule: {
      armed: "input_boolean.ecco_dump_to_grid_schedule_armed",
      start: "input_datetime.ecco_dump_to_grid_schedule_start",
      duration: "input_number.ecco_dump_to_grid_schedule_duration",
      power: "input_number.ecco_dump_to_grid_schedule_power",
      stop_soc: "input_number.ecco_dump_to_grid_schedule_stop_soc",
      last_result: "input_text.ecco_dump_to_grid_schedule_last_result",
      status: "sensor.ecco_dump_to_grid_schedule_status",
      cancel: "script.ecco_dump_to_grid_cancel_schedule",
    },
  },
};

export type States = Record<string, { state: string; attributes?: Record<string, unknown> }>;

export function idleStates(): States {
  const c = BASE_CONFIG;
  return {
    [c.free_power.active]: { state: "off" },
    [c.free_power.operation_in_progress]: { state: "off" },
    [c.free_power.snapshot_valid]: { state: "off" },
    [c.free_power.status]: { state: "Idle" },
    [c.free_power.ends_at]: { state: "Inactive" },
    [c.free_power.write_enable]: { state: "off" },
    [c.free_power.max_charge_power]: { state: "5000" },
    [c.free_power.duration]: { state: "60" },
    [c.schedule.armed]: { state: "off" },
    [c.schedule.start]: { state: "2026-11-15 02:00:00" },
    [c.schedule.duration]: { state: "90" },
    [c.schedule.power]: { state: "4000" },
    [c.schedule.last_result]: { state: "CANCELLED" },
    [c.schedule.status]: { state: "IDLE" },
    [c.dump_to_grid.active]: { state: "off" },
    [c.dump_to_grid.operation_in_progress]: { state: "off" },
    [c.dump_to_grid.snapshot_valid]: { state: "off" },
    [c.dump_to_grid.status]: { state: "Idle" },
    [c.dump_to_grid.ends_at]: { state: "Inactive" },
    [c.dump_to_grid.battery_soc]: { state: "64" },
    [c.dump_to_grid.write_enable]: { state: "off" },
    [c.dump_to_grid.export_power]: { state: "2500" },
    [c.dump_to_grid.stop_soc]: { state: "30" },
    [c.dump_to_grid.duration]: { state: "45" },
    [c.dump_to_grid.schedule.armed]: { state: "off" },
    [c.dump_to_grid.schedule.start]: { state: "2026-11-15 17:00:00" },
    [c.dump_to_grid.schedule.duration]: { state: "40" },
    [c.dump_to_grid.schedule.power]: { state: "2000" },
    [c.dump_to_grid.schedule.stop_soc]: { state: "25" },
    [c.dump_to_grid.schedule.last_result]: { state: "CANCELLED" },
    [c.dump_to_grid.schedule.status]: { state: "IDLE" },
  };
}

/** A hass mock whose callService records every call (the views must never make one). */
export function makeHass(states: States) {
  const calls: unknown[][] = [];
  return {
    hass: { states, callService: (...args: unknown[]) => { calls.push(args); return Promise.resolve(); } },
    calls,
  };
}
