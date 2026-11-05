"""Constants of the ECCO Intelligence SHADOW integration (pure; no homeassistant import).

Every number below marked PROPOSED is an engineering suggestion for the runtime, NOT an owner value and not an Intelligence
decision (I-D1..I-D9 stay OPEN). They bound how long a cycle may run and how often it runs; none of them can make a gated
number appear.
"""

from __future__ import annotations

DOMAIN = "ecco_intelligence"
INTEGRATION_VERSION = "0.1.0"
MODE = "SHADOW"                               # the constant mode; anything else refuses setup (runtime/gates.mode_gate)
PLATFORMS = ("sensor", "binary_sensor")       # the only platforms (the runtime boundary suite pins this)
SITE_TZ = "Europe/London"
DEVICE_IDENTIFIER = "ecco_intelligence_shadow"
DEVICE_NAME = "ECCO Intelligence (SHADOW)"

# PROPOSED runtime constants (NOT owner values)
PROPOSED_TIME_BUDGET_S = 120.0                # a cycle (recorder read + engine) that takes longer is abandoned, with a reason
PROPOSED_STARTUP_GRACE_S = 180.0              # the first cycle runs this long after Home Assistant has started
PROPOSED_RESULT_MAX_AGE_S = 8100.0            # a result older than this (2 h 15 min) with no new cycle goes STALE
TICK_S = 60.0                                 # the one timer: staleness, pause and schedule checks (not a tunable)
PROPOSED_TICK_MARGIN_S = 5.0                  # a tick may come this late: payloads are mapped as of the next tick plus this
SCHEDULE_DAILY_LOCAL = (21, 30)               # plus every full hour; local time in Europe/London

# Refresh before expiry (INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.4). Between the schedule slots a REFRESH cycle
# recomputes the result from fresh Home Assistant states with the slot's cached recorder rows; it writes nothing to the
# state store. It never loosens anything: every limit, the 900 s validity ceiling and the null rule are the engine's.
REFRESH_MARGIN_S = 2 * TICK_S + PROPOSED_TICK_MARGIN_S   # 125 s: a result is shown without a gap only if it is valid this
#                                               long when computed; a refresh starts at a tick when less than this is left.
#                                               It must equal the engine's shadow_cycle.REFRESH_MARGIN_S (drift test).
PROPOSED_REFRESH_FLOOR_S = 55.0               # at least this long between two cycle starts for a refresh: one per tick
PROPOSED_CPU_BUDGET_S_PER_H = 180.0           # engine CPU (thread time) per rolling hour above which refreshes are suspended
#                                               (slot cycles continue; the only effect is STALE, which fails closed)
CPU_WINDOW_S = 3600.0                         # the rolling window of the CPU guard (not a tunable)
PROPOSED_EXCEPTION_RETRY_S = 300.0            # after RUNTIME_EXCEPTION: one retry this long after the failed start, then
#                                               slot cycles only (a time-budget overrun is never retried before the next slot)
PROPOSED_STALE_BACKOFF_S = (60.0, 300.0)      # a result published STALE at once: the next refresh waits 60 s, doubling to
#                                               300 s, reset by the next result that is published as computed
PROPOSED_HISTORY_CATCHUP_S = 300.0            # cached recorder rows ending before the due slot are read again once, at least
#                                               this long after the slot (the recorder compiles an hour shortly after it ends)
PROPOSED_RECORDER_RETRY_S = 600.0             # a failed recorder read is retried by a refresh at most this often
PROPOSED_CYCLE_STATS_N = 4800                 # cycle_stats keeps the last this many runs (diagnostics only): more than
#                                               72 h of wall time can start at the highest cycle rate (A50: at most 4713
#                                               starts 55 s apart plus at most 78 schedule slots, 26 a day, in all
#                                               4791), so T1, T5 and T9 can be read from one download at the end of a
#                                               window that spans at most 72 h (runbook section 8); memory stays bounded
#                                               (a deque of tuples)

# Poll-phase-aligned refresh (A23; INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.4). The dongle's telemetry poll text moves
# about once a minute and the 60 s tick holds a near-fixed phase against it; a refresh more than 55 s after a poll would
# withhold every item resting on a dongle input (INPUT_EXPIRING: the 180 s liveness bound less the 125 s margin). So the
# coordinator listens to the mapped telemetry poll text (its one state listener) and starts its refreshes, and the slot
# cycles while polls are arriving, a moment after each poll. Cadence only: no limit, margin, floor value, gate or
# published-value rule changes, and the tick keeps its present rules whenever the poll text stops moving.
PROPOSED_POLL_INTERVAL_S = 60.0               # the telemetry poll text's nominal period (it moves about every 60 s)
PROPOSED_POLL_SETTLE_S = 3.0                  # a poll-driven refresh starts this long after the poll text changed, so the
#                                               rest of that poll's entity writes land first
PROPOSED_POLL_ACTIVE_S = 1.5 * PROPOSED_POLL_INTERVAL_S  # 90 s: poll-driven refreshes count as arriving while a new poll
#                                               text was seen within this long; past it the tick's present rules apply
POLL_REFRESH_THRESHOLD_S = REFRESH_MARGIN_S + PROPOSED_POLL_INTERVAL_S   # 185 s: a poll-driven refresh starts when less
#                                               than this is left (the margin plus one poll), so the margin is never
#                                               entered between two poll-driven refreshes (derived, not a tunable)

# Recorder load (A17; INTELLIGENCE_FOUNDATION_CONTRACT.md section 13.4): the timestamp-only attributes are kept out of Home
# Assistant's recorder by every entity class (_unrecorded_attributes, together with the contract's UNRECORDED_ATTRIBUTES;
# input_ages is one of those already). The published state and attributes stay exactly to_entity_payloads: only what the
# recorder stores changes, so a refresh whose values are unchanged adds no new attributes row to the recorder.
TIMESTAMP_ONLY_ATTRIBUTES = frozenset({"generated_at", "valid_until", "next_run_at"})
