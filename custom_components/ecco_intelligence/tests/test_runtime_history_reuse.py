#!/usr/bin/env python3
"""A50: the parsed history reused between cycles (runtime/engine_link.HistoryReuse, runtime/history_source.StatisticsImage).

  [1] the image of a read: rows_from_statistics' rows as tuples, the row cap's cut and the position of every negative
      zero; it holds only immutable values (a frozen dataclass of tuples); its content is equal for two reads exactly when
      their rows are bit for bit the same: a value whose zero changed sign has rows that compare equal (==) and a content
      that does not; another value, a None, the cut each differ; row_dicts() gives rows_from_statistics' rows back;
  [2] history_source.build is build_full, then truncate at `now`; truncate cuts at every `now` exactly as a fresh build
      does (an in-progress and a future hour included), each time into a new container of the same records;
  [3] differential (the real run_cycle through engine_link.compute, owner-record decisions and every decision OPEN): over
      cycles 20 minutes apart that cross hours without a read (statistics that run past `now`), a refused read, a re-read
      of the same content, a changed read, an in-place change of the raw read handed again, a zero whose sign changed and
      a configuration change, the cycles with a HistoryReuse (the image handed back after a read, as the coordinator
      does; with and without the coordinator's drop at a read) give byte-identical envelopes, the same History (records,
      values, flags and order) and the same diagnostics as cycles that parse and build every time; the reuse happens
      (non-vacuity), a changed or refused read always rebuilds, a refused read gives no history and keeps nothing;
      EngineJob.statistics is annotated with the image, and an image handed in without a HistoryReuse gives no history,
      exactly as a refused read (RUN-4);
  [4] no mutation: the History kept between cycles is fingerprinted (every record's values bit for bit, flags, sources,
      order and identity) before and after every cycle of [3], the scorecard step (store.record_cycle) included: never
      changed; the kept History itself never leaves the holder (each cycle gets its own container); the PV forecast series
      reach run_cycle as new dicts every cycle, so a cycle that changes them changes nothing kept; prepare_history (the one
      engine function that edits records) changes only its own deep copy; a cycle that writes into a shared record is
      caught by the fingerprint (non-vacuity);
  [5] the audit, pinned: every write to an hour record or a History index in the engine, ecco_core and the runtime
      (assignments, deletions, augmented assignments, setattr, the record's flag(), and mutating calls on e / flags /
      sources / by_start) is inside build_history (records it creates), HourRecord.flag, History.__init__ (its own new
      index) or quality._prepare (after its deepcopy), or in the offline-only modules (faults, synthetic, replay), which
      the runtime's import closure never reaches;
  [6] the A50 text: INTELLIGENCE_HA_RUNTIME's 'The parsed history (A50)' paragraph and engine_link's module docstring
      give the measured share (about 0.08 s of every cycle, about a third of a refresh; REV-E-4), name no workstation
      (RUN-5), and the paragraph is wrapped at 120 columns.
Plain script, offline; exits 1 on any failure. Only generic test_* ids and fictional 2030 values are used.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(1, str(Path(__file__).resolve().parent))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


from custom_components.ecco_intelligence.runtime import engine_link, history_source, sources  # noqa: E402
from custom_components.ecco_intelligence.runtime import store as rstore  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.advisory_contract import SiteFacts, Versions  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History, HourRecord  # noqa: E402
from intelligence.quality import prepare_history  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402

UTC = timezone.utc
REPO = H.REPO
T0 = datetime(2030, 1, 15, 17, 5, tzinfo=UTC)
FORECAST_ID = "sensor.test_solar_forecast_today"
SCALARS = ("soc_mean", "soc_min", "soc_max", "pv_w_mean", "load_w_mean", "batt_w_mean", "grid_w_mean")


def _v(v: object) -> str:
    return v.hex() if isinstance(v, float) else repr(v)


def fp_record(r: HourRecord) -> tuple:
    """Every field of a record, floats bit for bit (float.hex tells -0.0 from 0.0), each flag set's type and members."""
    return (r.start, tuple(sorted((k, _v(x)) for k, x in r.e.items())), tuple(_v(getattr(r, a)) for a in SCALARS),
            tuple(sorted((k, type(s).__name__, tuple(sorted(s))) for k, s in r.flags.items())),
            tuple(sorted(r.sources.items())))


def fp_history(h: History | None, identity: bool = False) -> tuple | None:
    if h is None:
        return None
    out = (tuple(h.by_start), tuple(fp_record(r) for r in h.by_start.values()))
    return out + (tuple(id(r) for r in h.by_start.values()),) if identity else out


