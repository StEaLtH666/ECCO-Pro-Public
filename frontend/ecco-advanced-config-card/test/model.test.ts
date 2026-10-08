import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CATALOGUE } from "../src/catalogue.generated.ts";
import {
  DEFAULT_ENTITY_PREFIX,
  DEFAULT_TITLE,
  HARDWARE_MAXIMUM_NOT_VERIFIED,
  REGULATORY_ALLOWANCE_NOT_RECORDED,
  buildGlobalPowerView,
  emptyFilter,
  entityId,
  filterItems,
  formatAge,
  formatNumber,
  freshnessOf,
  globalPowerItem,
  groupBySection,
  hex16,
  matchesQuery,
  normalizeConfig,
  registerLabel,
  resolveValue,
} from "../src/model.ts";
import type { Catalogue, CatalogueItem, HassEntityLike, StatesLike } from "../src/types.ts";
import { GP_MOCK_W, NOW, PREFIX, config, entityOf, iso, item, mockStates, withEntity } from "./fixtures.ts";

const CFG = config();

function fresh(state: unknown, ageMs = 5000, attrs: Record<string, unknown> = {}): HassEntityLike {
  const ts = iso(ageMs);
  return { state, attributes: attrs, last_changed: ts, last_updated: ts, last_reported: ts };
}

function value(id: string, states: StatesLike, cfg = CFG, now = NOW) {
  return resolveValue(item(id), states, CATALOGUE, cfg, now);
}

function search(query: string): string[] {
  const f = emptyFilter();
  f.query = query;
  return filterItems(CATALOGUE, f).map((i) => i.id);
}

function cloneCatalogue(): Catalogue {
  return JSON.parse(JSON.stringify(CATALOGUE)) as Catalogue;
}

describe("normalizeConfig", () => {
  it("applies the documented defaults", () => {
    const c = normalizeConfig({ type: "custom:ecco-advanced-config-card" });
    assert.deepEqual(c, {
      title: DEFAULT_TITLE,
      entity_prefix: DEFAULT_ENTITY_PREFIX,
      max_age_telemetry_s: 120,
      max_age_configuration_s: 300,
      max_age_rtc_s: 300,
    });
  });

  it("accepts every documented option and the Lovelace layout keys", () => {
    const c = normalizeConfig({
      type: "custom:ecco-advanced-config-card",
      title: "Advanced",
      entity_prefix: "my_dongle_2",
      max_age_telemetry_s: 60,
      max_age_configuration_s: 600,
      max_age_rtc_s: 900,
      view_layout: { position: "main" },
      grid_options: { columns: 12 },
      visibility: [],
      layout_options: {},
    });
    assert.equal(c.entity_prefix, "my_dongle_2");
    assert.equal(c.max_age_configuration_s, 600);
  });

  it("rejects a configuration that is not a mapping", () => {
    for (const bad of [null, undefined, "x", 42, [], true]) {
      assert.throws(() => normalizeConfig(bad), /must be a mapping/);
    }
  });

  it("rejects unknown options (no hidden write switch can be configured)", () => {
    for (const key of ["allow_writes", "service", "entity", "write", "unlock"]) {
      assert.throws(() => normalizeConfig({ [key]: true }), /unknown option/);
    }
  });

  it("rejects malformed entity prefixes", () => {
    for (const bad of ["", "Ecco", "ecco__dongle", "ecco-dongle", "1ecco", "ecco_", "_ecco", "ecco dongle", "e", 5, null, "sensor.ecco"]) {
      assert.throws(() => normalizeConfig({ entity_prefix: bad }), /entity_prefix/);
    }
  });

  it("rejects out-of-range or non-numeric max ages", () => {
    for (const bad of [4, 86401, -1, Number.NaN, Number.POSITIVE_INFINITY, "120", null]) {
      assert.throws(() => normalizeConfig({ max_age_telemetry_s: bad }), /max_age_telemetry_s/);
      assert.throws(() => normalizeConfig({ max_age_configuration_s: bad }), /max_age_configuration_s/);
      assert.throws(() => normalizeConfig({ max_age_rtc_s: bad }), /max_age_rtc_s/);
    }
  });

  it("rejects an over-long or non-text title", () => {
    assert.throws(() => normalizeConfig({ title: "x".repeat(121) }), /title/);
    assert.throws(() => normalizeConfig({ title: 7 }), /title/);
    assert.equal(normalizeConfig({ title: "x".repeat(120) }).title.length, 120);
  });
});

