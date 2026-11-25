#!/usr/bin/env python3
"""Host C++ compile and replay proof of firmware/proposed/ecco_gentle_rate_core.h against the GRC reference model.

The header is the pure decision core of the guarded charge-rate controller (spec docs/dev/gentle-rate-controller/
SPEC.md revision 1); docs/dev/gentle-rate-controller/reference_model.py is its executable specification and
vectors.json holds the golden vectors. This suite proves the header equals the model:

  [1] compiler: a GCC C++ compiler that can also RUN executables must exist. It FAILS, never skips. Search order:
      $ECCO_CXX, g++ / c++ on PATH, then (only on a Windows development PC) the WSL g++ (Ubuntu-24.04) through
      built-in path translation (C:\\x\\y -> /mnt/c/x/y).
  [2] the header compiles under -std=gnu++17 and gnu++20 with -Wall -Wextra -Wpedantic -Werror -fsyntax-only,
      included twice; the default configuration passes config_ok (static_assert in the header);
  [3] the enumerations of the header (states, actions, results, reasons, decode statuses) carry exactly the model's
      numbers, and the harness reads every model configuration and input field;
  [4] the model meets every hand-computed expectation of vectors.json (so CI checks the golden vectors too), and
      EXECUTABLE PROOF: the harness (registry/tests/gentle_rate_harness.cpp) replays every golden vector (with its
      boot record and restarts), the unit vectors (classifier, record decode of valid, corrupted and truncated
      records) and FUZZ_SEQUENCES seeded fuzz sequences; every printed line must equal the model's line;
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
HEADER = ROOT / "firmware" / "proposed" / "ecco_gentle_rate_core.h"
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
REC_FIELDS = ["flags", "slot", "reason", "original", "v", "p", "night_id", "writes_night", "changes",
              "restore_attempts", "lease_end"]


def vector_program(vectors: list[dict]) -> tuple[list[str], list[str], list[str]]:
    inp, exp, fails = [], [], []
    for v in vectors:
        _, cfg = VR.make_core(v, M)
        inp += [VR.serialise_config(cfg), "S"]
        if v.get("boot") is not None:
            r = M.Record(**v["boot"])
            inp.append("B " + " ".join(str(getattr(r, k)) for k in REC_FIELDS) + f" {VR.NOW0}")
        for i, meta in VR.expand(v, M):
            if meta["reboot"] is not None:
                rb = meta["reboot"]
                inp.append("R " + str(-2 if rb.get("absent") else rb.get("corrupt", -1)))
            inp.append(VR.serialise_in(i))
        inp.append("E")
        lines, bad, _ = VR.run(v, M)
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
    inp, exp = [VR.serialise_config(M.Config()), "S"], []
    for live, orig, v, p, _want in units["classify"]:
        inp.append(f"K {live} {orig} {v} {p}")
        exp.append(f"K {M.classify_restore(live, orig, v, p)}")
    cfg = M.Config()
    blobs = []
    for r in units["records"]:
        blobs.append(M.encode_record(M.Record(**r["fields"])))
    good = blobs[0]
    for k in range(len(good)):
        blobs.append(good[:k] + bytes([good[k] ^ 0x01]) + good[k + 1:])
    for n in (0, 1, 27):
        blobs.append(good[:n] if n else b"")
    for b in blobs:
        st, rec = M.decode_record(b, cfg)
        inp.append("H " + b.hex())
        exp.append("H " + " ".join(str(x) for x in [st] + [getattr(rec, k) for k in REC_FIELDS]))
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
                  "static_assert(ecco_grc::config_ok(ecco_grc::Config{}), \"defaults\");\nint main() { return 0; }\n",
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
                  ("A_NONE", "A_WRITE", "A_RESTORE"), ("OP_NONE", "OP_OK", "OP_OK_NOWRITE", "OP_FAIL", "OP_FOREIGN"),
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
        xtu.write_text(f'#include "{HEADER.name}"\nint grc_probe() {{ return ecco_grc::config_ok(ecco_grc::Config{{}}); }}\n',
                       encoding="utf-8")
        r = subprocess.run([xt, "-std=gnu++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", "-I", str(inc), str(xtu)],
                           capture_output=True, text=True, timeout=600)
        check("the ESP32 cross compiler accepts the header (-Werror)", r.returncode == 0, r.stderr[-600:])


HEADER_MUTANTS = [
    ("floor clamp removed", "return (int32_t) imax(c.floor_w, imin(ceiling, r));", "return (int32_t) imin(ceiling, r);"),
    ("ceiling ignores the pre-lease value", "imin(imin(original, i.plan.ceiling_w), c.fw_bound_w)",
     "imin(i.plan.ceiling_w, c.fw_bound_w)"),
    ("no step cap", "raw = imax((int64_t) v - c.max_step_w, imin((int64_t) v + c.max_step_w, raw));", "(void) 0;"),
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
    ("the record CRC is not checked", "if (get32(d + 24) != crc32(d, 24)) { o.status = DEC_BAD_CRC; return o; }", ""),
    ("the pending value is not owned", "if (live == v || live == p) return CLS_OWNED;", "if (live == v) return CLS_OWNED;"),
    ("two leases a night", "if (night_used) return R_REFUSE_NIGHT_USED;", ""),
    ("target guard ignores the taper tail", "int64_t e_tail = (tgt - imax(soc, knee)) * cap_wh / 1000;",
     "int64_t e_tail = 0;"),
    ("an RTC correction does not defer a change", "if (i.rtc_busy || i.mutex_busy) return;\n    int32_t d = desired(i);",
     "if (i.mutex_busy) return;\n    int32_t d = desired(i);"),
    ("END lost while a write is in flight",
     "if (i.end) end_pending = true;\n    if (st == ADJUSTING) { adjusting(i, o); return o; }",
     "if (st == ADJUSTING) { adjusting(i, o); return o; }\n    if (i.end) end_pending = true;"),
    ("uptime comparison not wrap safe", "constexpr uint32_t elapsed(uint32_t now, uint32_t then) { return (uint32_t) (now - then); }",
     "constexpr uint32_t elapsed(uint32_t now, uint32_t then) { return now >= then ? now - then : 0u; }"),
    ("relative step ignores the realised power", "int64_t raw = (int64_t) v * plan_power(i.plan, i.epoch) / p_ref;",
     "int64_t raw = plan_power(i.plan, i.epoch);"),
    ("SOC jump unchecked",
     "if (iabs((int64_t) i.soc - last_soc) > c.soc_jump_max || i.soc < soc_max - c.soc_drop_max) return R_SOC_INVALID;",
     "if (i.soc < soc_max - c.soc_drop_max) return R_SOC_INVALID;"),
]


if __name__ == "__main__":
    sys.exit(main())
