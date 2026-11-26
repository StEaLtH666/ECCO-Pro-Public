"""Shared helpers for the runtime suites (tests only): paths, a kit build into a temporary directory, a generic site file
with placeholder-style entity ids (never site values), synthetic states and recorder statistics in the fictional year 2030,
and the L2 harness that runs the BUILT integration under the stand-in Home Assistant (_fake_ha).

Every value here is synthetic. Entity ids use the generic slug 'test_dongle' and 'test_*' names only.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
REPO = TESTS.parents[2]
BUILD_TOOL = REPO / "tools" / "build_ha_integration.py"
UTC = timezone.utc
SLUG = "test_dongle"

def build_kit(out: Path, git_sha: str | None = "0000000", timeout: int = 300) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-I", "-B", str(BUILD_TOOL), "--out", str(out)]
    if git_sha is not None:
        cmd += ["--git-sha", git_sha]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout, env=env)


def tree_hashes(root: Path) -> dict[str, str]:
    """{relative posix path: sha256} of every file under root (directories by a trailing '/')."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for name in sorted(dirnames):
            out[(d / name).relative_to(root).as_posix() + "/"] = "dir"
        for name in sorted(filenames):
            p = d / name
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------------------------------------------------
# a generic site file (placeholders of the 'test_*' form; never site values)
# ---------------------------------------------------------------------------------------------------------------------

def eid(kind: str, name: str) -> str:
    return f"{kind}.{SLUG}_{name}"


# the TOU slot table (schema v2): six slots, each mapping six entities (site-file field -> the entity name suffix the
# dongle's naming would give; generic test ids only)
TOU_SLOT_FIELDS = ("start", "target_soc", "charge_source", "power", "flags_raw", "mode")
TOU_SLOT_SUFFIX = {"start": "time", "target_soc": "soc", "charge_source": "charge", "power": "power",
                   "flags_raw": "raw_flags", "mode": "mode"}
TOU_STARTS = ["01:00", "04:30", "12:00", "16:00", "19:00", "22:00"]      # synthetic; the 01:00-04:30 window is not the example
TOU_GRID_SLOT = 1                                                        # the one grid-charge slot (01:00-04:30)
TOU_SLOT_POWER_W = "5000"                                                # equal to the grid-charge limit: the cap lowers nothing


def slot_eid(i: int, field: str) -> str:
    """The entity mapped to field `field` of TOU slot `i` (1..6)."""
    return eid("sensor", f"timezone{i}_{TOU_SLOT_SUFFIX[field]}")


def tou_slot_spec() -> list[dict]:
    return [{f: slot_eid(i, f) for f in TOU_SLOT_FIELDS} for i in range(1, 7)]


CONFIG_POLL_TEXT = eid("sensor", "last_configuration_update")            # the configuration-poll text (about every 60 s)
CONFIG_ONLINE = eid("binary_sensor", "configuration_online")             # the configuration poll's online flag
TOU_ENABLED = eid("binary_sensor", "time_of_use_enabled")
GRID_CHARGE_ENABLED = eid("binary_sensor", "battery_grid_charge_enabled")
OVERLAY_ENTITIES = [eid("binary_sensor", n) for n in ("free_power_active", "dump_to_grid_active",
                                                      "manual_write_in_progress")]
RESERVE_RAISE_HELPER = "input_number.test_intel_reserve_raise"
CONFIG_POLL_AGE_S = 30                                                   # as the shared cycle fixture: well inside 300 s

