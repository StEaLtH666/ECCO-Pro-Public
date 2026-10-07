#!/usr/bin/env python3
"""ecco_core.capability: statuses come only from the capability registry's evidence, unsupported and unknown fail closed,
controller-variant proof is honest, and decoding uses only the registry's declared types. Pure, synthetic, offline."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ecco_core import capability as cap  # noqa: E402
from ecco_core.state import DERIVED, NORMALIZED, RAW  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


NOW = datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc)
records = cap.load_registry()
P = cap.DeviceProfile(records)

print("[1] statuses on the real registry")
expect = {"telemetry.battery_soc": cap.SUPPORTED, "telemetry.battery_power": cap.SUPPORTED, "telemetry.house_power": cap.SUPPORTED,
          "telemetry.pv_power": cap.SUPPORTED, "telemetry.grid_power": cap.SUPPORTED, "telemetry.inverter_state": cap.SUPPORTED,
          "control.clock": cap.SUPPORTED, "control.tou_schedule": cap.SUPPORTED, "control.grid_charge": cap.SUPPORTED,
          "control.export_mode": cap.SUPPORTED,
          "control.dump_to_grid": cap.UNKNOWN,          # registry record: documented_not_live_proven
          "control.export_limit": cap.UNSUPPORTED,      # register 245 is read-only in this firmware
          "control.battery_protection": cap.UNSUPPORTED}
got = {c.id: P.status(c.id).status for c in cap.CAPABILITIES}
check("every capability's status is the evidence-derived one", got == expect, str({k: v for k, v in got.items() if expect.get(k) != v}))
check("Dump-to-Grid is UNKNOWN because its registry write proof is only documentary (no upgrade from elsewhere)",
      "documented_not_live_proven" in " ".join(P.status("control.dump_to_grid").reasons))
check("the export limit register is named as read-only", P.status("control.export_limit").registers == {245}
      and "read_only" in P.status("control.export_limit").reasons[0])
check("an unknown capability is UNKNOWN", P.status("control.teleport").status == cap.UNKNOWN)
check("the registers behind each control capability", P.registers("control.clock") == {22, 23, 24}
      and P.registers("control.export_mode") == {244} and P.registers("control.grid_charge") >= {230, 232, 256, 268}
      and P.registers("control.dump_to_grid") == {244, 256, 257, 258, 259, 260, 261})

print("[2] fail closed")
raised = []
for cid in ("control.dump_to_grid", "control.export_limit", "control.teleport"):
    try:
        P.require(cid)
    except cap.CapabilityUnavailable:
        raised.append(cid)
check("require() refuses everything that is not SUPPORTED", len(raised) == 3, str(raised))
check("require() returns the status of a supported capability", P.require("control.export_mode").supported)
recs = copy.deepcopy(records)
del recs["grid_export_policy"]
check("a missing record makes the capability UNKNOWN", cap.DeviceProfile(recs).status("control.export_mode").status == cap.UNKNOWN)
recs = copy.deepcopy(records)
recs["grid_export_policy"]["live_proof_status"] = "unknown"
check("an unknown write proof makes it UNKNOWN", cap.DeviceProfile(recs).status("control.export_mode").status == cap.UNKNOWN)
recs = copy.deepcopy(records)
recs["grid_export_policy"]["current_access"] = "read_only"
check("a read-only record makes a control UNSUPPORTED", cap.DeviceProfile(recs).status("control.export_mode").status == cap.UNSUPPORTED)
recs = copy.deepcopy(records)
recs["battery_soc"]["live_proof_status"] = "documented_not_live_proven"
check("telemetry without read proof is UNKNOWN", cap.DeviceProfile(recs).status("telemetry.battery_soc").status == cap.UNKNOWN)
check("the profile has no API that upgrades a status (only evidence in the registry can)",
      not [n for n in dir(cap.DeviceProfile) if any(n.startswith(p) for p in ("set_", "mark_", "upgrade", "learn", "record_"))])

print("[3] proof per controller variant (SUPPORTED_HARDWARE.md H-001 / H-002)")
check("classic ESP32: control hardware tested", P.proof_on("control.export_mode", "esp32_classic") == cap.HARDWARE_TESTED)
check("ESP32-S3: write features offline only", P.proof_on("control.export_mode", "esp32s3") == cap.OFFLINE_ONLY)
check("ESP32-S3: read-only telemetry hardware tested", P.proof_on("telemetry.battery_soc", "esp32s3") == cap.HARDWARE_TESTED)
check("an unknown variant is never proven", P.proof_on("control.export_mode", "esp32c3") == cap.NOT_PROVEN)
hw = (ROOT / "SUPPORTED_HARDWARE.md").read_text(encoding="utf-8")
h2 = next(line for line in hw.splitlines() if line.startswith("| H-002"))
check("the variant table follows SUPPORTED_HARDWARE.md: H-001 hardware tested, H-002 writes offline only",
      "| Hardware tested |" in next(line for line in hw.splitlines() if line.startswith("| H-001"))
      and "No write feature has been separately re-proven" in h2 and "offline only" in h2)
check("an unsupported or unknown capability is never proven",
      P.proof_on("control.export_limit", "esp32_classic") == cap.NOT_PROVEN
      and P.proof_on("control.dump_to_grid", "esp32_classic") == cap.NOT_PROVEN)

print("[4] decoding uses only the registry's declared type, sign and scale")
words = {184: 77, 190: 0xFF38, 178: 650, 186: 1200, 187: 800, 188: 0, 189: 0, 172: 0xFFCE, 59: 2}
d = {o.signal: o for c in ("telemetry.battery_soc", "telemetry.battery_power", "telemetry.house_power", "telemetry.pv_power",
                           "telemetry.grid_power", "telemetry.inverter_state") for o in P.decode(c, words, NOW)}
check("SOC word 77 -> 77 %", d["battery.soc"].value == 77.0 and d["battery.soc"].raw == 77 and d["battery.soc"].kind == NORMALIZED)
check("signed battery power 0xFF38 -> -200 W (charging), raw word kept", d["battery.power"].value == -200.0 and d["battery.power"].raw == 0xFF38)
check("grid power 0xFFCE -> -50 W (exporting)", d["grid.power"].value == -50.0)
check("PV power is DERIVED from the four strings, which stay present",
      d["pv.power"].value == 2000.0 and d["pv.power"].kind == DERIVED and d["pv.string_power.1"].value == 1200.0
      and set(d["pv.power"].derived_from) == {f"pv.string_power.{n}" for n in range(1, 5)})
check("inverter state 2 -> 'normal'", d["inverter.state"].value == "normal")
check("an unknown enum value is unavailable, never guessed",
      P.decode("telemetry.inverter_state", {59: 9}, NOW)[0].value is None)
check("a missing word is unavailable (RAW, flagged)", P.decode("telemetry.battery_soc", {}, NOW)[0].value is None
      and P.decode("telemetry.battery_soc", {}, NOW)[0].kind == RAW)
check("an out-of-range word is unavailable", P.decode("telemetry.battery_soc", {184: 70000}, NOW)[0].value is None)
check("one missing PV string makes the PV total unavailable, not partial",
      [o for o in P.decode("telemetry.pv_power", {186: 100, 187: 100, 188: 100}, NOW) if o.signal == "pv.power"][0].value is None)
try:
    P.decode("control.export_mode", words, NOW)
    check("decoding a control capability is refused", False)
except ValueError:
    check("decoding a control capability is refused", True)
recs = copy.deepcopy(records)
recs["battery_soc"]["live_proof_status"] = "unknown"
check("an unsupported telemetry capability decodes to unavailable",
      cap.DeviceProfile(recs).decode("telemetry.battery_soc", words, NOW)[0].value is None)
h = cap.inverter_healthy(d["inverter.state"])
check("inverter.healthy is DERIVED: normal -> True; alarm -> False; unknown -> None",
      h.value is True and h.kind == DERIVED
      and cap.inverter_healthy(P.decode("telemetry.inverter_state", {59: 3}, NOW)[0]).value is False
      and cap.inverter_healthy(P.decode("telemetry.inverter_state", {}, NOW)[0]).value is None)

print("[5] the registry's own write view")
rw = P.read_write_records()
check("read_write records cover exactly the expected write surface",
      frozenset().union(*rw.values()) == frozenset({22, 23, 24, 230, 232, 244} | set(range(250, 262)) | set(range(268, 280))),
      str(sorted(frozenset().union(*rw.values()))))
bad_schema = False
try:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pth = Path(td) / "r.yaml"
        pth.write_text("schema_version: 1\ncapabilities: []\n", encoding="utf-8")
        cap.load_registry(pth)
except ValueError:
    bad_schema = True
check("an unexpected registry schema fails loudly", bad_schema)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in ecco_core capability:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll ecco_core capability checks passed")
