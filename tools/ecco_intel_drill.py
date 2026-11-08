#!/usr/bin/env python3
"""ECCO Intelligence SHADOW kit: install / upgrade / rollback / uninstall DRILLS on a MOCK configuration directory, the
runbook printer, and the offline site-file check. Offline only: this tool never runs ssh, scp or any other process, opens
no network connection and never touches a real Home Assistant.

    python tools/ecco_intel_drill.py drill      --config-root <mock> --kit <kit> [--upgrade-kit <kit2>] [--stamp S]
    python tools/ecco_intel_drill.py install    --config-root <mock> --kit <kit>       [--stamp S]
    python tools/ecco_intel_drill.py upgrade    --config-root <mock> --kit <kit>       [--stamp S]
    python tools/ecco_intel_drill.py rollback   --config-root <mock> [--backup STAMP]  [--stamp S]
    python tools/ecco_intel_drill.py uninstall  --config-root <mock>                   [--stamp S]
    python tools/ecco_intel_drill.py runbook    --kit <kit>
    python tools/ecco_intel_drill.py site-check --site <site.local.json> [--json]

site-check reads one site file exactly as the runtime's start-up gates do (runtime/gates.load_site: the decisions block
through DecisionSet.from_mapping(source='site_local'), the strict shadow_runtime entity map, the V1 history sources) and
reports, for the owner before the file is placed: the file's sha256 and the runtime's config_hash (its first 16 hex
digits), every load check, each decision's status, and each published item's readiness. Readiness is static: an item is
BLOCKED when the file alone already withholds it (a decision it needs is OPEN or INVALID, an input it needs is not
mapped, a gate reading it needs has no I-D6 limit and so is never fresh, a site fact or the history source is missing,
a load check FAILs); otherwise the live inputs decide (the check can prove BLOCKED, never OK). It also applies the v0.1
site-file rule that the learned and the register-204 capacity stay unmapped (amendment A25). It prints no entity id,
record reference, source name or decision value: codes, contract keys, counts and hashes only. Exit 0 when the file loads
with no FAIL, no INVALID decision and no v0.1 rule broken (every item may still be BLOCKED); exit 1 otherwise.

A config root is accepted only when it contains the marker file `.ecco_mock_config_root` and does not look like a real Home
Assistant configuration (no `.storage/`); an argument naming the host alias `ecco-ha` or a `host:path` remote spec is
refused. The steps mirror the deploy tooling's semantics (tools/deploy-ha.ps1, read-only reference): verify the kit's
SHA256SUMS, stage a copy under ecco/staging/<stamp>/ (never inside custom_components/), verify the staged copy, back up the
installed integration to ecco-backups/<stamp>/ and verify the backup, swap by atomic renames, verify in place, and on a
failed verification roll the swap back. Nothing is ever deleted: a replaced or uninstalled tree is moved under
ecco/staging/<stamp>/. ecco/intelligence/site.local.json and ecco/intelligence/state/ are never touched (their hashes are
checked before and after every step).

Status of the real install: PENDING DP-4. The runbook steps are NOT AVAILABLE until PR-5 (the deploy route for
custom_components/: tools/deploy-ha-kit.ps1 and tools/place-ha-site-file.ps1) has merged and the owner has given the
separate go for the install. Nothing here is installed or deployed.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

MARKER = ".ecco_mock_config_root"
REFUSED_HOSTS = ("ecco-ha",)
DOMAIN = "ecco_intelligence"
KIT_PREFIX = f"custom_components/{DOMAIN}/"
STAMP_RE = re.compile(r"[0-9]{8}-[0-9]{6}")
PROTECTED = ("ecco/intelligence/site.local.json", "ecco/intelligence/state")
IGNORED_IN_PLACE = ("__pycache__",)


class DrillError(Exception):
    """A refused root, a failed verification or an unsafe step: nothing further happens."""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp_now() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def refuse_hosts(values) -> None:
    for v in values:
        if v is None:
            continue
        s = str(v)
        if any(hst in s.lower() for hst in REFUSED_HOSTS):
            raise DrillError(f"refused: {s!r} names the live host alias; this tool works on a mock directory only")
        if re.match(r"^[^/\\]{2,}:", s) or s.startswith(("ssh://", "scp://", "\\\\")):
            raise DrillError(f"refused: {s!r} looks like a remote location; this tool works on a local mock directory only")


def mock_root(path: str) -> Path:
    root = Path(path).resolve()
    if not root.is_dir():
        raise DrillError(f"{root} is not a directory")
    if not (root / MARKER).is_file():
        raise DrillError(f"refused: {root} has no {MARKER} marker; drills run only on a marked mock configuration directory")
    if (root / ".storage").exists():
        raise DrillError(f"refused: {root} has a .storage directory and looks like a real Home Assistant configuration")
    return root


def read_sums(sums_file: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in sums_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, sep, rel = line.partition("  ")
        rel = rel.strip()
        if not sep or not re.fullmatch(r"[0-9a-f]{64}", digest) or rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
            raise DrillError(f"{sums_file.name}: malformed line {line[:40]!r}")
        out[rel] = digest
    return out


def tree(base: Path, ignore: tuple[str, ...] = ()) -> dict[str, str]:
    """{relative posix path: sha256} of every file under base (symlinks refused)."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        d = Path(dirpath)
        for n in list(dirnames):
            if (d / n).is_symlink():
                raise DrillError(f"{(d / n)} is a symlink")
            if n in ignore:
                dirnames.remove(n)
        for n in filenames:
            p = d / n
            if p.is_symlink():
                raise DrillError(f"{p} is a symlink")
            out[p.relative_to(base).as_posix()] = sha256(p)
    return dict(sorted(out.items()))


