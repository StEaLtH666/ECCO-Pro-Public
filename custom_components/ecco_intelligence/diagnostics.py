"""The diagnostics download: versions, the full self-test (PASS / INFO / WARN / FAIL), counters and the last cycle's
summary. Entity ids, the configuration hash, the location and the git sha are redacted (they are site values). The last
cycle's source notes are shown (A42, RT4-1 (b)): each is a contract key and a constant code (runtime/sources.public_notes,
SOURCE_NOTE_CODES), never an entity id, an attribute name, a state text or a site number, so a refused rate table's code
(TABLE_*) is visible in the download. The last cycle's signals are listed by contract name, and a PV forecast observation
by its day and position only (A45, RV9-3: runtime/sources.public_signals), never by the site file's source name."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

TO_REDACT = {"entities", "config_hash", "latitude", "longitude", "git_sha"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"loaded": False}
    return async_redact_data({"loaded": True, **coordinator.diagnostics()}, TO_REDACT)
