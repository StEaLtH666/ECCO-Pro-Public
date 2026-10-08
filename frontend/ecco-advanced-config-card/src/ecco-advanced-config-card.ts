// ECCO Advanced / Experimental Configuration card (read-only).
//
// A searchable catalogue of the inverter registers in ECCO's capability registry, with live values from the ECCO
// controller's Home Assistant entities and a Global Power / Export Limit (register 245) panel.
//
// READ-ONLY GUARANTEE (structural): the `hass` setter keeps only `hass.states` - the Home Assistant object itself is
// never stored, so no service, websocket or connection method of it is reachable from this card. The only events
// handled are search typing, filter chips and expanding a row; each changes local view state only. The Global Power
// write controls are rendered disabled and carry no action attribute. No Modbus, no Home Assistant service call, no
// network request exists anywhere in this card.
import { CATALOGUE, CATALOGUE_SHA256 } from "./catalogue.generated.ts";
import {
  DEFAULT_ENTITY_PREFIX,
  buildGlobalPowerView,
  emptyFilter,
  entityId,
  filterItems,
  groupBySection,
  normalizeConfig,
  resolveValue,
} from "./model.ts";
import { renderFilters, renderGlobalPower, renderResults, renderShell, renderSummary } from "./render.ts";
import { STYLES } from "./styles.ts";
import type { CardConfig, Catalogue, Evidence, FilterState, StatesLike, Status, ValueView } from "./types.ts";

export const CARD_TAG = "ecco-advanced-config-card";
export const CARD_VERSION = "0.1.0";
/** Re-render at least this often even when no referenced entity changed, so freshness labels age honestly. */
export const REFRESH_INTERVAL_MS = 30000;

interface RegionLike {
  innerHTML: string;
  value?: unknown;
}

interface RootLike {
  innerHTML: string;
  querySelector(selector: string): RegionLike | null;
  addEventListener(type: string, listener: (ev: Event) => void): void;
}

interface ActionElementLike {
  getAttribute(name: string): string | null;
}

const STATUS_VALUES = new Set<string>(["PROVEN", "EXPERIMENTAL", "READ_ONLY", "LOCKED", "UNSUPPORTED"]);
const EVIDENCE_VALUES = new Set<string>(["M3", "M2", "M1", "M0", "MX"]);

export class EccoAdvancedConfigCard extends HTMLElement {
  static readonly catalogueSha256 = CATALOGUE_SHA256;

  /** Clock used for freshness; replaceable in tests. */
  now: () => number = () => Date.now();

  private _config: CardConfig | null = null;
  private _states: StatesLike = {};
  private _filter: FilterState = emptyFilter();
  private _expanded = new Set<string>();
  private _root: RootLike | null = null;
  private _listening = false;
  private _catalogue: Catalogue = CATALOGUE;
  private _values = new Map<string, ValueView>();
  private _signature = "";
  private _renderedAt = 0;

  setConfig(config: unknown): void {
    this._config = normalizeConfig(config);
    this._buildShell();
    this._signature = "";
    this._renderFilters();
    this._renderData(true);
  }

  set hass(hass: unknown) {
    // Keep ONLY the states map; never the Home Assistant object (read-only by construction).
    const states = hass !== null && typeof hass === "object" ? (hass as { states?: unknown }).states : undefined;
    this._states = states !== null && typeof states === "object" ? (states as StatesLike) : {};
    this._renderData(false);
  }

  getCardSize(): number {
    return 12;
  }

  static getStubConfig(): Record<string, unknown> {
    return { entity_prefix: DEFAULT_ENTITY_PREFIX };
  }

  private _buildShell(): void {
    if (!this._config) return;
    const root = (this.shadowRoot ?? this.attachShadow({ mode: "open" })) as unknown as RootLike;
    root.innerHTML = renderShell(
      this._config.title,
      STYLES,
      this._catalogue,
      `Catalogue ${CATALOGUE_SHA256.slice(0, 12)} - card ${CARD_VERSION}`,
    );
    if (!this._listening) {
      root.addEventListener("input", this._onInput);
      root.addEventListener("click", this._onClick);
      this._listening = true;
    }
    this._root = root;
    const search = root.querySelector('input[data-action="search"]');
    if (search) search.value = this._filter.query;
  }

  private _region(name: string): RegionLike | null {
    return this._root ? this._root.querySelector(`[data-region="${name}"]`) : null;
  }

