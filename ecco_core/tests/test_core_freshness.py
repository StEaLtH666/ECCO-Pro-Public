#!/usr/bin/env python3
"""ecco_core.freshness: every catalogued limit equals its source in the repository (firmware, mirrored header, Intelligence,
design registries), unresolved limits stay unresolved, and assessment fails closed. Pure, synthetic, offline."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "registry"))

from ecco_core import freshness as fr  # noqa: E402
from ecco_core.state import NORMALIZED, Observation, Snapshot, spec_for  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
NOW = datetime(2030, 5, 1, 12, 0, tzinfo=UTC)
LIM = {(c.signal, c.purpose): c for c in fr.CATALOGUE}

print("[1] the catalogue is well formed")
check("every catalogued signal is a known signal", all(spec_for(c.signal) is not None for c in fr.CATALOGUE))
check("one limit per signal and purpose", len(LIM) == len(fr.CATALOGUE))
check("every purpose and standing is a declared one", all(c.purpose in fr.PURPOSES and c.standing in
                                                          (fr.CONTROLLER, fr.INTELLIGENCE, fr.DESIGN, fr.UNRESOLVED)
                                                          for c in fr.CATALOGUE))
check("a limit has a source exactly when it is resolved",
      all((c.max_age_s is None) == (c.standing == fr.UNRESOLVED) == (c.source == "") for c in fr.CATALOGUE))
check("resolved limits are positive numbers", all(c.max_age_s > 0 for c in fr.CATALOGUE if c.max_age_s is not None))

print("[2] each limit equals its source (no drift from the code it documents)")
fw = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")


def fw_ms(name: str) -> int | None:
    m = re.search(rf'^\s*{name}:\s*"(\d+)"\s*$', fw, re.M)
    return int(m.group(1)) if m else None


for (sig, purpose), sub in ((("battery.soc", fr.CONTROL_GATE), "ecco_dump_soc_stale_ms"),
                            (("grid.power", fr.CONTROL_GATE), "ecco_dump_grid_stale_ms"),
                            (("inverter.config_readback", fr.CONTROL_GATE), "ecco_dump_cfg_stale_ms")):
    lim = LIM[(sig, purpose)]
    check(f"{sig}/{purpose} = firmware {sub}", fw_ms(sub) is not None and lim.max_age_s * 1000 == fw_ms(sub)
          and sub in lim.source and lim.standing == fr.CONTROLLER, f"{fw_ms(sub)} vs {lim.max_age_s}")
hdr = (ROOT / "firmware" / "include" / "ecco_fallback_capture.h").read_text(encoding="utf-8")
m = re.search(r"constexpr uint32_t LIVE_CACHE_MAX_AGE_MS = (\d+)u;", hdr)
import fallback_capture  # noqa: E402

lc = LIM[("inverter.config_readback", fr.HEALTH)]
check("the fallback live-cache limit equals the header and its Python mirror",
      m is not None and int(m.group(1)) == fallback_capture.LIVE_CACHE_MAX_AGE_MS == lc.max_age_s * 1000)
from intelligence.advisor import STALE_SOC_SECONDS  # noqa: E402

check("advisory SOC limit = intelligence.advisor.STALE_SOC_SECONDS", LIM[("battery.soc", fr.ADVISORY)].max_age_s == STALE_SOC_SECONDS)
eng = (ROOT / "intelligence" / "engine.py").read_text(encoding="utf-8")
check("advisory history limit = the engine's 6 h rule", LIM[("history.hourly", fr.ADVISORY)].max_age_s == 6 * 3600
      and eng.count("data_age_h > 6") >= 2)
reg = {c["id"]: c for c in yaml.safe_load((ROOT / "registry" / "system_health_checks.yaml").read_text(encoding="utf-8"))["checks"]}
for (sig, cid, key) in (("controller.telemetry", "telemetry_freshness", "failure_threshold_seconds"),
                        ("controller.configuration", "configuration_freshness", "failure_threshold_seconds"),
                        ("canonical.telemetry", "canonical_stale_raw_fresh", "failure_threshold_seconds"),
                        ("battery_outlook", "battery_outlook_freshness", "warning_threshold_seconds")):
    lim = LIM[(sig, fr.HEALTH)]
    check(f"{sig}/health = registry check {cid}.{key}", reg[cid]["parameters"][key] == lim.max_age_s
          and cid in lim.source and lim.standing == fr.DESIGN, f"{reg[cid]['parameters'][key]} vs {lim.max_age_s}")
check("the registry's unresolved Influx thresholds are not invented here",
      all(reg[c]["parameters"].get("thresholds_unresolved") is True for c in ("influx_raw_freshness", "influx_5m_freshness"))
      and not any("influx" in c.source for c in fr.CATALOGUE))
import transaction_state_machine as tsm  # noqa: E402

check("transaction snapshot limit = the design model's Snapshot.max_age_seconds",
      tsm.Snapshot.__dataclass_fields__["max_age_seconds"].default == LIM[("transaction.snapshot", fr.CONTROL_GATE)].max_age_s)

print("[3] assessment fails closed")


def snap(*obs: Observation) -> Snapshot:
    return Snapshot.of(NOW, obs)


def soc(age: float | None, value=55.0) -> Observation:
    return Observation("battery.soc", value, None if age is None else NOW - timedelta(seconds=age), "c", NORMALIZED)


gate, adv = fr.FreshnessPolicy(fr.CONTROL_GATE), fr.FreshnessPolicy(fr.ADVISORY)
check("90 s at the control gate is FRESH, 91 s is STALE",
      gate.assess(snap(soc(90.0)), "battery.soc").status == fr.FRESH and gate.assess(snap(soc(91.0)), "battery.soc").status == fr.STALE)
check("the same 120 s reading is STALE for a control gate and FRESH for advice",
      gate.assess(snap(soc(120.0)), "battery.soc").status == fr.STALE and adv.assess(snap(soc(120.0)), "battery.soc").status == fr.FRESH)
check("no observation is UNKNOWN", adv.assess(snap(), "battery.soc").status == fr.UNKNOWN)
check("an unknown observation time is UNKNOWN", adv.assess(snap(soc(None)), "battery.soc").status == fr.UNKNOWN)
check("a future observation time is UNKNOWN (clock skew is not freshness)", adv.assess(snap(soc(-30.0)), "battery.soc").status == fr.UNKNOWN)
check("no usable value is UNAVAILABLE", adv.assess(snap(soc(5.0, None)), "battery.soc").status == fr.UNAVAILABLE)
hs = Observation("inverter.healthy", True, NOW - timedelta(seconds=1), "c", NORMALIZED)
a = adv.assess(snap(hs), "inverter.healthy")
check("an UNRESOLVED limit is never FRESH, even for a 1 s old reading", a.status == fr.UNKNOWN and "no freshness limit" in a.reason
      and a.standing == fr.UNRESOLVED)
check("a signal with no catalogue entry is UNRESOLVED", gate.limit("house.power").standing == fr.UNRESOLVED)
site = fr.FreshnessPolicy(fr.ADVISORY, {"inverter.healthy": 180.0})
check("a site override resolves it, with SITE standing", site.assess(snap(hs), "inverter.healthy").status == fr.FRESH
      and site.limit("inverter.healthy").standing == fr.SITE)
fam = fr.FreshnessPolicy(fr.CONTROL_GATE, {"controller.owner.*": 10.0, "controller.owner.manual_write_in_progress": 3.0})
check("a family override resolves every member, with SITE standing",
      fam.limit("controller.owner.dump_operation_in_progress").max_age_s == 10.0
      and fam.limit("controller.owner.dump_operation_in_progress").standing == fr.SITE)
check("an exact override wins over its family's", fam.limit("controller.owner.manual_write_in_progress").max_age_s == 3.0)
try:
    fr.FreshnessPolicy(fr.CONTROL_GATE, {"battery.soc": 3600.0})
    check("an override cannot LOOSEN a defined limit (the controller's 90 s SOC gate stays 90 s at most)", False)
except ValueError:
    check("an override cannot LOOSEN a defined limit (the controller's 90 s SOC gate stays 90 s at most)", True)
tight = fr.FreshnessPolicy(fr.CONTROL_GATE, {"battery.soc": 30.0})
check("...but may tighten it", tight.limit("battery.soc").max_age_s == 30.0 and tight.assess(snap(soc(60.0)), "battery.soc").status == fr.STALE)
check("a family override does not leak into another family", fam.limit("controller.arm.dump_write_enable").standing == fr.UNRESOLVED)
bad = []
for ov in ({"inverter.healthy": 0}, {"inverter.healthy": -5}, {"inverter.healthy": float("nan")}, {"inverter.healthy": True},
           {"inverter.typo": 60}, {"controller.typo.*": 60}):
    try:
        fr.FreshnessPolicy(fr.ADVISORY, ov)
        bad.append(ov)
    except ValueError:
        pass
check("invalid overrides are refused", not bad, str(bad))
try:
    fr.FreshnessPolicy("whenever")
    check("an unknown purpose is refused", False)
except ValueError:
    check("an unknown purpose is refused", True)
nf = gate.not_fresh(snap(soc(10.0)), ("battery.soc", "grid.power"))
check("not_fresh lists exactly the readings that are not fresh", [x.signal for x in nf] == ["grid.power"])
check("catalogue rows are plain data for documentation", len(fr.catalogue_rows()) == len(fr.CATALOGUE))

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in ecco_core freshness:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll ecco_core freshness checks passed")
