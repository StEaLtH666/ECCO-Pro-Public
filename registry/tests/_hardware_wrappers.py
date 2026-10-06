"""Explicit allowlist of hardware-only firmware wrappers.

A hardware wrapper is a firmware/*.yaml that only pulls in a production firmware YAML
as an ESPHome package and overrides hardware blocks (esp32 variant / flash size, logger
UART). It carries no application identity (no esphome.name, no entities, globals,
restore values, lambdas) of its own - that all comes from the package.

Suites that characterise PRODUCTION application YAMLs (entity names, restore_value
preferences, device names, NVS key universe) iterate firmware/*.yaml and must skip the
wrappers listed here, because a wrapper has none of that content by design. The wrapper's
own shape and its equivalence to production are pinned by test_esp32s3_variant.py, and
the wrapper IS included in the exclusivity / lambda scans (it must contain zero
call sites).

Adding a name here is a deliberate act: test_esp32s3_variant.py fails for any entry that
is not pinned there.
"""

from __future__ import annotations

from pathlib import Path

HARDWARE_WRAPPERS = ("ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml",)


def is_hardware_wrapper(path: Path) -> bool:
    return path.name in HARDWARE_WRAPPERS
