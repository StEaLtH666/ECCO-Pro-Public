"""A model of the dongle's MANUAL TOU write path (Load Current Slot N To Manual Staging, Manual Configuration Write Enable,
Apply Manual Slot N Settings) at the level Home Assistant can observe, for the offline Advanced Configuration edit suite.

Faithful to firmware/ecco_clock_dongle_stage3_4_free_power.yaml (apply_manual_slot1 ~12570, its refusal branch ~13013,
load_manual_slot1_staging ~21492, the configuration poll that publishes ECCO TimezoneN Time / Power / SOC / Charge / Mode):
  - the configuration poll refreshes a RAM cache every 60 s; the live TimezoneN sensors and Last Configuration Update come
    from that cache; Load copies the CACHE (not the inverter) into staging and sets the slot's staging-loaded flag;
  - Apply's gate and its refusal texts follow the firmware's order; every attempt disarms the write enable; a passing
    Apply clears staging-loaded, takes the manual write lock, writes 232 bit0, the slot's start / end, power, SOC and flags
    (sequentially, 700 ms apart) from STAGING, verifies by readback and reports VERIFIED OK or VERIFY FAILED, then polls;
  - fault injection: refuse_bus (bus busy at the gate), verify_fail (all written, readback fails), partial=k (only the
    first k writes land, then FAILED), clamp_soc=x (the inverter stores x instead of the requested SOC), drop_press.
  - acs0r1: the Modbus BUS TIMELINE the Apply gate's `tx_buffer_empty() / tx_blocked()` check sees (firmware intervals at
    ~24516-24550: telemetry every 10 s, configuration and inverter clock read every 60 s). The configuration poll reads
    blocks A / B / C 2.5 s apart and publishes Last Configuration Update with B (at `poll_phase`); the telemetry poll reads
    two blocks 2.5 s apart and publishes Last Telemetry Update with the second (`tel_offset` s after a configuration
    publish, mod 10); the clock read publishes Inverter Time (`clock_offset` s after it, mod 60). Each frame holds the
    bus for `busy` s; an Apply whose gate runs inside any such frame is REFUSED "bus busy", exactly as on the live S3 on
    2026-10-16 (defaults: the live offsets 5.35 s / 7.37 s). `arm_latency` / `press_latency` model Home Assistant ->
    dongle delays (scheduler jitter). `post_busy` keeps the bus busy for that long AFTER each telemetry publish (the 2026-10-16
    B1 refusal reached Home Assistant 1 ms after the publish: a frame still running, or the publish batched early);
    `clock_stalled` keeps the clock read's frame on the bus but never changes Inverter Time (a stalled inverter RTC).
"""
from __future__ import annotations

import copy

from _ha_script_sim import Unsupported, World, local_str

P = "ecco_clock_dongle_"
ARM = f"switch.{P}manual_configuration_write_enable"
GC_STAGED = f"switch.{P}manual_stage_grid_charge_enabled"
GC_LIVE = f"binary_sensor.{P}ecco_battery_grid_charge_enabled"
RESULT = f"sensor.{P}manual_configuration_last_result"
SUCCESSES = f"sensor.{P}manual_configuration_write_successes_since_boot"
ATTEMPTS = f"sensor.{P}manual_configuration_write_attempts_since_boot"
MANUAL = f"binary_sensor.{P}manual_write_in_progress"
CFG_UPDATE = f"sensor.{P}last_configuration_update"
HB_COUNT = f"sensor.{P}ecco_supervision_valid_heartbeat_count"
HB_AGE = f"sensor.{P}ecco_supervision_heartbeat_age"
SHUTDOWN = f"sensor.{P}ecco_battery_shutdown"
TEL_UPDATE = f"sensor.{P}last_telemetry_update"
CLOCK = f"sensor.{P}inverter_time"
FLAGS = {
    "tel": f"binary_sensor.{P}telemetry_online", "cfg": f"binary_sensor.{P}configuration_online",
    "fp_active": f"binary_sensor.{P}free_power_active", "fp_op": f"binary_sensor.{P}free_power_operation_in_progress",
    "fp_snap": f"binary_sensor.{P}free_power_snapshot_valid", "dump_active": f"binary_sensor.{P}dump_to_grid_active",
    "dump_op": f"binary_sensor.{P}dump_to_grid_operation_in_progress",
    "dump_snap": f"binary_sensor.{P}dump_to_grid_snapshot_valid", "rtc": f"binary_sensor.{P}rtc_correction_in_progress",
}


