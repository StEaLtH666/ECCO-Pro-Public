#!/usr/bin/env python3
"""FB-B2 - self-tests of the FB-B2 simulator extensions and of the scenario driver (Phase-0 style).

The FB-B2 behavioural suites execute the REAL firmware YAML (SAVE / INVALIDATE / the arm / the api action) through
registry/tests/_fbb_harness.FbbSim and drive it with registry/tests/_fbb2_drive.Driver. This file proves the harness itself,
each capability against its specification and with a negative control that fails LOUDLY (FbbNotModelled), using small synthetic
YAML fixtures built here and the live FB-B1 / FB-B2 firmware for everything that already exists. It does not depend on the
FB-B2 firmware or on registry/fallback_save.py being final: the SAVE-shaped lambdas it runs are the synthetic ones of
_fbb2_synth.py, the `ecco_fbsave::` adapter is exercised over the test double _fbb2_save_double.py (and, generically, over the
real mirror when it exists).

  [1] esphome::StringRef and the std::string members: size / str() / c_str() NOT NUL-terminated (the over-read is real),
      operators, conversions, mutators, std::string(ptr, n), std::string has no str()
  [2] call_api on the engine: StringRef variables, then: lambda / if (lambda condition) / script.execute / delay on the same
      scheduler, concurrency, strictness; the REAL ha_supervision_heartbeat action and a mutant of it (c_str() over-read)
  [3] template switches: turn_on_action / turn_off_action run every time, optimistic publish with the Deduplicator,
      on_turn_on / on_turn_off / on_state, ALWAYS_OFF at boot, operator flips on the timeline, reboot, strictness
  [4] the write-allowing NVS audit: DirectNvs.sets / before_op, Since.violations_fb (and Since.violations unchanged)
  [5] the `ecco_fbsave::` namespace: introspection over a mirror module, lazy / missing mirror, the real mirror when present
  [6] the ecco_fbdurable names the SAVE / INVALIDATE lambdas use (MirrorRecords{}, seal_provision, validate_transition, ...)
  [7] syntax-level lambda compile: the api-action / switch-action walker, StringRef / switch / clock stubs, the ecco_fbsave
      header staging, negative controls that are real compiler rejections
  [8] the scenario driver against the LIVE firmware (boot, review, seeds, leases, bank hooks, supervision, time, reboot, cuts)
  [9] the scenario driver over a synthetic SAVE / INVALIDATE (arm, execute, exact bytes, reboot, power-cut sweeps, faults)
 [10] harness mutants: 13 deliberately broken synthetic SAVE / INVALIDATE lambdas, each killed by a named driver scenario
[10b] harness-code mutants: 18 in-place breakages of the harness itself (dedup, operator flip, StringRef over-read, the audit,
      the set log, the adapter fixes, the lambda walker, the save-header staging ...), each killed by a named probe
 [11] regression guards for the FB-B1 harness and the capability coverage

No I/O beyond reading repository files and compiling in a temporary directory, no hardware.
"""

from __future__ import annotations

import copy
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "registry"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbb1_lambda_compile as LC  # noqa: E402
import _fbb1_types as T  # noqa: E402
import _fbb2_drive as D  # noqa: E402
import _fbb2_save_double as DBL  # noqa: E402
import _fbb2_synth as S  # noqa: E402
import _fbb_harness as H  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FAILURES: list[str] = []
COVERED: set[str] = set()
NCHECKS = [0]


def check(name: str, condition: bool, detail: str = "", cap: str | None = None) -> None:
    NCHECKS[0] += 1
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


def compile_jobs() -> int:
    """The compiler-job cap in force: ECCO_CAPPED_JOBS (set by the heavy-batch wrapper: 6, or 4 after a memory fallback), else the CPU
    count; never above 6. [7] runs at most this many g++ processes at once (see `capped_compiles`)."""
    try:
        n = int(os.environ.get("ECCO_CAPPED_JOBS", ""))
    except ValueError:
        n = os.cpu_count() or 4
    return max(1, min(6, n))


def lambda_keys(node, in_handler=False) -> tuple:
    """(lambda nodes, lambda nodes under a Modbus reply handler) of a parsed YAML subtree: a plain recursive count of the `lambda` keys,
    deliberately NOT sharing code with the walker under test (_fbb1_lambda_compile._walk), so it is an independent oracle for it."""
    n = h = 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "lambda":
                n += 1
                h += int(in_handler)
            else:
                a, b = lambda_keys(v, in_handler or k in ("on_response", "on_error", "on_no_response", "on_not_sent", "on_custom_response"))
                n, h = n + a, h + b
    elif isinstance(node, list):
        for v in node:
            a, b = lambda_keys(v, in_handler)
            n, h = n + a, h + b
    return n, h


class capped_compiles:
    """Context: at most `compile_jobs()` compiler processes run at once, however many threads ask (LC.compile_source is the one place a
    g++ is started; the pools of [7] nest, so the thread count alone would not bound it)."""

    def __enter__(self):
        self._sem = threading.BoundedSemaphore(compile_jobs())
        self._orig = LC.compile_source
        sem, orig = self._sem, self._orig

        def capped(*a, **k):
            with sem:
                return orig(*a, **k)
        LC.compile_source = capped
        return self

    def __exit__(self, *exc):
        LC.compile_source = self._orig
        return False


# ---------------------------------------------------------------------------
# fixture builders (the shapes of test_fallback_capture_harness.py)
# ---------------------------------------------------------------------------
def G(i, t, v=None):
    g = {"id": i, "type": t, "restore_value": "no"}
    if v is not None:
        g["initial_value"] = v
    return g


def L(code):
    return {"lambda": code}


def S_(i, then, mode=None):
    s = {"id": i, "then": then}
    if mode:
        s["mode"] = mode
    return s


def mkfw(globals_=(), scripts=(), actions=(), switches=(), text_sensors=(), buttons=()):
    return {"globals": list(globals_), "script": list(scripts), "_substitutions": {}, "sensor": [],
            "api": {"actions": list(actions)}, "interval": [], "button": list(buttons), "text_sensor": list(text_sensors),
            "switch": list(switches), "esphome": {}}


BASE_G = [G("s", "std::string", '""'), G("t", "std::string", '""'), G("c", "std::string", '""'), G("u", "uint32_t", "0"),
          G("w", "uint32_t", "0"), G("n", "uint8_t", "0"), G("b", "bool", "false"), G("f", "float", "0")]


def new_sim(actions=(), scripts=(), switches=(), globals_=None, **kw):
    return H.FbbSim(mkfw(BASE_G if globals_ is None else globals_, scripts, actions, switches), **kw)


def api(name, then, **variables):
    return {"action": name, "variables": variables or {"action": "string", "target_id": "string", "confirmation": "string"},
            "then": then}


def lam(code, sim=None, show=(), **kw):
    """('ok', {global: value}) or ('raise', the exception)."""
    s = sim or new_sim(**kw)
    try:
        s.run_lambda(code)
    except BaseException as e:  # noqa: BLE001
        return "raise", e
    return "ok", {k: str(s.g[k]) if isinstance(s.g[k], str) else s.g[k] for k in show}