def statistics(until: datetime, *, gap: tuple[int, int] | None = None) -> dict:
    """30 days of the harness's synthetic statistics ending at the last complete hour before `until`, plus the day-ahead
    PV forecast rows (the 06:00 UTC bucket of each day, fictional kWh) the site file's `forecasts` block names."""
    st = H.synthetic_statistics(until, days=30, gap=gap)
    end = until.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    rows = []
    t = end - timedelta(days=30)
    while t < end:
        if t.hour == 6:
            rows.append({"start": t.timestamp(), "mean": None, "min": None, "max": None,
                         "state": 2.0 + (t.day % 4) * 0.5, "sum": None})
        t += timedelta(hours=1)
    st[FORECAST_ID] = rows
    return st


class _States:
    def __init__(self) -> None:
        self._states: dict = {}

    def seed(self, entity_id, state, attributes=None, *, changed_at=None, reported_at=None):
        a = dict(attributes or {})
        ch = changed_at
        self._states[entity_id] = {"state": state, "attributes": a, "last_changed": ch, "last_updated": ch,
                                   "last_reported": reported_at or ch}


def states_at(now: datetime) -> dict:
    s = _States()
    H.seed_fresh_states(s, now)
    for v in s._states.values():
        for k in ("last_changed", "last_updated", "last_reported"):
            if v[k] is None:
                v[k] = now - timedelta(hours=1)
    return dict(s._states)


PROFILE_OWNER = H.site_profile(decisions=H.owner_decisions())
PROFILE_OPEN = H.site_profile()
EMAP = sources.parse_entity_map(PROFILE_OWNER)
PLAN = history_source.plan_history(PROFILE_OWNER)
CFG = SiteConfig(pv_array_kwp=6.0)
FACTS = SiteFacts(6.0, 51.5, -0.1)
DEC_OWNER = sd.DecisionSet.from_mapping(H.owner_decisions(), source="site_local")
DEC_OPEN = sd.DecisionSet.from_mapping(H.all_open_decisions(), source="site_local")


def job_at(now: datetime, stats, reuse, *, decisions=DEC_OWNER, cfg=CFG) -> engine_link.EngineJob:
    return engine_link.EngineJob(now=now, states=states_at(now), entity_map=EMAP, liveness_at=now - timedelta(seconds=20),
                                 plan=PLAN, statistics=stats, base_cfg=cfg, site_facts=FACTS, decisions=decisions,
                                 outcome_metrics=None, paused=False, previous=None, versions=Versions(),
                                 config_liveness_at=now - timedelta(seconds=H.CONFIG_POLL_AGE_S), history_reuse=reuse)


def env_json(env) -> str:
    return json.dumps(env.to_dict(), sort_keys=True, default=str)


DIAG_SAME = ("history_rows", "history_rows_truncated", "history_hours", "history_newest_end", "skipped_statistic_ids",
             "source_notes", "source_notes_withheld", "site_readings", "signals", "signals_withheld")


def kept(reuse: engine_link.HistoryReuse) -> History | None:
    """The History the holder keeps (tests only: the holder never hands it out)."""
    entry = reuse._entry
    return None if entry is None else entry[1]


# ---------------------------------------------------------------------------------------------------------------------
print("== [1] the image of a read")
S1 = statistics(T0 + timedelta(hours=3))
rows1, tr1 = history_source.rows_from_statistics(S1)
img1 = history_source.image_from_rows(rows1, tr1)
img1b = history_source.image_from_rows(*history_source.rows_from_statistics(statistics(T0 + timedelta(hours=3))))
check("the image holds rows_from_statistics' rows as tuples in ROW_FIELDS order, its cut and no negative zero here; "
      "row_dicts() gives the rows back", img1.rows and all(type(r) is tuple and len(r) == 7 for r in img1.rows)
      and img1.row_dicts() == rows1 and img1.truncated is False and img1.negative_zeros == ()
      and history_source.ROW_FIELDS == ("statistic_id", "start_ts", "mean", "min", "max", "state", "sum"),
      f"{len(img1.rows)} {img1.truncated}")
check("the image is immutable: a frozen dataclass whose rows are tuples of str, int, float or None",
      dataclasses.is_dataclass(img1) and type(img1).__dataclass_params__.frozen
      and all(type(x) in (str, int, float, type(None)) for r in img1.rows for x in r))
try:
    img1.rows = ()  # type: ignore[misc]
    check("... assigning to it raises", False, "assigned")
