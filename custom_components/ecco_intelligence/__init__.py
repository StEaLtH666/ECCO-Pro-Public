"""ECCO Intelligence (SHADOW): read-only advisory sensors for Home Assistant. It applies nothing.

Source only: install only from a kit built by tools/build_ha_integration.py (whose SHA256SUMS verifies). The kit carries the
engine as an import-rewritten _vendor/ copy, so nothing is added to Home Assistant's global import path.

No homeassistant import at module level (the runtime boundary suite checks it): this file imports in a plain interpreter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN, INTEGRATION_VERSION, MODE, PLATFORMS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

__all__ = ["DOMAIN", "INTEGRATION_VERSION", "MODE", "PLATFORMS", "async_setup_entry", "async_unload_entry"]


async def async_setup_entry(hass: "HomeAssistant", entry: Any) -> bool:
    """Start-up gates, then the sensor and binary_sensor platforms, then the coordinator's timer. A mode other than SHADOW
    refuses setup; any other failed gate publishes SELF_TEST_FAILED and computes nothing."""
    from .coordinator import async_create_coordinator

    coordinator = await async_create_coordinator(hass, entry)
    entry.runtime_data = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, list(PLATFORMS))
    except Exception:
        await coordinator.async_stop()
        raise
    coordinator.verify_entities()          # a contract entity Home Assistant did not add -> SELF_TEST_FAILED
    coordinator.async_start()
    return True


async def async_unload_entry(hass: "HomeAssistant", entry: Any) -> bool:
    """Stop computing first, then unload the platforms. Nothing is written on unload."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None:
        await coordinator.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, list(PLATFORMS))
