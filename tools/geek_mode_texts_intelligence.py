"""The plain-words texts of the Geek Mode catalogue for the ECCO Intelligence SHADOW tab (data only; no logic).

tools/geek_mode_coverage.py computes WHAT exists (from the contract, the packages, the integration and the advisors) and takes
the words from here. It refuses a source or attribute that has no text, and a text whose source or attribute no longer exists,
so this file cannot lag the code and cannot keep an invented entry.

Lookup order for an attribute text: ENTITY_ATTRS[source id], then KIND_ATTRS[entity kind], then COMMON_ATTRS.
An entry is (priority, text): 'headline' = what a normal user cares about, 'normal', 'obscure' = diagnostics.
All text is ASCII. Written for people, not for the code: no internal jargon without its meaning.
"""

from __future__ import annotations


def H(text):
    return ("headline", text)


def N(text):
    return ("normal", text)


def O(text):
    return ("obscure", text)


TITLE = "ECCO Intelligence (SHADOW)"

GROUPS = [
    {"id": "health", "title": "Status and health", "order": 10,
     "description": "Is ECCO Intelligence running, is its latest result fresh, and does the watchdog agree?"},
    {"id": "advice", "title": "Advice", "order": 20,
     "description": "The advice items: what ECCO Intelligence would suggest, and why. Advice only; nothing is applied."},
    {"id": "forecasts", "title": "Forecasts", "order": 30,
     "description": "Predictions for tomorrow: the home's demand, solar generation and the battery level in the morning."},
    {"id": "quality", "title": "Data quality and accuracy", "order": 40,
     "description": "How reliable the inputs are and how accurate recent results have been."},
    {"id": "controls", "title": "Controls and alerts", "order": 50,
     "description": "The pause switch, the reserve preference and the three alert automations. Geek Mode only shows them."},
    {"id": "discovered", "title": "Discovered (not in the catalogue)", "order": 90,
     "description": "Entities that follow the ecco_intel_ naming but are not in this catalogue yet. They appear here by themselves."},
]

SOURCES = {
    "intel.status": {
        "group": "health", "title": "Intelligence status", "priority": "headline",
        "description": "The one word that says whether ECCO Intelligence has advice for you right now: OK, NO_ADVICE, BLOCKED, "
                       "INSUFFICIENT_DATA, STARTING, PAUSED, STALE or SELF_TEST_FAILED. Its attributes carry the report time, the "
                       "blocked conditions, the open owner decisions, the input ages and more. Advice only: nothing it says is applied."},
    "intel.fresh": {
        "group": "health", "title": "Result is fresh (integration)", "priority": "normal",
        "description": "On while the integration's latest result is still inside its validity time and the system is not paused, "
                       "stale, starting or failed. Off means there is no current result."},
    "intel.watchdog_fresh": {
        "group": "health", "title": "Watchdog: recognised, recent result", "priority": "headline",
        "description": "Home Assistant's own dead-man check on the status. On only while a recognised, recent result exists. It keeps "
                       "working when the integration itself is down, which is why it is the most reliable sign of a silent failure."},
    "intel.paused": {
        "group": "controls", "title": "Pause switch (advice only)", "priority": "headline",
        "description": "The owner's pause for ECCO Intelligence advice. While it is on, Intelligence publishes PAUSED and no advice. "
                       "It pauses advice only: it does not touch the battery, the inverter or any other setting. Geek Mode only shows it."},
    "intel.data_quality": {
        "group": "quality", "title": "Data quality", "priority": "headline",
        "description": "One word for how reliable the inputs to the latest result were: OK, DEGRADED, BLOCKED or UNKNOWN. UNKNOWN "
                       "also appears while the system is paused, stale, starting or failed its self-test."},
    "intel.accuracy": {
        "group": "quality", "title": "Recent accuracy", "priority": "normal",
        "description": "How far recent results were from what really happened: the state is the mean absolute error over the last 7 "
                       "days in kWh; the share of days measured and the number of measurements are attributes. Empty until there are "
                       "enough outcomes."},
    "intel.charge_target": {
        "group": "advice", "title": "Next charge target", "priority": "headline",
        "description": "The battery level, in percent, that ECCO Intelligence advises charging to by the end of the next cheap-rate "
                       "window: the reserve plus a margin plus the battery's share of the energy the home is expected to use. The "
                       "state is empty unless the status is OK and the result is still valid. Advice only."},
    "intel.overnight_demand": {
        "group": "advice", "title": "Overnight demand", "priority": "normal",
        "description": "The energy, in kWh, that ECCO Intelligence plans for the home to use overnight, learned from recent nights. "
                       "The state is the cautious planning value; the expected value is in the details. Advice only."},
    "intel.export_event": {
        "group": "advice", "title": "Export event", "priority": "normal",
        "description": "For an export event such as a saving session: the energy, in kWh, that could be exported while the home stays "
                       "covered and the reserve stays intact. Empty when there is no event or it cannot be judged. Advice only."},
    "intel.dump_to_grid": {
        "group": "advice", "title": "Dump to Grid estimate", "priority": "normal",
        "description": "The energy, in kWh, that a reserve-aware Dump to Grid would export now, stopping at a level that keeps the "
                       "reserve and what the home needs until the next refill. Advice only: the Dump to Grid feature does not read it."},
    "intel.predicted_day_load": {
        "group": "forecasts", "title": "Demand forecast (tomorrow)", "priority": "normal",
        "description": "The home's expected energy use tomorrow, in kWh (the middle estimate); the low and high ends of the range are "
                       "the attributes p10 and p90."},
    "intel.pv_tomorrow": {
        "group": "forecasts", "title": "Solar tomorrow", "priority": "headline",
        "description": "The expected solar generation tomorrow, in kWh (the middle estimate), corrected using how past forecasts "
                       "compared with what happened; the low and high ends are the attributes p10 and p90."},
    "intel.predicted_morning_soc": {
        "group": "forecasts", "title": "Predicted morning battery", "priority": "headline",
        "description": "The battery level, in percent, expected tomorrow morning if the advised charge target is reached at the end of "
                       "the window and the forecast demand and solar then apply, with the reserve held."},
    "intel.pref.advisory_reserve_raise_pct": {
        "group": "controls", "title": "Reserve raise preference", "priority": "normal",
        "description": "A number, 0 to 100 percent, that the owner can set to RAISE the reserve level used by ECCO Intelligence advice "
                       "(it can never lower it). It is a preference, not a decision. Nothing in ECCO writes it; the owner edits it in "
                       "Home Assistant. It is read only when the owner's site file maps it. Geek Mode only shows it."},
    "intel.automation.alert_watchdog_stale": {
        "group": "controls", "title": "Alert: no fresh result", "priority": "obscure",
        "description": "A Home Assistant automation that raises one notification when the watchdog has stayed off for 30 minutes while "
                       "the pause is not on. It only creates a notification and changes nothing else."},
    "intel.automation.alert_self_test_failed": {
        "group": "controls", "title": "Alert: self-test failed", "priority": "obscure",
        "description": "A Home Assistant automation that raises one notification when the status turns SELF_TEST_FAILED, or already is "
                       "when Home Assistant starts. It only creates a notification and changes nothing else."},
    "intel.automation.alert_contract_mismatch": {
        "group": "controls", "title": "Alert: output not recognised", "priority": "obscure",
        "description": "A Home Assistant automation that raises one notification when the status is published in a form the package and "
                       "card do not recognise (wrong contract version, not advice-only, or no integration version). It only creates a "
                       "notification and changes nothing else."},
}

