"""The SHADOW coordinator: schedules cycles, runs the engine in the executor, publishes envelopes. Reads only.

What it touches in Home Assistant (the complete list; the runtime boundary suite allows nothing else):

  * hass.states.get(...)                     read the mapped entities and the pause helper (never a write)
  * recorder get_instance(hass).async_add_executor_job(statistics_during_period, ...)   read statistics, recorder executor
  * hass.async_add_executor_job(...)         the start-up gates, the engine and the state store, never on the event loop
  * hass.async_add_import_executor_job(...)  in __init__.py: this module (and through it most of the vendored engine) is
                                             imported in the import executor, never on the event loop
  * hass.loop.call_soon(...)                 the release of each executor job above (__init__.release_after_step): a job
                                             starts only once the event-loop step that submitted it has ended, and ends
                                             with the SUBMIT_COOLDOWN_S cool-down (__init__.released_call)
  * hass.async_create_background_task(..., CYCLE_TASK_NAME, eager_start=False)   one cycle at a time (cancelled by HA at
                                             shutdown and by unload); never started eagerly, so the callback that starts
                                             it only schedules it
  * async_track_time_interval(.., 60 s, name=TICK_JOB_NAME)   the one timer, attached by _attach_tick (its one call site)
                                             at the start and again when each cycle ends; detached while a cycle is in
                                             flight, so its phase follows the last cycle's end
  * async_track_state_change_event(hass, <the telemetry poll text>, ...)   the one state listener (A23), on the entity mapped
                                             for liveness.dongle_poll_changed_at only (none when it is not mapped),
                                             removed on unload; while a cycle is in flight it notes a poll, arming nothing
  * async_call_later(hass, .., HassJob(_on_poll_step, POLL_STEP_JOB_NAME))   the poll-driven refresh, at most one pending,
                                             never while a cycle is in flight (cancelled at its start with its due time
                                             kept, armed again at its end), cancelled on unload
  * hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, ...)   the start-up grace starts when HA has started
  * its own entities' async_write_ha_state() (sensor.py / binary_sensor.py)

The quiet cycle. While a cycle is in flight (from the moment _maybe_start creates its task until the cycle has ended) no
timer of the integration fires and none is created: the tick is detached at the start, a pending poll-driven step is
cancelled (its due time kept) and the listener notes each poll without arming a step. When the cycle ends (after its last
step, or in the done callback of a task cancelled before its first step) the second-run guard is released and the tick
body runs once as a catch-up (liveness, pause, self-test, STALE, re-render, _maybe_start: a slot that fell due can start,
the floor still bars a second refresh); unless that started the next cycle, the tick is attached again and the held step
is armed, unheld, at max(its due time, now), where the floor, A33 and A36 apply as before. This holds whatever the cycle's
outcome, also when recording its diagnostics raised. After an unload nothing is attached or armed again. Home Assistant's
shutdown cancels the cycle task but does not unload the entry: the catch-up then runs (it publishes; no cycle starts
while Core is stopping) and the tick and a held step come back, as the tick stayed attached through a shutdown before the
quiet cycle. The tick body still runs at least every TICK_S + PROPOSED_TICK_MARGIN_S, counted from its last run (the
publish horizon below). Inside a cycle its deadline is its
last run plus TICK_S, the moment the tick itself would have come, so the PROPOSED_TICK_MARGIN_S left before the horizon
the last run mapped its payloads to takes the deadline run's own latency (the job wait's timeout and the cycle task's
next step), as it takes a late tick's. A cycle's first step runs the tick body unless the tick body started the cycle (the
tick, or the catch-up at the previous cycle's end, ran at the cycle's start), before any job of the cycle, so its next
deadline is at least TICK_S after the cycle's start and falls inside the cycle only when the cycle runs longer than
TICK_S; when that deadline comes while the cycle waits for an executor job, the cycle task runs the tick body itself at
that moment, as one of its own steps (the job's wait times out there; no timer of the integration), and waits on. An
engine thread abandoned at the time budget keeps the second-run guard but not the quiet, by design: the tick is attached
again when that cycle ends (so the STALE and pause rules run every minute while the thread hangs), and a step held
meanwhile is armed when the thread ends.

The cycle's steps. The tick, the poll-driven step and the start-up callbacks do no cycle work: _maybe_start (the one place a
cycle starts) applies the cadence rules, sets the second-run guard and creates the cycle task, which first runs at a later
event-loop step. The cycle then runs in short steps, yielding to the event loop between them (_next_step):
  1. the tick body unless the tick body started this cycle (the quiet cycle, above), then the pause helper and the
     self-test (PAUSED or SELF_TEST_FAILED end the cycle there, as before);
  2. the snapshot: both poll texts and every mapped state, read in one step. The cycle starts a loop step or two before
     its snapshot, so a new poll text can arrive in between, after the start's settle check: the snapshot is then held
     once to that poll's settle end (the settle hold at the snapshot, A36 below). The cycle time (the engine's `now`) is
     read in the snapshot's step, so no state in the snapshot is newer than the cycle time; the cycle's start (the
     refresh floor, the exception retry, cycle_stats' started_at) stays the moment _maybe_start started it, and a
     poll-driven step is covered by a cycle that started after its poll or held its snapshot for it;
  3. the recorder statistics and the scorecard metrics (_history_inputs, at the cycle time; a SLOT cycle awaits both
     executor jobs);
  4. the engine job, built from that snapshot (EngineJob, envelope_summary of the last computed result) and submitted;
  5. after the engine: the pause helper and the self-test are read again, then one publish (every changed entity in the
     same step, so the entities never show a mix of two envelopes), then, for a SLOT cycle, the scorecard step.
Each executor job is held until the step that submitted it has ended (__init__.released_call), so the job and the rest of
that step never run at once, and ends with a cool-down, so its completion starts in a fresh CPU-quota period. The cycle
waits for each job with asyncio.wait_for (_job_wait), whose timeout is the time budget or the tick body's deadline,
whichever comes first: a timer asyncio makes, which fires only when that moment comes before the job ends. An unload or a
shutdown cancels the task at whichever step it waits; a task cancelled before its first step ends with the outcome
'cancelled' all the same (its done callback, _never_entered). What the cycle's end does then differs (the quiet cycle,
above): nothing after an unload, the catch-up, the tick and a held step after a shutdown.

Envelopes are built only by the contract constructors (starting_envelope, paused_envelope, stale_from,
self_test_failed_envelope, with_last_good, with_next_run_at) or returned by run_cycle; entities are fed only from
to_entity_payloads.

Rules:
  * schedule: every full hour and 21:30 Europe/London (SLOT cycles), the first cycle PROPOSED_STARTUP_GRACE_S after HA
    has started. A SLOT cycle reads the recorder statistics and the scorecard metrics and records the scorecard once per
    slot;
  * refresh before expiry (INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.4): between slots, a REFRESH cycle starts at a
    tick when the published computed result has less than REFRESH_MARGIN_S (125 s) of validity left, when it holds an
    item the engine BLOCKED INPUT_EXPIRING (withheld until the inputs are refreshed; since such an item no longer shortens
    the envelope's validity, that validity alone would leave it withheld until the envelope nears its end), or when it was
    published STALE (after a back-off of PROPOSED_STALE_BACKOFF_S when a result went STALE as soon as it was computed). A
    refresh reads fresh states and both poll-text liveness times, reuses the slot's cached recorder rows and metrics
    (re-read once PROPOSED_HISTORY_CATCHUP_S after the slot when they end before the slot's hour; a failed recorder read
    retried at most every PROPOSED_RECORDER_RETRY_S) and writes nothing to the state store. The cached rows are kept as
    the image the first cycle after the read parsed them into, and the history built from it is reused while its exact
    content is unchanged (A50, runtime/engine_link.HistoryReuse); every read drops it. At most one cycle start per
    tick (PROPOSED_REFRESH_FLOOR_S); a SLOT cycle wins when both are due. Refreshes are suspended while the engine's CPU
    time over the rolling hour exceeds PROPOSED_CPU_BUDGET_S_PER_H (self-test WARN CPU_BUDGET; slot cycles continue, the
    only effect is STALE). A refresh changes no limit, no validity and no rule: the engine decides every value;
  * poll-phase-aligned refresh (A23; section 13.4): the telemetry poll text moves about every PROPOSED_POLL_INTERVAL_S
    and the tick holds a phase against it that follows the last cycle's end (the quiet cycle above), so a refresh
    started at a tick long after a poll would withhold every item resting on a dongle input (INPUT_EXPIRING). The one
    state listener notes each new poll text (a replayed or unavailable text is no new poll) and schedules one
    poll-driven step PROPOSED_POLL_SETTLE_S later (the rest of that poll's entity writes land first); a pending step is
    never moved later (it keeps the earliest due time, so a text that changes faster than the settle delay cannot
    postpone it). That step starts a due slot cycle, or a REFRESH when the published result is STALE, has less than
    POLL_REFRESH_THRESHOLD_S of validity left (the margin plus one poll, so the margin is never entered between two
    polls), holds an item BLOCKED INPUT_EXPIRING, or holds an item BLOCKED for an input reason (INPUT_BLOCK_CODES:
    recovery after a transient input fault takes one poll, not up to the 835 s ceiling). A refresh inside the floor is
    deferred to the floor's end, never dropped; a step due while a cycle is in flight waits for its end (held, not
    armed: the quiet cycle), then runs (one poll noted meanwhile is served by it). While polls are arriving (one seen
    within PROPOSED_POLL_ACTIVE_S) the tick starts no slot cycle (the next poll-driven step does) and no refresh for
    validity or INPUT_EXPIRING unless the published envelope would go STALE at the next tick before the next expected
    poll-driven step, so a badly phased tick never replaces a good result with a worse one. When the poll text stops
    moving the tick resumes its present rules, so a frozen dongle fails closed (the dongle items BLOCK). A missed, late
    or frozen poll can leave the published result expiring before a tick's publish horizon while the hold still expected
    a poll-driven step: that tick then publishes STALE (every item null, never a wrong number) and starts the refresh
    that replaces it, so the episode costs at most one STALE cycle (A32, accepted as fail closed; no staleness rule
    changes; when that tick falls inside a poll's settle delay, its refresh is held to the delay's end, so that STALE
    lasts at most PROPOSED_POLL_SETTLE_S longer). Healthy polls (60 s plus or minus 3 s, any phase) give no STALE and no
    INPUT_EXPIRING. The pause helper, the self-test, the second-run guard, the CPU guard, the time-budget bar and the
    refresh switch apply to the poll-driven step and to a held cycle unchanged;
  * the settle hold (A36): no cycle starts inside the settle delay of the newest poll seen. At the one place a cycle
    starts (_maybe_start), a cycle of any trigger (the tick's refresh after STALE or its back-off, the exception retry,
    the tick's exception to its hold, a poll-driven step, one deferred to the floor's end, one armed again when a cycle
    in flight ended) whose start falls before the newest poll seen plus PROPOSED_POLL_SETTLE_S is held once to that
    moment, on the one pending step: when a step is already pending by then it serves the held cycle (a poll-driven step
    starts whatever the tick would), otherwise the step is armed there as a settle hold. The hold is one-shot (the held
    step starts without a second hold), at most PROPOSED_POLL_SETTLE_S, never re-armed by a later poll (a pending step
    is never moved later, A33), so a poll period below the settle delay cannot starve it; it never applies when no poll
    was seen within the settle delay. So a cycle that started after the poll was seen has read it already (the step is
    then covered). The same hold at the snapshot (_snapshot_hold): a cycle starts a loop step or two before its
    snapshot, so a poll text seen in between (after the start's check) holds the snapshot once to that poll's settle
    end, at most PROPOSED_POLL_SETTLE_S and never past the cycle's deadline (snapshot_holds); that cycle then covers the
    poll, so its own step starts no second cycle. A cycle is held at most once at its start and once at its snapshot.
    Residual (documented, not fixed): two polls within one settle delay (an abnormal sub-settle poll period), where the
    held cycle starts inside the second poll's settle delay (settle_residual_starts), or the second poll arrives while
    the snapshot is held and the snapshot is read inside its settle delay (snapshot_residual_reads; that poll is not
    covered, so its step refreshes at the floor's end when a refresh is due); a snapshot hold cut short by the cycle's
    deadline is read inside the settle delay too, so it counts there as well and covers nothing;
  * after RUNTIME_EXCEPTION one retry PROPOSED_EXCEPTION_RETRY_S after the failed start, then slot cycles only (until a
    result is published again); after CYCLE_TIME_BUDGET no refresh before the next slot, and never while the abandoned
    thread runs;
  * a second cycle never starts while one is in flight (an abandoned engine thread counts as in flight until it ends);
  * a cycle longer than PROPOSED_TIME_BUDGET_S is abandoned: SELF_TEST_FAILED with the reason CYCLE_TIME_BUDGET, the last
    values only in last_good; its late result is discarded;
  * any exception -> SELF_TEST_FAILED with a reason (last values only in last_good);
  * what is written stays on the entities until the next write, at the latest the next run of the tick body (the tick, the
    run at a cycle's first step, the catch-up at its end or the deadline run inside it, TICK_S after the last run: at
    least every TICK_S plus PROPOSED_TICK_MARGIN_S): the payloads are mapped as of that moment (the publish horizon,
    TICK_S plus PROPOSED_TICK_MARGIN_S ahead), so no number and no fresh=on outlives its valid_until between two runs.
    Only the entities whose payload changed are written (plus any whose last write raised); a refresh changes
    generated_at, so it writes all eleven, and Home Assistant's recorder keeps the timestamp-only attributes out of its
    rows (sensor.py / binary_sensor.py), so an unchanged refresh adds no new attributes row;
  * at least every TICK_S plus PROPOSED_TICK_MARGIN_S, even while an engine thread hangs (the tick body: by the tick, at a
    cycle's first step and its end, and inside a cycle at its deadline): a computed result whose valid_until (or whose
    age limit, PROPOSED_RESULT_MAX_AGE_S) falls before the publish horizon -> STALE; a fresh result that would expire
    before the next tick is published STALE at once (its values in last_good);
  * next_run_at on every computed and STALE envelope: the earliest moment the next cycle can start, min(the next schedule
    slot, valid_until - REFRESH_MARGIN_S (while polls are arriving valid_until - POLL_REFRESH_THRESHOLD_S, the moment from
    which a poll-driven step refreshes; the refresh floor alone while an item is BLOCKED INPUT_EXPIRING, or, while polls
    are arriving, BLOCKED for an input reason), bounded below by the publish time, the refresh floor and a STALE
    back-off); the next slot alone while refreshes are off, suspended or barred; PAUSED carries the next slot;
  * the pause helper input_boolean.ecco_intel_paused is read only: on -> PAUSED and nothing is computed; missing ->
    not paused, pause_control MISSING, self-test WARN. It is read again when a cycle's result arrives: a helper turned
    on while the cycle ran wins (PAUSED is published, the result is discarded and nothing is recorded);
  * an entity registered under another id than ENTITY_IDS (for example a '_2' suffix), or a contract entity Home
    Assistant never added (for example one disabled in the entity registry) -> SELF_TEST_FAILED;
  * one entity whose state write raises never stops the others from following the envelope: each entity is told in
    turn, and any such failure is a failed self-test (ENTITY_WRITE) -> SELF_TEST_FAILED.

Diagnostics only (never an entity attribute): last_cycle_timing {recorder_s, engine_s, store_s, total_s, cpu_s},
cycle_duration_s, cycle_stats (the last PROPOSED_CYCLE_STATS_N runs, more than 72 h of wall time at the highest cycle
rate (A50): kind, outcome, times, trigger TICK / POLL and the age of the last poll text at the cycle's start, which L3
logs) and the cadence state, with last_tick_at (the tick body's last run, whichever ran it: the tick, the run at a
cycle's first step, the catch-up at a cycle's end or the deadline run inside a cycle) and tick_poll_phase_s (that run's
phase against the last poll seen: the seconds from that poll to that run; None while polls are not arriving).
recorder_s, engine_s and store_s are the event loop's wall time from each submit to its result, so each includes its
job's release wait and its SUBMIT_COOLDOWN_S cool-down (and a tick body run at the deadline during that wait); total_s is
the whole cycle, every cool-down and any settle hold included; cpu_s is the engine thread's CPU time, with no cool-down.

Texts that reach an entity or the diagnostics carry codes, field paths and exception types only, never a site value or an
exception message; the detail goes to a debug log line.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time as time_mod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, REQUIRED_PYTHON_VER
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import CoreState, HassJob, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from intelligence.advisory_contract import (ENTITY_IDS, INTEGRATION_ENTITY_KEYS, AdvisoryEnvelope, ItemStatus, SystemStatus,
                                            Versions, envelope_summary, paused_envelope, self_test_failed_envelope,
                                            stale_from, starting_envelope, to_entity_payloads, with_last_good,
                                            with_next_run_at)
from intelligence.quality import RULE_INPUTS
from intelligence.site_decisions import CONFIG_LIVENESS_KEY, DecisionSet

from . import release_after_step, released_call
from .const import (CPU_WINDOW_S, CYCLE_TASK_NAME, DOMAIN, INTEGRATION_VERSION, MODE, POLL_REFRESH_THRESHOLD_S,
                    POLL_STEP_JOB_NAME, PROPOSED_CPU_BUDGET_S_PER_H, PROPOSED_CYCLE_STATS_N, PROPOSED_EXCEPTION_RETRY_S,
                    PROPOSED_HISTORY_CATCHUP_S, PROPOSED_POLL_ACTIVE_S, PROPOSED_POLL_INTERVAL_S, PROPOSED_POLL_SETTLE_S,
                    PROPOSED_RECORDER_RETRY_S, PROPOSED_REFRESH_FLOOR_S, PROPOSED_RESULT_MAX_AGE_S,
                    PROPOSED_STALE_BACKOFF_S, PROPOSED_STARTUP_GRACE_S, PROPOSED_TICK_MARGIN_S, PROPOSED_TIME_BUDGET_S,
                    REFRESH_MARGIN_S, SCHEDULE_DAILY_LOCAL, SITE_TZ, SUBMIT_COOLDOWN_S, TICK_JOB_NAME, TICK_S)
from .runtime import engine_link, gates, history_source, sources
from .runtime import store as rstore
from .runtime.selftest import FAIL, PASS, WARN, SelfTest

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
LONDON = ZoneInfo(SITE_TZ)
PAUSE_ENTITY = ENTITY_IDS["paused"]
SLOT, REFRESH = "SLOT", "REFRESH"                       # the two cycle kinds
# The engine's per-item code for an OK item valid for less than REFRESH_MARGIN_S at compute time (FOUNDATION CONTRACT
# section 13.4): the item is withheld until the inputs are refreshed, so its presence asks for a refresh at the next tick.
INPUT_EXPIRING = "INPUT_EXPIRING"
TICK, POLL = "TICK", "POLL"                             # what started a cycle: the one timer or a poll-driven step (A23)
# A23: the blocker codes that mean "BLOCKED for an input reason", so a new poll may lift them and a poll-driven step
# refreshes (recovery within one poll). Taken from the engine's own registry: every quality rule whose inputs
# (quality.RULE_INPUTS) name a live input, a signal or site reading the runtime maps (INPUT_NOT_FRESH's own input list,
# less the recorder history, which a refresh does not re-read); plus the codes of the readings the planning layer judges
# itself: the TOU table and charge window (TOU_*, CHARGE_WINDOW_*), the tariff tables (TARIFF_*), the raise-only reserve
# helper, INPUT_EXPIRING and a caller / quality freshness disagreement. A code outside this set (an OPEN decision, the
# history) leaves the item to the present rules; that only delays its recovery, it never shows a number.
HISTORY_INPUT_KEY = "history.hourly"
_LIVE_INPUT_KEYS = frozenset(RULE_INPUTS.get("INPUT_NOT_FRESH", ())) - {HISTORY_INPUT_KEY}
INPUT_BLOCK_CODES = (frozenset(code for code, keys in RULE_INPUTS.items() if _LIVE_INPUT_KEYS.intersection(keys))
                     | {INPUT_EXPIRING, "INPUT_NOT_FRESH", "PREF_RESERVE_RAISE_UNKNOWN", "CALLER_FRESHNESS_DISAGREES"})
INPUT_BLOCK_PREFIXES = ("TOU_", "CHARGE_WINDOW_", "TARIFF_")
CYCLE_STATS_FIELDS = ("started_at", "kind", "outcome", "total_s", "recorder_s", "engine_s", "store_s", "cpu_s", "trigger",
                      "poll_age_s")


def state_view(st: Any) -> Mapping | None:
    """A plain copy of an HA State (what the HA-free runtime consumes)."""
    if st is None:
        return None
    return {"state": st.state, "attributes": dict(st.attributes), "last_changed": st.last_changed,
            "last_updated": st.last_updated, "last_reported": getattr(st, "last_reported", None)}


def due_slot(now: datetime) -> datetime:
    """The latest schedule slot at or before `now`: a full hour (UK offsets are whole hours, so the UTC hour is the local
    hour) or 21:30 Europe/London."""
    hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    local = now.astimezone(LONDON)
    daily = datetime.combine(local.date(), time(*SCHEDULE_DAILY_LOCAL), tzinfo=LONDON).astimezone(UTC)
    if daily > now:
        daily = datetime.combine(local.date() - timedelta(days=1), time(*SCHEDULE_DAILY_LOCAL), tzinfo=LONDON).astimezone(UTC)
    return max(hour, daily)


def publish_horizon(now: datetime) -> datetime:
    """The latest moment what is written at `now` can still be on the entities: the next tick (or, inside a cycle, the
    deadline run that stands in for it, TICK_S after the tick body's last run), plus a margin for a late one. Payloads
    are mapped as of this moment (to_entity_payloads applies the null rule at that time)."""
    return now + timedelta(seconds=TICK_S + PROPOSED_TICK_MARGIN_S)


def expires_before_next_tick(env: AdvisoryEnvelope | None, now: datetime) -> bool:
    """A computed (non-null) envelope whose validity, or whose PROPOSED maximum age, ends before the publish horizon."""
    if env is None or env.status in SystemStatus.NULL:
        return False
    horizon = publish_horizon(now)
    return ((env.valid_until is not None and horizon > env.valid_until)
            or (horizon - env.generated_at).total_seconds() > PROPOSED_RESULT_MAX_AGE_S)


def withheld_until_refresh(env: AdvisoryEnvelope | None) -> bool:
    """A computed (non-null) envelope holding an item or forecast the engine BLOCKED INPUT_EXPIRING. Such an item no longer
    shortens the envelope's validity (section 13.4), so the validity alone would not bring the next refresh before the
    envelope nears its end (up to the 900 s advice validity, or the next slot); the item would stay withheld that long
    although its inputs may be fresh again at the next tick."""
    if env is None or env.status in SystemStatus.NULL:
        return False
    return any(INPUT_EXPIRING in v.reason_codes or any(code == INPUT_EXPIRING for code, _t in v.blockers)
               for v in tuple(env.items) + tuple(env.forecasts))


def input_block_code(code: object) -> bool:
    """A blocker code that means BLOCKED for an input reason (INPUT_BLOCK_CODES or one of INPUT_BLOCK_PREFIXES)."""
    return isinstance(code, str) and (code in INPUT_BLOCK_CODES or code.startswith(INPUT_BLOCK_PREFIXES))


def blocked_for_input(env: AdvisoryEnvelope | None) -> bool:
    """A computed (non-null) envelope holding an item or forecast BLOCKED for an input reason (one of its blockers is an
    input code): a new poll may lift it, so a poll-driven step refreshes (A23). Only blockers count (a reason code may be
    an INFO or WARN finding of an item blocked for another reason)."""
    if env is None or env.status in SystemStatus.NULL:
        return False
    return any(v.status == ItemStatus.BLOCKED and any(input_block_code(code) for code, _t in v.blockers)
               for v in tuple(env.items) + tuple(env.forecasts))


def next_slot(now: datetime) -> datetime:
    hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    local = now.astimezone(LONDON)
    daily = datetime.combine(local.date(), time(*SCHEDULE_DAILY_LOCAL), tzinfo=LONDON).astimezone(UTC)
    if daily <= now:
        daily = datetime.combine(local.date() + timedelta(days=1), time(*SCHEDULE_DAILY_LOCAL), tzinfo=LONDON).astimezone(UTC)
    return min(hour, daily)


async def _next_step() -> None:
    """Yield to the event loop between two steps of a cycle (the cycle's next step runs at a later loop iteration)."""
    await asyncio.sleep(0)


async def _settle_wait(seconds: float) -> None:
    """The settle hold at the snapshot (A36): the cycle task waits `seconds` (at most PROPOSED_POLL_SETTLE_S) on the
    event loop's clock, so the rest of a poll's entity writes land before its snapshot."""
    await asyncio.sleep(seconds)


async def _job_wait(fut: asyncio.Future, timeout: float) -> Any:
    """The cycle task waits for an executor job's result at most `timeout` seconds on the event loop's clock (the time
    budget left or the tick body's deadline, whichever comes first): asyncio.TimeoutError then, and the job, shielded,
    runs on."""
    return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)


def _finite_s(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 else None


def _p(values: list[float], q: float) -> float | None:
    """The nearest-rank q-quantile of `values` (None for none)."""
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))], 6)


