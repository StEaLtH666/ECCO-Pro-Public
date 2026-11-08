"""The SHADOW sensors (read-only displays). Every state and attribute comes from advisory_contract.to_entity_payloads via
the coordinator; the entity id, unique_id and units are the contract's. No services, no RestoreEntity, no state class
(nothing here is a long-term statistic).

Recorder: every class keeps the contract's UNRECORDED_ATTRIBUTES and the timestamp-only attributes
(const.TIMESTAMP_ONLY_ATTRIBUTES: generated_at, valid_until, next_run_at) out of Home Assistant's recorder. That changes
only what the recorder stores, never the published state or attributes (A17)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant

from intelligence.advisory_contract import ITEM_UNITS, UNRECORDED_ATTRIBUTES, DataQuality, SystemStatus

from .const import TIMESTAMP_ONLY_ATTRIBUTES
from .entity_base import EccoIntelEntity

RUNTIME_UNRECORDED_ATTRIBUTES = frozenset(UNRECORDED_ATTRIBUTES | TIMESTAMP_ONLY_ATTRIBUTES)

VALUE_KEYS = ("charge_target", "overnight_demand", "export_event", "dump_to_grid", "predicted_day_load", "pv_tomorrow",
              "predicted_morning_soc")


async def async_setup_entry(hass: HomeAssistant, entry: Any, async_add_entities: Any) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [EccoIntelStatusSensor(coordinator)]
    entities += [EccoIntelValueSensor(coordinator, k) for k in VALUE_KEYS]
    entities += [EccoIntelAccuracySensor(coordinator), EccoIntelDataQualitySensor(coordinator)]
    async_add_entities(entities)


class EccoIntelStatusSensor(EccoIntelEntity, SensorEntity):
    _unrecorded_attributes = RUNTIME_UNRECORDED_ATTRIBUTES
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SystemStatus.ALL)

    def __init__(self, coordinator: Any) -> None:
        self._setup(coordinator, "status")

    @property
    def native_value(self) -> Any:
        return self._state()


class EccoIntelValueSensor(EccoIntelEntity, SensorEntity):
    """An advice item or forecast: a number only when the contract allows one (status OK and within its validity)."""
    _unrecorded_attributes = RUNTIME_UNRECORDED_ATTRIBUTES

    def __init__(self, coordinator: Any, key: str) -> None:
        self._setup(coordinator, key)
        self._attr_native_unit_of_measurement = ITEM_UNITS[key]

    @property
    def native_value(self) -> Any:
        return self._state()


class EccoIntelAccuracySensor(EccoIntelEntity, SensorEntity):
    _unrecorded_attributes = RUNTIME_UNRECORDED_ATTRIBUTES
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, coordinator: Any) -> None:
        self._setup(coordinator, "accuracy")

    @property
    def native_value(self) -> Any:
        return self._state()


class EccoIntelDataQualitySensor(EccoIntelEntity, SensorEntity):
    _unrecorded_attributes = RUNTIME_UNRECORDED_ATTRIBUTES
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(DataQuality.ALL)

    def __init__(self, coordinator: Any) -> None:
        self._setup(coordinator, "data_quality")

    @property
    def native_value(self) -> Any:
        return self._state()