# ---------------------------------------------------------------------------------------------------------------------
# attribute texts
# ---------------------------------------------------------------------------------------------------------------------

DECISION_ATTR = ("normal", "Owner decision {label}: {title}. Its state is OPEN (not decided yet), RECORDED (decided) or INVALID "
                           "(recorded but not usable). Battery advice that depends on it stays withheld until it is RECORDED.")

COMMON_ATTRS = {
    "mode": O("The mode the integration reports. Always SHADOW: advice only, nothing is applied."),
    "applies_nothing": N("A safety flag that is always true: ECCO Intelligence applies nothing to the battery, the inverter or any "
                         "setting. If it were ever false, this output must not be trusted."),
    "contract_version": O("The version of the data contract this entity follows (ecco-intel-entities/1). Readers only trust a result "
                          "whose version is the one they expect."),
    "kind": O("Which part of the Intelligence output this entity is (for example status or charge_target). Readers use it to check "
              "they are looking at the right entity."),
    "generated_at": N("When the result was computed (UTC). All entities of one publish share this time."),
    "unit": O("The unit of this entity's figure, such as % or kWh. Empty for an entity without a figure."),
    "reason_codes": N("Short codes that explain why the result looks the way it does: a rule that applied, a data gap, a test value. "
                      "Each code names one reason; the list can be empty."),
    "blockers": H("The conditions that currently withhold this result. Each has a short code and a sentence saying what is missing. "
                  "An empty list means nothing blocks it."),
    "friendly_name": O("The display name Home Assistant shows for this entity."),
    "unit_of_measurement": O("The unit Home Assistant attaches to the state."),
    "device_class": O("Home Assistant's device class. 'enum' tells Home Assistant that the state is one of a fixed list of words."),
    "options": O("The complete list of words the state can take."),
    "icon": O("The icon Home Assistant shows for this entity."),
    "editable": O("True when the helper can be edited in the Home Assistant interface; false for a helper defined in a configuration file."),
    "advice.status": N("Only when the item is not OK: the item's status (BLOCKED, INSUFFICIENT_DATA, NO_ADVICE or WITHHELD). Absent when "
                       "the item is OK, because the full advice is given instead."),
    "advice.blocker_codes": N("Only when the item is not OK: the short codes of the conditions that block it. Absent when the item is OK."),
}

