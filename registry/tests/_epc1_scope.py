"""epc1 (stage 2 of the two-master-card energy-control work: the read-only plan views in the Energy Actions card). Made on the export after
isp1. FROZEN edits (PEX): the card's README.md (a pub0 target) and its src/config.ts and src/ecco-energy-actions-card.ts (enrolled): the
`show_plan` / `plan` configuration, the plan section rendered under the two tiles, and the README's plan-views section. The card's
tsconfig.json was edited by the stage-2 commits; it is NOT frozen and NOT enrolled (enrolling it is an owner decision), so this entry
does not declare it and the working tree keeps it at its export content. ADDED: the plan sources and tests of the card, the plan-core
package and its tests (the card folder's added files are what the three folder pins skip). ZERO firmware, Home Assistant package,
deployment, registry, Intelligence or ecco_core byte; ZERO Modbus operation; no service call (the views display only).

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked (apply then revert reproduces both texts byte for byte), and
each reverter raises unless each of its edits is present exactly once. The post-export chain entry `epc1` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES; registry/tests/_pex.py) carries them; its fingerprint is sealed with _pex.sealed and must be sealed again if another
entry merges first.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'epc1'

ADDED_FILES = frozenset({
    'frontend/ecco-energy-actions-card/src/plan/adapter.ts',
    'frontend/ecco-energy-actions-card/src/plan/helpers.ts',
    'frontend/ecco-energy-actions-card/src/plan/present.ts',
    'frontend/ecco-energy-actions-card/src/plan/view.ts',
    'frontend/ecco-energy-actions-card/test/golden/flag-off-render.json',
    'frontend/ecco-energy-actions-card/test/golden/plan-on-render.json',
    'frontend/ecco-energy-actions-card/test/planAdapter.test.ts',
    'frontend/ecco-energy-actions-card/test/planOverrides.test.ts',
    'frontend/ecco-energy-actions-card/test/planView.test.ts',
    'frontend/ecco-energy-actions-card/test/support/capture-golden.ts',
    'frontend/ecco-energy-actions-card/test/support/fixtures.ts',
    'frontend/ecco-energy-actions-card/test/support/loadCard.ts',
    'frontend/ecco-energy-actions-card/test/support/overrideFixtures.ts',
    'frontend/ecco-energy-actions-card/test/support/planFixtures.ts',
    'frontend/ecco-energy-actions-card/test/support/planOnScenarios.ts',
    'frontend/ecco-energy-actions-card/test/support/scenarios.ts',
    'frontend/ecco-energy-actions-card/test/support/staticBans.ts',
    'frontend/ecco-energy-actions-card/test/testSourcesClean.test.ts',
    'frontend/ecco-plan-core/README.md',
    'frontend/ecco-plan-core/package.json',
    'frontend/ecco-plan-core/src/chargePlanner.ts',
    'frontend/ecco-plan-core/src/guards.ts',
    'frontend/ecco-plan-core/src/index.ts',
    'frontend/ecco-plan-core/src/overridePolicy.ts',
    'frontend/ecco-plan-core/src/overrides.ts',
    'frontend/ecco-plan-core/src/settings.ts',
    'frontend/ecco-plan-core/src/time.ts',
    'frontend/ecco-plan-core/src/tomorrow.ts',
    'frontend/ecco-plan-core/src/tou.ts',
    'frontend/ecco-plan-core/test/fixtures.ts',
    'frontend/ecco-plan-core/test/guards.test.ts',
    'frontend/ecco-plan-core/test/overridePolicy.test.ts',
    'frontend/ecco-plan-core/test/overrides-planner.test.ts',
    'frontend/ecco-plan-core/test/settings.test.ts',
    'frontend/ecco-plan-core/test/tomorrow.test.ts',
    'frontend/ecco-plan-core/test/tou.test.ts',
    'frontend/ecco-plan-core/tsconfig.json',
    'home-assistant/tests/test_ecco_plan_helper_proposal.py',
    'registry/tests/_epc1_scope.py',
})

import hashlib


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"{ID} scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"{ID} scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"{ID} scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) the card README ---------------------------------------------------------------------------
README_REL = 'frontend/ecco-energy-actions-card/README.md'
README_EDITS = (
    (_blk(r"""
    firmware's own mutual-exclusion preconditions apply unchanged.

