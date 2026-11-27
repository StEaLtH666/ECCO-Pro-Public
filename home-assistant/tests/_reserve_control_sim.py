"""Test support for the reserve control package (home-assistant/packages/ecco_reserve_control.yaml): ONE virtual Home Assistant for its guarded script.

It runs the REAL package on the repository's own models, reused unchanged: the FPS1 interpreter (_ha_script_sim.py), the zone-aware plan layer (_plan_sim.PlanWorld,
whose helper services carry Home Assistant's own range checks: input_number.set_value outside min / max / step raises), the REAL owner reserve helper definition
(read from ecco_pro.yaml, so a changed range there reaches this suite) and, by default, the REAL plan helper package (ecco_plan_helpers.yaml), so the effective
reserve sensor is produced by its real template and a Prepare for power cut reserve can be put in place the way the plan package records it.

What this module adds, and why:
  - fault hooks on the one write the script makes: `drop` (the call succeeds and the helper does not change), `skew` (the helper takes another number), `raise_next`
    (the call raises, as an out-of-range write would);
  - helpers to put a power cut reserve in place, to remove the plan package's sensor, and to read the result text and the notifications;
  - EVERY service call is recorded with its target and data (the model's `w.service_log`), and an unsupported service raises (the interpreter is fail loud), so a suite
    can pin the whole write vocabulary.
Home Assistant's own behaviour is MODELLED as recalled, NOT verified on a real instance (the package header lists it). No network, no hardware, no write to anything.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

import _ha_script_sim as S
import _plan_sim as PL

HERE = Path(__file__).resolve().parent
PKGS = HERE.parent / "packages"
HELPER = "input_number.ecco_minimum_reserve_soc"
PLAN = "sensor.ecco_plan_effective_reserve"
RESULT = "input_text.ecco_reserve_set_result"
NOTE = "ecco_reserve_set_refused"
FMT = "%Y-%m-%d %H:%M:%S"
START = "2026-11-27 12:00:00"


def helper_package() -> dict:
    """The owner reserve helper, exactly as ecco_pro.yaml defines it."""
    d = yaml.safe_load((PKGS / "ecco_pro.yaml").read_text(encoding="utf-8"))
    return {"input_number": {"ecco_minimum_reserve_soc": d["input_number"]["ecco_minimum_reserve_soc"]}}


class ControlWorld:
    def __init__(self, package_text: str, reserve=5, with_plan: bool = True, start: str = START, zone: str = "Europe/London", with_helper: bool = True):
        self.package_text = package_text
        pkgs = ([helper_package()] if with_helper else []) + ([yaml.safe_load((PKGS / "ecco_plan_helpers.yaml").read_text(encoding="utf-8"))] if with_plan else []) \
            + [yaml.safe_load(package_text)]
        self.pw = PL.PlanWorld(start, pkgs, zone)
        self.w, self.ha = self.pw.w, self.pw.ha
        self.zone = self.pw.zone
        self.with_plan = with_plan
        self.drop = False
        self.skew = 0.0
        self.raise_next = 0
        self.write_log: list = []
        self._plan_number = self.w.service_handlers["input_number.set_value"]
        self.w.service_handlers["input_number.set_value"] = self._number
        if with_helper:
            self.pw.num(HELPER, reserve)
        if not with_plan:
            self.w.set(PLAN, str(reserve))
        self.ha.start()
        self.w.run_until(self.w.t + 1.0)          # the plan package's first-run seed (its own helpers) runs here, before any request
        self.write_log.clear()

    def _number(self, entity: str, data: dict) -> None:
        if entity == HELPER:
            self.write_log.append((self.w.t, entity, data.get("value")))
        if self.raise_next > 0:
            self.raise_next -= 1
            raise S.ServiceError(f"{entity} {data.get('value')!r}")
        if self.drop:
            return
        if self.skew:
            data = dict(data, value=float(data["value"]) + self.skew)
        self._plan_number(entity, data)

    # --- the world ---------------------------------------------------------------------------------------------------------
    def set_owner(self, value) -> None:
        self.pw.num(HELPER, value)

    def raw(self, entity: str, state: str | None) -> None:
        """Put a raw state (a junk, unavailable or unknown helper state); None removes the entity."""
        if state is None:
            self.w.states.pop(entity, None)
            self.w._changed()
        else:
            self.w.set(entity, state)

    def power_cut(self, reserve: int = 80, minutes: int = 120) -> None:
        """A running Prepare for power cut reserve, recorded the way the plan package records it (its reserve, and its expiry in both of its sources)."""
        exp = datetime.fromtimestamp(self.w.t, self.zone) + timedelta(minutes=minutes)
        self.pw.num("input_number.ecco_plan_override_prepare_power_cut_reserve", reserve)
        self.pw.num("input_number.ecco_plan_override_prepare_power_cut_expires_epoch", exp.timestamp())
        self.pw.set_local("input_datetime.ecco_plan_override_prepare_power_cut_expires", exp.strftime(FMT))

    # --- running -----------------------------------------------------------------------------------------------------------
    def run(self, value=S._MISSING, confirm=S._MISSING, seconds: float = 30.0) -> str:
        """Run the script with the given fields (an omitted field is not passed at all); returns the result text it leaves."""
        data = {}
        if value is not S._MISSING:
            data["value"] = value
        if confirm is not S._MISSING:
            data["confirm"] = confirm
        self.pw.run_script("ecco_reserve_set", data, seconds)
        return self.result

    @property
    def result(self) -> str:
        return self.w.state(RESULT)

    def owner(self) -> str:
        return self.w.state(HELPER)

    def services(self, since: int = 0) -> list:
        return self.pw.services(since)

    def notified(self) -> dict:
        return self.w.notifications
