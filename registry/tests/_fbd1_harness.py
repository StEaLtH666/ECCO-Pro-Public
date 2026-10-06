"""FB-D1 test harness (test-only): the strict FB-B simulator (registry/tests/_fbb_harness.FbbSim + _fbb1_engine) extended with
what the FB-D1 RTC / poll liveness suite (registry/tests/test_fbd1_liveness.py) needs to run the REAL firmware lambdas of the RTC
correction, the telemetry / configuration polls, the configuration catch-up and the B10 fence - on the live firmware, on the
pre-FB-D1 firmware (`pre_text()` == main, `_fbd1_scope.pre_fbd1_firmware`) or on an in-memory mutant. It edits no shared harness:
everything is a subclass (D1Sim) or a helper on top of the existing modules.

  G1 wall clock       WallClock: a flowing UTC epoch -> Europe/London local ESPTime (year / month / day_of_month / hour / minute /
                      second / day_of_week / day_of_year / timestamp / is_dst / is_valid() / strftime()), DST hand-coded (no tz
                      database needed), the NTP-valid switch (sim.ntp_valid), an SNTP step, `ntp_synced` through the firmware's
                      own `time: on_time_sync` lambda (ntp_sync())
  G3 inverter RTC     InverterRtc: the inverter clock = local time + offset + rate * elapsed (piecewise linear, integer ms), packed
                      into registers 22-24 exactly as read_inverter_clock decodes them (reg22 = (year-2000)<<8 | month,
                      reg23 = day<<8 | hour, reg24 = minute<<8 | second) at the instant the read frame goes on the wire; a Modbus
                      image that refreshes every image_period_ms (staleness) and freeze windows; an FC16 22-24 sets the clock only
                      when the write LANDS (ok / no_response_landed / timeout_landed)
  G4 deferred writes  FC16 frames on the hub FIFO (writes ahead of queued reads, one frame in flight, latency, the outcome later
                      or never): ok / ack_not_applied / error / no_response_landed / no_response_lost / custom_response /
                      not_sent (the synchronous refusal inside the action) / timeout_landed / timeout_lost (no callback at all)
  G7 seeding          correction_threshold (20), automatic_clock_sync / configuration_polling / live_telemetry, the cached TOU
                      zone start words manual_cfg_reg250..255_raw
  G8 audit            every global ASSIGNMENT and entity PUBLICATION is attributed to the firmware path whose lambda made it
                      (rtc / poll / hook / other); allow-lists (RTC_ALLOWED, POLL_ALLOWED, HOOK_ALLOWED, RTC_ENTITIES); a whole-state
                      diff against the rig baseline (state_violations: catches array / record writes that bypass set_global); the
                      wire audit (only FC16 22-24 + FC03 22/3 from RTC paths, only the five poll blocks from poll paths); the NVS
                      audit; I1 (no progress flag without the lock) after EVERY 1 s RTC tick; I2 (at most one RTC frame queued or
                      in flight); I3 (no FC16 22-24 queued while manual_write_in_progress)
  G9 oracle           before every regular RTC read response the inputs of ecco_rtc::decide() are collected from the world
                      (error from the register words and the wall clock, tod / day / elapsed independently computed, the flags
                      from the pre-response state) and registry/rtc_policy.decide() is compared with what the firmware did
                      (reason, queue, rtc_prev_err_s, boot alignment, precision key, txn stamps); the oracle also keeps its own
                      record of the previous regular read and cross-checks the firmware's rtc_prev_err_s / previous_ntp_sod
  I6 tracker          every corrections_since_boot increment must come from an FC03 22/3 response sent AFTER the last FC16
                      acknowledgement, read while verification_read_active, whose decoded time passes the verification rule
  fence rig           make_fence_rig(): the FB-B2 boot (VALID stored profile, trusted environment) + the 10 s housekeeping /
                      B10 refresh, with the B10 text checked after every housekeeping tick (never MATCH while the RTC lock is
                      held; MATCH only once the cache was dispatched twice after the last hot fence sample)

No I/O beyond reading the firmware YAML, no hardware, no network.
"""

from __future__ import annotations

import hashlib
import math
import sys
import time as _time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT / "tools"), str(ROOT / "registry"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

import _dump_sim as ds  # noqa: E402
import _fbb1_engine as E  # noqa: E402
import _fbb_harness as H  # noqa: E402
import _fbd1_scope as scope  # noqa: E402
import rtc_policy as rp  # noqa: E402

FbbNotModelled = H.FbbNotModelled
FW_PATH = ROOT / scope.FIRMWARE_REL

# ---------------------------------------------------------------------------------------------------------------------------
# firmware texts
# ---------------------------------------------------------------------------------------------------------------------------
_LIVE: list = []
_FW_CACHE: dict = {}


def live_text() -> str:
    """The firmware YAML as Path.read_text returns it (LF; the working tree is CRLF)."""
    if not _LIVE:
        _LIVE.append(FW_PATH.read_text(encoding="utf-8"))
    return _LIVE[0]


def pre_text(live: str | None = None) -> str:
    """The firmware with exactly FB-D1's edits removed (== main, the FB-C2 checkpoint)."""
    return scope.pre_fbd1_firmware(live if live is not None else live_text())


def load(text: str) -> dict:
    """Parsed firmware (cached by sha256; FbbSim never mutates it)."""
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    fw = _FW_CACHE.get(key)
    if fw is None:
        fw = _FW_CACHE[key] = ds.load_firmware_text(text)
    return fw


def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    """An exact-count text mutant (a mutant can never be a silent no-op)."""
    n = text.count(old)
    if n != count:
        raise AssertionError(f"mutation anchor occurs {n} times, want {count}: {old[:90]!r}")
    return text.replace(old, new)


# ---------------------------------------------------------------------------------------------------------------------------
# civil time: Europe/London without a tz database (BST from the last Sunday of March 01:00 UTC to the last Sunday of October
# 01:00 UTC)
# ---------------------------------------------------------------------------------------------------------------------------
def days_from_civil(y: int, m: int, d: int) -> int:
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * ((m + 9) % 12) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z: int) -> tuple:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d)


def _last_sunday_0100_utc(year: int, month: int) -> int:
    nxt = days_from_civil(year + (1 if month == 12 else 0), month % 12 + 1, 1)
    last = nxt - 1
    sunday = last - (last + 4) % 7  # (days + 4) % 7 == 0 on a Sunday: 1970-01-01 was a Thursday
    return sunday * 86400 + 3600


