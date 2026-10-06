#!/usr/bin/env python3
"""FB-B1 - self-tests of the FB-B1 simulator extensions (Phase-0 style).

The FB-B1 behavioural suite (test_fallback_profile_capture.py) executes the
REAL firmware YAML through registry/tests/_fbb_harness.FbbSim. This file proves
the harness itself, every capability against its specification and with a
negative control that fails LOUDLY (FbbNotModelled), using small synthetic YAML
fixtures embedded below - it does not depend on the FB-B1 firmware or on
registry/fallback_capture.py existing (the `ecco_fbcap::` adapter is exercised
over the test double registry/tests/_fbb1_fbcap_double.py).

  [1] _dump_sim additions: random_uint32() + seed, Modbus handler `values` as a
      vector / `exception_code`, ESPTime::strftime, tokenizer back-compat
  [2] array globals (std::array<T, N>): strict types, zero init, value
      semantics, bounds-checked indexing, by-reference passing
  [3] transpiler gaps (casts, constexpr, loops, arrays, sizeof, std::string +,
      compound ops, ++ --, switch blocks, static_assert) + negative controls
  [4] unsigned wrap: millis() - x, typed values, TTL arithmetic near 2^32
  [5] the generic `ecco_fbcap::` adapter (constants, enums, PODs, arrays,
      functions, out-parameters, text) + byte-image helpers
  [6] ecco_durable::ValidMarker probes through the direct NVS
  [7] the discrete-event engine: ordering rules, asynchronous scripts, waits,
      delays, buttons, bounded runs, clock rebase
  [8] deferred Modbus frames, the hub model, foreign frames, late callbacks
  [9] the interval scheduler
 [10] injectable events, the unified event timeline, power cut, reboot
 [11] safety marks (no write / no NVS set / exact read list)
 [12] a REVIEW-shaped fixture (gate + dispatch + housekeeping) through the whole
      machinery: the scenarios the FB-B1 behavioural suite needs
 [13] strictness summary, capability coverage, live-firmware smoke

No I/O beyond reading repository files, no hardware.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbb1_fbcap_double as DBL  # noqa: E402
import _fbb1_types as T  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FAILURES: list[str] = []
COVERED: set[str] = set()


def check(name: str, condition: bool, detail: str = "", cap: str | None = None) -> None:
    if condition:
        if cap:
            COVERED.add(cap)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn, exc=H.FbbNotModelled):
    try:
        fn()
    except exc as e:
        return e
    return None


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def G(i, t, v=None):
    g = {"id": i, "type": t, "restore_value": "no"}
    if v is not None:
        g["initial_value"] = v
    return g


def L(code):
    return {"lambda": code}


def S(i, then, mode=None, parameters=None):
    s = {"id": i, "then": then}
    if mode:
        s["mode"] = mode
    if parameters:
        s["parameters"] = parameters
    return s


def READ(start, count, ok="", err="", nores="", notsent="", custom=""):
    node = {"modbus_id": "inverter_modbus", "address": 1, "start_address": start, "count": count}
    for key, code in (("on_response", ok), ("on_error", err), ("on_no_response", nores), ("on_not_sent", notsent),
                      ("on_custom_response", custom)):
        if code:
            node[key] = {"then": [L(code)]}
    return {"modbus_client.read_holding_registers": node}


def mkfw(globals_=(), scripts=(), buttons=(), intervals=(), text_sensors=(), boot=()):
    return {"globals": list(globals_), "script": list(scripts), "_substitutions": {}, "sensor": [], "api": {},
            "interval": list(intervals), "button": list(buttons), "text_sensor": list(text_sensors),
            "esphome": {"on_boot": {"then": list(boot)}} if boot else {}}


BASE_G = [G("u", "uint32_t", "0"), G("b", "bool", "false"), G("b2", "bool", "false"), G("b3", "bool", "false"),
          G("s", "std::string", '""'), G("n", "uint8_t", "0"), G("h", "uint16_t", "0"), G("e", "int32_t", "0"),
          G("u64", "uint64_t", "0"), G("w", "std::array<uint16_t, 31>"), G("w2", "std::array<uint16_t, 31>"),
          G("by", "std::array<uint8_t, 96>")]


def new_sim(globals_=None, **kw):
    return H.FbbSim(mkfw(BASE_G if globals_ is None else globals_), **kw)


def lam(code, show=(), sim=None, **kw):
    """('ok', {global: value}) or ('raise', the exception)."""
    s = sim or new_sim(**kw)
    try:
        s.run_lambda(code)
    except BaseException as e:  # noqa: BLE001
        return "raise", e
    return "ok", {k: (list(s.g[k]) if isinstance(s.g[k], list) else s.g[k]) for k in show}


def _indent(text: str, n: int) -> str:
    return "\n".join((" " * n + line) if line.strip() else line for line in text.split("\n"))


def _read_node(k: int, start: int, count: int, store: str) -> str:
    """One FC03 read node in the S1 1.5 template: per-step guard BEFORE the terminal flag, all five outcome handlers,
    a bounded 3 s wait, a post-wait terminal check."""
    return f"""
- lambda: |-
    id(step) = {k};
    id(step_terminal) = false;
- modbus_client.read_holding_registers:
    modbus_id: inverter_modbus
    address: 0x01
    start_address: {start}
    count: {count}
    on_response:
      then:
        - lambda: |-
            if (!id(op_in_progress) || id(step) != {k}) return;
            id(step_terminal) = true;
            if (values.size() != {count}) {{ id(read_failed) = true; id(read_fail_code) = 3; return; }}
            {store}
    on_error:
      then:
        - lambda: |-
            if (!id(op_in_progress) || id(step) != {k}) return;
            id(step_terminal) = true;
            id(read_failed) = true;
            id(read_fail_code) = 4;
            id(last_exc) = exception_code;
    on_no_response:
      then:
        - lambda: |-
            if (!id(op_in_progress) || id(step) != {k}) return;
            id(step_terminal) = true;
            id(read_failed) = true;
            id(read_fail_code) = 5;
    on_not_sent:
      then:
        - lambda: |-
            if (!id(op_in_progress) || id(step) != {k}) return;
            id(step_terminal) = true;
            id(read_failed) = true;
            id(read_fail_code) = 6;
    on_custom_response:
      then:
        - lambda: |-
            if (!id(op_in_progress) || id(step) != {k}) return;
            id(step_terminal) = true;
            id(read_failed) = true;
            id(read_fail_code) = 8;
- wait_until:
    condition:
      lambda: 'return id(step_terminal);'
    timeout: 3000ms
- lambda: |-
    if (!id(step_terminal)) {{ id(read_failed) = true; id(read_fail_code) = 7; }}
"""


def review_fixture_yaml() -> str:
    """A synthetic firmware shaped like FB-B1's REVIEW: a synchronous gate (one decision lambda, then `if:` on the
    recorded code), an async dispatch (idle wait, four nested fail-fast FC03 nodes, final lambda, release lambda), a
    10 s housekeeping interval (breaker + TTL) and a button. It uses std::array globals, the ecco_fbcap:: double,
    is_running(), tx_buffer_empty()/tx_blocked(), random_uint32() and (uint32_t)(millis() - x) - everything the real
    firmware will."""
    nodes = [
        _read_node(1, 230, 3, "for (int i = 0; i < 3; i++) id(pass1)[i] = values[i];"),
        _read_node(2, 241, 53, "ecco_fbcap::store_block_241(id(pass1), values);"),
        _read_node(3, 230, 3, "for (int i = 0; i < 3; i++) id(pass2)[i] = values[i];"),
        _read_node(4, 241, 53, "ecco_fbcap::store_block_241(id(pass2), values);"),
    ]
    body = nodes[3]
    for nd in (nodes[2], nodes[1]):
        body = nd + "\n- if:\n    condition:\n      lambda: 'return !id(read_failed);'\n    then:\n" + _indent(body, 6)
    body = nodes[0] + "\n- if:\n    condition:\n      lambda: 'return !id(read_failed);'\n    then:\n" + _indent(body, 6)
    glob = [("mwip", "bool", "false"), ("op_in_progress", "bool", "false"), ("op_started_ms", "uint32_t", "0"),
            ("step", "uint8_t", "0"), ("step_terminal", "bool", "false"), ("read_failed", "bool", "false"),
            ("read_fail_code", "uint8_t", "0"), ("last_exc", "uint8_t", "0"), ("gate_code", "uint8_t", "0"),
            ("diff_idx", "int32_t", "-1"), ("cand_valid", "bool", "false"), ("cand_ms", "uint32_t", "0"),
            ("boot_salt", "uint32_t", "0"), ("capture_state", "uint8_t", "0"),
            ("pass1", "std::array<uint16_t, 31>", None), ("pass2", "std::array<uint16_t, 31>", None),
            ("cand_words", "std::array<uint16_t, 31>", None)]
    text = "globals:\n" + "\n".join(
        f"  - id: {i}\n    type: {t}\n    restore_value: no" + (f"\n    initial_value: '{v}'" if v is not None else "")
        for i, t, v in glob)
    text += """
text_sensor:
  - platform: template
    id: result_ts
    name: Result
button:
  - platform: template
    id: review_button
    name: Review
    on_press:
      - script.execute: review_gate
script:
  - id: poll_cfg
    mode: single
    then:
      - delay: 5s
  - id: poll_tel
    mode: single
    then:
      - delay: 2s
  - id: invalidate_candidate
    mode: single
    then:
      - lambda: |-
          if (id(op_in_progress)) return;
          id(cand_valid) = false;
          id(capture_state) = 0;
          id(result_ts).publish_state("REVIEW EXPIRED");
  - id: review_gate
    mode: single
    then:
      - lambda: |-
          id(gate_code) = 0;
          if (id(op_in_progress) || id(capture_dispatch).is_running()) { id(gate_code) = 1; return; }
          if (id(boot_salt) == 0) id(boot_salt) = random_uint32() | 1u;
          if (id(mwip)) { id(gate_code) = 2; return; }
          id(op_in_progress) = true;
          id(mwip) = true;
          id(step) = 0;
          id(op_started_ms) = millis();
          id(read_failed) = false;
          id(read_fail_code) = 0;
          id(capture_state) = 1;
          id(result_ts).publish_state("review in progress (read-only)");
      - if:
          condition:
            lambda: 'return id(gate_code) != 0;'
          then:
            - lambda: |-
                if (id(gate_code) == 1) id(result_ts).publish_state("REVIEW REFUSED - another Fallback Profile operation is in progress");
                else id(result_ts).publish_state("REVIEW REFUSED - busy");
          else:
            - script.execute:
                id: capture_dispatch
  - id: capture_dispatch
    mode: single
    then:
      - wait_until:
          condition:
            lambda: 'return !id(poll_cfg).is_running() && !id(poll_tel).is_running() && id(inverter_modbus)->tx_buffer_empty() && !id(inverter_modbus)->tx_blocked();'
          timeout: 7000ms
      - lambda: |-
          if (id(poll_cfg).is_running() || id(poll_tel).is_running() || !id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked()) { id(read_failed) = true; id(read_fail_code) = 9; }
      - if:
          condition:
            lambda: 'return !id(read_failed);'
          then:
""" + _indent(body, 12) + """
      - lambda: |-
          if (!id(op_in_progress)) return;
          if (id(read_failed)) {
            char b[64];
            snprintf(b, sizeof(b), "REVIEW NOT COMPLETED - code %u", (unsigned) id(read_fail_code));
            id(result_ts).publish_state(b);
            id(capture_state) = 0;
            return;
          }
          int d = ecco_fbcap::first_diff(id(pass1), id(pass2));
          id(diff_idx) = d;
          if (d != -1) {
            id(result_ts).publish_state("REVIEW NOT COMPLETED - live configuration changed");
            id(capture_state) = 0;
            return;
          }
          id(cand_words) = id(pass2);
          id(cand_ms) = millis();
          id(cand_valid) = true;
          id(capture_state) = 2;
          id(result_ts).publish_state(ecco_fbcap::TXT_READY);
      - lambda: |-
          id(op_in_progress) = false;
          id(mwip) = false;
          id(step) = 0;
interval:
  - interval: 10s
    startup_delay: 5s
    then:
      - lambda: |-
          if (id(op_in_progress) && !id(capture_dispatch).is_running() && (uint32_t) (millis() - id(op_started_ms)) > ecco_fbcap::BREAKER_MS) {
            id(op_in_progress) = false;
            id(step) = 0;
            id(result_ts).publish_state("INTERNAL - breaker");
          }
          if (id(cand_valid) && (uint32_t) (millis() - id(cand_ms)) >= ecco_fbcap::CANDIDATE_TTL_MS) {
            id(invalidate_candidate).execute();
          }
