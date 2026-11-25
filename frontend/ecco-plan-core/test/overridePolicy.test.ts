import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  EXPIRY_CEILING_MIN,
  HELPER_BOUNDS,
  LIMITS,
  OVERRIDE_KINDS,
  ORDINARY_DAY,
  PROPOSED_DEFAULTS,
  applyOverrides,
  expiryChoices,
  formatDurationMin,
  overridePolicyAt,
  proposedOverrideConfig,
  startConfiguredOverride,
  untilLocalTime,
  validateOverrideConfig,
} from "../src/index.ts";
import type { ClockContext, OverrideConfig, OverrideConfigRaw, OverrideConfigResult, OverrideKind, PlanView } from "../src/index.ts";
import { rng } from "./fixtures.ts";

const SPRING = { changeAtMin: 120, deltaMin: 60 } as const;
const AUTUMN = { changeAtMin: 120, deltaMin: -60 } as const;
const at = (h: number, m: number, day: ClockContext["day"] = ORDINARY_DAY): ClockContext => ({ nowWallMin: h * 60 + m, day });

/** The proposed values, confirmed: what an owner who accepted every proposal would have set. */
const PROPOSED_CONFIRMED: OverrideConfigRaw = { ...proposedOverrideConfig(), confirmed: true };

function good(raw: OverrideConfigRaw = PROPOSED_CONFIRMED, currentReservePct: number | null = 50): OverrideConfig {
  const r = validateOverrideConfig(raw, { currentReservePct });
  assert.equal(r.ok, true, JSON.stringify(r));
  return (r as { ok: true; config: OverrideConfig }).config;
}

const KEY_BOUND: Record<string, keyof typeof HELPER_BOUNDS> = {
  minExpiryMin: "min_expiry",
  holdDefaultMin: "hold_default",
  holdCapMin: "hold_cap",
  skipUntilMin: "skip_until",
  skipCapMin: "skip_cap",
  cutDefaultMin: "cut_default",
  cutCapMin: "cut_cap",
  cutReservePct: "cut_reserve",
};

// ---- the proposed defaults -----------------------------------------------------------------------------------------------------

test("proposed defaults: one reason per value, all eight present once, and they validate once the owner confirms them", () => {
  assert.deepEqual(PROPOSED_DEFAULTS.map((p) => p.key).sort(), Object.keys(KEY_BOUND).sort());
  for (const p of PROPOSED_DEFAULTS) {
    assert.ok(p.why.length > 20 && p.why.length < 140 && /^[\x20-\x7e]+$/.test(p.why), p.key + " has a short ASCII rationale");
  }
  const cfg = good();
  assert.deepEqual([cfg.minExpiryMin, cfg.holdDefaultMin, cfg.holdCapMin, cfg.skipUntilMin, cfg.skipCapMin, cfg.cutDefaultMin, cfg.cutCapMin, cfg.cutReservePct], [15, 240, 1440, 420, 1440, 1440, 4320, 80]);
  assert.ok(Object.isFrozen(cfg));
});

test("the proposed defaults are never adopted: as shown (unconfirmed) they validate to nothing, and nothing starts", () => {
  const shown = proposedOverrideConfig();
  assert.equal(shown.confirmed, false);
  const r = validateOverrideConfig(shown, { currentReservePct: 40 });
  assert.equal(r.ok, false);
  assert.equal("config" in r, false);
  assert.match((r as { reasons: string[] }).reasons.join(" "), /not confirmed/);
  for (const k of OVERRIDE_KINDS) assert.equal(startConfiguredOverride(k, 1000, null, r, { clock: at(19, 0), currentReservePct: 40 }).ok, false);
  // The proposal is data only: mutating the copy it returns never changes the next one.
  (shown as Record<string, unknown>).holdCapMin = 1;
  assert.equal(proposedOverrideConfig().holdCapMin, 1440);
  assert.ok(Object.isFrozen(PROPOSED_DEFAULTS));
});

