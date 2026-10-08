// Integrity of the generated catalogue (src/catalogue.generated.ts). The generator (tools/build_advanced_config_catalogue.py)
// has its own Python suite; these checks hold the card's side of the contract.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, it } from "node:test";

import { CATALOGUE, CATALOGUE_SHA256 } from "../src/catalogue.generated.ts";
import type { Status } from "../src/types.ts";

const LADDER: Status[] = ["PROVEN", "EXPERIMENTAL", "READ_ONLY", "LOCKED", "UNSUPPORTED"];
const EVIDENCE_BY_PROOF: Record<string, string> = {
  live_proven_write: "M3",
  live_proven_read: "M2",
  documented_not_live_proven: "M1",
  repository_inferred_read_only: "M0",
  inferred_do_not_write: "M0",
  unknown: "MX",
};

/** Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) for this catalogue's value shapes. */
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v !== null && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(v);
}

describe("generated catalogue", () => {
  it("is the declared, read-only schema with every registry record", () => {
    assert.equal(CATALOGUE.schema, "ecco-advanced-config-catalogue/1");
    assert.equal(CATALOGUE.read_only, true);
    assert.equal(CATALOGUE.generator, "tools/build_advanced_config_catalogue.py");
    assert.equal(CATALOGUE.record_count, 165);
    assert.equal(CATALOGUE.items.length, 165);
    assert.equal(new Set(CATALOGUE.items.map((i) => i.id)).size, 165);
  });

  it("matches its embedded SHA-256 (the module was not edited by hand)", () => {
    assert.equal(createHash("sha256").update(canonical(CATALOGUE), "utf8").digest("hex"), CATALOGUE_SHA256);
  });

  it("is grouped into the nine requested sections, none empty", () => {
    assert.deepEqual(
      CATALOGUE.sections.map((s) => [s.id, s.title]),
      [
        ["battery_charging", "Battery and Charging"],
        ["grid_export", "Grid and Export"],
        ["inverter_power", "Inverter Power"],
        ["time_of_use", "Time of Use"],
        ["generator_aux", "Generator / AUX / Smart Load"],
        ["solar_pv", "Solar / PV"],
        ["protection_safety", "Protection and Safety"],
        ["comms_diagnostics", "Communications and Diagnostics"],
        ["experimental", "Experimental / Undocumented"],
      ],
    );
    for (const s of CATALOGUE.sections) {
      assert.ok(CATALOGUE.items.some((i) => i.section === s.id), s.id);
      assert.ok(s.summary.length > 10, s.id);
    }
    for (const i of CATALOGUE.items) assert.ok(CATALOGUE.sections.some((s) => s.id === i.section), i.id);
  });

  it("is sorted by section, then by first register", () => {
    const order = new Map(CATALOGUE.sections.map((s, n) => [s.id, n]));
    const key = (i: (typeof CATALOGUE.items)[number]) => [order.get(i.section) ?? 99, i.registers[0]?.address ?? 1e9, i.id] as const;
    for (let n = 1; n < CATALOGUE.items.length; n++) {
      const a = key(CATALOGUE.items[n - 1]!);
      const b = key(CATALOGUE.items[n]!);
      assert.ok(a[0] < b[0] || (a[0] === b[0] && (a[1] < b[1] || (a[1] === b[1] && a[2] < b[2]))), `${a} before ${b}`);
    }
  });
});

describe("status classification", () => {
  it("every status is on the ladder, and the overlay only ever moved a record DOWN it", () => {
    for (const i of CATALOGUE.items) {
      assert.ok(LADDER.includes(i.status), i.id);
      assert.ok(LADDER.includes(i.status_derived), i.id);
      assert.ok(LADDER.indexOf(i.status) >= LADDER.indexOf(i.status_derived), `${i.id}: ${i.status_derived} -> ${i.status}`);
    }
  });

  it("derives status from the registry's own proof and policy fields", () => {
    for (const i of CATALOGUE.items) {
      let expected: Status;
      if (i.live_proof_status === "unknown" || i.write_policy === "WX") expected = "UNSUPPORTED";
      else if (i.current_access !== "read_only" && i.live_proof_status === "live_proven_write") expected = "PROVEN";
      else if (i.current_access !== "read_only") expected = "EXPERIMENTAL";
      else expected = "READ_ONLY";
      assert.equal(i.status_derived, expected, i.id);
    }
  });

  it("maps evidence one-to-one from the registry's live-proof status", () => {
    for (const i of CATALOGUE.items) assert.equal(i.evidence, EVIDENCE_BY_PROOF[i.live_proof_status], i.id);
  });

  it("has the expected distribution (41 proven elsewhere, 1 experimental, 100 read-only, 16 locked, 7 unsupported)", () => {
    const count = (s: Status) => CATALOGUE.items.filter((i) => i.status === s).length;
    assert.deepEqual(LADDER.map(count), [41, 1, 100, 16, 7]);
  });

  it("every record says why it is not writable here, and every locked record has a specific reason", () => {
    for (const i of CATALOGUE.items) assert.ok(i.lock_reason.length > 20, i.id);
    const generic = new Set(CATALOGUE.items.filter((i) => i.status === "READ_ONLY").map((i) => i.lock_reason));
    for (const i of CATALOGUE.items.filter((x) => x.status === "LOCKED")) {
      assert.ok(!generic.has(i.lock_reason) || i.lock_reason.includes("Locked"), i.id);
      assert.ok(["D2", "D3", "D4"].includes(i.danger), `${i.id}: ${i.danger}`);
    }
  });

  it("danger classes are D0-D4", () => {
    for (const i of CATALOGUE.items) assert.match(i.danger, /^D[0-4]$/, i.id);
  });
});

