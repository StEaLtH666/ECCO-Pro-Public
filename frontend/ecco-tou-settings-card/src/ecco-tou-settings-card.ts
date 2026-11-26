// ECCO TOU Settings card: the six live TOU slots and a guarded editor for the target SOC, the power and the charge source of
// one slot, through the installed ACS1 scripts (Review -> typed confirmation -> Apply; Acknowledge after an UNCERTAIN outcome).
//
// AUTHORITY: this card holds no safety logic of its own. It calls exactly three Home Assistant scripts (src/actions.ts) and
// reads the editor's helpers back. Every decision it shows before a Review is ADVISORY (it can only disable more, never
// enable more than the scripts allow); the Review's refusal text is the truth and is shown verbatim. Success is reported
// only when the editor itself writes APPLIED AND VERIFIED. The `hass` setter keeps the `states` map and the service
// function, never the Home Assistant object. No websocket message, network request, storage or timer exists in this card.
import { perform } from "./actions.ts";
import type { ActionKind, CallFn } from "./actions.ts";
import {
  ACK_PHRASE,
  EDITABLE,
  H_RESULT,
  POWER_STEP_W,
  REQUEST_TIMEOUT_S,
  context,
  dongleIds,
  editorView,
  formatAge,
  isOn,
  londonMinutes,
  normalizeConfig,
  phraseMatches,
  planMatchesDraft,
  referencedIds,
  slotView,
  stateText,
  configAgeSeconds,
  validateDraft,
} from "./model.ts";
import type { Context } from "./model.ts";
import { planSlotEligibility, renderBadges, renderPanel, renderShell, renderSlots, renderStatus } from "./render.ts";
import type { PanelInput } from "./render.ts";
import { STYLES } from "./styles.ts";
import type { CardConfig, Draft, EditableSetting, EditorView, SlotView, StatesLike } from "./types.ts";

export const CARD_TAG = "ecco-tou-settings-card";
export const CARD_VERSION = "0.1.0";
/** On a hass update that changed none of the referenced entities, re-render anyway once this long has passed since the last render, so
 *  countdowns and freshness age honestly. The card sets no timer: without hass updates (or clicks) nothing redraws. */
export const REFRESH_INTERVAL_MS = 15000;

interface RegionLike {
  innerHTML: string;
}

interface RootLike {
  innerHTML: string;
  querySelector(selector: string): RegionLike | null;
  addEventListener(type: string, listener: (ev: Event) => void): void;
}

interface ActionElementLike {
  getAttribute(name: string): string | null;
}

interface Sent {
  kind: ActionKind;
  atMs: number;
  resultBefore: string;
}

export class EccoTouSettingsCard extends HTMLElement {
  /** Clock used for freshness and countdowns; replaceable in tests. */
  now: () => number = () => Date.now();

  private _config: CardConfig | null = null;
  private _states: StatesLike = {};
  private _call: CallFn | null = null;
  private _root: RootLike | null = null;
  private _listening = false;
  private _signature = "";
  private _renderedAt = 0;
  private _draft: Draft | null = null;
  private _typed = "";
  private _ackTyped = "";
  private _sent: Sent | null = null;
  private _startInfo = false;
  private _lastError: string | null = null;
  /** What each region last showed, so a region is rewritten only when its content changed (an input keeps its caret). */
  private _shown: Record<string, string> = {};

  setConfig(config: unknown): void {
    this._config = normalizeConfig(config);
    this._buildShell();
    this._signature = "";
    this._render(true);
  }

  set hass(hass: unknown) {
    // Keep ONLY the states map and the service function; never the Home Assistant object.
    const h = hass !== null && typeof hass === "object" ? (hass as { states?: unknown; callService?: unknown }) : null;
    this._states = h && h.states !== null && typeof h.states === "object" ? (h.states as StatesLike) : {};
    this._call = h && typeof h.callService === "function" ? (h.callService as CallFn).bind(h) : null;
    this._render(false);
  }

  getCardSize(): number {
    return 10;
  }

  static getStubConfig(): Record<string, unknown> {
    return { entity_prefix: "ecco_clock_dongle" };
  }

