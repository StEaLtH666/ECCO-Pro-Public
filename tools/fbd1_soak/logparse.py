"""ESPHome firmware log lines -> typed events.

Every pattern below is a literal firmware format string (firmware/ecco_clock_dongle_stage3_4_free_power.yaml) with its
printf fields turned into named groups; tools/tests/test_fbd1_soak_analyser.py proves each one still exists in the firmware
and matches its own rendering, so a renamed log line fails the suite instead of silently disappearing from a report.

Accepted line shapes (ANSI colour codes are stripped first):
  [00:03:12][W][ecco:21267]: RTC correction queued - clock difference: -47 seconds       (`esphome logs` output)
  [00:03:12.345][W][ecco:D951]: ...                                                        (ESPHome 2026: ms clock, hex line)
  2026-10-05T00:03:12+01:00 [W][ecco:21267]: ...                                          (a capture that prefixes a full timestamp)
  2026-10-05 00:03:12 [00:03:12][W][ecco]: ...                                             (both)
A clock-only line needs a date: the caller passes an anchor date, or the analyser takes it from a capture header line
`# esphome logs ... start=<ISO date-time> ...`, or from the first `Inverter RTC: <date> <time> | Difference from NTP: <d> s`
line (the dongle's NTP wall time is that date-time minus d).
"""

from __future__ import annotations

import re

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LINE = re.compile(
    r"^(?:(?P<iso>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s*)?"
    r"(?:\[(?P<hms>\d{2}:\d{2}:\d{2})(?P<frac>[.,]\d+)?\])?\s*"
    r"\[(?P<lvl>[EWIDCVS]{1,2})\]\[(?P<tag>[A-Za-z0-9_.]+)(?::[0-9A-Fa-f]+)?\]:\s?(?P<msg>.*)$")

