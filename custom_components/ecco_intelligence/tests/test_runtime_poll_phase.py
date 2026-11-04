#!/usr/bin/env python3
"""L2, A23: the poll-phase-aligned refresh of the BUILT kit under the stand-in Home Assistant, with state_changed events.

The world (synthetic, 2030, generic test_* ids): the dongle's telemetry poll writes its poll text, and re-reports the other
mapped entities, at chosen times: every 60 s plus or minus 3 s, each poll jittered around a fixed grid at a chosen phase
offset from the one-minute tick ('grid'), or each interval 60 s plus or minus 3 s ('walk'), or an explicit list; the
configuration poll writes its own text every 60 s at its own phase; the recorder compiles each hour as it ends. Time is
event driven (Harness.run_until): the tick fires at its own times, the coordinator's poll-driven step at its
async_call_later time, each poll at its time, and every cycle finishes before the clock moves on.

STALE, INPUT_EXPIRING and the numbers are counted from the stand-in's recorder rows (every write that changed a state or an
attribute, as Home Assistant's states table keeps it), never only from observations taken after each cycle has finished:
a STALE that a tick writes and the same tick's refresh replaces is in the recorder, not in a post-cycle observation (A32).

  [1] phase sweep (owner-record decisions, the real vendored cycle) at the offsets 0.5, 1.5, 3, 15, 30, 45, 55, 56, 58
      and 59.5 s (A36's list included): at every offset, over three simulated hours after the
      first result, no recorder row has the status STALE or an item or forecast BLOCKED INPUT_EXPIRING, and no computed
      result holds INPUT_EXPIRING; every charge_target and predicted_morning_soc row (and every observation) carries its
      number, and no item resting on a dongle input ever holds a number its inputs no longer cover; every refresh is
      poll-driven and starts PROPOSED_POLL_SETTLE_S after its poll (the tick-to-poll phase is in cycle_stats and the
      diagnostics); cycles per
      hour are at most one per poll, state writes per hour at most eleven per published cycle; every cycle starts at or
      after the next_run_at published before it, and next_run_at lies between generated_at and valid_until; at the badly
      phased offsets the tick held refreshes and slot cycles back (non-vacuity of the hold); the A36 settle hold never
      applies (no cycle is due inside a poll's settle delay)
  [2] the same with each poll interval 60 s plus or minus 3 s (the phase drifts)
  [3] recovery, each within one poll plus the settle delay of the input recovering: a TOU slot's charge source 'unknown'
      (while BLOCKED for that input reason next_run_at is the refresh floor); a frozen configuration-poll text; a frozen
      telemetry poll text, which meanwhile gives the fail-closed result (the poll-driven step idle, the tick's own rules:
      every item resting on a dongle input BLOCKED without a number, the history-only items keep theirs, no
      CALLER_FRESHNESS_DISAGREES, at most one STALE recorder row, replaced by a computed result at once or, inside a
      poll's settle delay, at that delay's end)
  [4] the settle delay: the poll-driven refresh reads an entity that poll writes one second after its text
  [5] the 55 s floor: a poll inside the floor is deferred to the floor's end, never dropped
  [6] A36: the exception retry the tick asks for 1 s after a poll is held to that poll's settle delay's end (no cycle
      at the tick) and started there by the poll-driven step; it reads what that poll writes 1.5 s after its text, with
      that poll's liveness time; no second cycle for that poll
  [7] the second-run guard: a poll-driven step while a cycle is in flight waits for its end, then runs; when a newer
      poll arrived while it waited (it keeps the step, A33) and the cycle ends inside that poll's settle delay, the step
      is held (A36) and still starts the settle delay after that poll and reads what that poll writes just after its
      text (the RR-2 timeline)
  [8] the CPU guard, the time-budget bar, the refresh switch, the pause helper and a failed self-test apply to the
      poll-driven step (slot cycles still start at the poll-driven step)
  [9] the listener: exactly one, on the mapped telemetry poll text; a replayed or unavailable text and an attribute-only
      change are no new poll; a second new text before the pending step never moves it later (A33, RT-2); unload removes
      the listener and cancels the pending step
  [10] the poll-driven threshold (the margin plus one poll): results valid 186 s are refreshed at every poll, so a late
      poll leaves no STALE, and next_run_at is never after the next start; the tick's exception to its hold (it refreshes
      only an envelope that would go STALE at the next tick before the next expected poll-driven step)
  [11] missed, late and frozen polls (A32), each over seven phase offsets: one poll 90 s after the previous, one skipped
      poll (120 s), a 150 s gap and a freeze (no poll for 480 s). Per episode: at most one STALE status row in the
      recorder, replaced by a computed status at the same tick or, when the tick falls inside a poll's settle delay, at
      that delay's end (A36; one STALE cycle); never a wrong number (no item resting on
      a dongle input is written with, or holds, a number its last telemetry poll no longer covers); during the freeze the
      fallback (the tick's own rules: dongle items BLOCKED INPUT_NOT_FRESH, history-only items keep their numbers); then
      recovery at the next poll plus the settle delay (deferred to the 55 s floor's end when the tick's refresh started
      less than 55 s before it), with every dongle item's number back and no STALE afterwards. A31(b), the polls-stop
      half of the exposure: in the freeze every item resting on a dongle input (Dump among them) loses the number of the
      last poll's compute no later than the first tick after the last poll plus PROPOSED_POLL_ACTIVE_S (90 s), at most
      150 s after that poll; the supervision heartbeat stops with the polls, and the first compute after the last
      poll's compute (more than 90 s and at most 150 s after that poll) BLOCKs export and Dump SUPERVISION_NOT_STABLE
  [12] A31(b): the supervision heartbeat stops while the telemetry polls continue: the supervision bound (90 s) lapses at
      a known moment; every poll-driven compute before it keeps export and Dump free of SUPERVISION_NOT_STABLE (Dump OK
      with a number valid past the lapse: supervision is not in the item validity, by design); the first poll-driven
      compute after it BLOCKs export and Dump SUPERVISION_NOT_STABLE, at most one poll plus the settle delay after the
      lapse (the worst-case exposure while polls arrive; [11] pins the case where they stop); charge_target is
      unaffected
  [13] A33 (RT-2) and A36: a poll text that changes every 2 s (faster than the settle delay) never postpones the
      pending step, and the settle hold is one-shot, never re-armed by a later poll: cycles start after the start-up
      grace and then at each 55 s floor's end plus at most the settle delay, all poll-driven, the status OK (no
      starvation; each such start is the documented residual: a second poll within one settle delay)
  [14] A36: no cycle starts inside the settle delay of the newest poll seen. (a) a step deferred to the floor's end with
      a newer poll 1 s before that end: held to that poll's settle delay's end and reads what that poll writes 2 s after
      its text; (b) a late poll 0.5 s before a tick that publishes STALE: the tick's refresh is held to that poll's
      settle delay's end and reads what that poll writes 1 s after its text; the one STALE row is replaced there
Every scenario also ends with zero write attempts of any kind, no stand-in violation and the configuration tree unchanged
outside ecco/intelligence/state/. Plain script; exits 1 on any failure.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
START = datetime(2030, 1, 15, 20, 5, tzinfo=UTC)
PREFIX = "ecco_intel_poll_phase_"
root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(kit)
C = h.contract
COORD = importlib.import_module("custom_components.ecco_intelligence.coordinator")
CONST = importlib.import_module("custom_components.ecco_intelligence.const")
ENGINE_LINK = importlib.import_module("custom_components.ecco_intelligence.runtime.engine_link")
ORIG_COMPUTE = ENGINE_LINK.compute
VEN_Q = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.quality")
SD = importlib.import_module("custom_components.ecco_intelligence._vendor.intelligence.site_decisions")
ITEM_KEYS = C.ADVICE_ITEMS + C.FORECAST_ITEMS
DONGLE_ITEMS = tuple(k for k in H.gated_keys(C) if set(SD.REQUIRED_SIGNALS.get(k, ())) & set(SD.DONGLE_SIGNALS))
TOU_ITEMS = ("charge_target", "overnight_demand", "export_event", "dump_to_grid", "predicted_morning_soc")
SETTLE = CONST.PROPOSED_POLL_SETTLE_S
FLOOR = CONST.PROPOSED_REFRESH_FLOOR_S
TEL = H.eid("sensor", "last_telemetry_update")
SOC = H.eid("sensor", "battery_soc")
HEARTBEAT = "sensor.test_supervision_heartbeat_age"                     # as the harness map (READING_MAP)
LIVENESS_BOUND_S = VEN_Q.DQ_PROPOSED.liveness_max_age_s
# an item resting on a dongle input: the telemetry liveness bounds its validity (the charge-window items rest on the
# configuration poll too, whose readings are observed at the older of the two poll times)
COVERED_ITEMS = tuple(dict.fromkeys(DONGLE_ITEMS + TOU_ITEMS))
HISTORY_ONLY = ("pv_tomorrow", "predicted_day_load")


def num_text(s) -> bool:
    """A recorded state that is a number (an item entity's state carries its number, or 'unknown' without one)."""
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def row_codes(attrs) -> set:
    """The reason codes and blocker codes of one recorded attributes set."""
    return set(attrs.get("reason_codes") or []) | {b.get("code") for b in attrs.get("blockers") or [] if isinstance(b, dict)}


def owner_profile(readings=None):
    return H.site_profile(decisions=H.owner_decisions(), readings=readings)


class World:
    """One stand-in Home Assistant (state_changed events on) with the built integration set up at `start` on the generic
    test site file, a dongle whose telemetry poll follows `mode` ('grid', 'walk' or 'list' with `poll_times`) and a
    configuration poll every 60 s at `config_offset` from the tick."""

    def __init__(self, name, profile=None, *, start=START, offset=30.0, jitter=3.0, mode="grid", config_offset=17.0,
                 seed=1, poll_times=None, grace=None, inject=None, settle=5.0):
        self.name = name
        self.cfg = root / name
        self.cfg.mkdir()
        self.hass = h.new_hass(self.cfg, start)
        H.write_site(self.cfg, profile if profile is not None else owner_profile())
        h.clear_world()
        self.rng = random.Random(seed)
        self.start, self.offset, self.jitter, self.mode = start, offset, jitter, mode
        self.settle = settle
        self.tel_at = start - timedelta(seconds=30)        # the poll times the dongle last wrote
        self.cfg_at = start - timedelta(seconds=30)
        self.tel_frozen = self.cfg_frozen = False
        self.mutate = None                                   # callable(world) after each telemetry poll's writes
        self.on_config = None                                # callable(world) after each configuration poll's write
        self.polls: list[datetime] = []                      # the telemetry poll times written (text moved)
        self.obs: list[dict] = []
        self.envs: list = []                                 # every computed envelope published, in order
        self._last_env = None
        H.seed_fresh_states(self.hass.states, start, telemetry_at=self.tel_at, config_at=self.cfg_at)
        h.recorder().statistics = H.synthetic_statistics(start, days=30)
        self.before = H.tree_hashes(self.cfg)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        if grace is not None:
            self.c.grace_s = grace
        if inject is not None:
            H.inject(self.c, inject)
        self._k = 0
        self._poll_list = list(poll_times or [])
        self._next_tel = None
        self._schedule_tel()
        self._schedule_cfg(start + timedelta(seconds=config_offset))
        hour = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        for k in range(8):
            h.at(hour + timedelta(hours=k), self._compile_hour)

    # --- the world --------------------------------------------------------------------------------------------------
    def _schedule_tel(self) -> None:
        if self.mode == "list":
            if not self._poll_list:
                return
            at = self._poll_list.pop(0)
        elif self.mode == "walk":
            prev = self._next_tel or (self.start + timedelta(seconds=self.offset - 60.0))
            at = prev + timedelta(seconds=60.0 + self.rng.uniform(-self.jitter, self.jitter))
        else:
            at = self.start + timedelta(seconds=self.offset + 60.0 * self._k + self.rng.uniform(-self.jitter, self.jitter))
            self._k += 1
        self._next_tel = at
        h.at(at, self._tel_poll)

    def _tel_poll(self) -> None:
        now = h.now
        if not self.tel_frozen:
            self.tel_at = now
            self.polls.append(now)
        # the poll text first (its state_changed reaches the coordinator at once), then that poll's other entities
        H.seed_fresh_states(self.hass.states, now, telemetry_at=self.tel_at, config_at=self.cfg_at)
        if self.mutate is not None:
            self.mutate(self)
        self._schedule_tel()

    def _schedule_cfg(self, at: datetime) -> None:
        h.at(at, lambda: self._cfg_poll(at))

    def _cfg_poll(self, at: datetime) -> None:
        if not self.cfg_frozen:
            self.cfg_at = h.now
            self.hass.states.seed(H.CONFIG_POLL_TEXT, H.poll_time_text(self.cfg_at), changed_at=self.cfg_at)
        if self.on_config is not None:
            self.on_config(self)
        self._schedule_cfg(at + timedelta(seconds=60))

    def _compile_hour(self) -> None:
        h.recorder().statistics = H.synthetic_statistics(h.now, days=30)

    # --- observing --------------------------------------------------------------------------------------------------
    def attrs(self, key="status"):
        s = h.state(key)
        return {} if s is None else dict(s.attributes)

    def numeric(self, keys=ITEM_KEYS):
        return [k for k in keys if H.numeric_state(h.state(k))]

    def codes(self, key):
        lc = self.c._last_computed  # noqa: SLF001
        if lc is None:
            return set()
        v = {x.key: x for x in tuple(lc.items) + tuple(lc.forecasts)}.get(key)
        return set() if v is None else {c_ for c_, _t in v.blockers} | set(v.reason_codes)

    def observe(self, kind: str) -> None:
        env = self.c._last_computed  # noqa: SLF001
        if env is not None and env is not self._last_env:
            self._last_env = env
            self.envs.append(env)
        st = h.state("status")
        self.obs.append({"t": h.now, "kind": kind, "status": None if st is None else st.state,
                         "numeric": tuple(self.numeric()), "computed": env is not None,
                         "pub_codes": {k: tuple(self.attrs(k).get("reason_codes", []))
                                       + tuple(b_.get("code") for b_ in self.attrs(k).get("blockers", []) or [])
                                       for k in ITEM_KEYS}})

    def run(self, until: datetime, settle: float | None = None) -> None:
        h.run_until(until, settle=self.settle if settle is None else settle, observe=self.observe)

    def run_for(self, seconds: float, settle: float | None = None) -> None:
        self.run(h.now + timedelta(seconds=seconds), settle)

    def starts(self, since: datetime | None = None) -> list[tuple]:
        """(started_at, kind, trigger, poll_age_s, outcome) of every cycle in cycle_stats, oldest first."""
        f = list(COORD.CYCLE_STATS_FIELDS)
        rows = [dict(zip(f, r)) for r in self.c.cycle_stats]
        out = [(datetime.fromisoformat(r["started_at"]), r["kind"], r["trigger"], r["poll_age_s"], r["outcome"])
               for r in rows]
        return [x for x in out if since is None or x[0] >= since]

    def next_poll_after(self, t: datetime) -> datetime | None:
        later = [p for p in self.polls if p >= t]
        return min(later) if later else None

    def last_poll_at(self, t: datetime) -> datetime | None:
        earlier = [p for p in self.polls if p <= t]
        return max(earlier) if earlier else None

    # --- the recorder (every write that changed a state or an attribute: Home Assistant's states table) -------------
    def rows(self, key: str, since: datetime | None = None, until: datetime | None = None) -> list[tuple]:
        """(time, state, recorded attributes) of every recorder states row of the integration entity `key`, oldest
        first (hass.recorder_log and hass.recorder_rows are appended together, one entry per states row)."""
        eid_ = C.ENTITY_IDS[key]
        return [(t, row[1], row[2]) for (t, e, _n), row in zip(self.hass.recorder_log, self.hass.recorder_rows)
                if e == eid_ and (since is None or t >= since) and (until is None or t <= until)]

    def stale_rows(self, since: datetime, until: datetime | None = None) -> list[datetime]:
        return [t for t, s, _a in self.rows("status", since, until) if s == "STALE"]

    def stale_not_replaced(self, since: datetime, until: datetime | None = None) -> list[str]:
        """Each STALE status row that is not followed by a computed status row at the same moment or, when the last
        telemetry poll lies within the settle delay before it, at that poll's settle delay's end at the latest (A36: the
        refresh the tick asks for is held to that moment), with no other status row in between. The stand-in runs a
        cycle with the clock standing, so a STALE the tick writes before the refresh it starts is replaced at that same
        time, or at the end of the hold, when it lasts one cycle only."""
        rs = self.rows("status", since, until)
        bad = []
        for i, (t, s, _a) in enumerate(rs):
            if s != "STALE":
                continue
            nxt = rs[i + 1] if i + 1 < len(rs) else None
            p = self.last_poll_at(t)
            limit = t if p is None else max(t, p + timedelta(seconds=SETTLE))
            if nxt is None or not t <= nxt[0] <= limit or nxt[1] in C.SystemStatus.NULL:
                bad.append(f"{t.isoformat()[11:21]} -> {nxt and (nxt[0].isoformat()[11:21], nxt[1])}")
        return bad

    def stale_held(self, since: datetime, until: datetime | None = None) -> int:
        """How many STALE status rows were replaced later than their own moment (the A36 hold)."""
        rs = self.rows("status", since, until)
        return sum(1 for i, (t, s, _a) in enumerate(rs) if s == "STALE" and i + 1 < len(rs) and rs[i + 1][0] > t)

    def uncovered_numbers(self, since: datetime, until: datetime, keys=COVERED_ITEMS) -> list[tuple]:
        """Every span in which an item resting on a dongle input held a number (from a recorder row with a numeric state
        to that entity's next row, or `until`) that its inputs did not cover: written more than the liveness bound less
        one tick and the tick margin after the last telemetry poll (so not covered through the publish horizon), or still
        held past the last poll plus the liveness bound. Empty when no wrong number was ever shown."""
        bad = []
        slack = LIVENESS_BOUND_S - CONST.TICK_S - CONST.PROPOSED_TICK_MARGIN_S
        for k in keys:
            rs = self.rows(k, None, until)
            for i, (t, s, _a) in enumerate(rs):
                if not num_text(s):
                    continue
                end = rs[i + 1][0] if i + 1 < len(rs) else until
                if end < since:
                    continue
                p = self.last_poll_at(t)
                if (p is None or (t - p).total_seconds() > slack
                        or (end - p).total_seconds() > LIVENESS_BOUND_S):
                    bad.append((k, t.isoformat()[11:19], end.isoformat()[11:19], p and p.isoformat()[11:19]))
        return bad

    def close(self, unload=True):
        if unload and self.c is not None and not self.c.closed:
            h.unload(self.entry)
        h.clear_world()
        after = H.tree_hashes(self.cfg)
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k)
                         and not k.startswith("ecco/intelligence/state/"))
        check(f"{self.name}: zero write attempts", not self.hass.write_attempts, str(self.hass.write_attempts[:3]))
        check(f"{self.name}: no stand-in violation", not self.hass.violations, str(self.hass.violations[:3]))
        check(f"{self.name}: the configuration tree changed only under ecco/intelligence/state/", not changed, str(changed[:3]))