except dataclasses.FrozenInstanceError:
    check("... assigning to it raises", True)
check("two parses of the same content (new objects) have equal content", img1 is not img1b
      and img1.content() == img1b.content())
_zero_at = next(i for i, r in enumerate(rows1) if r["min"] == 0.0)
_neg = [dict(r) for r in rows1]
_neg[_zero_at]["min"] = -0.0
img_neg = history_source.image_from_rows(_neg, False)
check("a zero whose sign changed: the rows still compare equal (==), the content does not (its position is recorded)",
      img_neg.rows == img1.rows and img_neg.negative_zeros == ((_zero_at, 3),) and img_neg.content() != img1.content())
_val = [dict(r) for r in rows1]
_val[-1]["mean" if _val[-1]["mean"] is not None else "state"] = 1234.5
_none = [dict(r) for r in rows1]
_none[0]["max" if _none[0]["max"] is not None else "state"] = None
check("another value, a None in place of a value and the row cap's cut each give another content",
      history_source.image_from_rows(_val, False).content() != img1.content()
      and history_source.image_from_rows(_none, False).content() != img1.content()
      and history_source.image_from_rows(rows1, True).content() != img1.content())
_capped = history_source.image_from_rows(*history_source.rows_from_statistics(S1, cap=100))
check("a capped read's image keeps the newest rows and says it was cut", len(_capped.rows) == 100 and _capped.truncated)

# ---------------------------------------------------------------------------------------------------------------------
print("== [2] build = build_full, then truncate at now")
full1 = history_source.build_full(PLAN, rows1, CFG)
cuts = [T0, T0 + timedelta(minutes=55), T0 + timedelta(hours=1), T0 + timedelta(hours=2, minutes=59, seconds=59),
        T0 + timedelta(hours=5)]
_same = []
for now_ in cuts:
    fresh_h, fresh_ne = history_source.build(PLAN, rows1, CFG, now_)
    cut_h, cut_ne = history_source.truncate(full1, now_)
    _same.append(fp_history(fresh_h) == fp_history(cut_h) and fresh_ne == cut_ne and cut_h is not full1
                 and all(a is b for a, b in zip(cut_h.by_start.values(), (full1.by_start[s] for s in cut_h.by_start))))
check("at every cut (in the in-progress hour, on an hour, past the newest row) truncate gives exactly what a fresh build "
      "gives, in a new container of the kept records", all(_same), str(_same))
check("the statistics run past T0, so the cut matters (non-vacuity): the History grows across the cuts",
      len(history_source.truncate(full1, cuts[0])[0]) < len(history_source.truncate(full1, cuts[3])[0]))
check("no full History, or a cut before every record, gives (None, None)",
      history_source.truncate(None, T0) == (None, None)
      and history_source.truncate(full1, T0 - timedelta(days=40)) == (None, None))

# ---------------------------------------------------------------------------------------------------------------------
print("== [3] / [4] differential and no mutation (the real run_cycle)")
SEEN: dict = {}


def spy(inputs):
    SEEN["pvh"] = inputs.pv_forecast_history
    SEEN["history"] = inputs.history
    return run_cycle(inputs)


def mutating_spy(inputs):
    env = spy(inputs)
    if isinstance(inputs.pv_forecast_history, dict):
        for series in inputs.pv_forecast_history.values():
            series.clear()                                # a downstream change of its own PV forecast copy
        inputs.pv_forecast_history.clear()
    return env


