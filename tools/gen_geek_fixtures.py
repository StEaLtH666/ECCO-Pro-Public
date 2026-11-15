#!/usr/bin/env python3
"""Synthetic Home Assistant state fixtures for the Geek Mode card tests (the ECCO Intelligence SHADOW tab).

    python tools/gen_geek_fixtures.py            # (re)write the fixtures
    python tools/gen_geek_fixtures.py --check    # regenerate in memory and compare with the committed files (exit 1 on drift)

Each fixture is a map  entity_id -> {state, attributes, last_changed, last_updated}  exactly as `hass.states` holds it (a state is
always a text; attributes keep their JSON types; Home Assistant's own standard attributes are included). They are built from the
REAL contract builders (intelligence/advisory_contract.py: assemble_envelope, stale_from, paused_envelope,
self_test_failed_envelope, to_entity_payloads) and the contract fixtures' constructors (intelligence/tests/_gen_contract_fixtures.py),
then wrapped the way Home Assistant publishes them. Every value is SYNTHETIC: fictional 2030 timestamps, invented figures, no site
data. The advice samples carry exactly the key sets the tool computes from the advisors' source (a test and this script refuse a
drift in either direction).

Files written under frontend/ecco-mode-shell/test/fixtures/:
  intelligence.states.healthy.json           every item and forecast OK, a verified tariff, a value, a plan: the richest result
  intelligence.states.mixed.json             a realistic mix: two items OK, one NO_ADVICE, one INSUFFICIENT_DATA, tariff unverified
  intelligence.states.stale.json             the contract's STALE fixture (nothing numeric; last_good carries the history)
  intelligence.states.unavailable.json       every integration entity unavailable (the integration is down)
  intelligence.states.self-test-failed.json  the contract's SELF_TEST_FAILED fixture
  intelligence.states.paused.json            the contract's PAUSED fixture, with the pause switch on
  intelligence.states.watchdog-stale.json    a healthy result that stopped being refreshed: the watchdog is off, the alert has fired
  intelligence.states.contract-breach.json   the healthy result with ONE change: the status entity says mode ASSISTED while its state is OK and the
                                             watchdog is still on (a case the package watchdog turns off for, and the status strip must name)
  intelligence.states.extras.json            healthy plus things nobody declared: an unknown attribute, new ecco_intel_ entities (to be
                                             discovered), and lookalikes outside the prefix (never to be discovered)
  noise.states.json                          a few hundred unrelated entities with secret-looking DECOYS (to prove redaction)
  intelligence.states.meta.json              what each fixture is, and the clock to read it at

The decoys are kept below the thresholds of the repository's own secret scanners (a JWT-shaped text whose segments are short, an
address from a documentation range, a non-routable host) so they can be committed; the card's own tests build the full-size
private-address, MAC and long-token shapes at test time.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import geek_mode_coverage as G  # noqa: E402

UTC = timezone.utc
OUT_REL = G.FIXTURE_DIR_REL
SCHEMA = "ecco-geek-fixtures/1"

# ---------------------------------------------------------------------------------------------------------------------
# synthetic advice samples: every key of every advice shape (values are invented)
# ---------------------------------------------------------------------------------------------------------------------

RESERVE = {"user_reserve_pct": 40.0, "technical_min_pct": 10.0, "ha_reserve_pct": None, "effective_pct": 40.0,
           "binding": "user_reserve", "override_code": None, "override_reason": None}
WINDOW = ["2030-01-15T23:30:00+00:00", "2030-01-16T05:30:00+00:00"]

SAMPLES = {
    "charge_target": {
        "target_soc_pct": 80.0, "raw_target_soc_pct": 77.42, "binding_constraint": "DEMAND", "shortfall_soc_pct": 0.0,
        "conservative_fallback": False, "effective_reserve_pct": 40.0, "buffer_pct": 5.0, "end_of_period_floor_pct": 45.0,
        "desired_morning_soc_pct": None, "reserve": RESERVE, "demand_planning_kwh": 6.4, "demand_expected_kwh": 6.1,
        "pv_credit_used_kwh": 0.0, "net_need_kwh": 6.4, "need_soc_pct": 32.42, "window": WINDOW, "achievable_soc_pct": 95.0,
        "grid_charge_kwh": 4.8, "window_start_soc_pct": 52.0, "window_start_soc_source": "predicted SOC (synthetic fixture)",
        "inputs_used": {"end_floor_pct": 45.0, "demand_planning_kwh": 6.4, "pv_credit_used_kwh": 0.0, "battery_capacity_kwh": 10.0,
                        "eta_one_way": 0.96},
        "changed_from_previous": {"previous_target_soc_pct": 80.0, "target_soc_pct": 80.0, "delta_pct": 0.0, "drivers": [],
                                  "unexplained_by_inputs_pct": 0.0,
                                  "note": "effects are on the unrounded target; the remainder is rounding to the target step and caps"}},
    "overnight_demand": {
        "expected_kwh": 6.1, "planning_kwh": 6.4, "planning_quantile": 0.9, "learned_kwh": 6.0, "nights_used": 14,
        "nights_window": 28, "latest_night": "2030-01-14", "nights_missing_since_latest": 0, "nights_clipped": [],
        "nights_excluded": {}, "nights_invalid": 0, "prior_kwh": None, "prior_weight": 0.0, "regime": "NORMAL",
        "recent_median_kwh": 6.0, "baseline_median_kwh": 6.2, "recent_to_baseline_ratio": 0.968, "recent_robust_z": -0.3,
        "conservative_fallback": False},
    "export_event": {
        "event": {"label": "SYNTHETIC EVENT", "start": "2030-01-15T22:00:00+00:00", "end": "2030-01-15T23:00:00+00:00",
                  "started": False, "remaining_hours": 2.0},
        "cover_household_from_battery": True, "export_advised": True, "export_kwh": 3.2, "export_kw_avg": 3.2,
        "binding_constraint": "ENERGY_ABOVE_RESERVE", "soc_at_start_pct": 90.0, "soc_at_end_expected_pct": 60.0,
        "effective_reserve_pct": 40.0, "desired_min_pct": 45.0, "reserve": RESERVE, "energy_above_minimum_kwh": 4.3,
        "keep_for_after_kwh": 0.5, "household_during_kwh": 0.6, "energy_for_export_kwh": 3.2},
    "dump_to_grid": {
        "dump_advisable": True, "stop_soc_pct": 60.0, "raw_stop_soc_pct": 58.3, "export_kwh": 2.1, "export_kw_avg": 2.1,
        "stop_set_by": "RESERVE_AND_DEMAND", "export_limited_by": "STOP_LEVEL", "soc_pct": 85.0, "effective_reserve_pct": 40.0,
        "desired_min_pct": 45.0, "reserve": RESERVE, "keep_until_refill_kwh": 1.4, "keep_soc_pct": 14.6,
        "refill_at": "2030-01-15T23:30:00+00:00", "feature_stop_bounds_pct": [10, 90]},
    "predicted_day_load": {
        "kind": "day", "t0": "2030-01-16T00:00:00+00:00", "t1": "2030-01-17T00:00:00+00:00", "p10": 11.0, "p50": 14.2, "p90": 17.5,
        "n_days": 14, "n_residuals": 10, "confidence": 0.62, "label": "MEDIUM", "usable": True},
    "pv_tomorrow": {
        "inflation": 1.0, "usable": True, "day": "2030-01-16", "source": "synthetic-forecast", "raw_kwh": 9.4, "ratio": 1.04,
        "p10": 6.1, "p50": 9.8, "p90": 12.4, "n_pairs": 12, "mae_corrected": 1.1, "mae_raw": 1.6, "confidence": 0.4, "label": "LOW",
        "notes": ["synthetic fixture value"], "plausibility": {"verdict": "PLAUSIBLE", "ceiling_kwh": 20.0, "rejected": []}},
    "predicted_morning_soc": {
        "at": "2030-01-16T07:00:00+00:00", "planned_window_end_soc_pct": 80.0,
        "basis": "the V1.1 charge target reached at the window end, then the forecast load and PV, with the effective reserve held"},
}
ENGINE_COMPARISON = {"v1_target_soc_pct": 85.0, "v11_target_soc_pct": 80.0, "difference_pct": 5.0,
                     "v1_feasible_on_pessimistic_path": True, "authority": "V1.1 charge_target",
                     "basis": "V1 hourly simulation versus the V1.1 closed-form budget, both on the decided configuration"}
TARIFF_VERIFIED = {"provenance": "VERIFIED", "window": {"start": WINDOW[0], "end": WINDOW[1]}, "price_range": [7.5, 24.5]}
TARIFF_UNVERIFIED = {"provenance": "UNVERIFIED", "window": None, "price_range": None}
VALUE = {"range_gbp": [0.1, 0.45], "assumptions": ["Projected on forecasts; synthetic data gives no real-data claim.",
                                                    "Rates as the verified tariff states them; VAT and standing charge excluded."],
         "baselines": {"ALWAYS_100": [0.1, 0.45], "HOLD_CURRENT": [0.05, 0.3]}}
PLAN = {"precharge_by": "2030-01-15T23:00:00+00:00", "headroom_ceiling_pct": 92.0, "reserve_runout_at": None}
ACCURACY = {"mae_7d": 1.2, "coverage_7d": 0.8, "n": 7}
INPUT_AGES = tuple({"name": n, "age_s": a, "limit_s": lim, "status": st} for n, a, lim, st in (
    ("battery.soc", 40.0, 900.0, "fresh"), ("pv.forecast_tomorrow_kwh", 3000.0, 3600.0, "fresh"),
    ("tariff.import_rates", 7300.0, 7200.0, "stale"), ("tou.slot_table", None, 3600.0, "unknown"), ("capacity.helper_kwh", None, None, "missing")))
SELF_TEST_PASS = {"ENTITY_IDS": "PASS", "ZONEINFO": "PASS", "VENDOR_MANIFEST": "PASS"}

NOW = None          # set from the contract fixture module in contract()
STAMP_OLD = "2030-01-10T09:00:00+00:00"


class Contract:
    """The real contract builders and the contract fixtures' constructors, loaded from this repository."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ac, self.sd, self.dp = G.load_contract(root)
        self.gen = G._load_module(root, "intelligence/tests/_gen_contract_fixtures.py", "_geek_contract_fixture_builders_gen")
        self.universe = G.build_universe(root)
        self.names = G.universe_friendly_names(root)
        self.main, self.pre = G._package_entities(root)
        for key, sample in SAMPLES.items():
            want = {p.split(".", 1)[1] for p, i in self.universe.by_ident()[f"intel.{key}"].attrs.items() if p.startswith("advice.") and i["shape"] == "ok"}
            if set(sample) != want:
                raise SystemExit(f"gen_geek_fixtures: the {key} advice sample and the advice keys computed from the code differ "
                                 f"(sample only: {sorted(set(sample) - want)}; code only: {sorted(want - set(sample))})")
        eng = {p.split(".", 1)[1] for p in self.universe.by_ident()["intel.charge_target"].attrs if p.startswith("engine_comparison.")}
        if set(ENGINE_COMPARISON) != eng:
            raise SystemExit("gen_geek_fixtures: the engine comparison sample and the code differ")

    # ---- envelopes (real constructors) ----
    def _items(self, *, mixed: bool):
        ac, gen = self.ac, self.gen
        v = gen.VALID
        ct = ac.ItemView("charge_target", ac.ItemStatus.OK, 80.0, v, "MEDIUM", (), ("SYNTHETIC_FIXTURE",), SAMPLES["charge_target"])
        on = ac.ItemView("overnight_demand", ac.ItemStatus.OK, 6.4, v, "HIGH", (), ("SYNTHETIC_FIXTURE",), SAMPLES["overnight_demand"])
        if mixed:
            ex = ac.ItemView("export_event", ac.ItemStatus.NO_ADVICE, reason_codes=("NO_EVENT",))
            dg = ac.ItemView("dump_to_grid", ac.ItemStatus.INSUFFICIENT_DATA, confidence="INSUFFICIENT", reason_codes=("NO_REFILL_WINDOW",))
        else:
            ex = ac.ItemView("export_event", ac.ItemStatus.OK, 3.2, v, "MEDIUM", (), ("SYNTHETIC_FIXTURE",), SAMPLES["export_event"])
            dg = ac.ItemView("dump_to_grid", ac.ItemStatus.OK, 2.1, v, "LOW", (), ("SYNTHETIC_FIXTURE",), SAMPLES["dump_to_grid"])
        fc = (ac.ForecastView("predicted_day_load", ac.ItemStatus.OK, 14.2, 11.0, 17.5, v, "MEDIUM", (), ("SYNTHETIC_FIXTURE",),
                              SAMPLES["predicted_day_load"]),
              ac.ForecastView("pv_tomorrow", ac.ItemStatus.OK, 9.8, 6.1, 12.4, v, "LOW", (), ("SYNTHETIC_FIXTURE",), SAMPLES["pv_tomorrow"]),
              ac.ForecastView("predicted_morning_soc", ac.ItemStatus.OK, 72.0, None, None, v, "MEDIUM", (), ("SYNTHETIC_FIXTURE",),
                              SAMPLES["predicted_morning_soc"]))
        return (ct, on, ex, dg), fc

    def healthy(self):
        ac, gen = self.ac, self.gen
        items, fc = self._items(mixed=False)
        return ac.assemble_envelope(
            gen.NOW, gen.VERSIONS, items=items, forecasts=fc, data_quality=ac.DataQuality.OK, decisions=gen._synthetic_decisions(),
            accept_provenance=frozenset({self.sd.Provenance.SYNTHETIC_TEST}), paused=False, valid_until=gen.VALID, next_run_at=gen.NEXT,
            reason_codes=("SYNTHETIC_FIXTURE",), self_test=SELF_TEST_PASS, input_ages=INPUT_AGES, tariff=TARIFF_VERIFIED, value=VALUE,
            plan=PLAN, accuracy=ACCURACY, engine_comparison=ENGINE_COMPARISON, scorecard_report={"days": 7, "kinds": ["day_load"]})

    def mixed(self):
        ac, gen = self.ac, self.gen
        items, fc = self._items(mixed=True)
        return ac.assemble_envelope(
            gen.NOW, gen.VERSIONS, items=items, forecasts=fc, data_quality=ac.DataQuality.DEGRADED, decisions=gen._synthetic_decisions(),
            accept_provenance=frozenset({self.sd.Provenance.SYNTHETIC_TEST}), paused=False, valid_until=gen.VALID, next_run_at=gen.NEXT,
            reason_codes=("SYNTHETIC_FIXTURE",), self_test=SELF_TEST_PASS, input_ages=INPUT_AGES, tariff=TARIFF_UNVERIFIED, plan=PLAN,
            accuracy=ACCURACY, engine_comparison=ENGINE_COMPARISON)

    # ---- wrapping the payloads the way Home Assistant publishes them ----
    def _ha_state(self, value) -> str:
        if value is None:
            return "unknown"
        if value is True:
            return "on"
        if value is False:
            return "off"
        return str(value)

    def _integration_states(self, env, stamp: str) -> dict:
        ac, u = self.ac, self.universe
        by_eid = {e.entity_id: e for e in u.entities}
        out = {}
        for eid, (state, rec, unrec) in ac.to_entity_payloads(env).items():
            ent = by_eid[eid]
            attrs = {**rec, **unrec}
            attrs["friendly_name"] = self.names[eid]
            if "unit_of_measurement" in ent.attrs and ent.unit:
                attrs["unit_of_measurement"] = ent.unit
            if "device_class" in ent.attrs:
                attrs["device_class"] = "enum"
            if "options" in ent.attrs:
                attrs["options"] = list(ac.SystemStatus.ALL if ent.kind == "status" else ac.DataQuality.ALL)
            extra = set(attrs) - set(ent.attrs)
            if extra:
                raise SystemExit(f"gen_geek_fixtures: {eid} carries attributes no source declares: {sorted(extra)}")
            out[eid] = {"state": self._ha_state(state), "attributes": dict(sorted(attrs.items())), "last_changed": stamp, "last_updated": stamp}
        return out

    def _package_states(self, *, paused: bool, watchdog: bool, triggered: dict | None = None, watchdog_changed: str | None = None,
                        paused_changed: str | None = None) -> dict:
        out = {}
        triggered = triggered or {}
        for domain, obj, spec, name_key in self.main + self.pre:
            eid = f"{domain}.{obj}"
            attrs = {"friendly_name": spec[name_key]}
            changed = STAMP_OLD
            if domain == "input_boolean":
                state, attrs["editable"] = ("on" if paused else "off"), False
                changed = paused_changed or STAMP_OLD
            elif domain == "binary_sensor":
                state = "on" if watchdog else "off"
                changed = watchdog_changed or STAMP_OLD
            elif domain == "automation":
                state = "on"
                attrs.update({"current": 0, "id": spec["id"], "last_triggered": triggered.get(spec["id"]), "mode": spec.get("mode", "single")})
            elif domain == "input_number":
                state = "0.0"
                attrs.update({"initial": None, "editable": False})
            else:
                raise SystemExit(f"gen_geek_fixtures: unexpected package domain {domain}")
            for k in G.YAML_HELPER_ATTRIBUTES:
                if k in spec and domain != "automation":
                    attrs[k] = spec[k]
            out[eid] = {"state": state, "attributes": dict(sorted(attrs.items())), "last_changed": changed, "last_updated": changed}
        return out

    def states(self, env, *, paused=False, watchdog=True, stamp=None, **kw) -> dict:
        stamp = stamp or env.generated_at.isoformat()
        out = self._integration_states(env, stamp)
        out.update(self._package_states(paused=paused, watchdog=watchdog, **kw))
        return dict(sorted(out.items()))

    def unavailable(self) -> dict:
        stamp = self.gen.NOW.isoformat()
        out = {e.entity_id: {"state": "unavailable", "attributes": {"friendly_name": self.names[e.entity_id]}, "last_changed": stamp,
                             "last_updated": stamp} for e in self.universe.entities if e.origin == "integration"}
        out.update(self._package_states(paused=False, watchdog=False))
        return dict(sorted(out.items()))


