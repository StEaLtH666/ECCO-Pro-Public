"""epc3 (the Gentle Smart Charging controller MODEL: read-only, offline, nothing installed, nothing actuated). ADDED files only: the pure
controller model in the plan-core package (frontend/ecco-plan-core/src/gentleController.ts), its closed-loop battery simulator
(test/support/batterySim.ts) and its suite (test/gentleController.test.ts). The plan-core files the entry also touches (src/index.ts, which
exports the model, and README.md, which documents it) are epc1 ADDED files, not frozen and not chain-pinned, so they need no reverter.
ZERO frozen or chain-pinned edit, ZERO firmware, Home Assistant package, deployment, registry data, Intelligence, ecco_core or VERSION.yaml
byte, ZERO Modbus operation, no service call and no write of any kind: the model returns data labelled "model, not a command" and reports
actuationSupported: false (today's firmware fixes the Free Power rate at START).

Same technique as the earlier post-export scope modules: the entry `epc3` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES;
registry/tests/_pex.py) carries the declaration; its fingerprint is sealed with _pex.sealed and must be sealed again if another entry
merges first.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

ID = 'epc3'

ADDED_FILES = frozenset({
    'frontend/ecco-plan-core/src/gentleController.ts',
    'frontend/ecco-plan-core/test/gentleController.test.ts',
    'frontend/ecco-plan-core/test/support/batterySim.ts',
    'registry/tests/_epc3_scope.py',
})
