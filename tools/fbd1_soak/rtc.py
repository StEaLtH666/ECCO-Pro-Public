"""Areas 1 and 2: RTC corrections and RTC stall detection, plus the evidence for the FB-D1 A3 stall-veto decision.

READS. A regular RTC read happens every 60 s; each read publishes `Inverter Time` and `Clock Difference` and logs
`Inverter RTC: <time> | Difference from NTP: <d> s`. Home Assistant drops a row whose state did not change, so two reads with
the same difference leave one Clock Difference row: the second read is recovered from its Inverter Time row (which changes
every read) and takes the difference in force (marked `ha-inferred`). A firmware log read is preferred when both exist.

CORRECTION EPISODES are assembled from `Last Correction Result` (Automatic correction queued (<reason>) - error <e> s ->
Write acknowledged - verifying attempt <n> -> Verified OK - error now <r> s | Verification failed ... | FAILED ... | ABORTED
...) and from the firmware log lines of the same steps; the same step seen in both sources within 5 s is one step. With
neither source, the counters still give confirmed totals but no per-episode detail.

STALE-PAIR CLASSIFICATION (every label is INFERRED; the facts behind it are listed per episode). For a background correction
the firmware confirmed two consecutive reads E1 (prior read) and E2 (queue read). The analyser compares E1 with the trend of
the reads before it (median of the last <= 3 non-stalled regular reads in Rules.trend_window_s after the previous correction)
allowing the measured drift for the PV level plus the 0-10 s staleness of the register image:
  stale_first_read_candidate     E1 jumps away from the trend beyond that allowance AND the stall detector fired on E1
                                 (logged, its binary sensor, or the same rule recomputed from the two reads)
  false_confirmation_candidate   E1 jumps away from the trend, without a stall flag (or the pair itself disagrees by more
                                 than the drift allowance)
  inconclusive_stale_signature   a stall flag or a disagreeing pair, but E1 is consistent with the trend
  consistent_with_drift          E1 and E2 are consistent with the trend: genuine drift
  undetermined                   not enough reads to tell
A candidate whose trend error is below the background threshold is a SUSPECTED NO-OP: the write moved the clock by roughly
(residual - trend), not by the confirmed error.
"""

from __future__ import annotations

import bisect
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import rtc_policy as RP  # registry/rtc_policy.py: the C++-exact FB-D1 policy mirror (on sys.path via the package)

from .evidence import as_bool, as_float, counter_delta, is_missing
from .model import (CONFIRMED, FAIL, INFERRED, INSUFFICIENT, MIXED, NONE, PASS, WARNING, Criterion, Ctx, num)
from .timeutil import days_from_civil_local, fmt_duration, local_seconds_of_day, stamp, to_local

# ---------------------------------------------------------------------------------------------------------------------------
# Firmware strings (Last Correction Result)
# ---------------------------------------------------------------------------------------------------------------------------
RESULT_PATTERNS = (
    ("START", re.compile(r"^Automatic correction queued \((?P<reason>[a-z-]+)\) - error (?P<err>-?\d+) s$")),
    ("MANUAL", re.compile(r"^Manual correction started$")),
    ("ACK", re.compile(r"^Write acknowledged - verifying attempt (?P<attempt>\d+)$")),
    ("VERIFIED", re.compile(r"^Verified OK - error now (?P<err>-?\d+) s$")),
    ("VFAIL", re.compile(r"^Verification failed \((?P<err>-?\d+) s\) - retry (?P<retry>\d+) queued$")),
    ("FAILED", re.compile(r"^FAILED after retries - error (?P<err>-?\d+) s - 5 min cooldown$")),
    ("FAILED", re.compile(r"^FAILED after communication errors - 5 min cooldown$")),
    ("ABORTED", re.compile(r"^ABORTED - correction exceeded its deadline - 5 min cooldown$")),
    ("RETRY", re.compile(r"^Communication failure - retry (?P<retry>\d+) queued$")),
    ("WRITE_ERR", re.compile(r"^(?:Modbus write error|No response to write|Write not sent|Non-standard write reply) - processing retry$")),
    ("VREAD_ERR", re.compile(r"^Verification read .+ processing retry$")),
    ("DEFER", re.compile(r"^Deferred - inverter write path busy; will retry$")),
    ("CANCELLED", re.compile(r"^Correction cancelled(?: - confirmed NTP time unavailable)?$")),
    ("BOOT", re.compile(r"^None since boot$")),
)
LOG_KINDS = {
    "rtc_queued": "START", "rtc_policy": "POLICY", "rtc_write_start": "WRITE", "rtc_write_ack": "ACK", "rtc_write_error": "WRITE_ERR",
    "rtc_write_deferred": "DEFER", "rtc_verify_start": "VSTART", "rtc_verified": "VERIFIED", "rtc_verify_failed": "VFAIL",
    "rtc_failed_retries": "FAILED", "rtc_failed_comm": "FAILED", "rtc_aborted": "ABORTED",
}
TERMINAL = {"VERIFIED": "verified", "FAILED": "failed", "ABORTED": "aborted", "CANCELLED": "cancelled"}


def parse_result(text: str):
    for kind, rx in RESULT_PATTERNS:
        m = rx.match(text.strip())
        if m:
            d = {k: v for k, v in m.groupdict().items() if v is not None}
            if kind == "FAILED":
                d["why"] = "communication" if "communication" in text else "retries"
            return kind, d
    return None, {}


# ---------------------------------------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class Read:
    t: datetime
    err: int | None
    src: str  # log | ha | ha-inferred
    ref: str
    inv: str | None = None
    verify: bool = False
    stall: bool | None = None  # the firmware stall detector's verdict for this read
    stall_basis: str = ""
    computed_stall: bool | None = None
    ntp_adv: float | None = None
    inv_adv: float | None = None


def build_reads(ctx: Ctx) -> list:
    ev, r = ctx.ev, ctx.rules
    tol = timedelta(seconds=r.read_match_s)
    logs = [Read(e.t, int(e.fields["diff"]), "log", e.ref, e.fields.get("inv")) for e in ev.logs if e.kind == "rtc_read"]
    ha = []
    cd = ev.get("clock_difference")
    if cd:
        for x in cd.samples:
            v = as_float(x.raw)
            if v is not None:
                ha.append(Read(x.t, int(round(v)), "ha", x.ref))
    it = ev.get("inverter_time")
    if it:
        ha.sort(key=lambda z: z.t)
        ha_times = [z.t for z in ha]
        inferred = []
        for x in it.samples:
            if is_missing(x.raw):
                continue
            i = bisect.bisect_left(ha_times, x.t - tol)
            if i < len(ha_times) and ha_times[i] <= x.t + tol:
                if ha[i].inv is None:
                    ha[i].inv = x.raw
                continue
            cur = cd.at(x.t) if cd else None
            v = as_float(cur.raw) if cur else None
            inferred.append(Read(x.t, None if v is None else int(round(v)), "ha-inferred", x.ref, x.raw))
        ha.extend(inferred)
    ha.sort(key=lambda z: z.t)
    if logs:
        lt = [z.t for z in logs]
        keep = []
        for h in ha:
            i = bisect.bisect_left(lt, h.t - tol)
            if i < len(lt) and lt[i] <= h.t + tol:
                continue
            keep.append(h)
        ha = keep
    reads = sorted(logs + ha, key=lambda z: z.t)
    # stall detector verdicts
    stall_logs = [e for e in ev.logs if e.kind == "rtc_stall"]
    for z in reads:
        if z.src == "log":
            z.stall, z.stall_basis = False, "log (no STALL line)"
    rtimes = [z.t for z in reads]
    for e in stall_logs:
        # the STALL line follows its read's `Inverter RTC` line in the same lambda: the latest read up to 2 s before it
        i = bisect.bisect_right(rtimes, e.t) - 1
        if i >= 0 and e.t - reads[i].t <= timedelta(seconds=2):
            z = reads[i]
            z.stall, z.stall_basis = True, f"log {e.ref}"
            z.inv_adv = float(e.fields["inv_adv"]) if e.fields.get("inv_adv") else z.inv_adv
            z.ntp_adv = float(e.fields["ntp_adv"]) if e.fields.get("ntp_adv") else z.ntp_adv
    sd = ev.get("rtc_stall_detected")
    if sd:
        for z in reads:
            if z.stall is not None:
                continue
            row = sd.at(z.t + timedelta(seconds=1))
            if row is None:
                continue
            b = as_bool(row.raw)
            if b is None:
                continue
            fresh = abs((row.t - z.t).total_seconds()) <= r.read_match_s
            z.stall, z.stall_basis = b, ("binary sensor row " if fresh else "binary sensor in force ") + row.ref
    return reads