// ---- fail closed ------------------------------------------------------------------------------------------------------------------

test("fail closed: missing, empty or malformed configuration gives reasons and no configuration, and every start is refused", () => {
  const bads: unknown[] = [undefined, null, {}, [], "x", 5, true, { confirmed: true }, { ...PROPOSED_CONFIRMED, holdCapMin: undefined }, { ...PROPOSED_CONFIRMED, confirmed: "on" }, { ...PROPOSED_CONFIRMED, confirmed: 1 }, { ...PROPOSED_CONFIRMED, confirmed: null }];
  for (const raw of bads) {
    const r = validateOverrideConfig(raw as OverrideConfigRaw, { currentReservePct: 50 });
    assert.equal(r.ok, false, JSON.stringify(raw));
    assert.equal("config" in r, false);
    assert.ok((r as { reasons: string[] }).reasons.length > 0);
    for (const k of OVERRIDE_KINDS) {
      for (const e of [null, undefined, 60, 240]) {
        const s = startConfiguredOverride(k, 1000, e, r, { clock: at(19, 0), currentReservePct: 50 });
        assert.equal(s.ok, false);
        assert.match((s as { error: string }).error, /no override can be started/);
      }
    }
  }
  for (const k of OVERRIDE_KINDS) assert.equal(startConfiguredOverride(k, 1000, 60, undefined, { clock: null, currentReservePct: 50 }).ok, false);
  assert.equal(startConfiguredOverride("hold_battery", 1000, 60, null, { clock: null, currentReservePct: 50 }).ok, false);
});

test("every problem is reported, not only the first", () => {
  const r = validateOverrideConfig({ ...PROPOSED_CONFIRMED, confirmed: false, holdCapMin: NaN, skipCapMin: "x", cutReservePct: 5 }, { currentReservePct: 50 });
  assert.equal(r.ok, false);
  const text = (r as { reasons: string[] }).reasons.join(" | ");
  for (const needle of [/not confirmed/, /Hold battery maximum/, /Skip tonight maximum/, /Power-cut reserve/]) assert.match(text, needle);
});

// ---- bounds ---------------------------------------------------------------------------------------------------------------------

// Neighbouring values that keep the ordering rules satisfied when a field sits at its own minimum or maximum.
const RELAX_AT_MIN: Record<string, Record<string, number>> = {
  minExpiryMin: {},
  holdDefaultMin: { minExpiryMin: 5 },
  holdCapMin: { minExpiryMin: 5, holdDefaultMin: 5 },
  skipUntilMin: {},
  skipCapMin: { minExpiryMin: 5 },
  cutDefaultMin: { minExpiryMin: 5 },
  cutCapMin: { minExpiryMin: 5, cutDefaultMin: 5 },
  cutReservePct: {},
};
const RELAX_AT_MAX: Record<string, Record<string, number>> = { holdDefaultMin: { holdCapMin: 4320 }, cutDefaultMin: { cutCapMin: 10080 } };

test("each value: its bounds and step are enforced exactly (min and max pass, one step beyond and off-step fail)", () => {
  for (const [key, bound] of Object.entries(KEY_BOUND)) {
    const b = HELPER_BOUNDS[bound];
    const run = (v: unknown, relax: Record<string, number> = {}) => validateOverrideConfig({ ...PROPOSED_CONFIRMED, ...relax, [key]: v } as OverrideConfigRaw, { currentReservePct: 10 });
    assert.equal(run(b.min, RELAX_AT_MIN[key]).ok, true, key + " at its minimum");
    assert.equal(run(b.max, RELAX_AT_MAX[key]).ok, true, key + " at its maximum");
    for (const [name, v] of [["below min", b.min - b.step], ["above max", b.max + b.step], ["far above", b.max * 10 + 7]] as const) {
      const r = run(v, { ...RELAX_AT_MIN[key], ...RELAX_AT_MAX[key] });
      assert.equal(r.ok, false, key + " " + name);
    }
    if (b.step > 1) assert.equal(run(b.min + 1, RELAX_AT_MIN[key]).ok, false, key + " off its step");
    for (const junk of [NaN, Infinity, -Infinity, "60", null, undefined, true, {}, b.min + 0.5]) {
      const r = run(junk, { ...RELAX_AT_MIN[key], ...RELAX_AT_MAX[key] });
      assert.equal(r.ok, false, key + " junk " + String(junk));
    }
  }
});

