// Test support for the corrections of the Energy Actions card (CURRENT reserve vs power-cut TARGET, the installed-detection messages, the compact
// layout): the one set of end-to-end checks that both the real card and every source mutant of the new logic are run against. Nothing here sends
// anything to Home Assistant: the card's hass records each call.
import { HELPER_IDS } from "../../src/plan/helpers.ts";
import { PLAN_CONTROL_IDS } from "../../src/plan/planActions.ts";
import { BASE_CONFIG } from "./fixtures.ts";
import type { States } from "./fixtures.ts";
import { flatten } from "./loadCard.ts";
import { NOW_MS, helperStates, running } from "./overrideFixtures.ts";
import { PLAN_CONFIG, planConfig, planStates } from "./planFixtures.ts";
import { GUARDED_START, handlersOf, scriptStates } from "./controlsProbe.ts";

type Ctor = new () => { render(): unknown; setConfig(c: unknown): void; hass?: unknown; [k: string]: unknown };

export const SENSORS = { effective_reserve: "sensor.ecco_plan_effective_reserve", export_hold: "sensor.ecco_plan_export_hold" };

/** One value of the owner's reserve helper, and what the card must do about Prepare for power cut (target 80 %). */
export interface ReserveCase {
  state: string;
  /** The reserve is known and shown as "Reserve now <shown> %". */
  shown?: string;
  /** Prepare for power cut is offered (start choices exist). */
  offered: boolean;
  /** A phrase the reason or the reserve line must contain. */
  says?: RegExp;
}

export const RESERVE_CASES: ReserveCase[] = [
  { state: "0", shown: "0", offered: true },
  { state: "4.9", shown: "4.9", offered: true },
  { state: "5", shown: "5", offered: true },
  { state: "5.0", shown: "5", offered: true },
  { state: "9.9", shown: "9.9", offered: true },
  { state: "10", shown: "10", offered: true },
  { state: "20", shown: "20", offered: true },
  { state: "79", shown: "79", offered: true },
  // The installed effective-reserve sensor rounds the owner's reserve UP: 79.01, 79.5 and 79.9 are all published as 80, so a target of 80 raises nothing.
  { state: "79.01", shown: "79.01", offered: false, says: /not above the reserve now \(79\.01 %, which the plan uses as 80 %\), so it cannot raise the reserve/ },
  { state: "79.5", shown: "79.5", offered: false, says: /not above the reserve now \(79\.5 %, which the plan uses as 80 %\), so it cannot raise the reserve/ },
  { state: "79.9", shown: "79.9", offered: false, says: /not above the reserve now \(79\.9 %, which the plan uses as 80 %\), so it cannot raise the reserve/ },
  { state: "80", shown: "80", offered: false, says: /not above the reserve now \(80 %\), so it cannot raise the reserve/ },
  { state: "80.1", shown: "80.1", offered: false, says: /below the current backup reserve \(80\.1 %\)/ },
  { state: "100", shown: "100", offered: false, says: /below the current backup reserve \(100 %\)/ },
  { state: "100.01", offered: false, says: /not a percentage from 0 to 100/ },
  { state: "100.05", offered: false, says: /not a percentage from 0 to 100/ },
  { state: "100.1", offered: false, says: /not a percentage from 0 to 100/ },
  { state: "-1", offered: false, says: /not a percentage from 0 to 100/ },
  { state: "NaN", offered: false, says: /is not a number/ },
  { state: "abc", offered: false, says: /is not a number/ },
  { state: "unknown", offered: false, says: /cannot be read/ },
  { state: "unavailable", offered: false, says: /cannot be read/ },
  { state: "", offered: false, says: /cannot be read/ },
];

export function section(text: string, kind: string): string {
  return text.split("data-control=").find((p) => p.startsWith(kind)) ?? "";
}

/** The number of `<details` elements still open at character `idx` of a flattened template. */
export function depthAt(text: string, idx: number): number {
  const before = text.slice(0, idx);
  return (before.match(/<details/g) ?? []).length - (before.match(/<\/details>/g) ?? []).length;
}

