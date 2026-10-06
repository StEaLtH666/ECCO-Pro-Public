#!/usr/bin/env python3
"""FB-B0 - host C++ compile and fault injection of the Fallback durable model.

firmware/include/ecco_fallback_durable_model.h holds the REAL templated code
the device will run (read_direct_t, write_one_, commit_transition_t,
read_pair_t) plus the FBW witness, compose rules, outcome table and golden
tables (S2 Part A A4). This suite:

  [1] compiler: a GCC C++ compiler must exist - it FAILS, never skips;
  [2] compiles the model header ALONE with the FB-A header (standalone proof)
      under g++ -std=gnu++17 and -std=gnu++20, -fsyntax-only -Wall -Wextra
      -Werror, included twice (#pragma once);
  [3] compiles the version-pin header and the EspNvs adapter against stub
      ESPHome / ESP-IDF headers that declare exactly the real signatures
      (the real headers are proven by the native CI compile and by
      registry/tests/check_fbb_esphome_source_facts.py), and runs the
      version-pin NEGATIVE controls (2026.9.0, 2026.8.1, IDF 5.6.0 / 5.5.4 fail);
  [4] compile-time negative controls: a third write_one_ target, a flipped
      FBW golden vector, a zero-valued success enum, flipped witness /
      compose golden cases, a mutated per-key outcome table, B8 after B9;
  [5] builds and RUNS a fault-injection driver: the real commit_transition_t
      against a C++ fake NVS with the exact semantics of
      registry/tests/_fbb_harness.py's DirectNvs, over every
      (error class x readback class x health) cell for both keys, every
      power-cut point of every architecture section 5 transaction and every
      section 5.5 fault row (F1-F13, F-H1, F-H2), refusals and invalid
      transitions. Every result line must equal the Python mirror's, byte
      for byte, and every line is checked against the architecture tables;
  [6] mutation kills: each header mutant must be rejected - by a
      static_assert or by a fault-driver mismatch.

Writes only to a temporary directory; no hardware, no network.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE_DIR = ROOT / "firmware" / "include"
MODEL_PATH = INCLUDE_DIR / "ecco_fallback_durable_model.h"
ADAPTER_PATH = INCLUDE_DIR / "ecco_fallback_durable.h"
PINS_PATH = INCLUDE_DIR / "ecco_fallback_version_pins.h"
FBA_PATH = INCLUDE_DIR / "ecco_fallback_profile.h"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "registry"))
import _fbb_harness as H  # noqa: E402
import fallback_durable as fd  # noqa: E402
import fallback_profile as fp  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def find_compiler() -> str | None:
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    patterns = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*",
                                     "xtensa-esp-elf", "bin", "xtensa-esp32-elf-g++*"))
    home = Path.home()
    patterns += [str(home / ".esphome" / "**" / "xtensa-esp32-elf-g++*"),
                 str(home / ".platformio" / "packages" / "toolchain-xtensa*" / "bin" / "xtensa-esp32-elf-g++*")]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[-1]
    return None


STRICT = ["-Wall", "-Wextra", "-Werror"]


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900, **kw)


# ===========================================================================
print("[1] compiler")
# ===========================================================================
for p in (MODEL_PATH, ADAPTER_PATH, PINS_PATH, FBA_PATH):
    if not p.is_file():
        print(f"  FAIL  required file not found: {p}")
        sys.exit(1)
CXX = find_compiler()
check("a C++ compiler is available (the host compile never silently skips)", CXX is not None, "set ECCO_CXX or install g++")
if CXX is None:
    print("\nFAILED: no C++ compiler found")
    sys.exit(1)
version = run([CXX, "--version"]).stdout.splitlines()[:1]
print(f"  info  compiler: {CXX}")
print(f"  info  version:  {version[0] if version else '?'}")
macros = run([CXX, "-x", "c++", "-dM", "-E", os.devnull]).stdout
check("the compiler is GCC (the FB-A constexpr digests rely on GCC's constexpr limits)",
      "#define __GNUC__ " in macros and "__clang__" not in macros)
IS_HOST_GCC = "xtensa" not in Path(CXX).name

MODEL = MODEL_PATH.read_text(encoding="utf-8")
ADAPTER = ADAPTER_PATH.read_text(encoding="utf-8")
PINS = PINS_PATH.read_text(encoding="utf-8")
FBA = FBA_PATH.read_text(encoding="utf-8")

TMP = Path(tempfile.mkdtemp(prefix="ecco_fbb0_"))
INC = TMP / "include"
INC.mkdir()


def stage(model: str = MODEL, adapter: str = ADAPTER, pins: str = PINS, inc: Path = INC) -> Path:
    inc.mkdir(parents=True, exist_ok=True)
    (inc / "ecco_fallback_profile.h").write_text(FBA, encoding="utf-8")
    (inc / "ecco_fallback_durable_model.h").write_text(model, encoding="utf-8")
    (inc / "ecco_fallback_durable.h").write_text(adapter, encoding="utf-8")
    (inc / "ecco_fallback_version_pins.h").write_text(pins, encoding="utf-8")
    return inc


def compile_tu(source: str, std: str = "gnu++17", extra=(), incs=(), syntax_only: bool = True,
               out: Path | None = None, inc: Path = INC) -> subprocess.CompletedProcess:
    tu = inc.parent / f"tu_{inc.name}_{abs(hash(source)) % 10**9}.cpp"
    tu.write_text(source, encoding="utf-8")
    cmd = [CXX, f"-std={std}", *STRICT, *extra, "-I", str(inc)]
    for i in incs:
        cmd += ["-I", str(i)]
    cmd += ["-fsyntax-only", str(tu)] if syntax_only else [str(tu), "-o", str(out)]
    return run(cmd)


def parallel(fn, items) -> list:
    """Mutant compiles are independent (each in its own include directory): run them concurrently."""
    with ThreadPoolExecutor(max_workers=max(1, min(8, os.cpu_count() or 1))) as pool:
        return list(pool.map(fn, items))


TWICE = '#include "ecco_fallback_durable_model.h"\n#include "ecco_fallback_durable_model.h"\nint main() { return 0; }\n'

# ===========================================================================
print("[2] model header: standalone, gnu++17 / gnu++20, -Wall -Wextra -Werror")
# ===========================================================================
stage()
alone = TMP / "alone"
alone.mkdir()
(alone / "ecco_fallback_profile.h").write_text(FBA, encoding="utf-8")
(alone / "ecco_fallback_durable_model.h").write_text(MODEL, encoding="utf-8")
check("the isolated include directory holds ONLY the FB-A and model headers",
      sorted(p.name for p in alone.iterdir()) == ["ecco_fallback_durable_model.h", "ecco_fallback_profile.h"])
for std in ("gnu++17", "gnu++20"):
    tu = TMP / f"alone_{std}.cpp"
    tu.write_text(TWICE, encoding="utf-8")
    r = run([CXX, f"-std={std}", "-fsyntax-only", *STRICT, "-I", str(alone), str(tu)])
    check(f"model header compiles alone under -std={std} {' '.join(STRICT)} (included twice) - every static_assert "
          "holds (FBW layout + 4 golden vectors, witness / compose golden cases, outcome table, latch transitions)",
          r.returncode == 0, (r.stderr or r.stdout)[-2500:])

# ===========================================================================
print("[3] version pins + EspNvs adapter against stub ESPHome / ESP-IDF declarations")
# ===========================================================================
STUB = TMP / "stub"
(STUB / "esphome" / "core").mkdir(parents=True)


def write_stubs(esphome_version=(2026, 8, 2), idf_version=(5, 5, 5)) -> None:
    (STUB / "esphome" / "core" / "macros.h").write_text(
        "#pragma once\n#define VERSION_CODE(major, minor, patch) ((major) << 16 | (minor) << 8 | (patch))\n", encoding="utf-8")
    (STUB / "esphome" / "core" / "version.h").write_text(
        '#pragma once\n#include "esphome/core/macros.h"\n#define ESPHOME_VERSION "stub"\n'
        f"#define ESPHOME_VERSION_CODE VERSION_CODE({esphome_version[0]}, {esphome_version[1]}, {esphome_version[2]})\n",
        encoding="utf-8")
    (STUB / "esp_idf_version.h").write_text(
        f"#pragma once\n#define ESP_IDF_VERSION_MAJOR {idf_version[0]}\n#define ESP_IDF_VERSION_MINOR {idf_version[1]}\n"
        f"#define ESP_IDF_VERSION_PATCH {idf_version[2]}\n"
        "#define ESP_IDF_VERSION_VAL(major, minor, patch) ((major << 16) | (minor << 8) | (patch))\n"
        "#define ESP_IDF_VERSION ESP_IDF_VERSION_VAL(ESP_IDF_VERSION_MAJOR, ESP_IDF_VERSION_MINOR, ESP_IDF_VERSION_PATCH)\n",
        encoding="utf-8")
    # Declarations copied from ESP-IDF 5.5.5 nvs.h / esp_err.h (values and signatures only).
    (STUB / "nvs.h").write_text(
        "#pragma once\n#include <stddef.h>\n#include <stdint.h>\ntypedef int esp_err_t;\n#define ESP_OK 0\n"
        "#define ESP_ERR_NVS_BASE 0x1100\n#define ESP_ERR_NVS_NOT_INITIALIZED (ESP_ERR_NVS_BASE + 0x01)\n"
        "#define ESP_ERR_NVS_NOT_FOUND (ESP_ERR_NVS_BASE + 0x02)\n#define ESP_ERR_NVS_READ_ONLY (ESP_ERR_NVS_BASE + 0x04)\n"
        "#define ESP_ERR_NVS_INVALID_HANDLE (ESP_ERR_NVS_BASE + 0x07)\ntypedef uint32_t nvs_handle_t;\n"
        "typedef struct { size_t used_entries; size_t free_entries; size_t available_entries; size_t total_entries;"
        " size_t namespace_count; } nvs_stats_t;\n"
        'extern "C" esp_err_t nvs_set_blob(nvs_handle_t handle, const char *key, const void *value, size_t length);\n'
        'extern "C" esp_err_t nvs_get_blob(nvs_handle_t handle, const char *key, void *out_value, size_t *length);\n'
        'extern "C" esp_err_t nvs_get_stats(const char *part_name, nvs_stats_t *nvs_stats);\n', encoding="utf-8")
    # Declarations copied from ESPHome 2026.8.2 (preferences.h, helpers.h, hal.h).
    (STUB / "esphome" / "core" / "helpers.h").write_text(
        "#pragma once\n#include <cstddef>\n#include <cstdint>\n#include <span>\nnamespace esphome {\n"
        "static constexpr size_t UINT32_MAX_STR_SIZE = 11;\n"
        "size_t uint32_to_str(std::span<char, UINT32_MAX_STR_SIZE> buf, uint32_t val);\n}\n", encoding="utf-8")
    (STUB / "esphome" / "core" / "hal.h").write_text(
        "#pragma once\n#include <cstdint>\nnamespace esphome {\nuint32_t micros();\n}\n", encoding="utf-8")
    (STUB / "esphome" / "core" / "preferences.h").write_text(
        "#pragma once\n#include <cstdint>\nnamespace esphome {\nnamespace esp32 {\nclass ESP32Preferences {\n public:\n"
        "  uint32_t nvs_handle;\n};\n}\nusing Preferences = esp32::ESP32Preferences;\nusing ESPPreferences = Preferences;\n"
        "extern ESPPreferences *global_preferences;\n}\n", encoding="utf-8")


write_stubs()
ADAPTER_TU = '#include "ecco_fallback_durable.h"\n#include "ecco_fallback_durable.h"\nint main() { return 0; }\n'
INSTANTIATE_TU = r'''#include "ecco_fallback_durable.h"
using namespace ecco_fbdurable;
TxnOutcome probe_commit(const FailbackProvisionV1 &wn, const FailbackProvisionV1 &wp, const ecco_fallback::FallbackProfileV1 &pn,
                        const ecco_fallback::FallbackProfileV1 &pp, TxnResult &r) {
  EspNvs nvs;
  return commit_transition_t(nvs, wn, wp, PriorDesc{0, 48}, pn, pp, PriorDesc{0, 96}, r);
}
PairRead probe_pair(ReadLatch &l) { EspNvs nvs; return read_pair_t(nvs, l); }
uint8_t probe_fbs(ecco_fallback::FailbackStateV1 &s, ReadDiag &d) { EspNvs nvs; return read_direct_t(nvs, FAILBACK_STATE_KEY, s, d); }
bool probe_health() { return nvs_healthy(); }
int main() { return 0; }
'''
r = compile_tu(ADAPTER_TU, "gnu++20", incs=[STUB])
check("the EspNvs adapter + version pins compile (gnu++20, ESPHome's language mode, -Werror) against the stub "
      "declarations; its IDF error-code / nvs_handle_t / nvs_handle / key-buffer static_asserts hold",
      r.returncode == 0, (r.stderr or r.stdout)[-2500:])
r = compile_tu(INSTANTIATE_TU, "gnu++20", incs=[STUB])
check("every template instantiates with the PRODUCTION EspNvs policy (commit_transition_t, read_pair_t, "
      "read_direct_t<FailbackStateV1>, nvs_healthy) - host type-check only, nothing links or runs",
      r.returncode == 0, (r.stderr or r.stdout)[-2500:])
for esph, idf, ok in (((2026, 8, 2), (5, 5, 5), True), ((2026, 8, 9), (5, 5, 9), True), ((2026, 9, 0), (5, 5, 5), False),
                      ((2026, 8, 1), (5, 5, 5), False), ((2025, 12, 0), (5, 5, 5), False),
                      ((2026, 8, 2), (5, 6, 0), False), ((2026, 8, 2), (5, 5, 4), False), ((2026, 8, 2), (6, 0, 0), False)):
    write_stubs(esph, idf)
    r = compile_tu(ADAPTER_TU, "gnu++20", incs=[STUB])
    label = f"ESPHome {'.'.join(map(str, esph))} / IDF {'.'.join(map(str, idf))}"
    if ok:
        check(f"version pins ACCEPT {label}", r.returncode == 0, r.stderr[-1200:])
    else:
        check(f"version pins REJECT {label} (negative control)", r.returncode != 0 and "ecco_fbdurable" in r.stderr
              and ("ESPHome preference facts" in r.stderr or "ESP-IDF NVS facts" in r.stderr), r.stderr[-800:])
write_stubs()
PINS_ONLY = TMP / "pins_only"
PINS_ONLY.mkdir()
(PINS_ONLY / "ecco_fallback_version_pins.h").write_text(PINS, encoding="utf-8")
tu = TMP / "pins_only.cpp"
tu.write_text('#include "ecco_fallback_version_pins.h"\nint main() { return 0; }\n', encoding="utf-8")
r = run([CXX, "-std=gnu++17", "-fsyntax-only", *STRICT, "-I", str(PINS_ONLY), "-I", str(STUB), str(tu)])
check("the version-pin header is standalone: it needs only the two version headers", r.returncode == 0, r.stderr[-800:])

# ===========================================================================
print("[4] compile-time negative controls (the static_asserts are really evaluated)")
# ===========================================================================
THIRD = '#include "ecco_fallback_durable_model.h"\n' + r'''
struct N {
  uint32_t handle() const { return 1; }
  int32_t set_blob(uint32_t, const void *, size_t) { return 0; }
  int32_t get_blob(uint32_t, void *, size_t *) { return 0; }
  int32_t get_stats() const { return 0; }
  uint32_t now_us() const { return 0; }
};
int main() {
  N n; ecco_fallback::FailbackStateV1 s{}, rb{}; ecco_fbdurable::KeyReport rep{};
  (void) ecco_fbdurable::write_one_<ecco_fallback::FailbackStateV1, ecco_fbdurable::FAILBACK_STATE_KEY>(n, s, s, ecco_fbdurable::PriorDesc{1, 0}, rb, rep);
  return 0;
}
'''
stage()
r = compile_tu(THIRD)
check("a THIRD write_one_ target (FailbackStateV1 / FAILBACK_STATE_KEY) fails to compile (exclusivity pin X2)",
      r.returncode != 0 and "exclusivity pin X2" in r.stderr, r.stderr[-800:])
TWO_OK = THIRD.replace("ecco_fallback::FailbackStateV1 s{}, rb{};", "ecco_fbdurable::FailbackProvisionV1 s{}, rb{};") \
    .replace("<ecco_fallback::FailbackStateV1, ecco_fbdurable::FAILBACK_STATE_KEY>",
             "<ecco_fbdurable::FailbackProvisionV1, ecco_fbdurable::FAILBACK_PROVISION_KEY>")
r = compile_tu(TWO_OK)
check("...while an allowed target (FailbackProvisionV1 / FAILBACK_PROVISION_KEY) compiles (the control is specific)",
      r.returncode == 0, r.stderr[-800:])
WRONG_KEY = TWO_OK.replace("ecco_fbdurable::FAILBACK_PROVISION_KEY>", "ecco_fbdurable::FALLBACK_PROFILE_KEY>")
r = compile_tu(WRONG_KEY)
check("...and a crossed pair (FBW record under the FBP key) is rejected", r.returncode != 0 and "exclusivity pin X2" in r.stderr)

HEADER_MUTANTS = (
    ("FBW golden vector W-FIRST flipped", "GOLDEN_PROVISION_FIRST.binding == 0xA8B8788B4C915BB6ULL",
     "GOLDEN_PROVISION_FIRST.binding == 0xA8B8788B4C915BB7ULL", "FBW golden vector W-FIRST"),
    ("FBW golden vector W-ZERO flipped", "== 0x1FDA24BEF28230CFULL", "== 0x1FDA24BEF28230CEULL", "FBW golden vector W-ZERO"),
    ("FBW golden vector W-FF flipped", "0x06E1F1CA2CBB0327ULL", "0x06E1F1CA2CBB0326ULL", "FBW golden vector W-FF"),
    ("FBW golden vector W-INV flipped", "0x9E8AEC8F7D7DF2D7ULL", "0x9E8AEC8F7D7DF2D6ULL", "FBW golden vector W-INV"),
    ("binding domain renamed", '"ECCO-FAILBACK-PROVISION-v1"', '"ECCO-FAILBACK-PROVISION-v2"', "FBW golden vector"),
    ("binding covers the binding field (bytes [0, 48))", "i < PROVISION_BOUND_BYTES", "i < PROVISION_SIZE", "FBW golden vector"),
    ("zero-valued success enum (KEY_COMMITTED = 0)", "KEY_UNKNOWN_REBOOT = 0,\n  KEY_COMMITTED = 1,",
     "KEY_UNKNOWN_REBOOT = 1,\n  KEY_COMMITTED = 0,", "KeyOutcome: 0 is UNKNOWN_REBOOT"),
    ("zero-valued success enum (TXN_COMMITTED = 0)", "TXN_UNKNOWN_REBOOT = 0,\n  TXN_COMMITTED = 1,",
     "TXN_UNKNOWN_REBOOT = 1,\n  TXN_COMMITTED = 0,", "TxnOutcome: 0 is UNKNOWN_REBOOT"),
    ("RB_INTENDED is the zero readback class", "RB_NOT_READ = 0,\n  RB_INTENDED = 1,", "RB_NOT_READ = 1,\n  RB_INTENDED = 0,",
     "ReadbackClass: 0 is 'not read'"),
    ("witness golden case flipped (flags accepted)",
     "{1, ecco_fallback::LOAD_OK, 38, 0x0102, 0xFF, 0x0000, 1, WIT_DEFECT_FLAGS, W_CORRUPT},",
     "{1, ecco_fallback::LOAD_OK, 38, 0x0102, 0xFF, 0x0000, 1, WIT_DEFECT_NONE, W_VALID},", "witness classifier golden cases"),
    ("compose golden case flipped (lagging witness writer-usable)",
     "{ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW6, 0, EPC_VALID, WHY_WIT_LAGGING, RULE_B8},",
     "{ecco_fallback::LOAD_OK, PV_GOLD7, ecco_fallback::LOAD_OK, WV_HW6, 0, EPC_VALID, WHY_NONE, RULE_B10},",
     "compose_profile_class golden cases"),
    ("outcome table: OK + any readback commits (ARCH A16 shape)", "(e == WERR_OK && r == RB_INTENDED) ? KEY_COMMITTED",
     "(e == WERR_OK) ? KEY_COMMITTED", "per-key outcome table"),
    ("outcome table: health gate after the write ignored", "return !healthy_after ? KEY_UNKNOWN_REBOOT",
     "return false ? KEY_UNKNOWN_REBOOT", "per-key outcome table"),
    ("raw TIMEOUT classified pre-write (MB23)", "(e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY ||",
     "(e == 0x107 || e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY ||", "write error classes"),
    ("NO_MEM classified pre-write (E03 8.3 mutant)", "(e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY ||",
     "(e == 0x101 || e == IDF_ERR_NVS_INVALID_HANDLE || e == IDF_ERR_NVS_READ_ONLY ||", "write error classes"),
    ("B8 moved after B9", "    if (p.generation > w.hw_generation)\n      return {c, WHY_WIT_LAGGING, RULE_B8};\n"
     "    if (w.hw_tag_key != FALLBACK_PROFILE_KEY || w.hw_record_schema != ecco_fallback::PROFILE_SCHEMA)\n"
     "      return {EPC_PROFILE_STALE, WHY_SUPERSEDED, RULE_B9};\n",
     "    if (w.hw_tag_key != FALLBACK_PROFILE_KEY || w.hw_record_schema != ecco_fallback::PROFILE_SCHEMA)\n"
     "      return {EPC_PROFILE_STALE, WHY_SUPERSEDED, RULE_B9};\n    if (p.generation > w.hw_generation)\n"
     "      return {c, WHY_WIT_LAGGING, RULE_B8};\n", "compose_profile_class golden cases"),
    ("B12 interrupted record usable (MB-B12)", "return {EPC_PROFILE_STALE, WHY_INTERRUPTED, RULE_B12};",
     "return {c, WHY_NONE, RULE_B12};", "compose_profile_class golden cases"),
    ("ABSENT FBP + VALID FBW -> NOT_CAPTURED (MB30)", "      return {EPC_PROFILE_LOST, WHY_NONE, RULE_B6};",
     "      return {EPC_NOT_CAPTURED, WHY_NONE, RULE_B6};", "compose_profile_class golden cases"),
    ("g < hw accepted (MB31)", "return {EPC_PROFILE_STALE, WHY_ROLLBACK, RULE_B13};", "return {c, WHY_NONE, RULE_B13};",
     "compose_profile_class golden cases"),
    ("B5 without hw == 1 (m7)", "w.last_op == PROV_OP_SAVE && w.hw_generation == 1)", "w.last_op == PROV_OP_SAVE)",
     "compose_profile_class golden cases"),
    ("writer-usable accepts a lagging witness (MB32)", "return cls == EPC_VALID && why == WHY_NONE; }",
     "return cls == EPC_VALID && (why == WHY_NONE || why == WHY_WIT_LAGGING); }", "only VALID && WHY_NONE is writer-usable"),
    ("generation base ignores seen_hw_gen (MB34)", "wc == W_VALID ? hw : 0u, seen_hw_gen);", "wc == W_VALID ? hw : 0u, 0u);",
     "SAVE generation base"),
    ("same-boot vanish not an anomaly", "    if (s.present_seen & key_bit)\n      out.read_anomaly",
     "    if (false)\n      out.read_anomaly", "per-boot read latch"),
    ("witness PRIOR rule dropped", "if (w.prior_generation >= w.hw_generation || (w.prior_generation == 0) != (w.prior_binding == 0))",
     "if (false)", "witness classifier golden cases"),
)


def compile_mutant(item):
    index, (_label, old, new, _message) = item
    mutated = MODEL.replace(old, new, 1)
    return MODEL.count(old) == 1 and mutated != MODEL, compile_tu(TWICE, inc=stage(model=mutated, inc=TMP / f"hm{index}"))


for (label, _old, _new, message), (applies, r) in zip(HEADER_MUTANTS, parallel(compile_mutant, enumerate(HEADER_MUTANTS))):
    check(f"compile mutant [{label}] is rejected by its static_assert",
          applies and r.returncode != 0 and "static assertion failed" in r.stderr and message in r.stderr,
          ("pattern does not apply exactly once; " if not applies else "") + (r.stderr or "compiled")[-600:])
stage()

# ===========================================================================
print("[5] fault-injection driver: real commit_transition_t vs the Python mirror, every cell / cut / fault row")
# ===========================================================================
DRIVER = r'''
#include "ecco_fallback_durable_model.h"
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

using namespace ecco_fbdurable;
using ecco_fallback::FallbackProfileV1;

struct PowerCut {};
enum { VIS_NEW, VIS_OLD, VIS_ABSENT, VIS_CRCBAD, VIS_NOCHUNK_OLD, VIS_OTHER, VIS_WRONGSIZE, VIS_UNAVAILABLE };
enum { BOOT_ASIS, BOOT_NEW, BOOT_OLD, BOOT_ABSENT };
struct PriorSpec { int kind; const char *hex; uint32_t len; };
struct FaultSpec { char key; int32_t result; int visible; int boot; int healthy_after; const char *other_hex; uint32_t wrong_len; };
struct Scenario {
  const char *name; PriorSpec prior_p; PriorSpec prior_w; const char *new_p_hex; const char *new_w_hex;
  uint32_t handle; int health_before; int latch; int n_faults; FaultSpec faults[2]; int cut; int boot_absent; int boot_wipe;
  long long handle_at_commit;
};
#include "scenarios.inc"

static std::vector<uint8_t> unhex(const char *h) {
  std::vector<uint8_t> out;
  for (size_t i = 0; h[i] && h[i + 1]; i += 2) {
    unsigned v = 0;
    std::sscanf(h + i, "%2x", &v);
    out.push_back((uint8_t) v);
  }
  return out;
}
static uint64_t fnv64(const uint8_t *d, size_t n) {
  uint64_t h = ecco_fallback::FNV1A64_OFFSET_BASIS;
  for (size_t i = 0; i < n; i++) h = ecco_fallback::fnv1a64_step(h, d[i]);
  return h;
}
struct Blob { std::vector<uint8_t> data; bool crc_ok = true; bool chunk_present = true; };
struct Pending { int boot; bool had_old; Blob old; Blob nw; };

struct FakeNvs {
  std::map<uint32_t, Blob> blobs;
  uint32_t handle_value = 1;
  bool healthy = true;
  bool unavailable = false;
  std::map<uint32_t, std::vector<FaultSpec>> faults;
  std::map<uint32_t, Pending> pending;
  mutable int events = 0;
  int cut_at = -1;
  mutable uint32_t clock_us = 0;
  int sets = 0;

  void event(bool after) const {
    if (cut_at >= 0 && 2 * events + (after ? 1 : 0) == cut_at) throw PowerCut{};
  }
  uint32_t handle() const { return handle_value; }
  uint32_t now_us() const { clock_us += 7; return clock_us; }
  int32_t get_stats() const {
    event(false);
    const int32_t r = healthy ? IDF_OK : 0x103;
    event(true);
    events++;
    return r;
  }
  int32_t get_blob(uint32_t key, void *out, size_t *len) {
    event(false);
    const int32_t r = get_(key, out, len);
    event(true);
    events++;
    return r;
  }
  int32_t get_(uint32_t key, void *out, size_t *len) {
    if (handle_value == 0) return IDF_ERR_NVS_INVALID_HANDLE;
    if (unavailable) return IDF_ERR_NVS_NOT_INITIALIZED;
    auto it = blobs.find(key);
    if (it == blobs.end()) return IDF_ERR_NVS_NOT_FOUND;
    Blob &b = it->second;
    if (out == nullptr) { *len = b.data.size(); return IDF_OK; }
    if (!b.chunk_present) { blobs.erase(it); return -1; }
    if (!b.crc_ok) { b.chunk_present = false; return IDF_ERR_NVS_NOT_FOUND; }
    if (*len < b.data.size()) { *len = b.data.size(); return 0x110C; }
    std::memcpy(out, b.data.data(), b.data.size());
    *len = b.data.size();
    return IDF_OK;
  }
  int32_t set_blob(uint32_t key, const void *data, size_t len) {
    event(false);
    const int32_t r = set_(key, data, len);
    sets++;  // the set happened: a cut AFTER it still counts it (as DirectNvs's op log does)
    event(true);
    events++;
    return r;
  }
  int32_t set_(uint32_t key, const void *data, size_t len) {
    if (handle_value == 0) return IDF_ERR_NVS_INVALID_HANDLE;
    FaultSpec f{0, IDF_OK, VIS_NEW, BOOT_ASIS, 1, "", 0};
    auto q = faults.find(key);
    if (q != faults.end() && !q->second.empty()) { f = q->second.front(); q->second.erase(q->second.begin()); }
    auto it = blobs.find(key);
    const bool had_old = it != blobs.end();
    Blob old = had_old ? it->second : Blob{};
    Blob nw;
    nw.data.assign((const uint8_t *) data, (const uint8_t *) data + len);
    switch (f.visible) {
      case VIS_NEW: blobs[key] = nw; break;
      case VIS_OLD: break;
      case VIS_ABSENT: blobs.erase(key); break;
      case VIS_CRCBAD: { Blob b = nw; b.crc_ok = false; blobs[key] = b; } break;
      case VIS_NOCHUNK_OLD:
        if (!had_old) blobs.erase(key);
        else { Blob b = old; b.chunk_present = false; blobs[key] = b; }
        break;
      case VIS_OTHER: { Blob b; b.data = unhex(f.other_hex); blobs[key] = b; } break;
      case VIS_WRONGSIZE: { Blob b; b.data.assign(f.wrong_len, 0); blobs[key] = b; } break;
      case VIS_UNAVAILABLE: blobs[key] = nw; unavailable = true; break;
    }
    if (!f.healthy_after) healthy = false;
    pending[key] = Pending{f.boot, had_old, old, nw};
    return f.result;
  }
  FakeNvs reboot(int absent_mask) const {
    FakeNvs n;
    n.blobs = blobs;
    for (const auto &kv : pending) {
      const uint32_t key = kv.first;
      const Pending &p = kv.second;
      if (p.boot == BOOT_NEW) n.blobs[key] = p.nw;
      else if (p.boot == BOOT_OLD) { if (p.had_old) n.blobs[key] = p.old; else n.blobs.erase(key); }
      else if (p.boot == BOOT_ABSENT) n.blobs.erase(key);
    }
    for (auto it = n.blobs.begin(); it != n.blobs.end();) {
      if (!it->second.chunk_present) it = n.blobs.erase(it); else ++it;
    }
    if (absent_mask & 1) n.blobs.erase(FALLBACK_PROFILE_KEY);
    if (absent_mask & 2) n.blobs.erase(FAILBACK_PROVISION_KEY);
    return n;
  }
  std::string state_of(uint32_t key) const {
    auto it = blobs.find(key);
    if (it == blobs.end()) return "ABS";
    const Blob &b = it->second;
    const char *tag = (b.crc_ok && b.chunk_present) ? "OK" : (b.chunk_present ? "CRCBAD" : "NOCHUNK");
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%s:%u:%016llX", tag, (unsigned) b.data.size(),
                  (unsigned long long) fnv64(b.data.data(), b.data.size()));
    return buf;
  }
};

static void install(FakeNvs &n, uint32_t key, const PriorSpec &p) {
  Blob b;
  if (p.kind == 0) return;
  if (p.kind == 2) b.data.assign(p.len, 0);
  else b.data = unhex(p.hex);
  if (p.kind == 3) b.crc_ok = false;
  if (p.kind == 4) b.chunk_present = false;
  n.blobs[key] = b;
}
template<class T> static T from_hex(const char *h) {
  T t{};
  std::vector<uint8_t> v = unhex(h);
  if (v.size() == sizeof(T)) std::memcpy(&t, v.data(), sizeof(T));
  return t;
}
template<class T> static uint64_t rec_hash(const T &t) {
  uint8_t b[sizeof(T)];
  std::memcpy(b, &t, sizeof(T));
  return fnv64(b, sizeof(T));
}
static void keyrep(char *out, size_t n, const KeyReport &k) {
  std::snprintf(out, n, "%u/%u/%d/%u/%u", (unsigned) k.outcome, (unsigned) k.rb_class, (int) k.err,
                (unsigned) k.healthy_after, (unsigned) k.rb_load);
}

int main() {
  for (const Scenario &s : SCENARIOS) {
    FakeNvs nvs;
    nvs.handle_value = s.handle;
    install(nvs, FALLBACK_PROFILE_KEY, s.prior_p);
    install(nvs, FAILBACK_PROVISION_KEY, s.prior_w);
    for (int i = 0; i < s.n_faults; i++)
      nvs.faults[s.faults[i].key == 'W' ? FAILBACK_PROVISION_KEY : FALLBACK_PROFILE_KEY].push_back(s.faults[i]);
    FallbackProfileV1 p_prior{};
    FailbackProvisionV1 w_prior{};
    ReadDiag dp{}, dw{};
    const uint8_t p_load = read_direct_t(nvs, FALLBACK_PROFILE_KEY, p_prior, dp);
    const uint8_t w_load = read_direct_t(nvs, FAILBACK_PROVISION_KEY, w_prior, dw);
    if (s.handle_at_commit >= 0) nvs.handle_value = (uint32_t) s.handle_at_commit;
    nvs.healthy = s.health_before != 0;
    s_write_latched = s.latch != 0;
    nvs.events = 0;
    nvs.cut_at = s.cut;
    const int sets_before = nvs.sets;
    const FallbackProfileV1 p_new = from_hex<FallbackProfileV1>(s.new_p_hex);
    const FailbackProvisionV1 w_new = from_hex<FailbackProvisionV1>(s.new_w_hex);
    TxnResult r{};
    TxnOutcome o = TXN_UNKNOWN_REBOOT;
    bool cut = false;
    try {
      o = commit_transition_t(nvs, w_new, w_prior, PriorDesc{w_load, dw.stored_len}, p_new, p_prior,
                              PriorDesc{p_load, dp.stored_len}, r);
    } catch (const PowerCut &) {
      cut = true;
    }
    FakeNvs boot = s.boot_wipe ? FakeNvs{} : nvs.reboot(s.boot_absent);
    ReadLatch bl{};
    const PairRead br = read_pair_t(boot, bl);
    std::printf("%s ld=%u/%u sets=%d fp=%s fw=%s boot=%u/%u/%u", s.name, (unsigned) p_load, (unsigned) w_load,
                nvs.sets - sets_before, nvs.state_of(FALLBACK_PROFILE_KEY).c_str(), nvs.state_of(FAILBACK_PROVISION_KEY).c_str(),
                (unsigned) br.e.cls, (unsigned) br.e.why, (unsigned) br.e.rule);
    if (cut) {
      std::printf(" txn=CUT latch=%d\n", s_write_latched ? 1 : 0);
      continue;
    }
    const MirrorRecords m = mirror_after(o, r, p_prior, p_load, w_prior, w_load);
    char wk[64], pk[64];
    keyrep(wk, sizeof(wk), r.w);
    keyrep(pk, sizeof(pk), r.p);
    std::printf(" txn=%u ref=%u w=%s p=%s latch=%d adv=%u mirror=%u:%016llX/%u:%016llX\n", (unsigned) o,
                (unsigned) r.refusal, wk, pk, s_write_latched ? 1 : 0, (unsigned) r.witness_advanced,
                (unsigned) m.p_load, (unsigned long long) rec_hash(m.p), (unsigned) m.w_load,
                (unsigned long long) rec_hash(m.w));
  }
  return 0;
}
'''


def P(**kw) -> dict:
    return fp.seal_profile(fp.blank_profile(**kw))


GOLD7 = P(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
          reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30],
          reg274_279=[1, 0, 1, 0, 0, 1], reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330],
          reg230=185, reg245=8000, reg247=1, reserved0=0, reserved1=0, binding=0)
check("the scenario builder's FB-A golden profile is FB-A's GOLDEN_PROFILE_V1 (binding 0xD852A4FA2DF7DBA3)",
      GOLD7["binding"] == 0xD852A4FA2DF7DBA3)


def gen(p: dict, g: int, **kw) -> dict:
    return fp.seal_profile(dict(p, generation=g, **kw))


def pb(p) -> bytes:
    return fp.pack_profile(p)


def wb(w) -> bytes:
    return fd.pack_provision(w)


K, S = fd.FALLBACK_PROFILE_KEY, 1
SAVE, INV, RC = fd.PROV_OP_SAVE, fd.PROV_OP_INVALIDATE, fd.PROV_OP_REPLACE_CORRUPT
W7 = fd.make_provision(7, GOLD7["binding"], 6, 0x6666, K, S, SAVE)          # consistent with GOLD7
G8 = gen(GOLD7, 8, captured_epoch=1790086400)                                # the recapture payload at g8
W8 = fd.make_provision(8, G8["binding"], 7, GOLD7["binding"], K, S, SAVE)    # its witness (prior = GOLD7)
G1 = gen(GOLD7, 1)
W1 = fd.make_provision(1, G1["binding"], 0, 0, K, S, SAVE)                   # first capture
WH12 = fd.make_provision(12, 0x1212, 11, 0x1111, K, S, SAVE)                 # after loss: hw 12
G13 = gen(GOLD7, 13)
W13 = fd.make_provision(13, G13["binding"], 0, 0, K, S, SAVE)
I8 = fd.invalidate_profile_cxx(GOLD7)
WI8 = fd.make_provision(8, I8["binding"], 7, GOLD7["binding"], K, S, INV)
BAD = dict(GOLD7, binding=(GOLD7["binding"] + 1) & 0xFFFFFFFFFFFFFFFF)       # CORRUPT (binding)
WRC13 = fd.make_provision(13, G13["binding"], 0, 0, K, S, RC)                # REPLACE CORRUPT after hw 12
W7RC = fd.make_provision(8, G8["binding"], 0, 0, K, S, RC)
OTHER_W = wb(fd.make_provision(99, 0x9999, 98, 0x9898, K, S, SAVE))
OTHER_P = pb(gen(GOLD7, 99))

OK_ = (H.PRIOR_OK,)
ABSENT_ = (H.PRIOR_ABSENT, b"")
E = fd  # error-code namespace
PRE = (E.IDF_ERR_NVS_INVALID_HANDLE, E.IDF_ERR_NVS_READ_ONLY, E.IDF_ERR_NVS_NOT_INITIALIZED)
OTHERS = (E.IDF_ERR_TIMEOUT, E.IDF_ERR_NVS_NOT_FOUND, E.IDF_ERR_NO_MEM, E.IDF_ERR_NVS_NOT_ENOUGH_SPACE,
          E.IDF_ERR_FLASH_OP_FAIL, E.IDF_FAIL, E.IDF_ERR_NVS_REMOVE_FAILED, E.IDF_ERR_NVS_INVALID_STATE,
          E.IDF_ERR_NVS_PAGE_FULL, E.IDF_ERR_INVALID_ARG)
CODES = (E.IDF_OK, *PRE, *OTHERS)
VIS_FOR_RB = ((H.VIS_NEW, fd.RB_INTENDED), (H.VIS_OLD, fd.RB_PRIOR), (H.VIS_OTHER, fd.RB_OTHER_BYTES),
              (H.VIS_ABSENT, fd.RB_ABSENT_UNEXPECTED), (H.VIS_WRONGSIZE, fd.RB_WRONG_SIZE),
              (H.VIS_CRCBAD, fd.RB_READ_ERROR), (H.VIS_UNAVAILABLE, fd.RB_UNAVAILABLE))

SCENARIOS: list[H.Scenario] = []
EXPECT: dict[str, dict] = {}


def add(s: H.Scenario, **expect) -> None:
    SCENARIOS.append(s)
    EXPECT[s.name] = expect


def fault(key, result=E.IDF_OK, visible=H.VIS_NEW, boot=H.BOOT_ASIS, healthy=True, size=48):
    other = OTHER_W if size == 48 else OTHER_P
    return (key, H.WriteFault(result, visible, boot, healthy, other if visible == H.VIS_OTHER else b"",
                              size + 4 if visible == H.VIS_WRONGSIZE else 0))


def recapture(name, faults=(), **kw) -> H.Scenario:
    return H.Scenario(name, (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8), faults=list(faults), **kw)


def expected_key(code: int, rb: int, healthy: bool) -> int:
    return fd.classify_key_outcome(fd.classify_write_err(code), rb, healthy)


# (A) every (error class x readback class x health) cell on the WITNESS key (first write)
for code in CODES:
    for vis, rb in VIS_FOR_RB:
        for healthy in (True, False):
            n = f"cellW_{code:x}_{vis}_{int(healthy)}".replace("-", "m")
            add(recapture(n, [fault("W", code, vis, healthy=healthy)]), w_rb=rb, w_out=expected_key(code, rb, healthy))
# RB_PRIOR from an ABSENT prior (first capture): pre-write -> NOT_COMMITTED; OK -> UNKNOWN
for code in (E.IDF_OK, *PRE, E.IDF_ERR_TIMEOUT):
    for healthy in (True, False):
        s = H.Scenario(f"cellW_first_{code:x}_ABSENT_{int(healthy)}", ABSENT_, ABSENT_, pb(G1), wb(W1),
                       faults=[fault("W", code, H.VIS_ABSENT, healthy=healthy)])
        add(s, w_rb=fd.RB_PRIOR, w_out=expected_key(code, fd.RB_PRIOR, healthy))
# (B) every cell on the PROFILE key (second write, witness COMMITTED)
for code in CODES:
    for vis, rb in VIS_FOR_RB:
        for healthy in (True, False):
            n = f"cellP_{code:x}_{vis}_{int(healthy)}".replace("-", "m")
            add(recapture(n, [fault("W"), fault("P", code, vis, healthy=healthy, size=96)]), w_out=fd.KEY_COMMITTED,
                p_rb=rb, p_out=expected_key(code, rb, healthy))
for code in (E.IDF_OK, *PRE, E.IDF_ERR_TIMEOUT):
    s = H.Scenario(f"cellP_first_{code:x}_ABSENT", ABSENT_, ABSENT_, pb(G1), wb(W1),
                   faults=[fault("W"), fault("P", code, H.VIS_ABSENT, size=96)])
    add(s, w_out=fd.KEY_COMMITTED, p_rb=fd.RB_PRIOR, p_out=expected_key(code, fd.RB_PRIOR, True))

# (C) power cut at every event of the section 5 transactions -> next-boot class
# Events of a full two-key transaction: 0 stats, 1 set W, 2 probe W, 3 read W, 4 stats, 5 set P, 6 probe P,
# 7 read P, 8 stats. Cut point 2n = before event n, 2n+1 = after it. The FBW index is WRITTEN once event 1
# completed (point 3); the FBP index once event 5 completed (point 11).
TXNS = {
    # name: (prior_p, prior_w, new_p, new_w, (before-FBW class/why), (FBW-only class/why), (both class/why))
    "save_recapture": ((H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), G8, W8,
                       (fd.EPC_VALID, fd.WHY_NONE), (fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED), (fd.EPC_VALID, fd.WHY_NONE)),
    "save_first": (ABSENT_, ABSENT_, G1, W1, (fd.EPC_NOT_CAPTURED, fd.WHY_NONE),
                   (fd.EPC_PROFILE_LOST, fd.WHY_FIRST_SAVE_UNCONFIRMED), (fd.EPC_VALID, fd.WHY_NONE)),
    "save_after_loss": (ABSENT_, (H.PRIOR_OK, wb(WH12)), G13, W13, (fd.EPC_PROFILE_LOST, fd.WHY_NONE),
                        (fd.EPC_PROFILE_LOST, fd.WHY_NONE), (fd.EPC_VALID, fd.WHY_NONE)),
    "invalidate": ((H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), I8, WI8, (fd.EPC_VALID, fd.WHY_NONE),
                   (fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED), (fd.EPC_INVALIDATED, fd.WHY_NONE)),
    "replace_corrupt": ((H.PRIOR_OK, pb(BAD)), (H.PRIOR_OK, wb(WH12)), G13, WRC13, (fd.EPC_CORRUPT, fd.WHY_NONE),
                        (fd.EPC_CORRUPT, fd.WHY_NONE), (fd.EPC_VALID, fd.WHY_NONE)),
    "replace_wrong_size": ((H.PRIOR_WS, 40), (H.PRIOR_OK, wb(WH12)), G13, WRC13, (fd.EPC_CORRUPT, fd.WHY_NONE),
                           (fd.EPC_CORRUPT, fd.WHY_NONE), (fd.EPC_VALID, fd.WHY_NONE)),
}
for tname, (pp, pw, np_, nw, before, middle, after) in TXNS.items():
    for cut in range(0, 18):
        expect_cls = before if cut <= 2 else (middle if cut <= 10 else after)
        add(H.Scenario(f"cut_{tname}_{cut}", pp, pw, pb(np_), wb(nw), cut=cut), cut=True, boot=expect_cls)
    add(H.Scenario(f"cut_{tname}_none", pp, pw, pb(np_), wb(nw)), txn=fd.TXN_COMMITTED, boot=after)

# (D) architecture 5.5 fault rows
add(recapture("F1_prewrite_readback_prior", [fault("W", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD)]),
    txn=fd.TXN_NOT_COMMITTED, latch=0, sets=1, boot=(fd.EPC_VALID, fd.WHY_NONE))
for code in (E.IDF_ERR_TIMEOUT, E.IDF_ERR_NVS_NOT_FOUND, E.IDF_ERR_NO_MEM, E.IDF_ERR_NVS_NOT_ENOUGH_SPACE):
    add(recapture(f"F2_{code:x}_old", [fault("W", code, H.VIS_OLD, H.BOOT_OLD)]), txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=1,
        boot=(fd.EPC_VALID, fd.WHY_NONE))
    add(recapture(f"F2_{code:x}_new", [fault("W", code, H.VIS_OLD, H.BOOT_NEW)]), txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=1,
        boot=(fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED))
    add(recapture(f"F2_{code:x}_gone", [fault("W", code, H.VIS_ABSENT, H.BOOT_ABSENT)]), txn=fd.TXN_UNKNOWN_REBOOT, latch=1,
        sets=1, boot=(fd.EPC_VALID, fd.WHY_WIT_MISSING))
add(recapture("F3_ok_other_bytes", [fault("W", E.IDF_OK, H.VIS_OTHER)]), txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=1)
add(recapture("F3_ok_other_boot_absent", [fault("W", E.IDF_OK, H.VIS_OTHER, H.BOOT_ABSENT)]), txn=fd.TXN_UNKNOWN_REBOOT,
    latch=1, boot=(fd.EPC_VALID, fd.WHY_WIT_MISSING))
add(recapture("F4_fbw_ok_fbp_prewrite", [fault("W"), fault("P", E.IDF_ERR_NVS_INVALID_HANDLE, H.VIS_OLD, size=96)]),
    txn=fd.TXN_NOT_COMMITTED, adv=1, latch=0, sets=2, boot=(fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED))
# F4 over a WRONG_SIZE prior (REPLACE CORRUPT): the readback of the untouched 40-byte blob is RB_PRIOR because its
# stored length equals the prior's - the pre-write outcome is still provably NOT_COMMITTED.
add(H.Scenario("F4b_replace_wrong_size_fbp_prewrite", (H.PRIOR_WS, 40), (H.PRIOR_OK, wb(WH12)), pb(G13), wb(WRC13),
               faults=[fault("W"), fault("P", E.IDF_ERR_NVS_READ_ONLY, H.VIS_OLD, size=96)]),
    txn=fd.TXN_NOT_COMMITTED, adv=1, latch=0, sets=2, p_rb=fd.RB_PRIOR, p_out=fd.KEY_NOT_COMMITTED)
for boot, cls in ((H.BOOT_ASIS, (fd.EPC_VALID, fd.WHY_NONE)), (H.BOOT_OLD, (fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED)),
                  (H.BOOT_ABSENT, (fd.EPC_PROFILE_LOST, fd.WHY_NONE))):
    add(recapture(f"F5_readback_intended_{boot}", [fault("W"), fault("P", E.IDF_ERR_TIMEOUT, H.VIS_NEW, boot, size=96)]),
        txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=2, boot=cls)
for boot, cls in ((H.BOOT_NEW, (fd.EPC_VALID, fd.WHY_NONE)), (H.BOOT_ASIS, (fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED))):
    add(recapture(f"F6_lands_later_{boot}", [fault("W"), fault("P", E.IDF_ERR_TIMEOUT, H.VIS_OLD, boot, size=96)]),
        txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=2, boot=cls)
add(recapture("F7_n9_old_chunk_erased", [fault("W"), fault("P", E.IDF_ERR_NO_MEM, H.VIS_NOCHUNK_OLD, size=96)]),
    txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=2, p_rb=fd.RB_READ_ERROR, boot=(fd.EPC_PROFILE_LOST, fd.WHY_NONE))
add(recapture("F8_fresh_misprogram", [fault("W"), fault("P", E.IDF_OK, H.VIS_CRCBAD, size=96)]),
    txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=2, p_rb=fd.RB_READ_ERROR, boot=(fd.EPC_PROFILE_LOST, fd.WHY_NONE))
for boot, cls in ((H.BOOT_ASIS, (fd.EPC_VALID, fd.WHY_NONE)), (H.BOOT_OLD, (fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED)),
                  (H.BOOT_ABSENT, (fd.EPC_PROFILE_LOST, fd.WHY_NONE))):
    add(recapture(f"F9_invisible_state_bit_{boot}", [fault("W"), fault("P", E.IDF_OK, H.VIS_NEW, boot, size=96)]),
        txn=fd.TXN_COMMITTED, latch=0, sets=2, boot=cls)
add(H.Scenario("F10_partition_wipe", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8), boot_wipe=True),
    txn=fd.TXN_COMMITTED, boot=(fd.EPC_NOT_CAPTURED, fd.WHY_NONE))
add(H.Scenario("F11_dedup_erase_fbp", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8),
               boot_absent=(fd.FALLBACK_PROFILE_KEY,)), txn=fd.TXN_COMMITTED, boot=(fd.EPC_PROFILE_LOST, fd.WHY_NONE))
add(H.Scenario("F11_dedup_erase_fbw", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8),
               boot_absent=(fd.FAILBACK_PROVISION_KEY,)), txn=fd.TXN_COMMITTED, boot=(fd.EPC_VALID, fd.WHY_WIT_MISSING))
add(H.Scenario("F12_handle_zero", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8), handle=0),
    txn=fd.TXN_REFUSED_LATCHED, sets=0, ld=(fp.LOAD_STORAGE_UNAVAILABLE, fp.LOAD_STORAGE_UNAVAILABLE))
add(H.Scenario("F12b_handle_zero_at_commit", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8),
               handle_at_commit=0),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_STORAGE_UNAVAILABLE, sets=0, latch=0, boot=(fd.EPC_VALID, fd.WHY_NONE))
add(recapture("F13_latched_second_save", latch=True), txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_LATCHED, sets=0, latch=1)
add(recapture("FH1_invalid_page_before_commit", health_before=False), txn=fd.TXN_REFUSED_LATCHED,
    ref=fd.REFUSAL_STORAGE_UNHEALTHY, sets=0, latch=0, boot=(fd.EPC_VALID, fd.WHY_NONE))
add(recapture("FH2_invalid_page_between_writes", [fault("W", healthy=False)]), txn=fd.TXN_UNKNOWN_REBOOT, latch=1, sets=1,
    w_out=fd.KEY_UNKNOWN_REBOOT, boot=(fd.EPC_PROFILE_STALE, fd.WHY_INTERRUPTED))
add(recapture("FH2b_invalid_page_after_fbp", [fault("W"), fault("P", healthy=False, size=96)]), txn=fd.TXN_UNKNOWN_REBOOT,
    latch=1, sets=2, p_out=fd.KEY_UNKNOWN_REBOOT)

# (E) refusals: invalid transitions write nothing
add(H.Scenario("refuse_unreadable_prior", (H.PRIOR_CRCBAD, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W8)),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_unreadable_witness", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_NOCHUNK, wb(W7)), pb(G8), wb(W8)),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_plain_save_over_corrupt", (H.PRIOR_OK, pb(BAD)), (H.PRIOR_OK, wb(WH12)), pb(G13), wb(W13)),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_replace_corrupt_over_valid", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8), wb(W7RC)),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_generation_not_advancing", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(gen(GOLD7, 7, captured_epoch=5)),
               wb(fd.make_provision(7, gen(GOLD7, 7, captured_epoch=5)["binding"], 7, GOLD7["binding"], K, S, SAVE))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_below_high_water", ABSENT_, (H.PRIOR_OK, wb(WH12)), pb(G8),
               wb(fd.make_provision(8, G8["binding"], 0, 0, K, S, SAVE))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_witness_names_other_record", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8),
               wb(fd.make_provision(8, 0x1234, 7, GOLD7["binding"], K, S, SAVE))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_wrong_prior_fields", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8),
               wb(fd.make_provision(8, G8["binding"], 0, 0, K, S, SAVE))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_invalidate_not_exact", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)),
               pb(fd.invalidate_profile_cxx(dict(GOLD7, reg245=1))), wb(WI8)),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_invalidate_stale", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W8)), pb(I8), wb(WI8)),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_invalidate_at_max", (H.PRIOR_OK, pb(gen(GOLD7, 0xFFFFFFFF))), ABSENT_,
               pb(fd.invalidate_profile_cxx(gen(GOLD7, 0xFFFFFFFF))),
               wb(fd.make_provision(1, 0x1, 0, 0, K, S, INV))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_save_at_generation_max", (H.PRIOR_OK, pb(gen(GOLD7, 0xFFFFFFFF))), ABSENT_,
               pb(gen(GOLD7, 1)), wb(fd.make_provision(1, gen(GOLD7, 1)["binding"], 0xFFFFFFFE, 1, K, S, SAVE))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
add(H.Scenario("refuse_foreign_tag_witness", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(W7)), pb(G8),
               wb(fd.make_provision(8, G8["binding"], 7, GOLD7["binding"], 0x12345678, S, SAVE))),
    txn=fd.TXN_REFUSED_LATCHED, ref=fd.REFUSAL_INVALID_TRANSITION, sets=0)
# accepted: SAVE over PROFILE_STALE / INVALIDATED / CORRUPT_DOMAIN / LOST with a corrupt witness (B7)
STALE_W = fd.make_provision(8, 0x8888, 7, GOLD7["binding"], K, S, SAVE)
G9 = gen(GOLD7, 9)
add(H.Scenario("accept_save_over_stale", (H.PRIOR_OK, pb(GOLD7)), (H.PRIOR_OK, wb(STALE_W)), pb(G9),
               wb(fd.make_provision(9, G9["binding"], 7, GOLD7["binding"], K, S, SAVE))), txn=fd.TXN_COMMITTED,
    boot=(fd.EPC_VALID, fd.WHY_NONE))
add(H.Scenario("accept_save_over_invalidated", (H.PRIOR_OK, pb(I8)), (H.PRIOR_OK, wb(WI8)), pb(G9),
               wb(fd.make_provision(9, G9["binding"], 8, I8["binding"], K, S, SAVE))), txn=fd.TXN_COMMITTED,
    boot=(fd.EPC_VALID, fd.WHY_NONE))
DOM7 = fp.seal_profile(dict(GOLD7, reg244=0))
add(H.Scenario("accept_save_over_corrupt_domain", (H.PRIOR_OK, pb(DOM7)), ABSENT_, pb(G8),
               wb(fd.make_provision(8, G8["binding"], 7, DOM7["binding"], K, S, SAVE))), txn=fd.TXN_COMMITTED,
    boot=(fd.EPC_VALID, fd.WHY_NONE))
add(H.Scenario("accept_save_lost_corrupt_witness", ABSENT_, (H.PRIOR_OK, wb(dict(WH12, binding=1))), pb(G1), wb(W1)),
    txn=fd.TXN_COMMITTED, boot=(fd.EPC_VALID, fd.WHY_NONE))
add(H.Scenario("accept_save_lagging_witness_repairs", (H.PRIOR_OK, pb(GOLD7)),
               (H.PRIOR_OK, wb(fd.make_provision(6, 0x5555, 5, 0x4444, K, S, SAVE))), pb(G8), wb(W8)),
    txn=fd.TXN_COMMITTED, boot=(fd.EPC_VALID, fd.WHY_NONE))

names = [s.name for s in SCENARIOS]
check(f"{len(SCENARIOS)} scenarios, unique names", len(names) == len(set(names)))
(TMP / "scenarios.inc").write_text(
    "static const Scenario SCENARIOS[] = {\n" + ",\n".join(H.scenario_cxx_initializer(s) for s in SCENARIOS) + "\n};\n",
    encoding="utf-8")


# Behaviour mutants must be killed by a static_assert or by a scenario mismatch - never merely by an
# unused-parameter / unused-variable warning that the mutation happens to leave behind.
MUTANT_RELAX = ["-Wno-unused-parameter", "-Wno-unused-variable", "-Wno-unused-but-set-variable",
                "-Wno-unused-but-set-parameter", "-Wno-unused-function"]


def build_and_run(model: str = MODEL, work: Path = TMP / "driver", extra=()):
    inc = stage(model=model, inc=work / "include")
    exe = work / "fbb_fault_driver"
    src = work / "fbb_fault_driver.cpp"
    src.write_text(DRIVER, encoding="utf-8")
    r = run([CXX, "-std=gnu++17", "-O1", *STRICT, *extra, "-I", str(inc), "-I", str(TMP), str(src), "-o", str(exe)])
    if r.returncode != 0:
        return None, r.stderr
    if not IS_HOST_GCC:
        return None, "cross compiler: cannot execute the driver on this host"
    rr = run([str(exe)])
    if rr.returncode != 0:
        return None, rr.stderr
    return rr.stdout.splitlines(), ""


PY_LINES = [H.run_scenario(s) for s in SCENARIOS]
lines, err = build_and_run()
check("the fault driver compiles (-std=gnu++17 -O1 -Wall -Wextra -Werror) and runs", lines is not None, err[-2500:])
lines = lines or []
mismatch = [(a, b) for a, b in zip(lines, PY_LINES) if a != b]
check(f"C++ commit_transition_t == Python mirror, byte for byte, on all {len(SCENARIOS)} scenarios "
      "(outcome, refusal, per-key outcome / readback class / err / health / readback load, latch, witness-advanced, "
      "flash state of both keys, set_blob count, RAM-mirror bytes, next-boot class)",
      len(lines) == len(PY_LINES) and not mismatch, f"{len(lines)} vs {len(PY_LINES)} lines; first mismatch {mismatch[:1]}")

FIELD = re.compile(r"(\w+)=(\S+)")


def parse(line: str) -> dict:
    out = dict(FIELD.findall(line))
    out["name"] = line.split(" ", 1)[0]
    return out


RESULTS = {parse(l)["name"]: parse(l) for l in PY_LINES}
bad: list[str] = []
for name, exp in EXPECT.items():
    got = RESULTS[name]
    b_cls, b_why, _b_rule = (int(x) for x in got["boot"].split("/"))
    if exp.get("cut") and got.get("txn") != "CUT":
        bad.append(f"{name}: expected a power cut")
    if "txn" in exp and got.get("txn") != str(exp["txn"]):
        bad.append(f"{name}: txn {got.get('txn')} != {exp['txn']}")
    if "ref" in exp and got.get("ref") != str(exp["ref"]):
        bad.append(f"{name}: ref {got.get('ref')} != {exp['ref']}")
    if "latch" in exp and got.get("latch") != str(exp["latch"]):
        bad.append(f"{name}: latch {got.get('latch')} != {exp['latch']}")
    if "adv" in exp and got.get("adv") != str(exp["adv"]):
        bad.append(f"{name}: adv {got.get('adv')} != {exp['adv']}")
    if "sets" in exp and got.get("sets") != str(exp["sets"]):
        bad.append(f"{name}: sets {got.get('sets')} != {exp['sets']}")
    if "ld" in exp and got.get("ld") != f"{exp['ld'][0]}/{exp['ld'][1]}":
        bad.append(f"{name}: ld {got.get('ld')} != {exp['ld']}")
    if "boot" in exp and (b_cls, b_why) != tuple(exp["boot"]):
        bad.append(f"{name}: next-boot {b_cls}/{b_why} != {exp['boot']}")
    for key in ("w", "p"):
        if f"{key}_out" in exp or f"{key}_rb" in exp:
            parts = got.get(key, "").split("/")
            if len(parts) < 2:
                bad.append(f"{name}: no {key} report")
                continue
            if f"{key}_out" in exp and parts[0] != str(exp[f"{key}_out"]):
                bad.append(f"{name}: {key} outcome {parts[0]} != {exp[f'{key}_out']}")
            if f"{key}_rb" in exp and parts[1] != str(exp[f"{key}_rb"]):
                bad.append(f"{name}: {key} readback {parts[1]} != {exp[f'{key}_rb']}")
check("every scenario matches the architecture tables (4.3 cells for both keys, 5.1-5.4 power-cut rows, 5.5 fault "
      "rows F1-F13 / F-H1 / F-H2, refusals)", not bad, "; ".join(bad[:6]))


def cells(key: str):
    return [RESULTS[n] for n in RESULTS if n.startswith(f"cell{key}_")]


def outcome_counts(key: str) -> dict:
    out: dict = {}
    for g in cells(key):
        o = g[key.lower()].split("/")[0]
        out[o] = out.get(o, 0) + 1
    return out


cw, cp = outcome_counts("W"), outcome_counts("P")
check(f"witness-key cells: {sum(cw.values())} cells, COMMITTED only for (OK, INTENDED, healthy), NOT_COMMITTED only for "
      f"(pre-write, PRIOR, healthy), every other cell UNKNOWN_REBOOT {cw}",
      cw.get(str(fd.KEY_COMMITTED)) == 1 and cw.get(str(fd.KEY_NOT_COMMITTED)) == 2 * len(PRE)
      and str(fd.KEY_NOT_ATTEMPTED) not in cw)
check(f"profile-key cells (witness COMMITTED first): same shape {cp}",
      cp.get(str(fd.KEY_COMMITTED)) == 1 and cp.get(str(fd.KEY_NOT_COMMITTED)) == 2 * len(PRE)
      and str(fd.KEY_NOT_ATTEMPTED) not in cp)
latch_ok = all(g["latch"] == ("1" if g["w"].split("/")[0] == str(fd.KEY_UNKNOWN_REBOOT)
                              or g["p"].split("/")[0] == str(fd.KEY_UNKNOWN_REBOOT) else "0")
               for g in RESULTS.values() if g.get("txn") not in ("CUT", str(fd.TXN_REFUSED_LATCHED)))
check("the write latch is set exactly when some key outcome was UNKNOWN_REBOOT (PO13)", latch_ok)
witness_first = all(not (g.get("w", "").startswith(f"{fd.KEY_UNKNOWN_REBOOT}/") or g.get("w", "").startswith(f"{fd.KEY_NOT_COMMITTED}/"))
                    or g.get("p", "").startswith(f"{fd.KEY_NOT_ATTEMPTED}/") for g in RESULTS.values() if "w" in g)
check("the profile is never written unless the witness COMMITTED in the same call (PO12, witness first)", witness_first)
unknown_keeps_prior = []
for s in SCENARIOS:
    g = RESULTS[s.name]
    if g.get("txn") in (str(fd.TXN_UNKNOWN_REBOOT), str(fd.TXN_REFUSED_LATCHED)):
        nvs0 = H.DirectNvs(handle=s.handle)
        H._install_prior(nvs0, fd.FALLBACK_PROFILE_KEY, s.prior_p)
        H._install_prior(nvs0, fd.FAILBACK_PROVISION_KEY, s.prior_w)
        lp, bp, _ = fd.read_direct(nvs0, fd.FALLBACK_PROFILE_KEY, 96)
        lw, bw, _ = fd.read_direct(nvs0, fd.FAILBACK_PROVISION_KEY, 48)
        if g["mirror"] != f"{lp}:{H.fnv64_hex(bp)}/{lw}:{H.fnv64_hex(bw)}":
            unknown_keeps_prior.append(s.name)
check("after UNKNOWN_REBOOT or a refusal the RAM mirror keeps the pre-transaction prior bytes (PO5)",
      not unknown_keeps_prior, str(unknown_keeps_prior[:4]))
committed_mirror = [n for n, g in RESULTS.items() if g.get("txn") == str(fd.TXN_COMMITTED)
                    and g["mirror"].split("/")[0].split(":")[1] != g["fp"].split(":")[-1]]
check("after COMMITTED the RAM mirror is the readback bytes, which equal the flash state (PO5)", not committed_mirror,
      str(committed_mirror[:4]))

# ===========================================================================
print("[6] mutation kills: every behavioural mutant of the model header is rejected")
# ===========================================================================
BEHAVIOUR_MUTANTS = (
    ("MB22 profile written before the witness",
     "  const KeyOutcome ow = write_one_<FailbackProvisionV1, FAILBACK_PROVISION_KEY>(nvs, w_new, w_prior, w_pd, r.w_rb, r.w);\n",
     "  (void) write_one_<FallbackProfileV1, FALLBACK_PROFILE_KEY>(nvs, p_new, p_prior, p_pd, r.p_rb, r.p);\n"
     "  const KeyOutcome ow = write_one_<FailbackProvisionV1, FAILBACK_PROVISION_KEY>(nvs, w_new, w_prior, w_pd, r.w_rb, r.w);\n"),
    ("FBP attempted after an UNKNOWN witness", "  if (ow != KEY_COMMITTED)\n    return TXN_UNKNOWN_REBOOT;",
     "  if (ow != KEY_COMMITTED && ow != KEY_UNKNOWN_REBOOT)\n    return TXN_UNKNOWN_REBOOT;"),
    ("MB25 health gate after the write skipped", "classify_key_outcome(classify_write_err(err), rc, healthy)",
     "classify_key_outcome(classify_write_err(err), rc, true)"),
    ("MB27 latch not checked", "  if (s_write_latched) {\n    r.refusal = REFUSAL_LATCHED;", "  if (false) {\n    r.refusal = REFUSAL_LATCHED;"),
    ("latch never set", "  if (o == KEY_UNKNOWN_REBOOT)\n    s_write_latched = true;", "  if (o == KEY_UNKNOWN_REBOOT)\n    (void) 0;"),
    ("A1(b) health gate before the commit dropped", "  if (!storage_healthy(nvs)) {\n    r.refusal = REFUSAL_STORAGE_UNHEALTHY;",
     "  if (false) {\n    r.refusal = REFUSAL_STORAGE_UNHEALTHY;"),
    ("pre-validation bypassed", "  if (!validate_transition(w_new, w_prior, w_pd, p_new, p_prior, p_pd)) {",
     "  if (false) {"),
    ("MB35 UNREADABLE prior overwritable", "  return cls == EPC_NOT_CAPTURED || cls == EPC_CORRUPT ||",
     "  return cls == EPC_UNREADABLE || cls == EPC_NOT_CAPTURED || cls == EPC_CORRUPT ||"),
    ("REPLACE CORRUPT phrase rule dropped (plain SAVE over CORRUPT)",
     "  if ((op == PROV_OP_REPLACE_CORRUPT) != (prior.cls == EPC_CORRUPT) && op != PROV_OP_INVALIDATE)\n    return false;\n", ""),
    ("MB29 CRC-erased data read taken as ABSENT (single-step read conflation)",
     "  if (e != IDF_OK || got != sizeof(T))\n    return ecco_fallback::LOAD_READ_ERROR;",
     "  if (e == IDF_ERR_NVS_NOT_FOUND)\n    return ecco_fallback::LOAD_ABSENT;\n  if (e != IDF_OK || got != sizeof(T))\n"
     "    return ecco_fallback::LOAD_READ_ERROR;"),
    ("witness-advanced flag lost", "    r.witness_advanced = 1;", "    (void) 0;"),
    ("ABSENT prior readback never RB_PRIOR", "(prior.load == ecco_fallback::LOAD_ABSENT ? RB_PRIOR : RB_ABSENT_UNEXPECTED)",
     "RB_ABSENT_UNEXPECTED"),
    ("MB26 mirror from the readbacks after UNKNOWN (instead of the prior)",
     "  return MirrorRecords{p_prior, w_prior, p_prior_load, w_prior_load};",
     "  return MirrorRecords{r.p_rb, r.w_rb, r.p.rb_load, r.w.rb_load};"),
    ("zero handle not refused", "  if (nvs.handle() == 0) {\n    r.refusal = REFUSAL_STORAGE_UNAVAILABLE;",
     "  if (false) {\n    r.refusal = REFUSAL_STORAGE_UNAVAILABLE;"),
    ("wrong-size readback compared by content not length",
     "((prior.load == ecco_fallback::LOAD_WRONG_SIZE && prior.stored_len == rb_len) ? RB_PRIOR : RB_WRONG_SIZE)",
     "RB_WRONG_SIZE"),
)


def run_behaviour_mutant(item):
    index, (_label, old, new) = item
    mutated = MODEL.replace(old, new, 1)
    if MODEL.count(old) != 1 or mutated == MODEL:
        return None, None, "pattern does not apply exactly once"
    mlines, merr = build_and_run(mutated, TMP / f"bm{index}", MUTANT_RELAX)
    if mlines is None:
        # Only a static_assert counts as a compile-time kill; any other error means the mutant is malformed.
        return ("static_assert" if "static assertion failed" in merr else None), None, merr
    diffs = [a for a, b in zip(mlines, PY_LINES) if a != b] + (["<line count>"] if len(mlines) != len(PY_LINES) else [])
    return (f"{len(diffs)} scenario mismatch(es)" if diffs else None), diffs, merr


for (label, _old, _new), (killed_by, _diffs, merr) in zip(
        BEHAVIOUR_MUTANTS, parallel(run_behaviour_mutant, enumerate(BEHAVIOUR_MUTANTS))):
    check(f"behaviour mutant [{label}] is killed ({killed_by or 'SURVIVED'})", killed_by is not None, (merr or "")[-600:])
stage()

shutil.rmtree(TMP, ignore_errors=True)
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-B0 host-compile and fault-injection checks passed.")