describe("formatting helpers", () => {
  it("builds entity ids from the configured prefix", () => {
    assert.equal(entityId({ domain: "sensor", object: "ecco_export_limit" }, "ecco_clock_dongle"), "sensor.ecco_clock_dongle_ecco_export_limit");
    assert.equal(entityId({ domain: "binary_sensor", object: "telemetry_online" }, "site_b"), "binary_sensor.site_b_telemetry_online");
  });

  it("formats numbers, ages and 16-bit hex", () => {
    assert.equal(formatNumber(3500), "3500");
    assert.equal(formatNumber(12.3), "12.3");
    assert.equal(formatNumber(0.1 + 0.2), "0.3");
    assert.equal(formatNumber(-1.5), "-1.5");
    assert.equal(formatAge(0), "0 s");
    assert.equal(formatAge(59), "59 s");
    assert.equal(formatAge(600), "10 min");
    assert.equal(formatAge(7200), "2 h");
    assert.equal(formatAge(172800), "2 d");
    assert.equal(formatAge(-5), "0 s");
    assert.equal(hex16(245), "0x00F5");
    assert.equal(hex16(-1), "0xFFFF");
    assert.equal(hex16(65535), "0xFFFF");
  });

  it("labels registers, including multi-register records and records without a register", () => {
    assert.equal(registerLabel(item("export_limit")), "245");
    assert.equal(registerLabel(item("rtc_clock")), "22, 23, 24");
    assert.equal(registerLabel(item("inverter_rated_power")), "no register");
  });
});

describe("freshness", () => {
  const gateOn = (ageMs: number): HassEntityLike => fresh("on", ageMs);

  it("is live only when the entity's own timestamp is within the maximum age", () => {
    assert.equal(freshnessOf(fresh("1", 10_000), 120, undefined, NOW).freshness, "live");
    assert.equal(freshnessOf(fresh("1", 120_000), 120, undefined, NOW).freshness, "live");
    assert.equal(freshnessOf(fresh("1", 121_000), 120, undefined, NOW).freshness, "stale");
  });

  it("uses last_reported, then last_updated, then last_changed", () => {
    const e: HassEntityLike = { state: "1", last_reported: iso(1000), last_updated: iso(999_000), last_changed: iso(999_000) };
    assert.equal(freshnessOf(e, 120, undefined, NOW).freshness, "live");
    const e2: HassEntityLike = { state: "1", last_updated: iso(1000), last_changed: iso(999_000) };
    assert.equal(freshnessOf(e2, 120, undefined, NOW).freshness, "live");
    const e3: HassEntityLike = { state: "1", last_changed: iso(999_000) };
    assert.equal(freshnessOf(e3, 120, undefined, NOW).freshness, "stale");
  });

  it("is unverified without a valid timestamp, never live", () => {
    for (const e of [{ state: "1" }, { state: "1", last_reported: "not a date" }, { state: "1", last_updated: 12345 }, { state: "1", last_changed: "" }]) {
      const f = freshnessOf(e as HassEntityLike, 120, gateOn(1000), NOW);
      assert.equal(f.freshness, "unverified");
      assert.equal(f.age, null);
    }
  });

  it("is unverified for a timestamp in the future beyond the skew tolerance", () => {
    assert.equal(freshnessOf(fresh("1", -120_000), 120, undefined, NOW).freshness, "unverified");
    assert.equal(freshnessOf(fresh("1", -30_000), 120, undefined, NOW).freshness, "live");
  });

  it("reports 'unchanged' only when the block's poll gate is on AND fresh", () => {
    const old = fresh("1", 3_600_000);
    assert.equal(freshnessOf(old, 120, gateOn(10_000), NOW).freshness, "unchanged");
    assert.equal(freshnessOf(old, 120, gateOn(3_600_000), NOW).freshness, "stale");
    assert.equal(freshnessOf(old, 120, fresh("off", 1000), NOW).freshness, "stale");
    assert.equal(freshnessOf(old, 120, fresh("unavailable", 1000), NOW).freshness, "stale");
    assert.equal(freshnessOf(old, 120, { state: "on" }, NOW).freshness, "stale");
    assert.equal(freshnessOf(old, 120, undefined, NOW).freshness, "stale");
  });
});

