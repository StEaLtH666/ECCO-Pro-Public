"""ECCO Intelligence (SHADOW): read-only advisory sensors for Home Assistant. It applies nothing.

Source only: install only from a kit built by tools/build_ha_integration.py (whose SHA256SUMS verifies). The kit carries the
engine as an import-rewritten _vendor/ copy, so nothing is added to Home Assistant's global import path.

No homeassistant import at module level (the runtime boundary suite checks it): this file imports in a plain interpreter.

The coordinator module, and through it most of the vendored engine (the modules it and its runtime package import; the
rest, the engine cycle's own closure, load in the start-up gates' executor job), is imported in Home Assistant's import
executor (hass.async_add_import_executor_job), never on the event loop: async_setup_entry only waits for it.

Every executor job the integration submits (that import, the start-up gates, the recorder read, the engine and the state
store) is held until the event loop has finished the step that submitted it (release_after_step / released_call): the job
waits for a flag the loop sets in its next handle, polling it with short sleeps for at most SUBMIT_RELEASE_CAP_S. A job
that starts at once competes for the GIL with the rest of the submitting step (the futures and timers asyncio creates
after the submit), and in an asyncio debug session every one of those reads its stack's source files, which hands the
GIL to the job each time; held, the step ends before the job runs. Every job also ends with a cool-down: once its target
has returned (or raised) it sleeps SUBMIT_COOLDOWN_S before it completes, so the loop-side completion and the step that
follows start in a fresh CPU-quota period of a CPU-limited container instead of the throttled tail of the job's own.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from .const import (DOMAIN, INTEGRATION_VERSION, MODE, PLATFORMS, SUBMIT_COOLDOWN_S, SUBMIT_RELEASE_CAP_S,
                    SUBMIT_RELEASE_POLL_S)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

__all__ = ["DOMAIN", "INTEGRATION_VERSION", "MODE", "PLATFORMS", "async_setup_entry", "async_unload_entry"]


def _release(flag: list[bool]) -> None:
    flag[0] = True


def release_after_step(hass: "HomeAssistant") -> list[bool]:
    """Event loop side, just before an executor job is submitted: a flag the event loop sets in its next handle, so after
    the step that submits the job has ended."""
    flag = [False]
    hass.loop.call_soon(_release, flag)
    return flag


def released_call(flag: list[bool], target: Callable[..., Any], *args: Any) -> Any:
    """Executor side: run target(*args) once the event loop has set `flag` (release_after_step), or after
    SUBMIT_RELEASE_CAP_S at the latest, so a job never waits for a loop that has stopped. Then, whether the target
    returned or raised, sleep SUBMIT_COOLDOWN_S (the cool-down) before the job completes."""
    end = time.monotonic() + SUBMIT_RELEASE_CAP_S
    while not flag[0] and time.monotonic() < end:
        time.sleep(SUBMIT_RELEASE_POLL_S)
    try:
        return target(*args)
    finally:
        time.sleep(SUBMIT_COOLDOWN_S)


def _import_coordinator() -> Any:
    """Executor side (the import executor): import the coordinator module, and through it most of the vendored engine."""
    from . import coordinator
    return coordinator


async def async_setup_entry(hass: "HomeAssistant", entry: Any) -> bool:
    """Start-up gates, then the sensor and binary_sensor platforms, then the coordinator's timer. A mode other than SHADOW
    refuses setup; any other failed gate publishes SELF_TEST_FAILED and computes nothing."""
    coordinator_module = await hass.async_add_import_executor_job(released_call, release_after_step(hass),
                                                                  _import_coordinator)
    coordinator = await coordinator_module.async_create_coordinator(hass, entry)
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
