"""The Ghost's diagnostics block from the integration's own data (no homeassistant import; runs in the executor, never on the
event loop). Read-only: it reads, it simulates, it returns a dict. It writes nothing, calls no service, adds no entity, changes
no contract and gives no control authority; the block appears only in the diagnostics download. The advice it reads is the advice
log, a durable write that the SLOT cycle's store step makes (runtime/store.py, intelligence/scorecard.py: one table, at most about
52 rows a day, failure-isolated); this module only reads it.

    ghost_block(job, store) -> dict          (never raises: a failure is a small block with a status and a constant reason)
    unavailable(reason) -> dict              the small block for a failure before any computation

Where it is computed, and why there. LAZILY, when the owner downloads the diagnostics, from data the coordinator already holds:
  * the last cycle's EngineJob (the coordinator keeps a reference, without its recorder rows): the HA state copies, the site
    plan, the decisions, the site facts and the cycle time `now`;
  * the recorder statistics the coordinator caches for the slot (the same parsed image the cycles use), turned into a History by
    a THROW-AWAY HistoryReuse, so the coordinator's own reused history is never touched and no recorder read happens;
  * the same input judgement the engine makes (quality.assess_inputs on the same sources.build_sources and
    engine_link.cycle_inputs), so the verified tariffs, the decided battery configuration and the reserve helper are the
    engine's own, not a second opinion;
  * the logged advice, read through RuntimeStateStore.advice_rows (SQLite mode=ro).
So the computation adds nothing to the poll, refresh or slot cycles: its cost is paid by the download only, in the executor, with a
time budget (PROPOSED_GHOST_BUDGET_S) and one job at a time (the advice log it reads is written by the slot cycle, not here). The history is as of the LAST cycle (the block says so: inputs_as_of).

The decided SiteConfig comes from site_decisions.apply_to_siteconfig exactly as the engine's cycle builds it, with ONE
difference: the charge window it insists on is a placeholder (the base configuration's own window), because the Ghost never reads
the cheap window (the advice carries its own windows); a test pins that the block does not depend on it. The grid-charge limit is
the register reading, without the engine's further cap by the TOU table's lowest slot power (a cap that can only lower it).

PROPOSED (engineering suggestion, NOT an owner value): PROPOSED_GHOST_BUDGET_S.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from intelligence import ghost_compare
from intelligence import tariff as tf
from intelligence.ghost_feed import DEFAULT_DAYS
from intelligence.quality import assess_inputs
from intelligence.site_decisions import CHARGE_WINDOW_KEY, InputState, apply_to_siteconfig

from . import engine_link, sources

PROPOSED_GHOST_BUDGET_S = 30.0                # the download waits at most this long for the Ghost block (then: TIME_BUDGET)
ADVICE_LOOKBACK_DAYS = DEFAULT_DAYS + 3       # advice issued up to three days before the period can still be in force in it
HA_RESERVE_KEY = "reserve.ha_minimum_soc"
IMPORT_KEY, EXPORT_KEY = "tariff.import_rates", "tariff.export_rates"


def unavailable(reason: str) -> dict:
    """The block of a failure before any computation (UNAVAILABLE and a constant reason code)."""
    return ghost_compare.small_block(ghost_compare.UNAVAILABLE, reason)


def _observed_at(readings, key: str) -> datetime | None:
    for r in readings:
        if getattr(r, "key", None) == key:
            return getattr(r, "observed_at", None)
    return None


def _helper_reserve(ages) -> float | None:
    """The Home Assistant reserve helper, only when the quality layer judged it fresh under a defined limit and it is a
    percentage; otherwise None (the reserve is then the configuration's, and the advice's own recorded reserve)."""
    st = ages.get(HA_RESERVE_KEY)
    v = st.usable_number if isinstance(st, InputState) else None
    return v if v is not None and 0.0 <= v <= 100.0 else None


def ghost_block(job: engine_link.EngineJob | None, store) -> dict:
    """The diagnostics block for `job` (the last cycle's job, its `statistics` set by the caller) and the state store. Never
    raises."""
    try:
        return _block(job, store)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail the download; only the exception class is kept
        return ghost_compare.error_block(exc)


def _block(job: engine_link.EngineJob | None, store) -> dict:
    if job is None:
        return unavailable(ghost_compare.R_NO_CYCLE)
    now = job.now
    _rows, _truncated, history, newest_end, pv_history, _parsed, _reused = engine_link.HistoryReuse().history(job)
    if history is None:
        return unavailable(ghost_compare.R_NO_STATISTICS)
    src = sources.build_sources(now, job.states, job.entity_map, job.liveness_at, newest_end,
                                config_liveness_at=job.config_liveness_at)
    quality = assess_inputs(engine_link.cycle_inputs(job, src.snapshot, src.site_readings, history, pv_history))
    ages = quality.ages
    base = job.base_cfg
    window = (base.cheap_window_start_min, base.cheap_window_end_min)
    readings = dict(ages)
    readings[CHARGE_WINDOW_KEY] = InputState(CHARGE_WINDOW_KEY, window, True, 0.0, 1.0)   # the placeholder (module docstring)
    cfg, _notes = apply_to_siteconfig(replace(base, tz=job.site_facts.tz), job.decisions, readings)
    if cfg is None:
        return unavailable(ghost_compare.R_CONFIG_NOT_DECIDED)
    try:
        advice = store.advice_rows(now - timedelta(days=ADVICE_LOOKBACK_DAYS), now + timedelta(days=1))
    except Exception:  # noqa: BLE001 - an unreadable log is not an empty one
        return unavailable(ghost_compare.R_ADVICE_LOG)
    imp = tf.assess_rates(ages.get(IMPORT_KEY), now, kind="import", observed_at=_observed_at(src.site_readings, IMPORT_KEY))
    exp = tf.assess_rates(ages.get(EXPORT_KEY), now, kind="export", observed_at=_observed_at(src.site_readings, EXPORT_KEY))
    out = ghost_compare.build_ghost_comparison(history, advice, cfg, import_tariff=imp, export_tariff=exp, now=now,
                                               ha_reserve_pct=_helper_reserve(ages))
    out["inputs_as_of"] = now.isoformat()
    return out