describe("resolveValue: unknown is never zero", () => {
  const states = mockStates();

  it("an unmapped record says so and has no number", () => {
    const v = value("inverter_rated_power", states);
    assert.equal(v.state, "unmapped");
    assert.equal(v.display, "Not exposed by an ECCO entity");
    assert.equal(v.numeric, null);
    assert.equal(v.freshness, "not_applicable");
  });

  it("a missing entity is 'not found', not zero", () => {
    const v = value("export_limit", withEntity(states, entityOf("export_limit"), undefined));
    assert.equal(v.state, "missing");
    assert.equal(v.display, "Entity not found in Home Assistant");
    assert.equal(v.numeric, null);
    assert.equal(v.freshness, "not_applicable");
    assert.equal(v.raw.kind, "unavailable");
  });

  for (const [state, expected, label] of [
    ["unavailable", "unavailable", "Unavailable"],
    ["unknown", "unknown", "Unknown"],
    ["", "unknown", "Unknown"],
    [null, "unknown", "Unknown"],
    [undefined, "unknown", "Unknown"],
  ] as const) {
    it(`state ${JSON.stringify(state)} shows '${label}' with no number and no live claim`, () => {
      const v = value("export_limit", withEntity(states, entityOf("export_limit"), fresh(state)));
      assert.equal(v.state, expected);
      assert.equal(v.display, label);
      assert.equal(v.numeric, null);
      assert.equal(v.freshness, "not_applicable");
      assert.equal(v.raw.kind, "unavailable");
    });
  }

  it("no item ever displays 0 when its entity is unavailable, unknown or missing", () => {
    for (const st of ["unavailable", "unknown", "", undefined]) {
      const s: StatesLike = {};
      for (const it of CATALOGUE.items) if (it.entity) s[entityId(it.entity, PREFIX)] = st === undefined ? undefined : fresh(st);
      for (const it of CATALOGUE.items) {
        const v = resolveValue(it, s, CATALOGUE, CFG, NOW);
        assert.equal(v.numeric, null, it.id);
        assert.ok(!/^0(\s|$)/.test(v.display), `${it.id}: ${v.display}`);
        assert.notEqual(v.freshness, "live", it.id);
      }
    }
  });

  it("no value is claimed live when every entity is old and both poll gates are off", () => {
    const s = mockStates(PREFIX, 3_600_000);
    s[entityId(CATALOGUE.freshness_gates.telemetry, PREFIX)] = fresh("off");
    s[entityId(CATALOGUE.freshness_gates.configuration, PREFIX)] = fresh("off");
    const live = CATALOGUE.items.filter((it) => resolveValue(it, s, CATALOGUE, CFG, NOW).freshness === "live");
    assert.deepEqual(live.map((i) => i.id), []);
  });

  it("with old entities but fresh, online gates the values are 'unchanged', never 'live'", () => {
    const s = mockStates(PREFIX, 3_600_000);
    s[entityId(CATALOGUE.freshness_gates.telemetry, PREFIX)] = fresh("on");
    s[entityId(CATALOGUE.freshness_gates.configuration, PREFIX)] = fresh("on");
    assert.equal(value("export_limit", s).freshness, "unchanged");
    assert.equal(value("battery_power", s).freshness, "unchanged");
    // The inverter clock has no poll gate: an old reading is stale.
    assert.equal(value("rtc_clock", s).freshness, "stale");
  });
});