KIND_ATTRS = {
    "item": {
        "status": H("The status of this advice item: OK (a figure is given), BLOCKED (a condition withholds it), INSUFFICIENT_DATA, "
                    "NO_ADVICE (nothing to advise), or WITHHELD (not computed because the system is paused, stale, starting or "
                    "failed its self-test)."),
        "confidence": N("How much to trust the figure: HIGH, MEDIUM, LOW or INSUFFICIENT. Empty when there is no figure."),
        "valid_until": N("The time until which this advice may be used. Empty unless the item is OK."),
        "advice": N("The working behind the figure. For an OK item: the full breakdown (the sub-rows below). For an item that is not "
                    "OK: only its status and the codes of what blocks it."),
        "engine_comparison": O("A comparison with the older V1 engine's answer. Only the charge target carries it, and only while it is "
                               "OK; empty otherwise."),
        "advice.reserve": N("How the effective battery reserve was worked out: the owner's reserve, the technical minimum, any Home "
                            "Assistant reserve and any raise preference, and which of them set the level."),
        "advice.effective_reserve_pct": N("The lowest battery level, in percent, this advice allows itself: the highest of the owner's "
                                          "reserve, the technical minimum, a Home Assistant reserve and the raise preference."),
        "advice.export_kwh": H("The energy, in kWh, that could be exported (rounded down, within the power limits when they are known)."),
        "advice.export_kw_avg": N("The average export power, in kW, that exporting that energy over the available time would need."),
        "advice.desired_min_pct": N("The lowest battery level, in percent, this advice plans to leave: the effective reserve plus the "
                                    "safety margin."),
    },
    "forecast": {
        "status": H("The status of this forecast: OK (a figure is given), BLOCKED, INSUFFICIENT_DATA, or WITHHELD (not computed because "
                    "the system is paused, stale, starting or failed its self-test)."),
        "confidence": N("How much to trust the forecast: HIGH, MEDIUM, LOW or INSUFFICIENT. Empty when there is no figure."),
        "valid_until": N("The time until which this forecast may be used. Empty unless the forecast is OK."),
        "p10": N("The low end of the forecast range (the 10th percentile): the real value should be above it about 9 times in 10."),
        "p90": N("The high end of the forecast range (the 90th percentile): the real value should be below it about 9 times in 10."),
        "advice": N("The working behind the forecast. For an OK forecast: its summary (the sub-rows below). For one that is not OK: "
                    "only its status and the codes of what blocks it."),
        "advice.confidence": N("The forecast's confidence as a score between 0 and 1."),
        "advice.label": N("The forecast's confidence as a word: HIGH, MEDIUM, LOW or INSUFFICIENT."),
        "advice.usable": N("True when the forecast has enough evidence to be used."),
        "advice.p10": N("The low end of the range (10th percentile)."),
        "advice.p50": H("The middle estimate (the median)."),
        "advice.p90": N("The high end of the range (90th percentile)."),
    },
    "accuracy": {
        "status": O("The overall ECCO Intelligence status when this accuracy figure was published."),
        "coverage_7d": N("The share of the last 7 days for which an accuracy figure could be measured, between 0 and 1. Empty when not "
                         "measured or when the system is paused, stale, starting or failed."),
        "n": N("How many measurements the accuracy figure rests on. Empty when not measured."),
        "reason_codes": O("Short codes that explain the accuracy figure. Usually empty."),
    },
    "data_quality": {
        "status": O("The overall ECCO Intelligence status when this data-quality word was published."),
        "coverage_7d": O("Not used by data quality: always empty. It exists so that the accuracy and data-quality entities share a shape."),
        "n": O("Not used by data quality: always empty."),
        "reason_codes": H("Short codes that explain why data quality has its current value: which input is missing, old or unusable."),
        "unit": O("Always empty: data quality is a word, not a measured figure."),
    },
    "fresh": {
        "status": O("The overall ECCO Intelligence status when this freshness flag was published."),
        "valid_until": N("The time until which the latest result counts as fresh. Empty under a paused, stale, starting or failed status."),
    },
    "pause_helper": {
        "editable": O("False: the pause switch is defined in a configuration file, so its settings cannot be edited in the interface. "
                      "Its on/off state is still changed from the Pause tile."),
    },
    "automation": {
        "friendly_name": O("The automation's name in Home Assistant."),
        "current": O("How many runs of this automation are in progress right now. Normally 0."),
        "id": O("The automation's fixed identifier."),
        "last_triggered": O("When the automation last ran, or empty if it never has."),
        "mode": O("How Home Assistant treats overlapping runs. 'single' means a new run is ignored while one is in progress."),
    },
    "reserve_helper": {
        "min": O("The lowest value the preference can take: 0 percent."),
        "max": O("The highest value the preference can take: 100 percent."),
        "step": O("The step size of the preference: 1 percent."),
        "mode": O("How the number is entered in Home Assistant: 'box' means a typed number."),
        "initial": O("The value Home Assistant starts with; empty here, so the owner's last value is restored at every start."),
        "unit_of_measurement": O("The unit of the preference: percent."),
    },
}