export function reserveInstallProblems(Card: Ctor): string[] {
  const bad: string[] = [];
  const mk = (states: States, config: Record<string, unknown> = {}, plan: Record<string, unknown> = {}) => {
    const calls: unknown[][] = [];
    const card = new Card();
    card.setConfig(planConfig(config, plan));
    card.hass = { states, callService: (...a: unknown[]) => { calls.push(a); return Promise.resolve(); } };
    return { card, calls };
  };
  const planOf = (card: ReturnType<typeof mk>["card"]): unknown => (card as unknown as { _renderPlan(): unknown })._renderPlan();
  const base = (): States => helperStates(scriptStates(planStates()));
  // the two plan sensors the installed backend publishes (the reserve ECCO's plan uses, and the export hold), so that nothing is reported as not found
  const withPlanSensors = (s: States, effective = "20"): States => {
    (s as Record<string, unknown>)[SENSORS.effective_reserve] = { state: effective };
    (s as Record<string, unknown>)[SENSORS.export_hold] = { state: "clear" };
    return s;
  };
  const realNow = Date.now;
  Date.now = () => NOW_MS;
  try {
    // 1. the CURRENT reserve table: Prepare for power cut with the policy target 80 %; Hold battery and Skip tonight never depend on the reserve
    for (const c of RESERVE_CASES) {
      const states = base();
      (states as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: c.state };
      const { card, calls } = mk(states);
      const text = flatten(planOf(card));
      const prep = section(text, "prepare_power_cut");
      const offered = prep.includes("data-choice=");
      if (offered !== c.offered) bad.push("reserve " + JSON.stringify(c.state) + ": Prepare for power cut " + (offered ? "is offered" : "is not offered") + ", expected " + (c.offered ? "offered" : "blocked"));
      if (!c.offered && !prep.includes("data-control-blocked")) bad.push("reserve " + JSON.stringify(c.state) + ": no reason is given");
      if (c.says && !c.says.test(prep)) bad.push("reserve " + JSON.stringify(c.state) + ": the reason does not say " + String(c.says));
      if (c.shown !== undefined && !prep.includes("Reserve now " + c.shown + " %")) bad.push("reserve " + JSON.stringify(c.state) + ": the line does not say 'Reserve now " + c.shown + " %'");
      if (c.shown === undefined && !prep.includes("Reserve now unknown")) bad.push("reserve " + JSON.stringify(c.state) + ": an unknown reserve is not called unknown");
      if (!prep.includes("Power cut target 80 %")) bad.push("reserve " + JSON.stringify(c.state) + ": the target 80 % is not shown");
      if (c.state === "20" && text.includes("keeps no figure for this value")) bad.push("reserve 20: a value inside the plan range carries the outside-the-model note");
      if (text.includes("outside what ECCO accepts")) bad.push("reserve " + JSON.stringify(c.state) + ": the planner floor is applied to the reserve now");
      for (const k of ["hold_battery", "skip_tonight"]) if (!section(text, k).includes("data-choice=")) bad.push("reserve " + JSON.stringify(c.state) + ": " + k + " is not offered");
      // what is sent: only the start script, with Prepare for power cut among the calls exactly when it is offered
      for (const h of handlersOf(planOf(card))) h.fn();
      const sent = calls.map((a) => a[2] as { entity_id: string; variables?: { kind?: string; expiry_min?: number; expected_revision?: number } });
      if (!sent.every((d) => d.entity_id === PLAN_CONTROL_IDS.start_script)) bad.push("reserve " + JSON.stringify(c.state) + ": a call other than the start script");
      const prepCalls = sent.filter((d) => d.variables?.kind === "prepare_power_cut");
      if ((prepCalls.length > 0) !== c.offered) bad.push("reserve " + JSON.stringify(c.state) + ": " + prepCalls.length + " Prepare for power cut start calls");
      if (!sent.every((d) => Object.keys(d.variables ?? {}).every((k) => k === "kind" || k === "expiry_min" || k === "until_local" || k === "expected_revision"))) bad.push("reserve " + JSON.stringify(c.state) + ": a variable the scripts do not take");
    }
    // 2. the TARGET keeps its floor: the helper minimum 10 and strictly above the reserve now
    const target = (cutReserve: string, current: string): { prep: string; text: string } => {
      const states = base();
      (states as Record<string, unknown>)[HELPER_IDS.cut_reserve] = { state: cutReserve };
      (states as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: current };
      const text = flatten(planOf(mk(states).card));
      return { prep: section(text, "prepare_power_cut"), text };
    };
    // (the installed reserve sensor rounds the owner's value UP, so 9.9 is published as 10 and 99.9 as 100: a target of 10 or 100 over them raises nothing)
    if (!target("10", "9").prep.includes("data-choice=")) bad.push("target 10 over a reserve of 9 is not offered");
    if (target("10", "9.9").prep.includes("data-choice=")) bad.push("target 10 over a reserve of 9.9 is offered (the plan uses 10)");
    if (target("10", "10").prep.includes("data-choice=")) bad.push("target 10 equal to a reserve of 10 is offered");
    if (!target("100", "99").prep.includes("data-choice=")) bad.push("target 100 over a reserve of 99 is not offered");
    if (target("100", "99.9").prep.includes("data-choice=")) bad.push("target 100 over a reserve of 99.9 is offered (the plan uses 100)");
    if (target("100", "100").prep.includes("data-choice=")) bad.push("target 100 equal to a reserve of 100 is offered");
    const low = target("9", "5");
    if (low.text.includes("data-choice=") || !/at least 10 %/.test(low.text)) bad.push("a target below the helper minimum 10 is accepted (or not explained)");
    const high = target("101", "5");
    if (high.text.includes("data-choice=")) bad.push("a target above 100 is offered");
    // a reserve now above the target (90 over 80): the limits stay usable, Hold battery and Skip tonight start, only Prepare for power cut is withheld
    {
      const states = withPlanSensors(base());
      (states as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "90" };
      (states as Record<string, unknown>)[SENSORS.effective_reserve] = { state: "90" };
      const text = flatten(planOf(mk(states).card));
      // the readiness is about the limits themselves (the reserve-aware policy is only about Prepare for power cut): everything is found, so it is plainly ready
      if (!/data-readiness=ready role="status">Overrides ready\./.test(text)) bad.push("a reserve above the target: the status is not 'Overrides ready.' (readiness must follow the start limits, not the reserve-aware policy)");
      for (const k of ["hold_battery", "skip_tonight"]) if (!section(text, k).includes("data-choice=")) bad.push("a reserve above the target: " + k + " is not offered");
      if (section(text, "prepare_power_cut").includes("data-choice=")) bad.push("a reserve above the target: Prepare for power cut is offered");
      if (!text.includes("data-override-policy=ok")) bad.push("a reserve above the target makes the limits look unusable");
      if (!/data-summary="limits">Limits in force/.test(text)) bad.push("a reserve above the target: the limits summary does not say 'Limits in force'");
      if (text.includes("no override can be started. Nothing falls back")) bad.push("a reserve above the target says that no override can be started");
      if (!text.includes("Prepare for power cut is not offered")) bad.push("a reserve above the target: the withheld Prepare for power cut is not explained in the limits");
    }
    // no reserve entity configured: unknown with its honest reason, not offered
    {
      const { card } = mk(base(), {}, { reserve: undefined });
      const prep = section(flatten(planOf(card)), "prepare_power_cut");
      if (prep.includes("data-choice=") || !prep.includes("No backup reserve entity is configured")) bad.push("no reserve entity: Prepare for power cut is offered or the reason is wrong");
    }
    // the Tomorrow summary and the planned settings carry the REAL reserve (5), not the plan model's placeholder (10)
    {
      const states = base();
      (states as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "5" };
      const text = flatten(planOf(mk(states).card));
      // the fold summary names the owner's reserve unambiguously, always (the reserve ECCO's plan uses is a different figure, shown beside the controls)
      if (!/data-summary="tomorrow">[^<]*Your reserve 5 %/.test(text)) bad.push("the Tomorrow's Plan summary does not carry the owner's reserve (Your reserve 5 %)");
      if (/data-summary="tomorrow">[^<]*(?<!Your )[Rr]eserve 5 %/.test(text)) bad.push("the Tomorrow's Plan summary still says a bare 'Reserve 5 %'");
      if (!/data-figure=reserve>\s*<dt>Your reserve<\/dt>/.test(text)) bad.push("the Tomorrow's Plan reserve figure inside the fold is not labelled 'Your reserve'");
      if (!/data-setting=reserve\.backupPct>\s*<span class="plan-setting-label">[^<]*<\/span>\s*<span class="plan-setting-value">5 %/.test(text)) bad.push("the planned settings row does not show the reserve now (5 %)");
    }

    // 3. what exists in Home Assistant decides what is said
    {
      const ready = flatten(planOf(mk(withPlanSensors(base())).card));
      if (!/data-readiness=ready role="status">Overrides ready\./.test(ready)) bad.push("scripts, sensors present, switch on: the status is not 'Overrides ready.'");
      if (/not installed|guarded start path/i.test(ready.replace(/Partial protection only[^<]*/, ""))) bad.push("scripts present: a 'not installed' or 'guarded start path' message is shown");
      // 'Overrides ready.' is said only when nothing the controls rely on is missing or unreadable
      const gaps = flatten(planOf(mk(base()).card));
      if (!/data-readiness=ready_with_gaps role="status">Overrides only partly ready\. Not found: the effective-reserve sensor, the export-hold sensor\./.test(gaps)) bad.push("the two plan sensors absent: the status is not the ready-with-gaps line");
      if (gaps.includes("Overrides ready.") || gaps.includes("data-readiness=ready ")) bad.push("the two plan sensors absent: 'Overrides ready.' is still said");
      const oneGap = withPlanSensors(base());
      delete (oneGap as Record<string, unknown>)[SENSORS.export_hold];
      const oneGapText = flatten(planOf(mk(oneGap).card));
      if (!/data-readiness=ready_with_gaps role="status">Overrides only partly ready\. Not found: the export-hold sensor\./.test(oneGapText) || oneGapText.includes("Overrides ready.")) bad.push("only the export-hold sensor absent: not said, or 'Overrides ready.' is still said");
      // the stored plan revision cannot be read: the installed start script refuses every start, so 'Overrides ready.' must not be said
      for (const bit of ["unavailable", "2.5", "-1"]) {
        const norev = withPlanSensors(base());
        (norev as Record<string, unknown>)[HELPER_IDS.revision] = { state: bit };
        const norevText = flatten(planOf(mk(norev).card));
        if (!/data-readiness=revision_unreadable role="status">The stored plan revision (cannot be read|is not a whole number), so no override can be started\./.test(norevText)) bad.push("plan revision " + bit + ": the status does not say the revision cannot be used");
        if (norevText.includes("Overrides ready.")) bad.push("plan revision " + bit + ": 'Overrides ready.' is still said");
      }
      const off = base();
      (off as Record<string, unknown>)[HELPER_IDS.confirmed] = { state: "off" };
      const offText = flatten(planOf(mk(off).card));
      if (!offText.includes("Turn on the confirmation switch: override limits reviewed and confirmed.")) bad.push("switch off: the confirmation message is not shown");
      if (section(offText, "hold_battery").includes("data-choice=")) bad.push("switch off: a start is offered");
      const gone = flatten(planOf(mk(helperStates(planStates())).card));
      if (!gone.includes("The guarded scripts were not found") || !gone.includes("not installed")) bad.push("scripts absent: 'not installed' is not said");
      if (!gone.includes("data-readiness=not_installed") || gone.includes("data-readiness=ready")) bad.push("scripts absent: the status is not not_installed");
      if (gone.includes("data-choice=")) bad.push("scripts absent: a start is offered");
      // one script absent: the card says which one, in the readiness text (it is NOT 'not installed': that is said only when both are absent)
      const part = base();
      delete (part as Record<string, unknown>)[PLAN_CONTROL_IDS.start_script];
      const partText = flatten(planOf(mk(part).card));
      if (!partText.includes("Only part of the override package is installed: " + PLAN_CONTROL_IDS.start_script + " was not found, so overrides cannot be started or cancelled here.") || partText.includes("data-choice=")) bad.push("only the cancel script present: a start is offered or the absence is not said in the status text");
      if (!partText.includes("data-readiness=partial") || partText.includes("data-readiness=ready")) bad.push("only the cancel script present: the status is not partial");
      if (/not installed|The guarded scripts were not found/.test(partText.replace(/Partial protection only[^<]*/, ""))) bad.push("only the cancel script present: the generic 'not installed' sentence is shown");
      if (partText.includes('class="plan-readiness"')) bad.push("only the cancel script present: a readiness line is drawn next to the missing-scripts line");
      // the same the other way round: ONLY the cancel script deleted (the start script stays)
      const noCancel = base();
      delete (noCancel as Record<string, unknown>)[PLAN_CONTROL_IDS.cancel_script];
      const noCancelText = flatten(planOf(mk(noCancel).card));
      if (!noCancelText.includes("data-readiness=partial") || noCancelText.includes("data-readiness=ready") || noCancelText.includes("data-readiness=not_installed")) bad.push("only the start script present: the status is not partial");
      if (noCancelText.includes('class="plan-readiness"')) bad.push("only the start script present: a readiness line is drawn");
      if (noCancelText.includes("data-choice=")) bad.push("only the start script present: a start is offered");
      if (!noCancelText.includes("Only part of the override package is installed: " + PLAN_CONTROL_IDS.cancel_script + " was not found, so overrides cannot be started or cancelled here.")) bad.push("only the start script present: the missing cancel script is not named in the status text");
      if (/not installed|The guarded scripts were not found/.test(noCancelText.replace(/Partial protection only[^<]*/, ""))) bad.push("only the start script present: the generic 'not installed' sentence is shown");
      const unread = base();
      (unread as Record<string, unknown>)[HELPER_IDS.confirmed] = { state: "unavailable" };
      if (!flatten(planOf(mk(unread).card)).includes("cannot be read, so no override can be started")) bad.push("switch unreadable: not said");
      // the guarded Dump to Grid start
      const dumpCfg = { dump_to_grid: { ...BASE_CONFIG.dump_to_grid, guarded_start: GUARDED_START } };
      const noGuard = flatten(planOf(mk(base(), dumpCfg).card));
      if (!noGuard.includes("the guarded Dump to Grid start script")) bad.push("guarded Dump start named but absent: not said");
      const onlyGuard = flatten(planOf(mk(withPlanSensors(base()), dumpCfg).card));
      if (!/data-readiness=ready_with_gaps role="status">Overrides only partly ready\. Not found: the guarded Dump to Grid start script\./.test(onlyGuard) || onlyGuard.includes("Overrides ready.")) bad.push("only the guarded Dump start absent: not said as a gap, or 'Overrides ready.' is still said");
      const withGuard = base();
      (withGuard as Record<string, unknown>)[GUARDED_START] = { state: "off" };
      if (flatten(planOf(mk(withGuard, dumpCfg).card)).includes("the guarded Dump to Grid start script")) bad.push("guarded Dump start present: still reported missing");
      if (flatten(planOf(mk(base()).card)).includes("the guarded Dump to Grid start script")) bad.push("no guarded Dump start configured: reported missing");
      // the two plan sensors
      const noSensors = flatten(planOf(mk(base()).card));
      if (!noSensors.includes("Not found: the effective-reserve sensor, the export-hold sensor")) bad.push("sensors absent: not said");
      const withSensors = base();
      (withSensors as Record<string, unknown>)[SENSORS.effective_reserve] = { state: "5" };
      (withSensors as Record<string, unknown>)[SENSORS.export_hold] = { state: "clear" };
      if (flatten(planOf(mk(withSensors).card)).includes("Not found:")) bad.push("sensors present: still reported missing");
    }

    // 3b. the owner's reserve and the reserve ECCO's plan uses are never mistaken for one another: while an override record is held, or whenever the installed
    // effective-reserve sensor reads a figure other than the owner's, the owner's is labelled "Your reserve" and "Plan reserve now" stands beside it
    {
      const SOC = BASE_CONFIG.dump_to_grid.battery_soc;
      const line = (text: string): string => /data-reserve-line>(.*?)<\/p>/.exec(text.replace(/\s+/g, " "))?.[1]?.replace(/<[^>]*>/g, "").replace(/&middot;/g, "·").replace(/\s+/g, " ").trim() ?? "";
      // a running Prepare for power cut (reserve 80 over the owner's 5, battery at 40 %): the very case the owner met
      const run = withPlanSensors(base(), "80");
      (run as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "5" };
      (run as Record<string, unknown>)[SOC] = { state: "40" };
      running(run, "prepare_power_cut", 30, 600, 80);
      const runText = flatten(planOf(mk(run).card));
      const runPrep = section(runText, "prepare_power_cut");
      if (line(runPrep) !== "Your reserve 5 % · Plan reserve now 80 % · Power cut target 80 %") bad.push("a running Prepare for power cut: the reserve line is " + JSON.stringify(line(runPrep)));
      if (!/data-control-active>Active until /.test(runPrep)) bad.push("a running Prepare for power cut: 'Active until' is not shown");
      if (!runPrep.includes("The battery is at 40 percent, below the 80 percent reserve.")) bad.push("a running Prepare for power cut: the below-reserve sentence is not shown beside it");
      if (/Reserve now 5 %/.test(runPrep)) bad.push("a running Prepare for power cut: the owner's reserve is still labelled 'Reserve now'");
      if (!/data-summary="tomorrow">[^<]*Your reserve 5 %/.test(runText)) bad.push("a running Prepare for power cut: the Tomorrow's Plan summary does not say 'Your reserve 5 %'");
      if (!/data-reserve-plan>Plan reserve now 80 %</.test(runPrep)) bad.push("a running Prepare for power cut: the plan's reserve is not in its own labelled element");
      // while it is held the plan's figure may be unreadable: said, never guessed
      const noSensor = base();
      (noSensor as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "5" };
      running(noSensor, "prepare_power_cut", 30, 600, 80);
      const noSensorLine = line(section(flatten(planOf(mk(noSensor).card)), "prepare_power_cut"));
      if (noSensorLine !== "Your reserve 5 % · Plan reserve now unknown (the effective-reserve sensor was not found) · Power cut target 80 %") bad.push("a running Prepare for power cut, no sensor: the reserve line is " + JSON.stringify(noSensorLine));
      const dead = withPlanSensors(base(), "unavailable");
      running(dead, "prepare_power_cut", 30, 600, 80);
      if (!line(section(flatten(planOf(mk(dead).card)), "prepare_power_cut")).includes("Plan reserve now unknown (the effective-reserve sensor cannot be read)")) bad.push("a running Prepare for power cut, sensor unavailable: not said");
      const wild = withPlanSensors(base(), "150");
      running(wild, "prepare_power_cut", 30, 600, 80);
      if (!line(section(flatten(planOf(mk(wild).card)), "prepare_power_cut")).includes("Plan reserve now unknown (the effective-reserve sensor does not read a percentage from 0 to 100)")) bad.push("sensor 150: not taken as unknown");
      // any other held record counts as well: with the sensor equal to the owner's reserve the two figures are both shown (and equal)
      const hold = withPlanSensors(base(), "20");
      running(hold, "hold_battery", 30, 200);
      const holdLine = line(section(flatten(planOf(mk(hold).card)), "prepare_power_cut"));
      if (holdLine !== "Your reserve 20 % · Plan reserve now 20 % · Power cut target 80 %") bad.push("a running Hold battery: the reserve line is " + JSON.stringify(holdLine));
      // nothing running and the plan uses what the owner set: one figure, as before
      const calm = withPlanSensors(base(), "5");
      (calm as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "5" };
      const calmText = flatten(planOf(mk(calm).card));
      if (line(section(calmText, "prepare_power_cut")) !== "Reserve now 5 % · Power cut target 80 %" || calmText.includes("Plan reserve now") || calmText.includes("Your reserve 5 % · Plan")) bad.push("nothing running, sensor equal: the reserve line is " + JSON.stringify(line(section(calmText, "prepare_power_cut"))));
      // nothing running but the plan rounds the owner's 79.5 up to 80: both figures
      const round = withPlanSensors(base(), "80");
      (round as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "79.5" };
      const roundLine = line(section(flatten(planOf(mk(round).card)), "prepare_power_cut"));
      if (roundLine !== "Your reserve 79.5 % · Plan reserve now 80 % · Power cut target 80 %") bad.push("owner reserve 79.5, sensor 80: the reserve line is " + JSON.stringify(roundLine));
      // nothing running, no sensor: the owner's figure alone (the sensor is reported as not found in the status)
      const lone = base();
      (lone as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "5" };
      if (line(section(flatten(planOf(mk(lone).card)), "prepare_power_cut")) !== "Reserve now 5 % · Power cut target 80 %") bad.push("nothing running, no sensor: the reserve line changed");
      // the owner's reserve unknown while the sensor reads a figure: both, the owner's honestly unknown
      const unk = withPlanSensors(base(), "80");
      (unk as Record<string, unknown>)[PLAN_CONFIG.reserve] = { state: "unavailable" };
      const unkLine = line(section(flatten(planOf(mk(unk).card)), "prepare_power_cut"));
      if (!unkLine.startsWith("Your reserve unknown (") || !unkLine.includes("Plan reserve now 80 %")) bad.push("owner reserve unreadable, sensor 80: the reserve line is " + JSON.stringify(unkLine));
    }

    // 3c. the guarded view has working Start and Cancel controls, so the 'status only' line is gone from it; the records it describes carry a scoped note instead
    {
      const idle = flatten(planOf(mk(base()).card));
      if (idle.includes("Status only:") || idle.includes("nothing in this view starts, cancels or enforces an override")) bad.push("the guarded view still says 'Status only: nothing in this view starts, cancels or enforces an override'");
      if (idle.includes("data-records-note")) bad.push("no record is held: the records note is shown");
      const runs = base();
      running(runs, "hold_battery", 30, 200);
      const runsText = flatten(planOf(mk(runs).card));
      if (runsText.includes("Status only:") || runsText.includes("nothing in this view starts, cancels or enforces an override")) bad.push("a record is held: the guarded view still says 'Status only: nothing in this view ...'");
      const noteAt = runsText.indexOf("data-records-note");
      if (noteAt < 0 || !/data-records-note>This list only shows the records Home Assistant holds: nothing in it starts, cancels or enforces an override\. Start and Cancel are under Quick overrides\./.test(runsText)) bad.push("a record is held: the records note is missing or reworded");
      // the note stands right after the list of records it is about, inside the limits fold
      const rowAt = runsText.lastIndexOf("data-override=", noteAt);
      if (noteAt >= 0 && (rowAt < 0 || runsText.slice(rowAt, noteAt).includes("data-override-policy") || depthAt(runsText, noteAt) < 1)) bad.push("the records note is not attached to the records block");
      if (noteAt >= 0 && runsText.indexOf('data-fold="limits"') > noteAt) bad.push("the records note is outside the limits fold");
    }

    // 4. the compact layout: folded by default, one-line summaries, the limitation visible, the section's old content still there
    {
      const states = base();
      const text = flatten(planOf(mk(states).card));
      for (const f of ["tomorrow", "limits", "tou"]) {
        if (!text.includes('data-fold="' + f + '"')) bad.push("compact: the " + f + " fold is missing");
        if (!new RegExp('data-summary="' + f + '">[^<]+<').test(text)) bad.push("compact: the " + f + " summary line is empty or missing");
      }
      if (/<details[^>]*\sopen[\s>=]/.test(text)) bad.push("compact: a fold is open by default");
      const at = text.indexOf("data-plan-limitation");
      if (at < 0 || depthAt(text, at) !== 0) bad.push("compact: the limitation sentence is inside a fold");
      if (!text.includes("Partial protection only: the dongle's own Start button")) bad.push("compact: the limitation sentence is missing");
      for (const must of ["Tomorrow's Plan", "Six-slot TOU timeline", "Why?", "Planned settings", "Quick overrides", "Hold battery", "Skip tonight", "Prepare for power cut", "Slot 1"]) if (!text.includes(must)) bad.push("compact: " + must + " is gone");
      const startAt = text.indexOf("data-control=hold_battery");
      if (startAt < 0 || depthAt(text, startAt) !== 0) bad.push("compact: the override start controls are inside a fold");
      const figuresAt = text.indexOf('class="plan-figures"');
      if (figuresAt < 0 || depthAt(text, figuresAt) < 1) bad.push("compact: the figures are not folded");
      const slotAt = text.indexOf("data-slot=");
      if (slotAt < 0 || depthAt(text, slotAt) < 1) bad.push("compact: the six slots are not folded");
    }
    // 5. no plan helpers: the read-only section keeps its former markup (no fold)
    {
      const text = flatten(planOf(mk(planStates()).card));
      if (text.includes("data-fold=") || text.includes("plan-compact")) bad.push("no helpers: the read-only section changed");
    }
  } finally {
    Date.now = realNow;
  }
  return bad;
}
