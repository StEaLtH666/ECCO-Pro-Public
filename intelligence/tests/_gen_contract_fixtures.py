#!/usr/bin/env python3
"""Golden fixtures of the advisory contract `ecco-intel-entities/1`, built from LITERAL envelope constructors (never from
run_cycle), with fictional 2030 timestamps and synthetic values. Each fixture holds the envelope and its entity payloads.

    python intelligence/tests/_gen_contract_fixtures.py            # compare with the committed files (exit 1 on drift)
    python intelligence/tests/_gen_contract_fixtures.py --write    # rewrite them

test_intel_advisory_contract.py regenerates them in memory and requires byte-identical files.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "fixtures" / "advisory_contract"
NAMES = ("all_open_blocked", "synthetic_ok", "stale", "paused", "self_test_failed", "starting")
UTC = timezone.utc
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
VALID = NOW + timedelta(minutes=30)
NEXT = NOW + timedelta(minutes=15)
VERSIONS = ac.Versions("0.1.0-fixture", "intel-v1.1.0-foundation-shadow", "0000000", "fixture00000hash")
SYN = (("SYNTHETIC_FIXTURE", "fictional values for the contract fixture"),)


def _open_blockers(item: str) -> tuple[tuple[str, str], ...]:
    return tuple((f"DECISION_{d}_OPEN", f"{sd.display_label(d)} ({sd.DECISION_TITLES[d]}) is OPEN; this item depends on it")
                 for d in sd.ITEM_GATES[item])


def all_open_blocked() -> ac.AdvisoryEnvelope:
    items = tuple(ac.ItemView(k, ac.ItemStatus.BLOCKED, blockers=_open_blockers(k), reason_codes=("DECISIONS_OPEN",))
                  for k in ac.ADVICE_ITEMS)
    forecasts = (
        ac.ForecastView("predicted_day_load", ac.ItemStatus.BLOCKED, blockers=_open_blockers("predicted_day_load")),
        ac.ForecastView("pv_tomorrow", ac.ItemStatus.INSUFFICIENT_DATA, reason_codes=("NO_FRESH_FORECAST_READING",)),
        ac.ForecastView("predicted_morning_soc", ac.ItemStatus.BLOCKED, blockers=_open_blockers("predicted_morning_soc")),
    )
    return ac.assemble_envelope(NOW, VERSIONS, items=items, forecasts=forecasts, data_quality=ac.DataQuality.OK,
                                decisions=sd.DecisionSet(), paused=False, valid_until=VALID, next_run_at=NEXT,
                                blockers=(("DECISIONS_OPEN", "every I-D decision is OPEN; battery advice is withheld"),),
                                reason_codes=("DECISIONS_OPEN",), self_test={"ENTITY_IDS": "PASS", "ZONEINFO": "PASS"},
                                input_ages=({"name": "battery.soc", "age_s": 40.0, "limit_s": 900.0, "status": "fresh"},))


def _synthetic_decisions() -> sd.DecisionSet:
    t = sd.Provenance.SYNTHETIC_TEST
    ds = sd.DecisionSet()
    for did, v in (("D1", sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 30.0, True)),
                   ("D2", sd.Protection(sd.OWNER_STATEMENT, 12.0, datetime(2030, 1, 1, tzinfo=UTC))),
                   ("D3", sd.CapacityAuthority("CONFIGURED_HELPER", 20.0)), ("D4", sd.CapacityBand(10.0)),
                   ("D5", sd.Efficiency(0.92, sd.FRACTION, sd.ROUND_TRIP)), ("D6", sd.FreshnessOverrides({"house.power": 120.0})),
                   ("D8", sd.HD1Cutover(datetime(2030, 1, 1, tzinfo=UTC), sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER)),
                   ("D9", sd.DSTPolicy(sd.NORMALISE_TO_NOMINAL, sd.SCALE_UP_ONLY))):
        ds = ds.with_decision(did, v, t)
    return ds


def synthetic_ok() -> ac.AdvisoryEnvelope:
    items = (
        ac.ItemView("charge_target", ac.ItemStatus.OK, 80.0, VALID, "MEDIUM", (), ("SYNTHETIC_FIXTURE",),
                    {"target_soc_pct": 80.0, "binding_constraint": "DEMAND"}),
        ac.ItemView("overnight_demand", ac.ItemStatus.OK, 6.4, VALID, "HIGH", (), ("SYNTHETIC_FIXTURE",),
                    {"expected_kwh": 6.1, "planning_kwh": 6.4}),
        ac.ItemView("export_event", ac.ItemStatus.NO_ADVICE, reason_codes=("NO_EVENT",)),
        ac.ItemView("dump_to_grid", ac.ItemStatus.INSUFFICIENT_DATA, confidence="INSUFFICIENT", reason_codes=("NO_REFILL_WINDOW",)),
    )
    forecasts = (
        ac.ForecastView("predicted_day_load", ac.ItemStatus.OK, 14.2, 11.0, 17.5, VALID, "MEDIUM", (), ("SYNTHETIC_FIXTURE",)),
        ac.ForecastView("pv_tomorrow", ac.ItemStatus.OK, 9.8, 6.1, 12.4, VALID, "LOW", (), ("SYNTHETIC_FIXTURE",)),
        ac.ForecastView("predicted_morning_soc", ac.ItemStatus.OK, 72.0, None, None, VALID, "MEDIUM", (), ("SYNTHETIC_FIXTURE",)),
    )
    return ac.assemble_envelope(NOW, VERSIONS, items=items, forecasts=forecasts, data_quality=ac.DataQuality.OK,
                                decisions=_synthetic_decisions(), accept_provenance=frozenset({sd.Provenance.SYNTHETIC_TEST}),
                                paused=False, valid_until=VALID, next_run_at=NEXT, reason_codes=("SYNTHETIC_FIXTURE",),
                                self_test={"ENTITY_IDS": "PASS", "ZONEINFO": "PASS"},
                                input_ages=({"name": "battery.soc", "age_s": 40.0, "limit_s": 900.0, "status": "fresh"},),
                                accuracy={"mae_7d": 1.2, "coverage_7d": 0.8, "n": 7},
                                engine_comparison={"v1_target_soc_pct": 85.0, "difference_pct": 5.0},
                                scorecard_report={"days": 7, "kinds": ["day_load"]})


def stale() -> ac.AdvisoryEnvelope:
    return ac.stale_from(synthetic_ok(), NOW + timedelta(hours=2))


def paused() -> ac.AdvisoryEnvelope:
    return ac.paused_envelope(NOW, VERSIONS, decisions=sd.DecisionSet(), next_run_at=NEXT)


def self_test_failed() -> ac.AdvisoryEnvelope:
    return ac.self_test_failed_envelope(NOW, VERSIONS, {"ENTITY_ID_MISMATCH": "sensor.ecco_intel_status registered with a suffix"})


def starting() -> ac.AdvisoryEnvelope:
    return ac.starting_envelope(NOW, VERSIONS, next_run_at=NEXT)


BUILDERS = {"all_open_blocked": all_open_blocked, "synthetic_ok": synthetic_ok, "stale": stale, "paused": paused,
            "self_test_failed": self_test_failed, "starting": starting}


def render(name: str) -> str:
    env = BUILDERS[name]()
    ents = {eid: {"state": st, "recorded": rec, "unrecorded": un} for eid, (st, rec, un) in ac.to_entity_payloads(env).items()}
    doc = {"fixture": name, "note": "SYNTHETIC contract fixture (fictional 2030 values); not site data, not advice",
           "envelope": env.to_dict(), "entities": ents}
    return json.dumps(doc, indent=1, sort_keys=True, allow_nan=False, ensure_ascii=True) + "\n"


def main(argv: list[str]) -> int:
    write = "--write" in argv
    drift = []
    for name in NAMES:
        text = render(name)
        path = OUT_DIR / f"{name}.json"
        if write:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        elif not path.is_file() or path.read_bytes() != text.encode("utf-8"):
            drift.append(name)
    if drift:
        print("fixtures differ from the constructors:", ", ".join(drift))
        return 1
    print("fixtures written" if write else "fixtures match")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
