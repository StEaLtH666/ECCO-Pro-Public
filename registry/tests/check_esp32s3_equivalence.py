#!/usr/bin/env python3
"""ESP32-S3 wrapper vs production: GENERATED C++ equivalence (native ESPHome required).

Not a test_*.py on purpose: it needs a native ESPHome 2026.8.x on PATH (the firmware
static_asserts < 2026.9.0) and takes ~1 minute, so it is not part of the offline CI
suite. Run it before flashing the S3 variant and after ANY edit of the wrapper:

    python registry/tests/check_esp32s3_equivalence.py

It copies the tracked firmware into a scratch directory with CI-style PLACEHOLDER
secrets (the real firmware/secrets.yaml is never read or copied), runs
`esphome compile --only-generate` for production and for the S3 wrapper into separate
ESPHOME_DATA_DIRs, and requires that the generated main.cpp (every entity, global,
script, lambda, API action, Modbus call and NVS call) differs ONLY in the logger UART
selection and the config-echo comments, and that defines.h differs ONLY in the board /
variant / USB-logger defines. That is the "no authority delta" proof.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROD = "ecco_clock_dongle_stage3_4_free_power.yaml"
S3 = "ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml"
PLACEHOLDER_SECRETS = (
    'wifi_ssid: "ci-test"\nwifi_password: "ci-test-password"\n'
    'ecco_api_key: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="\necco_ota_password: "ci-test-password"\n'
)

# Lines allowed to differ in main.cpp (substring match on the diff line, after stripping the +/- marker).
MAIN_ALLOWED = (
    "//   hardware_uart:", "//   board:", "//   flash_size:", "//   variant:",
    "set_uart_selection(logger::UART_SELECTION_",
)
DEFINES_ALLOWED = (
    '#define ESPHOME_BOARD ', '#define ESPHOME_VARIANT ', "#define USE_LOGGER_UART_SELECTION_",
    "#define USE_LOGGER_USB_CDC", "#define USE_LOGGER_USB_SERIAL_JTAG", "#define USE_LOGGER_UART_SELECTION_UART0",
)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name)
    if not ok:
        FAILURES.append(name + (f" :: {detail}" if detail else ""))


def generate(fw_dir: Path, yaml_name: str, data_dir: Path) -> Path:
    env = dict(os.environ, ESPHOME_DATA_DIR=str(data_dir))
    r = subprocess.run(["esphome", "compile", "--only-generate", yaml_name], cwd=fw_dir, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"esphome generate failed for {yaml_name}")
    return data_dir / "build" / "ecco-clock-dongle" / "src"


def changed_lines(a: Path, b: Path) -> list[str]:
    out = []
    for ln in difflib.unified_diff(a.read_text(encoding="utf-8").splitlines(), b.read_text(encoding="utf-8").splitlines(), lineterm="", n=0):
        if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---")):
            out.append(ln[1:].strip())
    return out


def main() -> int:
    ver = subprocess.run(["esphome", "version"], capture_output=True, text=True).stdout.strip()
    print(f"[0] {ver}")
    if "2026.8." not in ver:
        raise SystemExit("ESPHome 2026.8.x is required (firmware static_asserts < 2026.9.0)")
    with tempfile.TemporaryDirectory(prefix="ecco_s3_equiv_") as td:
        tmp = Path(td)
        fw = tmp / "firmware"
        (fw / "include").mkdir(parents=True)
        for f in (PROD, S3):
            shutil.copy2(ROOT / "firmware" / f, fw / f)
        for h in (ROOT / "firmware" / "include").glob("*.h"):
            shutil.copy2(h, fw / "include" / h.name)
        (fw / "secrets.yaml").write_text(PLACEHOLDER_SECRETS, encoding="ascii")
        print("[1] generating production C++ ...")
        src_p = generate(fw, PROD, tmp / "data_prod")
        print("[2] generating S3 C++ ...")
        src_s = generate(fw, S3, tmp / "data_s3")
        main_diff = changed_lines(src_p / "main.cpp", src_s / "main.cpp")
        bad = [ln for ln in main_diff if not any(a in ln for a in MAIN_ALLOWED)]
        check(f"main.cpp ({(src_p / 'main.cpp').stat().st_size} B): {len(main_diff)} differing lines, ALL logger-UART / config-echo",
              main_diff != [] and not bad, str(bad[:5]))
        check("main.cpp: the logger selection is the only functional difference (UART0 -> USB_SERIAL_JTAG)",
              [ln for ln in main_diff if "set_uart_selection" in ln] == [
                  "logger_logger_id->set_uart_selection(logger::UART_SELECTION_UART0);",
                  "logger_logger_id->set_uart_selection(logger::UART_SELECTION_USB_SERIAL_JTAG);"], str(main_diff))
        d_diff = changed_lines(src_p / "esphome" / "core" / "defines.h", src_s / "esphome" / "core" / "defines.h")
        bad_d = [ln for ln in d_diff if not any(ln.startswith(a) for a in DEFINES_ALLOWED)]
        check("defines.h differs only in board / variant / USB-logger defines", d_diff != [] and not bad_d, str(bad_d[:5]))
        inc_same = all((src_p / h.name).read_bytes() == (src_s / h.name).read_bytes()
                       for h in (src_p).glob("ecco_*.h")) if list(src_p.glob("ecco_*.h")) else True
        check("any ecco_* headers copied into the generated source are byte-identical", inc_same)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("\nS3 wrapper equivalence holds: no authority delta in the generated C++.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