"""
    return text


def main() -> int:
    # =======================================================================
    print("[1] _dump_sim additions: random_uint32, handler values / exception_code, strftime, tokenizer back-compat")
    # =======================================================================
    p = ds.Sim(mkfw(BASE_G))
    p.seed_rng(1234)
    a, b = p.random_uint32(), p.random_uint32()
    q = ds.Sim(mkfw(BASE_G))
    q.seed_rng(1234)
    r = ds.Sim(mkfw(BASE_G))
    r.seed_rng(99)
    check("random_uint32(): a seedable per-sim RNG - the same seed gives the same stream, another seed another stream; "
          "the seed is observable (rng_seed) and every value is logged (random_log)",
          (q.random_uint32(), q.random_uint32()) == (a, b) and r.random_uint32() != a and p.rng_seed == 1234
          and p.random_log == [a, b] and 0 <= a < 2 ** 32, cap="random_uint32")
    p.random_values = [0, 0x1FFFFFFFF]
    check("random_values is a FIFO of FORCED values (a test pins the salt), masked to 32 bits, then the RNG resumes",
          (p.random_uint32(), p.random_uint32()) == (0, 0xFFFFFFFF) and p.random_uint32() not in (0, 0xFFFFFFFF),
          cap="random_uint32")
    s = ds.Sim(mkfw(BASE_G))
    s.seed_rng(5)
    expect = ds.Sim(mkfw(BASE_G))
    expect.seed_rng(5)
    s.run_lambda("id(u) = random_uint32();")
    check("`random_uint32()` is a Transpiler primary of the plain _dump_sim.Sim too (it was Unsupported)",
          s.g["u"] == expect.random_uint32(), cap="random_uint32")
    s = H.FbbSim(mkfw(BASE_G))
    s.random_values = [0]
    s.run_lambda("id(u) = random_uint32() | 1u;")
    check("FbbSim: `random_uint32() | 1u` with a forced 0 is the salt 1 (the REVIEW golden salt)", s.g["u"] == 1,
          cap="random_uint32")

    fw_h = mkfw(BASE_G, [S("rd", [READ(230, 3, ok="id(u) = values.size(); id(n) = values[2]; id(h) = values.empty() ? 1 : 2;",
                                       err="id(n) = exception_code; id(u) = 77;")])])
    ps = ds.Sim(fw_h)
    ps.bank.update({230: 1, 231: 2, 232: 9})
    ps.execute("rd")
    check("plain Sim: an on_response handler sees `values` as a vector (.size() / [i] / .empty()) - it was a list without .size()",
          (ps.g["u"], ps.g["n"], ps.g["h"]) == (3, 9, 2), cap="modbus_handlers")
    ps.outcome_fn = lambda k, a_, c: "error"
    ps.exception_code = 5
    ps.execute("rd")
    check("plain Sim: an on_error handler sees `exception_code` (default 2, settable) - it was a KeyError",
          (ps.g["u"], ps.g["n"]) == (77, 5) and ds.Sim(fw_h).exception_code == 2, cap="modbus_handlers")
    check("Vec is a list (indexing, iteration, equality) with size() / data() / empty()",
          ds.Vec([1, 2]) == [1, 2] and ds.Vec([1, 2]).size() == 2 and ds.Vec([]).empty() and list(ds.Vec([3, 4])) == [3, 4])
    check("TimeNow.strftime: ESPTime::strftime (UTC) - the real configuration / telemetry polls need it",
          ds.TimeNow(True, 1_790_000_000, 14, 0).strftime("%Y-%m-%d") == time.strftime("%Y-%m-%d", time.gmtime(1_790_000_000)))
    # tokenizer back-compat: every lambda of the live firmware tokenises exactly as with the pre-FB-B1 operator list
    old_op = r"(?P<op>->|::|\+\+|--|&&|\|\||==|!=|<=|>=|\+=|-=|\*=|/=|\|=|&=|<<|>>|[{}()\[\];,.?:<>=!+\-*/%&|^~])"
    new_op = re.search(r"\(\?P<op>.*\)\n", ds._TOKEN.pattern).group(0).strip()
    old_re = re.compile(ds._TOKEN.pattern.replace(new_op, old_op), re.X)
    check("the tokenizer's operator list only GAINED <<= >>= %= ^= (the old pattern is reconstructed to prove it)",
          old_re.pattern != ds._TOKEN.pattern and all(op in ds._TOKEN.pattern for op in ("<<=", ">>=", "%=", "\\^=")))

    def tokens_with(regex, code):
        code = re.sub(r"//[^\n]*", "", code)
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        toks, pos = [], 0
        while pos < len(code) and code[pos:].strip():
            m = regex.match(code, pos)
            toks.append((m.lastgroup, m.group(m.lastgroup)))
            pos = m.end()
        return toks

    live_fw = ds.load_firmware(FIRMWARE_PATH)
    lambdas = []

    def collect(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "lambda" and isinstance(v, str):
                    lambdas.append(v)
                else:
                    collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)
    collect({k: v for k, v in live_fw.items() if not k.startswith("_")})
    uniq = sorted(set(lambdas))
    differ = []
    for code in uniq:
        code2 = ds.substitute(code, live_fw["_substitutions"])
        try:
            if tokens_with(old_re, code2) != tokens_with(ds._TOKEN, code2):
                differ.append(code)
        except AttributeError:
            differ.append(code)
    check(f"every one of the live firmware's {len(uniq)} distinct lambdas tokenises identically with the old and the new "
          "operator list unless it actually USES one of the new compound operators (no existing code changes meaning)",
          all(re.search(r"<<=|>>=|%=|\^=", c) for c in differ), f"{len(differ)} differ")

    # =======================================================================
    print("[2] array globals: std::array<T, N> (the FB-B1 firmware state; no header struct may be a global)")
    # =======================================================================
    s = new_sim()
    check("std::array globals exist as zero-initialised FbArrays of the declared element type and size (no initial_value)",
          isinstance(s.g["w"], T.FbArray) and len(s.g["w"]) == 31 and s.g["w"].ctype == "uint16_t" and not any(s.g["w"])
          and len(s.g["by"]) == 96 and s.g["by"].ctype == "uint8_t" and s.array_globals["w"] == ("uint16_t", 31),
          cap="array_globals")
    check("the std::array<uint8_t, 48> / <uint16_t, 31> / <uint8_t, 96> FB-B1 shapes are all accepted",
          [H.FbbSim(mkfw([G("x", t)])).g["x"].size() for t in ("std::array<uint8_t, 48>", "std::array<uint16_t, 31>",
                                                              "std::array<uint8_t, 96>")] == [48, 31, 96],
          cap="array_globals")
    check("strict types: an unknown struct global, a header-defined struct global (D1) and an unmodelled array element / "
          "non-literal size raise FbbNotModelled at construction",
          all(raises(lambda t=t: H.FbbSim(mkfw([G("x", t)]))) is not None for t in (
              "MyStruct", "ecco_fbcap::Candidate", "ecco_fbcap::DispatchCtx", "std::array<float, 3>", "std::array<uint16_t, N>",
              "std::vector<uint16_t>", "std::array<uint16_t, 31>*")), cap="strict_global_types")
    check("strict types: an array global's initial_value must be omitted (value-initialised) - `{}` is the zero form, "
          "anything else raises; the OLD _dump_sim.Sim keeps silently reading such a global as 0",
          H.FbbSim(mkfw([G("x", "std::array<uint8_t, 4>", "{}")])).g["x"] == [0, 0, 0, 0]
          and raises(lambda: H.FbbSim(mkfw([G("x", "std::array<uint8_t, 4>", "{1, 2}")]))) is not None
          and ds.Sim(mkfw([G("x", "std::array<uint8_t, 4>")])).g["x"] == 0, cap="strict_global_types")
    res = lam("id(w)[3] = 70000; id(w)[4] = id(w)[3] + 1; id(u) = id(w)[4]; id(n) = id(w).size(); id(h) = id(by).size();",
              ("w", "u", "n", "h"))
    check("`id(g)[i]` reads and writes with C width wrapping on the element (70000 -> 4464 in a uint16_t), .size()",
          res[0] == "ok" and res[1]["w"][3] == 4464 and res[1]["w"][4] == 4465 and res[1]["u"] == 4465
          and (res[1]["n"], res[1]["h"]) == (31, 96), str(res), cap="array_globals")
    check("indexing is bounds-checked: index 31 / -1 / a slice raise (C++ undefined behaviour must never pass), reads and writes",
          all(lam(c)[0] == "raise" and isinstance(lam(c)[1], H.FbbNotModelled) for c in (
              "id(u) = id(w)[31];", "id(w)[31] = 1;", "int i = -1; id(u) = id(w)[i];", "int i = -1; id(w)[i] = 1;")),
          cap="array_globals")
    s = new_sim()
    s.run_lambda("std::array<uint16_t, 31> c{}; c[1] = 7; id(w) = c; c[1] = 8; id(u) = id(w)[1]; id(h) = c[1];")
    check("value semantics: assigning a local to an array global COPIES (a later store to the local does not leak); the "
          "global object keeps its identity (in-place copy), so a reference to it sees the new value",
          (s.g["u"], s.g["h"]) == (7, 8), cap="array_globals")
    s = new_sim()
    s.run_lambda("auto &r = id(w); r[0] = 11; auto c = id(w); c[0] = 3; id(u) = id(w)[0]; id(h) = c[0];")
    check("`auto &r = id(g)` ALIASES the global; `auto c = id(g)` COPIES it", (s.g["u"], s.g["h"]) == (11, 3),
          cap="array_globals")
    res = lam("id(w) = std::array<uint16_t, 31>{}; id(u) = id(w)[0];", ("u",))
    check("assignment from a std::array<T, N>{} temporary zeroes the global", res[0] == "ok" and res[1]["u"] == 0,
          cap="array_globals")
    check("assigning an array of the wrong length / a scalar to an array global raises",
          all(isinstance(lam(c)[1], H.FbbNotModelled) for c in (
              "std::array<uint16_t, 4> c{}; id(w) = c;", "id(w) = 5;", "id(by) = id(w);")), cap="array_globals")
    s = new_sim()
    s.run_lambda("id(w)[2] = 9; id(w)[2] += 5; id(w)[2]++; id(w)[2] <<= 1; id(u) = id(w)[2];")
    check("compound assignment / ++ / <<= on an array element wrap at the element width", s.g["u"] == 30, cap="array_globals")
    sn = H.FbbSim(mkfw(BASE_G))
    sn.g["w"][5] = 4
    cp = sn.g["w"].copy()
    cp[5] = 9
    import copy as _copy
    check("FbArray: copy() / copy.copy / deepcopy give independent arrays; structural changes (append, pop, ...) and "
          "slices raise; fill / assign_from / to_bytes work",
          sn.g["w"][5] == 4 and _copy.copy(sn.g["w"])[5] == 4 and _copy.deepcopy(sn.g["w"]) == sn.g["w"]
          and all(raises(lambda f=f: f()) is not None for f in (
              lambda: sn.g["w"].append(1), lambda: sn.g["w"].pop(), lambda: sn.g["w"].__setitem__(slice(0, 2), [1, 2]),
              lambda: sn.g["w"].__delitem__(0), lambda: sn.g["w"].extend([1])))
          and (sn.g["by"].fill(300), sn.g["by"][0])[1] == 44 and sn.g["by"].to_bytes()[:2] == bytes([44, 44]),
          cap="array_globals")

    # =======================================================================
    print("[3] transpiler gaps: casts, constexpr, loops, local arrays, sizeof, std::string, compound ops, ++ --, switch")
    # =======================================================================
    CASES = [
        ("static_cast narrows", "id(u) = static_cast<uint16_t>(70000);", {"u": 4464}),
        ("cast chain (uint8_t) then (uint32_t)", "id(u) = (uint32_t) (uint8_t) 300;", {"u": 44}),
        ("(unsigned long long) and a shift on uint64_t", "id(u64) = (unsigned long long) 5 << 40;", {"u64": 5497558138880}),
        ("(unsigned long), (unsigned), (int), (bool)", "id(u) = (unsigned long) 5 + (unsigned) 2 + (int) 3.9f; id(b) = (bool) 7;",
         {"u": 10, "b": True}),
        ("constexpr and static const locals", "constexpr uint32_t K = 5; static const uint32_t J = 7; id(u) = K * 2 + J;",
         {"u": 17}),
        ("uint8_t narrowing on a typed local", "uint8_t x = 300; id(u) = x;", {"u": 44}),
        ("brace-initialised scalars", "uint16_t k{5}; uint16_t j{}; id(h) = k + j;", {"h": 5}),
        ("uninitialised local array, then stores", "uint16_t x[31]; x[3] = 70000; id(u) = x[3];", {"u": 4464}),
        ("local array with an initialiser list", "uint16_t x[] = {1, 2, 3}; id(u) = x[0] + x[2];", {"u": 4}),
        ("std::array local, zero-init and brace list", "std::array<uint16_t, 31> c{}; c[2] = 9; std::array<uint8_t, 4> d = {1, 2, 3}; "
         "id(u) = c[2] + d[2] + d[3];", {"u": 12}),
        ("local copy from a global does not alias", "std::array<uint16_t, 31> c = id(w); c[0] = 5; id(u) = id(w)[0];", {"u": 0}),
        ("const reference to a global", "const std::array<uint16_t, 31> &r = id(w); id(u) = r[0] + r.size();", {"u": 31}),
        ("while", "uint32_t t = 0; while (t < 5) { t++; } id(u) = t;", {"u": 5}),
        ("while with continue and break", "uint32_t t = 0, s = 0; while (true) { t++; if (t == 3) continue; if (t > 6) break; s += t; } "
         "id(u) = s;", {"u": 18}),
        ("do ... while", "uint32_t t = 0; do { t += 2; } while (t < 7); id(u) = t;", {"u": 8}),
        ("for with continue (the step still runs)", "uint32_t s = 0; for (int i = 0; i < 10; i++) { if (i % 2) continue; s += i; } "
         "id(u) = s;", {"u": 20}),
        ("for with break", "uint32_t s = 0; for (int i = 0; i < 10; i++) { if (i == 4) break; s += i; } id(u) = s;", {"u": 6}),
        ("nested for / continue binds to the inner loop", "uint32_t s = 0; for (int i = 0; i < 3; i++) { for (int j = 0; j < 3; j++) "
         "{ if (j == 1) continue; s += 1; } } id(u) = s;", {"u": 6}),
        ("for filling an array global through size()", "for (size_t k = 0; k < id(w).size(); k++) { id(w)[k] = k * 2; } id(u) = id(w)[30];",
         {"u": 60}),
        ("range-for over an array", "uint32_t s = 0; for (const auto &x : id(w)) { s += x + 1; } id(u) = s;", {"u": 31}),
        ("compound ops << >> ^ % * /", "uint32_t x = 5; x <<= 2; x ^= 3; x %= 7; x *= 3; x /= 2; id(u) = x;", {"u": 3}),
        ("prefix / postfix ++ as statements", "++id(u); id(u)++; ++id(u);", {"u": 3}),
        ("postfix ++ as an expression returns the old value", "uint32_t k = id(u)++; id(h) = k;", {"u": 1, "h": 0}),
        ("prefix ++ as an expression returns the new value", "uint32_t k = ++id(u); id(h) = k;", {"u": 1, "h": 1}),
        ("~ and unary +", "id(u) = ~0u; id(h) = ~5 & 0xFF; id(n) = +3;", {"u": 4294967295, "h": 250, "n": 3}),
        ("sizeof of types", "id(u) = sizeof(uint16_t) + sizeof(uint64_t) + sizeof(unsigned long long);", {"u": 18}),
        ("sizeof of array globals / locals", "uint16_t x[7]; id(u) = sizeof(id(w)) + sizeof(id(by)) + sizeof(x);", {"u": 62 + 96 + 14}),
        ("sizeof of a char buffer in snprintf", 'char buf[16]; snprintf(buf, sizeof(buf), "%u-%s", 5u, "a"); id(s) = buf;', {"s": "5-a"}),
        ("std::string +, += and a ternary", 'std::string a = "x"; std::string c = a + "yz"; a += "yz"; a += a; '
         'id(s) = (a + c).c_str();', {"s": "xyzxyzxyz"}),
        ("std::string global concatenation stays a std::string", 'id(s) = "ab"; id(s) = id(s) + "cd"; id(n) = id(s).size();',
         {"s": "abcd", "n": 4}),
        ("std::to_string / substr / find / npos", 'std::string a = "abcdef"; id(s) = a.substr(2, 3) + std::to_string(id(u) + 5); '
         'id(b) = a.find("z") == std::string::npos; id(b2) = a.find("cd") == 2;', {"s": "cde5", "b": True, "b2": True}),
        ("a ternary on strings", 'id(s) = id(b) ? "A" : "B";', {"s": "B"}),
        ("std::string default / direct / brace construction", 'std::string a; a += "x"; std::string c("yz"); std::string d{"w"}; '
         'std::string e2{}; uint32_t k(5); id(s) = a + c + d + e2; id(u) = k;', {"s": "xyzw", "u": 5}),
        ("switch with a block clause ending in break", "switch (id(u)) { case 0: { id(n) = 4; break; } default: { char c[8]; "
         'snprintf(c, sizeof(c), "x%u", 1u); id(s) = c; break; } }', {"n": 4}),
        ("switch default block", "id(u) = 9; switch (id(u)) { case 0: id(n) = 4; break; default: { id(n) = 5; break; } }", {"n": 5}),
        ("continue inside a switch inside a loop belongs to the loop", "uint32_t s = 0; for (int i = 0; i < 6; i++) { switch (i % 3) "
         "{ case 0: continue; case 1: s += 1; break; default: s += 10; break; } s += 100; } id(u) = s;", {"u": 422}),
        ("static_assert that holds", 'static_assert(1 + 1 == 2, "x"); id(u) = 1;', {"u": 1}),
        ("a lambda local still works", "auto f = [](uint32_t a) -> uint32_t { return a + 1; }; id(u) = f(4);", {"u": 5}),
        ("narrowing / promotion", "uint8_t a = 200, c = 100; id(h) = a + c; id(n) = a + c;", {"h": 300, "n": 44}),
        ("int32_t division truncates toward zero", "int32_t x = -5; id(e) = x / 2;", {"e": -2}),
    ]
    bad = []
    for name, code, want in CASES:
        res = lam(code, tuple(want))
        if res[0] != "ok" or any(res[1][k] != v for k, v in want.items()):
            bad.append((name, res[1] if res[0] == "ok" else f"{type(res[1]).__name__}: {res[1]}"))
    check(f"{len(CASES)} constructs the FB-B1 lambdas may use execute with C semantics", not bad, str(bad), cap="transpiler_gaps")
    NEG = [
        ("an undeclared identifier (enums / macros / `using namespace`)", "id(u) = LOAD_OK;"),
        ("`using namespace`", "using namespace ecco_fallback; id(u) = 1;"),
        ("an unqualified function (memcpy)", "uint16_t a[2]; memcpy(a, a, 4);"),
        ("a static local keeps state across invocations", "static uint32_t c = 0; id(u) = c;"),
        ("(char) - platform-dependent signedness", "id(u) = (char) 65;"),
        ("reinterpret_cast", "id(u) = reinterpret_cast<uint32_t>(5);"),
        ("sizeof of a scalar expression", "id(u) = sizeof(id(u));"),
        ("a non-const reference to a scalar", "uint32_t x = 1; uint32_t &r = x; r = 2;"),
        ("std::vector locals", "std::vector<uint16_t> v; id(u) = 1;"),
        ("a break that is neither a loop exit nor a switch end", "if (id(u) == 0) { break; }"),
        ("a break nested inside another statement of a switch clause (it would silently exit the LOOP)",
         "for (int i = 0; i < 3; i++) { switch (i) { case 1: if (i == 1) break; id(u) = 1; break; default: break; } }"),
        ("++ on a non-lvalue", "id(u) = (id(u) + 1)++;"),
        ("an unmodelled entity member", "id(u) = id(some_select).current_option();"),
        ("an array of an unmodelled element type", "float f[3]; id(u) = 1;"),
        ("`volatile`", "volatile uint32_t v = 1; id(u) = v;"),
    ]
    bad = [name for name, code in NEG if not isinstance(lam(code)[1], H.FbbNotModelled)]
    check(f"{len(NEG)} unsupported constructs raise FbbNotModelled (never skipped, never a silent default)", not bad, str(bad),
          cap="strictness")
    res = lam('static_assert(1 + 1 == 3, "bad"); id(u) = 1;')
    check("static_assert is evaluated at run time: a violated one fails the lambda", res[0] == "raise"
          and isinstance(res[1], AssertionError) and "bad" in str(res[1]), str(res), cap="transpiler_gaps")
    check("FbbNotModelled IS a _dump_sim.Unsupported (callers that catch the old class keep working); a plain-Sim "
          "Unsupported inside an FbbSim lambda is re-raised as FbbNotModelled",
          issubclass(H.FbbNotModelled, ds.Unsupported) and isinstance(lam("id(u) = 5 +;")[1], H.FbbNotModelled))

    # =======================================================================
    print("[4] unsigned wrap: millis() - x, typed globals / locals / casts, TTL arithmetic near 2^32")
    # =======================================================================
    s = new_sim()
    s.now_ms = (1 << 32) - 5
    s.run_lambda("id(u) = millis();")
    born = s.g["u"]
    s.advance(10)
    s.run_lambda("id(b) = (uint32_t) (millis() - id(u)) == 10; id(b2) = (millis() - id(u)) == 10; id(b3) = millis() < id(u); "
                 "id(h) = (uint32_t) (millis() - id(u));")
    check("millis() wraps at 2^32; `(uint32_t)(millis() - x)`, the UNCAST `millis() - x` and `millis() < x` are all wrap-safe "
          "(millis() and typed globals are unsigned VALUES, as in C)",
          born == (1 << 32) - 5 and s.g["b"] and s.g["b2"] and s.g["b3"] and s.g["h"] == 10, cap="unsigned_wrap")
    flips = []
    for age in (119_999, 120_000):
        s = new_sim()
        s.now_ms = (1 << 32) - 50_000
        s.run_lambda("id(u) = millis();")
        s.advance(age)
        s.run_lambda("id(b) = (uint32_t) (millis() - id(u)) >= 120000UL; id(b2) = millis() - id(u) >= 120000;")
        flips.append((s.g["b"], s.g["b2"]))
    check("the REVIEW TTL (120 000 ms) flips exactly between 119 999 and 120 000 ms across the millis() wrap, cast or uncast",
          flips == [(False, False), (True, True)], str(flips), cap="unsigned_wrap")
    s = new_sim()
    s.now_ms = 3
    s.run_lambda("id(b) = (millis() - 5) > 100; id(b2) = (5 - millis()) < 100; id(b3) = (millis() - 5u) == 4294967294u; "
                 "id(u) = millis_64() - 5;")
    check("millis() / millis_64() are unsigned values on their own: at millis() == 3, `millis() - 5` is 4294967294 (not -2), "
          "`5 - millis()` is 2, millis_64() - 5 wraps at 64 bits",
          (s.g["b"], s.g["b2"], s.g["b3"]) == (True, True, True) and s.g["u"] == 0xFFFFFFFE, str((s.g["b"], s.g["b2"], s.g["b3"], s.g["u"])),
          cap="unsigned_wrap")
    res = lam("uint32_t a = 3, c = 5; id(b) = (a - c) > 100; int32_t d = (int32_t) (a - c); id(e) = d; "
              "uint16_t x = 3, y = 5; id(b2) = (x - y) > 100; id(b3) = (id(u) - 1) > 100;", ("b", "e", "b2", "b3"))
    check("uint32_t locals / globals subtract with unsigned wrap (3 - 5 is 4294967294), a (int32_t) cast recovers -2, while "
          "uint16_t operands promote to int (3 - 5 is -2) - C's usual arithmetic conversions",
          res == ("ok", {"b": True, "e": -2, "b2": False, "b3": True}), str(res), cap="unsigned_wrap")
    res = lam("uint64_t v = 1; v <<= 63; v <<= 1; id(u64) = v; uint64_t m = 0xFFFFFFFFFFFFFFFFULL; id(h) = (m * 3) >> 62;",
              ("u64", "h"))
    check("uint64_t shifts and products wrap at 64 bits", res == ("ok", {"u64": 0, "h": 3}), str(res), cap="unsigned_wrap")
    u = T.U32(7)
    check("U32 / U64 value semantics: mixed width promotes to the wider unsigned, a negative plain int converts modulo 2^32 "
          "in a comparison, float arithmetic stays float, hashing / indexing / formatting behave as ints",
          type(u * T.U64(2)) is T.U64 and type(u + 1) is T.U32 and (u > -1) is False and (T.U32(0) - 1) == 0xFFFFFFFF
          and u / 2.0 == 3.5 and [10, 20, 30, 40, 50, 60, 70, 80][u] == 80 and "%08X|%d" % (u, u) == "00000007|7"
          and {T.U32(3): 1}[3] == 1 and T.c_div_t(T.U32(7), 2) == 3 and type(T.c_div_t(T.U32(7), 2)) is T.U32
          and T.c_mod_t(-7, 2) == -1, cap="unsigned_wrap")
    check("the unsigned wrap lives in the FB transpiler only: the plain _dump_sim.Sim keeps its plain-int behaviour",
          (lambda sim: (sim.run_lambda("id(b) = (id(u) - 1) > 100;"), sim.g["b"])[1])(ds.Sim(mkfw(BASE_G))) is False)

    # =======================================================================
    print("[5] the generic ecco_fbcap:: adapter over a Python mirror (test double) + byte-image helpers")
    # =======================================================================
    def cap_lam(code, show=(), **kw):
        return lam(code, show, fbcap=DBL, **kw)

    CAP_CASES = [
        ("constants", "id(u) = ecco_fbcap::CANDIDATE_TTL_MS + ecco_fbcap::BREAKER_MS;", {"u": 150000}),
        ("a text constant", "id(s) = ecco_fbcap::TXT_READY;", {"s": DBL.TXT_READY}),
        ("a constexpr array constant", "id(u) = ecco_fbcap::REGS[2] + ecco_fbcap::REGS.size();", {"u": 244 + len(DBL.REGS)}),
        ("a scoped enum member and an enum-typed local", "ecco_fbcap::Purpose p = ecco_fbcap::Purpose::REVIEW; id(n) = p; "
         "id(h) = (uint8_t) ecco_fbcap::Purpose::NONE;", {"n": 1, "h": 0}),
        ("POD: declare, store (C widths from CTYPES), read", "ecco_fbcap::Pod pod{}; pod.kind = 3; pod.word = 70000; pod.big = 70000; "
         "id(u) = pod.word; id(h) = pod.big;", {"u": 4464, "h": 4464}),
        ("POD: brace init in field order", "ecco_fbcap::Pod pod{2, 5}; id(u) = pod.kind + pod.word;", {"u": 7}),
        ("POD: an array field element", "ecco_fbcap::Pod pod{}; pod.words[1] = 9; id(u) = pod.words[1];", {"u": 9}),
        ("POD: a nested struct field chain (width hint on hhmm, none on watts: stored as given)",
         "ecco_fbcap::Pod pod{}; pod.slot.watts = 70000; pod.slot.hhmm = 70000; id(u) = pod.slot.hhmm; id(b) = pod.slot.watts == 70000;",
         {"u": 4464, "b": True}),
        ("a pure function taking a POD, returning a POD with an array field", "ecco_fbcap::Pod pod{}; pod.kind = 9; "
         "pod.words[1] = 77; pod.slot.watts = 5; ecco_fbcap::Verdict v = ecco_fbcap::decide(pod, 1000); id(b) = v.refused; "
         "id(u) = v.words[0] + v.words[30];", {"b": True, "u": 82}),
        ("`auto` and `const T` results", "ecco_fbcap::Pod pod{}; auto v = ecco_fbcap::decide(pod, 5); "
         "const ecco_fbcap::Verdict w = ecco_fbcap::decide(pod, 6); id(u) = v.code + w.code;", {"u": 11}),
        ("a returned array field assigned to an array global", "ecco_fbcap::Pod pod{}; pod.words[1] = 4; auto v = ecco_fbcap::decide(pod, 5); "
         "id(w) = v.words; id(u) = id(w)[0];", {"u": 4}),
        ("POD value semantics (copy on initialisation)", "ecco_fbcap::Pod a{}; a.kind = 1; ecco_fbcap::Pod c = a; c.kind = 2; "
         "id(u) = a.kind;", {"u": 1}),
        ("a namedtuple result", "auto p = ecco_fbcap::classify(4); id(u) = p.kind * 100 + p.basis;", {"u": 508}),
        ("an array argument is the LIVE array: the function fills it in place (C++ reference parameter)",
         "uint16_t v[53]; for (int i = 0; i < 53; i++) v[i] = i + 1; id(b) = ecco_fbcap::store_block_241(id(w), v); "
         "id(u) = id(w)[3] + id(w)[30];", {"b": True, "u": 29}),
        ("a functional out-parameter (HARNESS_OUT_PARAMS) is written back", "uint16_t v[3] = {5, 6, 7}; "
         "id(b) = ecco_fbcap::store_functional(id(w), v); id(u) = id(w)[1];", {"b": True, "u": 6}),
        ("first_diff over two array globals", "id(w2)[5] = 3; id(u) = ecco_fbcap::first_diff(id(w), id(w2));", {"u": 5}),
        ("a wrap-safe expiry predicate with U32 arguments", "uint32_t born = millis(); "
         "id(b) = ecco_fbcap::candidate_expired(millis() + 120000, born); id(b2) = ecco_fbcap::candidate_expired(millis() + 119999, born);",
         {"b": True, "b2": False}),
        ("a str result is a std::string", "std::string t = ecco_fbcap::epc_name(5); id(s) = t.c_str(); id(n) = t.size();",
         {"s": "VALID", "n": 5}),
        ("a TextBuf-like result keeps c_str() / size()", "id(s) = ecco_fbcap::refusal_text(7).c_str(); "
         "id(u) = ecco_fbcap::refusal_text(7).size(); auto t = ecco_fbcap::refusal_text(12); id(h) = t.size();",
         {"s": "REVIEW REFUSED - code 7", "u": 23, "h": 24}),
        ("an array alias (CaptureWords) as a type", "ecco_fbcap::CaptureWords cw{}; cw[3] = 5; id(w) = cw; id(u) = id(w)[3];", {"u": 5}),
        ("sizeof of a type with a HARNESS_SIZEOF hint", "id(u) = sizeof(ecco_fbcap::Pod);", {"u": 28}),
        ("a mirror written in plain Python (slice assignment, negative index) works on the live array; lambda code keeps "
         "the strict C++ indexing", "uint16_t v[3] = {1, 2, 3}; id(u) = ecco_fbcap::store_block_slices(id(w), v); id(h) = id(w)[3]; "
         "id(n) = id(w)[30];", {"u": 0, "h": 3, "n": 9}),
        ("a dict-returning mirror function becomes the record a lambda holds", "id(w)[0] = 2; id(w)[1] = 0x11; "
         "ecco_fallback::FallbackProfileV1 q = ecco_fbcap::make_profile_dict(id(w)); id(u) = q.reg244 + q.reg232; id(h) = q.schema;",
         {"u": 19, "h": 1}),
        ("a record stored into a dict-typed field, a std::array<uint8_t, N> into a bytes field (copy semantics), a nested "
         "ecco_fbdurable::ReadLatch dataclass in the result", "ecco_fallback::FallbackProfileV1 p{}; p.generation = 7; "
         "p.magic = ecco_fallback::PROFILE_MAGIC; ecco_fbcap::ReadIn ri{}; ri.p = p; ri.raw = id(by); p.generation = 9; "
         "ecco_fbcap::ReadOut o = ecco_fbcap::read_eval(ri); id(u) = o.gen; id(n) = o.latch.present_seen; id(h) = o.raw_len;",
         {"u": 7, "n": 1, "h": 96}),
        ("a str-subclass type and a std::string argument that keeps c_str()", 'ecco_fbcap::Txt t; id(u) = t.size(); '
         'id(s) = ecco_fbcap::echo_c(std::string("hi"));', {"u": 0, "s": "hi!"}),
        ("a header type with a numeric template argument (TextBuf<256>) - the argument is dropped",
         'ecco_fbcap::TextBuf<256> tb; tb.append("abc"); id(n) = tb.size(); id(s) = tb.c_str();', {"n": 3, "s": "abc"}),
    ]
    bad = []
    for name, code, want in CAP_CASES:
        res = cap_lam(code, tuple(want))
        if res[0] != "ok" or any(res[1][k] != v for k, v in want.items()):
            bad.append((name, res[1] if res[0] == "ok" else f"{type(res[1]).__name__}: {res[1]}"))
    check(f"{len(CAP_CASES)} adapter cases (constants, enums, PODs, arrays, functions, out-parameters, text, aliases) "
          "execute against the mirror", not bad, str(bad), cap="fbcap_adapter")
    CAP_NEG = [
        ("a missing constant", "id(u) = ecco_fbcap::NOT_THERE;", "ecco_fbcap::NOT_THERE"),
        ("a missing function", "id(u) = ecco_fbcap::not_there(1);", "ecco_fbcap::not_there"),
        ("a private name", "id(u) = ecco_fbcap::_private_helper;", "private"),
        ("an imported module", "id(u) = ecco_fbcap::dataclasses;", "module"),
        ("a missing enum member", "id(n) = ecco_fbcap::Purpose::NOPE;", "NOPE"),
        ("a missing POD field (store)", "ecco_fbcap::Pod pod{}; pod.nonsense = 1;", "nonsense"),
        ("a missing POD field (read)", "ecco_fbcap::Pod pod{}; id(u) = pod.nonsense;", "nonsense"),
        ("an array field index out of range", "ecco_fbcap::Pod pod{}; pod.words[4] = 9;", "out of range"),
        ("too many POD initialisers", "ecco_fbcap::Pod pod{1, 2, 3, 4, 5, 6, 7};", "initialisers"),
        ("sizeof without a HARNESS_SIZEOF hint", "id(u) = sizeof(ecco_fbcap::Verdict);", "HARNESS_SIZEOF"),
        ("an array result of the wrong length assigned to a global", "id(w2) = ecco_fbcap::make_words();", "3 elements"),
        ("a call the mirror rejects (wrong arity)", "id(u) = ecco_fbcap::epc_name(1, 2, 3);", "rejected"),
    ]
    bad = []
    for name, code, needle in CAP_NEG:
        res = cap_lam(code)
        if not (res[0] == "raise" and isinstance(res[1], H.FbbNotModelled) and needle in str(res[1])):
            bad.append((name, str(res[1])[:90]))
    check(f"{len(CAP_NEG)} adapter negative controls raise FbbNotModelled naming the offending name", not bad, str(bad),
          cap="fbcap_adapter")
    check("a mirror that cannot be imported raises FbbNotModelled on first use (not at construction), a module name string "
          "works, and the real mirror module is the default",
          (lambda sm: sm.g["u"] == 150000)((lambda x: (x.run_lambda("id(u) = ecco_fbcap::CANDIDATE_TTL_MS + ecco_fbcap::BREAKER_MS;"), x)[1])(
              new_sim(fbcap="_fbb1_fbcap_double")))
          and isinstance(raises(lambda: new_sim(fbcap="no_such_mirror_module").run_lambda("id(u) = ecco_fbcap::X;")), H.FbbNotModelled)
          and new_sim()._fbcap_spec is None, cap="fbcap_adapter")

    # byte-image helpers (the firmware keeps std::array<uint8_t, N> globals, never a struct global)
    GOLD = fp.seal_profile(fp.blank_profile(
        magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
        reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30], reg274_279=[1, 0, 1, 0, 0, 1],
        reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330], reg230=185, reg245=8000, reg247=1,
        reserved0=0, reserved1=0, binding=0))
    PB = fp.pack_profile(GOLD)
    K_P, K_W = fd.FALLBACK_PROFILE_KEY, fd.FAILBACK_PROVISION_KEY
    W7 = fd.pack_provision(fd.make_provision(7, GOLD["binding"], 6, 0x6666, K_P, 1, fd.PROV_OP_SAVE))
    s = new_sim([G("fbp_bytes", "std::array<uint8_t, 96>"), G("fbw_bytes", "std::array<uint8_t, 48>"), G("ld", "uint8_t", "0"),
                 G("gen", "uint32_t", "0"), G("same", "bool", "false"), G("bind", "uint64_t", "0"), G("df", "uint8_t", "0")])
    s.nvs_direct.put(K_P, PB)
    s.nvs_direct.put(K_W, W7)
    s.run_lambda(
        "ecco_fbdurable::EspNvs nvs; ecco_fallback::FallbackProfileV1 p; ecco_fbdurable::FailbackProvisionV1 w;"
        "ecco_fbdurable::ReadDiag dp; ecco_fbdurable::ReadDiag dw;"
        "id(ld) = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, p, dp);"
        "ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, w, dw);"
        "id(fbp_bytes) = ecco_fallback::encode_profile(p);"
        "id(fbw_bytes) = ecco_fbdurable::encode_provision(w);"
        "ecco_fallback::FallbackProfileV1 back = ecco_fallback::decode_profile(id(fbp_bytes));"
        "ecco_fbdurable::FailbackProvisionV1 wback = ecco_fbdurable::decode_provision(id(fbw_bytes));"
        "id(gen) = back.generation;"
        "id(bind) = back.binding;"
        "id(same) = ecco_fbdurable::records_equal(back, p) && ecco_fbdurable::records_equal(wback, w) "
        "&& ecco_fbdurable::bytes_equal(id(fbp_bytes), ecco_fallback::encode_profile(back));"
        "id(df) = ecco_fallback::profile_defect(back);")
    check("the byte images: encode_profile / encode_provision fill std::array<uint8_t, 96 / 48> globals, decode_* rebuild the "
          "record, records_equal / bytes_equal compare, profile_defect works on the decoded copy",
          bytes(list(s.g["fbp_bytes"])) == PB and bytes(list(s.g["fbw_bytes"])) == W7 and s.g["gen"] == 7
          and s.g["bind"] == GOLD["binding"] and s.g["same"] is True and s.g["df"] == fp.PROFILE_DEFECT_NONE,
          cap="byte_image_helpers")
    res = lam("ecco_fallback::FallbackProfileV1 p; id(u) = ecco_fallback::ctx_matches(244, 2, 2) + 10 * ecco_fallback::ctx_matches(232, 0x11, 0x01) "
              "+ 100 * ecco_fallback::ctx_matches(250, 5, 5);", ("u",))
    check("ctx_matches has the C++ semantics (false for a non-CTX register, where the Python mirror raises)",
          res == ("ok", {"u": 110}), str(res), cap="byte_image_helpers")
    check("byte-image strictness: decode of the wrong length, records_equal of two kinds, an unmodelled FB-A / FB-B0 name raise",
          all(isinstance(lam(c)[1], H.FbbNotModelled) for c in (
              "std::array<uint8_t, 4> b{}; ecco_fallback::decode_profile(b);",
              "ecco_fallback::FallbackProfileV1 p; ecco_fbdurable::FailbackProvisionV1 w; ecco_fbdurable::records_equal(p, w);",
              "ecco_fallback::nonexistent_fn(1);", "ecco_fbdurable::nonexistent_fn(1);")), cap="byte_image_helpers")

    # =======================================================================
    print("[6] ecco_durable::ValidMarker probes through the direct NVS (key = FNV-1 32 of the tag)")
    # =======================================================================
    TAG = ds.Durable.FREE_POWER_VALID_TAG
    KEY = fp.tag_key_fnv1_32(TAG)
    PROBE = ("ecco_fbdurable::EspNvs nvs; ecco_durable::ValidMarker marker{}; ecco_fbdurable::ReadDiag d{}; "
             "uint8_t ld = ecco_fbdurable::read_direct_t(nvs, ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), marker, d); "
             "id(n) = ld; id(u) = marker.magic; id(h) = marker.state; id(e) = d.probe_err;")
    PG = [G("u", "uint32_t", "0"), G("n", "uint8_t", "0"), G("h", "uint16_t", "0"), G("e", "int32_t", "0")]
    MAGIC = ds.Durable.VALID_MARKER_MAGIC
    ABS, OK, WSZ, RERR, UNAV = fp.LOAD_ABSENT, fp.LOAD_OK, fp.LOAD_WRONG_SIZE, fp.LOAD_READ_ERROR, fp.LOAD_STORAGE_UNAVAILABLE
    PROBES = [
        ("absent", lambda x: None, (ABS, 0, 0), ["get"]),
        ("CLEAR marker", lambda x: x.seed_marker(TAG, 0), (OK, MAGIC, 0), ["get", "read"]),
        ("RESTORE_REQUIRED marker", lambda x: x.seed_marker(TAG, 1), (OK, MAGIC, 1), ["get", "read"]),
        ("PENDING_CLEAR marker", lambda x: x.seed_marker(TAG, 2), (OK, MAGIC, 2), ["get", "read"]),
        ("wrong size", lambda x: x.seed_marker(TAG, 1, size=24), (WSZ, 0, 0), ["get"]),
        ("CRC-bad chunk -> READ_ERROR (the read erases it)", lambda x: x.seed_marker(TAG, 1, crc_ok=False), (RERR, 0, 0),
         ["get", "read"]),
        ("storage not initialised", lambda x: (x.seed_marker(TAG, 1), setattr(x.nvs_direct, "unavailable", True)), (UNAV, 0, 0),
         ["get"]),
        ("zero handle: no NVS operation at all", lambda x: (x.seed_marker(TAG, 1), setattr(x.nvs_direct, "handle_value", 0)),
         (UNAV, 0, 0), []),
        ("bad magic, right size", lambda x: x.seed_marker(TAG, 1, magic=0xDEADBEEF), (OK, 0xDEADBEEF, 1), ["get", "read"]),
    ]
    bad = []
    for label, setup, want, ops in PROBES:
        sm = H.FbbSim(mkfw(PG))
        setup(sm)
        sm.run_lambda(PROBE)
        got = (sm.g["n"], sm.g["u"], sm.g["h"])
        if got != want or [o[0] for o in sm.nvs_direct.ops] != ops:
            bad.append((label, got, sm.nvs_direct.ops))
    check("a ValidMarker probe maps the NVS state to (load, magic, state) with the exact op sequence (probe, then data); a "
          "marker seeded through the direct NVS is read back through read_direct_t", not bad, str(bad), cap="marker_probes")
    sm = H.FbbSim(mkfw(PG))
    sm.seed_marker(TAG, 1, crc_ok=False)
    loads = []
    for _ in range(3):
        sm.run_lambda(PROBE)
        loads.append(sm.g["n"])
    check("two-step read side effects through a marker probe: READ_ERROR, READ_ERROR, then ABSENT (a re-probe would turn an "
          "unreadable marker into 'clear') - why the REVIEW latch is never cleared; NVS reads are counted from nvs_direct.ops",
          loads == [RERR, RERR, ABS] and sm.nvs_direct.read_probe_count() == 3
          and [o[0] for o in sm.nvs_direct.ops] == ["get", "read", "get", "read", "get"], str(loads), cap="marker_probes")
    sm = H.FbbSim(mkfw(PG))
    sm.seed_marker(TAG, 1, direct=False)
    sm.run_lambda(PROBE)
    probe_load = sm.g["n"]
    sm.run_lambda("ecco_durable::ValidMarker m{}; id(n) = ecco_durable::load_record_status(ecco_durable::key_for("
                  "ecco_durable::FREE_POWER_VALID_TAG), m); id(h) = m.state;")
    check("the boot lambda's legacy tag-keyed store and the REVIEW probe's direct NVS are DIFFERENT stores: a ghost marker "
          "(legacy RESTORE_REQUIRED, direct ABSENT) reads LOAD_OK/1 to the boot load and ABSENT to the probe; seed_marker "
          "builds either side or both, and mirror_markers_to_direct() syncs them",
          probe_load == ABS and (sm.g["n"], sm.g["h"]) == (OK, 1) and sm.mirror_markers_to_direct() == 1
          and (lambda x: (x.run_lambda(PROBE), x.g["h"])[1])(sm) == 1, cap="marker_probes")
    check("read_direct_t of another ecco_durable record kind is not modelled (loud), and the marker byte layout is "
          "{uint32 magic; uint8 state} + 3 padding = 8 bytes",
          isinstance(lam("ecco_durable::Reg244SnapshotData r{}; ecco_fbdurable::EspNvs nvs; ecco_fbdurable::ReadDiag d{}; "
                         "ecco_fbdurable::read_direct_t(nvs, 5, r, d);")[1], H.FbbNotModelled)
          and H.FbbSim.marker_bytes(MAGIC, 1) == MAGIC.to_bytes(4, "little") + bytes([1, 0, 0, 0])
          and len(H.FbbSim.marker_bytes(MAGIC, 1)) == 8, cap="marker_probes")
    check("sizeof(ecco_durable::ValidMarker) / the FB records are known (8 / 96 / 80 / 48)",
          lam("id(u) = sizeof(ecco_durable::ValidMarker);", ("u",)) == ("ok", {"u": 8})
          and lam("id(u) = sizeof(ecco_fallback::FallbackProfileV1) + sizeof(ecco_fbdurable::FailbackProvisionV1);", ("u",))
          == ("ok", {"u": 144}), cap="marker_probes")

    # =======================================================================
    print("[7] the discrete-event engine: ordering rules, asynchronous scripts, waits, delays, buttons, bounded runs")
    # =======================================================================
    EG = [G("flag", "bool", "false"), G("gen", "uint32_t", "0"), G("n", "uint8_t", "0"), G("m", "uint8_t", "0"),
          G("trace", "std::string", '""'), G("u", "uint32_t", "0"), G("b", "bool", "false")]
    ADD = lambda c: L(f'id(trace) = id(trace) + "{c}";')  # noqa: E731
    ESCRIPTS = [
        S("waiter", [L("id(n) = 1;"), {"wait_until": {"condition": L("return id(flag);"), "timeout": "1s"}},
                     L("id(n) = 2; id(gen) = millis();")]),
        S("forever", [{"wait_until": {"condition": L("return id(flag);")}}, L("id(n) = 5;")]),
        S("delayer", [ADD("d0,"), {"delay": "250ms"}, L('id(trace) = id(trace) + "d1,"; id(gen) = millis();')]),
        S("outer", [{"script.execute": "delayer"}, L('id(m) = 9; id(trace) = id(trace) + "o,";')]),
        S("selfcheck", [L("id(b) = id(selfcheck).is_running();")]),
        S("tail_gate", [L("id(n) = id(delayer).is_running() ? 1 : 0;"), {"script.execute": {"id": "delayer"}}]),
        S("parametrised", [L("id(u) = 1;")], parameters={"reason": "string"}),
        S("queued_mode", [L("id(u) = 1;")], mode="queued"),
        S("thrower", [{"delay": "100ms"}, L("id(u) = 1 / id(n);")]),
        S("handler_parks", [READ(230, 1, ok="id(u) = 1;")]),
    ]
    ESCRIPTS[-1]["then"][0]["modbus_client.read_holding_registers"]["on_response"] = {"then": [{"delay": "1s"}]}
    EBUTTONS = [{"platform": "template", "id": "btn", "name": "B", "on_press": [{"script.execute": "delayer"}]},
                {"platform": "template", "id": "btn_empty", "name": "E"}]
    EFW = mkfw(EG, ESCRIPTS, EBUTTONS)

    def esim():
        return H.FbbSim(EFW)

    # -- the ordering rules
    s = esim()
    t0 = s.now_ms
    order = []
    rec = lambda tag: (lambda sim: order.append(tag))  # noqa: E731
    s.at(t0 + 50, rec("loop-1"), prio=E.P_LOOP)
    s.at(t0 + 50, rec("sched-1"), prio=E.P_SCHED)
    s.at(t0 + 50, rec("ext-1"))
    s.at(t0 + 50, rec("ext-2"))
    s.at(t0 + 50, rec("loop-2"), prio=E.P_LOOP)
    s.at(t0 + 40, rec("early"))
    s.run_until(t0 + 49)
    mid = list(order)
    s.run_until(t0 + 50)
    check("event ordering: by time, then priority (injected world events, then the scheduler, then the component loop), then "
          "insertion order; run_until(t) runs events at exactly t and stops short of t+1",
          mid == ["early"] and order == ["early", "ext-1", "ext-2", "sched-1", "loop-1", "loop-2"] and s.now_ms == t0 + 50
          and (E.P_EXTERNAL, E.P_SCHED, E.P_LOOP) == (0, 1, 2), str(order), cap="async_scripts")

    # -- start_script: runs to the first park and returns
    s = esim()
    t0 = s.now_ms
    task = s.start_script("waiter")
    snap = (s.g["n"], "waiter" in s.running, task.parked, s.now_ms - t0, task.done)
    s.run_for(999)
    still = (task.done, s.g["n"], "waiter" in s.running)
    s.run_for(1)
    check("start_script (`script.execute`) runs until the FIRST wait_until and returns: the script is running, parked in a wait; "
          "nothing else happens until time passes; a wait with a 1 s timeout CONTINUES at exactly +1000 ms, the script then "
          "finishes and stops being 'running'",
          snap == (1, True, "wait", 0, False) and still == (False, 1, True) and task.done and task.finished_ms == t0 + 1000
          and s.g["n"] == 2 and s.g["gen"] == (t0 + 1000) and "waiter" not in s.running and task.timed_out is True,
          str((snap, still, task)), cap="async_scripts")
    s = esim()
    t0 = s.now_ms
    task = s.start_script("waiter")
    s.at(t0 + 300, lambda sim: sim.g.__setitem__("flag", True))
    s.run_for(2000)
    a = task.finished_ms - t0
    s = esim()
    t0 = s.now_ms
    task = s.start_script("waiter")
    s.at(t0 + 305, lambda sim: sim.g.__setitem__("flag", True))
    s.run_for(2000)
    b = task.finished_ms - t0
    check("a wait_until condition is polled every tick_ms (10 ms) in the component loop AFTER injected events: a flag set at "
          "+300 ends the wait at +300, one set at +305 at +310 (before the 1 s timeout either way)", (a, b) == (300, 310),
          str((a, b)), cap="async_scripts")
    s = esim()
    s.g["flag"] = True
    t0 = s.now_ms
    task = s.start_script("waiter")
    check("a wait_until whose condition already holds does not park: the script completes inside start_script",
          task.done and s.g["n"] == 2 and s.now_ms == t0 and "waiter" not in s.running, cap="async_scripts")
    s = esim()
    s.start_script("forever")
    err = raises(lambda: s.run_until_idle(max_ms=5000), T.FbbTimeout)
    s.g["flag"] = True
    el = s.run_until_idle()
    check("a wait_until WITHOUT a timeout parks forever (no MAX_WAIT_MS failure like the blocking loop); run_until_idle raises "
          "FbbTimeout while it is parked, and returns once the condition holds", err is not None and s.g["n"] == 5 and el <= 20,
          str(err), cap="async_scripts")
    s = esim()
    t0 = s.now_ms
    task = s.start_script("delayer")
    check("delay: parked for exactly its duration (+250 ms), script running meanwhile",
          task.parked == "delay" and "delayer" in s.running and (s.run_for(249), "delayer" in s.running)[1]
          and (s.run_for(1), task.done and task.finished_ms == t0 + 250 and s.g["trace"] == "d0,d1,")[1],
          cap="async_scripts")
    # -- script.execute inside a script: the caller continues at the callee's first park
    s = esim()
    s.start_script("outer")
    mid = (s.g["m"], str(s.g["trace"]), "outer" in s.running, "delayer" in s.running)
    s.run_for(250)
    check("`script.execute` returns at the callee's first park, exactly like ESPHome: the CALLER continues at once (and "
          "finishes) while the callee is still parked - the caller's trailing actions run BEFORE the callee's tail",
          mid == (9, "d0,o,", False, True) and s.g["trace"] == "d0,o,d1," and not s.running, str(mid), cap="async_scripts")
    s = esim()
    s.start_script("tail_gate")
    during = ("tail_gate" in s.running, "delayer" in s.running)
    s.start_script("tail_gate")
    n2 = s.g["n"]
    s.run_for(250)
    check("a gate whose LAST action is `script.execute` of a parking script is NOT running while the callee is parked "
          "(the FB-B1 gate / dispatch shape: another gate lambda sees only the dispatch as running); re-entry of the callee "
          "is dropped by mode: single", during == (False, True) and n2 == 1 and s.g["trace"] == "d0,d1,"
          and len([x for x in s.executed if x[0] == "delayer"]) == 2, str((during, n2, s.g["trace"])), cap="async_scripts")
    s = esim()
    a1 = s.start_script("delayer")
    a2 = s.start_script("delayer")
    s.run_for(250)
    a3 = s.start_script("delayer")
    check("mode: single drops a second execute while running (returns None, still logged in sim.executed - the Z9 evidence), "
          "and accepts one after the first finished", a1 is not None and a2 is None and a3 is not None
          and [x[0] for x in s.executed] == ["delayer"] * 3 and s.g["trace"] == "d0,d1,d0,", s.g["trace"], cap="async_scripts")
    s = esim()
    s.start_script("selfcheck")
    ran = s.g["b"]
    check("is_running() is true inside the script itself and false afterwards", ran is True and "selfcheck" not in s.running,
          cap="async_scripts")
    # -- buttons
    s = esim()
    t1 = s.press_button("btn")
    t2 = s.press_button("btn")
    check("a button press runs its on_press actions as an automation (not a script: two presses run side by side; the "
          "callee script drops the second execute); the pressed script is running until it finishes",
          t1.label == "button:btn" and t1.done and t2.done and "delayer" in s.running and s.g["trace"] == "d0,"
          and (s.run_for(250), s.g["trace"])[1] == "d0,d1,", cap="async_scripts")
    check("`id(button).press()` from a lambda starts the same automation",
          (lambda x: (x.run_lambda("id(btn).press();"), "delayer" in x.running)[1])(esim()), cap="async_scripts")
    check("strict: pressing an unknown button, a button without on_press, executing an unknown script, a script that needs a "
          "parameter, a non-`single` script mode raise FbbNotModelled",
          all(isinstance(raises(f), H.FbbNotModelled) for f in (
              lambda: esim().press_button("nope"), lambda: esim().press_button("btn_empty"),
              lambda: esim().start_script("nope"), lambda: esim().start_script("parametrised"),
              lambda: esim().start_script("queued_mode"))) and esim().start_script("parametrised", {"reason": "x"}).done,
          cap="strictness")
    # -- errors, handlers, clock
    s = esim()
    task = s.start_script("thrower")
    err = raises(lambda: s.run_for(200), ZeroDivisionError)
    check("an exception inside a lambda propagates out of run_for (the test sees it); the failed script is no longer running",
          err is not None and task.done and isinstance(task.result_error, ZeroDivisionError) and "thrower" not in s.running,
          cap="async_scripts")
    s = esim()
    check("a Modbus handler that parks (delay / wait_until) raises FbbNotModelled - ESPHome forbids it - in both delivery modes",
          isinstance(raises(lambda: s.start_script("handler_parks")), H.FbbNotModelled)
          and isinstance(raises(lambda: (lambda x: (x.set_modbus_mode("deferred"), x.start_script("handler_parks"), x.run_for(500)))(esim())),
                         H.FbbNotModelled), cap="strictness")
    s = esim()
    s.now_ms = 5_000
    t0 = s.now_ms
    task = s.start_script("waiter")
    s.at(t0 + 5000, lambda sim: sim.g.__setitem__("u", 77))
    s.rebase_clock((1 << 32) - 100)
    base = s.now_ms
    s.run_for(1000)
    check("rebase_clock jumps the clock (to just before the millis() wrap) keeping every pending event's offset: the 1 s wait "
          "ends at +1000, millis() wrapped to 900 meanwhile, the +5000 event is still ahead",
          base == (1 << 32) - 100 and task.finished_ms == base + 1000 and s.g["gen"] == 900 and s.g["u"] == 0
          and (s.run_for(4000), s.g["u"])[1] == 77, str((base, task, s.g["gen"])), cap="unsigned_wrap")
    s = esim()
    t0 = s.now_ms
    s.execute("delayer")
    el = s.now_ms - t0
    s.g["flag"] = False
    s.at(s.now_ms + 100, lambda sim: sim.g.__setitem__("flag", True))
    t1 = s.now_ms
    s.execute("waiter")
    check("the FB-B0 blocking execute() still works next to the engine (waits poll the engine clock, so injected events fire "
          "during them): delay 250 ms; a wait ended by an event at +100", el == 250 and s.now_ms - t1 == 100, str((el, s.now_ms - t1)),
          cap="async_scripts")
    check("run_until_done on a script that never ran / a finished task is well-defined; FbbTimeout is an AssertionError",
          isinstance(raises(lambda: esim().run_until_done("delayer")), H.FbbNotModelled)
          and (lambda x: (x.start_script("delayer"), x.run_until_done("delayer"), x.task_of("delayer").done)[2])(esim())
          and issubclass(T.FbbTimeout, AssertionError), cap="async_scripts")

    # =======================================================================
    print("[8] deferred Modbus frames, the hub model, foreign frames, late callbacks")
    # =======================================================================
    MG = [G("u", "uint32_t", "0"), G("n", "uint8_t", "0"), G("cnt", "uint8_t", "0"), G("x", "uint8_t", "0")]
    RD = READ(230, 3, ok="id(u) = values.size(); id(n) = values[1]; id(cnt)++;", err="id(n) = exception_code; id(cnt)++;",
              nores="id(n) = 200; id(cnt)++;", notsent="id(n) = 201; id(cnt)++;", custom="id(n) = 202; id(cnt)++;")
    MFW = mkfw(MG, [S("reader", [RD]), S("holder", [{"delay": "400ms"}]), S("writer", [{
        "modbus_client.write_multiple_registers": {"modbus_id": "inverter_modbus", "address": 1, "start_address": 244,
                                                   "values": ds.LambdaStr("return std::vector<uint16_t>{2};")}}])])

    def msim(latency=120):
        m = H.FbbSim(MFW)
        m.bank.update({230: 10, 231: 20, 232: 30})
        m.set_modbus_mode("deferred", latency)
        return m

    s = msim()
    t0 = s.now_ms
    s.start_script("reader")
    q0 = (s.hub.tx_buffer_empty(), s.hub.tx_blocked(), s.g["cnt"], len(s.modbus_log))
    s.run_until(t0)
    q1 = (s.hub.tx_buffer_empty(), s.hub.tx_blocked(), s.g["cnt"], len(s.modbus_log))
    s.run_for(119)
    q2 = (s.hub.tx_blocked(), s.g["cnt"])
    s.run_for(1)
    q3 = (s.hub.tx_buffer_empty(), s.hub.tx_blocked(), s.g["cnt"], s.g["u"], s.g["n"])
    w = s.wire_log[0]
    check("deferred frame: queued (tx_buffer_empty false) -> on the wire (empty, tx_blocked true, logged) -> its handler runs "
          "`latency_ms` later with values.size() / values[i], and the hub is idle again; the script that issued it had long "
          "finished", q0 == (False, False, 0, 0) and q1 == (True, True, 0, 1) and q2 == (True, 0) and q3 == (True, False, 1, 3, 20)
          and (w.origin, w.addr, w.count, w.t_queued - t0, w.t_start - t0, w.t_end - t0) == ("fw", 230, 3, 0, 0, 120)
          and [e[0] for e in s.events if e[0] in ("read", "deliver")] == ["read", "deliver"], str((q0, q1, q2, q3, w)),
          cap="deferred_frames")
    s = msim()
    s.start_script("reader")
    s.run_for(60)
    s.bank[231] = 99
    s.run_for(100)
    first = s.g["n"]
    s.start_script("reader")
    s.run_for(130)
    check("the register bank is snapshotted when the frame goes on the wire: a mutation during its flight is not seen by it, "
          "the next frame sees it", first == 20 and s.g["n"] == 99, cap="deferred_frames")
    s = msim()
    t0 = s.now_ms
    s.start_script("reader")
    s.start_script("reader")
    s.start_script("reader")
    s.run_for(500)
    check("frames go on the wire one at a time in FIFO order (hub idle -> next frame starts at the same millisecond)",
          [(w.t_start - t0, w.t_end - t0) for w in s.wire_log] == [(0, 120), (120, 240), (240, 360)] and s.g["cnt"] == 3,
          cap="deferred_frames")
    s = msim()
    s.hub.turnaround_ms = 30
    t0 = s.now_ms
    s.start_script("reader")
    s.start_script("reader")
    s.run_until(t0 + 125)
    blocked_gap = s.hub.tx_blocked()
    s.run_for(500)
    check("turnaround_ms models the inter-frame gap: tx_blocked stays true after a reply and the next frame starts 30 ms later",
          [(w.t_start - t0, w.t_end - t0) for w in s.wire_log] == [(0, 120), (150, 270)] and blocked_gap, cap="deferred_frames")
    # outcomes
    results = {}
    for label, spec in (("ok", "ok"), ("error", E.FrameSpec(outcome="error", exception_code=3)), ("error-default", "error"),
                        ("no_response", "no_response"), ("custom_response", "custom_response")):
        s = msim()
        s.queue_frames(spec)
        s.start_script("reader")
        s.run_for(200)
        results[label] = (s.g["cnt"], s.g["n"])
    s = msim()
    s.exception_code = 6
    s.queue_frames("error")
    s.start_script("reader")
    s.run_for(200)
    results["error-sim"] = (s.g["cnt"], s.g["n"])
    check("all five outcomes reach their handlers in deferred mode; on_error sees exception_code (per frame, else "
          "sim.exception_code, default 2)",
          results == {"ok": (1, 20), "error": (1, 3), "error-default": (1, 2), "no_response": (1, 200),
                      "custom_response": (1, 202), "error-sim": (1, 6)}, str(results), cap="modbus_handlers")
    s = msim()
    s.queue_frames("not_sent")
    s.start_script("reader")
    check("not_sent never reaches the wire: its handler runs synchronously at the action in either mode, the hub stays idle, "
          "the read is logged in modbus_log but not in wire_log",
          s.g["cnt"] == 1 and s.g["n"] == 201 and s.hub.tx_buffer_empty() and not s.hub.tx_blocked() and not s.wire_log
          and [e[3] for e in s.modbus_log] == ["not_sent"], cap="modbus_handlers")
    s = msim()
    t0 = s.now_ms
    s.queue_frames(E.FrameSpec(outcome="timeout", latency_ms=500))
    s.start_script("reader")
    s.run_until(t0)
    held = s.hub.tx_blocked()
    s.run_for(499)
    still_held = s.hub.tx_blocked()
    s.run_for(10)
    check("a `timeout` frame occupies the bus for its latency and then NEVER calls a handler (a stuck reply)",
          held and still_held and not s.hub.tx_blocked() and s.g["cnt"] == 0 and s.wire_log[0].t_end - t0 == 500,
          cap="modbus_handlers")
    s = msim()
    s.queue_frames(E.FrameSpec(values=[1, 2]))
    s.start_script("reader")
    s.run_for(130)
    check("FrameSpec.values replaces what the HANDLER receives (a short reply: values.size() is 2, not 3) while the log keeps "
          "the 3-word request (modbus_log values / Since.reads)", (s.g["u"], s.g["n"]) == (2, 2)
          and s.since(E.Mark(0, 0, 0, 0, 0, 0, 0, {})).reads == [(230, 3)] and s.modbus_log[0][2] == [10, 20, 30],
          cap="modbus_handlers")
    s = msim()
    s.queue_frames("ok", {"outcome": "error", "exception_code": 4}, lambda addr, count: E.FrameSpec(outcome="no_response"))
    for _ in range(3):
        s.start_script("reader")
        s.run_for(130)
    seq = [e[3] for e in s.modbus_log]
    s.outcome_fn = lambda kind, addr, count: {"outcome": "custom_response"}
    s.start_script("reader")
    s.run_for(130)
    check("outcomes are configurable PER CALL: queue_frames (str / dict / FrameSpec / callable(addr, count)) is consumed in call "
          "order, then outcome_fn(kind, addr, count) decides (and may return any of the three forms)",
          seq == ["ok", "error", "no_response"] and [e[3] for e in s.modbus_log][-1] == "custom_response" and s.g["cnt"] == 4,
          str(seq), cap="modbus_handlers")
    check("strict outcomes: an unknown outcome, an unknown FrameSpec key, a bad mode and a non-read frame spec raise "
          "FbbNotModelled (the old Sim silently ran no handler for an unknown outcome)",
          all(isinstance(raises(f), H.FbbNotModelled) for f in (
              lambda: (lambda x: (x.queue_frames("bogus"), x.start_script("reader")))(msim()),
              lambda: (lambda x: (x.queue_frames({"outcome": "ok", "latencyms": 5}), x.start_script("reader")))(msim()),
              lambda: msim().set_modbus_mode("sometimes"),
              lambda: (lambda x: (x.queue_frames(42), x.start_script("reader")))(msim()))), cap="strictness")
    # immediate mode (the default) and the shared logs
    s = H.FbbSim(MFW)
    s.bank.update({230: 10, 231: 20, 232: 30})
    s.start_script("reader")
    check("the default (immediate) mode delivers synchronously at the action - the older behaviour - with the same logs: "
          "modbus_log keeps its 4-tuples, wire_log has the frame, the hub is never involved",
          s.g["cnt"] == 1 and s.modbus_log == [("read", 230, [10, 20, 30], "ok")] and len(s.wire_log) == 1
          and s.wire_log[0].t_start == s.wire_log[0].t_end and s.hub.tx_buffer_empty() and s.modbus_mode == "immediate",
          cap="modbus_handlers")
    # foreign frames
    s = msim()
    t0 = s.now_ms
    s.inject_foreign_frame(22, 3, latency_ms=900)
    s.start_script("reader")
    s.run_for(2000)
    sn = s.since(E.Mark(0, 0, 0, 0, 0, 0, 0, {}))
    check("wire records carry their ISSUER (the script / button / interval task): Since.reads_by('read') keeps only the "
          "firmware's own reads - a foreign frame has none", sn.reads_by("reader") == [(230, 3)] and sn.reads_by("poll") == []
          and [w.issuer for w in s.wire_log] == [None, "reader"], str([w.issuer for w in s.wire_log]), cap="foreign_frames")
    check("a foreign frame (a configuration poll / RTC read in flight) holds the bus: the firmware's read starts only after "
          "it; the foreign frame is in wire_log (origin 'foreign') but NOT in modbus_log (which is what the firmware issued)",
          [(w.origin, w.addr, w.t_start - t0, w.t_end - t0) for w in s.wire_log] == [("foreign", 22, 0, 900), ("fw", 230, 900, 1020)]
          and [(e[0], e[1]) for e in s.modbus_log] == [("read", 230)] and sn.reads == [(230, 3)]
          and sn.wire_reads == [(22, 3, "foreign"), (230, 3, "fw")], cap="foreign_frames")
    s = msim()
    t0 = s.now_ms
    s.inject_foreign_frame(22, 3, latency_ms=900)
    s.start_script("reader")
    s.at_bank(t0 + 100, {231: 55})
    s.run_for(1100)
    check("a frame QUEUED behind another is snapshotted when it goes on the wire, not when it was queued: a bank mutation "
          "while it waits (+100 ms, behind a 900 ms foreign frame) is what it reads", s.g["n"] == 55 and s.modbus_log[0][2][1] == 55,
          cap="deferred_frames")
    s = msim()
    t0 = s.now_ms
    s.hold_bus(500)
    s.start_script("reader")
    s.run_for(1000)
    check("hold_bus keeps tx_blocked true for a duration (opaque traffic); a queued read starts the moment it ends",
          s.wire_log[0].t_start - t0 == 500 and s.g["cnt"] == 1, cap="foreign_frames")
    s = msim()
    t0 = s.now_ms
    s.hold_script_running("holder", 400)
    s.run_until(t0)
    r1 = "holder" in s.running
    s.run_for(399)
    r2 = "holder" in s.running
    dropped = s.start_script("holder")
    s.run_for(1)
    r3 = "holder" in s.running
    check("hold_script_running makes id(script).is_running() true for a duration without running it (a foreign script), and a "
          "start_script of it is dropped meanwhile (mode: single)", (r1, r2, r3) == (True, True, False) and dropped is None,
          cap="foreign_frames")
    s = msim()
    s.at_foreign_frame(s.now_ms + 50, 22, 3, latency_ms=300)
    s.run_for(60)
    check("at_foreign_frame schedules the injection at a chosen time", s.hub.tx_blocked() and s.wire_log[0].origin == "foreign",
          cap="foreign_frames")
    # late delivery with no script running
    s = msim()
    s.queue_frames(E.FrameSpec(latency_ms=5000))
    s.start_script("reader")
    check("late delivery with NO script running: the handler fires at +5000 ms from the engine alone (the issuing script "
          "finished at +0)", (s.run_for(4999), s.g["cnt"])[1] == 0 and (s.run_for(1), s.g["cnt"])[1] == 1
          and not s.running and not s.hub.tx_blocked(), cap="deferred_frames")
    # the clock attaches to the legacy in_flight_until
    s = msim()
    s.hub.in_flight_until = s.now_ms + 100
    b1 = s.hub.tx_blocked()
    s.run_for(100)
    check("a hand-set hub.in_flight_until (FB-B0 style) stops blocking by itself once the sim clock passes it (no tick needed); "
          "legacy enqueue / tick still behave as before",
          b1 and not s.hub.tx_blocked() and (lambda r: (r[2], r[4]))((lambda h: (h.enqueue(2), h.tick(0), h.tx_blocked(), h.tick(100),
                                                                              h.tx_buffer_empty()))(H.HubModel(frame_ms=100))) == (True, True),
          cap="deferred_frames")
    # writes are logged
    s = H.FbbSim(MFW)
    s.start_script("writer")
    check("a Modbus WRITE is never deferred and is always logged (modbus_log, wire_log kind 'write') so the safety marks see it",
          [e[:2] for e in s.modbus_log] == [("write", 244)] and s.wire_log[0].kind == "write", str(s.modbus_log),
          cap="safety_marks")
    # deferred + the FB-B0 blocking execute()
    s = msim()
    s.bank.update({230: 1, 231: 2, 232: 3})
    FWB = mkfw(MG, [S("blocking", [{"modbus_client.read_holding_registers": {
        "modbus_id": "inverter_modbus", "address": 1, "start_address": 230, "count": 3,
        "on_response": {"then": [L("id(cnt) = 5; id(x) = 1;")]}}}, {"wait_until": {"condition": L("return id(x) == 1;"), "timeout": "1s"}},
        L("id(n) = 7;")])])
    b = H.FbbSim(FWB)
    b.set_modbus_mode("deferred", 120)
    t0 = b.now_ms
    b.execute("blocking")
    check("the blocking execute() also gets deferred deliveries during its waits (the wait ends at the delivery, +120 ms)",
          b.g["n"] == 7 and b.now_ms - t0 == 120, str(b.now_ms - t0), cap="deferred_frames")

    # =======================================================================
    print("[9] the interval scheduler: period, startup_delay, declaration order, phase, re-arm, parked scripts, millis() wrap")
    # =======================================================================
    IG = [G("trace", "std::string", '""'), G("u", "uint32_t", "0"), G("flag", "bool", "false"), G("n", "uint8_t", "0")]
    IV = [
        {"interval": "10s", "then": [ADD("A")]},
        {"interval": "10s", "startup_delay": "5s", "then": [ADD("B")]},
        {"interval": "5s", "startup_delay": "5s", "then": [ADD("C")]},
        {"interval": "1s", "then": [L("id(u) = millis();")]},
        {"interval": "30s", "then": [{"delay": "2s"}, ADD("Z")]},
        {"interval": "1s", "startup_delay": "3s", "then": [L("id(flag) = true;")]},
    ]
    IFW = mkfw(IG, [S("forever", [{"wait_until": {"condition": L("return id(flag);")}}, L("id(n) = 5;")])], intervals=IV)

    def isim():
        return H.FbbSim(IFW)

    s = isim()
    t0 = s.now_ms
    started = s.start_intervals([0, 1, 2])
    s.run_until(t0 + 20_000)
    check("intervals fire on period + startup_delay (first at boot + startup_delay + phase, then every period) in DECLARATION "
          "order on ties: A at 0/10/20 s, B at 5/15 s, C at 5/10/15/20 s", started == [0, 1, 2]
          and [(t - t0, i) for t, i in s.interval_log] == [(0, 0), (5000, 1), (5000, 2), (10000, 0), (10000, 2), (15000, 1),
                                                           (15000, 2), (20000, 0), (20000, 2)]
          and s.g["trace"] == "ABCACBCAC", str(s.g["trace"]), cap="interval_scheduler")
    s = isim()
    t0 = s.now_ms
    s.start_intervals(3)
    s.run_until(t0 + 100_000)
    check("re-armed on the SCHEDULED time: 101 firings of a 1 s interval in 100 s, no drift", len(s.interval_log) == 101
          and all(t - t0 == k * 1000 for k, (t, _i) in enumerate(s.interval_log)), cap="interval_scheduler")
    forms = {}
    s = isim()
    forms["index"] = s.start_intervals(3)
    s = isim()
    forms["list"] = s.start_intervals([1, 3])
    s = isim()
    forms["substring"] = s.start_intervals("id(u) = millis()")
    s = isim()
    forms["predicate"] = s.start_intervals(lambda i, iv: iv["interval"] == "5s")
    s = isim()
    forms["all"] = s.start_intervals("all")
    s = isim()
    check("select: an index, a list, a substring of the interval's actions, a predicate(idx, interval) or 'all'; "
          "interval_index(marker) names THE interval (exactly one)",
          forms == {"index": [3], "list": [1, 3], "substring": [3], "predicate": [2], "all": [0, 1, 2, 3, 4, 5]}
          and s.interval_index("id(u) = millis()") == 3, str(forms), cap="interval_scheduler")
    check("strict: no match, an ambiguous marker, a double start and a non-positive period raise FbbNotModelled",
          all(isinstance(raises(f), H.FbbNotModelled) for f in (
              lambda: isim().start_intervals("no such marker"), lambda: isim().start_intervals(99),
              lambda: isim().interval_index("id(trace)"), lambda: (lambda x: (x.start_intervals(0), x.start_intervals(0)))(isim()),
              lambda: H.FbbSim(mkfw(IG, intervals=[{"interval": "0s", "then": []}])).start_intervals(0),
              lambda: isim().start_intervals(0, rearm="sometimes"))), cap="strictness")
    s = isim()
    t0 = s.now_ms
    s.start_intervals([0, 1], phase={0: 3})
    s.run_until(t0 + 6000)
    first_a = [t - t0 for t, i in s.interval_log if i == 0][0]
    s2 = isim()
    s2.start_intervals([0, 1], phase=7)
    s2.run_until(s2.now_ms + 6000)
    check("per-interval initial phase offsets: an int for all, a dict per index",
          first_a == 3 and [t - t0 for t, i in s.interval_log if i == 1][0] == 5000
          and [t - t0 for t, i in s2.interval_log] == [7, 5007], str(s.interval_log), cap="interval_scheduler")

    def phases(seed, burn):
        x = isim()
        x.seed_rng(seed)
        for _ in range(burn):
            x.random_uint32()
        t = x.now_ms
        x.start_intervals([0, 3, 4], phase="random")
        x.run_until(t + 35_000)
        return [(i, tt - t) for tt, i in x.interval_log if tt - t < 6000]
    a_, b_, c_ = phases(7, 0), phases(7, 5), phases(8, 0)
    first_off = {i: min(off for j, off in a_ if j == i) for i in (0, 3, 4)}
    check("phase='random' is ESPHome's initial offset, [0, min(period/2, 5000)) ms: deterministic per seed, a different seed "
          "differs, and drawing random_uint32() values does NOT disturb it (separate RNG stream)",
          a_ == b_ and a_ != c_ and 0 <= first_off[0] < 5000 and 0 <= first_off[3] < 500 and 0 <= first_off[4] < 5000,
          str((a_[:4], c_[:4])), cap="interval_scheduler")
    s = isim()
    s.start_script("forever")
    t0 = s.now_ms
    s.start_intervals(5)
    s.run_for(10_000)
    check("an interval fires WHILE a script is parked in a wait_until: the interval at +3 s sets the flag and the wait ends at "
          "exactly +3 s (scheduler before the loop's condition poll)", s.g["n"] == 5 and "forever" not in s.running
          and s.task_of("forever").finished_ms == t0 + 3000, cap="interval_scheduler")
    s = isim()
    t0 = s.now_ms
    s.start_intervals(4)
    s.run_for(1999)
    mid = ("Z" in str(s.g["trace"]), s.interval_log)
    s.run_for(1)
    check("an interval whose actions park (delay) is a task per firing: its tail runs 2 s after each firing; the next firing "
          "is not delayed", mid[0] is False and s.g["trace"] == "Z" and (s.run_for(28_000), s.interval_log[-1][0] - t0)[1] == 30_000,
          cap="interval_scheduler")
    s = isim()
    s.now_ms = 5_000
    s.rebase_clock((1 << 32) - 25_000)
    t0 = s.now_ms
    s.start_intervals(3)
    seen = []
    for _ in range(60):
        s.run_for(1000)
        seen.append(s.g["u"])
    check("millis() wrap: an interval started 25 s before the wrap keeps firing every 1 s across it; its lambda sees millis() "
          "wrap to small values (the 32-bit clock) while the scheduler's own 64-bit time never wraps",
          len(s.interval_log) == 61 and seen[0] == (1 << 32) - 24_000 and seen[24] == 0 and seen[25] == 1000
          and seen[-1] == 35_000 and min(seen) == 0, str((seen[:2], seen[24:27], seen[-1])), cap="interval_scheduler")
    s = isim()
    s.start_intervals(3)
    s.run_for(2500)
    s.rebase_clock((1 << 32) - 1500)
    s.run_for(5000)
    post = [tt for tt, _i in s.interval_log[3:]]
    check("rebase_clock with an interval already running: its schedule moves with the clock (no burst, no gap): 3 firings "
          "before the jump, then 1 s spacing from +500 ms after it, across the millis() wrap", len(s.interval_log) == 8
          and post == [(1 << 32) - 1000 + 1000 * k for k in range(5)], str(post), cap="interval_scheduler")
    s = isim()
    s.start_intervals(3)
    s.run_for(5000)
    n1 = len(s.interval_log)
    s.stop_intervals(3)
    s.run_for(5000)
    n2 = len(s.interval_log)
    s.start_intervals(3)
    s.run_for(2000)
    check("stop_intervals cancels the schedule; the interval can be started again", n1 == 6 and n2 == 6 and len(s.interval_log) >= 8,
          str((n1, n2, len(s.interval_log))), cap="interval_scheduler")

    # =======================================================================
    print("[10] injectable events, the unified event timeline, power cut, reboot")
    # =======================================================================
    s = msim()
    t0 = s.now_ms
    s.at_bank(t0 + 50, {231: 77})
    s.after(100, lambda sim: sim.g.__setitem__("x", 9), name="after")
    s.run_for(60)
    b60 = s.bank[231]
    s.run_for(60)
    check("at_bank mutates the register bank at a chosen time; after(d, fn) schedules relative to now",
          b60 == 77 and s.g["x"] == 9, cap="injectable_events")
    s = esim()
    t0 = s.now_ms
    s.at_press(t0 + 10, "btn")
    s.run_for(9)
    before = str(s.g["trace"])
    s.run_for(1)
    check("at_press presses a button at a chosen time (its on_press actions run as an automation)",
          before == "" and s.g["trace"] == "d0," and "delayer" in s.running, cap="injectable_events")
    s = msim()
    s.at_power_cut(s.now_ms + 250)
    s.start_script("reader")
    t0 = s.now_ms
    err = raises(lambda: s.run_for(1000), T.PowerCut)
    check("at_power_cut raises PowerCut out of run_for at exactly that time (the Sim's state is frozen as at the cut); "
          "PowerCut is the same class DirectNvs raises", err is not None and s.now_ms == t0 + 250 and T.PowerCut is H.PowerCut,
          cap="injectable_events")
    # events + hook + nvs timeline
    NV = [G("u", "uint32_t", "0"), G("n", "uint8_t", "0"), G("h", "uint16_t", "0"), G("e", "int32_t", "0")]
    s = H.FbbSim(mkfw(NV))
    s.seed_marker(TAG, 1)
    seen = []
    s.event_hook = seen.append
    s.run_lambda(PROBE)
    s.run_lambda("ecco_fbdurable::EspNvs nvs; id(n) = ecco_fbdurable::nvs_healthy();")
    check("the direct NVS feeds the ONE event timeline: every get / read / stats is a ('nvs', op, key, result) event delivered "
          "to sim.events and event_hook, in call order", [e[:2] for e in seen] == [("nvs", "get"), ("nvs", "read"), ("nvs", "stats")]
          and [e[:2] for e in s.events] == [("nvs", "get"), ("nvs", "read"), ("nvs", "stats")], str(seen), cap="event_timeline")
    s = msim()
    s.start_script("reader")
    s.run_for(200)
    kinds = [e[0] for e in s.events]
    check("tasks, frames and deliveries are events too, in time order: the script's start and done, then the frame on "
          "the wire, then its delivery", kinds == ["task", "task", "read", "deliver"], str(kinds), cap="event_timeline")
    s = H.FbbSim(mkfw(NV))
    s.seed_marker(TAG, 1)
    s.power_cut_when(lambda ev: ev[0] == "nvs" and ev[1] == "read")
    err = raises(lambda: s.run_lambda(PROBE), T.PowerCut)
    check("power_cut_when(predicate) raises PowerCut right after the first event that matches (here the marker's data read), "
          "so a test can cut between any two steps; the NVS op log shows exactly how far it got",
          err is not None and [o[0] for o in s.nvs_direct.ops] == ["get", "read"], cap="injectable_events")
    s = msim()
    s.g["u"] = 5
    s.bank[230] = 7
    s.seed_marker(TAG, 1)
    s.random_values = [123]
    s.start_script("holder")
    s2 = s.reboot()
    check("reboot(): a NEW sim with all RAM reset (globals, running scripts, tasks, events), millis() restarted, and what "
          "survives: the register bank, the legacy records, the direct NVS; modbus mode carried; the RNG reseeds (seed + 1)",
          s2.g["u"] == 0 and not s2.running and not s2.tasks and s2.now_ms == 1_000_000 and s2.bank == {230: 7, 231: 20, 232: 30}
          and s2.nvs[TAG].state == 1 and s2.nvs_direct.state_of(KEY).startswith("OK:8:") and s2.modbus_mode == "deferred"
          and s2.rng_seed == s.rng_seed + 1 and s2.nvs_direct is not s.nvs_direct and s2.events == [],
          cap="injectable_events")
    s = H.FbbSim(mkfw(NV))
    s.nvs_direct.put(KEY, H.FbbSim.marker_bytes(MAGIC, 1))
    s.nvs_direct.faults[KEY] = [H.WriteFault(fd.IDF_ERR_TIMEOUT, H.VIS_OLD, H.BOOT_ABSENT)]
    s.nvs_direct.set_blob(KEY, H.FbbSim.marker_bytes(MAGIC, 2))
    s2 = s.reboot()
    check("reboot(resolve_nvs=True) resolves pending write faults at the power cycle (the direct NVS's own reboot())",
          s2.nvs_direct.state_of(KEY) == "ABS" and s.reboot(resolve_nvs=False).nvs_direct is s.nvs_direct, cap="injectable_events")
    check("on_boot actions run through run_boot (lambdas only; anything else raises)",
          (lambda x: (x.run_boot(), x.g["u"])[1])(H.FbbSim(mkfw(NV, boot=[L("id(u) = 41;"), L("id(u) = id(u) + 1;")]))) == 42
          and isinstance(raises(lambda: H.FbbSim(mkfw(NV, boot=[{"delay": "1s"}])).run_boot()), H.FbbNotModelled),
          cap="injectable_events")

    # =======================================================================
    print("[11] safety marks: no Modbus write, no NVS set, no durable commit, exact read list")
    # =======================================================================
    s = msim()
    m = s.mark()
    s.start_script("reader")
    s.start_script("reader")
    s.run_for(300)
    ok = s.since(m)
    check("a read-only run has no violations; reads are the (address, count) list in wire order",
          ok.violations(reads=[(230, 3), (230, 3)]) == [] and ok.reads == [(230, 3), (230, 3)] and ok.nvs_read_probes == []
          and ok.writes == [], cap="safety_marks")
    check("negative control - a wrong read list is reported", any("reads" in v for v in ok.violations(reads=[(230, 3)])),
          cap="safety_marks")
    s = H.FbbSim(MFW)
    m = s.mark()
    s.start_script("writer")
    v = s.since(m).violations()
    check("negative control - a Modbus write is reported", len(v) == 1 and v[0].startswith("Modbus writes"), str(v),
          cap="safety_marks")
    s = H.FbbSim(mkfw(NV))
    m = s.mark()
    s.nvs_direct.set_blob(KEY, H.FbbSim.marker_bytes(MAGIC, 1))
    sn = s.since(m)
    check("negative control - a direct NVS set is reported (and counted from nvs_direct.ops)",
          len(sn.nvs_sets) == 1 and any("NVS sets" in v for v in sn.violations()), cap="safety_marks")
    s = H.FbbSim(mkfw(NV))
    m = s.mark()
    s.D.commit_record(TAG, ds.Record("ValidMarker", MAGIC, 1))
    sn = s.since(m)
    check("negative control - an ecco_durable commit is reported, and so is a changed record",
          len(sn.commits) == 1 and any("commits" in v for v in sn.violations()) and sn.legacy_changed == [TAG], cap="safety_marks")
    fw_ent = mkfw(BASE_G, text_sensors=[{"id": "ts", "platform": "template"}])
    fw_ent["switch"] = [{"id": "arm_off", "restore_mode": "ALWAYS_OFF"}, {"id": "arm_on", "restore_mode": "RESTORE_DEFAULT_ON"},
                        {"id": "arm_default"}, {"id": "arm_disabled", "restore_mode": "DISABLED"}]
    fw_ent["binary_sensor"] = [{"id": "bsens", "platform": "template"}]
    s = H.FbbSim(fw_ent)
    s.run_lambda("id(b) = !id(arm_off).state && id(arm_on).state && !id(arm_default).state && !id(bsens).state; "
                 "id(b2) = id(ts).state.empty(); id(n) = id(ts).state.size();")
    check("entity boot states as in ESPHome: a switch holds its restore_mode value (ALWAYS_OFF / default off -> off, "
          "RESTORE_DEFAULT_ON -> on; DISABLED stays unknown), a template binary sensor reads false, a text sensor reads as the "
          "empty std::string - so a gate's `!id(arm).state` is not defeated by NaN (which is truthy)",
          s.g["b"] and s.g["b2"] and s.g["n"] == 0 and s.ent("arm_off").has_state() and not s.ent("bsens").has_state()
          and s.ent("arm_disabled").state != s.ent("arm_disabled").state, cap="strictness")
    s = H.FbbSim(fw_ent)
    snap = s.snapshot_state()
    quiet = s.state_diff(snap)
    s.run_lambda('id(w)[2] = 5; id(u) = 7; id(s) = "x"; id(ts).publish_state("hello"); id(ts).publish_state("again");')
    d = s.state_diff(snap)
    check("snapshot_state / state_diff: 'this refused / idle path touched NOTHING' is assertable - the globals that changed "
          "(arrays and strings compared by value) and every entity publish since the snapshot",
          quiet == {"globals": [], "published": {}} and d == {"globals": ["s", "u", "w"], "published": {"ts": ["hello", "again"]}}
          and s.state_diff(snap, ignore=("w", "u")) == {"globals": ["s"], "published": d["published"]}, str(d), cap="safety_marks")
    s = H.FbbSim(mkfw(NV))
    s.seed_marker(TAG, 1)
    m = s.mark()
    s.run_lambda(PROBE)
    sn = s.since(m)
    check("marker probes are READS: no violation, two ops (probe + data) counted as one read probe",
          sn.violations() == [] and len(sn.nvs_read_probes) == 1 and len(sn.nvs_ops) == 2, cap="safety_marks")

    # =======================================================================
    print("[12] a REVIEW-shaped fixture (gate + dispatch + housekeeping + button) through the whole machinery")
    # =======================================================================
    RFW = ds.load_firmware_text(review_fixture_yaml())

    def rsim(mode="deferred", latency=120, forced_salt=0, **kw):
        r = H.FbbSim(RFW, fbcap=DBL, **kw)
        r.bank.update({230 + i: 1000 + i for i in range(3)})
        r.bank.update({241 + i: 2000 + i for i in range(53)})
        r.random_values = [forced_salt]
        if mode == "deferred":
            r.set_modbus_mode("deferred", latency)
        return r

    READS4 = [(230, 3), (241, 53), (230, 3), (241, 53)]
    s = rsim("immediate")
    m = s.mark()
    s.press_button("review_button")
    sn = s.since(m)
    check("immediate mode: the button press runs the whole gate -> dispatch -> final -> release chain synchronously (the "
          "older behaviour): candidate READY, the four reads in order, nothing left locked, zero writes / NVS sets",
          s.g["cand_valid"] and s.g["capture_state"] == 2 and s.ent("result_ts").state == DBL.TXT_READY
          and not s.g["op_in_progress"] and not s.g["mwip"] and sn.violations(reads=READS4) == [] and not s.running
          and list(s.g["cand_words"])[:3] == [1000, 1001, 1002] and s.g["boot_salt"] == 1 and s.random_log == [0],
          str((s.g["capture_state"], s.ent("result_ts").state, sn.violations(reads=READS4))), cap="async_scripts")
    s.press_button("review_button")
    check("the lazy salt is drawn ONCE (`if (salt == 0) salt = random_uint32() | 1u`): a second review draws nothing",
          s.random_log == [0] and s.g["boot_salt"] == 1, cap="random_uint32")

    s = rsim()
    t0 = s.now_ms
    m = s.mark()
    s.press_button("review_button")
    snap = (s.g["capture_state"], sorted(s.running), "review_gate" in s.running, s.g["op_in_progress"],
            s.hub.tx_buffer_empty(), s.hub.tx_blocked())
    s.press_button("review_button")
    refused = str(s.ent("result_ts").state)
    s.run_until(t0 + 130)
    mid = (s.hub.tx_buffer_empty(), s.hub.tx_blocked(), s.wire_log[1].addr, s.wire_log[1].t_end is None)
    s.run_until_idle()
    sn = s.since(m)
    check("deferred review: right after the press the capture is READING, only the DISPATCH is running (the gate finished: it is "
          "not 'running' while the dispatch it started is parked), the hub has R1 queued; a second press during the dispatch is "
          "REFUSED by V1 with the B9 text (the old blocking model silently dropped it)",
          snap == (1, ["capture_dispatch"], False, True, False, False)
          and refused == "REVIEW REFUSED - another Fallback Profile operation is in progress"
          and mid == (True, True, 241, True), str((snap, refused, mid)), cap="async_scripts")
    check("deferred review completes after 4 x 120 ms: each read goes on the wire the moment the previous reply was delivered, "
          "texts in order, zero writes / NVS sets, exact read list, locks released",
          s.now_ms - t0 == 480 and [(w.addr, w.t_start - t0, w.t_end - t0) for w in s.wire_log] ==
          [(230, 0, 120), (241, 120, 240), (230, 240, 360), (241, 360, 480)]
          and [str(x) for x in s.ent("result_ts").published] == ["review in progress (read-only)", refused, DBL.TXT_READY]
          and sn.violations(reads=READS4) == [] and not s.g["mwip"] and not s.g["op_in_progress"],
          str([(w.addr, w.t_start - t0, w.t_end - t0) for w in s.wire_log]), cap="deferred_frames")
    kinds = [(e[0], e[1] if e[0] == "read" else None) for e in s.events if e[0] in ("read", "deliver")]
    check("the event timeline orders reads and deliveries: read, deliver, read, deliver, ...", [k[0] for k in kinds] ==
          ["read", "deliver"] * 4, str(kinds), cap="event_timeline")

    # T-CAP-01: a configuration poll in flight at the gate
    s = rsim()
    t0 = s.now_ms
    s.inject_foreign_frame(22, 3, latency_ms=900)
    s.run_for(50)
    m = s.mark()
    s.press_button("review_button")
    s.run_until_idle()
    wl = [(w.origin, w.addr) for w in s.wire_log]
    check("T-CAP-01 shape: a foreign frame in flight at the gate is drained by the idle wait (R1 goes out at +900, the first "
          "moment the bus is idle) and no foreign frame sits between R1 and R4", wl == [("foreign", 22), ("fw", 230), ("fw", 241),
                                                                                         ("fw", 230), ("fw", 241)]
          and s.wire_log[1].t_start - t0 == 900 and s.g["cand_valid"] and s.since(m).violations(reads=READS4) == [],
          str(wl), cap="foreign_frames")
    s = rsim()
    t0 = s.now_ms
    s.start_script("poll_cfg")
    s.press_button("review_button")
    s.run_until_idle()
    check("T-CAP-01 shape: the REAL poll scripts are participants: a script running a 5 s delay (the fixture's poll_cfg) keeps "
          "the idle wait parked until it finishes; the reads then start at +5000", s.wire_log[0].t_start - t0 == 5000
          and s.g["cand_valid"], str(s.wire_log[0].t_start - t0), cap="foreign_frames")
    # T-CAP-02: drain longer than 7 s
    s = rsim()
    t0 = s.now_ms
    s.hold_script_running("poll_cfg", 9_000)
    s.run_until(t0)
    m = s.mark()
    s.press_button("review_button")
    s.run_until(t0 + 8_000)
    task = s.task_of("capture_dispatch")
    check("T-CAP-02 shape: a poll that does not drain within 7 s -> NOT COMPLETED at exactly +7000 ms, ZERO FB reads, lock "
          "released, no candidate", task.done and task.finished_ms == t0 + 7000
          and str(s.ent("result_ts").state) == "REVIEW NOT COMPLETED - code 9" and s.since(m).reads == [] and not s.g["mwip"]
          and not s.g["op_in_progress"] and not s.g["cand_valid"] and not s.since(m).violations(), cap="async_scripts")
    # T-CAP-03: a late reply after the bounded wait failed, then a new review
    s = rsim()
    t0 = s.now_ms
    m = s.mark()
    s.queue_frames("ok", E.FrameSpec(latency_ms=3500))
    s.press_button("review_button")
    s.run_until(t0 + 3_150)
    first = (str(s.ent("result_ts").state), s.g["read_fail_code"], s.g["mwip"], s.g["op_in_progress"], s.hub.tx_blocked())
    s.run_until(t0 + 3_200)
    s.press_button("review_button")
    s.run_until(t0 + 3_619)
    waiting = (s.g["op_in_progress"], s.task_of("capture_dispatch").parked, s.hub.tx_blocked(), s.g["step"])
    s.run_until_idle()
    texts = [str(x) for x in s.ent("result_ts").published]
    sn = s.since(m)
    check("T-CAP-03 shape: R2's reply (3500 ms) arrives AFTER the 3 s bounded wait failed -> NOT COMPLETED, lock released, the "
          "late frame still blocks the bus; a new review pressed meanwhile waits in its idle wait; the stale callback is "
          "delivered while that review has step == 0 and is IGNORED; the second review completes from ITS OWN four frames",
          first == ("REVIEW NOT COMPLETED - code 7", 7, False, False, True) and waiting == (True, "wait", True, 0)
          and texts == ["review in progress (read-only)", "REVIEW NOT COMPLETED - code 7", "review in progress (read-only)", DBL.TXT_READY]
          and s.g["cand_valid"] and not s.g["read_failed"] and not s.g["mwip"]
          and [(w.addr, w.t_end - w.t_start) for w in s.wire_log] == [(230, 120), (241, 3500), (230, 120), (241, 120), (230, 120), (241, 120)]
          and sn.reads == [(230, 3), (241, 53)] + READS4 and sn.violations() == [],
          str((first, waiting, texts, sn.reads)), cap="deferred_frames")
    # T-CAP-03 variant: a foreign frame queued between reads pushes R2 past its bound
    s = rsim()
    t0 = s.now_ms
    s.at_foreign_frame(t0 + 60, 22, 3, latency_ms=3500)
    s.press_button("review_button")
    s.run_until_idle()
    check("a foreign frame queued BETWEEN reads only ever causes a fail-closed bounded-wait failure (R2 queued behind it waits "
          "3 s), never a torn candidate: NOT COMPLETED, no candidate, locks released",
          str(s.ent("result_ts").state) == "REVIEW NOT COMPLETED - code 7" and not s.g["cand_valid"] and not s.g["mwip"]
          and not s.since(E.Mark(0, 0, 0, 0, 0, 0, 0, {})).writes, cap="foreign_frames")
    # exception codes / short replies / not sent / non-standard
    for label, spec, text in (
            ("exception", E.FrameSpec(outcome="error", exception_code=3), "REVIEW NOT COMPLETED - code 4"),
            ("no response", "no_response", "REVIEW NOT COMPLETED - code 5"),
            ("not sent", "not_sent", "REVIEW NOT COMPLETED - code 6"),
            ("non-standard reply", "custom_response", "REVIEW NOT COMPLETED - code 8"),
            ("short reply", E.FrameSpec(values=[1, 2]), "REVIEW NOT COMPLETED - code 3")):
        s = rsim()
        m = s.mark()
        s.queue_frames(spec)
        s.press_button("review_button")
        s.run_until_idle()
        sn = s.since(m)
        ok_ = str(s.ent("result_ts").state) == text and len(sn.reads) == 1 and not s.g["mwip"] and not s.g["cand_valid"] \
            and sn.violations() == []
        if label == "exception":
            ok_ = ok_ and s.g["last_exc"] == 3
        check(f"first read fails ({label}): fail-fast - exactly ONE read issued, NOT COMPLETED, lock released, no candidate",
              ok_, str((s.ent("result_ts").state, sn.reads)), cap="modbus_handlers")
    # T-CAP-06: bank mutation between the passes, each of the 31 stored words
    results = []
    for idx in range(31):
        addr = 230 + idx if idx < 3 else 241 + (idx - 3)
        s = rsim()
        t0 = s.now_ms
        s.at_bank(t0 + (100 if idx < 3 else 200), {addr: 5000 + idx})
        s.press_button("review_button")
        s.run_until_idle()
        results.append((idx, s.g["diff_idx"], s.g["cand_valid"], str(s.ent("result_ts").state)))
    bad = [r for r in results if r[1] != r[0] or r[2] or "live configuration changed" not in r[3]]
    quiet = []
    for t_off in (-1, 500):
        s = rsim()
        t0 = s.now_ms
        s.at_bank(t0 + t_off, {230: 4242, 241: 4243})
        s.press_button("review_button")
        s.run_until_idle()
        quiet.append(s.g["cand_valid"])
    check("T-CAP-06 shape: a bank mutation between the read passes - each of the 31 stored words, between its two reads - "
          "is a pass mismatch naming that word (first differing index), no candidate; a mutation before R1 / after R4 is "
          "stable", not bad and quiet == [True, True], str(bad[:2]), cap="injectable_events")
    # TTL, housekeeping interval
    s = rsim()
    t0 = s.now_ms
    s.start_intervals("cand_valid")
    s.press_button("review_button")
    s.run_until(t0 + 124_999)
    alive = (s.g["cand_valid"], str(s.ent("result_ts").state))
    s.run_until(t0 + 125_000)
    check("housekeeping interval: the candidate (born +480 ms) is still valid at +124 999 ms and expired by the 10 s tick at "
          "+125 000 ms - it lingers up to one tick past the 120 s TTL (D9) - with the REVIEW EXPIRED text",
          alive == (True, DBL.TXT_READY) and not s.g["cand_valid"] and str(s.ent("result_ts").state) == "REVIEW EXPIRED",
          str(alive), cap="interval_scheduler")
    s = rsim()
    s.now_ms = 5_000
    s.rebase_clock((1 << 32) - 60_000)
    t0 = s.now_ms
    s.start_intervals("cand_valid")
    s.press_button("review_button")
    s.run_until(t0 + 124_999)
    alive = s.g["cand_valid"]
    s.run_until(t0 + 125_000)
    check("the same TTL expiry when the candidate is born 60 s before the millis() wrap (the wrap-safe (uint32_t) age)",
          alive and not s.g["cand_valid"] and (t0 + 125_000) > (1 << 32), cap="unsigned_wrap")
    # breaker: a leaked op flag, no dispatch running
    s = rsim()
    t0 = s.now_ms
    s.g["op_in_progress"] = True
    s.g["mwip"] = True
    s.g["op_started_ms"] = s.millis()
    s.start_intervals("cand_valid")
    s.run_until(t0 + 25_000)
    before = (s.g["op_in_progress"], s.g["mwip"])
    s.run_until(t0 + 35_000)
    check("breaker (30 s): clears ONLY the module's own flag and never touches the shared write lock (the manual_write_in_progress "
          "analogue); nothing before 30 s", before == (True, True) and s.g["op_in_progress"] is False and s.g["mwip"] is True
          and str(s.ent("result_ts").state) == "INTERNAL - breaker", cap="interval_scheduler")
    # power cut mid review, then reboot
    s = rsim()
    t0 = s.now_ms
    s.at_power_cut(t0 + 250)
    s.press_button("review_button")
    err = raises(lambda: s.run_until(t0 + 1000), T.PowerCut)
    cut = (s.g["op_in_progress"], s.g["mwip"], s.hub.tx_blocked(), s.now_ms - t0)
    s2 = s.reboot()
    s2.press_button("review_button")
    s2.run_until_idle()
    check("power cut in the middle of a review: the sim freezes with the lock held and a frame in flight; after reboot() all RAM "
          "is clear (no candidate, no lock, lazy salt unset), the review works again from scratch with a different RNG stream",
          err is not None and cut == (True, True, True, 250) and s2.g["cand_valid"] and not s2.g["mwip"]
          and s2.random_log != [] and s2.rng_seed == 1, str(cut), cap="injectable_events")

    # =======================================================================
    print("[13] strictness summary, capability coverage, live-firmware smoke")
    # =======================================================================
    check("every unmodelled construct raised FbbNotModelled above - spot check across layers (type, namespace, action, "
          "outcome, entity)",
          all(isinstance(raises(f), H.FbbNotModelled) for f in (
              lambda: H.FbbSim(mkfw([G("x", "Mystery")])),
              lambda: new_sim().run_lambda("ecco_fallback::nope();"),
              lambda: H.FbbSim(mkfw(BASE_G, [S("a", [{"component.update": "x"}])])).start_script("a"),
              lambda: H.FbbSim(mkfw(BASE_G, [S("a", [{"if": {"condition": {"binary_sensor.is_on": "x"}, "then": []}}])])).start_script("a"),
              lambda: H.FbbSim(mkfw(BASE_G, [S("a", [{"wait_until": {"condition": {"binary_sensor.is_on": "x"}}}])])).start_script("a"),
              lambda: H.FbbSim(mkfw(BASE_G)).ent("x").something)), cap="strictness")
    live = ds.load_firmware(FIRMWARE_PATH)
    polls = {}
    for sid in ("poll_inverter_telemetry", "poll_inverter_configuration_dispatch"):
        x = H.FbbSim(live)
        x.set_modbus_mode("deferred", 120)
        x.bank.update({i: i for i in range(0, 400)})
        try:
            task = x.start_script(sid)
            running = sid in x.running
            x.run_until_idle(max_ms=60_000)
            polls[sid] = (running, len([w for w in x.wire_log if w.kind == "read"]) >= 2, sid not in x.running)
        except BaseException as e:  # noqa: BLE001
            polls[sid] = f"{type(e).__name__}: {e}"
    check("the LIVE firmware's real telemetry poll and configuration poll scripts run on the engine as participants (running "
          "while parked in their 2.5 s delays, at least two reads on the wire, then finished) - the foreign traffic a REVIEW "
          "test can use instead of an injected frame", all(v == (True, True, True) for v in polls.values()) and len(polls) == 2,
          str(polls), cap="foreign_frames")
    missing = sorted(set(H.FbbSim.CAPABILITIES) - COVERED)
    check(f"every one of the {len(H.FbbSim.CAPABILITIES)} documented capabilities (FbbSim.CAPABILITIES) was exercised by a "
          "passing check above", not missing, f"never exercised: {missing}")
    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B1 harness self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
