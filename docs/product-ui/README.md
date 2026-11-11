# Energy Plan UI (design, phase 1)

**Status: OFFLINE DESIGN ONLY.** Nothing in this folder is implemented, installed or authorised. It changes no firmware, no
Home Assistant package and no card.

| File | What it is |
|---|---|
| [FEASIBILITY_MATRIX.md](FEASIBILITY_MATRIX.md) | what works today, what needs new protected Home Assistant scripting, and what needs firmware plus live hardware evidence, for each requested capability; every claim cites the source |
| [UX_CONCEPT.md](UX_CONCEPT.md) | the two master cards (Charge Battery, Export to Grid), the canonical plan, who owns each setting, the compiler and single-writer rules, reconciliation, and the acceptance tests |
| [ROADMAP.md](ROADMAP.md) | the staged order of work, with gates and no dates |
| [mock/index.html](mock/index.html) | an interactive offline mock (static HTML and JavaScript, fictional data, no network access): Home, Controls, Intelligence and Advanced |
| [mock/test/plan-model.test.mjs](mock/test/plan-model.test.mjs) | Node checks for the mock's plan model and for the page having no network or Home Assistant path |

## Open the mock

Open `mock/index.html` in a browser (a file URL is fine). Append `#controls`, `#intel` or `#advanced` to open another view.
Widgets are tagged **Works today** (an existing feature, fictional values), **Proposal** (not a working feature),
**Derived** (read-only view) or **Simulation** (a fake in-page backend for the test cases).

## Run the checks

```bash
node --test docs/product-ui/mock/test/plan-model.test.mjs
```

The same twenty-four cross-card checks run in the page under **Advanced -> Cross-card checks**.
