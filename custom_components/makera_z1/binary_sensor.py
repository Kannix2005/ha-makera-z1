"""Binary sensors: machine reachable, job running, alarm."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MakeraConfigEntry
from .entity import MakeraEntity


async def async_setup_entry(hass: HomeAssistant, entry: MakeraConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([MakeraOnline(c), MakeraRunning(c), MakeraAlarm(c)])


class MakeraOnline(MakeraEntity, BinarySensorEntity):
    """On while the machine answers; stays available so 'off' is shown instead of 'unavailable'."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "online")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class MakeraRunning(MakeraEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "running")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.status.state == "run" if self.coordinator.data else None


class MakeraAlarm(MakeraEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "alarm")

    @property
    def is_on(self) -> bool | None:
        d = self.coordinator.data
        return (d.status.state == "alarm" or d.status.halt_reason is not None) if d else None