  private _buildShell(): void {
    if (!this._config) return;
    const root = (this.shadowRoot ?? this.attachShadow({ mode: "open" })) as unknown as RootLike;
    root.innerHTML = renderShell(this._config.title, STYLES, `ECCO TOU Settings card ${CARD_VERSION}. Edits go through the ECCO ACS1 editor scripts; this card adds no write path of its own.`);
    if (!this._listening) {
      root.addEventListener("input", this._onInput);
      root.addEventListener("change", this._onChange);
      root.addEventListener("click", this._onClick);
      this._listening = true;
    }
    this._root = root;
    this._shown = {};
  }

  private _region(name: string): RegionLike | null {
    return this._root ? this._root.querySelector(`[data-region="${name}"]`) : null;
  }

  private _referencedSignature(): string {
    if (!this._config) return "";
    const parts: string[] = [];
    for (const id of referencedIds(this._config.entity_prefix)) {
      const e = this._states[id];
      parts.push(e ? `${String(e.state)}|${String(e.last_updated ?? e.last_changed ?? "")}` : "-");
    }
    parts.push(JSON.stringify([this._sent, this._call !== null]));
    return parts.join("\u0002");
  }

  private _write(name: string, html: string, key = html): void {
    if (this._shown[name] === key) return;
    const r = this._region(name);
    if (!r) return;
    r.innerHTML = html;
    this._shown[name] = key;
  }

  /** The current view models; the element's one place that reads the states. */
  private _views(nowMs: number): { ctx: Context; slots: SlotView[]; editor: EditorView } {
    const config = this._config as CardConfig;
    const now = new Date(nowMs);
    const ctx = context(this._states, config, nowMs, now);
    const slots: SlotView[] = [];
    // the slot clock is Europe/London's (the inverter's and the gate's), never the browser's zone (O-1)
    for (let n = 1; n <= 6; n++) slots.push(slotView(this._states, config, n, nowMs, londonMinutes(nowMs), ctx));
    const editor = editorView(this._states, config, nowMs, now, ctx, slots);
    return { ctx, slots, editor };
  }

  private _render(force: boolean): void {
    if (!this._config || !this._root) return;
    const nowMs = this.now();
    const sig = this._referencedSignature();
    if (!force && sig === this._signature && nowMs - this._renderedAt < REFRESH_INTERVAL_MS) return;
    this._signature = sig;
    this._renderedAt = nowMs;
    this._expireSent(nowMs);
    const { ctx, slots, editor } = this._views(nowMs);
    // A plan the editor settled (used, expired or replaced) or a locked / busy editor ends any local draft.
    if (this._draft && (editor.state === "LOCKED" || editor.state === "BUSY" || editor.state === "UNAVAILABLE")) this._draft = null;
    if (editor.state !== "REVIEWED" && this._typed) this._typed = "";
    if (editor.state !== "LOCKED" && this._ackTyped) this._ackTyped = "";
    const d = dongleIds(this._config.entity_prefix);
    const loadLimit = stateText(this._states, d.loadLimit);
    const powerLabel = loadLimit === "Zero Export" ? "Discharge limit" : loadLimit === "Allow Export" ? "Export limit" : "Power";
    const configAge = configAgeSeconds(this._states, this._config.entity_prefix, nowMs);
    const input: PanelInput = {
      config: this._config,
      states: this._states,
      editor,
      slots,
      ctx,
      draft: this._draft,
      typed: this._typed,
      ackTyped: this._ackTyped,
      sent: this._sent ? { kind: this._sent.kind, ageSeconds: Math.max(0, (nowMs - this._sent.atMs) / 1000) } : null,
      canCall: this._call !== null,
      startInfo: this._startInfo,
      lastError: this._lastError,
      nowMs,
      powerLabel,
      touEnabled: isOn(this._states, d.touEnabled) ? "on" : stateText(this._states, d.touEnabled) === "off" ? "off" : "unknown",
      configAgeText: configAge === null ? "Configuration read time unknown" : `Values read ${formatAge(configAge)} ago${isOn(this._states, d.configOnline) ? ", configuration poll online" : ", configuration poll NOT online"}`,
    };
    this._write("badges", renderBadges(input));
    this._write("status", renderStatus(input));
    this._write("slots", renderSlots(input));
    // The panel holds the text inputs: it is rewritten only when something other than the typed text changed (its key
    // renders the inputs empty), so typing keeps the caret and a rewrite restores the typed text from the card's state.
    this._write("panel", renderPanel(input, false), renderPanel(input, true));
  }