STORE_ROOT = H.mktemp("ecco_intel_reuse_")
store = None
try:
    H.write_site(STORE_ROOT, PROFILE_OWNER)
    store = rstore.RuntimeStateStore(str(STORE_ROOT))
    ok_store, _t = store.try_open()
    check("the scratch state store opens (the scorecard step runs on the shared records)", ok_store, _t)

    def run_pair(now, raw, held, reuse, *, decisions=DEC_OWNER, cfg=CFG, slot=False, fn=spy):
        """One cycle with the holder (`held`: what the coordinator would hand it) and one fresh (raw, no holder). Returns
        (equal, detail, the reuse cycle's diag, the stats to hold next, pv dict id)."""
        before = fp_history(kept(reuse), identity=True)
        env_r, diag_r, hist_r = engine_link.compute(job_at(now, held, reuse, decisions=decisions, cfg=cfg), fn)
        pvh_r = SEEN.get("pvh")
        mid = fp_history(kept(reuse), identity=True)
        if slot and store is not None and hist_r is not None:
            store.record_cycle(env_r.scorecard_report, now.replace(minute=0, second=0, microsecond=0), now, hist_r, cfg)
        after = fp_history(kept(reuse), identity=True)
        img = reuse.take_image()
        env_f, diag_f, hist_f = engine_link.compute(job_at(now, raw, None, decisions=decisions, cfg=cfg), spy)
        same = (env_json(env_r) == env_json(env_f) and fp_history(hist_r) == fp_history(hist_f)
                and all(diag_r.get(k) == diag_f.get(k) for k in DIAG_SAME))
        # a cycle that reuses the kept History leaves it as it found it; the scorecard step leaves it as the cycle did
        unchanged = (before == mid or diag_r.get("history_reused") is not True) and mid == after
        detail = (f"{now.isoformat()} env {env_json(env_r) == env_json(env_f)} hist {fp_history(hist_r) == fp_history(hist_f)}"
                  f" diag {[k for k in DIAG_SAME if diag_r.get(k) != diag_f.get(k)]}")
        out_hist_is_kept = hist_r is not None and hist_r is kept(reuse)
        return same, unchanged, detail, diag_r, (img if img is not None else held), pvh_r, out_hist_is_kept, env_r

    # the coordinator's way: a read drops what is kept and hands the raw read; later cycles get the image back
    reuse = engine_link.HistoryReuse()
    S1_again = statistics(T0 + timedelta(hours=3))
    S2 = statistics(T0 + timedelta(hours=3), gap=(40, 30))
    schedule = {0: S1, 60: None, 80: S1_again, 120: S2}
    results, held, raw, pv_objs, kept_out, statuses = [], None, None, [], [], set()
    for minute in range(0, 180, 20):
        now = T0 + timedelta(minutes=minute)
        if minute in schedule:                        # a read (refused at +60 min)
            raw = schedule[minute]
            held = raw
            reuse.clear()
        same, unchanged, detail, diag, held, pvh, is_kept, env = run_pair(now, raw, held, reuse, slot=minute in schedule)
        results.append((minute, same, unchanged, detail, diag.get("history_parsed"), diag.get("history_reused"),
                        diag.get("history_hours")))
        pv_objs.append(pvh)                           # kept alive, so identities are never reused
        kept_out.append(is_kept)
        statuses.update(v.status for v in tuple(env.items) + tuple(env.forecasts))
    check("[3] coordinator order: every cycle (crossing three hours without a read, a refused read, a re-read of the same "
          "content, a changed read) gives the same envelope, History and diagnostics as a fresh parse and build",
          all(r[1] for r in results), str([r[3] for r in results if not r[1]][:3]))
    check("[3] non-vacuity: the learning path ran (an item OK) and the cycles between the reads reused the kept History",
          "OK" in {str(getattr(s, "value", s)) for s in statuses}
          and [r[0] for r in results if r[5]] == [20, 40, 100, 140, 160]
          and [r[0] for r in results if r[4]] == [0, 80, 120], str([(r[0], r[4], r[5]) for r in results]))
    check("[3] the refused read (+60 min): no history and nothing kept (the next read parses and builds again)",
          [r[6] for r in results if r[0] == 60] == [0] and reuse.parses == 3 and reuse.builds == 3,
          f"{[(r[0], r[6]) for r in results]} parses {reuse.parses} builds {reuse.builds}")
    check("[4] the kept History is never changed by a cycle that reuses it (the scorecard step at each read included)",
          all(r[2] for r in results), str([r[0] for r in results if not r[2]]))
    check("[4] the kept History itself never leaves the holder: every cycle gets its own container",
          not any(kept_out), str(kept_out))
    _pv = [p for p in pv_objs if p is not None]
    _inner = [s_ for p in _pv for s_ in p.values()]
    check("[4] the PV forecast series reach run_cycle as new dicts every cycle, outer and inner (non-vacuity: there are "
          "some, with values)", len(_pv) >= 7 and all(_inner)
          and all(a is not b for i, a in enumerate(_pv) for b in _pv[i + 1:])
          and all(a is not b for i, a in enumerate(_inner) for b in _inner[i + 1:]), f"{len(_pv)} {len(_inner)}")

    # the holder alone (no drop at a read): the content key decides
    reuse2 = engine_link.HistoryReuse()
    raw_inplace = statistics(T0 + timedelta(hours=3))
    plan2 = [(0, S1, "parse"), (20, "held", "reuse"), (40, S1_again, "reuse"), (60, S2, "build"),
             (80, raw_inplace, "build"), (100, raw_inplace, "reuse")]
    out2, held2 = [], None
    for minute, src, expect in plan2:
        now = T0 + timedelta(minutes=minute)
        if src == "held":
            raw2, hold = S1, held2
        else:
            raw2, hold = src, src
        b0, r0 = reuse2.builds, reuse2.reuses
        same, unchanged, detail, diag, held2, _p, _k, _e = run_pair(now, raw2, hold, reuse2)
        got = "reuse" if reuse2.reuses > r0 else "build" if reuse2.builds > b0 else "?"
        out2.append((minute, expect, got if not (expect == "parse" and got == "build") else "parse", same, unchanged))
    # the same raw read, changed in place and handed again: its identity is the same, its content is not
    _sid = sorted(raw_inplace)[0]
    _row = next(r for r in raw_inplace[_sid] if r.get("mean") is not None or r.get("state") is not None)
    _row["mean" if _row.get("mean") is not None else "state"] = 4321.0
    b0 = reuse2.builds
    same_ip, unch_ip, det_ip, _d, _h, _p, _k, _e = run_pair(T0 + timedelta(minutes=120), raw_inplace, raw_inplace, reuse2)
    out2.append((120, "build", "build" if reuse2.builds > b0 else "reuse", same_ip, unch_ip))
    # a zero whose sign changed (== cannot tell): rebuilt, and the History holds the -0.0 a fresh build holds
    raw_neg = statistics(T0 + timedelta(hours=3))
    _zs = next(s_ for s_ in sorted(raw_neg) if any(r.get("min") == 0.0 for r in raw_neg[s_]))
    next(r for r in raw_neg[_zs] if r.get("min") == 0.0)["min"] = -0.0
    b0 = reuse2.builds
    run_pair(T0 + timedelta(minutes=140), S1, S1, reuse2)                         # S1 kept again
    same_nz, unch_nz, det_nz, _d, _h, _p, _k, _e = run_pair(T0 + timedelta(minutes=140), raw_neg, raw_neg, reuse2)
    out2.append((140, "build", "build" if reuse2.builds > b0 + 1 else "reuse", same_nz, unch_nz))
    # another configuration (the key holds it): rebuilt
    b0 = reuse2.builds
    cfg2 = dataclasses.replace(CFG, pv_array_kwp=7.5)
    same_cf, unch_cf, det_cf, _d, _h, _p, _k, _e = run_pair(T0 + timedelta(minutes=160), raw_neg, raw_neg, reuse2, cfg=cfg2)
    out2.append((160, "build", "build" if reuse2.builds > b0 else "reuse", same_cf, unch_cf))
    check("[3] the holder alone: the same image again and a re-read of equal content reuse; a changed read, a raw read "
          "changed in place (same object), a zero whose sign changed and another configuration each rebuild",
          [(o[1], o[2]) for o in out2] == [(o[1], o[1]) for o in out2], str([(o[0], o[1], o[2]) for o in out2]))
    check("[3] ... and every one of those cycles equals a fresh parse and build (envelope, History, diagnostics)",
          all(o[3] for o in out2), f"{det_ip} | {det_nz} | {det_cf}")
    check("[4] ... and no cycle changed the kept History", all(o[4] for o in out2), str([o[0] for o in out2 if not o[4]]))

    # a refused read on the holder alone (no drop at the read): it keeps nothing, so the same content next is rebuilt
    reuse5 = engine_link.HistoryReuse()
    _r5 = []
    for minute, src in ((0, S1), (20, None), (40, S1_again)):
        b0, r0 = reuse5.builds, reuse5.reuses
        same5, unch5, _det5, diag5, _h5, _p5, _k5, _e5 = run_pair(T0 + timedelta(minutes=minute), src, src, reuse5)
        _r5.append((minute, reuse5.builds - b0, reuse5.reuses - r0, diag5.get("history_hours"), same5, kept(reuse5) is None))
    check("[3] the holder alone: a refused read gives no history and keeps nothing (even without the coordinator's drop), "
          "so a read of the same content as before it is rebuilt, never reused",
          [(m, b, r, h_ == 0, s_, k_) for m, b, r, h_, s_, k_ in _r5]
          == [(0, 1, 0, False, True, False), (20, 0, 0, True, True, True), (40, 1, 0, False, True, False)], str(_r5))

    # RUN-4: EngineJob.statistics is annotated with the image; an image without a HistoryReuse reads as no rows
    _t6 = T0 + timedelta(minutes=20)
    env_i6, diag_i6, hist_i6 = engine_link.compute(job_at(_t6, img1, None), spy)
    env_n6, diag_n6, hist_n6 = engine_link.compute(job_at(_t6, None, None), spy)
    env_r6, diag_r6, hist_r6 = engine_link.compute(job_at(_t6, img1, engine_link.HistoryReuse()), spy)

    def _st6(env) -> dict:
        return {v.key: str(getattr(v.status, "value", v.status)) for v in tuple(env.items) + tuple(env.forecasts)}
    _ok6 = sorted(k for k, s_ in _st6(env_r6).items() if s_ == "OK")
    check("[3] RUN-4: EngineJob.statistics is annotated as a mapping, a StatisticsImage or None; an image handed in "
          "without a HistoryReuse gives no history, exactly as a refused read (fail-closed: every item OK through a "
          "HistoryReuse is BLOCKED), while the same image through a HistoryReuse gives the history (non-vacuity)",
          "history_source.StatisticsImage" in str(engine_link.EngineJob.__annotations__.get("statistics"))
          and hist_i6 is None and diag_i6.get("history_rows") == 0 and env_json(env_i6) == env_json(env_n6)
          and hist_n6 is None and hist_r6 is not None and diag_r6.get("history_rows") == len(img1.rows)
          and bool(_ok6) and all(_st6(env_i6)[k] == "BLOCKED" for k in _ok6),
          f"{engine_link.EngineJob.__annotations__.get('statistics')} {diag_i6.get('history_rows')} "
          f"{diag_r6.get('history_rows')} {_ok6} {_st6(env_i6)}")

    # every decision OPEN: no prepared copy, the PV model learns from the shared records themselves
    reuse3 = engine_link.HistoryReuse()
    out3, held3 = [], S1
    for minute in (0, 20, 40, 60):
        now = T0 + timedelta(minutes=minute)
        same, unchanged, detail, diag, held3, _p, _k, _e = run_pair(now, S1, held3, reuse3, decisions=DEC_OPEN,
                                                                     fn=mutating_spy, slot=minute == 0)
        out3.append((same, unchanged, diag.get("history_reused"), detail))
    check("[3]/[4] every decision OPEN (the PV model reads the shared records; each cycle also empties its own PV forecast "
          "copy): the same results as a fresh build, the kept History unchanged, reused after the first cycle",
          all(o[0] and o[1] for o in out3) and [o[2] for o in out3] == [False, True, True, True], str(out3))

    # non-vacuity of the fingerprint: a cycle that writes into a shared record is caught
    reuse4 = engine_link.HistoryReuse()
    engine_link.compute(job_at(T0, S1, reuse4), spy)
    img4 = reuse4.take_image()
    before4 = fp_history(kept(reuse4), identity=True)

    def writing_spy(inputs):
        env = run_cycle(inputs)
        rec = next(iter(inputs.history.by_start.values()))
        rec.flag("load", "test_written_by_a_cycle")
        return env
    engine_link.compute(job_at(T0 + timedelta(minutes=20), img4, reuse4), writing_spy)
    check("[4] non-vacuity: a cycle that writes into a shared record changes the kept History's fingerprint",
          fp_history(kept(reuse4), identity=True) != before4)
