"""The one call into the vendored engine (no homeassistant import; runs in the executor, never on the event loop).

    compute(job, run_cycle=None) -> (AdvisoryEnvelope, diagnostics)

  1. the recorder rows -> History (history_source), and its newest complete hour (reused while the statistics content is
     unchanged, A50: see below);
  2. the HA state views -> Snapshot + SiteReadings (sources), with the dongle observation times from the poll text and
     the configuration-poll liveness time (the coordinator's second LivenessMemory) passed as config_liveness_at;
  3. ecco_core.bridge.advisory_live_inputs(snapshot, policy=FreshnessPolicy(ADVISORY, overrides=...)) where the overrides
     are site_decisions.freshness_limits(decisions) for the signals ecco_core knows (tighten-only, the 900 s ceiling),
     each dongle signal's limit clamped to the quality layer's liveness bound (V-4, see advisory_overrides);
  4. CycleInputs with the raw snapshot, the LiveInputs AND the bridge's own assessments (the quality layer re-verifies
     every one of them and BLOCKs on any disagreement);
  5. shadow_cycle.run_cycle(inputs) -> AdvisoryEnvelope (injectable for tests).

The diagnostics carry the job's wall time (engine_s, time.perf_counter) and the CPU time of the executor thread that ran it
(cpu_s, time.thread_time): the coordinator's CPU guard sums cpu_s over a rolling hour. They carry the source notes as
sources.public_notes gives them (a contract key and a constant code each, A42), which the diagnostics download shows
unredacted, and the number of notes it withheld (none while sources makes only such notes). They list the snapshot's
signals as sources.public_signals gives them (A45, RV9-3): a contract signal by name, a PV forecast observation by its
day and position only (never the site file's source name), and the number of other names withheld (none).

The parsed history is reused between cycles while the statistics content is unchanged (A50, HistoryReuse below): the
recorder statistics change only at a read (a slot, a catch-up or a retry), yet parsing about 32k rows and building the
History from them took about 0.08 s of every cycle on a desktop test machine, about a third of a refresh once the
engine's profile memo was in. The first cycle after a read parses it into a history_source.StatisticsImage, which the
coordinator keeps instead of the raw mapping and hands to the later cycles of that read. The History built from a whole
image is kept with the image's exact content (its rows, the sign of every zero, the row cap's cut) and the plan, the
configuration and the zone it was built with; a cycle whose image, plan, configuration and zone equal those reuses it,
cut at its own `now` into a new History (history_source.truncate), so it gets exactly what a fresh build gives. A
changed read (any other content) always rebuilds; a refused read (no statistics mapping) drops what is kept and gives no
history. Nothing downstream changes the shared records (the audit, pinned by tests/test_runtime_history_reuse.py): the
quality layer and the PV model only read them, prepare_history changes only its own deep copy, the scorecard reads them,
and the kept History itself never leaves this module (each cycle gets its own container); the PV forecast series are
copied for every cycle. Every freshness, age and expiry judgement still runs on every cycle from its own `now`.

The default acceptance (OWNER_RECORD only) always applies: this module never passes the acceptance keyword, in any form,
and builds no decision (the runtime boundary suite and tests/test_runtime_mapping.py check it). Decisions come only from
DecisionSet.from_mapping(..., source='site_local') in gates.py. In the built kit every absolute intelligence / ecco_core
import here is rewritten by tools/build_ha_integration.py to the package's own _vendor copy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from ecco_core.bridge import advisory_live_inputs
from ecco_core.freshness import ADVISORY, FreshnessPolicy
from ecco_core.state import spec_for
from intelligence.advisory_contract import MODE, AdvisoryEnvelope, CycleInputs, OutcomeMetrics, SiteFacts, Versions
from intelligence.config import SiteConfig
from intelligence.history import History
from intelligence.quality import DQ_PROPOSED
from intelligence.site_decisions import DONGLE_SIGNALS, DecisionSet, freshness_limits

from . import history_source, sources


@dataclass(frozen=True)
class EngineJob:
    """Everything one cycle needs, captured on the event loop as plain data (no HA object crosses into the executor)."""
    now: datetime
    states: Mapping[str, Mapping]             # entity id -> state view (copies), only the mapped entities
    entity_map: sources.EntityMap
    liveness_at: datetime | None
    plan: history_source.HistoryPlan
    # the recorder's statistics_during_period result, or the image a HistoryReuse parsed from it (the coordinator keeps
    # and hands back that image); an image needs history_reuse: the path without one reads a mapping only and gives an
    # image no rows, so every history item BLOCKs
    statistics: Mapping | history_source.StatisticsImage | None
    base_cfg: SiteConfig
    site_facts: SiteFacts
    decisions: DecisionSet
    outcome_metrics: OutcomeMetrics | None
    paused: bool | None
    previous: Mapping | None
    versions: Versions
    config_liveness_at: datetime | None = None   # when the configuration-poll text last changed (None: not seen)
    history_reuse: "HistoryReuse | None" = None   # the coordinator's parsed history (None: parse and build every cycle)


class HistoryReuse:
    """The parsed history of the newest statistics read, kept between cycles (A50; see the module docstring). One entry:
    the key (the image's exact content, the plan, the configuration, the zone), the History built from the whole image
    (never handed out) and the PV forecast series (copied for every cycle). The coordinator owns it and passes it in every
    job; cycles never overlap (the second-run guard), and every change here is one attribute assignment."""

    def __init__(self) -> None:
        self._entry: tuple | None = None
        self._image: history_source.StatisticsImage | None = None
        self.parses = 0                                   # raw reads parsed into an image
        self.builds = 0                                   # Histories built (a changed read, or nothing kept)
        self.reuses = 0                                   # cycles that reused the kept History

    def clear(self) -> None:
        self._entry = None
        self._image = None

    def take_image(self) -> history_source.StatisticsImage | None:
        """The image the last cycle parsed from a raw read (once), for the coordinator to keep instead of that read."""
        img, self._image = self._image, None
        return img

    def history(self, job: EngineJob) -> tuple[int, bool, History | None, datetime | None, dict | None, bool, bool]:
        """(rows, truncated, History or None, its newest end, the PV forecast series or None, parsed, reused) for `job`."""
        stats = job.statistics
        rows = None
        parsed = False
        if isinstance(stats, history_source.StatisticsImage):
            image = stats
        elif isinstance(stats, Mapping):                  # a read: parsed once, its image kept by the coordinator
            rows, truncated = history_source.rows_from_statistics(stats)
            image = history_source.image_from_rows(rows, truncated)
            self._image = image
            self.parses += 1
            parsed = True
        else:                                             # a refused read (or none): nothing kept, no history
            self.clear()
            return 0, False, None, None, None, False, False
        tz = job.site_facts.tz
        key = (image.content(), job.plan, job.base_cfg, tz)
        entry = self._entry
        reused = entry is not None and entry[0] == key
        if reused:
            full, pv_full = entry[1], entry[2]
            self.reuses += 1
        else:                                             # a changed read (or nothing kept): build from the whole image
            rows = rows if rows is not None else image.row_dicts()
            full = history_source.build_full(job.plan, rows, job.base_cfg)
            pv_full = history_source.pv_forecast_history(job.plan, rows, tz)
            self._entry = (key, full, pv_full)
            self.builds += 1
        history, newest_end = history_source.truncate(full, job.now)
        pv_history = {name: dict(series) for name, series in pv_full.items()} or None
        return len(image.rows), image.truncated, history, newest_end, pv_history, parsed, reused


def _history_inputs(job: EngineJob) -> tuple[int, bool, History | None, datetime | None, dict | None, bool, bool]:
    """(rows, truncated, History or None, its newest end, the PV forecast series or None, parsed, reused) for the job:
    through the coordinator's HistoryReuse, or without one parsed and built for this cycle alone. That second path reads
    a statistics mapping only: a StatisticsImage handed in without a HistoryReuse gives no rows, so no history (every
    history item BLOCKs, fail-closed); only a HistoryReuse reads an image."""
    if job.history_reuse is not None:
        return job.history_reuse.history(job)
    rows, truncated = history_source.rows_from_statistics(job.statistics)
    history, newest_end = history_source.build(job.plan, rows, job.base_cfg, job.now)
    pv_history = history_source.pv_forecast_history(job.plan, rows, job.site_facts.tz) or None
    return len(rows), truncated, history, newest_end, pv_history, False, False


def default_run_cycle() -> Callable:
    from intelligence.shadow_cycle import run_cycle
    return run_cycle


def engine_version() -> str:
    from intelligence import MODEL_VERSION
    from intelligence import shadow_cycle
    return f"{getattr(shadow_cycle, 'CYCLE_VERSION', 'unknown')}+{MODEL_VERSION}"


def advisory_overrides(decisions: DecisionSet) -> dict[str, float]:
    """The FreshnessPolicy overrides: site_decisions.freshness_limits for the signals ecco_core.state knows (the gate
    readings are judged by the quality layer only); an unresolved limit is no override (never fresh).

    V-4 (tighten-only): a dongle signal (site_decisions.DONGLE_SIGNALS) is aged from the poll-text liveness time, which the
    quality layer accepts only up to DQ_PROPOSED.liveness_max_age_s. Its limit here is therefore min(its limit, that
    bound), so the caller's assessment and the quality layer's judgement agree: between the liveness bound and the I-D6
    limit they no longer disagree (CALLER_FRESHNESS_DISAGREES, which blocked every item, history-only ones included), and
    the items resting on a dongle signal stay BLOCKED by the quality layer's own rule. A missing limit stays unset."""
    limits, _notes = freshness_limits(decisions)
    bound = float(DQ_PROPOSED.liveness_max_age_s)
    out: dict[str, float] = {}
    for k, v in sorted(limits.items()):
        if v is None or spec_for(k) is None:
            continue
        out[k] = min(float(v), bound) if k in DONGLE_SIGNALS else float(v)
    return out


def cycle_inputs(job: EngineJob, snapshot, site_readings, history, pv_history) -> CycleInputs:
    policy = FreshnessPolicy(ADVISORY, overrides=advisory_overrides(job.decisions))
    live, assessments = advisory_live_inputs(snapshot, policy=policy)
    caller = tuple((a.signal, bool(a.fresh), a.age_s) for a in assessments)
    return CycleInputs(now=job.now, snapshot=snapshot, live=live, caller_assessments=caller, history=history,
                       pv_forecast_history=pv_history, base_cfg=job.base_cfg, site_facts=job.site_facts,
                       decisions=job.decisions, site_readings=tuple(site_readings), outcome_metrics=job.outcome_metrics,
                       paused=job.paused, previous=job.previous, versions=job.versions)


def compute(job: EngineJob, run_cycle: Callable | None = None) -> tuple[AdvisoryEnvelope, dict, object]:
    """(envelope, diagnostics, the History used or None) for one cycle (see the module docstring). Raises on an internal
    error; the coordinator turns that into SELF_TEST_FAILED."""
    if job.paused is True:
        raise ValueError("a paused cycle is never computed")
    t0, cpu0 = time.perf_counter(), time.thread_time()
    n_rows, truncated, history, newest_end, pv_history, parsed, reused = _history_inputs(job)
    src = sources.build_sources(job.now, job.states, job.entity_map, job.liveness_at, newest_end,
                                config_liveness_at=job.config_liveness_at)
    fn = run_cycle if run_cycle is not None else default_run_cycle()
    env = fn(cycle_inputs(job, src.snapshot, src.site_readings, history, pv_history))
    if not isinstance(env, AdvisoryEnvelope) or env.mode != MODE or env.applies_nothing is not True:
        raise TypeError("the engine did not return a SHADOW, applies-nothing AdvisoryEnvelope")
    notes, notes_withheld = sources.public_notes(src.notes)
    signals, signals_withheld = sources.public_signals(src.snapshot.signals())
    diag = {"history_rows": n_rows, "history_rows_truncated": truncated,
            "history_hours": 0 if history is None else len(history),
            "history_newest_end": None if newest_end is None else newest_end.isoformat(),
            "history_parsed": parsed, "history_reused": reused,
            "skipped_statistic_ids": len(job.plan.skipped), "source_notes": notes,
            "source_notes_withheld": notes_withheld,
            "site_readings": sorted(r.key for r in src.site_readings),
            "signals": signals, "signals_withheld": signals_withheld,
            "engine_s": round(max(time.perf_counter() - t0, 0.0), 6), "cpu_s": round(max(time.thread_time() - cpu0, 0.0), 6)}
    return env, diag, history