@dataclass(frozen=True)
class Startup:
    """The start-up gates' results (computed in the executor)."""
    selftest: SelfTest
    site: gates.SiteLoad
    store: rstore.RuntimeStateStore
    versions: Versions


def _startup_io(config_dir: str, latitude: object, longitude: object) -> Startup:
    """Every start-up gate that reads a file (executor only)."""
    st = SelfTest()
    st.add(gates.tz_gate(SITE_TZ))
    raw, problem = rstore.read_site_file(config_dir)
    site = gates.load_site(raw, problem, latitude=latitude, longitude=longitude)
    for c in site.checks:
        st.add(c)
    man, want, mprob = gates.manifest_paths(rstore.read_package_manifest())
    st.add(gates.vendor_gate(man, want, rstore.hash_package_files(want.keys()), mprob))
    store = rstore.RuntimeStateStore(config_dir, SITE_TZ)
    ok, text = store.try_open()
    st.record("STORE_WRITABLE", PASS if ok else FAIL, text)
    try:
        engine_version = engine_link.engine_version()
        st.record("ENGINE_IMPORT", PASS, engine_version)
    except Exception as exc:  # noqa: BLE001 - an engine that cannot be imported is a failed self-test
        engine_version = "unknown"
        st.record("ENGINE_IMPORT", FAIL, f"the vendored engine cannot be imported: {type(exc).__name__}")
    versions = Versions(integration_version=INTEGRATION_VERSION, engine_version=engine_version,
                        git_sha=(man or {}).get("git_sha") if isinstance(man, dict) else None,
                        config_hash=site.config_hash)
    return Startup(st, site, store, versions)


