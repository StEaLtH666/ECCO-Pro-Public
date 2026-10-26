// Mock telemetry for the local preview: realistic ECCO entity states per
// scenario. These are DEMO values for the harness only; nothing here is live
// data and nothing here is used by the card bundle.

const ENT = {
  pv1: "sensor.ecco_clock_dongle_ecco_pv1_power",
  pv2: "sensor.ecco_clock_dongle_ecco_pv2_power",
  pv: "sensor.ecco_pv_power",
  inv: "sensor.ecco_clock_dongle_ecco_inverter_output_power",
  invState: "sensor.ecco_clock_dongle_ecco_inverter_system_state",
  home: "sensor.ecco_house_power",
  bat: "sensor.ecco_clock_dongle_ecco_battery_output_power",
  soc: "sensor.ecco_battery_soc",
  ttr: "sensor.ecco_battery_time_to_reserve",
  grid: "sensor.ecco_grid_power",
  gridConn: "binary_sensor.ecco_clock_dongle_ecco_grid_connected",
  gridV: "sensor.ecco_clock_dongle_ecco_grid_voltage_l1",
  gridHz: "sensor.ecco_clock_dongle_ecco_grid_frequency",
  tel: "binary_sensor.ecco_clock_dongle_telemetry_online",
  sun: "sun.sun",
  fpActive: "binary_sensor.ecco_clock_dongle_free_power_active",
  fpStatus: "sensor.ecco_clock_dongle_free_power_status",
  fpEnds: "sensor.ecco_clock_dongle_free_power_ends_at",
  fpSched: "sensor.ecco_free_power_schedule_status",
  dActive: "binary_sensor.ecco_clock_dongle_dump_to_grid_active",
  dStatus: "sensor.ecco_clock_dongle_dump_to_grid_status",
  dEnds: "sensor.ecco_clock_dongle_dump_to_grid_ends_at",
  dSched: "sensor.ecco_dump_to_grid_schedule_status",
  dExport: "sensor.ecco_clock_dongle_dump_to_grid_active_export_power",
  dStop: "sensor.ecco_clock_dongle_dump_to_grid_active_stop_soc",
  touValid: "binary_sensor.ecco_tou_schedule_valid",
  fcToday: "sensor.ecco_solar_forecast_today",
  fcRemaining: "sensor.ecco_solar_forecast_remaining",
  fcTomorrow: "sensor.ecco_solar_forecast_tomorrow",
  dayPv: "sensor.ecco_clock_dongle_ecco_day_pv_energy",
  dayLoad: "sensor.ecco_clock_dongle_ecco_day_load_energy",
  dayImp: "sensor.ecco_clock_dongle_ecco_day_grid_import",
  dayExp: "sensor.ecco_clock_dongle_ecco_day_grid_export",
  dayBc: "sensor.ecco_clock_dongle_ecco_day_battery_charge",
  dayBd: "sensor.ecco_clock_dongle_ecco_day_battery_discharge",
  tAc: "sensor.ecco_clock_dongle_ecco_temperature_ac_transformer",
  tDc: "sensor.ecco_clock_dongle_ecco_temperature_dc_transformer",
  tBat: "sensor.ecco_clock_dongle_ecco_battery_temperature",
  attention: "binary_sensor.ecco_dump_limits_attention",
  weather: "weather.forecast_home",
};

const HEALTH = [
  "sensor.ecco_health_communications",
  "sensor.ecco_health_inverter_telemetry",
  "sensor.ecco_health_runtime_configuration",
  "sensor.ecco_health_configuration",
  "sensor.ecco_health_manual_write_system",
  "sensor.ecco_health_rtc",
  "sensor.ecco_health_free_power",
  "sensor.ecco_health_start_failures",
  "sensor.ecco_health_supervision",
  "sensor.ecco_health_fallback",
];

// Slot starts (minutes): 00:00, 02:00, 05:30, 16:00, 19:00, 23:30
const TOU_STARTS = [0, 120, 330, 960, 1140, 1410];
const TOU_SOC = [100, 100, 40, 40, 30, 100];
const TOU_CHARGE = ["Grid", "Grid", "None", "None", "None", "Grid"];
const TOU_POWER = [3000, 3000, 8000, 8000, 8000, 3000];

function localStamp(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
}

function entity(state, attributes = {}, ageS = 0) {
  const ts = new Date(Date.now() - ageS * 1000).toISOString();
  return { state: String(state), attributes, last_updated: ts, last_changed: ts };
}