ENTITY_ATTRS = {
    "intel.status": {
        "status": H("The same word as the state: the overall status (OK, NO_ADVICE, BLOCKED, INSUFFICIENT_DATA, STARTING, PAUSED, "
                    "STALE or SELF_TEST_FAILED)."),
        "kind": O("Always 'status' for this entity."),
        "generated_at": N("When the cycle that produced every figure ran (UTC). All entities of one publish share this time."),
        "valid_until": N("Until when the whole result may be used. After it, nothing may be shown as current advice. Empty while "
                         "paused, starting, stale or failed."),
        "next_run_at": H("When the integration plans to run its next cycle."),
        "integration_version": N("The version of the ECCO Intelligence integration that produced this result."),
        "engine_version": O("The version of the advice engine inside the integration."),
        "git_sha": O("The source-code revision the engine was built from. Geek Mode withholds the value: the integration's own "
                     "diagnostics redact it as a site value."),
        "config_hash": O("A fingerprint of the site configuration, used to tell whether it changed. Geek Mode withholds the value: "
                         "the integration's own diagnostics redact it as a site value."),
        "blockers": H("The conditions that withhold advice as a whole, not tied to one item (for example an owner decision that is "
                      "INVALID). Each has a short code and a sentence. An empty list means none."),
        "reason_codes": N("Short codes that explain the overall result: why advice is withheld, a missing pause switch, a redacted text."),
        "decisions": N("The state of each of the nine owner decisions, I-D1 to I-D9."),
        "provenance_ok": N("True while every recorded owner decision comes from a source the system accepts (not a test or synthetic "
                           "source)."),
        "pause_control": H("What the integration sees of the pause switch: ON, OFF, or MISSING (the switch does not exist, so "
                           "Intelligence treats it as not paused)."),
        "data_quality": H("The data-quality word for this result: OK, DEGRADED, BLOCKED or UNKNOWN."),
        "tariff": N("The tariff facts the plan used: how far its prices can be trusted, the charge window and the price range. Prices "
                    "appear only when the tariff is verified."),
        "tariff.provenance": N("Where the tariff's prices come from and how far they can be trusted. Only VERIFIED or "
                               "VERIFIED_FROM_INTEGRATION allow prices to be shown."),
        "tariff.window": N("The cheap-rate charge window the plan used (start and end, UTC), or empty."),
        "tariff.price_range": N("The lowest and highest unit price in the verified window, in pence per kWh. Empty unless the tariff "
                                "is verified."),
        "value": N("An estimate of the money value of following the advice, with its assumptions and the alternatives it was compared "
                   "with. Only with a verified tariff and an OK charge target; empty otherwise."),
        "value.range_gbp": N("The estimated saving as a low-to-high range, in pounds, against the main alternative. Rounded outward, "
                             "so it never claims more precision than the evidence."),
        "value.assumptions": N("The assumptions behind the money estimate, in words (for example that VAT and the standing charge are "
                               "excluded)."),
        "value.baselines": N("The alternatives the saving was compared with (for example always charging to the maximum), each with its own "
                             "low-to-high range in pounds."),
        "plan": N("The plan around the charge target: when to pre-charge by, the PV headroom ceiling and when the reserve would run out. "
                  "Only while the charge target is OK; empty otherwise."),
        "plan.precharge_by": N("The time by which charging should start, taken from the older V1 recommendation, or empty."),
        "plan.headroom_ceiling_pct": N("The highest charge level, in percent, that still leaves room for tomorrow's solar on a cautious "
                                       "forecast. The charge target stays the authority when it is higher."),
        "plan.reserve_runout_at": N("When, without grid charging, the battery would reach its reserve level before the planning horizon "
                                    "ends, or empty."),
        "accuracy": N("The recent accuracy block: mean absolute error, how much of the last 7 days was measured, and the number of "
                      "measurements. Empty until measured."),
        "accuracy.mae_7d": N("The mean absolute error of recent results over 7 days, in kWh."),
        "accuracy.coverage_7d": N("The share of the last 7 days that could be measured, between 0 and 1."),
        "accuracy.n": N("How many measurements the accuracy block rests on."),
        "drift": O("Reserved for a future release. Always empty in this one."),
        "calibration": O("Reserved for a future release. Always empty in this one."),
        "self_test": N("The result of the integration's start-up self-test, one entry per check: PASS, or FAIL followed by the reason. "
                       "Empty when the integration carries no self-test result."),
        "input_ages": H("How old each input to the latest cycle was, against its freshness limit. One row per input with its name, age "
                        "in seconds, limit in seconds and a status: fresh, stale, unknown or missing."),
        "last_good": N("Only while paused, stale, starting or failed: the last good figures from before, with the time they were "
                       "computed. History for reference, never current advice."),
        "last_good.generated_at": N("When the last good figures were computed (UTC)."),
        "last_good.values": N("The last good figure of each item and forecast that had one, by name."),
    },
    "intel.charge_target": {
        "advice.target_soc_pct": H("The advised charge target, in percent: charge to this level by the end of the window. Advice only."),
        "advice.raw_target_soc_pct": N("The target before rounding up to the next step and capping at the maximum, in percent. Empty "
                                       "when there was not enough evidence."),
        "advice.binding_constraint": H("What set or capped the target: RESERVE, DESIRED_MORNING_SOC, DEMAND, MAX_SOC (even a full "
                                       "battery may not cover the period), CHARGE_WINDOW (the window cannot reach the target) or "
                                       "NO_DEMAND_EVIDENCE."),
        "advice.shortfall_soc_pct": N("How many percentage points the need exceeds the maximum charge level. 0 means the target covers it."),
        "advice.buffer_pct": N("The safety margin, in percentage points, kept above the reserve."),
        "advice.end_of_period_floor_pct": N("The lowest level, in percent, the battery should still have at the end of the period: the higher "
                                            "of the reserve plus margin and the desired morning level."),
        "advice.desired_morning_soc_pct": N("The morning battery level the owner would like, in percent, or empty if none is set."),
        "advice.demand_planning_kwh": N("The cautious (planning) overnight demand used, in kWh."),
        "advice.demand_expected_kwh": N("The expected (middle) overnight demand, in kWh, for comparison."),
        "advice.pv_credit_used_kwh": N("Solar energy, in kWh, counted against the demand. 0 unless a solar credit was vouched for with at "
                                       "least MEDIUM confidence."),
        "advice.net_need_kwh": N("The energy, in kWh, the battery has to supply after the solar credit."),
        "advice.need_soc_pct": N("The net need expressed as battery percentage points, allowing for charging losses and capacity."),
        "advice.window": N("The charge window the target is for: its start and end times."),
        "advice.achievable_soc_pct": N("The level, in percent, the window can reach from the level it starts at. Empty when that level is "
                                       "not known."),
        "advice.grid_charge_kwh": N("The energy, in kWh, to take from the grid to reach the target. Empty when the starting level is "
                                    "not known."),
        "advice.window_start_soc_pct": N("The battery level, in percent, the window starts from. Empty when not known."),
        "advice.window_start_soc_source": O("Where the starting level came from: the current level (window open) or a predicted one."),
        "advice.inputs_used": O("The rounded inputs of this calculation (floor, demand, solar credit, capacity, efficiency). They are "
                                "compared with the previous advice to say what moved the target."),
        "advice.changed_from_previous": N("What changed since the previous advice: the change in points and the inputs that drove it. "
                                          "Empty when there is no previous advice."),
        "advice.conservative_fallback": N("True when the target is the cautious default (charge to the maximum) because overnight demand "
                                          "has not been learned yet."),
        "engine_comparison.authority": O("Which engine's answer is the authority: the V1.1 charge target."),
        "engine_comparison.basis": O("How the two engines differ: an hourly simulation (V1) versus a closed-form budget (V1.1)."),
        "engine_comparison.difference_pct": N("V1's target minus the V1.1 target, in percentage points."),
        "engine_comparison.v11_target_soc_pct": N("The V1.1 charge target, in percent (the same as the advice)."),
        "engine_comparison.v1_feasible_on_pessimistic_path": N("Whether V1's target stays feasible on its pessimistic forecast path."),
        "engine_comparison.v1_target_soc_pct": N("The older V1 engine's target, in percent."),
    },
    "intel.overnight_demand": {
        "advice.expected_kwh": N("The expected (middle) energy for the coming night, in kWh."),
        "advice.planning_kwh": H("The cautious planning energy for the coming night, in kWh. This is the state."),
        "advice.planning_quantile": O("How cautious the planning value is: 0.9 means the night's use should be below it about 9 nights "
                                      "in 10."),
        "advice.learned_kwh": N("The energy learned from recent nights alone, in kWh."),
        "advice.nights_used": N("How many clean nights the estimate rests on."),
        "advice.nights_window": N("How many past nights were looked at."),
        "advice.latest_night": N("The date of the most recent night that was used."),
        "advice.nights_missing_since_latest": N("How many nights since the latest used night had no clean data."),
        "advice.nights_clipped": N("The nights whose totals were unusual and were clipped so they could not distort the estimate, each with "
                                   "its original and clipped energy in kWh."),
        "advice.nights_excluded": N("Nights left out on purpose: a count for each reason code (for example DECLARED_AWAY)."),
        "advice.nights_invalid": N("How many nights were unusable because the total was not a valid number."),
        "advice.prior_kwh": N("The configured default, in kWh, blended in while few nights are known. Empty when none is configured."),
        "advice.prior_weight": N("How much of the estimate comes from that default instead of learned nights, between 0 and 1."),
        "advice.regime": N("Whether recent nights look like the longer baseline (NORMAL), far lower (for example an empty house), far "
                           "higher, or UNKNOWN."),
        "advice.recent_median_kwh": N("The median of the most recent nights, in kWh."),
        "advice.baseline_median_kwh": N("The median of the older baseline nights, in kWh."),
        "advice.recent_to_baseline_ratio": N("Recent median divided by baseline median. Near 1 means similar."),
        "advice.recent_robust_z": O("How unusual the recent nights are against the baseline, in robust standard deviations."),
        "advice.conservative_fallback": N("True when the figure is the configured cautious default because too few clean nights are "
                                          "known."),
    },
    "intel.export_event": {
        "advice.event": N("The event this advice is for: its label, start, end, whether it has started and the hours remaining."),
        "advice.cover_household_from_battery": N("Whether the battery can carry the home through the event without importing while still "
                                                 "keeping what is needed afterwards."),
        "advice.export_advised": N("Whether exporting is worth advising (the exportable energy is above the minimum worth advising)."),
        "advice.binding_constraint": N("What limits the export: ENERGY_ABOVE_RESERVE (the energy above the reserve after what must be "
                                       "kept for later) or POWER_LIMIT (the discharge or export power limits)."),
        "advice.soc_at_start_pct": N("The battery level, in percent, when the event starts."),
        "advice.soc_at_end_expected_pct": N("The battery level, in percent, expected when the event ends."),
        "advice.energy_above_minimum_kwh": N("The battery energy, in kWh, above the minimum level at the start."),
        "advice.keep_for_after_kwh": N("The energy, in kWh, kept back for the home's needs after the event until the next refill."),
        "advice.household_during_kwh": N("The energy, in kWh, the home is expected to use during the event."),
        "advice.energy_for_export_kwh": N("The energy, in kWh, left over for export after the home's needs."),
    },
    "intel.dump_to_grid": {
        "advice.dump_advisable": H("Whether a reserve-aware Dump to Grid would be advisable now."),
        "advice.stop_soc_pct": H("The stop level, in percent, such a Dump to Grid would use. Empty when it is above the feature's maximum, "
                                 "so there is nothing to advise."),
        "advice.raw_stop_soc_pct": N("The stop level before rounding up to a whole percent and keeping inside the feature's range."),
        "advice.stop_set_by": N("What set the stop level: RESERVE_AND_DEMAND (the reserve, margin and later needs), FEATURE_MINIMUM (the "
                                "feature's own lowest stop level) or ABOVE_FEATURE_RANGE (nothing to advise)."),
        "advice.export_limited_by": N("What limits the export amount: STOP_LEVEL (the energy above the stop level) or POWER_LIMIT, or empty "
                                      "when not stated."),
        "advice.soc_pct": N("The battery level, in percent, when the advice was computed."),
        "advice.keep_until_refill_kwh": N("The energy, in kWh, kept back for the home until the next refill."),
        "advice.keep_soc_pct": N("That kept-back energy expressed as battery percentage points."),
        "advice.refill_at": N("When the battery can next be refilled (the end of the next cheap-rate window)."),
        "advice.feature_stop_bounds_pct": O("The lowest and highest stop level, in percent, that the Dump to Grid feature accepts."),
    },
    "intel.predicted_day_load": {
        "advice.kind": O("Which kind of forecast this is (a day forecast)."),
        "advice.t0": N("The start of the forecast period (UTC)."),
        "advice.t1": N("The end of the forecast period (UTC)."),
        "advice.n_days": N("How many past days the forecast rests on."),
        "advice.n_residuals": N("How many past forecast errors were used to size the range."),
    },
    "intel.pv_tomorrow": {
        "advice.day": N("The day this forecast is for."),
        "advice.source": N("Where the raw forecast came from, or 'persistence' (a repeat of recent days) when none was usable."),
        "advice.raw_kwh": N("The raw forecast, in kWh, before correction. Empty when none was usable."),
        "advice.ratio": N("The correction factor applied to the raw forecast, learned from past forecasts versus what happened."),
        "advice.inflation": O("How much the range was widened because recent results fell outside it. 1 means not widened."),
        "advice.n_pairs": N("How many past forecast-versus-actual pairs the correction rests on."),
        "advice.mae_corrected": N("The recent mean absolute error of the corrected forecast, in kWh."),
        "advice.mae_raw": N("The recent mean absolute error of the raw forecast, in kWh, for comparison."),
        "advice.notes": N("Plain-words notes about this forecast."),
        "advice.plausibility": O("The result of the sanity check: a verdict, the ceilings used, and any forecast source that was rejected."),
    },
    "intel.predicted_morning_soc": {
        "advice.at": N("The time the morning level refers to."),
        "advice.planned_window_end_soc_pct": N("The battery level, in percent, planned at the end of the charge window (the start of this "
                                               "prediction)."),
        "advice.basis": N("How the prediction is built, in words."),
    },
}