def intelligence_fixtures(c: Contract) -> tuple[dict, dict]:
    """({name: states}, {name: meta})"""
    gen = c.gen
    t0 = gen.NOW
    iso = lambda t: t.isoformat()  # noqa: E731
    healthy_env = c.healthy()
    fx: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    fx["healthy"] = c.states(healthy_env)
    meta["healthy"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "OK",
                       "what": "Every item and forecast OK, a verified tariff, a value, a plan: the richest result. Read it 30 s after it was published."}
    fx["mixed"] = c.states(c.mixed())
    meta["mixed"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "OK",
                     "what": "A realistic mix: two items OK, one NO_ADVICE, one INSUFFICIENT_DATA, data quality DEGRADED, tariff unverified."}
    stale_env = gen.stale()
    fx["stale"] = c.states(stale_env, watchdog=False)
    meta["stale"] = {"reference_now": iso(stale_env.generated_at + timedelta(seconds=30)), "status": "STALE",
                     "what": "The contract's STALE fixture: nothing numeric; last_good carries the earlier values with their time."}
    fx["unavailable"] = c.unavailable()
    meta["unavailable"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "unavailable",
                           "what": "Every integration entity is unavailable (the integration is down); the watchdog is off."}
    stf_env = gen.self_test_failed()
    fx["self-test-failed"] = c.states(stf_env, watchdog=False, triggered={"ecco_intel_alert_self_test_failed": iso(t0 + timedelta(seconds=5))})
    meta["self-test-failed"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "SELF_TEST_FAILED",
                                "what": "The contract's SELF_TEST_FAILED fixture: no advice, the failed check is in self_test; the alert automation has run."}
    paused_env = gen.paused()
    fx["paused"] = c.states(paused_env, paused=True, paused_changed="2030-01-15T20:55:00+00:00")
    meta["paused"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "PAUSED",
                      "what": "The contract's PAUSED fixture: the pause switch is on, the watchdog is on, no advice."}
    wd = c.states(healthy_env, watchdog=False, watchdog_changed=iso(t0 + timedelta(minutes=20)),
                  triggered={"ecco_intel_alert_watchdog_stale": iso(t0 + timedelta(minutes=50))})
    fx["watchdog-stale"] = wd
    meta["watchdog-stale"] = {"reference_now": iso(t0 + timedelta(minutes=55)), "status": "OK",
                              "what": "A healthy result that stopped being refreshed: its states are 55 minutes old at the reference time, the watchdog turned "
                                      "off 20 minutes after it, and the stale alert automation ran 30 minutes after that."}
    ex = json.loads(json.dumps(fx["healthy"]))
    stamp = iso(t0)
    ex["sensor.ecco_intel_status"]["attributes"]["zz_future_attribute"] = "an attribute nobody declared"
    ex["sensor.ecco_intel_status"]["attributes"] = dict(sorted(ex["sensor.ecco_intel_status"]["attributes"].items()))
    new = {
        "sensor.ecco_intel_future_probe": ("12.5", {"friendly_name": "ECCO Intel future probe (synthetic)", "unit_of_measurement": "kWh",
                                                    "simulated": True, "future_note": "a new safe entity the catalogue does not know"}),
        "binary_sensor.ecco_intel_future_flag": ("on", {"friendly_name": "ECCO Intel future flag (synthetic)"}),
        "automation.ecco_intel_alert_future_check": ("on", {"friendly_name": "ECCO Intel - alert: future check (synthetic)", "current": 0,
                                                            "id": "ecco_intel_alert_future_check", "last_triggered": None, "mode": "single"}),
        "input_number.ecco_intel_future_knob": ("3.0", {"friendly_name": "ECCO Intel future knob (synthetic)", "min": 0, "max": 10, "step": 1,
                                                        "mode": "box", "editable": True, "initial": None}),
    }
    for eid, (st, at) in new.items():
        ex[eid] = {"state": st, "attributes": dict(sorted(at.items())), "last_changed": stamp, "last_updated": stamp}
    look = {
        "sensor.ecco_intelligence_status": "the frozen V1 prototype's id family (ecco_intelligence_), not this contract",
        "sensor.xecco_intel_foo": "the name contains the prefix but does not start with it",
        "sensor.ecco_intel": "no underscore after intel",
        "light.ecco_intel_lamp": "right name prefix, a domain that is not in the discovery list",
        "sensor.ecco_other_thing": "another ECCO family",
    }
    for eid in look:
        ex[eid] = {"state": "1", "attributes": {"friendly_name": "lookalike (synthetic): must not be discovered"}, "last_changed": stamp,
                   "last_updated": stamp}
    # the status entity says a mode other than SHADOW, yet its state is OK and the watchdog is on: the offline fixtures used to model only the
    # cases where the watchdog had already turned off. Built from the healthy fixture with one attribute changed (the contract builders refuse a
    # non-SHADOW envelope by design, so this one cannot come from them).
    cb = json.loads(json.dumps(fx["healthy"]))
    cb["sensor.ecco_intel_status"]["attributes"]["mode"] = "ASSISTED"
    fx["contract-breach"] = dict(sorted(cb.items()))
    meta["contract-breach"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "OK",
                               "what": "The healthy result with one change: the status entity says mode ASSISTED (the contract says SHADOW) while its state is OK and the "
                                       "watchdog is still on. The strip must raise a critical line for it in both modes."}
    fx["extras"] = dict(sorted(ex.items()))
    meta["extras"] = {"reference_now": iso(t0 + timedelta(seconds=30)), "status": "OK",
                      "what": "Healthy plus: one attribute nobody declared (status.zz_future_attribute), four new ecco_intel_ entities that must be discovered "
                              "automatically (one carries a simulated flag), and five lookalikes that must NOT be discovered.",
                      "must_discover": sorted(new), "must_not_discover": sorted(look)}
    return fx, meta