describe("resolveValue: unexpected entity values", () => {
  const states = mockStates();
  const eid = entityOf("export_limit");

  for (const bad of ["abc", "NaN", "Infinity", "-Infinity", " ", "12 W", "0x10", "1e400", "1,5", "--1"]) {
    it(`a numeric record with state ${JSON.stringify(bad)} is 'unexpected', never a number`, () => {
      const v = value("export_limit", withEntity(states, eid, fresh(bad, 5000, { unit_of_measurement: "W" })));
      assert.equal(v.state, "unexpected");
      assert.equal(v.display, "Unexpected value");
      assert.equal(v.numeric, null);
      assert.ok(v.problem && v.problem.length > 0);
    });
  }

  it("plain decimal text is accepted, with a sign, a fraction or an exponent", () => {
    for (const [txt, n] of [["3500", 3500], ["+12", 12], ["-0.5", -0.5], [".5", 0.5], ["1e3", 1000], [" 42 ", 42]] as const) {
      const v = value("export_limit", withEntity(states, eid, fresh(txt, 5000, { unit_of_measurement: "W" })));
      assert.equal(v.state, "ok", txt);
      assert.equal(v.numeric, n, txt);
    }
  });

  it("a non-text state (number, object, boolean) is 'unexpected', even a numeric 0", () => {
    for (const bad of [0, 3500, {}, [], true]) {
      const v = value("export_limit", withEntity(states, eid, fresh(bad)));
      assert.equal(v.state, "unexpected", JSON.stringify(bad));
      assert.equal(v.numeric, null);
      assert.notEqual(v.display, "0");
    }
  });

  it("a binary sensor reporting anything but on / off is 'unexpected'", () => {
    const bid = entityOf("tou_generator_charge_enable");
    for (const bad of ["maybe", "1", "true", "ON"]) {
      const v = value("tou_generator_charge_enable", withEntity(states, bid, fresh(bad)));
      assert.equal(v.state, "unexpected", bad);
    }
    assert.equal(value("tou_generator_charge_enable", withEntity(states, bid, fresh("on"))).display, "On");
    assert.equal(value("tou_generator_charge_enable", withEntity(states, bid, fresh("off"))).display, "Off");
  });

  it("an enum text that is not a decoded option is shown as-is but flagged, with no raw value", () => {
    const id = entityOf("battery_control_mode");
    const v = value("battery_control_mode", withEntity(states, id, fresh("Plutonium")));
    assert.equal(v.state, "ok");
    assert.equal(v.display, "Plutonium");
    assert.match(v.problem ?? "", /not one of the decoded options/);
    assert.equal(v.raw.kind, "unavailable");
    // The firmware's own fallback text for an undecoded raw value is not a problem.
    assert.equal(value("battery_control_mode", withEntity(states, id, fresh("Unknown (7)"))).problem, null);
  });

  it("a malformed entity record (no attributes, odd timestamps) does not throw", () => {
    const v = value("export_limit", withEntity(states, eid, { state: "3500" }));
    assert.equal(v.state, "ok");
    assert.equal(v.freshness, "unverified");
    const v2 = value("export_limit", withEntity(states, eid, { state: "3500", attributes: { unit_of_measurement: 5 }, last_reported: {} }));
    assert.equal(v2.display, "3500 W");
    assert.equal(v2.freshness, "unverified");
  });
});