def london_offset_s(utc_s: int) -> int:
    y = civil_from_days(utc_s // 86400)[0]
    return 3600 if _last_sunday_0100_utc(y, 3) <= utc_s < _last_sunday_0100_utc(y, 10) else 0


def utc_of_local(Y: int, M: int, D: int, h: int = 0, mi: int = 0, s: int = 0) -> int:
    """The UTC epoch whose Europe/London local time is Y-M-D h:mi:s (the BST reading of an ambiguous hour)."""
    loc = days_from_civil(Y, M, D) * 86400 + h * 3600 + mi * 60 + s
    for off in (3600, 0):
        if london_offset_s(loc - off) == off:
            return loc - off
    raise ValueError(f"{Y}-{M}-{D} {h}:{mi}:{s} does not exist in Europe/London")


def local_fields(local_s: int) -> dict:
    days, sod = divmod(int(local_s), 86400)
    y, m, d = civil_from_days(days)
    return {"year": y, "month": m, "day": d, "hour": sod // 3600, "minute": (sod // 60) % 60, "second": sod % 60,
            "sod": sod, "days": days, "dow": (days + 4) % 7 + 1, "doy": days - days_from_civil(y, 1, 1) + 1}


def hms(h: int, m: int, s: int = 0) -> int:
    return h * 3600 + m * 60 + s


class EspTime:
    """esphome::ESPTime as the firmware uses it (local fields, day_of_week 1 = Sunday)."""

    def __init__(self, utc_s: int, valid: bool):
        off = london_offset_s(int(utc_s))
        f = local_fields(int(utc_s) + off)
        self.year, self.month, self.day_of_month = f["year"], f["month"], f["day"]
        self.hour, self.minute, self.second = f["hour"], f["minute"], f["second"]
        self.day_of_week, self.day_of_year = f["dow"], f["doy"]
        self.timestamp = int(utc_s)
        self.is_dst = off != 0
        self._valid = bool(valid)

    def is_valid(self):
        return self._valid

    def strftime(self, fmt):
        st = _time.struct_time((self.year, self.month, self.day_of_month, self.hour, self.minute, self.second,
                                (self.day_of_week + 5) % 7, self.day_of_year, int(self.is_dst)))
        return ds.CStr(_time.strftime(str(fmt), st))

    def local_s(self) -> int:
        return days_from_civil(self.year, self.month, self.day_of_month) * 86400 + self.hour * 3600 + self.minute * 60 + self.second


class WallClock(ds.Entity):
    """`id(ntp_time)`: the wall clock flows with the virtual clock (utc_ms = utc0_ms + now_ms - t0_ms); validity is sim.ntp_valid."""

    def __init__(self, sim, utc_epoch_s: int, t0_ms: int | None = None):
        super().__init__(sim, "ntp_time")
        self.utc0_ms = int(utc_epoch_s) * 1000
        self.t0_ms = sim.now_ms if t0_ms is None else int(t0_ms)

    def utc_ms(self, t_ms: int | None = None) -> int:
        return self.utc0_ms + ((self._sim.now_ms if t_ms is None else int(t_ms)) - self.t0_ms)

    def utc_s(self, t_ms: int | None = None) -> int:
        return self.utc_ms(t_ms) // 1000

    def local_ms(self, t_ms: int | None = None) -> int:
        u = self.utc_ms(t_ms)
        return u + 1000 * london_offset_s(u // 1000)

    def local_s(self, t_ms: int | None = None) -> int:
        return self.local_ms(t_ms) // 1000

    def tod(self, t_ms: int | None = None) -> int:
        return self.local_s(t_ms) % 86400

    def now(self):
        return EspTime(self.utc_s(), bool(self._sim.ntp_valid))

    def step(self, seconds: float) -> None:
        """An SNTP step: the wall clock jumps by `seconds`."""
        self.utc0_ms += int(round(seconds * 1000))

    def ms_until_local(self, h: int, m: int, s: int = 0) -> int:
        """Virtual ms from now until the next local h:m:s."""
        cur = self.local_ms()
        tgt = (cur // 86400000) * 86400000 + hms(h, m, s) * 1000
        if tgt <= cur:
            tgt += 86400000
        return tgt - cur


# ---------------------------------------------------------------------------------------------------------------------------
# the inverter RTC device model (G3)
# ---------------------------------------------------------------------------------------------------------------------------
def pack_rtc(local_s: int) -> list:
    f = local_fields(local_s)
    return [((f["year"] - 2000) << 8) | f["month"], (f["day"] << 8) | f["hour"], (f["minute"] << 8) | f["second"]]


def decode_rtc(values) -> dict | None:
    """The fields read_inverter_clock decodes, or None for the words it rejects as invalid."""
    v0, v1, v2 = (int(values[0]), int(values[1]), int(values[2]))
    y, mo, d = 2000 + ((v0 >> 8) & 0xFF), v0 & 0xFF, (v1 >> 8) & 0xFF
    h, mi, s = v1 & 0xFF, (v2 >> 8) & 0xFF, v2 & 0xFF
    if y < 2020 or y > 2099 or mo < 1 or mo > 12 or d < 1 or d > 31 or h > 23 or mi > 59 or s > 59:
        return None
    return {"year": y, "month": mo, "day": d, "hour": h, "minute": mi, "second": s, "sod": h * 3600 + mi * 60 + s,
            "local_s": days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s}


class InverterRtc:
    """The inverter clock (naive local time in integer ms) as piecewise linear segments (start_ms, value_ms, rate): value(t) =
    value_ms + (t - start) * (1 + rate). The Modbus image shows value(image_time(t)): with image_period_ms > 0 the image refreshes
    on that grid (0..period stale), inside a freeze window [a, b) it shows the image of `a`. apply_write() starts a new segment at
    the written value (minus set_loss_s) when an FC16 22-24 lands; `writes_applied` records every landed write."""

    def __init__(self, sim, offset_s: float = 0.0, rate: float = 0.0, *, image_period_ms: int = 0, image_phase_ms: int = 0):
        self.sim = sim
        t = sim.now_ms
        self.segs = [(t, sim.clock.local_ms(t) + int(round(offset_s * 1000)), float(rate))]
        self.image_period_ms = int(image_period_ms)
        self.image_phase_ms = int(image_phase_ms)
        self.freezes: list = []
        self.post_write_freeze_ms = 0
        self.set_loss_s = 0.0
        self.writes_applied: list = []
        self.override_words: list = []  # explicit word triples for the next reads (e.g. invalid data)
        self.reads_served = 0

    def value_ms(self, t_ms: int) -> int:
        seg = self.segs[0]
        for s in reversed(self.segs):
            if t_ms >= s[0]:
                seg = s
                break
        start, v0, rate = seg
        dt = t_ms - start
        return v0 + dt + int(round(dt * rate))

    def _now(self, t_ms):
        return self.sim.now_ms if t_ms is None else int(t_ms)

    def rate(self) -> float:
        return self.segs[-1][2]

    def set_rate(self, rate: float, t_ms: int | None = None) -> None:
        t = self._now(t_ms)
        self.segs.append((t, self.value_ms(t), float(rate)))

    def set_offset(self, offset_s: float, t_ms: int | None = None) -> None:
        t = self._now(t_ms)
        self.segs.append((t, self.sim.clock.local_ms(t) + int(round(offset_s * 1000)), self.rate()))

    def step(self, seconds: float, t_ms: int | None = None) -> None:
        t = self._now(t_ms)
        self.segs.append((t, self.value_ms(t) + int(round(seconds * 1000)), self.rate()))

    def offset_s(self, t_ms: int | None = None) -> float:
        t = self._now(t_ms)
        return (self.value_ms(t) - self.sim.clock.local_ms(t)) / 1000.0

    def freeze(self, start_ms: int, end_ms: int) -> None:
        self.freezes.append((int(start_ms), int(end_ms)))

    def image_time(self, t_ms: int) -> int:
        for a, b in self.freezes:
            if a <= t_ms < b:
                t_ms = a
                break
        if self.image_period_ms > 0:
            k = (t_ms - self.image_phase_ms) // self.image_period_ms
            t_ms = k * self.image_period_ms + self.image_phase_ms
        return t_ms

    def image_local_s(self, t_ms: int | None = None) -> int:
        return self.value_ms(self.image_time(self._now(t_ms))) // 1000

    def words(self, t_ms: int | None = None) -> list:
        return pack_rtc(self.image_local_s(t_ms))

    def read_words(self, t_ms: int) -> list:
        self.reads_served += 1
        if self.override_words:
            return list(self.override_words.pop(0))
        return self.words(t_ms)

    def apply_write(self, vals, t_ms: int) -> None:
        d = decode_rtc(vals)
        if d is None:  # the inverter keeps running when it is sent an invalid time
            self.writes_applied.append((t_ms, None))
            return
        self.segs.append((t_ms, d["local_s"] * 1000 - int(round(self.set_loss_s * 1000)), self.rate()))
        # a landed write refreshes the register image: a freeze in progress ends here (model choice, documented)
        self.freezes = [(a, min(b, t_ms)) if a <= t_ms < b else (a, b) for a, b in self.freezes]
        if self.post_write_freeze_ms:
            self.freezes.append((t_ms, t_ms + self.post_write_freeze_ms))
        self.writes_applied.append((t_ms, d["local_s"]))

    def shift(self, delta_ms: int) -> None:
        self.segs = [(s + delta_ms, v, r) for s, v, r in self.segs]
        self.freezes = [(a + delta_ms, b + delta_ms) for a, b in self.freezes]
        self.image_phase_ms += delta_ms


# ---------------------------------------------------------------------------------------------------------------------------
# path classification and allow-lists (G8)
# ---------------------------------------------------------------------------------------------------------------------------
RTC_SCRIPTS = ("write_inverter_rtc",)
RTC_BUTTONS = ("read_inverter_clock", "sync_inverter_clock")
POLL_SCRIPTS = ("poll_inverter_telemetry", "poll_inverter_configuration", "poll_inverter_configuration_dispatch")

# Globals an RTC path (write_inverter_rtc, the two RTC buttons, the 60 s RTC read interval, the 1 s RTC tick) may assign: the RTC
# state of main plus the FB-D1 RAM globals. Written out here, independently of the firmware.
RTC_ALLOWED = frozenset({
    "latest_clock_difference", "clock_difference_valid", "auto_sync_pending", "correction_in_progress", "correction_is_manual",
    "correction_attempt", "verification_pending", "verification_read_active", "verification_due_ms", "comm_failure_pending",
    "cooldown_until_ms", "corrections_since_boot", "failed_corrections", "write_attempts_since_boot", "rtc_stall_count",
    "max_clock_error", "have_rtc_baseline", "previous_inverter_sod", "previous_ntp_sod",
    "rtc_txn_since_ms", "rtc_verify_dispatching", "rtc_lock_seen", "rtc_prev_err_s", "rtc_have_last_auto", "rtc_last_auto_ms",
    "rtc_precision_served", "rtc_boot_aligned", "rtc_policy_reason", "cfg_poll_owed",
})
RTC_ENTITIES = frozenset({"last_correction_result", "inverter_clock", "clock_difference", "rtc_stall_detected", "last_correction"})
# Globals a poll path (the two poll scripts + wrapper, the telemetry / configuration intervals, the catch-up interval) may assign.
POLL_ALLOWED = frozenset({
    "telemetry_failures", "configuration_failures", "configuration_block1_ok", "manual_config_raw_cache_valid", "fbc_raw_filled",
    "cfg_block_b_seq", "cfg_block_b_ok_ms", "cfg_block_b_dispatch_seq", "cfg_block_b_response_dispatch_seq", "cfg_poll_owed",
})
POLL_ALLOWED_PREFIXES = ("manual_cfg_reg", "fbc_raw_")
# The telemetry sensors' on_value hooks (Dump grid / SOC freshness, overpower sampling) - run by the telemetry publishes.
HOOK_ALLOWED = frozenset({"dump_soc_last_update_ms", "dump_grid_last_update_ms", "dump_overpower_samples",
                          "dump_absolute_overpower_samples", "dump_overpower_last_w"})
# Ownership flags no RTC / poll path may ever assign.
OWNERSHIP_FLAGS = ("manual_write_in_progress", "free_power_operation_in_progress", "free_power_recovery_force_in_progress",
                   "free_power_recovery_accept_in_progress", "reg244_apply_in_progress", "dump_operation_in_progress",
                   "fallback_profile_op_in_progress")
LEASE_FLAGS = ("free_power_active_persisted", "free_power_restore_requested", "free_power_operation_in_progress",
               "dump_active_persisted", "dump_restore_requested", "dump_operation_in_progress", "reg244_apply_in_progress")
PROGRESS_FLAGS = ("auto_sync_pending", "verification_pending", "verification_read_active", "comm_failure_pending")
POLL_FRAMES = frozenset({("read", 59, 58), ("read", 150, 47), ("read", 200, 41), ("read", 241, 53), ("read", 330, 1)})
RTC_FRAMES = frozenset({("write", 22, 3), ("read", 22, 3)})
RTC_ISSUERS = ("write_inverter_rtc", "button:read_inverter_clock", "button:sync_inverter_clock")
POLL_ISSUERS = ("poll_inverter_telemetry", "poll_inverter_configuration", "poll_inverter_configuration_dispatch")

WRITE_OUTCOMES = ("ok", "ack_not_applied", "error", "no_response_landed", "no_response_lost", "custom_response", "not_sent",
                  "timeout_landed", "timeout_lost")
WRITE_ALIASES = {"no_response": "no_response_lost", "timeout": "timeout_lost"}
WRITE_LANDED = frozenset({"ok", "no_response_landed", "timeout_landed"})
WRITE_HANDLER = {"ok": "on_response", "ack_not_applied": "on_response", "error": "on_error", "not_sent": "on_not_sent",
                 "no_response_landed": "on_no_response", "no_response_lost": "on_no_response",
                 "custom_response": "on_custom_response"}
TERMINAL_HANDLERS = ("on_response", "on_error", "on_no_response", "on_not_sent", "on_custom_response")
GOLD_TOU = (0, 530, 1000, 1600, 2100, 2330)  # the golden profile's TOU zone starts (00:00 05:30 10:00 16:00 21:00 23:30)


def _lambdas(node, out: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, ds.LambdaStr):
                out.append(str(v))
            elif k == "lambda" and isinstance(v, str):
                out.append(v)
            else:
                _lambdas(v, out)
    elif isinstance(node, list):
        for x in node:
            _lambdas(x, out)


def modbus_actions(node, out: list | None = None) -> list:
    """Every modbus_client read / write action mapping under `node` (handlers included), in document order."""
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            if k in (ds.READ, ds.WRITE) and isinstance(v, dict):
                out.append((k, v))
            modbus_actions(v, out)
    elif isinstance(node, list):
        for x in node:
            modbus_actions(x, out)
    return out


_IV_CACHE: dict = {}


def interval_ids(fw: dict) -> dict:
    """{"rtc_read", "rtc_tick", "telemetry", "config", "catchup" (FB-D1 only), "housekeeping", "fbc"} -> interval index."""
    key = id(fw)
    if key in _IV_CACHE and _IV_CACHE[key][0] is fw:
        return _IV_CACHE[key][1]
    ids = {}
    for i, iv in enumerate(fw.get("interval") or []):
        txt = yaml.dump(iv["then"])
        period = str(iv["interval"])
        if "Processing queued NTP clock correction" in txt:
            ids["rtc_tick"] = i
        elif period == "60s" and "read_inverter_clock" in txt:
            ids["rtc_read"] = i
        elif "poll_inverter_telemetry" in txt:
            ids["telemetry"] = i
        elif period == "2s" and "cfg_poll_owed" in txt:
            ids["catchup"] = i
        elif period == "60s" and "poll_inverter_configuration" in txt:
            ids["config"] = i
        elif "fallback_profile_cand_valid" in txt:
            ids["housekeeping"] = i
        elif "failback_shadow_ready" in txt:
            ids["fbc"] = i
    _IV_CACHE[key] = (fw, ids)
    return ids


def domain_map(fw: dict) -> tuple:
    """(code -> domain, ambiguous codes): every lambda text of the firmware attributed to the path it belongs to."""
    iv = interval_ids(fw)
    owners: dict = {}

    def add(node, dom):
        out: list = []
        _lambdas(node, out)
        for c in out:
            owners.setdefault(c, set()).add(dom)
    for sc in fw.get("script") or []:
        sid = sc.get("id")
        add(sc.get("then"), "rtc" if sid in RTC_SCRIPTS else "poll" if sid in POLL_SCRIPTS else "other")
    for b in fw.get("button") or []:
        add(b.get("on_press"), "rtc" if b.get("id") in RTC_BUTTONS else "other")
    rtc_iv = {iv.get("rtc_read"), iv.get("rtc_tick")}
    poll_iv = {iv.get("telemetry"), iv.get("config"), iv.get("catchup")}
    for i, x in enumerate(fw.get("interval") or []):
        add(x.get("then"), "rtc" if i in rtc_iv else "poll" if i in poll_iv else "other")
    for s in fw.get("sensor") or []:
        if s.get("on_value"):
            add(s["on_value"], "hook")
    for key in ("esphome", "time", "api", "switch", "number", "text_sensor", "binary_sensor", "select"):
        add(fw.get(key), "other")
    dmap, ambiguous = {}, {}
    for c, doms in owners.items():
        if len(doms) == 1:
            dmap[c] = next(iter(doms))
        else:
            dmap[c] = "ambiguous:" + "|".join(sorted(doms))
            ambiguous[c] = doms
    return dmap, ambiguous


def _find_button(fw, bid):
    for b in fw.get("button") or []:
        if b.get("id") == bid:
            return b
    return None


def _find_script(fw, sid):
    for s in fw.get("script") or []:
        if s.get("id") == sid:
            return s
    return None


def _u32(v: int) -> int:
    return int(v) & 0xFFFFFFFF


def _i32(v: int) -> int:
    v = int(v) & 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------------------------------------------------------------------
# the simulator
# ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class WriteRec:
    t: int
    addr: int
    vals: list
    outcome: str
    issuer: str | None
    hub_busy: bool
    mwip: bool
    cip: bool


class WriteFrame(E.Frame):
    """An FC16 frame on the hub (G4)."""

    def __init__(self, sim, body, local, addr, vals, outcome, latency_ms, issuer):
        spec = E.FrameSpec(outcome="ok", latency_ms=latency_ms)
        spec._d1_write = self  # type: ignore[attr-defined]
        super().__init__("fw-write", addr, len(vals), spec, body=body, local=local,
                         on_deliver=lambda s, f: s._write_delivered(f))
        self.vals = list(vals)
        self.outcome = outcome
        self.wire = E.Wire("fw", "write", addr, len(vals), outcome, t_queued=sim.now_ms, values=list(vals), issuer=issuer)


class D1Entity(H.FbbEntity):
    """FbbEntity whose publications are attributed to the firmware path that made them (G8) and time-stamped for a few ids."""

    def publish_state(self, value):
        sim = self._sim
        if sim.audit_on:
            dom = sim._domain_stack[-1] if sim._domain_stack else "test"
            key = (dom, self.name)
            sim.pub_seen[key] = sim.pub_seen.get(key, 0) + 1
        if self.name in sim.pub_timed:
            sim.pub_times.append((sim.now_ms, self.name, str(value)))
        super().publish_state(value)


class D1Sim(H.FbbSim):
    """FbbSim + the FB-D1 instruments (see the module docstring). Construct with make_rig() / make_fence_rig() normally."""

    def __init__(self, firmware: dict, nvs=None, tick_ms: int = 10, *, fbcap=None, fbsave=None):
        self._domain_stack: list = []
        self.assign_seen: dict = {}
        self.pub_seen: dict = {}
        self.pub_timed = {"last_correction_result", "last_correction", "fallback_profile_live_match_text"}
        self.pub_times: list = []
        self.audit_on = True
        super().__init__(firmware, nvs, tick_ms, fbcap=fbcap, fbsave=fbsave)
        self.iv = interval_ids(firmware)
        self._domain_of, self.ambiguous_lambdas = domain_map(firmware)
        rb = _find_button(firmware, "read_inverter_clock")
        self._rtc_read_body = rb["on_press"][0][ds.READ] if rb else None
        ws = _find_script(firmware, "write_inverter_rtc")
        wacts = modbus_actions(ws["then"]) if ws else []
        self._rtc_write_body = next((b for k, b in wacts if k == ds.WRITE), None)
        self.write_mode = "immediate"
        self.write_latency_ms = None
        self.clock: WallClock | None = None
        self.rtc: InverterRtc | None = None
        self.inner_read_override = None
        self.read_override_fn = self._rtc_read_override
        self._delivering = None
        # evidence
        self.write_log: list = []
        self.write_acks: list = []
        self.cip_edges: list = []
        self.i1_violations: list = []
        self.i2_violations: list = []
        self.i3_violations: list = []
        self.successes: list = []
        self.rtc_ticks = 0
        self.oracle_on = False
        self.oracle_reads: list = []
        self.oracle_mismatches: list = []
        self._oracle_last = None
        self.fence_on = False
        self.fence_violations: list = []
        self.fence_log: list = []
        self._last_hot_dispatch = None
        self.nvs_mark = None
        self.poked: set = set()
        self._state0 = None

    # -- entities ----------------------------------------------------------------------------------------------------------
    def ent(self, name):
        e = self.entities.get(name)
        if e is None:
            e = self.entities[name] = D1Entity(self, name)
        return e

    # -- attribution (G8) --------------------------------------------------------------------------------------------------
    def run_lambda(self, code, local=None, params=()):
        self._domain_stack.append(self._domain_of.get(code, "test"))
        try:
            return super().run_lambda(code, local, params)
        finally:
            self._domain_stack.pop()

    def set_global(self, name, value):
        if self.audit_on:
            dom = self._domain_stack[-1] if self._domain_stack else "test"
            if dom != "test":
                key = (dom, name)
                self.assign_seen[key] = self.assign_seen.get(key, 0) + 1
        if name == "correction_in_progress":
            new = bool(value)
            if new != bool(self.g.get(name)):
                self.cip_edges.append((self.now_ms, new))
        super().set_global(name, value)

    def poke(self, name, value) -> None:
        """A test-side state change (not attributed to any firmware path; exempt from state_violations())."""
        if name == "correction_in_progress" and bool(value) != bool(self.g.get(name)):
            self.cip_edges.append((self.now_ms, bool(value)))
        self.poked.add(name)
        ds.Sim.set_global(self, name, value)

    # -- the inverter registers (G3) ---------------------------------------------------------------------------------------
    def _rtc_read_override(self, addr, count, values):
        out = list(values)
        if self.rtc is not None and addr <= 24 and addr + count - 1 >= 22:
            w = self.rtc.read_words(self.now_ms)
            for i in range(count):
                if 22 <= addr + i <= 24:
                    out[i] = w[addr + i - 22]
        if self.inner_read_override is not None:
            out = self.inner_read_override(addr, count, out)
        return out

    def _snapshot(self, addr, count, spec):
        wf = getattr(spec, "_d1_write", None)
        if wf is not None:  # an FC16 frame goes on the wire: it carries its own values
            self.modbus_log.append(("write", wf.addr, list(wf.vals), wf.outcome))
            self._log_event(("write_start", wf.addr, list(wf.vals), wf.outcome))
            return list(wf.vals)
        return super()._snapshot(addr, count, spec)

    # -- writes (G4) -------------------------------------------------------------------------------------------------------
    def _write_outcome(self, addr, n):
        if self.frame_script:
            r = self.frame_script.pop(0)
            if callable(r):
                r = r(addr, n)
        else:
            r = self.outcome_fn("write", addr, n)
        latency = None
        if isinstance(r, E.FrameSpec):
            latency, r = r.latency_ms, r.outcome
        elif isinstance(r, dict):
            latency, r = r.get("latency_ms"), r.get("outcome", "ok")
        r = WRITE_ALIASES.get(r, r)
        if r not in WRITE_OUTCOMES:
            raise FbbNotModelled(f"write outcome {r!r} (modelled: {', '.join(WRITE_OUTCOMES)})")
        return r, latency

    def _write_land(self, addr, vals, outcome):
        if outcome not in WRITE_LANDED:
            return
        for i, v in enumerate(vals):
            self.bank[addr + i] = v
        if self.rtc is not None and addr == 22 and len(vals) == 3:
            self.rtc.apply_write(vals, self.now_ms)

    def _modbus_write(self, body, local):
        addr = int(body["start_address"])
        vals = [int(v) & 0xFFFF for v in self.run_lambda(body["values"], local, params=tuple((local or {}).keys()))]
        outcome, latency = self._write_outcome(addr, len(vals))
        issuer = self._cur_task.label if self._cur_task is not None else None
        busy = not (self.hub.tx_buffer_empty() and not self.hub.tx_blocked())
        self.write_log.append(WriteRec(self.now_ms, addr, list(vals), outcome, issuer, busy,
                                       bool(self.g.get("manual_write_in_progress")), bool(self.g.get("correction_in_progress"))))
        if addr == 22 and self.g.get("manual_write_in_progress"):
            self.i3_violations.append((self.now_ms, "FC16 22-24 queued while manual_write_in_progress"))
        if outcome == "not_sent":  # refused at the door: fires synchronously inside the action, never reaches the wire
            self.modbus_log.append(("write", addr, list(vals), "not_sent"))
            self._log_event(("write", addr, list(vals), "not_sent"))
            self._handler(body, "on_not_sent", local)
            return
        if self.write_mode == "immediate":
            self.modbus_log.append(("write", addr, list(vals), outcome))
            self.wire_log.append(E.Wire("fw", "write", addr, len(vals), outcome, self.now_ms, self.now_ms, self.now_ms,
                                        list(vals), issuer))
            self._write_land(addr, vals, outcome)
            self._log_event(("write", addr, list(vals), outcome))
            h = WRITE_HANDLER.get(outcome)
            if h:
                self._handler(body, h, local, exception_code=self.exception_code if h == "on_error" else None)
            return
        lat = latency if latency is not None else (self.write_latency_ms if self.write_latency_ms is not None
                                                   else self.frame_latency_ms)
        self._hub_submit(WriteFrame(self, body, dict(local or {}), addr, vals, outcome, int(lat), issuer))

    def _write_delivered(self, frame):
        self._write_land(frame.addr, frame.vals, frame.outcome)
        self._log_event(("write", frame.addr, list(frame.vals), frame.outcome))
        h = WRITE_HANDLER.get(frame.outcome)
        if h:
            self._handler(frame.body, h, frame.local, exception_code=self.exception_code if h == "on_error" else None)

    def _hub_submit(self, frame):
        if isinstance(frame, WriteFrame):  # the hub sends WRITE-class frames ahead of queued one-shot reads
            frame.wire.t_queued = self.now_ms
            frames = self.hub.frames
            idx = next((i for i, f in enumerate(frames) if not isinstance(f, WriteFrame)), len(frames))
            frames.insert(idx, frame)
            self._hub_kick()
        else:
            super()._hub_submit(frame)
        n = sum(1 for f in list(self.hub.frames) + [self.hub.in_flight_frame] if f is not None and self._is_rtc_frame(f))
        if n > 1:
            self.i2_violations.append((self.now_ms, n))

    @staticmethod
    def _is_rtc_frame(f) -> bool:
        if isinstance(f, WriteFrame):
            return f.addr == 22
        return f.origin == "fw" and f.addr == 22 and f.count == 3

    def _hub_complete(self, frame):
        prev, self._delivering = self._delivering, frame
        try:
            super()._hub_complete(frame)
        finally:
            self._delivering = prev

    # -- handlers: write acks, the RTC read response (oracle + I6) ---------------------------------------------------------
    def _handler(self, body, name, local, values=None, exception_code=None):
        if body is not None and body is self._rtc_write_body and name == "on_response":
            self.write_acks.append(self.now_ms)
        if body is not None and body is self._rtc_read_body and name == "on_response":
            return self._rtc_read_response(body, name, local, values, exception_code)
        return super()._handler(body, name, local, values, exception_code)

    def _rtc_read_response(self, body, name, local, values, exception_code):
        g = self.g
        pre = dict(g)
        frame = self._delivering
        t_sent = frame.wire.t_start if (frame is not None and frame.wire.t_start is not None) else self.now_ms
        ctx = self._oracle_ctx(values, pre) if self.oracle_on else None
        super()._handler(body, name, local, values, exception_code)
        if g.get("corrections_since_boot", 0) > pre.get("corrections_since_boot", 0):
            self._check_success(pre, values, t_sent)
        if ctx is not None:
            self._oracle_compare(ctx, pre)

    def _ntp_fields(self):
        now = self.clock.now()
        return now, now.local_s(), now.hour * 3600 + now.minute * 60 + now.second

    def _check_success(self, pre, values, t_sent):
        d = decode_rtc(values)
        now, _loc, ntp_sod = self._ntp_fields()
        last_ack = self.write_acks[-1] if self.write_acks else None
        thr = int(self.ent("correction_threshold").state)
        why = []
        if not pre.get("verification_read_active"):
            why.append("not a verification read")
        if last_ack is None or t_sent < last_ack:
            why.append(f"read sent at {t_sent} before the last FC16 ack {last_ack}")
        if d is None:
            why.append("invalid words")
        else:
            diff = d["sod"] - ntp_sod
            if diff > 43200:
                diff -= 86400
            if diff < -43200:
                diff += 86400
            if (d["year"], d["month"], d["day"]) != (now.year, now.month, now.day_of_month):
                why.append("date mismatch")
            if abs(diff) > thr:
                why.append(f"|error| {abs(diff)} > threshold {thr}")
        self.successes.append((self.now_ms, not why, "; ".join(why)))

    # -- the policy oracle (G9) --------------------------------------------------------------------------------------------
    def _oracle_ctx(self, values, pre):
        if pre.get("verification_read_active"):
            return None
        d = decode_rtc(values)
        if d is None or not pre.get("ntp_synced") or not self.clock.now().is_valid():
            return None
        now, ntp_local, ntp_sod = self._ntp_fields()
        m = self.millis()
        inp = rp.Inputs()
        inp.auto_sync = bool(self.ent("automatic_clock_sync").state)
        inp.lock_held = bool(pre["correction_in_progress"])
        cd = pre["cooldown_until_ms"]
        inp.cooldown_active = cd != 0 and _i32(m - cd) < 0
        inp.lease_active = any(bool(pre[f]) for f in LEASE_FLAGS)
        inp.boot_aligned = bool(pre["rtc_boot_aligned"])
        err = d["local_s"] - ntp_local
        inp.err_s = max(-rp.kErrorClampS, min(rp.kErrorClampS, err))
        inp.prev_valid = bool(pre["have_rtc_baseline"])
        inp.prev_err_s = int(pre["rtc_prev_err_s"])
        inp.ntp_elapsed_s = (ntp_sod - int(pre["previous_ntp_sod"])) % 86400
        inp.inv_elapsed_s = (d["sod"] - int(pre["previous_inverter_sod"])) % 86400
        inp.tod_s = ntp_sod
        inp.day = days_from_civil(now.year, now.month, now.day_of_month)
        inp.threshold_s = int(self.ent("correction_threshold").state)
        inp.have_last_auto = bool(pre["rtc_have_last_auto"])
        inp.since_last_auto_ms = _u32(m - int(pre["rtc_last_auto_ms"]))
        inp.precision_served = int(pre["rtc_precision_served"])
        inp.tou_raw = [int(pre[f"manual_cfg_reg{r}_raw"]) for r in range(250, 256)]
        return {"inp": inp, "dec": rp.decide(inp), "d": d, "ntp_sod": ntp_sod, "m": m, "t": self.now_ms}

    def _oracle_compare(self, ctx, pre):
        g, inp, dec, d, t = self.g, ctx["inp"], ctx["dec"], ctx["d"], ctx["t"]
        bad = []

        def eq(field, want, got):
            if want != got:
                bad.append((t, field, want, got))
        # the oracle's own record of the previous regular read (independent bookkeeping)
        last = self._oracle_last
        if pre["have_rtc_baseline"] and last is not None:
            eq("pre rtc_prev_err_s == the oracle's previous regular error", last["err"], int(pre["rtc_prev_err_s"]))
            eq("pre previous_ntp_sod == the oracle's previous regular NTP second", last["ntp_sod"], int(pre["previous_ntp_sod"]))
            eq("pre previous_inverter_sod == the oracle's previous regular inverter second", last["inv_sod"],
               int(pre["previous_inverter_sod"]))
        eq("rtc_policy_reason", dec.reason, int(g["rtc_policy_reason"]))
        eq("rtc_prev_err_s", inp.err_s, int(g["rtc_prev_err_s"]))
        queued = bool(g["correction_in_progress"]) and not bool(pre["correction_in_progress"])
        eq("queued", dec.action == rp.ACT_CORRECT, queued)
        eq("rtc_boot_aligned", bool(pre["rtc_boot_aligned"]) or dec.boot_settled, bool(g["rtc_boot_aligned"]))
        if dec.action == rp.ACT_CORRECT:
            eq("auto_sync_pending", True, bool(g["auto_sync_pending"]))
            eq("correction_attempt", 1, int(g["correction_attempt"]))
            eq("correction_is_manual", False, bool(g["correction_is_manual"]))
            eq("rtc_txn_since_ms", ctx["m"], int(g["rtc_txn_since_ms"]))
            eq("rtc_last_auto_ms", ctx["m"], int(g["rtc_last_auto_ms"]))
            eq("rtc_have_last_auto", True, bool(g["rtc_have_last_auto"]))
            eq("have_rtc_baseline", False, bool(g["have_rtc_baseline"]))
            eq("rtc_precision_served", dec.precision_key if dec.precision_key else int(pre["rtc_precision_served"]),
               int(g["rtc_precision_served"]))
        else:
            eq("have_rtc_baseline", True, bool(g["have_rtc_baseline"]))
            eq("previous_ntp_sod", ctx["ntp_sod"], int(g["previous_ntp_sod"]))
            eq("previous_inverter_sod", d["sod"], int(g["previous_inverter_sod"]))
            eq("rtc_precision_served unchanged", int(pre["rtc_precision_served"]), int(g["rtc_precision_served"]))
        self._oracle_last = {"err": inp.err_s, "ntp_sod": ctx["ntp_sod"], "inv_sod": d["sod"]}
        self.oracle_reads.append({"t": t, "tod": inp.tod_s, "err": inp.err_s, "reason": dec.reason, "action": dec.action,
                                  "thr": dec.threshold_s, "pkey": dec.precision_key, "prev_err": inp.prev_err_s,
                                  "prev_valid": inp.prev_valid})
        self.oracle_mismatches.extend(bad)

    # -- per-tick invariants (I1) and the fence (B10) ----------------------------------------------------------------------
    def _fire_interval(self, st):
        hk = self.fence_on and st.idx == self.iv.get("housekeeping")
        if hk:
            g = self.g
            if g["correction_in_progress"] or g["verification_pending"] or g["verification_read_active"] or \
                    g["manual_write_in_progress"]:
                self._last_hot_dispatch = int(g["cfg_block_b_dispatch_seq"])
        super()._fire_interval(st)
        if st.idx == self.iv.get("rtc_tick"):
            self.rtc_ticks += 1
            g = self.g
            if not g["correction_in_progress"] and any(g[f] for f in PROGRESS_FLAGS):
                self.i1_violations.append((self.now_ms, {f: bool(g[f]) for f in PROGRESS_FLAGS}))
        if hk:
            self._after_housekeeping()

    def b10(self) -> str:
        return str(self.ent("fallback_profile_live_match_text").state)

    def b10_m(self) -> str:
        t = self.b10()
        return t.split(";")[0][2:] if t.startswith("m=") else t

    def _after_housekeeping(self):
        g = self.g
        m = self.b10_m()
        self.fence_log.append((self.now_ms, m, bool(g["correction_in_progress"]), int(g["cfg_block_b_dispatch_seq"]),
                               int(g["cfg_block_b_response_dispatch_seq"])))
        if m == "MATCH":
            if g["correction_in_progress"] or g["verification_pending"] or g["verification_read_active"]:
                self.fence_violations.append((self.now_ms, "B10 MATCH while the RTC lock / verification is held"))
            if self._last_hot_dispatch is not None and \
                    int(g["cfg_block_b_response_dispatch_seq"]) < self._last_hot_dispatch + 2:
                self.fence_violations.append((self.now_ms, f"B10 MATCH from a Block B dispatched before the fence "
                                              f"(response {g['cfg_block_b_response_dispatch_seq']} < "
                                              f"{self._last_hot_dispatch} + 2)"))

    # -- clock ---------------------------------------------------------------------------------------------------------------
    def rebase_clock(self, new_now_ms: int) -> None:
        delta = int(new_now_ms) - self.now_ms
        super().rebase_clock(new_now_ms)
        if self.clock is not None:
            self.clock.t0_ms += delta
        if self.rtc is not None:
            self.rtc.shift(delta)

    def install_clock(self, utc_epoch_s: int) -> WallClock:
        self.clock = WallClock(self, utc_epoch_s)
        self.entities["ntp_time"] = self.clock
        self.epoch = int(utc_epoch_s)
        return self.clock

    def ntp_sync(self) -> None:
        """NTP valid + the firmware's own `time: on_time_sync` lambdas (ntp_synced = true and the sensor publish)."""
        self.ntp_valid = True
        for t in self.fw.get("time") or []:
            for a in ((t.get("on_time_sync") or {}).get("then") or []):
                if "lambda" in a:
                    self.run_lambda(a["lambda"])
        self.poked.add("ntp_synced")  # an environment event the test injects (not an RTC / poll path)

    # -- audits -------------------------------------------------------------------------------------------------------------
    def mark_nvs(self) -> None:
        """The audit baseline (end of the rig setup): the NVS / durable counters and every global's value."""
        self.nvs_mark = (len(self.nvs_direct.ops), len(self.nvs_commits), len(self.nvs_loads),
                         sum(1 for e in self.events if e and e[0] == "nvs"))
        self._state0 = {k: E._freeze(v) for k, v in self.g.items()}
        self.poked = set()

    def state_violations(self) -> list:
        """Every global whose VALUE changed since mark_nvs() must be RTC / poll / sensor-hook state or poked by the test (catches
        array / record writes too, which bypass set_global); with the fence rig the FB-B housekeeping / B10 state is allowed."""
        if self._state0 is None:
            return ["mark_nvs() was never called"]
        out = []
        for k, v in self.g.items():
            if E._freeze(v) == self._state0.get(k):
                continue
            if k in RTC_ALLOWED or k in POLL_ALLOWED or k in HOOK_ALLOWED or k.startswith(POLL_ALLOWED_PREFIXES) or k in self.poked:
                continue
            if self.fence_on and k.startswith("fallback_profile_"):
                continue
            out.append(k)
        return out

    def nvs_violations(self) -> list:
        if self.nvs_mark is None:
            return ["mark_nvs() was never called"]
        now = (len(self.nvs_direct.ops), len(self.nvs_commits), len(self.nvs_loads),
               sum(1 for e in self.events if e and e[0] == "nvs"))
        return [] if now == self.nvs_mark else [f"NVS / durable activity: {self.nvs_mark} -> {now}"]

    def audit_violations(self) -> list:
        out = []
        for (dom, name), n in sorted(self.assign_seen.items()):
            if dom.startswith("ambiguous"):
                out.append(f"assignment of {name} by an ambiguous lambda ({dom})")
            elif dom == "rtc" and name not in RTC_ALLOWED:
                out.append(f"RTC path assigned {name} ({n}x)")
            elif dom == "poll" and name not in POLL_ALLOWED and not name.startswith(POLL_ALLOWED_PREFIXES):
                out.append(f"poll path assigned {name} ({n}x)")
            elif dom == "hook" and name not in HOOK_ALLOWED:
                out.append(f"sensor hook assigned {name} ({n}x)")
            if dom in ("rtc", "poll", "hook") and name in OWNERSHIP_FLAGS:
                out.append(f"{dom} path assigned the ownership flag {name}")
        for (dom, name), n in sorted(self.pub_seen.items()):
            if dom == "rtc" and name not in RTC_ENTITIES:
                out.append(f"RTC path published {name} ({n}x)")
            if dom == "poll" and name in RTC_ENTITIES:
                out.append(f"poll path published the RTC entity {name}")
        return out

    def wire_violations(self, extra=()) -> list:
        allowed = POLL_FRAMES | RTC_FRAMES | frozenset(extra)
        out = []
        for w in self.wire_log:
            key = (w.kind, w.addr, w.count)
            if w.origin != "fw":
                continue
            if key not in allowed:
                out.append(f"unexpected frame {key} from {w.issuer}")
            elif w.issuer in RTC_ISSUERS and key not in RTC_FRAMES:
                out.append(f"RTC path sent {key}")
            elif w.issuer in POLL_ISSUERS and key not in POLL_FRAMES:
                out.append(f"poll path sent {key}")
            if w.kind == "write" and not (w.addr == 22 and w.count == 3 and w.issuer == "write_inverter_rtc"):
                out.append(f"write {key} from {w.issuer}")
        return out

    # -- observation ----------------------------------------------------------------------------------------------------------
    def flags(self) -> dict:
        g = self.g
        return {"cip": bool(g["correction_in_progress"]), "asp": bool(g["auto_sync_pending"]), "vp": bool(g["verification_pending"]),
                "vra": bool(g["verification_read_active"]), "cfp": bool(g["comm_failure_pending"]),
                "att": int(g["correction_attempt"]), "manual": bool(g["correction_is_manual"]),
                "fails": int(g["failed_corrections"]), "ok": int(g["corrections_since_boot"]),
                "res": str(self.ent("last_correction_result").state)}

    def released(self) -> bool:
        g = self.g
        return not g["correction_in_progress"] and not any(g[f] for f in PROGRESS_FLAGS)

    def rtc_wire(self, kind=None) -> list:
        """FC16 22-24 / FC03 22/3 frames that reached the wire, in wire order."""
        return [w for w in self.wire_log if w.origin == "fw" and w.addr == 22 and (kind is None or w.kind == kind)]

    def rtc_writes_on_wire(self, since_ms: int = -1) -> list:
        return [w for w in self.rtc_wire("write") if (w.t_start or w.t_queued) >= since_ms]

    def rtc_write_attempts(self, since_ms: int = -1) -> list:
        return [w for w in self.write_log if w.addr == 22 and w.t >= since_ms]

    def frames(self, addr, count=None, since_ms: int = -1, kind="read") -> list:
        return [w for w in self.wire_log if w.kind == kind and w.addr == addr and (count is None or w.count == count)
                and (w.t_start if w.t_start is not None else w.t_queued) >= since_ms]

    def read_attempts(self, addr, since_idx: int = 0) -> int:
        """Firmware reads of `addr` in modbus_log (on the wire or refused) since modbus_log index since_idx."""
        return sum(1 for e in self.modbus_log[since_idx:] if e[0] == "read" and e[1] == addr)

    def lock_periods(self) -> list:
        """[(start_ms, end_ms | None)] of correction_in_progress."""
        out, start = [], None
        for t, v in self.cip_edges:
            if v and start is None:
                start = t
            elif not v and start is not None:
                out.append((start, t))
                start = None
        if start is not None:
            out.append((start, None))
        return out

    def results(self, since_ms: int = -1) -> list:
        return [v for t, n, v in self.pub_times if n == "last_correction_result" and t >= since_ms]

    def first_result_time(self, prefix: str, since_ms: int = -1):
        for t, n, v in self.pub_times:
            if n == "last_correction_result" and t >= since_ms and v.startswith(prefix):
                return t
        return None


# ---------------------------------------------------------------------------------------------------------------------------
# rigs
# ---------------------------------------------------------------------------------------------------------------------------
DEFAULT_LOCAL = (2026, 10, 4, 10, 10, 0)  # a Sunday in BST, away from every quiet window of GOLD_TOU


def make_rig(text: str | None = None, *, fw: dict | None = None, local=DEFAULT_LOCAL, offset_s: float = -75.0, rate: float = 0.0,
             image_period_ms: int = 0, image_phase_ms: int = 0, reads: str = "deferred", writes: str = "deferred",
             latency_ms: int = 120, threshold: float = 20.0, auto_sync: bool = True, tou=GOLD_TOU,
             intervals=("rtc_read", "rtc_tick"), phase=None, oracle: bool = False, ntp: bool = True, seed: int = 0,
             tick_ms: int = 10) -> D1Sim:
    """A D1Sim on `text` (default: the live firmware) with the wall clock at `local` (Europe/London), NTP synced (the firmware's
    own on_time_sync), correction_threshold, Automatic Clock Sync, the TOU zone start cache words, the inverter RTC model
    (offset / rate / image staleness) and the selected intervals started now (their own startup delays apply)."""
    if fw is None:
        fw = load(live_text() if text is None else text)
    sim = D1Sim(fw, tick_ms=tick_ms)
    sim.seed_rng(seed)
    sim.install_clock(utc_of_local(*local))
    if ntp:
        sim.ntp_sync()
    else:
        sim.ntp_valid = False
    sim.ent("correction_threshold").set(float(threshold))
    sim.ent("automatic_clock_sync").set(bool(auto_sync))
    for k, r in enumerate(range(250, 256)):
        sim.poke(f"manual_cfg_reg{r}_raw", int(tou[k]) if tou is not None else 0)
    sim.rtc = InverterRtc(sim, offset_s, rate, image_period_ms=image_period_ms, image_phase_ms=image_phase_ms)
    if reads == "deferred":
        sim.set_modbus_mode("deferred", latency_ms)
    else:
        sim.frame_latency_ms = latency_ms
    sim.write_mode = writes
    sim.oracle_on = bool(oracle) and "rtc_policy_reason" in sim.g  # the oracle needs the FB-D1 globals
    start_named(sim, intervals, phase=phase)
    sim.mark_nvs()
    return sim


def start_named(sim: D1Sim, names, *, phase=None) -> list:
    idx = [sim.iv[n] for n in names if n in sim.iv]
    if idx:
        sim.start_intervals(idx, phase=phase)
    return idx


def make_fence_rig(text: str | None = None, *, local=(2026, 10, 4, 10, 5, 0), offset_s: float = 0.0, latency_ms: int = 120,
                   intervals=("rtc_read", "rtc_tick", "config", "catchup", "housekeeping")) -> D1Sim:
    """The FB-B2 boot (VALID golden stored profile + witness, the REAL on_boot, a trusted environment, the inverter bank == the
    stored profile) on a D1Sim, with the wall clock / inverter RTC / threshold of make_rig() and the B10 checks after every
    housekeeping tick (D1Sim.fence_on)."""
    import _fbb2_drive as D
    fw = load(live_text() if text is None else text)
    sim = D1Sim(fw, tick_ms=10)
    sim.install_clock(utc_of_local(*local))
    D.SEEDS["valid"](sim)
    sim.run_boot()
    sim.random_values = [0]
    sim.bank.update(D.bank_for(D.GWORDS))
    sim.ntp_sync()
    sim.g["supervision_state"] = 1
    sim.g["supervision_stable"] = True
    sim.ent("correction_threshold").set(20.0)
    sim.ent("automatic_clock_sync").set(True)
    sim.rtc = InverterRtc(sim, offset_s, 0.0)
    sim.set_modbus_mode("deferred", latency_ms)
    sim.write_mode = "deferred"
    sim.fence_on = True
    start_named(sim, intervals)
    sim.mark_nvs()
    return sim


# ---------------------------------------------------------------------------------------------------------------------------
# outcome helpers
# ---------------------------------------------------------------------------------------------------------------------------
def outcomes(write=None, verify=None, regular=None, poll=None, default="ok"):
    """An outcome_fn: `write` for FC16 frames; `verify` for an FC03 22/3 queued while verification_read_active (the 1 s tick sets it
    before its press); `regular` for any other FC03 22/3; `poll` a dict addr -> outcome. Each may be a str, a FrameSpec, a list
    (consumed in order, then the last repeats) or a callable(sim) -> outcome. Bind with bind_outcomes(sim, fn)."""
    state = {}

    def pick(key, spec, sim):
        if callable(spec):
            return spec(sim)
        if isinstance(spec, list):
            i = state.get(key, 0)
            state[key] = i + 1
            return spec[min(i, len(spec) - 1)]
        return spec

    def fn_for(sim):
        def fn(kind, addr, count):
            if kind == "write":
                return pick("w", write, sim) if write is not None else default
            if addr == 22 and count == 3:
                if sim.g.get("verification_read_active"):
                    return pick("v", verify, sim) if verify is not None else default
                return pick("r", regular, sim) if regular is not None else default
            if poll and addr in poll:
                return pick(("p", addr), poll[addr], sim)
            return default
        return fn
    return fn_for


def bind_outcomes(sim: D1Sim, maker) -> None:
    sim.outcome_fn = maker(sim)


def run_until(sim: D1Sim, pred, max_ms: int, step_ms: int = 100) -> bool:
    """Advance in step_ms slices until pred(sim) or max_ms elapsed. True if pred became true."""
    end = sim.now_ms + int(max_ms)
    while sim.now_ms < end:
        if pred(sim):
            return True
        sim.run_for(min(step_ms, end - sim.now_ms))
    return bool(pred(sim))


def queue_time(sim: D1Sim, after_ms: int = -1):
    """The first time correction_in_progress rose at or after after_ms."""
    for t, v in sim.cip_edges:
        if v and t >= after_ms:
            return t
    return None


def release_time(sim: D1Sim, after_ms: int = -1):
    for t, v in sim.cip_edges:
        if not v and t >= after_ms:
            return t
    return None


CAPABILITIES = {
    "G1_wall_clock": "WallClock: flowing UTC -> Europe/London ESPTime (all fields, is_valid, strftime), NTP switch, SNTP step, on_time_sync",
    "G3_inverter_rtc": "InverterRtc: offset + rate (piecewise), registers 22-24 packed as decoded, image staleness grid, freezes, "
                       "set only when an FC16 22-24 lands",
    "G4_deferred_writes": "FC16 frames on the hub (writes first, one in flight, latency) with all nine outcomes incl. a synchronous "
                          "not_sent and lost callbacks",
    "G7_seeding": "correction_threshold, the RTC / poll switches, the TOU zone start cache words",
    "G8_audit": "per-path attribution of every assignment / publication, allow-lists, a whole-state diff, wire / NVS audits, I1 after "
                "every RTC tick, I2, I3",
    "G9_oracle": "registry/rtc_policy.decide() on independently collected inputs before every regular RTC read response",
    "I6_success": "every corrections_since_boot increment checked against a post-ack verification read that passes the rule",
    "fence_rig": "FB-B2 boot + B10 refresh with never-MATCH-under-the-lock and two-dispatches-after-the-fence checks",
}
