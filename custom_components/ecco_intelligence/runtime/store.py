"""The ONLY module of the integration that touches the file system (no homeassistant import; called in the executor).

Reads (never writes): the site file <config>/ecco/intelligence/site.local.json (placed by the owner) and the kit's own files
(VENDOR_MANIFEST.json and the sha256 of each packaged file, for the start-up self-test).

Writes: only under <config>/ecco/intelligence/state/, and only
  * store_meta.json      {schema, schema_version, retention_days} (atomic: a temporary file in state/, then os.replace);
  * scorecard.sqlite3    the vendored intelligence.scorecard database. Only an envelope's `scorecard_report` is recorded
                         (never a recommendation: the report is refused if it carries `recommended` anywhere, so the
                         scorecard's recommendations table stays empty), at most once per schedule slot, and rows older than
                         the PROPOSED retention are deleted. The slot claim and the run row are committed together (one
                         transaction), so a process that dies at any point records a slot at most once: a restart in the
                         middle of a run, or a crash between the two writes, never records it twice.
                         The advice just published is also logged (advice_log, additive; record_cycle's `advice`), in its own
                         transaction after the scorecard work, in the same file: ONE table, two rows per slot cycle at most
                         (about 52 a day), deleted after PROPOSED_RETENTION_DAYS (a durable write). The table is created by
                         the first advice write, not when the store is opened, so a failure there (another table of that
                         name, a failing CREATE, a full disk) is counted and never raised and cannot touch the scorecard
                         record, the start-up gate or outcome_metrics. This is a durable write of the integration (the
                         diagnostics download only reads it). Each advice write is READ BACK by its row ids after the commit
                         (a verified write; record_cycle reports it as advice_verified).
                         A failed advice write opens an INCIDENT, kept in memory by AdviceHealth (below). Once a later advice
                         write has been verified, the closed incidents are written by log_advice_incidents, in a table of their
                         own (advice_incident, at most ADVICE_INCIDENTS_KEPT rows) that is created only then: never at start-up,
                         never when the scorecard is opened, never by an advice write, and never while the database cannot take
                         the advice write. Its failure is isolated too. If the database never takes the advice write again, or
                         the integration restarts before it does, an open incident is lost except for the one warning that was
                         logged when it opened (the class name only).
The parent <config>/ecco/intelligence/ must already exist (the owner places the site file there); this module never creates
anything above state/. Every path is resolved and checked to lie inside state/ before it is written.

PROPOSED (engineering suggestion, NOT an owner value): PROPOSED_RETENTION_DAYS.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from intelligence.advisory_contract import OutcomeMetrics
from intelligence.scorecard import (ADVICE_INCIDENT_COLUMNS, ADVICE_INCIDENTS_KEPT, ADVICE_LOG_INCOMPATIBLE, ADVICE_LOG_MISSING,
                                    ADVICE_READ_BACK_MISSING, Scorecard, advice_incident_status, advice_log_status, incident_reason)

from .selftest import INFO, PASS, WARN

STORE_SCHEMA = "ecco-intel-runtime-store"
STORE_SCHEMA_VERSION = 1
PROPOSED_RETENTION_DAYS = 400                 # PROPOSED: a year of nights plus a margin for seasonal comparisons
MAX_SITE_FILE_BYTES = 256 * 1024              # a safety cap on the owner's site file (not an owner value)
MAX_PACKAGE_FILE_BYTES = 4 * 1024 * 1024
SITE_PARTS = ("ecco", "intelligence", "site.local.json")
STATE_PARTS = ("ecco", "intelligence", "state")
SCORECARD_FILE = "scorecard.sqlite3"
META_FILE = "store_meta.json"
ADVICE_ROWS_LIMIT = 5000                      # a safety cap on the advice rows one read returns (the newest are kept)
SLOTS_DDL = ("CREATE TABLE IF NOT EXISTS ecco_intel_slots (slot_utc TEXT PRIMARY KEY, run_id INTEGER NOT NULL, "
             "recorded_utc TEXT NOT NULL)")
UTC = timezone.utc


class StoreError(Exception):
    """A write that is not provably inside state/, or a refused record."""


def package_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def site_file_path(config_dir: str) -> Path:
    return Path(config_dir).joinpath(*SITE_PARTS)


def state_dir_path(config_dir: str) -> Path:
    return Path(config_dir).joinpath(*STATE_PARTS)


def read_site_file(config_dir: str) -> tuple[bytes | None, str | None]:
    """(bytes, None) or (None, problem). Read-only."""
    p = site_file_path(config_dir)
    try:
        if p.is_symlink() or not p.is_file():
            return None, "ecco/intelligence/site.local.json is missing (the owner places it)"
        if p.stat().st_size > MAX_SITE_FILE_BYTES:
            return None, "ecco/intelligence/site.local.json is larger than the safety cap"
        return p.read_bytes(), None
    except OSError as exc:
        return None, f"ecco/intelligence/site.local.json cannot be read: {type(exc).__name__}"


def read_package_manifest(pkg: Path | None = None) -> bytes | None:
    p = (pkg or package_dir()) / "VENDOR_MANIFEST.json"
    try:
        return p.read_bytes() if p.is_file() and not p.is_symlink() else None
    except OSError:
        return None


def hash_package_files(rel_paths, pkg: Path | None = None) -> dict[str, str | None]:
    """{package-relative path: sha256 or None (missing / unreadable / outside the package)}. Read-only."""
    base = (pkg or package_dir()).resolve()
    out: dict[str, str | None] = {}
    for rel in sorted(set(rel_paths)):
        out[rel] = None
        if not isinstance(rel, str) or rel.startswith("/") or "\\" in rel or ".." in rel.split("/"):
            continue
        p = base.joinpath(*rel.split("/"))
        try:
            if p.is_symlink() or not p.is_file() or base not in p.resolve().parents:
                continue
            if p.stat().st_size > MAX_PACKAGE_FILE_BYTES:
                continue
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def _contains_key(v: object, key: str) -> bool:
    if isinstance(v, Mapping):
        return key in v or any(_contains_key(x, key) for x in v.values())
    if isinstance(v, (list, tuple)):
        return any(_contains_key(x, key) for x in v)
    return False


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def _count(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


OUTCOME_VERIFIED, OUTCOME_NEUTRAL, OUTCOME_FAILED = "VERIFIED", "NEUTRAL", "FAILED"
OUTCOME_UNVERIFIED, OUTCOME_NOT_OFFERED, OUTCOME_STEP_FAILED = "UNVERIFIED", "NOT_OFFERED", "STEP_FAILED"


class AdviceHealth:
    """The advice log's health since the integration started, and its incidents. Pure (no file, no clock: every time is given); the
    coordinator owns one, feeds it the result of each slot cycle's store step and shows it in the diagnostics.

    What one slot cycle's store step is, for the advice log (note_store_result reads record_cycle's result):
      VERIFIED    rows were written and every one was read back by its id after the commit. The only thing that recovers health;
      NEUTRAL     nothing was written (no advice, or an identical re-publish while current): health is unchanged, it neither
                  recovers nor fails;
      FAILED      the write raised (advice_write_failures > 0);
      UNVERIFIED  rows were reported without a successful read-back (a row not found again, the read-back failing, or no
                  advice_verified at all): not a recovery, not a success;
      NOT_OFFERED the store was given no advice (its result has no advice keys): not an advice cycle;
      STEP_FAILED (note_step_failure) the whole store step timed out or raised, so nothing is known about the advice write.

    An INCIDENT opens at the first FAILED, UNVERIFIED or STEP_FAILED step and stays open, counting each further one (attempts and
    distinct slot cycles missed), until a VERIFIED step closes it. A closed incident is KEPT (the newest `kept` incidents, the open
    one included; older ones are dropped and counted) and offered once for persisting (pending_incidents / note_persisted). Its
    reason is an exception CLASS NAME only (incident_reason); the first reason is kept next to the latest. Health is never assumed:
    a new ledger has verified nothing, so after a restart it reads PASS only after its own first VERIFIED step. The cumulative
    failure counters belong to the coordinator and are never reset by a recovery."""

    def __init__(self, kept: int = ADVICE_INCIDENTS_KEPT) -> None:
        self._kept = max(1, int(kept))
        self._incidents: list[dict] = []          # oldest first; an open incident, when there is one, is the last
        self._dropped = 0
        self._attempts = 0
        self._verified = 0
        self._last_verified: str | None = None
        self._last_outcome: str | None = None
        self._last_persist: dict | None = None

    # --- reading -----------------------------------------------------------------------------------------------------
    def _open(self) -> dict | None:
        return self._incidents[-1] if self._incidents and self._incidents[-1]["state"] == "OPEN" else None

    @property
    def failing(self) -> bool:
        """True while an incident is open: the latest advice write attempt failed or is unverified."""
        return self._open() is not None

    def snapshot(self) -> dict:
        """The diagnostics block: copies only, newest incident first."""
        op = self._open()
        closed = [dict(i) for i in reversed(self._incidents) if i["state"] == "CLOSED"]
        return {"current_failure": op is not None, "last_outcome": self._last_outcome, "attempts": self._attempts,
                "verified_writes": self._verified, "last_verified_utc": self._last_verified, "kept_max": self._kept,
                "dropped": self._dropped, "open": None if op is None else dict(op), "closed": closed,
                "last_persist": None if self._last_persist is None else dict(self._last_persist)}

    def store_check(self, bad_writes_since_start: int) -> tuple[str, str] | None:
        """(level, text) for the STORE_RECORD self-test check after an advice store step, or None to leave the check as it is (a
        neutral step while an incident is open, or after a step failure whose own text the coordinator has recorded).
        WARN while an incident is open and the latest attempt failed or is unverified; PASS after a verified write, or when
        the store was not given advice; INFO (never PASS) while nothing has been verified since the start and nothing was written."""
        op = self._open()
        if op is not None:
            if self._last_outcome in (OUTCOME_FAILED, OUTCOME_UNVERIFIED):
                return (WARN, f"advice log not verified ({op['reason']}): {op['missed_slots']} slot(s) missed, "
                              f"{int(bad_writes_since_start)} failed/unverified since start; PASS needs a verified write")
            return None
        if self._last_outcome == OUTCOME_NEUTRAL and self._verified == 0:
            return (INFO, "the scorecard step completed; no advice row was written yet, so the advice log is not verified since start")
        return (PASS, "the scorecard step completed" + ("; the advice log write is verified" if self._verified else ""))

    def pending_incidents(self) -> list[dict]:
        """Copies of the closed incidents that have not been persisted yet (an open incident is never offered)."""
        return [dict(i) for i in self._incidents if i["state"] == "CLOSED" and not i["persisted"]]

    # --- writing -----------------------------------------------------------------------------------------------------
    def note_persisted(self, keys, *, error: object = None, now: datetime | None = None) -> None:
        """The store has persisted the closed incidents whose first_failed_utc is in `keys` (unknown keys are ignored); `error`
        and `now`, when given, are kept as the last persist attempt (class name only)."""
        wanted = {k for k in keys if isinstance(k, str)}
        for inc in self._incidents:
            if inc["state"] == "CLOSED" and inc["first_failed_utc"] in wanted:
                inc["persisted"] = True
        if now is not None:
            self._last_persist = {"at": _iso(now), "persisted": len(wanted), "error": None if error is None else incident_reason(error)}

    def note_store_result(self, last_store: object, *, slot: datetime, issued: datetime, now: datetime) -> str:
        """Feed one slot cycle's record_cycle result (see the class docstring). `slot` is the schedule slot, `issued` the issue time
        of the advice published, `now` the cycle time. Returns the outcome."""
        ls = last_store if isinstance(last_store, Mapping) else {}
        if "advice_rows" not in ls:
            return self._seen(OUTCOME_NOT_OFFERED)
        self._attempts += 1
        rows, failures = _count(ls.get("advice_rows")), _count(ls.get("advice_write_failures"))
        unverified = _count(ls.get("advice_unverified"))
        err = ls.get("advice_error")
        if failures > 0:
            return self._fail(OUTCOME_FAILED, incident_reason(err), slot, issued, now)
        if unverified > 0 or (rows > 0 and ls.get("advice_verified") is not True):
            return self._fail(OUTCOME_UNVERIFIED, ADVICE_READ_BACK_MISSING if err is None else incident_reason(err), slot, issued, now)
        if rows > 0:
            return self._verify(rows, now)
        return self._seen(OUTCOME_NEUTRAL)

    def note_step_failure(self, reason: object, *, slot: datetime, issued: datetime, now: datetime) -> str:
        """The whole store step timed out or raised: `reason` is the exception class name (TimeoutError for a timeout)."""
        self._attempts += 1
        return self._fail(OUTCOME_STEP_FAILED, incident_reason(reason), slot, issued, now)

    def _seen(self, outcome: str) -> str:
        self._last_outcome = outcome
        return outcome

    def _fail(self, outcome: str, reason: str, slot: datetime, issued: datetime, now: datetime) -> str:
        now_s, slot_s, issued_s = _iso(now), _iso(slot), _iso(issued)
        inc = self._open()
        if inc is None:
            inc = {"first_failed_utc": now_s, "last_failed_utc": now_s, "failed_count": 0, "missed_slots": 0, "reason": reason,
                   "first_reason": reason, "first_issued_utc": issued_s, "last_issued_utc": issued_s, "last_slot_utc": None,
                   "state": "OPEN", "recovered_utc": None, "rows_since": None, "persisted": False}
            self._incidents.append(inc)
            while len(self._incidents) > self._kept:      # the oldest closed incident goes; the open one is the newest
                self._incidents.pop(0)
                self._dropped += 1
        inc["failed_count"] += 1
        if inc["last_slot_utc"] != slot_s:
            inc["last_slot_utc"] = slot_s
            inc["missed_slots"] += 1
        inc["last_failed_utc"], inc["last_issued_utc"], inc["reason"] = now_s, issued_s, reason
        return self._seen(outcome)

    def _verify(self, rows: int, now: datetime) -> str:
        self._verified += 1
        self._last_verified = _iso(now)
        inc = self._open()
        if inc is not None:
            inc["state"], inc["recovered_utc"], inc["rows_since"] = "CLOSED", _iso(now), rows
        return self._seen(OUTCOME_VERIFIED)


class RuntimeStateStore:
    """The writer. Not thread-affine: every call opens and closes its own database connection (executor jobs may run on
    different threads). After close() every write is refused."""

    def __init__(self, config_dir: str, tz: str = "Europe/London", retention_days: int = PROPOSED_RETENTION_DAYS) -> None:
        if not (isinstance(retention_days, int) and not isinstance(retention_days, bool) and 1 <= retention_days <= 3660):
            raise StoreError("the retention must be a whole number of days between 1 and 3660")
        self._config = Path(config_dir)
        self._root = state_dir_path(config_dir)
        self._tz = tz
        self.retention_days = retention_days
        self._closed = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    # --- containment -------------------------------------------------------------------------------------------------
    def _inside(self, name: str) -> Path:
        if self._closed:
            raise StoreError("the store is closed: nothing more is written")
        if not isinstance(name, str) or "/" in name or "\\" in name or name in ("", ".", ".."):
            raise StoreError("a state file name is a plain name")
        root = self._root.resolve()
        p = (root / name).resolve()
        if p.parent != root or not root.is_dir():
            raise StoreError("a state file must lie directly inside state/")
        return p

    # --- set-up ------------------------------------------------------------------------------------------------------
    def open(self) -> str:
        """Create state/ (only; its parent must exist), write store_meta.json atomically and initialise the scorecard.
        Returns a short description; raises StoreError / OSError / sqlite3.Error when the store is not writable."""
        if self._closed:
            raise StoreError("the store is closed")
        parent = self._root.parent
        if parent.is_symlink() or not parent.is_dir():
            raise StoreError("ecco/intelligence/ does not exist: the store creates nothing above state/")
        if self._root.is_symlink():
            raise StoreError("state/ is a symlink")
        self._root.mkdir(exist_ok=True)
        meta = {"schema": STORE_SCHEMA, "schema_version": STORE_SCHEMA_VERSION, "retention_days": self.retention_days,
                "retention_label": "PROPOSED"}
        self._atomic_write(META_FILE, (json.dumps(meta, sort_keys=True, indent=1) + "\n").encode("utf-8"))
        with closing(self._scorecard()) as sc:
            sc.db.execute(SLOTS_DDL)
            sc.db.execute("INSERT OR REPLACE INTO schema_meta VALUES ('ecco_intel_store_schema_version', ?)",
                          (str(STORE_SCHEMA_VERSION),))
            sc.db.execute("INSERT OR REPLACE INTO schema_meta VALUES ('ecco_intel_retention_days', ?)",
                          (str(self.retention_days),))
            sc.db.commit()
        return f"state/ writable (schema {STORE_SCHEMA_VERSION}, PROPOSED retention {self.retention_days} days)"

    def try_open(self) -> tuple[bool, str]:
        """open(), with any failure turned into (False, reason) for the self-test."""
        try:
            return True, self.open()
        except StoreError as exc:                     # this module's own fixed texts (no path, no value)
            return False, f"not writable: {exc}"
        except (OSError, sqlite3.Error, ValueError) as exc:   # the type only: an OS message carries the path
            return False, f"not writable: {type(exc).__name__}"

    def _atomic_write(self, name: str, data: bytes) -> None:
        target = self._inside(name)
        fd, tmp = tempfile.mkstemp(prefix=".ecco-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, str(target))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _scorecard(self) -> Scorecard:
        return Scorecard(str(self._inside(SCORECARD_FILE)), self._tz)

    # --- the scorecard -----------------------------------------------------------------------------------------------
    def record_cycle(self, report: Mapping | None, slot_utc: datetime, now: datetime, history=None, cfg=None,
                     advice: Mapping | None = None, dump_duration_min: float | None = None) -> dict:
        """After a computed cycle: score the pending forecasts against `history`, record `report` for `slot_utc` (once per
        slot), then apply the retention. Returns what happened (diagnostics).

        `advice` (default None: nothing is logged) is the payload set the coordinator has just published
        (advisory_contract.to_entity_payloads). When given, it is logged in the scorecard's advice_log AFTER the scorecard
        work, in its own transaction: a failure there is caught and only counted (out['advice_write_failures'] > 0, or
        out['advice_error']); it never raises, so it cannot affect the published outputs or the scorecard record. The advice
        keys are added to the result only when `advice` was given: advice_rows, advice_write_failures, advice_unverified,
        advice_verified (True: every row written was read back by its id after the commit; False: the write failed or the
        rows were not found again; None: nothing was written) and, after a failure, advice_error (a class name or a code)."""
        out = {"recorded": False, "scored": 0, "removed": 0, "duplicate_slot": False}
        if self._closed:
            out["refused"] = "closed"
            return out
        if report is not None:
            if not isinstance(report, Mapping):
                raise StoreError("a scorecard report is a mapping")
            if _contains_key(report, "recommended"):
                raise StoreError("a scorecard report never carries 'recommended': refused")
            if report.get("mode") != "SHADOW":
                raise StoreError("only a SHADOW scorecard report is recorded")
        slot = _iso(slot_utc)
        with closing(self._scorecard()) as sc:
            sc.db.execute(SLOTS_DDL)
            if history is not None and cfg is not None:
                out["scored"] = len(sc.resolve(history, cfg, now))
            if report is not None:
                seen = sc.db.execute("SELECT run_id FROM ecco_intel_slots WHERE slot_utc=?", (slot,)).fetchone()
                if seen is not None:
                    out["duplicate_slot"] = True
                else:
                    self._claim_and_record(sc, dict(report), slot, now)
                    out["recorded"] = True
            out["removed"] = self._retention(sc, now)
        if advice is not None:
            self._log_advice(out, advice, dump_duration_min)
        return out

    def _log_advice(self, out: dict, advice: Mapping, dump_duration_min: float | None) -> None:
        """Log the published advice (see record_cycle). Never raises: Scorecard.record_advice counts its own failures, and
        opening the store for it is guarded here."""
        out["advice_rows"], out["advice_write_failures"], out["advice_unverified"], out["advice_verified"] = 0, 0, 0, None
        try:
            with closing(self._scorecard()) as sc:
                out["advice_rows"] = sc.record_advice(dict(advice), dump_duration_min=dump_duration_min)
                out["advice_write_failures"] = sc.advice_write_failures
                out["advice_unverified"] = sc.advice_unverified_writes      # rows written but not read back (or the read-back failed)
                out["advice_verified"] = sc.advice_last_verified            # True read back, False failed or unverified, None no write
                if sc.advice_last_error:
                    out["advice_error"] = sc.advice_last_error      # the exception class name (or the code AdviceReadBackMissing)
        except Exception as exc:  # noqa: BLE001 - the advice log is diagnostics only; the type is the whole message
            out["advice_write_failures"] += 1
            out["advice_verified"] = False
            out["advice_error"] = type(exc).__name__

    def log_advice_incidents(self, incidents, now: datetime) -> dict:
        """Persist the CLOSED incidents of `incidents` (AdviceHealth.pending_incidents) in the scorecard's advice_incident table,
        created by the first such write. The coordinator calls this only right after a slot cycle's advice write was VERIFIED, so
        the database has just shown that it takes the advice write; it is never called while an incident is open and never at
        start-up. Never raises: a failure (the table has another shape, a failing CREATE, a full disk) is counted by the scorecard
        and returned as the exception class name. Returns {"persisted": [first_failed_utc, ...], "error": None or a class name},
        and {"refused": "closed"} added after close()."""
        out: dict = {"persisted": [], "error": None}
        if self._closed:
            out["refused"] = "closed"
            return out
        try:
            with closing(self._scorecard()) as sc:
                res = sc.persist_advice_incidents(list(incidents), now)
            out["persisted"], out["error"] = list(res["persisted"]), res["error"]
        except Exception as exc:  # noqa: BLE001 - diagnostics only; the type is the whole message
            out["error"] = type(exc).__name__
        return out

    @staticmethod
    def _claim_and_record(sc: Scorecard, report: dict, slot: str, now: datetime) -> None:
        """Claim the slot and record the run in ONE transaction. The slot row goes in first, uncommitted, on the same
        connection; Scorecard.record_run's own commit then covers it together with the run and forecast rows. A process
        that dies before that commit leaves neither (the restarted cycle records the slot once); one that dies after it
        leaves both (the restart sees the slot and records nothing). The slot's run_id is filled in afterwards (0 until
        then; it is diagnostics only). Any failure rolls back what is not yet committed."""
        try:
            sc.db.execute("INSERT INTO ecco_intel_slots VALUES (?,?,?)", (slot, 0, _iso(now)))
            run_id = sc.record_run(report)
            sc.db.execute("UPDATE ecco_intel_slots SET run_id=? WHERE slot_utc=?", (run_id, slot))
            sc.db.commit()
        except BaseException:
            sc.db.rollback()
            raise

    def _retention(self, sc: Scorecard, now: datetime) -> int:
        cutoff = _iso(now - timedelta(days=self.retention_days))
        db = sc.db
        removed = 0
        removed += db.execute("DELETE FROM forecasts WHERE issued_utc < ?", (cutoff,)).rowcount
        removed += db.execute("DELETE FROM recommendations WHERE run_id IN (SELECT run_id FROM model_runs WHERE issued_utc < ?)",
                              (cutoff,)).rowcount
        removed += db.execute("DELETE FROM model_runs WHERE issued_utc < ?", (cutoff,)).rowcount
        removed += db.execute("DELETE FROM ecco_intel_slots WHERE slot_utc < ?", (cutoff,)).rowcount
        db.commit()
        return removed

    def enforce_retention(self, now: datetime) -> int:
        with closing(self._scorecard()) as sc:
            sc.db.execute(SLOTS_DDL)
            return self._retention(sc, now)

    def outcome_metrics(self, now: datetime) -> OutcomeMetrics | None:
        """The 7-day measured accuracy of the load forecasts, or None when the scorecard does not exist yet: every scored
        load_kwh:* kind the engine records (next_1h, to_next_cheap, cheap_window, day, morning, overnight, to_useful_pv or
        to_useful_pv_from_now) whose horizon ended within the 7 days before `now`, pooled, each kind's MAE and coverage
        weighted by its n (not the day-load forecast alone). The coordinator reads it in a slot cycle before that slot's
        scoring step (record_cycle), so the published figure lags one slot. Read-only apart from opening the database."""
        if self._closed or not (self._root / SCORECARD_FILE).is_file():
            return None
        with closing(self._scorecard()) as sc:
            rows = [r for r in sc.metrics(since=now - timedelta(days=7)) if str(r.get("kind", "")).startswith("load_kwh:")]
        n = sum(int(r["n"]) for r in rows)
        if n <= 0:
            return OutcomeMetrics(None, None, 0)
        mae = sum(float(r["mae"]) * int(r["n"]) for r in rows) / n
        cov_rows = [r for r in rows if r.get("coverage") is not None]
        cn = sum(int(r["n"]) for r in cov_rows)
        cov = (sum(float(r["coverage"]) * int(r["n"]) for r in cov_rows) / cn) if cn else None
        return OutcomeMetrics(mae, cov, n)

    def advice_rows(self, start: datetime, end: datetime, limit: int = ADVICE_ROWS_LIMIT) -> list[dict]:
        """READ-ONLY (SQLite mode=ro; nothing is created, altered or written, not even when the store is closed): the logged
        advice issued in [start, end), oldest first, at most the newest `limit` rows, as the dicts of
        ghost.AdviceRecord.from_dict (the mapping of Scorecard.advice_records and tools/advice_export.py; a test pins that the
        three agree). [] when there is no scorecard file or no advice_log table (nothing logged yet); raises sqlite3.Error /
        OSError when the file cannot be read or the table has another shape (an advice_log of other columns), so the caller can
        tell 'nothing logged' from 'unreadable'."""
        path = self._root / SCORECARD_FILE
        if not path.is_file():
            return []
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            st = advice_log_status(con)
            if st == ADVICE_LOG_MISSING:
                return []
            if st == ADVICE_LOG_INCOMPATIBLE:
                raise sqlite3.DatabaseError("advice_log exists with another shape")
            got = con.execute("SELECT * FROM advice_log WHERE issued_utc >= ? AND issued_utc < ? "
                              "ORDER BY issued_utc DESC, advice_id DESC LIMIT ?", (_iso(start), _iso(end), int(limit))).fetchall()
        finally:
            con.close()
        return [{"kind": r["kind"], "status": r["status"], "issued_at": r["issued_utc"], "window_start": r["window_start_utc"],
                 "window_end": r["window_end_utc"], "target_soc_pct": r["target_soc_pct"], "export_kwh": r["export_kwh"],
                 "export_kw": r["export_kw_avg"], "effective_reserve_pct": r["effective_reserve_pct"],
                 "conservative_fallback": bool(r["conservative_fallback"]),
                 "dump_advisable": True if r["dump_advisable"] is None else bool(r["dump_advisable"]),
                 "advice_id": f"advice_log:{r['advice_id']}"} for r in reversed(got)]

    def advice_incidents(self) -> list[dict]:
        """READ-ONLY (SQLite mode=ro; nothing is created, altered or written, not even when the store is closed): the persisted
        advice-log incidents, newest first, as dicts of ADVICE_INCIDENT_COLUMNS (at most ADVICE_INCIDENTS_KEPT). [] when there is
        no scorecard file or no advice_incident table (no incident has been persisted); raises sqlite3.Error / OSError when the
        file cannot be read or the table has another shape, so the caller can tell 'none' from 'unreadable'."""
        path = self._root / SCORECARD_FILE
        if not path.is_file():
            return []
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            st = advice_incident_status(con)
            if st == ADVICE_LOG_MISSING:
                return []
            if st == ADVICE_LOG_INCOMPATIBLE:
                raise sqlite3.DatabaseError("advice_incident exists with another shape")
            got = con.execute(f"SELECT {','.join(ADVICE_INCIDENT_COLUMNS)} FROM advice_incident ORDER BY first_failed_utc DESC LIMIT ?",
                              (ADVICE_INCIDENTS_KEPT,)).fetchall()
        finally:
            con.close()
        return [{c: r[c] for c in ADVICE_INCIDENT_COLUMNS} for r in got]

    def counts(self) -> dict:
        """Row counts (tests and diagnostics)."""
        if not (self._root / SCORECARD_FILE).is_file():
            return {}
        con = sqlite3.connect(f"file:{(self._root / SCORECARD_FILE).as_posix()}?mode=ro", uri=True)
        try:
            out = {}
            for t in ("model_runs", "forecasts", "recommendations", "ecco_intel_slots", "advice_log"):
                try:
                    out[t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                except sqlite3.Error:
                    out[t] = None
            return out
        finally:
            con.close()
