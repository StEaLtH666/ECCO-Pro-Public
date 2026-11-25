// Test support for the plan controls: walk a Lit TemplateResult for its event handlers (flatten shows a function as "[fn]" and cannot call it),
// and the one set of checks that both the real card and every source mutant of the controls are run against.
import { isPlanServiceCall, PLAN_CONTROL_IDS } from "../../src/plan/planActions.ts";
import type { PlanServiceCall } from "../../src/plan/planActions.ts";
import { BASE_CONFIG } from "./fixtures.ts";
import type { States } from "./fixtures.ts";
import { flatten } from "./loadCard.ts";
import { MIN, NOW_MS, helperStates, running } from "./overrideFixtures.ts";
import { PLAN_CONFIG, planConfig, planStates } from "./planFixtures.ts";

export interface Handler {
  attr: string;
  fn: () => void;
}

/** Every function bound in a template (and in the templates nested in it), with the attribute it is bound to, e.g. "@click". */
export function handlersOf(v: unknown, out: Handler[] = []): Handler[] {
  if (Array.isArray(v)) {
    for (const x of v) handlersOf(x, out);
    return out;
  }
  const o = v as { strings?: readonly string[]; values?: unknown[] } | null;
  if (o && o.strings && o.values) {
    o.values.forEach((val, i) => {
      if (typeof val === "function") {
        const m = /(@[a-z-]+)=$/.exec(o.strings?.[i] ?? "");
        out.push({ attr: m ? (m[1] as string) : "?", fn: val as () => void });
      } else handlersOf(val, out);
    });
  }
  return out;
}

export const GUARDED_START = "script.ecco_dump_to_grid_start_guarded";

export function scriptStates(s: States): States {
  (s as Record<string, unknown>)[PLAN_CONTROL_IDS.start_script] = { state: "off" };
  (s as Record<string, unknown>)[PLAN_CONTROL_IDS.cancel_script] = { state: "off" };
  return s;
}

type Ctor = new () => { render(): unknown; setConfig(c: unknown): void; hass?: unknown; [k: string]: unknown };

/**
 * The checks the plan controls must keep passing, run against a card class (the real one, or one bundled from a mutated source). Returns the
 * problems found; an empty list means every check passed. Nothing here sends anything: the card's hass records each call.
 */
