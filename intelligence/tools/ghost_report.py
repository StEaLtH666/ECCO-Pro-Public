#!/usr/bin/env python3
"""Read-only report: Intelligence versus reality (the ghost battery), from a JSON export. No network, writes nothing.

    python intelligence/tools/ghost_report.py export.json [--json] [--wear-p-per-kwh 1.5] [--outside-advice self_use]
                                                          [--include-fallback] [--strict]

THE GHOST IS A SIMULATION; Intelligence controlled nothing (see intelligence/ghost.py). Exit code 0 on a report, 2 on bad input.

Export format "ecco-intel-ghost-export/1" (one JSON object; energies in kWh per slot, prices in pence per kWh, times aware ISO):
    {
      "format": "ecco-intel-ghost-export/1",
      "site": {"tz": "<IANA zone>", "battery_capacity_kwh": 0.0, "round_trip_efficiency": 0.9, "user_reserve_soc_pct": 40,
               "technical_min_soc_pct": 10, "max_soc_pct": 100, "max_grid_charge_kw": 5.0},   # any SiteConfig fields; unknown = error
      "step_minutes": 30,                    # every slot has this length
      "soc0_pct": 55.0,                      # SOC at the start of the first slot
      "export_limit_kw": null,               # null = no export limit
      "wear_p_per_kwh": null,                # null = unknown (the report then says "before wear"); --wear-p-per-kwh overrides
      "opening_cost_p_per_kwh": null,        # price of the energy already stored at the start; null = unknown = 0, flagged
      "limits": {"max_charge_kw": null, "max_discharge_kw": null},   # null = the config's max_grid_charge_kw (stated)
      "slots": [ {"t": "<slot start>", "pv": 0.0, "load": 0.0, "import": 0.0, "export": 0.0, "charge": 0.0, "discharge": 0.0,
                  "import_p": 0.0, "export_p": 0.0, "export_ok": true, "curtailed": 0.0, "soc_pct": 55.0}, ... ],
          # "import"/"export" may both be omitted (derived from the balance); "soc_pct" (SOC at slot end), "curtailed" and
          # "export_ok" are optional (SOC is then reconstructed from the flows; export_ok defaults to true)
      "advice": [ {"kind": "charge_target" | "dump_to_grid", "status": "OK" | "INSUFFICIENT_DATA" | "BLOCKED",
                   "issued_at": "...", "window_start": "...", "window_end": "...", "target_soc_pct": 0.0,
                   "export_kwh": null, "export_kw": null, "effective_reserve_pct": null, "conservative_fallback": false,
                   "dump_advisable": true, "advice_id": "..."} ],     # the AdviceRecord fields (intelligence/ghost.py)
      "outside_advice": "follow_actual", "include_fallback": false, "ha_reserve_pct": null, "strict": false     # optional
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence.ghost import parse_export, render_text, run_ghost  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Intelligence versus reality (ghost battery): read-only report")
    ap.add_argument("export", help="JSON export (format in this module's docstring)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--wear-p-per-kwh", type=float, help="battery wear price per kWh of throughput (overrides the export)")
    ap.add_argument("--outside-advice", choices=("follow_actual", "self_use"))
    ap.add_argument("--strict", action="store_true", help="switch off the constraint release (the ghost repeats the real flows strictly)")
    ap.add_argument("--include-fallback", action="store_true", help="also follow INSUFFICIENT_DATA fallback targets")
    a = ap.parse_args(argv)
    try:
        obj = json.loads(Path(a.export).read_text(encoding="utf-8"))
        p = parse_export(obj)
        opts = dict(p["options"])
        if a.outside_advice:
            opts["outside_advice"] = a.outside_advice
        if a.strict:
            opts["strict"] = True
        if a.include_fallback:
            opts["include_fallback"] = True
        wear = a.wear_p_per_kwh if a.wear_p_per_kwh is not None else p["wear_p_per_kwh"]
        rep = run_ghost(p["period"], p["advice"], p["cfg"], limits=p["limits"], wear_p_per_kwh=wear, **opts)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ghost_report: bad input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2, sort_keys=True) if a.json else render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
