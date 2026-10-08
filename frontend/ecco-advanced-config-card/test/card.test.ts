// The custom element, driven through a recording DOM shim with a mocked Home Assistant object. The central claim:
// no UI operation reaches Home Assistant (no service, websocket or API call), the inverter, the network or a timer.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CATALOGUE, CATALOGUE_SHA256 } from "../src/catalogue.generated.ts";
import { emptyFilter, entityId, filterItems } from "../src/model.ts";
import type { StatesLike } from "../src/types.ts";
import { FakeRoot, elementsIn, installDomShim, makeEl, recordingHass } from "./dom-shim.ts";
import { GP_MOCK_W, NOW, PREFIX, entityOf, iso, mockStates, withEntity } from "./fixtures.ts";

const shim = installDomShim();
const mod = await import("../src/ecco-advanced-config-card.ts");
const { EccoAdvancedConfigCard, CARD_TAG, CARD_VERSION, REFRESH_INTERVAL_MS } = mod;

type Card = InstanceType<typeof EccoAdvancedConfigCard>;

function newCard(cfg: Record<string, unknown> = {}, now = NOW): { card: Card; root: FakeRoot } {
  const card = new EccoAdvancedConfigCard();
  card.now = () => now;
  card.setConfig({ type: `custom:${CARD_TAG}`, ...cfg });
  const root = (card as unknown as { shadowRoot: FakeRoot }).shadowRoot;
  return { card, root };
}

function summary(root: FakeRoot): string {
  return root.region("summary");
}

function rows(root: FakeRoot): number {
  return (root.region("results").match(/data-action="toggle-item"/g) ?? []).length;
}

function click(root: FakeRoot, attrs: Record<string, string>): void {
  root.dispatch("click", makeEl("button", attrs));
}

function type(root: FakeRoot, value: string): void {
  const el = makeEl("input", { "data-action": "search" });
  el.value = value;
  root.dispatch("input", el);
}

function expectedCount(query: string): number {
  const f = emptyFilter();
  f.query = query;
  return filterItems(CATALOGUE, f).length;
}

describe("registration", () => {
  it("defines the custom element once and announces it to the card picker once", () => {
    assert.equal(shim.defined.get(CARD_TAG), EccoAdvancedConfigCard);
    const cards = (shim.window.customCards ?? []).filter((c) => c.type === CARD_TAG);
    assert.equal(cards.length, 1);
    assert.equal(cards[0]?.name, "ECCO Advanced Configuration");
    assert.equal(cards[0]?.preview, false);
    assert.equal(CARD_TAG, "ecco-advanced-config-card");
    assert.equal(CARD_VERSION, "0.1.0");
    assert.equal(EccoAdvancedConfigCard.catalogueSha256, CATALOGUE_SHA256);
  });

  it("offers a stub configuration with the default device slug and a card size", () => {
    assert.deepEqual(EccoAdvancedConfigCard.getStubConfig(), { entity_prefix: "ecco_clock_dongle" });
    assert.equal(new EccoAdvancedConfigCard().getCardSize(), 12);
  });
});

