"""Makera Z1 desktop CNC: read-only status and camera over the local network."""
from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import MakeraConfigEntry, MakeraCoordinator
from .protocol import MakeraClient

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CAMERA, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: MakeraConfigEntry) -> bool:
    coordinator = MakeraCoordinator(hass, entry, MakeraClient(entry.data[CONF_HOST]))
    # the machine is often switched off: start anyway, entities stay unavailable until it answers
    await coordinator.async_refresh()
    entry.runtime_data = coordinator

    @callback
    def _update_model() -> None:
        """Write the reported model (Z1, Z1 Pro, ...) into the device registry once it is known."""
        model = coordinator.data.status.model if coordinator.data else None
        if not model:
            return
        registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            if (DOMAIN, entry.entry_id) in device.identifiers and device.model != model:
                registry.async_update_device(device.id, model=model)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _update_model()
    entry.async_on_unload(coordinator.async_add_listener(_update_model))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MakeraConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
