"""A model of the dongle's Dump to Grid start gate, start transaction and timer, for the scheduled Dump to Grid reliability
suite (post-export entry dgs1). It plugs into the FPS1 interpreter (_ha_script_sim.py: the World, the Home Assistant script /
automation subset and the measured Modbus poll), which it reuses unchanged.

Modelled from firmware/ecco_clock_dongle_stage3_4_free_power.yaml, script start_dump_to_grid_override:
  - the gate is ONE condition; its refusal branch publishes exactly one REJECTED text (first matching reason, in the
    firmware's own order) and turns the write enable off - no Modbus I/O, no counter, no durable write;
  - a passing gate turns the write enable off, raises operation-in-progress and manual-write-in-progress, counts a start
    attempt (published every 30 s) and publishes "STARTING - taking fresh inverter snapshot";
  - the script is `mode: single`: a press while a start transaction is still running is dropped (no text, the write enable
    is left exactly as it was);
  - the transaction ends ACTIVE (a timer ends it after the staged duration), or START FAILED with or without a retained
    snapshot. Measured on 6 Oct 2026 (the scheduled 18:00 BST start): HA pressed at +2.019 s, the gate answered 0.117 s
    later, the transaction took 4.07 s.
  - a call to a dongle entity while the dongle is offline raises in Home Assistant (the ESPHome integration turns an API
    connection error into a service error) unless `offline_raises` is False. This is an ASSUMPTION about Home Assistant,
    stated here and in the suite, not a measurement.
"""
from __future__ import annotations

import re
from datetime import datetime

import _ha_script_sim as S

P = S.P
D_ARM = f"switch.{P}dump_to_grid_write_enable"
D_PRESS = f"button.{P}start_dump_to_grid_now"
D_STATUS = f"sensor.{P}dump_to_grid_status"
D_ACTIVE = f"binary_sensor.{P}dump_to_grid_active"
D_OP = f"binary_sensor.{P}dump_to_grid_operation_in_progress"
D_SNAP = f"binary_sensor.{P}dump_to_grid_snapshot_valid"
D_DUR = f"number.{P}dump_to_grid_duration"
D_PWR = f"number.{P}dump_to_grid_export_power"
D_SOC = f"number.{P}dump_to_grid_stop_soc"
D_ATTEMPTS = f"sensor.{P}dump_to_grid_start_attempts_since_boot"
D_BATT = f"sensor.{P}ecco_battery_soc"
FP_ACTIVE, FP_SNAP, FP_OP = S.E_ACTIVE, S.E_SNAP, S.E_OP