def protected_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    site = root / PROTECTED[0]
    if site.is_file():
        out[PROTECTED[0]] = sha256(site)
    state = root / PROTECTED[1]
    if state.is_dir():
        for rel, d in tree(state).items():
            out[f"{PROTECTED[1]}/{rel}"] = d
    return out


class Drill:
    def __init__(self, root: Path, log=print) -> None:
        self.root = root
        self.log = log
        self.steps: list[tuple[str, str, str]] = []
        self.installed = root / "custom_components" / DOMAIN

    # --- bookkeeping -------------------------------------------------------------------------------------------------
    def step(self, ok: bool, name: str, detail: str = "") -> None:
        self.steps.append(("PASS" if ok else "FAIL", name, detail))
        self.log(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))
        if not ok:
            raise DrillError(f"{name}: {detail}")

    def _dirs(self, stamp: str) -> tuple[Path, Path]:
        if not STAMP_RE.fullmatch(stamp):
            raise DrillError(f"a stamp is YYYYMMDD-HHMMSS, got {stamp!r}")
        staging = self.root / "ecco" / "staging" / stamp
        backup = self.root / "ecco-backups" / stamp
        if staging.exists() or backup.exists():
            raise DrillError(f"refused: the stamp {stamp} is already used (nothing is overwritten)")
        cc = (self.root / "custom_components").resolve()
        if cc in staging.resolve().parents or staging.resolve() == cc:
            raise DrillError("staging must never be inside custom_components/")
        return staging, backup

    # --- the kit -----------------------------------------------------------------------------------------------------
    def verify_kit(self, kit: Path) -> dict[str, str]:
        sums_file = kit / "SHA256SUMS"
        self.step(sums_file.is_file() and (kit / "custom_components" / DOMAIN).is_dir(), "the kit has SHA256SUMS and the package",
                  str(kit))
        sums = read_sums(sums_file)
        files = {k: v for k, v in tree(kit).items() if k != "SHA256SUMS"}
        bad = sorted(k for k in set(sums) | set(files) if sums.get(k) != files.get(k))
        self.step(not bad, f"the kit verifies against its SHA256SUMS ({len(sums)} files)", ", ".join(bad[:3]))
        pkg = {k[len(KIT_PREFIX):]: v for k, v in sums.items() if k.startswith(KIT_PREFIX)}
        self.step(bool(pkg) and "manifest.json" in pkg, "the kit carries the integration package", f"{len(pkg)} files")
        return pkg

    def _copy_tree(self, src: Path, dst: Path) -> None:
        for rel in tree(src, IGNORED_IN_PLACE):
            target = dst.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src.joinpath(*rel.split("/")), target)

    def _write_sums(self, path: Path, hashes: dict[str, str]) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{d}  {rel}\n" for rel, d in sorted(hashes.items())))

    # --- the swap ----------------------------------------------------------------------------------------------------
    def _backup_current(self, backup: Path) -> dict[str, str] | None:
        if not self.installed.is_dir():
            self.step(True, "no integration installed: nothing to back up")
            return None
        current = tree(self.installed, IGNORED_IN_PLACE)
        dst = backup / f"custom_components__{DOMAIN}"
        self._copy_tree(self.installed, dst)
        self._write_sums(backup / "BACKUP_SHA256SUMS", current)
        self.step(tree(dst) == current, f"backed up the installed integration to ecco-backups/{backup.name}/ and verified",
                  f"{len(current)} files")
        return current

    def _swap_in(self, new_dir: Path, staging: Path, want: dict[str, str], label: str) -> None:
        previous = staging / "previous" / DOMAIN
        moved = False
        if self.installed.exists():
            previous.parent.mkdir(parents=True, exist_ok=True)
            os.rename(self.installed, previous)
            moved = True
        self.installed.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(new_dir, self.installed)
        except OSError as exc:
            if moved:
                os.rename(previous, self.installed)
            self.step(False, f"{label}: the atomic rename into place", f"{type(exc).__name__}; the previous tree was put back")
        self.step(True, f"{label}: atomic rename into custom_components/{DOMAIN}/"
                  + (f" (the previous tree moved to ecco/staging/{staging.name}/previous/)" if moved else ""))
        got = tree(self.installed, IGNORED_IN_PLACE)
        if got != want:
            failed = staging / "failed"
            failed.mkdir(parents=True)
            os.rename(self.installed, failed / DOMAIN)
            if moved:
                os.rename(previous, self.installed)
            self.step(False, f"{label}: verify in place", "the installed tree differs; the swap was rolled back")
        self.step(True, f"{label}: verified in place against the expected hashes", f"{len(got)} files")

    def _guard(self, before: dict[str, str], label: str) -> None:
        after = protected_hashes(self.root)
        self.step(after == before, f"{label}: ecco/intelligence/site.local.json and state/ untouched", f"{len(after)} files")

    # --- the operations ----------------------------------------------------------------------------------------------
    def install(self, kit: Path, stamp: str, *, upgrade: bool = False) -> None:
        label = "upgrade" if upgrade else "install"
        self.log(f"== {label} ({stamp})")
        before = protected_hashes(self.root)
        if upgrade:
            self.step(self.installed.is_dir(), "upgrade: an integration is installed")
        else:
            self.step(not self.installed.exists(), "install: no integration installed yet (use upgrade otherwise)")
        want = self.verify_kit(kit)
        staging, backup = self._dirs(stamp)
        new_dir = staging / "new" / DOMAIN
        self._copy_tree(kit / "custom_components" / DOMAIN, new_dir)
        self.step(tree(new_dir) == want, f"staged under ecco/staging/{stamp}/ (outside custom_components/) and verified")
        backup.mkdir(parents=True)
        self._backup_current(backup)
        self._swap_in(new_dir, staging, want, label)
        self._guard(before, label)

    def rollback(self, stamp: str, backup_stamp: str | None = None) -> None:
        self.log(f"== rollback ({stamp})")
        before = protected_hashes(self.root)
        backups = sorted(p.name for p in (self.root / "ecco-backups").iterdir()
                         if (p / f"custom_components__{DOMAIN}").is_dir()) if (self.root / "ecco-backups").is_dir() else []
        src_stamp = backup_stamp or (backups[-1] if backups else None)
        self.step(src_stamp is not None and src_stamp in backups, "a backup of the integration exists", str(src_stamp))
        bdir = self.root / "ecco-backups" / src_stamp
        want = read_sums(bdir / "BACKUP_SHA256SUMS")
        self.step(tree(bdir / f"custom_components__{DOMAIN}") == want, f"the backup ecco-backups/{src_stamp}/ verifies",
                  f"{len(want)} files")
        staging, backup = self._dirs(stamp)
        new_dir = staging / "restore" / DOMAIN
        self._copy_tree(bdir / f"custom_components__{DOMAIN}", new_dir)
        self.step(tree(new_dir) == want, f"the restore copy is staged under ecco/staging/{stamp}/ and verified")
        backup.mkdir(parents=True)
        self._backup_current(backup)
        self._swap_in(new_dir, staging, want, "rollback")
        self._guard(before, "rollback")

    def uninstall(self, stamp: str) -> None:
        self.log(f"== uninstall ({stamp})")
        before = protected_hashes(self.root)
        self.step(self.installed.is_dir(), "an integration is installed")
        staging, backup = self._dirs(stamp)
        backup.mkdir(parents=True)
        self._backup_current(backup)
        target = staging / "uninstalled" / DOMAIN
        target.parent.mkdir(parents=True)
        os.rename(self.installed, target)
        self.step(not self.installed.exists(), f"uninstalled: custom_components/{DOMAIN}/ moved to ecco/staging/{stamp}/uninstalled/ "
                  "(nothing deleted)")
        self._guard(before, "uninstall")


