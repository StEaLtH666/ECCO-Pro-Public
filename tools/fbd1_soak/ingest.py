"""Offline evidence import: Home Assistant history JSON, CSV exports and ESPHome firmware logs.

Supported inputs (auto-detected from the content; `fmt` forces one):
  ha-json   Home Assistant REST history  GET /api/history/period/<start>?filter_entity_id=...[&minimal_response][&no_attributes]
            -> a list (one per entity) of lists of state rows; with minimal_response only the first row of each list carries
            `entity_id` and later rows carry `state` + `last_changed`.
            Home Assistant websocket history (history/history_during_period), compressed: {entity_id: [{"s", "lu", "lc"?}]},
            optionally wrapped in {"result": ...}.
            A flat list of state objects ({entity_id, state, last_changed}), e.g. /api/states snapshots.
  csv       Long form: entity_id, state, last_changed (the Home Assistant History panel download).
            Wide form: a first column named timestamp / time / t / utc / datetime and one column per entity id.
  log       `esphome logs` output (see logparse.py for the accepted line shapes).

Nothing is coerced: a row whose timestamp or entity id cannot be read is rejected and reported (with its reference); a
value that is not valid for its entity kind is kept as-is and reported by the analysis that reads it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import catalogue, logparse
from .evidence import Evidence, InputInfo, LogEvent, Sample
from .timeutil import TimeParseError, UTC, is_ambiguous_local, is_naive_iso, local_to_utc, parse_ts

TIME_COLS = ("last_changed", "last_updated", "time", "timestamp", "when", "t", "utc", "datetime")


def _state_str(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) < 1e15 else repr(v)
    return str(v)


class _Sink:
    def __init__(self, ev: Evidence, info: InputInfo, overrides: dict | None):
        self.ev, self.info, self.overrides = ev, info, overrides or {}
        self.order_last: dict = {}

    def row(self, entity_id, state, ts, ref: str, *, naive_utc: bool = True) -> None:
        self.info.rows += 1
        if not isinstance(entity_id, str) or not entity_id:
            self.reject("missing-entity-id", "row has no entity id", ref)
            return
        st = _state_str(state)
        if st is None:
            self.reject("missing-state", f"{entity_id}: row has no state", ref)
            return
        try:
            t = parse_ts(ts, naive_is_local=not naive_utc)
        except TimeParseError as exc:
            self.reject("bad-timestamp", f"{entity_id}: {exc}", ref)
            return
        if naive_utc and is_naive_iso(ts):
            self.ev.diag("warning", "naive-timestamp", f"{entity_id}: {ts!r} has no UTC offset; read as UTC", ref)
        key = catalogue.match(entity_id, self.overrides)
        if key is None:
            self.ev.unknown_entities[entity_id] = self.ev.unknown_entities.get(entity_id, 0) + 1
            self._span(t)
            return
        prev = self.order_last.get(entity_id)
        if prev is not None and t < prev:
            self.ev.diag("warning", "out-of-order", f"{entity_id}: row at {t.isoformat()} precedes the previous row "
                         f"({prev.isoformat()}) in the file; rows are re-sorted", ref)
        self.order_last[entity_id] = t if prev is None else max(prev, t)
        self.ev.add(key, entity_id, Sample(t, st, ref))
        self.info.accepted += 1
        self._span(t)

    def _span(self, t: datetime) -> None:
        self.info.first = t if self.info.first is None or t < self.info.first else self.info.first
        self.info.last = t if self.info.last is None or t > self.info.last else self.info.last

    def reject(self, code: str, detail: str, ref: str) -> None:
        self.info.rejected += 1
        self.ev.diag("error", code, detail, ref)


# ---------------------------------------------------------------------------------------------------------------------------
# Home Assistant JSON
# ---------------------------------------------------------------------------------------------------------------------------
def _row_time(r: dict):
    for k in ("last_changed", "lc", "last_updated", "lu", "last_reported", "lr"):
        if r.get(k) is not None:
            return r[k]
    return None


def ingest_ha_json(data, sink: _Sink, name: str) -> None:
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], (dict, list)):
        data = data["result"]
    if isinstance(data, dict):  # websocket compressed: {entity_id: [rows]}
        for eid, rows in data.items():
            if not isinstance(rows, list):
                sink.reject("malformed", f"{eid}: history is not a list", f"{name}#{eid}")
                continue
            for i, r in enumerate(rows):
                ref = f"{name}#{eid}[{i}]"
                if not isinstance(r, dict):
                    sink.reject("malformed", f"{eid}: row is not an object", ref)
                    continue
                sink.row(eid, r.get("s", r.get("state")), _row_time(r), ref)
        return
    if not isinstance(data, list):
        sink.reject("malformed", "top level is neither a list nor an object", name)
        return
    for li, block in enumerate(data):
        if isinstance(block, dict):  # flat list of state objects
            eid = block.get("entity_id")
            sink.row(eid, block.get("state", block.get("s")), _row_time(block), f"{name}#[{li}]")
            continue
        if not isinstance(block, list):
            sink.reject("malformed", f"element {li} is neither a list nor an object", f"{name}#[{li}]")
            continue
        eid = None
        for i, r in enumerate(block):
            ref = f"{name}#{eid or li}[{i}]"
            if not isinstance(r, dict):
                sink.reject("malformed", "row is not an object", ref)
                continue
            eid = r.get("entity_id") or eid
            sink.row(eid, r.get("state", r.get("s")), _row_time(r), f"{name}#{eid}[{i}]")


# ---------------------------------------------------------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------------------------------------------------------
def ingest_csv(text: str, sink: _Sink, name: str) -> None:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        sink.reject("malformed", "empty CSV", name)
        return
    cols = [h.strip().lstrip("﻿").strip().lower() for h in header]
    if "entity_id" in cols and "state" in cols:
        ie, istate = cols.index("entity_id"), cols.index("state")
        it = next((cols.index(c) for c in TIME_COLS if c in cols), None)
        if it is None:
            sink.reject("malformed", "long-form CSV has no time column", name)
            return
        for n, rec in enumerate(reader, start=2):
            ref = f"{name}:{n}"
            if not rec or all(not c.strip() for c in rec):
                continue
            if len(rec) <= max(ie, istate, it):
                sink.info.rows += 1
                sink.reject("malformed", f"short CSV row ({len(rec)} fields)", ref)
                continue
            sink.row(rec[ie].strip(), rec[istate], rec[it].strip(), ref)
        return
    if cols and cols[0] in ("timestamp", "time", "t", "utc", "datetime", "last_changed"):
        ids = [h.strip() for h in header]
        for n, rec in enumerate(reader, start=2):
            if not rec or all(not c.strip() for c in rec):
                continue
            ts = rec[0].strip()
            for j in range(1, min(len(rec), len(ids))):
                cell = rec[j]
                if cell is None or cell.strip() == "":
                    continue
                sink.row(ids[j], cell.strip(), ts, f"{name}:{n}:{ids[j]}")
        return
    sink.reject("malformed", f"unrecognised CSV header {header[:4]}", name)


# ---------------------------------------------------------------------------------------------------------------------------
# ESPHome logs
# ---------------------------------------------------------------------------------------------------------------------------
def _anchor_from_rtc_line(hms: str, fields: dict) -> date | None:
    """The NTP local date of a clock-only `Inverter RTC` line: inverter date-time minus the difference, whose time of day
    must equal the line's own clock within 5 minutes (else the PC clock is not the dongle's wall time)."""
    try:
        inv = datetime.strptime(fields["inv"], "%Y-%m-%d %H:%M:%S")
        ntp = inv - timedelta(seconds=int(fields["diff"]))
    except (KeyError, ValueError):
        return None
    h, m, s, _us = logparse.hms_parts(hms)
    cand = datetime(ntp.year, ntp.month, ntp.day, h, m, s)
    for d in (cand, cand - timedelta(days=1), cand + timedelta(days=1)):
        if abs((d - ntp).total_seconds()) <= 300:
            return d.date()
    return None


def ingest_log(text: str, ev: Evidence, info: InputInfo, name: str, anchor: date | None) -> None:
    parsed = []
    header_anchor = None
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        hm = logparse.HEADER_START.match(line.strip())
        if hm and header_anchor is None:
            header_anchor = date.fromisoformat(hm.group("date"))
            continue
        sp = logparse.split_line(line)
        info.rows += 1
        if sp is None:
            continue  # esphome CLI chatter, wrapped continuation lines
        iso, hms, lvl, tag, msg = sp
        kind, fields = logparse.classify(msg)
        parsed.append((n, iso, hms, lvl, tag, msg, kind, fields))
    if anchor is None and header_anchor is not None:
        anchor = header_anchor
        ev.diag("info", "log-anchor", f"{name}: clock-only lines anchored to {anchor.isoformat()} from the capture header", name)
    if anchor is None:
        for (_n, iso, hms, _l, _t, _m, kind, fields) in parsed:
            if iso is None and kind == "rtc_read" and hms:
                anchor = _anchor_from_rtc_line(hms, fields)
                if anchor:
                    ev.diag("info", "log-anchor", f"{name}: clock-only lines anchored to {anchor.isoformat()} from the first "
                            "Inverter RTC line", name)
                    break
    day = anchor
    prev_local = None
    fold = 0
    for (n, iso, hms, lvl, tag, msg, kind, fields) in parsed:
        ref = f"{name}:{n}"
        try:
            if iso is not None:
                t = parse_ts(iso, naive_is_local=True)
            else:
                if day is None:
                    info.rejected += 1
                    ev.diag("error", "log-unanchored", "clock-only log line and no anchor date (pass LOG@YYYY-MM-DD)", ref)
                    continue
                h, m, s, us = logparse.hms_parts(hms)
                local = datetime(day.year, day.month, day.day, h, m, s, us)
                if prev_local is not None and local < prev_local - timedelta(hours=6):
                    day = day + timedelta(days=1)
                    local = local + timedelta(days=1)
                elif prev_local is not None and local < prev_local - timedelta(seconds=5):
                    back = prev_local - local
                    if not fold and timedelta(minutes=50) <= back <= timedelta(minutes=70) and is_ambiguous_local(local):
                        fold = 1  # the autumn fall-back: the wall clock repeats 01:00-02:00, now in GMT
                    else:
                        ev.diag("warning", "log-clock-backwards", f"log clock went back {prev_local.time()} -> {local.time()}", ref)
                if fold and not is_ambiguous_local(local):
                    fold = 0
                prev_local = local
                t = local_to_utc(local, fold=fold)
        except (TimeParseError, ValueError) as exc:
            info.rejected += 1
            ev.diag("error", "bad-timestamp", f"log line: {exc}", ref)
            continue
        ev.logs.append(LogEvent(t, lvl, tag, msg, ref, kind, fields))
        info.accepted += 1
        info.first = t if info.first is None or t < info.first else info.first
        info.last = t if info.last is None or t > info.last else info.last


# ---------------------------------------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------------------------------------
def detect_format(path: Path, text: str) -> str:
    """By extension first (.json / .csv / .log / .txt); otherwise by content. An esphome log line also starts with `[`, so
    content that does not parse as JSON is never taken for JSON."""
    suf = path.suffix.lower()
    if suf == ".json":
        return "ha-json"
    if suf == ".csv":
        return "csv"
    if suf in (".log", ".txt"):
        return "log"
    if text.lstrip()[:1] in ("[", "{"):
        try:
            json.loads(text)
            return "ha-json"
        except json.JSONDecodeError:
            pass
    first = text.splitlines()[0] if text else ""
    return "csv" if "," in first and ("entity_id" in first or first.lower().startswith(("timestamp", "time"))) else "log"


def load(path: str | Path, ev: Evidence, *, overrides: dict | None = None, fmt: str | None = None,
         log_date: date | None = None, label: str | None = None) -> InputInfo:
    p = Path(path)
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    name = label or p.name
    fmt = fmt or detect_format(p, text)
    info = InputInfo(str(path), fmt, hashlib.sha256(raw).hexdigest())
    if fmt == "ha-json":
        sink = _Sink(ev, info, overrides)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            sink.reject("malformed", f"not valid JSON: {exc}", name)
        else:
            ingest_ha_json(data, sink, name)
    elif fmt == "csv":
        ingest_csv(text, _Sink(ev, info, overrides), name)
    elif fmt == "log":
        ingest_log(text, ev, info, name, log_date)
    else:
        raise ValueError(f"unknown input format {fmt!r}")
    ev.inputs.append(info)
    return info


def load_object(data, ev: Evidence, *, name: str = "memory.json", overrides: dict | None = None) -> InputInfo:
    """Ingest an already-parsed Home Assistant JSON object (used by the tests and by callers that fetched history themselves)."""
    blob = json.dumps(data, sort_keys=True).encode()
    info = InputInfo(name, "ha-json", hashlib.sha256(blob).hexdigest())
    ingest_ha_json(data, _Sink(ev, info, overrides), name)
    ev.inputs.append(info)
    return info


def load_log_text(text: str, ev: Evidence, *, name: str = "memory.log", log_date: date | None = None) -> InputInfo:
    info = InputInfo(name, "log", hashlib.sha256(text.encode()).hexdigest())
    ingest_log(text, ev, info, name, log_date)
    ev.inputs.append(info)
    return info


__all__ = ["load", "load_object", "load_log_text", "detect_format", "UTC"]