def _regular(reads: list) -> list:
    return [z for z in reads if not z.verify and z.err is not None]


def compute_stalls(reads: list, write_times: list) -> None:
    """The firmware's stall rule recomputed from consecutive regular reads (ntp advance 45-90 s, inverter advance < ntp - 15)."""
    reg = _regular(reads)
    for p, q in zip(reg, reg[1:]):
        ntp = (q.t - p.t).total_seconds()
        if any(p.t <= w < q.t for w in write_times):
            continue  # a correction was queued at p or landed between them: the firmware re-bases its baseline
        inv = ntp + (q.err - p.err)
        if q.ntp_adv is None:
            q.ntp_adv, q.inv_adv = round(ntp, 1), round(inv, 1)
        if 45 <= ntp <= 90:
            q.computed_stall = inv < ntp - 15


# ---------------------------------------------------------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class Episode:
    idx: int
    t_start: datetime | None = None
    t_end: datetime | None = None
    kind: str = "unknown"  # auto | manual | unknown
    reason: str | None = None
    err: int | None = None
    thr_logged: int | None = None
    err_logged: int | None = None
    acks: list = field(default_factory=list)
    attempts: int = 0
    outcome: str = "incomplete"
    residual: int | None = None
    retries: int = 0
    write_errors: int = 0
    deferred: int = 0
    sources: set = field(default_factory=set)
    refs: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    lock: tuple | None = None
    a: dict = field(default_factory=dict)  # per-episode analysis

    @property
    def t(self) -> datetime | None:
        return self.t_start or (self.acks[0] if self.acks else self.t_end)


def _steps(ctx: Ctx) -> list:
    out = []
    s = ctx.ev.get("last_correction_result")
    if s:
        prev = None
        for x in s.samples:
            raw = x.raw.strip()
            if is_missing(raw) or raw == prev:
                continue
            prev = raw
            kind, d = parse_result(raw)
            if kind is None:
                ctx.ev.diag("warning", "unrecognised-correction-result", f"Last Correction Result {raw!r} is not a known firmware "
                            "string", x.ref)
                continue
            if kind == "BOOT":
                continue
            out.append([x.t, kind, d, "ha", [x.ref]])
    for e in ctx.ev.logs:
        k = LOG_KINDS.get(e.kind)
        if k is None:
            continue
        d = dict(e.fields)
        if e.kind == "rtc_queued":
            d = {"err": e.fields.get("diff")}
        if e.kind in ("rtc_failed_retries", "rtc_failed_comm"):
            d["why"] = "retries" if e.kind == "rtc_failed_retries" else "communication"
        out.append([e.t, k, d, "log", [e.ref]])
    out.sort(key=lambda z: (z[0], 0 if z[3] == "log" else 1))
    merged = []
    for st in out:
        dup = None
        for m in reversed(merged):
            if (st[0] - m[0]).total_seconds() > 5:
                break
            if m[1] == st[1] and st[3] not in m[3].split("+"):
                dup = m
                break
        if dup:
            dup[3] = dup[3] + "+" + st[3]
            dup[4].extend(st[4])
            for k, v in st[2].items():
                dup[2].setdefault(k, v)
        else:
            merged.append(st)
    return merged


def build_episodes(ctx: Ctx) -> list:
    eps, cur = [], None

    def open_ep(t, kind):
        nonlocal cur
        if cur is not None and cur.outcome == "incomplete":
            cur.outcome = "superseded"
        cur = Episode(len(eps) + 1, t_start=t, kind=kind)
        eps.append(cur)
        return cur

    for t, kind, d, src, refs in _steps(ctx):
        if kind in ("START", "MANUAL"):
            if cur is not None and cur.outcome == "incomplete" and cur.t_start and (t - cur.t_start).total_seconds() <= 5 \
                    and cur.kind == "auto" and kind == "START":
                ep = cur
            else:
                ep = open_ep(t, "manual" if kind == "MANUAL" else "auto")
            if kind == "START":
                ep.reason = d.get("reason") or ep.reason
                if d.get("err") is not None and ep.err is None:
                    ep.err = int(d["err"])
        elif kind == "POLICY":
            ep = cur if (cur is not None and cur.t_start and abs((t - cur.t_start).total_seconds()) <= 5) else open_ep(t, "auto")
            ep.reason = d.get("reason") or ep.reason
            ep.thr_logged = int(d["thr"]) if d.get("thr") is not None else None
            ep.err_logged = int(d["err"]) if d.get("err") is not None else None
            if ep.err is None and ep.err_logged is not None:
                ep.err = ep.err_logged
        else:
            ep = cur if (cur is not None and cur.outcome == "incomplete") else open_ep(None, "unknown")
            if kind == "ACK":
                ep.acks.append(t)
                ep.attempts = max(ep.attempts, int(d.get("attempt", len(ep.acks))))
            elif kind == "WRITE":
                ep.attempts = max(ep.attempts, int(d.get("attempt", 1)))
            elif kind in ("WRITE_ERR", "VREAD_ERR"):
                ep.write_errors += 1
            elif kind in ("VFAIL", "RETRY"):
                ep.retries += 1
            elif kind == "DEFER":
                ep.deferred += 1
            elif kind in TERMINAL:
                ep.outcome = TERMINAL[kind]
                ep.t_end = t
                if kind == "VERIFIED" and d.get("err") is not None:
                    ep.residual = int(d["err"])
                if kind == "FAILED":
                    ep.a["failure"] = d.get("why")
                    if d.get("err") is not None:
                        ep.residual = int(d["err"])
                if kind == "ABORTED" and d.get("held"):
                    ep.a["breaker_held_s"] = int(d["held"])
        ep.sources.update(src.split("+"))
        ep.refs.extend(refs)
        ep.steps.append((t, kind, src))
    return eps


def counter_episodes(ctx: Ctx) -> list:
    """Fallback when no correction text and no log is available: one episode per counter increment (time +-60 s)."""
    eps = []
    for key, outcome in (("verified_corrections", "verified"), ("failed_corrections", "failed")):
        r = counter_delta(ctx.ev.get(key), ctx.start, ctx.end)
        if not r.available:
            continue
        for t, amount, ref in r.increments:
            for _ in range(int(amount)):
                ep = Episode(0, t_start=None, t_end=t, outcome=outcome)
                ep.sources.add("counter")
                ep.refs.append(ref)
                ep.a["time_uncertainty_s"] = 60
                eps.append(ep)
    eps.sort(key=lambda e: e.t_end)
    for i, e in enumerate(eps, 1):
        e.idx = i
    return eps