test("hard ceilings: no value lifts a cap above the ceiling, whatever the helper holds", () => {
  assert.deepEqual({ ...EXPIRY_CEILING_MIN }, { hold_battery: 72 * 60, skip_tonight: 36 * 60, prepare_power_cut: 7 * 1440 });
  assert.ok(Object.isFrozen(EXPIRY_CEILING_MIN));
  for (const [key, kind] of [["holdCapMin", "hold_battery"], ["skipCapMin", "skip_tonight"], ["cutCapMin", "prepare_power_cut"]] as const) {
    const ceiling = EXPIRY_CEILING_MIN[kind];
    assert.equal(validateOverrideConfig({ ...PROPOSED_CONFIRMED, [key]: ceiling } as OverrideConfigRaw, { currentReservePct: 50 }).ok, true, key + " at the ceiling");
    for (const over of [ceiling + 5, ceiling + 1, ceiling * 2, 1e9, Number.MAX_SAFE_INTEGER, Infinity]) {
      assert.equal(validateOverrideConfig({ ...PROPOSED_CONFIRMED, [key]: over } as OverrideConfigRaw, { currentReservePct: 50 }).ok, false, key + " " + over);
    }
  }
  // The defaults share the ceilings, so even a default cannot exceed them.
  assert.equal(HELPER_BOUNDS.hold_default.max, HELPER_BOUNDS.hold_cap.max);
  assert.equal(HELPER_BOUNDS.cut_default.max, HELPER_BOUNDS.cut_cap.max);
  assert.ok(HELPER_BOUNDS.min_expiry.min > 0, "a zero or negative minimum is impossible");
});

test("ordering: the default sits between the minimum and the maximum; a maximum never undercuts the minimum", () => {
  const bad = (patch: Partial<Record<keyof OverrideConfigRaw, unknown>>) => validateOverrideConfig({ ...PROPOSED_CONFIRMED, ...patch } as OverrideConfigRaw, { currentReservePct: 50 }).ok;
  assert.equal(bad({}), true);
  assert.equal(bad({ holdDefaultMin: 10 }), false, "default below the minimum (15)");
  assert.equal(bad({ holdDefaultMin: 1500 }), false, "default above the maximum (1440)");
  assert.equal(bad({ cutDefaultMin: 4325 }), false);
  assert.equal(bad({ holdCapMin: 10 }), false, "cap below the minimum");
  assert.equal(bad({ skipCapMin: 10 }), false);
  assert.equal(bad({ cutCapMin: 10, cutDefaultMin: 10 }), false);
  assert.equal(bad({ holdDefaultMin: 15, holdCapMin: 15 }), true, "default equal to the minimum and the cap is allowed");
});

test("Skip tonight may not end in the clock-change hours (00:00 to 03:00)", () => {
  const ok = (m: number) => validateOverrideConfig({ ...PROPOSED_CONFIRMED, skipUntilMin: m } as OverrideConfigRaw, { currentReservePct: 50 }).ok;
  for (const m of [0, 60, 120, 175]) assert.equal(ok(m), false, "minute " + m);
  assert.equal(ok(180), true);
  assert.equal(ok(1435), true);
  assert.equal(ok(1440), false);
  assert.equal(ok(421), false, "off the 5-minute grid");
});

// ---- power-cut reserve ---------------------------------------------------------------------------------------------------------

