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
from intelligence.scorecard import Scorecard

STORE_SCHEMA = "ecco-intel-runtime-store"
STORE_SCHEMA_VERSION = 1
PROPOSED_RETENTION_DAYS = 400                 # PROPOSED: a year of nights plus a margin for seasonal comparisons
MAX_SITE_FILE_BYTES = 256 * 1024              # a safety cap on the owner's site file (not an owner value)
MAX_PACKAGE_FILE_BYTES = 4 * 1024 * 1024
SITE_PARTS = ("ecco", "intelligence", "site.local.json")
STATE_PARTS = ("ecco", "intelligence", "state")
SCORECARD_FILE = "scorecard.sqlite3"
META_FILE = "store_meta.json"
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
    def record_cycle(self, report: Mapping | None, slot_utc: datetime, now: datetime, history=None, cfg=None) -> dict:
        """After a computed cycle: score the pending forecasts against `history`, record `report` for `slot_utc` (once per
        slot), then apply the retention. Returns what happened (diagnostics)."""
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

    def counts(self) -> dict:
        """Row counts (tests and diagnostics)."""
        if not (self._root / SCORECARD_FILE).is_file():
            return {}
        con = sqlite3.connect(f"file:{(self._root / SCORECARD_FILE).as_posix()}?mode=ro", uri=True)
        try:
            out = {}
            for t in ("model_runs", "forecasts", "recommendations", "ecco_intel_slots"):
                try:
                    out[t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                except sqlite3.Error:
                    out[t] = None
            return out
        finally:
            con.close()