def stamps(base: str | None, n: int) -> list[str]:
    """n consecutive UTC stamps one second apart, from `base` (YYYYMMDD-HHMMSS) or now."""
    if base is not None and not STAMP_RE.fullmatch(base):
        raise DrillError(f"a stamp is YYYYMMDD-HHMMSS, got {base!r}")
    s0 = calendar.timegm(time.strptime(base, "%Y%m%d-%H%M%S")) if base else int(time.time())
    return [time.strftime("%Y%m%d-%H%M%S", time.gmtime(s0 + i)) for i in range(n)]


RUNBOOK = """ECCO Intelligence SHADOW install runbook (status: install kit staged, PENDING DP-4)
=====================================================================================
Every live step below is NOT AVAILABLE until (1) PR-5 (the deploy route for custom_components/: tools/deploy-ha-kit.ps1
and tools/place-ha-site-file.ps1) has merged and (2) the owner has given the separate go for the install (DP-4). Nothing
is installed or deployed by printing this. The full text, with the go / no-go criteria, is
docs/intelligence/INTELLIGENCE_SHADOW_INSTALL_RUNBOOK.md.

Kit: {kit}
SHA256SUMS: {sums_sha} ({n} files, verified: {verified})

 1. OFFLINE  verify this kit (done above) and run the offline suites (runbook section 2).
 2. OFFLINE  drill install / upgrade / rollback / uninstall on a marked mock root:
             python tools/ecco_intel_drill.py drill --config-root <mock root> --kit <kit>
 3. OFFLINE  owner: check the site file (decision status, item readiness, sha256; no ids printed):
             python tools/ecco_intel_drill.py site-check --site <site.local.json>
 4. PENDING  owner: place ecco/intelligence/site.local.json with tools/place-ha-site-file.ps1 (lands with PR-5);
             record its sha256 in <OFFLINE_EVIDENCE_DIR> first.
 5. PENDING  install the ui package (ecco_intelligence.yaml: the pause helper and the watchdog) BEFORE the integration.
 6. NOT AVAILABLE (PR-5, DP-4)  stage, verify, back up and swap the integration with tools/deploy-ha-kit.ps1 (Plan, then
             Install; lands with PR-5).
 7. NOT AVAILABLE (PR-5, DP-4)  restart Home Assistant ONLY with the owner's approval; keep it short (the latch caveat:
             an outage over ~5 min sets SHADOW_WOULD_AWAIT_ACK; recovery = a supervised dongle reboot by the owner).
 8. NOT AVAILABLE (PR-5, DP-4)  add the integration (one confirm step) with the pause helper still on, then verify: 11
             entities with the exact ids, status PAUSED and pause_control ON (helper on); turn the helper off: status
             STARTING, then a computed status after the start-up grace, pause_control OFF; supervision heartbeat age,
             SUPERVISED / stable nominal.
 9. Pause: turn input_boolean.ecco_intel_paused on (or disable the config entry). Never a restart.
10. Upgrade / rollback / uninstall: tools/deploy-ha-kit.ps1 -Action Upgrade / Rollback -BackupStamp / Uninstall; rollback
             restores ecco-backups/<stamp>/.
"""


