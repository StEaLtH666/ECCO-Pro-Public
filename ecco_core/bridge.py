"""The Intelligence bridge: the one crossing between system state and the advisory layer, in both directions.

    state  -> advice   `advisory_live_inputs` hands a Snapshot to the engine (intelligence.inputs.live_inputs_from_snapshot).
                       It gates only what the engine cannot judge for itself: the inverter status must be FRESH under the
                       ADVISORY freshness policy, whose limit for it is UNRESOLVED until an installation configures one, so
                       by default the engine sees an unknown status and withholds export advice. The SOC passes with its
                       age (the engine applies its own 15-minute rule); the HA reserve passes whatever its age (it can only
                       raise the reserve). Every assessment is returned for display.
    advice -> record   `record` / `record_report` turn an Intelligence V1.1 Advice or a V1 report into an AdvisoryRecord:
                       frozen, JSON-safe, marked SHADOW / applies_nothing, with no method that does anything.

This module imports nothing from ecco_core.authority, and an AdvisoryRecord carries nothing an authority intent could be
built from; ecco_core.authority.evaluate refuses advisory origins anyway. Both directions are checked statically by tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from .freshness import ADVISORY, Assessment, FreshnessPolicy
from .state import Observation, Snapshot

ADVISORY_SIGNALS = ("battery.soc", "inverter.healthy", "house.power", "pv.power", "reserve.ha_minimum_soc")


def advisory_live_inputs(snapshot: Snapshot, *, tariff=None, saving_sessions=(), policy: FreshnessPolicy | None = None):
    """(LiveInputs, assessments) for the Intelligence engine from a live snapshot."""
    from intelligence.inputs import live_inputs_from_snapshot   # the advisory side is imported only here

    policy = policy or FreshnessPolicy(ADVISORY)
    if policy.purpose != ADVISORY:
        raise ValueError("advisory inputs are judged with the ADVISORY freshness policy")
    assessments = tuple(policy.assess(snapshot, s) for s in ADVISORY_SIGNALS)
    health = next(a for a in assessments if a.signal == "inverter.healthy")
    gated = snapshot
    o = snapshot.get("inverter.healthy")
    if o is not None and not health.fresh:
        withheld = Observation(o.signal, None, o.observed_at, o.source, o.kind, raw=o.value, derived_from=o.derived_from,
                               quality=o.quality + (f"withheld_{health.status}",))
        gated = Snapshot(snapshot.as_of, {**snapshot.observations, o.signal: withheld})
    return live_inputs_from_snapshot(gated, tariff=tariff, saving_sessions=list(saving_sessions)), assessments


@dataclass(frozen=True)
class AdvisoryRecord:
    """A published piece of advice. Data only: SHADOW, applies nothing, no behaviour."""
    kind: str
    status: str
    generated_at: str
    payload: str                       # canonical JSON (sorted keys); immutable
    mode: str = "SHADOW"
    applies_nothing: bool = True

    def __post_init__(self) -> None:
        if self.mode != "SHADOW" or self.applies_nothing is not True:
            raise ValueError("an AdvisoryRecord is shadow-only")
        body = json.loads(self.payload)
        if body.get("mode") != "SHADOW" or body.get("applies_nothing") is not True:
            raise ValueError("the advice inside a record must itself be SHADOW and apply nothing")

    def as_dict(self) -> dict:
        return json.loads(self.payload)

    def display_attributes(self) -> dict:
        """What a read-only display sensor would carry."""
        return {"mode": self.mode, "applies_nothing": self.applies_nothing, "kind": self.kind, "status": self.status,
                "generated_at": self.generated_at, "advice": self.as_dict()}


def record(advice, generated_at: datetime) -> AdvisoryRecord:
    """An AdvisoryRecord from an Intelligence V1.1 Advice."""
    body = advice.to_dict()
    return AdvisoryRecord(body["kind"], body["status"], generated_at.isoformat(),
                          json.dumps(body, sort_keys=True, allow_nan=False, separators=(",", ":")))


def record_report(report: dict) -> AdvisoryRecord:
    """An AdvisoryRecord from an Intelligence V1 engine report (which must already state SHADOW / applies_nothing)."""
    return AdvisoryRecord("v1_report", str(report.get("status")), str(report.get("generated_for")),
                          json.dumps(report, sort_keys=True, allow_nan=False, default=str, separators=(",", ":")))
