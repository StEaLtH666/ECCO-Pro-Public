import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ORDINARY_DAY, startConfiguredOverride, untilLocalTime, validateOverrideConfig } from "../src/index.ts";
import type { ClockDay, OverrideConfigRaw, OverrideKind, RefusalCode } from "../src/index.ts";

// The parity table: ONE list of cases, TWO evaluators. This file runs the plan core validator over every case and requires exactly the
// recorded answer. home-assistant/tests/test_ecco_plan_helpers_package.py runs the Home Assistant guarded script
// (home-assistant/packages/ecco_plan_helpers.yaml) over the same cases and requires the same answers. So the backend that actually
// enforces an override and the validator the card shows its choices from cannot drift apart without one of the two suites failing.

interface Case {
  id: string;
  kind: string;
  expiry_min: number | null;
  until_local: boolean;
  policy: Record<string, unknown>;
  owner_reserve: number | null;
  now_local: string;
  clock_day: "ordinary" | "spring" | "autumn";
  expect: { ok: boolean; code: string; expiry_min: number };
}
const doc = JSON.parse(readFileSync(new URL("./parity/override_parity_cases.json", import.meta.url), "utf8")) as { policy: Record<string, unknown>; cases: Case[] };

// The clock changes of the table's zone, in the plan core's terms (01:00 -> 02:00 in spring, 02:00 -> 01:00 in autumn).
const DAYS: Record<Case["clock_day"], ClockDay> = { ordinary: ORDINARY_DAY, spring: { changeAtMin: 60, deltaMin: 60 }, autumn: { changeAtMin: 120, deltaMin: -60 } };

/** "HH:MM:SS" as a minute of day, a stray seconds part left as a fraction (the validator refuses it), as the card's reader does. */
function timeOfDayMin(text: unknown): number | null {
  if (typeof text !== "string") return null;
  const m = /^(\d{2}):(\d{2}):(\d{2})$/.exec(text);
  return m ? Number(m[1]) * 60 + Number(m[2]) + Number(m[3]) / 60 : null;
}

function rawOf(policy: Record<string, unknown>): OverrideConfigRaw {
  const n = (k: string): number | null => (typeof policy[k] === "number" ? (policy[k] as number) : null);
  return {
    confirmed: policy["confirmed"] === true,
    minExpiryMin: n("min_expiry"),
    holdDefaultMin: n("hold_default"),
    holdCapMin: n("hold_cap"),
    skipUntilMin: timeOfDayMin(policy["skip_until"]),
    skipCapMin: n("skip_cap"),
    cutDefaultMin: n("cut_default"),
    cutCapMin: n("cut_cap"),
    cutReservePct: n("cut_reserve"),
  };
}

function answer(c: Case): { ok: boolean; code: string; expiry_min: number } {
  const policy = { ...doc.policy, ...c.policy };
  const result = validateOverrideConfig(rawOf(policy)); // no current reserve here: the start itself checks it, for Prepare for power cut only
  const m = /^\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}$/.exec(c.now_local);
  assert.ok(m, c.id + ": now_local");
  const clock = { nowWallMin: Number(m[1]) * 60 + Number(m[2]), day: DAYS[c.clock_day] };
  let expiry: number | null = c.expiry_min;
  if (expiry === null && c.until_local) {
    // What the card does for its "until HH:MM" choice: the validator works out the minutes, then the start checks them like any length.
    const u = untilLocalTime(clock.nowWallMin, Math.round((timeOfDayMin(policy["skip_until"]) as number) * 1), clock.day);
    expiry = u.ok ? u.expiryMin : null;
  }
  const s = startConfiguredOverride(c.kind as OverrideKind, 1000, expiry, result, { clock, currentReservePct: c.owner_reserve });
  return s.ok ? { ok: true, code: "", expiry_min: s.override.expiresAtMin - s.override.startedAtMin } : { ok: false, code: s.code, expiry_min: 0 };
}

test("parity table: the validator gives exactly the recorded answer for every case", () => {
  assert.ok(doc.cases.length >= 40, "the table must stay broad");
  assert.equal(new Set(doc.cases.map((c) => c.id)).size, doc.cases.length, "case ids are unique");
  for (const c of doc.cases) assert.deepEqual(answer(c), c.expect, c.id);
});

test("parity table: it covers valid starts, every refusal the validator reaches, the clock-change days and the hard ceiling", () => {
  const codes = new Set(doc.cases.map((c) => c.expect.code));
  const reachable: RefusalCode[] = ["POLICY_UNCONFIRMED", "POLICY_INVALID", "UNKNOWN_KIND", "EXPIRY_NOT_WHOLE", "RESERVE_UNKNOWN", "RESERVE_BELOW_CURRENT", "EXPIRY_BELOW_MIN", "EXPIRY_ABOVE_CAP"];
  for (const code of reachable) assert.ok(codes.has(code), "no case for " + code);
  assert.ok(codes.has(""), "no valid case");
  for (const kind of ["hold_battery", "skip_tonight", "prepare_power_cut"]) assert.ok(doc.cases.some((c) => c.kind === kind && c.expect.ok), "no valid " + kind);
  assert.ok(doc.cases.some((c) => c.clock_day === "spring") && doc.cases.some((c) => c.clock_day === "autumn"), "both clock changes");
  // The hard ceiling is reachable only through the bounds: a cap above a ceiling is an invalid policy, never a started override.
  assert.ok(doc.cases.some((c) => c.id === "invalid_cap_above_hard_ceiling" && c.expect.code === "POLICY_INVALID"));
  for (const c of doc.cases) assert.equal(c.expect.ok, c.expect.code === "", c.id);
});

test("parity table: a clock-change day is measured in real minutes (an hour less in spring, an hour more in autumn)", () => {
  const by = (id: string) => doc.cases.find((c) => c.id === id) as Case;
  assert.equal(answer(by("skip_default_until_ordinary")).expiry_min, 570);
  assert.equal(answer(by("skip_spring_day")).expiry_min, 450);
  assert.equal(answer(by("skip_autumn_day")).expiry_min, 570);
  // The same wall-clock night is 8 h 30 min on an ordinary day; the autumn night is an hour longer in real time.
  assert.equal(answer({ ...by("skip_autumn_day"), clock_day: "ordinary" }).expiry_min, 510);
});

test("the stable refusal codes are exactly the ones the guarded script names", () => {
  const src = readFileSync(new URL("../src/overrides.ts", import.meta.url), "utf8");
  const block = /export type RefusalCode =([\s\S]*?);\n/.exec(src);
  assert.ok(block, "RefusalCode type");
  const codes = [...(block[1] as string).matchAll(/"([A-Z_]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(codes, [
    "EXPIRY_ABOVE_CAP", "EXPIRY_ABOVE_CEILING", "EXPIRY_BELOW_MIN", "EXPIRY_MISSING", "EXPIRY_NOT_WHOLE", "POLICY_INVALID", "POLICY_UNCONFIRMED",
    "POWER_CUT_RESERVE_RANGE", "RESERVE_BELOW_CURRENT", "RESERVE_UNKNOWN", "TIME_UNKNOWN", "UNKNOWN_KIND",
  ]);
});