def runbook(kit: Path, log=print) -> int:
    d = Drill(Path("."), log=lambda *_: None)
    try:
        d.verify_kit(kit)
        verified = "yes"
    except DrillError as exc:
        verified = f"NO ({exc})"
    sums = kit / "SHA256SUMS"
    sums_sha = sha256(sums) if sums.is_file() else "missing"
    n = len(read_sums(sums)) if sums.is_file() and verified == "yes" else 0
    log(RUNBOOK.format(kit=kit, sums_sha=sums_sha, n=n, verified=verified))
    return 0 if verified == "yes" else 1


# ---------------------------------------------------------------------------------------------------------------------
# site-check: the owner's site file, offline, through the runtime's own loader (no id, reference or value is printed)
# ---------------------------------------------------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
# amendment A25: the learned capacity and the register-204 capacity are never mapped in a v0.1 site file (I-D3 rests on the
# owner's stated value; the learned figure is compared read-only, outside the runtime, during acceptance)
V01_UNMAPPED_READINGS = ("capacity.fe1_wh_per_pct", "capacity.fe1_basis", "capacity.reg204_ah")
CAPACITY_READINGS = ("capacity.helper_kwh", "capacity.fe1_wh_per_pct", "capacity.reg204_ah")
SITE_CHECK_READ_LIMIT = 4 * 1024 * 1024             # the runtime's own cap is applied after the read (store.py)