"""),
     _blk(r"""
    firmware's own mutual-exclusion preconditions apply unchanged.

### Plan views (read only, default off)

`show_plan: true` adds a **Plan** section at the bottom of the card: a **Tomorrow's Plan** strip (expected import, export,
solar, charge finish, reserve, confidence, each with a Proposed / Armed / Executing / Applied and verified / Mismatch / Unknown
chip, plus a **Why?** detail and the planned settings), a **six-slot TOU timeline** (intended versus what the inverter reports,
mismatches and plans that do not fit six slots in plain words) and an honest SHADOW / advice-only line. Absent, `false` or any
value other than `true`: the card renders exactly as before (pinned by `test/planView.test.ts` against a golden captured
from the pre-plan source).

```yaml
show_plan: true
plan:                                   # all optional; anything missing is shown as unknown, never guessed
  entity_prefix: ecco_clock_dongle      # the six TOU slot entities (same prefix as the TOU Settings card)
  reserve: input_number.ecco_minimum_reserve_soc
  control_lock: input_boolean.example   # only an explicit "off" counts as unlocked; absent = export is not placed (fail-safe)
  advice:                               # defaults: the Intelligence contract's generic sensor.ecco_intel_* ids
    status: sensor.ecco_intel_status
```

The views **display only**: no button, no handler, no service call, no entity write (a test asserts `hass.callService` is
never called). Quick overrides appear as a read-only "none active" line. Figures come from the Intelligence advice entities
(import is Intelligence's planned overnight grid charge); a paused, stale or not-OK advice withholds every figure with its
reason. A setting reads "Applied and verified" only when a read-back equals it. The logic is the pure `frontend/ecco-plan-core`
package, bundled in (no runtime dependency): `src/plan/adapter.ts` (entities to plan inputs), `present.ts` (wording and
chips), `view.ts` (Lit templates).

""")),
    (_blk(r"""
Pure, DOM-free logic lives in four small modules, all unit tested without a
"""),
     _blk(r"""
Pure, DOM-free logic lives in small modules (plus the read-only plan views under `src/plan/`), all unit tested without a
""")),
)


def pre_epc1_readme(text: str) -> str:
    """frontend/ecco-energy-actions-card/README.md with exactly epc1's edits undone (a reverter of chain entry epc1, PEX): its text as of the entry before."""
    return _revert(text, README_EDITS, README_REL)


pre_epc1_readme.edits = README_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc1_readme(text: str) -> str:
    """Applies epc1's edits to frontend/ecco-energy-actions-card/README.md as of the entry before (the round trip)."""
    return _apply(text, README_EDITS, README_REL)


# ---- (PEX frozen edit) src/config.ts -----------------------------------------------------------------------------
CONFIG_REL = 'frontend/ecco-energy-actions-card/src/config.ts'
CONFIG_EDITS = (
    (_blk(r"""

export interface EccoEnergyActionsCardConfig {
"""),
     _blk(r"""

/**
 * Optional read-only plan views (stage 2 of the two-master-card energy-control UI). Used only when `show_plan: true`. Nothing here
 * is ever written: every id is read, never called. All ids are optional; anything missing is shown as unknown, never guessed.
 */
export interface PlanConfig {
  /** The dongle device slug the six TOU slot entities are named after (the TOU settings card's `entity_prefix`). */
  entity_prefix?: string;
  /** input_number - the backup reserve in percent (read only). */
  reserve?: string;
  /** Grid-loss lock state: only an explicit "off" counts as unlocked; absent or anything else is treated as locked (fail-safe). */
  control_lock?: string;
  /** Overrides for the Intelligence advice entity ids (default: the contract's generic ids). */
  advice?: Partial<Record<"status" | "charge_target" | "export_event" | "pv_tomorrow" | "fresh" | "paused", string>>;
}

export interface EccoEnergyActionsCardConfig {
""")),
    (_blk(r"""
  layout?: "side-by-side" | "tabbed";
}
"""),
     _blk(r"""
  layout?: "side-by-side" | "tabbed";
  /**
   * Default false. When exactly `true` the card also shows read-only plan views (Tomorrow's Plan and the six-slot TOU timeline).
   * Absent, false or any other value: the card renders exactly as before. The views display only; they make no service call.
   */
  show_plan?: boolean;
  plan?: PlanConfig;
}
""")),
)


def pre_epc1_config(text: str) -> str:
    """frontend/ecco-energy-actions-card/src/config.ts with exactly epc1's edits undone (a reverter of chain entry epc1, PEX): its text as of the entry before."""
    return _revert(text, CONFIG_EDITS, CONFIG_REL)


pre_epc1_config.edits = CONFIG_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc1_config(text: str) -> str:
    """Applies epc1's edits to frontend/ecco-energy-actions-card/src/config.ts as of the entry before (the round trip)."""
    return _apply(text, CONFIG_EDITS, CONFIG_REL)


# ---- (PEX frozen edit) src/ecco-energy-actions-card.ts -----------------------------------------------------------
SRC_REL = 'frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts'
SRC_EDITS = (
    (_blk(r"""
import { formatDurationMinutes, formatPercent, formatPower, toBoolean, toNumber } from "./utils/format";

"""),
     _blk(r"""
import { formatDurationMinutes, formatPercent, formatPower, toBoolean, toNumber } from "./utils/format";
import { planStyles, renderPlanSection } from "./plan/view.ts";

""")),
    (_blk(r"""
          ${this._renderDumpToGridTile()}
        </div>
      </ha-card>
"""),
     _blk(r"""
          ${this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
""")),
    (_blk(r"""
      </ha-card>
    `;
  }

  // ---------------------------------------------------------------------
  // `layout: tabbed` (OVW1) - presentation only. One track (Free Power or
  // Dump to Grid) is visible at a time, but BOTH tracks' display states are
"""),
     _blk(r"""
      </ha-card>
    `;
  }

  /**
   * Read-only plan views (Tomorrow's Plan, six-slot TOU timeline). `nothing` unless the config has `show_plan: true`; the views
   * display only and make no service call. See src/plan/.
   */
  private _renderPlan() {
    return renderPlanSection(this._config, this.hass?.states);
  }

  // ---------------------------------------------------------------------
  // `layout: tabbed` (OVW1) - presentation only. One track (Free Power or
  // Dump to Grid) is visible at a time, but BOTH tracks' display states are
""")),
    (_blk(r"""
          ${track === "free_power" ? this._renderFreePowerTile() : this._renderDumpToGridTile()}
        </div>
      </ha-card>
"""),
     _blk(r"""
          ${track === "free_power" ? this._renderFreePowerTile() : this._renderDumpToGridTile()}
        </div>${this._renderPlan()}
      </ha-card>
""")),
    (_blk(r"""
  static styles = css`
"""),
     _blk(r"""
  static styles = [planStyles, css`
""")),
    (_blk(r"""
    }
  `;
}
"""),
     _blk(r"""
    }
  `];
}
""")),
)


def pre_epc1_card(text: str) -> str:
    """frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts with exactly epc1's edits undone (a reverter of chain entry epc1, PEX): its text as of the entry before."""
    return _revert(text, SRC_EDITS, SRC_REL)


pre_epc1_card.edits = SRC_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_epc1_card(text: str) -> str:
    """Applies epc1's edits to frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts as of the entry before (the round trip)."""
    return _apply(text, SRC_EDITS, SRC_REL)


# The frozen files this entry edits, with their reverters (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    README_REL: pre_epc1_readme,
    CONFIG_REL: pre_epc1_config,
    SRC_REL: pre_epc1_card,
}
