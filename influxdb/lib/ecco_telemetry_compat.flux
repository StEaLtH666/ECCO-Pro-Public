// ECCO Pro - canonical/legacy telemetry compatibility layer
//
// STATUS: live-proven in both production Battery Outlook consumers on
// 2026-09-18: the 5-minute forecasting task and the daily scorer. This file
// remains the single source of truth for embedded compatibility copies.
//
// Why this can't be a real Flux "import" today: InfluxDB Flux tasks do
// not have a first-class mechanism for importing a plain repo file as a
// shared library the way a task's own `import "date"` pulls in a
// server-side stdlib package. Making this genuinely importable would
// require registering it as a custom package on the InfluxDB server
// (an admin/deployment action, out of scope here and not something this
// task is allowed to do - "do not modify live InfluxDB"). Until that
// exists, any consumer embeds these two functions verbatim and must keep
// them byte-for-byte identical to this file. See
// influxdb/diagnostics/test_telemetry_selection_logic.py for a static
// check that enforces that.
//
// Two access patterns, because Battery Outlook genuinely needs both:
//
// 1. readEccoTelemetryLatest - "give me the single most recent value"
//    (used for current SOC, and for the pre-charge actual-SOC scoring
//    read). Most-recent-wins: reads each source's own latest point in
//    the requested range and returns whichever of the two is itself
//    more recent (ties go to canonical). This is deliberately NOT
//    "prefer canonical whenever it has any point at all in a wide
//    lookback window" - that simpler rule was tried first and rejected
//    because it would keep returning a stale canonical point through a
//    canonical-side outage/gap even while legacy kept recording fresh
//    data through the same gap (see the "missing canonical samples"
//    case in test_telemetry_selection_logic.py, which is exactly what
//    caught this). A single point read never risks double-counting - at
//    most one point is ever returned.
//
// 2. readEccoTelemetryHistory - "give me a history suitable for
//    aggregation" (used for the 30-day house-load profile/training-day
//    count, read from the ecco_5m bucket). A naive union of both series
//    would double-count any period where both happen to have data.
//
//    First design tried here was a single permanent split at the
//    EARLIEST canonical timestamp (legacy strictly before it, canonical
//    from it onward). That is wrong for this consumer: if canonical has
//    a LATER gap - a Home Assistant restart, the dongle briefly
//    unavailable, anything after canonical has already been running for
//    a while - that gap falls entirely within "canonical territory" by
//    the permanent split, so it contributes neither canonical (absent)
//    nor legacy (excluded by the split) data. The 30-day training-day
//    count would silently lose real history it should have kept.
//
//    Instead this selects PER 5-MINUTE WINDOW (matching ecco_5m's own
//    granularity - this bucket is ECCO's 5-minute downsample, and the
//    production task's own load-profile logic already groups by
//    5-minute slot-of-day): every point's timestamp is truncated to its
//    containing 5-minute window. A window is served by canonical if
//    canonical has ANY point in it; every other window in range falls
//    back to legacy if legacy has a point there. This is a per-window
//    partition, not a global one - canonical is preferred wherever it
//    actually has data, a gap in canonical (at any point in time, not
//    just before some cutover) is transparently filled from legacy, and
//    a window can never be counted from both sources because legacy is
//    explicitly excluded from every window canonical already covers.
//    Existing legacy training history is never discarded, with no
//    manually-maintained cutover date.
//
//    The returned row's `_time` is the WINDOW BOUNDARY, not the winning
//    point's own original sample time (preserved separately in
//    `_ecco_original_time`). This matters because canonical and legacy
//    are two independently-polled series that are not synchronised to
//    the same instant, so two points chosen for the same logical
//    5-minute window can still carry different original timestamps -
//    and Battery Outlook's load-profile learning classifies history by
//    date.hour()/date.minute() of `_time`, so an unnormalised timestamp
//    could split one 5-minute slot across two minute-of-day buckets
//    depending on which source answered. Normalising removes that
//    dependency entirely, including any dependency on ecco_5m's own
//    exact timestamp alignment (unknown from this repository - no
//    rollup task for it is checked in here).
//
//    The exact real alignment of ecco_5m's own timestamps (whether
//    points land exactly on 5-minute boundaries or merely close to it)
//    is not visible from this repository - there is no rollup task
//    checked in here that produces ecco_5m, so truncation is used
//    specifically because it enforces a consistent window boundary
//    rather than assuming the underlying data already has one. See
//    "Live checks" in docs/CANONICAL_TELEMETRY_MIGRATION.md.
//
// Every returned row carries an added `_ecco_source` column
// ("canonical" or "legacy") so any consumer or diagnostic can see which
// source contributed each point.
//
// Grid sign convention: neither function transforms values in any way -
// whatever the source measurement's field value is, positive or
// negative, passes through unchanged. Sign convention (positive =
// import, negative = export for grid; the canonical grid entity is a
// direct alias of the CT-clamp source, no transform applied there
// either) is therefore preserved automatically, not by any logic in
// this file.
//
// LIVE STATUS: these functions and their Flux constructs were exercised
// successfully against the real InfluxDB installation on 2026-09-18 through
// diagnostics and both production Battery Outlook consumers. A newly-added
// consumer should still be validated at its own call site before that
// consumer is considered live-proven.

