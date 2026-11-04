"""The SHADOW freshness binary sensor: on only while the published result is within its validity (the contract's
`fresh` payload). Read-only display; no services, no RestoreEntity. Like the sensors it keeps the contract's
UNRECORDED_ATTRIBUTES and the timestamp-only attributes out of the recorder (A17; the published attributes are unchanged)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant

from intelligence.advisory_contract import UNRECORDED_ATTRIBUTES

from .const import TIMESTAMP_ONLY_ATTRIBUTES
from .entity_base import EccoIntelEntity

RUNTIME_UNRECORDED_ATTRIBUTES = frozenset(UNRECORDED_ATTRIBUTES | TIMESTAMP_ONLY_ATTRIBUTES)


async def async_setup_entry(hass: HomeAssistant, entry: Any, async_add_entities: Any) -> None:
    async_add_entities([EccoIntelFreshBinarySensor(entry.runtime_data)])


class EccoIntelFreshBinarySensor(EccoIntelEntity, BinarySensorEntity):
    _unrecorded_attributes = RUNTIME_UNRECORDED_ATTRIBUTES

    def __init__(self, coordinator: Any) -> None:
        self._setup(coordinator, "fresh")

    @property
    def is_on(self) -> bool | None:
        state = self._state()
        return None if state is None else state is True
