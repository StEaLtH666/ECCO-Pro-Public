#!/usr/bin/env python3
"""FB-A - host C++ compile of the standalone Fallback Profile header.

firmware/include/ecco_fallback_profile.h is deliberately NOT compiled by the
firmware build (it is in no `esphome: includes:` list and no production
source includes it), so this suite is what makes a real C++ compiler
evaluate its static_asserts (layouts, offsets, golden binding vectors, the
register/domain digests and both golden-case tables):

    g++ -std=gnu++17 -fsyntax-only -Wall -Werror

It FAILS - it never skips - when no C++ compiler is available. Compiler
search order: $ECCO_CXX, then `g++` / `c++` on PATH (CI: ubuntu-latest ships
g++), then the GCC cross compiler ESPHome's own ESP-IDF toolchain installs
(xtensa-esp32-elf-g++), which is the compiler the firmware itself uses.

The header is copied ALONE into an empty include directory, so a missing
standard include or an accidental dependency on another ECCO header fails
the compile (proves it is standalone). Negative controls prove the
static_asserts are really evaluated: a mutated golden case and a false
extra assertion must both fail to compile.

Writes only to a temporary directory; no hardware, no network.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER_PATH = ROOT / "firmware" / "include" / "ecco_fallback_profile.h"
FLAGS = ["-std=gnu++17", "-fsyntax-only", "-Wall", "-Werror"]

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
                 str(home / ".platformio" / "packages" / "toolchain-xtensa*" / "bin" / "xtensa-esp32-elf-g++*"),
                 str(home / ".espressif" / "tools" / "xtensa-esp-elf" / "*" / "xtensa-esp-elf" / "bin" / "xtensa-esp32-elf-g++*")]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[-1]
    return None


def compile_tu(cxx: str, include_dir: Path, source: str, flags=FLAGS) -> subprocess.CompletedProcess:
    tu = include_dir.parent / "tu.cpp"
    tu.write_text(source, encoding="utf-8")
    return subprocess.run([cxx, *flags, "-I", str(include_dir), str(tu)], capture_output=True, text=True, timeout=600)


print("[1] compiler")
if not HEADER_PATH.is_file():
    print(f"  FAIL  required file not found: {HEADER_PATH}")
    sys.exit(1)
CXX = find_compiler()
check("a C++ compiler is available (the host compile never silently skips)", CXX is not None,
      "set ECCO_CXX or install g++")
if CXX is None:
    print("\nFAILED: no C++ compiler found")
    sys.exit(1)
version = subprocess.run([CXX, "--version"], capture_output=True, text=True).stdout.splitlines()[:1]
print(f"  info  compiler: {CXX}")
print(f"  info  version:  {version[0] if version else '?'}")
macros = subprocess.run([CXX, "-x", "c++", "-dM", "-E", os.devnull], capture_output=True, text=True).stdout
check("the compiler is GCC (defines __GNUC__, not __clang__) - the constexpr limits the header relies on are GCC's",
      "#define __GNUC__ " in macros and "__clang__" not in macros)

HEADER = HEADER_PATH.read_text(encoding="utf-8")
TWICE = '#include "ecco_fallback_profile.h"\n#include "ecco_fallback_profile.h"\nint main() { return 0; }\n'

with tempfile.TemporaryDirectory(prefix="ecco_fb_a_") as tmp:
    inc = Path(tmp) / "include"
    inc.mkdir()
    (inc / "ecco_fallback_profile.h").write_text(HEADER, encoding="utf-8")
    check("the include directory holds ONLY the FB-A header (no other ECCO header can be picked up)",
          [p.name for p in inc.iterdir()] == ["ecco_fallback_profile.h"])

    print("[2] compile: g++ -std=gnu++17 -fsyntax-only -Wall -Werror")
    r = compile_tu(CXX, inc, TWICE)
    check("the standalone header compiles cleanly (included twice: #pragma once holds) and every static_assert holds",
          r.returncode == 0, (r.stderr or r.stdout)[-2000:])
    r20 = compile_tu(CXX, inc, TWICE, ["-std=gnu++20", "-fsyntax-only", "-Wall", "-Werror"])
    check("...and also under -std=gnu++20 (the ESPHome firmware's language mode)", r20.returncode == 0,
          (r20.stderr or r20.stdout)[-2000:])
    rx = compile_tu(CXX, inc, TWICE, FLAGS + ["-Wextra"])
    check("...and with -Wextra", rx.returncode == 0, (rx.stderr or rx.stdout)[-2000:])

    print("[3] negative controls: the static_asserts are really evaluated")
    r = compile_tu(CXX, inc, '#include "ecco_fallback_profile.h"\n'
                   'static_assert(ecco_fallback::GOLDEN_PROFILE_V1.binding == 0, "negative control");\n')
    check("an extra FALSE static_assert about the golden binding fails to compile",
          r.returncode != 0 and "negative control" in r.stderr)
    for label, old, new, message in (
        ("golden profile case flipped",
         "{LOAD_OK, 20, 8001, 0xFF, 0x0000, 1, PROFILE_DEFECT_DOMAIN, PROFILE_CORRUPT_DOMAIN}",
         "{LOAD_OK, 20, 8001, 0xFF, 0x0000, 1, PROFILE_DEFECT_NONE, PROFILE_VALID}",
         "FB-A profile classifier golden cases"),
        ("golden failback case flipped (APPLY_IN_PROGRESS without apply_committed accepted)",
         "{2, LOAD_OK, 10, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_INVARIANT, FAILBACK_RECORD_CORRUPT}",
         "{2, LOAD_OK, 10, 0x0100, 0xFF, 0x0000, 1, FAILBACK_DEFECT_NONE, FAILBACK_RECORD_VALID}",
         "FB-A failback classifier golden cases"),
        ("profile binding covers itself (bytes [0, 96))",
         "for (size_t i = 0; i < PROFILE_BOUND_BYTES; i++)", "for (size_t i = 0; i < PROFILE_SIZE; i++)",
         "FB-A profile binding"),
        ("reserved1 widened to u64 (layout grows, offsets shift)",
         "  uint32_t reserved1;       // 84  must be 0\n", "  uint64_t reserved1;       // 84  must be 0\n",
         "FallbackProfileV1 must be exactly 96 bytes"),
        ("230 classified E1", "if (addr == 244 || (addr >= 256", "if (addr == 230 || addr == 244 || (addr >= 256",
         "FB-A register classification digest"),
    ):
        mutated = HEADER.replace(old, new, 1)
        (inc / "ecco_fallback_profile.h").write_text(mutated, encoding="utf-8")
        r = compile_tu(CXX, inc, TWICE)
        check(f"compile mutant [{label}] is rejected by its static_assert",
              HEADER.count(old) >= 1 and mutated != HEADER and r.returncode != 0 and message in r.stderr,
              (r.stderr or "compiled")[-600:])
    (inc / "ecco_fallback_profile.h").write_text(HEADER, encoding="utf-8")

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FB-A host-compile checks passed.")