export function controlsProblems(Card: Ctor): string[] {
  const bad: string[] = [];
  const mk = (states: States, config: Record<string, unknown> = {}) => {
    const calls: unknown[][] = [];
    const card = new Card();
    card.setConfig(planConfig(config));
    card.hass = { states, callService: (...a: unknown[]) => { calls.push(a); return Promise.resolve(); } };
    return { card, calls };
  };
  const planHandlers = (card: ReturnType<typeof mk>["card"]): Handler[] => handlersOf((card as unknown as { _renderPlan(): unknown })._renderPlan());
  const realNow = Date.now;
  Date.now = () => NOW_MS;
  try {
    // 1. nothing configured: no control and no handler in the plan section
    {
      const { card } = mk(planStates());
      const text = flatten((card as unknown as { _renderPlan(): unknown })._renderPlan());
      if (planHandlers(card).length || text.includes("plan-controls")) bad.push("controls appear without the plan helpers");
    }
    // 2. configured: every handler is a click, every call is exactly a guarded script, and the three kinds can be started
    {
      const states = helperStates(scriptStates(planStates()));
      (states as Record<string, unknown>)[BASE_CONFIG.dump_to_grid.battery_soc] = { state: "35" };
      const { card, calls } = mk(states);
      const hs = planHandlers(card);
      if (hs.length < 6) bad.push("fewer than six control handlers: " + hs.length);
      if (hs.some((h) => h.attr !== "@click")) bad.push("a handler that is not a click");
      for (const h of hs) h.fn();
      const sent = calls.map((c) => ({ domain: c[0], service: c[1], data: c[2] }));
      if (sent.length !== hs.length) bad.push("a control did not send exactly one call");
      if (!sent.every((c) => isPlanServiceCall(c, null))) bad.push("a control sent a call outside the allow-list: " + JSON.stringify(sent.find((c) => !isPlanServiceCall(c, null))));
      const kinds = new Set(sent.map((c) => (c.data as { variables?: { kind?: string } }).variables?.kind));
      for (const k of ["hold_battery", "skip_tonight", "prepare_power_cut"]) if (!kinds.has(k)) bad.push("no start for " + k);
      if (sent.some((c) => (c.data as { entity_id: string }).entity_id === PLAN_CONTROL_IDS.cancel_script)) bad.push("a cancel is offered with nothing running");
      if (!sent.every((c) => (c.data as { variables?: { expected_revision?: number } }).variables?.expected_revision === 12)) bad.push("a call without the revision the card saw (12)");
      const text = flatten((card as unknown as { _renderPlan(): unknown })._renderPlan());
      const holdSeg = text.split('data-control=hold_battery')[1]?.split('data-control=skip_tonight')[0] ?? "";
      const chips = [...holdSeg.matchAll(/data-choice=d(\d+)/g)].map((m) => Number(m[1]));
      if (!chips.includes(240) || !chips.includes(1440) || chips.some((n) => n < 15 || n > 1440)) bad.push("Hold battery chips are not inside the owner's limits: " + chips.join(","));
      if (!/is-default" data-choice=d240/.test(holdSeg)) bad.push("the owner's Hold battery default (4 h) is not marked");
      const cutSeg = text.split('data-control=prepare_power_cut')[1] ?? "";
      const cutChips = [...cutSeg.matchAll(/data-choice=d(\d+)/g)].map((m) => Number(m[1]));
      if (!cutChips.includes(1440) || !cutChips.includes(4320) || cutChips.some((n) => n > 4320)) bad.push("Prepare for power cut chips are not inside the owner's limits: " + cutChips.join(","));
    }
    // 2b. the owner's own limits move the chips: a shortest length of 60 min removes the 30-min chip, a longest of 120 min removes every longer one
    {
      const states = helperStates(scriptStates(planStates()), {
        "input_number.ecco_plan_policy_min_expiry": { state: "60" },
        "input_number.ecco_plan_policy_hold_default": { state: "60" },
        "input_number.ecco_plan_policy_hold_cap": { state: "120" },
        "input_number.ecco_plan_policy_cut_cap": { state: "1440" },
      });
      const { card } = mk(states);
      const text = flatten((card as unknown as { _renderPlan(): unknown })._renderPlan());
      const seg = (k: string, next: string) => text.split("data-control=" + k)[1]?.split(next)[0] ?? "";
      const holdChips = [...seg("hold_battery", "data-control=skip_tonight").matchAll(/data-choice=d(\d+)/g)].map((m) => Number(m[1]));
      if (holdChips.length === 0 || holdChips.some((n) => n < 60 || n > 120) || !holdChips.includes(120) || !holdChips.includes(60)) bad.push("the chips ignore the owner's shortest and longest length: " + holdChips.join(","));
      const cutChips = [...(text.split("data-control=prepare_power_cut")[1] ?? "").matchAll(/data-choice=d(\d+)/g)].map((m) => Number(m[1]));
      if (cutChips.some((n) => n > 1440 || n < 60) || !cutChips.includes(1440)) bad.push("the power-cut chips ignore the owner's limits: " + cutChips.join(","));
    }
    // 3. running: a Cancel for the running one only, with the revision; the below-reserve sentence for Prepare for power cut only
    {
      const states = helperStates(scriptStates(planStates()));
      running(states, "hold_battery", 30, 200);
      running(states, "prepare_power_cut", 30, 600, 80);
      (states as Record<string, unknown>)[BASE_CONFIG.dump_to_grid.battery_soc] = { state: "35" };
      const { card, calls } = mk(states);
      const text = flatten((card as unknown as { _renderPlan(): unknown })._renderPlan());
      const sentence = "The battery is at 35 percent, below the 80 percent reserve. Nothing is charging. Use Charge Battery if you want it filled.";
      if (!text.includes(sentence)) bad.push("the below-reserve sentence is missing");
      if ((text.split(sentence).length - 1) < 2) bad.push("the sentence is not shown in both the override row and the controls");
      if (text.split('data-control=hold_battery')[1]?.split('data-control=skip_tonight')[0]?.includes(sentence)) bad.push("the sentence is shown under Hold battery");
      for (const h of planHandlers(card)) h.fn();
      const cancels = calls.filter((c) => (c[2] as { entity_id: string }).entity_id === PLAN_CONTROL_IDS.cancel_script).map((c) => (c[2] as { variables: { kind: string; expected_revision: number } }).variables);
      if (cancels.map((c) => c.kind).sort().join() !== "hold_battery,prepare_power_cut" || cancels.some((c) => c.expected_revision !== 12)) bad.push("the cancels are not exactly the two running overrides with the revision: " + JSON.stringify(cancels));
      (states as Record<string, unknown>)[BASE_CONFIG.dump_to_grid.battery_soc] = { state: "90" };
      if (flatten((card as unknown as { _renderPlan(): unknown })._renderPlan()).includes("Nothing is charging")) bad.push("the sentence is shown while the battery is above the reserve");
    }
    // 4. fail closed: limits not confirmed, reserve unknown or above the power-cut reserve, scripts missing
    {
      const unconfirmed = helperStates(scriptStates(planStates()), { [PLAN_CONTROL_IDS.last_result]: { state: "REFUSED POLICY_UNCONFIRMED - nope" } });
      (unconfirmed as Record<string, unknown>)["input_boolean.ecco_plan_overrides_enabled"] = { state: "off" };
      const a = mk(unconfirmed);
      const textA = flatten((a.card as unknown as { _renderPlan(): unknown })._renderPlan());
      if (planHandlers(a.card).length !== 0) bad.push("a start is offered while the limits are not confirmed");
      if (!textA.includes("Last answer: REFUSED POLICY_UNCONFIRMED - nope")) bad.push("the script's last answer is not shown verbatim");
      const noReserve = helperStates(scriptStates(planStates()));
      delete (noReserve as Record<string, unknown>)[PLAN_CONFIG.reserve];
      const b = mk(noReserve);
      const segB = flatten((b.card as unknown as { _renderPlan(): unknown })._renderPlan()).split('data-control=prepare_power_cut')[1] ?? "";
      if (/data-choice=/.test(segB) || !segB.includes("data-control-blocked")) bad.push("Prepare for power cut is offered with an unknown reserve");
      const high = helperStates(scriptStates(planStates()));
      (high as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "85" };
      const c = mk(high);
      const textC = flatten((c.card as unknown as { _renderPlan(): unknown })._renderPlan());
      const segC = textC.split('data-control=prepare_power_cut')[1] ?? "";
      if (/data-choice=/.test(segC)) bad.push("Prepare for power cut is offered below the current reserve");
      if (!(textC.split('data-control=hold_battery')[1]?.split('data-control=skip_tonight')[0] ?? "").includes("data-choice=")) bad.push("Hold battery is blocked by the reserve");
      const noScripts = helperStates(planStates());
      const d = mk(noScripts);
      if (planHandlers(d.card).length !== 0 || !flatten((d.card as unknown as { _renderPlan(): unknown })._renderPlan()).includes("data-controls-missing")) bad.push("controls offered without the guarded scripts");
    }
    // 5. the card drops every call that is not exactly a guarded script
    {
      const { card, calls } = mk(helperStates(scriptStates(planStates())), { dump_to_grid: { ...BASE_CONFIG.dump_to_grid, guarded_start: GUARDED_START } });
      const send = (call: unknown) => (card as unknown as { _callPlanService(c: unknown): void })._callPlanService(call);
      const forged: unknown[] = [
        { domain: "button", service: "press", data: { entity_id: BASE_CONFIG.dump_to_grid.start } },
        { domain: "script", service: "turn_on", data: { entity_id: "script.something_else" } },
        { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script, value: 5 } },
        { domain: "script", service: "turn_off", data: { entity_id: PLAN_CONTROL_IDS.start_script } },
        { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script, variables: { kind: "hold_battery", entity_id: "switch.x" } } },
        { domain: "switch", service: "turn_on", data: { entity_id: "switch.x" } },
        { domain: "script", service: "turn_on", data: { entity_id: GUARDED_START, variables: { kind: "hold_battery" } } },
      ];
      forged.forEach(send);
      if (calls.length) bad.push("a forged call was sent: " + JSON.stringify(calls[0]));
      send({ domain: "script", service: "turn_on", data: { entity_id: GUARDED_START } });
      send({ domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.cancel_script, variables: { kind: "skip_tonight" } } });
      if (calls.length !== 2) bad.push("an allowed call was dropped");
    }
    // 6. the manual Dump to Grid start: the guarded script only, the direct press as before, nothing when the script id is not a script
    {
      const startClicks = (config: Record<string, unknown>) => {
        const { card, calls } = mk(helperStates(scriptStates(planStates())), config);
        const tile = (card as unknown as { _renderDumpToGridTile(): unknown })._renderDumpToGridTile();
        const clicks = handlersOf(tile).filter((h) => h.attr === "@click");
        return { clicks, calls };
      };
      const press = (config: Record<string, unknown>) => {
        const r = startClicks(config);
        // The Start button is the click whose handler, run alone, reaches Home Assistant with the start entity or the guarded script.
        const out: unknown[][][] = [];
        for (const h of r.clicks) {
          const before = r.calls.length;
          h.fn();
          if (r.calls.length > before) out.push(r.calls.slice(before));
        }
        return out.flat();
      };
      const direct = press({});
      if (!direct.some((c) => c[0] === "button" && c[1] === "press" && (c[2] as { entity_id: string }).entity_id === BASE_CONFIG.dump_to_grid.start)) bad.push("without guarded_start the start is not pressed directly");
      const guarded = press({ dump_to_grid: { ...BASE_CONFIG.dump_to_grid, guarded_start: GUARDED_START } });
      if (guarded.some((c) => (c[2] as { entity_id: string }).entity_id === BASE_CONFIG.dump_to_grid.start)) bad.push("with guarded_start the start button is still pressed directly");
      if (!guarded.some((c) => c[0] === "script" && c[1] === "turn_on" && (c[2] as { entity_id: string }).entity_id === GUARDED_START)) bad.push("with guarded_start the guarded script is not called");
      const broken = press({ dump_to_grid: { ...BASE_CONFIG.dump_to_grid, guarded_start: BASE_CONFIG.dump_to_grid.start } });
      if (broken.some((c) => (c[2] as { entity_id: string }).entity_id === BASE_CONFIG.dump_to_grid.start)) bad.push("a guarded_start that is not a script falls back to the direct press");
    }
  } catch (e) {
    bad.push("threw " + (e instanceof Error ? e.message : String(e)).slice(0, 160));
  } finally {
    Date.now = realNow;
  }
  void MIN;
  return bad;
}

export type { PlanServiceCall };
