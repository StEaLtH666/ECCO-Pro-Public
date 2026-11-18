// The plan section's start and cancel controls (Lit). Shown only when the plan helper entities are configured (and the card has
// `show_plan: true`). Every button hands ONE prebuilt service call (planActions.ts: `script.turn_on` on a guarded script) to the callback
// the card gives; nothing here names a service, a helper to write, a charge, a discharge or an inverter entity. The card double-checks
// each call against the same allow-list before it sends it. Every value reaches the DOM through a Lit text binding, never innerHTML.
//
// What the owner sees, in order: what each override does (it holds back ECCO's own export starts and, for Prepare for power cut, sets the
// reserve ECCO's plan uses; it never charges and never changes the inverter's own reserve),
// the choices the owner's limits allow (their default, chips inside the shortest and longest length, "until 07:00"), the running
// override with its expiry and a Cancel, why a start is not offered, and the guarded script's own last answer, refusals included.
import { css, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import { buildControlsVM } from "./controlsModel.ts";
import type { ControlsVM, KindControlVM } from "./controlsModel.ts";
import { localClockContext } from "./clock.ts";
import type { PlanServiceCall } from "./planActions.ts";
import type { ControlsRenderer } from "./view.ts";

const KIND_BLURB: Record<string, string> = {
  hold_battery: "Holds back ECCO's own scheduled and guarded export starts. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",
  skip_tonight: "Holds back ECCO's own scheduled and guarded export starts tonight. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",
  prepare_power_cut: "Sets the reserve ECCO's plan uses to the larger of your own reserve and the power-cut reserve, and holds back ECCO's own export starts. It does not change the inverter's own reserve and does not stop the house using the battery. It does not charge the battery.",
};

// The stated limitation of Stage 3 (release gate RG-ST3), always visible beside the controls. Plain text only: it adds no button, handler or
// service call. The same sentence stands in the card README, the plan-core README and the Stage 3 package headers; a static test
// (home-assistant/tests/test_ecco_stage3_limitation.py) requires it, word for word, in each of those places and in the built bundle.
export const START_BUTTON_LIMITATION =
  "Partial protection only: the dongle's own Start button (the Dump to Grid or Free Power start entity) can still be pressed from Home Assistant or by an assistant. These overrides and the reserve protect ECCO's own starts and this card, not an administrator, an assistant or a press of the dongle's own button, and their helpers are plain helpers that an administrator or assistant can write. Binding the Start button needs a firmware gate (a flash, approved separately).";

function kindView(k: KindControlVM, dispatch: (call: PlanServiceCall) => void): TemplateResult {
  return html`
    <div class="plan-control" data-control=${k.kind}>
      <div class="plan-control-head">
        <span class="plan-setting-label">${k.label}</span>
        ${k.activeText ? html`<span class="plan-setting-value" data-control-active>${k.activeText}</span>` : nothing}
      </div>
      <p class="plan-reason">${KIND_BLURB[k.kind] ?? ""}</p>
      ${k.belowReserve ? html`<p class="plan-reason plan-below-reserve" data-below-reserve role="note">${k.belowReserve}</p>` : nothing}
      ${k.blockedReason ? html`<p class="plan-reason" data-control-blocked>${k.blockedReason}</p>` : nothing}
      <div class="plan-control-buttons">
        ${k.choices.length ? html`<span class="plan-note">${k.active ? "Start again for" : "Start for"}</span>` : nothing}
        ${k.choices.map(
          (c) => html`<button type="button" class="plan-control-btn ${c.isDefault ? "is-default" : ""}" data-choice=${c.id}
            aria-label=${k.label + ": start for " + c.label} @click=${() => dispatch(c.call)}>${c.label}</button>`,
        )}
        ${k.cancel
          ? html`<button type="button" class="plan-control-btn is-cancel" data-cancel aria-label=${"Cancel " + k.label} @click=${() => dispatch(k.cancel as PlanServiceCall)}>Cancel</button>`
          : nothing}
      </div>
    </div>
  `;
}

export function controlsView(vm: ControlsVM, dispatch: (call: PlanServiceCall) => void): TemplateResult {
  return html`
    <div class="plan-controls" data-block="controls">
      <h3 class="plan-heading">Quick overrides</h3>
      <p class="plan-reason">They hold back ECCO's own export starts and, for Prepare for power cut, set the reserve ECCO's plan uses. They do not change the inverter's own reserve or any inverter setting, do not stop the house using the battery and never charge it. Home Assistant checks every one against your limits again and may refuse it.</p>
      <p class="plan-reason plan-limitation" data-plan-limitation role="note">${START_BUTTON_LIMITATION}</p>
      ${vm.missingScripts.length
        ? html`<p class="plan-reason" data-controls-missing>The guarded scripts were not found (${vm.missingScripts.join(", ")}), so no override can be started or cancelled here.</p>`
        : vm.kinds.map((k) => kindView(k, dispatch))}
      ${vm.lastResult ? html`<p class="plan-reason plan-result" data-plan-result role="status">Last answer: ${vm.lastResult}</p>` : nothing}
    </div>
  `;
}

/** The renderer the card hands to the plan section. `nothing` when the plan helper entities are not configured. */
export function renderPlanControls(dispatch: (call: PlanServiceCall) => void): ControlsRenderer {
  return ({ snap, states, nowMs }) => {
    const vm = buildControlsVM({ snap, states, nowMs, clock: localClockContext(nowMs) });
    return vm ? controlsView(vm, dispatch) : nothing;
  };
}

export const controlStyles = css`
  .plan-controls {
    margin-top: 12px;
    min-width: 0;
  }
  .plan-control {
    padding: 8px 0;
    border-top: 1px solid var(--eaa-border);
    min-width: 0;
  }
  .plan-control-head {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    align-items: center;
  }
  .plan-control-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 8px;
    align-items: center;
    margin-top: 4px;
  }
  .plan-control-btn {
    min-height: 40px;
    min-width: 44px;
    padding: 6px 14px;
    border-radius: 999px;
    border: 1px solid var(--eaa-border);
    background: transparent;
    color: inherit;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .plan-control-btn.is-default {
    border-color: var(--eaa-accent);
  }
  .plan-control-btn.is-cancel {
    border-color: var(--eaa-fault);
    color: var(--eaa-fault);
  }
  .plan-control-btn:focus-visible {
    outline: 2px solid var(--eaa-accent);
    outline-offset: 2px;
  }
  .plan-below-reserve,
  .plan-limitation {
    color: var(--eaa-warning);
  }
  .plan-result {
    margin-top: 8px;
  }
`;