def _engine():
    """The runtime's loader and the engine's rule constants, imported from this repository (no Home Assistant import:
    runtime/gates.py, runtime/store.py and the engine are plain Python). The repository root is appended to the import path
    (never in front of the standard library)."""
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    from custom_components.ecco_intelligence.runtime import gates, store
    from intelligence import quality, site_decisions, tou_table
    return gates, store, site_decisions, quality, tou_table


def _dedupe(seq) -> list:
    return list(dict.fromkeys(seq))


def _decision_rows(decisions, sd) -> dict:
    """Each decision's status, provenance and basis code: never its record reference, its value or a problem text (each can
    carry site text; an INVALID decision shows how many problems it has)."""
    rows = {}
    for did in sd.DECISION_IDS:
        d = decisions.get(did)
        row: dict = {"status": d.status}
        if d.status == sd.DecisionStatus.RECORDED:
            row["provenance"] = d.provenance              # one of Provenance.ALL (the type's invariant)
            row["accepted"] = decisions.satisfied(did)    # the runtime's default acceptance: OWNER_RECORD only
            row["record_ref"] = "present" if d.record_ref else "none"
            v = d.value
            basis = {"D1": getattr(v, "source", None), "D2": getattr(v, "supplied_by", None),
                     "D3": getattr(v, "kind", None), "D5": getattr(v, "basis", None)}.get(did)
            if did == "D3" and getattr(v, "resolve_at_run", False):
                basis = f"{basis} resolve_at_run"
            if did == "D6":
                basis = f"{len(getattr(v, 'limits_s', {}) or {})} limits"
            if basis:
                row["basis"] = basis
            row["accepted"] = "yes" if row["accepted"] else "no (not an OWNER_RECORD: counts as OPEN)"
        elif d.status == sd.DecisionStatus.INVALID:
            row["problems"] = len(d.problems)
        rows[sd.display_label(did)] = row
    return rows


