"""Intelligence S1 offline advice harness: a PROTOTYPE, SHADOW-only, applies nothing.

Explicit synthetic / offline records in, a typed report of the existing V1.1 advisors (and a V1 summary) out. No runner, no
Home Assistant, no statistics export, no network, no schedule and no control path. The Intelligence decisions D1-D9
(I-D1..I-D9, intelligence/site_decisions.py) stay with the owner: an OPEN decision withholds the advice that depends on it.
See docs/intelligence/INTELLIGENCE_S1_OFFLINE_ADVICE_PROTOTYPE.md.
"""

from .harness import (GATES, NOTICE, PROTOTYPE_VERSION, S1_ACCEPT_PROVENANCE, Item, Report, learn_period,  # noqa: F401
                      run_harness)
from .scenario import (DECISION_IDS, OPEN, RECORDED, SYNTHETIC_TEST, DecisionRecord, EventDecl, MockHour,  # noqa: F401
                       Observation, PowerLimits, ReserveContext, Scenario, TariffDecl)