# ---------------------------------------------------------------------------------------------------------------------
# the noise fixture
# ---------------------------------------------------------------------------------------------------------------------

_WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
          "oscar", "papa")
_KINDS = ("temperature", "humidity", "power", "energy", "voltage", "current", "battery", "signal", "pressure", "illuminance")


def _lcg(seed: int):
    x = seed
    while True:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        yield x


def noise_states() -> dict:
    """Unrelated entities (deterministic), then the explicit decoys."""
    rnd = _lcg(20300115)
    stamp = "2030-01-15T20:59:00+00:00"
    out: dict[str, dict] = {}

    def put(eid, state, attrs):
        out[eid] = {"state": state, "attributes": dict(sorted(attrs.items())), "last_changed": stamp, "last_updated": stamp}

    plan = (("sensor", 150), ("binary_sensor", 40), ("light", 30), ("switch", 30), ("input_number", 15), ("automation", 15), ("script", 10),
            ("climate", 10), ("update", 8), ("media_player", 6))
    for domain, count in plan:
        for i in range(count):
            r = next(rnd)
            word = _WORDS[r % len(_WORDS)]
            kind = _KINDS[(r >> 8) % len(_KINDS)]
            eid = f"{domain}.noise_{word}_{kind}_{i:03d}"
            if domain == "sensor":
                put(eid, f"{(r >> 4) % 1000 / 10:.1f}", {"friendly_name": f"Noise {word} {kind} {i}", "unit_of_measurement": "u", "state_class": "measurement"})
            elif domain in ("binary_sensor", "light", "switch"):
                put(eid, "on" if r % 2 else "off", {"friendly_name": f"Noise {word} {i}"})
            elif domain == "input_number":
                put(eid, f"{r % 100}.0", {"friendly_name": f"Noise number {i}", "min": 0, "max": 100, "step": 1, "mode": "box", "editable": True})
            elif domain == "automation":
                put(eid, "on", {"friendly_name": f"Noise automation {i}", "current": 0, "id": f"noise_automation_{i:03d}", "last_triggered": None, "mode": "single"})
            elif domain == "script":
                put(eid, "off", {"friendly_name": f"Noise script {i}", "mode": "single", "current": 0, "last_triggered": None})
            elif domain == "climate":
                put(eid, "heat", {"friendly_name": f"Noise climate {i}", "temperature": 19 + (r % 5), "hvac_modes": ["off", "heat"]})
            elif domain == "update":
                put(eid, "off", {"friendly_name": f"Noise update {i}", "installed_version": "1.0.0", "latest_version": "1.0.0"})
            else:
                put(eid, "idle", {"friendly_name": f"Noise player {i}"})
    # ---- decoys: secret-looking values that must never be shown ----
    d = "SYNTHETIC-DECOY"
    put("sensor.synthetic_decoy_token", "ok", {"friendly_name": "Decoy: token attribute", "access_token": f"{d}-0001-not-a-token"})
    put("sensor.synthetic_decoy_credentials", "ok", {"friendly_name": "Decoy: password and api key", "password": f"{d}-0002", "api_key": f"{d}-0003"})
    put("sensor.synthetic_decoy_jwt", "eyJhbGciOiJub25lIn0.eyJzeW50aGV0aWMiOjF9.c2lnbmF0dXJl", {"friendly_name": "Decoy: a JWT-shaped state"})
    put("sensor.synthetic_decoy_webhook", "ok", {"friendly_name": "Decoy: webhook", "webhook_url": f"https://hooks.example.invalid/api/webhook/{d}-0004"})
    put("sensor.synthetic_decoy_network", "203.0.113.7", {"friendly_name": "Decoy: an address from a documentation range",
                                                          "ip_address": "203.0.113.7", "host": "decoy-host.example.invalid"})
    put("device_tracker.synthetic_decoy_phone", "synthetic_zone", {"friendly_name": "Decoy: a location", "latitude": 1.2345, "longitude": 5.4321,
                                                                    "location": "Synthetic Test Lab", "gps_accuracy": 10})
    put("sensor.synthetic_decoy_connection", "ok", {"friendly_name": "Decoy: connection strings",
                                                    "connection": "postgresql://synthetic:decoy@db.example.invalid:5432/synthetic",
                                                    "broker": "mqtt://synthetic:decoy@broker.example.invalid:1883"})
    put("sensor.synthetic_decoy_url_token", f"https://decoy.example.invalid/feed?token={d}-0008&format=json", {"friendly_name": "Decoy: a token in a URL"})
    put("sensor.synthetic_decoy_blobs", "0123456789abcdef" * 4, {"friendly_name": "Decoy: long hex and base64 blobs",
                                                                 "digest": "fedcba9876543210" * 4,
                                                                 "payload": "U1lOVEhFVElDLURFQ09ZLVBBWUxPQUQtMDAwOS1ub3QtYS1yZWFsLXNlY3JldC12YWx1ZS1hdC1hbGw="})
    put("sensor.synthetic_decoy_nested", "ok", {
        "friendly_name": "Decoy: secrets inside nested values",
        "config": {"client_secret": f"{d}-0010", "nested": {"session_id": f"{d}-0011", "list": [{"bearer": f"{d}-0012"}, {"safe": "visible"}]}},
        "headers": {"Authorization": f"Bearer {d}-0013", "Cookie": f"sid={d}-0014"},
        "private_key_pem_note": f"{d}-0015", "refresh_token": f"{d}-0016"})
    put("sensor.synthetic_decoy_keynames", "ok", {"friendly_name": "Decoy: key NAMES that look secret",
                                                  "eyJhbGciOiJub25lIn0.eyJzeW50aGV0aWMiOjF9.c2lnbmF0dXJl": "a value under a JWT-shaped key name",
                                                  "x-" + "0123456789abcdef" * 3: "a value under a long hex key name"})
    # ---- lookalikes of the prefix, outside it ----
    put("sensor.ecco_intelligence_decoy", "1", {"friendly_name": "lookalike (synthetic): frozen V1 prototype id family"})
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------------------------------------------------