def scripted(step, calls):
    """An injected run_cycle built ONLY from the kit's contract constructors: pv_tomorrow OK, every advice item BLOCKED
    (TEST_BLOCK, not an input reason). Call n does what step(n) returns: {"valid_s", "block": an Event, "sleep",
    "burn": CPU seconds, "error"}; every call's inputs.now is appended to `calls`."""
    def run(inputs):
        n = len(calls)
        calls.append(inputs.now)
        sp = step(n) or {}
        if sp.get("block") is not None:
            sp["block"].wait(60)
        if sp.get("sleep"):
            time.sleep(sp["sleep"])
        if sp.get("burn"):
            t0 = time.thread_time()
            while time.thread_time() - t0 < sp["burn"]:
                pass
        if sp.get("error") is not None:
            raise sp["error"]
        vs = float(sp.get("valid_s", 180.0))
        bl = (("TEST_BLOCK", "synthetic block"),)
        items = tuple(C.ItemView(k, C.ItemStatus.BLOCKED, blockers=bl) for k in C.ADVICE_ITEMS)
        fc = (C.ForecastView("predicted_day_load", C.ItemStatus.BLOCKED, blockers=bl),
              C.ForecastView("pv_tomorrow", C.ItemStatus.OK, value=4.2, valid_until=inputs.now + timedelta(seconds=vs)),
              C.ForecastView("predicted_morning_soc", C.ItemStatus.BLOCKED, blockers=bl))
        return C.assemble_envelope(inputs.now, inputs.versions, items=items, forecasts=fc, data_quality=C.DataQuality.OK,
                                   decisions=inputs.decisions, paused=inputs.paused,
                                   valid_until=inputs.now + timedelta(seconds=vs))
    return run