test("power-cut reserve: inside the reserve limits and never below the current reserve; unknown is reported, not assumed", () => {
  assert.equal(LIMITS.reserveMin, HELPER_BOUNDS.cut_reserve.min);
  assert.equal(LIMITS.reserveMax, HELPER_BOUNDS.cut_reserve.max);
  const v = (r: unknown, cur: number | null) => validateOverrideConfig({ ...PROPOSED_CONFIRMED, cutReservePct: r } as OverrideConfigRaw, { currentReservePct: cur });
  assert.equal(v(9, 10).ok, false);
  assert.equal(v(101, 10).ok, false);
  assert.equal(v(80.5, 10).ok, false);
  assert.match((v(80.5, 10) as { reasons: string[] }).reasons.join(" "), /whole number/, "a fractional value is called what it is");
  assert.equal(v(80, 80).ok, true, "equal to the current reserve is allowed (raise-only)");
  assert.equal(v(80, 81).ok, false, "below the current reserve");
  assert.equal(v(80, 100).ok, false);
  const unknown = v(80, null);
  assert.ok(unknown.ok && unknown.warnings.length === 1 && /not known/.test(unknown.warnings[0] as string));
  const none = validateOverrideConfig(PROPOSED_CONFIRMED);
  assert.ok(none.ok && none.warnings.length === 1);
  const cfg = good();
  const ctx = { clock: at(12, 0), currentReservePct: null };
  const s = startConfiguredOverride("prepare_power_cut", 5000, 60, { ok: true, config: cfg, warnings: [] }, ctx);
  assert.equal(s.ok, false, "starting a power-cut override needs the current reserve");
  assert.match((s as { error: string }).error, /not known/);
  const lower = startConfiguredOverride("prepare_power_cut", 5000, 60, { ok: true, config: cfg, warnings: [] }, { ...ctx, currentReservePct: 90 });
  assert.equal(lower.ok, false);
  assert.match((lower as { error: string }).error, /never lowers/);
  const up = startConfiguredOverride("prepare_power_cut", 5000, 60, { ok: true, config: cfg, warnings: [] }, { ...ctx, currentReservePct: 80 });
  assert.ok(up.ok && up.override.reservePct === 80);
  // The other two overrides do not need the reserve.
  assert.equal(startConfiguredOverride("hold_battery", 5000, 60, { ok: true, config: cfg, warnings: [] }, ctx).ok, true);
});

// ---- local-time expiry, clock changes ------------------------------------------------------------------------------------------

test("until local time: the next occurrence, strictly later; spring days are an hour shorter, autumn days an hour longer", () => {
  const u = (now: number, target: number, day: ClockContext["day"]) => {
    const r = untilLocalTime(now, target, day);
    assert.ok(r.ok, JSON.stringify(r));
    return r.ok ? r.expiryMin : NaN;
  };
  assert.equal(u(22 * 60, 420, ORDINARY_DAY), 540);
  assert.equal(u(420, 420, ORDINARY_DAY), 1440, "the same minute means tomorrow");
  assert.equal(u(425, 420, ORDINARY_DAY), 1435);
  assert.equal(u(415, 420, ORDINARY_DAY), 5);
  assert.equal(u(22 * 60, 420, SPRING), 480, "the wall clock skips an hour");
  assert.equal(u(22 * 60, 420, AUTUMN), 600, "the wall clock repeats an hour");
  assert.equal(u(425, 420, AUTUMN), 1495, "a full day to the next morning on a 25-hour day");
  assert.equal(u(425, 420, SPRING), 1375);
  assert.equal(u(200, 420, SPRING), 220, "after the change nothing is adjusted");
  assert.equal(u(200, 420, AUTUMN), 220);
  for (const bad of [[NaN, 420], [-1, 420], [1440, 420], [100.5, 420], [100, NaN], [100, 1440], [100, -5]] as const) assert.equal(untilLocalTime(bad[0], bad[1], ORDINARY_DAY).ok, false);
  assert.equal(untilLocalTime(100, 200, { changeAtMin: 120, deltaMin: 90 } as never).ok, false);
  assert.equal(untilLocalTime(100, 200, undefined as never).ok, false);
});

