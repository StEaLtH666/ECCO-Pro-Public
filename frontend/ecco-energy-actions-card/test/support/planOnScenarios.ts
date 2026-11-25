// Scenarios for the "plan flag on, no plan helper entities" identity proof. test/golden/plan-on-render.json was captured from the plan
// section as it stood BEFORE the override helpers were read (commit 9fc37bd), so a test comparing today's output with it proves the
// section is unchanged whenever the proposed helper entities do not exist.
import { BASE_CONFIG } from "./fixtures.ts";
import type { States } from "./fixtures.ts";
import { PLAN_CONFIG, planConfig, planStates, slotEntity } from "./planFixtures.ts";

export interface PlanOnScenario {
  config: Record<string, unknown>;
  states: States;
}

const D = BASE_CONFIG.dump_to_grid;
const SD = D.schedule;
const SF = BASE_CONFIG.schedule;

export const PLAN_ON_SCENARIOS: Record<string, () => PlanOnScenario> = {
  "idle-with-advice": () => ({ config: planConfig(), states: planStates() }),
  "idle-without-advice": () => ({ config: planConfig(), states: planStates(false) }),
  "advice-paused": () => ({ config: planConfig(), states: planStates(true, { paused: true }) }),
  "advice-proposes-other-target": () => ({ config: planConfig(), states: planStates(true, { target: 90 }) }),
  "no-reserve-entity": () => ({ config: planConfig({}, { reserve: undefined }), states: planStates() }),
  "no-plan-block": () => ({ config: { ...BASE_CONFIG, show_plan: true }, states: planStates() }),
  "unreadable-table": () => {
    const states = planStates();
    states[slotEntity(1, "time")] = { state: "unavailable" };
    return { config: planConfig(), states };
  },
  "armed-and-active": () => {
    const states = planStates();
    states[SF.armed] = { state: "on" };
    states[SF.power] = { state: "5000" };
    states[D.active] = { state: "on" };
    states[SD.armed] = { state: "on" };
    states["sensor.test_latched_power"] = { state: "2000" };
    states["sensor.test_latched_stop"] = { state: "40" };
    return {
      config: planConfig({ dump_to_grid: { ...D, active_export_power: "sensor.test_latched_power", active_stop_soc: "sensor.test_latched_stop" } }),
      states,
    };
  },
  "unrelated-helper-names": () => {
    const states = planStates();
    states["input_number.ecco_plan_unrelated"] = { state: "3" };
    states["sensor.ecco_plan_policy_min_expiry"] = { state: "5" };
    return { config: planConfig(), states };
  },
};

export { PLAN_CONFIG };
