"""Freshness: one catalogue of the age limits the project already uses, and one way to apply them.

Before this module the limits lived in many places with no shared definition (the controller's Dump-to-Grid gates, the
Intelligence advisor, the System Health design registry, the fallback live-match cache, the transaction design model).
They are collected here unchanged, each with WHERE it is defined and HOW established it is:

    CONTROLLER    enforced by the hardware-tested controller firmware (or its line-for-line mirrored policy header)
    INTELLIGENCE  used by the offline Intelligence engine
    DESIGN        a documented design threshold that no live component reads (registry/system_health_checks.yaml,
                  registry/transaction_state_machine.py)
    SITE          set by the installation (a FreshnessPolicy override)
    UNRESOLVED    no limit is defined anywhere in the project for that use: the reading can never be shown to be fresh

Freshness depends on the PURPOSE, so the same reading can be fresh for advice and stale for a control gate:

    CONTROL_GATE  may a controller-side action rely on it now (the strictest limits)
    ADVISORY      may a shadow recommendation rely on it
    HEALTH        is the data path healthy (display and diagnostics)

Fail closed: no observation, no usable value, an observation time that is unknown or in the future, or an UNRESOLVED limit
is never FRESH. tests check every catalogued limit against its source, so the catalogue cannot drift from the code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from .state import Snapshot, spec_for

CONTROL_GATE = "control_gate"
ADVISORY = "advisory"
HEALTH = "health"
PURPOSES = (CONTROL_GATE, ADVISORY, HEALTH)

CONTROLLER = "controller"
INTELLIGENCE = "intelligence"
DESIGN = "design"
SITE = "site"
UNRESOLVED = "unresolved"

FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"
UNAVAILABLE = "unavailable"

FIRMWARE = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
HEALTH_REGISTRY = "registry/system_health_checks.yaml"


@dataclass(frozen=True)
class Limit:
    signal: str
    purpose: str
    max_age_s: float | None          # None = UNRESOLVED
    source: str                      # where the project defines it ("" when unresolved)
    standing: str
    note: str = ""


CATALOGUE: tuple[Limit, ...] = (
    # --- enforced by the controller -----------------------------------------------------------------------------------
    Limit("battery.soc", CONTROL_GATE, 90.0, f"{FIRMWARE}: ecco_dump_soc_stale_ms = 90000", CONTROLLER,
          "Dump-to-Grid START gate and active lease"),
    Limit("grid.power", CONTROL_GATE, 90.0, f"{FIRMWARE}: ecco_dump_grid_stale_ms = 90000", CONTROLLER,
          "Dump-to-Grid closed-loop export controller"),
    Limit("inverter.config_readback", CONTROL_GATE, 180.0, f"{FIRMWARE}: ecco_dump_cfg_stale_ms = 180000", CONTROLLER,
          "Dump-to-Grid post-activation readback"),
    Limit("inverter.config_readback", HEALTH, 180.0, "registry/fallback_capture.py: LIVE_CACHE_MAX_AGE_MS = 180000 "
          "(mirrors firmware/include/ecco_fallback_capture.h)", CONTROLLER, "fallback profile live-match trust"),
    # --- used by the Intelligence engine --------------------------------------------------------------------------------
    Limit("battery.soc", ADVISORY, 900.0, "intelligence/advisor.py: STALE_SOC_SECONDS = 15 * 60", INTELLIGENCE,
          "export advice is withheld beyond it"),
    Limit("history.hourly", ADVISORY, 6 * 3600.0, "intelligence/engine.py: learning history older than 6 h is stale",
          INTELLIGENCE),
    # --- documented design thresholds (no live component reads them) ----------------------------------------------------
    Limit("controller.telemetry", HEALTH, 180.0, f"{HEALTH_REGISTRY}: telemetry_freshness failure_threshold_seconds",
          DESIGN, "warning at 60 s"),
    Limit("controller.configuration", HEALTH, 600.0, f"{HEALTH_REGISTRY}: configuration_freshness failure_threshold_seconds",
          DESIGN, "warning at 180 s"),
    Limit("canonical.telemetry", HEALTH, 60.0, f"{HEALTH_REGISTRY}: canonical_stale_raw_fresh failure_threshold_seconds",
          DESIGN),
    Limit("battery_outlook", HEALTH, 1200.0, f"{HEALTH_REGISTRY}: battery_outlook_freshness warning_threshold_seconds",
          DESIGN, "the registry defines no failure threshold"),
    Limit("transaction.snapshot", CONTROL_GATE, 30.0, "registry/transaction_state_machine.py: Snapshot.max_age_seconds = 30.0",
          DESIGN, "arming refuses an older pre-write snapshot in the design model"),
    # --- explicitly unresolved: nothing in the project defines a limit for these uses ------------------------------------
    Limit("inverter.healthy", ADVISORY, None, "", UNRESOLVED,
          "no limit is defined; advice cannot rely on the inverter status until a site limit is configured"),
    Limit("house.power", ADVISORY, None, "", UNRESOLVED, "display only in the V1 engine"),
    Limit("pv.power", ADVISORY, None, "", UNRESOLVED, "display only in the V1 engine"),
    Limit("battery.power", ADVISORY, None, "", UNRESOLVED),
    Limit("grid.power", ADVISORY, None, "", UNRESOLVED),
    Limit("reserve.ha_minimum_soc", ADVISORY, None, "", UNRESOLVED,
          "the HA reserve can only raise the effective reserve, so the advisor uses it whatever its age"),
)


@dataclass(frozen=True)
class Assessment:
    signal: str
    purpose: str
    status: str
    age_s: float | None
    max_age_s: float | None
    standing: str
    limit_source: str
    reason: str

    @property
    def fresh(self) -> bool:
        return self.status == FRESH

    def to_dict(self) -> dict:
        return {"signal": self.signal, "purpose": self.purpose, "status": self.status, "age_s": self.age_s,
                "max_age_s": self.max_age_s, "standing": self.standing, "limit_source": self.limit_source,
                "reason": self.reason}


class FreshnessPolicy:
    """The freshness limits for one purpose: the catalogue's, optionally overridden by the installation per signal or
    per signal family ("controller.owner.*"; an exact signal's override wins over its family's)."""

    def __init__(self, purpose: str, overrides: Mapping[str, float] | None = None,
                 catalogue: Iterable[Limit] = CATALOGUE):
        if purpose not in PURPOSES:
            raise ValueError(f"purpose must be one of {PURPOSES}, got {purpose!r}")
        self.purpose = purpose
        self._limits: dict[str, Limit] = {}
        for lim in catalogue:
            if lim.purpose != purpose:
                continue
            if lim.signal in self._limits:
                raise ValueError(f"two catalogue limits for {lim.signal!r} / {purpose}")
            self._limits[lim.signal] = lim
        for sig, v in (overrides or {}).items():
            if spec_for(sig) is None:
                raise ValueError(f"override for unknown signal {sig!r}")
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"override for {sig!r} must be a positive number of seconds, got {v!r}")
            defined = self._limits.get(sig)
            if defined is not None and defined.max_age_s is not None and v > defined.max_age_s:
                # like the run-time reserve, an installation may only make a defined limit STRICTER, never looser
                raise ValueError(f"override for {sig!r} ({v} s) would loosen the defined {purpose} limit of "
                                 f"{defined.max_age_s:g} s ({defined.source}); an override may only tighten it")
            self._limits[sig] = Limit(sig, purpose, float(v), "site configuration (FreshnessPolicy override)", SITE)

    def limit(self, signal: str) -> Limit:
        found = self._limits.get(signal)                 # an exact limit (catalogue or override) always wins
        if found is None:
            spec = spec_for(signal)
            if spec is not None and spec.name.endswith(".*") and spec.name in self._limits:
                fam = self._limits[spec.name]
                found = Limit(signal, self.purpose, fam.max_age_s, fam.source, fam.standing, f"from {spec.name}")
        return found or Limit(signal, self.purpose, None, "", UNRESOLVED, "no limit is defined for this signal and purpose")

    def assess(self, snapshot: Snapshot, signal: str) -> Assessment:
        lim = self.limit(signal)

        def out(status: str, age: float | None, reason: str) -> Assessment:
            return Assessment(signal, self.purpose, status, age, lim.max_age_s, lim.standing, lim.source, reason)

        obs = snapshot.get(signal)
        if obs is None:
            return out(UNKNOWN, None, "no observation")
        if obs.value is None:
            return out(UNAVAILABLE, obs.age_s(snapshot.as_of), "the source reported no usable value")
        age = obs.age_s(snapshot.as_of)
        if age is None:
            return out(UNKNOWN, None, "observation time unknown or in the future")
        if lim.max_age_s is None:
            return out(UNKNOWN, age, f"no freshness limit is defined for {signal} in {self.purpose} use")
        if age <= lim.max_age_s:
            return out(FRESH, age, f"{age:.0f} s old, limit {lim.max_age_s:.0f} s")
        return out(STALE, age, f"{age:.0f} s old, limit {lim.max_age_s:.0f} s")

    def not_fresh(self, snapshot: Snapshot, signals: Iterable[str]) -> tuple[Assessment, ...]:
        """The assessments of `signals` that are not FRESH (empty = every one is fresh)."""
        return tuple(a for a in (self.assess(snapshot, s) for s in signals) if not a.fresh)


def catalogue_rows() -> list[dict]:
    """The catalogue as plain rows (documentation and review)."""
    return [{"signal": c.signal, "purpose": c.purpose, "max_age_s": c.max_age_s, "standing": c.standing,
             "source": c.source, "note": c.note} for c in CATALOGUE]