test("Skip tonight's default is 'until the end time' for the real clock, and is refused when it would exceed the cap", () => {
  const ok = { ok: true as const, config: good(), warnings: [] };
  const ctx = (clock: ClockContext | null) => ({ clock, currentReservePct: 50 });
  const normal = startConfiguredOverride("skip_tonight", 10_000, null, ok, ctx(at(19, 30)));
  assert.ok(normal.ok && normal.override.expiresAtMin - normal.override.startedAtMin === 690);
  const spring = startConfiguredOverride("skip_tonight", 10_000, null, ok, ctx(at(19, 30, SPRING)));
  assert.ok(spring.ok && spring.override.expiresAtMin - spring.override.startedAtMin === 630);
  const autumn = startConfiguredOverride("skip_tonight", 10_000, null, ok, ctx(at(19, 30, AUTUMN)));
  assert.ok(autumn.ok && autumn.override.expiresAtMin - autumn.override.startedAtMin === 750);
  const tooLong = startConfiguredOverride("skip_tonight", 10_000, null, ok, ctx(at(7, 5, AUTUMN)));
  assert.equal(tooLong.ok, false, "1495 minutes is above the 1440 cap");
  assert.match((tooLong as { error: string }).error, /at most 1440/);
  const tooShort = startConfiguredOverride("skip_tonight", 10_000, null, ok, ctx(at(6, 50)));
  assert.equal(tooShort.ok, false, "10 minutes is below the 15 minute minimum");
  assert.equal(startConfiguredOverride("skip_tonight", 10_000, null, ok, ctx(null)).ok, false, "no clock, no default");
  assert.equal(startConfiguredOverride("skip_tonight", 10_000, 300, ok, ctx(null)).ok, true, "an explicit expiry does not need the clock");
});

// ---- expiry choices ------------------------------------------------------------------------------------------------------------------

test("expiry choices: every chip is within [minimum, cap], sorted, unique; the default is marked; 'until' appears only in bounds", () => {
  const cfg = good();
  for (const kind of OVERRIDE_KINDS) {
    const cap = kind === "hold_battery" ? cfg.holdCapMin : kind === "skip_tonight" ? cfg.skipCapMin : cfg.cutCapMin;
    const list = expiryChoices(kind, cfg, at(19, 30));
    assert.ok(list.length >= 3, kind);
    assert.equal(new Set(list.map((c) => c.id)).size, list.length);
    for (const c of list) assert.ok(c.expiryMin >= cfg.minExpiryMin && c.expiryMin <= cap && Number.isInteger(c.expiryMin), kind + " " + c.id);
    assert.deepEqual(list.map((c) => c.expiryMin), [...list.map((c) => c.expiryMin)].sort((a, b) => a - b));
    assert.ok(list.some((c) => c.expiryMin === cap), "the cap itself is selectable");
    assert.equal(list.filter((c) => c.isDefault).length, 1, kind + " has exactly one default");
  }
  const hold = expiryChoices("hold_battery", cfg, at(19, 30));
  assert.equal(hold.find((c) => c.isDefault)?.expiryMin, 240);
  assert.equal(hold.find((c) => c.id === "until")?.label, "until 07:00");
  assert.equal(hold.find((c) => c.id === "until")?.expiryMin, 690);
  const skip = expiryChoices("skip_tonight", cfg, at(19, 30));
  assert.equal(skip.find((c) => c.isDefault)?.id, "until");
  assert.equal(skip.find((c) => c.isDefault)?.expiryMin, 690);
  assert.equal(expiryChoices("prepare_power_cut", cfg, at(19, 30)).some((c) => c.id === "until"), false);
  assert.equal(expiryChoices("hold_battery", cfg, at(6, 50)).some((c) => c.id === "until"), false, "below the minimum");
  assert.equal(expiryChoices("skip_tonight", cfg, at(6, 50)).some((c) => c.isDefault), false, "no default when until is out of bounds");
  assert.equal(expiryChoices("skip_tonight", cfg, at(7, 5, AUTUMN)).some((c) => c.id === "until"), false, "above the cap");
  assert.equal(expiryChoices("hold_battery", cfg, null).some((c) => c.id === "until"), false, "no clock, no until");
  assert.equal(expiryChoices("hold_battery", cfg, at(22, 0, SPRING)).find((c) => c.id === "until")?.expiryMin, 480);
  // A smaller cap removes the chips above it.
  const small = good({ ...PROPOSED_CONFIRMED, holdCapMin: 480 });
  assert.ok(expiryChoices("hold_battery", small, at(19, 30)).every((c) => c.expiryMin <= 480));
});

