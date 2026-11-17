// Plan views (Lit). Every value reaches the DOM through a Lit text binding, never innerHTML. There is no event handler, no button and no
// service call in this file: the views only display. The start and cancel controls are built elsewhere (controls.ts) and handed in by the
// card as a renderer; with none given the section is exactly the read-only view of stage 2. See present.ts for every wording.
import { css, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import type { StatesLike } from "./adapter.ts";
import { buildPlanSnapshotWithHelpers } from "./helpers.ts";
import type { PlanSnapshotWithHelpers } from "./helpers.ts";
import { presentPlan } from "./present.ts";
import type { Chip, FigureVM, OverrideBlockVM, OverrideRowVM, PlanVM, SettingRowVM, SlotVM } from "./present.ts";
import type { EccoEnergyActionsCardConfig } from "../config";

function chip(c: Chip): TemplateResult {
  return html`<span class="plan-chip chip-${c.kind.toLowerCase()}" title=${c.meaning}><ha-icon icon=${c.icon} aria-hidden="true"></ha-icon><span class="plan-chip-text">${c.label}</span></span>`;
}

function figure(f: FigureVM): TemplateResult {
  return html`
    <div class="plan-figure ${f.known ? "" : "is-unknown"}" data-figure=${f.key}>
      <dt>${f.label}</dt>
      <dd>
        <span class="plan-figure-value">${f.text}</span>
        ${f.note ? html`<span class="plan-note">${f.note}</span>` : nothing}
        ${chip(f.chip)}
        ${f.known ? nothing : html`<span class="plan-reason">${f.reason}</span>`}
      </dd>
    </div>
  `;
}

function settingRow(r: SettingRowVM): TemplateResult {
  return html`
    <li class="plan-setting ${r.known ? "" : "is-unknown"}" data-setting=${r.path}>
      <span class="plan-setting-label">${r.label}</span>
      <span class="plan-setting-value">${r.text}</span>
      ${chip(r.chip)}
      ${r.known ? r.remarks.map((m) => html`<span class="plan-reason">${m}</span>`) : html`<span class="plan-reason">${r.reason}</span>`}
    </li>
  `;
}

function overrideRow(r: OverrideRowVM): TemplateResult {
  return html`
    <li class="plan-setting" data-override=${r.kind}>
      <span class="plan-setting-label">${r.label}</span>
      <span class="plan-setting-value">${r.untilText}</span>
      <span class="plan-note">${r.countdownText}</span>
      <span class="plan-reason">${r.effectText}</span>
      ${r.belowReserve ? html`<span class="plan-reason plan-below-reserve" data-below-reserve role="note">${r.belowReserve}</span>` : nothing}
    </li>
  `;
}

/** Shown only when the proposed plan helper entities exist: the override limits, the stored revision and any active override. */
function overrideBlock(b: OverrideBlockVM): TemplateResult {
  return html`
    <div class="plan-override-block" data-block="overrides">
      ${b.rows.length ? html`<ul class="plan-settings">${b.rows.map(overrideRow)}</ul>` : nothing}
      <p class="plan-reason" data-override-policy=${b.policyOk ? "ok" : "unusable"}>${b.policyLine}</p>
      ${b.reasons.length ? html`<ul class="plan-reasons">${b.reasons.map((r) => html`<li>${r}</li>`)}</ul>` : nothing}
      ${b.warnings.length ? html`<ul class="plan-reasons">${b.warnings.map((r) => html`<li>${r}</li>`)}</ul>` : nothing}
      ${b.problems.length ? html`<ul class="plan-reasons" data-override-problems>${b.problems.map((r) => html`<li>${r}</li>`)}</ul>` : nothing}
      ${b.missing.length ? html`<p class="plan-reason">Plan helper entities not found: ${b.missing.join(", ")}.</p>` : nothing}
      ${b.proposed.length
        ? html`
            <details class="plan-why">
              <summary>Proposed values (not in use)</summary>
              <ul>${b.proposed.map((p) => html`<li>${p}</li>`)}</ul>
            </details>
          `
        : nothing}
      <p class="plan-reason">${b.revisionText}</p>
      <p class="plan-reason">${b.note}</p>
    </div>
  `;
}

function slot(s: SlotVM): TemplateResult {
  return html`
    <li class="plan-slot ${s.mismatch ? "is-mismatch" : ""}" data-slot=${s.index}>
      <div class="plan-slot-head">
        <span class="plan-slot-name">Slot ${s.index}</span>
        <span class="plan-slot-range">${s.rangeText}</span>
        ${chip(s.chip)}
      </div>
      <div class="plan-slot-line"><span class="plan-slot-key">Intended</span> ${s.intendedText} <span class="plan-note">${s.originText}</span></div>
      <div class="plan-slot-line"><span class="plan-slot-key">Inverter</span> ${s.inverterText ?? "not read"}</div>
      ${s.mismatch ? html`<p class="plan-mismatch" role="note"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon><span>${s.mismatch}</span></p>` : nothing}
    </li>
  `;
}

/** The section's start and cancel controls, built by the card (controls.ts) from the snapshot the section was built from. */
export type ControlsRenderer = (ctx: { snap: PlanSnapshotWithHelpers; states: StatesLike; nowMs: number }) => TemplateResult | typeof nothing;

/** Everything inside the section. Kept apart so the read-only section's markup stays byte for byte what it was before the controls existed. */
function planBody(vm: PlanVM, controls: TemplateResult | typeof nothing, guarded: boolean): TemplateResult {
  const tou = vm.tou;
  const badge = guarded
    ? html`<span class="plan-badge"><ha-icon icon="mdi:shield-check-outline" aria-hidden="true"></ha-icon>Guarded controls</span>`
    : html`<span class="plan-badge"><ha-icon icon="mdi:eye-outline" aria-hidden="true"></ha-icon>Read only</span>`;
  return html`
      <h2 class="plan-title">Plan ${badge}</h2>
      <p class="plan-statusline" role="status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon><span>${vm.statusLine}</span></p>

      <div class="plan-block" data-block="tomorrow">
        <h3 class="plan-heading">Tomorrow's Plan</h3>
        ${vm.adviceNote ? html`<p class="plan-reason plan-advice-note">${vm.adviceNote}</p>` : nothing}
        <dl class="plan-figures">${vm.figures.map(figure)}</dl>
        <details class="plan-why">
          <summary>Why?</summary>
          <ul>${vm.why.map((w) => html`<li data-origin=${w.origin}>${w.text}</li>`)}</ul>
        </details>
        <details class="plan-why plan-settings-details">
          <summary>Planned settings</summary>
          <ul class="plan-settings">${vm.settings.map(settingRow)}</ul>
        </details>
        <p class="plan-overrides">${vm.overridesLine}</p>${vm.overrideBlock ? overrideBlock(vm.overrideBlock) : nothing}${controls}
      </div>

      <div class="plan-block" data-block="tou">
        <h3 class="plan-heading">Six-slot TOU timeline${tou.statusText ? html` <span class="plan-note">${tou.statusText}</span>` : nothing}</h3>
        <p class="plan-tou-headline">${tou.headline}</p>
        ${tou.reasons.length ? html`<ul class="plan-reasons">${tou.reasons.map((r) => html`<li>${r}</li>`)}</ul>` : nothing}
        ${tou.slots.length
          ? html`
              <div class="plan-bar" aria-hidden="true">
                ${tou.slots.map((s) => html`<span class="plan-seg ${s.mismatch ? "is-mismatch" : ""}" style=${"flex-grow:" + s.spanMin}>${s.index}</span>`)}
              </div>
              <ol class="plan-slots">${tou.slots.map(slot)}</ol>
            `
          : nothing}
      </div>
    `;
}

/** The whole section for a plan view model; `controls` is only passed when the plan helpers are configured and the card supplied them. */
export function renderPlanVM(vm: PlanVM, controls: TemplateResult | typeof nothing = nothing): TemplateResult {
  if (controls !== nothing) {
    return html`
    <section class="plan-section" aria-label="Plan, with guarded controls">${planBody(vm, controls, true)}</section>
  `;
  }
  return html`
    <section class="plan-section" aria-label="Plan, read only">${planBody(vm, nothing, false)}</section>
  `;
}

/**
 * The card's entry point. Returns `nothing` unless the config flag is exactly `true`; in that case it does not touch hass at all,
 * so a card with the flag off reads no extra entity and renders exactly as before.
 */
export function renderPlanSection(config: EccoEnergyActionsCardConfig | undefined, states: StatesLike | undefined, nowMs?: number, controls?: ControlsRenderer): TemplateResult | typeof nothing {
  if (!config || config.show_plan !== true) return nothing;
  // The clock is read only here, in the entry point, to judge stored override expiries; the card passes nothing, tests pass a moment.
  const at = typeof nowMs === "number" && Number.isFinite(nowMs) ? nowMs : Date.now();
  const snap = buildPlanSnapshotWithHelpers(config, states ?? {}, Math.floor(at / 60000));
  const vm = presentPlan(snap);
  return renderPlanVM(vm, controls ? controls({ snap, states: states ?? {}, nowMs: at }) : nothing);
}

export const planStyles = css`
  .plan-section {
    margin-top: 18px;
    padding: 14px;
    border-radius: 16px;
    background: var(--eaa-surface);
    border: 1px solid var(--eaa-border);
    min-width: 0;
  }
  .plan-title {
    margin: 0 0 8px;
    font-size: 16px;
    font-weight: 700;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .plan-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid var(--eaa-border);
    color: var(--eaa-text-muted);
  }
  .plan-badge ha-icon,
  .plan-statusline ha-icon,
  .plan-mismatch ha-icon {
    --mdc-icon-size: 16px;
    flex: 0 0 auto;
  }
  .plan-statusline {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    margin: 0 0 12px;
    font-size: 13px;
    color: var(--eaa-text-muted);
    overflow-wrap: anywhere;
  }
  .plan-block {
    margin-top: 12px;
    min-width: 0;
  }
  .plan-heading {
    margin: 0 0 6px;
    font-size: 14px;
    font-weight: 700;
  }
  .plan-figures {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 10px;
    margin: 0;
  }
  .plan-figure {
    min-width: 0;
    padding: 8px 10px;
    border-radius: 12px;
    border: 1px solid var(--eaa-border);
  }
  .plan-figure dt {
    font-size: 12px;
    color: var(--eaa-text-muted);
  }
  .plan-figure dd {
    margin: 2px 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
    min-width: 0;
  }
  .plan-figure-value {
    font-size: 18px;
    font-weight: 700;
  }
  .plan-figure.is-unknown .plan-figure-value {
    font-size: 15px;
    font-style: italic;
    color: var(--eaa-text-muted);
  }
  .plan-note {
    font-size: 11px;
    color: var(--eaa-text-muted);
  }
  .plan-reason {
    flex-basis: 100%;
    font-size: 12px;
    color: var(--eaa-text-muted);
    overflow-wrap: anywhere;
  }
  .plan-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    border: 1px solid currentColor;
    white-space: nowrap;
  }
  .plan-chip ha-icon {
    --mdc-icon-size: 14px;
  }
  .chip-proposed { color: var(--eaa-schedule); }
  .chip-armed { color: var(--eaa-armed); }
  .chip-executing { color: var(--eaa-accent); }
  .chip-applied_verified { color: var(--eaa-ok); }
  .chip-mismatch { color: var(--eaa-fault); }
  .chip-unknown { color: var(--eaa-text-muted); border-style: dashed; }
  .plan-why {
    margin-top: 10px;
    font-size: 13px;
  }
  .plan-why summary {
    cursor: pointer;
    min-height: 36px;
    display: flex;
    align-items: center;
    font-weight: 600;
  }
  .plan-why ul,
  .plan-reasons,
  .plan-slots,
  .plan-settings {
    margin: 4px 0 0;
    padding-left: 18px;
  }
  .plan-why li,
  .plan-reasons li {
    overflow-wrap: anywhere;
    margin-bottom: 4px;
  }
  .plan-settings,
  .plan-slots {
    list-style: none;
    padding-left: 0;
  }
  .plan-setting {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
    padding: 6px 0;
    border-top: 1px solid var(--eaa-border);
  }
  .plan-setting-label {
    flex: 1 1 160px;
    min-width: 0;
  }
  .plan-setting-value {
    font-weight: 600;
  }
  .plan-setting.is-unknown .plan-setting-value {
    font-style: italic;
    color: var(--eaa-text-muted);
  }
  .plan-overrides {
    margin: 10px 0 0;
    font-size: 12px;
    color: var(--eaa-text-muted);
  }
  .plan-tou-headline {
    margin: 0 0 6px;
    font-size: 13px;
    overflow-wrap: anywhere;
  }
  .plan-reasons {
    font-size: 12px;
    color: var(--eaa-warning);
  }
  .plan-bar {
    display: flex;
    gap: 2px;
    margin: 8px 0;
    height: 24px;
  }
  .plan-seg {
    flex-basis: 0;
    min-width: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    border-radius: 6px;
    background: color-mix(in srgb, var(--eaa-accent) 22%, transparent);
    border: 1px solid var(--eaa-border);
  }
  .plan-seg.is-mismatch {
    background: color-mix(in srgb, var(--eaa-fault) 28%, transparent);
    border-style: dashed;
  }
  .plan-slot {
    padding: 8px 10px;
    margin-bottom: 8px;
    border-radius: 12px;
    border: 1px solid var(--eaa-border);
    font-size: 13px;
    min-width: 0;
  }
  .plan-slot.is-mismatch {
    border-color: var(--eaa-fault);
    border-style: dashed;
  }
  .plan-slot-head {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
  }
  .plan-slot-name {
    font-weight: 700;
  }
  .plan-slot-key {
    display: inline-block;
    min-width: 64px;
    color: var(--eaa-text-muted);
  }
  .plan-slot-line {
    margin-top: 2px;
    overflow-wrap: anywhere;
  }
  .plan-mismatch {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    margin: 6px 0 0;
    font-size: 12px;
    color: var(--eaa-fault);
    overflow-wrap: anywhere;
  }
`;
