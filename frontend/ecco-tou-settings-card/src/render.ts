// Pure HTML-string rendering for the ECCO TOU Settings card.
//
// Every dynamic value goes through esc(). Interactive elements carry a data-action the element handles; a control that is
// not allowed right now is rendered `disabled aria-disabled="true"` with its reason in the title and beside it (never by
// colour alone). Nothing here calls Home Assistant: this module builds strings.
import {
  ACK_PHRASE,
  APPLY_SPACING_S,
  EDITABLE,
  POWER_MAX_W,
  POWER_MIN_W,
  POWER_STEP_W,
  SETTING_LABEL,
  SETTING_REGISTER_BASE,
  START_TIME_LOCKED_TEXT,
  displayValue,
  formatAge,
  formatCountdown,
  phraseFor,
  planMatchesDraft,
  refusalHint,
  validateDraft,
} from "./model.ts";
import type { Context } from "./model.ts";
import type { CardConfig, Draft, EditableSetting, EditorView, Eligibility, Plan, SlotView, StatesLike } from "./types.ts";

/** For the panel's change key: a numeric draft value is reduced to its validity class, so typing digits does not rewrite
 *  the panel until the value becomes valid / invalid / unchanged, and the source draft keeps its word (buttons, no caret). */
function maskValue(input: PanelInput): string {
  const d = input.draft;
  if (!d) return "";
  if (d.setting === "charge_source") return d.value;
  const v = input.slots[d.slot - 1];
  if (!v) return "";
  const check = validateDraft(d, v, input.ctx);
  return check.allowed ? "valid" : check.reason;
}

/** The reviewed slot's current eligibility for the plan's setting (P1); a start-time plan is never eligible here. */
export function planSlotEligibility(plan: Plan, slots: SlotView[]): Eligibility {
  const v = slots[plan.slot - 1];
  if (!v) return { allowed: false, reason: "slot not shown" };
  if (plan.setting === "start_time") return { allowed: false, reason: "start times are not editable here" };
  return v.eligibility[plan.setting];
}

export function esc(v: unknown): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export interface SentInfo {
  kind: "review" | "apply" | "acknowledge";
  ageSeconds: number;
}

export interface PanelInput {
  config: CardConfig;
  states: StatesLike;
  editor: EditorView;
  slots: SlotView[];
  ctx: Context;
  draft: Draft | null;
  typed: string;
  ackTyped: string;
  sent: SentInfo | null;
  /** Home Assistant offered a service function (otherwise the card is read-only). */
  canCall: boolean;
  startInfo: boolean;
  lastError: string | null;
  nowMs: number;
  powerLabel: string;
  touEnabled: string;
  configAgeText: string;
}

export function renderShell(title: string, styles: string, footer: string): string {
  return `<style>${styles}</style>
<ha-card>
<div class="card">
<div class="hdr"><div class="title">${esc(title)}</div><div data-region="badges"></div></div>
<div data-region="status" aria-live="polite"></div>
<div data-region="slots"></div>
<div data-region="panel"></div>
<p class="small foot">${esc(footer)}</p>
</div>
</ha-card>`;
}

export function renderBadges(input: PanelInput): string {
  return `<span class="badge muted">TOU master ${esc(input.touEnabled)}</span> <span class="badge muted" title="The saved-profile match and the shadow latch are read by the editor's gate, not by this card; the Safety view shows them.">Saved profile and shadow: Safety view</span>`;
}