finally:
    if store is not None:
        store.close()
    H.rmtree_own(STORE_ROOT, "ecco_intel_reuse_")

print("== [4] prepare_history changes only its own deep copy")
_h0 = 1_893_456_000                                       # 2030-01-01T00:00:00Z
recs = []
for k in range(72):
    s = _h0 + k * 3600
    r = HourRecord(start=s, e={"load": 0.4, "pv": 0.0, "imp": 0.4, "exp": 0.0, "chg": 0.0, "dis": 0.0},
                   soc_mean=50.0, soc_min=48.0, soc_max=52.0, load_w_mean=400.0, pv_w_mean=0.0, batt_w_mean=10.0,
                   grid_w_mean=400.0, sources={"load": "dongle"})
    if k == 3:                                            # one load reading zero while exporting (a false zero)
        r.e.update({"load": 0.0, "pv": 2.0, "exp": 1.5, "imp": 0.0})
        r.grid_w_mean = -1500.0
    if k % 11 == 5:                                       # an impossible SOC and a negative energy
        r.soc_mean = 150.0
        r.e["chg"] = -0.2
    if k % 13 == 6:
        r.flag("soc", "soc_zero_suspect")
    recs.append(r)
hist_p = History(recs)
fp_before = fp_history(hist_p, identity=True)
prep, notes = prepare_history(hist_p, DEC_OWNER, datetime.fromtimestamp(_h0 + 80 * 3600, UTC))
check("prepare_history leaves its input exactly as it was (every record, flag and the order)",
      fp_history(hist_p, identity=True) == fp_before)