async def async_create_coordinator(hass: HomeAssistant, entry: Any) -> "EccoIntelCoordinator":
    """Run the start-up gates. The mode gate REFUSES SETUP (ConfigEntryError); every other failed gate gives a coordinator
    that publishes SELF_TEST_FAILED and computes nothing."""
    data = entry.data if isinstance(entry.data, Mapping) else {}
    mode = gates.mode_gate(MODE, data.get("mode"))
    if mode.level == FAIL:
        raise ConfigEntryError(mode.text)
    startup = await hass.async_add_executor_job(released_call, release_after_step(hass), _startup_io,
                                                hass.config.config_dir, hass.config.latitude, hass.config.longitude)
    for code, detail in startup.site.details:          # the offending site-file value, for the owner's debug log only
        _LOGGER.debug("ECCO Intelligence start-up check %s: %s", code, detail)
    startup.selftest.add(mode)
    startup.selftest.add(gates.versions_check(HA_VERSION, REQUIRED_PYTHON_VER))
    return EccoIntelCoordinator(hass, entry, startup)


class EccoIntelCoordinator:
    def __init__(self, hass: HomeAssistant, entry: Any, startup: Startup) -> None:
        self.hass = hass
        self.entry = entry
        self.selftest = startup.selftest
        self.site = startup.site
        self.store = startup.store
        self.versions = startup.versions
        self.decisions: DecisionSet = startup.site.decisions or DecisionSet.from_mapping({}, source="site_local")
        self.time_budget_s = PROPOSED_TIME_BUDGET_S
        self.grace_s = PROPOSED_STARTUP_GRACE_S
        self.refresh_enabled = True                       # refresh before expiry (tests switch it off to pin slot-only)
        self.cpu_budget_s = PROPOSED_CPU_BUDGET_S_PER_H
        self.envelope: AdvisoryEnvelope | None = None
        self.payloads: dict[str, tuple] = {}
        self.last_diag: dict = {}
        self.last_store: dict = {}
        self.last_timing: dict = {}
        self.cycle_stats: deque = deque(maxlen=PROPOSED_CYCLE_STATS_N)
        self.counters = {"runs_started": 0, "runs_published": 0, "skipped_in_flight": 0, "budget_exceeded": 0,
                         "late_results_discarded": 0, "exceptions": 0, "paused_ticks": 0, "stale_applied": 0,
                         "results_discarded_paused": 0, "results_discarded_failed": 0, "entity_write_failures": 0,
                         "slot_runs_started": 0, "refresh_runs_started": 0, "refresh_skipped_in_flight": 0,
                         "refresh_suppressed_cpu": 0, "exception_retries": 0, "stale_backoffs": 0,
                         "history_catchup_reads": 0, "recorder_retry_reads": 0, "entity_writes": 0,
                         "refresh_input_expiring": 0, "polls_seen": 0, "poll_runs_started": 0, "poll_refresh_input": 0,
                         "poll_steps_deferred_floor": 0, "poll_steps_covered": 0, "poll_steps_waited_in_flight": 0,
                         "poll_steps_idle": 0, "poll_steps_kept_earlier": 0, "tick_refresh_held": 0, "tick_slot_held": 0,
                         "settle_holds": 0, "settle_held_starts": 0, "settle_residual_starts": 0,
                         "snapshot_holds": 0, "snapshot_residual_reads": 0,
                         "history_parses": 0, "history_reuses": 0, "ticks_deferred": 0, "catchup_ticks": 0,
                         "tick_start_runs": 0, "tick_deadline_runs": 0, "poll_steps_held_busy": 0}
        self._run_cycle: Callable | None = None           # None = the vendored shadow_cycle.run_cycle (tests inject)
        self._listeners: list[tuple[str | None, Callable[[], None]]] = []
        self._in_write_failure = False
        self._dirty: set[str] = set()                     # entities whose last state write raised: written again next time
        self._unsubs: list[Callable[[], None]] = []
        self._tick_unsub: Callable[[], None] | None = None   # the attached tick (None: detached, a cycle is in flight)
        self._tick_ran_at: datetime | None = None         # the tick body's last run (or the start's publish)
        self._cycle_live = False                          # a cycle is in flight: from its task's creation to its end
        self._unsub_started: Callable[[], None] | None = None
        self._started_at: datetime | None = None
        self._first_run_done = False
        self._run_now = False
        self._last_slot: datetime | None = None
        self._busy = False
        self._orphans: set = set()
        self._task: asyncio.Task | None = None
        self._pending_start: object | None = None        # the cycle task started but not yet entered (_never_entered)
        self._last_computed: AdvisoryEnvelope | None = None
        self._liveness: sources.LivenessMemory | None = None
        self._liveness_at: datetime | None = None
        self._config_liveness: sources.LivenessMemory | None = None      # the second memory: the configuration poll
        self._config_liveness_at: datetime | None = None
        # cadence state
        self._last_start: datetime | None = None
        self._last_kind: str | None = None
        self._retry_at: datetime | None = None
        self._retry_used = False
        self._budget_slot: datetime | None = None
        self._stale_backoff_s: float | None = None
        self._stale_until: datetime | None = None
        self._cpu_log: deque = deque()                    # (finished at, engine CPU seconds) of the rolling hour
        self._cpu_suspended = False
        self._hist: dict | None = None                    # the recorder rows of the current slot (refreshes reuse them)
        self._history_reuse = engine_link.HistoryReuse()  # the parsed history, reused while the statistics are unchanged
        self._metrics: Any = None
        self._metrics_ok = False
        self._entity_mismatch: dict[str, str] = {}
        self._entities_seen: set[str] = set()
        self._closed = False
        # the poll-phase-aligned refresh (A23)
        self._poll_entity: str | None = None              # the mapped telemetry poll text (None: not mapped, no listener)
        self._poll_text: str | None = None                # the last poll text the listener saw
        self._poll_seen_at: datetime | None = None        # when the listener last saw a new poll text
        self._poll_seq = 0                                # the new poll texts the listener saw (exact, whatever the clock)
        self._read_poll_seq: int | None = None            # the poll a snapshot was held for (A36): it covers that poll
        self._poll_due: datetime | None = None            # the pending poll-driven step (None: none pending)
        self._poll_cancel: Callable[[], None] | None = None
        self._poll_job = HassJob(self._on_poll_step, POLL_STEP_JOB_NAME)   # the one-shot's job, named for Home Assistant
        self._poll_wait: bool = False                     # the pending step waits for the cycle in flight to end
        self._poll_held: bool = False                     # the pending step is a settle hold (A36): it starts unheld
        self._last_trigger: str | None = None
        self._last_tick_at: datetime | None = None        # the tick body's last run, whichever ran it (diagnostics)
        self._tick_poll_phase_s: float | None = None      # seconds from the last poll seen to that run (diagnostics)

    def __repr__(self) -> str:
        """Short, and naming the integration: Home Assistant's job texts (a slow-callback line among them) end with it."""
        return f"<{type(self).__name__} {DOMAIN}>"

    # --- life cycle --------------------------------------------------------------------------------------------------
    @callback
    def async_start(self) -> None:
        now = dt_util.utcnow()
        paused = self._pause_state()
        if paused is True:                               # PAUSED > SELF_TEST_FAILED (the contract's precedence)
            self._publish_paused(now)
        elif self.selftest.failed:
            self._publish_failed(now, dict(self.selftest.failures()))
        else:
            self._publish(starting_envelope(now, self.versions, decisions=self.decisions, paused=paused,
                                            next_run_at=None), now)
        self._tick_ran_at = now                          # that publish maps as of the horizon, as a tick body's does
        self._attach_tick()
        spec = self.site.entity_map.readings.get(sources.LIVENESS_KEY)
        if spec is not None and isinstance(spec.get("entity"), str):
            # the one state listener (A23): the telemetry poll text; its current text is no new poll
            self._poll_entity = spec["entity"]
            self._poll_text = sources.poll_text(state_view(self.hass.states.get(self._poll_entity)))
            self._unsubs.append(async_track_state_change_event(self.hass, self._poll_entity, self._on_poll))
        if self.hass.state == CoreState.running:
            self._started_at = now
        else:
            self._unsub_started = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_started)

    @callback
    def _on_started(self, _event: Any) -> None:
        self._unsub_started = None
        if not self._closed:
            self._started_at = dt_util.utcnow()

    async def async_stop(self) -> None:
        """Unload: no further cycle, publish or write. An engine thread still running is left to finish; its result is
        discarded."""
        if self._closed:
            return
        self._closed = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._tick_unsub is not None:
            self._tick_unsub()
            self._tick_unsub = None
        self._cancel_poll_step()
        if self._unsub_started is not None:
            self._unsub_started()
            self._unsub_started = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._listeners.clear()
        self._hist = None
        self._history_reuse.clear()
        self.store.close()

    @property
    def closed(self) -> bool:
        return self._closed

    # --- entities ----------------------------------------------------------------------------------------------------
    @callback
    def async_add_listener(self, update: Callable[[], None], key: str | None = None) -> Callable[[], None]:
        item = (key, update)
        self._listeners.append(item)

        def remove() -> None:
            if item in self._listeners:
                self._listeners.remove(item)
        return remove

    def payload(self, entity_id: str) -> tuple | None:
        return self.payloads.get(entity_id)

    def _entity_ids_check(self, final: bool) -> bool:
        """Record ENTITY_IDS. FAIL for an entity under another id than the contract's and, once the platforms are set up
        (`final`), for a contract entity Home Assistant never added; PASS when all eleven match. True when it FAILs. The
        text names contract keys only (the id Home Assistant gave goes to the debug log)."""
        missing = sorted(set(INTEGRATION_ENTITY_KEYS) - self._entities_seen) if final else []
        parts = []
        if self._entity_mismatch:
            parts.append("registered under another id than the contract's: " + ", ".join(sorted(self._entity_mismatch)))
        if missing:
            parts.append("never added by Home Assistant (disabled in the entity registry?): " + ", ".join(missing))
        if parts:
            self.selftest.record("ENTITY_IDS", FAIL, "; ".join(parts))
            return True
        if self._entities_seen >= set(INTEGRATION_ENTITY_KEYS):
            self.selftest.record("ENTITY_IDS", PASS, f"all {len(INTEGRATION_ENTITY_KEYS)} entity ids match the contract")
        return False

    @callback
    def entity_added(self, key: str, entity_id: str) -> None:
        """An entity reports the id Home Assistant gave it; any other id than the contract's is a failed self-test."""
        self._entities_seen.add(key)
        if entity_id != ENTITY_IDS.get(key):
            self._entity_mismatch[key] = str(entity_id)
            _LOGGER.debug("ECCO Intelligence entity %s was registered as %s", key, entity_id)
        if self._entity_ids_check(final=False) and key in self._entity_mismatch:
            self._publish_failed(dt_util.utcnow(), dict(self.selftest.failures()))

    @callback
    def verify_entities(self) -> None:
        """After the platforms are set up: every contract entity must have been added (a missing one, for example the
        status entity that carries mode and applies_nothing, is a failed self-test, so nothing is computed)."""
        self._entity_ids_check(final=True)

    # --- reading Home Assistant (read only) --------------------------------------------------------------------------
    def _pause_state(self) -> bool | None:
        """True / False from input_boolean.ecco_intel_paused; None when it is missing, unavailable or unknown."""
        st = self.hass.states.get(PAUSE_ENTITY)
        value = sources.bool_value(state_view(st))
        self.selftest.record("PAUSE_CONTROL", PASS if value is not None else WARN,
                             "the pause helper is readable" if value is not None
                             else "the pause helper is missing: not paused, pause_control MISSING")
        return value

    def _track(self, key: str, memory: sources.LivenessMemory | None, now: datetime
               ) -> tuple[datetime | None, sources.LivenessMemory | None]:
        spec = self.site.entity_map.readings.get(key)
        if spec is None:
            return None, memory
        at, memory, _note = sources.track_liveness(state_view(self.hass.states.get(spec["entity"])), memory, now)
        return at, memory

    def _sample_liveness(self, now: datetime) -> None:
        """Both poll texts, each with its own memory: the telemetry poll (LIVENESS_KEY) and the configuration poll
        (CONFIG_LIVENESS_KEY, passed to build_sources as config_liveness_at)."""
        self._liveness_at, self._liveness = self._track(sources.LIVENESS_KEY, self._liveness, now)
        self._config_liveness_at, self._config_liveness = self._track(CONFIG_LIVENESS_KEY, self._config_liveness, now)

    def _collect_states(self) -> dict[str, Mapping]:
        out = {}
        for eid in self.site.entity_map.entity_ids():
            v = state_view(self.hass.states.get(eid))
            if v is not None:
                out[eid] = v
        return out

    # --- publishing --------------------------------------------------------------------------------------------------
    def _publish(self, env: AdvisoryEnvelope, now: datetime) -> None:
        """Map the envelope with THE mapping (to_entity_payloads as of the publish horizon: what is written now stays on the
        entities until the next tick at the latest) and tell each entity whose payload changed (or whose last write
        raised); an entity whose payload is unchanged is not written again."""
        if self._closed:
            return
        payloads = to_entity_payloads(env, publish_horizon(now))
        changed = {eid for eid in set(payloads) | set(self.payloads) if payloads.get(eid) != self.payloads.get(eid)}
        changed |= self._dirty
        self.payloads = payloads
        self.envelope = env
        if not changed:
            return
        failed: list[tuple[str, str]] = []
        for key, update in list(self._listeners):
            eid = ENTITY_IDS.get(key) if key is not None else None
            if eid is not None and eid not in changed:
                continue
            try:
                update()
                self.counters["entity_writes"] += 1
                self._dirty.discard(eid)
            except Exception as exc:  # noqa: BLE001 - one entity's refused write never stops the others from following
                failed.append((key or "unknown", type(exc).__name__))
                if eid is not None:
                    self._dirty.add(eid)
        if failed:
            self._entity_write_failed(failed, now)

    def _entity_write_failed(self, failed: list[tuple[str, str]], now: datetime) -> None:
        """A state write of one of its own entities raised: a failed self-test (ENTITY_WRITE), so SELF_TEST_FAILED is
        published to every entity (or PAUSED while the helper is on) and nothing more is computed. Only the contract keys
        and the exception types are named. A failure while that is being published is recorded but not re-published, and
        so is the same failure again when a refused entity is written again at a later tick (no republish every minute)."""
        self.counters["entity_write_failures"] += len(failed)
        text = "a state write of its own entities raised: " + ", ".join(f"{k} ({t})" for k, t in sorted(set(failed)))
        prev = self.selftest.get("ENTITY_WRITE")
        self.selftest.record("ENTITY_WRITE", FAIL, text)
        env = self.envelope
        repeat = (prev is not None and prev.level == FAIL and prev.text == text and env is not None
                  and env.status in (SystemStatus.SELF_TEST_FAILED, SystemStatus.PAUSED))
        if self._in_write_failure or repeat:
            _LOGGER.debug("ECCO Intelligence: %d entity state write(s) failed again", len(failed))
            return
        _LOGGER.warning("ECCO Intelligence: %d entity state write(s) failed", len(failed))
        self._in_write_failure = True
        try:
            self._publish_failed(now, dict(self.selftest.failures()))
        finally:
            self._in_write_failure = False

    def _last_good_source(self) -> AdvisoryEnvelope | None:
        cur = self.envelope
        if cur is not None and cur.status in SystemStatus.NULL and cur.last_good is not None:
            return cur
        return self._last_computed

    def _publish_failed(self, now: datetime, failures: Mapping[str, str]) -> None:
        """SELF_TEST_FAILED with the reasons and last_good; while the pause helper is on, PAUSED wins (precedence) and
        the failure shows once the helper is turned off."""
        paused = self._pause_state()
        if paused is True:
            self._publish_paused(now)
            return
        env = self_test_failed_envelope(now, self.versions, failures, decisions=self.decisions, paused=paused)
        self._publish(with_last_good(env, self._last_good_source()), now)

    def _publish_paused(self, now: datetime) -> None:
        env = paused_envelope(now, self.versions, decisions=self.decisions, next_run_at=next_slot(now))
        self._publish(with_last_good(env, self._last_good_source()), now)

    def _publish_stale(self, env: AdvisoryEnvelope, now: datetime, paused: bool | None) -> None:
        """STALE from a computed envelope (its OK values move to last_good), with the next run time."""
        self.counters["stale_applied"] += 1
        stale = stale_from(env, now, paused=paused)
        self._publish(with_next_run_at(stale, self._next_run_at(stale, now)), now)

    # --- cadence -----------------------------------------------------------------------------------------------------
    def _cpu_used(self, now: datetime) -> float:
        """The engine CPU seconds of the cycles that finished within the rolling CPU_WINDOW_S before `now`."""
        cutoff = now - timedelta(seconds=CPU_WINDOW_S)
        while self._cpu_log and self._cpu_log[0][0] <= cutoff:
            self._cpu_log.popleft()
        return sum(c for _t, c in self._cpu_log)

    def _note_cpu(self, cpu: object) -> None:
        v = _finite_s(cpu)
        if v is not None:
            self._cpu_log.append((dt_util.utcnow(), v))

    def _refresh_barred(self) -> bool:
        """No refresh at all: switched off, or a time-budget overrun in the current slot (never retried before the next)."""
        return (not self.refresh_enabled) or (self._budget_slot is not None and self._budget_slot == self._last_slot)

    def _refresh_reason(self, now: datetime, trigger: str = TICK) -> str | None:
        """Why a REFRESH cycle should start now (EXCEPTION_RETRY, STALE, EXPIRING, INPUT_EXPIRING and, for a poll-driven
        step, INPUT_BLOCKED), or None. The floor (one start per tick), the time-budget bar, the A23 tick hold and the CPU
        guard are applied here; the second-run guard by the caller."""
        if self._refresh_barred():
            return None
        if self._last_start is not None and (now - self._last_start).total_seconds() < PROPOSED_REFRESH_FLOOR_S:
            return None
        env = self.envelope
        poll = trigger == POLL
        if self._retry_at is not None:
            if now < self._retry_at:
                return None
            reason = "EXCEPTION_RETRY"
        elif env is not None and env.status == SystemStatus.STALE:
            if self._stale_until is not None and now < self._stale_until:
                return None
            reason = "STALE"
        elif (env is not None and env.status not in SystemStatus.NULL and env.valid_until is not None
              and (env.valid_until - now).total_seconds() < (POLL_REFRESH_THRESHOLD_S if poll else REFRESH_MARGIN_S)):
            reason = "EXPIRING"
        elif withheld_until_refresh(env):
            reason = INPUT_EXPIRING
        elif poll and blocked_for_input(env):
            reason = "INPUT_BLOCKED"
        else:
            return None
        if (not poll and reason in ("EXPIRING", INPUT_EXPIRING) and self._polls_arriving(now)
                and not self._stale_before_poll(env, now)):
            self.counters["tick_refresh_held"] += 1      # A23: the next poll-driven step refreshes, well phased
            return None
        if self._cpu_used(now) > self.cpu_budget_s:      # the CPU guard: refreshes suspended, slot cycles continue
            self.counters["refresh_suppressed_cpu"] += 1
            if not self._cpu_suspended:
                self._cpu_suspended = True
                _LOGGER.warning("ECCO Intelligence: refreshes suspended (engine CPU over the PROPOSED hourly budget)")
                self.selftest.record("CPU_BUDGET", WARN, "the engine's CPU time in the last hour is over "
                                     "PROPOSED_CPU_BUDGET_S_PER_H: refreshes are suspended, slot cycles continue")
            return None
        if self._cpu_suspended:
            self._cpu_suspended = False
            self.selftest.record("CPU_BUDGET", PASS, "the engine's CPU time in the last hour is within the budget again")
        return reason

    def _next_run_at(self, env: AdvisoryEnvelope, now: datetime) -> datetime:
        """The earliest moment the next cycle can start (see the module rules); never before `now` nor before the
        envelope's generated_at (with_next_run_at refuses that, for example after the wall clock stepped back)."""
        slot = next_slot(max(now, env.generated_at))
        if self._refresh_barred() or self._cpu_used(now) > self.cpu_budget_s:
            return slot
        floor = max(now, env.generated_at)
        if self._last_start is not None:
            floor = max(floor, self._last_start + timedelta(seconds=PROPOSED_REFRESH_FLOOR_S))
        arriving = self._polls_arriving(now)
        if env.status == SystemStatus.STALE:
            earliest = floor if self._stale_until is None else max(floor, self._stale_until)
        elif withheld_until_refresh(env) or (arriving and blocked_for_input(env)):
            earliest = floor
        elif env.status not in SystemStatus.NULL and env.valid_until is not None:
            ahead = POLL_REFRESH_THRESHOLD_S if arriving else REFRESH_MARGIN_S
            earliest = max(floor, env.valid_until - timedelta(seconds=ahead))
        else:
            return slot
        return min(slot, earliest)

    # --- the poll-phase-aligned refresh (A23) ----------------------------------------------------------------------
    def _polls_arriving(self, now: datetime) -> bool:
        """A new telemetry poll text was seen within PROPOSED_POLL_ACTIVE_S: a poll-driven step comes when one is needed."""
        return (self._poll_seen_at is not None and not self._closed
                and (now - self._poll_seen_at).total_seconds() <= PROPOSED_POLL_ACTIVE_S)

    def _next_poll_step(self) -> datetime | None:
        """When the next poll-driven step is expected: the pending one, else the latest moment one still counts as
        arriving (the last poll seen plus PROPOSED_POLL_ACTIVE_S, plus the settle delay)."""
        if self._poll_due is not None:
            return self._poll_due
        if self._poll_seen_at is None:
            return None
        return self._poll_seen_at + timedelta(seconds=PROPOSED_POLL_ACTIVE_S + PROPOSED_POLL_SETTLE_S)

    def _stale_before_poll(self, env: AdvisoryEnvelope | None, now: datetime) -> bool:
        """The published envelope would go STALE at the next tick (its validity ends before that tick's publish horizon)
        and the next poll-driven step is not expected before that tick: then the tick refreshes after all."""
        nxt = self._next_poll_step()
        tick = now + timedelta(seconds=TICK_S)
        return (nxt is None or nxt > tick) and expires_before_next_tick(env, tick)

    def _slot_due(self, now: datetime) -> bool:
        return ((not self._first_run_done) or self._run_now or self._last_slot is None
                or due_slot(now) > self._last_slot)

    def _cancel_poll_step(self) -> None:
        if self._poll_cancel is not None:
            self._poll_cancel()
            self._poll_cancel = None
        self._poll_due = None
        self._poll_wait = False
        self._poll_held = False

    def _arm_poll_step(self, at: datetime, held: bool = False) -> None:
        """(Re)schedule the one pending poll-driven step at `at` (never two pending). `held`: the step is a settle hold
        (A36), so the cycle it starts is not held again."""
        if self._poll_cancel is not None:
            self._poll_cancel()
        delay = max((at - dt_util.utcnow()).total_seconds(), 0.0)
        self._poll_due = at
        self._poll_wait = False
        self._poll_held = held
        self._poll_cancel = async_call_later(self.hass, delay, self._poll_job)

    def _settle_end(self, now: datetime) -> datetime | None:
        """The end of the newest poll's settle delay when `now` falls inside it (A36), else None (also when no poll was
        seen)."""
        if self._poll_seen_at is None:
            return None
        end = self._poll_seen_at + timedelta(seconds=PROPOSED_POLL_SETTLE_S)
        return end if now < end else None

    def _settle_hold(self, end: datetime) -> None:
        """A36: a cycle whose start falls inside the newest poll's settle delay is held once to `end`, on the one pending
        step. A step already pending by then serves it (it is held itself if it still falls inside a settle delay, and a
        poll-driven step starts whatever the tick would); otherwise the step is armed at `end` as a settle hold. It only
        ever moves a pending step earlier (A33)."""
        self.counters["settle_holds"] += 1
        if self._poll_due is not None and self._poll_due <= end:
            return
        self._arm_poll_step(end, held=True)

    def _hold_timers(self) -> None:
        """A cycle starts (the quiet cycle): the tick is detached and a pending poll-driven step is cancelled, its due time
        kept for _rearm_poll_step (a settle hold's one-shot mark is dropped there). Nothing of the integration fires or is
        armed until the cycle has ended."""
        self._detach_tick()
        if self._poll_cancel is not None:
            self._poll_cancel()
            self._poll_cancel = None
            self.counters["poll_steps_held_busy"] += 1

    def _rearm_poll_step(self) -> None:
        """The second-run guard is released (the cycle has ended and no abandoned engine thread runs): a poll-driven step
        held meanwhile is armed again at max(its due time, now), through _arm_poll_step, so the floor, A33 (never later: a
        poll that arrived meanwhile kept the earlier due time) and A36 (a step that comes inside a newer poll's settle
        delay is held once at its start, _maybe_start) apply as before. It is armed unheld, as a step that waited for a
        cycle in flight was resumed before the quiet cycle: a settle hold's one-shot mark does not outlive the cycle, so a
        poll seen in the cycle's last settle delay holds the step once more. It is armed once here, so a fast poll text
        cannot postpone it."""
        if self._busy or self._closed or self._poll_due is None or self._poll_cancel is not None:
            return
        self._arm_poll_step(max(self._poll_due, dt_util.utcnow()))

    @callback
    def _on_poll(self, event: Any) -> None:
        """The telemetry poll text changed: a new poll text (not a replay of the last one, not unavailable or 'Waiting')
        schedules the poll-driven step PROPOSED_POLL_SETTLE_S later. A pending step is never moved later (A33, RT-2): it
        keeps the earliest due time, so a text that changes faster than the settle delay cannot postpone it forever; a
        settle hold (A36) is never re-armed by this poll. When such a kept step comes to start a cycle inside this poll's
        settle delay, the settle hold applies at that start (_maybe_start), once. A step only moves earlier (a step
        deferred to the floor's end), where it meets the floor again. While the second-run guard is set (a cycle in
        flight, or an abandoned engine thread) the poll is noted all the same but no timer is armed: the step keeps its
        due time and is armed when the guard is released (_rearm_poll_step)."""
        if self._closed:
            return
        data = getattr(event, "data", None)
        new = data.get("new_state") if isinstance(data, Mapping) else None
        text = sources.poll_text(state_view(new))
        if text is None or text == self._poll_text:
            return
        self._poll_text = text
        now = dt_util.utcnow()
        self._poll_seen_at = now
        self._poll_seq += 1
        self.counters["polls_seen"] += 1
        due = now + timedelta(seconds=PROPOSED_POLL_SETTLE_S)
        if self._poll_due is not None and self._poll_due <= due:
            self.counters["poll_steps_kept_earlier"] += 1   # the pending step is due first: it serves this poll too
            return
        if self._busy:                                   # the quiet cycle: the due time is kept, no timer is armed
            self._poll_due, self._poll_wait, self._poll_held = due, False, False
            self.counters["poll_steps_held_busy"] += 1
            return
        self._arm_poll_step(due)

    @callback
    def _on_poll_step(self, _fired_at: Any = None) -> None:
        """The poll-driven step: a due slot cycle, or a REFRESH when one is needed (see the module rules). A settle hold
        (A36) runs the same step; the cycle it starts is not held again."""
        self._poll_cancel = None
        if self._closed or self._poll_due is None:
            return
        held = self._poll_held
        now = dt_util.utcnow()
        seen = self._poll_seen_at
        slot_due = self._slot_due(now)
        covered = seen is not None and ((self._last_start is not None and self._last_start >= seen)
                                        or self._read_poll_seq == self._poll_seq)
        if not slot_due and covered:
            # a cycle started after this poll was seen, or held its snapshot to this poll's settle end: it read it
            self._cancel_poll_step()
            self.counters["poll_steps_covered"] += 1
            return
        if not slot_due and self._last_start is not None:
            floor_end = self._last_start + timedelta(seconds=PROPOSED_REFRESH_FLOOR_S)
            if now < floor_end:                          # inside the floor: deferred to its end, never dropped
                self.counters["poll_steps_deferred_floor"] += 1
                self._arm_poll_step(floor_end)
                return
        if self._busy:                                   # the second-run guard (defensive: no step is armed while it is
            self.counters["poll_steps_waited_in_flight"] += 1   # set): wait for its release, _rearm_poll_step
            self._poll_wait = True
            return
        self._cancel_poll_step()
        env = self.envelope
        if env is None or env.status == SystemStatus.PAUSED or self._pause_state() is True:
            self.counters["poll_steps_idle"] += 1        # the tick publishes PAUSED and resumes
            return
        if not self._maybe_start(now, POLL, held=held):
            self.counters["poll_steps_idle"] += 1

    def _stale_backoff(self, now: datetime) -> None:
        lo, hi = PROPOSED_STALE_BACKOFF_S
        self._stale_backoff_s = lo if self._stale_backoff_s is None else min(self._stale_backoff_s * 2.0, hi)
        self._stale_until = now + timedelta(seconds=self._stale_backoff_s)
        self.counters["stale_backoffs"] += 1

    # --- the timer ---------------------------------------------------------------------------------------------------
    def _attach_tick(self) -> None:
        """Attach the one timer, the TICK_S interval tick (the one async_track_time_interval call site): at the start, and
        again when a cycle has ended, so its phase follows that end."""
        if self._closed or self._tick_unsub is not None:
            return
        self._tick_unsub = async_track_time_interval(self.hass, self._tick, timedelta(seconds=TICK_S),
                                                     name=TICK_JOB_NAME)

    def _detach_tick(self) -> None:
        """A cycle starts: the tick is detached until it has ended (counted in ticks_deferred)."""
        if self._tick_unsub is not None:
            self._tick_unsub()
            self._tick_unsub = None
            self.counters["ticks_deferred"] += 1

    def _tick_deadline_in(self) -> float:
        """Seconds until the tick body must run again inside a cycle: its last run plus TICK_S, the moment the tick itself
        would have come, within 0 and TICK_S. That run mapped its payloads as of its publish horizon, TICK_S +
        PROPOSED_TICK_MARGIN_S after it, so the whole margin is left for the deadline run's own latency (the job wait's
        timeout and the cycle task's next step), as it is for a late tick: no number outlives its valid_until."""
        if self._tick_ran_at is None:
            return TICK_S
        left = (self._tick_ran_at + timedelta(seconds=TICK_S) - dt_util.utcnow()).total_seconds()
        return min(max(left, 0.0), TICK_S)

    def _deadline_tick(self) -> None:
        """The tick body's deadline (_tick_deadline_in) has come while a cycle is in flight (the tick is detached): the cycle
        task runs it, as one of its own steps (counted in tick_deadline_runs)."""
        self.counters["tick_deadline_runs"] += 1
        self._tick_body(dt_util.utcnow())

    @callback
    def _tick(self, _now: datetime | None = None) -> None:
        """The TICK_S tick (the one timer; detached while a cycle is in flight)."""
        self._tick_body(dt_util.utcnow())

    def _tick_body(self, now: datetime) -> None:
        """The tick's work, also run at the first step of a cycle it did not start, as the catch-up when a cycle ends and at
        its deadline inside a cycle: both poll texts sampled, the pause helper and the self-test, STALE, the re-render as of
        the publish horizon, then _maybe_start."""
        if self._closed:
            return
        self._tick_ran_at = now
        self._sample_liveness(now)
        self._last_tick_at = now
        self._tick_poll_phase_s = (round((now - self._poll_seen_at).total_seconds(), 3) if self._polls_arriving(now)
                                   else None)
        env = self.envelope
        paused = self._pause_state()
        if paused is True:
            self.counters["paused_ticks"] += 1
            if env is None or env.status != SystemStatus.PAUSED:
                self._publish_paused(now)
            return
        if self.selftest.failed:                         # a failed self-test computes nothing until the entry is reloaded
            if env is None or env.status != SystemStatus.SELF_TEST_FAILED:
                self._publish_failed(now, dict(self.selftest.failures()))
            else:
                self._publish(env, now)
            return
        if env is not None and env.status == SystemStatus.PAUSED:
            self._run_now = True                         # resumed: compute at once (nothing was computed while paused)
            # the helper is off, so PAUSED (pause_control ON) no longer holds: STARTING, all nulls, last_good kept, until
            # the next result (the first cycle still waits for the start-up grace)
            self._publish(with_last_good(starting_envelope(now, self.versions, decisions=self.decisions, paused=paused,
                                                           next_run_at=None), self._last_good_source()), now)
            env = self.envelope
        if expires_before_next_tick(env, now):           # its validity (or age limit) ends before the next tick
            self._publish_stale(env, now, paused)
        if self.envelope is not None:                    # re-render: an item that expires before the next tick loses its number
            self._publish(self.envelope, now)
        self._maybe_start(now)

    def _maybe_start(self, now: datetime, trigger: str = TICK, held: bool = False) -> bool:
        """Start a cycle when one is due (True when one started). `trigger` is TICK (the one timer) or POLL (the
        poll-driven step, A23). This is the one place a cycle starts, so the settle hold (A36) is applied here: a cycle
        due inside the settle delay of the newest poll seen is held once to the delay's end (`held`: this start is that
        held one, so it is not held again)."""
        if self._closed or self._started_at is None or self.selftest.failed or self.hass.state != CoreState.running:
            return False
        if (now - self._started_at).total_seconds() < self.grace_s:
            return False
        slot = due_slot(now)
        if self._slot_due(now):
            if trigger == TICK and self._polls_arriving(now):
                self.counters["tick_slot_held"] += 1     # A23: the next poll-driven step starts it, well phased
                return False
            kind, reason = SLOT, "SLOT"                  # a slot cycle wins when both are due
        else:
            reason = self._refresh_reason(now, trigger)
            if reason is None:
                return False
            kind = REFRESH
        if self._busy:
            self.counters["skipped_in_flight"] += 1      # the second-run guard
            if kind == REFRESH:
                self.counters["refresh_skipped_in_flight"] += 1
            return False
        settle_end = self._settle_end(now)
        if settle_end is not None and not held:          # A36: never inside the newest poll's settle delay; held once
            self._settle_hold(settle_end)
            return False
        if held:
            self.counters["settle_held_starts"] += 1
            if settle_end is not None:                   # the residual: a second poll within one settle delay
                self.counters["settle_residual_starts"] += 1
        if kind == SLOT:
            self._first_run_done, self._run_now, self._last_slot = True, False, slot
            self._retry_at, self._retry_used = None, False
            self.counters["slot_runs_started"] += 1
        else:
            if reason == "EXCEPTION_RETRY":
                self._retry_at, self._retry_used = None, True
                self.counters["exception_retries"] += 1
            elif reason == INPUT_EXPIRING:
                self.counters["refresh_input_expiring"] += 1
            elif reason == "INPUT_BLOCKED":
                self.counters["poll_refresh_input"] += 1
            self.counters["refresh_runs_started"] += 1
        if trigger == POLL:
            self.counters["poll_runs_started"] += 1
        self._busy = True                                # the second-run guard, set before the task exists
        self._cycle_live = True
        self._hold_timers()                              # the quiet cycle: no timer of the integration until its end
        self._last_start, self._last_kind, self._last_trigger = now, kind, trigger
        self.counters["runs_started"] += 1
        poll_age = None if self._poll_seen_at is None else round((now - self._poll_seen_at).total_seconds(), 3)
        token = object()
        self._pending_start = token
        # a background task: Home Assistant cancels it at shutdown instead of waiting for it. Never eager: this callback
        # only schedules it, and its first step runs at a later event-loop step (the module docstring, the cycle's steps)
        task = self.hass.async_create_background_task(
            self._async_run(now, self._last_slot or slot, kind, trigger, poll_age, self._poll_seq), CYCLE_TASK_NAME,
            eager_start=False)
        self._task = task
        task.add_done_callback(lambda t: self._never_entered(t, token, now, kind, trigger, poll_age))
        return True

    def _never_entered(self, task: asyncio.Task, token: object, now: datetime, kind: str, trigger: str,
                       poll_age_s: float | None) -> None:
        """The cycle task's done callback: a task cancelled before its first step never ran _async_run (whose finally ends
        a cycle), so it is ended here, with the outcome 'cancelled', exactly as one cancelled at a later step."""
        if self._pending_start is not token:
            return                                       # it ran: its own finally ended it
        self._pending_start = None
        self._cycle_end(now, kind, "cancelled", {"recorder_s": 0.0, "engine_s": 0.0, "store_s": 0.0, "cpu_s": None}, 0.0,
                        trigger, poll_age_s)

    def _cycle_end(self, now: datetime, kind: str, outcome: str, timing: dict, total: float, trigger: str,
                   poll_age_s: float | None) -> None:
        """A cycle has ended, whatever its outcome: the second-run guard is released (unless an abandoned engine thread
        still runs) and the diagnostics are recorded. Then, unless the entry was unloaded, the catch-up (_catch_up) runs,
        also when recording the diagnostics raised. After an unload nothing is attached or armed again. Home Assistant's
        shutdown cancels the cycle task but does not unload the entry, so the catch-up runs then too (it publishes, and
        _maybe_start declines while Core is stopping) and the tick and a held step come back, as the tick stayed attached
        through a shutdown before the quiet cycle."""
        self._cycle_live = False
        if not self._orphans:
            self._busy = False
        try:
            self._finish(now, kind, outcome, timing, total, trigger, poll_age_s)
        finally:
            if not self._closed:
                self._catch_up()

    def _catch_up(self) -> None:
        """The end of a cycle the entry outlived: the tick body runs once as a catch-up (after the guard's release, so a
        slot that fell due can start; the floor still bars a second refresh) and, unless that started the next cycle, the
        tick is attached again and a poll-driven step held while the cycle ran is armed again, also when the catch-up
        raised."""
        try:
            self.counters["catchup_ticks"] += 1
            self._tick_body(dt_util.utcnow())
        finally:
            if not self._cycle_live and not self._closed:
                self._attach_tick()
                self._rearm_poll_step()

    def _submit(self, add_job: Callable[..., asyncio.Future], target: Callable[..., Any], *args: Any) -> asyncio.Future:
        """Submit an executor job that starts only once this event-loop step has ended (__init__.released_call)."""
        return add_job(released_call, release_after_step(self.hass), target, *args)

    # --- one cycle ---------------------------------------------------------------------------------------------------
    def _orphan(self, fut: asyncio.Future) -> None:
        """A job abandoned at the time budget stays 'in flight' until its thread ends; its result is discarded."""
        self._orphans.add(fut)

        def done(f: asyncio.Future) -> None:
            self._orphans.discard(f)
            if not f.cancelled():
                f.exception()                            # retrieved, so it is never logged as unhandled
            self.counters["late_results_discarded"] += 1
            if not self._orphans:
                self._busy = False
                self._rearm_poll_step()
        fut.add_done_callback(done)

    async def _bounded(self, fut: asyncio.Future, deadline: float) -> Any:
        """Wait for an executor job until the cycle's deadline (the time budget: then the job is abandoned, _orphan). The
        tick is detached meanwhile, so when the tick body's own deadline (_tick_deadline_in: its last run plus TICK_S)
        comes first, the wait ends there, the cycle task runs the tick body and waits on."""
        loop = asyncio.get_running_loop()
        while True:
            remaining = max(deadline - loop.time(), 0.0)
            tick_in = self._tick_deadline_in()
            cut = tick_in < remaining
            try:
                return await _job_wait(fut, tick_in if cut else remaining)
            except asyncio.TimeoutError:
                if not cut:
                    self._orphan(fut)
                    raise
            try:
                self._deadline_tick()
            except Exception:
                self._orphan(fut)                        # the cycle fails with the job still running: it stays in flight
                raise

    async def _history_inputs(self, now: datetime, slot: datetime, kind: str, deadline: float,
                              timing: dict) -> tuple[Mapping | None, Any]:
        """The recorder statistics and the scorecard metrics. A SLOT cycle reads both; a REFRESH reuses the slot's cached
        copies, except: no cache for this slot (read), a failed recorder read (read again at most every
        PROPOSED_RECORDER_RETRY_S), rows ending before the slot's hour (read once, PROPOSED_HISTORY_CATCHUP_S after the
        slot). `now` is the cycle time (read with the snapshot, the engine's `now`), not the cycle's start: the recorder
        window, the cache's read_at, the retry and catch-up comparisons and the metrics all use it."""
        plan = self.site.plan
        cache = self._hist
        read = kind == SLOT or cache is None or cache["slot"] != slot
        if not read and plan.statistic_ids and not cache["caught_up"]:
            hour = history_source.window(slot)[1]
            if not cache["ok"]:
                if (now - cache["read_at"]).total_seconds() >= PROPOSED_RECORDER_RETRY_S:
                    read = True
                    self.counters["recorder_retry_reads"] += 1
            elif ((cache["newest_end"] is None or cache["newest_end"] < hour)
                  and (now - slot).total_seconds() >= PROPOSED_HISTORY_CATCHUP_S):
                read = True
                self.counters["history_catchup_reads"] += 1
        if read:
            stats, ok = None, True
            if plan.statistic_ids:
                start, end = history_source.window(now)
                t0 = time_mod.perf_counter()
                try:
                    fut = self._submit(get_instance(self.hass).async_add_executor_job,
                                       statistics_during_period, self.hass, start, end, set(plan.statistic_ids), "hour",
                                       None, set(history_source.STAT_TYPES))
                    stats = await self._bounded(fut, deadline)
                    self.selftest.record("RECORDER_READ", PASS, f"{len(stats or {})} statistic series read")
                except asyncio.TimeoutError:
                    raise
                except Exception as exc:  # noqa: BLE001 - no history: the quality layer blocks what needs it
                    stats, ok = None, False
                    self.selftest.record("RECORDER_READ", WARN, f"statistics could not be read: {type(exc).__name__}")
                finally:
                    timing["recorder_s"] += time_mod.perf_counter() - t0
            # a refresh's read is this slot's one catch-up (a failed read is retried on its own rule); every read, refused
            # or not, drops the parsed history kept from the previous one, so the next cycle rebuilds it (A50)
            self._hist = {"slot": slot, "stats": stats, "ok": ok, "read_at": now, "newest_end": None,
                          "caught_up": kind != SLOT and ok}
            self._history_reuse.clear()
        else:
            stats = cache["stats"]
        if kind == SLOT or not self._metrics_ok:
            t0 = time_mod.perf_counter()
            try:
                self._metrics = await self._bounded(
                    self._submit(self.hass.async_add_executor_job, self.store.outcome_metrics, now), deadline)
                self._metrics_ok = True
            finally:
                timing["store_s"] += time_mod.perf_counter() - t0
        return stats, self._metrics

    def _keep_image(self, stats: object, diag: object) -> None:
        """A50: the cycle parsed this slot's raw statistics into an image; the cache keeps the image instead, so the later
        cycles of this read hand it to the engine job and reuse the parsed history (its exact content is the key). Counts
        the parses and the reuses (diagnostics)."""
        image = self._history_reuse.take_image()
        if isinstance(diag, Mapping):
            self.counters["history_parses"] += 1 if diag.get("history_parsed") is True else 0
            self.counters["history_reuses"] += 1 if diag.get("history_reused") is True else 0
        if image is not None and self._hist is not None and self._hist["stats"] is stats:
            self._hist["stats"] = image

    def _note_history(self, diag: object) -> None:
        if self._hist is None or not isinstance(diag, Mapping):
            return
        ne = diag.get("history_newest_end")
        try:
            self._hist["newest_end"] = datetime.fromisoformat(ne) if isinstance(ne, str) else None
        except ValueError:
            self._hist["newest_end"] = None

    def _finish(self, started: datetime, kind: str, outcome: str, timing: dict, total: float, trigger: str = TICK,
                poll_age_s: float | None = None) -> None:
        """Diagnostics only: last_cycle_timing, cycle_duration_s and one cycle_stats row (with what started the cycle and
        the age of the last poll text at its start). recorder_s, engine_s and store_s run from
        each submit to its result, so they include each job's release wait and SUBMIT_COOLDOWN_S cool-down; total_s
        includes those and any settle hold; cpu_s (the engine thread's CPU time) includes neither."""
        rec = {"started_at": started.isoformat(), "kind": kind, "outcome": outcome, "total_s": round(max(total, 0.0), 6),
               "recorder_s": round(timing["recorder_s"], 6), "engine_s": round(timing["engine_s"], 6),
               "store_s": round(timing["store_s"], 6), "cpu_s": _finite_s(timing.get("cpu_s")), "trigger": trigger,
               "poll_age_s": poll_age_s}
        self.last_timing = rec
        self.cycle_stats.append(tuple(rec[k] for k in CYCLE_STATS_FIELDS))

    async def _snapshot_hold(self, poll_seq: int | None, deadline: float) -> None:
        """The settle hold at the snapshot (A36). The cycle started a loop step or two before its snapshot, so a new poll
        text can have arrived in between, after the start's settle check (`poll_seq`: the poll count at the start). When
        one did and its settle delay is still running, the snapshot is held once to the delay's end (at most
        PROPOSED_POLL_SETTLE_S, never past the cycle's deadline), so the rest of that poll's entity writes land first.
        The cycle covers that poll from the hold on (its own step, due at the same moment, starts no second cycle; not
        when the hold is cancelled). One-shot: a further poll during the hold is not waited for (the residual of two
        polls within one settle delay, counted in snapshot_residual_reads, and that poll is not covered). A hold cut short
        by the cycle's deadline is read inside the settle delay too: it counts there as well and covers nothing."""
        if poll_seq is None or self._poll_seq == poll_seq or self._poll_seen_at is None:
            return                                       # no poll since the start: the start's settle check stands
        seq, before = self._poll_seq, self._read_poll_seq
        self._read_poll_seq = seq
        wait = (self._poll_seen_at + timedelta(seconds=PROPOSED_POLL_SETTLE_S) - dt_util.utcnow()).total_seconds()
        if wait <= 0:
            return                                       # its settle delay has ended already: read it now
        self.counters["snapshot_holds"] += 1
        remaining = deadline - asyncio.get_running_loop().time()
        hold = min(wait, PROPOSED_POLL_SETTLE_S, max(remaining, 0.0))
        try:
            await _settle_wait(hold)
        except asyncio.CancelledError:
            self._read_poll_seq = before                 # never read: this cycle does not cover the poll
            raise
        if hold < wait:                                  # cut short by the cycle's deadline: read inside the settle delay
            self._read_poll_seq = before                 # (a residual), so this cycle does not cover the poll
            self.counters["snapshot_residual_reads"] += 1
        elif self._poll_seq != seq:
            self.counters["snapshot_residual_reads"] += 1

    async def _async_run(self, now: datetime, slot: datetime, kind: str = SLOT, trigger: str = TICK,
                         poll_age_s: float | None = None, poll_seq: int | None = None) -> None:
        """One cycle, in the steps of the module docstring (the cycle's steps). `now` is the moment _maybe_start started
        it and `poll_seq` the poll count then (None: no settle hold at the snapshot); the cycle time `at` is read with the
        snapshot, and the history inputs are read at it."""
        self._pending_start = None                       # entered: the finally below ends this cycle
        t_start = time_mod.perf_counter()
        deadline = asyncio.get_running_loop().time() + self.time_budget_s
        timing = {"recorder_s": 0.0, "engine_s": 0.0, "store_s": 0.0, "cpu_s": None}
        outcome = "aborted"
        try:
            # the tick body first, unless the tick body started this cycle (it ran at the start, `now`: the tick or the
            # catch-up at the previous cycle's end) (tick_start_runs): its next deadline (_tick_deadline_in) is then at
            # least TICK_S after the cycle's start and falls inside this cycle only when the cycle runs longer than
            # TICK_S, so in practice no tick body runs while one of the cycle's jobs computes
            if self._tick_ran_at is None or self._tick_ran_at < now:
                self.counters["tick_start_runs"] += 1
                self._tick_body(dt_util.utcnow())
            # step 1: the pause helper and the self-test
            paused = self._pause_state()
            if paused is True:
                outcome = "paused"
                self._publish_paused(now)
                return
            if self.selftest.failed:
                outcome = "self_test_failed"
                self._publish_failed(now, dict(self.selftest.failures()))
                return
            await _next_step()
            # step 2: the snapshot, after the settle hold of a poll seen since the start (A36), with the cycle time read
            # in the same step (no state in it is newer than `at`); the liveness times are kept with it (a tick between
            # two steps samples the poll texts again)
            await self._snapshot_hold(poll_seq, deadline)
            at = dt_util.utcnow()
            self._sample_liveness(at)
            liveness_at, config_liveness_at = self._liveness_at, self._config_liveness_at
            states = self._collect_states()
            await _next_step()
            # step 3: the recorder statistics and the scorecard metrics
            stats, metrics = await self._history_inputs(at, slot, kind, deadline, timing)
            await _next_step()
            # step 4: the engine job, submitted last in its step
            job = engine_link.EngineJob(
                now=at, states=states, entity_map=self.site.entity_map, liveness_at=liveness_at,
                plan=self.site.plan, statistics=stats, base_cfg=self.site.base_cfg, site_facts=self.site.site_facts,
                decisions=self.decisions, outcome_metrics=metrics, paused=paused,
                previous=None if self._last_computed is None else envelope_summary(self._last_computed),
                versions=self.versions, config_liveness_at=config_liveness_at,
                history_reuse=self._history_reuse)
            t0 = time_mod.perf_counter()
            env, diag, history = await self._bounded(
                self._submit(self.hass.async_add_executor_job, engine_link.compute, job, self._run_cycle), deadline)
            timing["engine_s"] = time_mod.perf_counter() - t0
            timing["cpu_s"] = diag.get("cpu_s") if isinstance(diag, Mapping) else None
            self._note_cpu(timing["cpu_s"])
            self._note_history(diag)
            self._keep_image(stats, diag)
            if self._closed:
                outcome = "closed"
                return
            # read the pause helper (and the self-test) again: whatever changed while the cycle ran wins over its result
            paused_now = self._pause_state()
            if paused_now is True:
                outcome = "discarded_paused"
                self.counters["results_discarded_paused"] += 1
                self._publish_paused(dt_util.utcnow())
                return
            if self.selftest.failed:
                outcome = "discarded_failed"
                self.counters["results_discarded_failed"] += 1
                self._publish_failed(dt_util.utcnow(), dict(self.selftest.failures()))
                return
            self.last_diag = diag
            pub_now = dt_util.utcnow()
            self._retry_at, self._retry_used = None, False      # a result is published: a later exception retries again
            if expires_before_next_tick(env, pub_now):          # valid for less than a tick: STALE at once, values in last_good
                self._stale_backoff(pub_now)
                env = with_next_run_at(env, self._next_run_at(env, pub_now))
                self._publish_stale(env, pub_now, paused_now)
                outcome = "published_stale"
            else:
                self._stale_backoff_s = self._stale_until = None
                env = with_next_run_at(env, self._next_run_at(env, pub_now))   # run_cycle is pure and knows no schedule
                self._publish(env, pub_now)
                outcome = "published"
            self.counters["runs_published"] += 1
            if env.status not in SystemStatus.NULL:
                self._last_computed = env
            if kind != SLOT:                                    # a refresh writes nothing to the state store
                return
            t0 = time_mod.perf_counter()
            try:
                self.last_store = await self._bounded(self._submit(
                    self.hass.async_add_executor_job, self.store.record_cycle, env.scorecard_report, slot, at, history,
                    self.site.base_cfg), deadline)
                self.selftest.record("STORE_RECORD", PASS, "the scorecard step completed")
            except asyncio.TimeoutError:
                self.selftest.record("STORE_RECORD", WARN, "the scorecard step exceeded the time budget")
            except Exception as exc:  # noqa: BLE001 - the published result stands; the scorecard is only diagnostics
                self.selftest.record("STORE_RECORD", WARN, f"the scorecard step failed: {type(exc).__name__}")
            finally:
                timing["store_s"] += time_mod.perf_counter() - t0
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except asyncio.TimeoutError:
            outcome = "budget"
            self.counters["budget_exceeded"] += 1
            self._budget_slot, self._retry_at = slot, None      # no refresh before the next slot
            if not self._closed:
                self._publish_failed(now, {"CYCLE_TIME_BUDGET": "the cycle exceeded its PROPOSED time budget and was "
                                                                "abandoned; its late result is discarded"})
        except Exception as exc:  # noqa: BLE001 - fail closed: any exception publishes SELF_TEST_FAILED
            outcome = "exception"
            self.counters["exceptions"] += 1
            if not self._retry_used and self._retry_at is None:    # one retry, then slot cycles only
                self._retry_at = now + timedelta(seconds=PROPOSED_EXCEPTION_RETRY_S)
            _LOGGER.warning("ECCO Intelligence SHADOW cycle failed: %s", type(exc).__name__)
            _LOGGER.debug("ECCO Intelligence SHADOW cycle failure detail", exc_info=True)
            if not self._closed:                         # only the type is published: a message may carry site values
                self._publish_failed(now, {"RUNTIME_EXCEPTION": type(exc).__name__})
        finally:
            self._cycle_end(now, kind, outcome, timing, time_mod.perf_counter() - t_start, trigger, poll_age_s)

    # --- diagnostics -------------------------------------------------------------------------------------------------
    def _cycle_stats_summary(self) -> dict:
        runs = list(self.cycle_stats)
        by_kind: dict[str, dict] = {}
        for kind in (SLOT, REFRESH):
            rows = [r for r in runs if r[1] == kind]
            tot = [r[3] for r in rows]
            cpu = [r[7] for r in rows if r[7] is not None]
            by_kind[kind] = {"n": len(rows), "total_s_p50": _p(tot, 0.5), "total_s_p95": _p(tot, 0.95),
                             "total_s_max": _p(tot, 1.0), "cpu_s_p95": _p(cpu, 0.95), "cpu_s_max": _p(cpu, 1.0)}
        return {"fields": list(CYCLE_STATS_FIELDS), "kept": len(runs), "max_kept": PROPOSED_CYCLE_STATS_N,
                "job_cooldown_s": SUBMIT_COOLDOWN_S,
                "timings_with_cooldown": ["recorder_s", "engine_s", "store_s", "total_s"],
                "by_kind": by_kind, "runs": [list(r) for r in runs]}

    def _liveness_diag(self, now: datetime) -> dict:
        def age(at: datetime | None) -> float | None:
            return None if at is None else round((now - at).total_seconds(), 3)
        readings = self.site.entity_map.readings
        return {"telemetry": {"mapped": sources.LIVENESS_KEY in readings, "age_s": age(self._liveness_at)},
                "config": {"mapped": CONFIG_LIVENESS_KEY in readings, "age_s": age(self._config_liveness_at)}}

    def diagnostics(self) -> dict:
        env = self.envelope
        now = dt_util.utcnow()

        def iso(t: datetime | None) -> str | None:
            return None if t is None else t.isoformat()
        return {
            "mode": MODE, "versions": {"integration_version": self.versions.integration_version,
                                       "engine_version": self.versions.engine_version, "git_sha": self.versions.git_sha,
                                       "config_hash": self.versions.config_hash},
            "self_test": self.selftest.as_dict(), "status": None if env is None else env.status,
            "reason_codes": [] if env is None else list(env.reason_codes),
            "generated_at": None if env is None or env.generated_at is None else env.generated_at.isoformat(),
            "counters": dict(self.counters), "busy": self._busy, "started": self._started_at is not None,
            "last_slot": iso(self._last_slot),
            "time_budget_s": self.time_budget_s, "grace_s": self.grace_s, "last_cycle": dict(self.last_diag),
            "last_store": dict(self.last_store), "entities": sorted(self.site.entity_map.entity_ids()),
            "decisions": dict(self.decisions.status_map()),
            "last_cycle_timing": dict(self.last_timing), "cycle_duration_s": self.last_timing.get("total_s"),
            "cycle_stats": self._cycle_stats_summary(),
            "cadence": {"refresh_enabled": self.refresh_enabled, "refresh_margin_s": REFRESH_MARGIN_S,
                        "last_start": iso(self._last_start), "last_kind": self._last_kind,
                        "cpu_s_rolling_hour": round(self._cpu_used(now), 6), "cpu_budget_s_per_h": self.cpu_budget_s,
                        "refresh_suspended_cpu": self._cpu_suspended, "retry_at": iso(self._retry_at),
                        "retry_used": self._retry_used, "refresh_barred_until_next_slot": self._budget_slot is not None
                        and self._budget_slot == self._last_slot, "stale_backoff_s": self._stale_backoff_s,
                        "stale_backoff_until": iso(self._stale_until), "last_trigger": self._last_trigger,
                        "poll_listener": self._poll_entity is not None and not self._closed,
                        "polls_arriving": self._polls_arriving(now), "last_poll_seen_at": iso(self._poll_seen_at),
                        "poll_step_due": iso(self._poll_due), "poll_step_waits_in_flight": self._poll_wait,
                        "poll_step_settle_hold": self._poll_held, "poll_step_armed": self._poll_cancel is not None,
                        "cycle_in_flight": self._cycle_live, "tick_attached": self._tick_unsub is not None,
                        "last_tick_at": iso(self._last_tick_at), "tick_poll_phase_s": self._tick_poll_phase_s,
                        "poll_refresh_threshold_s": POLL_REFRESH_THRESHOLD_S},
            "liveness": self._liveness_diag(now),
            "proposed_constants": {"PROPOSED_TIME_BUDGET_S": PROPOSED_TIME_BUDGET_S,
                                   "PROPOSED_STARTUP_GRACE_S": PROPOSED_STARTUP_GRACE_S,
                                   "PROPOSED_RESULT_MAX_AGE_S": PROPOSED_RESULT_MAX_AGE_S,
                                   "PROPOSED_TICK_MARGIN_S": PROPOSED_TICK_MARGIN_S,
                                   "PROPOSED_REFRESH_FLOOR_S": PROPOSED_REFRESH_FLOOR_S,
                                   "PROPOSED_CPU_BUDGET_S_PER_H": PROPOSED_CPU_BUDGET_S_PER_H,
                                   "PROPOSED_EXCEPTION_RETRY_S": PROPOSED_EXCEPTION_RETRY_S,
                                   "PROPOSED_STALE_BACKOFF_S": list(PROPOSED_STALE_BACKOFF_S),
                                   "PROPOSED_HISTORY_CATCHUP_S": PROPOSED_HISTORY_CATCHUP_S,
                                   "PROPOSED_RECORDER_RETRY_S": PROPOSED_RECORDER_RETRY_S,
                                   "PROPOSED_POLL_INTERVAL_S": PROPOSED_POLL_INTERVAL_S,
                                   "PROPOSED_POLL_SETTLE_S": PROPOSED_POLL_SETTLE_S,
                                   "PROPOSED_POLL_ACTIVE_S": PROPOSED_POLL_ACTIVE_S,
                                   "PROPOSED_CYCLE_STATS_N": PROPOSED_CYCLE_STATS_N,
                                   "PROPOSED_RETENTION_DAYS": rstore.PROPOSED_RETENTION_DAYS,
                                   "PROPOSED_HISTORY_ROW_CAP": history_source.PROPOSED_HISTORY_ROW_CAP,
                                   "PROPOSED_HISTORY_LOOKBACK_DAYS": history_source.PROPOSED_HISTORY_LOOKBACK_DAYS},
        }
