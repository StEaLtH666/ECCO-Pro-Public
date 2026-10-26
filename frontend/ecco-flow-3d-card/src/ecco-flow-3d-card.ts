import { LitElement, html, css, nothing, type TemplateResult, type PropertyValues } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { DEFAULT_STALE_AFTER_S, normaliseSolarSources, validateConfig, type EccoFlow3dCardConfig } from "./config.ts";
import {
  aggregateSolarW,
  batteryState,
  buildFlowEdges,
  gridState,
  normaliseBatteryPower,
  normaliseGridPower,
  resolveHomeW,
  siteIsIdle,
  splitSolarFlows,
  type FlowEdge,
  type FlowId,
} from "./core/power.ts";
import { motionFor } from "./core/motion.ts";
import { formatAge, formatEnergy, formatPercent, formatPower, formatPowerCompact, toNumber } from "./core/format.ts";
import {
  attrsOf,
  classifyOnOff,
  minutesOfDay,
  numberOf,
  reserveRuntimeLine,
  reserveRuntimeTile,
  reserveRuntimeTooltip,
  resolveDaylight,
  resolveFreshness,
  resolveHealth,
  resolveReserveRuntime,
  resolveSession,
  resolveTimeToReserveMinutes,
  resolveTimeToTarget,
  resolveTouSlot,
  stateOf,
  type HassEntity,
  type States,
  type Tone,
} from "./core/status.ts";
import { renderScene, type PillData, type SceneModel } from "./scene/scene.ts";
import { v4Layout, v4ScaleForWidth } from "./scene/iso.ts";
import { SCENE_KEYS, sceneUrl, selectScene, type SceneKey } from "./core/scenes.ts";
import { ICONS, type IconName } from "./scene/icons.ts";

interface HomeAssistantLike {
  states: States;
}

interface Tile {
  key: string;
  icon: IconName;
  label: string;
  value: string;
  sub: string;
  tone: Tone;
  entity?: string;
  wide?: boolean;
  title?: string;
}

const REFRESH_MS = 15000;

@customElement("ecco-flow-3d-card")
export class EccoFlow3dCard extends LitElement {
  @property({ attribute: false }) public hass?: HomeAssistantLike;
  @state() private _config?: EccoFlow3dCardConfig;
  @state() private _detailsOpen = false;
  @state() private _nowMs = Date.now();
  /** Scene plates currently drawn: the active one and, during a crossfade, the previous one underneath. */
  @state() private _layers: Array<{ url: string; key: string; entering: boolean }> = [];
  /** Plate URLs that failed to load; the vector scene takes over while the active plate is one of them. */
  private _failedPlates = new Set<string>();
  private _fadeTimer = 0;
  /** Card width in px (ResizeObserver): picks the overlay scale of the artwork layout. */
  @state() private _widthPx = 0;
  private _resize?: ResizeObserver;

  private _raf = 0;
  private _timer = 0;
  private _lengthCache = new WeakMap<SVGPathElement, { d: string; length: number }>();
  private _reducedMotionQuery?: MediaQueryList;
  private _onMotionPref = (): void => {
    this.requestUpdate();
  };

  public static getStubConfig(): EccoFlow3dCardConfig {
    return {
      type: "custom:ecco-flow-3d-card",
      title: "Energy Flow",
      subtitle: "Live power overview",
      nodes: {
        solar: [{ label: "Array 1", power: "sensor.pv1_power" }],
        inverter: { power: "sensor.inverter_power" },
        home: { power: "sensor.house_power" },
        battery: { power: "sensor.battery_power", soc: "sensor.battery_soc", power_sign: "charge_positive" },
        grid: { power: "sensor.grid_power", power_sign: "import_positive" },
      },
    };
  }

  public setConfig(config: EccoFlow3dCardConfig): void {
    validateConfig(config);
    this._config = config;
    this._failedPlates = new Set();
  }

  /**
   * Which scene plate to show now: the pinned scene, else the pack's rules
   * over the date, the sun and the weather condition. Ambience only.
   */
  private _resolveScene(states: States, now: Date): { key: SceneKey; url: string } | null {
    const sc = this._config?.scene;
    if (!sc?.pack) return null;
    const ecco = this._config?.ecco ?? {};
    const sun = ecco.sun ? states[ecco.sun] : undefined;
    const elevation = typeof sun?.attributes?.elevation === "number" ? (sun.attributes.elevation as number) : null;
    const rising = typeof sun?.attributes?.rising === "boolean" ? (sun.attributes.rising as boolean) : null;
    const forced = sc.force && (SCENE_KEYS as string[]).includes(sc.force) ? (sc.force as SceneKey) : null;
    const key =
      forced ??
      selectScene({
        month: now.getMonth() + 1,
        day: now.getDate(),
        sunUp: sun ? (sun.state === "above_horizon" ? true : sun.state === "below_horizon" ? false : null) : null,
        elevation,
        rising,
        weather: ecco.weather ? stateOf(states, ecco.weather) : undefined,
        hour: now.getHours(),
      });
    return { key, url: sceneUrl(sc.pack, key, sc.scenes as Partial<Record<SceneKey, string>> | undefined) };
  }

  protected willUpdate(): void {
    const target = this._resolveScene(this.hass?.states ?? {}, new Date(this._nowMs));
    if (!target) {
      if (this._layers.length) this._layers = [];
      return;
    }
    const top = this._layers[this._layers.length - 1];
    if (top && top.url === target.url) return;
    // First plate: no fade. Later plates: enter on top and fade in; the old one stays beneath until the fade ends.
    this._layers = this._layers.length === 0 ? [{ url: target.url, key: target.key, entering: false }] : [...this._layers.slice(-1), { url: target.url, key: target.key, entering: true }];
  }

  private _plateLoaded(url: string): void {
    const top = this._layers[this._layers.length - 1];
    if (!top || top.url !== url || this._layers.length < 2) return;
    window.clearTimeout(this._fadeTimer);
    this._fadeTimer = window.setTimeout(
      () => {
        this._layers = this._layers.filter((l) => l.url === url).map((l) => ({ ...l, entering: false }));
      },
      (this._config?.scene?.crossfade_ms ?? 900) + 50
    );
  }

  private _plateFailed(url: string): void {
    this._failedPlates.add(url);
    this.requestUpdate();
  }

  public getCardSize(): number {
    return 8;
  }

  public connectedCallback(): void {
    super.connectedCallback();
    if (window.matchMedia) {
      this._reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
      this._reducedMotionQuery.addEventListener?.("change", this._onMotionPref);
    }
    this._timer = window.setInterval(() => {
      this._nowMs = Date.now();
    }, REFRESH_MS);
    if (typeof ResizeObserver !== "undefined") {
      this._resize = new ResizeObserver((entries) => {
        const w = Math.round(entries[0]?.contentRect.width ?? 0);
        if (w && Math.abs(w - this._widthPx) > 8) this._widthPx = w;
      });
      this._resize.observe(this);
    }
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    this._reducedMotionQuery?.removeEventListener?.("change", this._onMotionPref);
    window.clearInterval(this._timer);
    window.clearTimeout(this._fadeTimer);
    this._resize?.disconnect();
    cancelAnimationFrame(this._raf);
    this._raf = 0;
  }

  protected firstUpdated(): void {
    this._animate();
  }

  protected updated(_changed: PropertyValues): void {
    this._placeChevrons();
  }

  // -------------------------------------------------------------------------
  // Model

  private get _reducedMotion(): boolean {
    return !!this._reducedMotionQuery?.matches;
  }

