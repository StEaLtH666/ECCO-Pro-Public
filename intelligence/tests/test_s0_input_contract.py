#!/usr/bin/env python3
"""Intelligence S0: tests for the OFFLINE input-consistency diagnostic (intelligence/tools/s0_input_consistency.py) and the
facts the input-contract document (docs/intelligence/INTELLIGENCE_S0_INPUT_CONTRACT.md) states. Synthetic and example data only;
no Home Assistant, statistics export, network or device is touched.

  [1] authority: the diagnostic has no write path, reads only an explicitly named declaration file, imports nothing but
      ecco_core.state from ecco_core, and a report is always SHADOW / applies_nothing and carries no recommendation
  [2] nothing existing changes: SiteConfig defaults, effective_reserve, and the engine arithmetic are untouched by running it
  [3] reserves: roles are kept apart; unknown / invalid / unenforceable cases fail closed; no value is ever chosen
  [4] capacity: unit handling, the PROPOSED 8 % symmetric band (and the owner's override), example default, single source
  [5] efficiency: unit / basis fail closed, one-way vs round-trip detection, agreement with the engine's sqrt rule
  [6] signal readings: missing / non-numeric / stale / unknown-age / unit / sign / false-zero / disagreement
  [7] history periods against the derived-load cut-over (HD1); the load counter stays UNKNOWN offline
  [8] the 25 h autumn and 23 h spring UK local days / nights, against the real learner and a flat synthetic house
  [9] owner decisions stay OPEN until supplied; verdict ordering; determinism; JSON; strict declaration loader; CLI
  [10] review corrections I1/I2: the synthetic examples cannot be mistaken for site data or owner decisions, and the
       DRAFT / D1-D9 OPEN / PROPOSED / SHADOW-only / not-runtime-policy wording is present in the tool and the document
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import sys
import tempfile
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


def raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


from ecco_core.freshness import ADVISORY, CATALOGUE  # noqa: E402  (tests may read ecco_core freely)
from intelligence import battery  # noqa: E402
from intelligence import periods as SD_P  # noqa: E402
from intelligence import site_decisions as SD  # noqa: E402
from intelligence.advisor import STALE_SOC_SECONDS  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.overnight import OvernightSettings, learn_overnight, nightly_totals  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import UTC, local_wall, zone  # noqa: E402
from intelligence.tools import s0_input_consistency as s0  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "intelligence" / "tools" / "s0_input_consistency.py"
DOC = ROOT / "docs" / "intelligence" / "INTELLIGENCE_S0_INPUT_CONTRACT.md"
cfg = SiteConfig()


def codes(rep: s0.Report, sev: str | None = None) -> list[str]:
    return rep.codes(sev)


def clean() -> s0.Declaration:
    """A fully consistent, fully decided SYNTHETIC declaration (every value below is a test value, not a recommendation)."""
    cutover = datetime(2030, 3, 10, 12, 0, tzinfo=UTC)
    rd = [
        s0.ReadingDecl("battery.soc", "raw:soc", s0.RAW, 62.0, "62", "%", None, 20.0),
        s0.ReadingDecl("battery.soc", "canonical:soc", s0.CANONICAL, 62.0, "62", "%", None, 20.0),
        s0.ReadingDecl("battery.power", "raw:bp", s0.RAW, 800.0, "800", "W", "discharge_positive", 20.0),
        s0.ReadingDecl("grid.power", "ct", s0.RAW, -120.0, "-120", "W", "import_positive", 20.0),
    ]
    return s0.Declaration(
        cfg=cfg,
        reserves=(
            s0.ReserveDecl("floor", s0.SOFT_PLANNING_FLOOR, 40.0, "SiteConfig"),
            s0.ReserveDecl("helper", s0.HA_RESERVE_HELPER, 40.0, "helper"),
            s0.ReserveDecl("stop", s0.FEATURE_STOP_LEVEL, 40.0, "feature", enforced_by="firmware"),
            s0.ReserveDecl("protect", s0.PHYSICAL_PROTECTION, 10.0, "inverter", enforced_by="inverter"),
        ),
        capacities=(s0.CapacityDecl("helper cap", "CONFIGURED_HELPER", cfg.battery_capacity_kwh),
                    s0.CapacityDecl("learned cap", "LEARNED_FROM_DISCHARGE", cfg.battery_capacity_kwh * 0.99, age_s=3600.0)),
        efficiencies=(s0.EfficiencyDecl("helper eff", 90.0, "percent", s0.ROUND_TRIP),),
        readings=tuple(rd),
        history=(s0.HistoryPeriod(s0.LOAD_POWER_MEAN, datetime(2030, 3, 11, tzinfo=UTC), datetime(2030, 3, 20, tzinfo=UTC)),),
        nights=s0.NightSpec(date(2026, 10, 10), date(2026, 10, 12), 30, 330),
        decisions=typed(D1=SD.PlanningFloor(SD.INTELLIGENCE_USER_RESERVE, 40.0, True),
                        D2=SD.Protection(SD.OWNER_STATEMENT, 10.0, cutover),
                        D3=SD.CapacityAuthority("CONFIGURED_HELPER", cfg.battery_capacity_kwh), D4=SD.CapacityBand(8.0),
                        D5=SD.Efficiency(90.0, SD.PERCENT, s0.ROUND_TRIP), D6=SD.FreshnessOverrides({"house.power": 120.0}),
                        D7=SD.RequiredInputsOverride({"charge_target": ("battery.soc",)}),
                        D8=SD.HD1Cutover(cutover, SD.EXCLUDE, SD.EXCLUDE_PRE_CUTOVER),
                        D9=SD.DSTPolicy(SD.NORMALISE_TO_NOMINAL, SD.SCALE_UP_ONLY)),
    )


def typed(base_set: s0.DecisionSet | None = None, **values) -> s0.DecisionSet:
    """A typed decision set (CALLER_DECLARATION_UNVERIFIED provenance) from D<n>=value; None leaves / makes it OPEN."""
    ds = base_set if base_set is not None else s0.DecisionSet(source="declaration")
    for did, v in values.items():
        ds = ds.without(did) if v is None else ds.with_decision(did, v, s0.PROV_CALLER)
    return ds


# ---------------------------------------------------------------------------------------------------------------------
section("[1] authority: no write path, no recommendation")
BAD = {"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus", "paho", "ssl",
       "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc", "subprocess", "os", "pty", "shutil",
       "signal", "threading", "sqlite3"}
VOCAB = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt.publish")
for path in (TOOL, Path(__file__).resolve()):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.append(n.module)
    check(f"{path.name}: no network / process / serial / dynamic import", not [m for m in mods if m.split(".")[0] in BAD], str(mods))
    check(f"{path.name}: imports from ecco_core are limited to the state model (tests may also read freshness)",
          all(m in ("ecco_core.state", "ecco_core.freshness") for m in mods if m.split(".")[0] == "ecco_core")
          and (path == TOOL) <= all(m == "ecco_core.state" for m in mods if m.split(".")[0] == "ecco_core"), str(mods))
    if path != TOOL:
        continue  # the vocabulary / call rules are the tool's; this file legitimately names them and writes a temp file
    lits = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 200]
    check(f"{path.name}: no control vocabulary in string literals", not [v for v in lits if any(w in v.lower() for w in VOCAB)])
    names = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    check(f"{path.name}: no exec / eval / spawn / write call", not names & {"system", "popen", "Popen", "exec", "eval", "__import__",
                                                                          "write_text", "write_bytes", "compile"}, str(names))
tool_tree = ast.parse(TOOL.read_text(encoding="utf-8"))
opens = [n for n in ast.walk(tool_tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open"]
check("the tool opens no file for writing (its only file read is Path.read_text on a named declaration)", not opens)
rep = s0.run(s0.example_declaration())
d = rep.to_dict()
check("a report is SHADOW and applies nothing", d["mode"] == "SHADOW" and d["applies_nothing"] is True)
check("a report has exactly the documented keys (no 'recommended' / 'target' / 'apply' field)",
      set(d) == {"model_version", "status", "notice", "declaration_origin", "mode", "applies_nothing", "verdict", "counts",
                 "findings", "decisions", "proposed_thresholds"})
check("no finding carries a recommended value", not [f for f in d["findings"] if any("recommend" in k.lower() for k in f["evidence"])])
check("every proposed threshold is labelled PROPOSED_PENDING_OWNER", d["proposed_thresholds"]["status"] == "PROPOSED_PENDING_OWNER")

# ---------------------------------------------------------------------------------------------------------------------
section("[2] nothing existing changes")
h0 = cfg.config_hash()
before = (SiteConfig().user_reserve_soc_pct, SiteConfig().technical_min_soc_pct, SiteConfig().battery_capacity_kwh,
          SiteConfig().round_trip_efficiency, SiteConfig().effective_reserve(15.0).as_dict())
s0.run(s0.example_declaration()); s0.run(s0.example_declaration(faulty=True)); s0.run(clean())
check("running the diagnostic does not change SiteConfig (hash)", cfg.config_hash() == h0)
check("S0 pins the CURRENT SiteConfig defaults (a deliberate owner decision, not this job, would change them)",
      before[:4] == (40.0, 10.0, 31.7, 0.9), str(before[:4]))
check("a helper below the user reserve cannot lower the effective reserve (the engine's rule the diagnostic describes)",
      before[4]["effective_pct"] == 40.0 and before[4]["binding"] == "user_reserve", str(before[4]))
check("the diagnostic's one-way conversion is the engine's: eta_one_way == sqrt(round-trip)",
      abs(battery.eta_one_way(cfg) - math.sqrt(cfg.round_trip_efficiency)) < 1e-12)

# ---------------------------------------------------------------------------------------------------------------------
section("[3] reserves")
r = s0.run(clean())
check("the clean synthetic declaration has no BLOCK and no WARN", not codes(r, s0.BLOCK) and not codes(r, s0.WARN), str(codes(r)))
ex = s0.run(s0.example_declaration())
check("the four example levels are four different roles", len({x.role for x in s0.example_declaration().reserves}) == 4)
check("an unsupplied inverter protection level BLOCKS (never assumed)", "PHYSICAL_PROTECTION_UNKNOWN" in codes(ex, s0.BLOCK))
check("a helper below the planning floor is INFO (it can only raise)", "HA_HELPER_BELOW_PLANNING_FLOOR" in codes(ex, s0.INFO))
check("a feature stop below the floor is INFO (that feature does not read the floor today)",
      "FEATURE_STOP_BELOW_PLANNING_FLOOR" in codes(ex, s0.INFO))
base = clean()


def with_reserves(*rs: s0.ReserveDecl) -> s0.Report:
    return s0.run(replace(base, reserves=rs))


floor = s0.ReserveDecl("floor", s0.SOFT_PLANNING_FLOOR, 40.0, "x")
prot = s0.ReserveDecl("protect", s0.PHYSICAL_PROTECTION, 20.0, "inverter")
check("a soft floor below the protection level WARNs (the protection binds first)",
      "PLANNING_FLOOR_BELOW_PROTECTION" in codes(with_reserves(replace(floor, value_pct=15.0), prot), s0.WARN))
check("a feature stop below the protection level WARNs",
      "FEATURE_STOP_BELOW_PROTECTION" in codes(with_reserves(floor, prot, s0.ReserveDecl("stop", s0.FEATURE_STOP_LEVEL, 10.0, "x")), s0.WARN))
check("SiteConfig.technical_min below the protection level WARNs (10 % is a placeholder, not a safety minimum)",
      "TECHNICAL_MIN_BELOW_PROTECTION" in codes(with_reserves(floor, prot), s0.WARN))
check("a protection level declared writable by ECCO BLOCKS",
      "PROTECTION_DECLARED_WRITABLE" in codes(with_reserves(floor, replace(prot, writable_by_ecco=True)), s0.BLOCK))
check("a soft floor claimed to be enforced WARNs",
      "ENFORCEMENT_CLAIM_UNVERIFIED" in codes(with_reserves(replace(floor, enforced_by="firmware"), prot), s0.WARN))
check("a feature stop level may name its enforcer (no warning for the firmware stop)",
      "ENFORCEMENT_CLAIM_UNVERIFIED" not in codes(with_reserves(floor, prot, s0.ReserveDecl("stop", s0.FEATURE_STOP_LEVEL, 10.0, "x", enforced_by="firmware"))))
for bad in (float("nan"), float("inf"), -1.0, 101.0, True, "40"):
    check(f"reserve value {bad!r} is invalid", "RESERVE_VALUE_INVALID" in codes(with_reserves(replace(floor, value_pct=bad), prot), s0.BLOCK))
check("a missing value BLOCKS", "RESERVE_VALUE_UNKNOWN" in codes(with_reserves(replace(floor, value_pct=None), prot), s0.BLOCK))
check("an unknown role BLOCKS", "RESERVE_ROLE_UNKNOWN" in codes(with_reserves(replace(floor, role="WHATEVER"), prot), s0.BLOCK))
check("a duplicate name BLOCKS", "RESERVE_DUPLICATE_NAME" in codes(with_reserves(floor, floor, prot), s0.BLOCK))
check("no planning floor at all BLOCKS", "NO_PLANNING_FLOOR_DECLARED" in codes(with_reserves(prot), s0.BLOCK))
check("the diagnostic never emits a value it chose: no finding evidence has a key like 'chosen' / 'canonical_value'",
      not [f for f in ex.findings for k, _ in f.evidence if k in ("chosen", "canonical_value", "use")])

# ---------------------------------------------------------------------------------------------------------------------
section("[4] capacity")
TH = s0.ProposedThresholds()


def cap_run(*caps: s0.CapacityDecl, c=cfg, band=None) -> s0.Report:
    return s0.run(replace(base, cfg=c, capacities=caps, decisions=typed(base.decisions, D4=None if band is None else SD.CapacityBand(band))))


a = 30.0
b_in, b_out = a * (2 - 0.0799) / (2 + 0.0799), a * (2 - 0.0801) / (2 + 0.0801)
c30 = replace(cfg, battery_capacity_kwh=a)
check("a difference just inside 8 % is within the band",
      "CAPACITY_MISMATCH" not in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", b_in), c=c30)), str(codes(cap_run(s0.CapacityDecl('x', 'CONFIGURED_HELPER', b_in), c=c30))))
check("a difference just outside 8 % WARNs",
      "CAPACITY_MISMATCH" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", b_out), c=c30), s0.WARN))
check("the comparison is symmetric (a vs b equals b vs a)",
      ("CAPACITY_MISMATCH" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", b_out), c=c30)))
      == ("CAPACITY_MISMATCH" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", a), c=replace(cfg, battery_capacity_kwh=b_out)))))
check("an owner-recorded band replaces the proposal (15 % accepts a 12 % gap) and the message says so",
      "CAPACITY_MISMATCH" not in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 28.0), band=15.0))
      and any("owner-recorded" in f.message for f in cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 28.0), band=15.0).findings
              if f.code == "CAPACITY_WITHIN_BAND"))
check("the default band message says PROPOSED", any("PROPOSED" in f.message for f in
      cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 28.0)).findings if f.code == "CAPACITY_MISMATCH"))
check("Wh is converted (31700 Wh == 31.7 kWh, no mismatch)",
      "CAPACITY_MISMATCH" not in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 31700.0, "Wh"))))
check("an Ah figure without a voltage is left out, not guessed",
      "CAPACITY_AH_NEEDS_VOLTAGE" in codes(cap_run(s0.CapacityDecl("x", "REGISTER_AH", 600.0, "Ah")), s0.WARN))
check("an Ah figure with a stated voltage is compared (600 Ah x 52.8 V = 31.68 kWh)",
      "CAPACITY_MISMATCH" not in codes(cap_run(s0.CapacityDecl("x", "REGISTER_AH", 600.0, "Ah", 52.8))))
check("a Wh figure labelled kWh is implausible and BLOCKS",
      "CAPACITY_IMPLAUSIBLE" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 31700.0)), s0.BLOCK))
for badv in (0.0, -3.0, float("nan"), None, True):
    check(f"capacity value {badv!r} is not usable", "CAPACITY_VALUE_MISSING" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", badv))))
check("an unknown unit BLOCKS", "CAPACITY_UNIT_UNKNOWN" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 30.0, "MWh")), s0.BLOCK))
check("an unknown kind BLOCKS", "CAPACITY_KIND_UNKNOWN" in codes(cap_run(s0.CapacityDecl("x", "GUESS", 30.0)), s0.BLOCK))
check("SiteConfig is always one of the sources compared (so a helper that disagrees with it WARNs)",
      "CAPACITY_MISMATCH" in codes(cap_run(s0.CapacityDecl("x", "CONFIGURED_HELPER", 20.0))))
only = s0.run(replace(base, capacities=()))
check("with no independent source SiteConfig's shipped example capacity is flagged as an unconfirmed example",
      "CAPACITY_IS_EXAMPLE_DEFAULT" in codes(only, s0.WARN) and "CAPACITY_SINGLE_SOURCE" in codes(only, s0.INFO))
tiny = s0.run(replace(base, cfg=replace(cfg, battery_capacity_kwh=0.3), capacities=()))
check("no usable capacity at all BLOCKS (SiteConfig's own 0.3 kWh is implausible)", {"CAPACITY_IMPLAUSIBLE", "CAPACITY_UNKNOWN"} <= set(codes(tiny, s0.BLOCK)), str(codes(tiny)))
check("a learned capacity without an age WARNs", "CAPACITY_SOURCE_AGE_UNKNOWN" in codes(cap_run(s0.CapacityDecl("x", "LEARNED_FROM_DISCHARGE", 31.7))))
check("a declared EXAMPLE_DEFAULT source WARNs", "CAPACITY_IS_EXAMPLE_DEFAULT" in codes(cap_run(s0.CapacityDecl("x", "EXAMPLE_DEFAULT", 31.7))))

# ---------------------------------------------------------------------------------------------------------------------
section("[5] efficiency")


def eff_run(*es: s0.EfficiencyDecl, c=cfg) -> s0.Report:
    return s0.run(replace(base, cfg=c, efficiencies=es))


EF = s0.EfficiencyDecl
rt, ow, bad = s0.efficiency_round_trip(EF("a", 90.0, "percent", s0.ROUND_TRIP))
check("90 % round-trip -> round-trip 0.90, one-way sqrt(0.90)", bad is None and abs(rt - 0.9) < 1e-12 and abs(ow - math.sqrt(0.9)) < 1e-12)
rt, ow, bad = s0.efficiency_round_trip(EF("a", 0.9487, "fraction", s0.ONE_WAY))
check("0.9487 one-way -> round-trip 0.90 (squared)", bad is None and abs(rt - 0.9) < 1e-3 and abs(ow - 0.9487) < 1e-12)
check("a fraction above 1 is a unit mismatch", "EFFICIENCY_UNIT_MISMATCH" in codes(eff_run(EF("a", 90.0, "fraction", s0.ROUND_TRIP)), s0.BLOCK))
check("a 'percent' of 0.9 is a unit mismatch", "EFFICIENCY_UNIT_MISMATCH" in codes(eff_run(EF("a", 0.9, "percent", s0.ROUND_TRIP)), s0.BLOCK))
check("no unit BLOCKS", "EFFICIENCY_UNIT_UNSTATED" in codes(eff_run(EF("a", 0.9, None, s0.ROUND_TRIP)), s0.BLOCK))
check("no basis BLOCKS", "EFFICIENCY_BASIS_UNSTATED" in codes(eff_run(EF("a", 0.9, "fraction", None)), s0.BLOCK))
check("out of 0.5..1.0 BLOCKS", "EFFICIENCY_OUT_OF_RANGE" in codes(eff_run(EF("a", 0.3, "fraction", s0.ROUND_TRIP)), s0.BLOCK))
for badv in (float("nan"), None, True):
    check(f"efficiency {badv!r} is not usable", "EFFICIENCY_VALUE_MISSING" in codes(eff_run(EF("a", badv, "fraction", s0.ROUND_TRIP)), s0.BLOCK))
check("a 'round-trip' 0.98 looks one-way (WARN)", "EFFICIENCY_LOOKS_ONE_WAY" in codes(eff_run(EF("a", 0.98, "fraction", s0.ROUND_TRIP)), s0.WARN))
check("a 'one-way' 0.85 looks round-trip (WARN)", "EFFICIENCY_LOOKS_ROUND_TRIP" in codes(eff_run(EF("a", 0.85, "fraction", s0.ONE_WAY)), s0.WARN))
mix = eff_run(EF("helper", 90.0, "percent", s0.ROUND_TRIP), EF("flux", math.sqrt(0.9), "fraction", s0.ROUND_TRIP))
check("two 'round-trip' values where one is the square root of the other are detected as a mix (BLOCK)",
      "EFFICIENCY_ONE_WAY_ROUND_TRIP_MIX" in codes(mix, s0.BLOCK), str(codes(mix)))
ok = eff_run(EF("helper", 90.0, "percent", s0.ROUND_TRIP), EF("flux", math.sqrt(0.9), "fraction", s0.ONE_WAY))
check("a round-trip 90 % and a one-way sqrt(0.9) are CONSISTENT (different bases, same physics)",
      "EFFICIENCY_BASES_DIFFER_BUT_CONSISTENT" in codes(ok, s0.INFO) and "EFFICIENCY_DISAGREE" not in codes(ok)
      and "EFFICIENCY_ONE_WAY_ROUND_TRIP_MIX" not in codes(ok))
dis = eff_run(EF("a", 88.0, "percent", s0.ROUND_TRIP))
check("90 % (SiteConfig) vs 88 % is an ordinary disagreement (WARN), not a mix", "EFFICIENCY_DISAGREE" in codes(dis, s0.WARN)
      and "EFFICIENCY_ONE_WAY_ROUND_TRIP_MIX" not in codes(dis))

# ---------------------------------------------------------------------------------------------------------------------
section("[6] signal readings")
RD = s0.ReadingDecl


def rd_run(*rs: s0.ReadingDecl, advisory_limits_s="keep", required_signals="keep") -> s0.Report:
    over = {}
    if advisory_limits_s != "keep":
        over["D6"] = None if advisory_limits_s is None else SD.FreshnessOverrides(advisory_limits_s)
    if required_signals != "keep":
        over["D7"] = None if required_signals is None else SD.RequiredInputsOverride({"charge_target": tuple(required_signals)})
    return s0.run(replace(base, readings=rs, decisions=typed(base.decisions, **over)))


soc_raw = RD("battery.soc", "raw", s0.RAW, 62.0, "62", "%", None, 20.0)
soc_can = RD("battery.soc", "can", s0.CANONICAL, 62.0, "62", "%", None, 20.0)
check("a fresh agreeing raw + canonical SOC pair is clean", not codes(rd_run(soc_raw, soc_can), s0.BLOCK) and not codes(rd_run(soc_raw, soc_can), s0.WARN))
fz = rd_run(replace(soc_raw, value=None, raw_state="unavailable"), replace(soc_can, value=0.0, raw_state="0"))
check("canonical 0 over an unavailable raw state is a SUSPECTED FALSE ZERO (BLOCK)", "FALSE_ZERO_SUSPECTED" in codes(fz, s0.BLOCK))
check("... and the false zero is not counted as a usable source", "SIGNAL_NO_USABLE_SOURCE" in codes(fz, s0.BLOCK))
real0 = rd_run(replace(soc_raw, value=0.0, raw_state="0"), replace(soc_can, value=0.0, raw_state="0"))
check("a canonical 0 that the raw source confirms is NOT a false zero", "FALSE_ZERO_SUSPECTED" not in codes(real0))
check("a lone canonical SOC of 0 is only a WARN (unconfirmed)", "ZERO_UNCONFIRMED" in codes(rd_run(replace(soc_can, value=0.0, raw_state="0")), s0.WARN))
check("no SOC reading at all BLOCKS", "REQUIRED_SIGNAL_MISSING" in codes(rd_run(RD("grid.power", "g", s0.RAW, 0.0, "0", "W", "import_positive", 5.0)), s0.BLOCK))
check("the SOC age limit is the engine's 15 minutes", s0.DEFINED_ADVISORY_LIMITS_S["battery.soc"] == STALE_SOC_SECONDS == 900)
check("a SOC at exactly the limit is fresh, one second over is stale (BLOCK)",
      "READING_STALE" not in codes(rd_run(replace(soc_raw, age_s=900.0))) and "READING_STALE" in codes(rd_run(replace(soc_raw, age_s=901.0)), s0.BLOCK))
for age in (None, float("nan"), -5.0, True, "20"):
    check(f"SOC age {age!r} is UNKNOWN and BLOCKS", "READING_AGE_UNKNOWN" in codes(rd_run(replace(soc_raw, age_s=age)), s0.BLOCK))
for v in (float("nan"), float("inf"), True, "62"):
    check(f"SOC value {v!r} is not a usable number", "READING_NOT_NUMERIC" in codes(rd_run(replace(soc_raw, value=v))))
check("a SOC in the wrong unit BLOCKS", "UNIT_MISMATCH" in codes(rd_run(replace(soc_raw, unit="fraction")), s0.BLOCK))
check("an unknown signal name BLOCKS", "SIGNAL_UNKNOWN_NAME" in codes(rd_run(RD("battery.soc_pct", "x", s0.RAW, 1.0, "1", "%", None, 1.0)), s0.BLOCK))
check("an unknown reading kind BLOCKS", "READING_KIND_UNKNOWN" in codes(rd_run(replace(soc_raw, kind="GUESS")), s0.BLOCK))
bp = RD("battery.power", "bp", s0.RAW, 800.0, "800", "W", "discharge_positive", 20.0)
check("battery power must declare the repository's sign (discharge positive)",
      "SIGN_CONVENTION_MISMATCH" in codes(rd_run(soc_raw, replace(bp, sign="charge_positive")), s0.BLOCK)
      and "SIGN_UNDECLARED" in codes(rd_run(soc_raw, replace(bp, sign=None)), s0.WARN)
      and "SIGN_CONVENTION_MISMATCH" not in codes(rd_run(soc_raw, bp)))
check("grid power must declare import positive", "SIGN_CONVENTION_MISMATCH" in codes(
    rd_run(soc_raw, RD("grid.power", "g", s0.RAW, 5.0, "5", "W", "export_positive", 5.0)), s0.BLOCK))
check("kW for a W signal BLOCKS", "UNIT_MISMATCH" in codes(rd_run(soc_raw, RD("pv.power", "p", s0.RAW, 1.2, "1.2", "kW", None, 5.0)), s0.BLOCK))
check("a carried value over a non-numeric source state WARNs", "NON_NUMERIC_STATE_WITH_VALUE" in codes(
    rd_run(soc_raw, replace(soc_can, value=62.0, raw_state="unavailable")), s0.WARN))
check("two SOC readings 2 points apart agree; 3 points apart disagree",
      "SOURCE_DISAGREEMENT" not in codes(rd_run(soc_raw, replace(soc_can, value=64.0)))
      and "SOURCE_DISAGREEMENT" in codes(rd_run(soc_raw, replace(soc_can, value=65.0)), s0.WARN))
hp = [RD("house.power", "d", s0.DERIVED, 930.0, "930", "W", None, 20.0), RD("house.power", "n", s0.RAW, 1000.0, "1000", "W", None, 20.0)]
check("house load within max(100 W, 5 %) agrees; 2400 vs 930 disagrees",
      "SOURCE_DISAGREEMENT" not in codes(rd_run(soc_raw, *hp)) and "SOURCE_DISAGREEMENT" in codes(rd_run(soc_raw, hp[0], replace(hp[1], value=2400.0))))
unres = rd_run(soc_raw, hp[0], advisory_limits_s=None)
check("an undefined limit is reported once as INFO for a non-required signal", codes(unres).count("ADVISORY_LIMIT_UNRESOLVED") == 1)
req = rd_run(soc_raw, hp[0], required_signals=("battery.soc", "house.power"), advisory_limits_s=None)
check("a REQUIRED signal with no defined limit can never be fresh (BLOCK)", "READING_AGE_UNKNOWN" in codes(req, s0.BLOCK))
check("an owner limit supplies it (house power 120 s -> fresh at 20 s, stale at 121 s)",
      "READING_AGE_UNKNOWN" not in codes(rd_run(soc_raw, hp[0], required_signals=("battery.soc", "house.power"), advisory_limits_s={"house.power": 120.0}))
      and "READING_STALE" in codes(rd_run(soc_raw, replace(hp[0], age_s=121.0), required_signals=("battery.soc", "house.power"),
                                          advisory_limits_s={"house.power": 120.0}), s0.BLOCK))
check("an owner override may TIGHTEN the SOC limit", "READING_STALE" in codes(rd_run(replace(soc_raw, age_s=200.0), advisory_limits_s={"battery.soc": 120.0}), s0.BLOCK))
loose = rd_run(replace(soc_raw, age_s=1000.0), advisory_limits_s={"battery.soc": 3600.0})
check("... but never LOOSEN it (refused, the 900 s limit still applies)",
      "FRESHNESS_OVERRIDE_REFUSED" in codes(loose, s0.WARN) and "READING_STALE" in codes(loose, s0.BLOCK))
check("an invalid override BLOCKS", "FRESHNESS_OVERRIDE_INVALID" in codes(rd_run(soc_raw, advisory_limits_s={"house.power": -1.0}), s0.BLOCK))
adv = {l.signal: l.max_age_s for l in CATALOGUE if l.purpose == ADVISORY}
check("every limit the diagnostic treats as defined equals ecco_core's advisory catalogue (no drift)",
      all(adv.get(k) == v for k, v in s0.DEFINED_ADVISORY_LIMITS_S.items()), str(adv))
check("and every advisory signal the catalogue leaves unresolved is absent from the diagnostic's table",
      all(k not in s0.DEFINED_ADVISORY_LIMITS_S for k, v in adv.items() if v is None))

# ---------------------------------------------------------------------------------------------------------------------
section("[7] history periods and the derived-load cut-over")
cut = datetime(2030, 3, 10, 12, 0, tzinfo=UTC)
P = s0.HistoryPeriod


def hist(*ps: s0.HistoryPeriod, cutover=cut) -> list[str]:
    rep_ = s0.run(replace(base, history=ps, decisions=typed(base.decisions, D8=None if cutover is None else
                                                            SD.HD1Cutover(cutover, SD.EXCLUDE, SD.EXCLUDE_PRE_CUTOVER))))
    return [c for c in codes(rep_) if c.startswith(("LOAD_", "HD1_", "HISTORY_"))]


check("load power wholly before the cut-over: unreliable (WARN)",
      hist(P(s0.LOAD_POWER_MEAN, cut - timedelta(days=5), cut)) == ["LOAD_HISTORY_PRE_HD1_UNRELIABLE"])
check("a period starting before it: straddles (WARN)", hist(P(s0.LOAD_POWER_MEAN, cut - timedelta(days=1), cut + timedelta(days=1))) == ["LOAD_HISTORY_STRADDLES_HD1"])
check("a period after it: INFO only", hist(P(s0.LOAD_POWER_MEAN, cut, cut + timedelta(days=1))) == ["LOAD_HISTORY_POST_HD1"])
check("an unknown cut-over BLOCKS every load-power period",
      hist(P(s0.LOAD_POWER_MEAN, cut, cut + timedelta(days=1)), cutover=None) == ["HD1_CUTOVER_UNKNOWN"])
check("the load energy counter is UNKNOWN whatever the cut-over (cannot be settled offline)",
      hist(P(s0.LOAD_ENERGY_COUNTER, cut, cut + timedelta(days=1))) == ["LOAD_COUNTER_RELIABILITY_UNKNOWN"]
      and hist(P(s0.LOAD_ENERGY_COUNTER, cut - timedelta(days=9), cut)) == ["LOAD_COUNTER_RELIABILITY_UNKNOWN"])
check("an unknown series BLOCKS", hist(P("pv_power_mean", cut, cut + timedelta(days=1))) == ["HISTORY_SERIES_UNKNOWN"])
naive = datetime(2030, 1, 1)
check("a naive period start is refused loudly (ValueError)", raises(lambda: s0.run(replace(base, history=(P(s0.LOAD_POWER_MEAN, naive, cut),)))))
_nv = s0.run(replace(base, history=(P(s0.LOAD_POWER_MEAN, cut - timedelta(days=1), cut),),
                     decisions=typed(base.decisions, D8=SD.HD1Cutover(naive, SD.EXCLUDE, SD.EXCLUDE_PRE_CUTOVER))))
check("a naive cut-over is refused: the typed I-D8 record is INVALID and BLOCKs, and no period is classed against it",
      "DECISION_D8_INVALID" in codes(_nv, s0.BLOCK) and "HD1_CUTOVER_UNKNOWN" in codes(_nv, s0.BLOCK), str(codes(_nv)))
check("an inverted period is refused loudly (ValueError)", raises(lambda: hist(P(s0.LOAD_POWER_MEAN, cut, cut - timedelta(days=1)))))

# ---------------------------------------------------------------------------------------------------------------------
section("[8] the 25 h autumn and 23 h spring UK days and nights")
LON = "Europe/London"
tzl = zone(LON)
p_aut, p_sum = s0.night_profile(date(2026, 10, 25), 30, 330, LON), s0.night_profile(date(2026, 10, 24), 30, 330, LON)
p_spr, p_pre = s0.night_profile(date(2027, 3, 28), 30, 330, LON), s0.night_profile(date(2027, 3, 27), 30, 330, LON)
check("25 Oct 2026: the local day is 25 h and the 00:30-05:30 window lasts 6 h (AUTUMN_BACK)",
      p_aut["local_day_hours"] == 25.0 and p_aut["actual_hours"] == 6.0 and p_aut["clock_change"] == "AUTUMN_BACK", str(p_aut))
check("24 Oct 2026 (the evening before): 24 h day, 5 h window, no change", p_sum["local_day_hours"] == 24.0 and p_sum["actual_hours"] == 5.0
      and p_sum["clock_change"] == "NONE" and p_sum["next_local_day_hours"] == 25.0)
check("28 Mar 2027: the local day is 23 h and the same window lasts 4 h (SPRING_FORWARD)",
      p_spr["local_day_hours"] == 23.0 and p_spr["actual_hours"] == 4.0 and p_spr["clock_change"] == "SPRING_FORWARD", str(p_spr))
check("27 Mar 2027: 24 h day, 5 h window, no change", p_pre["actual_hours"] == 5.0 and p_pre["clock_change"] == "NONE" and p_pre["next_local_day_hours"] == 23.0)
check("an evening-to-morning window 22:00-06:00 spans 9 h across the autumn change and 7 h across the spring change",
      s0.night_profile(date(2026, 10, 24), 22 * 60, 30 * 60, LON)["actual_hours"] == 9.0
      and s0.night_profile(date(2027, 3, 27), 22 * 60, 30 * 60, LON)["actual_hours"] == 7.0)
check("a window that ends before it starts raises ValueError", raises(lambda: s0.night_profile(date(2026, 10, 25), 330, 30, LON)))
for year in range(2026, 2031):
    long_days = [d for d in (date(year, 10, 1) + timedelta(days=i) for i in range(31))
                 if (local_wall(d, 1440, tzl) - local_wall(d, 0, tzl)).total_seconds() == 25 * 3600]
    short_days = [d for d in (date(year, 3, 1) + timedelta(days=i) for i in range(31))
                  if (local_wall(d, 1440, tzl) - local_wall(d, 0, tzl)).total_seconds() == 23 * 3600]
    check(f"{year}: exactly one 25 h day in October and one 23 h day in March, both Sundays",
          len(long_days) == 1 and len(short_days) == 1 and long_days[0].weekday() == 6 and short_days[0].weekday() == 6,
          f"{long_days} {short_days}")
check("the 2026 and 2027 UK clock-change days are 25 Oct 2026 and 28 Mar 2027",
      date(2026, 10, 25) == [d for d in (date(2026, 10, 1) + timedelta(days=i) for i in range(31))
                             if (local_wall(d, 1440, tzl) - local_wall(d, 0, tzl)).total_seconds() == 25 * 3600][0]
      and date(2027, 3, 28) == [d for d in (date(2027, 3, 1) + timedelta(days=i) for i in range(31))
                                if (local_wall(d, 1440, tzl) - local_wall(d, 0, tzl)).total_seconds() == 23 * 3600][0])
rng = s0.check_nights(s0.NightSpec(date(2026, 10, 23), date(2026, 10, 27), 30, 330, LON))
check("the night check flags exactly the autumn night in a range around it", [f.subject for f in rng] == ["2026-10-25"] and rng[0].severity == s0.WARN)
rng2 = s0.check_nights(s0.NightSpec(date(2027, 3, 26), date(2027, 3, 30), 30, 330, LON))
check("... and exactly the spring night", [f.subject for f in rng2] == ["2027-03-28"])
check("ordinary nights produce no night finding", s0.check_nights(s0.NightSpec(date(2026, 10, 1), date(2026, 10, 20), 30, 330, LON)) == [])
check("no NightSpec, no night finding", s0.check_nights(None) == [])

# against the real learner and a flat 1 kWh/h synthetic house (no noise, no SOC)
flat = [1.0] * 24
hist_aut = make_history(date(2026, 9, 20), 60, cfg, seed=1, profile=flat, hour_noise=0.0, day_sigma=0.0, with_soc=False)
obs = {o.night: o.kwh for o in nightly_totals(hist_aut, cfg, 30, 330, date(2026, 10, 22), date(2026, 10, 28))}
check("nightly_totals reports the energy actually used: 5.0 kWh normally, 6.0 kWh on the 25 h night",
      obs[date(2026, 10, 24)] == 5.0 and obs[date(2026, 10, 25)] == 6.0 and obs[date(2026, 10, 26)] == 5.0, str(obs))
check("dividing by the diagnostic's length factor makes the autumn night comparable (6.0 / 1.2 == 5.0)",
      abs(obs[date(2026, 10, 25)] / p_aut["length_factor"] - 5.0) < 1e-9)
hist_spr = make_history(date(2027, 3, 1), 45, cfg, seed=1, profile=flat, hour_noise=0.0, day_sigma=0.0, with_soc=False)
obs2 = {o.night: o.kwh for o in nightly_totals(hist_spr, cfg, 30, 330, date(2027, 3, 26), date(2027, 3, 30))}
check("... 4.0 kWh on the 23 h night, normalised back to 5.0", obs2[date(2027, 3, 28)] == 4.0 and abs(4.0 / p_spr["length_factor"] - 5.0) < 1e-9, str(obs2))

settings = OvernightSettings.from_site(cfg)
history_obs = [o for o in nightly_totals(hist_aut, cfg, 30, 330, date(2026, 9, 21), date(2026, 11, 5)) if o.night < date(2026, 10, 25)]
adv_aut = learn_overnight(history_obs, date(2026, 10, 25), settings)
# KNOWN LIMITATION, pinned so it is visible: the learner works on raw totals and does not know the night is an hour longer.
# When a later change makes the learner length-aware this check is expected to fail and should then be replaced.
check("KNOWN LIMITATION: the V1.1 learner plans the 25 h night from ordinary 5 h nights (expected ~5.0 kWh, planning ~5.1 kWh) "
      "although the night will use 6.0 kWh",
      adv_aut.status == "OK" and abs(adv_aut.recommendation["expected_kwh"] - 5.0) < 0.05
      and adv_aut.recommendation["planning_kwh"] < 6.0 - 0.5, str(adv_aut.recommendation))
spr_obs = [o for o in nightly_totals(hist_spr, cfg, 30, 330, date(2027, 3, 2), date(2027, 4, 10)) if o.night < date(2027, 3, 28)]
adv_spr = learn_overnight(spr_obs, date(2027, 3, 28), settings)
check("... and plans the 23 h night at the ordinary level (over-planning, the safe direction)",
      adv_spr.status == "OK" and adv_spr.recommendation["planning_kwh"] > 4.0 + 0.5, str(adv_spr.recommendation))

# ---------------------------------------------------------------------------------------------------------------------
section("[9] owner decisions, verdicts, determinism, loader, CLI")
cl = s0.run(clean())
check("a fully decided, fully consistent declaration is CONSISTENT", cl.verdict == "CONSISTENT" and all(x.status == s0.RECORDED for x in cl.decisions),
      f"{cl.verdict} {[ (x.id,x.status) for x in cl.decisions if x.status != 'RECORDED']}")
nodec = s0.run(replace(clean(), decisions=s0.OwnerDecisions(), history=()))
check("with no decisions recorded the verdict is OPEN_DECISIONS and every owner-input decision is OPEN",
      nodec.verdict == "OPEN_DECISIONS" and [x.id for x in nodec.decisions if x.status == s0.OPEN] == ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"],
      str([(x.id, x.status) for x in nodec.decisions]))
check("D2 is RECORDED only by an explicit, valid I-D2 record (a declared protection reserve alone does not record it)",
      [x for x in nodec.decisions if x.id == "D2"][0].status == s0.OPEN and [x for x in cl.decisions if x.id == "D2"][0].status == s0.RECORDED
      and [x for x in ex.decisions if x.id == "D2"][0].status == s0.OPEN)
check("a recorded decision is echoed exactly as given and nothing is filled in",
      [x for x in cl.decisions if x.id == "D4"][0].recorded == {"pct": 8.0} and [x for x in nodec.decisions if x.id == "D4"][0].recorded is None)
warn_only = s0.run(replace(clean(), capacities=(s0.CapacityDecl("h", "CONFIGURED_HELPER", 20.0),)))
check("decided + a WARN gives CONSISTENT_WITH_WARNINGS", warn_only.verdict == "CONSISTENT_WITH_WARNINGS", warn_only.verdict)
check("a BLOCK outranks open decisions", s0.run(replace(clean(), decisions=s0.OwnerDecisions(),
                                                        readings=())).verdict == "BLOCKED")
check("the report is deterministic (same input, byte-identical JSON)",
      json.dumps(s0.run(s0.example_declaration(True)).to_dict(), sort_keys=True) == json.dumps(s0.run(s0.example_declaration(True)).to_dict(), sort_keys=True))
check("the report is strict JSON (no NaN / Infinity)", json.dumps(s0.run(s0.example_declaration(True)).to_dict(), allow_nan=False) is not None)
fl = s0.run(s0.example_declaration(True))
want = {"PROTECTION_DECLARED_WRITABLE", "CAPACITY_IMPLAUSIBLE", "EFFICIENCY_ONE_WAY_ROUND_TRIP_MIX", "SIGN_CONVENTION_MISMATCH",
        "FALSE_ZERO_SUSPECTED", "UNIT_MISMATCH", "HD1_CUTOVER_UNKNOWN", "CAPACITY_MISMATCH", "NIGHT_LENGTH_DIFFERS",
        "SOURCE_DISAGREEMENT", "CAPACITY_AH_NEEDS_VOLTAGE", "EFFICIENCY_LOOKS_ONE_WAY", "ENFORCEMENT_CLAIM_UNVERIFIED"}
check("the seeded-fault example exhibits every seeded fault", want <= set(codes(fl)), str(want - set(codes(fl))))

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "decl.json"
    p.write_text(json.dumps({
        "reserves": [{"name": "f", "role": "SOFT_PLANNING_FLOOR", "value_pct": 40.0, "source": "s"},
                     {"name": "p", "role": "PHYSICAL_PROTECTION", "value_pct": 10.0, "source": "s"}],
        "capacities": [{"name": "h", "kind": "CONFIGURED_HELPER", "value": 31.7}],
        "efficiencies": [{"name": "e", "value": 90.0, "unit": "percent", "basis": "ROUND_TRIP"}],
        "readings": [{"signal": "battery.soc", "source_id": "r", "kind": "RAW", "value": 50.0, "raw_state": "50", "unit": "%", "age_s": 5.0}],
        "decisions": {"I-D8": {"status": "RECORDED", "provenance": "CALLER_DECLARATION_UNVERIFIED",
                               "value": {"cutover": "2030-03-10T12:00:00+00:00", "load_power_policy": "EXCLUDE",
                                         "load_counter_policy": "EXCLUDE_PRE_CUTOVER"}},
                      "I-D7": {"status": "RECORDED", "provenance": "CALLER_DECLARATION_UNVERIFIED",
                               "value": {"add_signals": {"charge_target": ["battery.soc"]}}}},
        "nights": {"first_night": "2026-10-24", "last_night": "2026-10-26", "start_min": 30, "end_min": 330}}), encoding="utf-8")
    loaded = s0.declaration_from_dict(json.loads(p.read_text(encoding="utf-8")))
    lr = s0.run(loaded)
    check("the declaration loader builds a declaration and the run sees the DST night", "NIGHT_LENGTH_DIFFERS" in codes(lr) and lr.verdict == "OPEN_DECISIONS", lr.verdict)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = s0.main(["--declaration", str(p), "--json"])
    out = json.loads(buf.getvalue())
    check("the CLI prints strict JSON and exits 0 when not BLOCKED", rc == 0 and out["verdict"] == "OPEN_DECISIONS" and out["applies_nothing"] is True)
    bad = Path(td) / "bad.json"
    bad.write_text(json.dumps({"reserves": [], "surprise": 1}), encoding="utf-8")
    try:
        s0.declaration_from_dict(json.loads(bad.read_text(encoding="utf-8"))); strict = False
    except ValueError:
        strict = True
    check("the loader refuses unknown keys", strict)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc2 = s0.main(["--example"])
check("the built-in example is BLOCKED (inverter protection not supplied) and says so in text", rc2 == 1 and "VERDICT: BLOCKED" in buf.getvalue()
      and "nothing above is a recommendation" in buf.getvalue())

# ---------------------------------------------------------------------------------------------------------------------
section("[10] I1: a synthetic example cannot be mistaken for site data or an owner decision")
for label, faulty in (("--example", False), ("--example-faulty", True)):
    r = s0.run(s0.example_declaration(faulty))
    dd = r.to_dict()
    txt = s0.render_text(r)
    check(f"{label}: declaration_origin says synthetic / not site evidence",
          dd["declaration_origin"] == s0.ORIGIN_SYNTHETIC == "SYNTHETIC_EXAMPLE_NOT_SITE_EVIDENCE")
    check(f"{label}: the text output carries the SYNTHETIC EXAMPLE banner above the verdict",
          "SYNTHETIC EXAMPLE: every value below is fictional" in txt and txt.index("SYNTHETIC EXAMPLE:") < txt.index("VERDICT:"))
    recorded = [x for x in r.decisions if x.status == s0.RECORDED]
    check(f"{label}: every RECORDED decision carries provenance SYNTHETIC_EXAMPLE (object and JSON)",
          all(x.provenance == s0.PROV_SYNTHETIC for x in recorded)
          and all(x["provenance"] == "SYNTHETIC_EXAMPLE" for x in dd["decisions"] if x["status"] == s0.RECORDED))
    dlines = [ln for ln in txt.splitlines() if ln.startswith("  D") and ln[3:4].isdigit()]
    rec_lines = [ln for ln in dlines if "[RECORDED" in ln]
    check(f"{label}: every RECORDED decision line says it is a synthetic example, not an owner decision",
          len(rec_lines) == len(recorded) and all("SYNTHETIC EXAMPLE, NOT AN OWNER DECISION" in ln for ln in rec_lines), str(rec_lines))
    check(f"{label}: nine decision lines; an OPEN decision carries no provenance and is plainly OPEN",
          len(dlines) == 9 and all(x.provenance == "" for x in r.decisions if x.status == s0.OPEN)
          and all("[OPEN" in ln for ln in dlines if "[RECORDED" not in ln))
    decl = s0.example_declaration(faulty)
    check(f"{label}: every named reserve / capacity / efficiency item is prefixed [SYNTHETIC], every reading source synthetic:",
          all(x.name.startswith("[SYNTHETIC] ") for x in decl.reserves + decl.capacities + decl.efficiencies)
          and all(x.source_id.startswith("synthetic:") for x in decl.readings))
    check(f"{label}: the verdict is still BLOCKED (fail-closed semantics unchanged)", r.verdict == "BLOCKED")
r_ex = s0.run(s0.example_declaration())
d8 = [x for x in r_ex.decisions if x.id == "D8"][0]
check("I1 regression: D8 in --example is RECORDED but marked as a synthetic example (fictional 2030 cut-over)",
      d8.status == s0.RECORDED and d8.provenance == "SYNTHETIC_EXAMPLE" and "2030" in str(d8.recorded)
      and "D8 [RECORDED - SYNTHETIC EXAMPLE, NOT AN OWNER DECISION]" in s0.render_text(r_ex))
real = s0.run(clean())
rtxt = s0.render_text(real)
check("a caller's own declaration is labelled CALLER_DECLARATION and gets no synthetic banner",
      real.origin == s0.ORIGIN_CALLER and "SYNTHETIC EXAMPLE:" not in rtxt and "SYNTHETIC EXAMPLE, NOT AN OWNER" not in rtxt
      and all(x.provenance == s0.PROV_CALLER for x in real.decisions if x.status == s0.RECORDED))
check("... and its origin says the tool did not verify it against the site", "NOT_VERIFIED_AGAINST_THE_SITE" in real.origin)
check("the loader flag synthetic_example=true labels a hand-written file as synthetic; absent, it is a caller declaration",
      s0.declaration_from_dict({"synthetic_example": True}).synthetic is True and s0.declaration_from_dict({}).synthetic is False)
check("a declaration flagged synthetic is always reported as a synthetic example",
      s0.run(replace(clean(), synthetic=True)).origin == s0.ORIGIN_SYNTHETIC)

section("[10] I2: DRAFT / D1-D9 OPEN / PROPOSED / SHADOW-only / not-runtime-policy wording")
check("the report notice carries every required phrase",
      all(n in s0.DRAFT_NOTICE for n in ("DRAFT S0", "D1-D9", "OPEN", "PROPOSED", "SHADOW-only", "NOT configured runtime policy")),
      s0.DRAFT_NOTICE)
for label, r in (("example", r_ex), ("caller declaration", real)):
    check(f"{label}: JSON status is DRAFT_S0 and the notice is present",
          r.to_dict()["status"] == "DRAFT_S0" and r.to_dict()["notice"] == s0.DRAFT_NOTICE)
    check(f"{label}: the text output's first lines carry the draft notice", s0.DRAFT_NOTICE in "\n".join(s0.render_text(r).splitlines()[:3]))
tool_doc = ast.get_docstring(tool_tree)
check("the tool's module docstring opens with DRAFT / D1-D9 OPEN and says NOT configured runtime policy",
      "DRAFT" in tool_doc.splitlines()[0] and "D1-D9 OPEN" in tool_doc.splitlines()[0] and "NOT configured runtime policy" in tool_doc[:400])
check("the model version still says draft", s0.MODEL_VERSION.endswith("-draft"))
buf_h = io.StringIO()
with contextlib.redirect_stdout(buf_h):
    s0.main(["--example"])
check("CLI --example output carries the draft notice on its second line", buf_h.getvalue().splitlines()[1] == s0.DRAFT_NOTICE)
if DOC.is_file():
    doc_lines = DOC.read_text(encoding="utf-8").splitlines()
    head = " ".join(ln.lstrip("> ").strip() for ln in doc_lines[:12])  # unwrap the quoted block
    body = "\n".join(doc_lines)
    check("the document title and first block say DRAFT, D1-D9 OPEN, PROPOSED, SHADOW-only and NOT configured runtime policy",
          doc_lines[0].startswith("# ") and "DRAFT" in doc_lines[0] and "D1-D9 OPEN" in doc_lines[0]
          and all(n in head for n in ("thresholds PROPOSED", "offline, SHADOW-only", "NOT configured runtime policy")), head)
    check("the document's first block says the examples are fictional, not site evidence and not an owner decision",
          "fictional" in head and "not site evidence" in head and "not an owner decision" in head)
    check("the document tells the later PR to use the same wording and offers a title",
          "Wording the later pull request must use" in body and "Suggested title: `Intelligence S0 (DRAFT)" in body
          and "decisions D1-D9 open, not runtime policy" in body)
    check("the document states the expected BLOCKED examples and the local-environment note",
          "Expected outputs and local-environment notes" in body and "core.autocrlf=true" in body)
    rows = [ln for ln in doc_lines if ln[:6] in {f"| D{i} |" for i in range(1, 10)}]
    check("all nine decisions in the register are still OPEN",
          len(rows) == 9 and all(ln.rstrip().rstrip("|").rstrip().endswith(("OPEN", "OPEN (proposal only)")) for ln in rows), str(len(rows)))

section("[11] typed decisions, I-D labels and DST refusals (foundation reconciliation)")
PC = s0.PROV_CALLER
ft = s0.declaration_from_dict({"decisions": {"I-D1": {"provenance": PC, "value": "SiteConfig.user_reserve_soc_pct"},
                                             "D9": {"provenance": PC, "value": "NORMALISE_PER_HOUR"}}})
ft_rep = s0.run(replace(clean(), decisions=ft.decisions))
check("free-text decisions are INVALID, never RECORDED, and BLOCK the verdict",
      ft.decisions.status("D1") == s0.INVALID and ft.decisions.status("D9") == s0.INVALID
      and {"DECISION_D1_INVALID", "DECISION_D9_INVALID"} <= set(codes(ft_rep, s0.BLOCK)) and ft_rep.verdict == "BLOCKED", str(codes(ft_rep)))
for junk in ("garbage", 42):
    dj = s0.declaration_from_dict({"decisions": {"I-D9": {"provenance": PC, "value": junk}}})
    rj = s0.run(replace(clean(), decisions=dj.decisions))
    check(f"I-D9 {junk!r} is INVALID and BLOCKs", dj.decisions.status("D9") == s0.INVALID and "DECISION_D9_INVALID" in codes(rj, s0.BLOCK))
for hr in SD.DST_HISTORY_RULES:
    for tr in SD.DST_TARGET_RULES:
        check(f"I-D9 history rule {hr} + target rule {tr} is a valid split record",
              typed(D9=SD.DSTPolicy(hr, tr)).status("D9") == s0.RECORDED)
check("I-D9 with an unknown half is INVALID (each half is validated)",
      typed(D9=SD.DSTPolicy("NORMALISE_PER_HOUR", SD.SCALE_UP_ONLY)).status("D9") == s0.INVALID
      and typed(D9=SD.DSTPolicy(SD.NORMALISE_TO_NOMINAL, "PLAN_OWN_LENGTH")).status("D9") == s0.INVALID)
hh = s0.run(replace(clean(), decisions=typed(clean().decisions, D1=SD.PlanningFloor(SD.HA_RESERVE_HELPER, None, True))))
check("HA_RESERVE_HELPER is accepted as the I-D1 source", [x for x in hh.decisions if x.id == "D1"][0].status == s0.RECORDED
      and hh.verdict == "CONSISTENT", hh.verdict)
check("an OWNER_RECORD in a caller declaration is refused (INVALID: only the site-local file carries one)",
      s0.declaration_from_dict({"decisions": {"I-D4": {"provenance": "OWNER_RECORD", "record_ref": "REC-20300101-band-test",
                                                       "value": {"pct": 8.0}}}}).decisions.status("D4") == s0.INVALID)
check("an explicit I-D2 owner statement that disagrees with the declared protection level BLOCKs",
      "PROTECTION_RECORD_MISMATCH" in codes(s0.run(replace(clean(), decisions=typed(clean().decisions, D2=SD.Protection(SD.OWNER_STATEMENT, 20.0, cut)))), s0.BLOCK))
check("the spring-gap window (01:00-02:00 on 28 Mar 2027, factor 0) is refused by night_profile",
      raises(lambda: s0.night_profile(date(2027, 3, 28), 60, 120, LON)))
gap = s0.check_nights(s0.NightSpec(date(2027, 3, 26), date(2027, 3, 30), 60, 120, LON))
check("... and a night range over it BLOCKs exactly that night instead of raising (no factor-0 figure)",
      [(f.code, f.subject) for f in gap if f.severity == s0.BLOCK] == [("NIGHT_WINDOW_HAS_NO_LENGTH", "2027-03-28")], str(gap))
amb_n = s0.check_nights(s0.NightSpec(date(2026, 10, 24), date(2026, 10, 26), 90, 330, LON))
check("a window boundary in the repeated hour BLOCKs (the fixed I-D9 rule)",
      [(f.code, f.subject) for f in amb_n if f.severity == s0.BLOCK] == [("NIGHT_BOUNDARY_IN_CHANGED_HOUR", "2026-10-25")], str(amb_n))
check("the night profile's numbers come from intelligence.periods",
      s0.night_profile(date(2026, 10, 25), 30, 330, LON)["length_factor"] == SD_P.period_profile(date(2026, 10, 25), 30, 330).factor)
check("every decision's blocks are the items site_decisions.ITEM_GATES says it gates",
      all(x.blocks == SD.items_gated_by(x.id) for x in cl.decisions))
txt_cl = s0.render_text(cl)
check("decision lines show the internal id and the I-D display label", "  D1 I-D1 [RECORDED" in txt_cl and "  D9 I-D9 [" in txt_cl
      and all(x.to_dict()["label"] == f"I-{x.id}" for x in cl.decisions))
check("the retired I-D7 never holds the verdict open", s0.run(replace(clean(), decisions=typed(clean().decisions, D7=None))).verdict == "CONSISTENT")
check("I-D7 is add-only: a declaration cannot drop battery.soc from the required set",
      "battery.soc" in s0.required_signals(typed(D7=SD.RequiredInputsOverride({"charge_target": ("house.power",)}))))

section("document and tool agree")
if DOC.is_file():
    doc = DOC.read_text(encoding="utf-8")
    emitted = sorted({n.args[0].value for n in ast.walk(tool_tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_f"
                      and n.args and isinstance(n.args[0], ast.Constant)})
    missing = [c for c in emitted if c not in doc]
    check(f"the document lists all {len(emitted)} finding codes", not missing, str(missing))
    check("the document states the proposal status of the 8 % band", "PROPOSED" in doc and "8 %" in doc)
    check("the document lists the open decisions D1..D9", all(f"D{i}" in doc for i in range(1, 10)))
    check("the document's reserve rows are current: the ACS1 guarded TOU slot settings editor (not ACS0), the read-only "
          "battery-shutdown sensor written with <slug>, the helper as ACS1's lower bound, 'card JS' not 'script'",
          "ACS0" not in doc and "ACS1 guarded TOU slot settings editor" in doc and "sensor.<slug>_ecco_battery_shutdown" in doc
          and "lower bound" in doc and "Dashboard recommendation card JS" in doc and "Dashboard recommendation script" not in doc)
    check("the document uses the I-D display labels for the register", all(f"| D{i} | I-D{i} |" in doc for i in range(1, 10)))
else:
    check("the input-contract document exists", False, str(DOC))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all S0 input-contract checks passed")