describe("resolveValue: register and raw mapping", () => {
  const states = mockStates();
  const set = (id: string, s: string, unit: string) => value(id, withEntity(states, entityOf(id), fresh(s, 5000, { unit_of_measurement: unit })));

  it("Global Power / Export Limit reads register 245 from its configuration entity", () => {
    const v = value("export_limit", states);
    assert.equal(v.state, "ok");
    assert.equal(v.entityId, "sensor.ecco_clock_dongle_ecco_export_limit");
    assert.equal(v.numeric, GP_MOCK_W);
    assert.equal(v.display, `${GP_MOCK_W} W`);
    assert.equal(v.freshness, "live");
    assert.deepEqual(v.raw, { kind: "derived", value: GP_MOCK_W, hex: hex16(GP_MOCK_W), note: "from the value" });
  });

  it("derives raw words through the firmware's scale, offset and sign", () => {
    assert.deepEqual(set("day_battery_charge", "12.3", "kWh").raw, { kind: "derived", value: 123, hex: "0x007B", note: "as value / 0.1" });
    // (raw - 1000) * 0.1 = 25.0 degrees C  ->  raw 1250
    const t = set("battery_temperature", "25", "°C").raw;
    assert.deepEqual(t.kind === "derived" ? [t.value, t.note] : null, [1250, "as value / 0.1 + 1000 (signed 16-bit)"]);
    const neg = set("battery_power", "-1500", "W").raw;
    assert.deepEqual(neg.kind === "derived" ? [neg.hex, neg.note] : null, ["0xFA24", "from the value (signed 16-bit)"]);
  });

  it("refuses to derive a raw word that is not an exact multiple or is out of range", () => {
    assert.equal(set("day_battery_charge", "12.34", "kWh").raw.kind, "unavailable");
    assert.equal(set("export_limit", "70000", "W").raw.kind, "unavailable");
    assert.equal(set("export_limit", "-1", "W").raw.kind, "unavailable");
    assert.equal(set("export_limit", "-1", "W").state, "ok");
  });

  it("derives enum and HH:MM raw values, and reports raw-word entities", () => {
    const bcm = value("battery_control_mode", withEntity(states, entityOf("battery_control_mode"), fresh("Lithium")));
    assert.deepEqual(bcm.raw.kind === "derived" ? [bcm.raw.value, bcm.raw.hex] : null, [1, "0x0001"]);
    const t = value("tou_slot_1_start_time", withEntity(states, entityOf("tou_slot_1_start_time"), fresh("05:30")));
    assert.equal(t.raw.kind === "derived" ? t.raw.value : null, 530);
    assert.equal(value("tou_slot_1_start_time", withEntity(states, entityOf("tou_slot_1_start_time"), fresh("5.30"))).raw.kind, "unavailable");
    const it = item("tou_slot_1_mode");
    assert.ok(it.raw_entity);
    const rawId = entityId(it.raw_entity!, PREFIX);
    const r = value("tou_slot_1_mode", withEntity(states, rawId, fresh("5")));
    assert.deepEqual(r.raw, { kind: "reported", value: 5, hex: "0x0005", note: "by the controller's raw-word entity" });
    for (const bad of ["unavailable", "70000", "-1", "1.5", "x", "0x05", ""]) {
      assert.equal(value("tou_slot_1_mode", withEntity(states, rawId, fresh(bad))).raw.kind, "unavailable", bad);
    }
    assert.equal(value("tou_slot_1_mode", withEntity(states, rawId, undefined)).raw.kind, "unavailable");
  });

  it("never derives a full raw word from a partial-bit or derived decode", () => {
    assert.equal(value("tou_generator_charge_enable", states).raw.kind, "unavailable");
    assert.equal(value("rtc_clock", states).raw.kind, "unavailable");
  });

  it("uses the configured entity prefix", () => {
    const s = mockStates("site_b");
    const v = resolveValue(item("export_limit"), s, CATALOGUE, config({ entity_prefix: "site_b" }), NOW);
    assert.equal(v.entityId, "sensor.site_b_ecco_export_limit");
    assert.equal(v.numeric, GP_MOCK_W);
    // the default prefix finds nothing in a differently-named installation
    assert.equal(value("export_limit", s).state, "missing");
  });

  it("applies the per-block maximum ages", () => {
    const s = mockStates(PREFIX, 200_000);
    s[entityId(CATALOGUE.freshness_gates.telemetry, PREFIX)] = fresh("off");
    s[entityId(CATALOGUE.freshness_gates.configuration, PREFIX)] = fresh("off");
    assert.equal(value("battery_power", s).freshness, "stale"); // telemetry: 120 s
    assert.equal(value("export_limit", s).freshness, "live"); // configuration: 300 s
    assert.equal(value("rtc_clock", s).freshness, "live"); // rtc: 300 s
    assert.equal(value("rtc_clock", s, config({ max_age_rtc_s: 60 })).freshness, "stale");
  });
});

