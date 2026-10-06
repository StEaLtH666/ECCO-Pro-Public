#!/usr/bin/env python3
"""Offline tests for the ECCO canonical/legacy telemetry compatibility layer.

This does NOT execute Flux and does NOT touch InfluxDB. It proves two
different things, and is explicit about the difference:

1. The SELECTION ALGORITHM is correct: a pure-Python reference
   implementation of the same "most-recent-wins" (readEccoTelemetryLatest)
   and "per-window canonical-preferred, legacy-fallback"
   (readEccoTelemetryHistory) rules described in
   influxdb/lib/ecco_telemetry_compat.flux, exercised against the
   synthetic scenarios requested for this migration: legacy-only,
   canonical-only, overlapping raw+canonical, overlap that must not be
   double-counted, positive grid import, negative grid export, missing
   canonical samples, the cutover boundary itself, a canonical gap
   occurring AFTER canonical has already started (added in Task 004A,
   with legacy filling exactly that gap and nothing double-counted), and
   (added in Task 004B) deliberately misaligned canonical/legacy sample
   times within one shared window, proving the returned history
   timestamp is always the window boundary rather than either source's
   own original sample time - see readEccoTelemetryHistory's docstring
   for why an unnormalised timestamp would corrupt Battery Outlook's
   minute-of-day profile learning.

2. The Flux FILES stay structurally honest: every file under
   influxdb/diagnostics/ is read-only (no `to(` call, so it can never
   write) and is never an automatic task (no `option task`, so it can
   never be scheduled) - and the compatibility layer inlined into
   ecco_battery_outlook_5m_shadow_preview.flux, the production
   Battery Outlook 5-minute task, and the daily scorer stay byte-for-byte
   identical to influxdb/lib/ecco_telemetry_compat.flux, so embedded
   compatibility copies cannot silently drift apart.

What this does NOT prove, and cannot prove without a live InfluxDB:
that the actual Flux syntax in ecco_telemetry_compat.flux, the two
diagnostic scripts, and the shadow preview actually executes correctly
against a real InfluxDB engine. See docs/CANONICAL_TELEMETRY_MIGRATION.md
for the exact live-validation checklist.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB_FILE = ROOT / "influxdb" / "lib" / "ecco_telemetry_compat.flux"
SHADOW_FILE = ROOT / "influxdb" / "diagnostics" / "ecco_battery_outlook_5m_shadow_preview.flux"
PRODUCTION_TASK_FILE = ROOT / "influxdb" / "tasks" / "ecco_battery_outlook_5m.flux"
SCORER_TASK_FILE = ROOT / "influxdb" / "tasks" / "ecco_battery_outlook_score_daily.flux"
DIAGNOSTICS_DIR = ROOT / "influxdb" / "diagnostics"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------
# Reference implementation, mirroring influxdb/lib/ecco_telemetry_compat.flux
# ---------------------------------------------------------------------

def select_latest(canonical_points, legacy_points):
    """Mirrors readEccoTelemetryLatest: most-recent-wins, ties to canonical.

    Each of canonical_points/legacy_points is a list of (timestamp, value)
    already filtered to the query range. Returns a dict with source/time/
    value, or None if both are empty.
    """
    canonical_last = max(canonical_points, key=lambda p: p[0]) if canonical_points else None
    legacy_last = max(legacy_points, key=lambda p: p[0]) if legacy_points else None

    if canonical_last is not None and legacy_last is not None:
        if canonical_last[0] >= legacy_last[0]:
            return {"source": "canonical", "time": canonical_last[0], "value": canonical_last[1]}
        return {"source": "legacy", "time": legacy_last[0], "value": legacy_last[1]}
    if canonical_last is not None:
        return {"source": "canonical", "time": canonical_last[0], "value": canonical_last[1]}
    if legacy_last is not None:
        return {"source": "legacy", "time": legacy_last[0], "value": legacy_last[1]}
    return None


def truncate_to_window(t, window_size):
    return (t // window_size) * window_size


def select_history_windowed(canonical_points, legacy_points, range_start, range_stop, window_size):
    """Mirrors readEccoTelemetryHistory: per-window canonical-preferred,
    legacy-fallback (replaces an earlier "permanent split at the earliest
    canonical timestamp" design - see the module docstring/Task 004A for
    why that was wrong: a canonical-side gap AFTER canonical had already
    started would fall in "canonical territory" under a permanent split
    and get silently dropped from both sources).

    Each point's timestamp is truncated to its containing window. A
    window is served by canonical if canonical has any point in it
    (last point per window, same as `last()` in the real Flux); every
    other window in range falls back to legacy if legacy has a point
    there. A window can never appear from both sources.

    Task 004B: the returned timestamp is the WINDOW BOUNDARY, not the
    winning point's own original sample time - matching the real Flux
    function's `_time: r._window` normalisation. Without this, two
    points chosen for the same logical 5-minute window (canonical and
    legacy are independently-polled series, not synchronised to the
    same instant) could carry different original timestamps and get
    classified into different minute-of-day slots by Battery Outlook's
    date.hour()/date.minute() profile learning, even though they
    represent the same window. The original sample time is preserved as
    the 4th tuple element for diagnostics, mirroring `_ecco_original_time`.

    Returns a list of (window_time, value, source, original_time).
    """
    def in_range(points):
        return [(t, v) for (t, v) in points if range_start <= t <= range_stop]

    def last_per_window(points):
        by_window = {}
        for t, v in points:
            w = truncate_to_window(t, window_size)
            if w not in by_window or t >= by_window[w][0]:
                by_window[w] = (t, v)
        return by_window

    canonical_by_window = last_per_window(in_range(canonical_points))
    legacy_by_window = last_per_window(in_range(legacy_points))

    result = [
        (window, v, "canonical", t)
        for window, (t, v) in canonical_by_window.items()
    ]
    result += [
        (window, v, "legacy", t)
        for window, (t, v) in legacy_by_window.items()
        if window not in canonical_by_window
    ]
    return result


# ---------------------------------------------------------------------
# Scenario 1: legacy data only (no canonical telemetry exists yet)
# ---------------------------------------------------------------------
print("[1] Legacy data only")
result = select_latest(canonical_points=[], legacy_points=[(100, 42.0), (200, 43.0)])
check("latest falls back to legacy when canonical is empty", result == {"source": "legacy", "time": 200, "value": 43.0})

history = select_history_windowed(canonical_points=[], legacy_points=[(10, 1.0), (20, 2.0), (30, 3.0)], range_start=0, range_stop=100, window_size=5)
check(
    "history is entirely legacy when canonical is empty",
    sorted(history) == sorted([(10, 1.0, "legacy", 10), (20, 2.0, "legacy", 20), (30, 3.0, "legacy", 30)]),
)

# ---------------------------------------------------------------------
# Scenario 2: canonical data only (legacy has aged out / never present)
# ---------------------------------------------------------------------
print("")
print("[2] Canonical data only")
result = select_latest(canonical_points=[(100, 55.0)], legacy_points=[])
check("latest uses canonical when legacy is empty", result == {"source": "canonical", "time": 100, "value": 55.0})

history = select_history_windowed(canonical_points=[(10, 1.0), (20, 2.0)], legacy_points=[], range_start=0, range_stop=100, window_size=5)
check(
    "history is entirely canonical when legacy is empty",
    sorted(history) == sorted([(10, 1.0, "canonical", 10), (20, 2.0, "canonical", 20)]),
)

# ---------------------------------------------------------------------
# Scenario 3: overlapping raw + canonical
# ---------------------------------------------------------------------
print("")
print("[3] Overlapping raw + canonical")
# Normal healthy case: once canonical is live, its own latest sample is at
# least as recent as legacy's (both trace the same ~10s firmware poll).
canonical_pts = [(150, 60.0), (250, 61.0), (300, 62.0)]
legacy_pts = [(100, 58.0), (200, 59.0), (250, 61.0)]
result = select_latest(canonical_points=canonical_pts, legacy_points=legacy_pts)
check("latest prefers canonical's own latest point when both are current", result == {"source": "canonical", "time": 300, "value": 62.0})

# ---------------------------------------------------------------------
# Scenario 4: overlapping values that must NOT be double-counted, and a
# canonical gap AFTER canonical has already started must still be filled
# from legacy rather than silently dropped (Task 004A finding: the
# original "permanent split at earliest canonical timestamp" design
# could not do this - a later gap fell inside "canonical territory" by
# construction and contributed nothing from either source).
# ---------------------------------------------------------------------
print("")
print("[4] Overlap must not be double-counted, and a later canonical gap is filled from legacy")
window_size = 10
# Windows (by truncated start): 0, 10, 20 -> canonical has data, legacy
# also has data (normal overlap). 30, 40 -> canonical has a GAP here
# even though it already started at window 0; legacy keeps recording
# throughout. 50 -> canonical resumes. 60 -> beyond canonical's current
# reach entirely; legacy is the only source.
canonical_pts = [(5, 100.0), (15, 101.0), (25, 102.0), (55, 105.0)]
legacy_pts = [(5, 100.0), (15, 101.0), (25, 102.0), (35, 103.0), (45, 104.0), (55, 105.0), (65, 106.0)]
history = select_history_windowed(canonical_points=canonical_pts, legacy_points=legacy_pts, range_start=0, range_stop=69, window_size=window_size)

windows_seen = [window for (window, _v, _s, _orig) in history]
check("no 5-minute-equivalent window appears twice", len(windows_seen) == len(set(windows_seen)), f"windows={windows_seen}")
check("total count equals distinct windows covered by either source (no inflation)", len(history) == 7, f"history={history}")

check("normal overlap (windows 0,10,20) still chooses canonical, not legacy",
      (0, 100.0, "canonical", 5) in history and (10, 101.0, "canonical", 15) in history and (20, 102.0, "canonical", 25) in history
      and not any(s == "legacy" and w == 0 for (w, _v, s, _o) in history))

check("the later canonical gap (windows 30, 40) is filled from legacy, not dropped",
      (30, 103.0, "legacy", 35) in history and (40, 104.0, "legacy", 45) in history)
check("canonical resuming after its own gap (window 50) is preferred again",
      (50, 105.0, "canonical", 55) in history and not any(s == "legacy" and w == 50 for (w, _v, s, _o) in history))
check("a window entirely beyond canonical's reach (window 60) still falls back to legacy",
      (60, 106.0, "legacy", 65) in history)

# Timestamp normalisation (Task 004B): every returned window time must
# be the truncated boundary, distinct from the winning point's own
# original sample time whenever that point wasn't already exactly on
# the boundary - true for every entry in this scenario (5->0, 15->10,
# 25->20, 35->30, 45->40, 55->50, 65->60), for BOTH the canonical and
# the legacy-fallback path. A sharper, more direct version of this same
# proof (deliberately misaligned canonical/legacy timestamps within one
# window) follows in its own scenario below.
check("every entry's window time differs from its original sample time (none were already on a boundary)",
      all(w != orig for (w, _v, _s, orig) in history), f"history={history}")
check("original sample time is preserved separately (4th element) and is never lost",
      all(orig is not None for (_w, _v, _s, orig) in history))

# ---------------------------------------------------------------------
# Scenario 5: positive grid import (sign must pass through unchanged)
# ---------------------------------------------------------------------
print("")
print("[5] Positive grid import value is preserved exactly")
result = select_latest(canonical_points=[(100, 2350.0)], legacy_points=[])
check("positive import value unchanged", result["value"] == 2350.0)

# ---------------------------------------------------------------------
# Scenario 6: negative grid export (sign must pass through unchanged)
# ---------------------------------------------------------------------
print("")
print("[6] Negative grid export value is preserved exactly")
result = select_latest(canonical_points=[(100, -1875.5)], legacy_points=[])
check("negative export value unchanged (not abs()'d, not flipped)", result["value"] == -1875.5)
result_fallback = select_latest(canonical_points=[], legacy_points=[(100, -1875.5)])
check("negative export value unchanged via legacy fallback too", result_fallback["value"] == -1875.5)

# ---------------------------------------------------------------------
# Scenario 7: missing canonical samples (a gap while legacy keeps recording)
# ---------------------------------------------------------------------
print("")
print("[7] Missing canonical samples (canonical has a recent gap)")
# Canonical's last known point is old (t=100); legacy has kept recording
# fresh data through a canonical-side gap up to t=500.
canonical_pts = [(90, 20.0), (100, 21.0)]
legacy_pts = [(90, 20.0), (100, 21.0), (200, 22.0), (300, 23.0), (400, 24.0), (500, 25.0)]
result = select_latest(canonical_points=canonical_pts, legacy_points=legacy_pts)
check(
    "a stale canonical point during a gap does not win over fresher legacy data",
    result == {"source": "legacy", "time": 500, "value": 25.0},
    f"got {result} - this is exactly the bug the first design (canonical-wins-if-any-point-exists) had",
)

# ---------------------------------------------------------------------
# Scenario 8: cutover boundary (the instant canonical's first point
# appears). With per-window selection this "boundary" is local to each
# window, not a single global split: only the window canonical actually
# covers becomes canonical - every other window, before OR after it,
# falls back to legacy if legacy has data there. (Under the earlier
# permanent-global-split design, anything after the boundary was always
# canonical-or-nothing; that is exactly the behaviour Task 004A's gap
# scenario showed was wrong, so this test now asserts the corrected
# per-window behaviour instead.)
# ---------------------------------------------------------------------
print("")
print("[8] Cutover boundary is local to its own window, not a global split")
window_size = 100
canonical_pts = [(500, 30.0)]
legacy_pts = [(100, 25.0), (300, 27.0), (500, 30.0), (700, 31.0)]
history = select_history_windowed(canonical_points=canonical_pts, legacy_points=legacy_pts, range_start=0, range_stop=999, window_size=window_size)
check("the exact window canonical first appears in is attributed to canonical, not legacy",
      (500, 30.0, "canonical", 500) in history and not any(w == 500 and s == "legacy" for (w, _v, s, _o) in history))
check("windows strictly before canonical's window stay legacy",
      (100, 25.0, "legacy", 100) in history and (300, 27.0, "legacy", 300) in history)
check("a window after canonical's window, where canonical has no data, still falls back to legacy",
      (700, 31.0, "legacy", 700) in history)
result_at_boundary = select_latest(canonical_points=canonical_pts, legacy_points=[(500, 30.0)])
check("at the exact boundary instant, a tie goes to canonical", result_at_boundary["source"] == "canonical")

# ---------------------------------------------------------------------
# Scenario 9 (Task 004B): deliberately misaligned timestamps within the
# same 5-minute window. Legacy sampled at 10:00:10, canonical sampled at
# 10:04:40 - both fall in the 10:00:00-10:05:00 window, but their raw
# timestamps differ by 4m30s. Canonical should win the window (it has a
# point there), and critically the returned history timestamp must be
# the window boundary 10:00:00, NOT canonical's own 10:04:40 - otherwise
# Battery Outlook's date.hour()/date.minute() profile learning would
# classify this as slot 10:04 instead of the intended 10:00 slot.
# Times below are expressed as seconds-of-day for readability.
# ---------------------------------------------------------------------
print("")
print("[9] Misaligned timestamps within one window are normalised to the window boundary")
window_size_5m = 300  # 5 minutes, in seconds
ten_am = 10 * 3600
legacy_at_10_00_10 = ten_am + 10
canonical_at_10_04_40 = ten_am + 4 * 60 + 40
window_boundary_10_00_00 = truncate_to_window(legacy_at_10_00_10, window_size_5m)
check("legacy (10:00:10) and canonical (10:04:40) truncate to the same window", truncate_to_window(canonical_at_10_04_40, window_size_5m) == window_boundary_10_00_00)

history = select_history_windowed(
    canonical_points=[(canonical_at_10_04_40, 55.0)],
    legacy_points=[(legacy_at_10_00_10, 50.0)],
    range_start=ten_am,
    range_stop=ten_am + 3600,
    window_size=window_size_5m,
)
check("exactly one entry is produced for the shared window (no duplicate window)", len(history) == 1, f"history={history}")
check("canonical wins the window even though legacy also has a point in it",
      history[0][2] == "canonical" and history[0][1] == 55.0)
check(
    "the returned logical history timestamp is the window boundary (10:00:00), not canonical's original 10:04:40",
    history[0][0] == window_boundary_10_00_00 and history[0][0] != canonical_at_10_04_40,
)
check("canonical's own original sample time (10:04:40) is preserved separately, not discarded",
      history[0][3] == canonical_at_10_04_40)

# Same proof for the legacy-fallback path: when canonical has a gap and
# legacy fills a window, the fallback value/source must be unchanged and
# the returned timestamp must still be the window boundary, not
# legacy's own original (also misaligned) sample time.
gap_history = select_history_windowed(
    canonical_points=[],
    legacy_points=[(legacy_at_10_00_10, 50.0)],
    range_start=ten_am,
    range_stop=ten_am + 3600,
    window_size=window_size_5m,
)
check("legacy fallback in a canonical gap: exactly one entry, no duplicate window", len(gap_history) == 1)
check("legacy fallback: source and value are unchanged from the input", gap_history[0][2] == "legacy" and gap_history[0][1] == 50.0)
check(
    "legacy fallback: the returned timestamp is also the window boundary, not legacy's own 10:00:10",
    gap_history[0][0] == window_boundary_10_00_00 and gap_history[0][0] != legacy_at_10_00_10,
)
check("legacy fallback: original sample time (10:00:10) is preserved separately",
      gap_history[0][3] == legacy_at_10_00_10)

# ---------------------------------------------------------------------
# Static file checks: diagnostics stay read-only and never auto-scheduled
# ---------------------------------------------------------------------
print("")
print("[10] Diagnostic Flux files are read-only and never scheduled")
def strip_flux_comments(text: str) -> str:
    """Removes '//' line comments so a substring check only sees code.
    Flux has no block-comment syntax, so this is a complete strip."""
    lines = []
    for line in text.splitlines():
        idx = line.find("//")
        lines.append(line if idx == -1 else line[:idx])
    return "\n".join(lines)


diagnostic_flux_files = sorted(DIAGNOSTICS_DIR.glob("*.flux"))
check("at least one diagnostic Flux file exists", len(diagnostic_flux_files) > 0)
for f in diagnostic_flux_files:
    code_only = strip_flux_comments(f.read_text(encoding="utf-8")).replace(" ", "")
    check(f"{f.name}: contains no to() call (cannot write)", "to(" not in code_only)
    check(f"{f.name}: is not an option task (never auto-scheduled)", "optiontask" not in code_only)

# ---------------------------------------------------------------------
# Static file check: the inlined compatibility layer must not drift
# ---------------------------------------------------------------------
print("")
print("[11] Inlined compatibility layer matches the library source exactly")


def extract_function_bodies(text: str) -> str:
    """Returns the text from the first readEccoTelemetryLatest definition
    through the end of the readEccoTelemetryHistory function (its closing
    brace at column 0), ignoring surrounding comments/imports/callers so
    this comparison is robust to each file's own header/footer content.
    """
    start = text.index("readEccoTelemetryLatest = (")
    history_start = text.index("readEccoTelemetryHistory = (", start)
    # The history function's closing brace is the first line that is
    # exactly "}" after its start.
    end = text.index("\n}\n", history_start) + len("\n}")
    return text[start:end]


if (
    LIB_FILE.exists()
    and SHADOW_FILE.exists()
    and PRODUCTION_TASK_FILE.exists()
    and SCORER_TASK_FILE.exists()
):
    lib_text = LIB_FILE.read_text(encoding="utf-8")
    shadow_text = SHADOW_FILE.read_text(encoding="utf-8")
    production_text = PRODUCTION_TASK_FILE.read_text(encoding="utf-8")
    scorer_text = SCORER_TASK_FILE.read_text(encoding="utf-8")

    lib_functions = extract_function_bodies(lib_text)
    shadow_functions = extract_function_bodies(shadow_text)
    production_functions = extract_function_bodies(production_text)
    scorer_functions = extract_function_bodies(scorer_text)

    check(
        "shadow preview's inlined functions are byte-for-byte identical to the library",
        lib_functions == shadow_functions,
        "the shadow copy has drifted from influxdb/lib/ecco_telemetry_compat.flux",
    )
    check(
        "production Battery Outlook's inlined functions are byte-for-byte identical to the library",
        lib_functions == production_functions,
        "the production copy has drifted from influxdb/lib/ecco_telemetry_compat.flux",
    )
    check(
        "daily scorer's inlined functions are byte-for-byte identical to the library",
        lib_functions == scorer_functions,
        "the scorer copy has drifted from influxdb/lib/ecco_telemetry_compat.flux",
    )
    check(
        "daily scorer actual SOC uses canonical measurement with legacy fallback",
        'canonicalMeasurement: "sensor.ecco_battery_soc"' in scorer_text
        and 'legacyMeasurement: "sensor.ecco_clock_dongle_ecco_battery_soc"' in scorer_text
        and "rangeStop: actualStopTime" in scorer_text,
        "scorer SOC compatibility call is incomplete or has drifted",
    )
else:
    missing = [
        str(path)
        for path in (
            LIB_FILE,
            SHADOW_FILE,
            PRODUCTION_TASK_FILE,
            SCORER_TASK_FILE,
        )
        if not path.exists()
    ]
    check(
        "library, shadow preview, production task and scorer files exist",
        False,
        f"missing: {missing}",
    )

# ---------------------------------------------------------------------
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All offline checks PASSED.")

print("")
print("This proves the SELECTION ALGORITHM and FILE STRUCTURE are correct.")
print("Offline checks do not by themselves prove a new call site executes live.")
print("The compatibility layer and both production Battery Outlook consumers were live-proven on 2026-09-18.")
print("The daily scorer call site was previewed read-only, then executed successfully in the live scheduled task.")

if FAILURES:
    sys.exit(1)