  /** A request whose result changed, or that timed out, is no longer "sent". */
  private _expireSent(nowMs: number): void {
    if (!this._sent) return;
    const result = stateText(this._states, H_RESULT) ?? "";
    const changed = result !== this._sent.resultBefore;
    if (changed || nowMs - this._sent.atMs > REQUEST_TIMEOUT_S * 1000) {
      if (!changed) this._lastError = `No result from the editor within ${REQUEST_TIMEOUT_S} s; check ECCO Advanced Config Edit Last Result`;
      this._sent = null;
    }
  }

  private _send(kind: ActionKind, payload: Draft | string): void {
    if (!this._call) return;
    const nowMs = this.now();
    this._sent = { kind, atMs: nowMs, resultBefore: stateText(this._states, H_RESULT) ?? "" };
    this._lastError = null;
    try {
      const { done } = perform(this._call, kind, payload);
      void done.then(
        () => undefined,
        (err: unknown) => {
          this._lastError = err instanceof Error ? err.message : String(err);
          this._sent = null;
          this._render(true);
        },
      );
    } catch (err) {
      this._lastError = err instanceof Error ? err.message : String(err);
      this._sent = null;
    }
    this._render(true);
  }

  private _onInput = (ev: Event): void => {
    const t = ev.target as unknown as (ActionElementLike & { value?: unknown }) | null;
    if (!t || typeof t.getAttribute !== "function") return;
    const action = t.getAttribute("data-action");
    const value = String(t.value ?? "");
    if (action === "value" && this._draft) {
      this._draft = { ...this._draft, value: value.slice(0, 6) };
    } else if (action === "phrase") {
      this._typed = value.slice(0, 80);
    } else if (action === "ack-phrase") {
      this._ackTyped = value.slice(0, 40);
    } else {
      return;
    }
    // Typing: the panel is rewritten only when its gate (a button's enabled state, a validation message) changed.
    this._render(true);
  };

  /** A committed value (blur / Enter) refreshes everything, the effect line included. */
  private _onChange = (ev: Event): void => {
    const t = ev.target as unknown as (ActionElementLike & { value?: unknown }) | null;
    if (!t || typeof t.getAttribute !== "function") return;
    const action = t.getAttribute("data-action");
    if (action !== "value" && action !== "phrase" && action !== "ack-phrase") return;
    this._onInput(ev);
    this._shown.panel = "";
    this._render(true);
  };

  /** Every handled click ends in a render (P3): a click the handler refused (a blocker that depends on time alone, a plan that just
   *  expired) redraws the controls as they now are instead of leaving an enabled-looking button that does nothing. */
  private _onClick = (ev: Event): void => {
    try {
      this._handleClick(ev);
    } finally {
      this._render(true);
    }
  };