describe("configuration and rendering with mocked Home Assistant state", () => {
  it("rejects a malformed configuration", () => {
    const card = new EccoAdvancedConfigCard();
    assert.throws(() => card.setConfig({ entity_prefix: "Bad Slug" }), /entity_prefix/);
    assert.throws(() => card.setConfig({ allow_writes: true }), /unknown option/);
    assert.throws(() => card.setConfig(null), /mapping/);
  });

  it("renders the Global Power panel, every catalogue row and the summary", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    assert.equal(rows(root), 165);
    assert.equal(summary(root), "165 of 165 settings shown. This page is read-only.");
    const gp = root.region("gp");
    assert.ok(gp.includes("Register 245"));
    assert.ok(gp.includes(`<span class="big v-ok">${GP_MOCK_W} W</span>`));
    assert.ok(gp.includes("Hardware maximum not verified"));
    assert.ok(root.innerHTML.includes(`Catalogue ${CATALOGUE_SHA256.slice(0, 12)} - card 0.1.0`));
    assert.ok(root.innerHTML.includes('<span class="badge ro">READ ONLY</span>'));
  });

  it("before any hass, and with garbage hass, nothing is invented", () => {
    const { card, root } = newCard();
    assert.ok(root.region("gp").includes("Entity not found in Home Assistant"));
    for (const bad of [null, undefined, 42, "x", { states: null }, { states: "x" }, { states: 5 }, []]) {
      assert.doesNotThrow(() => {
        card.hass = bad;
      });
      assert.ok(root.region("gp").includes("Entity not found in Home Assistant"), JSON.stringify(bad));
      assert.ok(!root.region("gp").includes(">0 W<"));
    }
  });

  it("hass set before setConfig is used once the card is configured", () => {
    const card = new EccoAdvancedConfigCard();
    card.now = () => NOW;
    card.hass = { states: mockStates() };
    card.setConfig({});
    const root = (card as unknown as { shadowRoot: FakeRoot }).shadowRoot;
    assert.ok(root.region("gp").includes(`${GP_MOCK_W} W`));
  });

  it("uses the configured device slug", () => {
    const { card, root } = newCard({ entity_prefix: "site_b" });
    card.hass = { states: mockStates("site_b") };
    assert.ok(root.region("gp").includes("<code>sensor.site_b_ecco_export_limit</code>"));
    assert.ok(root.region("gp").includes(`${GP_MOCK_W} W`));
    card.hass = { states: mockStates() };
    assert.ok(root.region("gp").includes("Entity not found in Home Assistant"));
  });

  it("re-configuring keeps one shadow root and one listener per event type", () => {
    const { card, root } = newCard();
    card.setConfig({ title: "Again" });
    card.setConfig({ title: "And again" });
    assert.equal((card as unknown as { shadowRoot: FakeRoot }).shadowRoot, root);
    assert.equal(root.listeners.get("click")?.length, 1);
    assert.equal(root.listeners.get("input")?.length, 1);
    assert.deepEqual([...root.listeners.keys()].sort(), ["click", "input"]);
    assert.ok(root.innerHTML.includes("And again"));
  });

  it("entity text is escaped all the way to the shadow DOM", () => {
    const { card, root } = newCard();
    const eid = entityOf("battery_control_mode");
    const ts = iso(1000);
    card.hass = { states: withEntity(mockStates(), eid, { state: '<img src=x onerror="alert(1)">', last_reported: ts }) };
    click(root, { "data-action": "toggle-item", "data-id": "battery_control_mode" });
    assert.ok(!root.region("results").includes("<img"));
    assert.ok(root.region("results").includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
  });
});

