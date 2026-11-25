#!/usr/bin/env python3
"""Host C++ compile and replay proof of docs/dev/gentle-rate-controller/proposed/ecco_gentle_rate_core.h
against the GRC reference model.

The header is the pure decision core of the guarded charge-rate controller (spec docs/dev/gentle-rate-controller/
SPEC.md revision 3); docs/dev/gentle-rate-controller/reference_model.py is its executable specification and
vectors.json holds the golden vectors. This suite proves the header equals the model:

  [1] compiler: a GCC C++ compiler that can also RUN executables must exist. It FAILS, never skips. Search order:
      $ECCO_CXX, g++ / c++ on PATH, then (only on a Windows development PC) the WSL g++ (Ubuntu-24.04) through
      built-in path translation (C:\\x\\y -> /mnt/c/x/y).
  [2] the header compiles under -std=gnu++17 and gnu++20 with -Wall -Wextra -Wpedantic -Werror -fsyntax-only,
      included twice; the default configuration FAILS config_ok (no site capacity floor) and site_config(floor)
      passes it (static_asserts in the header and in the probe);
  [3] the enumerations of the header (states, actions, results, reasons, decode statuses) carry exactly the model's
      numbers, and the harness reads every model configuration and input field;
  [4] the model meets every hand-computed expectation of vectors.json (so CI checks the golden vectors too), and
      EXECUTABLE PROOF: the harness (registry/tests/gentle_rate_harness.cpp) replays every golden vector (with its
      boot record and restarts from the record last COMMITTED, with each result echoing the sequence number and
      kind it answers), the unit vectors (classifier with the owned readback, the lost-lease warning, record decode
      of valid, corrupted, truncated and valid-CRC-but-wrong records) and FUZZ_SEQUENCES seeded fuzz sequences;
      every printed line (the tick, the boot, the RAM record and the flash record) must equal the model's line;
  [5] SANITIZERS: the same harness built with -fsanitize=address,undefined replays the vectors and 200 fuzz
      sequences without a report;
  [6] MUTATION: faults injected into a COPY of the header must each make [4] fail;
  [7] header discipline: only <cstddef> and <cstdint>, no heap, no formatted print, no ESPHome / Arduino / Modbus /
      storage token, no string literal that the durable-tag inventory (registry/tests/_tag_inventory.py) would count;
  [8] OPTIONAL, when the ESP32 cross compiler that ESPHome installs exists under the user profile (read-only): the
      header also compiles with it under -std=gnu++17 -Wall -Wextra -Werror -fsyntax-only.

Writes only to a temporary directory; no hardware, no network.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "docs" / "dev" / "gentle-rate-controller" / "proposed" / "ecco_gentle_rate_core.h"
HARNESS = ROOT / "registry" / "tests" / "gentle_rate_harness.cpp"
MODEL_DIR = ROOT / "docs" / "dev" / "gentle-rate-controller"

FUZZ_SEQUENCES = 600
FUZZ_SEED = 20261132
WSL_DISTRO = "Ubuntu-24.04"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


sys.path.insert(0, str(MODEL_DIR))
_spec = importlib.util.spec_from_file_location("grc_reference_model_host", MODEL_DIR / "reference_model.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["grc_reference_model_host"] = M
_spec.loader.exec_module(M)
import vector_runner as VR  # noqa: E402


# ===========================================================================================================
# Compiler discovery (never skips)
# ===========================================================================================================
class Cxx:
    def __init__(self, base: list[str], wsl: bool) -> None:
        self.base, self.wsl = base, wsl

    def p(self, path) -> str:
        s = str(path)
        if self.wsl:
            m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
            if m:
                return "/mnt/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
        return s

    def run(self, args: list, timeout: int = 600) -> subprocess.CompletedProcess:
        cmd = self.base + [self.p(a) if isinstance(a, Path) else a for a in args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def exe(self, exe: Path, stdin: str, timeout: int = 600) -> subprocess.CompletedProcess:
        cmd = (["wsl.exe", "-d", WSL_DISTRO, "--", self.p(exe)] if self.wsl else [str(exe)])
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)


def find_compiler(tmp: Path) -> Cxx | None:
    cands: list[Cxx] = []
    env = os.environ.get("ECCO_CXX")
    if env:
        cands.append(Cxx(shlex.split(env, posix=(os.name != "nt")), False))
    for name in ("g++", "c++"):
        found = shutil.which(name)
        if found:
            cands.append(Cxx([found], False))
    if os.name == "nt" and shutil.which("wsl.exe"):
        cands.append(Cxx(["wsl.exe", "-d", WSL_DISTRO, "--", "g++"], True))
    probe = tmp / "probe.cpp"
    probe.write_text("#include <cstdio>\nint main(){std::puts(\"ok\");return 0;}\n", encoding="utf-8")
    for c in cands:
        try:
            exe = tmp / ("probe_" + ("w" if c.wsl else "n") + (".exe" if os.name == "nt" and not c.wsl else ""))
            if c.run(["-std=gnu++17", probe, "-o", exe]).returncode != 0:
                continue
            r = c.exe(exe, "")
            if r.returncode == 0 and "ok" in r.stdout:
                return c
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def find_xtensa() -> str | None:
    import glob
    local = os.environ.get("LOCALAPPDATA")
    pats = []
    if local:
        pats.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*", "xtensa-esp-elf",
                                 "bin", "xtensa-esp32-elf-g++*"))
    home = Path.home()
    pats += [str(home / ".platformio" / "packages" / "toolchain-xtensa*" / "bin" / "xtensa-esp32-elf-g++*"),
             str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
             str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pat in pats:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[-1]
    return None


# ===========================================================================================================
# The replay input and the model's expected output
# ===========================================================================================================
REC_FIELDS = VR.REC_FIELDS


def vector_program(vectors: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """The inputs the model actually stepped (VR.run fills each result's echoed sequence number and kind), so the
    header replays exactly the same ticks."""
    inp, exp, fails = [], [], []
    for v in vectors:
        _, cfg = VR.make_core(v, M)
        inp += [VR.serialise_config(cfg), "S"]
        if v.get("boot") is not None:
            r = M.Record(**v["boot"])
            inp.append("B " + VR.serialise_record(r) + f" {VR.NOW0}")
        lines, bad, _, items = VR.run(v, M)
        for kind, x in items:
            if kind == "R":
                inp.append("R " + str(-2 if x.get("absent") else x.get("corrupt", -1)) + f" {x['now_ms']}")
            else:
                inp.append(VR.serialise_in(x))
        inp.append("E")
        exp += lines
        fails += bad
    return inp, exp, fails


def fuzz_program(n: int, seed: int) -> tuple[list[str], list[str]]:
    inp, exp = [], []
    for k in range(n):
        cfg, items = VR.fuzz_items(seed + k, M)
        inp += [VR.serialise_config(cfg), "S"]
        for kind, x in items:
            inp.append(f"R {x}" if kind == "R" else VR.serialise_in(x))
        inp.append("E")
        exp += VR.run_items(cfg, items, M)
    return inp, exp


def unit_program() -> tuple[list[str], list[str]]:
    import json
    units = json.loads((MODEL_DIR / "vectors.json").read_text(encoding="utf-8"))["units"]
    cfg = M.Config()
    for k, v in VR.FRAME_CONFIG.items():
        setattr(cfg, k, v)
    inp, exp = [VR.serialise_config(cfg), "S"], []
    for live, orig, v, p, q, _want in units["classify"]:
        inp.append(f"K {live} {orig} {v} {p} {q}")
        exp.append(f"K {M.classify_restore(live, orig, v, p, q)}")
    for live, table, _want in units["lost_lease"]:
        inp.append("W " + " ".join(str(x) for x in list(live) + list(table)))
        exp.append(f"W {M.lost_lease_slots(live, table)}")
    blobs = []
    for r in units["records"]:
        blobs.append(M.encode_record(M.Record(**r["fields"])))
    good = blobs[0]
    for hexs, _want in units["raw"]:
        blobs.append(bytes.fromhex(hexs))
    for k in range(len(good)):
        blobs.append(good[:k] + bytes([good[k] ^ 0x01]) + good[k + 1:])
    for n in (0, 1, 31, 32, 43, 44, 47):
        blobs.append(good[:n] if n else b"")
    blobs.append(good + b"\x00")
    for b in blobs:
        st, rec = M.decode_record(b, cfg)
        inp.append("H " + b.hex())
        exp.append("H " + " ".join(str(x) for x in [st] + [getattr(rec, k) for k in REC_FIELDS] + list(rec.hist)))
    return inp, exp


def first_diff(got: list[str], want: list[str]) -> str:
    for k in range(max(len(got), len(want))):
        g = got[k] if k < len(got) else "<missing>"
        w = want[k] if k < len(want) else "<missing>"
        if g != w:
            return f"line {k + 1}: header '{g}' / model '{w}'"
    return ""


# ===========================================================================================================
def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="grc_host_"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): " + "; ".join(FAILURES))
        return 1
    print("ALL PASS")
    return 0


def run(tmp: Path) -> None:
    header_text = HEADER.read_text(encoding="utf-8")
    print("[1] compiler")
    cxx = find_compiler(tmp)
    check("a C++ compiler that can build and run executables exists (never skipped)", cxx is not None,
          "set ECCO_CXX, install g++, or provide the WSL Ubuntu-24.04 g++")
    if cxx is None:
        return
    print(f"        using: {' '.join(cxx.base)}")

    print("[2] the header compiles cleanly")
    inc = tmp / "inc"
    inc.mkdir()
    (inc / HEADER.name).write_text(header_text, encoding="utf-8", newline="\n")
    tu = tmp / "twice.cpp"
    tu.write_text(f'#include "{HEADER.name}"\n#include "{HEADER.name}"\n'
                  "static_assert(!ecco_grc::config_ok(ecco_grc::Config{}), \"no usable default floor\");\n"
                  "static_assert(ecco_grc::config_ok(ecco_grc::site_config(30000)), \"a site floor\");\n"
                  "int main() { return 0; }\n",
                  encoding="utf-8", newline="\n")
    for std in ("gnu++17", "gnu++20"):
        r = cxx.run([f"-std={std}", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fsyntax-only", "-I", inc, tu])
        check(f"-std={std} -Wall -Wextra -Wpedantic -Werror, included twice", r.returncode == 0, r.stderr[-600:])

    print("[3] the contract: enumerations and fields")
    enum_ok = True
    detail = []
    for name, val in M.REASONS.items():
        m = re.search(r"\b" + name + r" = (\d+)", header_text)
        if not m or int(m.group(1)) != val:
            enum_ok = False
            detail.append(name)
    header_reasons = set(re.findall(r"\b(R_[A-Z_]+) = \d+", header_text))
    for group in (("IDLE", "ARMED", "LEASED", "ADJUSTING", "SETTLING", "RESTORING", "FAULT"),
                  ("A_NONE", "A_WRITE", "A_RESTORE"),
                  ("OP_NONE", "OP_OK", "OP_OK_NOWRITE", "OP_FAIL", "OP_FOREIGN", "OP_NO_ANSWER", "OP_DEFERRED"),
                  ("CLS_ALREADY", "CLS_OWNED", "CLS_FOREIGN"),
                  ("DEC_OK", "DEC_ABSENT", "DEC_BAD_SIZE", "DEC_BAD_CRC", "DEC_BAD_MAGIC", "DEC_BAD_VERSION",
                   "DEC_BAD_VALUE")):
        for name in group:
            m = re.search(r"\b" + name + r" = (\d+)", header_text)
            if not m or int(m.group(1)) != getattr(M, name):
                enum_ok = False
                detail.append(name)
    check("every reason, state, action, result, class and decode status has the model's number",
          enum_ok and header_reasons == set(M.REASONS), ", ".join(detail) + str(header_reasons ^ set(M.REASONS)))
    cfg_fields = {f.name for f in fields(M.Config)}
    hdr_cfg = set(re.findall(r"^\s+(?:int32_t|uint32_t) (\w+) = ", header_text[header_text.index("struct Config"):
                                                                              header_text.index("constexpr bool config_ok")], re.M))
    check("the header Config, the model Config and the harness field list are the same set",
          cfg_fields == hdr_cfg == set(VR.CONFIG_FIELDS), str((cfg_fields ^ hdr_cfg) | (cfg_fields ^ set(VR.CONFIG_FIELDS))))
    in_fields = {f.name for f in fields(M.In)} - {"plan"}
    plan_fields = {f.name for f in fields(M.Plan)} - {"t", "p"}
    check("the harness reads every input and plan field", in_fields == set(VR.IN_FIELDS) and
          plan_fields == set(VR.PLAN_FIELDS), str(in_fields ^ set(VR.IN_FIELDS)))

    print(f"[4] executable proof: vectors, units and {FUZZ_SEQUENCES} fuzz sequences (seed {FUZZ_SEED})")
    vectors = VR.load_vectors()
    v_in, v_exp, v_fails = vector_program(vectors)
    check(f"the model meets every hand-computed expectation of the {len(vectors)} golden vectors", not v_fails,
          "; ".join(v_fails[:3]))
    u_in, u_exp = unit_program()
    f_in, f_exp = fuzz_program(FUZZ_SEQUENCES, FUZZ_SEED)
    exe = tmp / "harness"
    r = cxx.run(["-std=gnu++17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", inc, HARNESS, "-o", exe])
    check("the harness builds", r.returncode == 0, r.stderr[-800:])
    if r.returncode != 0:
        return
    for label, inp, exp in (("golden vectors (%d, %d lines)" % (len(vectors), len(v_exp)), v_in, v_exp),
                            ("unit vectors (%d lines)" % len(u_exp), u_in, u_exp),
                            ("fuzz (%d lines)" % len(f_exp), f_in, f_exp)):
        rr = cxx.exe(exe, "\n".join(inp) + "\n")
        got = rr.stdout.splitlines()
        d = first_diff(got, exp)
        check(f"header trace == model trace: {label}", rr.returncode == 0 and not d, d or rr.stderr[-400:])

    print("[5] sanitizers")
    exe_s = tmp / "harness_san"
    r = cxx.run(["-std=gnu++17", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I", inc,
                 HARNESS, "-o", exe_s])
    check("the harness builds with -fsanitize=address,undefined", r.returncode == 0, r.stderr[-600:])
    if r.returncode == 0:
        s_in, s_exp = fuzz_program(200, FUZZ_SEED + 50_000)
        rr = cxx.exe(exe_s, "\n".join(v_in + u_in + s_in) + "\n")
        d = first_diff(rr.stdout.splitlines(), v_exp + u_exp + s_exp)
        check("vectors, units and 200 fuzz sequences under the sanitizers: no report, same trace",
              rr.returncode == 0 and not d and "runtime error" not in rr.stderr, (d or rr.stderr[-600:]))

    print("[6] mutation of a copy of the header")
    m_in, m_exp = fuzz_program(120, FUZZ_SEED + 90_000)
    prog_in = v_in + u_in + m_in
    prog_exp = v_exp + u_exp + m_exp
    survivors = []
    for k, (name, old, new) in enumerate(HEADER_MUTANTS):
        if header_text.count(old) != 1:
            check(f"header mutant '{name}' applies exactly once", False, f"found {header_text.count(old)} times")
            continue
        md = tmp / f"mut{k}"
        md.mkdir()
        (md / HEADER.name).write_text(header_text.replace(old, new), encoding="utf-8", newline="\n")
        mexe = tmp / f"mut{k}_exe"
        r = cxx.run(["-std=gnu++17", "-O1", "-w", "-I", md, HARNESS, "-o", mexe])
        if r.returncode != 0:
            print(f"        killed (does not compile): {name}")
            continue
        rr = cxx.exe(mexe, "\n".join(prog_in) + "\n")
        d = first_diff(rr.stdout.splitlines(), prog_exp)
        if not d and rr.returncode == 0:
            survivors.append(name)
        print(f"        {'killed' if d or rr.returncode else 'SURVIVED'}: {name}" + (f"  <- {d[:80]}" if d else ""))
    check(f"every one of {len(HEADER_MUTANTS)} header mutants is caught by the replay", not survivors,
          ", ".join(survivors))

    print("[7] header discipline")
    code = re.sub(r"//[^\n]*", "", header_text)
    includes = re.findall(r"#include\s*[<\"]([^>\"]+)[>\"]", code)
    check("only <cstddef> and <cstdint>", sorted(includes) == ["cstddef", "cstdint"], str(includes))
    banned = [t for t in ("new ", "malloc", "free(", "printf", "std::", "esphome", "Arduino", "millis(", "nvs_",
                          "commit_record", "load_record", "global_preferences", "make_preference", ".save(", ".sync(",
                          "modbus", "id(", "ESP_LOG", "static int", "static uint", "static bool")
              if t in code]
    check("no heap, print, ESPHome, Arduino, Modbus, storage or static-state token", not banned, str(banned))
    sys.path.insert(0, str(ROOT / "registry" / "tests"))
    import _tag_inventory as ti
    check("the durable-tag inventory sees no declaration and no durable literal in the header",
          not ti.inventory(header_text) and not ti.durable_literals(header_text),
          str(ti.inventory(header_text)) + str(ti.durable_literals(header_text)))

    print("[8] optional: ESP32 cross compiler")
    xt = find_xtensa()
    if xt is None:
        print("  NOTE  [8] no xtensa cross compiler found under the user profile: the -Werror compile with uint32_t = "
              "unsigned long is unproven here (CI and the integration build cover it)")
    else:
        xtu = tmp / "xt.cpp"
        xtu.write_text(f'#include "{HEADER.name}"\n'
                       'int grc_probe() { return ecco_grc::config_ok(ecco_grc::site_config(30000)); }\n',
                       encoding="utf-8")
        r = subprocess.run([xt, "-std=gnu++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", "-I", str(inc), str(xtu)],
                           capture_output=True, text=True, timeout=600)
        check("the ESP32 cross compiler accepts the header (-Werror)", r.returncode == 0, r.stderr[-600:])


HEADER_MUTANTS = [
    ("floor clamp removed", "return (int32_t) imax(c.floor_w, imin(ceiling, r));", "return (int32_t) imin(ceiling, r);"),
    ("ceiling ignores the pre-lease value", "int64_t hard = imin(original, c.fw_bound_w) / c.round_w * c.round_w;",
     "int64_t hard = (int64_t) c.fw_bound_w / c.round_w * c.round_w;"),
    ("no step cap", "r = imax(lo, imin(hi, r));", "(void) 0;"),
    ("no hysteresis", "if (iabs(delta) < c.hyst_w) return;", "if (iabs(delta) < 0) return;"),
    ("dwell is the settle time", "if (elapsed(i.now_ms, last_change_ms) < c.dwell_ms) return;",
     "if (elapsed(i.now_ms, last_change_ms) < c.settle_ms) return;"),
    ("max changes off by one", "if (bms_limited || changes >= c.max_changes) return;",
     "if (bms_limited || changes > c.max_changes) return;"),
    ("deadline exclusive", "if (i.epoch >= lease_end) return R_DEADLINE;", "if (i.epoch > lease_end) return R_DEADLINE;"),
    ("plan age ignored", "if (pl.age_ms > c.plan_max_age_ms) return R_PLAN_LOST;", ""),
    ("no ownership fence", "if (elapsed(i.now_ms, last_change_ms) > i.cfg_age_ms) {", "if (true) {"),
    ("a foreign value is restored over", "if (i.live_sp != v && i.live_sp != p) return R_FOREIGN;",
     "if (i.live_sp != v && i.live_sp != p) return R_CONFIG_DRIFT;"),
    ("restore attempts unbounded", "if (restore_attempts >= c.max_restore_attempts) {\n          fault(o, R_RESTORE_FAILED);",
     "if (false) {\n          fault(o, R_RESTORE_FAILED);"),
    ("the record CRC is not checked", "if (get32(d + 44) != crc32(d, 44)) { o.status = DEC_BAD_CRC; return o; }", ""),
    ("the pending value is not owned", "if (live == v || live == p || (q >= 0 && live == q)) return CLS_OWNED;",
     "if (live == v || (q >= 0 && live == q)) return CLS_OWNED;"),
    ("two leases a night", "if (night_used) return R_REFUSE_NIGHT_USED;", ""),
    ("target guard ignores the taper tail", "int64_t e_tail = (tgt - imax(soc, knee)) * cap_wh / 1000;",
     "int64_t e_tail = 0;"),
    ("an RTC correction does not defer a change", "if (i.rtc_busy || i.mutex_busy) return;\n    int32_t d = desired(i);",
     "if (i.mutex_busy) return;\n    int32_t d = desired(i);"),
    ("END lost while a write is in flight",
     "if (i.end) end_pending = true;\n    if (!i.grid_ok) grid_pending = true;\n"
     "    if (st == ADJUSTING) { adjusting(i, o, res); return o; }",
     "if (!i.grid_ok) grid_pending = true;\n    if (st == ADJUSTING) { adjusting(i, o, res); return o; }\n"
     "    if (i.end) end_pending = true;"),
    ("uptime comparison not wrap safe", "constexpr uint32_t elapsed(uint32_t now, uint32_t then) { return (uint32_t) (now - then); }",
     "constexpr uint32_t elapsed(uint32_t now, uint32_t then) { return now >= then ? now - then : 0u; }"),
    ("relative step ignores the realised power", "int64_t raw = (int64_t) v * plan_power(i.plan, i.epoch) / p_ref;",
     "int64_t raw = plan_power(i.plan, i.epoch);"),
    ("SOC jump unchecked",
     "if (iabs((int64_t) i.soc - last_soc) > c.soc_jump_max || i.soc < soc_max - c.soc_drop_max) return R_SOC_INVALID;",
     "if (i.soc < soc_max - c.soc_drop_max) return R_SOC_INVALID;"),
    # ---- revision 2 (the review findings), each also a model mutant
    ("no restore operation timeout",
     "} else if (res == OP_FAIL || elapsed(i.now_ms, op_start_ms) >= c.op_timeout_ms) {\n        op_pending = false;\n"
     "        if (res == OP_FAIL) {\n          own_readback(i, o);\n        } else {\n          late_seq = op_seq;\n"
     "          late_kind = op_kind;\n        }\n        if (restore_attempts >= c.max_restore_attempts) {",
     "} else if (res == OP_FAIL) {\n        op_pending = false;\n"
     "        if (res == OP_FAIL) {\n          own_readback(i, o);\n        } else {\n          late_seq = op_seq;\n"
     "          late_kind = op_kind;\n        }\n        if (restore_attempts >= c.max_restore_attempts) {"),
    ("the in_slot wrap branch is never true", "if (start > end) return m >= start || m < end;",
     "if (start > end) return false;"),
    ("an unanswered restore spends an attempt", "restore_attempts = (int32_t) imax(0, restore_attempts - 1);", "(void) 0;"),
    ("the restore does not wait for the inverter to answer",
     "if (i.rx_age_ms > c.rx_fresh_ms) return;\n    if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve)",
     "if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve)"),
    ("a clamped readback is not owned", "set_q(i.op_value, o);\n      begin_restore(i, o, R_READBACK_MISMATCH);",
     "begin_restore(i, o, R_WRITE_FAILED);"),
    ("the classifier ignores the owned readback", "if (live == v || live == p || (q >= 0 && live == q)) return CLS_OWNED;",
     "if (live == v || live == p) return CLS_OWNED;"),
    ("a result is taken whatever its sequence", "if (op_pending && i.op_seq == op_seq && i.op_kind == op_kind) return i.op;",
     "if (op_pending && i.op_kind == op_kind) return i.op;"),
    ("a result is taken whatever its kind", "if (op_pending && i.op_seq == op_seq && i.op_kind == op_kind) return i.op;",
     "if (op_pending && i.op_seq == op_seq) return i.op;"),
    ("the sequence number does not advance", "seq = seq + 1;\n    if (seq == 0) seq = 1;", "if (seq == 0) seq = 1;"),
    ("the plan's window end is not checked at START",
     "if (iabs(pl.window_end - slot_end) > c.window_match_s) return R_REFUSE_SLOT;", ""),
    ("the plan's window end is not checked in a lease",
     "if (iabs(pl.window_end - slot_end) > c.window_match_s) return R_PLAN_WINDOW;", ""),
    ("the target guard uses the plan's window end",
     "if (guard_trips(i.epoch, i.soc, target, capacity_wh, p0, slot_end, taper)) return R_TARGET_GUARD;",
     "if (guard_trips(i.epoch, i.soc, target, capacity_wh, p0, pl.window_end, taper)) return R_TARGET_GUARD;"),
    ("the lease end ignores the slot's own end",
     "lease_end = imin(pl.deadline, slot_end_epoch(i.epoch, i.local_min, i.slot_end_min) - c.end_margin_s);",
     "lease_end = imin(pl.deadline, pl.window_end - c.end_margin_s);"),
    ("the slot end does not wrap midnight", "return epoch + (int64_t) mod1440(slot_end_min - local_min) * 60 - 60;",
     "return epoch + (int64_t) (slot_end_min - local_min) * 60 - 60;"),
    ("no capacity floor in the lease", "capacity_wh = (int32_t) imax(pl.capacity_wh, c.capacity_floor_wh);",
     "capacity_wh = pl.capacity_wh;"),
    ("a later plan may lower the guard's capacity", "if (cap > capacity_wh) capacity_wh = cap;",
     "if (cap != capacity_wh) capacity_wh = cap;"),
    ("the guard accepts any taper knee", "int64_t knee = imin(tgt, imin(taper_pct, c.taper_max_pct) * 10);",
     "int64_t knee = imin(tgt, (int64_t) taper_pct * 10);"),
    ("the owner ceiling bypasses the step cap", "int64_t ceiling = imin(hard, imax(i.plan.ceiling_w, lo));",
     "int64_t ceiling = imin(hard, (int64_t) i.plan.ceiling_w);"),
    ("grid loss ignored in a lease", "if (grid_pending) return R_GRID_LOSS;", ""),
    ("START with the grid lost", "if (!i.grid_ok) return R_REFUSE_GRID;", ""),
    ("grid loss not acted on at the verified write",
     "if (grid_pending) { begin_restore(i, o, R_GRID_LOSS); restoring(i, o, OP_NONE); return; }", ""),
    ("Restore original without a known original", "if (original == 0 || busy ||", "if (busy ||"),
    ("FAULT restores without the owner's pulse", "if (i.restore_req) {\n      bool busy", "if (true) {\n      bool busy"),
    ("an unanswered change does not end the lease",
     "} else if (res == OP_NO_ANSWER) {\n      begin_restore(i, o, R_WRITE_UNANSWERED);",
     "} else if (false) {\n      begin_restore(i, o, R_WRITE_UNANSWERED);"),
    # ---- revision 3 (the confirmation review), each also a model mutant
    ("the free retries unbounded", "if (free_night >= c.restore_free_max) {\n          fault(o, R_RESTORE_STALLED);",
     "if (false) {\n          fault(o, R_RESTORE_STALLED);"),
    ("the free retries not persisted", "    r.free_night = (uint8_t) free_night;\n", ""),
    ("the boot forgets the free retries", "    free_night = rec.free_night;\n", ""),
    ("no stall bound", "if (stall_ms >= c.restore_stall_ms) { fault(o, R_RESTORE_STALLED); return; }", ""),
    ("the stall bound counts a silent inverter", "if (i.rx_age_ms <= c.rx_fresh_ms) {\n      uint64_t s",
     "if (true) {\n      uint64_t s"),
    ("the stall bound adds a whole tick gap", "(d < c.rx_fresh_ms ? d : c.rx_fresh_ms)", "d"),
    ("an owned readback is not committed", "q = value;\n      o.commit = true;", "q = value;"),
    ("the late readback of an abandoned operation is not owned",
     "if (i.op == OP_FAIL) own_readback(i, o);\n    }\n    return OP_NONE;", "(void) 0;\n    }\n    return OP_NONE;"),
    ("a late result owns more than once",
     "      late_seq = 0;\n      late_kind = A_NONE;\n      if (i.op == OP_FAIL) own_readback(i, o);",
     "      if (i.op == OP_FAIL) own_readback(i, o);"),
    ("the write timeout does not remember the abandoned write",
     "late_seq = op_seq;\n      late_kind = op_kind;\n      begin_restore(i, o, R_OP_TIMEOUT);",
     "begin_restore(i, o, R_OP_TIMEOUT);"),
    ("G19 a later -1 readback erases q",
     "if (i.op_value >= 0 && i.op_value != original && i.op_value != v && i.op_value != p) set_q(i.op_value, o);",
     "if (i.op_value != original && i.op_value != v && i.op_value != p) set_q(i.op_value, o);"),
    ("G04 a 0 W readback not owned", "if (res == OP_FAIL && i.op_value >= 0 && i.op_value != v && i.op_value != p) {",
     "if (res == OP_FAIL && i.op_value > 0 && i.op_value != v && i.op_value != p) {"),
    ("G03 the owner restore's readback not owned",
     "        if (res == OP_FAIL) {\n          own_readback(i, o);\n        } else {\n          late_seq = op_seq;\n"
     "          late_kind = op_kind;\n        }\n        last_reason = R_RESTORE_FAILED;",
     "        if (res == OP_FAIL) {\n          (void) 0;\n        } else {\n          late_seq = op_seq;\n"
     "          late_kind = op_kind;\n        }\n        last_reason = R_RESTORE_FAILED;"),
    ("G14 the owner's Restore original never times out",
     "} else if (res == OP_FAIL || elapsed(i.now_ms, op_start_ms) >= c.op_timeout_ms) {\n        op_pending = false;\n"
     "        if (res == OP_FAIL) {\n          own_readback(i, o);\n        } else {\n          late_seq = op_seq;\n"
     "          late_kind = op_kind;\n        }\n        last_reason = R_RESTORE_FAILED;",
     "} else if (res == OP_FAIL) {\n        op_pending = false;\n"
     "        if (res == OP_FAIL) {\n          own_readback(i, o);\n        } else {\n          late_seq = op_seq;\n"
     "          late_kind = op_kind;\n        }\n        last_reason = R_RESTORE_FAILED;"),
    ("G23 an unanswered restore in FAULT keeps the operation pending",
     "      } else if (res == OP_NO_ANSWER || res == OP_DEFERRED) {\n        op_pending = false;\n"
     "        if (free_night < c.restore_free_max) {",
     "      } else if (res == OP_NO_ANSWER || res == OP_DEFERRED) {\n        if (free_night < c.restore_free_max) {"),
    ("G24 the restore is not begun in the tick of a clamped readback",
     "      set_q(i.op_value, o);\n      begin_restore(i, o, R_READBACK_MISMATCH);",
     "      set_q(i.op_value, o);\n      begin_restore(i, o, R_READBACK_MISMATCH);\n      return;"),
    ("the core leases without a site floor", "if (!config_ok(c)) return R_REFUSE_CONFIG;", ""),
    ("G10 the lower step bound rounds down", "int64_t lo = round_up((int64_t) v - c.max_step_w, c.round_w);",
     "int64_t lo = imax(0, (int64_t) v - c.max_step_w) / c.round_w * c.round_w;"),
    ("no upper step bound", "r = imax(lo, imin(hi, r));", "r = imax(lo, r);"),
    ("no lower step bound", "r = imax(lo, imin(hi, r));", "r = imin(hi, r);"),
    ("the backoff compared by absolute time (the 24.8-day wrap)",
     "if (restore_hold && elapsed(i.now_ms, restore_from_ms) >= c.restore_backoff_ms) restore_hold = false;",
     "restore_hold = (uint32_t) (i.now_ms - restore_from_ms - c.restore_backoff_ms) >= 0x80000000u;"),
    ("the 7-day ceiling ignored",
     "if ((int64_t) week_writes() + n > c.week_write_ceiling - reserve) return R_REFUSE_WEEK_BUDGET;", ""),
    ("the lifetime ceiling ignored",
     "if ((int64_t) life_writes + n > c.life_write_ceiling - reserve) return R_REFUSE_LIFE_BUDGET;", ""),
    ("the night roll drops the closing night", "if (age == k) nw[j] = writes_night;", "if (age == k) nw[j] = 0;"),
    ("the night roll does not shift the window", "else if (age > k) nw[j] = hist[age - k - 1];", ""),
    ("the 7-day window not persisted", "for (int k = 0; k < 6; k++) r.hist[k] = (uint8_t) hist[k];", ""),
    ("the lifetime count not persisted", "    r.life_writes = life_writes;\n", ""),
    ("an unanswered operation keeps its lifetime count", "    if (life_writes > 0) life_writes--;\n", ""),
    ("no night roll in FAULT", "if ((st == IDLE || st == ARMED || st == FAULT) && !night_unknown",
     "if ((st == IDLE || st == ARMED) && !night_unknown"),
    ("G15 the restore path's night ceiling removed",
     "if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve) { fault(o, R_NIGHT_CEILING); return; }", ""),
    ("the lease restore takes the owner's reserved write",
     "if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve) { fault(o, R_NIGHT_CEILING); return; }",
     "if (writes_night + 1 > c.night_write_ceiling) { fault(o, R_NIGHT_CEILING); return; }"),
    ("a corrupt record boots with empty counts",
     "      night_unknown = true;\n      night_used = true;\n      writes_night = c.night_write_ceiling;\n"
     "      free_night = c.restore_free_max;\n      for (int k = 0; k < 6; k++) hist[k] = c.night_write_ceiling;\n", ""),
    ("the unknown night is never adopted",
     "if (night_unknown && i.night_id != 0) { night_id = i.night_id; night_unknown = false; }", ""),
    ("ACK clears the night's counts", "      clear_lease();\n      state = IDLE;\n      last_reason = R_ACKED;",
     "      clear_lease();\n      writes_night = 0;\n      night_used = false;\n      state = IDLE;\n"
     "      last_reason = R_ACKED;"),
    ("a night number going backwards accepted", " || i.night_id < night_id) return R_REFUSE_CLOCK;",
     ") return R_REFUSE_CLOCK;"),
    ("an action names no slot", "    o.slot = slot;\n", "    o.slot = 0;\n"),
    ("START ignores which slot the configuration describes", "if (i.cfg_slot != pl.slot || !i.slot_grid",
     "if (!i.slot_grid"),
    ("the lease ignores which slot the configuration describes", "if (i.cfg_slot != slot || !i.slot_grid",
     "if (!i.slot_grid"),
    ("G01 the rx gate inclusive",
     "if (i.rx_age_ms > c.rx_fresh_ms) return;\n    if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve)",
     "if (i.rx_age_ms >= c.rx_fresh_ms) return;\n    if (writes_night + 1 > c.night_write_ceiling - c.owner_restore_reserve)"),
    ("G07 grid loss ignored while SETTLING", "if (!i.grid_ok) grid_pending = true;\n    if (st == ADJUSTING)",
     "if (!i.grid_ok && st != SETTLING) grid_pending = true;\n    if (st == ADJUSTING)"),
    ("G08 the lease's window tolerance doubled",
     "if (iabs(pl.window_end - slot_end) > c.window_match_s) return R_PLAN_WINDOW;",
     "if (iabs(pl.window_end - slot_end) > 2 * c.window_match_s) return R_PLAN_WINDOW;"),
    ("G18 the lease's window check one-sided",
     "if (iabs(pl.window_end - slot_end) > c.window_match_s) return R_PLAN_WINDOW;",
     "if (pl.window_end - slot_end > c.window_match_s) return R_PLAN_WINDOW;"),
    ("G22 END outranks the latched grid loss at the verified write",
     "if (grid_pending) { begin_restore(i, o, R_GRID_LOSS); restoring(i, o, OP_NONE); return; }",
     "if (grid_pending && !end_pending) { begin_restore(i, o, R_GRID_LOSS); restoring(i, o, OP_NONE); return; }"),
]


if __name__ == "__main__":
    sys.exit(main())