# (kind, regex over the message). The first match wins. Groups are named after the firmware's printf arguments.
PATTERNS = (
    ("rtc_read", re.compile(r"^Inverter RTC: (?P<inv>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Difference from NTP: (?P<diff>-?\d+) s$")),
    ("rtc_read_waiting_ntp", re.compile(r"^Inverter RTC: (?P<inv>\S+ \S+) \| (?:Waiting for confirmed NTP|NTP currently invalid)$")),
    ("rtc_read_invalid", re.compile(r"^Invalid inverter RTC data received$")),
    ("rtc_read_error", re.compile(r"^(?:Modbus exception while reading RTC: 0x(?P<code>[0-9A-Fa-f]{2})|No response while reading inverter RTC"
                                  r"|Non-standard reply while reading inverter RTC \((?P<bytes>\d+) bytes\)"
                                  r"|RTC read request not queued \(not a verification read\)"
                                  r"|RTC verification read was not queued - processing retry)$")),
    ("rtc_stall", re.compile(r"^RTC STALL detected - inverter advanced (?P<inv_adv>-?\d+) s while NTP advanced (?P<ntp_adv>-?\d+) s$")),
    ("rtc_queued", re.compile(r"^RTC correction queued - clock difference: (?P<diff>-?\d+) seconds$")),
    ("rtc_policy", re.compile(r"^RTC policy: (?P<reason>[a-z-]+) \(threshold (?P<thr>-?\d+) s, full error (?P<err>-?\d+) s\)$")),
    ("rtc_held", re.compile(r"^RTC correction held \((?P<reason>[a-z-]+)\) - full error (?P<err>-?\d+) s, threshold (?P<thr>-?\d+) s$")),
    ("rtc_write_start", re.compile(r"^Starting RTC write attempt (?P<attempt>\d+)$")),
    ("rtc_write_value", re.compile(r"^Writing inverter RTC from NTP: (?P<ntp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})$")),
    ("rtc_write_ack", re.compile(r"^RTC write acknowledged - verification scheduled in 10 seconds$")),
    ("rtc_write_error", re.compile(r"^(?:RTC write Modbus exception: 0x(?P<code>[0-9A-Fa-f]{2})|No response to RTC write"
                                   r"|RTC write was not queued - processing retry"
                                   r"|Non-standard reply to RTC write \((?P<bytes>\d+) bytes\) - processing retry)$")),
    ("rtc_write_deferred", re.compile(r"^RTC write deferred - inverter write path owned by another transaction; will retry on the next "
                                      r"scheduled correction check$")),
    ("rtc_verify_start", re.compile(r"^Performing post-write RTC verification$")),
    ("rtc_verified", re.compile(r"^RTC correction VERIFIED - error now (?P<err>-?\d+) seconds$")),
    ("rtc_verify_failed", re.compile(r"^RTC verification failed at (?P<err>-?\d+) seconds - retry queued$")),
    ("rtc_failed_retries", re.compile(r"^RTC correction failed after retries - entering 5 minute cooldown$")),
    ("rtc_failed_comm", re.compile(r"^RTC correction failed after communication errors$")),
    ("rtc_aborted", re.compile(r"^RTC correction held its lock (?P<held>\d+) s - deadline breaker released RTC state only \(5 min cooldown\)$")),
    ("rtc_flags_cleared", re.compile(r"^RTC progress flags set without the correction lock - cleared$")),
    ("rtc_cooldown_expired", re.compile(r"^RTC correction cooldown expired$")),
    ("telemetry_error", re.compile(r"^(?:No response to telemetry block (?P<blk>\d+-\d+)|Non-standard reply to telemetry block (?P<blk2>\d+-\d+) \(\d+ bytes\)"
                                   r"|Telemetry block (?P<blk3>\d+-\d+) was not sent|Telemetry block (?P<blk4>\d+-\d+) Modbus exception: 0x[0-9A-Fa-f]{2})$")),
    ("config_block_error", re.compile(r"^(?:No response to configuration block (?P<blk>\d+-\d+)"
                                      r"|Non-standard reply to configuration block (?P<blk2>\d+-\d+) \(\d+ bytes\)"
                                      r"|Configuration block (?P<blk3>\d+-\d+) was not sent"
                                      r"|Configuration block (?P<blk4>\d+-\d+) Modbus exception: 0x[0-9A-Fa-f]{2})$")),
    ("block_c_error", re.compile(r"^(?:No response to configuration register 330|Non-standard reply to configuration register 330 \(\d+ bytes\)"
                                 r"|Configuration register 330 was not sent|Configuration register 330 Modbus exception: 0x[0-9A-Fa-f]{2})$")),
    ("block_c_skipped", re.compile(r"^Configuration register 330 read skipped - inverter write path owned by another transaction$")),
    ("config_yield", re.compile(r"^Configuration poll yielded before Block B - inverter write path owned by another transaction; nothing stamped, "
                                r"catch-up owed$")),
    ("config_deferred", re.compile(r"^Configuration poll (?:deferred - inverter write path owned by another transaction; will retry on the next "
                                   r"scheduled poll|dispatch refused - inverter write path owned by another transaction \(checked at final "
                                   r"dispatch point\))$")),
    ("telemetry_skipped", re.compile(r"^Telemetry block 150-196 skipped - inverter write path owned by another transaction$")),
    ("boot_shadow", re.compile(r"^boot (?P<nonce>[0-9A-F]{8}) shadow ready$")),
    ("boot_load", re.compile(r"^boot load: profile ld=")),
    ("recovery_blocked", re.compile(r"^RECOVERY BLOCKED\b")),
    ("heartbeat_rejected", re.compile(r"^Heartbeat rejected: ")),
)


HEADER_START = re.compile(r"^#.*\bstart=(?P<date>\d{4}-\d{2}-\d{2})[T ]")


def classify(msg: str) -> tuple[str, dict]:
    for kind, rx in PATTERNS:
        m = rx.match(msg)
        if m:
            return kind, {k: v for k, v in m.groupdict().items() if v is not None}
    return "other", {}


def split_line(line: str):
    """(iso, hms, level, tag, msg) of one log line, or None when it is not an ESPHome log line. `hms` keeps the clock's
    fraction (`HH:MM:SS.fff`): a correction's write is often acknowledged within the same second as its queue read."""
    m = LINE.match(ANSI.sub("", line).rstrip("\r\n"))
    if not m or (m.group("iso") is None and m.group("hms") is None):
        return None
    hms = m.group("hms")
    if hms is not None and m.group("frac"):
        hms += "." + m.group("frac")[1:]
    return m.group("iso"), hms, m.group("lvl"), m.group("tag"), m.group("msg").rstrip()


def hms_parts(hms: str) -> tuple:
    """`HH:MM:SS[.fff]` -> (h, m, s, microseconds)."""
    main, _, frac = hms.partition(".")
    h, m, s = (int(x) for x in main.split(":"))
    return h, m, s, int(frac[:6].ljust(6, "0")) if frac else 0