# units that the suffix rules in the tool do not give (path or leaf name -> unit)
ATTR_UNITS = {
    "tariff.price_range": "p/kWh", "value.range_gbp": "GBP", "value.baselines": "GBP", "mae_7d": "kWh", "mae_corrected": "kWh",
    "mae_raw": "kWh",
}

# ---------------------------------------------------------------------------------------------------------------------
# alerts (derived from the contract's statuses; the tool refuses a status or data-quality state that is in neither table)
# ---------------------------------------------------------------------------------------------------------------------

STATUS_ALERTS = {
    "PAUSED": ("info", "ECCO Intelligence is paused. It is producing no advice.",
               "Turn the Pause switch off when you want advice again. Nothing else is affected."),
    "SELF_TEST_FAILED": ("critical", "ECCO Intelligence failed its start-up self-test and is publishing no advice.",
                         "Open the status details to see which checks failed, fix them, then reload the ECCO Intelligence integration "
                         "in Home Assistant."),
    "STALE": ("warning", "The last ECCO Intelligence result is out of date, so no advice figures are shown.",
              "Check that the ECCO Intelligence integration is loaded (Settings, Devices and services). Nothing on your system was "
              "changed."),
    "STARTING": ("info", "ECCO Intelligence is starting up. The first result normally arrives within a few minutes.",
                 "Wait a few minutes. If it stays like this, check that the integration is loaded."),
    "BLOCKED": ("info", "ECCO Intelligence is withholding advice because a required input or an owner decision is not in place.",
                "Open the blocked conditions to see exactly what is missing. Nothing is applied either way."),
    "INSUFFICIENT_DATA": ("info", "ECCO Intelligence does not have enough recent data to give advice yet.",
                          "No action is needed; figures appear once enough history has been collected."),
}
NO_ALERT_STATUSES = ("OK", "NO_ADVICE")