# Every other HA-visible state the edit's safety gate reads, at its SAFE value (tests flip them one at a time).
SAFE_STATES = {
    f"binary_sensor.{P}manual_configuration_raw_cache_valid": "on",
    f"switch.{P}free_power_write_enable": "off", f"switch.{P}free_power_recovery_arm": "off",
    f"switch.{P}dump_to_grid_write_enable": "off", f"switch.{P}dump_to_grid_recovery_arm": "off",
    "sensor.ecco_clock_dongle_ecco_fallback_profile_live_match":
        "m=MATCH;dx=00000;cx=000;ox=00000;ix=00;eh=0;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=F;elig=OK;ew=-",
    "sensor.ecco_clock_dongle_ecco_fallback_profile_review": "st=IDLE;prior=VALID;exp=-;warn=-;obl=-;latch=-;sv=-",
    f"sensor.{P}ecco_supervision_state": "SUPERVISED", f"binary_sensor.{P}ecco_supervision_stable": "on",
    "sensor.ecco_clock_dongle_ecco_failback_shadow_state": "SHADOW_IDLE",
    f"sensor.{P}dump_to_grid_export_containment": "NOT_APPLICABLE",
    f"sensor.{P}free_power_recovery_evidence_id": "-", f"sensor.{P}reg244_original_snapshot": "—",
    f"sensor.{P}free_power_recovery_state": "NONE", f"sensor.{P}dump_to_grid_recovery_state": "NONE",
    "binary_sensor.ecco_fallback_save_available": "off", "binary_sensor.ecco_fallback_replace_corrupt_available": "off",
    "binary_sensor.ecco_fallback_invalidate_available": "off", "script.ecco_free_power_start_scheduled": "off",
    "script.ecco_dump_to_grid_start_scheduled": "off",
}
SRC_BITS = {"None": 0, "Grid": 1, "Generator": 2, "Grid + Generator": 3}
MODE_BITS = {"None": 0x00, "General": 0x04, "Backup": 0x08, "Charge": 0x10}


def hhmm_text(v: int) -> str:
    return f"{v // 100:02d}:{v % 100:02d}"


DEFAULT_SLOTS = {
    1: dict(start=0, power=8000, soc=100, src="Grid", mode="General"),
    2: dict(start=500, power=8000, soc=100, src="Grid", mode="General"),
    3: dict(start=900, power=8000, soc=40, src="None", mode="General"),
    4: dict(start=1600, power=8000, soc=40, src="None", mode="General"),
    5: dict(start=1900, power=8000, soc=40, src="None", mode="General"),
    6: dict(start=2300, power=8000, soc=40, src="None", mode="General"),
}


