"""Print a synthetic example report as JSON (offline; reads and writes nothing else).

    python -m intelligence.prototypes.s1_advice --example blocked     # every decision OPEN: items withheld
    python -m intelligence.prototypes.s1_advice --example shadow      # SYNTHETIC_TEST decisions: SHADOW advice
    python -m intelligence.prototypes.s1_advice --example dst-open    # a clock-change period with D9 OPEN
    python -m intelligence.prototypes.s1_advice --example dst-normalised   # the same, D9 a SYNTHETIC_TEST record

Decisions count only with provenance SYNTHETIC_TEST: the command line passes accept_provenance={SYNTHETIC_TEST}
explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys

from ...site_decisions import NORMALISE_TO_NOMINAL, SCALE_UP_ONLY, DSTPolicy, Provenance
from . import fixtures
from .harness import run_harness

ACCEPT_PROVENANCE = frozenset({Provenance.SYNTHETIC_TEST})

EXAMPLES = {
    "blocked": fixtures.example_blocked,
    "shadow": fixtures.example_shadow,
    "dst-open": lambda: fixtures.example_dst(True, None),
    "dst-normalised": lambda: fixtures.example_dst(True, DSTPolicy(NORMALISE_TO_NOMINAL, SCALE_UP_ONLY)),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="S1 offline advice harness (PROTOTYPE, SHADOW): synthetic examples only")
    ap.add_argument("--example", choices=sorted(EXAMPLES), required=True)
    ap.add_argument("--summary", action="store_true", help="print one line per item instead of the full JSON")
    a = ap.parse_args(argv)
    rep = run_harness(EXAMPLES[a.example](), accept_provenance=ACCEPT_PROVENANCE)
    if a.summary:
        print(rep.notice)
        for it in rep.items:
            why = ", ".join(b.code for b in it.withheld_because)
            print(f"{it.kind:18} {it.status:17} {('withheld: ' + why) if why else ''}")
    else:
        print(json.dumps(rep.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