_c5 = prep.get(_h0 + 5 * 3600) if prep is not None else None
_c3 = prep.get(_h0 + 3 * 3600) if prep is not None else None
check("... while it did change its copy (non-vacuity: the impossible SOC nulled, the negative energy and the false zero "
      "removed there, and still present in the input)", _c5 is not None and _c5.soc_mean is None and "chg" not in _c5.e
      and _c3 is not None and "load" not in _c3.e and hist_p.get(_h0 + 5 * 3600).soc_mean == 150.0
      and hist_p.get(_h0 + 3 * 3600).e["load"] == 0.0, str([n.code for n in notes][:4]))

# ---------------------------------------------------------------------------------------------------------------------
print("== [5] the audit: every write to an hour record or a History index, pinned")
REC_ATTRS = frozenset({"e", "flags", "sources", "by_start"})
REC_FIELDS = frozenset({"start", "e", "soc_mean", "soc_min", "soc_max", "pv_w_mean", "load_w_mean", "batt_w_mean",
                        "grid_w_mean", "flags", "sources", "by_start"})
MUTATORS = frozenset({"flag", "setdefault", "pop", "popitem", "update", "clear", "add", "discard", "remove", "append",
                      "extend", "insert", "sort", "reverse", "difference_update", "intersection_update",
                      "symmetric_difference_update", "__setitem__", "__delitem__"})