  private _moreInfo(entityId: string | undefined): void {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  protected render(): TemplateResult {
    const config = this._config;
    if (!config) return html``;
    const states: States = this.hass?.states ?? {};
    const nodes = config.nodes ?? {};
    const ecco = config.ecco ?? {};
    const now = new Date(this._nowMs);

    // --- powers (established model) ---
    const arrays = normaliseSolarSources(nodes.solar);
    const arrayW = arrays.map((a) => numberOf(states, a.power));
    const solarW = aggregateSolarW(numberOf(states, nodes.solar_total), arrayW);
    const inverterW = numberOf(states, nodes.inverter?.power);
    const batteryRaw = numberOf(states, nodes.battery?.power);
    const batteryW = batteryRaw === null ? null : normaliseBatteryPower(batteryRaw, nodes.battery?.power_sign);
    const gridRaw = numberOf(states, nodes.grid?.power);
    const gridW = gridRaw === null ? null : normaliseGridPower(gridRaw, nodes.grid?.power_sign);
    const homeW = resolveHomeW(numberOf(states, nodes.home?.power), inverterW, gridW);
    const soc = numberOf(states, nodes.battery?.soc);
    const edges = buildFlowEdges({ solarW, batteryW, gridW, homeW });
    const byId = Object.fromEntries(edges.map((e) => [e.id, e])) as Record<FlowId, FlowEdge>;
    // Artwork plates split the solar system: card -> main array carries the total; main array -> inverter carries
    // array 1 and garage array -> inverter carries array 2 when both are individually known (the Solar pill always
    // shows the authoritative total, so nothing is counted twice). With one array, or no per-array readings, the
    // main route carries the total and the garage route is not drawn.
    const split = splitSolarFlows(solarW, arrayW[0] ?? null, arrayW[1] ?? null, arrays.length);

    // --- freshness ---
    const telemetry = classifyOnOff(stateOf(states, ecco.telemetry_online));
    const fresh = resolveFreshness(
      [...arrays.map((a) => a.power), nodes.solar_total, nodes.inverter?.power, nodes.battery?.power, nodes.grid?.power, nodes.home?.power],
      states,
      telemetry,
      this._nowMs,
      config.features?.stale_after_s ?? DEFAULT_STALE_AFTER_S
    );
    const stale = fresh.stale;
    const animate = (config.features?.animate_flow ?? true) && !this._reducedMotion;

    // --- FE-1 runtime (shown in the battery pill and the Runtime tile) ---
    const ttrId = nodes.battery?.time_to_reserve;
    const rt = resolveReserveRuntime(ttrId, resolveTimeToReserveMinutes(ttrId, numberOf(states, ttrId), attrsOf(states, ttrId)?.unit_of_measurement), attrsOf(states, ttrId));
    const runtimeWord = rt && (rt.status === "discharging" || rt.status === "at_reserve") ? reserveRuntimeLine(rt) : "";

    // --- scene pills ---
    const bState = batteryState(batteryW);
    const gState = gridState(gridW);
    const gridConnected = classifyOnOff(stateOf(states, nodes.grid?.connected));
    const pills: Record<FlowId, PillData> = {
      solar: {
        label: "Solar Generation",
        value: formatPowerCompact(solarW),
        // Per-array figures, shown beside the authoritative total (never added to it).
        sub: arrays.length > 1 ? arrays.map((_, i) => formatPowerCompact(arrayW[i] ?? null)).join(" + ") : "",
        tone: solarW === null ? "muted" : "ok",
        icon: "sun",
        clickable: !!(nodes.solar_total ?? arrays[0]?.power),
      },
      grid: {
        label: "Grid",
        value: formatPowerCompact(gridW === null ? null : Math.abs(gridW)),
        sub: gridConnected === "off" ? "Disconnected" : gState === "importing" ? "Importing" : gState === "exporting" ? "Exporting" : gState === "idle" ? "Idle" : "Unknown",
        tone: gridConnected === "off" ? "alert" : gState === "unknown" ? "muted" : "ok",
        icon: "pylon",
        clickable: !!nodes.grid?.power,
      },
      home: {
        label: "Home Load",
        value: formatPowerCompact(homeW),
        sub: "",
        tone: homeW === null ? "muted" : "ok",
        icon: "home",
        clickable: !!nodes.home?.power,
      },
      battery: {
        label: "Battery Storage",
        value: formatPowerCompact(batteryW === null ? null : Math.abs(batteryW)),
        sub: bState === "charging" ? "Charging" : bState === "discharging" ? "Discharging" : bState === "idle" ? "Idle" : "Unknown",
        extra: runtimeWord,
        tone: bState === "unknown" ? "muted" : "ok",
        icon: "battery",
        clickable: !!(nodes.battery?.power ?? nodes.battery?.soc),
        soc,
      },
    };

    const daylight = resolveDaylight(ecco.sun ? states[ecco.sun] : undefined, now);
    const activePlate = this._layers[this._layers.length - 1];
    const artworkOn = !!activePlate && !this._failedPlates.has(activePlate.url);
    const scene: SceneModel = {
      daylight,
      artwork: artworkOn
        ? {
            layers: this._layers,
            layout: v4Layout(v4ScaleForWidth(this._widthPx || this.getBoundingClientRect().width || 1200), config.scene?.routing),
            onError: (url) => this._plateFailed(url),
            onLoad: (url) => this._plateLoaded(url),
            debug: !!config.scene?.debug_anchors,
          }
        : undefined,
      solarSplit: artworkOn
        ? {
            card: { edge: split.card, motion: motionFor(split.card, stale) },
            main: { edge: split.main, motion: motionFor(split.main, stale) },
            garage: split.garage ? { edge: split.garage, motion: motionFor(split.garage, stale) } : null,
          }
        : undefined,
      flows: {
        solar: { edge: byId.solar, motion: motionFor(byId.solar, stale) },
        battery: { edge: byId.battery, motion: motionFor(byId.battery, stale) },
        grid: { edge: byId.grid, motion: motionFor(byId.grid, stale) },
        home: { edge: byId.home, motion: motionFor(byId.home, stale) },
      },
      stale,
      animate,
      pills,
      inverterLed: stale ? "warn" : edges.some((e) => !e.unknown) ? "ok" : "off",
      onPill: (id) => {
        const target =
          id === "solar" ? (nodes.solar_total ?? arrays[0]?.power) : id === "grid" ? nodes.grid?.power : id === "home" ? nodes.home?.power : (nodes.battery?.power ?? nodes.battery?.soc);
        this._moreInfo(target);
      },
    };

    const idle = siteIsIdle(edges) && !stale;
    const chip = this._chip(telemetry, fresh.ageS, stale, fresh.reason);

    return html`
      <ha-card style=${`--ef-crossfade:${config.scene?.crossfade_ms ?? 900}ms`}>
        <div class="card">
          <header class="head">
            <div class="titles">
              ${(config.brand ?? "ECCO") !== "" ? html`<div class="wordmark"><span class="wm-accent">${(config.brand ?? "ECCO").slice(0, 1)}</span>${(config.brand ?? "ECCO").slice(1)}</div>` : nothing}
              <div class="brand">${config.title ?? "Energy Flow"}</div>
              ${config.subtitle ? html`<div class="subtitle">${config.subtitle}</div>` : nothing}
            </div>
            <button class=${`chip tone-${chip.tone}`} type="button" @click=${() => this._moreInfo(ecco.telemetry_online)} title=${chip.title}>
              <span class="dot"></span>${chip.text}
            </button>
          </header>
          ${stale ? html`<div class="strip stale-strip">${fresh.reason === "telemetry_offline" ? "Telemetry offline: the values shown are the last received, not live." : `Values are stale: the newest power reading is ${formatAge(fresh.ageS)}.`}</div>` : nothing}
          <div class="body">
            <div class="scene-wrap">
              ${renderScene(scene)}
              ${idle ? html`<div class="banner idle-banner">Site idle: no power is flowing above ${5} W.</div>` : nothing}
            </div>
            <div class="side">
              ${config.features?.show_status_panel === false ? nothing : this._renderStatus(states, now, stale, fresh.ageS)}
              ${config.features?.show_details_panel === false ? nothing : this._renderDetails(states, arrays, arrayW, solarW, inverterW, batteryW, gridW, homeW)}
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  private _chip(telemetry: ReturnType<typeof classifyOnOff>, ageS: number | null, stale: boolean, reason: string | null): { text: string; tone: Tone; title: string } {
    if (telemetry === "off") return { text: "Telemetry offline", tone: "alert", title: "The dongle's telemetry polling is offline" };
    if (stale && reason === "age") return { text: `Stale · ${formatAge(ageS)}`, tone: "warn", title: "No power reading has updated recently" };
    if (telemetry === "on") return { text: "System online", tone: "ok", title: ageS === null ? "Telemetry online" : `Telemetry online · updated ${formatAge(ageS)}` };
    return { text: ageS === null ? "Status unknown" : `Updated ${formatAge(ageS)}`, tone: "muted", title: "No telemetry-online entity configured" };
  }

  // -------------------------------------------------------------------------
  // Status grid

  private _renderStatus(states: States, now: Date, stale: boolean, ageS: number | null): TemplateResult {
    const config = this._config!;
    const ecco = config.ecco ?? {};
    const nodes = config.nodes ?? {};
    const tiles: Tile[] = [];

    // TOU
    const tou = ecco.tou;
    const touView = resolveTouSlot(
      (tou?.slot_start_minutes ?? []).map((id) => numberOf(states, id)),
      minutesOfDay(now),
      tou?.valid ? classifyOnOff(stateOf(states, tou.valid)) : "unknown"
    );
    const slotIdx = touView.slot === null ? null : touView.slot - 1;
    const targetSocId = slotIdx === null ? undefined : tou?.slot_target_soc?.[slotIdx];
    const chargeSrcId = slotIdx === null ? undefined : tou?.slot_charge_source?.[slotIdx];
    const slotPowerId = slotIdx === null ? undefined : tou?.slot_power?.[slotIdx];
    const targetSoc = numberOf(states, targetSocId);
    const chargeSrc = stateOf(states, chargeSrcId);
    const slotPower = numberOf(states, slotPowerId);
    tiles.push({
      key: "tou",
      icon: "clock",
      label: "TOU Slot",
      value: touView.value,
      sub: touView.sub,
      tone: touView.tone,
      entity: slotIdx === null ? tou?.slot_start_minutes?.[0] : tou?.slot_start_minutes?.[slotIdx],
      title: "The slot containing the current local time, from the six slot start sensors",
    });
    tiles.push({
      key: "charge",
      icon: "plug",
      label: "Charge Source",
      value: chargeSrcId ? (chargeSrc && chargeSrc !== "unknown" && chargeSrc !== "unavailable" ? chargeSrc : "--") : "--",
      sub: slotIdx === null ? "Needs the current slot" : slotPower !== null ? `Slot limit ${formatPower(slotPower, config.format)}` : "Current slot setting",
      tone: chargeSrc && chargeSrc.toLowerCase() === "grid" ? "accent" : "muted",
      entity: chargeSrcId,
    });
    tiles.push({
      key: "target",
      icon: "target",
      label: "Target SOC",
      value: formatPercent(targetSoc),
      sub: slotIdx === null ? "Needs the current slot" : `Slot ${touView.slot} setting`,
      tone: targetSoc === null ? "muted" : "accent",
      entity: targetSocId,
    });

    // Battery runtime (FE-1)
    const ttrId = nodes.battery?.time_to_reserve;
    const ttrMinutes = resolveTimeToReserveMinutes(ttrId, numberOf(states, ttrId), attrsOf(states, ttrId)?.unit_of_measurement);
    const rt = resolveReserveRuntime(ttrId, ttrMinutes, attrsOf(states, ttrId));
    const rtTile = reserveRuntimeTile(rt);
    tiles.push({ key: "runtime", icon: "battery", label: "Runtime", value: rtTile.value, sub: rtTile.sub, tone: rtTile.tone, entity: ttrId, title: rt ? reserveRuntimeTooltip(rt) : "No time-to-reserve entity configured" });

    // Sessions
    const fp = ecco.free_power;
    const fpView = resolveSession(
      {
        active: classifyOnOff(stateOf(states, fp?.active)),
        endsAtText: stateOf(states, fp?.ends_at),
        scheduleStatus: stateOf(states, fp?.schedule_status),
        statusText: stateOf(states, fp?.status),
        scheduleAttrs: attrsOf(states, fp?.schedule_status),
        anyConfigured: !!(fp?.active || fp?.status || fp?.schedule_status),
      },
      this._nowMs,
      "free_power"
    );
    tiles.push({ key: "fp", icon: "leaf", label: "Free Power", value: fpView.value, sub: fpView.sub, tone: fpView.tone, entity: fp?.status ?? fp?.active ?? fp?.schedule_status, title: stateOf(states, fp?.status) });
    const dump = ecco.dump_to_grid;
    const dumpView = resolveSession(
      {
        active: classifyOnOff(stateOf(states, dump?.active)),
        endsAtText: stateOf(states, dump?.ends_at),
        scheduleStatus: stateOf(states, dump?.schedule_status),
        statusText: stateOf(states, dump?.status),
        scheduleAttrs: attrsOf(states, dump?.schedule_status),
        exportPowerW: numberOf(states, dump?.export_power),
        stopSoc: numberOf(states, dump?.stop_soc),
        anyConfigured: !!(dump?.active || dump?.status || dump?.schedule_status),
      },
      this._nowMs,
      "dump"
    );
    tiles.push({ key: "dump", icon: "swap", label: "Dump to Grid", value: dumpView.value, sub: dumpView.sub, tone: dumpView.tone, entity: dump?.status ?? dump?.active ?? dump?.schedule_status, title: stateOf(states, dump?.status) });

    // Health
    const health = resolveHealth(ecco.health?.sensors ?? [], ecco.health?.attention ?? [], states);
    tiles.push({
      key: "health",
      icon: health.grade === "FAILED" ? "alert" : "heart",
      label: "Health",
      value: health.value,
      sub: health.sub,
      tone: health.tone,
      entity: ecco.health?.sensors?.[0],
      wide: true,
      title: [...health.failed.map((n) => `FAILED: ${n}`), ...health.degraded.map((n) => `DEGRADED: ${n}`), ...health.attention.map((n) => `attention: ${n}`), ...health.unknown.map((n) => `unknown: ${n}`)].join("\n") || "All configured subsystems healthy",
    });

    // Forecast
    const fcToday = numberOf(states, ecco.forecast?.today);
    const fcRemaining = numberOf(states, ecco.forecast?.remaining);
    const pvToday = numberOf(states, config.today?.solar);
    tiles.push({
      key: "forecast",
      icon: "forecast",
      label: "Forecast Today",
      value: formatEnergy(fcToday, config.format),
      sub:
        fcRemaining !== null
          ? `${formatEnergy(fcRemaining, config.format)} still expected` + (pvToday !== null ? ` · ${formatEnergy(pvToday, config.format)} so far` : "")
          : pvToday !== null
            ? `${formatEnergy(pvToday, config.format)} generated so far`
            : ecco.forecast?.today
              ? "Remaining forecast unavailable"
              : "No forecast entity configured",
      tone: fcToday === null ? "muted" : "ok",
      entity: ecco.forecast?.remaining ?? ecco.forecast?.today,
      wide: true,
    });

    return html`
      <section class="status" aria-label="ECCO system status">
        <div class="status-head">
          <span class="status-title">ECCO System Status</span>
          <span class=${`status-age ${stale ? "stale" : ""}`}><span class="dot"></span>${ageS === null ? "No timestamp" : `Updated ${formatAge(ageS)}`}</span>
        </div>
        <div class="tiles">
          ${tiles.map(
            (t) => html`
              <button
                type="button"
                class=${`tile tone-${t.tone} ${t.wide ? "wide" : ""} ${t.entity ? "clickable" : ""}`}
                title=${t.title ?? ""}
                ?disabled=${!t.entity}
                @click=${() => this._moreInfo(t.entity)}
              >
                <span class="tile-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d=${ICONS[t.icon]}></path></svg></span>
                <span class="tile-text">
                  <span class="tile-label">${t.label}</span>
                  <span class="tile-value">${t.value}</span>
                  ${t.sub ? html`<span class="tile-sub">${t.sub}</span>` : nothing}
                </span>
                ${t.entity ? html`<svg class="tile-chev" viewBox="0 0 24 24" aria-hidden="true"><path d=${ICONS.chevron}></path></svg>` : nothing}
              </button>
            `
          )}
        </div>
      </section>
    `;
  }

  // -------------------------------------------------------------------------
  // Details

  private _renderDetails(
    states: States,
    arrays: ReturnType<typeof normaliseSolarSources>,
    arrayW: Array<number | null>,
    solarW: number | null,
    inverterW: number | null,
    batteryW: number | null,
    gridW: number | null,
    homeW: number | null
  ): TemplateResult {
    const config = this._config!;
    const nodes = config.nodes ?? {};
    const ecco = config.ecco ?? {};
    const det = config.inverter_details ?? {};
    const f = config.format;
    const row = (label: string, value: string, entity?: string, note?: string) => html`
      <div class=${`row ${entity ? "clickable" : ""}`} @click=${() => this._moreInfo(entity)} role=${entity ? "button" : "listitem"} tabindex=${entity ? 0 : -1}>
        <span class="row-label">${label}</span>
        <span class="row-value">${value}${note ? html`<span class="row-note">${note}</span>` : nothing}</span>
      </div>`;
    const temp = (id?: string) => {
      const v = numberOf(states, id);
      return v === null ? "--" : `${v.toFixed(1)} °C`;
    };
    const ttt = resolveTimeToTarget(nodes.battery?.time_to_target, states);
    const gridConn = classifyOnOff(stateOf(states, nodes.grid?.connected));
    const ttrId = nodes.battery?.time_to_reserve;
    const rt = resolveReserveRuntime(ttrId, resolveTimeToReserveMinutes(ttrId, numberOf(states, ttrId), attrsOf(states, ttrId)?.unit_of_measurement), attrsOf(states, ttrId));
    const health = resolveHealth(ecco.health?.sensors ?? [], ecco.health?.attention ?? [], states);
    const today = config.today ?? {};
    const hasToday = Object.values(today).some(Boolean);
    const fcTomorrow = numberOf(states, ecco.forecast?.tomorrow);
    return html`
      <details class="details" ?open=${this._detailsOpen} @toggle=${(e: Event) => (this._detailsOpen = (e.target as HTMLDetailsElement).open)}>
        <summary>
          <span>Inverter, grid and diagnostics</span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${ICONS.chevron}></path></svg>
        </summary>
        <div class="details-grid">
          <div class="group">
            <div class="group-title">Inverter</div>
            ${row("State", stateOf(states, nodes.inverter?.state) ?? "--", nodes.inverter?.state)}
            ${row("AC output", formatPower(inverterW, f), nodes.inverter?.power)}
            ${row("Home load", formatPower(homeW, f), nodes.home?.power, numberOf(states, nodes.home?.power) === 0 && homeW !== 0 ? "derived" : undefined)}
            ${row("AC transformer", temp(det.ac_temperature), det.ac_temperature)}
            ${row("DC transformer", temp(det.dc_temperature), det.dc_temperature)}
            ${det.temperature ? row("Temperature", temp(det.temperature), det.temperature) : nothing}
          </div>
          <div class="group">
            <div class="group-title">Grid</div>
            ${row("Connected", gridConn === "on" ? "Yes" : gridConn === "off" ? "No" : "Unknown", nodes.grid?.connected)}
            ${row("Power", gridW === null ? "--" : `${formatPower(Math.abs(gridW), f)} ${gridW >= 5 ? "import" : gridW <= -5 ? "export" : ""}`, nodes.grid?.power)}
            ${row("Voltage", numberOf(states, nodes.grid?.voltage) === null ? "--" : `${numberOf(states, nodes.grid?.voltage)!.toFixed(1)} V`, nodes.grid?.voltage)}
            ${row("Frequency", numberOf(states, nodes.grid?.frequency) === null ? "--" : `${numberOf(states, nodes.grid?.frequency)!.toFixed(2)} Hz`, nodes.grid?.frequency)}
          </div>
          <div class="group">
            <div class="group-title">Solar</div>
            ${arrays.map((a, i) => row(a.label ?? `Array ${i + 1}`, formatPower(arrayW[i] ?? null, f), a.power))}
            ${row("Total", formatPower(solarW, f), nodes.solar_total, nodes.solar_total ? undefined : arrays.length > 1 ? "sum of arrays" : undefined)}
            ${ecco.forecast?.tomorrow ? row("Forecast tomorrow", formatEnergy(fcTomorrow, f), ecco.forecast.tomorrow) : nothing}
          </div>
          <div class="group">
            <div class="group-title">Battery</div>
            ${row("Power", batteryW === null ? "--" : `${formatPower(Math.abs(batteryW), f)} ${batteryW >= 5 ? "discharge" : batteryW <= -5 ? "charge" : ""}`, nodes.battery?.power)}
            ${row("State of charge", formatPercent(numberOf(states, nodes.battery?.soc)), nodes.battery?.soc)}
            ${row("Time to reserve", rt ? reserveRuntimeTooltip(rt).replace(/^Time to reserve: /, "") : "No entity configured", ttrId)}
            ${row("Time to charge target", ttt.value, nodes.battery?.time_to_target, ttt.sub)}
            ${det.battery_temperature ? row("Temperature", temp(det.battery_temperature), det.battery_temperature) : nothing}
          </div>
          ${
            (ecco.health?.sensors?.length ?? 0) > 0
              ? html`<div class="group">
                  <div class="group-title">Health</div>
                  ${(ecco.health?.sensors ?? []).map((id) => {
                    const s = (stateOf(states, id) ?? "--").toUpperCase();
                    return row(
                      id
                        .replace(/^.*?\./, "")
                        .replace(/^ecco_health_/, "")
                        .replace(/_/g, " "),
                      s === "HEALTHY" ? "Healthy" : s === "DEGRADED" ? "Degraded" : s === "FAILED" ? "Failed" : "Unknown",
                      id,
                      typeof attrsOf(states, id)?.summary === "string" && s !== "HEALTHY" ? String(attrsOf(states, id)?.summary).trim().slice(0, 80) : undefined
                    );
                  })}
                  ${(ecco.health?.attention ?? []).map((id) => row(id.replace(/^.*?\./, "").replace(/_/g, " "), classifyOnOff(stateOf(states, id)) === "on" ? "Needs attention" : classifyOnOff(stateOf(states, id)) === "off" ? "Clear" : "Unknown", id))}
                  ${health.attention.length + health.failed.length > 0 ? html`<div class="row-note block">Warnings are listed in full above; the Health tile summarises them.</div>` : nothing}
                </div>`
              : nothing
          }
          ${
            hasToday
              ? html`<div class="group today">
                  <div class="group-title">Today</div>
                  ${row("Solar", formatEnergy(numberOf(states, today.solar), f), today.solar)}
                  ${row("Load", formatEnergy(numberOf(states, today.load), f), today.load)}
                  ${row("Import", formatEnergy(numberOf(states, today.import), f), today.import)}
                  ${row("Export", formatEnergy(numberOf(states, today.export), f), today.export)}
                  ${row("Battery charge", formatEnergy(numberOf(states, today.battery_charge), f), today.battery_charge)}
                  ${row("Battery discharge", formatEnergy(numberOf(states, today.battery_discharge), f), today.battery_discharge)}
                </div>`
              : nothing
          }
        </div>
      </details>
    `;
  }

  // -------------------------------------------------------------------------
  // Pulse animation: positions every .pulse along its path with getPointAtLength.

  private _pathFor(root: ShadowRoot, id: string): { path: SVGPathElement; length: number } | null {
    const path = root.querySelector<SVGPathElement>(`#${CSS.escape(id)}`);
    if (!path) return null;
    const d = path.getAttribute("d") ?? "";
    let cached = this._lengthCache.get(path);
    if (!cached || cached.d !== d) {
      cached = { d, length: path.getTotalLength() };
      this._lengthCache.set(path, cached);
    }
    return cached.length ? { path, length: cached.length } : null;
  }

  private _animate(): void {
    this._raf = requestAnimationFrame(() => this._animate());
    const root = this.shadowRoot;
    if (!root || this._reducedMotion) return;
    const pulses = root.querySelectorAll<SVGGElement>(".pulse");
    if (!pulses.length) return;
    const nowS = performance.now() / 1000;
    pulses.forEach((pulse) => {
      const pathId = pulse.dataset.path;
      const duration = parseFloat(pulse.dataset.duration ?? "");
      const phase = parseFloat(pulse.dataset.phase ?? "0");
      if (!pathId || !duration) return;
      const target = this._pathFor(root, pathId);
      if (!target) return;
      let p = (nowS / duration + phase) % 1;
      if (pulse.dataset.reversed === "1") p = 1 - p;
      const pt = target.path.getPointAtLength(p * target.length);
      pulse.setAttribute("transform", `translate(${pt.x.toFixed(2)},${pt.y.toFixed(2)})`);
    });
  }

  /** Static direction chevrons for the no-motion rendering: placed once per render. */
  private _placeChevrons(): void {
    const root = this.shadowRoot;
    if (!root) return;
    root.querySelectorAll<SVGGElement>(".chevron").forEach((chev) => {
      const pathId = chev.dataset.path;
      const phase = parseFloat(chev.dataset.phase ?? "0.5");
      if (!pathId) return;
      const target = this._pathFor(root, pathId);
      if (!target) return;
      const reversed = chev.dataset.reversed === "1";
      const at = (reversed ? 1 - phase : phase) * target.length;
      const a = target.path.getPointAtLength(Math.max(0, at - 2));
      const b = target.path.getPointAtLength(Math.min(target.length, at + 2));
      const angle = (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI + (reversed ? 180 : 0);
      const p = target.path.getPointAtLength(at);
      chev.setAttribute("transform", `translate(${p.x.toFixed(2)},${p.y.toFixed(2)}) rotate(${angle.toFixed(1)})`);
    });
  }

  // -------------------------------------------------------------------------
  // Styles

  static styles = css`
    :host {
      display: block;
      --ef-bg-a: #0a1220;
      --ef-bg-b: #0d1626;
      --ef-surface: rgba(255, 255, 255, 0.045);
      --ef-surface-2: rgba(255, 255, 255, 0.07);
      --ef-border: rgba(255, 255, 255, 0.09);
      --ef-text: #e9eefb;
      --ef-muted: #8e9bb7;
      --ef-ok: #35e08a;
      --ef-warn: #f5b942;
      --ef-alert: #ff6b6b;
      --ef-accent: #5aa9ff;
      --ef-solar: #f7c948;
      --ef-grid: #3ea6ff;
      --ef-battery: #35e08a;
      --ef-home: #a9dcff;
      color: var(--ef-text);
      font-family: var(--paper-font-body1_-_font-family, "Inter", "Segoe UI", Roboto, system-ui, sans-serif);
    }
    ha-card {
      background: radial-gradient(120% 90% at 20% 0%, #14213a 0%, var(--ef-bg-a) 48%, var(--ef-bg-b) 100%);
      border-radius: 24px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.06);
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
    }
    .card {
      container-type: inline-size;
      padding: 14px 14px 10px;
    }
    .head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 4px 4px 8px;
    }
    .wordmark {
      font-size: 15px;
      font-weight: 900;
      letter-spacing: 0.34em;
      color: #dfe7f7;
      margin-bottom: 2px;
    }
    .wm-accent {
      color: var(--ef-ok);
    }
    .brand {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.02em;
      line-height: 1.1;
    }
    .subtitle {
      color: var(--ef-muted);
      font-size: 13px;
      margin-top: 3px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
      color: var(--ef-text);
      border-radius: 999px;
      padding: 8px 14px;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--ef-muted);
      box-shadow: 0 0 10px currentColor;
      flex: none;
    }
    .tone-ok .dot,
    .status-age .dot {
      background: var(--ef-ok);
      color: var(--ef-ok);
    }
    .tone-warn .dot,
    .status-age.stale .dot {
      background: var(--ef-warn);
      color: var(--ef-warn);
    }
    .tone-alert .dot {
      background: var(--ef-alert);
      color: var(--ef-alert);
    }
    .body {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
    }
    @container (min-width: 760px) {
      .body {
        grid-template-columns: minmax(0, 1.75fr) minmax(300px, 1fr);
        align-items: start;
      }
    }
    /* Artwork plates: the whole 1448 x 1086 canvas at every width (no crop, so the hardware anchors never move). */
    .scene.artwork {
      aspect-ratio: 1448 / 1086;
      max-height: none;
      height: auto;
      background: #0a1322;
    }
    .scene.artwork .plate {
      image-rendering: auto;
    }
    .scene.artwork .plate.entering {
      animation: ef3d-plate-in var(--ef-crossfade, 900ms) ease-in-out both;
    }
    @keyframes ef3d-plate-in {
      from {
        opacity: 0;
      }
      to {
        opacity: 1;
      }
    }
    .scene.artwork .pill-label {
      font-size: calc(11px * var(--k, 1));
    }
    .scene.artwork .pill-value {
      font-size: calc(19px * var(--k, 1));
    }
    .scene.artwork .pill-sub {
      font-size: calc(10px * var(--k, 1));
    }
    .scene.artwork .ring-value {
      font-size: calc(12px * var(--k, 1));
    }
    .scene.artwork .ring-caption {
      font-size: calc(6.5px * var(--k, 1));
    }
    .scene.artwork .pill-border {
      stroke-width: calc(1.4px * var(--k, 1));
    }
    .scene.artwork .ring-track,
    .scene.artwork .ring-fill {
      stroke-width: calc(5px * var(--k, 1));
    }
    .scene.artwork .pill-bg {
      fill: rgba(7, 12, 24, 0.78);
    }
    .scene.artwork .chevron path {
      stroke-width: 2;
    }
    .scene-wrap {
      position: relative;
      border-radius: 20px;
      overflow: hidden;
      background: #0a1322;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .scene {
      display: block;
      width: 100%;
      height: auto;
      max-height: 640px;
      user-select: none;
    }
    .banner {
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 12px;
      padding: 8px 12px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      background: rgba(10, 15, 28, 0.82);
      border: 1px solid var(--ef-border);
      backdrop-filter: blur(6px);
    }
    .strip {
      margin: 0 0 10px;
      padding: 9px 14px;
      border-radius: 12px;
      font-size: 12.5px;
      font-weight: 600;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
    }
    .stale-strip {
      color: var(--ef-warn);
      border-color: rgba(245, 185, 66, 0.45);
      background: rgba(245, 185, 66, 0.08);
    }
    .side {
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      container-type: inline-size;
    }
    .idle-banner {
      color: var(--ef-muted);
      bottom: auto;
      top: 92px;
      left: auto;
      right: 12px;
      max-width: 46%;
      font-weight: 500;
    }

    /* ---- scene palette (night default) ---- */
    .scene {
      --sky-a: #182845;
      --sky-b: #0a1322;
      --ground-top: #10322d;
      --ground-side: #07160f;
      --lawn: rgba(255, 255, 255, 0.03);
      --drive: #2a3346;
      --wall-l: #3b4356;
      --wall-r: #272e3d;
      --roof: #1a2130;
      --roof-back: #121826;
      --window: #ffd37a;
      --window-glow: 0.75;
      --pv: #163a74;
      --pv-line: rgba(140, 190, 255, 0.35);
      --canopy-1: #1f5a3c;
      --canopy-2: #184830;
      --canopy-3: #12392a;
      --lamp: 1;
      --star: 0.8;
      --moon: 1;
      --sun: 0;
      --cab: #d9dde6;
      --cab-r: #aab1c0;
      --cab-t: #eef1f6;
      --wire: rgba(170, 190, 220, 0.4);
    }
    .scene.dusk {
      --sky-a: #3a3558;
      --sky-b: #121a2e;
      --ground-top: #1c4635;
      --wall-l: #5a5f73;
      --wall-r: #3b4052;
      --window-glow: 0.5;
      --pv: #1b4a8f;
      --star: 0.25;
      --moon: 0.5;
      --sun: 0.55;
      --canopy-1: #2b6a46;
      --canopy-2: #205538;
      --canopy-3: #18432d;
    }
    .scene.day {
      --sky-a: #35598f;
      --sky-b: #16243f;
      --ground-top: #2f6b45;
      --ground-side: #16331f;
      --lawn: rgba(255, 255, 255, 0.05);
      --drive: #4a5569;
      --wall-l: #cdc7bb;
      --wall-r: #9b958b;
      --roof: #2d3443;
      --roof-back: #232a38;
      --window: #2f4b73;
      --window-glow: 0;
      --pv: #2460bb;
      --pv-line: rgba(200, 225, 255, 0.45);
      --canopy-1: #3f8c57;
      --canopy-2: #2f7246;
      --canopy-3: #245a37;
      --lamp: 0;
      --star: 0;
      --moon: 0;
      --sun: 1;
      --wire: rgba(210, 225, 245, 0.45);
    }
    .sky-a {
      stop-color: var(--sky-a);
    }
    .sky-b {
      stop-color: var(--sky-b);
    }
    .star {
      fill: #ffffff;
      opacity: var(--star);
    }
    .moon {
      fill: #e9f0ff;
      opacity: var(--moon);
    }
    .moon-halo {
      fill: #cfe0ff;
      opacity: calc(var(--moon) * 0.12);
      filter: url(#ef3d-blur-soft);
    }
    .sun-disc {
      fill: #ffe9a8;
      opacity: var(--sun);
    }
    .sun-halo {
      fill: #ffd56a;
      opacity: calc(var(--sun) * 0.22);
      filter: url(#ef3d-blur-soft);
    }
    .ground-top {
      fill: var(--ground-top);
    }
    .ground-side {
      fill: var(--ground-side);
    }
    .ground-side-r {
      filter: brightness(0.8);
    }
    .lawn-stripe {
      fill: var(--lawn);
    }
    .drive {
      fill: var(--drive);
      opacity: 0.9;
    }
    .drive.path {
      opacity: 0.55;
    }
    .tree-shadow {
      fill: rgba(0, 0, 0, 0.35);
    }
    .trunk {
      fill: #3b2a1e;
    }
    .canopy.c1 {
      fill: var(--canopy-1);
    }
    .canopy.c2 {
      fill: var(--canopy-2);
    }
    .canopy.c3 {
      fill: var(--canopy-3);
    }
    .lamp-post {
      stroke: #6a7388;
      stroke-width: 1.2;
    }
    .lamp-light {
      fill: #ffe6a0;
      opacity: calc(0.25 + var(--lamp) * 0.75);
    }
    .lamp-halo {
      fill: #ffd36a;
      opacity: calc(var(--lamp) * 0.28);
      filter: url(#ef3d-blur);
    }
    .contact-shadow {
      fill: rgba(0, 0, 0, 0.42);
      filter: url(#ef3d-blur);
    }
    .contact-shadow.soft {
      fill: rgba(0, 0, 0, 0.5);
    }
    .wall-l {
      fill: var(--wall-l);
    }
    .wall-r {
      fill: var(--wall-r);
    }
    .gable {
      filter: brightness(1.06);
    }
    .window {
      fill: var(--window);
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
      filter: drop-shadow(0 0 calc(var(--window-glow) * 6px) rgba(255, 200, 100, var(--window-glow)));
    }
    .window.small {
      opacity: 0.85;
    }
    .door {
      fill: #5a3d2b;
      stroke: rgba(0, 0, 0, 0.4);
      stroke-width: 0.6;
    }
    .garage-door {
      fill: rgba(255, 255, 255, 0.16);
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
    }
    .garage-line {
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
      fill: none;
    }
    .roof-front {
      fill: var(--roof);
    }
    .roof-back {
      fill: var(--roof-back);
    }
    .roof-flat {
      fill: var(--roof-back);
    }
    .roof-flat-top {
      fill: var(--roof);
    }
    .roof-lip {
      fill: #0f1420;
    }
    .fascia {
      fill: #0d111a;
    }
    .ridge {
      stroke: rgba(255, 255, 255, 0.18);
      stroke-width: 1;
      fill: none;
    }
    .pv {
      fill: var(--pv);
      stroke: rgba(190, 220, 255, 0.55);
      stroke-width: 0.7;
    }
    .pv-line {
      stroke: var(--pv-line);
      stroke-width: 0.5;
    }
    .inverter-face {
      fill: #c9ced8;
      stroke: rgba(0, 0, 0, 0.45);
      stroke-width: 0.6;
    }
    .inverter-vent {
      stroke: rgba(0, 0, 0, 0.35);
      stroke-width: 0.6;
      fill: none;
    }
    .inverter-led {
      fill: var(--ef-ok);
    }
    .inverter-led-halo {
      fill: var(--ef-ok);
      opacity: 0.35;
      filter: url(#ef3d-blur);
    }
    .cab-l {
      fill: var(--cab);
    }
    .cab-r {
      fill: var(--cab-r);
    }
    .cab-t {
      fill: var(--cab-t);
    }
    .cab-strip-bg {
      fill: #1b2230;
    }
    .cab-strip {
      fill: var(--ef-battery);
      filter: drop-shadow(0 0 4px rgba(53, 224, 138, 0.9));
    }
    .cab-label {
      font-size: 7.5px;
      font-weight: 800;
      letter-spacing: 0.12em;
      fill: #2b3140;
      text-anchor: middle;
    }
    .pylon-line {
      stroke: #7a879e;
      stroke-width: 1.6;
      stroke-linecap: round;
    }
    .pylon-line.thin {
      stroke-width: 0.8;
      opacity: 0.8;
    }
    .wire {
      stroke: var(--wire);
      stroke-width: 1;
      fill: none;
    }
    .pylon-tip {
      fill: #ff6b6b;
      opacity: 0.9;
    }
    .pylon.live .pylon-line {
      filter: drop-shadow(0 0 3px rgba(62, 166, 255, 0.6));
    }
    .pylon.unknown {
      opacity: 0.6;
    }

    /* ---- flows ---- */
    .flow-base {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      opacity: 0.22;
    }
    .flow-dots {
      fill: none;
      stroke: var(--flow-colour);
      stroke-width: 2.4;
      stroke-linecap: round;
      stroke-dasharray: 0.1 7;
      opacity: 0.55;
    }
    .flow-glow {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      opacity: 0;
      filter: url(#ef3d-blur);
    }
    .flow-packets {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      opacity: 0;
      filter: drop-shadow(0 0 3px var(--flow-colour));
    }
    .flow.moving .flow-packets {
      animation: ef3d-dash linear infinite;
    }
    .flow.moving.reversed .flow-packets {
      animation-direction: reverse;
    }
    .flow.idle .flow-base,
    .flow.idle .flow-dots {
      opacity: 0.14;
    }
    .flow.unknown .flow-base {
      stroke: #6b778d;
      stroke-dasharray: 3 5;
      opacity: 0.45;
    }
    .flow.unknown .flow-dots {
      display: none;
    }
    .scene.stale .flow-base,
    .scene.stale .flow-dots {
      opacity: 0.12;
    }
    /* Artwork routes: thin base, soft glow, crisp highlight, travelling particles. */
    .fine-base {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.55;
    }
    .fine-glow {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      filter: url(#ef3d-blur);
    }
    .fine-highlight {
      fill: none;
      stroke: #ffffff;
      stroke-linecap: round;
      stroke-linejoin: round;
      mix-blend-mode: screen;
    }
    .fine-base {
      opacity: 0.4;
    }
    .fine-riser {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      filter: drop-shadow(0 0 3px var(--flow-colour));
    }
    .flow.fine.idle .fine-base {
      opacity: 0.16;
    }
    .flow.fine.idle .fine-riser,
    .flow.fine.unknown .fine-riser {
      opacity: 0.2;
      filter: none;
    }
    .debug-riser {
      fill: rgba(255, 212, 0, 0.12);
      stroke: #ffd400;
      stroke-dasharray: 4 4;
      stroke-width: 2;
    }
    .debug-entry {
      stroke: #00e5ff;
      stroke-width: 3;
    }
    .flow.fine.unknown .fine-base {
      stroke: #9aa6bd;
      stroke-dasharray: 4 6;
      opacity: 0.35;
    }
    .scene.stale .fine-base {
      opacity: 0.18;
    }
    .node-light-halo {
      fill: var(--flow-colour);
      opacity: 0.1;
      filter: url(#ef3d-blur-soft);
    }
    .node-light-core {
      fill: var(--flow-colour);
      opacity: 0.35;
    }
    .node-light.active .node-light-halo {
      opacity: 0.5;
    }
    .node-light.active .node-light-core {
      fill: #ffffff;
      opacity: 0.95;
      filter: drop-shadow(0 0 4px var(--flow-colour));
    }
    .info-line {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.38;
      stroke-dasharray: 0.01 calc(5px * var(--k, 1));
    }
    .info-glow {
      fill: none;
      stroke: var(--flow-colour);
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0;
      filter: url(#ef3d-blur);
    }
    .info-link.active .info-line {
      opacity: 0.8;
    }
    .info-link.active .info-glow {
      opacity: 0.16;
    }
    .pit-shadow {
      fill: rgba(0, 0, 0, 0.18);
      filter: url(#ef3d-blur);
    }
    .pit-face {
      fill: rgba(20, 26, 38, 0.28);
      stroke: rgba(255, 255, 255, 0.22);
      stroke-width: calc(0.5px * var(--k, 1));
    }
    .junction-bar.led-ok {
      fill: #e7edf7;
    }
    .junction-bar.led-warn {
      fill: var(--ef-warn);
    }
    .junction-bar.led-off {
      fill: #6b778d;
      opacity: 0.6;
    }
    .debug-bend {
      fill: #ffd400;
      stroke: #000;
      stroke-width: 1;
    }
    .debug-paving {
      fill: none;
      stroke: #ffffff;
      stroke-width: 2;
      stroke-dasharray: 6 5;
      opacity: 0.9;
    }
    .debug-paving-label {
      font-size: calc(7px * var(--k, 1));
      fill: #ffffff;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.8);
      stroke-width: calc(1.6px * var(--k, 1));
    }
    .debug-waypoint {
      fill: rgba(53, 224, 138, 0.9);
      stroke: #000;
      stroke-width: 1.5;
    }
    .debug-waypoint-label {
      font-size: calc(7px * var(--k, 1));
      font-weight: 700;
      fill: #b7ffd9;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.85);
      stroke-width: calc(1.6px * var(--k, 1));
    }
    .debug-buried {
      stroke: #ff9f1a;
      stroke-width: 4;
      stroke-dasharray: 3 6;
    }
    .debug-dot {
      fill: #ff3b6b;
    }
    .debug-ring {
      fill: none;
      stroke: #ff3b6b;
      stroke-width: 2;
    }
    .debug-port {
      fill: #fff;
      stroke: #ff3b6b;
      stroke-width: 2;
    }
    .debug-zone {
      fill: none;
      stroke: #ff3b6b;
      stroke-dasharray: 8 6;
      stroke-width: 2;
    }
    .debug-label {
      font-size: calc(10px * var(--k, 1));
      font-weight: 700;
      fill: #fff;
      paint-order: stroke;
      stroke: rgba(0, 0, 0, 0.8);
      stroke-width: calc(2px * var(--k, 1));
    }
    .pulse-halo {
      fill: var(--pulse-colour);
      opacity: 0.22;
      filter: url(#ef3d-blur);
    }
    .pulse-glow {
      fill: var(--pulse-colour);
      opacity: 0.9;
    }
    .pulse-core {
      fill: #ffffff;
    }
    .flow.fine .pulse-halo {
      opacity: 0.3;
    }
    .flow.fine .pulse-glow {
      opacity: 0.95;
      filter: drop-shadow(0 0 4px var(--pulse-colour));
    }
    .flow.fine .pulse-halo {
      opacity: 0.38;
    }
    .chevron path {
      stroke: var(--pulse-colour);
    }
    .scene.still .pulse {
      display: none;
    }
    .junction {
      fill: #e7edf7;
    }
    .junction-halo {
      opacity: 0.35;
      filter: url(#ef3d-blur);
    }
    .junction.led-ok,
    .junction-halo.led-ok {
      fill: #e7edf7;
    }
    .junction.led-warn,
    .junction-halo.led-warn {
      fill: var(--ef-warn);
    }
    .junction.led-off,
    .junction-halo.led-off {
      fill: #6b778d;
      opacity: 0.6;
    }
    @keyframes ef3d-dash {
      to {
        stroke-dashoffset: var(--dash-travel, -30);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .flow.moving .flow-packets {
        animation: none;
      }
      .pulse {
        display: none;
      }
    }

    /* ---- pills ---- */
    .pill {
      cursor: default;
    }
    .pill.clickable {
      cursor: pointer;
    }
    .pill-bg {
      fill: rgba(9, 14, 26, 0.84);
    }
    .pill-border {
      fill: none;
      stroke: var(--pill-colour);
      stroke-width: 1.4;
      opacity: 0.85;
      filter: drop-shadow(0 0 6px var(--pill-colour));
    }
    .pill.idle .pill-border,
    .pill.unknown .pill-border {
      opacity: 0.35;
      filter: none;
    }
    .pill.unknown .pill-border {
      stroke: #6b778d;
      stroke-dasharray: 4 3;
    }
    .pill.clickable:hover .pill-bg,
    .pill.clickable:focus-visible .pill-bg {
      fill: rgba(20, 28, 46, 0.92);
    }
    .pill:focus {
      outline: none;
    }
    .pill-icon-bg {
      fill: rgba(255, 255, 255, 0.06);
    }
    .pill-label {
      font-size: 11px;
      font-weight: 600;
      fill: #c8d2e6;
      letter-spacing: 0.01em;
    }
    .pill-value {
      font-size: 19px;
      font-weight: 800;
      fill: #ffffff;
      letter-spacing: -0.01em;
    }
    .pill.unknown .pill-value {
      fill: #8e9bb7;
    }
    .pill-sub {
      font-size: 10px;
      font-weight: 600;
      fill: var(--pill-colour);
    }
    .pill-extra {
      font-size: 10px;
      font-weight: 600;
      fill: #dfe7f7;
    }
    .scene.artwork .pill-extra {
      font-size: calc(10px * var(--k, 1));
    }
    .pill.tone-alert .pill-sub {
      fill: var(--ef-alert);
    }
    .pill.unknown .pill-sub,
    .pill.idle .pill-sub {
      fill: #8e9bb7;
    }
    .ring-track {
      fill: none;
      stroke: rgba(255, 255, 255, 0.1);
      stroke-width: 5;
    }
    .ring-fill {
      fill: none;
      stroke: var(--pill-colour);
      stroke-width: 5;
      stroke-linecap: round;
      filter: drop-shadow(0 0 4px var(--pill-colour));
    }
    .ring-value {
      font-size: 12px;
      font-weight: 800;
      fill: #fff;
      text-anchor: middle;
    }
    .ring-caption {
      font-size: 6.5px;
      font-weight: 700;
      fill: #8e9bb7;
      text-anchor: middle;
      letter-spacing: 0.1em;
    }

    /* ---- status grid ---- */
    .status {
      border-radius: 20px;
      background: var(--ef-surface);
      border: 1px solid var(--ef-border);
      padding: 12px;
    }
    .status-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 4px 10px;
    }
    .status-title {
      font-weight: 700;
      font-size: 15px;
    }
    .status-age {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--ef-muted);
      font-size: 12px;
    }
    .status-age.stale {
      color: var(--ef-warn);
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .tile {
      display: grid;
      grid-template-columns: 30px minmax(0, 1fr) 12px;
      align-items: center;
      gap: 7px;
      text-align: left;
      border-radius: 14px;
      border: 1px solid var(--ef-border);
      background: rgba(255, 255, 255, 0.035);
      color: inherit;
      padding: 9px 6px 9px 8px;
      font: inherit;
      min-height: 72px;
      cursor: default;
    }
    /* Row three: Health (one column) and Solar Forecast (two columns), as in the reference. */
    .tiles .tile:nth-child(8) {
      grid-column: span 2;
    }
    /* Phones: two readable columns; three columns need about 150 px per tile. */
    @container (max-width: 459px) {
      .tiles {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .tiles .tile:nth-child(8) {
        grid-column: span 1;
      }
    }
    .tile.clickable {
      cursor: pointer;
    }
    .tile.clickable:hover,
    .tile.clickable:focus-visible {
      background: var(--ef-surface-2);
      border-color: rgba(255, 255, 255, 0.16);
      outline: none;
    }
    .tile-icon {
      width: 30px;
      height: 30px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: rgba(255, 255, 255, 0.06);
      color: var(--ef-accent);
    }
    .tile-icon svg,
    .tile-chev,
    summary svg {
      width: 18px;
      height: 18px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.9;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .tile-chev {
      width: 12px;
      height: 12px;
      color: rgba(255, 255, 255, 0.4);
    }
    .tone-ok .tile-icon {
      color: var(--ef-ok);
    }
    .tone-warn .tile-icon {
      color: var(--ef-warn);
    }
    .tone-alert .tile-icon {
      color: var(--ef-alert);
      background: rgba(255, 107, 107, 0.14);
    }
    .tone-accent .tile-icon {
      color: #b8a4ff;
    }
    .tone-muted .tile-icon {
      color: var(--ef-muted);
    }
    .tile-text {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .tile-label {
      font-size: 11px;
      color: var(--ef-muted);
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tile-value {
      font-size: 16px;
      font-weight: 800;
      letter-spacing: -0.01em;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tone-muted .tile-value {
      color: #c3cbdc;
    }
    .tone-alert .tile-value {
      color: var(--ef-alert);
    }
    .tone-warn .tile-value {
      color: var(--ef-warn);
    }
    .tile-sub {
      font-size: 10.5px;
      color: var(--ef-muted);
      margin-top: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }

    /* ---- details ---- */
    .details {
      border-radius: 16px;
      border: 1px solid var(--ef-border);
      background: var(--ef-surface);
    }
    summary {
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 14px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
      color: #c8d2e6;
    }
    summary::-webkit-details-marker {
      display: none;
    }
    summary svg {
      width: 16px;
      height: 16px;
      transform: rotate(90deg);
      transition: transform 0.2s ease;
    }
    .details[open] summary svg {
      transform: rotate(-90deg);
    }
    .details-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 10px 18px;
      padding: 0 14px 14px;
    }
    .group-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ef-muted);
      font-weight: 700;
      padding: 8px 0 4px;
    }
    .row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 5px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      font-size: 13px;
    }
    .row.clickable {
      cursor: pointer;
    }
    .row.clickable:hover .row-value {
      color: #fff;
    }
    .row-label {
      color: var(--ef-muted);
      text-transform: capitalize;
    }
    .row-value {
      text-align: right;
      font-weight: 600;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
    }
    .row-note {
      font-size: 10.5px;
      color: var(--ef-muted);
      font-weight: 500;
    }
    .row-note.block {
      padding: 6px 0;
    }
  `;
}

declare global {
  interface HTMLElementTagNameMap {
    "ecco-flow-3d-card": EccoFlow3dCard;
  }
}

(window as unknown as { customCards?: unknown[] }).customCards = [
  ...((window as unknown as { customCards?: unknown[] }).customCards ?? []),
  {
    type: "ecco-flow-3d-card",
    name: "ECCO 3D Energy Flow",
    description: "Read-only isometric energy flow scene (solar, battery, grid, home) with animated power paths and the ECCO status grid.",
    preview: false,
  },
];

export type { HassEntity };
