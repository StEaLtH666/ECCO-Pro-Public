// The plan section's start and cancel controls (Lit). Shown only when the plan helper entities are configured (and the card has
// `show_plan: true`). Every button hands ONE prebuilt service call (planActions.ts: `script.turn_on` on a guarded script) to the callback
// the card gives; nothing here names a service, a helper to write, a charge, a discharge or an inverter entity. The card double-checks
// each call against the same allow-list before it sends it. Every value reaches the DOM through a Lit text binding, never innerHTML.
//
// What the owner sees, in order: what each override does (it holds back ECCO's own export starts and, for Prepare for power cut, sets the
// reserve ECCO's plan uses; it never charges and never changes the inverter's own reserve),
// the choices the owner's limits allow (their default, chips inside the shortest and longest length, "until 07:00"), the running
// override with its expiry and a Cancel, why a start is not offered, and the guarded script's own last answer, refusals included.
// Owner decision r15: the same Cancel is also offered for a kind that Home Assistant holds only through its absolute epoch record, or whose
// record cannot be read ("Held by Home Assistant"), and after a Cancel the card reads back the plan revision and BOTH records and says
// plainly whether it is confirmed, still pending, or NOT confirmed (controlsModel.ts decides; this file only draws it).
import { css, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import { buildControlsVM, noteCall } from "./controlsModel.ts";
import type { CancelLedger, ControlsVM, KindControlVM } from "./controlsModel.ts";
import { localClockContext } from "./clock.ts";
import type { PlanServiceCall } from "./planActions.ts";
import type { ControlsRenderer } from "./view.ts";

const KIND_BLURB: Record<string, string> = {
  hold_battery: "Holds back ECCO's own scheduled and guarded export starts. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",
  skip_tonight: "Holds back ECCO's own scheduled and guarded export starts tonight. It does not stop the battery charging or discharging, and it does not stop the dongle's own Start button.",
  prepare_power_cut: "Sets the reserve ECCO's plan uses to the larger of your own reserve and the power-cut reserve, and holds back ECCO's own export starts. It does not change the inverter's own reserve and does not stop the house using the battery. It does not charge the battery.",
};

// One short line per kind, always visible (the longer KIND_BLURB sits behind "What it does", closed by default).
const KIND_SHORT: Record<string, string> = {
  hold_battery: "Holds back ECCO's own export starts.",
  skip_tonight: "Holds back ECCO's own export starts tonight.",
  prepare_power_cut: "Raises the reserve ECCO's plan uses and holds back its export starts. Never charges.",
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
        ${k.activeText
          ? k.held
            ? html`<span class="plan-setting-value" data-control-held>${k.activeText}</span>`
            : html`<span class="plan-setting-value" data-control-active>${k.activeText}</span>`
          : nothing}
      </div>
      <p class="plan-reason plan-effect" data-effect>${KIND_SHORT[k.kind] ?? ""}</p>
      ${k.reserve
        ? html`<p class="plan-reason plan-reserve-line" data-reserve-line><span data-reserve-now>${k.reserve.nowText}</span>${k.reserve.planText !== null ? html` &middot; <span data-reserve-plan>${k.reserve.planText}</span>` : nothing} &middot; <span data-reserve-target>${k.reserve.targetText}</span></p>`
        : nothing}
      ${k.note ? html`<p class="plan-reason" data-control-note role="note">${k.note}</p>` : nothing}
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
      <details class="plan-why plan-fold plan-kind-more" data-fold="kind-more">
        <summary>What ${k.label} does</summary>
        <p class="plan-reason">${KIND_BLURB[k.kind] ?? ""}</p>
      </details>
      ${k.readback ? html`<p class="plan-reason plan-readback" data-readback=${k.readback.outcome} role="status">${k.readback.text}</p>` : nothing}
    </div>
  `;
}

export function controlsView(vm: ControlsVM, dispatch: (call: PlanServiceCall) => void): TemplateResult {
  return html`
    <div class="plan-controls" data-block="controls">
      <div class="plan-controls-head">
        <h3 class="plan-heading">Quick overrides</h3>
        ${vm.readiness.kind !== "not_installed" && vm.readiness.kind !== "partial" ? html`<span class="plan-readiness" data-readiness=${vm.readiness.kind} role="status">${vm.readiness.text}</span>` : nothing}
      </div>
      <details class="plan-why plan-fold plan-intro" data-fold="overrides-intro">
        <summary>What quick overrides do</summary>
        <p class="plan-reason">They hold back ECCO's own export starts and, for Prepare for power cut, set the reserve ECCO's plan uses. They do not change the inverter's own reserve or any inverter setting, do not stop the house using the battery and never charge it. Home Assistant checks every one against your limits again and may refuse it.</p>
      </details>
      <p class="plan-reason plan-limitation" data-plan-limitation role="note">${START_BUTTON_LIMITATION}</p>
      ${vm.missingScripts.length
        ? html`<p class="plan-reason" data-controls-missing data-readiness=${vm.readiness.kind}>${vm.readiness.kind === "partial" ? vm.readiness.text : "The guarded scripts were not found (" + vm.missingScripts.join(", ") + "), so the overrides are not installed here and no override can be started or cancelled."}</p>`
        : vm.kinds.map((k) => kindView(k, dispatch))}
      ${vm.lastResult ? html`<p class="plan-reason plan-result" data-plan-result role="status">Last answer: ${vm.lastResult}</p>` : nothing}
    </div>
  `;
}

/**
 * The Cancel clicks of this page, remembered so that the next states can be read back against them (owner decision r15). It holds the plan revision
 * and the script's answer the card had seen when the owner pressed Cancel, nothing else; a reload forgets it, and the card then makes no claim.
 */
const cancelLedger: CancelLedger = {};

/** The renderer the card hands to the plan section. `nothing` when the plan helper entities are not configured. */
export function renderPlanControls(send: (call: PlanServiceCall) => void): ControlsRenderer {
  return ({ snap, states, nowMs, guardedStart }) => {
    const vm = buildControlsVM({ snap, states, nowMs, clock: localClockContext(nowMs), cancels: cancelLedger, guardedStart });
    return vm
      ? controlsView(vm, (call) => {
          noteCall(cancelLedger, call, vm.lastResult);
          send(call);
        })
      : nothing;
  };
}

export const controlStyles = css`
  .plan-controls {
    margin-top: 8px;
    min-width: 0;
  }
  .plan-controls-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 10px;
  }
  .plan-controls-head .plan-heading {
    margin: 0;
  }
  .plan-readiness {
    font-size: 12px;
    font-weight: 600;
    color: var(--eaa-ok);
  }
  .plan-readiness[data-readiness="needs_confirmation"],
  .plan-readiness[data-readiness="confirmation_unreadable"],
  .plan-readiness[data-readiness="limits_unusable"],
  .plan-readiness[data-readiness="ready_with_gaps"],
  .plan-readiness[data-readiness="revision_unreadable"] {
    color: var(--eaa-warning);
  }
  .plan-effect,
  .plan-reserve-line {
    margin: 2px 0 0;
  }
  .plan-reserve-line {
    font-weight: 600;
    color: inherit;
  }
  .plan-kind-more,
  .plan-intro {
    margin-top: 2px;
    border-top: 0;
  }
  .plan-kind-more > summary,
  .plan-intro > summary {
    min-height: 28px;
    font-size: 12px;
    font-weight: 600;
    color: var(--eaa-text-muted);
  }
  .plan-control {
    padding: 6px 0;
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
  .plan-readback[data-readback="confirmed"] {
    color: var(--eaa-ok);
  }
  .plan-readback[data-readback="not_confirmed"] {
    color: var(--eaa-fault);
  }
`;