ALLOWED = {("intelligence/history.py", "HourRecord.flag"), ("intelligence/history.py", "History.__init__"),
           ("intelligence/history.py", "build_history"), ("intelligence/quality.py", "_prepare")}
OFFLINE_ONLY = frozenset({"intelligence/faults.py", "intelligence/synthetic.py", "intelligence/replay.py"})


def _touches_record(node: ast.AST) -> bool:
    while True:
        if isinstance(node, ast.Attribute):
            if node.attr in REC_ATTRS:
                return True
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return False


def write_sites(path: Path) -> list[tuple[str, int, str]]:
    """(enclosing function, line, the write) of every write to a record field or a History index in one module."""
    out: list[tuple[str, int, str]] = []

    def visit(n: ast.AST, scope: list[str]) -> None:
        for ch in ast.iter_child_nodes(n):
            sc = scope + [ch.name] if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else scope
            hits = []
            if isinstance(ch, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                for t in (ch.targets if isinstance(ch, (ast.Assign, ast.Delete)) else [ch.target]):
                    for el in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                        if (isinstance(el, ast.Attribute) and el.attr in REC_FIELDS) or (
                                isinstance(el, ast.Subscript) and _touches_record(el.value)):
                            hits.append(ast.unparse(el))
            elif isinstance(ch, ast.Call):
                f = ch.func
                if isinstance(f, ast.Name) and f.id in ("setattr", "delattr"):
                    hits.append(ast.unparse(ch))
                elif isinstance(f, ast.Attribute) and (f.attr == "flag" or (f.attr in MUTATORS and _touches_record(f.value))):
                    hits.append(ast.unparse(ch))
            out.extend((".".join(sc) or "<module>", ch.lineno, h_[:70]) for h_ in hits)
            visit(ch, sc)
    visit(ast.parse(path.read_text(encoding="utf-8")), [])
    return out


scan_files = sorted(list((REPO / "intelligence").glob("*.py")) + list((REPO / "ecco_core").glob("*.py"))
                    + [p for p in (REPO / "custom_components" / "ecco_intelligence").rglob("*.py")
                       if "tests" not in p.relative_to(REPO / "custom_components" / "ecco_intelligence").parts
                       and "__pycache__" not in p.parts])
sites = {p.relative_to(REPO).as_posix(): write_sites(p) for p in scan_files}
outside = sorted((rel, fn, ln, w) for rel, ws in sites.items() for fn, ln, w in ws
                 if rel not in OFFLINE_ONLY and (rel, fn) not in ALLOWED)
check(f"every write to an hour record or a History index in the engine, ecco_core and the runtime ({len(scan_files)} "
      "modules) is in build_history, HourRecord.flag, History.__init__ or quality._prepare, or in an offline-only module",
      not outside, str(outside[:5]))
_found = {(rel, fn) for rel, ws in sites.items() for fn, _ln, _w in ws if (rel, fn) in ALLOWED}
check("... the scan is not vacuous: it finds the writes it allows (each allowed function writes) and the offline modules'",
      _found == ALLOWED and all(sites.get(m) for m in OFFLINE_ONLY), f"{sorted(_found)}")
_q = ast.parse((REPO / "intelligence" / "quality.py").read_text(encoding="utf-8"))
_prep_fn = next(n for n in ast.walk(_q) if isinstance(n, ast.FunctionDef) and n.name == "_prepare")
_deep = [n.lineno for n in ast.walk(_prep_fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "copy.deepcopy"]
_prep_writes = [ln for fn, ln, _w in sites["intelligence/quality.py"] if fn == "_prepare"]
check("quality._prepare deep-copies the records before its first write (it changes only its copy)",
      _deep and _prep_writes and min(_deep) < min(_prep_writes), f"{_deep} {_prep_writes[:3]}")


def import_closure(starts: list[Path]) -> set[str]:
    """The repository modules (intelligence/*, ecco_core/*) reachable by import from `starts`."""
    seen: set[str] = set()
    todo = list(starts)
    while todo:
        p = todo.pop()
        rel = p.relative_to(REPO).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        pkg = p.parent
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(n, ast.ImportFrom):
                if n.level:
                    base = pkg
                    for _ in range(n.level - 1):
                        base = base.parent
                    mod = (n.module or "").replace(".", "/")
                    cand = [base / mod] if n.module else []
                    cand += [base / mod / a.name if mod else base / a.name for a in n.names]
                    names = [str(c) for c in cand]
                elif n.module and n.module.split(".")[0] in ("intelligence", "ecco_core"):
                    names = [str(REPO / n.module.replace(".", "/"))] + [str(REPO / n.module.replace(".", "/") / a.name)
                                                                         for a in n.names]
            elif isinstance(n, ast.Import):
                names = [str(REPO / a.name.replace(".", "/")) for a in n.names
                         if a.name.split(".")[0] in ("intelligence", "ecco_core")]
            for c in names:
                cp = Path(c)
                for f in (cp.with_suffix(".py"), cp / "__init__.py"):
                    if f.is_file() and REPO in f.parents:
                        todo.append(f)
    return {s for s in seen if s.startswith(("intelligence/", "ecco_core/"))}


_rt = [p for p in (REPO / "custom_components" / "ecco_intelligence").rglob("*.py")
       if "tests" not in p.relative_to(REPO / "custom_components" / "ecco_intelligence").parts and "__pycache__" not in p.parts]
closure = import_closure(_rt)
check("the offline-only writers (faults, synthetic, replay) are outside the runtime's import closure, which holds the "
      "cycle and the modules that read the shared records",
      not (closure & OFFLINE_ONLY) and {"intelligence/shadow_cycle.py", "intelligence/quality.py", "intelligence/pv.py",
                                        "intelligence/history.py", "intelligence/scorecard.py"} <= closure,
      str(sorted(closure & OFFLINE_ONLY)))

# ---------------------------------------------------------------------------------------------------------------------
print("== [6] the A50 text: the measured share and no workstation reference (REV-E-4, RUN-5)")
_rt_doc = (REPO / "docs" / "intelligence" / "INTELLIGENCE_HA_RUNTIME.md").read_text(encoding="utf-8")
_pi = _rt_doc.find("**The parsed history (A50).**")
_para_lines = _rt_doc[_pi:_rt_doc.find("\n\n", _pi)].split("\n") if _pi >= 0 else []
_texts = {"INTELLIGENCE_HA_RUNTIME 'The parsed history (A50)'": " ".join(_para_lines),
          "engine_link's module docstring": " ".join((engine_link.__doc__ or "").split())}
_bad = {k: [w for w in ("profiling PC", "over a third", "about 0.1 s") if w in t] for k, t in _texts.items()}
check("the HA_RUNTIME paragraph and engine_link's docstring give the parse and build as about 0.08 s of every cycle on "
      "a desktop test machine, about a third of a refresh once the memo was in (REV-E-4), never the 'profiling PC' or "
      "'over a third' (RUN-5)",
      all("took about 0.08 s of every cycle on a desktop test machine, about a third of a refresh once the engine's "
          "profile memo was in" in t for t in _texts.values()) and not any(_bad.values()), str(_bad))
check("... and the HA_RUNTIME paragraph is wrapped at the file's width (no line over 120 columns; RUN-5)",
      len(_para_lines) > 5 and max(len(ln) for ln in _para_lines) <= 120,
      str(max((len(ln) for ln in _para_lines), default=0)))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the parsed-history reuse suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all parsed-history reuse checks passed")
