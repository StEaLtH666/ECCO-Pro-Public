"""State model: what the system knows at one instant, as immutable observations with provenance and observation time.

An Observation keeps apart:

    value        the value in the signal's canonical unit and sign convention (None = the source gave no usable value)
    raw          the value exactly as its source reported it (a register word, a Home Assistant state string), kept for
                 diagnostics and never overwritten by a derived value
    kind         RAW (as read), NORMALIZED (a raw value scaled or converted, nothing else) or DERIVED (computed from other
                 signals, which `derived_from` names)
    observed_at  when the SOURCE observed it (aware datetime), not when it was copied; None = unknown
    source       where it came from ("controller:register:184", "ha:sensor.x", "history:hour_mean", ...)
    quality      short flags such as "hour_mean" or "caller_override"

Raw and derived values live side by side under different signal names, so a derived figure can never silently replace the
raw one. Freshness is deliberately NOT stored on an observation: whether a reading is fresh enough depends on what it is
used for (freshness.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Iterable, Mapping

RAW = "raw"
NORMALIZED = "normalized"
DERIVED = "derived"
KINDS = (RAW, NORMALIZED, DERIVED)


@dataclass(frozen=True)
class SignalSpec:
    name: str                       # exact name, or a family "prefix.*"
    unit: str | None
    description: str
    sign: str | None = None         # sign convention, when the value is signed


# The signals this model knows. Unit and sign conventions are the repository's existing ones: battery power positive =
# discharge (capability registry record battery_power), grid power positive = import (the canonical grid sensor of
# home-assistant/packages/ecco_canonical_telemetry.yaml). An unknown signal name is refused, so a typo cannot silently
# create a second, unused signal.
SIGNALS: Mapping[str, SignalSpec] = MappingProxyType({s.name: s for s in (
    SignalSpec("battery.soc", "%", "battery state of charge"),
    SignalSpec("battery.power", "W", "battery power", "positive = discharging, negative = charging"),
    SignalSpec("house.power", "W", "house load power"),
    SignalSpec("pv.power", "W", "total PV power, the sum of all strings"),
    SignalSpec("pv.string_power.*", "W", "power of one PV string"),
    SignalSpec("grid.power", "W", "grid power at the CT clamp", "positive = importing, negative = exporting"),
    SignalSpec("inverter.state", None, "inverter system state (enumeration label)"),
    SignalSpec("inverter.healthy", None, "the inverter is known to be in normal operation (boolean)"),
    SignalSpec("inverter.config_readback", None, "the controller's latest successful configuration read (boolean)"),
    SignalSpec("reserve.ha_minimum_soc", "%", "the Home Assistant reserve helper: an input that can only raise the reserve"),
    SignalSpec("pv.energy_today_so_far", "kWh", "PV energy produced so far today"),
    SignalSpec("pv.forecast.today.*", "kWh", "one forecast source's PV energy forecast for today"),
    SignalSpec("pv.forecast.tomorrow.*", "kWh", "one forecast source's PV energy forecast for tomorrow"),
    SignalSpec("pv.forecast.remaining_today.*", "kWh", "one forecast source's remaining PV energy for today"),
    SignalSpec("history.hourly", None, "the newest complete hour of the canonical hourly history (boolean: present)"),
    SignalSpec("controller.telemetry", None, "the controller's telemetry poll is succeeding (boolean)"),
    SignalSpec("controller.configuration", None, "the controller's configuration poll is succeeding (boolean)"),
    SignalSpec("controller.owner.*", None, "one controller ownership flag (boolean: held)"),
    SignalSpec("controller.obligation.*", None, "one controller durable obligation (boolean: open)"),
    SignalSpec("controller.arm.*", None, "one controller write-enable switch (boolean: on)"),
    SignalSpec("canonical.telemetry", None, "the Home Assistant canonical telemetry entities are refreshing (boolean)"),
    SignalSpec("battery_outlook", None, "the InfluxDB Battery Outlook result is present (boolean)"),
    SignalSpec("transaction.snapshot", None, "a transaction's pre-write snapshot (boolean: taken)"),
)})


def spec_for(signal: str) -> SignalSpec | None:
    """The spec of an exact signal name, or of the family it belongs to ("pv.forecast.today.solcast" -> "pv.forecast.today.*")."""
    if signal in SIGNALS:
        return SIGNALS[signal]
    head, dot, tail = signal.rpartition(".")
    if dot and tail and head:
        fam = SIGNALS.get(head + ".*")
        if fam is not None:
            return fam
    return None


def _acceptable_value(v: object) -> bool:
    if v is None or isinstance(v, (bool, str)):
        return True
    return isinstance(v, (int, float)) and math.isfinite(v)


@dataclass(frozen=True)
class Observation:
    signal: str
    value: object
    observed_at: datetime | None
    source: str
    kind: str = NORMALIZED
    unit: str | None = None
    raw: object = None
    derived_from: tuple[str, ...] = ()
    quality: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        spec = spec_for(self.signal)
        if spec is None:
            raise ValueError(f"unknown signal {self.signal!r} (add it to ecco_core.state.SIGNALS)")
        if self.kind not in KINDS:
            raise ValueError(f"{self.signal}: kind must be one of {KINDS}, got {self.kind!r}")
        if not _acceptable_value(self.value):
            raise ValueError(f"{self.signal}: value must be None, bool, str or a finite number, got {self.value!r}")
        if spec.unit is not None and self.value is not None and (isinstance(self.value, (bool, str))):
            # a measured quantity is a number or nothing: an HA state string ("unavailable") or a boolean is not a reading
            raise ValueError(f"{self.signal}: a {spec.unit} reading must be a finite number or None, got {self.value!r}")
        if self.observed_at is not None and (not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None):
            raise ValueError(f"{self.signal}: observed_at must be an aware datetime or None")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError(f"{self.signal}: a source is required")
        object.__setattr__(self, "derived_from", tuple(self.derived_from))
        object.__setattr__(self, "quality", tuple(self.quality))
        if (self.kind == DERIVED) != bool(self.derived_from):
            raise ValueError(f"{self.signal}: a DERIVED observation names what it was derived from, and only a derived one does")
        for d in self.derived_from:
            if spec_for(d) is None and not d.startswith("registry:"):
                raise ValueError(f"{self.signal}: derived from unknown signal {d!r}")
        if self.unit is None:
            object.__setattr__(self, "unit", spec.unit)
        elif self.unit != spec.unit:
            raise ValueError(f"{self.signal}: unit {self.unit!r} differs from the signal's canonical unit {spec.unit!r}")

    @property
    def available(self) -> bool:
        return self.value is not None

    def age_s(self, now: datetime) -> float | None:
        """Seconds between observation and `now`. None when the observation time is unknown or lies in the future
        (clock skew): an age that cannot be trusted is unknown, never zero."""
        if self.observed_at is None:
            return None
        age = (now - self.observed_at).total_seconds()
        return age if age >= 0.0 else None

    def to_dict(self) -> dict:
        return {"signal": self.signal, "value": self.value, "unit": self.unit, "kind": self.kind,
                "observed_at": None if self.observed_at is None else self.observed_at.isoformat(), "source": self.source,
                "raw": self.raw if _acceptable_value(self.raw) else repr(self.raw),
                "derived_from": list(self.derived_from), "quality": list(self.quality)}


@dataclass(frozen=True)
class Snapshot:
    """Everything known at `as_of`: at most one observation per signal. Immutable."""
    as_of: datetime
    observations: Mapping[str, Observation]

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError("Snapshot.as_of must be an aware datetime")
        obs = dict(self.observations)
        for k, o in obs.items():
            if not isinstance(o, Observation) or o.signal != k:
                raise ValueError(f"snapshot key {k!r} does not match its observation")
        object.__setattr__(self, "observations", MappingProxyType(obs))

    @staticmethod
    def of(as_of: datetime, observations: Iterable[Observation]) -> "Snapshot":
        out: dict[str, Observation] = {}
        for o in observations:
            if o.signal in out:
                raise ValueError(f"two observations for {o.signal!r} in one snapshot")
            out[o.signal] = o
        return Snapshot(as_of, out)

    def get(self, signal: str) -> Observation | None:
        return self.observations.get(signal)

    def value(self, signal: str) -> object:
        o = self.observations.get(signal)
        return None if o is None else o.value

    def age_s(self, signal: str) -> float | None:
        o = self.observations.get(signal)
        return None if o is None else o.age_s(self.as_of)

    def signals(self, prefix: str = "") -> tuple[str, ...]:
        return tuple(sorted(s for s in self.observations if s.startswith(prefix)))

    def to_dict(self) -> dict:
        return {"as_of": self.as_of.isoformat(), "observations": [self.observations[s].to_dict() for s in self.signals()]}