def _readiness(load, sd, q, tt) -> tuple[dict, list[str]]:
    """({item: {"readiness": BLOCKED | LIVE_INPUTS_DECIDE, "blockers": [...]}}, the mapped keys that have no I-D6 limit).

    The blockers the file alone already causes, from the engine's own rules: the decision gate (site_decisions.gate), the
    required inputs (site_decisions.required_inputs), the charge window's TOU inputs and both liveness readings (the
    charge-window items and overnight_demand; the clock offset for the charge-window items: quality and daily_plan), the
    supervision readings (export and Dump) and the event table (export), an I-D6 limit for every gate reading needed
    (UNRESOLVED is never fresh) and the site facts. (The charge target rests on overnight_demand and the morning SOC on the
    charge target; their own needs already include everything those items need, so no separate entry is made.) A FAIL
    load check withholds everything (the runtime publishes SELF_TEST_FAILED). Codes and contract keys only."""
    decisions = load.decisions or sd.DecisionSet.from_mapping({}, source="site_local")
    emap = load.entity_map
    limits, _notes = sd.freshness_limits(decisions)
    failed = [c.code for c in load.checks if c.level == "FAIL"]
    cap = decisions.value("D3") if decisions.satisfied("D3") else None
    n_cap = int(cap is not None and not cap.resolve_at_run and cap.value_kwh is not None)
    n_cap += sum(1 for k in CAPACITY_READINGS if k in emap.readings)
    unconverted = ("capacity.reg204_ah" in emap.readings
                   and not (cap is not None and cap.nominal_voltage_v is not None))
    ctx = sd.GateContext(capacity_sources=n_cap, capacity_mismatch_pct=None if unconverted else 0.0)
    out: dict = {}
    for item in sd.PUBLISHED_ITEMS:
        blockers = [f"SELF_TEST_FAILED:{code}" for code in failed]
        blockers += [f.code for f in sd.gate(item, decisions, ctx) if f.severity == sd.BLOCK]
        ri = sd.required_inputs(item, decisions)
        signals, readings = list(ri.signals), list(ri.readings)
        if ri.charge_window_sources or item == "overnight_demand":
            readings += [*tt.TOU_INPUT_KEYS, sd.LIVENESS_KEY, sd.CONFIG_LIVENESS_KEY]
        if ri.charge_window_sources:
            readings.append("inverter.clock_offset_s")
        if item in q.EXPORT_ITEMS:
            readings += [*q.SUPERVISION_KEYS, sd.LIVENESS_KEY]
        if item in q.EVENT_ITEMS:
            readings.append("tariff.events")
        for s in _dedupe(signals):
            if s == "history.hourly":
                if not load.plan.statistic_ids:
                    blockers.append("NO_HISTORY_SOURCE")
                continue
            mapped = s in emap.signals or (s == "battery.soc" and "battery.soc_raw_pct" in emap.readings)
            if not mapped:
                blockers.append(f"NOT_MAPPED:{s}")
            elif limits.get(s) is None:
                blockers.append(f"NO_I_D6_LIMIT:{s}")
        for r in _dedupe(readings):
            if r not in emap.readings:
                blockers.append(f"NOT_MAPPED:{r}")
            elif r in sd.FRESHNESS_OVERRIDE_KEYS and limits.get(r) is None:
                blockers.append(f"NO_I_D6_LIMIT:{r}")
        for fact in ri.site_facts:
            if getattr(load.site_facts, fact, None) is None:
                blockers.append(f"SITE_FACT_MISSING:{fact}")
        out[item] = _dedupe(blockers)
    unlimited = sorted(k for k in set(emap.readings) | set(emap.signals)
                       if k in sd.FRESHNESS_OVERRIDE_KEYS and limits.get(k) is None)
    return ({item: {"readiness": "BLOCKED" if b else "LIVE_INPUTS_DECIDE", "blockers": b} for item, b in out.items()},
            unlimited)