export function renderStatus(input: PanelInput): string {
  const e = input.editor;
  const first = e.blockers[0];
  let cls = "status";
  let word: string;
  let detail = "";
  if (e.state === "UNAVAILABLE") {
    cls += " lock";
    word = "Editor unavailable";
    detail = `missing: ${e.missing.join(", ")}`;
  } else if (!input.canCall) {
    cls += " block";
    word = "Read-only view";
    detail = "Home Assistant offered no service interface to this card; nothing can be reviewed or applied from here.";
  } else if (first) {
    cls += first.code === "locked" ? " lock" : " block";
    word = first.text;
    if (e.blockers.length > 1) detail = `and ${e.blockers.length - 1} more condition${e.blockers.length > 2 ? "s" : ""}`;
  } else if (input.ctx.resultProblem) {
    cls += " block";
    word = input.ctx.resultProblem;
  } else if (e.state === "REVIEWED") {
    word = `Plan reviewed; expires in ${formatCountdown(e.planExpiresInS ?? 0)}`;
    if (e.spacingRemainingS > 0) detail = `next Apply advised in ${formatCountdown(e.spacingRemainingS)} (provisional ${APPLY_SPACING_S / 60}-minute spacing, not a firmware rule)`;
  } else if (e.spacingRemainingS > 0) {
    word = `Next Apply advised in ${formatCountdown(e.spacingRemainingS)} (provisional ${APPLY_SPACING_S / 60}-minute spacing, not a firmware rule)`;
  } else {
    word = "Ready to review an edit";
  }
  return `<div class="${cls}"><span class="word">${esc(word)}</span>${detail ? `<span class="small">${esc(detail)}</span>` : ""}<span class="small">${esc(input.configAgeText)}</span></div>`;
}

/** Every label says only what its own branch checked (O-5): the value's own age, and the poll, each from its own flag. */
function freshTag(v: SlotView, config: CardConfig): string {
  const poll = v.pollCurrent ? "poll current" : "poll not current";
  const pollTitle = v.pollCurrent ? "the configuration poll is current (read within 150 s)" : "the configuration poll is not current";
  if (!v.available) return `<span class="fresh f-missing" title="A value is unavailable or missing; ${esc(pollTitle)}">value unavailable; ${esc(poll)}</span>`;
  if (v.ageSeconds === null) {
    return `<span class="fresh f-missing" title="A value has no usable timestamp (missing, or more than 60 s in the future), so its own age is unverified; ${esc(pollTitle)}">timestamp unverified; ${esc(poll)}</span>`;
  }
  if (v.fresh) return `<span class="fresh f-live" title="Reported ${esc(formatAge(v.ageSeconds))} ago; ${esc(pollTitle)}">live ${esc(formatAge(v.ageSeconds))}; ${esc(poll)}</span>`;
  if (v.currentBy === "report") {
    return `<span class="fresh f-live" title="Reported ${esc(formatAge(v.ageSeconds))} ago (within 300 s, older than the ${esc(formatAge(config.max_age_configuration_s))} label window); ${esc(pollTitle)}">reported ${esc(formatAge(v.ageSeconds))}; ${esc(poll)}</span>`;
  }
  if (v.currentBy === "poll") {
    return `<span class="fresh f-live" title="Unchanged for ${esc(formatAge(v.ageSeconds))}; the dongle re-publishes a value only when it changes, and ${esc(pollTitle)}">unchanged ${esc(formatAge(v.ageSeconds))}; poll current</span>`;
  }
  return `<span class="fresh f-stale" title="Last reported ${esc(formatAge(v.ageSeconds))} ago, more than 300 s; ${esc(pollTitle)}">stale ${esc(formatAge(v.ageSeconds))}; ${esc(poll)}</span>`;
}

function pen(v: SlotView, setting: EditableSetting, canCall: boolean): string {
  const el = v.eligibility[setting];
  const ok = el.allowed && canCall;
  const reason = !canCall ? "Read-only view: Home Assistant offered no service interface" : el.reason;
  const attrs = ok ? "" : ` disabled aria-disabled="true" title="${esc(reason)}"`;
  return `<button type="button" class="pen" data-action="edit" data-slot="${v.slot}" data-setting="${esc(setting)}" aria-label="Edit slot ${v.slot} ${esc(SETTING_LABEL[setting])}"${attrs}>&#9998;</button>`;
}