def main() -> int:
    t_start = time.time()
    SR, CP = T.StringRef, T.CPtr

    # =======================================================================
    print("[1] esphome::StringRef and the std::string members")
    # =======================================================================
    r = SR("SAVE 1234")
    check("StringRef: size() / length() / empty() / str() (an FCStr copy)",
          r.size() == 9 and r.length() == 9 and not r.empty() and SR("").empty() and r.str() == "SAVE 1234"
          and isinstance(r.str(), T.FCStr) and r.str().size() == 9, cap="string_ref")
    p = r.c_str()
    check("c_str() is NOT NUL-terminated: it is a CPtr whose text runs on into the bytes behind the string (the protobuf buffer)",
          isinstance(p, CP) and str(p) == "SAVE 1234" + T.STRINGREF_TAIL and str(p) != r.str(), cap="string_ref")
    check("the bytes behind the string are configurable (tail=); an empty tail makes c_str() look terminated",
          str(SR("ab", tail="XY").c_str()) == "abXY" and str(SR("ab", tail="").c_str()) == "ab", cap="string_ref")
    check("a `const char *` has no members: ptr.size() / ptr.find() are compile errors in C++ -> FbbNotModelled, never a silent str method",
          raises(lambda: p.size()) is not None and raises(lambda: p.find("S")) is not None
          and raises(lambda: p.upper()) is not None and str(p).startswith("SAVE"), cap="string_ref")
    check("== / != against std::string, const char *, another StringRef and the reflected order",
          r == "SAVE 1234" and r == T.FCStr("SAVE 1234") and r == ds.CStr("SAVE 1234") and "SAVE 1234" == r
          and T.FCStr("SAVE 1234") == r and r == SR("SAVE 1234") and r != "SAVE 123" and "x" != r and T.FCStr("a") != SR("b")
          and not (r != "SAVE 1234"), cap="string_ref")
    check("comparing with the over-read c_str() pointer is NOT equal (the pointer reads on past the view); with an empty tail it is",
          (r == p) is False and SR("a", tail="") == SR("a", tail="").c_str(), cap="string_ref")
    check("operator< exists only between two StringRefs; bool(StringRef) does not compile",
          SR("a") < SR("b") and not (SR("b") < SR("a")) and raises(lambda: SR("a") < "b") is not None
          and raises(lambda: bool(r)) is not None, cap="string_ref")
    check("operator+ with const char * / std::string yields a std::string (both orders); StringRef + StringRef is ambiguous (error)",
          r + "x" == "SAVE 1234x" and "x" + r == "xSAVE 1234" and T.FCStr("x") + r == "xSAVE 1234"
          and isinstance(r + "x", T.FCStr) and raises(lambda: r + SR("y")) is not None, cap="string_ref")
    check("starts_with / compare (3-way, memcmp order) / find / substr / operator[]",
          r.starts_with("SAVE ") and not r.starts_with("SAVEX") and r.starts_with(SR("SA")) and r.compare("SAVE 1234") == 0
          and r.compare("SAVE 1235") < 0 and r.compare("SAVE 123") > 0 and r.find("1234") == 5 and r.find("b") == T.NPOS
          and r.find("S", 1) == T.NPOS and r.substr(5) == "1234" and r.substr(0, 4) == "SAVE" and r.substr(99) == ""
          and r.substr(5, 99) == "1234" and r[0] == "S" and r[8] == "4" and raises(lambda: r[9]) is not None, cap="string_ref")
    check("find(const char *) is strstr over the NUL-terminated text, then the match must lie inside the view: a needle that "
          "only matches across the end of the view (into the bytes behind it) is not found",
          SR("ab", tail="cd").find("bc") == T.NPOS and SR("ab", tail="cd").find("b") == 1 and SR("ab", tail="cd").find("cd") == T.NPOS,
          cap="string_ref")
    check("a StringRef is an immutable view: copies are itself, unknown members and stores raise",
          copy.deepcopy(r) is r and copy.copy(r) is r and raises(lambda: r.nope()) is not None
          and raises(lambda: setattr(r, "x", 1)) is not None and raises(lambda: r.replace("a", "b")) is not None,
          cap="string_ref")
    check("a std::string has NO str() member (only StringRef does): FCStr.str() raises FbbNotModelled - the lambda would not compile",
          raises(lambda: T.FCStr("x").str()) is not None, cap="string_mutators")
    fs = T.FCStr("hello world")
    check("std::string accessors the new lambdas may use: data / front / back / rfind / starts_with / ends_with / find / compare",
          fs.data() == fs and fs.front() == "h" and fs.back() == "d" and fs.rfind("o") == 7 and fs.rfind("o", 6) == 4
          and fs.rfind("zz") == T.NPOS and fs.starts_with("hello") and fs.ends_with("world") and not fs.ends_with("x")
          and fs.find("lo") == 3 and fs.compare("hello") > 0 and raises(lambda: T.FCStr("").front()) is not None
          and raises(lambda: T.FCStr("").back()) is not None, cap="string_mutators")
    check("str_mut: assign / append (string, (ptr, n), (count, char)) / clear / push_back / pop_back / erase / resize / insert",
          T.str_mut("assign", "x", "abc") == "abc" and T.str_mut("append", "ab", "cd") == "abcd"
          and T.str_mut("append", "ab", "cdef", 2) == "abcd" and T.str_mut("append", "ab", 3, "z") == "abzzz"
          and T.str_mut("assign", "ab", 2, "q") == "qq" and T.str_mut("clear", "abc") == "" and T.str_mut("push_back", "ab", "c") == "abc"
          and T.str_mut("pop_back", "abc") == "ab" and T.str_mut("erase", "abcdef", 1, 2) == "adef"
          and T.str_mut("erase", "abcdef", 3) == "abc" and T.str_mut("erase", "abc") == "" and T.str_mut("resize", "abc", 2) == "ab"
          and T.str_mut("resize", "ab", 4, "x") == "abxx" and T.str_mut("insert", "ad", 1, "bc") == "abcd"
          and T.str_mut("reserve", "ab", 100) == "ab" and isinstance(T.str_mut("append", "a", "b"), T.FCStr), cap="string_mutators")
    check("str_mut strictness: pop_back of empty, erase / insert past the end, a (ptr, n) longer than the text, replace / swap, an unknown op",
          all(raises(f) is not None for f in (lambda: T.str_mut("pop_back", ""), lambda: T.str_mut("erase", "ab", 5),
                                              lambda: T.str_mut("insert", "ab", 5, "x"), lambda: T.str_mut("append", "ab", "cd", 9),
                                              lambda: T.str_mut("replace", "ab", 0, 1, "x"), lambda: T.str_mut("swap", "ab", "c"),
                                              lambda: T.str_mut("frobnicate", "ab"))), cap="string_mutators")
    check("str_from: (), (string), (StringRef), (header TextBuf), (ptr, n), (count, char); a ptr with a size reads exactly the view, "
          "without one it reads on",
          T.str_from() == "" and T.str_from("ab") == "ab" and T.str_from(SR("ab")) == "ab" and T.str_from(DBL.TextBuf("tb")) == "tb"
          and T.str_from(SR("ab").c_str(), 2) == "ab" and T.str_from(SR("ab").c_str()) == "ab" + T.STRINGREF_TAIL
          and T.str_from(3, "x") == "xxx" and raises(lambda: T.str_from(SR("ab").c_str(), 99)) is not None
          and raises(lambda: T.str_from(5.5)) is not None, cap="string_mutators")
    st_, vals = lam('id(s) = "ab"; id(s).append("cd"); id(s).push_back(\'e\'); std::string l = "xyz"; l.assign("12345"); l.erase(1, 2); '
                    'id(t) = l; id(u) = id(s).size(); id(s).clear(); id(w) = std::string("hello", 3).size(); '
                    'std::string m(id(t).c_str(), 2); id(c) = m; std::string k(3, \'z\'); id(n) = k.size();', show=("s", "t", "u", "w", "c", "n"))
    check("transpiled: the mutators as statements on a global and a local, std::string(ptr, n) as an expression and a declaration, "
          "std::string(count, char)",
          st_ == "ok" and vals == {"s": "", "t": "145", "u": 5, "w": 3, "c": "14", "n": 3}, str(vals), cap="string_mutators")
    check("transpiled strictness: replace() raises FbbNotModelled; .str() on a std::string raises; a mutator through a reference raises",
          lam('std::string l = "a"; l.replace(0, 1, "b");')[0] == "raise"
          and isinstance(lam('std::string l = "a"; id(w) = l.str().size();')[1], H.FbbNotModelled)
          and isinstance(lam('std::string &r = id(s); r.append("x");')[1], H.FbbNotModelled), cap="string_mutators")

    # =======================================================================
    print("[2] call_api: an api action on the engine")
    # =======================================================================
    route = api("exec", [
        L("id(s) = action.str();\nid(t) = target_id;\nid(c) = confirmation;\nid(u) = confirmation.size();"),
        {"if": {"condition": {"lambda": 'return action == "INVALIDATE";'}, "then": [{"script.execute": "inv"}],
                "else": [{"script.execute": "sav"}]}}])
    scripts = [S_("sav", [L("id(n) = 1;")]), S_("inv", [L("id(n) = 2;")])]
    sim = new_sim([route], scripts)
    tk = sim.call_api("exec", action="INVALIDATE", target_id="ABC", confirmation="INVALIDATE ABC")
    check("call_api runs the action's then: (lambda copying StringRefs to std::string globals, `if` with a lambda condition, "
          "script.execute) and returns the finished Task",
          tk.done and tk.label == "api:exec" and (str(sim.g["s"]), str(sim.g["t"]), str(sim.g["c"]), sim.g["u"], sim.g["n"])
          == ("INVALIDATE", "ABC", "INVALIDATE ABC", 14, 2), cap="call_api")
    sim.call_api("exec", action="SAVE", target_id="X", confirmation="Y")
    sim.call_api("exec", action="RESTORE", target_id="", confirmation="")
    check("the else branch routes everything that is not INVALIDATE to the second script, an empty StringRef is an empty string",
          sim.g["n"] == 1 and str(sim.g["s"]) == "RESTORE" and str(sim.g["t"]) == "" and sim.g["u"] == 0, cap="call_api")
    check("an api action is not a script: no running state, no mode: single - and the call is on the timeline",
          "exec" not in sim.running and ("task", "api:exec", "start") in sim.events and ("task", "api:exec", "done") in sim.events,
          cap="call_api")
    sim = new_sim([api("ovr", [L('std::string a = confirmation.c_str(); std::string b(confirmation.c_str(), confirmation.size());\n'
                                  'id(s) = a; id(t) = b; id(u) = a.size(); id(w) = confirmation.size();')])])
    sim.call_api("ovr", action="a", target_id="b", confirmation="SAVE")
    over = (str(sim.g["s"]), str(sim.g["t"]), sim.g["u"], sim.g["w"])
    sim.call_api("ovr", action="a", target_id="b", confirmation="SAVE", _tail="")
    check("StringRef::c_str() over-reads in a lambda: `std::string a = x.c_str()` carries the bytes behind the string, "
          "`std::string(x.c_str(), x.size())` is exact (a lambda that does the first is a bug the harness can SEE)",
          over == ("SAVE" + T.STRINGREF_TAIL, "SAVE", 4 + len(T.STRINGREF_TAIL), 4)
          and (str(sim.g["s"]), str(sim.g["t"])) == ("SAVE", "SAVE"), str(over), cap="string_ref")
    sim = new_sim([api("conv", [L('id(s) = action; id(t) = std::string(target_id); std::string x = confirmation; id(c) = x + "|" + action;\n'
                                  'id(n) = (action == "A") + (target_id != "B") * 2 + (confirmation == id(c)) * 4;')])])
    sim.call_api("conv", action="A", target_id="B", confirmation="C")
    check("the implicit conversion to std::string: assignment to a global, std::string(x), a local copy, concatenation; == / != "
          "against literals and std::string globals",
          (str(sim.g["s"]), str(sim.g["t"]), str(sim.g["c"]), sim.g["n"]) == ("A", "B", "C|A", 1), cap="string_ref")
    sim = new_sim([api("mix", [L("id(w) = n_; id(b) = flag; id(f) = r; id(s) = str_;")], n_="int", flag="bool", r="float", str_="string")])
    sim.call_api("mix", n_=7, flag=True, r=1.5, str_="hi")
    check("bool / int / float api variables arrive as plain values (int wrapped to int32), string as StringRef",
          (sim.g["w"], sim.g["b"], sim.g["f"], str(sim.g["s"])) == (7, True, 1.5, "hi"), cap="call_api")
    sim = new_sim([api("park", [L("id(n) = 1;"), {"delay": "100ms"}, L("id(n) = 2;"), {"script.execute": "slow"}]),
                   api("later", [{"wait_until": {"condition": {"lambda": "return id(b);"}, "timeout": "1s"}}, L("id(u) = 9;")])],
                  [S_("slow", [{"delay": "500ms"}, L("id(w) = 1;")])])
    tk = sim.call_api("park", action="a", target_id="b", confirmation="c")
    mid = (tk.done, tk.parked, sim.g["n"], "slow" in sim.running)
    sim.run_for(100)
    after_delay = (tk.done, sim.g["n"], "slow" in sim.running)
    sim.run_until_idle()
    check("an api action whose then: parks (delay / wait_until) returns at the first park; the engine finishes it later; the script it "
          "started keeps running after the action is done",
          mid == (False, "delay", 1, False) and after_delay == (True, 2, True) and sim.g["w"] == 1, str((mid, after_delay)), cap="call_api")
    sim = new_sim([api("later", [{"wait_until": {"condition": {"lambda": "return id(b);"}, "timeout": "1s"}}, L("id(u) = 9;")],
                       action="string")])
    t1 = sim.call_api("later", action="x")
    t2 = sim.call_api("later", action="y")
    both = (t1.parked, t2.parked, [t.label for t in sim.tasks if not t.done])
    sim.g["b"] = True
    sim.run_for(20)
    check("two calls of the same action run side by side (no mode: single for an api action) and both finish when the condition holds",
          both == ("wait", "wait", ["api:later", "api:later"]) and t1.done and t2.done and sim.g["u"] == 9, str(both), cap="call_api")
    sim = new_sim([route], scripts)
    t0 = sim.now_ms
    sim.at_api(t0 + 250, "exec", action="SAVE", target_id="a", confirmation="b")
    sim.run_until(t0 + 249)
    before = sim.g["n"]
    sim.run_until(t0 + 250)
    check("at_api() schedules the call at an absolute virtual time", before == 0 and sim.g["n"] == 1, cap="call_api")
    check("call_api strictness: an unknown action, a missing variable, an extra variable, a non-string for a string variable, an "
          "unmodelled variable type, two actions with one name",
          all(raises(f) is not None for f in (
              lambda: sim.call_api("nope", action="a", target_id="b", confirmation="c"),
              lambda: sim.call_api("exec", action="a", target_id="b"),
              lambda: sim.call_api("exec", action="a", target_id="b", confirmation="c", extra="d"),
              lambda: sim.call_api("exec", action=5, target_id="b", confirmation="c"),
              lambda: new_sim([api("v", [L("id(n) = 1;")], x="std::vector<int>")]).call_api("v", x=[1]),
              lambda: new_sim([api("d", [L("")]), api("d", [L("")])]).call_api("d", action="a", target_id="b", confirmation="c"))),
          cap="call_api")
    sim = new_sim([api("cond", [{"if": {"condition": {"binary_sensor.is_on": "x"}, "then": []}}])])
    check("an api action with a non-lambda condition / an unmodelled action raises FbbNotModelled (never skipped)",
          raises(lambda: sim.call_api("cond", action="a", target_id="b", confirmation="c")) is not None
          and raises(lambda: new_sim([api("o", [{"component.update": "x"}])]).call_api("o", action="a", target_id="b", confirmation="c"))
          is not None, cap="call_api")
    # ---- the REAL heartbeat action
    live = D.load_fw()
    sim = H.FbbSim(live)
    sim.run_boot()
    ch = str(sim.g["supervision_challenge"])
    tk = sim.call_api("ha_supervision_heartbeat", challenge=ch)
    ok1 = (tk.done, sim.g["supervision_valid_count"], sim.g["supervision_state"], sim.g["supervision_have_valid"],
           str(sim.g["supervision_challenge"]) != ch, str(sim.g["supervision_previous_challenge"]) == ch)
    sim.call_api("ha_supervision_heartbeat", challenge="WRONG")
    sim.call_api("ha_supervision_heartbeat", challenge="")
    sim.call_api("ha_supervision_heartbeat", challenge=ch)
    check("the REAL ha_supervision_heartbeat action runs through call_api: a valid beat consumes the challenge and publishes the next, "
          "a wrong / empty / replayed challenge is counted invalid with its reason (`challenge.str()` on a StringRef)",
          ok1 == (True, 1, 1, True, True, True) and sim.g["supervision_invalid_count"] == 3
          and str(sim.g["supervision_last_invalid_reason"]) == "STALE CHALLENGE (already consumed)", str(ok1), cap="call_api")
    src = live["_text"]
    needle = "std::string received = challenge.str();"
    mutant = src.replace(needle, "std::string received = challenge.c_str();")
    check("(setup) the heartbeat mutant text differs from the live firmware in exactly one line", src.count(needle) == 1 and mutant != src)
    msim = H.FbbSim(D.load_fw(mutant))
    msim.run_boot()
    msim.call_api("ha_supervision_heartbeat", challenge=str(msim.g["supervision_challenge"]))
    check("MUTANT: the heartbeat reading `challenge.c_str()` instead of `.str()` is KILLED - the unterminated pointer over-reads, the valid "
          "challenge is rejected as WRONG CHALLENGE (the exact bug class StringRef has)",
          msim.g["supervision_valid_count"] == 0 and str(msim.g["supervision_last_invalid_reason"]) == "WRONG CHALLENGE", cap="string_ref")
    msim.call_api("ha_supervision_heartbeat", challenge=str(msim.g["supervision_challenge"]), _tail="")
    check("... and the same mutant passes when the bytes behind the string happen to be empty (so only the over-read tail kills it)",
          msim.g["supervision_valid_count"] == 1)

    # =======================================================================
    print("[3] template switches")
    # =======================================================================
    sg = BASE_G + [G("stamp", "uint32_t", "0"), G("n_on", "uint32_t", "0"), G("n_off", "uint32_t", "0"), G("cb_on", "uint32_t", "0"),
                   G("cb_off", "uint32_t", "0"), G("last_x", "uint8_t", "0")]
    sw_arm = {"id": "arm", "platform": "template", "optimistic": True, "restore_mode": "ALWAYS_OFF",
              "turn_on_action": [L("id(stamp) = millis(); id(n_on) += 1;")], "turn_off_action": {"then": [L("id(n_off) += 1;")]},
              "on_turn_on": [L("id(cb_on) += 1;")], "on_turn_off": {"then": [L("id(cb_off) += 1;")]},
              "on_state": [L("id(last_x) = x ? 1 : 2;")]}
    sw_plain = {"id": "plain", "platform": "template", "optimistic": True, "restore_mode": "RESTORE_DEFAULT_OFF"}
    sw_manual = {"id": "manual", "platform": "template", "optimistic": False, "restore_mode": "ALWAYS_OFF",
                 "turn_on_action": [L("id(n_on) += 100;")]}
    sw_on = {"id": "alwayson", "platform": "template", "optimistic": True, "restore_mode": "ALWAYS_ON"}
    sw_inv = {"id": "inv", "platform": "template", "optimistic": True, "inverted": True, "restore_mode": "ALWAYS_OFF"}
    swsim = lambda **kw: H.FbbSim(mkfw(sg, switches=[sw_arm, sw_plain, sw_manual, sw_on, sw_inv]), **kw)  # noqa: E731
    sim = swsim()
    check("restore modes at boot: ALWAYS_OFF / RESTORE_DEFAULT_OFF off, ALWAYS_ON on; nothing was published or run at boot",
          [sim.ent(x).state for x in ("arm", "plain", "manual", "alwayson")] == [False, False, False, True]
          and sim.ent("arm").published == [] and sim.g["n_on"] == 0 and sim.g["cb_off"] == 0, cap="template_switch")
    sim.now_ms = 5_000
    sim.operator_switch("arm", True)
    check("Home Assistant switch.turn_on: turn_on_action ran (millis() stamped), the optimistic state was published once, on_turn_on and "
          "on_state(x) fired",
          (sim.ent("arm").state, sim.g["stamp"], sim.g["n_on"], sim.ent("arm").published, sim.g["cb_on"], sim.g["last_x"])
          == (True, 5000, 1, [True], 1, 1), cap="template_switch")
    sim.now_ms = 5_500
    sim.operator_switch("arm", True)
    check("turn_on() while already ON runs the turn_on_action AGAIN (the stamp is refreshed) but publish_state() deduplicates: nothing "
          "new is published and on_turn_on does not fire again",
          (sim.g["stamp"], sim.g["n_on"], sim.ent("arm").published, sim.g["cb_on"]) == (5500, 2, [True], 1), cap="template_switch")
    sim.run_lambda("id(arm).turn_off();")
    check("turn_off() from a lambda: turn_off_action (the {then: [...]} form), state False, published, on_turn_off / on_state(x=false)",
          (sim.ent("arm").state, sim.g["n_off"], sim.ent("arm").published, sim.g["cb_off"], sim.g["last_x"])
          == (False, 1, [True, False], 1, 2), cap="template_switch")
    sim.run_lambda("id(arm).turn_off(); id(arm).turn_off();")
    check("turn_off() on an OFF switch still runs turn_off_action every time, publishes nothing",
          (sim.g["n_off"], sim.ent("arm").published, sim.g["cb_off"]) == (3, [True, False], 1), cap="template_switch")
    sim = swsim()
    sim.run_lambda("id(arm).turn_off();")
    check("boot Deduplicator: the ALWAYS_OFF boot value counts as published, so the first turn_off() after boot publishes nothing",
          (sim.g["n_off"], sim.ent("arm").published, sim.g["cb_off"]) == (1, [], 0), cap="template_switch")
    sim.run_lambda("id(arm).toggle();")
    check("toggle() flips through the same write path", sim.ent("arm").state is True and sim.g["n_on"] == 1, cap="template_switch")
    sim.ent("alwayson").set(True)
    sim.run_lambda("id(alwayson).turn_off();")
    sim.ent("plain").set(True)
    sim.run_lambda("id(plain).turn_off();")
    check("a test that forces the state with .set() (the write arms) does not break a later turn_off() from a lambda (the forced state "
          "is the last 'published' one)", sim.ent("alwayson").state is False and sim.ent("plain").state is False, cap="template_switch")
    sim.run_lambda("id(manual).turn_on();")
    held = (sim.ent("manual").state, sim.g["n_on"])
    sim.run_lambda("id(manual).publish_state(true);")
    check("a non-optimistic switch runs the action but keeps its state until the action / lambda publishes (publish_state(true))",
          held == (False, 101) and sim.ent("manual").state is True and sim.ent("manual").published == [True], cap="template_switch")
    sim.run_lambda("id(plain).turn_on();")
    check("a switch without actions (the nine existing arms) just changes state", sim.ent("plain").state is True, cap="template_switch")
    check("`inverted: true` and an unknown switch id raise FbbNotModelled",
          raises(lambda: sim.run_lambda("id(inv).turn_on();")) is not None and raises(lambda: sim.operator_switch("nope", True)) is not None
          and raises(lambda: sim.operator_switch("plain", True)) is None, cap="template_switch")
    sim = swsim()
    sim.at_operator_switch(sim.now_ms + 300, "arm", True)
    t0 = sim.now_ms
    sim.run_until(t0 + 299)
    early = sim.ent("arm").state
    sim.run_until(t0 + 300)
    check("at_operator_switch() flips the switch at an absolute instant, on the same timeline (events: api, switch write, switch state)",
          early is False and sim.ent("arm").state is True and sim.g["stamp"] == (t0 + 300) and ("api", "switch", "arm", True) in sim.events
          and ("switch", "arm", "write", True) in sim.events and ("switch", "arm", "state", True) in sim.events, cap="operator_events")
    delay_sw = {"id": "dsw", "platform": "template", "optimistic": True, "restore_mode": "ALWAYS_OFF",
                "turn_on_action": [{"delay": "100ms"}, L("id(n_on) += 1;")]}
    sim = H.FbbSim(mkfw(sg, switches=[delay_sw]))
    sim.operator_switch("dsw", True)
    now_ = (sim.ent("dsw").state, sim.g["n_on"])
    sim.run_until_idle()
    check("a turn_on_action that parks (delay) does not hold up the state: the optimistic state is published at once, the action finishes later",
          now_ == (True, 0) and sim.g["n_on"] == 1, cap="template_switch")
    sim = swsim()
    sim.operator_switch("arm", True)
    sim2 = sim.reboot()
    check("a reboot puts the switch back to its restore mode (ALWAYS_OFF) and forgets the stamp; nothing is restored",
          sim2.ent("arm").state is False and sim2.g["stamp"] == 0 and sim.ent("arm").state is True, cap="template_switch")
    sim = swsim()
    snap = sim.snapshot_state()
    sim.operator_switch("arm", True)
    diff = sim.state_diff(snap)
    check("snapshot_state / state_diff see a switch publication and the globals its automations moved",
          diff["published"] == {"arm": ["True"]} and {"stamp", "n_on", "cb_on", "last_x"} <= set(diff["globals"]), str(diff), cap="template_switch")
    sim = H.FbbSim(live)
    sim.ent("free_power_write_enable").set(True)
    sim.run_lambda("id(free_power_write_enable).turn_off();")
    check("the live firmware's nine optimistic switches: a write arm forced ON by a test is turned off by a lambda's turn_off() "
          "(what the writer scripts do)", sim.ent("free_power_write_enable").state is False and sim.ent("dump_write_enable").state is False)
    sim.run_lambda("id(free_power_write_enable).turn_on();")
    check("... and turned on again by turn_on() (no automation on any of them)", sim.ent("free_power_write_enable").state is True)
    check("any non-switch entity keeps the legacy turn_on() / turn_off() (state only)",
          (lambda e: (e.turn_on(), e.state)[1])(sim.ent("some_light")) is True)

    # =======================================================================
    print("[4] the write-allowing NVS audit")
    # =======================================================================
    nv = H.DirectNvs()
    nv.put(D.K_P, b"\x01" * 96)
    nv.set_blob(D.K_W, b"\xaa" * 48)
    nv.set_blob(D.K_P, b"\xbb" * 96)
    check("DirectNvs.sets records every set_blob in call order with its payload and result (ops carries no payload)",
          nv.sets == [(D.K_W, b"\xaa" * 48, 0), (D.K_P, b"\xbb" * 96, 0)] and [o[0] for o in nv.ops] == ["set", "set"], cap="nvs_set_log")
    seen = []
    nv.before_op = lambda op, key: seen.append((op, key))
    nv.get_blob(D.K_P, None)
    nv.get_blob(D.K_P, 96)
    nv.get_stats()
    nv.set_blob(D.K_P, b"\xcc" * 96)
    check("DirectNvs.before_op sees every operation before it takes effect: get (size probe), read (data), stats, set - with decimal keys",
          seen == [("get", D.FBP_DEC), ("read", D.FBP_DEC), ("stats", None), ("set", D.FBP_DEC)], str(seen), cap="nvs_set_log")

    def cut_before(op, key):
        if op == "set" and key == D.FBP_DEC:
            raise H.PowerCut("before the FBP set")
    nv.before_op = cut_before
    err = raises(lambda: nv.set_blob(D.K_P, b"\xdd" * 96), H.PowerCut)
    check("a before_op hook can cut the power BEFORE the set: nothing is written, nothing is logged, the event counter did not move",
          err is not None and nv.blobs[D.K_P].data == b"\xcc" * 96 and len(nv.sets) == 3, cap="nvs_set_log")
    d = D.Driver(fw=S.with_mini_save(live), api=S.SYNTH_API, arm=S.SYNTH_ARM, arm_on_ms_global="fbs_synth_arm_on_ms")
    d.review(expect="CANDIDATE_READY")
    words = d.bank_words()
    exp_p = fp.seal_profile(fp.blank_profile(**{**D.GOLD_FIELDS, "generation": 8, "captured_epoch": D.EPOCH0, "binding": 0}))
    exp_w = fd.make_provision(8, exp_p["binding"], 7, D.GOLD["binding"], D.K_P, 1, fd.PROV_OP_SAVE)
    exp = {"FBW": fd.pack_provision(exp_w), "FBP": fp.pack_profile(exp_p)}
    st = d.save()
    check("(setup) a synthetic SAVE commits g7 -> g8: FBW then FBP", st.b9 == "SAVED - synthetic" and st.fb_set_order == ["FBW", "FBP"])
    check("Since.violations_fb: the expected ordered FB sets with exactly the independently derived bytes, zero Modbus writes -> clean",
          st.violations_fb(("FBW", "FBP"), bytes_=exp) == [] and st.violations_fb((D.K_W, D.FBP_DEC), bytes_=[exp["FBW"], exp["FBP"]]) == []
          and st.violations_fb(("FBW", "FBP"), bytes_=exp, reads=[]) == [], cap="fb_write_audit")
    check("Since.violations() (the FB-B1 read-only contract) STILL flags those same two NVS sets - it is unchanged",
          len(st.violations()) == 1 and "direct NVS sets" in st.violations()[0], cap="fb_write_audit")
    check("negative controls: wrong order expected, FBP only expected, nothing expected, an extra expected set, a different byte",
          all(st.violations_fb(e) for e in (("FBP", "FBW"), ("FBP",), (), ("FBW", "FBP", "FBP")))
          and "bytes" in "".join(st.violations_fb(("FBW", "FBP"), bytes_={**exp, "FBP": exp["FBP"][:-1] + bytes([exp["FBP"][-1] ^ 1])}))
          and "bytes" in "".join(st.violations_fb(("FBW", "FBP"), bytes_=[exp["FBP"], exp["FBW"]])), cap="fb_write_audit")
    m = d.sim.mark()
    d.sim.nvs_direct.set_blob(0x1234, b"x")
    d.sim.nvs_direct.set_blob(D.K_S, bytes(fp.FAILBACK_SIZE))
    sn = d.sim.since(m)
    check("a direct-NVS set to a key that is neither FBP nor FBW is flagged, and a set of FBS is flagged on its own (FBS is never written in FB-B)",
          any("not FBP / FBW" in v for v in sn.violations_fb(("FBS",))) and any("FBS" in v for v in sn.violations_fb(("FBS",)))
          and sn.other_nvs_sets == [fd.decimal_key(0x1234)] and sn.fb_set_order == ["FBS"], str(sn.violations_fb(("FBS",))),
          cap="fb_write_audit")
    m = d.sim.mark()
    d.sim.modbus_log.append(("write", 232, [1], "ok"))
    d.sim.nvs_commits.append(("tag", ds.Record("ValidMarker", 1, 1)))
    sn = d.sim.since(m)
    check("any Modbus write and any ecco_durable commit are flagged (the commit only when allow_legacy is not set)",
          any("Modbus writes" in v for v in sn.violations_fb(())) and any("ecco_durable commits" in v for v in sn.violations_fb(()))
          and not any("commits" in v for v in sn.violations_fb((), allow_legacy=True)), cap="fb_write_audit")
    check("fb_key_name accepts a name, the 32-bit key and the decimal key string, and refuses anything else",
          E.fb_key_name("FBW") == "FBW" and E.fb_key_name(D.K_P) == "FBP" and E.fb_key_name(D.FBS_DEC) == "FBS"
          and raises(lambda: E.fb_key_name(7)) is not None, cap="fb_write_audit")
    check("Mark is backwards compatible (the 8-field positional form older suites build still works)",
          E.Since(d.sim, E.Mark(0, 0, 0, 0, 0, 0, 0, {})).nvs_set_log == d.sim.nvs_direct.sets, cap="fb_write_audit")

    # =======================================================================
    print("[5] the `ecco_fbsave::` namespace (introspection over a mirror module)")
    # =======================================================================
    g5 = BASE_G + [G("v", "uint8_t", "0"), G("tb", "std::string", '""')]
    fsim = lambda **kw: H.FbbSim(mkfw(g5, **kw), fbsave=DBL)  # noqa: E731
    sim = fsim()
    sim.run_lambda('id(s) = "SAVE"; id(u) = ecco_fbsave::ARM_TTL_MS; id(w) = ecco_fbsave::PURPOSE_SAVE; id(n) = ecco_fbsave::ACT_SAVE; '
                   'id(v) = ecco_fbsave::action_token(id(s).c_str(), id(s).size());')
    check("ecco_fbsave:: constants (an int, a tuple-unpacked enum) and a pure function over a std::string c_str() / size() resolve through "
          "the mirror module by introspection",
          (sim.g["u"], sim.g["w"], sim.g["n"], sim.g["v"]) == (120000, 2, 1, 1), cap="fbsave_adapter")
    sim.run_lambda('ecco_fbsave::GateIn g{}; g.arm_was_on = true; g.cand_id = 255; g.now_ms = 5; g.bus.mutex = true; g.note = "x";\n'
                   'ecco_fbsave::GateOut o = ecco_fbsave::gate_decide(g, "SAVE", 4, "00000000000000FF", 16);\n'
                   'id(v) = o.code; id(tb) = o.text.c_str();\n'
                   'ecco_fbsave::GateOut o2 = ecco_fbsave::gate_decide(g, "SAVE", 4, "00000000000000FE", 16);\n'
                   'id(n) = o2.code; id(t) = o2.text.c_str();')
    got5 = (sim.g["v"], str(sim.g["tb"]), sim.g["n"], str(sim.g["t"]))
    check("POD structs: brace-init, scalar and NESTED-struct field stores, passing to a function, a result POD with a text field",
          got5 == (1, "", 3, "SAVE REFUSED - candidate ID does not match"), str(got5), cap="fbsave_adapter")
    sim.run_lambda('id(tb) = ecco_fbsave::expected_phrase(ecco_fbsave::ACT_SAVE, 255).c_str(); '
                   'id(b) = ecco_fbsave::arm_expired(millis(), millis() - 120000u); id(u) = ecco_fbsave::first_non_ok(0, 5); '
                   'id(w) = sizeof(ecco_fbsave::GateIn);')
    check("a text builder's TextBuf passes through (.c_str()), a wrap-safe arm_expired over uint32 values, first_non_ok, sizeof via HARNESS_SIZEOF",
          str(sim.g["tb"]) == "SAVE 00000000000000FF" and sim.g["b"] is True and sim.g["u"] == 5 and sim.g["w"] == 40, cap="fbsave_adapter")
    sim.rebase_clock((1 << 32) - 1000)
    sim.run_lambda("id(b) = ecco_fbsave::arm_expired(millis(), millis() - 119999u);")
    off_by_one = sim.g["b"]
    sim.run_lambda("id(b) = ecco_fbsave::arm_expired(millis() + 5u, millis() - 119995u);")
    check("uint32 values reach the mirror as ints and the wrap-safe arithmetic survives the wrap (millis() near 2^32): 119999 ms is not "
          "expired, 120000 ms is", off_by_one is False and sim.g["b"] is True, cap="fbsave_adapter")
    sim = fsim(actions=[api("x", [L('id(v) = ecco_fbsave::action_token(action.c_str(), action.size());\n'
                                    'id(n) = ecco_fbsave::action_token(action.c_str());\n'
                                    'id(t) = ecco_fbsave::unsupported_action_text(action.c_str(), action.size()).c_str();\n'
                                    'id(c) = ecco_fbsave::unsupported_action_text(action.c_str()).c_str();')])])
    sim.call_api("x", action="SAVE", target_id="", confirmation="")
    exact_, over_ = (sim.g["v"], str(sim.g["t"])), (sim.g["n"], str(sim.g["c"]))
    sim.call_api("x", action="we!rd", target_id="", confirmation="", _tail="")
    check("a StringRef c_str() handed to the mirror WITHOUT its size runs on into the next bytes (the token is not recognised, the echo "
          "carries the garbage), WITH its size it is exact - the over-read reaches the pure code",
          exact_ == (1, "REFUSED - unsupported action 'SAVE'") and over_[0] == 0 and "next" in over_[1]
          and str(sim.g["t"]) == "REFUSED - unsupported action 'we?rd'", str((exact_, over_)), cap="fbsave_adapter")
    sim.run_lambda("ecco_fbsave::TextBuf<200> q{}; id(u) = q.size();")
    check("`ecco_fbsave::TextBuf<N>` numeric template arguments are dropped like ecco_fbcap::'s (documented limit)",
          sim.g["u"] == 0, cap="fbsave_adapter")
    check("a missing name, a private name, a module and a wrong call raise FbbNotModelled naming the symbol - never a silent default",
          all(isinstance(lam(code, sim=fsim())[1], H.FbbNotModelled) for code in (
              "id(u) = ecco_fbsave::NOPE;", "id(u) = ecco_fbsave::nope(1);", "id(u) = ecco_fbsave::_private_thing;",
              "id(u) = ecco_fbsave::action_token();")) and "NOPE" in str(lam("id(u) = ecco_fbsave::NOPE;", sim=fsim())[1]), cap="fbsave_adapter")
    sim = H.FbbSim(mkfw(g5), fbsave="no_such_mirror_module")
    e_ = lam("id(u) = ecco_fbsave::ARM_TTL_MS;", sim=sim)[1]
    check("the mirror is imported LAZILY: a firmware that never names ecco_fbsave:: needs no mirror; one that does, with the mirror missing, "
          "raises FbbNotModelled saying so - and the simulator still builds",
          isinstance(e_, H.FbbNotModelled) and "no_such_mirror_module" in str(e_) and lam("id(u) = 1;", sim=sim)[0] == "ok", cap="fbsave_adapter")
    check("the rewrite maps ecco_fbsave::X and a scoped ecco_fbsave::A::B like the other namespaces (and leaves ecco_fbcap / ecco_fallback alone)",
          H.rewrite_fb_namespaces("ecco_fbsave::A(ecco_fbsave::B::C, ecco_fbcap::D, ecco_fallback::E)")
          == "ecco_durable::FBSV__A(ecco_durable::FBSV__B__FBCNS__C, ecco_durable::FBC__D, ecco_durable::FBA__E)", cap="fbsave_adapter")
    import importlib
    try:
        real_mod, real_err = importlib.import_module("fallback_save"), ""
    except Exception as e:  # noqa: BLE001
        real_mod, real_err = None, f"{type(e).__name__}: {e}"
    if real_mod is None and "No module named" in real_err:
        check("registry/fallback_save.py does not exist yet: the ecco_fbsave:: hook stays lazy (nothing above needed it)", True,
              cap="fbsave_adapter")
    else:
        check("registry/fallback_save.py (the real mirror) imports", real_mod is not None, real_err)
    if real_mod is not None:
        rsim = H.FbbSim(mkfw(g5))
        names = [n for n, v in vars(real_mod).items()
                 if not n.startswith("_") and not isinstance(v, type(sys)) and (isinstance(v, (int, str, tuple, list))
                                                                                 or getattr(v, "__module__", None) == real_mod.__name__)]
        bad = []
        for n in names:
            try:
                getattr(rsim.D, "FBSV__" + n)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{n}: {type(e).__name__}: {str(e)[:80]}")
        check(f"every public name the real mirror defines ({len(names)}: constants, structs, functions) resolves through the adapter",
              len(names) >= 10 and not bad, "; ".join(bad[:5]), cap="fbsave_adapter")
        rsim.run_lambda('id(s) = "INVALIDATE"; id(u) = ecco_fbsave::action_token(id(s).c_str(), id(s).size()); '
                        'id(n) = ecco_fbsave::is_invalidate_action(id(s).c_str(), id(s).size());')
        check("the real mirror answers a lambda call (action_token / is_invalidate_action over a std::string)",
              rsim.g["u"] == real_mod.ACT_INVALIDATE and rsim.g["n"] == 1, cap="fbsave_adapter")
        import inspect
        zero_arg = sorted(n for n, f in vars(real_mod).items()
                          if n.endswith("_text") and inspect.isfunction(f) and f.__module__ == real_mod.__name__
                          and all(p_.default is not inspect.Parameter.empty for p_ in inspect.signature(f).parameters.values()))
        bad_text = []
        for n in zero_arg:
            try:
                rsim.run_lambda(f"id(tb) = ecco_fbsave::{n}().c_str();")
                s_ = str(rsim.g["tb"])
                if not s_ or len(s_) > 200:
                    bad_text.append((n, len(s_)))
            except Exception as e:  # noqa: BLE001
                bad_text.append((n, type(e).__name__))
        rsim.run_lambda("ecco_fbcap::CaptureWords w{}; const auto rf = ecco_fbcap::capture_refusals(w, 5000u); "
                        "id(tb) = ecco_fbsave::save_l2_text(rf, w).c_str();")
        check(f"every zero-argument text builder of the real mirror ({len(zero_arg)}) is callable from a lambda and returns a non-empty text of at most 200 "
              "characters; a text builder taking a refusals POD returned by an ecco_fbcap function works (save_l2_text(capture_refusals(...), words))",
              len(zero_arg) >= 10 and not bad_text and str(rsim.g["tb"]).startswith("SAVE REFUSED - ") and str(rsim.g["tb"]).endswith("profile unchanged"),
              str(bad_text[:3]), cap="fbsave_adapter")

    g5q = g5 + [G("q", "uint64_t", "0"), G("seen", "uint32_t", "0")]
    sim = H.FbbSim(mkfw(g5q), fbsave=DBL)
    sim.run_lambda("ecco_fbsave::Wide w{}; w.id64 = 0xD852A4FA2DF7DBA3ULL; id(q) = w.id64; id(seen) = w.seen; w.seen = 0xFFFFFFFFu; id(u) = w.seen;\n"
                   "ecco_fbsave::Planned pl = ecco_fbsave::make_plan(w, 3); id(n) = pl.code; id(w) = pl.p_new.generation;\n"
                   "ecco_fbdurable::EspNvs nvs; ecco_fbdurable::FailbackProvisionV1 wp{}; ecco_fallback::FallbackProfileV1 pp{};\n"
                   "ecco_fbdurable::TxnResult r{};\n"
                   "const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(nvs, pl.w_new, wp, ecco_fbdurable::PriorDesc{1, 0}, "
                   "pl.p_new, pp, ecco_fbdurable::PriorDesc{1, 0}, r); id(v) = (uint8_t) o;")
    check("mirror POD fields with plain `int` annotations keep their width: a uint64_t id (0xD852A4FA2DF7DBA3) and a 0xFFFFFFFF sentinel survive a "
          "store from a lambda untruncated (a bare Python `int` is not a C int)",
          sim.g["q"] == 0xD852A4FA2DF7DBA3 and sim.g["seen"] == 0xFFFFFFFF and sim.g["u"] == 0xFFFFFFFF and sim.g["n"] == 1, cap="fbsave_adapter")
    check("a record the mirror holds as a dict (Plan.p_new / .w_new, the C++ struct members) reads as the harness record a lambda passes to "
          "commit_transition_t: p_new.generation is readable and the writer ran (the prior it was given was a deliberately absent pair)",
          sim.g["w"] == 3 and sim.g["v"] in (fd.TXN_COMMITTED, fd.TXN_NOT_COMMITTED, fd.TXN_UNKNOWN_REBOOT, fd.TXN_REFUSED_LATCHED), cap="fbsave_adapter")
    if real_mod is not None:
        # ---- the call patterns of the header contract (FB_B2_IMPLEMENTATION_NOTES.md section 2: the header call patterns) through the REAL mirror
        dr = D.Driver()
        dr.review(expect="CANDIDATE_READY")
        rs = dr.sim
        rs.run_lambda("const ecco_fbsave::SaveGateResult g1 = ecco_fbsave::save_in_flight_gate(true, false); id(fallback_profile_step) = g1.code;"
                      "id(fallback_profile_obl_text) = g1.text.c_str(); id(fallback_profile_op_started_ms) = g1.arm_off_only;\n"
                      "const ecco_fbsave::SaveGateResult g0 = ecco_fbsave::save_in_flight_gate(false, false); id(fallback_profile_seen_hw_gen) = g0.code;")
        check("save_in_flight_gate (G1): in flight -> SG_IN_FLIGHT with arm_off_only and its text; idle -> SG_UNSET",
              rs.g["fallback_profile_step"] == real_mod.SG_IN_FLIGHT and rs.g["fallback_profile_op_started_ms"] == 1
              and "another Fallback Profile operation is in progress" in str(rs.g["fallback_profile_obl_text"])
              and rs.g["fallback_profile_seen_hw_gen"] == real_mod.SG_UNSET, cap="fbsave_adapter")
        gate = (
            "ecco_fbsave::SaveGateInputs si{}; si.arm_was_on = %s; si.cand_valid = id(fallback_profile_cand_valid); si.cand_saveable = "
            "id(fallback_profile_cand_saveable); si.cand_id = id(fallback_profile_cand_id); si.cand_ms = id(fallback_profile_cand_ms);\n"
            "si.cand_prior_class = id(fallback_profile_cand_prior_class); si.cand_writes_fp = id(fallback_profile_cand_writes_fp); "
            "si.now_ms = millis(); si.writes_fp_now = id(fallback_profile_cand_writes_fp); si.boot_loaded = id(fallback_profile_boot_loaded); "
            "si.unconfirmed = false; si.read_anomaly = id(fallback_profile_read_anomaly); si.hb_ok = true; si.time_trusted = true;\n"
            "ecco_fbcap::GateInputs gi{}; gi.boot_loaded = true; gi.fbs_slot = id(fallback_profile_fbs_slot); "
            "gi.fp.free_power_marker_boot_load = 0; gi.dump.dump_marker_boot_load = 0; gi.r244.reg244_marker_boot_load = 0;\n"
            "const ecco_fbsave::SaveGateResult sr = ecco_fbsave::save_gate_decide(si, \"SAVE\", 4, id(fallback_profile_review_id_text).state.c_str(), 16, "
            "%s, %s, gi);\n"
            "id(fallback_profile_step) = sr.code; id(fallback_profile_obl_text) = sr.text.c_str(); id(fallback_profile_invalidate_reason) = sr.obl.c_str();")
        cid = f"{rs.g['fallback_profile_cand_id']:016X}"
        outcomes = {}
        for label, arm, conf, clen in (("arm off", "false", f'"SAVE {cid}"', 21), ("phrase", "true", '"SAVE nope"', 9), ("ok", "true", f'"SAVE {cid}"', 21)):
            rs.run_lambda(gate % (arm, conf, clen))
            outcomes[label] = (rs.g["fallback_profile_step"], str(rs.g["fallback_profile_obl_text"]))
        check("save_gate_decide over StringRef-free std::string c_str() / size() arguments and a filled SaveGateInputs + capture GateInputs: the arm "
              "check, the phrase check (echoing the EXPECTED phrase) and an accept with the 64-bit candidate id compared untruncated",
              outcomes["arm off"][0] == real_mod.SG_ARM_OFF and outcomes["phrase"][0] == real_mod.SG_PHRASE
              and f"expected 'SAVE {cid}'" in outcomes["phrase"][1] and outcomes["ok"][0] == real_mod.SG_ACCEPT, str(outcomes), cap="fbsave_adapter")
        plan_code = r"""
        ecco_fbdurable::EspNvs nvs; ecco_fallback::FallbackProfileV1 pp{}; ecco_fbdurable::FailbackProvisionV1 wp{}; ecco_fbdurable::ReadDiag dp{}, dw{};
        const uint8_t pl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FALLBACK_PROFILE_KEY, pp, dp);
        const uint8_t wl = ecco_fbdurable::read_direct_t(nvs, ecco_fbdurable::FAILBACK_PROVISION_KEY, wp, dw);
        ecco_fbsave::SavePlanInputs pi{}; pi.p_load = pl; pi.p = pp; pi.p_stored_len = dp.stored_len; pi.w_load = wl; pi.w = wp; pi.w_stored_len = dw.stored_len;
        pi.cls = ecco_fbdurable::EPC_VALID; pi.why = 0; pi.read_anomaly = 0; pi.unconfirmed = false; pi.seen_hw_gen = id(fallback_profile_seen_hw_gen);
        pi.cand_prior_class = id(fallback_profile_cand_prior_class); pi.cand_prior_gen = id(fallback_profile_cand_prior_gen);
        pi.cand_prior_binding = id(fallback_profile_cand_prior_binding); pi.replace_corrupt = false; pi.words = id(fallback_profile_cand_words);
        pi.captured_epoch = EPOCH;
        const ecco_fbsave::Plan plan = ecco_fbsave::plan_save(pi);
        id(fallback_profile_step) = plan.code; id(fallback_profile_invalidate_reason) = plan.text.c_str(); id(fallback_profile_op_started_ms) = plan.generation;
        ecco_fbdurable::TxnResult r{};
        if (plan.code == ecco_fbsave::PLAN_OK) {
          const ecco_fbdurable::TxnOutcome o = ecco_fbdurable::commit_transition_t(nvs, plan.w_new, wp, ecco_fbdurable::PriorDesc{wl, dw.stored_len},
                                                                                    plan.p_new, pp, ecco_fbdurable::PriorDesc{pl, dp.stored_len}, r);
          id(fallback_profile_op_purpose) = (uint8_t) o;
          id(fallback_profile_obl_text) = ecco_fbsave::txn_outcome_text(plan.op, o, r, plan.generation, pp.generation).c_str();
          id(fallback_profile_probe_latch) = ecco_fbsave::first_non_ok(r.w.err, r.p.err);
          id(fallback_profile_seen_hw_gen) = ecco_fbsave::total_us(r.w.us, r.p.us);
        }
        """
        m0 = rs.mark()
        rs.run_lambda(plan_code.replace("EPOCH", "1790000000u"))
        sn = rs.since(m0)
        check("plan_save over a FRESH read of both keys (SavePlanInputs filled field by field, the candidate words as a std::array, a record stored into a "
              "dict field): PLAN_OK g8, then `commit_transition_t(nvs, plan.w_new, ..., plan.p_new, ...)` writes FBW then FBP, COMMITTED, and "
              "txn_outcome_text / first_non_ok / total_us read the TxnResult",
              rs.g["fallback_profile_step"] == real_mod.PLAN_OK and rs.g["fallback_profile_op_started_ms"] == 8
              and sn.fb_set_order == ["FBW", "FBP"] and rs.g["fallback_profile_op_purpose"] == fd.TXN_COMMITTED
              and str(rs.g["fallback_profile_obl_text"]) == "SAVED - known-good profile generation 8 saved (verified this boot)"
              and rs.g["fallback_profile_probe_latch"] == 0 and rs.g["fallback_profile_seen_hw_gen"] > 0
              and sn.violations_fb(("FBW", "FBP"), reads=[]) == [], str((rs.g["fallback_profile_step"], str(rs.g["fallback_profile_obl_text"]))),
              cap="fbsave_adapter")
        dr2 = D.Driver()
        dr2.review(expect="CANDIDATE_READY")
        dr2.sim.g["fallback_profile_cand_prior_gen"] = 6
        dr2.sim.run_lambda(plan_code.replace("EPOCH", "1790000000u"))
        dr3 = D.Driver()
        dr3.review(expect="CANDIDATE_READY")
        dr3.sim.run_lambda(plan_code.replace("EPOCH", "0u"))
        check("plan_save refuses with its own text and writes nothing: a stored profile that is not the one reviewed (PLAN_PRIOR_CHANGED), a zero capture "
              "epoch (PLAN_CLOCK)",
              dr2.sim.g["fallback_profile_step"] == real_mod.PLAN_PRIOR_CHANGED and dr3.sim.g["fallback_profile_step"] == real_mod.PLAN_CLOCK
              and "stored profile changed since Review" in str(dr2.sim.g["fallback_profile_invalidate_reason"]) and dr2.sim.nvs_direct.sets == []
              and dr3.sim.nvs_direct.sets == [], cap="fbsave_adapter")
        di = D.Driver()
        inv_code = r"""
        ecco_fbsave::InvalidateGateInputs ii{}; ii.arm_was_on = true; ii.boot_loaded = true; ii.read_anomaly = 0; ii.unconfirmed = false;
        ii.cls = id(fallback_profile_class); ii.p_load = id(fallback_profile_load); ii.p = ecco_fallback::decode_profile(id(fallback_profile_bytes));
        ii.w_load = id(fallback_witness_load); ii.w = ecco_fbdurable::decode_provision(id(fallback_witness_bytes));
        ii.seen_hw_gen = id(fallback_profile_seen_hw_gen); ii.tx_buffer_empty = id(inverter_modbus)->tx_buffer_empty();
        ii.tx_blocked = id(inverter_modbus)->tx_blocked(); ii.fbs_slot = id(fallback_profile_fbs_slot); ii.bus.now_ms = millis();
        ii.bus.manual_write_in_progress = id(manual_write_in_progress);
        const ecco_fbsave::InvalidateGateResult ir = ecco_fbsave::invalidate_gate_decide(ii, "INVALIDATE", 10, TARGET, 16, CONF, 27);
        id(fallback_profile_step) = ir.code; id(fallback_profile_invalidate_reason) = ir.text.c_str();
        """
        bind = f"{di.stored('FBP')['binding']:016X}"
        di.sim.run_lambda(inv_code.replace("TARGET", f'"{bind}"').replace("CONF", f'"INVALIDATE {bind}"'))
        ok_code = di.sim.g["fallback_profile_step"]
        di.sim.run_lambda(inv_code.replace("TARGET", f'"{bind}"').replace("CONF", '"INVALIDATE 0000000000000000"'))
        bad_code, bad_text = di.sim.g["fallback_profile_step"], str(di.sim.g["fallback_profile_invalidate_reason"])
        di.sim.run_lambda("id(manual_write_in_progress) = true;")
        di.sim.run_lambda(inv_code.replace("TARGET", f'"{bind}"').replace("CONF", f'"INVALIDATE {bind}"'))
        check("invalidate_gate_decide over the RAM mirror decoded from the byte-image globals (decode_profile / decode_provision), the bus busy flags and "
              "the full 64-bit binding as the target: accept; a wrong phrase is refused with the EXPECTED phrase; a held write mutex is refused (IG_BUS)",
              ok_code == real_mod.IG_ACCEPT and bad_code == real_mod.IG_PHRASE and f"expected 'INVALIDATE {bind}'" in bad_text
              and di.sim.g["fallback_profile_step"] == real_mod.IG_BUS, str((ok_code, bad_code, bad_text)), cap="fbsave_adapter")
        rs.run_lambda('id(fallback_profile_step) = ecco_fbsave::overlay_class(ecco_fbdurable::EPC_VALID, true); '
                      'id(fallback_profile_capture_state) = ecco_fbcap::CAPTURE_SAVING; '
                      'id(fallback_profile_probe_latch) = ecco_fbsave::commit_bus_quiet(true, true, false, true, false) + ecco_fbsave::commit_bus_quiet(true, true, false, true, true) * 2; '
                      'id(fallback_profile_invalidate_reason) = ecco_fbsave::save_changed_during_read_text(id(fallback_profile_pass1), id(fallback_profile_cand_words)).c_str();')
        check("overlay_class (SAVE_UNCONFIRMED wins), ecco_fbcap::CAPTURE_SAVING, commit_bus_quiet (quiet / blocked) and a text builder over two std::array "
              "arguments", rs.g["fallback_profile_step"] == fd.EPC_SAVE_UNCONFIRMED and rs.g["fallback_profile_capture_state"] == 4
              and rs.g["fallback_profile_probe_latch"] == 1 and str(rs.g["fallback_profile_invalidate_reason"]).startswith("SAVE REFUSED - live configuration changed"),
              str(rs.g["fallback_profile_invalidate_reason"])[:80], cap="fbsave_adapter")

    # =======================================================================
    print("[6] the ecco_fbdurable names the SAVE / INVALIDATE lambdas use")
    # =======================================================================
    sim = H.FbbSim(mkfw(g5))
    sim.run_lambda("ecco_fbdurable::MirrorRecords m{}; id(u) = m.p_load + m.w_load + m.p.generation + m.w.hw_generation;\n"
                   "ecco_fbdurable::MirrorRecords m2{m.p, m.w, 1, 2}; id(w) = m2.p_load * 10 + m2.w_load; "
                   "m2.p_load = 9; id(n) = m2.p_load;")
    check("MirrorRecords: a default-constructed value is all zero / empty records, brace-init takes {p, w, p_load, w_load}, fields assign",
          (sim.g["u"], sim.g["w"], sim.g["n"]) == (0, 12, 9), cap="durable_adapter_additions")
    sim.run_lambda("ecco_fbdurable::TxnResult r{};\n"
                   "id(u) = r.w.err + r.p.err + r.w.us + r.p.us + r.witness_advanced + r.refusal + r.w.rb_diag.stored_len + r.p.rb_class "
                   "+ r.p.healthy_after + r.w.rb_load;\n"
                   "id(n) = r.w.outcome; id(w) = r.p.outcome; id(v) = r.refusal;")
    check("a zero-initialised TxnResult reads as UNKNOWN_REBOOT with refusal UNSET (the fail-closed zeros) and every field the SAVE lambda "
          "reads exists (err, us, rb_load, rb_class, rb_diag.stored_len, healthy_after, outcome, witness_advanced, refusal)",
          (sim.g["u"], sim.g["n"], sim.g["w"], sim.g["v"]) == (0, fd.KEY_UNKNOWN_REBOOT, fd.KEY_UNKNOWN_REBOOT, fd.REFUSAL_UNSET),
          cap="durable_adapter_additions")
    sim.run_lambda("id(s) = ecco_fbdurable::decimal_key(ecco_fbdurable::FALLBACK_PROFILE_KEY); "
                   "id(t) = ecco_fbdurable::decimal_key(ecco_fbdurable::FAILBACK_PROVISION_KEY); "
                   "id(u) = ecco_fbdurable::IDF_OK; id(w) = ecco_fbdurable::IDF_ERR_NVS_INVALID_HANDLE; "
                   "id(n) = ecco_fbdurable::WIT_DEFECT_PRIOR; id(v) = ecco_fbdurable::RULE_NONE;")
    check("decimal_key (the FBP / FBW key strings), IDF_OK / IDF_ERR_NVS_INVALID_HANDLE, WIT_DEFECT_*, RULE_NONE",
          (str(sim.g["s"]), str(sim.g["t"]), sim.g["u"], sim.g["w"], sim.g["n"], sim.g["v"]) == (D.FBP_DEC, D.FBW_DEC, 0, 0x1107, 7, 0),
          cap="durable_adapter_additions")
    check("only the idf codes the C++ model declares are exposed (IDF_ERR_TIMEOUT / IDF_FAIL are not in ecco_fallback_durable_model.h): "
          "they raise FbbNotModelled instead of letting a lambda compile in the harness and fail on the device",
          isinstance(lam("id(u) = ecco_fbdurable::IDF_ERR_TIMEOUT;", sim=H.FbbSim(mkfw(g5)))[1], H.FbbNotModelled)
          and isinstance(lam("id(u) = ecco_fbdurable::IDF_FAIL;", sim=H.FbbSim(mkfw(g5)))[1], H.FbbNotModelled), cap="durable_adapter_additions")
    fbd = H.FbdNamespace(sim)

    def rec_p(**kw):
        return H.FbRecord.from_bytes("FallbackProfileV1", fp.pack_profile(fp.seal_profile(fp.blank_profile(**{**D.GOLD_FIELDS, **kw}))))

    def pd(load, n):
        return H.Plain("PriorDesc", ("load", "stored_len"), load, n)

    p7, p8 = rec_p(binding=0), rec_p(generation=8, binding=0)
    w7 = H.FbRecord.from_bytes("FailbackProvisionV1", D.prov_bytes(7, p7.binding, 6))
    w8 = fbd.make_provision(8, p8.binding, 7, p7.binding, fd.FALLBACK_PROFILE_KEY, 1, fd.PROV_OP_SAVE)
    ok_ = fbd.validate_transition(w8, w7, pd(fp.LOAD_OK, 48), p8, p7, pd(fp.LOAD_OK, 96))
    crossed = fbd.validate_transition(w7, w7, pd(fp.LOAD_OK, 48), p8, p7, pd(fp.LOAD_OK, 96))
    check("validate_transition (the pure PO14 pre-validation) accepts the legitimate SAVE g7 -> g8 and refuses a crossed pair "
          "(witness of the OLD generation)", ok_ is True and crossed is False, cap="durable_adapter_additions")
    broken = w8.copy()
    broken.binding = 0
    check("seal_provision re-seals a record (idempotent on a sealed one; restores the binding of one whose binding was cleared)",
          fbd.seal_provision(w8) == w8 and fbd.seal_provision(broken) == w8, cap="durable_adapter_additions")

    # =======================================================================
    print("[7] syntax-level lambda compile (api actions, the switch, StringRef, the ecco_fbsave header)")
    # =======================================================================
    cxx = LC.find_compiler()
    print(f"    compiler: {cxx}")
    check("a C++ compiler is available ($ECCO_CXX, g++ / c++ / clang++ on PATH, or ESPHome's xtensa GCC) - this check FAILS rather than skips",
          cxx is not None, LC.NO_CXX)
    fw2 = S.with_mini_save(live)
    synth_kw = dict(scripts_fbb2=(S.SYNTH_SAVE, S.SYNTH_INVALIDATE), api_action=S.SYNTH_API, arm_switch=S.SYNTH_ARM)
    # The walk of the FB-B1-era code (the three Review scripts, the housekeeping interval, the appended on_boot lambda) of the LIVE firmware,
    # whatever FB-B2 added beside it. FB-B2: the live firmware edits that code (the dispatch gained its SAVE pre-commit wait and SAVE_FINAL
    # lambdas, the interval its arm-lifetime lambda), so its walk is 52 lambdas where FB-B1's was 47: the expected count is DERIVED from the
    # parsed YAML by an independent recursive count (`lambda_keys`), never a literal that the next YAML edit silently outdates.
    base_l = LC.lambdas_of(live, scripts_fbb2=(), api_action="", arm_switch="")
    lams = LC.lambdas_of(fw2, **synth_kw)
    api_l = [x for x in lams if x.name.startswith("api:")]
    sw_l = [x for x in lams if x.name.startswith("switch:")]
    scr = {s["id"]: s for s in live["script"]}
    fb1_ivs = [iv for iv in live["interval"] if LC.INTERVAL_MARK in str(iv["then"])]
    fb1_trees = [scr[i]["then"] for i in LC.FB_SCRIPT_IDS] + [fb1_ivs[0]["then"], [live["esphome"]["on_boot"]["then"][3]]]
    n_fb1, h_fb1 = (sum(c) for c in zip(*(lambda_keys(t) for t in fb1_trees)))
    n_base = len(base_l)
    check("the walker finds EVERY lambda of the live firmware's FB-B1-era code first - exactly the count an independent recursive count of "
          "the parsed YAML gives (FB-B2: 52 where FB-B1 had 47), 20 of them Modbus reply handlers (four reads x five handlers) - and, for a "
          "firmware with an api action / scripts / arm switch, adds them: the action's lambda and its `if` condition (both generated as "
          "[](StringRef action, StringRef target_id, StringRef confirmation)), the two scripts' lambdas, the switch's turn_on_action",
          len(fb1_ivs) == 1 and n_base == n_fb1 and n_base >= 47 and sum(1 for x in base_l if x.params) == h_fb1 == 20
          and [x.name for x in base_l] == [x.name for x in lams[:n_base]] and sum(1 for x in lams[:n_base] if x.params) == 20
          and len(lams) == n_base + 5 and [x.kind for x in api_l] == ["void", "bool"]
          and all(x.params == "StringRef action, StringRef target_id, StringRef confirmation" for x in api_l)
          and [x.name for x in sw_l] == [f"switch:{S.SYNTH_ARM}.turn_on_action[0]"]
          and {x.name for x in lams} >= {f"{S.SYNTH_SAVE}[0]", f"{S.SYNTH_INVALIDATE}[0]"}, f"{len(lams)} lambdas, base {n_base} vs oracle {n_fb1}",
          cap="lambda_compile")
    # FB-B2: the live firmware now carries the real SAVE / INVALIDATE scripts, the fallback_profile_execute action and the arm switch, which the
    # default walk adds after the FB-B1-era code. Same oracle, per piece.
    live_act = [a for a in live["api"]["actions"] if a.get("action") == LC.FBB2_API_ACTION]
    live_arm = [s for s in live["switch"] if s.get("id") == LC.FBB2_ARM_SWITCH]
    full_l = LC.lambdas_of(live)
    n_sv, n_iv = lambda_keys(scr["fallback_profile_save"]["then"])[0], lambda_keys(scr["fallback_profile_invalidate"]["then"])[0]
    n_ap, n_sw = lambda_keys(live_act[0]["then"])[0], lambda_keys(live_arm[0]["turn_on_action"])[0]
    live_api_l = [x for x in full_l if x.name.startswith("api:")]
    check("the walker on the LIVE FB-B2 firmware adds, after the FB-B1-era code, every lambda of the SAVE script, the INVALIDATE script, the "
          "fallback_profile_execute api action (action lambda and `if` condition, three StringRef parameters) and the arm switch's turn_on_action: "
          "the exact counts of the independent recursive count, nothing missed and nothing invented",
          len(live_act) == 1 and len(live_arm) == 1 and len(full_l) == n_base + n_sv + n_iv + n_ap + n_sw
          and [x.name for x in full_l[:n_base]] == [x.name for x in base_l]
          and sum(1 for x in full_l if x.name.startswith("fallback_profile_save[")) == n_sv
          and sum(1 for x in full_l if x.name.startswith("fallback_profile_invalidate[")) == n_iv
          and [x.kind for x in live_api_l] == ["void", "bool"] and len(live_api_l) == n_ap
          and all(x.params == "StringRef action, StringRef target_id, StringRef confirmation" for x in live_api_l)
          and [x.name for x in full_l if x.name.startswith("switch:")] == [f"switch:{LC.FBB2_ARM_SWITCH}.turn_on_action[0]"] and n_sw == 1,
          f"{len(full_l)} lambdas: base {n_base} + save {n_sv} + invalidate {n_iv} + api {n_ap} + switch {n_sw}", cap="lambda_compile")
    check("the api parameter list follows the declared variable types (string -> StringRef, bool / int32_t / float plain) and refuses a type it "
          "does not know",
          LC.api_params({"action": "x", "variables": {"a": "string", "b": "bool", "c": "int", "d": "float"}})
          == "StringRef a, bool b, int32_t c, float d" and raises(lambda: LC.api_params({"action": "x", "variables": {"a": "std::vector<int>"}}),
                                                                   ValueError) is not None, cap="lambda_compile")
    src = LC.build_source(fw2, lams=lams)
    SAVE_INC = '#include "ecco_fallback_save.h"'
    names_save = [x.name for x in lams if "ecco_fbsave::" in x.code]       # the lambdas that name the header's namespace
    no_save = [x for x in lams if "ecco_fbsave::" not in x.code]           # the same set minus those (the synthetic ones never name it)
    live_names_save = [x.name for x in full_l if "ecco_fbsave::" in x.code]
    # FB-B2: the live firmware's own lambdas name ecco_fbsave:: now (the dispatch's PURPOSE_SAVE, the SAVE / INVALIDATE gates, the housekeeping arm
    # lifetime, the api routing), so the translation unit of the live firmware - and of `lams`, which carries the live FB-B1-era lambdas - DOES include
    # the header. What the check proves is unchanged: the header is included EXACTLY when some lambda names ecco_fbsave::, and not otherwise.
    check("the translation unit rewrites id(arm) to the switch stub and id(ntp_time) to the clock stub, takes StringRef parameters, and includes "
          "the ecco_fbsave header EXACTLY when a lambda names ecco_fbsave:: (FB-B2: the live firmware's lambdas do, so its translation unit does; "
          "the same lambdas without those do not)",
          "static SwitchStub fbs_synth_arm_o" in src and "static ClockStub ntp_time_o" in src
          and "(StringRef action, StringRef target_id, StringRef confirmation)" in src.replace("[[maybe_unused]] ", "")
          and len(names_save) > 0 and len(live_names_save) > 0 and (SAVE_INC in src) is True
          and SAVE_INC in LC.build_source(live) and SAVE_INC in LC.build_source(live, lams=[x for x in full_l if "ecco_fbsave::" in x.code])
          and SAVE_INC not in LC.build_source(live, lams=[x for x in full_l if "ecco_fbsave::" not in x.code])
          and SAVE_INC not in LC.build_source(fw2, lams=no_save)
          and SAVE_INC in LC.build_source(fw2, lams=no_save + [LC.Lam("x", "void", "", "id(fbs_synth_calls) = ecco_fbsave::ACT_SAVE;")]),
          f"{len(names_save)} lambdas of `lams` and {len(live_names_save)} of the live walk name ecco_fbsave::", cap="lambda_compile")
    check("a lambda that references an id the stub set does not know is refused by the TU builder (never a vacuous compile)",
          raises(lambda: LC.build_source(fw2, lams=lams + [LC.Lam("x", "void", "", "id(no_such_symbol_xyz) = 1;")]), ValueError) is not None,
          cap="lambda_compile")
    # The stand-in header (a test double of ecco_fallback_save.h) for the self-tests of the adapter against the SYNTHETIC lambdas. FB-B2: the real
    # header exists now, so the stand-in is used only with the lambda set that does not need the real one (`no_save`: the live lambdas that name
    # ecco_fbsave:: - PURPOSE_SAVE, the gates, ... - need the real header and compile against it below), and `STANDIN_MARK` is a name ONLY the
    # stand-in defines: that is what proves the staged header, not the real one, was compiled against.
    stub = ('#pragma once\n#include <cstdint>\n#include <cstddef>\nnamespace ecco_fbsave { constexpr uint8_t ACT_SAVE = 1; constexpr uint8_t STANDIN_MARK = 7; '
            'inline uint8_t action_token(const char *, size_t) { return ACT_SAVE; } }\n')
    if cxx is not None:
        from concurrent.futures import ThreadPoolExecutor
        inj_api = "api:" + S.SYNTH_API + "[0]"
        inj_stub = (S.SYNTH_SAVE, "id(fbs_synth_outcome) = ecco_fbsave::ACT_SAVE; id(fbs_synth_calls) = ecco_fbsave::STANDIN_MARK;")
        stand_in = {"ecco_fallback_save.h": stub}
        controls = {
            ".str() on a std::string global": ("has no member named 'str'", dict(inject=(S.SYNTH_SAVE, "id(fbs_synth_exec_action).str();"))),
            "StringRef + StringRef is ambiguous": ("ambiguous", dict(inject=(inj_api, "std::string z = action + target_id; (void) z;"))),
            "a member on the c_str() pointer": ("non-class type", dict(inject=(inj_api, "(void) action.c_str().size();"))),
            "a misspelled switch member": ("turn_onn", dict(inject=(S.SYNTH_SAVE, "id(fbs_synth_arm).turn_onn();"))),
            "a misspelled clock member": ("timestampp", dict(inject=(S.SYNTH_SAVE, "(void) id(ntp_time).now().timestampp;"))),
            "StringRef has no operator bool": ("bool", dict(inject=(inj_api, "if (action) { id(fbs_synth_calls) = 9; }"))),
            "a name the ecco_fbsave header does not define": ("ACT_SAVEE", dict(
                lams=no_save, inject=(S.SYNTH_SAVE, "id(fbs_synth_outcome) = ecco_fbsave::ACT_SAVEE;"), extra_headers=stand_in)),
            "a name only the stand-in header defines, with no stand-in staged (the REAL header is compiled against)": ("STANDIN_MARK", dict(
                lams=no_save, inject=inj_stub)),
        }
        # FB-B2: at most compile_jobs() g++ processes at once (6, or 4 after a memory fallback of the heavy-batch wrapper), however the pools nest
        with capped_compiles(), ThreadPoolExecutor(max_workers=compile_jobs()) as pool:
            f_real = pool.submit(LC.compile_all, fw2, lams=lams)
            f_live = pool.submit(LC.compile_all, live)
            f_hdr = pool.submit(LC.compile_all, fw2, lams=no_save, inject=inj_stub, extra_headers=stand_in)
            f_ctl = {n: pool.submit(LC.compile_rejects, fw2, needle, "gnu++20", **{"lams": lams, **kw}) for n, (needle, kw) in controls.items()}
            real, live_ok, hdr_ok = f_real.result(), f_live.result(), f_hdr.result()
            ctl = {n: f.result() for n, f in f_ctl.items()}
        check("the synthetic api action / arm switch / SAVE / INVALIDATE lambdas compile clean with -fsyntax-only -Wall -Wextra -Werror under "
              "gnu++17 AND gnu++20 against the REAL FB headers, a faithful esphome::StringRef, switch and clock stubs", not real,
              "; ".join(real)[:600], cap="lambda_compile")
        check("FB-B2: EVERY lambda of the LIVE firmware (the FB-B1-era code as edited, the real SAVE and INVALIDATE scripts, the "
              "fallback_profile_execute action, the arm switch) compiles clean under gnu++17 AND gnu++20 against the REAL headers, "
              "including the real ecco_fallback_save.h that its lambdas name", not live_ok and SAVE_INC in LC.build_source(live),
              "; ".join(live_ok)[:600], cap="lambda_compile")
        check("a lambda naming ecco_fbsave:: compiles against a staged stand-in header (extra_headers wins over firmware/include: the name only "
              "the stand-in defines resolves, and is rejected when no stand-in is staged - the control below)",
              not hdr_ok, "; ".join(hdr_ok)[:400], cap="lambda_compile")
        for n, (ok, out) in ctl.items():
            check(f"negative control: {n} is rejected by the compiler itself (rc != 0, an `error:` line naming the defect)", ok, out[:300],
                  cap="lambda_compile")
    else:
        check("the compile checks need a compiler", False, LC.NO_CXX)

    # =======================================================================
    print("[8] the scenario driver against the LIVE firmware")
    # =======================================================================
    d = D.Driver()
    check("Driver(): the live firmware boots through the real on_boot over the golden VALID g7 pair; trusted environment (NTP synced + valid, "
          "supervision SUPERVISED + Stable), bank == the stored profile, the 10 s housekeeping interval running, nothing written",
          d.b1 == "VALID" and d.boots == 1 and d.g["ntp_synced"] is True and (d.g["supervision_state"], d.g["supervision_stable"]) == (1, True)
          and d.bank_words() == D.GWORDS and len(d.sim._intervals) == 1 and d.housekeeping_on and d.sim.nvs_direct.sets == []
          and d.b9 == "No Fallback Profile action since boot" and d.b3 == D.IDLE_B3 and d.reads_seen == 0, cap="boot_real_yaml")
    check("every seed boots to the class the FB-B0 model derives from the same NVS image (the independent oracle: compose_profile_class over the "
          "stored bytes); the read-fault seed is the one that is UNREADABLE although its bytes are fine",
          all(D.Driver(seed=n).b1 == D.Driver(seed=n).model_class()[0] for n in D.SEEDS if n != "unreadable")
          and D.Driver(seed="unreadable").b1 == "UNREADABLE" and D.Driver(seed="unreadable").model_class()[0] == "VALID"
          and {D.Driver(seed=n).b1 for n in D.SEEDS} == {"NOT_CAPTURED", "VALID", "INVALIDATED", "CORRUPT", "CORRUPT_DOMAIN", "UNREADABLE",
                                                         "PROFILE_LOST", "PROFILE_STALE"}, cap="boot_real_yaml")
    dd = D.Driver(seed={"fbp": D.gold_profile(generation=9), "fbw": D.prov_bytes(9, D.gold_profile(generation=9)["binding"], 8)})
    check("a seed given as a dict {fbp, fbw, fbs} (a record dict or raw bytes) and a callable seed",
          dd.b1 == "VALID" and dd.stored("FBP")["generation"] == 9 and dd.stored("FBW")["hw_generation"] == 9
          and D.Driver(seed=lambda sim: sim.nvs_direct.put(D.K_P, bytes(40))).b1 == "CORRUPT", cap="boot_real_yaml")
    check("an unknown seed / env / lease name raises a DriverError, never a silent default",
          raises(lambda: D.Driver(seed="nope"), D.DriverError) is not None and raises(lambda: D.Driver(env="weird"), D.DriverError) is not None
          and raises(lambda: d.lease("nope"), D.DriverError) is not None and raises(lambda: d.write_arm("dump_recovery_arm"), D.DriverError) is not None,
          cap="boot_real_yaml")
    db = D.Driver(env="bare")
    check("env=\"bare\" is what a fresh boot has: no NTP, no supervision, nothing stable",
          (db.g["ntp_synced"], db.g["supervision_state"], db.g["supervision_stable"]) == (False, 0, False), cap="world_state")
    st = d.review(expect="CANDIDATE_READY")
    check("review(): the four reads (230/3, 241/53, 230/3, 241/53), no write / NVS set / commit (violations), B3 CANDIDATE_READY with the "
          "golden id, B9 'CANDIDATE READY ...' published after 'review in progress', the Step carries texts, publications, task and time",
          st.reads == D.READS and st.violations(reads=D.READS) == [] and st.b9.startswith("CANDIDATE READY") and d.b4 == d.texts()["B4"]
          and len(d.b4) == 16 and st.published["B9"][0].startswith("review in progress") and st.published["B9"][-1] == st.b9
          and st.elapsed_ms == 0 and st.task is not None and st.cut is None and st.texts["B3"].startswith("st=CANDIDATE_READY;prior=VALID;")
          and d.b3_field("exp") == "120" and d.b3_field("sv") == "OK" and d.candidate()["valid"] is True and d.reads_seen == 4,
          cap="operator_actions")
    dd_ = D.Driver(mode=("deferred", 120))
    std_ = dd_.review(expect="CANDIDATE_READY")
    check("(execution fidelity) a review leaves the driver's own books straight: one step recorded, FB sets none, fb_set_order empty; on a "
          "deferred hub the same review takes virtual time (4 reads x 120 ms on the wire)",
          len(d.steps) == 1 and st.fb_sets == [] and st.fb_set_order == [] and st.violations_fb(()) == [] and std_.elapsed_ms >= 480
          and std_.reads == D.READS, cap="operator_actions")
    check("review(expect=...) is a scenario guard: a state other than the expected one raises DriverError naming B3 and B9",
          raises(lambda: D.Driver().lease("fp_active").review(expect="CANDIDATE_READY"), D.DriverError) is not None
          and "REVIEW REFUSED" in str(raises(lambda: D.Driver().lease("fp_active").review(expect="CANDIDATE_READY"), D.DriverError)),
          cap="operator_actions")
    refused_ok = []
    for name, (code, obl, frag) in D.LEASE_RAM.items():
        dl = D.Driver().lease(name)
        stl = dl.review()
        refused_ok.append(stl.b9.startswith("REVIEW REFUSED - ") and frag in stl.b9 and obl in dl.b3_field("obl") and stl.reads == []
                          and stl.violations(reads=[]) == [])
    check(f"all {len(D.LEASE_RAM)} lease / obligation presets (LEASE_RAM) put the RAM legs in the state the FB gate refuses on: the refusal "
          "text fragment, the obligation-vector code, zero reads", all(refused_ok), str(refused_ok), cap="world_state")
    arms_ok = []
    for arm in D.WRITE_ARMS:
        da = D.Driver().write_arm(arm)
        sta = da.review()
        arms_ok.append("write arm is on" in sta.b9 and sta.reads == [])
    dm = D.Driver().mutex(True)
    stm = dm.review()
    check("each of the three write arms and a held write mutex refuse a review (BUS) with zero reads",
          all(arms_ok) and "another inverter transaction is in progress" in stm.b9 and stm.reads == [], cap="world_state")
    w_pre = list(D.GWORDS)
    w_pre[0] = 0
    dn = D.Driver(words=w_pre)
    dn.review(expect="CANDIDATE_NOT_SAVEABLE")
    d2 = D.Driver()
    d2.set_words([w + (1 if k == 5 else 0) for k, w in enumerate(D.GWORDS)])
    d2.review(expect="CANDIDATE_READY")
    check("words= / set_words() change what the four reads return: reg244 = 0 gives a not-saveable preview (no id), changing one word gives a "
          "different candidate id", d.b4 != d2.b4 and dn.b4 == "-" and dn.g["fallback_profile_cand_saveable"] is False, cap="world_state")
    dh = D.Driver()
    dh.change_word_before_read(3, 28, 186)   # word 28 = register 230: pass 2 differs from pass 1
    sth = dh.review()
    n1 = dh.reads_seen
    sth2 = dh.review()
    check("before_read(k, ...) mutates the bank just before the k-th read takes its snapshot: a register changing between the passes gives "
          "REVIEW NOT COMPLETED (all four reads happened), and the hook does not fire again on the next review",
          sth.b9.startswith("REVIEW NOT COMPLETED") and sth.reads == D.READS and n1 == 4 and sth2.b9.startswith("CANDIDATE READY")
          and dh.reads_seen == 8, cap="world_state")
    dr = D.Driver()
    dr.review()
    dr.before_read(1, lambda sim, a, c: sim.bank.__setitem__(256, 1234))
    dr.before_read(1, lambda sim, a, c: sim.bank.__setitem__(257, 4321))
    seen_calls = []
    dr.before_read(2, lambda sim, a, c: seen_calls.append((a, c)))
    dr.review()
    check("before_read counts RELATIVE to now by default (k=1 is the next review's first read), several hooks per read run in order and the "
          "change is in effect for that very read (both passes agree, so the candidate carries it), the hook sees (sim, address, count)",
          seen_calls == [(241, 53)] and dr.sim.bank[256] == 1234 and dr.sim.bank[257] == 4321 and dr.reads_seen == 8
          and dr.b9.startswith("CANDIDATE READY") and dr.candidate()["words"][1:3] == [1234, 4321], str(seen_calls), cap="world_state")
    ds_ = D.Driver(env="bare")
    ds_.establish_supervision()
    ds_.sim.g["ntp_synced"] = False
    check("establish_supervision(): the REAL heartbeat action three times 30 s apart; the firmware's own rule then sets supervision_stable "
          "(and supervise(...) / supervise(state=, stable=) set the globals directly)",
          ds_.g["supervision_stable"] is True and ds_.g["supervision_valid_count"] == 3 and ds_.g["supervision_state"] == 1
          and ds_.sim.now_ms == 1_000_000 + 60_000 and ds_.supervise(False).g["supervision_stable"] is False
          and ds_.supervise(state=1, stable=False).g["supervision_state"] == 1, cap="world_state")
    dt = D.Driver()
    wall = lambda x: (x.run("id(supervision_last_valid_epoch) = (uint32_t) id(ntp_time).now().timestamp;"), x.g["supervision_last_valid_epoch"])[1]  # noqa: E731
    e0 = wall(dt)
    dt.advance(5000)
    e_const = wall(dt)
    dt.set_time(flow=True)
    dt.advance(5000)
    e_flow = wall(dt)
    dt.untrusted_time()
    dt.run("id(supervision_have_valid) = id(ntp_time).now().is_valid();")
    check("set_time(): the wall clock is constant by default (a SAVE captures epoch 1790000000), flow=True makes it advance with the virtual clock, "
          "untrusted_time() clears ntp_synced and the clock's validity", (e0, e_const, e_flow) == (D.EPOCH0, D.EPOCH0, D.EPOCH0 + 5)
          and dt.g["ntp_synced"] is False and dt.g["supervision_have_valid"] is False, str((e0, e_const, e_flow)), cap="world_state")
    dx = D.Driver()
    dx.review()
    dx.put("FBP", D.gold_profile(generation=9))
    check("put() / erase() / stored() / state_of() / nvs_image(): the direct NVS after the boot, decoded records, None for absent or damaged",
          dx.stored("FBP")["generation"] == 9 and dx.state_of("FBP").startswith("OK:96:") and dx.stored("FBS") is None
          and (dx.erase("FBP"), dx.stored("FBP"), dx.state_of("FBP"))[1:] == (None, "ABS")
          and (dx.put("FBP", bytes(96), crc_ok=False), dx.stored("FBP"))[1] is None and set(dx.nvs_image()) == {D.K_W, D.K_P}, cap="observation")
    du = D.Driver()
    du.unhealthy()
    stu = du.review()
    df = D.Driver()
    df.fault_read("FBP", fd.IDF_FAIL, fd.IDF_FAIL)
    df.review()
    check("unhealthy() / fault_read() inject the NVS faults the next fresh read sees (an INVALID page -> UNREADABLE prior; a read error -> "
          "UNREADABLE) - the review still reads, still writes nothing",
          du.b3.startswith("st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;") and stu.violations(reads=D.READS) == []
          and df.b3.startswith("st=CANDIDATE_NOT_SAVEABLE;prior=UNREADABLE;"), cap="world_state")
    img = d.nvs_image()
    d.sim.set_modbus_mode("deferred", 120)
    d.reboot()
    check("reboot(): a power cycle through the REAL on_boot - RAM gone (candidate, B3, arm), the environment re-applied, housekeeping running, the "
          "NVS image carried over byte for byte, read-only history empty",
          d.boots == 2 and d.candidate()["valid"] is False and d.b3 == D.IDLE_B3 and d.g["ntp_synced"] is True
          and len(d.sim._intervals) == 1 and d.nvs_image() == img and d.nvs_set_history() == [] and d.b1 == "VALID"
          and d.sim.modbus_mode == "deferred", cap="reboot")
    d.reboot(env="bare")
    check("reboot(env=\"bare\") brings the device back untrusted", d.g["ntp_synced"] is False and d.g["supervision_stable"] is False, cap="reboot")
    check("reboot() resets the arm and every global through a NEW sim: the old sim object is left as the frozen pre-reboot world",
          d.sim.g["fallback_profile_boot_loaded"] is True and d.boots == 3, cap="reboot")
    dc = D.Driver()
    dc.cut_when(lambda ev: ev[0] == "read")
    stc = dc.review(catch_cut=True)
    img0 = D.Driver().nvs_image()
    check("cut_when(pred): the first read raises PowerCut out of the engine; Step.cut holds it (catch_cut=True), the sim stays frozen mid-review "
          "(lock held, one read issued); reboot() then comes back clean with the NVS image untouched",
          isinstance(stc.cut, H.PowerCut) and len(stc.reads) == 1 and dc.g["manual_write_in_progress"] is True
          and (dc.reboot(), dc.b3 == D.IDLE_B3 and dc.g["manual_write_in_progress"] is False and dc.nvs_image() == img0)[1], cap="power_cuts")
    check("without catch_cut a PowerCut inside a step propagates (an unexpected cut is a failure, not a Step)",
          raises(lambda: D.Driver().cut_when(lambda ev: ev[0] == "read").review(), H.PowerCut) is not None, cap="power_cuts")
    dk = D.Driver()
    dk.cut_before_nvs("set", "FBP").cut_after_nvs("get", "FBW", nth=1)
    cut_hit = raises(lambda: dk.review(), H.PowerCut)
    check("cut_before_nvs / cut_after_nvs: a hook for an NVS operation the review never does (an FBP set) stays silent; the one for the review's "
          "own FBW size probe (cut_after_nvs(\"get\", \"FBW\")) fires exactly there - the last NVS event on the timeline is that probe",
          cut_hit is not None and [e for e in dk.sim.events if e[0] == "nvs"][-1] == ("nvs", "get", D.FBW_DEC, 0), cap="power_cuts")
    dk2 = D.Driver()
    dk2.cut_at_nvs_point(0).clear_cuts()
    dk2.cut_at_nvs_point(2 * 3 + 1)
    stk = dk2.review(catch_cut=True)
    check("cut_at_nvs_point(2n + 1) = right AFTER the n-th (0-based) NVS event counted from now: the review is cut after its 4th NVS operation; "
          "clear_cuts() disarms (the cut at point 0 armed first never fires)",
          isinstance(stk.cut, H.PowerCut) and len([e for e in stk.since.events if e[0] == "nvs"]) == 4, cap="power_cuts")
    dv = D.Driver()
    dv.review()
    check("the remaining text accessors: B5 / B6 are the candidate views while a candidate exists, B7 / B8 the saved view of the stored profile; "
          "modbus_reads() / modbus_writes() are the sim's logs",
          dv.b5.startswith("v=CAND;") and dv.b6.startswith("v=CAND;") and dv.b7.startswith("v=SAVED;g=7;") and dv.b8.startswith("v=SAVED;")
          and dv.modbus_reads() == D.READS and dv.modbus_writes() == [], cap="observation")
    dh = D.Driver(env="bare")
    dh.heartbeat()
    dh.heartbeat()
    dh.heartbeat(challenge="NOT-THE-CHALLENGE")
    check("heartbeat(): one REAL ha_supervision_heartbeat call with the current challenge (two valid beats counted, the third with a wrong "
          "challenge counted invalid); the first beat alone makes the state SUPERVISED but not Stable",
          dh.g["supervision_valid_count"] == 2 and dh.g["supervision_invalid_count"] == 1 and dh.g["supervision_state"] == 1
          and dh.g["supervision_stable"] is False, cap="world_state")
    dm = D.Driver().mode("deferred", 200)
    stm = dm.review(expect="CANDIDATE_READY")
    check("mode(\"deferred\", ms) puts the Modbus hub on the wire model for the next operations (4 reads x 200 ms); idle() runs the engine to "
          "idle and returns the virtual ms it took", stm.elapsed_ms >= 800 and dm.idle() == 0, cap="world_state")
    dbus = D.Driver().mode("deferred", 120)
    dbus.hold_bus(3000)
    stb_ = dbus.review(expect="CANDIDATE_READY")
    check("hold_bus(ms): a foreign master holds the bus - the review waits (the 7 s idle wait) and still completes after it",
          3000 <= stb_.elapsed_ms <= 3000 + 600, str(stb_.elapsed_ms), cap="world_state")
    dpk = D.Driver()
    dpk.poke(256, 9999)
    dpk.review()
    check("poke(register, value) changes one inverter register: it is in the candidate and in bank_words()",
          dpk.candidate()["words"][1] == 9999 and dpk.bank_words()[1] == 9999, cap="world_state")
    dsg = D.Driver()
    dsg.set_g("fallback_profile_boot_loaded", False)
    stg = dsg.press_review()
    check("set_g(name, value) sets any global and press_review() is review() without the guard: with the boot load not done the gate refuses "
          "(zero reads) and the Step is labelled",
          stg.label == "review" and stg.b9.startswith("REVIEW REFUSED - ") and stg.reads == [], cap="world_state")
    dhk = D.Driver()
    dhk.review(expect="CANDIDATE_READY")
    dhk.stop_housekeeping()
    dhk.advance(130_000)
    alive = dhk.candidate()["valid"]
    started = dhk.start_housekeeping()
    dhk.advance(10_000)
    check("stop_housekeeping() / start_housekeeping(): without the 10 s tick a candidate outlives its 120 s TTL (nothing clears it), restarting "
          "the interval expires it on the next tick", alive is True and len(started) == 1 and dhk.candidate()["valid"] is False
          and dhk.b9.startswith("REVIEW EXPIRED"), cap="world_state")
    dap = D.Driver()
    dap.apply_env(lambda x: x.sim.g.__setitem__("ntp_synced", False))
    check("apply_env(callable) runs a custom environment recipe on the driver", dap.g["ntp_synced"] is False, cap="world_state")
    dce = D.Driver()
    dce.cut_after_event(1, ("read",))
    stce = dce.review(catch_cut=True)
    check("cut_after_event(k, kinds): a power cut right after the k-th (0-based) timeline event of those kinds counted from now - here the review "
          "is cut after its second Modbus read", isinstance(stce.cut, H.PowerCut) and len(stce.reads) == 2, cap="power_cuts")
    dba = D.Driver(mode=("deferred", 120))
    dba.bank_at(300, {256: 1234})      # after the 2nd read (t+120) took its snapshot, before the 4th (t+360)
    stba = dba.review()
    dbb = D.Driver(mode=("deferred", 120))
    dbb.bank_at(100, {256: 1234})      # before the 2nd read: both passes see it
    dbb.review()
    check("bank_at(delay_ms, {reg: v}) changes registers at a virtual instant: a change between the passes (t+300 ms: after read 2, before read 4) "
          "is REVIEW NOT COMPLETED, one before the 2nd read (t+100 ms) is seen by both passes and lands in the candidate",
          stba.b9.startswith("REVIEW NOT COMPLETED") and dbb.b9.startswith("CANDIDATE READY") and dbb.candidate()["words"][1] == 1234,
          cap="world_state")
    dsn = D.Driver()
    snap = dsn.snapshot()
    stref = dsn.review(expect=None)
    dif = dsn.diff(snap)
    snap2 = dsn.snapshot()
    dsn.lease("fp_active")
    dsn.press_review()
    dif2 = dsn.diff(snap2)
    check("snapshot() / diff(): a review moves the candidate globals and publishes B3..B6 / B9; a REFUSED review moves only the refusal state "
          "(no candidate global changes except what it republishes) - the 'refusal touched nothing else' evidence",
          "fallback_profile_cand_id" in dif["globals"] and "fallback_profile_review_id_text" in dif["published"]
          and "fallback_profile_cand_id" not in dif2["globals"] and "fallback_profile_last_result_text" in dif2["published"], cap="observation")
    dw_ = D.Driver()
    n_reads = [0]

    def third_read(ev):
        if ev[0] == "read":
            n_reads[0] += 1
            return n_reads[0] == 3
        return False
    dw_.when(third_read, lambda sim: sim.bank.__setitem__(256, 1234))
    stw = dw_.review()
    dw2 = D.Driver()
    hits = []
    dw2.when(lambda ev: ev[0] == "read", lambda sim: hits.append(sim.now_ms), once=False)
    dw2.review()
    dw3 = D.Driver()
    once_hits = []
    dw3.when(lambda ev: ev[0] == "read", lambda sim: once_hits.append(1))
    dw3.review()
    check("when(pred, fn): fn(sim) runs right after the first matching timeline event (here: the third Modbus read -> a register changes between "
          "the passes -> REVIEW NOT COMPLETED); once=False runs it for every match (4 reads), the default only once",
          stw.b9.startswith("REVIEW NOT COMPLETED") and len(hits) == 4 and once_hits == [1], cap="power_cuts")
    check("arr(name) returns a std::array global as a plain list (slicing the FbArray itself raises FbbNotModelled)",
          dw3.arr("fallback_profile_cand_words") == D.GWORDS and raises(lambda: dw3.g["fallback_profile_cand_words"][0:3]) is not None,
          cap="observation")
    dro = D.Driver()
    dro.read_override(lambda addr, count, values: values[:-1] if (addr, count) == (241, 53) else values)
    stro = dro.review()
    dro.read_override(None)
    dro2 = D.Driver()
    dro2.read_override(lambda addr, count, values: [v + 1 for v in values] if dro2.reads_seen == 4 else values)
    stro2 = dro2.review()
    check("read_override(fn) rewrites what a read returns after the bank snapshot (a short reply -> the review gives up, nothing candidate; the "
          "4th read off by one -> the passes disagree), None removes it; write_latched is the FB-B0 write latch (clear on a plain boot)",
          not dro.candidate()["valid"] and dro.b9.startswith("REVIEW NOT COMPLETED") and stro.violations() == []
          and dro2.b9.startswith("REVIEW NOT COMPLETED") and stro2.reads == D.READS and dro.write_latched is False, cap="world_state")
    make = lambda: D.Driver()  # noqa: E731
    rows = D.sweep_timeline_cuts(make, lambda x: x.review(), kinds=("read", "nvs"))
    n_events = len(rows)
    clean = all(r_.cut and r_.drv.b3 == D.IDLE_B3 and r_.drv.nvs_image() == img0 and r_.drv.model_class()[0] == "VALID"
                and r_.drv.boots == 2 and not r_.drv.g["manual_write_in_progress"] for r_ in rows)
    check(f"sweep_timeline_cuts: a power cut right after each of the {n_events} NVS / Modbus-read events of a review, each on a fresh driver and "
          "each followed by a reboot: every row was really cut, the next boot is clean and the NVS image is what it was",
          n_events >= 8 and clean and [r_.index for r_ in rows] == list(range(n_events)), str(n_events), cap="power_cuts")
    rows = D.sweep_nvs_cuts(make, lambda x: x.review())
    n_cut = sum(1 for r_ in rows if r_.cut)
    check(f"sweep_nvs_cuts: a power cut BEFORE and AFTER every direct-NVS event of a review ({len(rows)} points, {n_cut} of them inside the "
          "operation; the points past the last event are the 'no cut' rows), every cut followed by a clean reboot with the NVS image untouched",
          len(rows) == n_cut + 2 and n_cut >= 8 and all(r_.drv.nvs_image() == img0 and r_.drv.b3 == D.IDLE_B3 for r_ in rows)
          and rows[-1].cut is False and rows[0].cut is True and rows[0].label.startswith("nvs point 0 (before event 0)"), str((len(rows), n_cut)),
          cap="power_cuts")
    check("a driver whose firmware lacks the api action / the arm raises FbbNotModelled saying so (execute / arm_on / save / invalidate), and "
          "has_api() / has_arm() tell the truth",
          not D.Driver(api="no_such_action").has_api() and not D.Driver(arm="no_such_arm").has_arm()
          and raises(lambda: D.Driver(api="no_such_action").execute("SAVE", "x", "y")) is not None
          and raises(lambda: D.Driver(arm="no_such_arm").arm_on()) is not None and raises(lambda: D.Driver(arm="no_such_arm").arm_off()) is not None
          and D.Driver().has_api() == any(a.get("action") == "fallback_profile_execute" for a in live["api"]["actions"])
          and D.Driver().has_arm() == any(s_.get("id") == "fallback_profile_arm" for s_ in live["switch"]), cap="operator_actions")
    check("load_fw caches by text (one parse per distinct firmware text) and a mutant text builds its own firmware",
          D.load_fw() is D.load_fw() and D.load_fw(live["_text"]) is D.load_fw() and D.load_fw(live["_text"] + "\n# x\n") is not D.load_fw())

    # =======================================================================
    print("[9] the scenario driver over a synthetic SAVE / INVALIDATE (api action + arm switch + commit_transition_t)")
    # =======================================================================
    def mk(**kw):
        save_text = kw.pop("save_text", None)
        inv_text = kw.pop("invalidate_text", None)
        fw_s = S.with_mini_save(live, save_text=save_text, invalidate_text=inv_text) if (save_text or inv_text) else FW_SYNTH
        return D.Driver(fw=fw_s, api=S.SYNTH_API, arm=S.SYNTH_ARM, arm_on_ms_global="fbs_synth_arm_on_ms", **kw)

    FW_SYNTH = S.with_mini_save(live)

    def ready(**kw):
        x = mk(**kw)
        x.review(expect="CANDIDATE_READY")
        return x

    d = mk()
    check("the synthetic fixture adds an api action, an arm switch and two scripts to the live firmware; the driver finds them by name",
          d.has_api() and d.has_arm() and d.arm_state is False and d.arm_on_ms == 0, cap="operator_actions")
    d.sim.now_ms = 2_000_000
    d.arm_on()
    t_on = d.arm_on_ms
    d.advance(500)
    d.arm_on()
    t_on2 = d.arm_on_ms
    d.arm_off()
    check("arm_on() / arm_off() are Home Assistant's switch.turn_on / turn_off: turn_on_action stamps millis() EVERY time (a repeat refreshes the "
          "stamp), the state follows",
          t_on == 2_000_000 and t_on2 == 2_000_500 and d.arm_state is False, cap="operator_actions")
    d = ready()
    pre_bank, cand_id = d.bank_words(), d.b4
    exp_p = fp.seal_profile(fp.blank_profile(**{**D.GOLD_FIELDS, "generation": 8, "captured_epoch": D.EPOCH0, "binding": 0}))
    exp_w = fd.make_provision(8, exp_p["binding"], 7, D.GOLD["binding"], D.K_P, 1, fd.PROV_OP_SAVE)
    exp = {"FBW": fd.pack_provision(exp_w), "FBP": fp.pack_profile(exp_p)}
    st = d.save()
    check("save(): arm on, then fallback_profile_execute(SAVE, <B4>, SAVE <B4>): SAVED, FBW then FBP with exactly the independently derived bytes, "
          "zero Modbus writes / reads, the arm turned off again by the lambda (one-shot), the three strings copied out of the StringRefs",
          st.b9 == "SAVED - synthetic" and st.violations_fb(("FBW", "FBP"), bytes_=exp, reads=[]) == [] and d.arm_state is False
          and (str(d.g["fbs_synth_exec_action"]), str(d.g["fbs_synth_exec_target_id"]), str(d.g["fbs_synth_exec_confirmation"]))
          == ("SAVE", cand_id, f"SAVE {cand_id}") and d.g["fbs_synth_calls"] == 1 and d.g["fbs_synth_outcome"] == fd.TXN_COMMITTED,
          cap="operator_actions")
    check("the world after the SAVE: stored FBP / FBW decode to the expected records, the FB-B0 model class of the image is VALID, the firmware's "
          "own mirror agrees (B1 VALID, B2 g=8), the candidate is consumed, the SAVE is in the cross-boot write history",
          d.stored("FBP") == exp_p and d.stored("FBW") == exp_w and d.model_class()[0] == "VALID" and d.b1 == "VALID" and "g=8;" in d.b2
          and d.candidate()["valid"] is False and [(b, n, len(x)) for b, n, x, r in d.nvs_set_history()] == [(1, "FBW", 48), (1, "FBP", 96)]
          and st.published["B9"] == ["SAVED - synthetic"] and st.published["B1"] == ["VALID"], cap="observation")
    st2 = d.save(target_id=cand_id)
    check("a second SAVE of the consumed candidate is refused (no saveable candidate), nothing written, the arm turned off again",
          st2.b9 == "SAVE REFUSED - no saveable candidate" and st2.violations_fb(()) == [] and d.arm_state is False, cap="operator_actions")
    d.review(expect="CANDIDATE_READY")
    st3 = d.save()
    exp3_p = fp.seal_profile(fp.blank_profile(**{**D.GOLD_FIELDS, "generation": 9, "captured_epoch": D.EPOCH0, "binding": 0}))
    exp3_w = fd.make_provision(9, exp3_p["binding"], 8, exp_p["binding"], D.K_P, 1, fd.PROV_OP_SAVE)
    check("review + SAVE again in the same boot: generation 9 (the floor includes what this boot committed), the witness's prior is the g8 pair",
          st3.violations_fb(("FBW", "FBP"), bytes_={"FBW": fd.pack_provision(exp3_w), "FBP": fp.pack_profile(exp3_p)}) == []
          and d.stored("FBP")["generation"] == 9 and d.g["fallback_profile_seen_hw_gen"] == 9, cap="operator_actions")
    d.reboot()
    d.review(expect="CANDIDATE_READY")
    d.save()
    check("reboot() between SAVEs: the REAL boot reads g9 VALID, the next SAVE is g10; the write history spans boots (1: FBW FBP FBW FBP, 2: FBW FBP)",
          d.stored("FBP")["generation"] == 10 and [(b, n) for b, n, x, r in d.nvs_set_history()]
          == [(1, "FBW"), (1, "FBP"), (1, "FBW"), (1, "FBP"), (2, "FBW"), (2, "FBP")] and d.boots == 2, cap="reboot")
    refusals = []

    def refusal(label, fn, text_part):
        x = ready()
        stx = fn(x)
        refusals.append((label, text_part in stx.b9, stx.violations_fb(()) == [], x.arm_state is False))

    refusal("arm not on", lambda x: x.save(arm=False), "arm is not on")
    refusal("wrong id", lambda x: x.save(target_id="0" * 16, confirmation="SAVE " + "0" * 16), "candidate ID does not match")
    refusal("wrong phrase", lambda x: x.save(confirmation="SAVE nope"), "confirmation phrase mismatch (expected 'SAVE ")
    refusal("RESTORE is not an action", lambda x: (x.arm_on(), x.execute("RESTORE", x.b4, "RESTORE " + x.b4))[1], "REFUSED - unsupported action")
    refusal("INVALIDATE with a candidate id (not the binding)", lambda x: x.invalidate(target_id=x.b4), "INVALIDATE REFUSED - profile ID does not match")
    check("the refusal matrix (arm off, wrong id, wrong phrase echoing the expected one, an unsupported action, INVALIDATE with the wrong id): each "
          "refuses with its text, writes nothing (violations_fb(()) clean) and leaves the arm off",
          all(a and b and c for _l, a, b, c in refusals), str(refusals), cap="operator_actions")
    dx = ready()
    dx.stop_housekeeping()
    dx.advance(125_000)
    stx = dx.save()
    check("an expired candidate (no housekeeping tick to clear it): the SAVE's own wrap-safe age check refuses, nothing written",
          stx.b9 == "SAVE REFUSED - candidate expired" and stx.violations_fb(()) == [], cap="operator_actions")
    dx = ready()
    dx.advance(131_000)
    stx = dx.save()
    check("with the 10 s tick running the candidate is cleared by IE1 first (REVIEW EXPIRED), so a late SAVE finds no saveable candidate",
          any(s_.startswith("REVIEW EXPIRED") for s_ in dx.published("B9"))
          and stx.b9 == "SAVE REFUSED - no saveable candidate" and stx.violations_fb(()) == [], cap="operator_actions")
    # ---- INVALIDATE
    d = mk()
    binding = d.stored("FBP")["binding"]
    sti = d.invalidate()
    inv_p = fp.pack_profile(fd.invalidate_profile_cxx(D.GOLD))
    inv_w = fd.pack_provision(fd.make_provision(8, fp.unpack_profile(inv_p)["binding"], 7, binding, D.K_P, 1, fd.PROV_OP_INVALIDATE))
    check("invalidate(): the target id defaults to the stored profile's full binding (B2 id=); the synthetic INVALIDATE commits g7 -> g8 INVALIDATED, "
          "FBW then FBP, exact bytes, the model and the firmware agree",
          sti.b9 == "INVALIDATED - synthetic" and sti.violations_fb(("FBW", "FBP"), bytes_={"FBW": inv_w, "FBP": inv_p}) == []
          and d.model_class()[0] == "INVALIDATED" and d.b1 == "INVALIDATED" and d.b2_id() == f"{fp.unpack_profile(inv_p)['binding']:016X}",
          cap="operator_actions")
    sti2 = d.invalidate()
    check("a second INVALIDATE (the profile is INVALIDATED now) is refused and writes nothing",
          "not a VALID profile" in sti2.b9 and sti2.violations_fb(()) == [], cap="operator_actions")
    db_ = mk().mutex(True)
    stb = db_.invalidate()
    dn_ = mk()
    stn = dn_.invalidate(arm=False)
    check("INVALIDATE refuses without the arm and when the bus is busy (a held write mutex): nothing written, the mutex is not ours to release",
          "arm is not on" in stn.b9 and "inverter busy" in stb.b9 and stb.violations_fb(()) == [] and stn.violations_fb(()) == []
          and db_.g["manual_write_in_progress"] is True, cap="operator_actions")
    # ---- faults and the write latch
    d = ready()
    d.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
    stf = d.save()
    check("fault_write(FBW, raw NO_MEM): UNKNOWN_REBOOT - FBP never attempted, the write latch is set, the lambda's overlay says SAVE_UNCONFIRMED, "
          "the error code is reported; the flash still holds the old pair",
          stf.b9 == "SAVE OUTCOME UNKNOWN - synthetic" and stf.fb_set_order == ["FBW"] and d.write_latched
          and d.g["fbs_synth_unconfirmed"] is True and d.b1 == "SAVE_UNCONFIRMED" and d.g["fbs_synth_last_err"] == fd.IDF_ERR_NO_MEM
          and d.stored("FBP") == D.GOLD and d.model_class()[0] == "VALID", cap="world_state")
    d.run("id(fbs_synth_last_us) = ecco_fbdurable::write_latched() ? 77u : 0u;")
    latched_in_lambda = d.g["fbs_synth_last_us"]
    check("write_latched() called from a lambda reports the FB-B0 per-boot latch (set by the UNKNOWN_REBOOT, cleared only by a reboot)",
          latched_in_lambda == 77 and d.write_latched, cap="durable_adapter_additions")
    d.review(expect=None)
    stf2 = d.save()
    check("after UNKNOWN the SAVE is refused for the rest of the boot with ZERO writes (the overlay; and the model's latch would refuse anyway)",
          "previous save outcome unknown" in stf2.b9 and stf2.violations_fb(()) == [], cap="world_state")
    d.reboot()
    check("a reboot is the resolution: the latch is gone, the class is whatever the NVS holds (VALID g7), the overlay is gone",
          d.b1 == "VALID" and not d.sim.write_latch.write_latched and d.g["fbs_synth_unconfirmed"] is False and "g=7;" in d.b2, cap="reboot")
    d = ready()
    d.fault_write("FBW", result=0x1107, visible=H.VIS_OLD)
    stf = d.save()
    stf_retry = (d.review(expect="CANDIDATE_READY"), d.save())[1]
    check("fault_write(FBW, pre-write INVALID_HANDLE): NOT_COMMITTED, nothing changed, no latch; after a fresh review the retry commits "
          "(history: one failed FBW set, then FBW + FBP)",
          stf.b9 == "SAVE NOT COMMITTED - nothing changed" and stf.fb_set_order == ["FBW"] and d.sim.write_latch.write_latched is False
          and stf_retry.b9 == "SAVED - synthetic" and [n for _b, n, _x, _r in d.nvs_set_history()] == ["FBW", "FBW", "FBP"], cap="world_state")
    d = ready()
    d.fault_write("FBP", result=0x1107, visible=H.VIS_OLD)
    stf = d.save()
    check("fault_write(FBP, pre-write) after a committed FBW: NOT_COMMITTED with the witness advanced - the flash is PROFILE_STALE NOW, the firmware's "
          "mirror says so, nothing was written but the witness",
          stf.b9 == "SAVE NOT COMMITTED - witness advanced" and stf.fb_set_order == ["FBW", "FBP"] and d.model_class()[0] == "PROFILE_STALE"
          and d.b1 == "PROFILE_STALE" and d.stored("FBP") == D.GOLD and d.stored("FBW")["hw_generation"] == 8, cap="world_state")
    # ---- power-cut sweeps
    probe = ready()
    n0 = len(probe.sim.nvs_direct.ops)
    probe.sim.nvs_direct.events = 0
    probe.save()
    ops = [(o[0], o[1]) for o in probe.sim.nvs_direct.ops[n0:]]
    k_w, k_p = ops.index(("set", D.FBW_DEC)), ops.index(("set", D.FBP_DEC))
    check("(setup) the SAVE's NVS events: fresh reads, the health probe, then the witness set strictly before the profile set",
          0 < k_w < k_p and probe.sim.nvs_direct.events == len(ops), str(ops))
    rows = D.sweep_nvs_cuts(ready, lambda x: x.save())
    verdict, wrong = {"v7": 0, "stale": 0, "v8": 0}, []
    for r_ in rows:
        p_ = r_.point
        want = "v7" if p_ < 2 * k_w + 1 else ("stale" if p_ < 2 * k_p + 1 else "v8")
        got_g = r_.drv.stored("FBP")["generation"] if r_.drv.stored("FBP") else None
        cls = r_.drv.b1
        have = ("v7" if (cls, got_g) == ("VALID", 7) else "stale" if cls == "PROFILE_STALE" else "v8" if (cls, got_g) == ("VALID", 8) else "?")
        verdict[want] += 1
        if have != want or cls != r_.drv.model_class()[0] or r_.cut is not (p_ < 2 * len(ops)):
            wrong.append((p_, want, have))
    check(f"sweep_nvs_cuts over the SAVE ({len(rows)} points = a cut before and after each of its {len(ops)} NVS events, plus the 'no cut' rows): "
          "the next boot's class is VALID g7 before the witness set landed, PROFILE_STALE between the two sets, VALID g8 once the profile set landed "
          "- every row, and the firmware's boot always agrees with the FB-B0 model's class of the same image",
          not wrong and len(rows) == 2 * len(ops) + 2 and min(verdict.values()) >= 2, str(wrong[:4] + [verdict]), cap="power_cuts")
    rows_t = D.sweep_timeline_cuts(ready, lambda x: x.save(), kinds=("nvs",))
    wrong_t = []
    for r_ in rows_t:
        k = r_.point
        want = "v7" if k < k_w else ("stale" if k < k_p else "v8")
        cls = r_.drv.b1
        g_ = r_.drv.stored("FBP")["generation"]
        have = "v7" if (cls, g_) == ("VALID", 7) else "stale" if cls == "PROFILE_STALE" else "v8" if (cls, g_) == ("VALID", 8) else "?"
        if have != want or not r_.cut:
            wrong_t.append((k, want, have))
    check(f"sweep_timeline_cuts over the same SAVE: a cut right after each of the {len(rows_t)} NVS events gives the same classes (the cut after the "
          "witness set is the first PROFILE_STALE, the cut after the profile set the first VALID g8)",
          len(rows_t) == len(ops) and not wrong_t, str(wrong_t[:4]), cap="power_cuts")
    for label, fn, want_g, want_cls in (("before the FBP set", lambda x: x.cut_before_nvs("set", "FBP"), 7, "PROFILE_STALE"),
                                        ("after the FBP set", lambda x: x.cut_after_nvs("set", "FBP"), 8, "VALID"),
                                        ("before the FBW set", lambda x: x.cut_before_nvs("set", "FBW"), 7, "VALID")):
        x = ready()
        fn(x)
        stc = x.save(catch_cut=True)
        sets_cut = [n for n, _d, _r in stc.fb_sets]
        x.clear_cuts().reboot()
        check(f"cut_{label.replace(' ', '_')}: the SAVE is cut there ({stc.fb_set_order} landed), the reboot reads {want_cls} g{want_g}",
              isinstance(stc.cut, H.PowerCut) and x.b1 == want_cls and x.stored("FBP")["generation"] == (7 if want_cls == "PROFILE_STALE" else want_g)
              and x.b1 == x.model_class()[0], f"{x.b1} {sets_cut}", cap="power_cuts")
    # ---- storage events at boot (F10 / F11 / F12)
    dw = ready()
    dw.save()
    dw.reboot(wipe=True)
    dl = ready()
    dl.save()
    dl.reboot(absent_keys=("FBW",))
    dh0 = ready()
    dh0.save()
    dh0.reboot(handle=0)
    check("reboot(wipe=True) = ESPHome's whole-partition erase at boot (F10): every FB key and the legacy store gone, the firmware boots NOT_CAPTURED; "
          "reboot(absent_keys=(\"FBW\",)) = an init-time key loss (F11): VALID with the witness missing, agreeing with the FB-B0 model of the image; "
          "reboot(handle=0) = a zero NVS handle (F12): every read is unavailable -> UNREADABLE although the bytes are there",
          dw.b1 == "NOT_CAPTURED" and dw.nvs_image() == {} and dw.sim.nvs == {} and dl.b1 == dl.model_class()[0] == "VALID" and "w=MISS" in dl.b2
          and dl.stored("FBW") is None and dl.stored("FBP")["generation"] == 8 and dh0.b1 == "UNREADABLE" and "ld=UNAV" in dh0.b2
          and dh0.stored("FBP")["generation"] == 8, cap="reboot")
    d = ready()
    sg_ = d.step("custom", lambda x: x.sim.call_api(S.SYNTH_API, action="NOPE", target_id="", confirmation=""), idle=False)
    check("Driver.step(label, fn, idle=False) is the generic measured operation: it returns a Step without running the engine and records it in "
          "d.steps; the unsupported action text echoes nothing it should not",
          sg_.label == "custom" and sg_ is d.steps[-1] and sg_.b9 == "REFUSED - unsupported action" and sg_.t1 == sg_.t0, cap="operator_actions")

    d = ready()
    d.save()
    d.review(expect="CANDIDATE_READY")
    d.invalidate()
    check("text_invariants(driver) / idle_invariants(driver): after a review, a SAVE and an INVALIDATE every published FB text is within 200 "
          "characters, free of hazard words, B1 a class name, B9 a locked prefix - and nothing is half-accepted at idle",
          D.text_invariants(d) == [] and D.idle_invariants(d) == [] and len(d.published("B9")) >= 4, str(D.text_invariants(d)[:3]),
          cap="observation")
    d.sim.ent(D.B_IDS["B9"]).publish_state("SAVE FAILED - nope")
    d.sim.ent(D.B_IDS["B1"]).publish_state("NOT_A_CLASS")
    d.sim.ent(D.B_IDS["B3"]).publish_state("st=IDLE; has a space")
    d.sim.ent(D.B_IDS["B2"]).publish_state("x" * 201)
    bad = D.text_invariants(d)
    dcut = D.Driver()
    dcut.cut_when(lambda ev: ev[0] == "read")
    dcut.review(catch_cut=True)
    idle_bad = D.idle_invariants(dcut)
    check("negative controls: a B9 'FAILED' / unknown prefix, a B1 that is no class, a space in B3 and a 201-character text are all flagged; a "
          "review frozen by a power cut is flagged by idle_invariants (lock held, step set), and locked=True excuses the held mutex",
          sum("hazard" in e for e in bad) >= 1 and any("B9 prefix" in e for e in bad) and any("B1:" in e for e in bad)
          and any("B3: a space" in e for e in bad) and any("201 chars" in e for e in bad)
          and any("manual_write_in_progress" in e for e in idle_bad) and any("fallback_profile_step" in e for e in idle_bad)
          and not any("manual_write_in_progress" in e for e in D.idle_invariants(dcut, locked=True)), str((bad[:2], idle_bad[:2])),
          cap="observation")
    check("mutate(text, old, new, count) is an exact-count text mutant (a mismatch raises, so a mutant can never be a silent no-op)",
          D.mutate("a b a", "b", "c") == "a c a" and D.mutate("a b a", "a", "z", count=2) == "z b z"
          and raises(lambda: D.mutate("a b a", "a", "z"), D.DriverError) is not None
          and raises(lambda: D.mutate("a b a", "q", "z"), D.DriverError) is not None, cap="boot_real_yaml")
    # =======================================================================
    print("[10] harness mutants: broken synthetic SAVE / INVALIDATE lambdas, each killed by a named driver scenario")
    # =======================================================================
    def sc_oneshot(x):
        x.review(expect="CANDIDATE_READY")
        x.save()
        return ["the arm stayed ON after the SAVE"] if x.arm_state else []

    def sc_arm(x):
        x.review(expect="CANDIDATE_READY")
        return x.save(arm=False).violations_fb(())

    def sc_id(x):
        x.review(expect="CANDIDATE_READY")
        return x.save(target_id="0000000000000001", confirmation="SAVE " + x.b4).violations_fb(())

    def sc_phrase(x):
        x.review(expect="CANDIDATE_READY")
        return x.save(confirmation="SAVE").violations_fb(())

    def sc_expiry(x):
        x.review(expect="CANDIDATE_READY")
        x.stop_housekeeping()
        x.advance(125_000)
        return x.save().violations_fb(())

    def sc_unconfirmed(x):
        x.review(expect="CANDIDATE_READY")
        x.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
        x.save()
        x.review()
        st_ = x.save()
        return st_.violations_fb(()) + ([] if "previous save outcome unknown" in st_.b9 else [f"refused for the wrong reason: {st_.b9}"])

    def sc_mirror(x):
        x.review(expect="CANDIDATE_READY")
        x.save()
        x.review(expect="CANDIDATE_READY")   # a stale mirror makes the next fresh read look diverged -> UNREADABLE -> not saveable
        return []

    def sc_candidate_consumed(x):
        x.review(expect="CANDIDATE_READY")
        x.save()
        return ["the candidate survived the SAVE"] if x.candidate()["valid"] else []

    def sc_inv_busy(x):
        x.mutex(True)
        return x.invalidate().violations_fb(())

    def sc_inv_arm(x):
        return x.invalidate(arm=False).violations_fb(())

    def sc_inv_twice(x):
        x.invalidate()
        st_ = x.invalidate()
        return st_.violations_fb(()) + ([] if "not a VALID profile" in st_.b9 else [f"refused for the wrong reason: {st_.b9}"])

    def sc_inv_unconfirmed(x):
        x.fault_write("FBW", result=fd.IDF_ERR_NO_MEM, visible=H.VIS_OLD)
        x.invalidate()
        st_ = x.invalidate()
        return st_.violations_fb(()) + ([] if "previous outcome unknown" in st_.b9 else [f"refused for the wrong reason: {st_.b9}"])

    def sc_inv_id(x):
        return x.invalidate(target_id="0000000000000001", confirmation="INVALIDATE 0000000000000001").violations_fb(())

    def edit(text, old, new):
        assert text.count(old) == 1, (text.count(old), old[:60])
        return text.replace(old, new)

    SV, IV = S.SAVE_TEXT, S.INVALIDATE_TEXT
    MUTANTS = [  # (id, what is broken, which script, old, new, the scenario that must see it)
        ("H1", "SAVE never turns the arm off (the one-shot is gone)", "save", "id(fbs_synth_arm).turn_off();\n", "", sc_oneshot),
        ("H2", "SAVE does not check the arm", "save", "if (!armed) {", "if (false) {", sc_arm),
        ("H3", "SAVE does not compare the candidate id", "save", 'if (id(fbs_synth_exec_target_id) != idbuf) {', "if (false) {", sc_id),
        ("H4", "SAVE does not compare the confirmation phrase", "save", "if (id(fbs_synth_exec_confirmation) != want) {", "if (false) {", sc_phrase),
        ("H5", "SAVE has no age check on the candidate", "save", "if ((uint32_t) (millis() - id(fallback_profile_cand_ms)) >= 120000u) {", "if (false) {", sc_expiry),
        ("H6", "SAVE ignores the SAVE_UNCONFIRMED overlay (the model's write latch still refuses)", "save", "if (id(fbs_synth_unconfirmed)) {", "if (false) {", sc_unconfirmed),
        ("H7", "SAVE does not update the RAM mirror from the readbacks", "save", "id(fallback_profile_bytes) = ecco_fallback::encode_profile(m.p);\n", "", sc_mirror),
        ("H8", "SAVE does not consume the candidate (IE6)", "save", "  id(fallback_profile_cand_valid) = false;\n", "", sc_candidate_consumed),
        ("H9", "INVALIDATE does not refuse on a busy bus", "inv", "if (!id(inverter_modbus)->tx_buffer_empty() || id(inverter_modbus)->tx_blocked() || id(manual_write_in_progress)) {", "if (false) {", sc_inv_busy),
        ("H10", "INVALIDATE does not check the arm", "inv", "if (!armed) {", "if (false) {", sc_inv_arm),
        ("H11", "INVALIDATE does not compare the profile id", "inv", 'if (id(fbs_synth_exec_target_id) != idbuf) {', "if (false) {", sc_inv_id),
        ("H12", "INVALIDATE ignores the SAVE_UNCONFIRMED overlay (the latch still refuses)", "inv", "if (id(fbs_synth_unconfirmed)) {", "if (false) {", sc_inv_unconfirmed),
        ("H13", "INVALIDATE skips the class / permission gate (the writer's validation still refuses)", "inv",
         "!ecco_fbdurable::invalidate_class_permitted(e.cls) || !ecco_fallback::profile_invalidate_permitted(pp)\n    || ", "", sc_inv_twice),
    ]
    control = [("save", sc_oneshot), ("save", sc_arm), ("save", sc_id), ("save", sc_phrase), ("save", sc_expiry), ("save", sc_unconfirmed),
               ("save", sc_mirror), ("save", sc_candidate_consumed), ("inv", sc_inv_busy), ("inv", sc_inv_arm), ("inv", sc_inv_id),
               ("inv", sc_inv_unconfirmed), ("inv", sc_inv_twice)]
    check("(control) every harness-mutant scenario is clean on the intact synthetic SAVE / INVALIDATE",
          all(sc(mk()) == [] for _w, sc in control), str([(sc.__name__, sc(mk())) for _w, sc in control if sc(mk())]))
    killed = []
    for mid, what, which, old, new, sc in MUTANTS:
        text = edit(SV if which == "save" else IV, old, new)
        mx = mk(save_text=text) if which == "save" else mk(invalidate_text=text)
        try:
            problems = sc(mx)
        except (D.DriverError, H.FbbNotModelled, AssertionError) as e:
            problems = [f"{type(e).__name__}: {str(e)[:60]}"]
        killed.append(bool(problems))
        check(f"mutant {mid}: {what} - KILLED by {sc.__name__}", bool(problems), "survived")
    check(f"{len(MUTANTS)} harness mutants, all killed", len(killed) == len(MUTANTS) and all(killed), f"{sum(killed)} / {len(MUTANTS)}")
    print(f"    harness mutants: {len(MUTANTS)} total, {sum(killed)} killed")

    # =======================================================================
    print("[10b] harness-code mutants: the harness itself broken in place, each killed by a named probe")
    # =======================================================================
    from unittest import mock
    import _fbb1_fbcap as FC

    def probe_dedup():       # publish_state deduplicates a repeat of the last published state
        s_ = swsim()
        s_.operator_switch("arm", True)
        s_.operator_switch("arm", True)
        return s_.ent("arm").published == [True] and s_.g["cb_on"] == 1

    def probe_rerun():       # turn_on() on an ON switch re-runs turn_on_action (the arm stamp is refreshed)
        s_ = swsim()
        s_.now_ms = 5_000
        s_.operator_switch("arm", True)
        s_.now_ms = 5_500
        s_.operator_switch("arm", True)
        return s_.g["stamp"] == 5500 and s_.g["n_on"] == 2

    def probe_operator():    # the operator's flip goes through the switch's actions
        s_ = swsim()
        s_.operator_switch("arm", True)
        return s_.g["n_on"] == 1 and s_.ent("arm").state is True

    def probe_overread():    # StringRef.c_str() is not NUL-terminated
        s_ = new_sim([api("o", [L("std::string a = confirmation.c_str(); id(u) = a.size();")])])
        s_.call_api("o", action="a", target_id="b", confirmation="SAVE")
        return s_.g["u"] == 4 + len(T.STRINGREF_TAIL)

    def probe_no_str():      # std::string has no str()
        return isinstance(lam('std::string l = "a"; id(w) = l.str().size();')[1], H.FbbNotModelled)

    def probe_call_api_ref():  # api string variables are StringRefs: .str() works on them
        s_ = H.FbbSim(live)
        s_.run_boot()
        s_.call_api("ha_supervision_heartbeat", challenge=str(s_.g["supervision_challenge"]))
        return s_.g["supervision_valid_count"] == 1

    def probe_bytes():       # the audit compares the written bytes
        x = mk()
        x.review(expect="CANDIDATE_READY")
        s_ = x.save()
        fbp = s_.fb_sets[1][1]
        return s_.violations_fb(("FBW", "FBP")) == [] and bool(s_.violations_fb(("FBW", "FBP"), bytes_={"FBP": fbp[:-1] + bytes([fbp[-1] ^ 1])}))

    def probe_foreign_key():  # the audit flags a set to a key that is neither FBP nor FBW
        x = D.Driver()
        m_ = x.sim.mark()
        x.sim.nvs_direct.set_blob(0x1234, b"x")
        return bool(x.sim.since(m_).violations_fb(()))

    def probe_set_log():     # DirectNvs.sets carries every set with its payload
        n_ = H.DirectNvs()
        n_.set_blob(D.K_W, b"\x01" * 48)
        return n_.sets == [(D.K_W, b"\x01" * 48, 0)]

    def probe_wide():        # a plain `int` annotation does not truncate a uint64_t
        s_ = H.FbbSim(mkfw(g5q), fbsave=DBL)
        s_.run_lambda("ecco_fbsave::Wide w{}; w.id64 = 0xD852A4FA2DF7DBA3ULL; id(q) = w.id64;")
        return s_.g["q"] == 0xD852A4FA2DF7DBA3

    def probe_plan_record():  # a dict-held record reads as a harness record
        s_ = H.FbbSim(mkfw(g5q), fbsave=DBL)
        s_.run_lambda("ecco_fbsave::Wide w{}; w.id64 = 0xD852A4FA2DF7DBA3ULL; ecco_fbsave::Planned pl = ecco_fbsave::make_plan(w, 3); id(w) = pl.p_new.generation;")
        return s_.g["w"] == 3

    def probe_before_stats():  # DirectNvs.before_op sees get_stats
        n_ = H.DirectNvs()
        seen_ = []
        n_.before_op = lambda op, key: seen_.append(op)
        n_.get_stats()
        return seen_ == ["stats"]

    def probe_api_params():  # the walker gives api-action lambdas the StringRef parameter list
        return all(x_.params for x_ in LC.lambdas_of(fw2, **synth_kw) if x_.name.startswith("api:"))

    def probe_walker_complete():  # FB-B2: the walk of the live FB-B1-era code finds every lambda the independent count finds (wait_until conditions too)
        return len(LC.lambdas_of(live, scripts_fbb2=(), api_action="", arm_switch="")) == n_fb1 == n_base

    def probe_tu_header():   # FB-B2: the translation unit includes the save header exactly when a lambda names ecco_fbsave::
        return SAVE_INC in LC.build_source(live) and SAVE_INC not in LC.build_source(fw2, lams=no_save)

    def probe_reboot_nvs():  # reboot() carries the NVS: a SAVE survives it
        x = mk()
        x.review(expect="CANDIDATE_READY")
        x.save()
        x.reboot()
        return x.b1 == "VALID" and "g=8;" in x.b2

    def probe_hold_arm():    # a power cut after the witness set leaves PROFILE_STALE (cut_after_nvs fires)
        x = mk()
        x.review(expect="CANDIDATE_READY")
        x.cut_after_nvs("set", "FBW")
        x.save(catch_cut=True)
        x.clear_cuts().reboot()
        return x.b1 == "PROFILE_STALE"

    orig_violations_fb = E.Since.violations_fb
    orig_wr, orig_pub = E.EngineMixin._switch_write, E.EngineMixin._switch_publish
    orig_set_blob, orig_get_stats = H.DirectNvs.set_blob, H.DirectNvs.get_stats
    orig_ctypes = FC._ctypes_of
    orig_call_api = E.EngineMixin.call_api
    orig_getattr = FC.PodValue.__getattr__

    def old_ctypes_of(cls):  # the pre-FB-B2 rule: a bare `int` annotation is a C int
        out = {}
        explicit = getattr(cls, "CTYPES", None)
        if isinstance(explicit, dict):
            out.update(explicit)
        import dataclasses
        if dataclasses.is_dataclass(cls):
            for f in dataclasses.fields(cls):
                if f.name not in out and isinstance(f.type, str) and f.type in T._INT_TYPES:
                    out[f.name] = f.type
        return out

    def no_dedup(self, name, state):
        cfg, ent = self._switches[name], self.ent(name)
        ent.state, ent._has = bool(state), True
        ent.published.append(bool(state))
        for key, local in (("on_state", {"x": bool(state)}), ("on_turn_on" if state else "on_turn_off", {})):
            acts = E._automation_actions(cfg.get(key))
            if acts:
                self._advance_task(self._new_task(None, acts, local, "x"))

    def skip_same_state(self, name, state):
        if self.ent(name).state == bool(state):
            return None
        return orig_wr(self, name, state)

    def operator_state_only(self, name, on):
        self.ent(name).state = bool(on)

    def strict_call_api(self, api_name_, /, **variables):  # variables handed over as plain strings (no StringRef)
        variables = {k: (str(v) if isinstance(v, str) else v) for k, v in variables.items()}
        act = self.api_action(api_name_)
        local = {k: ds.CStr(v) if isinstance(v, str) else v for k, v in variables.items() if k != "_tail"}
        task = self._new_task(None, act.get("then") or [], local, f"api:{api_name_}")
        self._advance_task(task)
        return task

    def set_blob_nolog(self, key, data):
        n0 = len(self.sets)
        r_ = orig_set_blob(self, key, data)
        del self.sets[n0:]
        return r_

    def get_stats_nohook(self):
        hook, self.before_op = self.before_op, None
        try:
            return orig_get_stats(self)
        finally:
            self.before_op = hook

    def pod_getattr_no_record(self, name):
        v = orig_getattr(self, name)
        return v.as_dict() if hasattr(v, "as_dict") and hasattr(v, "to_bytes") else v

    orig_reboot = H.FbbSim.reboot

    def _wiped_reboot(self, kw):
        new = orig_reboot(self, **kw)
        new.nvs_direct = H.DirectNvs()
        return new

    orig_walk, orig_build = LC._walk, LC.build_source

    def walk_no_waits(actions, label, out, params=""):        # HM16: the walker skips every wait_until
        return orig_walk([a for a in (actions or []) if not (isinstance(a, dict) and "wait_until" in a)], label, out, params)

    def build_never_save_inc(*a, **k):                         # HM17: the translation unit never stages the save header
        return orig_build(*a, **k).replace(SAVE_INC + "\n", "")

    def build_always_save_inc(*a, **k):                        # HM18: the translation unit always includes the save header
        s = orig_build(*a, **k)
        return s if SAVE_INC in s else s.replace('#include "ecco_fallback_capture.h"\n', '#include "ecco_fallback_capture.h"\n' + SAVE_INC + "\n", 1)

    H_MUTANTS = [  # (id, what is broken, patch context, the probe that must turn false / raise)
        ("HM1", "publish_state does not deduplicate (a repeat of the last published state publishes again)",
         lambda: mock.patch.object(E.EngineMixin, "_switch_publish", no_dedup), probe_dedup),
        ("HM2", "turn_on() on an already-ON switch is skipped (the turn_on_action does not re-run)",
         lambda: mock.patch.object(E.EngineMixin, "_switch_write", skip_same_state), probe_rerun),
        ("HM3", "the operator's switch flip only sets the state (the actions never run)",
         lambda: mock.patch.object(E.EngineMixin, "operator_switch", operator_state_only), probe_operator),
        ("HM4", "StringRef.c_str() is exact (looks NUL-terminated)",
         lambda: mock.patch.object(T.StringRef, "c_str", lambda self: T.CPtr(self._v)), probe_overread),
        ("HM5", "std::string gains a str() member",
         lambda: mock.patch.object(T.FCStr, "str", lambda self: T.FCStr(self)), probe_no_str),
        ("HM6", "call_api hands the variables over as plain strings (no StringRef)",
         lambda: mock.patch.object(E.EngineMixin, "call_api", strict_call_api), probe_call_api_ref),
        ("HM7", "the audit ignores the written bytes",
         lambda: mock.patch.object(E.Since, "violations_fb", lambda self, expect=(), *, bytes_=None, reads=None, allow_legacy=False:
                                   orig_violations_fb(self, expect, bytes_=None, reads=reads, allow_legacy=allow_legacy)), probe_bytes),
        ("HM8", "the audit does not see a set to a foreign key",
         lambda: mock.patch.object(E.Since, "other_nvs_sets", property(lambda self: [])), probe_foreign_key),
        ("HM9", "DirectNvs.set_blob does not log the payload",
         lambda: mock.patch.object(H.DirectNvs, "set_blob", set_blob_nolog), probe_set_log),
        ("HM10", "a bare `int` annotation is a C int again (uint64_t fields truncate to 32 bits)",
         lambda: mock.patch.object(FC, "_ctypes_of", old_ctypes_of), probe_wide),
        ("HM11", "a record-valued dict member is handed to the lambda as a dict",
         lambda: mock.patch.object(FC.PodValue, "__getattr__", pod_getattr_no_record), probe_plan_record),
        ("HM12", "get_stats does not call before_op",
         lambda: mock.patch.object(H.DirectNvs, "get_stats", get_stats_nohook), probe_before_stats),
        ("HM13", "the lambda walker drops the api action's parameter list",
         lambda: mock.patch.object(LC, "api_params", lambda act: ""), probe_api_params),
        ("HM14", "reboot() wipes the NVS instead of carrying it",
         lambda: mock.patch.object(H.FbbSim, "reboot", lambda self, **kw: _wiped_reboot(self, kw)), probe_reboot_nvs),
        ("HM15", "cut_after_nvs never fires",
         lambda: mock.patch.object(D.Driver, "cut_after_nvs", lambda self, *a, **k: self), probe_hold_arm),
        ("HM16", "FB-B2: the lambda walker skips every wait_until condition (the live FB-B1-era count drops below the independent count)",
         lambda: mock.patch.object(LC, "_walk", walk_no_waits), probe_walker_complete),
        ("HM17", "FB-B2: the translation unit never stages the ecco_fbsave header although the live lambdas name it",
         lambda: mock.patch.object(LC, "build_source", build_never_save_inc), probe_tu_header),
        ("HM18", "FB-B2: the translation unit always includes the ecco_fbsave header, even for lambdas that never name it",
         lambda: mock.patch.object(LC, "build_source", build_always_save_inc), probe_tu_header),
    ]
    hm_killed = []
    for mid, what, ctx, probe in H_MUTANTS:
        control_ok = probe() is True
        try:
            with ctx():
                outcome = probe()
        except BaseException:  # noqa: BLE001 - a crash is a detection too
            outcome = False
        hm_killed.append(control_ok and outcome is not True)
        check(f"harness mutant {mid}: {what} - the probe is true on the real harness and KILLS the mutant", control_ok and outcome is not True,
              f"control {control_ok}, mutant {outcome}")
    check(f"{len(H_MUTANTS)} harness-code mutants, all killed", all(hm_killed), f"{sum(hm_killed)} / {len(H_MUTANTS)}")
    print(f"    harness-code mutants: {len(H_MUTANTS)} total, {sum(hm_killed)} killed")

    # =======================================================================
    print("[11] regression guards and capability coverage")
    # =======================================================================
    check("the FB-B1 capability list is untouched (17 keys, asserted by test_fallback_capture_harness.py) and FCStr / CStr keep their old "
          "behaviour: `+` stays a std::string, ds.CStr has no str() (a raw AttributeError, as before)",
          len(H.FbbSim.CAPABILITIES) == 17 and isinstance(T.FCStr("a") + "b", T.FCStr) and T.FCStr("a") + "b" == "ab"
          and raises(lambda: ds.CStr("a").str(), AttributeError) is not None)
    miss2 = sorted(set(H.FbbSim.CAPABILITIES_FBB2) - COVERED)
    check(f"every one of the {len(H.FbbSim.CAPABILITIES_FBB2)} documented FB-B2 harness capabilities (FbbSim.CAPABILITIES_FBB2) was exercised by a "
          "passing check above", not miss2, f"never exercised: {miss2}")
    miss3 = sorted(set(D.CAPABILITIES) - COVERED)
    check(f"every one of the {len(D.CAPABILITIES)} documented scenario-driver capabilities (_fbb2_drive.CAPABILITIES) was exercised by a passing "
          "check above", not miss3, f"never exercised: {miss3}")
    this_src = Path(__file__).read_text(encoding="utf-8")
    unused = sorted(n for n in dir(D.Driver) if not n.startswith("_") and not re.search(r"[.]" + re.escape(n) + r"\b", this_src))
    check("every public attribute / method of Driver is used by this suite (nothing in the driver is untested)", not unused, f"never used: {unused}")

    print("")
    print(f"{NCHECKS[0]} checks in {time.time() - t_start:.0f} s")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All FB-B2 harness self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