describe("register mapping", () => {
  it("entity references carry no device slug and use read-only Home Assistant domains", () => {
    for (const i of CATALOGUE.items) {
      for (const ref of [i.entity, i.raw_entity]) {
        if (!ref) continue;
        assert.ok(["sensor", "binary_sensor", "switch"].includes(ref.domain), `${i.id}: ${ref.domain}`);
        assert.match(ref.object, /^[a-z0-9_]+$/, i.id);
        assert.ok(!ref.object.startsWith("ecco_clock_dongle"), i.id);
        assert.ok(ref.firmware_id.length > 0, i.id);
      }
    }
    for (const g of [CATALOGUE.freshness_gates.telemetry, CATALOGUE.freshness_gates.configuration]) {
      assert.equal(g.domain, "binary_sensor");
    }
  });

  it("a linked firmware decode reads the record's own registers", () => {
    for (const i of CATALOGUE.items) {
      if (!i.decode) continue;
      const own = new Set(i.registers.map((r) => r.address));
      assert.ok(i.decode.registers.some((r) => own.has(r)), `${i.id}: ${i.decode.registers} vs ${[...own]}`);
      assert.ok(CATALOGUE.steady_windows.includes(i.decode.window), i.id);
    }
  });

  it("links 158 of 165 records to an entity; the unlinked ones say so", () => {
    const unlinked = CATALOGUE.items.filter((i) => !i.entity).map((i) => i.id);
    assert.equal(unlinked.length, 7);
    assert.ok(unlinked.includes("inverter_rated_power"));
  });

  it("Global Power is register 245, the Export Limit record, read-only", () => {
    const gp = CATALOGUE.global_power;
    assert.equal(gp.record, "export_limit");
    assert.equal(gp.register, 245);
    assert.equal(gp.title, "Global Power / Export Limit");
    assert.equal(gp.write_status, "not_implemented");
    assert.equal(gp.hardware_maximum_w, null);
    assert.equal(gp.hardware_maximum_evidence, null);
    assert.equal(gp.regulatory_allowance_w, null);
    assert.deepEqual(Object.keys(gp.future_controls).sort(), ["apply", "history", "permitted_range", "previous_value", "staged_value", "unlock", "verification"]);
    const single245 = CATALOGUE.items.filter((i) => i.registers.length === 1 && i.registers[0]?.address === 245);
    assert.deepEqual(single245.map((i) => i.id), ["export_limit"]);
    const el = single245[0]!;
    assert.equal(el.status, "READ_ONLY");
    assert.equal(el.section, "inverter_power");
    assert.equal(el.danger, "D3");
    assert.equal(el.unit, "W");
    assert.deepEqual(el.options, {});
    assert.deepEqual(el.entity && [el.entity.domain, el.entity.object], ["sensor", "ecco_export_limit"]);
    assert.equal(el.decode?.kind, "linear");
    assert.deepEqual(el.decode?.registers, [245]);
    assert.equal(el.poll_class, "configuration");
  });

  it("no record presents a firmware ceiling as a hardware maximum", () => {
    for (const i of CATALOGUE.items) {
      assert.ok(!("hardware_maximum" in i.options) || i.options.hardware_maximum === null, i.id);
      if (i.options.firmware_ceiling !== undefined) {
        assert.match(i.options.firmware_ceiling_note ?? "", /not a verified inverter hardware maximum/, i.id);
      }
    }
    assert.ok(!JSON.stringify(CATALOGUE.global_power).includes("8000"));
  });

  it("spells no reserved token of the protected fallback / shadow layers", () => {
    const text = JSON.stringify(CATALOGUE);
    const reserved = [
      "ecco_" + "fallback",
      "FALLBACK" + "_PROFILE",
      "FAILBACK" + "_STATE",
      "ecco_" + "failback",
      "failback" + "_shadow",
      "ecco_" + "shadow_",
      "Shadow" + " Recovery",
      "fbc_" + "raw_",
    ];
    for (const tok of reserved) assert.ok(!text.includes(tok), tok);
  });
});