export function renderSlots(input: PanelInput): string {
  const owned = input.editor.blockers.some((b) => b.code === "free_power" || b.code === "dump_to_grid");
  const rows = input.slots
    .map((v) => {
      const cls = `slot${v.active ? " active" : ""}${owned ? " owned" : ""}`;
      return `<li class="${cls}">
<div class="head"><span>Slot ${v.slot}</span>${v.active ? `<span class="badge ok">now</span>` : ""}</div>
<div class="cell"><span class="k">Window</span><span class="v">${esc(v.start.text)} &ndash; ${esc(v.end.text)}</span><button type="button" class="lockicon" data-action="start-info" aria-label="Why start times cannot be edited here" title="Start time: not editable here">&#128274;</button></div>
<div class="cell"><span class="k">${esc(input.powerLabel)}</span><span class="v">${esc(v.power.text)}</span>${pen(v, "power", input.canCall)}</div>
<div class="cell"><span class="k">Target SOC</span><span class="v">${esc(v.soc.text)}</span>${pen(v, "target_soc", input.canCall)}</div>
<div class="cell"><span class="k">Charge from</span><span class="v">${esc(v.source.text)}</span>${pen(v, "charge_source", input.canCall)}</div>
<div class="cell"><span class="k">Mode</span><span class="v muted">${esc(v.mode.text)}</span></div>
<div class="cell">${freshTag(v, input.config)}</div>
</li>`;
    })
    .join("");
  const head = `<li class="slot hdrrow"><span>Slot</span><span>Window</span><span>${esc(input.powerLabel)}</span><span>Target SOC</span><span>Charge from</span><span>Mode</span><span>Freshness</span></li>`;
  return `<ul class="slots">${head}${rows}</ul>${input.startInfo ? `<p class="small">${esc(START_TIME_LOCKED_TEXT)}</p>` : ""}`;
}

function sentNote(input: PanelInput, kind: SentInfo["kind"]): string {
  if (!input.sent || input.sent.kind !== kind) return "";
  const what = kind === "review" ? "Review" : kind === "apply" ? "Apply" : "Acknowledge";
  return `<p class="small" aria-live="polite">${esc(what)} sent ${esc(formatAge(input.sent.ageSeconds))} ago; waiting for the editor&#39;s result&hellip;</p>`;
}

function errorNote(input: PanelInput): string {
  return input.lastError ? `<p class="warn">The last service call did not complete: ${esc(input.lastError)}</p>` : "";
}

function effectLine(d: Draft, v: SlotView, valid: boolean): string {
  if (!valid) return "";
  const reg = SETTING_REGISTER_BASE[d.setting] + d.slot;
  const current = d.setting === "target_soc" ? v.soc.text : d.setting === "power" ? v.power.text : v.source.text;
  const target = displayValue(d.setting, d.value.trim());
  const unchanged = [
    `start ${v.start.text}`,
    `end ${v.end.text}`,
    d.setting !== "power" ? `power ${v.power.text}` : "",
    d.setting !== "target_soc" ? `target SOC ${v.soc.text}` : "",
    d.setting !== "charge_source" ? `charge source ${v.source.text}` : "",
    `mode ${v.mode.text}`,
  ].filter((s) => s);
  const fallbackNote = "The saved fallback profile will then show DRIFT until you Review and Save it.";
  const dumpNote = d.setting === "charge_source" && d.value.trim() === "Grid"
    ? " A slot with a charge source set makes a scheduled Dump to Grid whose window overlaps it refuse at start (no health alert counts that refusal)."
    : "";
  return `<p>Slot ${d.slot} ${esc(SETTING_LABEL[d.setting])} <strong>${esc(current)} &rarr; ${esc(target)}</strong> (register ${reg}). Rewritten unchanged: ${esc(unchanged.join(", "))}.</p><p class="small">${esc(fallbackNote)}${esc(dumpNote)} Do not use SmartDeye or the inverter&#39;s own panel until the edit is finished.</p>`;
}