DQ_ALERTS = {
    "BLOCKED": ("warning", "Data quality is blocked: ECCO Intelligence cannot rely on its inputs, so advice is withheld.",
                "Open the input ages and the blocked conditions to see which input is missing or too old."),
    "DEGRADED": ("info", "Data quality is degraded: some inputs are old or missing, so advice has lower confidence.",
                 "Open the input ages to see which input needs attention."),
}
NO_ALERT_DQ = ("OK", "UNKNOWN")

OTHER_ALERTS = [
    {"id": "status_unavailable", "severity": "critical", "entity": "status", "when": {"unavailable": True},
     "text": "ECCO Intelligence is not publishing: its status is unavailable or missing.",
     "action": "Check that the ECCO Intelligence integration is installed and loaded in Settings, Devices and services. Nothing on "
               "your system was changed."},
    {"id": "status_unknown", "severity": "info", "entity": "status", "when": {"state_in": ["unknown"]},
     "text": "ECCO Intelligence has not published a result yet.",
     "action": "Wait a few minutes after Home Assistant starts. If it stays like this, check that the integration is loaded."},
    {"id": "applies_nothing_false", "severity": "critical", "entity": "status", "when": {"attribute": "applies_nothing", "in": [False, "false", "False"]},
     "text": "ECCO Intelligence reports that it may apply changes. This release is advice only and must never do that.",
     "action": "Do not rely on its output. Disable the ECCO Intelligence integration and report this."},
    # The package watchdog template turns OFF when the status entity itself says one of these four things. A watchdog that is off is only a
    # warning, so without these lines the strip would not name a safety breach that the status states plainly. "@contract_version" and
    # "@statuses" are placeholders the tool fills from the contract (never typed here, so they cannot drift from the code).
    {"id": "mode_not_shadow", "severity": "critical", "entity": "status", "when": {"attribute": "mode", "not_in": ["SHADOW"]},
     "text": "ECCO Intelligence reports a mode other than SHADOW. This release is advice only and must never run in any other mode.",
     "action": "Do not rely on its output. Disable the ECCO Intelligence integration and report this."},
    # Every value that is not the boolean true and is not already named by applies_nothing_false below (false, "false", "False"): the two alerts
    # together cover every value but the boolean true, and no value raises both.
    {"id": "applies_nothing_not_true", "severity": "critical", "entity": "status",
     "when": {"attribute": "applies_nothing", "not_in": [True, False, "false", "False"]},
     "text": "ECCO Intelligence does not state that it applies nothing. This release is advice only and must always say so.",
     "action": "Do not rely on its output. Disable the ECCO Intelligence integration and report this."},
    {"id": "contract_mismatch", "severity": "critical", "entity": "status", "when": {"attribute": "contract_version", "not_in": ["@contract_version"]},
     "text": "ECCO Intelligence publishes a data contract this view does not know, so its figures cannot be trusted here.",
     "action": "Do not rely on the figures shown. Update this dashboard and the ECCO Intelligence package to the same release as the integration, "
               "then reload."},
    {"id": "status_unrecognised", "severity": "warning", "entity": "status", "when": {"state_outside": ["@statuses"]},
     "text": "ECCO Intelligence published a status word this view does not recognise.",
     "action": "Do not rely on the figures shown. Check that this dashboard and the integration are the same release."},
    {"id": "pause_control_missing", "severity": "warning", "entity": "status", "when": {"attribute": "pause_control", "in": ["MISSING"]},
     "text": "ECCO Intelligence cannot see its pause switch, so it cannot be paused from Home Assistant.",
     "action": "Install the ECCO Intelligence package that defines the pause switch, then reload."},
    {"id": "watchdog_off", "severity": "warning", "entity": "watchdog_fresh", "when": {"state_in": ["off"]},
     "text": "The watchdog does not see a fresh, recognised ECCO Intelligence result.",
     "action": "Check that the integration is running. A Home Assistant notification follows if the watchdog stays off for 30 minutes."},
    {"id": "watchdog_unavailable", "severity": "warning", "entity": "watchdog_fresh", "when": {"unavailable": True},
     "text": "The watchdog is missing or unavailable, so a silent failure of ECCO Intelligence would not be noticed.",
     "action": "Install or reload the ECCO Intelligence package that defines the watchdog."},
    {"id": "pause_switch_unavailable", "severity": "warning", "entity": "paused", "when": {"unavailable": True},
     "text": "The pause switch is missing or unavailable, so ECCO Intelligence cannot be paused.",
     "action": "Install or reload the ECCO Intelligence package that defines the pause switch."},
]