SIGNAL_MAP = {
    "battery.soc": {"entity": "sensor.test_canonical_battery_soc"},
    "battery.power": {"entity": eid("sensor", "battery_output_power")},
    "grid.power": {"entity": eid("sensor", "grid_power_ct_clamp")},
    "house.power": {"entity": "sensor.test_canonical_house_power"},
    "pv.power": {"entity": eid("sensor", "pv_power")},
    "inverter.healthy": {"entity": eid("sensor", "inverter_system_state"), "healthy_states": ["Normal"]},
    "reserve.ha_minimum_soc": {"entity": "input_number.test_minimum_reserve_soc"},
}
READING_MAP = {
    "liveness.dongle_poll_changed_at": {"entity": eid("sensor", "last_telemetry_update")},
    "supervision.state": {"entity": "sensor.test_supervision_status"},
    "supervision.stable": {"entity": "binary_sensor.test_supervision_stable"},
    "supervision.heartbeat_age_s": {"entity": "sensor.test_supervision_heartbeat_age"},
    "battery.soc_raw_pct": {"entity": eid("sensor", "battery_soc")},
    "capacity.helper_kwh": {"entity": "input_number.test_battery_model_capacity"},
    "capacity.reg204_ah": {"entity": eid("sensor", "battery_capacity_ah")},
    "efficiency.helper_pct": {"entity": "input_number.test_round_trip_efficiency"},
    "protection.shutdown_soc_pct": {"entity": eid("sensor", "battery_shutdown")},
    "stop.dump_soc_pct": {"entity": eid("sensor", "dump_stop_soc")},
    "liveness.config_poll_changed_at": {"entity": CONFIG_POLL_TEXT, "online_entity": CONFIG_ONLINE},
    "tou.slot_table": {"slots": tou_slot_spec()},
    "tou.current_target_soc_pct": {"entity": "sensor.test_tou_current_target_soc"},
    "tou.enabled": {"entity": TOU_ENABLED},
    "tou.grid_charge_enabled": {"entity": GRID_CHARGE_ENABLED},
    "tou.overlay_state": {"entities": list(OVERLAY_ENTITIES)},
    "pref.advisory_reserve_raise_pct": {"entity": RESERVE_RAISE_HELPER},
    "limits.max_grid_charge_w": {"entity": "sensor.test_max_grid_charge_power"},
    "tariff.import_rates": {"entity": "event.test_your_import_rates", "attribute": "rates"},
    "tariff.export_rates": {"entity": "event.test_your_export_rates", "attribute": "rates"},
    "tariff.events": {"entity": "event.test_your_saving_events", "attribute": "events"},
    "pv.forecast_today_kwh": {"entity": "sensor.test_solar_forecast_today"},
    "pv.forecast_tomorrow_kwh": {"entity": "sensor.test_solar_forecast_tomorrow"},
    "inverter.clock_offset_s": {"entity": eid("sensor", "clock_difference")},
}
SOURCE_ENTITIES = {
    "load_energy": eid("sensor", "total_load_energy"), "pv_energy": eid("sensor", "total_pv_energy"),
    "imp_energy": eid("sensor", "total_grid_import"), "exp_energy": eid("sensor", "total_grid_export"),
    "load_power": eid("sensor", "load_power"), "pv_power": eid("sensor", "pv_power"),
    "batt_power": eid("sensor", "battery_output_power"), "soc": eid("sensor", "battery_soc"),
}
# The I-D6 keys of the TOU classification inputs (foundation contract section 13.1). They become I-D6 keys only when the
# engine's freshness rules know them (WP-1); before that an I-D6 entry naming them is refused and makes I-D6 INVALID, so
# owner_decisions() gives them a limit exactly when the loaded engine accepts them.
TOU_I_D6_KEYS = ("tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state")
_ENGINE_SITE_DECISIONS = ("intelligence.site_decisions",
                          "custom_components.ecco_intelligence._vendor.intelligence.site_decisions")


def engine_override_keys() -> frozenset[str] | None:
    """FRESHNESS_OVERRIDE_KEYS of the engine this process uses: the repository's when the repository is importable, else the
    built kit's vendored copy once the L2 harness has imported it (never imported from here: that would load the
    integration before the stand-in Home Assistant is installed). None when neither is available."""
    for name in _ENGINE_SITE_DECISIONS:
        mod = sys.modules.get(name)
        if mod is None and name == _ENGINE_SITE_DECISIONS[0] and importlib.util.find_spec("intelligence") is not None:
            mod = importlib.import_module(name)
        if mod is not None:
            return frozenset(mod.FRESHNESS_OVERRIDE_KEYS)
    return None


