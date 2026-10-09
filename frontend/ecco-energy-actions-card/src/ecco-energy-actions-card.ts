import { LitElement, html, css, nothing, type TemplateResult, type PropertyValues } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import {
  DEFAULT_TITLE,
  type EccoEnergyActionsCardConfig,
  type FreePowerEntities,
  type ScheduleEntities,
  type DumpToGridEntities,
  type DumpScheduleEntities,
} from "./config";
import {
  classifyFreePower,
  canStartFreePower,
  canEndRestore,
  canToggleArm,
  freePowerStateLabel,
  type FreePowerVisualState,
} from "./freePowerState";
import {
  classifyDump,
  canStartDump,
  canEndDump,
  canToggleDumpArm,
  resolveDumpDisplayState,
  dumpDisplayStateLabel,
  resolveLatchedExportPower,
  resolveLatchedStopSoc,
  dumpRecoveryControlsVisible,
  type DumpVisualState,
  type DumpDisplayState,
} from "./dumpState";
import { classifyRecoveryAction } from "./recoveryPresentation";
import { isInterlocked, canActWhileInterlocked, interlockMessage } from "./interlock";
import {
  canChooseTrack,
  initialTrack,
  hiddenTrackAlert,
  alertTone,
  trackName,
  hiddenTrackAlertText,
  type Track,
  type TrackSummary,
} from "./trackSelection";
import {
  classifySchedule,
  isScheduleRejected,
  isScheduleBlocked,
  scheduleFieldsLocked,
  resolveDisplayState,
  scheduleArmServiceCall,
  scheduleCancelServiceCall,
  scheduleSetStartServiceCall,
  scheduleSetNumberServiceCall,
  effectiveSchedulePowerMax,
  type FreePowerDisplayState,
  type ServiceCall,
} from "./schedule";
import { formatCountdown, formatLocalTimestamp, formatWeekdayDateTime, parseLocalTimestamp } from "./utils/time";
import { formatDurationMinutes, formatPercent, formatPower, toBoolean, toNumber } from "./utils/format";

// Minimal shape of the pieces of `hass` this card actually reads/calls -
// same pattern as the sibling ecco-energy-flow-card, avoiding a dependency
// on the large, versioned full Home Assistant frontend types.
interface HassEntity {
  state: string;
  attributes?: Record<string, unknown>;
}
interface HomeAssistantLike {
  states: Record<string, HassEntity | undefined>;
  callService?: (domain: string, service: string, serviceData?: Record<string, unknown>) => Promise<unknown>;
}

const CONFIRM_WINDOW_MS = 4000;
const TICK_INTERVAL_MS = 1000;

