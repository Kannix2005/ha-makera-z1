"""Polls the Makera Z1: fast while a job runs, slow when idle, slower still when the machine is off."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BUSY_INTERVAL, DOMAIN, IDLE_INTERVAL, LOGGER, OFFLINE_INTERVAL
from .protocol import BUSY_STATES, MakeraClient, MakeraError, Progress, Status


@dataclass
class MakeraData:
    status: Status
    progress: Progress

    @property
    def job_active(self) -> bool:
        return self.status.state in BUSY_STATES or self.status.value("P", 1) is not None


MakeraConfigEntry: TypeAlias = ConfigEntry["MakeraCoordinator"]


class MakeraCoordinator(DataUpdateCoordinator[MakeraData]):
    config_entry: MakeraConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MakeraConfigEntry, client: MakeraClient) -> None:
        super().__init__(hass, LOGGER, config_entry=entry, name=DOMAIN, update_interval=IDLE_INTERVAL)
        self.client = client

    async def _async_update_data(self) -> MakeraData:
        try:
            status = await self.client.status()
        except MakeraError as err:
            self.update_interval = OFFLINE_INTERVAL
            raise UpdateFailed(str(err)) from err
        busy = status.state in BUSY_STATES or status.value("P", 1) is not None
        progress = Progress()
        if busy:
            try:
                progress = await self.client.progress()
            except MakeraError as err:  # keep the status; file name and remaining time are missing this round
                LOGGER.debug("Makera progress query failed: %s", err)
                if self.data:
                    progress = self.data.progress
        self.update_interval = BUSY_INTERVAL if busy else IDLE_INTERVAL
        return MakeraData(status, progress)
