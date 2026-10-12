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
SHUTDOWN = f"sensor.{P}ecco_battery_shutdown"
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
    f"sensor.{P}ecco_fallback_profile_live_match":
        "m=MATCH;dx=00000;cx=000;ox=00000;ix=00;eh=0;obl=FP:CR,DP:CR,R4:CR,BUS:OK;ca=F;elig=OK;ew=-",
    f"sensor.{P}ecco_fallback_profile_review": "st=IDLE;id=-;age=-",
    f"sensor.{P}ecco_supervision_state": "SUPERVISED", f"binary_sensor.{P}ecco_supervision_stable": "on",
    f"sensor.{P}ecco_failback_shadow_state": "SHADOW_IDLE",
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
    def __init__(self, world: World, poll_phase: float = 42.0, shutdown_soc: int = 10):
        self.w = world
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
        world.set(SHUTDOWN, f"{float(shutdown_soc)}")
        for e, v in SAFE_STATES.items():
            world.set(e, v)
        self._publish_live()
        self._publish_staging_all()
        self.phase = poll_phase
        first = (world.t // 60) * 60 + poll_phase
        world.at(first if first > world.t else first + 60, self._poll_tick)
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
        self.w.set(CFG_UPDATE, local_str(self.w.t))

    def _counter_tick(self):
        """The firmware publishes its write counters every 30 s (not on change)."""
        if self.flags["tel"]:
            self.w.set(ATTEMPTS, f"{float(self.attempts)}")
        self.w.after(30.0, self._counter_tick)

    def _poll_tick(self):
        self.poll()
        self.w.after(60.0, self._poll_tick)

    # ---- services -----------------------------------------------------------------------------------------------
    def _switch(self, on: bool):
        def h(entity, data):
            if entity == ARM:
                self.arm = on
                self.w.after(0.1, lambda: self.w.set(ARM, "on" if on else "off"))
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
                self.w.after(0.1, lambda n=n: self._apply(n))
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
        elif self.fault.get("refuse_bus"):
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
        self.w.after(3.9, self.poll)                    # the firmware's own post-Apply poll (Block A +0.9 s, Block B +3.4 s)
