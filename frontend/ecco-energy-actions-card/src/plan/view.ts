// Read-only plan views (Lit). Every value reaches the DOM through a Lit text binding, never innerHTML. There is no event handler,
// no button and no service call in this file: the views only display. See present.ts for every wording.
import { css, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import { buildPlanSnapshot } from "./adapter.ts";
import type { StatesLike } from "./adapter.ts";
import { presentPlan } from "./present.ts";
import type { Chip, FigureVM, PlanVM, SettingRowVM, SlotVM } from "./present.ts";
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

/** The whole read-only section for a plan view model. */
export function renderPlanVM(vm: PlanVM): TemplateResult {
  const tou = vm.tou;
  return html`
    <section class="plan-section" aria-label="Plan, read only">
      <h2 class="plan-title">Plan <span class="plan-badge"><ha-icon icon="mdi:eye-outline" aria-hidden="true"></ha-icon>Read only</span></h2>
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
        <p class="plan-overrides">${vm.overridesLine}</p>
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
    </section>
  `;
}

/**
 * The card's entry point. Returns `nothing` unless the config flag is exactly `true`; in that case it does not touch hass at all,
 * so a card with the flag off reads no extra entity and renders exactly as before.
 */
export function renderPlanSection(config: EccoEnergyActionsCardConfig | undefined, states: StatesLike | undefined): TemplateResult | typeof nothing {
  if (!config || config.show_plan !== true) return nothing;
  const vm = presentPlan(buildPlanSnapshot(config, states ?? {}));
  return renderPlanVM(vm);
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
