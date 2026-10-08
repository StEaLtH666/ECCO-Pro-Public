// Shared test fixtures: a mocked Home Assistant `states` map for every entity the catalogue links to.
import { CATALOGUE } from "../src/catalogue.generated.ts";
import { DEFAULT_ENTITY_PREFIX, entityId, normalizeConfig } from "../src/model.ts";
import type { CardConfig, CatalogueItem, HassEntityLike, StatesLike } from "../src/types.ts";

export const NOW = Date.parse("2026-10-08T12:00:00Z");
export const PREFIX = DEFAULT_ENTITY_PREFIX;
export const GP_MOCK_W = 3500;

export function iso(msAgo: number): string {
  return new Date(NOW - msAgo).toISOString();
}

export function config(over: Record<string, unknown> = {}): CardConfig {
  return normalizeConfig({ type: "custom:ecco-advanced-config-card", ...over });
}

export function item(id: string): CatalogueItem {
  const it = CATALOGUE.items.find((i) => i.id === id);
  if (!it) throw new Error(`no catalogue item ${id}`);
  return it;
}

export function entityOf(id: string, prefix = PREFIX): string {
  const it = item(id);
  if (!it.entity) throw new Error(`${id} has no entity`);
  return entityId(it.entity, prefix);
}

function plausible(it: CatalogueItem): string {
  if (it.entity?.domain === "binary_sensor") return "off";
  const kind = it.decode?.kind;
  if (kind === "enum" && it.options.enum && it.options.enum[0]) return it.options.enum[0].label;
  if (kind === "hhmm") return "05:30";
  if (kind === "tou_charge") return "Grid";
  if (kind === "tou_mode") return "General";
  if (kind === "bit_text") return it.decode?.clear_text ?? "Enable";
  if (it.unit === "W") return "1000";
  return "1";
}

/** A fresh, plausible state for every linked entity (and raw-word entity), plus both freshness gates on. */
export function mockStates(prefix = PREFIX, ageMs = 5000): StatesLike {
  const states: StatesLike = {};
  const put = (eid: string, state: string, attrs: Record<string, unknown> = {}): void => {
    const ts = iso(ageMs);
    states[eid] = { state, attributes: attrs, last_changed: ts, last_updated: ts, last_reported: ts };
  };
  for (const it of CATALOGUE.items) {
    if (it.entity) put(entityId(it.entity, prefix), plausible(it), it.unit ? { unit_of_measurement: it.unit } : {});
    if (it.raw_entity) put(entityId(it.raw_entity, prefix), "1");
  }
  put(entityId(CATALOGUE.freshness_gates.telemetry, prefix), "on");
  put(entityId(CATALOGUE.freshness_gates.configuration, prefix), "on");
  // Global Power / Export Limit: an arbitrary mocked reading (deliberately not any ceiling the card might be suspected of
  // defaulting to).
  put(entityId(item("export_limit").entity!, prefix), String(GP_MOCK_W), { unit_of_measurement: "W" });
  return states;
}

export function withEntity(states: StatesLike, eid: string, e: HassEntityLike | undefined): StatesLike {
  const copy: StatesLike = { ...states };
  if (e === undefined) delete copy[eid];
  else copy[eid] = e;
  return copy;
}