describe("search, filters and expansion", () => {
  it("search by register, name and description narrows the list", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    for (const q of ["245", "r245", "export limit", "global power", "configured export power", "zzqqxx"]) {
      type(root, q);
      assert.equal(summary(root), `${expectedCount(q)} of 165 settings shown. This page is read-only.`, q);
      assert.equal(rows(root), expectedCount(q), q);
    }
    type(root, "245");
    assert.ok(root.region("results").includes('data-id="export_limit"'));
  });

  it("over-long input is truncated; input events from anything but the search box are ignored", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    type(root, "x".repeat(500));
    assert.equal((card as unknown as { _filter: { query: string } })._filter.query.length, 200);
    type(root, "");
    const before = root.writesOf("results");
    root.dispatch("input", makeEl("button", { "data-action": "toggle-filter" }));
    root.dispatch("input", null);
    root.dispatch("input", { value: "245" });
    assert.equal(root.writesOf("results"), before);
    assert.equal(summary(root), "165 of 165 settings shown. This page is read-only.");
  });

  it("filter chips toggle status, evidence and category; forged chips are ignored", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    click(root, { "data-action": "toggle-filter", "data-kind": "status", "data-value": "LOCKED" });
    assert.equal(summary(root), "16 of 165 settings shown. This page is read-only.");
    assert.ok(root.region("filters").includes('data-value="LOCKED" aria-pressed="true"'));
    click(root, { "data-action": "toggle-filter", "data-kind": "status", "data-value": "LOCKED" });
    assert.equal(summary(root), "165 of 165 settings shown. This page is read-only.");
    click(root, { "data-action": "toggle-filter", "data-kind": "evidence", "data-value": "MX" });
    assert.equal(summary(root), "7 of 165 settings shown. This page is read-only.");
    click(root, { "data-action": "toggle-filter", "data-kind": "section", "data-value": "experimental" });
    assert.equal(summary(root), "7 of 165 settings shown. This page is read-only.");
    const writes = root.writesOf("filters");
    for (const forged of [
      { "data-kind": "status", "data-value": "WRITABLE" },
      { "data-kind": "evidence", "data-value": "M9" },
      { "data-kind": "section", "data-value": "no_such_section" },
      { "data-kind": "service", "data-value": "number.set_value" },
      { "data-kind": "status" },
    ]) {
      click(root, { "data-action": "toggle-filter", ...forged });
    }
    assert.equal(root.writesOf("filters"), writes);
    assert.equal(summary(root), "7 of 165 settings shown. This page is read-only.");
    click(root, { "data-action": "clear-filters" });
    assert.equal(summary(root), "165 of 165 settings shown. This page is read-only.");
  });

  it("clear-filters resets the search box and every filter", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    type(root, "245");
    click(root, { "data-action": "toggle-filter", "data-kind": "status", "data-value": "READ_ONLY" });
    assert.ok(root.region("filters").includes('data-action="clear-filters"'));
    click(root, { "data-action": "clear-filters" });
    assert.equal(root.querySelector('input[data-action="search"]')?.value, "");
    assert.equal(summary(root), "165 of 165 settings shown. This page is read-only.");
    assert.ok(!root.region("filters").includes('data-action="clear-filters"'));
  });

  it("rows expand and collapse; unknown ids and unknown actions are ignored", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    click(root, { "data-action": "toggle-item", "data-id": "export_limit" });
    assert.ok(root.region("results").includes('id="d-export_limit"'));
    assert.ok(root.region("results").includes('data-id="export_limit" aria-expanded="true"'));
    click(root, { "data-action": "toggle-item", "data-id": "export_limit" });
    assert.ok(!root.region("results").includes('id="d-export_limit"'));
    const before = root.writesOf("results");
    click(root, { "data-action": "toggle-item", "data-id": "no_such_item" });
    click(root, { "data-action": "toggle-item" });
    for (const a of ["apply", "unlock", "write", "call-service", "set-value", "press", "turn_on", ""]) click(root, { "data-action": a, "data-id": "export_limit" });
    root.dispatch("click", null);
    root.dispatch("click", {});
    root.dispatch("click", { closest: () => null });
    assert.equal(root.writesOf("results"), before);
  });
});

