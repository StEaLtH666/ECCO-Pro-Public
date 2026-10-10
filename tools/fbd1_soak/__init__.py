"""FB-D1 seven-day soak evidence analyser (offline, read-only, standard library only).

Reads exported Home Assistant history and ESPHome firmware logs of the ECCO clock dongle and decides, criterion by criterion,
whether the FB-D1 soak (RTC correction policy, stall detection, B10 Live Match, Modbus polling liveness, D1 supervision and
write authority) met its acceptance criteria: PASS, WARNING, FAIL or INSUFFICIENT_EVIDENCE. It never connects to Home
Assistant, the dongle or the inverter. See tools/fbd1_soak/README.md and the CLI tools/fbd1_soak_analyse.py.

The FB-D1 RTC policy itself is not re-implemented: policy consistency is judged with registry/rtc_policy.py, the offline
mirror the firmware header (firmware/include/ecco_rtc_policy.h) is held to.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_REGISTRY = str(REPO / "registry")
if _REGISTRY not in sys.path:
    sys.path.insert(0, _REGISTRY)

ANALYSER_VERSION = "1.0.0"
REPORT_SCHEMA = "ecco-fbd1-soak-analysis/1"