@customElement("ecco-energy-actions-card")
export class EccoEnergyActionsCard extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistantLike;

  @state() private _config?: EccoEnergyActionsCardConfig;
  /** Local optimistic override for the staged manual number inputs while the user is dragging, before hass confirms the new state. */
  @state() private _pendingPower?: number;
  @state() private _pendingDuration?: number;
  /** Same idea, for the LATER (schedule) staging inputs - entirely separate from the manual ones above. */
  @state() private _pendingSchedulePower?: number;
  @state() private _pendingScheduleDuration?: number;
  /** True for CONFIRM_WINDOW_MS after a first tap on End & Restore, awaiting the confirming second tap. */
  @state() private _confirmEndRestore = false;
  /** Dump-to-Grid's own staging/confirm state - entirely separate from Free Power's above. */
  @state() private _pendingDumpPower?: number;
  @state() private _pendingDumpStopSoc?: number;
  @state() private _pendingDumpDuration?: number;
  @state() private _confirmEndDump = false;
  /** Dump-to-Grid's own NOW/LATER selector and LATER staging overrides - separate from Free Power's. */
  @state() private _dumpMode: "now" | "later" = "now";
  @state() private _pendingDumpSchedulePower?: number;
  @state() private _pendingDumpScheduleStopSoc?: number;
  @state() private _pendingDumpScheduleDuration?: number;
  @state() private _nowMs = Date.now();
  /** NOW/LATER selector - purely local UI state, never derived from hass. Manual staging (NOW) is always the default. */
  @state() private _mode: "now" | "later" = "now";
  /** `layout: tabbed` only - the visible track. null until willUpdate() picks it once from both tracks' states (see trackSelection.ts); after that only a tab click changes it. */
  @state() private _track: Track | null = null;

  private _confirmTimer?: ReturnType<typeof setTimeout>;
  private _confirmDumpTimer?: ReturnType<typeof setTimeout>;
  private _tickTimer?: ReturnType<typeof setInterval>;
  /** Bookkeeping only (not reactive) - lets willUpdate() detect a visual-state transition and drop a stale End & Restore confirmation. */
  private _lastVisualState?: FreePowerVisualState;
  private _lastDumpVisualState?: DumpVisualState;

  public static getStubConfig(): EccoEnergyActionsCardConfig {
    return {
      type: "custom:ecco-energy-actions-card",
      title: DEFAULT_TITLE,
      free_power: {
        active: "binary_sensor.free_power_active",
        operation_in_progress: "binary_sensor.free_power_operation_in_progress",
        snapshot_valid: "binary_sensor.free_power_snapshot_valid",
        status: "sensor.free_power_status",
        ends_at: "sensor.free_power_ends_at",
        failures: "sensor.free_power_failures_since_boot",
        start_attempts: "sensor.free_power_start_attempts_since_boot",
        start_successes: "sensor.free_power_start_successes_since_boot",
        restore_successes: "sensor.free_power_restore_successes_since_boot",
        write_enable: "switch.free_power_write_enable",
        max_charge_power: "number.free_power_max_charge_power",
        duration: "number.free_power_duration",
        start: "button.start_free_power_charge_now",
        end_restore: "button.end_free_power_restore_now",
      },
      schedule: {
        armed: "input_boolean.ecco_free_power_schedule_armed",
        start: "input_datetime.ecco_free_power_schedule_start",
        duration: "input_number.ecco_free_power_schedule_duration",
        power: "input_number.ecco_free_power_schedule_power",
        last_result: "input_text.ecco_free_power_schedule_last_result",
        status: "sensor.ecco_free_power_schedule_status",
        cancel: "script.ecco_free_power_cancel_schedule",
      },
      dump_to_grid: {
        active: "binary_sensor.dump_to_grid_active",
        operation_in_progress: "binary_sensor.dump_to_grid_operation_in_progress",
        snapshot_valid: "binary_sensor.dump_to_grid_snapshot_valid",
        status: "sensor.dump_to_grid_status",
        ends_at: "sensor.dump_to_grid_ends_at",
        battery_soc: "sensor.ecco_battery_soc",
        failures: "sensor.dump_to_grid_failures_since_boot",
        start_attempts: "sensor.dump_to_grid_start_attempts_since_boot",
        start_successes: "sensor.dump_to_grid_start_successes_since_boot",
        restore_successes: "sensor.dump_to_grid_restore_successes_since_boot",
        write_enable: "switch.dump_to_grid_write_enable",
        export_power: "number.dump_to_grid_export_power",
        stop_soc: "number.dump_to_grid_stop_soc",
        duration: "number.dump_to_grid_duration",
        start: "button.start_dump_to_grid_now",
        end_restore: "button.end_dump_to_grid_restore_now",
        active_export_power: "sensor.dump_to_grid_active_export_power",
        active_stop_soc: "sensor.dump_to_grid_active_stop_soc",
        last_end_reason: "sensor.dump_to_grid_last_end_reason",
        recovery_arm: "switch.dump_to_grid_recovery_arm",
        recovery_force_restore: "button.dump_to_grid_force_restore_original",
        recovery_accept: "button.dump_to_grid_accept_current_state",
        recovery_state: "sensor.dump_to_grid_recovery_state",
        schedule: {
          armed: "input_boolean.ecco_dump_to_grid_schedule_armed",
          start: "input_datetime.ecco_dump_to_grid_schedule_start",
          duration: "input_number.ecco_dump_to_grid_schedule_duration",
          power: "input_number.ecco_dump_to_grid_schedule_power",
          stop_soc: "input_number.ecco_dump_to_grid_schedule_stop_soc",
          last_result: "input_text.ecco_dump_to_grid_schedule_last_result",
          status: "sensor.ecco_dump_to_grid_schedule_status",
          cancel: "script.ecco_dump_to_grid_cancel_schedule",
        },
      },
    };
  }

  public setConfig(config: EccoEnergyActionsCardConfig): void {
    if (!config || typeof config !== "object") {
      throw new Error("ecco-energy-actions-card: invalid configuration");
    }
    if (!config.free_power) {
      throw new Error("ecco-energy-actions-card: `free_power:` entity mapping is required");
    }
    this._config = config;
  }

  public getCardSize(): number {
    return this._config?.schedule || this._config?.dump_to_grid?.schedule ? 6 : 4;
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    this._stopTicking();
    if (this._confirmTimer) clearTimeout(this._confirmTimer);
    if (this._confirmDumpTimer) clearTimeout(this._confirmDumpTimer);
  }

  protected shouldUpdate(_changed: PropertyValues): boolean {
    return !!this._config;
  }

  /**
   * Three independent pieces of "before render" bookkeeping:
   *   1. Drop a local optimistic manual-staging override once hass confirms
   *      the committed value, so a later external change is reflected live
   *      again rather than staying pinned to whatever this card last set.
   *   2. The same, for the LATER (schedule) staging inputs.
   *   3. Reset a stale End & Restore confirmation if the Free Power visual
   *      state itself changed since the last render (P2.10) - a confirm
   *      window that carries over across a state transition (e.g. the tile
   *      flips to a fresh RECOVERY ATTENTION or ACTIVE while "tap again" was
   *      still showing) would apply to a different action than the one the
   *      user actually saw.
   * Belongs in `willUpdate` (before render), not inline in `render()` -
   * mutating `@state()` mid-render works in Lit but is the wrong lifecycle
   * hook for it.
   */
  protected willUpdate(): void {
    const fp = this._config?.free_power;
    if (fp) {
      if (this._pendingPower !== undefined && toNumber(this._entityState(fp.max_charge_power)) === this._pendingPower) {
        this._pendingPower = undefined;
      }
      if (this._pendingDuration !== undefined && toNumber(this._entityState(fp.duration)) === this._pendingDuration) {
        this._pendingDuration = undefined;
      }

      const active = toBoolean(this._entityState(fp.active));
      const armed = toBoolean(this._entityState(fp.write_enable));
      const operationInProgress = toBoolean(this._entityState(fp.operation_in_progress));
      const statusText = this._entityState(fp.status);
      const visualState = classifyFreePower({ active, armed, operationInProgress, statusText });
      if (this._lastVisualState !== undefined && this._lastVisualState !== visualState && this._confirmEndRestore) {
        this._confirmEndRestore = false;
        if (this._confirmTimer) clearTimeout(this._confirmTimer);
      }
      this._lastVisualState = visualState;
    }

    const schedule = this._config?.schedule;
    if (schedule) {
      if (this._pendingSchedulePower !== undefined && toNumber(this._entityState(schedule.power)) === this._pendingSchedulePower) {
        this._pendingSchedulePower = undefined;
      }
      if (
        this._pendingScheduleDuration !== undefined &&
        toNumber(this._entityState(schedule.duration)) === this._pendingScheduleDuration
      ) {
        this._pendingScheduleDuration = undefined;
      }
    }

    const dump = this._config?.dump_to_grid;
    if (dump) {
      if (this._pendingDumpPower !== undefined && toNumber(this._entityState(dump.export_power)) === this._pendingDumpPower) {
        this._pendingDumpPower = undefined;
      }
      if (this._pendingDumpStopSoc !== undefined && toNumber(this._entityState(dump.stop_soc)) === this._pendingDumpStopSoc) {
        this._pendingDumpStopSoc = undefined;
      }
      if (
        this._pendingDumpDuration !== undefined &&
        toNumber(this._entityState(dump.duration)) === this._pendingDumpDuration
      ) {
        this._pendingDumpDuration = undefined;
      }

      const dumpSchedule = dump.schedule;
      if (dumpSchedule) {
        if (
          this._pendingDumpSchedulePower !== undefined &&
          toNumber(this._entityState(dumpSchedule.power)) === this._pendingDumpSchedulePower
        ) {
          this._pendingDumpSchedulePower = undefined;
        }
        if (
          this._pendingDumpScheduleStopSoc !== undefined &&
          toNumber(this._entityState(dumpSchedule.stop_soc)) === this._pendingDumpScheduleStopSoc
        ) {
          this._pendingDumpScheduleStopSoc = undefined;
        }
        if (
          this._pendingDumpScheduleDuration !== undefined &&
          toNumber(this._entityState(dumpSchedule.duration)) === this._pendingDumpScheduleDuration
        ) {
          this._pendingDumpScheduleDuration = undefined;
        }
      }

      const active = toBoolean(this._entityState(dump.active));
      const armed = toBoolean(this._entityState(dump.write_enable));
      const operationInProgress = toBoolean(this._entityState(dump.operation_in_progress));
      const snapshotValid = toBoolean(this._entityState(dump.snapshot_valid));
      const statusText = this._entityState(dump.status);
      const visualState = classifyDump({ active, armed, operationInProgress, snapshotValid, statusText });
      if (this._lastDumpVisualState !== undefined && this._lastDumpVisualState !== visualState && this._confirmEndDump) {
        this._confirmEndDump = false;
        if (this._confirmDumpTimer) clearTimeout(this._confirmDumpTimer);
      }
      this._lastDumpVisualState = visualState;
    }

    // `layout: tabbed` only: the visible track is chosen ONCE, on the first
    // update in which a track has a real state, by state priority
    // (trackSelection.ts) - after that only a tab click changes it, never a
    // state change. An all-"unavailable" snapshot (device offline, entities
    // not registered yet) is not a choice: _renderTabbed() shows Free Power
    // provisionally until a state arrives, so a Dump to Grid recovery that
    // surfaces when the device reconnects still wins the initial tab.
    if (this._config?.layout === "tabbed" && this._track === null && this.hass) {
      const tracks = this._trackSummary();
      if (canChooseTrack(tracks.fp.state, tracks.dump.state)) {
        this._track = initialTrack(tracks.fp.state, tracks.dump.state);
      }
    }
  }

  protected updated(): void {
    // Keep the live countdown ticking only while there's actually something
    // to count down (an active session, or an armed schedule waiting to
    // fire) - no background timer running for the vast majority of this
    // card's life (idle/ready/armed/no-schedule).
    const needsTicking = this._active() || this._scheduleArmed() || this._dumpActive() || this._dumpScheduleArmed();
    if (needsTicking && !this._tickTimer) {
      this._tickTimer = setInterval(() => {
        this._nowMs = Date.now();
      }, TICK_INTERVAL_MS);
    } else if (!needsTicking && this._tickTimer) {
      this._stopTicking();
    }
  }

  private _stopTicking(): void {
    if (this._tickTimer) {
      clearInterval(this._tickTimer);
      this._tickTimer = undefined;
    }
  }

  private _active(): boolean {
    const fp = this._config?.free_power;
    if (!fp) return false;
    return toBoolean(this._entityState(fp.active)) === true;
  }

  private _scheduleArmed(): boolean {
    const schedule = this._config?.schedule;
    if (!schedule) return false;
    return toBoolean(this._entityState(schedule.armed)) === true;
  }

  private _dumpActive(): boolean {
    const dump = this._config?.dump_to_grid;
    if (!dump) return false;
    return toBoolean(this._entityState(dump.active)) === true;
  }

  private _dumpScheduleArmed(): boolean {
    const schedule = this._config?.dump_to_grid?.schedule;
    if (!schedule) return false;
    return toBoolean(this._entityState(schedule.armed)) === true;
  }

  /** Free Power's own current visual state, read purely for the Dump tile's sibling-interlock check - `null` when Free Power isn't configured/available (never treated as ownership, see interlock.ts). */
  private _freePowerVisualStateForInterlock(): FreePowerVisualState | null {
    const fp = this._config?.free_power;
    if (!fp || !this.hass) return null;
    const active = toBoolean(this._entityState(fp.active));
    const armed = toBoolean(this._entityState(fp.write_enable));
    const operationInProgress = toBoolean(this._entityState(fp.operation_in_progress));
    const statusText = this._entityState(fp.status);
    return classifyFreePower({ active, armed, operationInProgress, statusText });
  }

  /** Dump to Grid's own current visual state, read purely for the Free Power tile's sibling-interlock check - `null` when Dump isn't configured/available. */
  private _dumpVisualStateForInterlock(): DumpVisualState | null {
    const dump = this._config?.dump_to_grid;
    if (!dump || !this.hass) return null;
    const active = toBoolean(this._entityState(dump.active));
    const armed = toBoolean(this._entityState(dump.write_enable));
    const operationInProgress = toBoolean(this._entityState(dump.operation_in_progress));
    const snapshotValid = toBoolean(this._entityState(dump.snapshot_valid));
    const statusText = this._entityState(dump.status);
    return classifyDump({ active, armed, operationInProgress, snapshotValid, statusText });
  }

  private _entityState(entityId: string | undefined): string | undefined {
    if (!entityId || !this.hass) return undefined;
    return this.hass.states[entityId]?.state;
  }

  private _entity(entityId: string | undefined): HassEntity | undefined {
    if (!entityId || !this.hass) return undefined;
    return this.hass.states[entityId];
  }

  private _moreInfo(entityId: string | undefined): void {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  private _callService(domain: string, service: string, serviceData: Record<string, unknown>): void {
    if (!this.hass?.callService) return;
    void this.hass.callService(domain, service, serviceData);
  }

  private _callServiceObj(call: ServiceCall): void {
    this._callService(call.domain, call.service, call.data);
  }

  protected render(): TemplateResult {
    if (!this._config) return html``;
    const title = this._config.title ?? DEFAULT_TITLE;
    if (this._config.layout === "tabbed") return this._renderTabbed(title);

    return html`
      <ha-card>
        <h1 class="card-title">${title}</h1>
        <div class="actions-grid">
          ${this._renderFreePowerTile()}
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `;
  }

  // ---------------------------------------------------------------------
  // `layout: tabbed` (OVW1) - presentation only. One track (Free Power or
  // Dump to Grid) is visible at a time, but BOTH tracks' display states are
  // still computed on every render with the tiles' own classifiers and
  // overlays, so the header chips, the initial tab and the cross-track alert
  // can never hide the other track's live state. The two tiles render
  // exactly as in the side-by-side layout; no service call, entity read or
  // handler is added or shared between them. See src/trackSelection.ts.
  // ---------------------------------------------------------------------

  /** Both tracks' display states, labels and firmware status text - the same resolveDisplayState / resolveDumpDisplayState + interlock chain the two tiles run, never short-circuited for the hidden track. */
  private _trackSummary(): { fp: TrackSummary; dump: TrackSummary } {
    const fpVisual = this._freePowerVisualStateForInterlock();
    const dumpVisual = this._dumpVisualStateForInterlock();

    let fp: TrackSummary = { state: "unavailable", pill: "unavailable", label: "Unavailable", statusText: undefined };
    const fpEntities = this._config?.free_power;
    if (fpVisual !== null && fpEntities) {
      const schedule = this._config?.schedule;
      const scheduled: FreePowerDisplayState = schedule
        ? resolveDisplayState(fpVisual, classifySchedule({ armed: toBoolean(this._entityState(schedule.armed)) }))
        : fpVisual;
      const state: FreePowerDisplayState = isInterlocked(fpVisual, dumpVisual) ? "interlocked" : scheduled;
      fp = { state, pill: state, label: this._labelFor(state), statusText: this._entityState(fpEntities.status) };
    }

    // the locked preview shell exactly when _renderDumpToGridTile() renders it: Dump not configured, or hass not arrived yet
    const dumpEntities = this._config?.dump_to_grid;
    let dump: TrackSummary = dumpEntities && this.hass
      ? { state: "unavailable", pill: "unavailable", label: "Unavailable", statusText: undefined }
      : { state: "unavailable", pill: "locked", label: "Coming Soon", statusText: undefined };
    if (dumpVisual !== null && dumpEntities) {
      const dumpSchedule = dumpEntities.schedule;
      const scheduled = resolveDumpDisplayState(dumpVisual, dumpSchedule ? toBoolean(this._entityState(dumpSchedule.armed)) : null);
      const state: DumpDisplayState = isInterlocked(dumpVisual, fpVisual) ? "interlocked" : scheduled;
      dump = { state, pill: state, label: dumpDisplayStateLabel(state), statusText: this._entityState(dumpEntities.status) };
    }
    return { fp, dump };
  }

  /** The tab click handler. Switching tracks cancels any pending two-tap End & Restore confirmation of BOTH modes, so a stale "tap again" can never apply to the other mode; NOW/LATER, staged values and every entity stay per-mode and untouched. */
  private _selectTrack(track: Track): void {
    if (this._confirmTimer) clearTimeout(this._confirmTimer);
    if (this._confirmDumpTimer) clearTimeout(this._confirmDumpTimer);
    this._confirmEndRestore = false;
    this._confirmEndDump = false;
    this._track = track;
  }

  private _renderTabbed(title: string): TemplateResult {
    const tracks = this._trackSummary();
    // _track is null until willUpdate() pins it on the first update with a real state - render the same choice provisionally meanwhile.
    const track: Track = this._track ?? initialTrack(tracks.fp.state, tracks.dump.state);
    const hiddenTrack: Track = track === "free_power" ? "dump_to_grid" : "free_power";
    const hidden = track === "free_power" ? tracks.dump : tracks.fp;
    const tone = alertTone(hiddenTrackAlert(hidden.state));
    const alertIcon = tone === "fault" ? "mdi:alert-circle-outline" : tone === "warning" ? "mdi:alert-outline" : "mdi:information-outline";

    return html`
      <ha-card>
        <div class="tabbed-header">
          <h1 class="card-title">${title}</h1>
          <div class="track-strip">
            <span class="state-pill state-${tracks.fp.pill}">Free Power · ${tracks.fp.label}</span>
            <span class="state-pill state-${tracks.dump.pill}">Dump to Grid · ${tracks.dump.label}</span>
          </div>
        </div>
        <div class="mode-selector track-selector" role="tablist">
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${track === "free_power" ? "is-active" : ""}"
            aria-selected=${track === "free_power"}
            @click=${() => this._selectTrack("free_power")}
          >
            <ha-icon icon="mdi:flash"></ha-icon> Free Power
          </button>
          <button
            type="button"
            role="tab"
            class="mode-tab track-tab ${track === "dump_to_grid" ? "is-active" : ""}"
            aria-selected=${track === "dump_to_grid"}
            @click=${() => this._selectTrack("dump_to_grid")}
          >
            <ha-icon icon="mdi:transmission-tower-export"></ha-icon> Dump to Grid
          </button>
        </div>
        ${tone
          ? html`
              <div class="track-alert track-alert-${tone}" role="status">
                <ha-icon icon=${alertIcon}></ha-icon>
                <div class="track-alert-text">${hiddenTrackAlertText(trackName(hiddenTrack), hidden.label, hidden.statusText)}</div>
                <button type="button" class="track-alert-show" @click=${() => this._selectTrack(hiddenTrack)}>Show</button>
              </div>
            `
          : nothing}
        <div class="actions-grid is-tabbed">
          ${track === "free_power" ? this._renderFreePowerTile() : this._renderDumpToGridTile()}
        </div>
      </ha-card>
    `;
  }

  // ---------------------------------------------------------------------
  // Free Power tile
  // ---------------------------------------------------------------------

  private _renderFreePowerTile(): TemplateResult {
    const fp = this._config?.free_power;
    if (!fp || !this.hass) {
      return this._renderFreePowerUnavailable("Free Power is not configured on this card.");
    }

    const active = toBoolean(this._entityState(fp.active));
    const armed = toBoolean(this._entityState(fp.write_enable));
    const operationInProgress = toBoolean(this._entityState(fp.operation_in_progress));
    const snapshotValid = toBoolean(this._entityState(fp.snapshot_valid));
    const statusText = this._entityState(fp.status);

    const visualState = classifyFreePower({ active, armed, operationInProgress, statusText });

    if (visualState === "unavailable") {
      return this._renderFreePowerUnavailable("Free Power entities are unavailable right now.");
    }

    const schedule = this._config?.schedule;
    const scheduleArmedRaw = schedule ? toBoolean(this._entityState(schedule.armed)) : null;
    const scheduleBanner = classifySchedule({ armed: scheduleArmedRaw });
    // Hardware/safety states always win - schedule cosmetics can only ever
    // upgrade the plain "ready" state, never conceal anything else (see
    // schedule.ts's resolveDisplayState doc comment for the full priority
    // order this implements).
    const scheduledDisplayState: FreePowerDisplayState = schedule
      ? resolveDisplayState(visualState, scheduleBanner)
      : visualState;

    // Sibling interlock (2026-09-26 sibling card polish): layered on last, so
    // it can only ever replace the plain "ready"/"armed"/"scheduled" states -
    // this feature's own recovery/busy/active states above always outrank it
    // (see interlock.ts's isInterlocked() doc comment for the full rule).
    const dumpVisualState = this._dumpVisualStateForInterlock();
    const interlocked = isInterlocked(visualState, dumpVisualState);
    const displayState: FreePowerDisplayState = interlocked ? "interlocked" : scheduledDisplayState;
    const interlockMessageText = interlocked ? interlockMessage("Dump to Grid", dumpVisualState) : undefined;

    const stagedPowerEntity = this._entity(fp.max_charge_power);
    const stagedDurationEntity = this._entity(fp.duration);
    const stagedPowerW = this._pendingPower ?? toNumber(stagedPowerEntity?.state);
    const stagedDurationMin = this._pendingDuration ?? toNumber(stagedDurationEntity?.state);

    const icon = this._iconFor(displayState);
    const label = this._labelFor(displayState);

    return html`
      <div class="tile free-power-tile state-${displayState}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${icon}></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-${displayState}">${label}</span>
        </div>

        <div class="free-power-body">
          ${schedule && scheduleBanner === "armed" ? this._renderScheduleBanner(schedule) : nothing}
          ${interlocked ? this._renderInterlockBanner(interlockMessageText!) : nothing}

          ${this._renderFreePowerBody(visualState, {
            fp,
            schedule,
            statusText,
            snapshotValid,
            interlocked,
            stagedPowerW,
            stagedDurationMin,
            stagedPowerEntity,
            stagedDurationEntity,
          })}
        </div>
      </div>
    `;
  }

  private _iconFor(state: FreePowerDisplayState): string {
    if (state === "scheduled") return "mdi:calendar-clock";
    if (state === "interlocked") return "mdi:lock-outline";
    switch (state) {
      case "active":
        return "mdi:flash";
      case "armed":
        return "mdi:shield-flash-outline";
      case "busy":
        return "mdi:autorenew";
      case "deferred":
        return "mdi:timer-sand";
      case "recovery_attention":
        return "mdi:alert-circle-outline";
      case "unavailable":
        return "mdi:flash-off-outline";
      default:
        return "mdi:flash-outline";
    }
  }

  private _labelFor(state: FreePowerDisplayState): string {
    if (state === "scheduled") return "Scheduled";
    if (state === "interlocked") return "Interlocked";
    return freePowerStateLabel(state);
  }

  /** Shared muted "why you can't use this right now" banner for both tiles - visually distinct from the schedule banner's purple, deliberately not alarm-coloured (this feature isn't at fault, see interlock.ts's doc comment). */
  private _renderInterlockBanner(message: string): TemplateResult {
    return html`
      <div class="interlock-banner">
        <ha-icon icon="mdi:lock-outline"></ha-icon>
        <div class="interlock-banner-text">${message}</div>
      </div>
    `;
  }

  private _renderFreePowerUnavailable(message: string): TemplateResult {
    return html`
      <div class="tile free-power-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:flash-off-outline"></ha-icon>
            <span class="tile-name">Free Power</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${message}</p>
      </div>
    `;
  }

  private _renderFreePowerBody(
    // "unavailable" is deliberately excluded - the caller (_renderFreePowerTile)
    // already returns its own dedicated unavailable rendering before this is
    // ever invoked, so every remaining case here can safely fall through to
    // the ready/armed body without a redundant runtime check. Note this
    // switches on the TRUE hardware `visualState`, never the cosmetic
    // `displayState` - a "scheduled" tile still renders the plain ready
    // body underneath (with the schedule banner rendered separately above
    // it in _renderFreePowerTile).
    visualState: Exclude<FreePowerVisualState, "unavailable">,
    ctx: {
      fp: FreePowerEntities;
      schedule: ScheduleEntities | undefined;
      statusText: string | undefined;
      snapshotValid: boolean | null;
      interlocked: boolean;
      stagedPowerW: number | null;
      stagedDurationMin: number | null;
      stagedPowerEntity: HassEntity | undefined;
      stagedDurationEntity: HassEntity | undefined;
    }
  ): TemplateResult {
    switch (visualState) {
      case "active":
        return this._renderActiveBody(ctx);
      case "busy":
        return this._renderBusyBody(ctx.statusText, ctx.fp.status);
      case "deferred":
        return this._renderDeferredBody(ctx.statusText, ctx.fp.status);
      case "recovery_attention":
        return this._renderAttentionBody(ctx);
      default:
        return this._renderReadyOrArmedBody(visualState, ctx);
    }
  }

  /** READY and ARMED share the same staging controls - only the arm/start affordances and tile tint differ. */
  private _renderReadyOrArmedBody(
    visualState: "ready" | "armed",
    ctx: {
      fp: FreePowerEntities;
      interlocked: boolean;
      schedule: ScheduleEntities | undefined;
      statusText: string | undefined;
      stagedPowerW: number | null;
      stagedDurationMin: number | null;
      stagedPowerEntity: HassEntity | undefined;
      stagedDurationEntity: HassEntity | undefined;
    }
  ): TemplateResult {
    const hasSchedule = !!ctx.schedule;
    const mode = hasSchedule ? this._mode : "now";

    return html`
      ${hasSchedule ? this._renderModeSelector() : nothing}
      ${mode === "later" && ctx.schedule
        ? this._renderLaterPanel(ctx.schedule)
        : this._renderNowPanel(visualState, ctx)}
    `;
  }

  private _renderModeSelector(): TemplateResult {
    const isNow = this._mode === "now";
    return html`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${isNow ? "is-active" : ""}"
          aria-selected=${isNow}
          @click=${() => (this._mode = "now")}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${!isNow ? "is-active" : ""}"
          aria-selected=${!isNow}
          @click=${() => (this._mode = "later")}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `;
  }

  private _renderNowPanel(
    visualState: "ready" | "armed",
    ctx: {
      fp: FreePowerEntities;
      interlocked: boolean;
      statusText: string | undefined;
      stagedPowerW: number | null;
      stagedDurationMin: number | null;
      stagedPowerEntity: HassEntity | undefined;
      stagedDurationEntity: HassEntity | undefined;
    }
  ): TemplateResult {
    const armed = visualState === "armed";
    const canStart = canActWhileInterlocked(canStartFreePower(visualState), ctx.interlocked);
    const canArm = canActWhileInterlocked(canToggleArm(visualState), ctx.interlocked);

    return html`
      <p class="tile-description">Charge the battery from free/zero-cost grid energy.</p>

      ${this._renderNumberControl({
        label: "Max Charge Power",
        icon: "mdi:flash",
        entity: ctx.stagedPowerEntity,
        value: ctx.stagedPowerW,
        fallbackMin: 500,
        fallbackMax: 8000,
        fallbackStep: 100,
        formatValue: formatPower,
        disabled: ctx.interlocked,
        onPreview: (v) => (this._pendingPower = v),
        onCommit: (v) => this._commitNumber("power", v, ctx.fp.max_charge_power),
      })}
      ${this._renderNumberControl({
        label: "Duration",
        icon: "mdi:timer-outline",
        entity: ctx.stagedDurationEntity,
        value: ctx.stagedDurationMin,
        fallbackMin: 1,
        fallbackMax: 240,
        fallbackStep: 1,
        formatValue: formatDurationMinutes,
        disabled: ctx.interlocked,
        onPreview: (v) => (this._pendingDuration = v),
        onCommit: (v) => this._commitNumber("duration", v, ctx.fp.duration),
      })}

      <div class="readiness-row">
        <ha-icon icon=${armed ? "mdi:shield-check" : "mdi:shield-outline"}></ha-icon>
        <span>${armed ? "Armed - ready to start" : "Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(ctx.statusText, ctx.fp.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${armed ? "is-armed" : ""}"
          ?disabled=${!canArm}
          @click=${() => this._toggleArm(ctx.fp.write_enable, armed)}
        >
          <ha-icon icon=${armed ? "mdi:shield-key" : "mdi:shield-key-outline"}></ha-icon>
          ${armed ? "Disarm" : "Arm Free Power"}
        </button>
        <button
          class="start-button"
          ?disabled=${!canStart}
          @click=${() => this._callService("button", "press", { entity_id: ctx.fp.start })}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `;
  }

  // ---------------------------------------------------------------------
  // LATER (Scheduled Free Power) panel - presents the existing, unmodified
  // home-assistant/packages/ecco_free_power_schedule.yaml package. Never
  // duplicates its validation logic; only stages its input_number/
  // input_datetime entities and arms/cancels via its own input_boolean/
  // script. See schedule.ts for the pure mapping this renders from.
  // ---------------------------------------------------------------------

  private _renderLaterPanel(schedule: ScheduleEntities): TemplateResult {
    const armedRaw = toBoolean(this._entityState(schedule.armed));
    const locked = scheduleFieldsLocked(armedRaw);

    const startText = this._entityState(schedule.start);
    const startDate = parseLocalTimestamp(startText);

    const durationEntity = this._entity(schedule.duration);
    const powerEntity = this._entity(schedule.power);
    const statusEntity = this._entity(schedule.status);
    const lastResult = this._entityState(schedule.last_result);

    const durationMin = this._pendingScheduleDuration ?? toNumber(durationEntity?.state);
    const powerW = this._pendingSchedulePower ?? toNumber(powerEntity?.state);

    const effectiveLimitAttr = statusEntity?.attributes?.effective_power_limit_w;
    const effectiveLimit =
      typeof effectiveLimitAttr === "number"
        ? effectiveLimitAttr
        : toNumber(typeof effectiveLimitAttr === "string" ? effectiveLimitAttr : undefined);
    const powerMaxAttr = this._numericAttr(powerEntity?.attributes?.max, 8000);
    const effectivePowerMax = effectiveSchedulePowerMax(powerMaxAttr, effectiveLimit);

    const rejected = isScheduleRejected(lastResult);
    const blocked = isScheduleBlocked(lastResult);
    const canArmSchedule = !locked && startDate !== null && startDate.getTime() > this._nowMs;

    return html`
      <p class="tile-description">Stage a future Free Power session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${startDate ? this._toDatetimeLocalValue(startDate) : ""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${locked}
          @change=${(e: Event) => this._handleScheduleStartChange(schedule.start, (e.target as HTMLInputElement).value)}
        />
      </div>

      ${this._renderNumberControl({
        label: "Scheduled Power",
        icon: "mdi:flash",
        entity: powerEntity,
        value: powerW,
        fallbackMin: 500,
        fallbackMax: 8000,
        fallbackStep: 100,
        maxOverride: effectivePowerMax,
        formatValue: formatPower,
        disabled: locked || !powerEntity,
        onPreview: (v) => (this._pendingSchedulePower = v),
        onCommit: (v) => this._commitScheduleNumber("power", v, schedule.power),
      })}
      ${this._renderNumberControl({
        label: "Scheduled Duration",
        icon: "mdi:timer-outline",
        entity: durationEntity,
        value: durationMin,
        fallbackMin: 1,
        fallbackMax: 240,
        fallbackStep: 1,
        formatValue: formatDurationMinutes,
        disabled: locked || !durationEntity,
        onPreview: (v) => (this._pendingScheduleDuration = v),
        onCommit: (v) => this._commitScheduleNumber("duration", v, schedule.duration),
      })}

      ${lastResult
        ? html`<p class="firmware-note ${rejected || blocked ? "is-warning" : ""}">${lastResult}</p>`
        : nothing}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${locked || !canArmSchedule}
          @click=${() => this._callServiceObj(scheduleArmServiceCall(schedule.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${locked
          ? "Fields are locked while this schedule is armed - cancel it above to edit, then re-arm."
          : "Arm Schedule never touches the manual Free Power write-enable switch - Home Assistant arms and starts the inverter automatically when the time comes."}
      </p>
    `;
  }

  private _renderScheduleBanner(schedule: ScheduleEntities): TemplateResult {
    const startText = this._entityState(schedule.start);
    const startDate = parseLocalTimestamp(startText);
    const durationMin = toNumber(this._entityState(schedule.duration));
    const powerW = toNumber(this._entityState(schedule.power));
    const countdown = startDate ? formatCountdown(startDate.getTime(), this._nowMs) : null;

    return html`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${startDate ? formatWeekdayDateTime(startDate) : "--"} • ${formatPower(powerW)} • ${formatDurationMinutes(durationMin)}
          </div>
          <div class="schedule-banner-countdown">${countdown ? `Starts in ${countdown}` : "Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${() => this._callServiceObj(scheduleCancelServiceCall(schedule.cancel))}
        >
          Cancel
        </button>
      </div>
    `;
  }

  private _toDatetimeLocalValue(date: Date): string {
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  private _handleScheduleStartChange(entityId: string, rawValue: string): void {
    if (!rawValue) return;
    // datetime-local's value is an unambiguous local-time ISO-like string
    // (no timezone offset) - the platform Date parser is spec-guaranteed to
    // read that as local time, unlike the space-separated firmware/HA
    // format parseLocalTimestamp() exists for elsewhere in this file.
    const parsed = new Date(rawValue);
    if (Number.isNaN(parsed.getTime())) return;
    this._callServiceObj(scheduleSetStartServiceCall(entityId, formatLocalTimestamp(parsed)));
  }

  private _commitScheduleNumber(kind: "power" | "duration", value: number, entityId: string): void {
    if (kind === "power") this._pendingSchedulePower = value;
    else this._pendingScheduleDuration = value;
    this._callServiceObj(scheduleSetNumberServiceCall(entityId, value));
  }

  private _renderActiveBody(ctx: {
    fp: FreePowerEntities;
    statusText: string | undefined;
    snapshotValid: boolean | null;
    stagedPowerW: number | null;
    stagedDurationMin: number | null;
  }): TemplateResult {
    const endsAtText = this._entityState(ctx.fp.ends_at);
    const endsAtDate = parseLocalTimestamp(endsAtText);
    const countdown = endsAtDate ? formatCountdown(endsAtDate.getTime(), this._nowMs) : null;

    return html`
      <div class="active-hero">
        <div class="active-hero-time">${countdown ?? "--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        ${formatPower(ctx.stagedPowerW)} target • ends ${endsAtDate ? this._formatClock(endsAtDate) : endsAtText ?? "--"}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${ctx.snapshotValid ? "mdi:content-save-check-outline" : "mdi:content-save-alert-outline"}></ha-icon>
        <span>${ctx.snapshotValid ? "Original settings snapshot saved" : "No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(ctx.statusText, ctx.fp.status, { alwaysShow: true })}
      ${this._renderDiagnosticsDetails(ctx.fp)}
      ${this._renderEndRestoreButton(ctx.fp.end_restore, "End & Restore Now", false, canEndRestore("active"))}
    `;
  }

  private _renderBusyBody(statusText: string | undefined, statusEntityId: string | undefined): TemplateResult {
    return html`
      <div class="transition-panel">
        <ha-icon class="spin" icon="mdi:autorenew"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Working...</div>
          ${this._renderTransitionDetail(statusText ?? "Free Power is mid-transaction.", statusEntityId)}
        </div>
      </div>
      <p class="transition-hint">Controls are disabled while a transaction is in flight - this clears on its own.</p>
    `;
  }

  private _renderDeferredBody(statusText: string | undefined, statusEntityId: string | undefined): TemplateResult {
    return html`
      <div class="transition-panel deferred">
        <ha-icon icon="mdi:timer-sand"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Waiting for inverter bus</div>
          ${this._renderTransitionDetail(statusText ?? "Modbus bus busy - the watchdog will retry.", statusEntityId)}
        </div>
      </div>
      <p class="transition-hint">This is expected occasionally - the watchdog retries automatically. No action needed.</p>
    `;
  }

  private _renderAttentionBody(ctx: {
    fp: FreePowerEntities;
    statusText: string | undefined;
    snapshotValid: boolean | null;
  }): TemplateResult {
    const presentation = classifyRecoveryAction({ statusText: ctx.statusText, snapshotValid: ctx.snapshotValid });

    return html`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(ctx.statusText ?? "Free Power requires operator attention.", ctx.fp.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${presentation.explanation ??
        "No automatic retry. Starting a new Free Power session is disabled until this clears."}
      </p>
      ${presentation.actionable
        ? this._renderEndRestoreButton(
            ctx.fp.end_restore,
            presentation.actionLabel ?? "End & Restore Now",
            presentation.secondary,
            canEndRestore("recovery_attention")
          )
        : nothing}
    `;
  }

  /** The tappable status-text line used inside the busy/deferred/attention panels - same more-info behaviour as _renderStatusLine(), just embedded in their existing icon+headline+detail layout rather than as its own standalone quiet line. */
  private _renderTransitionDetail(text: string, entityId: string | undefined): TemplateResult {
    return html`
      <div
        class="transition-detail clickable"
        tabindex="0"
        role="button"
        @click=${() => this._moreInfo(entityId)}
        @keydown=${(e: KeyboardEvent) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            this._moreInfo(entityId);
          }
        }}
      >
        ${text}
      </div>
    `;
  }

  /** The quiet, single-line, always-tappable firmware status area used by the ready/armed and active bodies. */
  private _renderStatusLine(
    statusText: string | undefined,
    entityId: string | undefined,
    options?: { alwaysShow?: boolean }
  ): TemplateResult | typeof nothing {
    const show = options?.alwaysShow || (!!statusText && statusText !== "Inactive");
    if (!show || !statusText) return nothing;
    return html`
      <p
        class="firmware-note clickable"
        tabindex="0"
        role="button"
        @click=${() => this._moreInfo(entityId)}
        @keydown=${(e: KeyboardEvent) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            this._moreInfo(entityId);
          }
        }}
      >
        ${statusText}
      </p>
    `;
  }

  private _renderDiagnosticsDetails(fp: FreePowerEntities): TemplateResult | typeof nothing {
    const items: { label: string; value: string }[] = [];
    const push = (label: string, entityId: string | undefined) => {
      const v = toNumber(this._entityState(entityId));
      if (v !== null) items.push({ label, value: v.toString() });
    };
    push("Starts", fp.start_attempts);
    push("Started OK", fp.start_successes);
    push("Restored OK", fp.restore_successes);
    push("Failures", fp.failures);
    if (items.length === 0) return nothing;

    return html`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${items.map((item) => html`<span class="diagnostic-chip">${item.label}: ${item.value}</span>`)}
        </div>
      </details>
    `;
  }

  private _renderEndRestoreButton(entityId: string, label: string, secondary: boolean, enabled: boolean): TemplateResult {
    const confirming = this._confirmEndRestore;
    return html`
      <button
        class="end-restore-button ${secondary ? "secondary" : ""} ${confirming ? "confirming" : ""}"
        ?disabled=${!enabled}
        @click=${() => this._handleEndRestoreClick(entityId)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${confirming ? "Tap again to End & Restore" : label}
        ${confirming ? html`<span class="confirm-progress" style="animation-duration:${CONFIRM_WINDOW_MS}ms"></span>` : nothing}
      </button>
    `;
  }

  private _handleEndRestoreClick(entityId: string): void {
    if (!this._confirmEndRestore) {
      this._confirmEndRestore = true;
      this._confirmTimer = setTimeout(() => {
        this._confirmEndRestore = false;
      }, CONFIRM_WINDOW_MS);
      return;
    }
    if (this._confirmTimer) clearTimeout(this._confirmTimer);
    this._confirmEndRestore = false;
    this._callService("button", "press", { entity_id: entityId });
  }

  private _toggleArm(entityId: string, currentlyArmed: boolean): void {
    this._callService("switch", currentlyArmed ? "turn_off" : "turn_on", { entity_id: entityId });
  }

  /** Commits a staged number control's value once the user finishes interacting (the `change` event, not every `input` tick) - avoids flooding `number.set_value` with a call per pixel of drag. Staging a value is always safe: these numbers never touch the inverter by themselves (see FreePowerEntities.max_charge_power/duration). */
  private _commitNumber(kind: "power" | "duration", value: number, entityId: string): void {
    if (kind === "power") this._pendingPower = value;
    else this._pendingDuration = value;
    this._callService("number", "set_value", { entity_id: entityId, value });
  }

  /** Same as _commitNumber, for Dump-to-Grid's own three staged values. */
  private _commitDumpNumber(kind: "power" | "stop_soc" | "duration", value: number, entityId: string): void {
    if (kind === "power") this._pendingDumpPower = value;
    else if (kind === "stop_soc") this._pendingDumpStopSoc = value;
    else this._pendingDumpDuration = value;
    this._callService("number", "set_value", { entity_id: entityId, value });
  }

  private _handleEndDumpClick(entityId: string): void {
    if (!this._confirmEndDump) {
      this._confirmEndDump = true;
      this._confirmDumpTimer = setTimeout(() => {
        this._confirmEndDump = false;
      }, CONFIRM_WINDOW_MS);
      return;
    }
    if (this._confirmDumpTimer) clearTimeout(this._confirmDumpTimer);
    this._confirmEndDump = false;
    this._callService("button", "press", { entity_id: entityId });
  }

  /** Reads a numeric entity attribute (e.g. a number entity's `min`/`max`/`step`), which Home Assistant may report as either a number or a numeric string, falling back when absent/non-numeric. */
  private _numericAttr(raw: unknown, fallback: number): number {
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
    if (typeof raw === "string") {
      const n = toNumber(raw);
      if (n !== null) return n;
    }
    return fallback;
  }

  private _formatClock(d: Date): string {
    const hh = d.getHours().toString().padStart(2, "0");
    const mm = d.getMinutes().toString().padStart(2, "0");
    return `${hh}:${mm}`;
  }

  private _renderNumberControl(opts: {
    label: string;
    icon: string;
    entity: HassEntity | undefined;
    value: number | null;
    fallbackMin: number;
    fallbackMax: number;
    fallbackStep: number;
    /** Wins outright over both the entity's own `max` attribute and fallbackMax - e.g. the schedule power slider's site-configured effective limit. */
    maxOverride?: number;
    formatValue: (value: number | null) => string;
    disabled?: boolean;
    /** Fires on every drag tick - local visual state only, never a service call. */
    onPreview: (value: number) => void;
    /** Fires once when the user releases/finishes - the actual `*.set_value` call. */
    onCommit: (value: number) => void;
  }): TemplateResult {
    const attrs = opts.entity?.attributes ?? {};
    const min = this._numericAttr(attrs.min, opts.fallbackMin);
    const max = opts.maxOverride ?? this._numericAttr(attrs.max, opts.fallbackMax);
    const step = this._numericAttr(attrs.step, opts.fallbackStep);
    const value = opts.value ?? min;
    const disabled = opts.disabled ?? !opts.entity;
    const fillPct = max > min ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 0;

    return html`
      <div class="number-control">
        <div class="number-control-label">
          <ha-icon icon=${opts.icon}></ha-icon>
          <span>${opts.label}</span>
          <span class="number-control-value">${opts.formatValue(value)}</span>
        </div>
        <input
          type="range"
          class="number-control-slider"
          style="--eaa-slider-fill:${fillPct}%"
          min=${min}
          max=${max}
          step=${step}
          .value=${String(value)}
          ?disabled=${disabled}
          @input=${(e: InputEvent) => {
            const v = Number((e.target as HTMLInputElement).value);
            if (Number.isFinite(v)) opts.onPreview(v);
          }}
          @change=${(e: Event) => {
            const v = Number((e.target as HTMLInputElement).value);
            if (Number.isFinite(v)) opts.onCommit(v);
          }}
        />
      </div>
    `;
  }

  // ---------------------------------------------------------------------
  // Dump to Grid tile - V1: a real, interactive tile once `dump_to_grid:` is
  // configured. Falls back to the original static "Coming Soon" shell when
  // it is not, so existing dashboards keep rendering unchanged. See
  // docs/DUMP_TO_GRID_V1.md.
  // ---------------------------------------------------------------------

  private _renderDumpToGridTile(): TemplateResult {
    const dump = this._config?.dump_to_grid;
    if (!dump || !this.hass) {
      return this._renderDumpToGridLockedShell();
    }

    const active = toBoolean(this._entityState(dump.active));
    const armed = toBoolean(this._entityState(dump.write_enable));
    const operationInProgress = toBoolean(this._entityState(dump.operation_in_progress));
    const snapshotValid = toBoolean(this._entityState(dump.snapshot_valid));
    const statusText = this._entityState(dump.status);

    const visualState = classifyDump({ active, armed, operationInProgress, snapshotValid, statusText });

    if (visualState === "unavailable") {
      return this._renderDumpUnavailable("Dump to Grid entities are unavailable right now.");
    }

    // Same rule as Free Power: a CONFIRMED armed schedule may only upgrade the
    // plain "ready" state - it can never conceal attention/deferred/busy/active.
    const schedule = dump.schedule;
    const scheduleArmed = schedule ? toBoolean(this._entityState(schedule.armed)) : null;
    const scheduledDisplayState = resolveDumpDisplayState(visualState, scheduleArmed);

    // Sibling interlock - same rule and priority as the Free Power tile (see
    // interlock.ts's isInterlocked() doc comment): this feature's own
    // recovery/busy/active states above always outrank it.
    const freePowerVisualState = this._freePowerVisualStateForInterlock();
    const interlocked = isInterlocked(visualState, freePowerVisualState);
    const displayState: DumpDisplayState = interlocked ? "interlocked" : scheduledDisplayState;
    const interlockMessageText = interlocked ? interlockMessage("Free Power", freePowerVisualState) : undefined;

    const stagedPowerEntity = this._entity(dump.export_power);
    const stagedStopSocEntity = this._entity(dump.stop_soc);
    const stagedDurationEntity = this._entity(dump.duration);
    const stagedPowerW = this._pendingDumpPower ?? toNumber(stagedPowerEntity?.state);
    const stagedStopSoc = this._pendingDumpStopSoc ?? toNumber(stagedStopSocEntity?.state);
    const stagedDurationMin = this._pendingDumpDuration ?? toNumber(stagedDurationEntity?.state);

    const icon = this._dumpIconFor(displayState);
    const label = dumpDisplayStateLabel(displayState);

    return html`
      <div class="tile dump-to-grid-tile state-${displayState}">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon=${icon}></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-${displayState}">${label}</span>
        </div>

        <div class="dump-to-grid-body">
          ${schedule && scheduleArmed === true ? this._renderDumpScheduleBanner(schedule) : nothing}
          ${interlocked ? this._renderInterlockBanner(interlockMessageText!) : nothing}

          ${this._renderDumpBody(visualState, {
            dump,
            statusText,
            snapshotValid,
            interlocked,
            stagedPowerW,
            stagedStopSoc,
            stagedDurationMin,
            stagedPowerEntity,
            stagedStopSocEntity,
            stagedDurationEntity,
          })}
        </div>
      </div>
    `;
  }

  private _renderDumpToGridLockedShell(): TemplateResult {
    return html`
      <div class="tile dump-to-grid-tile locked">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-export"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-locked"><ha-icon icon="mdi:lock-outline"></ha-icon> Coming Soon</span>
        </div>
        <p class="tile-description">Export stored battery energy to the grid.</p>

        <div class="locked-preview">
          <div class="locked-row"><span>Export Power</span><span>--</span></div>
          <div class="locked-row"><span>Minimum SOC</span><span>--</span></div>
          <div class="locked-row"><span>Duration</span><span>--</span></div>
        </div>

        <p class="tile-footnote">
          Configure <code>dump_to_grid:</code> on this card to enable Manual Dump to Grid V1.
        </p>
      </div>
    `;
  }

  private _dumpIconFor(state: DumpDisplayState): string {
    switch (state) {
      case "scheduled":
        return "mdi:calendar-clock";
      case "interlocked":
        return "mdi:lock-outline";
      case "active":
        return "mdi:transmission-tower-export";
      case "armed":
        return "mdi:shield-flash-outline";
      case "busy":
        return "mdi:autorenew";
      case "deferred":
        return "mdi:timer-sand";
      case "recovery_attention":
        return "mdi:alert-circle-outline";
      case "unavailable":
        return "mdi:transmission-tower-off";
      default:
        return "mdi:transmission-tower-export";
    }
  }

  private _renderDumpUnavailable(message: string): TemplateResult {
    return html`
      <div class="tile dump-to-grid-tile state-unavailable">
        <div class="tile-header">
          <div class="tile-heading">
            <ha-icon class="tile-icon" icon="mdi:transmission-tower-off"></ha-icon>
            <span class="tile-name">Dump to Grid</span>
          </div>
          <span class="state-pill state-unavailable">Unavailable</span>
        </div>
        <p class="tile-description">${message}</p>
      </div>
    `;
  }

  private _renderDumpBody(
    // "unavailable" is deliberately excluded - the caller already returns
    // its own dedicated unavailable rendering before this is ever invoked.
    // Switches on the TRUE hardware state, never the cosmetic "scheduled"
    // display state (the schedule banner is rendered separately above).
    visualState: Exclude<DumpVisualState, "unavailable">,
    ctx: {
      dump: DumpToGridEntities;
      statusText: string | undefined;
      snapshotValid: boolean | null;
      interlocked: boolean;
      stagedPowerW: number | null;
      stagedStopSoc: number | null;
      stagedDurationMin: number | null;
      stagedPowerEntity: HassEntity | undefined;
      stagedStopSocEntity: HassEntity | undefined;
      stagedDurationEntity: HassEntity | undefined;
    }
  ): TemplateResult {
    switch (visualState) {
      case "active":
        return this._renderDumpActiveBody(ctx);
      case "busy":
        return this._renderBusyBody(ctx.statusText ?? "Dump to Grid is mid-transaction.", ctx.dump.status);
      case "deferred":
        return this._renderDumpDeferredBody(ctx);
      case "recovery_attention":
        return this._renderDumpAttentionBody(ctx);
      default:
        return this._renderDumpReadyOrArmedBody(visualState, ctx);
    }
  }

  /** READY and ARMED share the NOW/LATER selector - exactly Free Power's interaction pattern. */
  private _renderDumpReadyOrArmedBody(
    visualState: "ready" | "armed",
    ctx: {
      dump: DumpToGridEntities;
      statusText: string | undefined;
      interlocked: boolean;
      stagedPowerW: number | null;
      stagedStopSoc: number | null;
      stagedDurationMin: number | null;
      stagedPowerEntity: HassEntity | undefined;
      stagedStopSocEntity: HassEntity | undefined;
      stagedDurationEntity: HassEntity | undefined;
    }
  ): TemplateResult {
    const schedule = ctx.dump.schedule;
    const mode = schedule ? this._dumpMode : "now";

    return html`
      ${schedule ? this._renderDumpModeSelector() : nothing}
      ${mode === "later" && schedule ? this._renderDumpLaterPanel(schedule) : this._renderDumpNowPanel(visualState, ctx)}
      ${this._renderDumpLastEndReason(ctx.dump)}
    `;
  }

  private _renderDumpModeSelector(): TemplateResult {
    const isNow = this._dumpMode === "now";
    return html`
      <div class="mode-selector" role="tablist">
        <button
          type="button"
          role="tab"
          class="mode-tab ${isNow ? "is-active" : ""}"
          aria-selected=${isNow}
          @click=${() => (this._dumpMode = "now")}
        >
          <ha-icon icon="mdi:flash"></ha-icon> Now
        </button>
        <button
          type="button"
          role="tab"
          class="mode-tab ${!isNow ? "is-active" : ""}"
          aria-selected=${!isNow}
          @click=${() => (this._dumpMode = "later")}
        >
          <ha-icon icon="mdi:calendar-clock"></ha-icon> Later
        </button>
      </div>
    `;
  }

  private _renderDumpNowPanel(
    visualState: "ready" | "armed",
    ctx: {
      dump: DumpToGridEntities;
      statusText: string | undefined;
      interlocked: boolean;
      stagedPowerW: number | null;
      stagedStopSoc: number | null;
      stagedDurationMin: number | null;
      stagedPowerEntity: HassEntity | undefined;
      stagedStopSocEntity: HassEntity | undefined;
      stagedDurationEntity: HassEntity | undefined;
    }
  ): TemplateResult {
    const armed = visualState === "armed";
    const canStart = canActWhileInterlocked(canStartDump(visualState), ctx.interlocked);
    const canArm = canActWhileInterlocked(canToggleDumpArm(visualState), ctx.interlocked);

    return html`
      <p class="tile-description">Export stored battery energy to the grid down to a chosen floor.</p>

      ${this._renderNumberControl({
        label: "Export Power",
        icon: "mdi:transmission-tower-export",
        entity: ctx.stagedPowerEntity,
        value: ctx.stagedPowerW,
        fallbackMin: 500,
        fallbackMax: 8000,
        fallbackStep: 100,
        formatValue: formatPower,
        disabled: ctx.interlocked,
        onPreview: (v) => (this._pendingDumpPower = v),
        onCommit: (v) => this._commitDumpNumber("power", v, ctx.dump.export_power),
      })}
      ${this._renderNumberControl({
        label: "Stop SOC",
        icon: "mdi:battery-arrow-down",
        entity: ctx.stagedStopSocEntity,
        value: ctx.stagedStopSoc,
        fallbackMin: 10,
        fallbackMax: 90,
        fallbackStep: 1,
        formatValue: formatPercent,
        disabled: ctx.interlocked,
        onPreview: (v) => (this._pendingDumpStopSoc = v),
        onCommit: (v) => this._commitDumpNumber("stop_soc", v, ctx.dump.stop_soc),
      })}
      ${this._renderNumberControl({
        label: "Duration",
        icon: "mdi:timer-outline",
        entity: ctx.stagedDurationEntity,
        value: ctx.stagedDurationMin,
        fallbackMin: 1,
        fallbackMax: 240,
        fallbackStep: 1,
        formatValue: formatDurationMinutes,
        disabled: ctx.interlocked,
        onPreview: (v) => (this._pendingDumpDuration = v),
        onCommit: (v) => this._commitDumpNumber("duration", v, ctx.dump.duration),
      })}

      <div class="readiness-row">
        <ha-icon icon=${armed ? "mdi:shield-check" : "mdi:shield-outline"}></ha-icon>
        <span>${armed ? "Armed - ready to start" : "Safe - no inverter change made by staging values"}</span>
      </div>
      ${this._renderStatusLine(ctx.statusText, ctx.dump.status)}

      <div class="action-row">
        <button
          class="arm-toggle ${armed ? "is-armed" : ""}"
          ?disabled=${!canArm}
          @click=${() => this._toggleArm(ctx.dump.write_enable, armed)}
        >
          <ha-icon icon=${armed ? "mdi:shield-key" : "mdi:shield-key-outline"}></ha-icon>
          ${armed ? "Disarm" : "Arm Dump to Grid"}
        </button>
        <button
          class="start-button"
          ?disabled=${!canStart}
          @click=${() => this._callService("button", "press", { entity_id: ctx.dump.start })}
        >
          <ha-icon icon="mdi:play-circle-outline"></ha-icon>
          Start Now
        </button>
      </div>
      <p class="arm-caption">Arm is single-use - it's consumed the moment you press Start, or if the attempt is rejected.</p>
    `;
  }

  // ---------------------------------------------------------------------
  // LATER (Scheduled Dump to Grid) panel - presents the existing
  // home-assistant/packages/ecco_dump_to_grid_schedule.yaml package exactly
  // like the Free Power LATER panel presents its own: it only stages the
  // package's input_datetime/input_number helpers and arms/cancels via its
  // input_boolean/script. It never arms the firmware write_enable switch or
  // presses START - at the scheduled time the package does that, and the
  // firmware re-checks every START precondition itself.
  // ---------------------------------------------------------------------

  private _renderDumpLaterPanel(schedule: DumpScheduleEntities): TemplateResult {
    const armedRaw = toBoolean(this._entityState(schedule.armed));
    const locked = scheduleFieldsLocked(armedRaw);

    const startText = this._entityState(schedule.start);
    const startDate = parseLocalTimestamp(startText);

    const durationEntity = this._entity(schedule.duration);
    const powerEntity = this._entity(schedule.power);
    const stopSocEntity = this._entity(schedule.stop_soc);
    const lastResult = this._entityState(schedule.last_result);

    const durationMin = this._pendingDumpScheduleDuration ?? toNumber(durationEntity?.state);
    const powerW = this._pendingDumpSchedulePower ?? toNumber(powerEntity?.state);
    const stopSoc = this._pendingDumpScheduleStopSoc ?? toNumber(stopSocEntity?.state);

    // FAILED TO START (the firmware refused a scheduled START, e.g. a
    // charging TOU slot or a live obligation) is as much a warning as a
    // REJECTED/BLOCKED arm.
    const rejected = isScheduleRejected(lastResult) || (!!lastResult && /^FAILED/i.test(lastResult.trim()));
    const blocked = isScheduleBlocked(lastResult);
    const helpersAvailable = !!powerEntity && !!durationEntity && !!stopSocEntity && armedRaw !== null;
    const canArmSchedule =
      helpersAvailable && !locked && startDate !== null && startDate.getTime() > this._nowMs;

    return html`
      <p class="tile-description">Stage a future Dump to Grid session - Home Assistant arms and starts it automatically.</p>

      <div class="schedule-field">
        <label class="schedule-field-label"><ha-icon icon="mdi:calendar-clock"></ha-icon> Start</label>
        <input
          type="datetime-local"
          class="schedule-datetime-input"
          .value=${startDate ? this._toDatetimeLocalValue(startDate) : ""}
          min=${this._toDatetimeLocalValue(new Date(this._nowMs))}
          ?disabled=${locked}
          @change=${(e: Event) => this._handleScheduleStartChange(schedule.start, (e.target as HTMLInputElement).value)}
        />
      </div>

      ${this._renderNumberControl({
        label: "Scheduled Export Power",
        icon: "mdi:transmission-tower-export",
        entity: powerEntity,
        value: powerW,
        fallbackMin: 500,
        fallbackMax: 8000,
        fallbackStep: 100,
        formatValue: formatPower,
        disabled: locked || !powerEntity,
        onPreview: (v) => (this._pendingDumpSchedulePower = v),
        onCommit: (v) => this._commitDumpScheduleNumber("power", v, schedule.power),
      })}
      ${this._renderNumberControl({
        label: "Scheduled Stop SOC",
        icon: "mdi:battery-arrow-down",
        entity: stopSocEntity,
        value: stopSoc,
        fallbackMin: 10,
        fallbackMax: 90,
        fallbackStep: 1,
        formatValue: formatPercent,
        disabled: locked || !stopSocEntity,
        onPreview: (v) => (this._pendingDumpScheduleStopSoc = v),
        onCommit: (v) => this._commitDumpScheduleNumber("stop_soc", v, schedule.stop_soc),
      })}
      ${this._renderNumberControl({
        label: "Scheduled Duration",
        icon: "mdi:timer-outline",
        entity: durationEntity,
        value: durationMin,
        fallbackMin: 1,
        fallbackMax: 240,
        fallbackStep: 1,
        formatValue: formatDurationMinutes,
        disabled: locked || !durationEntity,
        onPreview: (v) => (this._pendingDumpScheduleDuration = v),
        onCommit: (v) => this._commitDumpScheduleNumber("duration", v, schedule.duration),
      })}

      ${!helpersAvailable
        ? html`<p class="firmware-note is-warning">
            Scheduled Dump to Grid helpers are unavailable - is ecco_dump_to_grid_schedule.yaml installed?
          </p>`
        : nothing}
      ${lastResult ? html`<p class="firmware-note ${rejected || blocked ? "is-warning" : ""}">${lastResult}</p>` : nothing}

      <div class="action-row">
        <button
          class="schedule-arm-toggle"
          ?disabled=${!canArmSchedule}
          @click=${() => this._callServiceObj(scheduleArmServiceCall(schedule.armed))}
        >
          <ha-icon icon="mdi:calendar-arrow-right"></ha-icon>
          Arm Schedule
        </button>
      </div>
      <p class="arm-caption">
        ${locked
          ? "Fields are locked while this schedule is armed - cancel it above to edit, then re-arm."
          : "Arm Schedule never touches the Dump to Grid write-enable switch. At the start time Home Assistant stages these values, arms and presses Start; the firmware re-checks Stop SOC, charging TOU slots and Free Power itself. Arming is refused if it overlaps an armed Free Power schedule or a charging TOU slot."}
      </p>
    `;
  }

  private _renderDumpScheduleBanner(schedule: DumpScheduleEntities): TemplateResult {
    const startDate = parseLocalTimestamp(this._entityState(schedule.start));
    const durationMin = toNumber(this._entityState(schedule.duration));
    const powerW = toNumber(this._entityState(schedule.power));
    const stopSoc = toNumber(this._entityState(schedule.stop_soc));
    const countdown = startDate ? formatCountdown(startDate.getTime(), this._nowMs) : null;

    return html`
      <div class="schedule-banner">
        <ha-icon icon="mdi:calendar-clock"></ha-icon>
        <div class="schedule-banner-text">
          <div class="schedule-banner-line">
            ${startDate ? formatWeekdayDateTime(startDate) : "--"} • ${formatPower(powerW)} • stop
            ${formatPercent(stopSoc)} • ${formatDurationMinutes(durationMin)}
          </div>
          <div class="schedule-banner-countdown">${countdown ? `Starts in ${countdown}` : "Starting..."}</div>
        </div>
        <button
          type="button"
          class="schedule-cancel-button"
          @click=${() => this._callServiceObj(scheduleCancelServiceCall(schedule.cancel))}
        >
          Cancel
        </button>
      </div>
    `;
  }

  private _commitDumpScheduleNumber(kind: "power" | "stop_soc" | "duration", value: number, entityId: string): void {
    if (kind === "power") this._pendingDumpSchedulePower = value;
    else if (kind === "stop_soc") this._pendingDumpScheduleStopSoc = value;
    else this._pendingDumpScheduleDuration = value;
    this._callServiceObj(scheduleSetNumberServiceCall(entityId, value));
  }

  private _renderDumpLastEndReason(dump: DumpToGridEntities): TemplateResult | typeof nothing {
    const reason = this._entityState(dump.last_end_reason);
    if (!reason || reason === "unknown" || reason === "unavailable") return nothing;
    return html`<p class="firmware-note">Last lease ended: ${reason}</p>`;
  }

  private _renderDumpActiveBody(ctx: {
    dump: DumpToGridEntities;
    statusText: string | undefined;
    snapshotValid: boolean | null;
  }): TemplateResult {
    const endsAtText = this._entityState(ctx.dump.ends_at);
    const endsAtDate = parseLocalTimestamp(endsAtText);
    const countdown = endsAtDate ? formatCountdown(endsAtDate.getTime(), this._nowMs) : null;
    const batterySoc = toNumber(this._entityState(ctx.dump.battery_soc));
    // LATCHED values only - never the staged number entities, which can be
    // edited while a lease runs and are not what the inverter was set to.
    const latchedPowerW = resolveLatchedExportPower(toNumber(this._entityState(ctx.dump.active_export_power)), ctx.statusText);
    const latchedStopSoc = resolveLatchedStopSoc(toNumber(this._entityState(ctx.dump.active_stop_soc)), ctx.statusText);

    return html`
      <div class="active-hero">
        <div class="active-hero-time">${countdown ?? "--:--"}</div>
        <div class="active-hero-label">time remaining</div>
      </div>
      <div class="active-secondary-line">
        Target ${formatPower(latchedPowerW)} export • ends ${endsAtDate ? this._formatClock(endsAtDate) : endsAtText ?? "--"}
      </div>
      <div class="active-secondary-line">
        Battery: ${formatPercent(batterySoc)} • stops at ${formatPercent(latchedStopSoc)}
      </div>

      <div class="readiness-row">
        <ha-icon icon=${ctx.snapshotValid ? "mdi:content-save-check-outline" : "mdi:content-save-alert-outline"}></ha-icon>
        <span>${ctx.snapshotValid ? "Original settings snapshot saved" : "No snapshot recorded - check status"}</span>
      </div>

      ${this._renderStatusLine(ctx.statusText, ctx.dump.status, { alwaysShow: true })}
      ${this._renderDumpDiagnosticsDetails(ctx.dump)}
      ${this._renderEndDumpButton(ctx.dump.end_restore, "End & Restore Now", canEndDump("active"))}
    `;
  }

  /** Free Power's shared deferred panel, plus End & Restore while a restore obligation is outstanding (always safe - the firmware only ever defers or restores). */
  private _renderDumpDeferredBody(ctx: {
    dump: DumpToGridEntities;
    statusText: string | undefined;
    snapshotValid: boolean | null;
  }): TemplateResult {
    return html`
      ${this._renderDeferredBody(ctx.statusText, ctx.dump.status)}
      ${ctx.snapshotValid === true
        ? this._renderEndDumpButton(ctx.dump.end_restore, "End & Restore Now", canEndDump("deferred"))
        : nothing}
    `;
  }

  private _renderDumpAttentionBody(ctx: {
    dump: DumpToGridEntities;
    statusText: string | undefined;
    snapshotValid: boolean | null;
  }): TemplateResult {
    const hasRecoveryControls = !!ctx.dump.recovery_arm && !!ctx.dump.recovery_force_restore && !!ctx.dump.recovery_accept;
    const showRecovery = hasRecoveryControls && dumpRecoveryControlsVisible(ctx.statusText, ctx.snapshotValid);

    return html`
      <div class="attention-panel">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="transition-text">
          <div class="transition-headline">Attention needed</div>
          ${this._renderTransitionDetail(ctx.statusText ?? "Dump to Grid requires operator attention.", ctx.dump.status)}
        </div>
      </div>
      <p class="transition-hint">
        ${showRecovery
          ? "Automatic restore is stopped until you decide. Arm recovery, then Force Restore Original (writes only the saved original settings) or Accept Current State (writes nothing; refused while the inverter still shows Dump export)."
          : "If the status above says the watchdog will retry, ECCO keeps retrying the restore automatically. Only OPERATOR DECISION REQUIRED stops automatic retries."}
      </p>
      ${showRecovery ? this._renderDumpRecoveryPanel(ctx.dump) : nothing}
      ${this._renderEndDumpButton(ctx.dump.end_restore, "End & Restore Now", canEndDump("recovery_attention"))}
    `;
  }

  /** Operator recovery controls - only rendered while the firmware says an operator decision is required (see dumpRecoveryControlsVisible). The firmware independently requires the Recovery Arm and re-checks every other precondition; it also disarms after every press. */
  private _renderDumpRecoveryPanel(dump: DumpToGridEntities): TemplateResult {
    const recArmed = toBoolean(this._entityState(dump.recovery_arm)) === true;
    const recoveryState = this._entityState(dump.recovery_state);

    return html`
      <div class="dump-recovery-panel">
        ${recoveryState && recoveryState !== "unknown" && recoveryState !== "unavailable"
          ? html`<p class="firmware-note">${recoveryState}</p>`
          : nothing}
        <div class="action-row">
          <button
            class="arm-toggle ${recArmed ? "is-armed" : ""}"
            @click=${() => this._toggleArm(dump.recovery_arm!, recArmed)}
          >
            <ha-icon icon=${recArmed ? "mdi:shield-key" : "mdi:shield-key-outline"}></ha-icon>
            ${recArmed ? "Disarm Recovery" : "Arm Recovery"}
          </button>
        </div>
        <div class="action-row">
          <button
            class="start-button"
            ?disabled=${!recArmed}
            @click=${() => this._callService("button", "press", { entity_id: dump.recovery_force_restore })}
          >
            <ha-icon icon="mdi:backup-restore"></ha-icon>
            Force Restore Original
          </button>
          <button
            class="arm-toggle"
            ?disabled=${!recArmed}
            @click=${() => this._callService("button", "press", { entity_id: dump.recovery_accept })}
          >
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            Accept Current State
          </button>
        </div>
      </div>
    `;
  }

  private _renderDumpDiagnosticsDetails(dump: DumpToGridEntities): TemplateResult | typeof nothing {
    const items: { label: string; value: string }[] = [];
    const push = (label: string, entityId: string | undefined) => {
      const v = toNumber(this._entityState(entityId));
      if (v !== null) items.push({ label, value: v.toString() });
    };
    push("Starts", dump.start_attempts);
    push("Started OK", dump.start_successes);
    push("Restored OK", dump.restore_successes);
    push("Failures", dump.failures);
    if (items.length === 0) return nothing;

    return html`
      <details class="diagnostics-details">
        <summary>Details</summary>
        <div class="diagnostics-row">
          ${items.map((item) => html`<span class="diagnostic-chip">${item.label}: ${item.value}</span>`)}
        </div>
      </details>
    `;
  }

  private _renderEndDumpButton(entityId: string, label: string, enabled: boolean): TemplateResult {
    const confirming = this._confirmEndDump;
    return html`
      <button
        class="end-restore-button ${confirming ? "confirming" : ""}"
        ?disabled=${!enabled}
        @click=${() => this._handleEndDumpClick(entityId)}
      >
        <ha-icon icon="mdi:backup-restore"></ha-icon>
        ${confirming ? "Tap again to End & Restore" : label}
        ${confirming ? html`<span class="confirm-progress" style="animation-duration:${CONFIRM_WINDOW_MS}ms"></span>` : nothing}
      </button>
    `;
  }

  // ---------------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------------

  static styles = css`
    :host {
      /* Container query, not a viewport media query: this card is often
         docked in a narrow dashboard column on an otherwise-wide desktop
         browser (a sidebar/split-view layout), which a viewport-width
         media query would never see as "narrow" - the responsive rules
         below need to react to the CARD's own rendered width instead. */
      container-type: inline-size;

      --eaa-bg: var(--ecco-card-background, #141c2d);
      --eaa-surface: color-mix(in srgb, var(--eaa-bg) 82%, white 6%);
      --eaa-border: color-mix(in srgb, var(--eaa-bg) 70%, white 12%);
      --eaa-text: var(--primary-text-color, #eef2f7);
      --eaa-text-muted: var(--secondary-text-color, #9aa7b8);
      --eaa-accent: var(--primary-color, #4fd1ff);
      --eaa-ok: #38d996;
      --eaa-warning: #f4b942;
      --eaa-fault: #ff5c6c;
      --eaa-armed: #ffbd3d;
      --eaa-schedule: #c07cff;
      --eaa-glow: color-mix(in srgb, var(--eaa-accent) 45%, transparent);

      display: block;
    }

    ha-card {
      background: linear-gradient(160deg, var(--eaa-bg), color-mix(in srgb, var(--eaa-bg) 88%, black 8%));
      color: var(--eaa-text);
      border-radius: 20px;
      padding: 18px 18px 20px;
      overflow: hidden;
    }

    .card-title {
      margin: 0 0 14px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--eaa-text);
    }

    .actions-grid {
      display: grid;
      /* 2026-09-26 sibling card polish: Free Power and Dump to Grid are
         equal first-class siblings, not a main feature plus a secondary
         column - both tracks get the same flexible 1fr share, each with the
         same 280px floor Dump to Grid alone used to have, so neither tile's
         controls (NOW/LATER selector, sliders, Arm/Start, banners) get
         squeezed. No max-width on the grid itself: a real wide dashboard
         card should use its full width - see .free-power-body/
         .dump-to-grid-body below for where the actual controls are capped
         instead, so sliders/buttons never stretch edge-to-edge even though
         each tile's own card border now does. */
      grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr);
      gap: 16px;
      /* 2026-09-26 equal-height polish: stretch (the grid default, made
         explicit here) rather than "start" - Dump to Grid's extra Stop SOC
         row and status/last-lease line make it naturally taller than Free
         Power, and the two should still finish on the same line rather than
         Free Power ending early with a visible gap beneath it. Only has an
         effect while both tiles share one grid row (the two-column desktop/
         tablet layout above) - the single-column stack below has exactly
         one tile per row, so this is a no-op there and each stacked card
         keeps its own natural content height (see .tile's comment below). */
      align-items: stretch;
    }

    @container (max-width: 620px) {
      .actions-grid {
        grid-template-columns: 1fr;
      }
    }

    /* Caps and centres the actual staging/control area within each tile -
       the tile's own border/background still spans the full flexible grid
       column (so the tile reads as deliberately sized, not glued to one
       side with empty space beside it), but the sliders, buttons and text
       inside stay a comfortable, non-absurd width. Centring (not
       left-alignment) is what keeps the extra space either side of the
       controls, once a tile is wider than this, from reading as a leftover
       void - has no effect at all once the tile itself is narrower than
       this, which is the common case on tablet/mobile and needs no
       separate breakpoint. Both tiles share the same cap so they read as
       the same product family.
       Also a flex column (2026-09-26 equal-height polish) so it can grow to
       fill whatever extra height .actions-grid's stretch gives the shorter
       tile - see .action-row's margin-top: auto below for where that spare
       height actually goes. */
    .free-power-body,
    .dump-to-grid-body {
      max-width: 680px;
      margin: 0 auto;
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
    }

    .tile {
      border-radius: 16px;
      background: var(--eaa-surface);
      border: 1px solid var(--eaa-border);
      padding: 14px 16px 16px;
      box-sizing: border-box;
      /* Flex column (2026-09-26 equal-height polish) purely so
         .free-power-body/.dump-to-grid-body above can flex:1 to fill
         whatever height .actions-grid's align-items: stretch gives this
         tile - visually identical to plain block stacking otherwise. */
      display: flex;
      flex-direction: column;
      transition:
        border-color 0.28s ease,
        background 0.28s ease,
        box-shadow 0.28s ease;
    }

    .tile-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }

    .tile-heading {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .tile-icon {
      --mdc-icon-size: 20px;
      color: var(--eaa-text-muted);
    }

    .tile-name {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.01em;
      /* Never truncated (e.g. "Dump to Grid" -> "Dump...") - if the header
         row gets tight, the pill wraps to its own line before the name
         would ever be squeezed (see .tile-header's flex-wrap above). */
      white-space: normal;
    }

    .tile-description {
      margin: 2px 0 12px;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    .state-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 10.5px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 4px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
      white-space: nowrap;
    }
    .state-pill ha-icon {
      --mdc-icon-size: 12px;
    }
    .state-pill.state-ready {
      background: color-mix(in srgb, var(--eaa-accent) 20%, transparent);
      color: var(--eaa-accent);
    }
    .state-pill.state-armed {
      background: color-mix(in srgb, var(--eaa-armed) 24%, transparent);
      color: var(--eaa-armed);
    }
    .state-pill.state-scheduled {
      background: color-mix(in srgb, var(--eaa-schedule) 24%, transparent);
      color: var(--eaa-schedule);
    }
    .state-pill.state-active {
      background: color-mix(in srgb, var(--eaa-ok) 24%, transparent);
      color: var(--eaa-ok);
    }
    .state-pill.state-busy,
    .state-pill.state-deferred {
      background: color-mix(in srgb, var(--eaa-warning) 20%, transparent);
      color: var(--eaa-warning);
    }
    .state-pill.state-recovery_attention {
      background: color-mix(in srgb, var(--eaa-fault) 24%, transparent);
      color: var(--eaa-fault);
    }
    .state-pill.state-locked {
      background: color-mix(in srgb, var(--eaa-text-muted) 16%, transparent);
      color: var(--eaa-text-muted);
    }
    .state-pill.state-interlocked {
      background: color-mix(in srgb, var(--eaa-text-muted) 20%, transparent);
      color: var(--eaa-text-muted);
    }

    /* ---- Free Power tile state tints ---- */
    .free-power-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .free-power-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .free-power-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .free-power-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .free-power-tile.state-busy,
    .free-power-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .free-power-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    .free-power-tile.state-unavailable {
      opacity: 0.6;
    }
    /* Subdued, no glow/animation - a deliberately quieter tint than
       recovery_attention/busy (this feature is not at fault, its sibling
       currently owns the inverter, see interlock.ts). */
    .free-power-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }

    /* ---- Dump to Grid tile state tints - same tokens as Free Power above ---- */
    .dump-to-grid-tile.state-ready {
      border-color: var(--eaa-border);
    }
    .dump-to-grid-tile.state-armed {
      border-color: color-mix(in srgb, var(--eaa-armed) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-armed) 8%, var(--eaa-surface));
      box-shadow: 0 0 20px -8px color-mix(in srgb, var(--eaa-armed) 55%, transparent);
    }
    .dump-to-grid-tile.state-active {
      border-color: color-mix(in srgb, var(--eaa-ok) 60%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-ok) 9%, var(--eaa-surface));
      box-shadow: 0 0 24px -6px color-mix(in srgb, var(--eaa-ok) 50%, transparent);
      animation: eaa-active-glow 3.4s ease-in-out infinite;
    }
    .dump-to-grid-tile.state-scheduled {
      border-color: color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-schedule) 7%, var(--eaa-surface));
      box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-schedule) 45%, transparent);
    }
    .dump-recovery-panel {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px;
      border-radius: 12px;
      border: 1px dashed color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
    }
    .dump-to-grid-tile.state-busy,
    .dump-to-grid-tile.state-deferred {
      border-color: color-mix(in srgb, var(--eaa-warning) 45%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-warning) 6%, var(--eaa-surface));
    }
    .dump-to-grid-tile.state-recovery_attention {
      border-color: color-mix(in srgb, var(--eaa-fault) 55%, var(--eaa-border));
      background: color-mix(in srgb, var(--eaa-fault) 8%, var(--eaa-surface));
      box-shadow: 0 0 18px -6px color-mix(in srgb, var(--eaa-fault) 45%, transparent);
    }
    /* Subdued, no glow/animation - same rationale as
       .free-power-tile.state-interlocked above. */
    .dump-to-grid-tile.state-interlocked {
      border-color: var(--eaa-border);
      background: color-mix(in srgb, var(--eaa-text-muted) 5%, var(--eaa-surface));
      opacity: 0.82;
    }
    .dump-to-grid-tile.state-unavailable {
      opacity: 0.6;
    }

    @keyframes eaa-active-glow {
      0%,
      100% {
        box-shadow: 0 0 18px -8px color-mix(in srgb, var(--eaa-ok) 45%, transparent);
      }
      50% {
        box-shadow: 0 0 26px -4px color-mix(in srgb, var(--eaa-ok) 62%, transparent);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .free-power-tile.state-active,
      .dump-to-grid-tile.state-active {
        animation: none;
      }
      .spin {
        animation: none !important;
      }
      .confirm-progress {
        display: none;
      }
    }

    /* ---- NOW / LATER mode selector ---- */
    .mode-selector {
      display: flex;
      gap: 4px;
      padding: 3px;
      margin-bottom: 12px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--eaa-bg) 60%, transparent);
      border: 1px solid var(--eaa-border);
    }
    .mode-tab {
      flex: 1 1 auto;
      border: none;
      background: transparent;
      color: var(--eaa-text-muted);
      padding: 7px 10px;
      font-size: 12px;
      font-weight: 700;
    }
    .mode-tab ha-icon {
      --mdc-icon-size: 15px;
    }
    .mode-tab.is-active {
      background: var(--eaa-surface);
      color: var(--eaa-text);
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
    }

    /* ---- Schedule banner (shown in both Now and Later views while armed) ---- */
    .schedule-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-schedule) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-schedule) 45%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .schedule-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-schedule);
      flex-shrink: 0;
    }
    .schedule-banner-text {
      min-width: 0;
      flex: 1 1 auto;
    }
    .schedule-banner-line {
      font-size: 12px;
      font-weight: 700;
      color: var(--eaa-text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .schedule-banner-countdown {
      font-size: 11px;
      color: var(--eaa-schedule);
      font-variant-numeric: tabular-nums;
    }
    .schedule-cancel-button {
      flex: 0 0 auto;
      padding: 7px 12px;
      font-size: 11px;
      min-height: 36px;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      background: transparent;
    }

    /* ---- Interlock banner - deliberately muted/neutral, not warning-
       coloured like the schedule banner above: this feature isn't at
       fault, its sibling currently owns the inverter (see interlock.ts). */
    .interlock-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, var(--eaa-surface));
      border: 1px dashed color-mix(in srgb, var(--eaa-text-muted) 40%, var(--eaa-border));
      margin-bottom: 12px;
    }
    .interlock-banner ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-text-muted);
      flex-shrink: 0;
    }
    .interlock-banner-text {
      min-width: 0;
      flex: 1 1 auto;
      font-size: 12px;
      font-weight: 600;
      color: var(--eaa-text-muted);
      line-height: 1.4;
    }

    /* ---- Schedule (LATER) fields ---- */
    .schedule-field {
      margin-bottom: 12px;
    }
    .schedule-field-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .schedule-field-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .schedule-datetime-input {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      font-size: 13px;
      color: var(--eaa-text);
      background: color-mix(in srgb, var(--eaa-bg) 55%, transparent);
      border: 1px solid var(--eaa-border);
      border-radius: 8px;
      padding: 9px 10px;
      min-height: 40px;
      color-scheme: dark;
    }
    .schedule-datetime-input:disabled {
      opacity: 0.5;
    }
    .schedule-arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-schedule) 55%, var(--eaa-border));
      color: var(--eaa-schedule);
      background: color-mix(in srgb, var(--eaa-schedule) 10%, var(--eaa-surface));
    }
    .schedule-arm-toggle:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-schedule) 18%, var(--eaa-surface));
    }

    .arm-caption {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 8px 0 0;
      opacity: 0.85;
    }

    /* ---- Number controls ---- */
    .number-control {
      margin-bottom: 12px;
    }
    .number-control-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      margin-bottom: 5px;
    }
    .number-control-label ha-icon {
      --mdc-icon-size: 14px;
    }
    .number-control-value {
      margin-left: auto;
      font-size: 13px;
      font-weight: 700;
      color: var(--eaa-text);
      font-variant-numeric: tabular-nums;
    }
    .number-control-slider {
      width: 100%;
      appearance: none;
      -webkit-appearance: none;
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(
        to right,
        var(--eaa-accent) 0%,
        var(--eaa-accent) var(--eaa-slider-fill, 0%),
        color-mix(in srgb, var(--eaa-text-muted) 28%, transparent) var(--eaa-slider-fill, 0%)
      );
      outline: none;
      cursor: pointer;
    }
    .number-control-slider::-webkit-slider-thumb {
      appearance: none;
      -webkit-appearance: none;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--eaa-accent) 60%, transparent);
    }
    .number-control-slider::-moz-range-thumb {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--eaa-accent);
      border: 2px solid var(--eaa-bg);
    }
    .number-control-slider:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .number-control-slider:focus-visible {
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--eaa-accent) 40%, transparent);
    }

    .readiness-row {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      margin: 6px 0 10px;
    }
    .readiness-row ha-icon {
      --mdc-icon-size: 15px;
    }

    .firmware-note {
      /* Deliberately quiet - a plain status line, not a boxed/input-like
         control. The literal firmware text stays fully readable and
         tappable; it just no longer competes visually with the actual
         controls above it. .is-warning (below) is the one exception - a
         schedule REJECTED/BLOCKED outcome earns the extra weight. */
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      opacity: 0.9;
      margin: 0 0 10px;
      line-height: 1.4;
      word-break: break-word;
    }
    .firmware-note.is-warning {
      background: color-mix(in srgb, var(--eaa-warning) 16%, transparent);
      color: color-mix(in srgb, var(--eaa-warning) 70%, var(--eaa-text));
      border-radius: 8px;
      padding: 6px 9px;
      opacity: 1;
    }
    .firmware-note.clickable,
    .transition-detail.clickable {
      cursor: pointer;
    }
    .firmware-note.clickable:hover {
      color: var(--eaa-text);
      opacity: 1;
    }
    .firmware-note:focus-visible,
    .transition-detail:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .action-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      /* 2026-09-26 equal-height polish: an auto top margin inside the now-
         flex-column .free-power-body/.dump-to-grid-body absorbs whatever
         spare height align-items: stretch gave the shorter tile, so the
         Arm/Start row (and the footer text right after it) settles at the
         bottom of the card instead of leaving a gap beneath it - every
         control above keeps its normal spacing untouched. Resolves to 0
         (today's exact layout) whenever there's no spare height to absorb -
         the taller tile, and every tile once stacked single-column. */
      margin-top: auto;
    }

    button {
      font: inherit;
      border: 1px solid var(--eaa-border);
      background: var(--eaa-surface);
      color: var(--eaa-text);
      border-radius: 10px;
      padding: 10px 14px;
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      font-size: 12.5px;
      font-weight: 700;
      cursor: pointer;
      transition:
        background 0.18s ease,
        border-color 0.18s ease,
        opacity 0.18s ease,
        transform 0.1s ease;
      flex: 1 1 auto;
    }
    button ha-icon {
      --mdc-icon-size: 16px;
    }
    button:disabled {
      opacity: 0.38;
      cursor: not-allowed;
    }
    button:not(:disabled):active {
      transform: scale(0.98);
    }
    button:focus-visible {
      outline: 2px solid var(--eaa-accent);
      outline-offset: 1px;
    }

    .arm-toggle {
      border-color: color-mix(in srgb, var(--eaa-armed) 45%, var(--eaa-border));
      color: var(--eaa-armed);
    }
    .arm-toggle.is-armed {
      background: color-mix(in srgb, var(--eaa-armed) 18%, var(--eaa-surface));
      border-color: color-mix(in srgb, var(--eaa-armed) 70%, var(--eaa-border));
    }

    .start-button {
      border-color: color-mix(in srgb, var(--eaa-ok) 55%, var(--eaa-border));
      color: var(--eaa-ok);
      background: color-mix(in srgb, var(--eaa-ok) 10%, var(--eaa-surface));
    }
    .start-button:not(:disabled):hover {
      background: color-mix(in srgb, var(--eaa-ok) 18%, var(--eaa-surface));
    }

    .end-restore-button {
      position: relative;
      overflow: hidden;
      width: 100%;
      border-color: color-mix(in srgb, var(--eaa-fault) 45%, var(--eaa-border));
      color: var(--eaa-fault);
      margin-top: 4px;
    }
    .end-restore-button.secondary {
      border-color: var(--eaa-border);
      color: var(--eaa-text-muted);
      background: transparent;
      font-weight: 600;
    }
    .end-restore-button.confirming {
      background: color-mix(in srgb, var(--eaa-fault) 22%, var(--eaa-surface));
      border-color: var(--eaa-fault);
    }
    .confirm-progress {
      position: absolute;
      left: 0;
      bottom: 0;
      height: 3px;
      background: currentColor;
      animation-name: eaa-confirm-shrink;
      animation-timing-function: linear;
      animation-fill-mode: forwards;
    }
    @keyframes eaa-confirm-shrink {
      from {
        width: 100%;
      }
      to {
        width: 0%;
      }
    }

    /* ---- Active hero ---- */
    .active-hero {
      text-align: center;
      padding: 6px 0 2px;
    }
    .active-hero-time {
      font-size: 34px;
      font-weight: 800;
      color: var(--eaa-ok);
      font-variant-numeric: tabular-nums;
      line-height: 1.1;
    }
    .active-hero-label {
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--eaa-text-muted);
      margin-top: 2px;
    }
    .active-secondary-line {
      text-align: center;
      font-size: 12.5px;
      color: var(--eaa-text-muted);
      margin: 8px 0 12px;
    }

    .diagnostics-details {
      margin: 0 0 10px;
    }
    .diagnostics-details summary {
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      color: var(--eaa-text-muted);
      list-style: none;
      user-select: none;
    }
    .diagnostics-details summary::-webkit-details-marker {
      display: none;
    }
    .diagnostics-details summary::before {
      content: "▸ ";
    }
    .diagnostics-details[open] summary::before {
      content: "▾ ";
    }
    .diagnostics-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .diagnostic-chip {
      font-size: 9.5px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 12%, transparent);
      border-radius: 999px;
      padding: 3px 8px;
    }

    /* ---- Transition / attention panels ---- */
    .transition-panel,
    .attention-panel {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-warning) 10%, transparent);
      margin-bottom: 8px;
    }
    .attention-panel {
      background: color-mix(in srgb, var(--eaa-fault) 12%, transparent);
    }
    .transition-panel ha-icon,
    .attention-panel ha-icon {
      --mdc-icon-size: 22px;
      color: var(--eaa-warning);
      flex-shrink: 0;
      margin-top: 1px;
    }
    .attention-panel ha-icon {
      color: var(--eaa-fault);
    }
    .transition-panel.deferred ha-icon {
      color: var(--eaa-warning);
    }
    .transition-text {
      min-width: 0;
    }
    .transition-headline {
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .transition-detail {
      font-size: 11.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      word-break: break-word;
    }
    .transition-hint {
      font-size: 11px;
      color: var(--eaa-text-muted);
      margin: 0 0 10px;
      line-height: 1.4;
    }

    .spin {
      animation: eaa-spin 1.6s linear infinite;
    }
    @keyframes eaa-spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }

    /* ---- Dump to Grid (locked) tile ---- */
    .dump-to-grid-tile.locked {
      background: color-mix(in srgb, var(--eaa-bg) 92%, transparent);
      position: relative;
    }
    /* Scoped to .locked only - the dimmed icon is a "not available yet" cue
       for the static preview shell and must NOT bleed into the real
       interactive tile once dump_to_grid: is configured (V1). */
    .dump-to-grid-tile.locked .tile-icon {
      opacity: 0.6;
    }
    .locked-preview {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 10px;
      opacity: 0.55;
      pointer-events: none;
      user-select: none;
    }
    .locked-row {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--eaa-text-muted);
      background: color-mix(in srgb, var(--eaa-text-muted) 8%, transparent);
      border-radius: 8px;
      padding: 7px 10px;
    }
    .tile-footnote {
      font-size: 10.5px;
      color: var(--eaa-text-muted);
      line-height: 1.4;
      margin: 0;
      opacity: 0.85;
    }

    /* Mobile: Dump to Grid collapses to a compact locked row - header +
       description + footnote only, dropping the dimmed preview rows. */
    /* Covers both the cramped-second-column case just above the 620px
       stacking point, and a typical stacked phone width below it - in
       both cases Dump to Grid has too little room to justify the three
       dimmed preview rows. */
    @container (max-width: 700px) {
      .dump-to-grid-tile .locked-preview {
        display: none;
      }
      .dump-to-grid-tile {
        padding: 12px 14px 14px;
      }
    }

    /* ---- layout: tabbed (OVW1) - one track visible at a time. The track
       tabs reuse the NOW/LATER selector's look, the header chips reuse the
       state-pill tones, and the cross-track alert banner mirrors the
       schedule banner's shape in the hidden track's own tone. ---- */
    .tabbed-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-bottom: 12px;
    }
    .tabbed-header .card-title {
      margin: 0;
    }
    .track-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .track-selector {
      border-radius: 12px;
      margin-bottom: 10px;
    }
    .track-tab {
      min-height: 44px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 800;
    }
    .track-tab ha-icon {
      --mdc-icon-size: 17px;
    }
    .track-alert {
      --eaa-alert: var(--eaa-accent);
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--eaa-alert) 14%, var(--eaa-surface));
      border: 1px solid color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
      margin-bottom: 12px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.4;
    }
    .track-alert-warning {
      --eaa-alert: var(--eaa-warning);
    }
    .track-alert-fault {
      --eaa-alert: var(--eaa-fault);
    }
    .track-alert ha-icon {
      --mdc-icon-size: 19px;
      color: var(--eaa-alert);
      flex-shrink: 0;
    }
    .track-alert-text {
      min-width: 0;
      flex: 1 1 auto;
      word-break: break-word;
    }
    .track-alert-show {
      flex: 0 0 auto;
      min-height: 36px;
      padding: 7px 12px;
      font-size: 11px;
      background: transparent;
      color: var(--eaa-alert);
      border-color: color-mix(in srgb, var(--eaa-alert) 45%, var(--eaa-border));
    }
    .actions-grid.is-tabbed {
      /* minmax(0, 1fr), not 1fr: a bare 1fr track is min-content-sized and lets a long nowrap line (the armed
         schedule banner) push the single tile wider than the card on a phone. Scoped to the tabbed layout. */
      grid-template-columns: minmax(0, 1fr);
    }
    @container (max-width: 620px) {
      .tabbed-header {
        flex-direction: column;
        align-items: flex-start;
      }
      .track-tab {
        padding: 7px 8px;
        font-size: 12px;
      }
    }
  `;
}

declare global {
  interface HTMLElementTagNameMap {
    "ecco-energy-actions-card": EccoEnergyActionsCard;
  }
}

// HACS/Lovelace card-picker registration.
(window as unknown as { customCards?: unknown[] }).customCards = [
  ...(((window as unknown as { customCards?: unknown[] }).customCards) ?? []),
  {
    type: "ecco-energy-actions-card",
    name: "ECCO Energy Actions Card",
    description:
      "Free Power as a real product feature (staged controls, two-step arm/start safety, live firmware states, Now/Later scheduling) plus a locked Dump to Grid preview.",
    preview: false,
  },
];
