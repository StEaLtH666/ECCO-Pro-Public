"""The closed-loop bench: telemetry and command channels, a model of the dongle's lease engine (the firmware side) and a model of the
Home Assistant planner host, wired around the plant and ONE kernel module.

REFERENCE MODEL AND TEST BENCH. NOT PRODUCTION CODE. Not wired to Home Assistant, the dongle, the inverter or any register; stdlib
only; deterministic (seeded); it writes nothing outside its own return value. The dongle model is a MODEL of what the firmware does
(the Dump loop is the proven one; the charge lease follows the GRC design; the one-owner arbiter and the raise-only Stop SOC are the
proposed N6 behaviour); it is not the firmware.

Who does what in the bench:
  * Home Assistant (the HA part of Bench): at every plan tick builds the kernel inputs from what the dongle published (one tick
    late), calls the kernel policy, and sends START / ADJUST / END / RAISE_STOP / PLAN commands through a channel with delay and loss.
    It never writes a register.
  * The dongle (the dongle part of Bench): the only register writer. It owns the lease (one setpoint owner at a time), snapshots the
    registers before the first write, verifies every write by readback, runs the kernel's guards every 15 s tick (they keep running
    with Home Assistant gone), closes the export loop, restores the snapshot (never a computed value) and, at a restart, ends and
    restores any lease (never resumes it).
  * The plant (plant.Plant): physics only.

The kernel is passed in as a module, so the same runs can be repeated with a mutated copy of it (test_sim.py).
"""

from collections import namedtuple
from dataclasses import dataclass, replace
from typing import Optional

import plant as P

TICK = P.DT_S
HA_EXTRA_S = P.DT_S            # Home Assistant sees the dongle's publication one tick late
UNAVAIL_S = 60                 # ASSUMED: the dongle's entities read 'unavailable' after this long without an update
ALERT_AFTER_S = 120            # ASSUMED: Home Assistant alerts the owner when the dongle has been unavailable this long inside a session
RESTORE_ATTEMPTS = 3           # GRC max_restore_attempts: answered restore failures before a FAULT is raised and the owner alerted
KINDS_CHARGE = ("gentle", "charge_fixed")

Row = namedtuple("Row", "t soc read batt grid house pv inv mode slot_w dump_w fp_w lease unserved ac_in reserve imp_ceiling time_ok grid_up")
Write = namedtuple("Write", "t owner lease_id kind reg value ok")
Rec = namedtuple("Rec", "t who policy reason detail wanted write end unreachable explanation")


@dataclass(frozen=True)
class Scenario:
    """The run configuration. Invariants and expectations live in scenarios.py, never here."""
    name: str
    kind: str                                   # gentle | charge_fixed | export
    summary: str = ""
    reqs: tuple = ()
    duration_s: float = 18000.0
    plant: P.PlantParams = P.PlantParams()
    soc0_pct: float = 25.0
    house: P.Series = P.Series([(0.0, 800.0)])
    pv: P.Series = P.Series([(0.0, 0.0)])
    # charge
    window: Optional[tuple] = (0.0, 18000.0)    # the owner's charge window on the inverter's clock (start_s, end_s); None = no window
    table_charges: bool = True                  # the owner's own TOU table charges in that window (Gentle); False for Charge Fixed (Free Power)
    slot_target_pct: Optional[float] = None     # the slot's own target SOC (None = the plan's target): the inverter ends the charge there
    target_soc_pct: float = 90.0                # what the plan must reach
    buffer_s: float = 3600.0                    # the finish-early buffer
    trusted_capacity_kwh: float = 35.0          # the capacity the kernel is told
    original_w: float = 8000.0                  # the slot power before any lease
    owner_rate_w: Optional[float] = None        # Charge Fixed: the owner's requested rate
    # export
    export_start_s: float = 0.0
    target_export_w: float = 2000.0
    stop_soc_pct: float = 20.0
    lease_ceiling_w: float = 3000.0
    max_export_w: Optional[float] = 5000.0
    export_len_s: float = 7200.0
    # limits and the owner's state
    power_ceiling_w: float = 8000.0
    import_ceiling_w: Optional[float] = None
    reserve_pct: float = 20.0
    # Home Assistant and the channels
    plan_s: float = 300.0
    ha_first_s: Optional[float] = None          # the first plan tick (default: one plan period for a charge, one tick for an export)
    cmd_delay_s: float = 0.0
    cmd_loss: frozenset = frozenset()           # indices (from 0) of the Home Assistant commands that never arrive
    tel_gaps: tuple = ()                        # ((t0, t1), ...) the dongle gets no new sample
    trust: tuple = ()                           # ((t0, t1, 'inverter' | 'ntp'), ...) untrusted clock windows
    noise_w: float = 0.0
    seed: int = 1
    events: tuple = ()                          # ((t, name, {args}), ...)
    react_s: float = 120.0                      # the declared reaction bound (tick + command + settle) the floor margin and the invariants use
    boot_s: float = 60.0
    inverter_skew_s: float = 0.0                # the inverter clock error (shifts the owner's window)