function renderEditor(input: PanelInput, d: Draft): string {
  const v = input.slots[d.slot - 1];
  if (!v) return "";
  const check = validateDraft(d, v, input.ctx);
  const busy = input.sent !== null;
  const canReview = check.allowed && input.canCall && !busy && (input.editor.state === "IDLE" || input.editor.state === "OUTCOME");
  let control: string;
  if (d.setting === "charge_source") {
    control = ["None", "Grid"]
      .map((o) => `<button type="button" class="btn" data-action="set-value" data-value="${o}" aria-pressed="${d.value.trim() === o ? "true" : "false"}">${o}</button>`)
      .join("");
  } else {
    const step = d.setting === "power" ? POWER_STEP_W : 1;
    const range = d.setting === "power" ? `${POWER_MIN_W}-${POWER_MAX_W} W, steps of ${POWER_STEP_W} W` : `${input.ctx.socFloor ?? "?"}-100 %`;
    control = `<button type="button" class="btn" data-action="step" data-delta="-${step}" aria-label="decrease">&minus;</button><input class="in num" type="text" inputmode="numeric" data-action="value" value="${esc(d.value)}" aria-label="New ${esc(SETTING_LABEL[d.setting])}" maxlength="6"><button type="button" class="btn" data-action="step" data-delta="${step}" aria-label="increase">+</button><span class="small">${esc(range)}</span>`;
  }
  return `<div class="panel editor">
<h2>Edit slot ${d.slot} ${esc(SETTING_LABEL[d.setting])}</h2>
<div class="row">${control}</div>
${effectLine(d, v, check.allowed)}
${check.allowed ? "" : `<p class="warn">${esc(check.reason)}</p>`}
${sentNote(input, "review")}${errorNote(input)}
<div class="row"><button type="button" class="btn primary" data-action="review"${canReview ? "" : ` disabled aria-disabled="true" title="${esc(busy ? "waiting for the editor" : check.reason || "not available now")}"`}>Review (writes nothing)</button><button type="button" class="btn" data-action="cancel">Cancel</button></div>
<p class="small">Review runs the editor&#39;s full safety gate in Home Assistant and records a plan with a one-time code; it writes nothing to the inverter. Only the next step, after your typed confirmation, writes.</p>
</div>`;
}

function renderConfirm(input: PanelInput): string {
  const e = input.editor;
  const plan = e.plan;
  if (!plan) return "";
  const d = input.draft;
  const mine = d !== null && planMatchesDraft(plan, d);
  const phrase = phraseFor(plan);
  const typedOk = input.typed === phrase;
  const spacing = e.spacingRemainingS;
  const busy = input.sent !== null;
  const blocker = e.blockers[0] ?? null;
  // S2: the card's own advisory blockers hold Apply too (the script would refuse anyway; the card never asks it to).
  // P1: so does the reviewed slot's own eligibility for that setting (a value, the raw flags or a bound that became unavailable).
  const slotElig = planSlotEligibility(plan, input.slots);
  const canApply = mine && typedOk && spacing <= 0 && input.canCall && !busy && blocker === null && slotElig.allowed;
  let why = "";
  if (!mine) why = "This pending plan was not reviewed in this card (or the page was reloaded). Review the change here again; the plan expires on its own.";
  else if (blocker) why = `${blocker.text}. The editor would refuse this Apply; it is not sent while the condition lasts.`;
  else if (!slotElig.allowed) why = `Slot ${plan.slot}: ${slotElig.reason}. The editor would refuse this Apply; it is not sent while the condition lasts.`;
  else if (spacing > 0) why = `Provisional spacing: wait about ${Math.ceil(spacing / 60)} min after the previous Apply (not a firmware rule; the exact countdown is in the status line).`;
  else if (!typedOk) why = "Type the confirmation phrase exactly as shown.";
  else if (busy) why = "Waiting for the editor.";
  return `<div class="panel confirm">
<h2>Confirm and apply</h2>
<p>Plan: slot ${plan.slot} ${esc(SETTING_LABEL[plan.setting])} <strong>${esc(displayValue(plan.setting, plan.before))} &rarr; ${esc(displayValue(plan.setting, plan.want))}</strong> (register ${SETTING_REGISTER_BASE[plan.setting] + plan.slot}), review code ${esc(plan.code)}, expires in about <strong>${Math.ceil((e.planExpiresInS ?? 0) / 60)} min</strong> (exact countdown in the status line).</p>
<div class="verbatim">${esc(e.result.text)}</div>
${mine ? `<p>Type exactly: <span class="phrase-show">${esc(phrase)}</span></p>
<div class="row"><input class="in phrase" type="text" data-action="phrase" value="${esc(input.typed)}" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="80" aria-label="Confirmation phrase"></div>` : ""}
${why ? `<p class="warn">${esc(why)}</p>` : ""}
${sentNote(input, "apply")}${errorNote(input)}
<div class="row"><button type="button" class="btn primary" data-action="apply"${canApply ? "" : ` disabled aria-disabled="true" title="${esc(why || "not available")}"`}>Apply (writes the inverter)</button><button type="button" class="btn" data-action="cancel">Cancel</button></div>
<p class="small">Apply re-runs the gate, loads the live slot into staging, proves every other field unchanged, arms once, presses Apply once in a quiet bus gap and judges the outcome from the firmware readback, two later reads and the gate counter. It never retries. Cancel here only closes this panel; the plan expires on its own.</p>
</div>`;
}

