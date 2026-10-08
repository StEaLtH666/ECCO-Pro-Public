"""Render the analysis dict as a Markdown report and CSV tables; write every output file."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .timeutil import fmt_duration

ICON = {"PASS": "PASS", "WARNING": "WARNING", "FAIL": "FAIL", "INSUFFICIENT_EVIDENCE": "INSUFFICIENT EVIDENCE"}


def _v(x, nd=1):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}" if not x.is_integer() else str(int(x))
    return str(x)


def _t(st):
    return st["local"] if st else "n/a"


def _esc(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _table(head, rows) -> list:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_esc(_v(c)) for c in r) + " |")
    return out


def markdown(rep: dict) -> str:
    L = []
    w = rep["window"]
    o = rep["overall"]
    L.append("# FB-D1 seven-day soak - evidence analysis")
    L.append("")
    L.append(f"**Overall verdict: {ICON[o['verdict']]}**" + (f" (deciding: {', '.join(o['deciding_criteria'])})"
                                                            if o["deciding_criteria"] else ""))
    L.append("")
    L.append(f"- Soak window: {_t(w['start'])} to {_t(w['end'])} ({w['days']} days; UTC {w['start']['utc']} to {w['end']['utc']})")
    L.append(f"- Analysis as of: {_t(w['as_of']) if w['as_of'] else 'not stated'}; window complete: {'yes' if w['complete'] else 'NO'}")
    L.append(f"- Analyser {rep['analyser_version']}, schema `{rep['schema']}`. Rule: {o['rule']}.")
    L.append("- Inputs:")
    for i in rep["evidence"]["inputs"]:
        L.append(f"  - `{Path(i['path']).name}` ({i['format']}, sha256 `{i['sha256'][:16]}...`): {i['accepted']} accepted / "
                 f"{i['rejected']} rejected of {i['rows']} rows, {_t(i['first'])} to {_t(i['last'])}")
    L.append("")
    L.append("## 1. Acceptance summary")
    L.append("")
    L += _table(["Criterion", "Verdict", "Basis", "Confidence", "Required", "Summary"],
                [[c["id"] + " " + c["title"], ICON[c["verdict"]], c["basis"], c["confidence"], "yes" if c["required"] else "no",
                  c["summary"]] for c in rep["criteria"]])
    L.append("")
    for c in rep["criteria"]:
        if c["reasons"]:
            L.append(f"- **{c['id']}** ({ICON[c['verdict']]}): " + "; ".join(c["reasons"]))
    L.append("")
    L.append("## 2. Daily metrics (soak days of 24 h from the start)")
    L.append("")
    L += _table(["Day", "From (local)", "Cover %", "Restarts", "Corr.", "Verified", "Failed", "Aborts", "Stalls", "Night bg",
                 "Stale cand.", "B10 MATCH % obs", "NOT MATCH s", "BLOCKED s", "UNKNOWN s", "No-evid. s", "Tel. fail", "Cfg fail",
                 "Blk B gaps"],
                [[d["day"], d["from"]["local"], d["coverage_pct"], d["restarts"], d["corrections"], d["verified_counter"],
                  d["failed_counter"], d["aborts"], d["stalls_counter"], d["night_background"], d["stale_candidates"],
                  d["match_pct_of_observed"], d["not_match_s"], d["blocked_s"], d["unknown_s"], d["no_evidence_s"],
                  d["telemetry_failures"], d["configuration_failures"], d["block_b_gaps"]] for d in rep["daily"]])
    L.append("")
    a = rep["areas"]
    r = a["rtc"]
    L.append("## 3. RTC corrections")
    L.append("")
    cnt = r["counters"]
    L.append(f"- Counters in the window: verified +{_v(cnt['verified']['delta'])}, failed +{_v(cnt['failed']['delta'])}, RTC write "
             f"attempts +{_v(cnt['write_attempts']['delta'])}, stalls +{_v(cnt['stalls']['delta'])} "
             "(n/a = counter not in the evidence, never zero).")
    L.append(f"- Episodes ({r['episode_basis']}): {r['episodes_in_window']} in window - verified {r['verified']}, failed "
             f"{r['failed']}, aborted {r['aborted']}, manual {r['manual']}, incomplete {r['incomplete']}; by reason: "
             + (", ".join(f"{k} {n}" for k, n in sorted(r["by_reason"].items())) or "none"))
    nd = r["night_vs_daylight"]
    L.append(f"- Night vs daylight ({nd['basis']}): daylight {nd['daylight']}, night {nd['night']} (night background "
             f"{nd['night_background']}).")
    L.append(f"- Duration queue->verdict: median {_v(r['duration_s']['median'])} s, max {_v(r['duration_s']['max'])} s. "
             f"RTC lock: max {_v(r['lock']['max_s'])} s over {r['lock']['intervals']} lock interval(s); "
             f"lock max-since-boot sensor {_v(r['lock']['max_since_boot_sensor_s'])} s.")
    rd = r["reads"]
    L.append(f"- RTC reads: {rd['total']} in window ({rd['from_log']} log, {rd['from_ha']} Clock Difference rows, "
             f"{rd['inferred_from_inverter_time']} recovered from Inverter Time); max |error| {_v(rd['max_abs_error_s'])} s.")
    L.append("- Corrections by local hour: " + " ".join(f"{h:02d}:{n}" for h, n in enumerate(r["per_local_hour"]) if n) or "none")
    pw = r["precision_windows"]
    L.append(f"- TOU precision windows in the soak: {pw.get('windows', 0)}; with a read {pw.get('with_read', 0)}; precision "
             f"corrections {pw.get('precision_corrections', 0)}; within threshold {pw.get('within_threshold', 0)}"
             + (f" ({pw['note']})" if pw.get("note") else ""))
    L.append("")
    if r["episodes"]:
        L += _table(["#", "Queued (local)", "Reason", "Error s", "Prior/queue reads", "Trend s", "Stall 1st", "Class", "Outcome",
                     "Residual s", "Lock s", "Policy", "Day/night"],
                    [[e["id"], _t(e["start"]) if e["start"] else (_t(e["end"]) + " (end)"), e["reason"] or e["kind"],
                      e["error_s"],
                      (f"{e['analysis']['prior_read']['error_s']}/{e['analysis']['queue_read']['error_s']}"
                       if e["analysis"].get("prior_read") and e["analysis"].get("queue_read") else "n/a"),
                      e["analysis"].get("trend_error_s"), e["analysis"].get("stall_on_prior_read"),
                      e["analysis"].get("classification", "n/a") + (" NO-OP?" if e["analysis"].get("suspected_noop") else ""),
                      e["outcome"], e["residual_s"], e["lock_s"], e["analysis"].get("policy", {}).get("result", "n/a"),
                      {True: "day", False: "night"}.get(e["analysis"].get("daylight"), "n/a")] for e in r["episodes"][:80]])
        if len(r["episodes"]) > 80:
            L.append(f"\n({len(r['episodes']) - 80} more episodes in the JSON.)")
        L.append("")
    L.append("## 4. RTC stall detection")
    L.append("")
    st = r["stalls"]
    s = st["sources"]
    L.append(f"- Stall count: counter {_v(s['counter'])}, log lines {_v(s['log_lines'])}, binary on-rows {_v(s['binary_on_rows'])}, "
             f"stall-flagged reads {s['stall_reads']}; repeated (frozen) reads {st['repeated_frozen_reads']}.")
    if st["events"]:
        L.append("")
        L += _table(["Stall read (local)", "Before s", "Read s", "After s", "Detector", "Computed", "Inv/NTP adv s", "Then bg corr."],
                    [[_t(x["time"]), x["before_s"], x["error_s"], x["after_s"], x["detector"], x["computed"],
                      f"{_v(x['inverter_advance_s'])}/{_v(x['ntp_advance_s'])}",
                      x["followed_by_background_correction"]] for x in st["events"][:60]])
    L.append("")
    L.append("## 5. B10 Live Match")
    L.append("")
    b = a["b10"]
    ts = b["time_s"]
    L += _table(["Category", "Time", "% of window"],
                [[k, fmt_duration(v), round(100 * v / max(1.0, sum(ts.values())), 3)] for k, v in ts.items()])
    L.append("")
    L.append(f"- MATCH {_v(b['match_pct_observed'], 3)} % of observed time ({_v(b['match_pct_window'], 3)} % of the window); "
             f"B10 coverage {_v(b['coverage_pct'], 3)} %; {b['interruptions']} interruption(s), causes "
             f"{b['interruption_causes'] or 'none'}.")
    li = b["longest_interruption"]
    if li:
        L.append(f"- Longest interruption: {fmt_duration(li['seconds'])} from {_t(li['from'])} ({', '.join(li['modes'])}; "
                 f"{', '.join(li['causes'])}); longest with evidence {fmt_duration(b['longest_evidenced_interruption_s'])}.")
    rec = [x["match_after_s"] for x in b["recovery_after_corrections"] if x["match_after_s"] is not None]
    if b["recovery_after_corrections"]:
        L.append(f"- Recovery after {len(b['recovery_after_corrections'])} correction(s): release->MATCH median "
                 f"{_v(sorted(rec)[len(rec) // 2] if rec else None)} s, max {_v(max(rec) if rec else None)} s.")
    if b["lock_overlaps"]:
        L.append(f"- **MATCH while the RTC lock was held: {len(b['lock_overlaps'])} interval(s).**")
    L.append("")
    L.append("## 6. Modbus and polling")
    L.append("")
    p = a["polling"]
    L.append(f"- Telemetry read failures: {_v(p['telemetry_failures']['delta']) if p['telemetry_failures']['available'] else 'UNAVAILABLE'}; "
             f"configuration read failures: {_v(p['configuration_failures']['delta']) if p['configuration_failures']['available'] else 'UNAVAILABLE'}.")
    L.append(f"- Configuration Online off: {len(p['configuration_offline'])}x; Telemetry Online off: {len(p['telemetry_offline'])}x.")
    bb = p["block_b"]
    L.append(f"- Block B successes {bb['successes']}; gaps > threshold {len([g for g in bb['gaps'] if not g['unverifiable']])} "
             f"(+{len([g for g in bb['gaps'] if g['unverifiable']])} unverifiable); early (catch-up candidate) polls "
             f"{len(bb['early_polls'])}, {sum(1 for x in bb['early_polls'] if x['after_rtc_correction'])} after an RTC correction.")
    L.append(f"- Telemetry stamps {p['telemetry']['successes']}, gaps {p['telemetry']['gaps']} (longest {_v(p['telemetry']['longest_gap_s'])} s).")
    L.append(f"- Firmware log counts: {p['log_counts'] if p['log_counts'] is not None else 'no log supplied'}.")
    L.append("")
    L.append("## 7. Continuity and supervision")
    L.append("")
    c = a["continuity"]
    L.append(f"- Continuity proven: {'yes' if c['continuity_proven'] else 'NO'}; witnesses: "
             + ("; ".join(c["continuity_witnesses"]) or "none"))
    L.append(f"- Soak boot evidence: {len(c['soak_boot'])}; unexpected restarts: {len(c['restarts'])}.")
    for x in c["restarts"]:
        L.append(f"  - {_t(x['time'])}: {', '.join(x['signals'])} - {'; '.join(x['details'][:3])}")
    L.append(f"- Evidence coverage {_v(c['coverage_pct'], 3)} %; {len(c['gaps'])} gap(s); {len(c['unavailable'])} device-unavailable period(s); "
             f"median dongle-vs-HA clock offset {_v(c['clock']['median_ntp_offset_s'])} s, discontinuities {len(c['clock']['discontinuities'])}.")
    sf = a["safety"]
    if sf["supervision_time_s"]:
        L.append("- Supervision state time: " + ", ".join(f"{k} {fmt_duration(v)}" for k, v in sorted(sf["supervision_time_s"].items())))
    L.append("")
    L.append("## 8. Safety and write authority")
    L.append("")
    cs = sf["counters"]
    L.append("- Write counters in the window: " + ", ".join(
        f"{k} {'+' + _v(v['delta']) if v['available'] else 'UNAVAILABLE'}" for k, v in cs.items()
        if k.endswith(("attempts", "failures", "successes"))))
    L.append(f"- Lease intervals: {len(sf['lease_intervals'])}; corrections inside a lease: {sf['corrections_in_lease'] or 'none'}; "
             f"RTC/manual write-path overlaps: {sf['rtc_manual_overlaps']}; Modbus write lock max {_v(sf['write_lock_max_s'])} s.")
    L.append(f"- Protected control state / setting changes: {len(sf['protected_changes'])}.")
    L.append("")
    L.append("## 9. Suspicious events")
    L.append("")
    ev = rep["suspicious_events"]
    if not ev:
        L.append("None.")
    for e in ev[:200]:
        L.append(f"- {_t(e['time']) if e['time'] else '(window)'} **{e['severity']}** `{e['code']}` ({e['basis']}): {e['summary']}"
                 + (f" [refs: {', '.join(e['refs'][:3])}]" if e["refs"] else ""))
    if len(ev) > 200:
        L.append(f"- ... {len(ev) - 200} more in the JSON.")
    L.append("")
    L.append("## 10. FB-D1 A3 stall-veto: evidence and recommendations")
    L.append("")
    a3 = rep["a3_stall_veto"]
    L.append(f"- Background corrections {a3['background_corrections']}: stale-read candidates {a3['candidates']}, drift-consistent "
             f"{a3['drift_consistent']}.")
    dd = a3["consecutive_read_delta_s"]
    L.append(f"- |difference| between consecutive regular reads: daylight n={dd['daylight']['n']} p50/p90/p99/max "
             f"{_v(dd['daylight']['p50'])}/{_v(dd['daylight']['p90'])}/{_v(dd['daylight']['p99'])}/{_v(dd['daylight']['max'])} s; "
             f"night n={dd['night']['n']} {_v(dd['night']['p50'])}/{_v(dd['night']['p90'])}/{_v(dd['night']['p99'])}/"
             f"{_v(dd['night']['max'])} s.")
    L.append("")
    L += _table(["Variant", "Rule", "Holds candidates", "Holds drift-consistent"],
                [[x["name"], x["rule"], f"{x['would_hold_candidates']}/{a3['candidates']}",
                  f"{x['would_hold_drift_consistent']}/{a3['drift_consistent']}"] for x in a3["variants"]])
    L.append("")
    for x in a3["recommendations"]:
        L.append(f"- {x}")
    L.append("")
    L.append("## 11. Evidence coverage and uncertainty")
    L.append("")
    L += _table(["Diagnostic", "Present", "Rows in window", "No-value % of window", "Invalid rows"],
                [[x["firmware_name"], "yes" if x["present"] else "**no**", x.get("rows_in_window"), x.get("no_value_pct_of_window"),
                  x.get("invalid_rows")] for x in a["coverage"]])
    L.append("")
    d = rep["evidence"]
    L.append(f"- Import diagnostics: {d['diagnostics_total']} ("
             + ", ".join(f"{k} {n}" for k, n in sorted(_codes(d['diagnostics']).items())) + ")" if d["diagnostics_total"] else
             "- Import diagnostics: none")
    if d["unknown_entities"]:
        L.append(f"- Rows for {len(d['unknown_entities'])} entity id(s) outside the FB-D1 catalogue were ignored.")
    L.append("- Limitations:")
    for x in rep["limitations"]:
        L.append(f"  - {x}")
    L.append("")
    L.append("## 12. Outstanding live-proof requirements")
    L.append("")
    for i, x in enumerate(rep["outstanding_live_proof"], 1):
        L.append(f"{i}. {x['requirement']} - _{x['why']}_")
    L.append("")
    L.append("## 13. Decision thresholds")
    L.append("")
    L.append("```json")
    L.append(json.dumps(rep["rules"], indent=1))
    L.append("```")
    L.append("")
    return "\n".join(L)


def _codes(diags) -> dict:
    out = {}
    for x in diags:
        out[x["code"]] = out.get(x["code"], 0) + 1
    return out


def daily_csv(rep: dict) -> str:
    buf = io.StringIO()
    rows = rep["daily"]
    if not rows:
        return ""
    keys = [k for k in rows[0].keys() if k not in ("from", "to")]
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["day", "from_utc", "from_local", "to_utc", "to_local"] + [k for k in keys if k != "day"])
    for r in rows:
        w.writerow([r["day"], r["from"]["utc"], r["from"]["local"], r["to"]["utc"], r["to"]["local"]] +
                   ["" if r[k] is None else r[k] for k in keys if k != "day"])
    return buf.getvalue()


def events_csv(rep: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["time_utc", "time_local", "severity", "area", "code", "basis", "summary", "refs"])
    for e in rep["suspicious_events"]:
        t = e["time"] or {"utc": "", "local": ""}
        w.writerow([t["utc"], t["local"], e["severity"], e["area"], e["code"], e["basis"], e["summary"], " ".join(e["refs"])])
    return buf.getvalue()


def write_all(rep: dict, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "json": out / "fbd1_soak_analysis.json",
        "markdown": out / "fbd1_soak_report.md",
        "daily_csv": out / "fbd1_soak_daily.csv",
        "events_csv": out / "fbd1_soak_events.csv",
    }
    files["json"].write_text(json.dumps(rep, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8", newline="\n")
    files["markdown"].write_text(markdown(rep), encoding="utf-8", newline="\n")
    files["daily_csv"].write_text(daily_csv(rep), encoding="utf-8", newline="\n")
    files["events_csv"].write_text(events_csv(rep), encoding="utf-8", newline="\n")
    return {k: str(v) for k, v in files.items()}