SOC_CANONICAL = H.SIGNAL_MAP["battery.soc"]["entity"]                   # SOC above is the raw SOC (battery.soc_raw_pct)


class LateSoc:
    """A world's `mutate` (A36): each telemetry poll's SOC (the raw and the canonical entity, so the two agree) is written
    `delay` seconds after its text; until then both hold the previous poll's value, as the dongle last wrote it. `want`
    maps each poll time to the SOC it writes."""

    def __init__(self, delay: float):
        self.delay = delay
        self.want: dict = {}
        self.cur = ["55", START - timedelta(hours=3)]

    def _seed(self, world, val, at):
        for e in (SOC, SOC_CANONICAL):
            world.hass.states.seed(e, val, {"unit_of_measurement": "%"}, changed_at=at)

    def __call__(self, world):
        p, val = h.now, str(60 + len(world.polls) % 30)
        self.want[p] = val
        self._seed(world, self.cur[0], self.cur[1])
        at = p + timedelta(seconds=self.delay)

        def write():
            self.cur[0], self.cur[1] = val, at
            self._seed(world, val, at)
        h.at(at, write)


def spy_jobs(jobs: list):
    """An engine_link.compute wrapper that records (now, the SOC entity's state, the telemetry liveness time) per job."""
    def spy(job, run_cycle=None):
        jobs.append((job.now, (job.states.get(SOC) or {}).get("state"), job.liveness_at))
        return ORIG_COMPUTE(job, run_cycle)
    return spy


def healthy_report(w: World, label: str, hours: float = 3.0) -> None:
    """Run `w` for `hours` after its first computed result and check the A23 acceptance on everything observed."""
    w.run(w.start + timedelta(minutes=8))
    first = next((e.generated_at for e in w.envs), None)
    check(f"{label}: a first result within eight minutes of start-up", first is not None, str(w.c.counters))
    if first is None:
        return
    t_end = first + timedelta(hours=hours)
    w.run(t_end)
    obs = [o for o in w.obs if o["t"] >= first]
    envs = [e for e in w.envs if e.generated_at >= first]
    expiring = [(e.generated_at.isoformat(), v.key) for e in envs for v in tuple(e.items) + tuple(e.forecasts)
                if "INPUT_EXPIRING" in v.reason_codes or any(c_ == "INPUT_EXPIRING" for c_, _t in v.blockers)]
    pub_exp = [(o["t"].isoformat(), k) for o in obs for k, cs in o["pub_codes"].items() if "INPUT_EXPIRING" in cs]
    rec_exp = [(t.isoformat(), k) for k in ITEM_KEYS for t, _s, a in w.rows(k, first, t_end) if "INPUT_EXPIRING" in row_codes(a)]
    stale = [t.isoformat() for t in w.stale_rows(first, t_end)]
    n_status = len(w.rows("status", first, t_end))
    check(f"{label}: over {hours:g} h no STALE status row ({n_status} status rows in the recorder: every write counted, "
          f"not only after each cycle), no item or forecast row BLOCKED INPUT_EXPIRING, and no computed result ({len(envs)}) "
          "or observation holding INPUT_EXPIRING", not expiring and not pub_exp and not rec_exp and not stale
          and n_status >= 150 * hours / 3.0, f"{expiring[:3]} {pub_exp[:3]} {rec_exp[:3]} {stale[:3]}")
    missing = [(o["t"].isoformat(), o["kind"]) for o in obs if not {"charge_target", "predicted_morning_soc"} <= set(o["numeric"])]
    blank = [(t.isoformat(), k) for k in ("charge_target", "predicted_morning_soc") for t, s, _a in w.rows(k, first, t_end)
             if not num_text(s)]
    check(f"{label}: non-vacuity: charge_target and predicted_morning_soc carry their numbers in every recorder row and at "
          f"every observation ({len(obs)})", not missing and not blank and len(obs) > 400, str((missing + blank)[:4]))
    uncovered = w.uncovered_numbers(first, t_end)
    check(f"{label}: no item resting on a dongle input was written with, or held, a number its last telemetry poll no "
          "longer covered", not uncovered, str(uncovered[:3]))
    rows = w.starts(first)
    refreshes = [r for r in rows if r[1] == "REFRESH"]
    tick_runs = [r for r in rows if r[2] != "POLL"]
    late = [r for r in rows if r[3] is None or abs(r[3] - SETTLE) > 1.01]
    check(f"{label}: every cycle ({len(rows)}: {len(refreshes)} refreshes, {len(rows) - len(refreshes)} slot cycles) is "
          f"poll-driven and starts the settle delay after its poll (at most one second later, the floor)",
          not tick_runs and not late and len(refreshes) >= 150 * hours / 3.0,
          f"tick {tick_runs[:3]} late {late[:3]} n={len(refreshes)}")
    holds = {k: w.c.counters[k] for k in ("settle_holds", "settle_held_starts", "settle_residual_starts")}
    check(f"{label}: A36: the settle hold never applied (with healthy polls no cycle is due inside a poll's settle delay, "
          "so the hold leaves the cadence unchanged)", not any(holds.values()), str(holds))
    hr0 = first.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    per_hour = []
    writes = w.hass.state_write_log
    for k in range(int(hours) - 1):
        a_, b_ = hr0 + timedelta(hours=k), hr0 + timedelta(hours=k + 1)
        per_hour.append({"hour": a_.isoformat(), "polls": sum(1 for p in w.polls if a_ <= p < b_),
                         "cycles": sum(1 for r in rows if a_ <= r[0] < b_),
                         "published": sum(1 for r in rows if a_ <= r[0] < b_ and str(r[4]).startswith("published")),
                         "state_writes": sum(1 for t, *_x in writes if a_ <= t < b_)})
    print(f"  {label}: per hour " + json.dumps(per_hour))
    check(f"{label}: cycles per hour at most one per poll; state writes per hour at most eleven per published cycle",
          bool(per_hour) and all(x["cycles"] <= x["polls"] + 1 and x["state_writes"] <= 11 * x["published"] + 11
                                 for x in per_hour), json.dumps(per_hour))
    bad_next = []
    for prev, nxt in zip(envs, envs[1:]):
        if prev.next_run_at is None or not (prev.generated_at <= prev.next_run_at <= (prev.valid_until or prev.next_run_at)):
            bad_next.append(("range", prev.generated_at.isoformat()))
        elif nxt.generated_at < prev.next_run_at:
            bad_next.append(("earliest", prev.generated_at.isoformat(), prev.next_run_at.isoformat(),
                             nxt.generated_at.isoformat()))
    check(f"{label}: next_run_at lies between generated_at and valid_until, and no cycle starts before the next_run_at "
          "published before it", not bad_next, str(bad_next[:3]))