def lock_intervals(ctx: Ctx) -> list:
    s = ctx.ev.get("rtc_correction_in_progress")
    if not s:
        return []
    out, on = [], None
    for x in s.samples:
        b = as_bool(x.raw)
        if b is True and on is None:
            on = x
        elif b is False and on is not None:
            out.append((on.t, x.t, on.ref, x.ref))
            on = None
        elif b is None and on is not None:
            on = None  # unavailable: the duration is unknown
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------------------------------------------------------
def pv_at(ctx: Ctx, t: datetime) -> float | None:
    s = ctx.ev.get("pv_power")
    row = s.at(t) if s else None
    return as_float(row.raw) if row else None


def daylight(ctx: Ctx, t: datetime) -> tuple:
    pv = pv_at(ctx, t)
    if pv is not None:
        return pv >= ctx.rules.daylight_pv_w, "pv", pv
    h = to_local(t).hour
    a, b = ctx.rules.daylight_hours
    return a <= h < b, "clock (no PV evidence)", None


def max_rate(ctx: Ctx, pv: float | None) -> float:
    r = ctx.rules
    if pv is None:
        return r.drift_high_pv_s_per_min
    if pv < r.daylight_pv_w:
        return r.drift_night_s_per_min
    if pv < r.high_pv_w:
        return r.drift_low_pv_s_per_min
    return r.drift_high_pv_s_per_min


def threshold_at(ctx: Ctx, t: datetime) -> tuple:
    s = ctx.ev.get("correction_threshold")
    row = s.at(t) if s else None
    v = as_float(row.raw) if row else None
    if v is not None:
        return int(round(v)), CONFIRMED
    if ctx.rules.threshold_s is not None:
        return int(ctx.rules.threshold_s), "operator-supplied"
    return None, NONE


def tou_at(ctx: Ctx, t: datetime) -> tuple:
    """(raw words for the valid zone starts known at t, all six known?)"""
    raws, known = [], 0
    for i in range(1, 7):
        s = ctx.ev.get(f"tou{i}_time")
        row = s.at(t) if s else None
        if row is None or is_missing(row.raw):
            continue
        m = re.match(r"^(\d{1,2}):(\d{2})$", row.raw.strip())
        if not m:
            continue
        known += 1
        raws.append(int(m.group(1)) * 100 + int(m.group(2)))
    return raws, known == 6


def lease_at(ctx: Ctx, t: datetime) -> tuple:
    found, any_ev = [], False
    for key in ("free_power_active", "dump_active", "free_power_op", "dump_op"):
        s = ctx.ev.get(key)
        row = s.at(t) if s else None
        b = as_bool(row.raw) if row else None
        if b is not None:
            any_ev = True
        if b:
            found.append(key)
    return found, any_ev


# ---------------------------------------------------------------------------------------------------------------------------
# Per-episode analysis
# ---------------------------------------------------------------------------------------------------------------------------
def _nearest(reads, t, tol_s):
    best = None
    for z in reads:
        d = abs((z.t - t).total_seconds())
        if d <= tol_s and (best is None or d < abs((best.t - t).total_seconds())):
            best = z
    return best


def attach_reads(ctx: Ctx, eps: list, reads: list) -> None:
    times = [z.t for z in reads]
    for ep in eps:
        # verification reads: the first read after each acknowledgement, and the read at the verdict
        for ack in ep.acks:
            i = bisect.bisect_right(times, ack)
            if i < len(reads) and (reads[i].t - ack).total_seconds() <= 30:
                reads[i].verify = True
        if ep.t_end is not None and ep.outcome in ("verified", "failed"):
            z = _nearest(reads, ep.t_end, ctx.rules.read_match_s)
            if z is not None and (ep.acks or ep.residual is not None) and (not ep.t_start or z.t > ep.t_start + timedelta(seconds=2)):
                z.verify = True
    # the firmware re-bases its stall baseline when it queues a correction and again at the verdict: a pair of regular reads
    # that straddles a queue instant, a write or a verdict is never a stall pair
    write_times = [a for ep in eps for a in ep.acks] + [x for ep in eps for x in (ep.t_start, ep.t_end) if x is not None]
    compute_stalls(reads, write_times)
    reg = _regular(reads)
    rtimes = [z.t for z in reg]
    prev_end = None
    for ep in eps:
        if ep.t_start is None or ep.kind != "auto":
            prev_end = ep.t_end or prev_end
            continue
        q = _nearest(reg, ep.t_start, ctx.rules.read_match_s)
        a = ep.a
        if q is None:
            a["queue_read"] = None
            prev_end = ep.t_end or prev_end
            continue
        i = rtimes.index(q.t)
        p = reg[i - 1] if i >= 1 else None
        if p is not None and not (20 <= (q.t - p.t).total_seconds() <= 150 and (prev_end is None or p.t > prev_end)):
            p = None
        o = reg[i - 2] if (p is not None and i >= 2) else None
        if o is not None and not (20 <= (p.t - o.t).total_seconds() <= 150 and (prev_end is None or o.t > prev_end)):
            o = None
        trend_from = max(p.t - timedelta(seconds=ctx.rules.trend_window_s), prev_end) if (p and prev_end) else (
            p.t - timedelta(seconds=ctx.rules.trend_window_s) if p else None)
        trend = [z for z in reg if p is not None and trend_from <= z.t < p.t and not z.stall and not z.computed_stall]
        a["queue_read"] = _rd(q)
        a["prior_read"] = _rd(p)
        a["read_before_prior"] = _rd(o)
        a["trend_reads"] = [_rd(z) for z in trend[-6:]]
        v = [z for z in reads if z.verify and ep.t_start and ep.t_start < z.t <= (ep.t_end or ep.t_start) + timedelta(seconds=2)]
        a["verify_read"] = _rd(v[-1]) if v else None
        ep._q, ep._p, ep._trend = q, p, trend
        prev_end = ep.t_end or prev_end


def _rd(z: Read | None):
    if z is None:
        return None
    return {"time": stamp(z.t), "error_s": z.err, "source": z.src, "stall_detector": z.stall, "stall_basis": z.stall_basis,
            "computed_stall": z.computed_stall, "ntp_advance_s": z.ntp_adv, "inverter_advance_s": z.inv_adv, "ref": z.ref}