# The firmware's refusal texts, verbatim, in the order its else-chain tests them (the suite checks them against the firmware).
REJECT = {
    "corrupt": ("REJECTED - RECOVERY BLOCKED: durable recovery marker exists but its snapshot data cannot be trusted; "
                "deliberate recovery required"),
    "active": "REJECTED - Dump to Grid already active",
    "snapshot": "REJECTED - saved snapshot pending restore/recovery",
    "write": "REJECTED - another inverter write is active",
    "rtc": "REJECTED - RTC correction currently active",
    "fp": "REJECTED - Free Power override/recovery owns inverter settings",
    "r244": "REJECTED - Register 244 proof transaction awaiting restoration",
    "config": "REJECTED - inverter configuration offline",
    "ntp": "REJECTED - valid NTP time required for automatic end",
    "voltage": "REJECTED - plausible live battery voltage required",
    "soc_bad": "REJECTED - plausible live battery SOC required for Stop SOC enforcement",
    "soc_stale": "REJECTED - battery SOC telemetry is stale; Live Inverter Telemetry must be on and updating",
    "polling": ("REJECTED - Read-Only Configuration Polling must be on (Dump to Grid monitors its registers during the "
                "lease)"),
    "cfg_stale": "REJECTED - no fresh inverter configuration readback yet; wait for the next configuration poll",
    "grid_stale": ("REJECTED - grid CT telemetry is not fresh/plausible; the closed-loop controller needs it from the first "
                   "tick"),
    "tou_unreadable": "REJECTED - TOU slot schedule unreadable; cannot confirm the lease avoids a charging slot",
    "tou_slot": ("REJECTED - lease window overlaps TOU slot {slot}, which has a charge source set; Dump V1 does not override "
                 "slot charge settings - choose a window outside that slot"),
    "soc_floor": "REJECTED - battery SOC is already at or below the requested Stop SOC",
    "power": "REJECTED - requested export power outside safe range 500-8000W",
    "stop_soc": "REJECTED - requested Stop SOC outside safe range 10-90%",
    "duration": "REJECTED - requested duration outside safe range 1-240 minutes",
    "arm": "REJECTED - arm Dump to Grid Write Enable first",
    "bus": "REJECTED - Modbus bus busy with another transaction; try again shortly",
}
OUTCOMES = {
    "capture_failed": ("START FAILED - could not capture/durably commit inverter snapshot; nothing written", False),
    "verify_failed": ("START FAILED - verify mismatch or write error; snapshot retained - press End & Restore Now", True),
    "commit_failed": ("START FAILED - export was enabled but ECCO could not durably record the lease; restoring original "
                      "settings automatically", True),
}
ACTIVE_TEXT = ("ACTIVE - VERIFIED OK; target {p}W export - SETTLING - battery ceiling 2000W (feed-forward start: house 1416W, "
               "PV 0W); Stop SOC {s}%")


def add_ha_filters(world: S.World) -> None:
    """The two Jinja extras the Dump package's arm validation uses (HA's timestamp_local filter and `match` test)."""
    world.env.filters["timestamp_local"] = lambda v, default=None: datetime.fromtimestamp(float(v), S.LOCAL).isoformat()
    world.env.tests["match"] = lambda value, pattern: re.match(pattern, str(value)) is not None


