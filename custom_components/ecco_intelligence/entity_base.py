"""What every ECCO Intelligence entity shares: the contract's entity id and unique_id, one device, the payload from
advisory_contract.to_entity_payloads (THE mapping), the contract's unrecorded attributes plus the timestamp-only
attributes (const.TIMESTAMP_ONLY_ATTRIBUTES, A17; every concrete class states the same set). No RestoreEntity: after a
restart every entity starts from the coordinator's STARTING envelope (all nulls), never from a remembered value."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from intelligence.advisory_contract import ENTITY_IDS, UNIQUE_IDS, UNRECORDED_ATTRIBUTES

from .const import DEVICE_IDENTIFIER, DEVICE_NAME, DOMAIN, INTEGRATION_VERSION, TIMESTAMP_ONLY_ATTRIBUTES

NAMES = {
    "status": "ECCO Intel status", "charge_target": "ECCO Intel charge target",
    "overnight_demand": "ECCO Intel overnight demand", "export_event": "ECCO Intel export event",
    "dump_to_grid": "ECCO Intel Dump to Grid estimate", "predicted_day_load": "ECCO Intel predicted day load",
    "pv_tomorrow": "ECCO Intel PV tomorrow", "predicted_morning_soc": "ECCO Intel predicted morning SOC",
    "accuracy": "ECCO Intel accuracy", "data_quality": "ECCO Intel data quality", "fresh": "ECCO Intel fresh",
}


def device_info() -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, DEVICE_IDENTIFIER)}, name=DEVICE_NAME, manufacturer="ECCO",
                      model="Intelligence SHADOW (advisory only, applies nothing)", sw_version=INTEGRATION_VERSION,
                      entry_type=DeviceEntryType.SERVICE)


class EccoIntelEntity:
    """A mixin placed before SensorEntity / BinarySensorEntity."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _unrecorded_attributes = frozenset(UNRECORDED_ATTRIBUTES | TIMESTAMP_ONLY_ATTRIBUTES)

    def _setup(self, coordinator: Any, key: str) -> None:
        self.coordinator = coordinator
        self._key = key
        self.entity_id = ENTITY_IDS[key]               # explicit: a different id given by HA is a failed self-test
        self._attr_unique_id = UNIQUE_IDS[key]
        self._attr_name = NAMES[key]
        self._attr_device_info = device_info()

    def _payload(self) -> tuple | None:
        return self.coordinator.payload(ENTITY_IDS[self._key])

    def _state(self) -> Any:
        p = self._payload()
        return None if p is None else p[0]

    @property
    def extra_state_attributes(self) -> dict | None:
        p = self._payload()
        return None if p is None else {**p[1], **p[2]}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update, self._key))
        self.coordinator.entity_added(self._key, self.entity_id)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