test("formatDurationMin", () => {
  assert.deepEqual([30, 60, 90, 240, 1440, 1500, 2880, 4320, 10080].map(formatDurationMin), ["30 min", "1 h", "1 h 30 min", "4 h", "1 day", "1 day 1 h", "2 days", "3 days", "7 days"]);
  for (const bad of [-1, NaN, Infinity, "5" as never]) assert.equal(formatDurationMin(bad), "unknown");
});

// ---- starting under the policy -----------------------------------------------------------------------------------------------------

test("starting: defaults, explicit expiries, and every refusal", () => {
  const ok = { ok: true as const, config: good(), warnings: [] };
  const ctx = { clock: at(19, 30), currentReservePct: 40 };
  const def = startConfiguredOverride("hold_battery", 10_000, null, ok, ctx);
  assert.ok(def.ok && def.override.expiresAtMin === 10_240);
  const cut = startConfiguredOverride("prepare_power_cut", 10_000, undefined, ok, ctx);
  assert.ok(cut.ok && cut.override.expiresAtMin === 11_440 && cut.override.reservePct === 80);
  assert.equal(startConfiguredOverride("hold_battery", 10_000, 1440, ok, ctx).ok, true);
  assert.equal(startConfiguredOverride("hold_battery", 10_000, 1441, ok, ctx).ok, false);
  assert.equal(startConfiguredOverride("hold_battery", 10_000, 14, ok, ctx).ok, false);
  assert.equal(startConfiguredOverride("hold_battery", 10_000, 15, ok, ctx).ok, true);
  assert.equal(startConfiguredOverride("prepare_power_cut", 10_000, 4320, ok, ctx).ok, true);
  assert.equal(startConfiguredOverride("prepare_power_cut", 10_000, 4321, ok, ctx).ok, false);
  for (const bad of [NaN, Infinity, -Infinity, -1, 0, 30.5, "60", {}, true]) assert.equal(startConfiguredOverride("hold_battery", 10_000, bad as never, ok, ctx).ok, false, String(bad));
  assert.equal(startConfiguredOverride("nonsense" as OverrideKind, 10_000, 60, ok, ctx).ok, false);
  assert.equal(startConfiguredOverride("hold_battery", NaN, 60, ok, ctx).ok, false);
  assert.equal(startConfiguredOverride("hold_battery", Infinity, 60, ok, ctx).ok, false);
});

test("the policy built for a moment is exactly the validated numbers", () => {
  const cfg = good();
  const p = overridePolicyAt(cfg, at(19, 30));
  assert.deepEqual(p.defaultExpiryMin, { hold_battery: 240, skip_tonight: 690, prepare_power_cut: 1440 });
  assert.deepEqual(p.maxExpiryMin, { hold_battery: 1440, skip_tonight: 1440, prepare_power_cut: 4320 });
  assert.equal(p.minExpiryMin, 15);
  assert.equal(p.powerCutReservePct, 80);
  assert.ok(Number.isNaN(overridePolicyAt(cfg, null).defaultExpiryMin.skip_tonight));
});

// ---- properties (seeded) ---------------------------------------------------------------------------------------------------------------

const KEYS = Object.keys(KEY_BOUND);

