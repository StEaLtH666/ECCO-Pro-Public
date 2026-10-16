"""Synthetic FB-D1 soak evidence for tools/tests/test_fbd1_soak_analyser.py (test-only, no I/O).

`Dongle` writes the Home Assistant rows a healthy ECCO clock dongle would produce, minute by minute, with HA's
record-on-change behaviour, and lets a scenario add exactly the events it is about (stale reads, corrections, failures,
restarts, B10 interruptions, gaps, malformed rows). Every scenario keeps its own ground truth (`truth`) computed from what it
put in, so the tests compare the analyser with numbers that were never produced by the analyser.

Entity ids use the public slug `ecco_clock_dongle_*`, optionally behind an area prefix (as a real installation may have).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
START = datetime(2026, 10, 4, 22, 14, 37, tzinfo=UTC)  # 2026-10-04 23:14:37 BST
B10_MATCH = "m=MATCH;dx=00000;cx=000;ox=00000;ix=00;eh=-;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=F;elig=Y;ew=-"
B10_IO = "m=PAUSED_IO;dx=-;cx=-;ox=-;ix=-;eh=-;obl=FP:CR,DP:CR,R4:CR,BUS:BY;ca=F;elig=Y;ew=-"
B10_UNKNOWN = "m=UNKNOWN;dx=-;cx=-;ox=-;ix=-;eh=-;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=P;elig=Y;ew=-"
B10_DRIFT = "m=DRIFT;dx=00004;cx=000;ox=00000;ix=00;eh=-;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=F;elig=Y;ew=-"
TOU = ("00:25", "00:30", "05:30", "12:00", "16:35", "22:00")

ENT = {  # key -> (domain, object-id suffix)
    "clock_difference": ("sensor", "clock_difference"), "inverter_time": ("sensor", "inverter_time"),
    "ntp_time": ("sensor", "ntp_time"), "verified_corrections": ("sensor", "verified_corrections_since_boot"),
    "rtc_write_attempts": ("sensor", "rtc_write_attempts_since_boot"), "failed_corrections": ("sensor", "failed_corrections_since_boot"),
    "rtc_stall_count": ("sensor", "rtc_stall_count"), "rtc_stall_detected": ("binary_sensor", "rtc_stall_detected"),
    "rtc_correction_in_progress": ("binary_sensor", "rtc_correction_in_progress"), "last_correction": ("sensor", "last_correction"),
    "last_correction_result": ("sensor", "last_correction_result"),
    "correction_lock_max": ("sensor", "ecco_rtc_correction_lock_max_age_since_boot"),
    "correction_threshold": ("number", "clock_correction_threshold"), "automatic_clock_sync": ("switch", "automatic_clock_sync"),
    "telemetry_failures": ("sensor", "telemetry_read_failures_since_boot"),
    "configuration_failures": ("sensor", "configuration_read_failures_since_boot"),
    "telemetry_online": ("binary_sensor", "telemetry_online"), "configuration_online": ("binary_sensor", "configuration_online"),
    "last_telemetry_update": ("sensor", "last_telemetry_update"), "last_configuration_update": ("sensor", "last_configuration_update"),
    "write_lock_max": ("sensor", "ecco_modbus_write_lock_max_age_since_boot"),
    "b10": ("sensor", "ecco_fallback_profile_live_match"), "profile_state": ("sensor", "ecco_fallback_profile_state"),
    "supervision_state": ("sensor", "ecco_supervision_state"), "supervision_challenge": ("sensor", "ecco_supervision_challenge"),
    "valid_heartbeats": ("sensor", "ecco_supervision_valid_heartbeat_count"),
    "suspect_events": ("sensor", "ecco_supervision_suspect_events"), "lost_events": ("sensor", "ecco_supervision_lost_events"),
    "manual_write_attempts": ("sensor", "manual_configuration_write_attempts_since_boot"),
    "manual_write_failures": ("sensor", "manual_configuration_write_failures_since_boot"),
    "fp_start_attempts": ("sensor", "free_power_start_attempts_since_boot"),
    "dtg_start_attempts": ("sensor", "dump_to_grid_start_attempts_since_boot"),
    "free_power_active": ("binary_sensor", "free_power_active"), "dump_active": ("binary_sensor", "dump_to_grid_active"),
    "free_power_op": ("binary_sensor", "free_power_operation_in_progress"),
    "dump_op": ("binary_sensor", "dump_to_grid_operation_in_progress"),
    "manual_write_in_progress": ("binary_sensor", "manual_write_in_progress"),
    "pv_power": ("sensor", "ecco_pv_power"),
    **{f"tou{i}_time": ("sensor", f"ecco_timezone{i}_time") for i in range(1, 7)},
}
COUNTERS = ("verified_corrections", "rtc_write_attempts", "failed_corrections", "rtc_stall_count", "telemetry_failures",
            "configuration_failures", "valid_heartbeats", "suspect_events", "lost_events", "manual_write_attempts",
            "manual_write_failures", "fp_start_attempts", "dtg_start_attempts")


def london(t: datetime) -> datetime:
    """Naive Europe/London wall time (BST throughout October 2026 up to the 25th; GMT after)."""
    bst = datetime(2026, 3, 29, 1, tzinfo=UTC) <= t < datetime(2026, 10, 25, 1, tzinfo=UTC)
    return (t + timedelta(hours=1 if bst else 0)).replace(tzinfo=None)


def utc_of_bst(y, mo, d, h, mi, s=0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC) - timedelta(hours=1)


def lstr(t: datetime) -> str:
    return london(t).strftime("%Y-%m-%d %H:%M:%S")


class Dongle:
    def __init__(self, start: datetime = START, hours: float = 168.0, *, prefix: str = "", offset: float = -6.0,
                 nonce: str = "62CEE2AF", pv_day_w: float = 400.0, pv_mid_w: float = 2500.0, threshold: float = 20.0,
                 telemetry_period_s: int = 60, boot_before_s: int = 120):
        self.start = start
        self.end = start + timedelta(hours=hours)
        self.prefix = prefix
        self.rows: dict = {}
        self.extra: list = []  # raw malformed / foreign rows appended to the export as-is
        self.offset = float(offset)
        self.drift = {}  # minute index -> s/min applied after that read
        self.stale = {}  # read time -> displayed error override
        self.offset_at = {}  # read time -> true offset set just before that read
        self.plans = {}  # read time -> correction plan dict
        self.nonce = nonce
        self.gen = 1
        self.counters = {k: 0 for k in COUNTERS}
        self.truth = {"corrections": [], "stalls": 0, "restarts": [], "b10_nonmatch": []}
        self.prev_disp = None
        self.prev_read_t = None
        self.pv_day_w, self.pv_mid_w = pv_day_w, pv_mid_w
        self.threshold = threshold
        self.telemetry_period_s = telemetry_period_s
        self.b10_windows = []  # (a, b, text)
        self.unavailable = []  # (a, b)
        self.restart_at = []  # boot times
        self.boot_t = start - timedelta(seconds=boot_before_s)
        self.cfg_skip = []  # (a, b) Block B failing
        self.seed_state()

    # ---------------------------------------------------------------- rows
    def eid(self, key: str) -> str:
        d, s = ENT[key]
        return f"{d}.{self.prefix}ecco_clock_dongle_{s}"

    def put(self, key: str, t: datetime, state, force: bool = False) -> None:
        """Record that the dongle published `state` at `t` (HA's drop-unchanged behaviour is applied at export)."""
        self.rows.setdefault(self.eid(key), []).append((t, str(state)))

    def history(self, eid: str) -> list:
        """The rows Home Assistant keeps for one entity: time order, consecutive identical states collapsed."""
        out = []
        for t, st in sorted(self.rows[eid], key=lambda r: r[0]):
            if out and out[-1][1] == st:
                continue
            out.append((t, st))
        return out

    def seed_state(self) -> None:
        t = self.boot_t
        for k in COUNTERS:
            self.put(k, t, 0)
        for k in ("rtc_stall_detected", "rtc_correction_in_progress", "free_power_active", "dump_active", "free_power_op",
                  "dump_op", "manual_write_in_progress"):
            self.put(k, t, "off")
        self.put("configuration_online", t, "on")
        self.put("telemetry_online", t, "on")
        self.put("last_correction", t, "Never")
        self.put("last_correction_result", t, "None since boot")
        self.put("correction_lock_max", t, 0)
        self.put("write_lock_max", t, 2)
        self.put("correction_threshold", t, self.threshold)
        self.put("automatic_clock_sync", t, "on")
        self.put("supervision_state", t, "SUPERVISED")
        self.put("profile_state", t, "VALID")
        self.put("b10", t, B10_MATCH)
        for i, z in enumerate(TOU, 1):
            self.put(f"tou{i}_time", t, z)
        self.put("supervision_challenge", t, f"{self.nonce}-{self.gen}")

    def bump(self, key: str, t: datetime, n: int = 1) -> None:
        self.counters[key] += n
        # the dongle publishes its counters every 60 s
        tp = t.replace(microsecond=0) + timedelta(seconds=60 - t.second % 60 if t.second % 60 else 0)
        self.put(key, tp, self.counters[key])

    # ---------------------------------------------------------------- scenario API
    def at_bst(self, day_offset: int, h: int, m: int, s: int = 20) -> datetime:
        """The read instant `h:m:s` BST on (soak start date + day_offset)."""
        d = london(self.start).date() + timedelta(days=day_offset)
        return utc_of_bst(d.year, d.month, d.day, h, m, s)

    def stale_read(self, t: datetime, displayed: int) -> None:
        self.stale[t] = displayed

    def correction(self, t: datetime, reason: str, *, residual: int = -3, outcome: str = "verified", recovery_s: int = 31,
                   lock_s: int = 11, attempts: int = 1, err: int | None = None, verify_errs=(), label: str = "") -> None:
        self.plans[t] = dict(reason=reason, residual=residual, outcome=outcome, recovery_s=recovery_s, lock_s=lock_s,
                             attempts=attempts, err=err, verify_errs=tuple(verify_errs), label=label)

    def set_offset(self, t: datetime, offset_s: float) -> None:
        self.offset_at[t] = offset_s

    def set_drift(self, t: datetime, rate_s_per_min: float) -> None:
        self.drift[t] = rate_s_per_min

    def b10(self, a: datetime, b: datetime, text: str = B10_DRIFT) -> None:
        self.b10_windows.append((a, b, text))
        self.truth["b10_nonmatch"].append((a, b, text))

    def restart(self, t: datetime, nonce: str = "9B71D224") -> None:
        self.restart_at.append((t, nonce))

    def block_b_outage(self, a: datetime, b: datetime) -> None:
        self.cfg_skip.append((a, b))

    # ---------------------------------------------------------------- run
    def run(self) -> "Dongle":
        t0 = self.start.replace(second=0, microsecond=0) - timedelta(minutes=3)
        t = t0
        rate = 0.0
        boots = sorted(self.restart_at)
        hb_next = t0
        while t <= self.end + timedelta(minutes=2):
            # restarts
            while boots and boots[0][0] <= t:
                bt, nonce = boots.pop(0)
                self._do_restart(bt, nonce)
            # periodic witnesses
            if t >= hb_next:
                self.gen += 1
                self.put("supervision_challenge", t + timedelta(seconds=7), f"{self.nonce}-{self.gen}")
                self.bump("valid_heartbeats", t + timedelta(seconds=7))
                hb_next = t + timedelta(seconds=120)
            self.put("ntp_time", t, lstr(t))
            tt = t + timedelta(seconds=40)
            if not any(a <= tt < b for a, b in self.cfg_skip):
                self.put("last_configuration_update", tt, lstr(tt))
            if self.telemetry_period_s:
                k = 0
                while k < 60:
                    ts = t + timedelta(seconds=5 + k)
                    self.put("last_telemetry_update", ts, lstr(ts))
                    k += self.telemetry_period_s
            if t.minute == 0:
                lt = london(t)
                pv = 0.0 if not (7 <= lt.hour < 19) else (self.pv_mid_w if 11 <= lt.hour < 15 else self.pv_day_w)
                self.put("pv_power", t, int(pv))
            # the regular RTC read at :20
            tr = t + timedelta(seconds=20)
            if tr in self.drift:
                rate = self.drift[tr]
            if tr in self.offset_at:
                self.offset = float(self.offset_at[tr])
            self._read(tr)
            self.offset += rate
            t += timedelta(minutes=1)
        # B10 interruptions planned by the scenario
        for a, b, text in self.b10_windows:
            self.put("b10", a, text, force=True)
            self.put("b10", b, B10_MATCH, force=True)
        return self

    def _read(self, tr: datetime) -> None:
        true_err = int(round(self.offset))
        disp = self.stale.get(tr, true_err)
        self.put("inverter_time", tr, lstr(tr + timedelta(seconds=disp)), force=True)
        self.put("clock_difference", tr, disp)
        if self.prev_read_t is not None and self.prev_disp is not None:
            ntp_adv = (tr - self.prev_read_t).total_seconds()
            if 45 <= ntp_adv <= 90:
                inv_adv = ntp_adv + (disp - self.prev_disp)
                stalled = inv_adv < ntp_adv - 15
                self.put("rtc_stall_detected", tr, "on" if stalled else "off")
                if stalled:
                    self.truth["stalls"] += 1
                    self.bump("rtc_stall_count", tr)
        self.prev_disp, self.prev_read_t = disp, tr
        plan = self.plans.get(tr)
        if plan:
            self._correct(tr, disp, plan)

    def _correct(self, tq: datetime, disp: int, p: dict) -> None:
        err = p["err"] if p["err"] is not None else disp
        self.put("last_correction_result", tq, f"Automatic correction queued ({p['reason']}) - error {err} s")
        self.put("rtc_correction_in_progress", tq, "on")
        self.put("b10", tq + timedelta(seconds=1), B10_UNKNOWN, force=True)
        t = tq
        outcome = p["outcome"]
        end = tq + timedelta(seconds=p["lock_s"])
        for n in range(1, p["attempts"] + 1):
            ta = t + timedelta(seconds=1)
            self.bump("rtc_write_attempts", ta)
            if outcome == "aborted":
                break
            self.put("last_correction_result", ta, f"Write acknowledged - verifying attempt {n}")
            tv = ta + timedelta(seconds=10)
            verr = p["verify_errs"][n - 1] if n - 1 < len(p["verify_errs"]) else p["residual"]
            self.put("inverter_time", tv, lstr(tv + timedelta(seconds=verr)), force=True)
            self.put("clock_difference", tv, verr)
            if outcome == "failed" and n < p["attempts"]:
                self.put("last_correction_result", tv, f"Verification failed ({verr} s) - retry {n} queued")
            t = tv
            end = tv
        if outcome == "verified":
            self.put("last_correction_result", end, f"Verified OK - error now {p['residual']} s")
            self.put("last_correction", end, lstr(end))
            self.bump("verified_corrections", end)
            self.offset = float(p["residual"])
        elif outcome == "failed":
            self.put("last_correction_result", end, f"FAILED after retries - error {p['verify_errs'][-1] if p['verify_errs'] else err} s"
                     " - 5 min cooldown")
            self.bump("failed_corrections", end)
        elif outcome == "aborted":
            end = tq + timedelta(seconds=p["lock_s"])
            self.put("last_correction_result", end, "ABORTED - correction exceeded its deadline - 5 min cooldown")
            self.bump("failed_corrections", end)
        self.put("rtc_correction_in_progress", end, "off")
        if p["lock_s"] > self.counters.get("_lock_max", 0):
            self.counters["_lock_max"] = p["lock_s"]
            self.put("correction_lock_max", end + timedelta(seconds=30), p["lock_s"])
        self.put("b10", end + timedelta(seconds=p["recovery_s"]), B10_MATCH, force=True)
        self.prev_disp = None  # the firmware re-bases: the next read has no stall baseline
        self.truth["corrections"].append(dict(p, t=tq, end=end, err=err))

    def _do_restart(self, bt: datetime, nonce: str) -> None:
        down = bt - timedelta(seconds=25)
        up = bt + timedelta(seconds=5)
        for eid in self.rows:  # nothing is published while the dongle is down
            self.rows[eid] = [r for r in self.rows[eid] if not (down < r[0] < up)]
        for key in ("ntp_time", "inverter_time", "b10", "supervision_challenge", "valid_heartbeats", "last_configuration_update"):
            self.put(key, down, "unavailable", force=True)
        self.nonce, self.gen = nonce, 1
        for k in COUNTERS:
            self.counters[k] = 0
            self.put(k, bt + timedelta(seconds=5), 0, force=True)
        self.put("last_correction_result", bt + timedelta(seconds=5), "None since boot", force=True)
        self.put("supervision_state", bt + timedelta(seconds=5), "STARTUP", force=True)
        self.put("supervision_state", bt + timedelta(seconds=60), "SUPERVISED", force=True)
        self.put("supervision_challenge", bt + timedelta(seconds=5), f"{nonce}-1", force=True)
        self.put("b10", bt + timedelta(seconds=5), B10_UNKNOWN, force=True)
        self.put("b10", bt + timedelta(seconds=110), B10_MATCH, force=True)
        self.truth["restarts"].append(bt)
        self.prev_disp = None

    # ---------------------------------------------------------------- export
    def drop(self, a: datetime, b: datetime, keys=None) -> None:
        """Simulate Home Assistant recording nothing in [a, b) (for all entities, or only `keys`)."""
        ids = None if keys is None else {self.eid(k) for k in keys}
        for eid, lst in self.rows.items():
            if ids is None or eid in ids:
                self.rows[eid] = [r for r in lst if not (a <= r[0] < b)]

    def only(self, keys) -> None:
        ids = {self.eid(k) for k in keys}
        self.rows = {e: r for e, r in self.rows.items() if e in ids}

    def without(self, keys) -> None:
        ids = {self.eid(k) for k in keys}
        self.rows = {e: r for e, r in self.rows.items() if e not in ids}

    def ha_history(self, minimal: bool = True) -> list:
        """The REST /api/history/period shape: one list per entity, the first row with entity_id, later rows minimal."""
        out = []
        for eid in sorted(self.rows):
            lst = self.history(eid)
            if not lst:
                continue
            block = []
            for i, (t, st) in enumerate(lst):
                iso = t.isoformat()
                if i == 0 or not minimal:
                    block.append({"entity_id": eid, "state": st, "last_changed": iso, "last_updated": iso, "attributes": {}})
                else:
                    block.append({"state": st, "last_changed": iso})
            out.append(block)
        out.extend(self.extra)
        return out

    def ws_history(self) -> dict:
        """The websocket history/history_during_period compressed shape."""
        out = {}
        for eid in sorted(self.rows):
            out[eid] = [{"s": st, "lu": t.timestamp()} for t, st in self.history(eid)]
        return {"id": 3, "type": "result", "success": True, "result": out}

    def long_csv(self) -> str:
        lines = ["entity_id,state,last_changed"]
        for eid in sorted(self.rows):
            for t, st in self.history(eid):
                v = f'"{st}"' if ("," in st or '"' in st) else st
                lines.append(f"{eid},{v},{t.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z")
        return "\n".join(lines) + "\n"