def classify_pair(ctx: Ctx, ep: Episode) -> None:
    a = ep.a
    q, p, trend = getattr(ep, "_q", None), getattr(ep, "_p", None), getattr(ep, "_trend", [])
    is_day, dbasis, pv = daylight(ctx, ep.t_start)
    a["daylight"] = is_day
    a["daylight_basis"] = dbasis
    a["pv_w"] = pv
    if ep.reason != "background":
        a["classification"] = "not-applicable"
        return
    if q is None or p is None:
        a["classification"] = "undetermined"
        a["why"] = "the two confirming reads are not both in the evidence"
        return
    rate = max_rate(ctx, pv)
    facts = []
    stall_first = bool(p.stall) or bool(p.computed_stall)
    stall_second = bool(q.stall) or bool(q.computed_stall)
    if p.stall:
        facts.append(f"stall detector fired on the prior read ({p.stall_basis})")
    elif p.computed_stall:
        facts.append(f"the stall rule recomputed from the reads fires on the prior read (inverter +{p.inv_adv} s vs NTP "
                     f"+{p.ntp_adv} s)")
    dt12 = (q.t - p.t).total_seconds()
    allow12 = rate * dt12 / 60 + ctx.rules.pair_tolerance_s
    pair_diff = q.err - p.err
    pair_disagrees = abs(pair_diff) > allow12
    if pair_disagrees:
        facts.append(f"the confirming reads differ by {pair_diff:+d} s in {dt12:.0f} s (drift allowance {allow12:.1f} s): their "
                     "implied staleness differs")
    jump = None
    base = None
    if trend:
        last3 = trend[-3:]
        base = statistics.median(z.err for z in last3)
        tb = last3[len(last3) // 2].t
        allow = ctx.rules.staleness_allowance_s + rate * max(0.0, (p.t - tb).total_seconds()) / 60
        jump = abs(p.err - base) > allow
        a["trend_error_s"] = base
        a["trend_allowance_s"] = round(allow, 1)
        a["prior_vs_trend_s"] = p.err - base
        if jump:
            facts.append(f"the prior read ({p.err:+d} s) is {p.err - base:+.0f} s away from the trend ({base:+.0f} s), beyond the "
                         f"{allow:.1f} s allowance for {'night' if rate <= ctx.rules.drift_night_s_per_min else 'this PV level'}")
    a["max_drift_s_per_min"] = rate
    a["stall_on_prior_read"] = stall_first
    a["stall_on_queue_read"] = stall_second
    a["pair_difference_s"] = pair_diff
    a["pair_disagrees"] = pair_disagrees
    if jump is None:
        cls = "inconclusive_stale_signature" if (stall_first or pair_disagrees) else "undetermined"
        a["why"] = "no trend reads before the confirming pair"
    elif jump and stall_first:
        cls = "stale_first_read_candidate"
    elif jump or (pair_disagrees and not trend):
        cls = "false_confirmation_candidate"
    elif stall_first or stall_second or pair_disagrees:
        cls = "inconclusive_stale_signature"
    else:
        cls = "consistent_with_drift"
        facts.append(f"both confirming reads follow the trend ({base:+.0f} s) within the drift + staleness allowance")
    a["classification"] = cls
    a["facts"] = facts
    thr, _ = threshold_at(ctx, ep.t_start)
    bg = max(RP.clamp_threshold(thr), RP.kBackgroundFloorS) if thr is not None else RP.kBackgroundFloorS
    if cls in ("stale_first_read_candidate", "false_confirmation_candidate") and base is not None and abs(base) < bg:
        a["suspected_noop"] = True
        if ep.residual is not None:
            a["estimated_effective_correction_s"] = ep.residual - base
    else:
        a["suspected_noop"] = False


def policy_check(ctx: Ctx, ep: Episode, eps: list) -> None:
    """Check one automatic correction against the FB-D1 policy (registry/rtc_policy.py). Results per check:
    ok | violation | edge (within Rules.edge_tolerance_s of a window boundary) | unknown (evidence missing)."""
    a = ep.a
    checks = []
    t = ep.t_start
    tod = local_seconds_of_day(t)
    lt = to_local(t)
    day = days_from_civil_local(lt)
    tou, tou_all = tou_at(ctx, t)
    P, pbasis = threshold_at(ctx, t)
    err = ep.err
    reason = ep.reason
    tolr = int(ctx.rules.edge_tolerance_s)

    def quiet(x):
        return RP.in_quiet_window(RP.Inputs(tod_s=x % 86400, tou_raw=list(tou)))

    qs = {quiet(tod + d) for d in range(-tolr, tolr + 1)}
    if qs == {True}:
        checks.append(("quiet-window", "violation", f"queued at {lt.strftime('%H:%M:%S')}, inside a quiet window"))
    elif len(qs) > 1:
        checks.append(("quiet-window", "edge", f"queued at {lt.strftime('%H:%M:%S')}, within {tolr} s of a quiet-window edge"))
    else:
        checks.append(("quiet-window", "ok" if tou_all else "ok-partial",
                       "outside every quiet window" + ("" if tou_all else " (half hours checked; TOU zone starts not all known)")))
    if err is None:
        checks.append(("threshold", "unknown", "the queued error is not in the evidence"))
    else:
        large = abs(err) >= RP.kLargeErrorS
        if reason == "background":
            if P is None:
                need = RP.kBackgroundFloorS
                checks.append(("threshold", "ok" if abs(err) >= need else "violation",
                               f"|{err}| vs the 30 s background floor (Clock Correction Threshold unknown)"))
            else:
                need = max(RP.clamp_threshold(P), RP.kBackgroundFloorS)
                checks.append(("threshold", "ok" if abs(err) >= need else "violation", f"|{err}| s vs background threshold {need} s"))
        elif reason == "precision":
            key = RP.precision_key(RP.Inputs(tod_s=tod, day=day, tou_raw=list(tou)))
            if not tou:
                checks.append(("precision-window", "unknown", "TOU zone starts unknown"))
            elif key == 0:
                checks.append(("precision-window", "violation", f"{lt.strftime('%H:%M:%S')} is not in [b-120 s, b-60 s) of any "
                               "zone start"))
            else:
                checks.append(("precision-window", "ok", f"{lt.strftime('%H:%M:%S')} is in the precision window of zone key {key}"))
                dup = [e for e in eps if e is not ep and e.reason == "precision" and e.a.get("precision_key") == key]
                if dup:
                    checks.append(("precision-once", "violation", f"zone key {key} already served by correction #{dup[0].idx}"))
                a["precision_key"] = key
            if P is not None:
                need = RP.precision_threshold(RP.clamp_threshold(P))
                okp = need <= abs(err) < RP.kLargeErrorS
                checks.append(("threshold", "ok" if okp else "violation", f"|{err}| s vs precision band [{need}, 300) s"))
        elif reason == "large":
            checks.append(("threshold", "ok" if large else "violation", f"|{err}| s vs the 300 s large-error bound"))
        elif reason == "boot":
            since_boot = [c for c in ctx.restarts if c["t"] <= t]
            ref_t = since_boot[-1]["t"] if since_boot else ctx.start
            late = (t - ref_t).total_seconds() > 3600
            checks.append(("boot", "warning" if late else "ok", "boot alignment " + (
                f"{fmt_duration((t - ref_t).total_seconds())} after the last boot" if late else "shortly after boot")))
        else:
            checks.append(("reason", "unknown", f"policy reason {reason!r} not recognised"))
        if not large:
            zc = RP.would_step_back_across(RP.Inputs(err_s=err, tod_s=tod, tou_raw=list(tou)))
            checks.append(("zone-cross", "violation" if zc else ("ok" if tou_all else "ok-partial"),
                           "a positive error would step the clock back across a boundary" if zc else "no boundary crossed"))
            lease, lease_ev = lease_at(ctx, t)
            if lease:
                checks.append(("lease-hold", "violation", f"lease state active: {', '.join(lease)}"))
            else:
                checks.append(("lease-hold", "ok" if lease_ev else "unknown",
                               "no Free Power / Dump to Grid lease active" if lease_ev else "lease state not in the evidence"))
        if reason == "background":
            prev = [e for e in eps if e is not ep and e.kind == "auto" and e.t_start and e.t_start < t]
            if prev and (t - prev[-1].t_start).total_seconds() < RP.kMinGapMs / 1000:
                checks.append(("min-gap", "violation", f"{(t - prev[-1].t_start).total_seconds():.0f} s after correction "
                               f"#{prev[-1].idx}"))
            else:
                checks.append(("min-gap", "ok", "at least 5 min after the previous automatic correction"))
            q, p = getattr(ep, "_q", None), getattr(ep, "_p", None)
            if q is None or p is None:
                checks.append(("confirmation", "unknown", "the two confirming reads are not both in the evidence"))
            else:
                need = max(RP.clamp_threshold(P), RP.kBackgroundFloorS) if P is not None else RP.kBackgroundFloorS
                ntp = (q.t - p.t).total_seconds()
                inv = ntp + (q.err - p.err)
                frozen = inv < ntp - RP.kFrozenSlackS and not (abs(q.err) >= RP.kLargeErrorS and abs(p.err) >= RP.kLargeErrorS)
                okc = (abs(p.err) >= need and (p.err < 0) == (q.err < 0) and RP.kConfirmMinS <= ntp <= RP.kConfirmMaxS
                       and not frozen)
                basis = "log" if (q.src == "log" and p.src == "log") else "Home Assistant rows"
                checks.append(("confirmation", "ok" if okc else ("violation" if basis == "log" else "warning"),
                               f"prior read {p.err:+d} s, queue read {q.err:+d} s, {ntp:.0f} s apart ({basis})"))
    worst_c = "violation" if any(c[1] == "violation" for c in checks) else (
        "warning" if any(c[1] in ("warning", "edge") for c in checks) else (
            "unknown" if any(c[1] == "unknown" for c in checks) else "consistent"))
    a["policy"] = {"result": worst_c, "threshold_setting_s": P, "threshold_basis": pbasis, "tou_zone_starts": sorted(tou),
                   "checks": [{"check": c[0], "result": c[1], "detail": c[2]} for c in checks]}


# ---------------------------------------------------------------------------------------------------------------------------
# Precision windows, stall events, A3 what-if
# ---------------------------------------------------------------------------------------------------------------------------
def precision_windows(ctx: Ctx, reads: list, eps: list) -> dict:
    out = {"windows": 0, "with_read": 0, "precision_corrections": 0, "within_threshold": 0, "examples": []}
    tou, _ = tou_at(ctx, ctx.end)
    if not tou:
        out["note"] = "TOU zone starts are not in the evidence"
        return out
    reg = _regular(reads)
    d0 = to_local(ctx.start).date()
    d1 = to_local(ctx.end).date()
    from .timeutil import local_to_utc
    day = d0
    while day <= d1:
        for raw in sorted(set(tou)):
            if not RP.tou_valid(raw):
                continue
            b_local = datetime(day.year, day.month, day.day) + timedelta(seconds=RP.tou_second_of_day(raw))
            try:
                w0 = local_to_utc(b_local - timedelta(seconds=RP.kPrecisionLeadS))
                w1 = local_to_utc(b_local - timedelta(seconds=RP.kQuietBeforeS))
            except ValueError:
                continue
            if w0 < ctx.start or w1 > ctx.end:
                continue
            out["windows"] += 1
            inwin = [z for z in reg if w0 <= z.t < w1]
            corr = [e for e in eps if e.reason == "precision" and e.t_start and w0 <= e.t_start < w1 + timedelta(seconds=2)]
            if inwin:
                out["with_read"] += 1
            if corr:
                out["precision_corrections"] += 1
            elif inwin:
                thr, _ = threshold_at(ctx, w0)
                need = RP.precision_threshold(RP.clamp_threshold(thr)) if thr is not None else None
                if need is not None and all(abs(z.err) < need for z in inwin):
                    out["within_threshold"] += 1
                elif need is not None:
                    # a read at or above the precision threshold inside the window and no precision correction: the policy
                    # would correct unless the lock, a cooldown or a lease held it (none of which the read alone shows)
                    z = next(z for z in inwin if abs(z.err) >= need)
                    held = (lease_at(ctx, z.t)[0] or any(e.t_end and e.t and e.t <= z.t <= e.t_end + timedelta(seconds=300)
                                                         for e in eps) or abs(z.err) >= RP.kLargeErrorS)
                    if not held:
                        out["expected_not_observed"] = out.get("expected_not_observed", 0) + 1
                        ctx.event(z.t, "rtc", "WARNING", "precision-window-no-correction",
                                  f"read {z.err:+d} s in the precision window before the {b_local.strftime('%H:%M')} zone start "
                                  f"(precision threshold {need} s) and no precision correction followed", INFERRED, [z.ref])
            if len(out["examples"]) < 14:
                out["examples"].append({"zone_start": b_local.strftime("%Y-%m-%d %H:%M"), "reads": [z.err for z in inwin],
                                        "precision_correction": bool(corr)})
        day += timedelta(days=1)
    return out


def a3_what_if(ctx: Ctx, eps: list, reads: list) -> dict:
    bg = [e for e in eps if e.reason == "background" and e.a.get("classification")]
    cands = [e for e in bg if e.a["classification"] in ("stale_first_read_candidate", "false_confirmation_candidate")]
    genuine = [e for e in bg if e.a["classification"] == "consistent_with_drift"]
    reg = _regular(reads)
    deltas_day, deltas_night = [], []
    stalled_pairs = 0
    writes = [a for e in eps for a in e.acks]
    for p, q in zip(reg, reg[1:]):
        dt = (q.t - p.t).total_seconds()
        if not 45 <= dt <= 90 or any(p.t <= w < q.t for w in writes):
            continue
        if any(e.t_start and p.t <= e.t_start <= q.t + timedelta(seconds=30) for e in eps):
            continue
        if q.stall or q.computed_stall or p.stall or p.computed_stall:
            stalled_pairs += 1
            continue  # normal reads only: a stale read and the read after it are counted separately
        is_day, _, _ = daylight(ctx, q.t)
        (deltas_day if is_day else deltas_night).append(abs(q.err - p.err))

    def pctl(xs, f):
        if not xs:
            return None
        s = sorted(xs)
        return s[min(len(s) - 1, int(round(f * (len(s) - 1))))]

    def veto_stall(e):
        return bool(e.a.get("stall_on_prior_read") or e.a.get("stall_on_queue_read"))

    out = {
        "background_corrections": len(bg),
        "candidates": len(cands),
        "drift_consistent": len(genuine),
        "stalled_read_pairs_excluded": stalled_pairs,
        "consecutive_read_delta_s": {
            "daylight": {"n": len(deltas_day), "p50": pctl(deltas_day, .5), "p90": pctl(deltas_day, .9),
                         "p99": pctl(deltas_day, .99), "max": max(deltas_day) if deltas_day else None},
            "night": {"n": len(deltas_night), "p50": pctl(deltas_night, .5), "p90": pctl(deltas_night, .9),
                      "p99": pctl(deltas_night, .99), "max": max(deltas_night) if deltas_night else None},
        },
        "variants": [],
    }
    variants = [("V1 stall veto", "hold the confirmation when the stall detector fired on either read of the confirming pair",
                 veto_stall)]
    for k in (8, 10, 12, 15):
        variants.append((f"V2 pair-consistency {k} s", f"hold when the two confirming reads differ by more than {k} s",
                         (lambda kk: lambda e: abs(e.a.get("pair_difference_s") or 0) > kk)(k)))
    variants.append(("V3 stall veto OR pair-consistency 10 s", "V1 or V2(10 s)",
                     lambda e: veto_stall(e) or abs(e.a.get("pair_difference_s") or 0) > 10))
    for name, desc, f in variants:
        out["variants"].append({"name": name, "rule": desc, "would_hold_candidates": sum(1 for e in cands if f(e)),
                                "would_hold_drift_consistent": sum(1 for e in genuine if f(e)),
                                "held_candidate_ids": [e.idx for e in cands if f(e)],
                                "held_genuine_ids": [e.idx for e in genuine if f(e)]})
    rec = []
    if not bg:
        rec.append("No background correction is in the evidence, so the soak gives no data for or against A3.")
    elif not cands:
        rec.append(f"None of the {len(bg)} background corrections looks like a stale-read false confirmation. A3 stays a "
                   "design hardening item; the soak does not evidence it.")
    else:
        v1 = out["variants"][0]
        if v1["would_hold_candidates"] == len(cands) and v1["would_hold_drift_consistent"] == 0:
            rec.append(f"V1 (stall veto) would have held all {len(cands)} candidate false confirmation(s) and none of the "
                       f"{len(genuine)} drift-consistent background correction(s): it is the minimal rule this evidence supports.")
        else:
            rec.append(f"V1 (stall veto) would have held {v1['would_hold_candidates']}/{len(cands)} candidate(s) and "
                       f"{v1['would_hold_drift_consistent']}/{len(genuine)} drift-consistent correction(s).")
        cand_d = [abs(e.a.get("pair_difference_s") or 0) for e in cands]
        gen_d = [abs(e.a.get("pair_difference_s") or 0) for e in genuine]
        if gen_d and cand_d and min(cand_d) <= max(gen_d):
            rec.append(f"A pair-difference threshold cannot separate the two groups (candidates from {min(cand_d)} s, genuine "
                       f"up to {max(gen_d)} s); prefer the stall-based veto.")
        if cand_d and any(d == 0 for d in cand_d):
            rec.append("At least one candidate has identical confirming reads (e.g. -60/-60): a pair-difference rule alone "
                       "cannot catch it; only the stall flag on the prior read distinguishes it.")
    rec.append("The stall rule fires only when the inverter advances more than 15 s less than NTP between reads (an implied "
               "drift beyond -15 s/min), more than twice the strongest genuine drift measured (-7 s/min at >= 2 kW PV), so a "
               "stall veto delays a genuine correction by at most one read cycle.")
    rec.append("Before adopting any variant, simulate it offline (registry/tests/test_fbd1_liveness.py stale/freeze scenarios "
               "PW1/PW9/PW10 plus a two-freeze replay of the observed pattern) and confirm it does not worsen TOU-boundary "
               "accuracy, as for the original FB-D1 policy decision.")
    out["recommendations"] = rec
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# Area entry point
# ---------------------------------------------------------------------------------------------------------------------------
def analyse(ctx: Ctx) -> dict:
    r = ctx.rules
    ev = ctx.ev
    reads = build_reads(ctx)
    eps = build_episodes(ctx)
    basis_eps = "text/log"
    if not eps:
        eps = counter_episodes(ctx)
        basis_eps = "counter" if eps else "none"
    attach_reads(ctx, eps, reads)
    locks = lock_intervals(ctx)
    for ep in eps:
        lo = (ep.t or ctx.start) - timedelta(seconds=5)
        hi = (ep.t_end or ep.t or ctx.start) + timedelta(seconds=5)
        for a, b, ra, rb in locks:
            if a <= hi and b >= lo:
                ep.lock = (a, b)
                ep.refs.extend([ra, rb])
                break
    ctx.reads = reads
    in_win = [e for e in eps if e.t is not None and ctx.start <= e.t <= ctx.end]
    ctx.episodes = in_win
    for ep in in_win:
        if ep.t_start is not None and ep.kind == "auto":
            classify_pair(ctx, ep)
            if ep.reason:
                policy_check(ctx, ep, in_win)
        elif ep.t is not None:
            d, dbasis, pv = daylight(ctx, ep.t)
            ep.a.update(daylight=d, daylight_basis=dbasis, pv_w=pv)

    verified_c = counter_delta(ev.get("verified_corrections"), ctx.start, ctx.end)
    failed_c = counter_delta(ev.get("failed_corrections"), ctx.start, ctx.end)
    stall_c = counter_delta(ev.get("rtc_stall_count"), ctx.start, ctx.end)
    attempts_c = counter_delta(ev.get("rtc_write_attempts"), ctx.start, ctx.end)
    ep_ver = [e for e in in_win if e.outcome == "verified"]
    ep_fail = [e for e in in_win if e.outcome == "failed"]
    ep_abort = [e for e in in_win if e.outcome == "aborted"]
    ep_manual = [e for e in in_win if e.kind == "manual"]
    text_ev = ev.has("last_correction_result") or any(e.kind.startswith("rtc_") for e in ev.logs)

    # consecutive failures
    run = best_run = 0
    for e in in_win:
        if e.outcome in ("failed", "aborted"):
            run += 1
            best_run = max(best_run, run)
        elif e.outcome == "verified":
            run = 0
    failed_n = max(failed_c.delta or 0, len(ep_fail) + len(ep_abort)) if (failed_c.available or text_ev) else None
    aborts = len(ep_abort)
    lock_durs = [(b - a).total_seconds() for a, b, _, _ in locks if ctx.start <= a <= ctx.end]
    lmax_s = ev.get("correction_lock_max")
    lmax_vals = [as_float(x.raw) for x in (lmax_s.between(ctx.start, ctx.end) if lmax_s else [])]
    lmax_vals = [v for v in lmax_vals if v is not None]
    lage_s = ev.get("correction_lock_age")
    lage_vals = [v for v in (as_float(x.raw) for x in (lage_s.between(ctx.start, ctx.end) if lage_s else [])) if v is not None]
    lock_max = max(lmax_vals + lage_vals + lock_durs, default=None)

    # per day
    daily = []
    for d in ctx.days:
        de = [e for e in in_win if d.start <= e.t < d.end]
        vd = counter_delta(ev.get("verified_corrections"), d.start, d.end)
        fd = counter_delta(ev.get("failed_corrections"), d.start, d.end)
        sd = counter_delta(ev.get("rtc_stall_count"), d.start, d.end)
        daily.append({
            "day": d.label,
            "corrections": len([e for e in de if e.outcome in ("verified", "failed", "aborted")]),
            "verified_counter": vd.delta if vd.available else None,
            "failed_counter": fd.delta if fd.available else None,
            "stalls_counter": sd.delta if sd.available else None,
            "aborts": len([e for e in de if e.outcome == "aborted"]),
            "night_background": len([e for e in de if e.reason == "background" and e.a.get("daylight") is False]),
            "stale_candidates": len([e for e in de if e.a.get("classification") in ("stale_first_read_candidate",
                                                                                   "false_confirmation_candidate")]),
        })
    hours = [0] * 24
    for e in in_win:
        hours[to_local(e.t).hour] += 1
    by_reason = {}
    for e in in_win:
        by_reason[e.reason or e.kind] = by_reason.get(e.reason or e.kind, 0) + 1
    night_bg = [e for e in in_win if e.reason == "background" and e.a.get("daylight") is False]
    cands = [e for e in in_win if e.a.get("classification") in ("stale_first_read_candidate", "false_confirmation_candidate")]
    noops = [e for e in in_win if e.a.get("suspected_noop")]
    violations = [e for e in in_win if e.a.get("policy", {}).get("result") == "violation"]
    pol_warn = [e for e in in_win if e.a.get("policy", {}).get("result") in ("warning", "unknown")]

    for e in ep_fail + ep_abort:
        ctx.event(e.t_end or e.t, "rtc", "WARNING", f"correction-{e.outcome}",
                  f"RTC correction #{e.idx} {e.outcome}" + (f" ({e.a.get('failure')})" if e.a.get("failure") else "") +
                  (f", breaker after {e.a['breaker_held_s']} s" if e.a.get("breaker_held_s") else ""), CONFIRMED, e.refs[:6])
    for e in violations:
        bad = [c for c in e.a["policy"]["checks"] if c["result"] == "violation"]
        ctx.event(e.t_start, "rtc", "FAIL", "policy-violation",
                  f"correction #{e.idx} ({e.reason}, {e.err:+d} s) outside the FB-D1 policy: " +
                  "; ".join(f"{c['check']}: {c['detail']}" for c in bad), CONFIRMED, e.refs[:6])
    for e in cands:
        ctx.event(e.t_start, "rtc", "WARNING", e.a["classification"].replace("_", "-"),
                  f"background correction #{e.idx} confirmed by reads {e.a['prior_read']['error_s']:+d}/"
                  f"{e.a['queue_read']['error_s']:+d} s against a trend of {e.a.get('trend_error_s', 0):+.0f} s"
                  + (" (suspected no-op)" if e.a.get("suspected_noop") else ""), INFERRED, e.refs[:6],
                  facts=e.a.get("facts", []))
    for e in ep_manual:
        ctx.event(e.t, "rtc", "WARNING", "manual-correction", f"manual RTC correction #{e.idx} during the soak", CONFIRMED, e.refs[:4])

    crit = []
    # C-RTC-1
    reasons = []
    if failed_n is None:
        v, basis = INSUFFICIENT, NONE
        reasons.append("neither the Failed Corrections counter nor correction results / logs are in the evidence")
    else:
        basis = CONFIRMED
        if failed_c.available:
            reasons.append(f"Failed Corrections Since Boot +{int(failed_c.delta or 0)} in the window"
                           + ("" if failed_c.spans_window else " (counter evidence does not span the window: lower bound)"))
        else:
            reasons.append("Failed Corrections counter unavailable: failures counted from result text / logs only")
        reasons.append(f"{len(ep_fail)} failed, {aborts} aborted (deadline breaker) episode(s); longest failure run {best_run}")
        if failed_n >= r.failed_corrections_fail or best_run >= r.consecutive_failures_fail or aborts >= r.aborts_fail:
            v = FAIL
        elif failed_n > 0 or aborts > 0:
            v = WARNING
        elif not failed_c.available or not failed_c.spans_window:
            v = INSUFFICIENT
            reasons.append("zero failures seen, but the counter does not cover the whole window: a confirmed zero needs it")
        else:
            v = PASS
    crit.append(Criterion("C-RTC-1", "rtc", "No failed or aborted RTC corrections", v, basis,
                          f"{failed_n if failed_n is not None else 'unknown'} failed correction(s), {aborts} abort(s)", True, reasons,
                          {"failed_counter_delta": failed_c.delta, "failed_episodes": len(ep_fail), "aborts": aborts,
                           "longest_failure_run": best_run},
                          [ref for e in ep_fail + ep_abort for ref in e.refs[:2]]))
    # C-RTC-2
    reasons = []
    auto = [e for e in in_win if e.kind == "auto"]
    if violations:
        v = FAIL
        reasons.append(f"{len(violations)} correction(s) outside the policy: " + ", ".join(f"#{e.idx}" for e in violations[:10]))
    elif not text_ev and not verified_c.available:
        v = INSUFFICIENT
        reasons.append("no correction evidence at all (no result text, no log, no counter)")
    elif auto and all(e.reason is None for e in auto):
        v = INSUFFICIENT
        reasons.append(f"the policy reason of the {len(auto)} correction(s) is not in the evidence (no `Automatic correction "
                       "queued (<reason>)` result text and no `RTC policy:` log line)")
    elif basis_eps == "counter":
        v = INSUFFICIENT
        reasons.append(f"{len(eps)} correction(s) known only from counters; no queue text or log to check them against")
    elif ep_manual or pol_warn:
        v = WARNING
        if ep_manual:
            reasons.append(f"{len(ep_manual)} manual correction(s) during the soak")
        if pol_warn:
            reasons.append(f"{len(pol_warn)} correction(s) could not be fully checked or sit on a window edge: "
                           + ", ".join(f"#{e.idx}" for e in pol_warn[:10]))
    else:
        v = PASS
        reasons.append(f"all {len(auto)} automatic correction(s) consistent with the policy" if auto else
                       "no automatic correction was queued in the window (result text / logs present)")
    crit.append(Criterion("C-RTC-2", "rtc", "Automatic corrections follow the FB-D1 policy", v,
                          CONFIRMED if (violations or (v == PASS)) else (NONE if v == INSUFFICIENT else MIXED),
                          f"{len(auto)} automatic correction(s): " + ", ".join(f"{k} {n}" for k, n in sorted(by_reason.items())),
                          True, reasons, {"by_reason": by_reason, "violations": len(violations), "unchecked_or_edge": len(pol_warn),
                                          "manual": len(ep_manual)}, [ref for e in violations for ref in e.refs[:2]]))
    # C-RTC-3
    reasons = []
    n_days = ctx.window_s / 86400
    per_day = [x["corrections"] for x in daily]
    if verified_c.available:
        per_day_c = [x["verified_counter"] or 0 for x in daily]
        per_day = [max(a, b) for a, b in zip(per_day, per_day_c)]
    # a rate per 24 h, so a partial soak day (or a short analysis window) is judged on the same scale; pieces under 1 h are
    # too short to extrapolate and keep their raw count
    rates = [n / (d.seconds / 86400) if d.seconds >= 3600 else float(n) for n, d in zip(per_day, ctx.days)]
    worst_day = round(max(rates, default=0.0), 1)
    if lock_max is None and not text_ev and not verified_c.available:
        v, basis = INSUFFICIENT, NONE
        reasons.append("no correction rate or lock-age evidence")
    else:
        basis = CONFIRMED
        v = PASS
        if worst_day > r.corrections_per_day_fail:
            v = FAIL
        elif worst_day > r.corrections_per_day_warn:
            v = WARNING
        reasons.append(f"highest rate {num(worst_day)} correction(s) per 24 h (warn > {r.corrections_per_day_warn}, fail > "
                       f"{r.corrections_per_day_fail})")
        if lock_max is None:
            v = INSUFFICIENT if v == PASS else v
            reasons.append("RTC correction lock age is not in the evidence")
        else:
            if lock_max > r.correction_lock_fail_s:
                v = FAIL
            elif lock_max > r.correction_lock_warn_s and v == PASS:
                v = WARNING
            reasons.append(f"longest RTC correction lock {lock_max:.0f} s (warn > {r.correction_lock_warn_s:.0f} s, fail > "
                           f"{r.correction_lock_fail_s:.0f} s; the breaker releases at 90 s)")
    crit.append(Criterion("C-RTC-3", "rtc", "Correction rate and lock hold bounded", v, basis,
                          f"{sum(per_day)} correction(s) in {n_days:.2f} day(s); lock max "
                          f"{'n/a' if lock_max is None else f'{lock_max:.0f} s'}", True, reasons,
                          {"per_day": per_day, "max_rate_per_24h": worst_day, "lock_max_s": lock_max}))
    # C-RTC-4 stale-read false confirmations (A3 evidence)
    bg = [e for e in in_win if e.reason == "background"]
    undetermined = [e for e in bg if e.a.get("classification") == "undetermined"]
    reasons = []
    if cands:
        v, basis = WARNING, INFERRED
        reasons.append(f"{len(cands)} of {len(bg)} background correction(s) look like stale-read false confirmations "
                       f"({sum(1 for e in cands if e.a['classification'] == 'stale_first_read_candidate')} with a stall on the "
                       f"first read); {len(noops)} suspected no-op(s); {len(night_bg)} background correction(s) at night")
    elif bg and len(undetermined) == len(bg):
        v, basis = INSUFFICIENT, NONE
        reasons.append("background corrections happened but their confirming reads are not in the evidence")
    elif not bg and not (text_ev or verified_c.available):
        v, basis = INSUFFICIENT, NONE
        reasons.append("no correction evidence")
    else:
        v, basis = PASS, INFERRED
        reasons.append(f"{len(bg)} background correction(s), none with a stale-read signature" if bg else
                       "no background correction in the window")
    crit.append(Criterion("C-RTC-4", "rtc", "No stale-read false confirmations (A3 watch item)", v, basis,
                          f"{len(cands)} candidate(s), {len(noops)} suspected no-op(s)", False, reasons,
                          {"background": len(bg), "candidates": len(cands), "suspected_noops": len(noops),
                           "night_background": len(night_bg), "undetermined": len(undetermined)},
                          [ref for e in cands for ref in e.refs[:2]]))

    # stalls (area 2)
    stall_logs = [e for e in ev.logs if e.kind == "rtc_stall" and ctx.start <= e.t <= ctx.end]
    sd = ev.get("rtc_stall_detected")
    bin_on = [x for x in (sd.between(ctx.start, ctx.end) if sd else []) if as_bool(x.raw)]
    stall_reads = [z for z in reads if ctx.start <= z.t <= ctx.end and (z.stall or z.computed_stall)]
    frozen = [z for z in reads if ctx.start <= z.t <= ctx.end and z.inv_adv is not None and z.ntp_adv and z.ntp_adv >= 45
              and abs(z.inv_adv) <= 2]
    stall_events = []
    reg = _regular(reads)
    for z in stall_reads:
        i = reg.index(z) if z in reg else None
        before = reg[i - 1] if (i is not None and i >= 1) else None
        after = reg[i + 1] if (i is not None and i + 1 < len(reg)) else None
        linked = next((e for e in in_win if e.reason == "background" and e.t_start and
                       0 <= (e.t_start - z.t).total_seconds() <= 90), None)
        stall_events.append({"time": stamp(z.t), "error_s": z.err, "before_s": before.err if before else None,
                             "after_s": after.err if after else None, "detector": z.stall, "detector_basis": z.stall_basis,
                             "computed": z.computed_stall, "inverter_advance_s": z.inv_adv, "ntp_advance_s": z.ntp_adv,
                             "followed_by_background_correction": linked.idx if linked else None, "ref": z.ref})
    stall_n_sources = {"counter": stall_c.delta if stall_c.available else None, "log_lines": len(stall_logs) if ev.logs else None,
                       "binary_on_rows": len(bin_on) if sd else None, "stall_reads": len(stall_reads)}
    reasons = []
    if not (stall_c.available or ev.logs or sd):
        v, basis = INSUFFICIENT, NONE
        reasons.append("no RTC Stall Count, no RTC Stall Detected rows and no firmware log")
    else:
        basis = CONFIRMED
        v = PASS
        if stall_c.available and ev.logs and stall_c.spans_window and (stall_c.delta or 0) < len(stall_logs):
            v = WARNING
            reasons.append("the stall counter rose less than the number of STALL log lines")
        linked = [s for s in stall_events if s["followed_by_background_correction"]]
        if linked:
            v = WARNING
            reasons.append(f"{len(linked)} stall(s) followed within 90 s by a background correction (see C-RTC-4)")
        reasons.append(f"stalls: counter {num(stall_n_sources['counter'])}, log lines {stall_n_sources['log_lines']}, binary "
                       f"on-rows {stall_n_sources['binary_on_rows']}; repeated (frozen) reads {len(frozen)}")
    crit.append(Criterion("C-RTC-5", "rtc", "RTC stall detection observed and accounted", v, basis,
                          f"{num(stall_n_sources['counter']) if stall_c.available else len(stall_reads)} stall(s)", False, reasons,
                          stall_n_sources))

    a3 = a3_what_if(ctx, in_win, reads)
    pw = precision_windows(ctx, reads, in_win)
    durations = [(e.t_end - e.t_start).total_seconds() for e in in_win if e.t_start and e.t_end]
    return {
        "criteria": crit,
        "a3": a3,
        "area": {
            "episode_basis": basis_eps,
            "counters": {"verified": _cd(verified_c), "failed": _cd(failed_c), "stalls": _cd(stall_c), "write_attempts": _cd(attempts_c)},
            "episodes_in_window": len(in_win),
            "verified": len(ep_ver), "failed": len(ep_fail), "aborted": aborts, "manual": len(ep_manual),
            "incomplete": len([e for e in in_win if e.outcome in ("incomplete", "superseded")]),
            "by_reason": by_reason,
            "per_local_hour": hours,
            "night_vs_daylight": {
                "daylight": len([e for e in in_win if e.a.get("daylight") is True]),
                "night": len([e for e in in_win if e.a.get("daylight") is False]),
                "night_background": len(night_bg),
                "basis": "pv" if ev.has("pv_power") else "clock (no PV evidence; inferred)",
            },
            "duration_s": {"median": statistics.median(durations) if durations else None, "max": max(durations, default=None)},
            "lock": {"max_s": lock_max, "intervals": len(lock_durs), "longest_interval_s": max(lock_durs, default=None),
                     "max_since_boot_sensor_s": max(lmax_vals, default=None)},
            "reads": {"total": len([z for z in reads if ctx.start <= z.t <= ctx.end]),
                      "from_log": len([z for z in reads if z.src == "log"]),
                      "from_ha": len([z for z in reads if z.src == "ha"]),
                      "inferred_from_inverter_time": len([z for z in reads if z.src == "ha-inferred"]),
                      "max_abs_error_s": max((abs(z.err) for z in reads if z.err is not None and ctx.start <= z.t <= ctx.end
                                              and not z.verify), default=None)},
            "stalls": {"sources": stall_n_sources, "repeated_frozen_reads": len(frozen), "events": stall_events[:200]},
            "precision_windows": pw,
            "episodes": [_ep_dict(e) for e in in_win],
            "daily": daily,
        },
    }


def _cd(c) -> dict:
    return {"available": c.available, "delta": c.delta, "spans_window": c.spans_window, "resets": len(c.resets), "note": c.note}


def _ep_dict(e: Episode) -> dict:
    return {"id": e.idx, "start": stamp(e.t_start), "end": stamp(e.t_end), "kind": e.kind, "reason": e.reason,
            "error_s": e.err, "threshold_logged_s": e.thr_logged, "attempts": e.attempts or len(e.acks), "retries": e.retries,
            "write_errors": e.write_errors, "deferred": e.deferred, "outcome": e.outcome, "residual_s": e.residual,
            "duration_s": (e.t_end - e.t_start).total_seconds() if (e.t_start and e.t_end) else None,
            "lock_s": (e.lock[1] - e.lock[0]).total_seconds() if e.lock else None,
            "sources": sorted(e.sources), "analysis": e.a, "refs": e.refs[:10]}


__all__ = ["analyse", "build_reads", "build_episodes", "parse_result", "RESULT_PATTERNS"]