describe("search and filters", () => {
  it("a register number matches that register exactly", () => {
    const hits = search("245");
    assert.ok(hits.includes("export_limit"));
    for (const id of hits) assert.ok(item(id).registers.some((r) => r.address === 245), id);
    assert.deepEqual(search("r245"), hits);
    assert.deepEqual(search("reg245"), hits);
    assert.deepEqual(search("register245"), hits);
    assert.deepEqual(search("R245"), hits);
    // exact, not prefix: 24 is one of the clock's registers, not 245
    assert.ok(!search("24").includes("export_limit"));
    assert.ok(search("24").includes("rtc_clock"));
  });

  it("text matches name, explanation, description and entity, case-insensitively", () => {
    assert.ok(search("export limit").includes("export_limit"));
    assert.ok(search("EXPORT LIMIT").includes("export_limit"));
    assert.ok(search("global power").includes("export_limit"));
    assert.ok(search("ecco_cfg_export_limit").includes("export_limit"));
    assert.ok(search("configured export power").includes("export_limit"));
    assert.deepEqual(search("zzqqxx-no-such-setting"), []);
    assert.equal(search("   ").length, CATALOGUE.items.length);
  });

  it("every token must match", () => {
    assert.ok(search("export 245").includes("export_limit"));
    assert.deepEqual(search("export 9999"), []);
  });

  it("matchesQuery is total over hostile input", () => {
    for (const q of ["<script>", "\u0000", "(((", "[a-", ".*", "\\", "%", "𝔘𝔫", "\ud800"]) {
      assert.doesNotThrow(() => CATALOGUE.items.forEach((i) => matchesQuery(i, "x", q)));
    }
  });

  it("filters by status, evidence and category, combined with AND", () => {
    const f = emptyFilter();
    assert.equal(filterItems(CATALOGUE, f).length, 165);
    f.statuses.add("LOCKED");
    const locked = filterItems(CATALOGUE, f);
    assert.equal(locked.length, 16);
    assert.ok(locked.every((i) => i.status === "LOCKED"));
    f.statuses.add("UNSUPPORTED");
    assert.equal(filterItems(CATALOGUE, f).length, 16 + 7);
    const g = emptyFilter();
    g.evidence.add("MX");
    assert.equal(filterItems(CATALOGUE, g).length, 7);
    g.sections.add("experimental");
    assert.equal(filterItems(CATALOGUE, g).length, 7);
    g.sections.clear();
    g.sections.add("inverter_power");
    assert.deepEqual(filterItems(CATALOGUE, g), []);
    const h = emptyFilter();
    h.sections.add("inverter_power");
    h.query = "245";
    assert.deepEqual(filterItems(CATALOGUE, h).map((i) => i.id), ["export_limit"]);
  });

  it("groups by section in catalogue order and loses nothing", () => {
    const groups = groupBySection(CATALOGUE, CATALOGUE.items);
    assert.deepEqual(groups.map((g) => g.id), CATALOGUE.sections.map((s) => s.id));
    assert.equal(groups.reduce((n, g) => n + g.items.length, 0), CATALOGUE.items.length);
  });
});

