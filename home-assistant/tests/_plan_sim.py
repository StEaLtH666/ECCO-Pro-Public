"""Shared test support for the plan helper suites (stage 3 of the two-master-card energy-control work): a zone-aware layer over the
FPS1 interpreter (_ha_script_sim.py), which it reuses unchanged.

What it adds, and why:
  - a local time zone with real clock changes (zoneinfo), so `now()`, `today_at()`, `as_timestamp()` of a local string and
    `timestamp_custom` follow the wall clock the way Home Assistant does (the interpreter's own zone is a fixed UTC+1);
  - `timedelta` in templates (Home Assistant has it);
  - the helper services with Home Assistant's own range checks: `input_number.set_value` outside min / max / step raises (a script that
    writes a value its helper refuses fails loudly here, not silently), `input_datetime.set_datetime` takes `timestamp`, `datetime`
    or `time`, and keeps the `timestamp` attribute the card reads;
  - the helper states a fresh Home Assistant would hold (date-and-time helpers start at 1970, numbers at their minimum);
  - `restart()`: a model of what a Home Assistant restart restores for each helper type (a date-and-time helper's attribute from its state
    string, read as the FIRST of two equal local times; a number exactly, or one of the abnormal restores a suite lists). The restore model is
    a recollection of Home Assistant core, not verified live; it exists so a suite can state it and test against it.
Everything outside the supported subset still raises (the interpreter is fail-loud). No I/O, no network, no hardware.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import _ha_script_sim as S

FMT = "%Y-%m-%d %H:%M:%S"


class PlanWorld:
    """A World in a zone, one HA (the merged packages) and the helper services with Home Assistant's range checks."""

    rejected_all: list[str] = []   # every write a helper refused, across every world of the run (a suite requires it empty)

    def __init__(self, local_start: str, packages: list, zone: str = "Europe/London"):
        self.zone = ZoneInfo(zone)
        t0 = datetime.strptime(local_start, FMT).replace(tzinfo=self.zone).timestamp()
        self.w = S.World(t0)
        z = self.zone
        w = self.w

        def now():
            return datetime.fromtimestamp(w.t, z)

        def as_ts(value, default=S._MISSING):
            try:
                if isinstance(value, datetime):
                    return value.timestamp()
                if isinstance(value, (int, float)):
                    return float(value)
                return datetime.strptime(str(value), FMT).replace(tzinfo=z).timestamp()
            except (TypeError, ValueError):
                if default is S._MISSING:
                    raise S.SimError(f"as_timestamp could not parse {value!r} and no default was given")
                return default

        def today_at(value="00:00"):
            hh, mm, *ss = (int(x) for x in str(value).split(":"))
            return datetime.combine(now().date(), dtime(hh, mm, ss[0] if ss else 0), tzinfo=z)

        w.env.globals.update(now=now, as_timestamp=as_ts, today_at=today_at, timedelta=timedelta)
        def ts_custom(v, fmt=FMT, local=True, default=S._MISSING):
            # Home Assistant's timestamp_custom(format_string, local=True, default): R9's arm validation gives every call a default so that a failed conversion refuses instead of raising
            # (the interpreter's own filter, _ha_script_sim.World._timestamp_custom, does the same). Without a default a bad value raises exactly as before.
            try:
                return datetime.fromtimestamp(float(v), z if local else timezone.utc).strftime(fmt)
            except (TypeError, ValueError, OverflowError, OSError):
                if default is S._MISSING:
                    raise
                return default

        w.env.filters["timestamp_custom"] = ts_custom
        w.as_timestamp = as_ts
        self.bounds: dict[str, tuple[float, float, float]] = {}
        for pk in packages:
            for name, cfg in (pk.get("input_number") or {}).items():
                self.bounds[f"input_number.{name}"] = (float(cfg.get("min", 0)), float(cfg.get("max", 100)), float(cfg.get("step", 1)))
        self.ha = S.HA(w, packages)
        self.rejected: list[str] = []
        self.datetime_records: list[str] = []      # the date-and-time helpers (date and time): what a restart restores from their state string
        for pk in packages:
            for name, cfg in (pk.get("input_datetime") or {}).items():
                if cfg.get("has_date"):
                    self._store_datetime(f"input_datetime.{name}", datetime.strptime("1970-01-02 00:00:00", FMT).replace(tzinfo=z))
                    if cfg.get("has_time"):
                        self.datetime_records.append(f"input_datetime.{name}")
        w.service_handlers.update({
            "input_number.set_value": self._number,
            "input_datetime.set_datetime": self._datetime,
        })

    # --- state helpers ---------------------------------------------------------------------------------------------
    def local_state(self, dt: datetime) -> str:
        return dt.astimezone(self.zone).strftime(FMT)

    def _store_datetime(self, entity: str, dt: datetime) -> None:
        self.w.set(entity, self.local_state(dt), {"timestamp": dt.timestamp(), "has_date": True, "has_time": True})

    def set_local(self, entity: str, local_text: str) -> None:
        """Put a date-and-time helper at a local wall-clock time (as an owner or an earlier run would have left it)."""
        self._store_datetime(entity, datetime.strptime(local_text, FMT).replace(tzinfo=self.zone))

    def set_time(self, entity: str, hhmmss: str) -> None:
        hh, mm, ss = (int(x) for x in hhmmss.split(":"))
        self.w.set(entity, f"{hh:02d}:{mm:02d}:{ss:02d}", {"hour": hh, "minute": mm, "second": ss, "timestamp": hh * 3600 + mm * 60 + ss})

    def num(self, entity: str, value) -> None:
        self.w.set(entity, f"{float(value)}")

    # --- services with Home Assistant's range checks ---------------------------------------------------------------
    def _number(self, entity: str, data: dict) -> None:
        v = data["value"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            self.rejected.append(f"{entity}: {v!r} is not a number")
            PlanWorld.rejected_all.append(self.rejected[-1])
            raise S.ServiceError(f"{entity} {v!r}")
        lo, hi, step = self.bounds.get(entity, (-math.inf, math.inf, 0))
        if not lo <= float(v) <= hi or (step and abs(((float(v) - lo) / step) - round((float(v) - lo) / step)) > 1e-9):
            self.rejected.append(f"{entity}: {v!r} outside {lo}..{hi} step {step}")
            PlanWorld.rejected_all.append(self.rejected[-1])
            raise S.ServiceError(f"{entity} {v!r}")
        self.w.set(entity, f"{float(v)}")

    def _datetime(self, entity: str, data: dict) -> None:
        if "timestamp" in data:
            self._store_datetime(entity, datetime.fromtimestamp(float(data["timestamp"]), self.zone))
        elif "datetime" in data:
            self._store_datetime(entity, datetime.strptime(str(data["datetime"]), FMT).replace(tzinfo=self.zone))
        elif "time" in data:
            self.set_time(entity, str(data["time"]))
        else:
            raise S.Unsupported(f"set_datetime data {sorted(data)}")

    # --- a Home Assistant restart: what each helper type is restored from --------------------------------------------
    def restart(self, datetimes: str = "first", numbers: dict | None = None) -> None:
        """Home Assistant restarts and the helpers are restored from what was stored. THE MODEL OF THE RESTORE IS THE OWNER'S RECOLLECTION OF
        HOME ASSISTANT CORE, NOT VERIFIED AGAINST A LIVE INSTANCE (known limitations 19 and 23); this method only lets a suite state it.

          datetimes  how a date-and-time helper's `timestamp` attribute is restored (the STATE STRING, local wall-clock time without an offset, is
                     kept as it was):
                       "first"  the attribute is the instant of the state string read as the FIRST of two equal local times (fold 0), so a time in
                                the repeated hour of the autumn clock change is restored 60 minutes EARLY; any other time is restored exactly;
                       "exact"  the attribute is kept as it was (the earlier suites' assumption);
                       "missing"  the attribute is not restored at all (the state string is kept);
                     a helper that reads unknown, unavailable or empty is left as it is.
          numbers    {entity: restored state text, or None for an entity that no longer exists}: a number helper is restored EXACTLY unless it is
                     listed (an abnormal restore: reset to 0, unavailable, unknown, junk, nan, inf, a value outside its range, or gone).
        """
        if datetimes not in ("first", "exact", "missing"):
            raise ValueError(datetimes)
        for entity in self.datetime_records:
            state, attrs = self.w.states.get(entity, ("unknown", {}))
            if datetimes == "exact":
                continue
            try:
                naive = datetime.strptime(state, FMT)
            except ValueError:
                continue
            new = dict(attrs)
            if datetimes == "first":
                new["timestamp"] = naive.replace(tzinfo=self.zone, fold=0).timestamp()
            else:
                new.pop("timestamp", None)
            self.w.set(entity, state, new)
        for entity, text in (numbers or {}).items():
            if text is None:
                self.w.states.pop(entity, None)
                self.w._changed()
            else:
                self.w.set(entity, text)

    # --- running ---------------------------------------------------------------------------------------------------
    def run_script(self, name: str, variables: dict | None = None, seconds: float = 30.0) -> None:
        """Start a script and let the virtual clock run for `seconds` (every action of these scripts takes no time)."""
        self.ha.start_script(name, dict(variables or {}))
        self.w.run_until(self.w.t + seconds)

    def state(self, entity: str) -> str:
        return self.w.state(entity)

    def services(self, since: int = 0) -> list[tuple[str, str, dict]]:
        """(service, entity ids, data) of every service call since the `since`th."""
        return [(s, e, d) for _t, s, e, d in self.w.service_log[since:]]