def site_check_report(raw: bytes, name: str) -> dict:
    """The site-check report of one site file's bytes (pure; nothing in it is an entity id, a record reference, a source
    name or a decision value)."""
    gates, store, sd, q, tt = _engine()
    problems: list[str] = []
    too_big = len(raw) > store.MAX_SITE_FILE_BYTES
    load = gates.load_site(None if too_big else raw,
                           "the site file is larger than the runtime's safety cap" if too_big else None)
    checks = [{"code": c.code, "level": c.level, "text": c.text} for c in load.checks]
    problems += [f"{c['code']} FAIL" for c in checks if c["level"] == "FAIL"]
    decisions = load.decisions
    drows = _decision_rows(decisions, sd) if decisions is not None else {}
    problems += [f"{lab} INVALID" for lab, row in drows.items() if row["status"] == sd.DecisionStatus.INVALID]
    items, unlimited = _readiness(load, sd, q, tt)
    emap = load.entity_map
    mapped_v01 = [k for k in V01_UNMAPPED_READINGS if k in emap.readings]
    rules = [{"rule": "V01_CAPACITY_SOURCES_UNMAPPED", "result": "FAIL" if mapped_v01 else "PASS",
              "text": ("mapped, but stays unmapped in v0.1 (A25): " + ", ".join(mapped_v01)) if mapped_v01 else
                      "no learned or register-204 capacity source is mapped (A25)"}]
    problems += [f"{r['rule']} FAIL" for r in rules if r["result"] == "FAIL"]
    return {
        "tool": "ecco_intel_drill site-check",
        "file": {"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                 "config_hash": hashlib.sha256(raw).hexdigest()[:16]},
        "checks": checks,
        "entity_map": {"present": emap.present, "signals": len(emap.signals), "readings": len(emap.readings),
                       "entities": len(emap.entity_ids()), "history_statistic_ids": len(load.plan.statistic_ids),
                       "mapped_without_i_d6_limit": unlimited},
        "decisions": drows if decisions is not None else "REFUSED",
        "items": items,
        "v01_rules": rules,
        "result": "PROBLEMS" if problems else "OK",
        "problems": problems,
    }


def render_site_check(rep: dict) -> str:
    f = rep["file"]
    lines = ["ECCO Intelligence site-check (offline; prints no entity id, record reference, source name or decision value)",
             f"File        : {f['name']}, {f['bytes']} bytes",
             f"sha256      : {f['sha256']}",
             f"config_hash : {f['config_hash']} (the status entity's config_hash attribute: the first 16 hex digits)",
             "Load checks :"]
    lines += [f"  {c['level']:<5} {c['code']}: {c['text']}" for c in rep["checks"]]
    m = rep["entity_map"]
    lines.append(f"Entity map  : {'present' if m['present'] else 'absent'}; {m['signals']} signals, {m['readings']} "
                 f"readings, {m['entities']} entities; {m['history_statistic_ids']} history statistic ids")
    if m["mapped_without_i_d6_limit"]:
        lines.append("  mapped, but no I-D6 limit (never fresh): " + ", ".join(m["mapped_without_i_d6_limit"]))
    lines.append("Decisions   :")
    if rep["decisions"] == "REFUSED":
        lines.append("  REFUSED: the decisions block does not load (see SITE_DECISIONS)")
    else:
        for lab, row in rep["decisions"].items():
            extra = [f"{k} {v}" for k, v in row.items() if k != "status"]
            lines.append((f"  {lab:<5} {row['status']:<8}" + (f" {'; '.join(extra)}" if extra else "")).rstrip())
    lines.append("Items (static readiness: the file can prove BLOCKED, never OK):")
    for item, r in rep["items"].items():
        lines.append(f"  {item:<22} {r['readiness']}" + (f": {', '.join(r['blockers'])}" if r["blockers"] else
                                                          " (the file blocks nothing; the live inputs decide)"))
    lines.append("v0.1 rules  :")
    lines += [f"  {r['result']:<5} {r['rule']}: {r['text']}" for r in rep["v01_rules"]]
    lines.append(f"Result      : {rep['result']}" + (f" ({'; '.join(rep['problems'])})" if rep["problems"] else ""))
    return "\n".join(lines)


def site_check(site: Path, *, as_json: bool = False, log=print) -> int:
    if not site.is_file():
        raise DrillError(f"site-check: {site.name} is not a file")
    with open(site, "rb") as fh:
        raw = fh.read(SITE_CHECK_READ_LIMIT + 1)
    if len(raw) > SITE_CHECK_READ_LIMIT:
        raise DrillError(f"site-check: {site.name} is far larger than any site file")
    rep = site_check_report(raw, site.name)
    log(json.dumps(rep, indent=1, sort_keys=True) if as_json else render_site_check(rep))
    return 0 if rep["result"] == "OK" else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("drill", "install", "upgrade", "rollback", "uninstall"):
        p = sub.add_parser(name)
        p.add_argument("--config-root", required=True)
        p.add_argument("--stamp", default=None)
        if name in ("drill", "install", "upgrade"):
            p.add_argument("--kit", required=True)
        if name == "drill":
            p.add_argument("--upgrade-kit", default=None)
        if name == "rollback":
            p.add_argument("--backup", default=None)
    p = sub.add_parser("runbook")
    p.add_argument("--kit", required=True)
    p = sub.add_parser("site-check")
    p.add_argument("--site", required=True)
    p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        refuse_hosts([getattr(args, k, None) for k in ("config_root", "kit", "upgrade_kit", "backup", "stamp", "site")])
        if args.cmd == "runbook":
            return runbook(Path(args.kit).resolve())
        if args.cmd == "site-check":
            return site_check(Path(args.site).resolve(), as_json=args.json)
        d = Drill(mock_root(args.config_root))
        if args.cmd == "drill":
            kit = Path(args.kit).resolve()
            up = Path(args.upgrade_kit).resolve() if args.upgrade_kit else kit
            s = stamps(args.stamp, 4)
            d.install(kit, s[0])
            d.install(up, s[1], upgrade=True)
            d.rollback(s[2], s[1])
            d.uninstall(s[3])
        elif args.cmd in ("install", "upgrade"):
            d.install(Path(args.kit).resolve(), args.stamp or stamp_now(), upgrade=args.cmd == "upgrade")
        elif args.cmd == "rollback":
            d.rollback(args.stamp or stamp_now(), args.backup)
        else:
            d.uninstall(args.stamp or stamp_now())
    except (DrillError, OSError, ValueError) as exc:
        print(f"ecco_intel_drill: REFUSED / FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"{args.cmd}: {sum(1 for s in d.steps if s[0] == 'PASS')} steps PASS (mock root only; nothing deployed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