def render(obj) -> bytes:
    return (json.dumps(obj, indent=1, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def build_files(root: Path) -> dict:
    c = Contract(root)
    fx, meta = intelligence_fixtures(c)
    # every declared path is exercised by some fixture; no fixture carries an undeclared attribute (the extras fixture on purpose)
    declared = {(e.entity_id, p) for e in c.universe.entities for p in e.attrs}
    seen = set()
    for name, states in fx.items():
        for eid, row in states.items():
            for a, v in row["attributes"].items():
                seen.add((eid, a))
                if isinstance(v, dict):
                    seen.update((eid, f"{a}.{k}") for k in v)
    missing = sorted(declared - seen)
    if missing:
        raise SystemExit(f"gen_geek_fixtures: no fixture exercises {missing[:8]} (and {max(0, len(missing) - 8)} more)")
    files = {f"{OUT_REL}/intelligence.states.{name}.json": render(states) for name, states in fx.items()}
    files[f"{OUT_REL}/noise.states.json"] = render(noise_states())
    files[f"{OUT_REL}/intelligence.states.meta.json"] = render({
        "schema": SCHEMA, "view_id": G.VIEW_ID,
        "note": "SYNTHETIC fixtures (fictional 2030 values, invented figures, decoys that are not secrets). Generated by tools/gen_geek_fixtures.py.",
        "state_shape": "entity_id -> {state, attributes, last_changed, last_updated}; a state is always a text",
        "fixtures": {name: {"file": f"intelligence.states.{name}.json", **m} for name, m in meta.items()},
        "noise": {"file": "noise.states.json",
                  "what": "A few hundred unrelated entities and secret-looking decoys (synthetic). None is an ecco_intel_ entity."}})
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare with the committed files instead of writing them")
    ap.add_argument("--repo-root", type=Path, default=G.REPO)
    ap.add_argument("--out-root", type=Path, default=None)
    args = ap.parse_args(argv)
    repo = args.repo_root.resolve()
    out = (args.out_root or repo).resolve()
    files = build_files(repo)
    if args.check:
        drift = [rel for rel, data in files.items() if not (out / rel).is_file() or (out / rel).read_bytes() != data]
        if drift:
            print("geek-mode fixtures DRIFT:")
            for d in drift:
                print(f"  {d}")
            print("run: python tools/gen_geek_fixtures.py   (then review the diff)")
            return 1
        print("geek-mode fixtures match a fresh regeneration")
        return 0
    for rel, data in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        print(f"wrote {rel} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