describe("no write authority: every UI operation is local", () => {
  it("drives every rendered control and proves nothing reached Home Assistant, the network or a timer", () => {
    const rec = shim.rec;
    rec.reads.length = 0;
    rec.calls.length = 0;
    const hass = recordingHass(mockStates(), rec);
    const { card, root } = newCard();
    shim.noTimers(() => {
      card.hass = hass;
      // every control in every region, in turn, twice (on and off)
      for (let pass = 0; pass < 2; pass++) {
        const html = [root.innerHTML, root.region("gp"), root.region("filters"), root.region("results")].join("\n");
        for (const el of elementsIn(html)) {
          root.dispatch("click", el);
          if (el.getAttribute("data-action") === "search") {
            for (const q of ["245", "export", "<script>", "number.set_value", ""]) {
              el.value = q;
              root.dispatch("input", el);
            }
          }
        }
      }
      // expand every row, then a forged write-looking action on every row
      for (const it of CATALOGUE.items) click(root, { "data-action": "toggle-item", "data-id": it.id });
      for (const it of CATALOGUE.items) click(root, { "data-action": "apply", "data-id": it.id, "data-value": "9999" });
      // the disabled Global Power controls, clicked anyway (a real browser would not even dispatch these)
      for (const el of elementsIn(root.region("gp"))) {
        root.dispatch("click", el);
        root.dispatch("input", el);
      }
      card.hass = hass;
    });
    assert.deepEqual(rec.calls, []);
    assert.ok(rec.reads.length >= 2);
    assert.deepEqual([...new Set(rec.reads)], ["states"]);
    // the card keeps the states map, never the Home Assistant object
    assert.ok(!Object.values(card).some((v) => v === hass));
    assert.equal(rows(root), 165);
  });

  it("negative control: the recorder does catch calls, writes, network use and timers", () => {
    const rec = { reads: [] as string[], calls: [] as string[] };
    const hass = recordingHass(mockStates(), rec) as {
      callService: (...a: unknown[]) => unknown;
      connection: { sendMessage: (m: unknown) => unknown };
      states: Record<string, unknown>;
    };
    void hass.callService("number", "set_value", { value: 1 });
    void hass.connection.sendMessage({ type: "call_service" });
    assert.throws(() => {
      hass.states["sensor.x"] = { state: "1" };
    }, TypeError);
    assert.throws(() => {
      (hass as unknown as Record<string, unknown>).extra = 1;
    }, TypeError);
    assert.deepEqual(rec.calls, ["hass.callService", "connection.sendMessage", "states set sensor.x", "hass set extra"]);
    assert.deepEqual(rec.reads, ["callService", "connection", "states"]);
    const before = shim.rec.calls.length;
    shim.noTimers(() => {
      setTimeout(() => undefined, 1);
      void fetch("http://127.0.0.1:1/").catch(() => undefined);
      new (globalThis as unknown as { WebSocket: new (u: string) => unknown }).WebSocket("ws://127.0.0.1:1/");
    });
    assert.deepEqual(shim.rec.calls.slice(before), ["setTimeout", "fetch", "WebSocket"]);
    shim.rec.calls.length = before;
  });

  it("the Global Power controls are disabled and carry no action", () => {
    const { card, root } = newCard();
    card.hass = { states: mockStates() };
    const gp = root.region("gp");
    const controls = elementsIn(gp);
    assert.equal(controls.length, 3);
    for (const el of controls) {
      assert.equal(el.getAttribute("disabled"), "");
      assert.equal(el.getAttribute("aria-disabled"), "true");
      assert.equal(el.getAttribute("data-action"), null);
      assert.equal(el.closest("[data-action]"), null);
    }
    assert.deepEqual(controls.map((e) => e.tag), ["button", "input", "button"]);
  });
});

describe("freshness through the element", () => {
  it("re-renders on entity changes, and ages values honestly without them", () => {
    const states = mockStates();
    const { card, root } = newCard();
    let now = NOW;
    card.now = () => now;
    card.hass = { states };
    const writes = root.writesOf("gp");
    card.hass = { states };
    assert.equal(root.writesOf("gp"), writes, "unchanged entities within the refresh interval do not re-render");
    const changed: StatesLike = withEntity(states, entityOf("export_limit"), {
      state: "3600",
      attributes: { unit_of_measurement: "W" },
      last_reported: iso(0),
    });
    card.hass = { states: changed };
    assert.ok(root.region("gp").includes('<span class="big v-ok">3600 W</span>'));
    assert.ok(root.region("gp").includes("<dt>Read freshness</dt><dd>Live"));
    // ten minutes later with no new report (and the configuration poll gate as old): no longer live
    now = NOW + 10 * 60 * 1000;
    card.hass = { states: changed };
    assert.ok(now - NOW > REFRESH_INTERVAL_MS);
    assert.ok(root.region("gp").includes("<dt>Read freshness</dt><dd>Stale"), root.region("gp").slice(0, 300));
    assert.ok(!root.region("results").includes('class="fresh f-live"'));
  });

  it("an old value with a fresh, online poll gate is 'current', not 'live'", () => {
    const states = mockStates(PREFIX, 3_600_000);
    const ts = iso(1000);
    states[entityId(CATALOGUE.freshness_gates.configuration, PREFIX)] = { state: "on", last_reported: ts };
    states[entityId(CATALOGUE.freshness_gates.telemetry, PREFIX)] = { state: "on", last_reported: ts };
    const { card, root } = newCard();
    card.hass = { states };
    assert.ok(root.region("gp").includes("<dt>Read freshness</dt><dd>Current (poll online)"));
  });
});