# ---------------------------------------------------------------------------------------------------------------------
# exceptions: information that is not a Home Assistant state or attribute, or that must not be shown
# ---------------------------------------------------------------------------------------------------------------------

# one text per top-level section of the integration's diagnostics download (the tool computes which sections exist)
DIAG_SECTIONS = {
    "mode": "The operating mode.",
    "versions": "The integration, engine, source revision and configuration fingerprint.",
    "self_test": "The full start-up self-test with PASS, INFO, WARN and FAIL results.",
    "status": "The status of the last cycle.",
    "reason_codes": "The reason codes of the last cycle.",
    "generated_at": "When the last cycle ran.",
    "counters": "How many cycles of each kind have run and how many were refused or failed.",
    "busy": "Whether a cycle is running right now.",
    "started": "Whether the integration has finished starting.",
    "last_slot": "The last scheduled slot a cycle ran for.",
    "time_budget_s": "The time one cycle may take before it is abandoned.",
    "grace_s": "The start-up grace period before the first cycle.",
    "last_cycle": "A summary of the last cycle, including the notes about each input source.",
    "last_store": "The last write to the integration's own results store.",
    "entities": "The Home Assistant entity ids the owner's site file maps to the cycle's inputs.",
    "decisions": "The state of the owner decisions.",
    "last_cycle_timing": "How long each step of the last cycle took.",
    "cycle_duration_s": "The total duration of the last cycle.",
    "cycle_stats": "A summary of recent cycle durations and counts.",
    "cadence": "The scheduling state: refresh rules, retries, backoff, poll tracking and timers.",
    "liveness": "How recently the input data was seen to change.",
    "proposed_constants": "The engineering limits (proposed values, not owner decisions) the integration runs with.",
}
# Texts for diagnostics sections that ANOTHER change adds to the download (here: the Ghost update's advice-log incidents), written
# before that change is merged with this one. The tool uses such a text only on a tree whose code HAS the section, exactly as a
# DIAG_SECTIONS text; on a tree without it the text waits unused and changes nothing (the catalogue and the ledger stay byte-identical,
# and it is not an orphan). A section the code has that neither table describes is still UNCATALOGUED, and a key in both tables is an
# error. The note the card shows is this text plus one fixed sentence (116 characters) and the card cuts a note at 400 characters
# (cleanText in ecco-mode-shell.js), so keep a text under 280 characters; the coverage suite checks it. Once the other change has
# landed, move the text up into DIAG_SECTIONS.
DIAG_SECTIONS_ARRIVING = {
    "advice_incidents": "Incidents of Intelligence's advice log: each time writing its advice failed or could not be read back (when, attempts, "
                        "cycles missed, kind of error). Only the newest are kept; one open at a restart is lost, so an empty list is no proof "
                        "of a complete log. Nothing is applied.",
}
# the diagnostics sections whose information is ALSO a status attribute with a Geek Mode row (section -> the status attributes);
# the tool checks each claim against the real attributes, and such a section is covered, not an exception
DIAG_COVERED = {"mode": ("mode",), "status": ("status",), "reason_codes": ("reason_codes",), "generated_at": ("generated_at",),
                "decisions": ("decisions",),
                "versions": ("integration_version", "engine_version", "git_sha", "config_hash")}
