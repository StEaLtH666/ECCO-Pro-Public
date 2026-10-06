"""Site configuration for ECCO Intelligence V1 (data only, no behaviour)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

# DEFAULT values only. 40 % is the default user reserve, not a project-wide floor: every installation chooses its own
# `user_reserve_soc_pct`. The technical minimum is a separate, site-specific hardware constraint and does NOT encode that
# preference. 10 % is only a placeholder default, NOT a universal battery-safety minimum: set technical_min_soc_pct to the
# minimum permitted by your inverter / battery configuration (for example the inverter's own battery shutdown SOC).
DEFAULT_USER_RESERVE_SOC_PCT = 40.0
DEFAULT_TECHNICAL_MIN_SOC_PCT = 10.0


def _finite(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class EffectiveReserve:
    """The minimum battery SOC every recommendation must respect, plus the context a UI needs to explain it.

    effective = max(user reserve, technical minimum, a reserve value supplied from HA at run time). Pure data: the single value
    other modules (dynamic charge, Dump-to-Grid, Saving Session optimisation, the bridge) can consume later. It
    commands nothing."""
    user_reserve_pct: float             # what the user asked for (user_reserve_soc_pct)
    technical_min_pct: float            # hardware / inverter constraint (technical_min_soc_pct)
    ha_reserve_pct: float | None        # a finite reserve supplied at run time (HA helper), else None; only ever raises
    effective_pct: float
    binding: str                        # "user_reserve" | "technical_min" | "ha_reserve": which input set effective_pct
    override_code: str | None           # None when the user's reserve is what applies
    override_reason: str | None         # plain-language explanation when something above overrides the user's reserve

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SiteConfig:
    # --- site ---------------------------------------------------------
    tz: str = "Europe/London"
    # Demo defaults only. At runtime these come from the HA core config.
    latitude: float = 51.5
    longitude: float = -0.1

    # --- PV array -----------------------------------------------------
    # Nameplate DC size, used ONLY as a physical plausibility ceiling on PV forecasts (intelligence/pv.py). None =
    # unknown: only observed history then limits a forecast. Set it per site (profile / CLI), do not assume it.
    pv_array_kwp: float | None = 9.5            # example value (reference installation): set yours, or None if unknown
    pv_max_kwh_per_kwp_day: float = 8.0         # generous physical ceiling at UK latitudes (a clear midsummer day gives ~6-7)
    pv_history_headroom: float = 1.25           # a forecast above 1.25 x the best day ever observed is rejected
    pv_recent_headroom: float = 2.5             # ... and above 2.5 x the best of the last `pv_recent_days` days
    pv_recent_days: int = 30

    # --- battery ------------------------------------------------------
    battery_capacity_kwh: float = 31.7          # example value (reference installation): set yours (input_number.ecco_battery_model_capacity)
    round_trip_efficiency: float = 0.90         # input_number.ecco_round_trip_efficiency (as a fraction)
    max_soc_pct: float = 100.0

    # --- BATTERY RESERVE (user setting) + TECHNICAL MINIMUM (hardware) -------
    # effective_min_soc = max(user_reserve_soc_pct, technical_min_soc_pct [, a run-time HA reserve value]). Nothing in HA or
    # the firmware enforces that HA value in 0.9.0; it is only an input that can raise this advisory minimum.
    # The intelligence layer recommends ABOVE the effective minimum, never at or below it in any scenario it presents
    # as safe. The user reserve is a PREFERENCE and may be set lower or higher per installation (default 40 %); the
    # technical minimum is a safety constraint the preference can never go below. Neither is mirrored automatically
    # from HA's reserve helper (input_number.ecco_minimum_reserve_soc) or the inverter's shutdown SOC: a reserve
    # supplied at run time can only RAISE the effective minimum.
    user_reserve_soc_pct: float = DEFAULT_USER_RESERVE_SOC_PCT
    technical_min_soc_pct: float = DEFAULT_TECHNICAL_MIN_SOC_PCT
    soc_safety_margin_pct: float = 5.0          # extra headroom above the effective minimum in recommendations

    # --- advisor constants (were module constants in advisor.py) -------------
    max_grid_charge_kw: float = 8.0             # example value (reference installation): your inverter's grid-charge limit (assumed in the cheap window)
    target_step_pct: float = 5.0                # recommended overnight targets are rounded UP to this step
    band_kappa: float = math.sqrt(0.5)          # share of each uncertainty band in the combined pessimistic path

    # --- tariff / operating pattern (defaults: a typical Octopus Go cheap window; set your own)
    cheap_window_start_min: int = 30            # 00:30 local
    cheap_window_end_min: int = 330             # 05:30 local

    # --- definitions ---------------------------------------------------
    useful_pv_threshold_w: float = 500.0        # "meaningful PV" = hourly mean PV at/above this
    stall_power_w: float = 300.0                # counter flat while power above this = stalled counter
    max_gap_fill_hours: int = 6                 # cumulative-counter gap spread limit
    max_hourly_kwh: float = 30.0                # larger counter jumps in one hour are glitches (inverters up to ~8 kW + margin)

    # --- learning -------------------------------------------------------
    fast_alpha: float = 0.30
    slow_alpha: float = 0.08
    winsor_k: float = 5.0                       # 3.0 cost 4-15 % MAE (heavy-tailed evenings); 5.0 keeps most of the protection
    lookback_days_fast: int = 60
    lookback_days_slow: int = 120
    min_days_for_forecast: int = 7              # below this -> INSUFFICIENT_HISTORY
    min_days_for_high_confidence: int = 28

    # --- slow-baseline guard (absence / return-day protection, intelligence/usage.py) ---------------------
    baseline_guard_ratio: float = 0.80          # active when the fast 24 h load is below this share of the long baseline
    baseline_days: int = 30                     # robust per-slot median length of the long baseline

    def __post_init__(self) -> None:
        """Reject values that could weaken the safety floor or make the arithmetic meaningless. Frozen dataclass:
        this runs once, at construction, so a bad profile fails loudly instead of producing quiet advice."""
        def bad(name: str, ok: bool) -> None:
            if not ok:
                raise ValueError(f"SiteConfig.{name} = {getattr(self, name)!r} is not acceptable")
        fin = _finite
        bad("max_soc_pct", fin(self.max_soc_pct) and 0.0 < self.max_soc_pct <= 100.0)
        bad("soc_safety_margin_pct", fin(self.soc_safety_margin_pct) and 0.0 <= self.soc_safety_margin_pct <= 20.0)
        bad("user_reserve_soc_pct", fin(self.user_reserve_soc_pct) and 0.0 <= self.user_reserve_soc_pct <= 100.0)
        bad("technical_min_soc_pct", fin(self.technical_min_soc_pct) and 0.0 <= self.technical_min_soc_pct <= 100.0)
        # the target range [effective minimum + margin, max SOC] must exist: otherwise every recommendation would be a
        # permanent shortfall. (A reserve supplied later at run time that breaks this is handled as a SHORTFALL, not here.)
        base = max(self.user_reserve_soc_pct, self.technical_min_soc_pct)
        bad("technical_min_soc_pct", self.technical_min_soc_pct < self.max_soc_pct)
        bad("max_soc_pct", base + self.soc_safety_margin_pct <= self.max_soc_pct)
        bad("max_grid_charge_kw", fin(self.max_grid_charge_kw) and 0.0 < self.max_grid_charge_kw <= 50.0)
        bad("target_step_pct", fin(self.target_step_pct) and 0.0 < self.target_step_pct <= 25.0)
        bad("band_kappa", fin(self.band_kappa) and 0.5 <= self.band_kappa <= 1.5)
        bad("battery_capacity_kwh", fin(self.battery_capacity_kwh) and self.battery_capacity_kwh > 0.0)
        bad("round_trip_efficiency", fin(self.round_trip_efficiency) and 0.5 <= self.round_trip_efficiency <= 1.0)
        bad("pv_array_kwp", self.pv_array_kwp is None or (fin(self.pv_array_kwp) and self.pv_array_kwp > 0.0))
        bad("pv_max_kwh_per_kwp_day", fin(self.pv_max_kwh_per_kwp_day) and 1.0 <= self.pv_max_kwh_per_kwp_day <= 12.0)
        bad("pv_history_headroom", fin(self.pv_history_headroom) and 1.0 <= self.pv_history_headroom <= 3.0)
        bad("pv_recent_headroom", fin(self.pv_recent_headroom) and 1.0 <= self.pv_recent_headroom <= 5.0)
        bad("pv_recent_days", isinstance(self.pv_recent_days, int) and 7 <= self.pv_recent_days <= 120)
        bad("baseline_guard_ratio", fin(self.baseline_guard_ratio) and 0.3 <= self.baseline_guard_ratio <= 1.0)
        bad("baseline_days", isinstance(self.baseline_days, int) and 14 <= self.baseline_days <= 120)

    def effective_reserve(self, ha_reserve_pct: float | None = None) -> EffectiveReserve:
        """max(user reserve, technical minimum, run-time HA reserve), with the reasoning. A run-time reserve that is
        not a finite number is ignored; anything above 100 is capped at 100. It can only raise the result, so a low
        HA helper never undoes the user's or the hardware's minimum."""
        user, tech = float(self.user_reserve_soc_pct), float(self.technical_min_soc_pct)
        ha = min(100.0, float(ha_reserve_pct)) if _finite(ha_reserve_pct) else None
        eff, binding = user, "user_reserve"
        if tech > eff:
            eff, binding = tech, "technical_min"
        if ha is not None and ha > eff:
            eff, binding = ha, "ha_reserve"
        code = reason = None
        if binding == "technical_min":
            code = "TECHNICAL_MIN_OVERRIDES_USER_RESERVE"
            reason = (f"You asked for a {user:.0f}% minimum battery reserve, but this battery/inverter needs at least "
                      f"{tech:.0f}%, so {eff:.0f}% is used.")
        elif binding == "ha_reserve":
            code = "HA_RESERVE_RAISES_USER_RESERVE"
            reason = (f"The reserve value supplied from Home Assistant ({eff:.0f}%) is above your {user:.0f}% setting "
                      f"(and the {tech:.0f}% technical minimum), so {eff:.0f}% is used.")
        return EffectiveReserve(user, tech, ha, eff, binding, code, reason)

    def effective_min_soc_pct(self, ha_reserve_pct: float | None = None) -> float:
        return self.effective_reserve(ha_reserve_pct).effective_pct

    def config_hash(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