@dataclass
class Lease:
    id: int
    kind: str
    owner: str
    snap: dict
    st: object
    obj: object
    lim: object
    start_t: float
    plan_t: float
    soc_start: float
    pending: Optional[tuple] = None       # (t_write, reg, value, kind, pre_ac_w)
    restore_owed: Optional[str] = None
    restore_attempts: int = 0
    end_reason: Optional[str] = None
    end_t: Optional[float] = None
    fault: bool = False
    soc_end: float = 0.0


class Run:
    def __init__(self, sc):
        self.sc = sc
        self.rows = []
        self.writes = []
        self.recs = []
        self.events = []
        self.leases = []
        self.alerts = []
        self.refusals = []
        self.first_unreachable_t = None
        self.first_unreachable_detail = ""
        self.start_cmd_t = None
        self.sent = 0
        self.lost = 0

    def log(self, t, text):
        self.events.append((t, text))


class Bench:
    def __init__(self, sc, K):
        self.sc = sc
        self.K = K
        self.run = Run(sc)
        self.plant = P.Plant(sc.plant, sc.soc0_pct, regs=P.Regs(slot_power_w=sc.original_w), seed=sc.seed)
        # the world and the owner's state
        self.grid_up = True
        self.hold = False
        self.reserve_pct = sc.reserve_pct
        self.import_ceiling_w = sc.import_ceiling_w
        self.power_ceiling_w = sc.power_ceiling_w
        self.max_export_w = sc.max_export_w
        self.slot_target = sc.target_soc_pct if sc.slot_target_pct is None else sc.slot_target_pct
        # channels
        self.queue = []
        self.cmd_seq = 0
        # the dongle
        self.d_up = True
        self.d_dead = False
        self.d_boot_until = None
        self.d_down_since = None
        self.api_connected = True
        self.api_age = 0.0
        self.lease = None
        self.lease_id = 0
        self.night_used = False
        self.last_end_t = None
        self.last_sample_t = None
        self.sample = None
        self.all_leases = []
        self.second = []
        # Home Assistant
        self.ha_down = False
        self.ha_plan_stopped = False
        self.ha_state = None
        self.ha_start_sent_t = None
        self.ha_inflight_until = -1.0
        self.ha_over = False
        self.ha_alerted = False
        self.unavailable_since = None
        self.pending_events = []

    # ------------------------------------------------------------------------------------------------------------------
    # the world
    # ------------------------------------------------------------------------------------------------------------------
    def skew(self, t):
        for (t0, t1, which) in self.sc.trust:
            if which == "inverter" and t0 <= t < t1:
                return max(self.sc.inverter_skew_s, 150.0)
        return self.sc.inverter_skew_s

    def time_ok(self, t):
        for (t0, t1, which) in self.sc.trust:
            if t0 <= t < t1 and (which == "ntp" or self.sc.kind in KINDS_CHARGE):
                return False
        return True

    def env(self, t):
        sc = self.sc
        tm = t + TICK / 2.0
        active = False
        if sc.window is not None and sc.table_charges:
            sk = self.skew(t)
            active = (sc.window[0] + sk) <= tm < (sc.window[1] + sk)
        return P.Env(house_w=sc.house.at(tm), pv_w=sc.pv.at(tm), grid_up=self.grid_up, window_active=active, slot_target_pct=self.slot_target)

    def apply_event(self, t, name, a):
        self.run.log(t, "event " + name + (" " + ",".join("%s=%s" % kv for kv in sorted(a.items())) if a else ""))
        later = self.pending_events
        if name == "grid_loss":
            self.grid_up = False
            later.append((t + a["dur"], "grid_back", {}))
        elif name == "grid_back":
            self.grid_up = True
        elif name == "hold":
            self.hold = True
            if "dur" in a:
                later.append((t + a["dur"], "release_hold", {}))
        elif name == "release_hold":
            self.hold = False
        elif name == "reserve":
            self.reserve_pct = a["pct"]
        elif name == "import_ceiling":
            self.import_ceiling_w = a["w"]
        elif name == "power_ceiling":
            self.power_ceiling_w = a["w"]
        elif name == "max_export":
            self.max_export_w = a["w"]
        elif name == "plant":
            self.plant.p = replace(self.plant.p, **a)
        elif name == "ignore_writes":
            self.plant.write_ignored = a.get("on", True)
        elif name == "dongle_restart":
            self.go_down(t)
            self.d_boot_until = t + a.get("boot_s", self.sc.boot_s)
        elif name == "dongle_dead":
            self.go_down(t)
            self.d_dead = True
            self.d_boot_until = None
            if "dur" in a:
                later.append((t + a["dur"], "dongle_back", {}))
        elif name == "dongle_back":
            self.d_dead = False
            self.d_boot_until = t + self.sc.boot_s
        elif name == "ha_down":
            self.ha_down = True
            self.api_connected = False
            if "dur" in a:
                later.append((t + a["dur"], "ha_back", {}))
        elif name == "ha_back":
            self.ha_down = False
            self.api_connected = True
        elif name == "plan_stop":
            self.ha_plan_stopped = True
            if "dur" in a:
                later.append((t + a["dur"], "plan_resume", {}))
        elif name == "plan_resume":
            self.ha_plan_stopped = False
        elif name == "second_start":
            self.second.append(a)
        else:
            raise ValueError("unknown event " + name)

    def go_down(self, t):
        self.d_up = False
        if self.d_down_since is None:
            self.d_down_since = t
        self.run.log(t, "dongle down")

    # ------------------------------------------------------------------------------------------------------------------
    # telemetry
    # ------------------------------------------------------------------------------------------------------------------
    def in_gap(self, t):
        return any(t0 <= t < t1 for (t0, t1) in self.sc.tel_gaps)

    def take_sample(self, t, m):
        if not self.d_up or self.in_gap(t):
            return
        pl, n = self.plant, self.sc.noise_w
        self.sample = dict(soc=m.soc_reading, batt=pl.noisy(m.batt_w, n), grid=pl.noisy(m.grid_w, n), pv=max(0.0, pl.noisy(m.pv_w, n)), inv=pl.noisy(m.inv_ac_w, n))
        self.last_sample_t = t

    def frame(self, t, extra=0.0):
        K = self.K
        if self.sample is None:
            return K.Frame()
        s = self.sample
        return K.Frame(soc_pct=s["soc"], age_s=t - self.last_sample_t + extra, batt_w=s["batt"], grid_w=s["grid"], pv_w=s["pv"], inv_ac_w=s["inv"])

    # ------------------------------------------------------------------------------------------------------------------
    # commands (Home Assistant -> dongle)
    # ------------------------------------------------------------------------------------------------------------------
    def send(self, t, cmd):
        i = self.cmd_seq
        self.cmd_seq += 1
        self.run.sent += 1
        if i in self.sc.cmd_loss:
            self.run.lost += 1
            self.run.log(t, "command %d (%s) lost in transit" % (i, cmd[0]))
            return
        self.queue.append((t + self.sc.cmd_delay_s, i, cmd))

    def rec(self, t, who, policy, d):
        self.run.recs.append(Rec(t, who, policy, d.reason, d.detail, d.wanted_w, d.write_w, d.end, d.unreachable, d.explanation))
        # a REPORT is any published decision that says the objective cannot be met, from Home Assistant or from the dongle's own guard
        # (the target guard's hand-back is the dongle's: its stop says 'at risk' at once, F02 of the N4 review)
        if d.unreachable and self.run.first_unreachable_t is None:
            self.run.first_unreachable_t = t
            self.run.first_unreachable_detail = d.detail

    def do_write(self, t, lease, reg, value, kind):
        ok = self.plant.write_reg(reg, value)
        self.run.writes.append(Write(t, lease.owner, lease.id, kind, reg, value, ok))
        return ok

    # ------------------------------------------------------------------------------------------------------------------
    # the dongle
    # ------------------------------------------------------------------------------------------------------------------
    def restore(self, t, lease, detail):
        """End the lease: write the snapshot back (never a computed value). A restore is never refused for plan or time-trust reasons."""
        if lease.end_t is not None or lease.restore_owed:
            return
        lease.restore_owed = detail
        self.try_restore(t, lease)

    def try_restore(self, t, lease):
        ok_all = True
        for reg in ("allow_export", "dump_ceiling_w", "fp_rate_w", "slot_power_w"):
            if reg in lease.snap and not self.do_write(t, lease, reg, lease.snap[reg], "restore"):
                ok_all = False
        lease.restore_attempts += 1
        if ok_all:
            lease.end_reason = lease.restore_owed
            lease.end_t = t
            lease.soc_end = self.plant.soc()
            lease.st = self.K.note_end(lease.st)
            lease.restore_owed = None
            self.lease = None
            self.run.log(t, "lease %d (%s) ended: %s" % (lease.id, lease.kind, lease.end_reason))
            self.last_end_t = t
            if lease.end_reason == "target_reached":
                self.ha_over = True          # the target was reached: the night's work is done
            if lease.kind == "gentle":
                self.night_used = True      # GRC: one lease a night. A Charge Fixed (Free Power) session may be started again, after the dwell
        elif lease.restore_attempts >= RESTORE_ATTEMPTS and not lease.fault:
            lease.fault = True
            self.run.alerts.append((t, "FAULT: the restore of lease %d failed %d times (the inverter did not take the value): owner action needed"
                                    % (lease.id, lease.restore_attempts)))

    def refuse(self, t, kind, why):
        self.run.refusals.append((t, kind, why))
        self.run.log(t, "START %s refused: %s" % (kind, why))

    def handle_start(self, t, p):
        K = self.K
        kind = p["kind"]
        f = self.frame(t)
        if self.lease is not None:
            return self.refuse(t, kind, "authority_busy (the setpoint is owned by %s)" % self.lease.owner)
        if not self.grid_up:
            return self.refuse(t, kind, "grid_lost")
        if not self.time_ok(t):
            return self.refuse(t, kind, "time_untrusted")
        if not K.frame_fresh(f, ("soc", "grid")):
            return self.refuse(t, kind, "stale_telemetry")
        if kind == "gentle" and self.night_used:
            return self.refuse(t, kind, "night_used (one lease a night)")
        self.lease_id += 1
        regs = self.plant.regs
        if kind == "gentle":
            first = p["first_w"]
            st = K.note_start(K.State(), t, regs.slot_power_w, p["gain"], regs.slot_power_w if first is None else first, pre_ac_w=K.ac_in_w(f))
            lease = Lease(self.lease_id, kind, p["owner"], {"slot_power_w": regs.slot_power_w}, st, p["obj"], p["lim"], t, t, self.plant.soc())
            self.lease = lease
            self.run.log(t, "lease %d START gentle first=%s original=%s" % (lease.id, first, regs.slot_power_w))
            if first is not None:
                self.do_write(t, lease, "slot_power_w", first, "start")
                lease.pending = (t, "slot_power_w", first, "start", K.ac_in_w(f))
        elif kind == "charge_fixed":
            st = replace(K.State(), phase="active", v_w=p["first_w"], writes=1, last_write_s=t)
            lease = Lease(self.lease_id, kind, p["owner"], {"fp_rate_w": regs.fp_rate_w}, st, p["obj"], p["lim"], t, t, self.plant.soc())
            self.lease = lease
            self.run.log(t, "lease %d START charge_fixed rate=%s" % (lease.id, p["first_w"]))
            self.do_write(t, lease, "fp_rate_w", p["first_w"], "start")
            lease.pending = (t, "fp_rate_w", p["first_w"], "start", None)
        else:
            st = replace(K.State(), phase="active", v_w=p["first_w"], stop_soc_pct=p["stop_soc"], last_update_s=t)
            lease = Lease(self.lease_id, kind, p["owner"], {"allow_export": regs.allow_export, "dump_ceiling_w": regs.dump_ceiling_w},
                          st, p["obj"], p["lim"], t, t, self.plant.soc())
            self.lease = lease
            self.run.log(t, "lease %d START export ceiling=%s stop_soc=%.1f end=%d" % (lease.id, p["first_w"], p["stop_soc"], p["obj"].end_s))
            self.do_write(t, lease, "dump_ceiling_w", p["first_w"], "start")
            self.do_write(t, lease, "allow_export", True, "start")
            lease.pending = (t, "dump_ceiling_w", p["first_w"], "start", None)
        self.all_leases.append(self.lease)

    def handle_command(self, t, cmd):
        K = self.K
        name = cmd[0]
        lease = self.lease
        if name == "START":
            self.handle_start(t, cmd[1])
        elif lease is None:
            return
        elif name == "PLAN":
            lease.plan_t = t
        elif name == "END":
            self.restore(t, lease, cmd[1])
        elif name == "RAISE_STOP":
            if lease.kind == "export" and cmd[1] is not None and cmd[1] > (lease.st.stop_soc_pct or 0.0):
                lease.st = replace(lease.st, stop_soc_pct=cmd[1])
                self.run.log(t, "Stop SOC raised to %.1f (raise-only)" % cmd[1])
        elif name == "ADJUST":
            if lease.kind != "gentle" or lease.pending is not None or lease.restore_owed:
                return
            # a lowered power ceiling is a safety reduction the dongle recognises itself (it never takes Home Assistant's word for it)
            forced = lease.st.v_w is not None and cmd[1] < lease.st.v_w and lease.st.v_w > self.power_ceiling_w + 1e-9
            write, why = K.ramp_charge(lease.st, t, cmd[1], self.power_ceiling_w, forced=forced)
            if write is None:
                self.run.refusals.append((t, "gentle", "ADJUST refused by the lease budget: " + str(why)))
                self.run.log(t, "ADJUST %s refused by the dongle's budget (%s)" % (cmd[1], why))
                return
            kind = "forced" if forced else "change"
            self.do_write(t, lease, "slot_power_w", write, kind)
            lease.pending = (t, "slot_power_w", write, kind, K.ac_in_w(self.frame(t)))

    def verify_pending(self, t, lease):
        """Read the register back: a write counts only when the inverter holds the value (REQ-D3: registers are not behaviour, but a
        mismatch is a failure). Returns False when the lease was sent to its restore."""
        K = self.K
        if lease.pending is None:
            return True
        t_w, reg, value, kind, pre_ac = lease.pending
        lease.pending = None
        got = self.plant.read_reg(reg)
        if got != value:
            self.run.log(t, "readback of %s is %s, %s was written: the write FAILED" % (reg, got, value))
            self.rec(t, "dongle", lease.kind, K.make("stop", "response_failed", end=True))
            self.restore(t, lease, "write_failed")
            return False
        if lease.kind == "gentle" and kind in ("change", "forced"):
            lease.st = K.note_write(lease.st, t_w, value, kind, pre_ac)
        elif lease.kind == "export" and kind == "loop":
            lease.st = K.note_export_write(lease.st, t_w, value)
        return True

    def boot(self, t):
        """A dongle boot: any lease on record is ended and restored, never resumed."""
        self.d_up = True
        self.d_boot_until = None
        self.d_down_since = None
        self.api_age = 0.0
        if self.lease is not None:
            self.run.log(t, "boot found lease %d open: restoring (never resumed)" % self.lease.id)
            self.rec(t, "dongle", self.lease.kind, self.K.make("stop", "restart", end=True))
            self.restore(t, self.lease, "restart")

    def dongle_tick(self, t):
        K = self.K
        if self.d_dead:
            return
        if not self.d_up:
            if self.d_boot_until is None or t < self.d_boot_until:
                return
            self.boot(t)
        if self.api_connected:
            self.api_age = 0.0
        else:
            self.api_age += TICK
            if self.api_age >= K.REBOOT_TIMEOUT_S:
                self.run.log(t, "no API client for %d s: ESPHome restarts the dongle" % K.REBOOT_TIMEOUT_S)
                self.go_down(t)
                self.d_boot_until = t + self.sc.boot_s
                self.api_age = 0.0
                return
        due = sorted([q for q in self.queue if q[0] <= t + 1e-9], key=lambda q: (q[0], q[1]))
        self.queue = [q for q in self.queue if q[0] > t + 1e-9]
        for (_t, _i, cmd) in due:
            self.handle_command(t, cmd)
        while self.second:
            self.handle_start(t, self.second.pop(0))
        lease = self.lease
        if lease is None:
            return
        if lease.restore_owed:
            if not lease.fault:
                self.try_restore(t, lease)
            return
        if not self.verify_pending(t, lease):
            return
        # the owner's Hold and the effective reserve are Home Assistant facts: the dongle learns of them only through END / RAISE_STOP
        inp = K.Inputs(now_s=t, frame=self.frame(t), grid_ok=self.grid_up, time_ok=self.time_ok(t), hold=False, reserve_pct=self.reserve_pct,
                       in_force_w=lease.st.v_w, dongle_ok=True)
        if lease.kind in KINDS_CHARGE:
            self.charge_tick(t, lease, inp)
        else:
            self.export_tick(t, lease, inp)

    def charge_tick(self, t, lease, inp):
        K = self.K
        if lease.kind == "gentle" and t - lease.plan_t > K.PLAN_MAX_AGE_S:
            self.rec(t, "dongle", lease.kind, K.make("stop", "plan_lost", end=True, age_s=t - lease.plan_t, limit_s=K.PLAN_MAX_AGE_S))
            self.restore(t, lease, "plan_lost")
            return
        lim = replace(lease.lim, import_ceiling_w=self.import_ceiling_w, power_ceiling_w=self.power_ceiling_w)
        d = K.charge_guards(inp, lease.obj, lim, lease.st, lease.kind)
        if d is not None:
            self.rec(t, "dongle", lease.kind, d)
            if d.end:
                self.restore(t, lease, d.detail)
            elif d.write_w is not None and lease.pending is None:
                self.do_write(t, lease, "slot_power_w", d.write_w, "forced")
                lease.pending = (t, "slot_power_w", d.write_w, "forced", K.ac_in_w(inp.frame))
            return
        if lease.kind != "gentle":
            return
        st = lease.st
        since = t - (st.last_write_s if st.last_write_s is not None else t)
        if since >= K.RUNAWAY_GRACE_S and st.gain is not None and st.v_w is not None:
            st, tripped = K.runaway_check(st, K.ac_in_w(inp.frame), st.v_w * st.gain, "charge")
            lease.st = st
            if tripped:
                self.rec(t, "dongle", lease.kind, K.make("stop", "runaway", end=True, measured_w=K.ac_in_w(inp.frame),
                                                         expected_w=st.v_w * st.gain, samples=K.RUNAWAY_SAMPLES))
                self.restore(t, lease, "runaway")
                return
        st, verdict = K.judge_response(inp, lease.st)
        lease.st = st
        if verdict == "wrong":
            self.rec(t, "dongle", lease.kind, K.make("stop", "response_failed", end=True))
            self.restore(t, lease, "response_failed")
        elif verdict == "implausible":
            self.rec(t, "dongle", lease.kind, K.make("blocked", "implausible_gain", end=True, gain=st.gain, gain_min=K.GRC_GAIN_MIN * st.gain0,
                                                     gain_max=K.GRC_GAIN_MAX * st.gain0))
            self.restore(t, lease, "implausible_gain")
        elif verdict == "weak" and st.weak >= K.GRC_MAX_INEFFECTIVE:
            self.rec(t, "dongle", lease.kind, K.make("blocked", "no_response", end=True))
            self.restore(t, lease, "no_response")

    def export_tick(self, t, lease, inp):
        K = self.K
        d, st = K.export_tick(inp, lease.obj, replace(lease.lim, max_export_w=self.max_export_w), lease.st)
        lease.st = st
        if d.end:
            self.rec(t, "dongle", "export", d)
            self.restore(t, lease, d.detail)
        elif d.write_w is not None:
            self.rec(t, "dongle", "export", d)
            self.do_write(t, lease, "dump_ceiling_w", d.write_w, "loop")
            lease.pending = (t, "dump_ceiling_w", d.write_w, "loop", None)
        elif d.unreachable:
            self.rec(t, "dongle", "export", d)

    # ------------------------------------------------------------------------------------------------------------------
    # Home Assistant
    # ------------------------------------------------------------------------------------------------------------------
    def dongle_ok(self, t):
        return self.d_down_since is None or t - self.d_down_since < UNAVAIL_S

    def ha_inputs(self, t):
        K = self.K
        lease = self.lease
        ok = self.dongle_ok(t)
        in_force = None
        if ok:
            in_force = lease.st.v_w if lease is not None else (self.plant.regs.slot_power_w if self.sc.kind == "gentle" else None)
        return K.Inputs(now_s=t, frame=self.frame(t, HA_EXTRA_S), grid_ok=self.grid_up, time_ok=self.time_ok(t), hold=self.hold,
                        reserve_pct=self.reserve_pct, in_force_w=in_force, dongle_ok=ok)

    def charge_objective(self):
        sc = self.sc
        return self.K.ChargeObjective(target_soc_pct=sc.target_soc_pct, deadline_s=sc.window[1] - sc.buffer_s, window_end_s=sc.window[1],
                                      capacity_kwh=sc.trusted_capacity_kwh)

    def limits(self):
        return self.K.Limits(power_ceiling_w=self.power_ceiling_w, import_ceiling_w=self.import_ceiling_w, max_export_w=self.max_export_w)

    def ha_tick(self, t):
        K, sc = self.K, self.sc
        if self.ha_down or self.ha_over:
            return
        inp = self.ha_inputs(t)
        self.ha_state = K.observe(self.ha_state if self.ha_state is not None else K.State(), inp, self.charge_objective() if sc.kind in KINDS_CHARGE else None)
        lease = self.lease
        if not inp.dongle_ok:
            # the dongle is not answering: no firmware guard can run; Home Assistant alerts the owner (the backstop that exists)
            if self.unavailable_since is None:
                self.unavailable_since = t
            self.rec(t, "ha", sc.kind, K.make("blocked", "dongle_unavailable"))
            if (lease is not None) and not self.ha_alerted and t - self.unavailable_since >= ALERT_AFTER_S:
                self.ha_alerted = True
                self.run.alerts.append((t, "dongle unavailable for %d s while session %d is open: no firmware guard runs" % (t - self.unavailable_since, lease.id)))
            return
        self.unavailable_since = None
        stopped = self.ha_plan_stopped
        # a stopped plan hand-over sends no PLAN, START, ADJUST or END command; Home Assistant's own judging goes on and still REPORTS a
        # target that is going to be missed (report only, F02 of the N4 review)
        if lease is not None and not lease.restore_owed and lease.kind == "gentle" and not stopped:
            self.send(t, ("PLAN",))
        if sc.kind == "gentle":
            self.ha_charge(t, inp, lease, K.plan_gentle, "gentle", report_only=stopped)
        elif sc.kind == "charge_fixed":
            self.ha_charge(t, inp, lease, lambda i, o, l, s: K.plan_charge_fixed(i, o, l, s, owner_rate_w=sc.owner_rate_w), "charge_fixed", report_only=stopped)
        elif not stopped:
            self.ha_export(t, inp, lease)

    def can_resend(self, t):
        sc = self.sc
        return self.ha_start_sent_t is None or t - self.ha_start_sent_t >= 2 * max(sc.plan_s, sc.cmd_delay_s + TICK)

    def ha_report(self, t, name, d):
        """Report only (the plan hand-over is stopped): a decision that says the target cannot be met is published without its write or its
        end; nothing else is recorded and nothing is sent."""
        if d.unreachable:
            self.rec(t, "ha", name, replace(d, write_w=None, end=False))

    def ha_watch(self, t, inp, obj, lim, name):
        """After a Gentle lease has ended, for any reason, the night's lease is used up (one lease a night) and the plan can no longer START,
        ADJUST or END anything; it keeps judging the rate in force and REPORTS a target that is going to be missed (kernel.plan_watch).
        Report only: this method never sends a command."""
        d = self.K.plan_watch(inp, obj, lim, self.ha_state)
        if d.unreachable:
            self.rec(t, "ha", name, d)
        elif d.reason == "stop":
            self.rec(t, "ha", name, d)
            self.ha_over = True          # the target is reached or the window is over: nothing more to watch tonight

    def ha_charge(self, t, inp, lease, plan, name, report_only=False):
        K, sc = self.K, self.sc
        obj, lim = self.charge_objective(), self.limits()
        if lease is None:
            if self.night_used or (self.last_end_t is not None and t - self.last_end_t < K.CHARGE_DWELL_S):
                if self.night_used:
                    self.ha_watch(t, inp, obj, lim, name)      # night_used stops ACTUATION, not reporting (F02)
                return
            d = plan(inp, obj, lim, self.ha_state)
            if report_only:
                self.ha_report(t, name, d)
                return
            self.rec(t, "ha", name, d)
            if d.reason == "stop":
                self.ha_over = True      # the target is reached or the window is over: nothing more to plan tonight
                return
            if d.write_w is not None and d.reason in ("increase", "unreachable", "reduce") and self.can_resend(t):
                self.ha_start_sent_t = t
                self.run.start_cmd_t = t if self.run.start_cmd_t is None else self.run.start_cmd_t
                gain, _why = K.measure_gain(inp, self.ha_state)
                self.send(t, ("START", {"kind": name, "owner": name, "first_w": d.write_w, "gain": gain, "obj": obj, "lim": lim}))
            return
        if lease.restore_owed:
            return
        st = K.carry_memory(lease.st, self.ha_state)
        d = plan(inp, obj, lim, st)
        if report_only:
            self.ha_report(t, name, d)
            return
        self.rec(t, "ha", name, d)
        if d.end:
            self.send(t, ("END", d.detail))
        elif name == "gentle" and d.write_w is not None and d.detail != "import_ceiling" and t >= self.ha_inflight_until and lease.pending is None:
            self.ha_inflight_until = t + sc.cmd_delay_s + 2 * TICK
            self.send(t, ("ADJUST", d.write_w))

    def ha_export(self, t, inp, lease):
        K, sc = self.K, self.sc
        lim = self.limits()
        if lease is None:
            if self.all_leases or t < sc.export_start_s or not self.can_resend(t):
                return
            probe = K.ExportObjective(sc.target_export_w, sc.stop_soc_pct, 0.0, sc.trusted_capacity_kwh, sc.lease_ceiling_w)
            floor_pct = K.export_floor_pct(probe, self.reserve_pct)
            hw = K.house_w(inp.frame)
            # the energy plan credits NO solar (REQ-B15): only the measured PV enters the loop, never the duration
            power = min(sc.lease_ceiling_w, max(K.EXPORT_MIN_CEILING_W, (hw if hw is not None else 0.0) + sc.target_export_w))
            soc = inp.frame.soc_pct if inp.frame.soc_pct is not None else 0.0
            dur = K.export_duration_s(soc, floor_pct, sc.trusted_capacity_kwh, power)
            obj = replace(probe, end_s=t + min(sc.export_len_s, max(0.0, dur - 300.0)))
            d = K.plan_export(inp, obj, lim, K.State(), authority_free=True)
            self.rec(t, "ha", "export", d)
            if d.write_w is not None and d.reason in ("increase", "unreachable") and d.stop_soc_pct is not None:
                self.ha_start_sent_t = t
                self.run.start_cmd_t = t if self.run.start_cmd_t is None else self.run.start_cmd_t
                self.send(t, ("START", {"kind": "export", "owner": "export", "first_w": d.write_w, "stop_soc": d.stop_soc_pct, "obj": obj, "lim": lim}))
            return
        if lease.restore_owed or lease.kind != "export":
            return
        d = K.plan_export(inp, lease.obj, lim, K.carry_memory(lease.st, self.ha_state))
        self.rec(t, "ha", "export", d)
        if d.end:
            self.send(t, ("END", d.detail))
        elif d.stop_soc_pct is not None:
            self.send(t, ("RAISE_STOP", d.stop_soc_pct))

    # ------------------------------------------------------------------------------------------------------------------
    # the run
    # ------------------------------------------------------------------------------------------------------------------
    def go(self):
        sc = self.sc
        n = int(round(sc.duration_s / TICK))
        self.pending_events = sorted(sc.events, key=lambda e: e[0])
        first = sc.ha_first_s if sc.ha_first_s is not None else (sc.plan_s if sc.kind in KINDS_CHARGE else TICK)
        next_plan = first
        for i in range(n):
            t = i * TICK
            while True:
                due = [e for e in self.pending_events if e[0] <= t + 1e-9]
                if not due:
                    break
                e = min(due, key=lambda x: x[0])
                self.pending_events.remove(e)
                self.apply_event(t, e[1], e[2])
            m = self.plant.step(TICK, self.env(t))
            t1 = t + TICK
            self.take_sample(t1, m)
            self.dongle_tick(t1)
            if t1 + 1e-9 >= next_plan:
                next_plan += sc.plan_s
                self.ha_tick(t1)
            lease = self.lease
            regs = self.plant.regs
            self.run.rows.append(Row(t1, m.soc_true, m.soc_reading, m.batt_w, m.grid_w, m.house_w, m.pv_w, m.inv_ac_w, m.mode, regs.slot_power_w,
                                     regs.dump_ceiling_w if regs.allow_export else 0.0, regs.fp_rate_w, 0 if lease is None else lease.id, m.unserved_w,
                                     m.ac_in_w, self.reserve_pct, self.import_ceiling_w, self.time_ok(t1), self.grid_up))
            if self.all_leases and self.lease is None and sc.kind in ("export",):
                self.ha_over = True
        if self.lease is not None:
            self.lease.soc_end = self.plant.soc()
        self.run.leases = [dict(id=l.id, kind=l.kind, owner=l.owner, start_t=l.start_t, end_t=l.end_t, reason=l.end_reason, soc_start=l.soc_start,
                                soc_end=l.soc_end, writes=l.st.writes, changes=l.st.changes, fault=l.fault,
                                planned_end=l.obj.end_s if l.kind == "export" else self.K.lease_end_s(l.obj)) for l in self.all_leases]
        return self.run


def run_scenario(sc, K):
    """Run one scenario with the kernel module K; returns the Run."""
    return Bench(sc, K).go()