class DumpDongle(S.Dongle):
    """The firmware side for Dump to Grid, at the level the HA package can observe. Reuses S.Dongle's bus model (the
    measured 10 s / 60 s busy windows, `phase`), RTC / write / offline / stall intervals and the publish model."""

    def __init__(self, world: S.World, phase: float = 0.0, handle_delays=(0.117,), publish: float = 0.12,
                 outcome: str = "ok", transaction_s: float = 4.07, offline_raises: bool = True):
        self.w = world
        self.phase = phase
        self.handle_delays = list(handle_delays)
        self.publish = publish
        self.outcome = outcome
        self.transaction_s = transaction_s
        self.offline_raises = offline_raises
        self.rtc: list = []
        self.writes: list = []
        self.offline: list = []
        self.stalls: list = []
        self.soc_stale: list = []
        self.cfg_stale: list = []
        self.grid_stale: list = []
        self.flags = {"corrupt": False, "snapshot": False, "fp": False, "fp_op": False, "r244": False, "ntp_bad": False,
                      "voltage_bad": False, "soc_bad": False, "polling_off": False, "tou_unreadable": False}
        self.tou_slot = 0
        self.soc = 80.0
        self.number_log: list = []
        self.drop_numbers = False
        self.op_intervals: list = []
        self.presses: list = []
        self.press_log: list = []
        self.attempts = 0
        self.successes = 0
        self.duration = 60                           # restore_value: the last staged values survive a reboot
        self.power = 1000
        self.stop_soc = 25
        self.arm = False
        self.active = False
        self.op = False
        self.ends_at = None
        self.started_at = None
        self.dropped = 0
        self.status = "Inactive"
        for e, s in ((D_ARM, "off"), (D_ACTIVE, "off"), (D_OP, "off"), (D_SNAP, "off"), (S.E_TEL, "on"), (S.E_CFG, "on"),
                     (S.E_NTP, "on"), (S.E_MANUAL, "off"), (D_ATTEMPTS, "0.0"), (D_DUR, "60.0"), (D_PWR, "1000.0"),
                     (D_SOC, "25.0"), (D_STATUS, self.status), (FP_ACTIVE, "off"), (FP_SNAP, "off"), (FP_OP, "off"),
                     (D_BATT, "80.0")):
            world.set(e, s)
        world.at(world.t + 7.0, self._attempts_tick)
        world.service_handlers.update({
            "switch.turn_on": self._switch(True), "switch.turn_off": self._switch(False),
            "button.press": self._press, "number.set_value": self._number,
        })

    DONGLE_ENTITIES = (D_ARM, D_STATUS, D_ACTIVE, D_OP, D_SNAP, S.E_TEL, S.E_CFG, S.E_NTP, S.E_MANUAL, D_ATTEMPTS, D_DUR,
                       D_PWR, D_SOC, FP_ACTIVE, FP_SNAP, FP_OP, D_BATT)

    @staticmethod
    def _in(intervals, t):
        return any(a <= t < b for a, b in intervals)

    def set_offline(self, a: float, b: float) -> None:
        self.offline.append((a, b))

        def down():
            for e in self.DONGLE_ENTITIES:
                self.w.set(e, "unavailable")

        def up():
            for e, v in ((D_ARM, "on" if self.arm else "off"), (D_ACTIVE, "on" if self.active else "off"),
                         (D_OP, "on" if self.op else "off"), (D_SNAP, "on" if self.flags["snapshot"] else "off"),
                         (S.E_TEL, "on"), (S.E_CFG, "on"), (S.E_NTP, "on"), (S.E_MANUAL, "on" if self.op else "off"),
                         (D_ATTEMPTS, f"{float(self.attempts)}"), (D_STATUS, self.status),
                         (D_DUR, f"{float(self.duration)}"), (D_PWR, f"{float(self.power)}"),
                         (D_SOC, f"{float(self.stop_soc)}"), (FP_ACTIVE, "on" if self.flags["fp"] else "off"),
                         (FP_SNAP, "off"), (FP_OP, "on" if self.flags["fp_op"] else "off"), (D_BATT, f"{self.soc}")):
                self.w.set(e, v)
        self.w.at(a, down)
        self.w.at(b, up)

    def _attempts_tick(self):
        if not self.is_offline(self.w.t):
            self._pub(D_ATTEMPTS, f"{float(self.attempts)}")
        self.w.after(30.0, self._attempts_tick)

    def manual_start(self, at: float, duration: int = 60, power: int = 1000, stop_soc: int = 25) -> None:
        """The owner's own Dump to Grid now (stage, arm, then press) at `at`."""
        def go():
            self.duration, self.power, self.stop_soc = duration, power, stop_soc
            self.arm = True
            self._pub(D_ARM, "on")
            self.w.after(1.0, lambda: (self.press_log.append(self.w.t), self._gate()))
        self.w.at(at, go)

    def _pub(self, entity, state, delay=None):
        if entity == D_STATUS:
            self.status = state
        when = self.w.t + (self.publish if delay is None else delay)
        for a, b in self.stalls:
            if a <= when < b:
                when = b + (when - a) * 1e-3
        if self.is_offline(when):
            return
        self.w.at(when, lambda: self.w.set(entity, state))

    # --- services --------------------------------------------------------------------------------------------
    def _offline_call(self) -> bool:
        if self.is_offline(self.w.t):
            if self.offline_raises:
                raise S.ServiceError("dongle offline (ESPHome API not connected)")
            return True
        return False

    def _switch(self, on: bool):
        def h(entity, data):
            if entity != D_ARM:
                raise S.Unsupported(f"switch {entity}")
            if self._offline_call():
                return
            self.w.after(0.03, lambda: self._set_arm(on))
        return h

    def _set_arm(self, on: bool):
        self.arm = on
        self._pub(D_ARM, "on" if on else "off")

    def _number(self, entity, data):
        if self._offline_call():
            return
        v = int(float(data["value"]))
        self.number_log.append((self.w.t, entity, v))
        if self.drop_numbers:
            return
        if entity == D_DUR:
            self.duration = v
        elif entity == D_PWR:
            self.power = v
        elif entity == D_SOC:
            self.stop_soc = v
        else:
            raise S.Unsupported(f"number {entity}")
        self._pub(entity, f"{float(data['value'])}")

    def _press(self, entity, data):
        if entity != D_PRESS:
            raise S.Unsupported(f"button {entity}")
        self.press_log.append(self.w.t)
        if self._offline_call():
            return
        d = self.handle_delays[(len(self.press_log) - 1) % len(self.handle_delays)]
        self.w.after(d, self._gate)

    def gate_reason(self, t: float):
        """The firmware's else-chain, in its own order (None = the gate passes)."""
        f = self.flags
        checks = (
            ("corrupt", f["corrupt"]), ("active", self.active), ("snapshot", f["snapshot"]),
            ("write", self.op or self._in(self.writes, t)), ("rtc", self.rtc_active(t)), ("fp", f["fp"] or f["fp_op"]),
            ("r244", f["r244"]), ("config", self.is_offline(t)), ("ntp", f["ntp_bad"]), ("voltage", f["voltage_bad"]),
            ("soc_bad", f["soc_bad"]), ("soc_stale", self._in(self.soc_stale, t)), ("polling", f["polling_off"]),
            ("cfg_stale", self._in(self.cfg_stale, t)), ("grid_stale", self._in(self.grid_stale, t)),
            ("tou_unreadable", f["tou_unreadable"]), ("tou_slot", self.tou_slot > 0), ("soc_floor", self.soc <= self.stop_soc),
            ("power", not 500 <= self.power <= 8000), ("stop_soc", not 10 <= self.stop_soc <= 90),
            ("duration", not 1 <= self.duration <= 240), ("arm", not self.arm), ("bus", self.bus_busy(t)),
        )
        return next((k for k, hit in checks if hit), None)

    def _gate(self):
        t = self.w.t
        if self.op:                                   # start_dump_to_grid_override is mode: single - the press is dropped
            self.dropped += 1
            return
        reason = self.gate_reason(t)
        self.arm = False
        if reason:
            text = REJECT[reason].format(slot=self.tou_slot)
            self.presses.append((t, text))
            self._pub(D_STATUS, text)
            self._pub(D_ARM, "off", (self.publish + 0.0003))
            return
        self.presses.append((t, "PASSED"))
        self.attempts += 1
        self.op = True
        self.op_intervals.append([t, None])
        self.gate_values = (self.power, self.stop_soc, self.duration)
        self._pub(D_ARM, "off", self.publish - 0.001)
        self._pub(D_STATUS, "STARTING - taking fresh inverter snapshot")
        self._pub(D_OP, "on", self.publish + 0.003)
        self._pub(S.E_MANUAL, "on", self.publish + 0.003)
        self.w.after(self.transaction_s, self._finish)

    def _finish(self):
        t = self.w.t
        self.op = False
        self.op_intervals[-1][1] = t
        if self.outcome == "ok":
            self.active = True
            self.successes += 1
            self.started_at = t
            power, soc, dur = self.gate_values
            self.ends_at = t + dur * 60
            self._pub(D_STATUS, ACTIVE_TEXT.format(p=power, s=soc))
            self._pub(D_ACTIVE, "on")
            self.w.at(self.ends_at, self._end)
        elif self.outcome in OUTCOMES:
            text, snap = OUTCOMES[self.outcome]
            if snap:
                self.flags["snapshot"] = True
                self._pub(D_SNAP, "on")
            self._pub(D_STATUS, text)
        else:
            raise S.Unsupported(self.outcome)
        self._pub(D_OP, "off")
        self._pub(S.E_MANUAL, "off")

    def _end(self):
        self.active = False
        self._pub(D_ACTIVE, "off")
        self._pub(D_STATUS, "RESTORED OK - original inverter settings verified")