import "array"
import "date"

readEccoTelemetryLatest = (bucket, canonicalMeasurement, legacyMeasurement, field, rangeStart, rangeStop=now()) => {
  canonicalLast =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == canonicalMeasurement and r._field == field)
      |> group()
      |> last()
      |> map(fn: (r) => ({ r with _ecco_source: "canonical" }))
      |> findRecord(fn: (key) => true, idx: 0)

  legacyLast =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == legacyMeasurement and r._field == field)
      |> group()
      |> last()
      |> map(fn: (r) => ({ r with _ecco_source: "legacy" }))
      |> findRecord(fn: (key) => true, idx: 0)

  hasCanonical = exists canonicalLast._time
  hasLegacy = exists legacyLast._time

  chosen =
    if hasCanonical and hasLegacy then
      (if canonicalLast._time >= legacyLast._time then canonicalLast else legacyLast)
    else if hasCanonical then
      canonicalLast
    else
      legacyLast

  return array.from(rows: [chosen])
}

readEccoTelemetryHistory = (bucket, canonicalMeasurement, legacyMeasurement, field, rangeStart, rangeStop=now(), windowEvery=5m) => {
  // One row per window that canonical actually covers, tagged as such.
  // group(columns: ["_window"]) then last() collapses any duplicate
  // points that land in the same window to a single representative
  // value per window, the same defensive "don't pick an arbitrary
  // duplicate" idiom already used elsewhere in this codebase (group()
  // before last()/first()).
  canonicalByWindow =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == canonicalMeasurement and r._field == field)
      |> map(fn: (r) => ({ r with _window: date.truncate(t: r._time, unit: windowEvery) }))
      |> group(columns: ["_window"])
      |> last()
      |> group()

  // The set of window keys canonical already covers, so legacy can be
  // excluded from exactly those windows and nowhere else - this is what
  // guarantees no window is ever double-counted, without depending on a
  // single global cutover time.
  canonicalWindowKeys = canonicalByWindow |> findColumn(fn: (key) => true, column: "_window")

  legacyFillIn =
    from(bucket: bucket)
      |> range(start: rangeStart, stop: rangeStop)
      |> filter(fn: (r) => r._measurement == legacyMeasurement and r._field == field)
      |> map(fn: (r) => ({ r with _window: date.truncate(t: r._time, unit: windowEvery) }))
      |> group(columns: ["_window"])
      |> last()
      |> group()
      |> filter(fn: (r) => not contains(value: r._window, set: canonicalWindowKeys))
      |> map(fn: (r) => ({ r with _ecco_source: "legacy" }))

  canonicalTagged =
    canonicalByWindow
      |> map(fn: (r) => ({ r with _ecco_source: "canonical" }))

  // Normalise _time to the window boundary before returning. Without
  // this, the winning row keeps its own original sample time, which can
  // differ between canonical and legacy even within the SAME window
  // (they are two independently-polled ~10s series, not synchronised to
  // the same instant) - Battery Outlook's load-profile learning buckets
  // history by date.hour(t: r._time)/date.minute(t: r._time) to build a
  // 5-minute time-of-day profile, so an unnormalised timestamp could
  // classify what is logically one 5-minute slot into two different
  // minute-of-day buckets depending on which source answered and
  // exactly when within the window it happened to sample. Normalising
  // makes the output's time-of-day classification depend only on the
  // window itself, never on source or exact sample instant, and removes
  // any dependency on ecco_5m's own exact timestamp alignment - which
  // this repository cannot verify, since no rollup task for it is
  // checked in here. The original sample time is preserved in
  // _ecco_original_time for diagnostics.
  return union(tables: [canonicalTagged, legacyFillIn])
    |> map(fn: (r) => ({ r with _ecco_original_time: r._time, _time: r._window }))
}