describe("Global Power / Export Limit (register 245)", () => {
  const states = mockStates();

  it("is the single catalogue record on register 245", () => {
    const gp = globalPowerItem(CATALOGUE);
    assert.equal(gp.id, "export_limit");
    assert.equal(CATALOGUE.global_power.register, 245);
    assert.deepEqual(gp.registers, [{ address: 245, bits: null }]);
    assert.equal(gp.unit, "W");
  });

  it("shows the value, raw word, unit, freshness, source entity, evidence and read-only status", () => {
    const v = buildGlobalPowerView(CATALOGUE, states, CFG, NOW);
    assert.equal(v.title, "Global Power / Export Limit");
    assert.equal(v.register, 245);
    assert.equal(v.unit, "W");
    assert.equal(v.value.numeric, GP_MOCK_W);
    assert.equal(v.value.raw.kind, "derived");
    assert.equal(v.value.freshness, "live");
    assert.equal(v.sourceEntityId, "sensor.ecco_clock_dongle_ecco_export_limit");
    assert.match(v.evidence, /M2 read-proven/);
    assert.match(v.evidence, /owner-confirmed 2026-10-08/);
    assert.equal(v.status, "READ_ONLY");
    assert.match(v.readOnlyText, /^Read only\./);
    assert.ok(v.blockers.length >= 4);
    assert.ok(v.limitations.length >= 3);
  });

  it("says 'Hardware maximum not verified' and never defaults a maximum", () => {
    const v = buildGlobalPowerView(CATALOGUE, states, CFG, NOW);
    assert.equal(v.hardwareMaximumText, HARDWARE_MAXIMUM_NOT_VERIFIED);
    assert.equal(v.hardwareMaximumText, "Hardware maximum not verified");
    assert.equal(v.regulatoryText, REGULATORY_ALLOWANCE_NOT_RECORDED);
    assert.match(v.permittedRangeText, /^Unavailable: hardware maximum not verified$/);
    assert.equal(CATALOGUE.global_power.hardware_maximum_w, null);
    assert.equal(CATALOGUE.global_power.hardware_maximum_evidence, null);
    const text = JSON.stringify(v);
    assert.ok(!text.includes("8000"), "no 8000 W default anywhere in the Global Power view");
  });

  it("a maximum without recorded evidence is still 'not verified'", () => {
    const c = cloneCatalogue();
    c.global_power.hardware_maximum_w = 9000;
    c.global_power.hardware_maximum_evidence = null;
    const v = buildGlobalPowerView(c, states, CFG, NOW);
    assert.equal(v.hardwareMaximumText, HARDWARE_MAXIMUM_NOT_VERIFIED);
    assert.match(v.permittedRangeText, /^Unavailable/);
  });

  it("designs every future control, and every one is disabled - even with a verified maximum", () => {
    const verified = cloneCatalogue();
    verified.global_power.hardware_maximum_w = 9000;
    verified.global_power.hardware_maximum_evidence = "synthetic test evidence";
    verified.global_power.regulatory_allowance_w = 3680;
    for (const cat of [CATALOGUE, verified]) {
      const v = buildGlobalPowerView(cat, states, CFG, NOW);
      assert.deepEqual(v.controls.map((c) => c.key), ["unlock", "staged_value", "permitted_range", "apply", "verification", "previous_value", "history"]);
      assert.deepEqual(v.controls.map((c) => c.label), ["Unlock", "Staged value", "Permitted technical range", "Apply", "Verification status", "Previous value", "History"]);
      for (const c of v.controls) {
        assert.equal(c.enabled, false, c.key);
        assert.match(c.reason, /^Disabled:/);
        assert.ok(c.description.length > 10);
      }
    }
    const v = buildGlobalPowerView(verified, states, CFG, NOW);
    assert.equal(v.hardwareMaximumText, "9000 W (verified: synthetic test evidence)");
    assert.match(v.permittedRangeText, /9000 W technical maximum, and at most 3680 W by the regulatory allowance/);
  });

  it("an unavailable Global Power entity is shown as unavailable, never 0 W", () => {
    for (const st of ["unavailable", "unknown"]) {
      const v = buildGlobalPowerView(CATALOGUE, withEntity(states, entityOf("export_limit"), fresh(st)), CFG, NOW);
      assert.equal(v.value.numeric, null);
      assert.ok(!v.value.display.startsWith("0"));
    }
    const missing = buildGlobalPowerView(CATALOGUE, {}, CFG, NOW);
    assert.equal(missing.value.display, "Entity not found in Home Assistant");
    assert.equal(missing.value.freshness, "not_applicable");
  });

  it("refuses a catalogue whose Global Power record is missing, duplicated or not register 245", () => {
    const missing = cloneCatalogue();
    missing.items = missing.items.filter((i) => i.id !== "export_limit");
    assert.throws(() => globalPowerItem(missing), /exactly once/);
    const dup = cloneCatalogue();
    dup.items.push(JSON.parse(JSON.stringify(item("export_limit"))) as CatalogueItem);
    assert.throws(() => globalPowerItem(dup), /exactly once/);
    const moved = cloneCatalogue();
    const m = moved.items.find((i) => i.id === "export_limit")!;
    m.registers = [{ address: 244, bits: null }];
    assert.throws(() => globalPowerItem(moved), /not register 245/);
    assert.throws(() => buildGlobalPowerView(moved, states, CFG, NOW), /not register 245/);
  });
});