# a section the status entity publishes only in part (section -> what is missing)
DIAG_PARTIAL = {"self_test": "The status attribute self_test carries only each check's PASS or FAIL result; the download also holds the INFO "
                             "and WARN results and their texts."}

# what AdvisoryEnvelope fields no entity publishes (the tool computes which fields those are)
ENVELOPE_UNPUBLISHED = {
    "scorecard_report": "The scorecard report of one cycle is kept in the integration's own database, never published, and never "
                        "contains a recommendation. Showing it would need a new read-only diagnostic entity.",
}

OTHER_EXCEPTIONS = {
    "recorder_history": (
        "History and long-term statistics of these entities (the Home Assistant recorder)", "not_exposed_in_states",
        "History is not a state: it is read with a history request, and Geek Mode makes no request of any kind. The integration also "
        "keeps the advice, input ages and self-test attributes and the timestamps out of the recorder, so history would lack them. "
        "Showing history would need an explicit decision to allow one read-only history query."),
    "logs": (
        "Home Assistant and integration log lines", "not_exposed_in_states",
        "Logs are files, not states. Showing them would need a read-only log endpoint and a redaction pass: a separate security "
        "decision, not a card feature."),
    "persistent_notifications": (
        "The persistent notifications the three alert automations create", "not_exposed_in_states",
        "A notification is not a state. Their texts are fixed (see the three automations); the alert strip shows the same conditions "
        "from the entity states."),
    "device_registry": (
        "The device record (name, manufacturer, model, software version) of the ECCO Intelligence device", "not_exposed_in_states",
        "The registry is read through a websocket call. The software version is also published as the status attribute "
        "integration_version."),
    "entity_registry": (
        "Entity-registry facts: unique id, disabled or hidden flags, recorder exclusions", "not_exposed_in_states",
        "The registry is read through a websocket call. By contract the unique id equals the entity's object id."),
    "state_context": (
        "The context of each state change (which user, automation or integration caused it)", "privacy",
        "A context can hold user ids. The Intelligence entities are written only by the integration, so it would add nothing."),
    "site_file": (
        "The owner's site file (site.local.json) that maps the cycle's inputs to the owner's own entities", "privacy",
        "It is site data (entity ids, tariffs, device names) and is never shown. The integration's own diagnostics redact the entity "
        "map for the same reason."),
    "scorecard_database": (
        "The scorecard database of past cycles (scorecard.sqlite3 in the integration's state folder)", "not_exposed_in_states",
        "A file, not a state. It holds accuracy bookkeeping only (never a recommendation). Showing it would need a new read-only "
        "diagnostic entity."),
}

# extra key fragments the redactor withholds for this view, beyond the card's own defaults. The tool adds the integration's own
# diagnostics redaction list (TO_REDACT) to these.
EXTRA_REDACTION_KEYS = ()

# the words of the honesty vocabulary (used in the ledger)
HONESTY_WORDS = (
    ("LIVE", "the value is current: it was read from Home Assistant and is within its expected update age"),
    ("STALE", "the value is older than the source's stale_after_s; it is shown with its age and never as current"),
    ("UNAVAILABLE", "Home Assistant reports the entity as unavailable"),
    ("UNKNOWN", "Home Assistant reports the state as unknown (nothing has been published yet)"),
    ("NOT_MEASURED", "the source or attribute is declared but not present in Home Assistant now; no value is invented"),
    ("SIMULATED", "the entity or attribute is flagged as a simulation or test value; it is never shown as a real measurement"),
    ("UNVERIFIED", "the value is present but its provenance is not verified (for example an unverified tariff)"),
    ("WITHHELD", "the value exists but the redaction rules withhold it; the row, its name and its description are still shown"),
)