  private _referencedSignature(): string {
    if (!this._config) return "";
    const prefix = this._config.entity_prefix;
    const parts: string[] = [];
    const add = (ref: { domain: string; object: string } | undefined): void => {
      if (!ref) return;
      const e = this._states[entityId(ref, prefix)];
      parts.push(e ? `${String(e.state)}|${String(e.last_reported ?? e.last_updated ?? e.last_changed ?? "")}` : "-");
    };
    for (const it of this._catalogue.items) {
      add(it.entity);
      add(it.raw_entity);
    }
    add(this._catalogue.freshness_gates.telemetry);
    add(this._catalogue.freshness_gates.configuration);
    return parts.join("\u0002");
  }

  private _renderData(force: boolean): void {
    if (!this._config || !this._root) return;
    const now = this.now();
    const sig = this._referencedSignature();
    if (!force && sig === this._signature && now - this._renderedAt < REFRESH_INTERVAL_MS) return;
    this._signature = sig;
    this._renderedAt = now;
    const values = new Map<string, ValueView>();
    for (const it of this._catalogue.items) {
      values.set(it.id, resolveValue(it, this._states, this._catalogue, this._config, now));
    }
    this._values = values;
    const gp = this._region("gp");
    if (gp) gp.innerHTML = renderGlobalPower(buildGlobalPowerView(this._catalogue, this._states, this._config, now));
    this._renderResults();
  }

  private _renderFilters(): void {
    const r = this._region("filters");
    if (r) r.innerHTML = renderFilters(this._catalogue, this._filter);
  }

  private _renderResults(): void {
    const items = filterItems(this._catalogue, this._filter);
    const res = this._region("results");
    if (res) res.innerHTML = renderResults(groupBySection(this._catalogue, items), this._values, this._expanded);
    const sum = this._region("summary");
    if (sum) sum.innerHTML = renderSummary(items.length, this._catalogue.items.length);
  }

  private _onInput = (ev: Event): void => {
    const t = ev.target as unknown as (ActionElementLike & { value?: unknown }) | null;
    if (!t || typeof t.getAttribute !== "function" || t.getAttribute("data-action") !== "search") return;
    this._filter.query = String(t.value ?? "").slice(0, 200);
    this._renderFilters();
    this._renderResults();
  };

  private _onClick = (ev: Event): void => {
    const target = ev.target as unknown as { closest?: (selector: string) => ActionElementLike | null } | null;
    const el = target && typeof target.closest === "function" ? target.closest("[data-action]") : null;
    if (!el) return;
    const action = el.getAttribute("data-action");
    if (action === "toggle-filter") {
      const kind = el.getAttribute("data-kind");
      const value = el.getAttribute("data-value") ?? "";
      if (kind === "status" && STATUS_VALUES.has(value)) toggle(this._filter.statuses, value as Status);
      else if (kind === "evidence" && EVIDENCE_VALUES.has(value)) toggle(this._filter.evidence, value as Evidence);
      else if (kind === "section" && this._catalogue.sections.some((s) => s.id === value)) toggle(this._filter.sections, value);
      else return;
      this._renderFilters();
      this._renderResults();
    } else if (action === "clear-filters") {
      this._filter = emptyFilter();
      const search = this._root ? this._root.querySelector('input[data-action="search"]') : null;
      if (search) search.value = "";
      this._renderFilters();
      this._renderResults();
    } else if (action === "toggle-item") {
      const id = el.getAttribute("data-id") ?? "";
      if (!this._catalogue.items.some((i) => i.id === id)) return;
      toggle(this._expanded, id);
      this._renderResults();
    }
    // Any other action value is ignored: there is nothing else this card can do.
  };
}

function toggle<T>(set: Set<T>, value: T): void {
  if (set.has(value)) set.delete(value);
  else set.add(value);
}

if (typeof customElements !== "undefined" && !customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, EccoAdvancedConfigCard);
}

if (typeof window !== "undefined") {
  const w = window as unknown as { customCards?: Array<Record<string, unknown>> };
  w.customCards = w.customCards || [];
  if (!w.customCards.some((c) => c.type === CARD_TAG)) {
    w.customCards.push({
      type: CARD_TAG,
      name: "ECCO Advanced Configuration",
      description: "Read-only catalogue of ECCO's inverter registers with the Global Power / Export Limit panel.",
      preview: false,
    });
  }
}
