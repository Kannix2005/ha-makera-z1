"""Base entity: one device per machine."""
from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MakeraCoordinator


class MakeraEntity(CoordinatorEntity[MakeraCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MakeraCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # the model is filled in by __init__.py once the machine has answered (it may be off at startup)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, manufacturer="Makera",
            name=entry.title, configuration_url=f"http://{entry.data[CONF_HOST]}/")