class ManualTouDongle:
    def __init__(self, world: World, poll_phase: float = 42.0, shutdown_soc: int = 10, tel_offset: float = 5.35,
                 clock_offset: float | None = 7.37, busy: float = 0.3, arm_latency: float = 0.1, press_latency: float = 0.1,
                 tel_period: float = 10.0, post_busy: float = 0.0, clock_stalled: bool = False):
        self.w = world
        self.tel_offset, self.clock_offset, self.busy, self.tel_period = tel_offset, clock_offset, busy, tel_period
        self.post_busy, self.clock_stalled = post_busy, clock_stalled
        self.arm_latency, self.press_latency = arm_latency, press_latency
        self.bus_refusals: list[float] = []               # gate times refused because a frame was on the bus
        self.regs = {"slots": copy.deepcopy(DEFAULT_SLOTS), "gc": True}
        self.cache = copy.deepcopy(self.regs)
        self.staging = {n: dict(start=0, end=0, power=0, soc=0, src="None", mode="None") for n in range(1, 7)}
        self.staged_gc = False
        self.loaded = {n: False for n in range(1, 7)}
        self.flags = {k: False for k in FLAGS}
        self.flags.update(tel=True, cfg=True)
        self.arm = False
        self.manual = False
        self.successes = 0
        self.fault: dict = {}
        self.presses: list[tuple[float, str, str]] = []   # (time, button, outcome)
        self.writes: list[tuple[float, int, int]] = []    # (time, register, value)
        self.apply_staging: list[dict] = []               # staging + regs at each passing Apply
        self.shutdown_soc = shutdown_soc
        for k, e in FLAGS.items():
            world.set(e, "on" if self.flags[k] else "off")
        world.set(ARM, "off")
        world.set(MANUAL, "off")
        world.set(RESULT, "No manual write since boot")
        world.set(SUCCESSES, "0.0")
        world.set(ATTEMPTS, "0.0")
        self.attempts = 0
        world.at(world.t + 13.0, self._counter_tick)
        # The supervision heartbeat: Home Assistant sends one every 30 s and the dongle counts each valid one (supervision_valid_count),
        # publishing the count every 30 s and the age of the last one every 20 s (fault "hb_dead": heartbeats stop arriving).
        self.hb_count = 40
        self.hb_last = world.t - 5.0
        world.at(world.t + 25.0, self._heartbeat)
        world.at(world.t + 7.0, self._hb_count_tick)
        world.at(world.t + 3.0, self._hb_age_tick)
        world.set(HB_COUNT, f"{float(self.hb_count)}")
        world.set(HB_AGE, "5.0")
        world.set(SHUTDOWN, f"{float(shutdown_soc)}")
        for e, v in SAFE_STATES.items():
            world.set(e, v)
        self._publish_live()
        self._publish_staging_all()
        self.phase = poll_phase
        first = (world.t // 60) * 60 + poll_phase
        world.at(first if first > world.t else first + 60, self._poll_tick)
        world.set(TEL_UPDATE, local_str(world.t - 4.0))
        world.set(CLOCK, local_str(world.t - 30.0 + 22.0))
        tel = world.t + ((poll_phase + tel_offset - world.t) % tel_period or tel_period)
        world.at(tel, self._tel_tick)
        if clock_offset is not None:                      # None: the clock read is not polling (no bus user, no publish)
            clk = world.t + ((poll_phase + clock_offset - world.t) % 60.0 or 60.0)
            world.at(clk, self._clock_tick)
        world.service_handlers.update({
            "button.press": self._press, "number.set_value": self._number, "select.select_option": self._select,
            "switch.turn_on": self._switch(True), "switch.turn_off": self._switch(False),
        })

    # ---- helpers -------------------------------------------------------------------------------------------------
    def end_of(self, regs, n):
        return regs["slots"][n % 6 + 1]["start"]

    def set_flag(self, k: str, on: bool):
        self.flags[k] = on
        self.w.set(FLAGS[k], "on" if on else "off")

    def _publish_live(self):
        for n in range(1, 7):
            s = self.cache["slots"][n]
            self.w.set(f"sensor.{P}ecco_timezone{n}_time", hhmm_text(s["start"]))
            self.w.set(f"sensor.{P}ecco_timezone{n}_power", f"{float(s['power'])}")
            self.w.set(f"sensor.{P}ecco_timezone{n}_soc", f"{float(s['soc'])}")
            self.w.set(f"sensor.{P}ecco_timezone{n}_charge", s["src"])
            self.w.set(f"sensor.{P}ecco_timezone{n}_mode", s["mode"])
            self.w.set(f"sensor.{P}ecco_timezone{n}_raw_flags",
                       f"{float(s.get('reserved', 0) | SRC_BITS[s['src']] | MODE_BITS[s['mode']])}")
        self.w.set(GC_LIVE, "on" if self.cache["gc"] else "off")

    def _publish_staging(self, n):
        st = self.staging[n]
        self.w.set(f"number.{P}manual_slot_{n}_start_hhmm", f"{float(st['start'])}")
        self.w.set(f"number.{P}manual_slot_{n}_end_hhmm", f"{float(st['end'])}")
        self.w.set(f"number.{P}manual_slot_{n}_power", f"{float(st['power'])}")
        self.w.set(f"number.{P}manual_slot_{n}_target_soc", f"{float(st['soc'])}")
        self.w.set(f"select.{P}manual_slot_{n}_charge_source", st["src"])
        self.w.set(f"select.{P}manual_slot_{n}_mode", st["mode"])

    def _publish_staging_all(self):
        for n in range(1, 7):
            self._publish_staging(n)
        self.w.set(GC_STAGED, "on" if self.staged_gc else "off")

    def poll(self):
        if not self.flags["cfg"] or self.manual:
            return
        self.cache = copy.deepcopy(self.regs)
        self._publish_live()
        self.w.set(CFG_UPDATE, local_str(self.w.t + self.fault.get("clock_skew", 0.0)))   # the dongle's own (SNTP) clock

    def _heartbeat(self):
        if not self.fault.get("hb_dead"):
            self.hb_count += 1
            self.hb_last = self.w.t
        self.w.after(30.0, self._heartbeat)

    def _hb_count_tick(self):
        if self.flags["tel"]:
            self.w.set(HB_COUNT, f"{float(self.hb_count)}")
        self.w.after(30.0, self._hb_count_tick)

    def _hb_age_tick(self):
        if self.flags["tel"]:
            self.w.set(HB_AGE, f"{float(int(self.w.t - self.hb_last))}")
        self.w.after(20.0, self._hb_age_tick)

    def _counter_tick(self):
        """The firmware publishes its write counters every 30 s (not on change)."""
        if self.flags["tel"]:
            self.w.set(ATTEMPTS, f"{float(self.attempts)}")
        self.w.after(30.0, self._counter_tick)

    def _poll_tick(self):
        self.poll()
        self.w.after(60.0, self._poll_tick)

    def _tel_tick(self):
        """The 10 s telemetry poll: Last Telemetry Update is published with its second (last) block's response."""
        if self.flags["tel"] and not self.manual and not self.flags["rtc"]:
            self.w.set(TEL_UPDATE, local_str(self.w.t))
        self.w.after(self.tel_period, self._tel_tick)

    def _clock_tick(self):
        """The once-a-minute inverter clock read (registers 22-24): publishes Inverter Time (the inverter's own clock)."""
        if self.flags["tel"] and not self.manual and not self.flags["rtc"]:
            if not self.clock_stalled:
                self.w.set(CLOCK, local_str(self.w.t + 22.0))
        self.w.after(60.0, self._clock_tick)

    def bus_busy(self, t: float) -> bool:
        """Is a routine poll frame queued / in flight at time t (what tx_buffer_empty()/tx_blocked() refuses on)?
        Frames end at their publish (response) instant and hold the bus for `busy` s before it."""
        tel, cfg, tp = self.phase + self.tel_offset, self.phase, self.tel_period
        frames = [(tel, 0.0, tp), (tel, -2.5, tp),                     # telemetry block 2 (publish), block 1
                  (cfg, -2.5, 60.0), (cfg, 0.0, 60.0), (cfg, 2.5, 60.0)]   # configuration blocks A, B (publish), C
        if self.clock_offset is not None:
            frames.append((self.phase + self.clock_offset, 0.0, 60.0))     # inverter clock read
        # a frame whose response lands at anchor+offset (mod period) holds the bus for `busy` s up to that instant
        if self.post_busy and (t - tel) % tp < self.post_busy:   # a tail after the telemetry publish (B1 hypothesis)
            return True
        return any((anchor + offset - t) % period < self.busy for anchor, offset, period in frames)

    # ---- services -----------------------------------------------------------------------------------------------
    def _switch(self, on: bool):
        def h(entity, data):
            if self.w.state(entity) == "unavailable":
                return                                  # Home Assistant cannot reach an unavailable ESPHome entity
            if entity == ARM:
                self.arm = on
                self.w.after(self.arm_latency, lambda: self.w.set(ARM, "on" if on else "off"))
            elif entity == GC_STAGED:
                self.staged_gc = on
                self.w.after(0.1, lambda: self.w.set(GC_STAGED, "on" if on else "off"))
            else:
                raise Unsupported(f"switch {entity}")
        return h

    def _number(self, entity, data):
        for n in range(1, 7):
            for f, key in (("start_hhmm", "start"), ("end_hhmm", "end"), ("power", "power"), ("target_soc", "soc")):
                if entity == f"number.{P}manual_slot_{n}_{f}":
                    self.staging[n][key] = int(float(data["value"]))
                    self.w.after(0.1, lambda n=n: self._publish_staging(n))
                    return
        raise Unsupported(f"number {entity}")

    def _select(self, entity, data):
        raise Unsupported(f"select {entity} (the edit never selects)")

    def _press(self, entity, data):
        if self.fault.get("drop_press"):
            self.presses.append((self.w.t, entity, "DROPPED"))
            self.fault["drop_press"] -= 1
            return
        for n in range(1, 7):
            if entity == f"button.{P}load_current_slot_{n}_to_manual_staging":
                self.w.after(self.fault.get("slow_load", 0.1), lambda n=n: self._load(n))
                return
            if entity == f"button.{P}apply_manual_slot_{n}_settings":
                self.w.after(self.press_latency, lambda n=n: self._apply(n))
                return
        raise Unsupported(f"button {entity}")

    def _owner(self):
        return any(self.flags[k] for k in ("fp_active", "fp_op", "fp_snap", "dump_active", "dump_op", "dump_snap"))

    def _load(self, n):
        if self.manual or self._owner():
            self.loaded[n] = False
            self.presses.append((self.w.t, f"load{n}", "REJECTED"))
            self.w.set(RESULT, f"REJECTED - cannot load Slot {n} staging while Free Power or Dump to Grid owns TOU settings")
            return
        s = self.cache["slots"][n]
        self.staging[n] = dict(start=s["start"], end=self.end_of(self.cache, n), power=s["power"], soc=s["soc"],
                               src=s["src"], mode=s["mode"])
        self.staged_gc = self.cache["gc"]
        self.loaded[n] = True
        self.presses.append((self.w.t, f"load{n}", "LOADED"))
        self.w.after(0.12, lambda: (self._publish_staging(n), self.w.set(GC_STAGED, "on" if self.staged_gc else "off"),
                                    self.w.set(RESULT, f"Manual staging loaded from current inverter Slot {n} readback")))

    def _apply(self, n):
        st = self.staging[n]
        valid = all(0 <= v <= 2359 and v % 100 <= 59 and v % 5 == 0 for v in (st["start"], st["end"])) \
            and st["start"] != st["end"] and 0 <= st["power"] <= 8000 and 0 <= st["soc"] <= 100
        refuse = None
        if self._owner():
            refuse = "REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings"
        elif self.fault.get("refuse_bus") or self.bus_busy(self.w.t):
            if not self.fault.get("refuse_bus"):
                self.bus_refusals.append(self.w.t)
            refuse = "REJECTED - Modbus bus busy with another transaction; try again shortly"
        elif not self.flags["cfg"]:
            refuse = "REJECTED - inverter configuration is offline"
        elif self.flags["rtc"]:
            refuse = "REJECTED - RTC correction currently active"
        elif self.manual:
            refuse = "REJECTED - manual configuration write already active"
        elif not self.arm:
            refuse = "REJECTED - arm Manual Configuration Write Enable first"
        elif not self.loaded[n]:
            refuse = f"REJECTED - load current Slot {n} values into staging first"
        elif not valid:
            refuse = f"REJECTED - staged Slot {n} values failed safety validation"
        self.arm = False
        if refuse:
            self.presses.append((self.w.t, f"apply{n}", refuse))
            self.w.after(0.12, lambda: (self.w.set(RESULT, refuse), self.w.set(ARM, "off")))
            return
        self.presses.append((self.w.t, f"apply{n}", "PASSED"))
        self.attempts += 1
        self.apply_staging.append(dict(staging=copy.deepcopy(st), gc=self.staged_gc, regs=copy.deepcopy(self.regs)))
        self.loaded[n] = False
        self.manual = True
        self.w.after(0.12, lambda: (self.w.set(MANUAL, "on"), self.w.set(ARM, "off")))
        base = 250 + n - 1
        plan = [(232, "gc", self.staged_gc), (base, "start", st["start"]), (base + 1 if n < 6 else 250, "end", st["end"]),
                (256 + n - 1, "power", st["power"]), (268 + n - 1, "soc", st["soc"]), (274 + n - 1, "flags", (st["src"], st["mode"]))]
        landed = self.fault.get("partial", len(plan))

        def write(i):
            if i >= landed:
                self._finish(n, "FAILED - one or more write transactions failed; no automatic retry")
                return
            reg, key, val = plan[i]
            if key == "gc":
                self.regs["gc"] = val
            elif key == "start":
                self.regs["slots"][n]["start"] = val
            elif key == "end":
                self.regs["slots"][n % 6 + 1]["start"] = val
            elif key == "power":
                self.regs["slots"][n]["power"] = val
            elif key == "soc":
                self.regs["slots"][n]["soc"] = self.fault.get("clamp_soc", val)
            else:
                self.regs["slots"][n]["src"], self.regs["slots"][n]["mode"] = val
            self.writes.append((self.w.t, reg, val if not isinstance(val, tuple) else 0))
            if i + 1 < len(plan):
                self.w.after(0.7, lambda: write(i + 1))
            else:
                self.w.after(0.7, lambda: self._finish(n, None))
        self.w.after(0.5, lambda: write(0))

    def _finish(self, n, failed):
        if failed is None and self.fault.get("verify_fail"):
            failed = f"VERIFY FAILED - Slot {n} verification timed out"
        if failed is None and self.regs["slots"][n]["soc"] != self.staging[n]["soc"]:
            failed = f"VERIFY FAILED read SOC={self.regs['slots'][n]['soc']}"
        self.manual = False
        text = failed or f"VERIFIED OK - manual Slot {n} settings match inverter readback"
        if failed is None:
            self.successes += 1
        self.w.after(0.12, lambda: (self.w.set(RESULT, text), self.w.set(MANUAL, "off"),
                                    self.w.set(SUCCESSES, f"{float(self.successes)}")))
        if not text.startswith("FAILED"):              # a failed write transaction ends without the post-verify poll
            self.w.after(3.9, self.poll)                # the firmware's own post-Apply poll (Block A +0.9 s, Block B +3.4 s)