function renderBusy(input: PanelInput): string {
  const e = input.editor;
  const steps = e.progress
    .map((s) => `<li class="${s.seen ? "seen" : "pending"}"><span class="dot"></span><span>${esc(s.label)}</span></li>`)
    .join("");
  return `<div class="panel busy">
<h2>Applying&hellip;</h2>
<div class="verbatim">${esc(e.result.text || "(no result text yet)")}</div>
<ul class="steps">${steps}</ul>
<p class="small">Derived from the editor&#39;s markers and the dongle&#39;s own last result; a step is marked only when its signal has been seen. Success is reported only when the editor itself writes APPLIED AND VERIFIED. All edit controls are disabled until the outcome is judged.</p>
</div>`;
}

function renderLocked(input: PanelInput): string {
  const e = input.editor;
  const typedOk = input.ackTyped === ACK_PHRASE;
  const busy = input.sent !== null;
  // P2: the Acknowledge script refuses while an Apply still runs or is in flight (the tail of an UNCERTAIN Apply, or the watchdog).
  const tail = e.applyRunning || e.inFlight;
  const can = typedOk && input.canCall && !busy && !tail;
  return `<div class="panel locked">
<h2>Edits locked: manual review needed</h2>
<div class="verbatim">${esc(e.result.text || "(no result text)")}</div>
<p><strong>Do not retry.</strong> Open Manual Controls, press Load Current Slot for the slot named above and compare every value with the inverter&#39;s own display; correct anything wrong there deliberately. Free Power and Dump to Grid restore whatever they snapshot next, so settle the slot first.</p>
<p>When you have checked the TOU slots, type exactly: <span class="phrase-show">${esc(ACK_PHRASE)}</span></p>
<div class="row"><input class="in phrase" type="text" data-action="ack-phrase" value="${esc(input.ackTyped)}" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="40" aria-label="Acknowledgement phrase"></div>
${sentNote(input, "acknowledge")}${errorNote(input)}
<div class="row"><button type="button" class="btn danger" data-action="ack"${can ? "" : ` disabled aria-disabled="true" title="${esc(tail ? "the Apply is still being judged; wait for it to finish" : busy ? "waiting for the editor" : "type the phrase exactly")}"`}>Acknowledge (unlock edits)</button></div>
${tail ? `<p class="small">The Apply that led here is still running or in flight; Acknowledge becomes available when the editor has finished judging it.</p>` : ""}
</div>`;
}

