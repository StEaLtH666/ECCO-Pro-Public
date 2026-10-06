#!/usr/bin/env python3
"""ESP32-S3 (N16R8) drop-in variant - the hardware wrapper must stay a wrapper.

firmware/ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml may override ONLY the
`esp32:` block (variant / flash size) and the `logger:` UART selection, and pull in
the unchanged production firmware as a package. It must not add logic, entities,
API actions, pins, secrets, a different node name, PSRAM or any other component.
The production file must keep its classic-ESP32 hardware block and the single
inverter UART mapping (GPIO17 TX / GPIO16 RX, 9600 8N1, no RS485 flow-control pin).

The compiled-output half of this guarantee (generated main.cpp identical apart
from the logger UART selection) is registry/tests/check_esp32s3_equivalence.py (needs
a native ESPHome 2026.8.x, so it is not a test_*.py of the offline CI suite); this
suite is the offline half. The wrapper lives under the normal firmware/*.yaml name and
is an explicit entry of registry/tests/_hardware_wrappers.py, which the suites that
characterise production application YAMLs use to skip it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
WRAPPER = FW / "ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml"
PROD = FW / "ecco_clock_dongle_stage3_4_free_power.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hardware_wrappers as hw  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("  PASS  " if condition else "  FAIL  ") + name)
    if not condition:
        FAILURES.append(name + (f" :: {detail}" if detail else ""))


class _Loader(yaml.SafeLoader):
    pass


def _tagged(loader, suffix, node):
    return {"__tag__": suffix, "value": loader.construct_scalar(node)}


_Loader.add_multi_constructor("!", _tagged)


def code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


w_text = WRAPPER.read_text(encoding="utf-8")
p_text = PROD.read_text(encoding="utf-8")
w = yaml.load(w_text, Loader=_Loader)

print("[1] wrapper shape")
check("wrapper uses the normal firmware/*.yaml name (discoverable, not hidden from the firmware globs)",
      WRAPPER.suffix == ".yaml" and WRAPPER.parent == FW and WRAPPER in FW.glob("*.yaml"))
check("wrapper is exactly the one entry of the hardware-wrapper allowlist the production-identity suites skip",
      hw.HARDWARE_WRAPPERS == (WRAPPER.name,) and hw.is_hardware_wrapper(WRAPPER) and not hw.is_hardware_wrapper(PROD))
check("wrapper top-level keys are exactly packages / esp32 / logger", sorted(w) == ["esp32", "logger", "packages"], str(sorted(w)))
check("the only package is the unchanged production firmware, included from the same directory",
      w["packages"] == {"ecco_production": {"__tag__": "include", "value": PROD.name}} and PROD.is_file(), str(w["packages"]))
check("esp32 override is exactly variant esp32s3 + flash_size 16MB + esp-idf, no board, no PSRAM",
      w["esp32"] == {"variant": "esp32s3", "flash_size": "16MB", "framework": {"type": "esp-idf"}}, str(w["esp32"]))
check("logger override is exactly the USB Serial/JTAG UART selection", w["logger"] == {"hardware_uart": "USB_SERIAL_JTAG"}, str(w["logger"]))

print("[2] the wrapper adds no identity, secrets, pins or logic")
body = "\n".join(code_lines(w_text))
for needle in ("!secret", "password", "key:", "ssid", "name:", "friendly_name", "GPIO", "pin", "psram", "modbus:",
               "lambda", "script", "interval", "api:", "ota:", "wifi:", "actions", "manual_ip", "flow_control"):
    check(f"wrapper code contains no '{needle}'", needle not in body)
check("wrapper declares no top-level uart: block (the inverter UART exists only in production)",
      re.search(r"^uart:", body, re.M) is None)

print("[3] production firmware keeps its classic hardware block and the one inverter UART")
check("production esp32 block is still variant esp32 + esp-idf, flash size / board / PSRAM untouched",
      re.search(r"^esp32:\n  variant: esp32\n  framework:\n    type: esp-idf\n\nlogger:\n  level: INFO\n", p_text, re.M) is not None
      and "psram" not in p_text.lower())
check("production node identity is ecco-clock-dongle / ECCO Clock Dongle with no MAC suffix",
      "  name: ecco-clock-dongle\n  friendly_name: ECCO Clock Dongle\n" in p_text and "name_add_mac_suffix: false" in p_text)
check("inverter UART is GPIO17 TX / GPIO16 RX, 9600 8N1",
      re.search(r"^uart:\n  id: inverter_uart\n  tx_pin: GPIO17\n  rx_pin: GPIO16\n  baud_rate: 9600\n  data_bits: 8\n  parity: NONE\n  stop_bits: 1\n",
                p_text, re.M) is not None)
pins = sorted(set(re.findall(r"^\s*[a-z_]*pin:\s*(\S+)", p_text, re.M)))
check("those two are the ONLY pins in the production firmware (no RS485 DE/RE control line, no other GPIO)",
      pins == ["GPIO16", "GPIO17"] and "GPIO" not in re.sub(r"(tx|rx)_pin: GPIO1[67]", "", "\n".join(code_lines(p_text))), str(pins))
check("no flow_control_pin and no manual_ip anywhere in production (auto-direction RS485, DHCP address)",
      "flow_control_pin" not in p_text and "manual_ip" not in p_text and "use_address" not in p_text)
check("the firmware YAML glob sees exactly the three historic firmware files plus the one allow-listed S3 wrapper",
      sorted(p.name for p in FW.glob("*.yaml") if p.name != "secrets.yaml") == sorted([
          "ecco_clock_dongle_stage3_2_manual_slot1.yaml", "ecco_clock_dongle_stage3_3_manual_tou6.yaml", PROD.name, WRAPPER.name]))

print("[4] package merge: the S3 build equals production except variant / flash size / logger UART")
prod = yaml.load(p_text, Loader=_Loader)


def deep_merge(base, over):
    """ESPHome package semantics for dict-valued blocks: the including file wins key by key."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base[k], v) if k in base else v
        return out
    return over


merged = deep_merge(prod, {k: v for k, v in w.items() if k != "packages"})
changed = sorted(k for k in merged if merged[k] != prod.get(k)) + sorted(k for k in prod if k not in merged)
check("only the esp32 and logger blocks differ from production after the merge", changed == ["esp32", "logger"], str(changed))
check("esp32: only variant and flash_size differ; the esp-idf framework block is production's",
      merged["esp32"] == {**prod["esp32"], "variant": "esp32s3", "flash_size": "16MB"}
      and merged["esp32"]["framework"] == prod["esp32"]["framework"])
check("logger: production's level is kept and only hardware_uart is added",
      merged["logger"] == {**prod["logger"], "hardware_uart": "USB_SERIAL_JTAG"})
check("the node identity, api, ota, wifi, uart, modbus, switch (Automatic Clock Sync) blocks are production's, byte for byte",
      all(merged[k] == prod[k] for k in ("esphome", "api", "ota", "wifi", "preferences", "time", "uart", "modbus", "switch",
                                          "script", "interval", "globals")))

if FAILURES:
    print(f"\n{len(FAILURES)} FAILED")
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("\nALL PASS")
