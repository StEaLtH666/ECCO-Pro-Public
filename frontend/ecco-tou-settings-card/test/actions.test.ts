// The one call site, exhaustively: perform() for every kind x slot 1-6 x setting, with a recording service function. Exactly one call
// each, with exactly the expected domain, service, entity id and variable keys and values (Window B H2: the earlier suites reached
// perform() for slot 3 only, so a call gated on another slot or a description altered for another slot passed).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { perform } from "../src/actions.ts";
import { ACK_PHRASE, EDITABLE, SCRIPT_ACK, SCRIPT_APPLY, SCRIPT_REVIEW } from "../src/model.ts";
import type { EditableSetting } from "../src/types.ts";

interface Call {
  domain: string;
  service: string;
  data: unknown;
}

function recorder(): { calls: Call[]; fn: (domain: string, service: string, data?: Record<string, unknown>) => Promise<unknown> } {
  const calls: Call[] = [];
  return {
    calls,
    fn: (domain, service, data) => {
      calls.push({ domain, service, data });
      return Promise.resolve(undefined);
    },
  };
}

const VALUES: Record<EditableSetting, { value: string; sent: string | number }[]> = {
  target_soc: [{ value: "90", sent: 90 }, { value: "20", sent: 20 }, { value: "100", sent: 100 }],
  power: [{ value: "7900", sent: 7900 }, { value: "500", sent: 500 }, { value: "8000", sent: 8000 }],
  charge_source: [{ value: "Grid", sent: "Grid" }, { value: "None", sent: "None" }],
};

describe("perform(): every kind, every slot, every setting", () => {
  it("review: one script.turn_on of the Review script per call, variables exactly {slot, setting, value}", () => {
    for (let slot = 1; slot <= 6; slot++) {
      for (const setting of EDITABLE) {
        for (const { value, sent } of VALUES[setting]) {
          const rec = recorder();
          const { call } = perform(rec.fn, "review", { slot, setting, value });
          assert.equal(rec.calls.length, 1, `slot ${slot} ${setting} ${value}`);
          assert.deepEqual(rec.calls[0], { domain: "script", service: "turn_on", data: { entity_id: SCRIPT_REVIEW, variables: { slot, setting, value: sent } } });
          assert.deepEqual(Object.keys((rec.calls[0]?.data as { variables: object }).variables).sort(), ["setting", "slot", "value"]);
          assert.deepEqual(call.data, { entity_id: SCRIPT_REVIEW, variables: { slot, setting, value: sent } });
        }
      }
    }
  });

  it("apply: one script.turn_on of the Apply script, variables exactly {confirmation: <the typed phrase>}, for every slot's phrase", () => {
    for (let slot = 1; slot <= 6; slot++) {
      for (const phrase of [`SET SLOT ${slot} TARGET SOC 90 REVIEW 4321`, `SET SLOT ${slot} POWER 7900 W REVIEW 0042`, `SET SLOT ${slot} CHARGE SOURCE GRID REVIEW 9999`, `SET SLOT ${slot} CHARGE SOURCE NONE REVIEW 0001`]) {
        const rec = recorder();
        perform(rec.fn, "apply", phrase);
        assert.deepEqual(rec.calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_APPLY, variables: { confirmation: phrase } } }]);
      }
    }
  });

  it("acknowledge: one script.turn_on of the Acknowledge script, variables exactly {confirmation}", () => {
    const rec = recorder();
    perform(rec.fn, "acknowledge", ACK_PHRASE);
    assert.deepEqual(rec.calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_ACK, variables: { confirmation: ACK_PHRASE } } }]);
  });

  it("a kind with the wrong payload type throws before any call", () => {
    const rec = recorder();
    assert.throws(() => perform(rec.fn, "review", "SET SLOT 3 TARGET SOC 90 REVIEW 4321"), /review needs a draft/);
    assert.throws(() => perform(rec.fn, "apply", { slot: 3, setting: "target_soc", value: "90" }), /needs the typed phrase/);
    assert.throws(() => perform(rec.fn, "acknowledge", { slot: 3, setting: "target_soc", value: "90" }), /needs the typed phrase/);
    assert.deepEqual(rec.calls, []);
  });

  it("the service function's own result is passed back; a rejection is not swallowed here", async () => {
    const calls: Call[] = [];
    const { done } = perform((d, s, data) => {
      calls.push({ domain: d, service: s, data });
      return Promise.reject(new Error("refused"));
    }, "acknowledge", ACK_PHRASE);
    await assert.rejects(done, /refused/);
    assert.equal(calls.length, 1);
  });
});