/** Builds hass.states for a scenario. All numbers are demo values. */
export function buildStates(name) {
  const now = new Date();
  const s = {};
  const put = (id, state, attrs, ageS) => (s[id] = entity(state, attrs, ageS));
  const sun = (above, elevation, rising = elevation > 0 ? now.getHours() < 13 : false) => put(ENT.sun, above ? "above_horizon" : "below_horizon", { elevation, rising });
  const weather = (condition) => put(ENT.weather, condition, { temperature: 14, humidity: 71 });
  const powers = ({ pv1, pv2, home, bat, grid, soc, inv }) => {
    put(ENT.pv1, pv1);
    put(ENT.pv2, pv2);
    put(ENT.pv, pv1 + pv2);
    put(ENT.inv, inv ?? Math.max(0, home - Math.max(0, grid)));
    put(ENT.home, home);
    put(ENT.bat, bat); // discharge positive
    put(ENT.soc, soc);
    put(ENT.grid, grid); // import positive
  };
  const common = () => {
    put(ENT.invState, "Normal");
    put(ENT.gridConn, "on");
    put(ENT.gridV, 241.3);
    put(ENT.gridHz, 50.02);
    put(ENT.tel, "on");
    put(ENT.touValid, "on");
    TOU_STARTS.forEach((m, i) => put(`sensor.ecco_tou_slot_${i + 1}_start_minute`, m, { unit_of_measurement: "min" }));
    TOU_SOC.forEach((v, i) => put(`sensor.ecco_clock_dongle_ecco_timezone${i + 1}_soc`, v, { unit_of_measurement: "%" }));
    TOU_CHARGE.forEach((v, i) => put(`sensor.ecco_clock_dongle_ecco_timezone${i + 1}_charge`, v));
    TOU_POWER.forEach((v, i) => put(`sensor.ecco_clock_dongle_ecco_timezone${i + 1}_power`, v, { unit_of_measurement: "W" }));
    put(ENT.fcToday, 18.2, { unit_of_measurement: "kWh" });
    put(ENT.fcRemaining, 7.4, { unit_of_measurement: "kWh" });
    put(ENT.fcTomorrow, 12.9, { unit_of_measurement: "kWh" });
    put(ENT.dayPv, 10.8);
    put(ENT.dayLoad, 14.2);
    put(ENT.dayImp, 6.1);
    put(ENT.dayExp, 2.3);
    put(ENT.dayBc, 7.9);
    put(ENT.dayBd, 4.4);
    put(ENT.tAc, 40.2);
    put(ENT.tDc, 46.9);
    put(ENT.tBat, 21.5);
    HEALTH.forEach((id) => put(id, "HEALTHY", { summary: "OK" }));
    put(ENT.attention, "off");
    put(ENT.fpActive, "off");
    put(ENT.fpStatus, "Inactive");
    put(ENT.fpEnds, "Inactive");
    put(ENT.fpSched, "IDLE", { scheduled_start: "02:00:00", duration_minutes: 120, requested_power_w: 3000 });
    put(ENT.dActive, "off");
    put(ENT.dStatus, "Inactive");
    put(ENT.dEnds, "Inactive");
    put(ENT.dSched, "IDLE", { scheduled_start: "17:00:00", duration_minutes: 60, requested_power_w: 3000, requested_stop_soc: 30 });
    put(ENT.dExport, "unavailable");
    put(ENT.dStop, "unavailable");
  };
  const ttr = (status, minutes, extra = {}) =>
    put(ENT.ttr, minutes ?? "unknown", {
      unit_of_measurement: "min",
      status,
      summary:
        status === "discharging"
          ? `About ${Math.round(minutes / 60)} h to the 20% reserve at recent usage (estimate)`
          : status === "charging"
            ? "Charging"
            : status === "holding"
              ? "Holding: the batteries are neither charging nor discharging significantly"
              : "Insufficient data: collecting recent usage (3 of 10 minutes)",
      minutes_low: extra.low ?? null,
      minutes_high: extra.high ?? null,
      beyond_horizon: false,
      solar_assisted: !!extra.solar,
    });

  common();
  switch (name) {
    case "night-discharge": {
      sun(false, -24);
      weather("clear-night");
      powers({ pv1: 0, pv2: 0, home: 920, bat: 930, grid: 4, soc: 54, inv: 925 });
      ttr("discharging", 384, { low: 330, high: 440 });
      put(ENT.fpSched, "ARMED", { scheduled_start: "02:00:00", duration_minutes: 120, requested_power_w: 3000 });
      break;
    }
    case "night-import-charge": {
      sun(false, -30);
      weather("lightning-rainy");
      powers({ pv1: 0, pv2: 0, home: 1180, bat: -2950, grid: 4180, soc: 35, inv: 0 });
      ttr("charging", "unknown");
      put(ENT.fpActive, "on");
      put(ENT.fpStatus, "ACTIVE - lease 02:00-04:00, 3000 W max charge");
      put(ENT.fpEnds, localStamp(new Date(now.getTime() + 47 * 60000)));
      put(ENT.fpSched, "ACTIVE", { scheduled_start: "02:00:00", duration_minutes: 120, requested_power_w: 3000 });
      break;
    }
    case "dump-active": {
      sun(true, 6, false);
      weather("sunny");
      powers({ pv1: 140, pv2: 90, home: 760, bat: 3480, grid: -2910, soc: 61, inv: 3680 });
      ttr("discharging", 95, { low: 80, high: 120 });
      put(ENT.dActive, "on");
      put(ENT.dStatus, "ACTIVE - exporting 3000 W until 30% SOC");
      put(ENT.dEnds, localStamp(new Date(now.getTime() + 21 * 60000)));
      put(ENT.dSched, "ACTIVE", { scheduled_start: "17:00:00", duration_minutes: 60, requested_power_w: 3000, requested_stop_soc: 30 });
      put(ENT.dExport, 3000);
      put(ENT.dStop, 30);
      break;
    }
    case "idle": {
      sun(true, 42);
      weather("partlycloudy");
      powers({ pv1: 2, pv2: 1, home: 3, bat: 0, grid: 1, soc: 100, inv: 0 });
      ttr("holding", "unknown");
      break;
    }
    case "unknown": {
      sun(true, 20);
      put(ENT.weather, "unavailable");
      [ENT.pv1, ENT.pv2, ENT.pv, ENT.inv, ENT.home, ENT.bat, ENT.soc, ENT.grid, ENT.gridConn, ENT.tel, ENT.fcToday, ENT.fcRemaining].forEach((id) => put(id, "unavailable"));
      HEALTH.forEach((id) => put(id, "unavailable"));
      [1, 2, 3, 4, 5, 6].forEach((i) => put(`sensor.ecco_tou_slot_${i}_start_minute`, "unavailable"));
      ttr("insufficient_data", "unknown");
      break;
    }
    case "stale": {
      sun(true, 30);
      weather("fog");
      powers({ pv1: 1800, pv2: 1500, home: 900, bat: -2400, grid: 0, soc: 66, inv: 900 });
      Object.keys(s).forEach((id) => (s[id] = entity(s[id].state, s[id].attributes, 600)));
      put(ENT.tel, "off");
      ttr("stale", "unknown");
      break;
    }
    case "attention": {
      sun(true, 12, true);
      weather("rainy");
      powers({ pv1: 400, pv2: 350, home: 2100, bat: 1400, grid: 0, soc: 44, inv: 2100 });
      put(ENT.gridConn, "off");
      put("sensor.ecco_health_communications", "FAILED", { summary: "Configuration polling offline; telemetry polling online." });
      put("sensor.ecco_health_rtc", "DEGRADED", { summary: "RTC drift 42 s against NTP" });
      put(ENT.attention, "on");
      ttr("discharging", 160, { low: 140, high: 190, solar: true });
      put(ENT.fpSched, "FAILED", { last_result: "FAILED: lease refused (telemetry stale)" });
      break;
    }
    case "uneven-arrays": {
      // G: one array generating far more than the other (shading on the garage roof).
      sun(true, 35, false);
      weather("partlycloudy");
      powers({ pv1: 4200, pv2: 900, home: 1500, bat: -2600, grid: -1000, soc: 62, inv: 2500 });
      ttr("charging", "unknown");
      break;
    }
    case "solar-trickle": {
      // F: solar producing almost nothing: the yellow routes must be idle (below the 5 W threshold) while the house runs on the battery.
      sun(true, 4, false);
      weather("cloudy");
      powers({ pv1: 3, pv2: 1, home: 640, bat: 650, grid: 2, soc: 71, inv: 645 });
      ttr("discharging", 540, { low: 480, high: 610 });
      break;
    }
    case "day-export":
    default: {
      sun(true, 38);
      weather("sunny");
      powers({ pv1: 3350, pv2: 3050, home: 2300, bat: -3100, grid: -1000, soc: 78, inv: 3300 });
      ttr("charging", "unknown");
      put(ENT.dSched, "ARMED", { scheduled_start: "17:00:00", duration_minutes: 60, requested_power_w: 3000, requested_stop_soc: 30 });
      break;
    }
  }
  return s;
}

export const SCENARIOS = ["day-export", "night-discharge", "night-import-charge", "dump-active", "uneven-arrays", "solar-trickle", "idle", "unknown", "stale", "attention"];