function randomRaw(rand: () => number): OverrideConfigRaw {
  const raw: Record<string, unknown> = { ...PROPOSED_CONFIRMED };
  const junk = [NaN, Infinity, -Infinity, -1, 0, 1, 7, 61, 4321, 10081, 1e9, 2 ** 53, "60", "", null, undefined, true, false, {}, [], 12.5];
  const touched = [0, 0, 1, 1, 1, 2, 3][Math.floor(rand() * 7)] as number;
  for (let t = 0; t < touched; t++) {
    const key = KEYS[Math.floor(rand() * KEYS.length)] as string;
    const roll = rand();
    const b = HELPER_BOUNDS[KEY_BOUND[key] as keyof typeof HELPER_BOUNDS];
    if (roll < 0.55) raw[key] = b.min + b.step * Math.floor(rand() * (Math.floor((b.max - b.min) / b.step) + 1));
    else if (roll < 0.75) raw[key] = rand() < 0.5 ? b.min : b.max;
    else raw[key] = junk[Math.floor(rand() * junk.length)];
  }
  if (rand() < 0.05) raw.confirmed = junk[Math.floor(rand() * junk.length)];
  return raw as OverrideConfigRaw;
}

test("property: an invalid configuration never yields a policy; a valid one only yields in-bounds, below-ceiling numbers", () => {
  const rand = rng(31337);
  let valid = 0;
  let invalid = 0;
  for (let n = 0; n < 6000; n++) {
    const raw = randomRaw(rand);
    const cur = rand() < 0.2 ? null : 10 + Math.floor(rand() * 91);
    const r = validateOverrideConfig(raw, { currentReservePct: cur });
    if (!r.ok) {
      invalid++;
      assert.equal("config" in r, false);
      assert.ok(r.reasons.length > 0 && r.reasons.every((x) => typeof x === "string" && x.length > 0));
      for (const k of OVERRIDE_KINDS) assert.equal(startConfiguredOverride(k, 5000, rand() < 0.5 ? null : 60, r, { clock: at(19, 0), currentReservePct: cur }).ok, false);
      continue;
    }
    valid++;
    const c = r.config;
    assert.equal(raw.confirmed, true);
    for (const v of Object.values(c)) assert.ok(Number.isInteger(v) && Number.isFinite(v));
    assert.ok(c.minExpiryMin > 0 && c.minExpiryMin <= 60);
    assert.ok(c.holdCapMin <= EXPIRY_CEILING_MIN.hold_battery && c.skipCapMin <= EXPIRY_CEILING_MIN.skip_tonight && c.cutCapMin <= EXPIRY_CEILING_MIN.prepare_power_cut);
    assert.ok(c.holdDefaultMin >= c.minExpiryMin && c.holdDefaultMin <= c.holdCapMin);
    assert.ok(c.cutDefaultMin >= c.minExpiryMin && c.cutDefaultMin <= c.cutCapMin);
    assert.ok(c.skipCapMin >= c.minExpiryMin);
    assert.ok(c.cutReservePct >= LIMITS.reserveMin && c.cutReservePct <= LIMITS.reserveMax);
    if (cur !== null) assert.ok(c.cutReservePct >= cur);
    assert.ok(c.skipUntilMin >= 180 && c.skipUntilMin < 1440 && c.skipUntilMin % 5 === 0);
  }
  assert.ok(valid > 300 && invalid > 300, "both sides exercised: " + valid + " valid, " + invalid + " invalid");
});