def owner_decisions(*, open_ids: tuple[str, ...] = ()) -> dict:
    """A decisions block in the site-file form with every gating decision RECORDED as an owner record (synthetic values and
    fictional record refs, for tests only: the only way a runtime test can satisfy a gate, integrator decision 8). I-D6
    gives a limit to every key that has no default, the CCR-DQ-1 / CCR-PLAN-1 keys included, so the items resting on
    them can be OK on fresh inputs (and a test of their withholding is not vacuous). The tariff tables, which
    seed_fresh_states reports 5 minutes before `now`, get the 900 s ceiling, so a result resting on them stays valid for
    more than one minute tick; every other key gets 300 s, the TOU classification inputs (TOU_I_D6_KEYS) only when the
    loaded engine accepts them as I-D6 keys (engine_override_keys). The configuration-poll liveness is never an I-D6 key."""
    limits = {k: 300.0 for k in ("inverter.healthy", "house.power", "pv.power", "battery.power", "grid.power",
                                 "reserve.ha_minimum_soc", "protection.shutdown_soc_pct", "stop.dump_soc_pct",
                                 "capacity.helper_kwh", "capacity.fe1_wh_per_pct", "capacity.reg204_ah",
                                 "limits.max_grid_charge_w", "tou.slot_table", "battery.soc_raw_pct",
                                 "inverter.clock_offset_s", "tou.current_target_soc_pct")}
    limits.update({k: 900.0 for k in ("tariff.import_rates", "tariff.export_rates", "tariff.events")})
    known = engine_override_keys() or frozenset()
    limits.update({k: 300.0 for k in TOU_I_D6_KEYS if k in known})
    vals = {
        "I-D1": {"source": "INTELLIGENCE_USER_RESERVE", "value_pct": 30.0, "advice_honours": True},
        "I-D2": {"supplied_by": "OWNER_STATEMENT", "value_pct": 12.0, "observed_at": "2030-01-01T00:00:00+00:00"},
        "I-D3": {"kind": "CONFIGURED_HELPER", "value_kwh": 20.0, "nominal_voltage_v": 51.2},
        "I-D4": {"pct": 10.0},
        "I-D5": {"value": 0.92, "unit": "fraction", "basis": "ROUND_TRIP"},
        "I-D6": {"limits_s": limits},
        "I-D8": {"cutover": "2029-12-01T00:00:00+00:00", "load_power_policy": "EXCLUDE",
                 "load_counter_policy": "EXCLUDE_PRE_CUTOVER"},
        "I-D9": {"history_rule": "NORMALISE_TO_NOMINAL", "target_rule": "SCALE_UP_ONLY"},
    }
    out: dict = {"_comment": "TEST ONLY: synthetic owner-record form; fictional refs"}
    for k, v in vals.items():
        if k in open_ids:
            out[k] = {"status": "OPEN"}
        else:
            out[k] = {"status": "RECORDED", "provenance": "OWNER_RECORD",
                      "record_ref": f"REC-20300101-test-{k.lower()}", "value": v}
    out["I-D7"] = {"status": "OPEN"}
    return out


def all_open_decisions() -> dict:
    return {f"I-D{i}": {"status": "OPEN"} for i in range(1, 10)}


# the profile's reserve hints: deliberately NOT the SiteConfig defaults (40 / 10), so a test can tell "ignored" from
# "applied" (the SHADOW path must ignore them: reserves come only from I-D1 / I-D2)
HINT_USER_RESERVE_PCT = 63
HINT_TECHNICAL_MIN_PCT = 27


def site_profile(*, decisions: dict | None = None, with_map: bool = True, readings: dict | None = None,
                 signals: dict | None = None) -> dict:
    """A fresh profile every call: every block is a deep copy, so a test that edits its profile never changes the module
    maps (SIGNAL_MAP / READING_MAP) that later scenarios use."""
    prof = {
        "_comment": "TEST site file: generic test_* entity ids, synthetic values",
        "site": {"pv_array_kwp": 6.0, "user_reserve_soc_pct": HINT_USER_RESERVE_PCT,
                 "technical_min_soc_pct": HINT_TECHNICAL_MIN_PCT},
        "decisions": copy.deepcopy(decisions) if decisions is not None else all_open_decisions(),
        "sources": [{"name": "dongle", "priority": 1, "entities": {k: {"id": v} for k, v in SOURCE_ENTITIES.items()}}],
        "forecasts": {"test_forecast_day": {"id": "sensor.test_solar_forecast_today"}},
    }
    if with_map:
        prof["shadow_runtime"] = {"signals": copy.deepcopy(signals if signals is not None else SIGNAL_MAP),
                                  "readings": copy.deepcopy(readings if readings is not None else READING_MAP),
                                  "pv_forecast_sources": {"tomorrow": {"test_forecast": "sensor.test_solar_forecast_tomorrow"}}}
    return prof