function renderOutcome(input: PanelInput): string {
  const e = input.editor;
  const k = e.result.kind;
  const cls = k === "applied" ? "applied" : k === "failed" || k === "refused" || k === "review_refused" ? "failed" : k === "uncertain" ? "uncertain" : "unknown";
  const title = k === "applied" ? "Applied and verified" : k === "failed" ? "Edit did not complete: nothing written" : k === "refused" || k === "review_refused" ? "Refused: nothing written" : k === "uncertain" ? "Outcome not proven" : k === "in_progress" ? "Editor state unclear" : k === "reviewed" ? "Review expired or not current: review again" : "Editor result not recognised";
  const undo = e.undo;
  const busy = input.sent !== null;
  const undoBtn = undo
    ? `<button type="button" class="btn" data-action="undo"${input.canCall && !busy ? "" : ` disabled aria-disabled="true"`}>Undo: review slot ${undo.slot} ${esc(SETTING_LABEL[undo.setting])} back to ${esc(displayValue(undo.setting, undo.value))}</button>`
    : k === "applied" ? `<span class="small">Undo is not offered: the result, the owner-edit record and the live slot do not all agree, the slot is not current, or an edit of that slot or that value is not allowed right now (the status line, or the slot's own pen, says why). Review by hand if needed.</span>` : "";
  const failClosed = k === "unknown" || k === "in_progress"
    ? `<p class="err">The editor&#39;s result text is not one this card recognises, so every edit control stays disabled. Use the ECCO scripts directly, or wait for the editor to finish.</p>`
    : "";
  const hint = refusalHint(e.result.text);
  return `<div class="panel outcome ${cls}">
<h2>${esc(title)}</h2>
<div class="verbatim">${esc(e.result.text)}</div>
${hint ? `<p class="warn">${esc(hint)}</p>` : ""}
${failClosed}
${k === "applied" ? `<p class="small">Success is as the editor reported it: firmware readback and an independent later read of every written register agree. The saved fallback profile now differs (DRIFT) until you Review and Save it.</p>` : ""}
${errorNote(input)}
<div class="row">${undoBtn}</div>
</div>`;
}

/** `masked` renders every text input empty and every countdown coarse: the element compares that form to decide whether the
 *  panel must be rewritten (a rewrite would move the caret), and writes the unmasked form when it does. */
export function renderPanel(raw: PanelInput, masked = false): string {
  // Masked: a typed phrase is kept only when it matches (the gate), so the key changes exactly when a button's state does.
  const plan = raw.editor.plan;
  const typedKey = plan && raw.typed === phraseFor(plan) ? raw.typed : "";
  const ackKey = raw.ackTyped === ACK_PHRASE ? raw.ackTyped : "";
  // The numeric draft value is reduced only while the editor row (with its value input) is shown; in the confirm step the
  // draft has no input and must stay exact (it decides whether the live plan is this card's own).
  const draftKey = raw.draft && raw.editor.state !== "REVIEWED" ? { ...raw.draft, value: maskValue(raw) } : raw.draft;
  const input: PanelInput = masked ? { ...raw, typed: typedKey, ackTyped: ackKey, draft: draftKey } : raw;
  const e = input.editor;
  if (e.state === "UNAVAILABLE") {
    return `<div class="panel locked"><h2>Editor unavailable</h2><p>These Home Assistant entities are missing, so nothing can be edited here:</p><ul class="plain">${e.missing.map((m) => `<li><code>${esc(m)}</code></li>`).join("")}</ul></div>`;
  }
  if (e.state === "LOCKED") return renderLocked(input);
  if (e.state === "BUSY") return renderBusy(input);
  if (e.state === "REVIEWED") return renderConfirm(input);
  const parts: string[] = [];
  if (e.state === "OUTCOME") parts.push(renderOutcome(input));
  if (input.draft && EDITABLE.includes(input.draft.setting) && (e.result.kind !== "unknown" && e.result.kind !== "in_progress")) parts.push(renderEditor(input, input.draft));
  else if (input.sent && input.sent.kind === "review") parts.push(`<div class="panel">${sentNote(input, "review")}</div>`);
  return parts.join("");
}