test("property: no request yields an open-ended, over-ceiling or lowered-reserve override", () => {
  const rand = rng(8675309);
  const expiries: unknown[] = [null, undefined, NaN, Infinity, -Infinity, -1, 0, 1, 14, 15, 30.5, "60", {}, 1e12, 2 ** 53, 20000];
  const days = [ORDINARY_DAY, SPRING, AUTUMN];
  let started = 0;
  let refused = 0;
  for (let n = 0; n < 8000; n++) {
    let raw = randomRaw(rand);
    if (rand() < 0.7) raw = { ...PROPOSED_CONFIRMED, ...(rand() < 0.5 ? {} : { holdCapMin: 5 + 5 * Math.floor(rand() * 864), cutReservePct: 10 + Math.floor(rand() * 91) }) };
    const cur = rand() < 0.15 ? null : 10 + Math.floor(rand() * 91);
    const result: OverrideConfigResult = validateOverrideConfig(raw, { currentReservePct: cur });
    const kind = OVERRIDE_KINDS[Math.floor(rand() * 3)] as OverrideKind;
    const req = rand() < 0.5 ? expiries[Math.floor(rand() * expiries.length)] : 15 + Math.floor(rand() * 11000);
    const now = Math.floor(rand() * 5_000_000);
    const clock: ClockContext | null = rand() < 0.1 ? null : { nowWallMin: Math.floor(rand() * 1440), day: days[Math.floor(rand() * 3)] as ClockContext["day"] };
    const out = startConfiguredOverride(kind, now, req as number, result, { clock, currentReservePct: rand() < 0.1 ? null : cur });
    if (!out.ok) {
      refused++;
      assert.ok(out.error.length > 0);
      continue;
    }
    started++;
    assert.equal(result.ok, true, "an override only starts under a valid policy");
    const cfg = (result as { config: OverrideConfig }).config;
    const length = out.override.expiresAtMin - out.override.startedAtMin;
    assert.ok(Number.isFinite(length) && Number.isInteger(length), "bounded and whole");
    assert.ok(length >= cfg.minExpiryMin && length > 0, "not shorter than the minimum");
    assert.ok(length <= EXPIRY_CEILING_MIN[kind], "never above the hard ceiling");
    const cap = kind === "hold_battery" ? cfg.holdCapMin : kind === "skip_tonight" ? cfg.skipCapMin : cfg.cutCapMin;
    assert.ok(length <= cap, "never above the owner's cap");
    assert.equal(out.override.startedAtMin, now);
    if (kind === "prepare_power_cut") {
      const r = out.override.reservePct as number;
      assert.ok(r >= LIMITS.reserveMin && r <= LIMITS.reserveMax);
      assert.ok(cur !== null && r >= cur, "never below the current reserve");
    } else {
      assert.equal(out.override.reservePct, undefined);
    }
    // And applying what was started never lowers a reserve, whatever the plan looked like.
    const view: PlanView = { startsAllowed: { charge: rand() < 0.5, export: rand() < 0.5 }, discretionaryRateEdits: rand() < 0.5, backupReservePct: 10 + Math.floor(rand() * 91), exportStopSoc: 10 + Math.floor(rand() * 81) };
    const applied = applyOverrides(view, [out.override], now + Math.floor(rand() * length));
    assert.ok(applied.view.backupReservePct >= view.backupReservePct && applied.view.exportStopSoc >= view.exportStopSoc);
  }
  assert.ok(started > 400 && refused > 400, "both sides exercised: " + started + " started, " + refused + " refused");
});

// ---- bounds table and README -----------------------------------------------------------------------------------------------------------

test("the bounds block is strict JSON (a Python test reads it) and matches the exported table", () => {
  const src = readFileSync(new URL("../src/overridePolicy.ts", import.meta.url), "utf8");
  const m = /BEGIN HELPER_BOUNDS_JSON\r?\nexport const HELPER_BOUNDS = (\{[\s\S]*?\n\}) as const;\r?\n\/\/ END HELPER_BOUNDS_JSON/.exec(src);
  assert.ok(m, "markers present");
  assert.deepEqual(JSON.parse(m[1] as string), HELPER_BOUNDS);
});

test("the README table of proposed defaults carries every key and value of the code", () => {
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  assert.match(readme, /PROPOSED/);
  for (const p of PROPOSED_DEFAULTS) {
    const row = readme.split(/\r?\n/).find((l) => l.includes("`" + p.key + "`"));
    assert.ok(row, "README row for " + p.key);
    assert.ok((row as string).includes(String(p.value)), p.key + " value " + p.value + " in its README row");
  }
});