def write_site(config_dir: Path, profile: dict | None) -> Path:
    d = config_dir / "ecco" / "intelligence"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "site.local.json"
    if profile is not None:
        p.write_text(json.dumps(profile, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return p


# ---------------------------------------------------------------------------------------------------------------------
# synthetic states and statistics
# ---------------------------------------------------------------------------------------------------------------------

def import_rates(now: datetime) -> list[dict]:
    """Synthetic import rates in the integration's form (fictional GBP/kWh): half-hour rows from 01:00 UTC of now's date to
    the end of the next day, 0.075 from 01:00 to 04:30 and 0.30 otherwise. They cover the planning layer's 24 h charge-window
    search from any time of that date, so the tariff verifies (current-day rates alone never do); the first row is the
    date's first cheap half-hour."""
    u = now.astimezone(UTC)
    t = datetime(u.year, u.month, u.day, 1, 0, tzinfo=UTC)
    end = datetime(u.year, u.month, u.day, tzinfo=UTC) + timedelta(days=2)
    rows = []
    while t < end:
        m = t.hour * 60 + t.minute
        rows.append({"start": t.isoformat(), "end": (t + timedelta(minutes=30)).isoformat(),
                     "value_inc_vat": 0.075 if 60 <= m < 270 else 0.30})
        t += timedelta(minutes=30)
    return rows


def poll_time_text(at: datetime) -> str:
    """A poll text as the dongle writes it (its poll time to the second; synthetic)."""
    return at.strftime("%Y-%m-%d %H:%M:%S")


def seed_fresh_states(states: Any, now: datetime, *, soc: str = "55", canonical_soc: str = "55", poll_tick: int = 0,
                      pause: str | None = "off", values_changed_at: datetime | None = None, config_tick: int = 0,
                      config_online: str = "on", telemetry_at: datetime | None = None,
                      config_at: datetime | None = None) -> None:
    """Every mapped entity with a plausible synthetic state. Both poll texts carry their poll time (each changes on every
    poll: the telemetry text 20 s ago, the configuration text CONFIG_POLL_AGE_S ago, or exactly `telemetry_at` /
    `config_at` when given: the A23 suite's own poll schedules); the other dongle values keep their own change time
    (values_changed_at), as the dongle firmware publishes only changes. The TOU table uses the dongle's own vocabulary:
    slot TOU_GRID_SLOT charges from 'Grid' (flags 1), the other five from the literal 'None' (flags 0), every mode 'None',
    every slot power TOU_SLOT_POWER_W; both enables on, every overlay off, the raise preference 0 %."""
    vt = values_changed_at or (now - timedelta(hours=3))
    if telemetry_at is not None:
        states.seed(eid("sensor", "last_telemetry_update"), poll_time_text(telemetry_at), changed_at=telemetry_at)
    else:
        poll_text = (now - timedelta(seconds=20) + timedelta(seconds=poll_tick)).strftime("%Y-%m-%d %H:%M:%S")
        states.seed(eid("sensor", "last_telemetry_update"), poll_text, changed_at=now - timedelta(seconds=20))
    if config_at is not None:
        states.seed(CONFIG_POLL_TEXT, poll_time_text(config_at), changed_at=config_at)
    else:
        config_at = now - timedelta(seconds=CONFIG_POLL_AGE_S)
        states.seed(CONFIG_POLL_TEXT, (config_at + timedelta(seconds=config_tick)).strftime("%Y-%m-%d %H:%M:%S"),
                    changed_at=config_at)
    states.seed(CONFIG_ONLINE, config_online, changed_at=vt)
    states.seed(TOU_ENABLED, "on", changed_at=vt)
    states.seed(GRID_CHARGE_ENABLED, "on", changed_at=vt)
    for e in OVERLAY_ENTITIES:
        states.seed(e, "off", changed_at=vt)
    states.seed(RESERVE_RAISE_HELPER, "0", {"unit_of_measurement": "%"}, changed_at=now - timedelta(days=1))
    w = {"unit_of_measurement": "W"}
    pct = {"unit_of_measurement": "%"}
    states.seed(eid("sensor", "battery_soc"), soc, pct, changed_at=vt)
    states.seed("sensor.test_canonical_battery_soc", canonical_soc, pct, changed_at=vt)
    states.seed(eid("sensor", "battery_output_power"), "400", w, changed_at=vt)
    states.seed(eid("sensor", "grid_power_ct_clamp"), "-50", w, changed_at=vt)
    states.seed("sensor.test_canonical_house_power", "450", w, changed_at=vt)
    states.seed(eid("sensor", "pv_power"), "0", w, changed_at=vt)
    states.seed(eid("sensor", "inverter_system_state"), "Normal", changed_at=vt)
    states.seed("input_number.test_minimum_reserve_soc", "20", pct, changed_at=vt)
    states.seed("sensor.test_supervision_status", "SUPERVISED", changed_at=vt)
    states.seed("binary_sensor.test_supervision_stable", "on", changed_at=vt)
    states.seed("sensor.test_supervision_heartbeat_age", "12", {"unit_of_measurement": "s"}, changed_at=now - timedelta(seconds=10))
    states.seed("input_number.test_battery_model_capacity", "20", {"unit_of_measurement": "kWh"}, changed_at=vt)
    states.seed(eid("sensor", "battery_capacity_ah"), "400", {"unit_of_measurement": "Ah"}, changed_at=vt)
    states.seed("input_number.test_round_trip_efficiency", "92", pct, changed_at=vt)
    states.seed(eid("sensor", "battery_shutdown"), "12", pct, changed_at=vt)
    states.seed(eid("sensor", "dump_stop_soc"), "30", pct, changed_at=vt)
    for i, start in enumerate(TOU_STARTS, start=1):
        grid = i == TOU_GRID_SLOT
        states.seed(slot_eid(i, "start"), start, changed_at=vt)
        states.seed(slot_eid(i, "target_soc"), "80" if grid else "20", pct, changed_at=vt)
        states.seed(slot_eid(i, "charge_source"), "Grid" if grid else "None", changed_at=vt)
        states.seed(slot_eid(i, "power"), TOU_SLOT_POWER_W, w, changed_at=vt)
        states.seed(slot_eid(i, "flags_raw"), "1" if grid else "0", changed_at=vt)
        states.seed(slot_eid(i, "mode"), "None", changed_at=vt)
    states.seed("sensor.test_tou_current_target_soc", "80", pct, changed_at=vt)
    states.seed("sensor.test_max_grid_charge_power", "5000", w, changed_at=vt)
    day = now.date().isoformat()
    states.seed("event.test_your_import_rates", now.isoformat(), {"rates": import_rates(now)}, changed_at=now - timedelta(minutes=5))
    states.seed("event.test_your_export_rates", now.isoformat(), {"rates": [
        {"start": f"{day}T00:00:00+00:00", "end": f"{day}T23:59:00+00:00", "value_inc_vat": 0.15}]}, changed_at=now - timedelta(minutes=5))
    states.seed("event.test_your_saving_events", now.isoformat(), {"events": []}, changed_at=now - timedelta(minutes=5))
    states.seed("sensor.test_solar_forecast_today", "3.1", {"unit_of_measurement": "kWh"}, changed_at=now - timedelta(hours=1))
    states.seed("sensor.test_solar_forecast_tomorrow", "4.2", {"unit_of_measurement": "kWh"}, changed_at=now - timedelta(hours=1))
    states.seed(eid("sensor", "clock_difference"), "2", {"unit_of_measurement": "s"}, changed_at=vt)
    if pause is not None:
        states.seed("input_boolean.ecco_intel_paused", pause, changed_at=now - timedelta(days=1))


def synthetic_statistics(now: datetime, days: int = 45, *, gap: tuple[int, int] | None = None,
                         drop_newest_hours: int = 0) -> dict[str, list[dict]]:
    """Hourly statistics rows {statistic_id: [{start, mean, min, max, state, sum}]} for SOURCE_ENTITIES, ending at the last
    complete hour before `now`. `gap` = (hours ago from, hours ago to) removed; `drop_newest_hours` removes the newest."""
    end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hours = days * 24
    out: dict[str, list[dict]] = {v: [] for v in SOURCE_ENTITIES.values()}
    load_c = pv_c = imp_c = exp_c = 0.0
    for k in range(hours, 0, -1):
        start = end - timedelta(hours=k)
        ago = k
        h = start.hour
        load = 0.35 + (0.6 if 17 <= h <= 21 else 0.0) + 0.05 * ((start.day * 7 + h) % 5)
        pv = max(0.0, 1.2 - abs(h - 12) * 0.25) if 7 <= h <= 17 else 0.0
        imp, exp = max(0.0, load - pv), max(0.0, pv - load)
        load_c, pv_c, imp_c, exp_c = load_c + load, pv_c + pv, imp_c + imp, exp_c + exp
        if gap is not None and gap[1] <= ago <= gap[0]:
            continue
        if ago <= drop_newest_hours:
            continue
        ts = start.timestamp()
        soc = 40.0 + 30.0 * ((h % 24) / 24.0)
        rows = {
            SOURCE_ENTITIES["load_energy"]: {"state": round(load_c, 3)},
            SOURCE_ENTITIES["pv_energy"]: {"state": round(pv_c, 3)},
            SOURCE_ENTITIES["imp_energy"]: {"state": round(imp_c, 3)},
            SOURCE_ENTITIES["exp_energy"]: {"state": round(exp_c, 3)},
            SOURCE_ENTITIES["load_power"]: {"mean": load * 1000, "min": load * 900, "max": load * 1100},
            SOURCE_ENTITIES["pv_power"]: {"mean": pv * 1000, "min": 0.0, "max": pv * 1200},
            SOURCE_ENTITIES["batt_power"]: {"mean": 100.0, "min": -500.0, "max": 600.0},
            SOURCE_ENTITIES["soc"]: {"mean": soc, "min": soc - 2, "max": soc + 2},
        }
        for sid, r in rows.items():
            out[sid].append(dict({"start": ts, "mean": None, "min": None, "max": None, "state": None, "sum": None}, **r))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# the L2 harness: the BUILT kit under the stand-in Home Assistant
# ---------------------------------------------------------------------------------------------------------------------

class Harness:
    """One process, one kit, one stand-in Home Assistant. `kit_root` is the build output directory (it holds
    custom_components/ecco_intelligence/); only it and this tests directory are on sys.path."""

    def __init__(self, kit_root: Path) -> None:
        if str(REPO) in sys.path or any(Path(p).resolve() == REPO for p in sys.path if p):
            raise RuntimeError("the repository root must not be on sys.path for an L2 run of the built kit")
        sys.path.insert(0, str(kit_root))
        import _fake_ha  # noqa: E402 - the tests directory is sys.path[0]
        self.fake = _fake_ha
        self.mods = _fake_ha.install()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.integration = importlib.import_module("custom_components.ecco_intelligence")
        self.contract = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.advisory_contract")
        self.store_mod = importlib.import_module("custom_components.ecco_intelligence.runtime.store")
        self.hass: Any = None
        self.config_dir: Path | None = None

    def new_hass(self, config_dir: Path, now: datetime) -> Any:
        self.fake.CLOCK.now = now
        self.config_dir = config_dir
        self.hass = self.fake.HomeAssistant(self.loop, str(config_dir))
        return self.hass

    def run(self, coro: Any, timeout: float = 60.0) -> Any:
        return self.loop.run_until_complete(asyncio.wait_for(coro, timeout))

    def new_entry(self, data: dict | None = None) -> Any:
        entry = self.fake.ConfigEntry("ecco_intelligence", data or {}, "ECCO Intelligence (SHADOW)")
        self.hass.config_entries._add(entry)  # noqa: SLF001
        return entry

    def setup(self, entry: Any) -> bool:
        ok = self.run(self.integration.async_setup_entry(self.hass, entry))
        self.install_job_wait()
        self.settle(0.5)
        return ok

    def install_job_wait(self) -> None:
        """The coordinator's job waits (coordinator._job_wait) under the stand-in's clock where Home Assistant's would
        follow the wall clock. A cycle waits for each executor job at most to its time budget (the loop's clock, kept
        real here) or, when that comes first, to the tick body's deadline (the wall clock: here the stand-in's, which
        moves only when the test moves it). So a wait whose timeout is the cycle's tick-body deadline (the coordinator's
        own _tick_deadline_in) ends when the stand-in's clock reaches it, and that moment is scheduled as a no-op world
        event, so run_until stops the clock there and the deadline run comes at its time (Harness.tick() moves in whole
        steps, so there it comes at the first step past it); a time-budget wait keeps the loop's clock alone, as before.
        Installed once, at the first setup; the real wait stays as real_job_wait."""
        coord = sys.modules.get("custom_components.ecco_intelligence.coordinator")
        if coord is None or getattr(coord._job_wait, "_stand_in_clock", False):  # noqa: SLF001
            return
        self.real_job_wait = coord._job_wait  # noqa: SLF001
        harness = self

        def waiting_coordinator() -> Any:
            task = asyncio.current_task()
            for e in harness.hass.config_entries.async_entries():
                co = getattr(e, "runtime_data", None)
                if co is not None and getattr(co, "_task", None) is task:
                    return co
            return None

        async def job_wait(fut: asyncio.Future, timeout: float) -> Any:
            loop = asyncio.get_running_loop()
            end_loop = loop.time() + timeout
            co = waiting_coordinator()
            tick_cut = co is not None and abs(co._tick_deadline_in() - timeout) < 1e-9  # noqa: SLF001
            end_clock = harness.fake.CLOCK.now + timedelta(seconds=timeout) if tick_cut else None
            if end_clock is not None:
                harness.at(end_clock, lambda: None)
            while not fut.done():
                if (end_clock is None and loop.time() >= end_loop) or (end_clock is not None
                                                                         and harness.fake.CLOCK.now >= end_clock):
                    raise asyncio.TimeoutError
                left = end_loop - loop.time() if end_clock is None else 0.02
                await asyncio.wait({fut}, timeout=max(min(0.02, left), 0.001))
            return fut.result()
        job_wait._stand_in_clock = True  # noqa: SLF001
        coord._job_wait = job_wait  # noqa: SLF001

    def unload(self, entry: Any) -> bool:
        ok = self.run(self.integration.async_unload_entry(self.hass, entry))
        self.settle(0.2)
        return ok

    def settle(self, timeout: float = 5.0) -> None:
        async def wait() -> None:
            for _ in range(3):
                pending = [t for t in self.hass.tasks if not t.done()]
                if not pending:
                    await asyncio.sleep(0)
                    return
                await asyncio.wait(pending, timeout=timeout)
        self.run(wait(), timeout=timeout * 4 + 5)

    def tick(self, seconds: float = 60.0, settle: float = 5.0) -> None:
        """Move the clock by `seconds`, fire every one-shot timer now due (late, at this time) and then every interval
        timer (the one-minute tick), whatever its own schedule (the pre-A23 suites drive the tick this way)."""
        self.fake.CLOCK.now = self.fake.CLOCK.now + timedelta(seconds=seconds)
        self._fire_due_later(settle)
        for t in list(self.hass.timers):
            if t["active"]:
                t["action"](self.fake.CLOCK.now)
                t["next"] = self.fake.CLOCK.now + t["interval"]
        self.settle(settle)

    def _fire_due_later(self, settle: float) -> None:
        while True:
            due = sorted((t for t in self.hass.later if t["active"] and t["due"] <= self.fake.CLOCK.now),
                         key=lambda t: t["due"])
            if not due:
                return
            due[0]["active"] = False
            due[0]["action"](self.fake.CLOCK.now)
            self.settle(settle)

    # --- event-driven time (A23): interval timers at their own times, one-shot timers, scripted world events ---------
    def at(self, when: datetime, fn: Callable[[], None]) -> None:
        """Schedule a world event (for example a dongle poll writing its entities) for run_until."""
        self._world_seq = getattr(self, "_world_seq", 0) + 1
        self._world = getattr(self, "_world", [])
        self._world.append((when, self._world_seq, fn))

    def clear_world(self) -> None:
        self._world = []

    def run_until(self, until: datetime, settle: float = 5.0, observe: Callable[[str], None] | None = None) -> None:
        """Advance the clock to `until`, processing in time order every scripted world event, one-shot timer and interval
        timer that comes due on the way, each at its own time (at equal times: world events, then one-shot timers, then
        interval timers), and letting the cycles they start finish (the clock stands still meanwhile). `observe(kind)` is
        called after each ('world', 'later' or 'timer')."""
        while True:
            cands = []
            world = getattr(self, "_world", [])
            if world:
                w = min(world, key=lambda x: (x[0], x[1]))
                cands.append((w[0], 0, w[1], "world", w))
            for t in self.hass.later:
                if t["active"]:
                    cands.append((t["due"], 1, id(t), "later", t))
            for t in self.hass.timers:
                if t["active"]:
                    cands.append((t["next"], 2, id(t), "timer", t))
            if not cands:
                break
            when, _o, _i, kind, obj = min(cands, key=lambda c: (c[0], c[1], c[2]))
            if when > until:
                break
            if when > self.fake.CLOCK.now:
                self.fake.CLOCK.now = when
            if kind == "world":
                world.remove(obj)
                obj[2]()
            elif kind == "later":
                obj["active"] = False
                obj["action"](self.fake.CLOCK.now)
            else:
                obj["next"] = obj["next"] + obj["interval"]
                obj["action"](self.fake.CLOCK.now)
            self.settle(settle)
            if observe is not None:
                observe(kind)
        if until > self.fake.CLOCK.now:
            self.fake.CLOCK.now = until

    @property
    def now(self) -> datetime:
        return self.fake.CLOCK.now

    def set_now(self, now: datetime) -> None:
        self.fake.CLOCK.now = now

    def state(self, key: str) -> Any:
        return self.hass.states._states.get(self.contract.ENTITY_IDS[key])  # noqa: SLF001

    def coordinator(self, entry: Any) -> Any:
        return getattr(entry, "runtime_data", None)

    def recorder(self) -> Any:
        return self.hass.data["recorder_instance"]


def gated_keys(contract: Any) -> tuple[str, ...]:
    """Items that rest on at least one decision (everything but pv_tomorrow and the diagnostics)."""
    return ("charge_target", "overnight_demand", "export_event", "dump_to_grid", "predicted_day_load",
            "predicted_morning_soc")


def has_number(v: Any) -> bool:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, dict):
        return any(has_number(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return any(has_number(x) for x in v)
    return True


def numeric_state(st: Any) -> bool:
    if st is None or st.state in ("unknown", "unavailable"):
        return False
    try:
        float(st.state)
        return True
    except ValueError:
        return False


def text_anywhere(hass: Any, needle: str, extra: Any = None) -> list[str]:
    """Where `needle` appears in what Home Assistant would show or keep: every state and attribute in the state machine,
    every recorder row, and `extra` (for example a diagnostics download), each as JSON text."""
    hits = []
    for eid, st in hass.states._states.items():  # noqa: SLF001
        if needle in json.dumps({"state": st.state, "attributes": dict(st.attributes)}, default=str):
            hits.append(f"state {eid}")
    for row in hass.recorder_rows:
        if needle in json.dumps(row, default=str):
            hits.append(f"recorder row {row[0]}")
    if extra is not None and needle in json.dumps(extra, default=str):
        hits.append("extra")
    return hits


def mktemp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def rmtree_own(path: Path, prefix: str) -> None:
    """Remove a temporary directory this suite created (only a directory whose name starts with `prefix` in the system
    temporary directory)."""
    p = Path(path).resolve()
    tmp = Path(tempfile.gettempdir()).resolve()
    if p.parent == tmp and p.name.startswith(prefix):
        shutil.rmtree(p, ignore_errors=True)


def inject(coordinator: Any, fn: Callable | None) -> None:
    coordinator._run_cycle = fn  # noqa: SLF001
