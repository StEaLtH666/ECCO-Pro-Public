"""The diagnostics download: versions, the full self-test (PASS / INFO / WARN / FAIL), counters and the last cycle's
summary. Entity ids, the configuration hash, the location and the git sha are redacted (they are site values). The last
cycle's source notes are shown (A42, RT4-1 (b)): each is a contract key and a constant code (runtime/sources.public_notes,
SOURCE_NOTE_CODES), never an entity id, an attribute name, a state text or a site number, so a refused rate table's code
(TABLE_*) is visible in the download. The last cycle's signals are listed by contract name, and a PV forecast observation
by its day and position only (A45, RV9-3: runtime/sources.public_signals), never by the site file's source name.

The `ghost` block (diagnostics only; no entity, no contract): the existing schedule against Intelligence's advice, a read-only
SIMULATION computed lazily at the download (runtime/ghost_link.py, intelligence/ghost_compare.py). It carries dates, numbers and
constant codes only, never an entity id, a coordinate, a secret or a sensor text. Its numbers ARE site-derived behaviour and money
figures (daily pence, SOC, kWh, throughput, the reserve percentage, dates and timestamps with an offset), and TO_REDACT does not
remove them: review a download before sharing it. Any failure gives a small block with a status and a constant reason, and the rest
of the download is unchanged.

The `advice_incidents` block (the coordinator's own, in memory) lists the incidents of the advice log's write, and its `stored` member
(read-only from the store's advice_incident table, in the executor, with a short time budget) the ones that survived a restart:
counts, times and exception class names only, never a message. A failure of the stored read is a small block with a status and
the class name. No top-level key is added to the download."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

TO_REDACT = {"entities", "config_hash", "latitude", "longitude", "git_sha"}


def _ghost_unavailable(reason: str) -> dict:
    """The small UNAVAILABLE block. The Ghost code is imported here, lazily (an import-time fault of it must only affect the download,
    never the integration's setup); if even that import fails, the same block is built by hand (the schema and the flags of
    intelligence.ghost_compare.small_block, no banner)."""
    try:
        from .runtime import ghost_link
        return ghost_link.unavailable(reason)
    except Exception:  # noqa: BLE001 - the Ghost code cannot be imported: a hand-built block, the rest of the download stands
        return {"schema": "ecco-intel-ghost-diagnostics/1", "simulated": True, "read_only": True,
                "intelligence_controlled_nothing": True, "status": "UNAVAILABLE", "reason": reason, "money_available": False}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"loaded": False}
    data = {"loaded": True, **coordinator.diagnostics()}
    try:                                    # the Ghost block (diagnostics-only, read-only): never allowed to fail the download
        data["ghost"] = await coordinator.async_ghost_diagnostics()
    except Exception:  # noqa: BLE001 - a failure of the Ghost is a small block, the rest of the download stands
        data["ghost"] = _ghost_unavailable("OTHER")
    try:                                    # the incidents the store holds (read-only, bounded): never allowed to fail the download
        stored = await coordinator.async_stored_advice_incidents()
    except Exception as exc:  # noqa: BLE001 - only the class name is kept
        stored = {"status": "ERROR", "error_type": type(exc).__name__, "incidents": []}
    if isinstance(data.get("advice_incidents"), dict):          # nested: the download's top-level keys stay the coordinator's own
        data["advice_incidents"] = {**data["advice_incidents"], "stored": stored}
    return async_redact_data(data, TO_REDACT)
