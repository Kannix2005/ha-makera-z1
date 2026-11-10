"""Sensors: machine state, alarm reason, job progress, spindle, tool, feed and work position."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MakeraConfigEntry, MakeraData
from .entity import MakeraEntity
from .protocol import HALT_REASONS, STATES


@dataclass(frozen=True, kw_only=True)
class MakeraSensorDescription(SensorEntityDescription):
    value: Callable[[MakeraData], str | float | int | None]


def _halt(d: MakeraData) -> str | None:
    reason = d.status.halt_reason
    return reason if reason in HALT_REASONS.values() else None


def _percent(d: MakeraData) -> float | None:
    p = d.status.value("P", 1)
    return p if p is not None else d.progress.percent


def _elapsed(d: MakeraData) -> float | None:
    e = d.status.value("P", 2)
    return e if e is not None else d.progress.elapsed


def _wpos(axis: int) -> Callable[[MakeraData], float | None]:
    return lambda d: d.status.value("WPos", axis)


TEMP = {"device_class": SensorDeviceClass.TEMPERATURE, "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT}
POS = {"device_class": SensorDeviceClass.DISTANCE, "native_unit_of_measurement": UnitOfLength.MILLIMETERS,
       "entity_category": EntityCategory.DIAGNOSTIC, "suggested_display_precision": 2}

SENSORS = (
    MakeraSensorDescription(key="state", device_class=SensorDeviceClass.ENUM, options=STATES,
                            value=lambda d: d.status.state),
    MakeraSensorDescription(key="alarm_reason", device_class=SensorDeviceClass.ENUM,
                            options=list(HALT_REASONS.values()), value=_halt),
    MakeraSensorDescription(key="job_progress", native_unit_of_measurement=PERCENTAGE, value=_percent),
    MakeraSensorDescription(key="job_file", value=lambda d: d.progress.file),
    MakeraSensorDescription(key="job_elapsed", device_class=SensorDeviceClass.DURATION,
                            native_unit_of_measurement=UnitOfTime.SECONDS, suggested_unit_of_measurement=UnitOfTime.MINUTES,
                            value=_elapsed),
    MakeraSensorDescription(key="job_remaining", device_class=SensorDeviceClass.DURATION,
                            native_unit_of_measurement=UnitOfTime.SECONDS, suggested_unit_of_measurement=UnitOfTime.MINUTES,
                            value=lambda d: d.progress.remaining),
    MakeraSensorDescription(key="spindle_speed", native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
                            state_class=SensorStateClass.MEASUREMENT, value=lambda d: d.status.value("S", 0)),
    MakeraSensorDescription(key="spindle_temperature", value=lambda d: d.status.value("S", 4), **TEMP),
    MakeraSensorDescription(key="power_temperature", entity_category=EntityCategory.DIAGNOSTIC,
                            value=lambda d: d.status.value("S", 5), **TEMP),
    MakeraSensorDescription(key="tool", value=lambda d: None if (t := d.status.value("T", 0)) is None else int(t)),
    MakeraSensorDescription(key="feed_rate", native_unit_of_measurement="mm/min",
                            state_class=SensorStateClass.MEASUREMENT, value=lambda d: d.status.value("F", 0)),
    MakeraSensorDescription(key="position_x", value=_wpos(0), **POS),
    MakeraSensorDescription(key="position_y", value=_wpos(1), **POS),
    MakeraSensorDescription(key="position_z", value=_wpos(2), **POS),
)


async def async_setup_entry(hass: HomeAssistant, entry: MakeraConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(MakeraSensor(entry.runtime_data, d) for d in SENSORS)


class MakeraSensor(MakeraEntity, SensorEntity):
    entity_description: MakeraSensorDescription

    def __init__(self, coordinator, description: MakeraSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | float | int | None:
        return self.entity_description.value(self.coordinator.data) if self.coordinator.data else None