try:
    # -----------------------------------------------------------------------------------------------------------------
    print("== [1] phase sweep: the telemetry poll every 60 s +/- 3 s at each offset from the tick, three hours each")
    # -----------------------------------------------------------------------------------------------------------------
    held = {}
    # each offset keeps its own jitter seed (the A36 offsets 55 and 58 s were added with seeds of their own)
    sweep_seeds = {0.5: 11, 1.5: 12, 3.0: 13, 15.0: 14, 30.0: 15, 45.0: 16, 55.0: 25, 56.0: 17, 58.0: 26, 59.5: 18}
    for i, off in enumerate(sorted(sweep_seeds)):
        w = World(f"sweep_{i}", offset=off, seed=sweep_seeds[off])
        healthy_report(w, f"offset {off:g} s")
        held[off] = (w.c.counters["tick_refresh_held"], w.c.counters["tick_slot_held"])
        d = w.c.diagnostics()["cadence"]
        if i == 0:
            check("the diagnostics carry the poll-driven cadence state and the tick-to-poll phase",
                  d["poll_listener"] is True and d["polls_arriving"] is True and d["last_poll_seen_at"] is not None
                  and isinstance(d["tick_poll_phase_s"], float) and d["poll_refresh_threshold_s"] == 185.0
                  and w.c.diagnostics()["proposed_constants"]["PROPOSED_POLL_SETTLE_S"] == SETTLE, json.dumps(d))
        w.close()
    print("  held (tick refreshes, tick slot starts): " + json.dumps({str(k): v for k, v in held.items()}))
    check("non-vacuity: at the badly phased offsets (the tick more than 55 s after the poll) the tick held refreshes back, "
          "and every offset held its slot cycles for the poll-driven step",
          all(held[o][0] > 0 for o in (0.5, 1.5)) and all(v[1] > 0 for v in held.values()), json.dumps(
              {str(k): v for k, v in held.items()}))

    # -----------------------------------------------------------------------------------------------------------------
    print("== [2] each poll interval 60 s +/- 3 s (the phase drifts), three hours")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("walk", mode="walk", offset=20.0, seed=7)
    healthy_report(w, "random-walk polls")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [3] recovery within one poll plus the settle delay of the input recovering")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("recover_slot", mode="walk", offset=25.0, seed=3)
    w.run(START + timedelta(minutes=8))
    check("non-vacuity: charge_target OK with a number before the fault", w.attrs("charge_target").get("status") == "OK"
          and "charge_target" in w.numeric(), str(w.attrs("charge_target").get("status")))
    slot = {"unknown": False}

    def keep_slot(world):
        if slot["unknown"]:
            world.hass.states.seed(H.slot_eid(3, "charge_source"), "unknown")

    def set_slot(unknown):
        def fn():
            slot["unknown"] = unknown
            w.hass.states.seed(H.slot_eid(3, "charge_source"), "unknown" if unknown else "None")
        return fn
    w.mutate = keep_slot
    t_fault = h.now + timedelta(seconds=41)
    h.at(t_fault, set_slot(True))
    w.run(t_fault + timedelta(minutes=3))
    env = w.c._last_computed  # noqa: SLF001
    blocked = {k: w.attrs(k).get("status") for k in TOU_ITEMS}
    check("slot 3's charge source 'unknown': every charge-window item BLOCKED TOU_SLOT_SOURCE_UNKNOWN without a number, "
          "refreshed at every poll (BLOCKED for an input reason) with next_run_at the refresh floor",
          all(v == "BLOCKED" for v in blocked.values()) and "TOU_SLOT_SOURCE_UNKNOWN" in w.codes("charge_target")
          and not w.numeric(TOU_ITEMS) and w.c.counters["poll_refresh_input"] >= 2 and env.next_run_at is not None
          and abs((env.next_run_at - env.generated_at).total_seconds() - FLOOR) < 1e-6,
          f"{blocked} {sorted(w.codes('charge_target'))[:4]} {w.c.counters['poll_refresh_input']} "
          f"{env.next_run_at and (env.next_run_at - env.generated_at).total_seconds()}")
    t_rec = h.now + timedelta(seconds=37)
    h.at(t_rec, set_slot(False))
    w.run(t_rec + timedelta(seconds=0.5))
    p_rec = w._next_tel  # noqa: SLF001 - the first telemetry poll after the input recovered
    w.run(p_rec - timedelta(seconds=0.2))
    before = w.attrs("charge_target").get("status")
    w.run(p_rec + timedelta(seconds=SETTLE + 0.2))
    check("slot 3 restored: charge_target OK with a number again at the first poll after the recovery plus the settle "
          f"delay ({(p_rec - t_rec).total_seconds():.1f} s + {SETTLE:g} s), BLOCKED until then",
          before == "BLOCKED" and w.attrs("charge_target").get("status") == "OK" and "charge_target" in w.numeric(),
          f"{before} {w.attrs('charge_target').get('status')}")
    w.close()

    w = World("recover_config", mode="walk", offset=25.0, seed=4)
    w.run(START + timedelta(minutes=8))
    check("non-vacuity: charge_target OK before the configuration-poll text freezes",
          w.attrs("charge_target").get("status") == "OK", str(w.attrs("charge_target").get("status")))
    w.cfg_frozen = True
    w.run_for(7 * 60)
    check("a configuration-poll text frozen for seven minutes: charge_target BLOCKED CONFIG_LIVENESS_STALE, no number",
          w.attrs("charge_target").get("status") == "BLOCKED" and "CONFIG_LIVENESS_STALE" in w.codes("charge_target")
          and "charge_target" not in w.numeric(), f"{w.attrs('charge_target').get('status')} {sorted(w.codes('charge_target'))[:4]}")
    t_rec = h.now + timedelta(seconds=23)

    def unfreeze_cfg():
        w.cfg_frozen = False
        w.cfg_at = h.now
        w.hass.states.seed(H.CONFIG_POLL_TEXT, H.poll_time_text(h.now), changed_at=h.now)
    h.at(t_rec, unfreeze_cfg)
    w.run(t_rec + timedelta(seconds=0.5))
    p_rec = w._next_tel  # noqa: SLF001
    w.run(p_rec - timedelta(seconds=0.2))
    before = w.attrs("charge_target").get("status")
    w.run(p_rec + timedelta(seconds=SETTLE + 0.2))
    check("the configuration-poll text moves again: charge_target OK with a number at the first telemetry poll after it "
          "plus the settle delay, BLOCKED until then", before == "BLOCKED" and w.attrs("charge_target").get("status") == "OK"
          and "charge_target" in w.numeric(), f"{before} {w.attrs('charge_target').get('status')}")
    w.close()

    w = World("recover_telemetry", mode="walk", offset=25.0, seed=6)
    w.run(START + timedelta(minutes=8))
    hist_only = [k for k in ("pv_tomorrow", "predicted_day_load") if H.numeric_state(h.state(k))]
    check("non-vacuity: before the freeze charge_target and the history-only items carry numbers",
          "charge_target" in w.numeric() and bool(hist_only), f"{w.numeric()}")
    t_freeze = h.now
    w.tel_frozen = True
    last_poll = w.polls[-1]
    n_obs, n_env = len(w.obs), len(w.envs)
    w.run_for(10 * 60)
    bound = VEN_Q.DQ_PROPOSED.liveness_max_age_s
    rows = w.starts(t_freeze)
    poll_runs = [r for r in rows if r[2] == "POLL" and r[0] > last_poll + timedelta(seconds=SETTLE + 1.0)]
    tick_runs = [r for r in rows if r[2] == "TICK"]
    obs = w.obs[n_obs:]
    stale = [t.isoformat() for t in w.stale_rows(t_freeze)]
    not_replaced = w.stale_not_replaced(t_freeze)
    uncovered = w.uncovered_numbers(t_freeze, h.now)
    late = [o for o in obs if o["t"] > last_poll + timedelta(seconds=bound + 60)]
    bad = [(o["t"].isoformat(), o["numeric"]) for o in late if set(o["numeric"]) & set(DONGLE_ITEMS)
           or not set(hist_only) <= set(o["numeric"])]
    disagree = [e.generated_at.isoformat() for e in w.envs[n_env:] if "CALLER_FRESHNESS_DISAGREES" in e.reason_codes
                or any("CALLER_FRESHNESS_DISAGREES" in v.reason_codes for v in tuple(e.items) + tuple(e.forecasts))]
    check("a frozen telemetry poll text: the poll-driven step stays idle and the tick resumes its present rules (refreshes "
          "started by the tick once polls stop arriving; polls_arriving off in the diagnostics)",
          not poll_runs and bool(tick_runs) and w.c.diagnostics()["cadence"]["polls_arriving"] is False,
          f"poll {poll_runs[:2]} tick {len(tick_runs)}")
    check("... the fail-closed result: past the liveness bound every item resting on a dongle input is withheld "
          "(charge_target BLOCKED INPUT_NOT_FRESH), the history-only items keep their numbers, no "
          "CALLER_FRESHNESS_DISAGREES; at most one STALE status row in the recorder, replaced at the same tick by the "
          "computed result (one STALE cycle, A32), and no number its inputs no longer cover",
          bool(late) and not bad and not disagree and len(stale) <= 1 and not not_replaced and not uncovered
          and w.attrs("charge_target").get("status") == "BLOCKED" and "INPUT_NOT_FRESH" in w.codes("charge_target"),
          f"{bad[:2]} {disagree[:2]} {stale[:2]} {not_replaced[:2]} {uncovered[:2]} {sorted(w.codes('charge_target'))[:4]}")
    w.tel_frozen = False
    w.run(w._next_tel + timedelta(seconds=0.1))  # noqa: SLF001 - the poll text moves again here
    p_rec = w.polls[-1]
    ls = w.c._last_start  # noqa: SLF001
    floor_free = ls is None or ls + timedelta(seconds=FLOOR) <= p_rec + timedelta(seconds=SETTLE)
    w.run(p_rec + timedelta(seconds=SETTLE + 0.2))
    check("the telemetry poll text moves again: charge_target OK with a number at that poll plus the settle delay",
          floor_free and w.attrs("charge_target").get("status") == "OK" and "charge_target" in w.numeric(),
          f"{floor_free} {w.attrs('charge_target').get('status')} {sorted(w.codes('charge_target'))[:4]}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [4] the settle delay: the refresh reads what the poll writes just after its text")
    # -----------------------------------------------------------------------------------------------------------------
    jobs = []
    orig_compute = ENGINE_LINK.compute

    def spy_compute(job, run_cycle=None):
        jobs.append((job.now, (job.states.get(SOC) or {}).get("state")))
        return orig_compute(job, run_cycle)
    ENGINE_LINK.compute = spy_compute
    try:
        w = World("settle", mode="walk", jitter=0.0, offset=25.0, seed=8)
        w.run(START + timedelta(minutes=7))
        want = {}

        def late_soc(world):
            p, val = h.now, str(50 + len(world.polls) % 40)
            want[p] = val
            h.at(p + timedelta(seconds=1.0), lambda: world.hass.states.seed(SOC, val, {"unit_of_measurement": "%"},
                                                                         changed_at=p + timedelta(seconds=1.0)))
        w.mutate = late_soc
        n0 = len(jobs)
        w.run_for(6 * 60)
        seen = [(t, s) for t, s in jobs[n0:] if t - timedelta(seconds=SETTLE) in want]
        check("each poll writes the SOC one second after its text: every poll-driven cycle (started the settle delay "
              "after its poll) read that poll's SOC, not the previous one",
              len(seen) >= 4 and all(s == want[t - timedelta(seconds=SETTLE)] for t, s in seen), str(seen[:4]))
        w.close()
    finally:
        ENGINE_LINK.compute = orig_compute

    # -----------------------------------------------------------------------------------------------------------------
    print("== [5] the 55 s floor: a poll inside it is deferred to the floor's end, never dropped")
    # -----------------------------------------------------------------------------------------------------------------
    base = START + timedelta(seconds=30)
    times = [base + timedelta(seconds=60 * k) for k in range(9)]
    p_a = times[-1]
    p_b = p_a + timedelta(seconds=50)
    times += [p_b] + [p_b + timedelta(seconds=60 * k) for k in range(1, 4)]
    w = World("floor", mode="list", poll_times=times, seed=9)
    w.run(p_b + timedelta(seconds=120))
    starts = [r for r in w.starts(p_a)]
    want_def = p_a + timedelta(seconds=SETTLE + FLOOR)
    check("a poll 50 s after the previous one: its refresh starts at the floor's end (the previous start plus 55 s), not "
          "at the poll plus the settle delay, and is not dropped",
          [r[0] for r in starts[:2]] == [p_a + timedelta(seconds=SETTLE), want_def] and starts[1][2] == "POLL"
          and w.c.counters["poll_steps_deferred_floor"] >= 1 and abs(starts[1][3] - (want_def - p_b).total_seconds()) < 1e-6,
          f"{[(r[0].isoformat(), r[2], r[3]) for r in starts[:3]]}")
    check("... and its result shows no INPUT_EXPIRING (the poll it serves is 8 s old)",
          not any("INPUT_EXPIRING" in cs for o in w.obs if o["t"] >= p_a for cs in o["pub_codes"].values()))
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [6] A36: the exception retry the tick asks for inside a poll's settle delay is held to that delay's end")
    # -----------------------------------------------------------------------------------------------------------------
    calls = []
    jobs6 = []
    s0 = START
    times = [s0 + timedelta(seconds=30 + 60 * k) for k in range(10)]        # ... s0+570
    p6 = s0 + timedelta(seconds=659)                                         # 1 s before the tick at s0+660
    times += [p6] + [s0 + timedelta(seconds=719 + 60 * k) for k in range(3)]
    late6 = LateSoc(1.5)                                                     # that poll's SOC lands at s0+660.5
    ENGINE_LINK.compute = spy_jobs(jobs6)
    try:
        w = World("covered", mode="list", poll_times=times, seed=10,
                  inject=scripted(lambda n: {"error": RuntimeError("synthetic refresh failure")} if n == 2 else {}, calls))
        w.mutate = late6
        w.run(s0 + timedelta(seconds=800))
    finally:
        ENGINE_LINK.compute = ORIG_COMPUTE
    rows = w.starts(s0)
    fail_at = s0 + timedelta(seconds=333)
    tick6 = s0 + timedelta(seconds=660)
    held6 = p6 + timedelta(seconds=SETTLE)
    retry = [r for r in rows if r[0] == held6]
    job6 = next((j for j in jobs6 if j[0] == held6), None)
    between = [r for r in rows if tick6 <= r[0] < held6]
    after = [r for r in rows if held6 < r[0] < s0 + timedelta(seconds=722)]
    check("a refresh at a poll-driven step raises (RUNTIME_EXCEPTION); the retry 300 s later, which the tick asks for 1 s "
          "after a poll, is held to that poll's settle delay's end (no cycle at the tick) and started there by the "
          "poll-driven step (poll_age_s 3); it reads that poll's SOC, written 1.5 s after its text, with that poll's "
          "liveness time; no second cycle for that poll (none until the next poll's step)",
          any(r[0] == fail_at and r[4] == "exception" for r in rows) and len(retry) == 1 and retry[0][2] == "POLL"
          and retry[0][1] == "REFRESH" and abs(retry[0][3] - SETTLE) < 1e-6 and not between and not after
          and job6 is not None and job6[1] == late6.want.get(p6) and job6[2] == p6
          and w.c.counters["exception_retries"] == 1 and w.c.counters["settle_holds"] >= 1
          and any(r[0] == s0 + timedelta(seconds=722) and r[2] == "POLL" for r in rows),
          f"{[(r[0].isoformat()[11:21], r[2], r[3], r[4]) for r in rows]} job {job6 and (job6[1], job6[2])} want "
          f"{late6.want.get(p6)} holds {w.c.counters['settle_holds']}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [7] the second-run guard: a poll-driven step while a cycle is in flight waits for its end")
    # -----------------------------------------------------------------------------------------------------------------
    calls = []
    gate = threading.Event()
    times = [s0 + timedelta(seconds=30 + 60 * k) for k in range(12)]
    w = World("busy", mode="list", poll_times=times, seed=12, settle=0.3,
              inject=scripted(lambda n: {"block": gate} if n == 2 else {}, calls))
    h.at(s0 + timedelta(seconds=400), gate.set)
    w.run(s0 + timedelta(seconds=470))
    rows = w.starts(s0)
    check("a refresh in flight from 333 s (held until 400 s): the step of the poll at 390 s waits and starts at 400 s, when "
          "the cycle ended (not dropped, never two cycles at once)",
          any(r[0] == s0 + timedelta(seconds=333) for r in rows)
          and any(r[0] == s0 + timedelta(seconds=400) and r[2] == "POLL" for r in rows)
          and not any(s0 + timedelta(seconds=333) < r[0] < s0 + timedelta(seconds=400) for r in rows)
          and w.c.counters["poll_steps_waited_in_flight"] >= 1,
          f"{[(r[0].isoformat()[11:19], r[2], r[4]) for r in rows]}")
    w.close()

    # The waiting step keeps its due time when a newer poll arrives (A33), so the cycle in flight can end inside that
    # poll's settle delay. The resumed step must then still wait for it, and so read that poll's late entity writes.
    jobs7 = []
    gate7 = threading.Event()
    hold_at = START + timedelta(seconds=CONST.PROPOSED_STARTUP_GRACE_S)     # the first cycle: the tick, no poll seen yet
    polls7 = [START + timedelta(seconds=181 + 60 * k) for k in range(6)]
    p_wait, p_new = polls7[0], polls7[1]
    release = p_new + timedelta(seconds=0.5)                            # the cycle in flight ends 0.5 s after p_new
    soc_now = ["55", START - timedelta(hours=3)]                        # the SOC entity as the dongle last wrote it
    want7 = {}

    def spy_hold(job, run_cycle=None):
        jobs7.append((job.now, (job.states.get(SOC) or {}).get("state"), job.liveness_at))
        if job.now == hold_at:
            gate7.wait(60)
        return orig_compute(job, run_cycle)

    def soc_after_text(world):
        p, val = h.now, str(60 + len(world.polls))
        want7[p] = val
        # the poll text has moved, but this poll's SOC is written one second later: until then the entity holds the
        # previous poll's value
        world.hass.states.seed(SOC, soc_now[0], {"unit_of_measurement": "%"}, changed_at=soc_now[1])

        def write():
            soc_now[0], soc_now[1] = val, p + timedelta(seconds=1.0)
            world.hass.states.seed(SOC, val, {"unit_of_measurement": "%"}, changed_at=p + timedelta(seconds=1.0))
        h.at(p + timedelta(seconds=1.0), write)
    ENGINE_LINK.compute = spy_hold
    try:
        w = World("busy_settle", mode="list", poll_times=polls7, seed=24, settle=0.3)
        w.mutate = soc_after_text
        h.at(release, gate7.set)
        w.run(polls7[3] + timedelta(seconds=10))
    finally:
        gate7.set()
        ENGINE_LINK.compute = orig_compute
    rows = w.starts(START)
    resumed = next((j for j in jobs7 if j[0] > hold_at), None)
    row_r = next((r for r in rows if r[0] > hold_at), None)
    check("a slot cycle in flight from the grace's end (held until 0.5 s after the second poll it overlaps): the first "
          "poll's step waits; the second poll keeps that step (A33); when the cycle ends inside the second poll's settle "
          "delay the resumed step still starts the settle delay after that poll (poll_age_s 3), never at once, and "
          "reads that poll's SOC written one second after its text, with that poll's liveness time",
          any(j[0] == hold_at for j in jobs7) and resumed is not None and row_r is not None
          and resumed[0] == p_new + timedelta(seconds=SETTLE) and resumed[1] == want7.get(p_new)
          and resumed[2] == p_new and row_r[2] == "POLL" and abs(row_r[3] - SETTLE) < 1e-6
          and not any(hold_at < r[0] < release for r in rows)
          and w.c.counters["poll_steps_waited_in_flight"] >= 1 and w.c.counters["poll_steps_kept_earlier"] >= 1,
          f"{[(j[0].isoformat()[11:21], j[1], j[2] and j[2].isoformat()[11:19]) for j in jobs7[:3]]} want "
          f"{want7.get(p_new)} {[(r[0].isoformat()[11:21], r[2], r[3]) for r in rows[:3]]} "
          f"{w.c.counters['poll_steps_waited_in_flight']} {w.c.counters['poll_steps_kept_earlier']}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [8] the CPU guard, the time-budget bar, the refresh switch, the pause helper and a failed self-test")
    # -----------------------------------------------------------------------------------------------------------------
    early = datetime(2030, 1, 15, 20, 48, tzinfo=UTC)
    slot_at = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)

    w = World("switch_off", start=early, offset=25.0, jitter=0.0, seed=13)
    w.run(early + timedelta(minutes=6))
    w.c.refresh_enabled = False
    t0 = h.now
    w.run(slot_at + timedelta(minutes=3))
    rows = w.starts(t0)
    check("refresh switched off: no refresh while polls arrive; the 21:00 slot cycle still starts, at a poll-driven step",
          not [r for r in rows if r[1] == "REFRESH"] and [(r[1], r[2]) for r in rows] == [("SLOT", "POLL")]
          and rows[0][0] > slot_at, f"{[(r[0].isoformat()[11:19], r[1], r[2]) for r in rows]}")
    w.close()

    calls = []
    w = World("cpu_guard", start=early, offset=25.0, jitter=0.0, seed=14,
              inject=scripted(lambda n: {"burn": 0.2}, calls))
    w.c.cpu_budget_s = 0.5
    w.run(early + timedelta(minutes=10))
    t0 = h.now
    sup0 = w.c.counters["refresh_suppressed_cpu"]
    w.run(slot_at + timedelta(minutes=2))
    rows = w.starts(t0)
    check("over the CPU budget (lowered for the test): the poll-driven steps start no refresh (suppressed, counted); the "
          "slot cycle still starts at a poll-driven step",
          [(r[1], r[2]) for r in rows] == [("SLOT", "POLL")] and w.c.counters["refresh_suppressed_cpu"] > sup0
          and w.c.selftest.get("CPU_BUDGET").level == "WARN", f"{[(r[0].isoformat()[11:19], r[1], r[2]) for r in rows]}")
    w.close()

    calls = []
    slow = {"n": None}
    w = World("budget_bar", start=early, offset=25.0, jitter=0.0, seed=15,
              inject=scripted(lambda n: {"sleep": 1.5 if n == slow["n"] else 0.0}, calls))
    w.run(early + timedelta(minutes=6))
    w.c.time_budget_s = 0.3
    slow["n"] = len(calls)
    t0 = h.now
    w.run_for(70, settle=2.5)
    st1 = h.state("status").state
    time.sleep(1.6)
    h.settle(0.5)
    w.c.time_budget_s = 120
    w.run(slot_at + timedelta(minutes=3))
    rows = w.starts(t0)
    refresh_before_slot = [r for r in rows[1:] if r[0] < slot_at]
    check("a poll-driven refresh over the time budget: SELF_TEST_FAILED (CYCLE_TIME_BUDGET), no poll-driven refresh before "
          "the next slot; the slot cycle starts at a poll-driven step and the refreshes resume after it",
          st1 == "SELF_TEST_FAILED" and rows and rows[0][4] == "budget" and not refresh_before_slot
          and any(r[1] == "SLOT" and r[2] == "POLL" and r[0] > slot_at for r in rows)
          and any(r[1] == "REFRESH" and r[0] > slot_at for r in rows),
          f"{st1} {[(r[0].isoformat()[11:19], r[1], r[2], r[4]) for r in rows]}")
    w.close()

    calls = []
    w = World("pause", start=early, offset=25.0, jitter=0.0, seed=16, inject=scripted(lambda n: {}, calls))
    w.run(early + timedelta(minutes=6))
    pause = {"v": "on"}
    w.mutate = lambda world: world.hass.states.seed("input_boolean.ecco_intel_paused", pause["v"])
    w.hass.states.seed("input_boolean.ecco_intel_paused", "on")
    n0, r0 = len(calls), w.c.counters["runs_started"]
    w.run(slot_at + timedelta(minutes=3))                               # the 21:00 slot falls due while paused
    paused_ok = (h.state("status").state == "PAUSED" and len(calls) == n0 and w.c.counters["runs_started"] == r0
                 and w.c.counters["poll_steps_idle"] > 0)
    pause["v"] = "off"
    w.hass.states.seed("input_boolean.ecco_intel_paused", "off")
    t0 = h.now
    w.run_for(3 * 60)
    rows = w.starts(t0)
    check("pause on: the poll-driven steps start nothing, not even the slot cycle that falls due (PAUSED); pause off: the "
          "cycle that resumes is a slot cycle at the next poll-driven step (the tick held it), then poll-driven refreshes",
          paused_ok and rows and (rows[0][1], rows[0][2]) == ("SLOT", "POLL")
          and all(r[2] == "POLL" for r in rows), f"{paused_ok} {[(r[0].isoformat()[11:19], r[1], r[2]) for r in rows]}")
    w.close()

    calls = []
    w = World("selftest_failed", offset=25.0, jitter=0.0, seed=17, inject=scripted(lambda n: {}, calls))
    w.run(START + timedelta(minutes=6))
    w.c.selftest.record("TEST_GATE", "FAIL", "a synthetic failed gate (test only)")
    n0 = len(calls)
    idle0 = w.c.counters["poll_steps_idle"]
    w.run_for(4 * 60)
    check("a failed self-test: the poll-driven steps start nothing (SELF_TEST_FAILED stays published)",
          len(calls) == n0 and h.state("status").state == "SELF_TEST_FAILED" and w.c.counters["poll_steps_idle"] > idle0,
          f"{len(calls) - n0} {h.state('status').state}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [9] the listener: what is a new poll; unload")
    # -----------------------------------------------------------------------------------------------------------------
    w = World("listener", offset=25.0, jitter=0.0, seed=18)
    w.run(START + timedelta(minutes=5) + timedelta(seconds=40))         # between two polls, no step pending
    check("exactly one state listener, on the entity mapped for the telemetry poll text",
          w.hass.states.change_listeners() == {TEL: 1}, str(w.hass.states.change_listeners()))
    seen0 = w.c.counters["polls_seen"]
    kept0 = w.c.counters["poll_steps_kept_earlier"]
    text = w.hass.states._states[TEL].state  # noqa: SLF001
    for st_, attrs in (("unavailable", None), (text, None), ("unknown", None), (text, {"note": "attribute only"}),
                       ("Waiting", None), (text, None)):
        w.hass.states.seed(TEL, st_, attrs)
    pending = [t for t in w.hass.later if t["active"]]
    check("unavailable, unknown, 'Waiting', the same text replayed and an attribute-only change are no new poll (no step "
          "scheduled)", w.c.counters["polls_seen"] == seen0 and not pending and w.c._poll_due is None,  # noqa: SLF001
          f"{w.c.counters['polls_seen'] - seen0} {len(pending)}")
    w.hass.states.seed(TEL, H.poll_time_text(h.now), changed_at=h.now)
    t1 = h.now
    first = [t["due"] for t in w.hass.later if t["active"]]
    h.set_now(h.now + timedelta(seconds=1))                             # before that step is due
    w.hass.states.seed(TEL, H.poll_time_text(h.now), changed_at=h.now)
    pending = [t for t in w.hass.later if t["active"]]
    check("a new text schedules one step the settle delay later; a second new text 1 s later never moves it later (it "
          "keeps the earliest due time, A33 RT-2; never two pending)",
          first == [t1 + timedelta(seconds=SETTLE)] and w.c.counters["polls_seen"] == seen0 + 2 and len(pending) == 1
          and pending[0]["due"] == t1 + timedelta(seconds=SETTLE) and w.c._poll_due == pending[0]["due"]  # noqa: SLF001
          and w.c.counters["poll_steps_kept_earlier"] == kept0 + 1,
          f"{first} {w.c.counters['polls_seen'] - seen0} {[p['due'].isoformat() for p in pending]}")
    n_runs = w.c.counters["runs_started"]
    h.unload(w.entry)
    left_armed = [t["due"].isoformat() for t in w.hass.later if t["active"]]
    w.run_for(120)
    check("unload removes the listener and cancels the pending step at once (no timer left armed); nothing runs "
          "afterwards", w.hass.states.change_listeners() == {} and not left_armed
          and not any(t["active"] for t in w.hass.later) and w.c.counters["runs_started"] == n_runs,
          f"{w.hass.states.change_listeners()} {left_armed} {w.c.counters['runs_started'] - n_runs}")
    w.close(unload=False)

    # -----------------------------------------------------------------------------------------------------------------
    print("== [10] the poll-driven threshold (the margin plus one poll) and the tick's exception to its hold")
    # -----------------------------------------------------------------------------------------------------------------
    calls = []
    t_star = s0 + timedelta(seconds=600)                                # a tick
    p0 = t_star - timedelta(seconds=125)
    times = [p0 - timedelta(seconds=60 * k) for k in range(7, 0, -1)] + [p0, p0 + timedelta(seconds=60),
                                                                         p0 + timedelta(seconds=126)]
    times += [times[-1] + timedelta(seconds=60 * k) for k in range(1, 3)]
    w = World("threshold", mode="list", poll_times=times, seed=19, inject=scripted(lambda n: {"valid_s": 186.0}, calls))
    w.run(times[-1] + timedelta(seconds=10))
    rows = w.starts(p0)
    stale = [o["t"].isoformat() for o in w.obs if o["t"] >= p0 and o["status"] == "STALE"]
    envs = [e for e in w.envs if e.generated_at >= p0]
    early_starts = [(a.generated_at.isoformat(), a.next_run_at.isoformat()) for a, b_ in zip(envs, envs[1:])
                    if b_.generated_at < a.next_run_at]
    check("results valid 186 s: each poll-driven step refreshes while less than the margin plus one poll is left (126 s at "
          "the second step), so a late third poll (66 s) leaves no STALE at the tick in between; next_run_at is never "
          "after the next cycle's start",
          [r[0] for r in rows[:3]] == [p + timedelta(seconds=SETTLE) for p in times[7:10]] and not stale
          and not early_starts, f"{[(r[0].isoformat()[11:19], r[2]) for r in rows[:4]]} {stale[:2]} {early_starts[:2]}")
    w.close()

    w = World("hold_rule", offset=25.0, jitter=0.0, seed=20, inject=scripted(lambda n: {"valid_s": 900.0}, []))
    w.run(START + timedelta(minutes=6) + timedelta(seconds=36))      # 11 s after a poll, its step done, none pending
    c_ = w.c
    now_ = h.now
    env0 = c_.envelope

    short, longer = (dataclasses.replace(env0, valid_until=now_ + timedelta(seconds=sec)) for sec in (100.0, 130.0))
    arriving = c_._polls_arriving(now_)  # noqa: SLF001
    no_pending = c_._poll_due is None  # noqa: SLF001
    rule = (c_._stale_before_poll(short, now_), c_._stale_before_poll(longer, now_))  # noqa: SLF001
    c_._poll_due = now_ + timedelta(seconds=SETTLE)  # noqa: SLF001 - as if a poll had just been seen
    rule_pending = c_._stale_before_poll(short, now_)  # noqa: SLF001
    c_._poll_due = None  # noqa: SLF001
    check("the tick's exception to its hold: with polls arriving and no step pending (the next one expected only 93 s after "
          "the last poll, after the next tick), an envelope that would go STALE at the next tick (valid 100 s) is "
          "refreshed by the tick, one valid 130 s is not; with a step pending before the next tick it is held",
          arriving and no_pending and rule == (True, False) and rule_pending is False, f"{arriving} {no_pending} {rule} "
          f"{rule_pending}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [11] missed, late and frozen telemetry polls (A32): at most one STALE cycle per episode, never a wrong "
          "number, then the fallback or recovery at the next poll plus the settle delay")
    # -----------------------------------------------------------------------------------------------------------------
    PHASES = (2.0, 10.0, 20.0, 30.0, 40.0, 50.0, 58.0)
    EPISODES = ((90.0, "one poll 90 s after the previous"), (120.0, "one skipped poll (120 s)"), (150.0, "a 150 s gap"),
                (480.0, "a freeze (no poll for 480 s)"))
    seen_stale, seen_in_obs, seen_held = 0, 0, 0
    # A31(b), the polls-stop half of the exposure (section 13.4): the documented bound is the first tick after the last
    # poll plus PROPOSED_POLL_ACTIVE_S (the tick holds its refresh while that poll still counts as arriving), at most
    # PROPOSED_POLL_ACTIVE_S + TICK_S = 150 s after the last poll
    ACTIVE_S = CONST.PROPOSED_POLL_ACTIVE_S
    held_bound_s = ACTIVE_S + CONST.TICK_S
    freeze_exposure, freeze_first = {}, {}
    for gap, what in EPISODES:
        per_phase, problems = {}, []
        for j, off in enumerate(PHASES):
            base = START + timedelta(seconds=off)
            times = [base + timedelta(seconds=60 * k) for k in range(12)]
            p_last = times[-1]                                          # the last poll on time
            late = p_last + timedelta(seconds=gap)                      # the next poll
            times += [late] + [late + timedelta(seconds=60 * k) for k in range(1, 4)]
            w = World(f"missed_{int(gap)}_{j}", mode="list", poll_times=times, seed=40 + j)
            w.run(p_last - timedelta(seconds=1))
            if not {"charge_target", "predicted_morning_soc"} <= set(w.numeric()):
                problems.append((off, "non-vacuity: charge_target / predicted_morning_soc without a number before", w.numeric()))
            n_obs = len(w.obs)
            if gap > LIVENESS_BOUND_S + CONST.TICK_S:                   # the freeze: the fallback just before it ends
                w.run(late - timedelta(seconds=0.5))
                # A31(b): every item resting on a dongle input that held a number after the last poll's compute loses it
                # no later than the first tick after the last poll plus PROPOSED_POLL_ACTIVE_S (recorder rows)
                computed = p_last + timedelta(seconds=SETTLE)
                held = [k for k in COVERED_ITEMS if num_text((w.rows(k, None, computed) or [(None, None, {})])[-1][1])]
                lost_after = {}
                for k in held:
                    after_c = w.rows(k, computed + timedelta(microseconds=1))
                    t_lost = next((t for t, s_, _a in after_c if not num_text(s_)), None)
                    lost_after[k] = None if t_lost is None else round((t_lost - p_last).total_seconds(), 3)
                freeze_exposure[off] = lost_after
                # ... and the first compute after it (the supervision heartbeat and the polls stopped together: no poll
                # reports the heartbeat again) BLOCKs export and Dump SUPERVISION_NOT_STABLE
                first_c = next((e for e in w.envs if e.generated_at > computed), None)
                hb_last = w.hass.states._states[HEARTBEAT].last_reported  # noqa: SLF001
                freeze_first[off] = None if first_c is None else dict(
                    {"after_s": round((first_c.generated_at - p_last).total_seconds(), 3),
                     "heartbeat_stopped": hb_last <= p_last},
                    **{v.key: [str(v.status), any(c_ == "SUPERVISION_NOT_STABLE" for c_, _t in v.blockers)]
                       for v in first_c.items if v.key in ("export_event", "dump_to_grid")})
                fb = {"numbers resting on a dongle input": sorted(set(w.numeric()) & set(COVERED_ITEMS)),
                      "history-only items without a number": sorted(set(HISTORY_ONLY) - set(w.numeric())),
                      "charge_target": (w.attrs("charge_target").get("status"), "INPUT_NOT_FRESH" in w.codes("charge_target")),
                      "polls_arriving": w.c.diagnostics()["cadence"]["polls_arriving"],
                      "tick cycles": sum(1 for r in w.starts(p_last + timedelta(seconds=SETTLE + 1)) if r[2] == "TICK")}
                if (fb["numbers resting on a dongle input"] or fb["history-only items without a number"]
                        or fb["charge_target"] != ("BLOCKED", True) or fb["polls_arriving"] or not fb["tick cycles"]):
                    problems.append((off, "fallback", fb))
            end = times[-1] + timedelta(seconds=30)
            w.run(end)
            stale = w.stale_rows(p_last, end)
            seen_stale += len(stale)
            seen_in_obs += sum(1 for o in w.obs[n_obs:] if o["status"] == "STALE")
            seen_held += w.stale_held(p_last, end)
            if len(stale) > 1:
                problems.append((off, "more than one STALE status row", [t.isoformat()[11:19] for t in stale]))
            nr = w.stale_not_replaced(p_last, end)
            if nr:
                problems.append((off, "a STALE not replaced by a computed status at the same tick or at the end of the "
                                 "settle hold (A36)", nr))
            unc = w.uncovered_numbers(p_last, end)
            if unc:
                problems.append((off, "a number its inputs no longer cover", unc[:3]))
            starts = w.starts()
            prev = max((r[0] for r in starts if r[0] < late), default=None)
            s1 = min((r[0] for r in starts if r[0] >= late), default=None)
            due = late + timedelta(seconds=SETTLE)
            if prev is not None:
                due = max(due, prev + timedelta(seconds=FLOOR))
            if s1 is None or s1 > due or s1 > late + timedelta(seconds=FLOOR):
                problems.append((off, "recovery late", s1 and s1.isoformat()[11:19], due.isoformat()[11:19]))
            else:
                last_at = {k: (w.rows(k, s1, s1) or [(None, None, {})])[-1][1] for k in ("status",) + COVERED_ITEMS}
                lost = [k for k in COVERED_ITEMS if k in ("charge_target", "predicted_morning_soc") and not num_text(last_at[k])]
                later = s1 + timedelta(microseconds=1)                  # rows after the recovery cycle's own writes
                after = [t.isoformat()[11:19] for t in w.stale_rows(later, end)]
                blank = [t.isoformat()[11:19] for t, s, _a in w.rows("charge_target", later, end) if not num_text(s)]
                if last_at["status"] in C.SystemStatus.NULL or lost or after or blank:
                    problems.append((off, "not recovered", last_at["status"], lost, after, blank[:3]))
            per_phase[off] = (len(stale), s1 and round((s1 - late).total_seconds(), 3))
            w.close()
        print(f"  {what}: per phase offset (STALE status rows, recovery after the next poll in s): "
              + json.dumps({str(k): v for k, v in per_phase.items()}))
        check(f"{what}, at {len(PHASES)} phase offsets: at most one STALE status row in the recorder, replaced by a "
              "computed status at the same tick or, inside a poll's settle delay, at that delay's end (A36; one STALE "
              "cycle); no number its last telemetry poll no longer covers"
              + ("; meanwhile the fallback (dongle items BLOCKED INPUT_NOT_FRESH, history-only items keep their numbers, "
                 "the tick's own rules)" if gap > LIVENESS_BOUND_S else "")
              + "; then recovery at the next poll plus the settle delay (the floor's end when the tick's refresh started "
              "within 55 s before it): charge_target and predicted_morning_soc carry their numbers, no STALE afterwards",
              not problems, str(problems[:3]))
    print(f"  STALE status rows {seen_stale}, of them replaced at the end of an A36 settle hold {seen_held}; STALE seen by "
          f"an observation after a cycle {seen_in_obs}")
    check(f"non-vacuity of the recorder count: it sees the one-cycle STALE writes of the missed-poll episodes that the "
          f"same tick replaces ({seen_stale - seen_held}), which an observation after each cycle never shows (only a STALE "
          f"held to a settle delay's end can be observed: {seen_in_obs} observations, {seen_held} such rows)",
          seen_stale - seen_held > 0 and (seen_in_obs == 0 or seen_held > 0), f"{seen_stale} {seen_held} {seen_in_obs}")
    worst = {str(k): max((v for v in d.values() if v is not None), default=None) for k, d in freeze_exposure.items()}
    print("  the freeze, A31(b): latest loss of a dongle item's number after the last poll, per phase offset (s): "
          + json.dumps(worst))
    check(f"A31(b), the polls stop (section 13.4): at each of the {len(PHASES)} phase offsets every item resting on a "
          f"dongle input that held a number after the last poll's compute (Dump among them: non-vacuity) loses it no "
          f"later than the first tick after the last poll plus PROPOSED_POLL_ACTIVE_S ({ACTIVE_S:g} s), at most "
          f"{held_bound_s:g} s after that poll: the documented worst-case exposure of an OK export or Dump item when "
          f"the polls stop",
          ACTIVE_S == 90.0 and held_bound_s == 150.0 and sorted(freeze_exposure) == sorted(PHASES)
          and all("dump_to_grid" in d and all(v is not None and 0 < v <= held_bound_s for v in d.values())
                  for d in freeze_exposure.values()),
          json.dumps({str(k): d for k, d in freeze_exposure.items()})[:600])
    print("  the freeze, A31(b): the first compute after the last poll's compute, per phase offset: "
          + json.dumps({str(k): v for k, v in freeze_first.items()}))
    check(f"A31(b), the polls and the supervision heartbeat stop together: at each of the {len(PHASES)} phase offsets the "
          f"first compute after the last poll's compute comes more than PROPOSED_POLL_ACTIVE_S and at most "
          f"{held_bound_s:g} s after that poll and BLOCKs export and Dump SUPERVISION_NOT_STABLE (the heartbeat's last "
          f"report is that poll's)",
          sorted(freeze_first) == sorted(PHASES)
          and all(v is not None and v["heartbeat_stopped"] and ACTIVE_S < v["after_s"] <= held_bound_s
                  and all(v.get(k) == ["BLOCKED", True] for k in ("export_event", "dump_to_grid"))
                  for v in freeze_first.values()),
          json.dumps({str(k): v for k, v in freeze_first.items()})[:600])

    # -----------------------------------------------------------------------------------------------------------------
    print("== [12] A31(b): the supervision heartbeat stops while the telemetry polls continue")
    # -----------------------------------------------------------------------------------------------------------------
    hb_bound = VEN_Q.DQ_PROPOSED.supervision_max_heartbeat_age_s
    sup_bound = VEN_Q.DQ_PROPOSED.supervision_reading_max_age_s
    w = World("supervision", offset=25.0, jitter=0.0, seed=21)
    w.run(START + timedelta(minutes=8))
    hb0 = w.hass.states._states[HEARTBEAT]  # noqa: SLF001
    hb_value = float(hb0.state)
    x_stop = h.now + timedelta(seconds=20)                              # its last report, between two polls (at :25)
    lapse = x_stop + timedelta(seconds=hb_bound - hb_value)             # reported age + the reading's own age > 90 s

    def heartbeat_stopped(world=None):
        w.hass.states.seed(HEARTBEAT, hb0.state, dict(hb0.attributes), changed_at=x_stop - timedelta(seconds=10),
                           reported_at=x_stop)
    h.at(x_stop, heartbeat_stopped)
    w.mutate = heartbeat_stopped                                        # every later poll leaves the heartbeat frozen
    w.run(lapse + timedelta(seconds=3 * 60))

    def item_of(e, key):
        return {v.key: v for v in tuple(e.items) + tuple(e.forecasts)}[key]

    def sup_blocked(e, key):
        v = item_of(e, key)
        return v.status == "BLOCKED" and any(c_ == "SUPERVISION_NOT_STABLE" for c_, _t in v.blockers)
    envs = [e for e in w.envs if e.generated_at >= x_stop]
    before = [e for e in envs if e.generated_at <= lapse]
    after = [e for e in envs if e.generated_at > lapse]
    trig = {r[0]: r[2] for r in w.starts(x_stop)}
    check(f"the supervision bounds are {hb_bound:g} s (the heartbeat's reported age plus its reading's own age; the state "
          f"and stable flag aged by the telemetry poll, {sup_bound:g} s), so the heartbeat last reported at x lapses at "
          f"x + {hb_bound - hb_value:g} s (its reported {hb_value:g} s)",
          hb_bound == 90.0 and sup_bound == 90.0 and (lapse - x_stop).total_seconds() == hb_bound - hb_value == 78.0,
          f"{hb_bound} {sup_bound} {hb_value}")
    d0 = item_of(before[-1], "dump_to_grid") if before else None
    check("every poll-driven compute before the lapse keeps export and Dump free of SUPERVISION_NOT_STABLE; the last one "
          "gives Dump OK with a number valid past the first compute after the lapse (supervision is not in the item "
          "validity, by design: A31(b))",
          len(before) >= 2 and all(trig.get(e.generated_at) == "POLL" for e in before)
          and not any(sup_blocked(e, k) for e in before for k in ("export_event", "dump_to_grid"))
          and d0.status == "OK" and d0.value is not None and after and d0.valid_until > after[0].generated_at,
          f"{[(e.generated_at.isoformat()[11:19], item_of(e, 'dump_to_grid').status) for e in before]}")
    first_after = after[0] if after else None
    exposure = None if first_after is None else (first_after.generated_at - lapse).total_seconds()
    dump_rows = w.rows("dump_to_grid", x_stop)
    num_after = [t.isoformat()[11:19] for t, s, _a in dump_rows if t > lapse and num_text(s)]
    blank_at = [t for t, s, _a in dump_rows if t > lapse and not num_text(s)]
    check("the first poll-driven compute after the lapse BLOCKs export and Dump SUPERVISION_NOT_STABLE, at most one poll "
          "plus the settle delay after the lapse (the worst-case exposure; the Dump entity loses its number then), and "
          "every later compute too; charge_target keeps its number, polls still arriving",
          first_after is not None and trig.get(first_after.generated_at) == "POLL"
          and all(sup_blocked(e, k) for e in after for k in ("export_event", "dump_to_grid"))
          and 0 < exposure <= CONST.PROPOSED_POLL_INTERVAL_S + SETTLE
          and blank_at and blank_at[0] == first_after.generated_at and not num_after
          and item_of(first_after, "charge_target").status == "OK" and "charge_target" in w.numeric()
          and w.c.diagnostics()["cadence"]["polls_arriving"] is True,
          f"{exposure} {[(e.generated_at.isoformat()[11:19], item_of(e, 'dump_to_grid').status) for e in after]} "
          f"{num_after[:2]}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [13] A33 (RT-2) and A36: a pending poll-driven step is never moved later; the settle hold is one-shot")
    # -----------------------------------------------------------------------------------------------------------------
    fast = [START + timedelta(seconds=1 + 2 * k) for k in range(12 * 30)]
    w = World("fast_text", mode="list", poll_times=fast, seed=22)
    w.run(START + timedelta(minutes=12))
    rows = w.starts(START)
    gaps = [(b_[0] - a_[0]).total_seconds() for a_, b_ in zip(rows, rows[1:])]
    grace_end = START + timedelta(seconds=CONST.PROPOSED_STARTUP_GRACE_S)
    held13 = (w.c.counters["settle_holds"], w.c.counters["settle_held_starts"], w.c.counters["settle_residual_starts"])
    check("a poll text moving every 2 s (faster than the 3 s settle delay): the first cycle starts within one poll plus "
          "the settle delay of the start-up grace's end, every later one at the 55 s floor's end plus at most the settle "
          "delay (the one-shot hold, never re-armed by the next poll), all poll-driven; every start is a held one and "
          "the documented residual (a second poll within one settle delay); the status is OK with charge_target's "
          "number (never STARTING forever: no starvation)",
          len(rows) >= 9 and grace_end <= rows[0][0] <= grace_end + timedelta(seconds=2 + SETTLE)
          and all(FLOOR - 1e-6 <= g <= FLOOR + SETTLE + 1e-6 for g in gaps) and all(r[2] == "POLL" for r in rows)
          and held13[1] == len(rows) and held13[2] == len(rows) and held13[0] >= len(rows)
          and h.state("status").state == "OK" and "charge_target" in w.numeric()
          and w.c.counters["poll_steps_kept_earlier"] > 100,
          f"{rows[:1]} {gaps[:4]} {held13} n={len(rows)} {h.state('status').state} "
          f"{w.c.counters['poll_steps_kept_earlier']}")
    w.close()

    times = [early + timedelta(seconds=25 + 60 * k) for k in range(12)]     # ... 20:59:25 (its refresh at 20:59:28)
    times += [slot_at - timedelta(seconds=10), slot_at + timedelta(seconds=10)]
    times += [slot_at + timedelta(seconds=70 + 60 * k) for k in range(2)]
    w = World("earliest", start=early, mode="list", poll_times=times, seed=23)
    w.run(slot_at + timedelta(minutes=3))
    rows = w.starts(slot_at - timedelta(seconds=40))
    check("... it moves earlier only: a step deferred to the floor's end (poll at 20:59:50, floor until 21:00:23) is moved "
          "to the next poll's step (21:00:13), so the 21:00 slot that fell due meanwhile starts there, not at the floor's "
          "end",
          [(r[0], r[1], r[2]) for r in rows[:2]] == [(slot_at - timedelta(seconds=32), "REFRESH", "POLL"),
                                                    (slot_at + timedelta(seconds=13), "SLOT", "POLL")]
          and not any(r[0] == slot_at + timedelta(seconds=23) for r in rows)
          and w.c.counters["poll_steps_deferred_floor"] >= 1,
          f"{[(r[0].isoformat()[11:19], r[1], r[2]) for r in rows[:4]]}")
    w.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [14] A36: no cycle starts inside the settle delay of the newest poll seen")
    # -----------------------------------------------------------------------------------------------------------------
    # (a) a step deferred to the floor's end, with a newer poll 1 s before that end (two polls within about 55 s)
    jobs14 = []
    base = START + timedelta(seconds=30)
    times = [base + timedelta(seconds=60 * k) for k in range(9)]           # ... START+510
    p_a = times[-1]
    p_b = p_a + timedelta(seconds=50)                                       # its step falls inside the floor
    floor_end = p_a + timedelta(seconds=SETTLE + FLOOR)                     # the refresh at p_a + 3, plus 55 s
    p_c = floor_end - timedelta(seconds=1)
    times += [p_b, p_c] + [p_c + timedelta(seconds=60 * k) for k in range(1, 3)]
    late14 = LateSoc(2.0)                                                   # p_c's SOC lands 1 s after the floor's end
    ENGINE_LINK.compute = spy_jobs(jobs14)
    try:
        w = World("settle_floor", mode="list", poll_times=times, seed=27)
        w.mutate = late14
        w.run(p_c + timedelta(seconds=90))
    finally:
        ENGINE_LINK.compute = ORIG_COMPUTE
    rows = w.starts(p_a)
    held_at = p_c + timedelta(seconds=SETTLE)
    job = next((j for j in jobs14 if j[0] == held_at), None)
    check("a step deferred to the floor's end (a poll 50 s after the previous one) with a newer poll 1 s before that end "
          "(the newer poll keeps the step, A33): no cycle at the floor's end; the step is held once to the newer poll's "
          "settle delay's end (POLL, poll_age_s 3) and reads that poll's SOC, written 2 s after its text, with that "
          "poll's liveness time",
          [r[0] for r in rows[:2]] == [p_a + timedelta(seconds=SETTLE), held_at] and rows[1][2] == "POLL"
          and abs(rows[1][3] - SETTLE) < 1e-6 and job is not None and job[1] == late14.want.get(p_c) and job[2] == p_c
          and w.c.counters["poll_steps_deferred_floor"] >= 1 and w.c.counters["poll_steps_kept_earlier"] >= 1
          and w.c.counters["settle_held_starts"] >= 1,
          f"{[(r[0].isoformat()[11:21], r[2], r[3]) for r in rows[:3]]} job {job and (job[1], job[2])} want "
          f"{late14.want.get(p_c)} {w.c.counters['settle_held_starts']}")
    w.close()

    # (b) one skipped poll whose late poll comes 0.5 s before a tick at which the result goes STALE
    jobs14b = []
    base = START + timedelta(seconds=59.5)
    times = [base + timedelta(seconds=60 * k) for k in range(10)]          # ... START+599.5
    p_last = times[-1]
    p_late = p_last + timedelta(seconds=120)                                # START+719.5, the tick at START+720
    times += [p_late] + [p_late + timedelta(seconds=60 * k) for k in range(1, 3)]
    late14b = LateSoc(1.0)
    ENGINE_LINK.compute = spy_jobs(jobs14b)
    try:
        w = World("settle_stale", mode="list", poll_times=times, seed=28)
        w.mutate = late14b
        w.run(p_late + timedelta(seconds=90))
    finally:
        ENGINE_LINK.compute = ORIG_COMPUTE
    tick_b = START + timedelta(seconds=720)
    held_b = p_late + timedelta(seconds=SETTLE)
    rows = w.starts(p_last)
    status = [(t, s) for t, s, _a in w.rows("status", p_last)]
    after_stale = next((x for i, x in enumerate(status) if i > 0 and status[i - 1] == (tick_b, "STALE")), None)
    job = next((j for j in jobs14b if j[0] == held_b), None)
    check("one skipped poll, the late poll 0.5 s before a tick: that tick writes STALE and asks for a refresh, which is "
          "held to the poll's settle delay's end (no cycle at the tick) and started there (REFRESH, POLL, poll_age_s 3); "
          "it reads that poll's SOC, written 1 s after its text, with that poll's liveness time; the one STALE row is "
          "replaced by that computed status at the delay's end (A32's one STALE cycle)",
          w.stale_rows(p_last) == [tick_b] and after_stale is not None and after_stale[0] == held_b
          and after_stale[1] not in C.SystemStatus.NULL and not w.stale_not_replaced(p_last)
          and not any(tick_b <= r[0] < held_b for r in rows)
          and any(r[0] == held_b and r[1] == "REFRESH" and r[2] == "POLL" and abs(r[3] - SETTLE) < 1e-6 for r in rows)
          and job is not None and job[1] == late14b.want.get(p_late) and job[2] == p_late
          and w.c.counters["settle_holds"] >= 1,
          f"stale {[t.isoformat()[11:21] for t in w.stale_rows(p_last)]} next {after_stale} "
          f"{[(r[0].isoformat()[11:21], r[1], r[2], r[3]) for r in rows[:3]]} job {job and (job[1], job[2])} want "
          f"{late14b.want.get(p_late)} holds {w.c.counters['settle_holds']}")
    w.close()
finally:
    h.loop.close()
    H.rmtree_own(root, PREFIX)

check("the temporary directory is removed", not root.exists(), str(root))
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the poll-phase suite (A23):")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all poll-phase (A23) checks passed")