  private _handleClick(ev: Event): void {
    const target = ev.target as unknown as { closest?: (selector: string) => ActionElementLike | null } | null;
    const el = target && typeof target.closest === "function" ? target.closest("[data-action]") : null;
    if (!el) return;
    if (el.getAttribute("disabled") !== null || el.getAttribute("aria-disabled") === "true") return;
    const action = el.getAttribute("data-action");
    const nowMs = this.now();
    if (action === "start-info") {
      this._startInfo = !this._startInfo;
    } else if (action === "edit") {
      const slot = Number(el.getAttribute("data-slot"));
      const setting = el.getAttribute("data-setting") as EditableSetting | null;
      if (!Number.isInteger(slot) || slot < 1 || slot > 6 || !setting || !EDITABLE.includes(setting)) return;
      const { slots, editor } = this._views(nowMs);
      const v = slots[slot - 1];
      if (!v || !v.eligibility[setting].allowed || this._call === null) return;
      if (editor.state !== "IDLE" && editor.state !== "OUTCOME") return;
      const current = setting === "target_soc" ? v.soc.numeric : setting === "power" ? v.power.numeric : v.source.raw;
      this._draft = { slot, setting, value: current === null ? "" : String(current) };
      this._lastError = null;
    } else if (action === "cancel" || action === "back") {
      this._draft = null;
      this._typed = "";
    } else if (action === "step" && this._draft && this._draft.setting !== "charge_source") {
      const delta = Number(el.getAttribute("data-delta"));
      const cur = Number(this._draft.value.trim());
      if (!Number.isFinite(delta) || !Number.isFinite(cur)) return;
      const step = this._draft.setting === "power" ? POWER_STEP_W : 1;
      if (Math.abs(delta) !== step) return;
      this._draft = { ...this._draft, value: String(cur + delta) };
    } else if (action === "set-value" && this._draft && this._draft.setting === "charge_source") {
      const value = el.getAttribute("data-value");
      if (value !== "None" && value !== "Grid") return;
      this._draft = { ...this._draft, value };
    } else if (action === "review") {
      if (!this._draft || this._sent) return;
      const { ctx, slots, editor } = this._views(nowMs);
      const v = slots[this._draft.slot - 1];
      if (!v || (editor.state !== "IDLE" && editor.state !== "OUTCOME")) return;
      if (!validateDraft(this._draft, v, ctx).allowed) return;
      this._send("review", { ...this._draft, value: this._draft.value.trim() });
      return;
    } else if (action === "apply") {
      if (!this._draft || this._sent) return;
      const { slots, editor } = this._views(nowMs);
      if (editor.state !== "REVIEWED" || !editor.plan || !editor.planLive) return;
      if (!planMatchesDraft(editor.plan, this._draft)) return;
      if (!phraseMatches(this._typed, editor.plan)) return;
      if (editor.spacingRemainingS > 0) return;
      if (editor.blockers.length) return;   // S2: the card's own blockers hold Apply (the button is disabled; a forged click stops here)
      if (!planSlotEligibility(editor.plan, slots).allowed) return;   // P1: so does the reviewed slot's own eligibility
      const phrase = this._typed;
      this._typed = "";
      this._send("apply", phrase);
      return;
    } else if (action === "undo") {
      if (this._sent) return;
      const { ctx, slots, editor } = this._views(nowMs);
      if (editor.state !== "OUTCOME" || !editor.undo || editor.blockers.length) return;
      const u = editor.undo;
      const v = slots[u.slot - 1];
      // S2: the Undo draft passes exactly the checks a hand-typed Review passes (eligibility, bounds, a real change).
      if (!v || !v.eligibility[u.setting].allowed) return;
      const draft: Draft = { slot: u.slot, setting: u.setting, value: u.value };
      if (!validateDraft(draft, v, ctx).allowed) return;
      this._draft = draft;
      this._send("review", draft);
      return;
    } else if (action === "ack") {
      if (this._sent) return;
      const { editor } = this._views(nowMs);
      if (editor.state !== "LOCKED" || this._ackTyped !== ACK_PHRASE) return;
      if (editor.applyRunning || editor.inFlight) return;   // P2: the script refuses while the Apply is still being judged
      const phrase = this._ackTyped;
      this._ackTyped = "";
      this._send("acknowledge", phrase);
      return;
    } else {
      // Any other action value is ignored: there is nothing else this card can do.
      return;
    }
  }
}

if (typeof customElements !== "undefined" && !customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, EccoTouSettingsCard);
}

if (typeof window !== "undefined") {
  const w = window as unknown as { customCards?: Array<Record<string, unknown>> };
  w.customCards = w.customCards || [];
  if (!w.customCards.some((c) => c.type === CARD_TAG)) {
    w.customCards.push({
      type: CARD_TAG,
      name: "ECCO TOU Settings",
      description: "The six ECCO TOU slots with a guarded Review, typed confirmation, Apply editor through the ACS1 scripts.",
      preview: false,
    });
  }
}
