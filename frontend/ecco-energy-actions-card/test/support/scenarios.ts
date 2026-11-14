// The flag-off identity scenarios: the card rendered with the existing configuration (no `show_plan`), flattened to text.
// test/golden/flag-off-render.json was captured from the card source as it stood BEFORE the plan views were added (commit
// c6e5a58 plus the stage-1 package), so a test comparing today's flag-off render with it proves the existing layout is unchanged.
import { BASE_CONFIG, idleStates, makeHass } from "./fixtures.ts";
import type { States } from "./fixtures.ts";
import { flatten } from "./loadCard.ts";

type Ctor = new () => { render(): unknown; setConfig(c: unknown): void; hass?: unknown };

export const SCENARIOS: Record<string, { layout?: string; patch?: (s: States) => void }> = {
  "side-by-side-idle": {},
  "tabbed-idle": { layout: "tabbed" },
  "side-by-side-armed-and-active": {
    patch: (s) => {
      const c = BASE_CONFIG;
      s[c.schedule.armed] = { state: "on" };
      s[c.dump_to_grid.active] = { state: "on" };
      s[c.dump_to_grid.write_enable] = { state: "on" };
      s[c.dump_to_grid.status] = { state: "Active" };
      s[c.dump_to_grid.ends_at] = { state: "2026-11-14 18:30:00" };
    },
  },
  "tabbed-free-power-armed": {
    layout: "tabbed",
    patch: (s) => {
      s[BASE_CONFIG.free_power.write_enable] = { state: "on" };
    },
  },
};

/** A fixed clock: the card's countdowns read Date.now() when it is constructed. */
export const FROZEN_NOW = Date.parse("2026-11-14T12:00:00Z");

export function renderScenario(Card: Ctor, name: string, extra: Record<string, unknown> = {}): string {
  const sc = SCENARIOS[name];
  if (!sc) throw new Error("unknown scenario " + name);
  return withFrozenClock(() => renderFrozen(Card, sc, extra));
}

export function withFrozenClock<T>(fn: () => T): T {
  const realNow = Date.now;
  Date.now = () => FROZEN_NOW;
  try {
    return fn();
  } finally {
    Date.now = realNow;
  }
}

function renderFrozen(Card: Ctor, sc: { layout?: string; patch?: (s: States) => void }, extra: Record<string, unknown>): string {
  const states = idleStates();
  sc.patch?.(states);
  const card = new Card();
  card.setConfig({ ...BASE_CONFIG, ...(sc.layout ? { layout: sc.layout } : {}), ...extra });
  card.hass = makeHass(states).hass;
  return flatten(card.render());
}
