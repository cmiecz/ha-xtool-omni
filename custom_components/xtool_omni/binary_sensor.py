"""Binary sensors for xTool O1 Omni."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OmniConfigEntry, OmniCoordinator
from .entity import OmniEntity

RUNNING_MODES = {"printing", "working", "running", "measure", "measuring", "scanning", "scan"}


@dataclass(frozen=True, kw_only=True)
class OmniBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]
    always_available: bool = False


def _door(n: int) -> Callable[[dict[str, Any]], bool | None]:
    return lambda d: (d.get("doors") or {}).get(n)


BINARY_SENSORS: tuple[OmniBinaryDescription, ...] = (
    OmniBinaryDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: bool(d.get("online")),
        always_available=True,
    ),
    OmniBinaryDescription(
        key="lid",
        translation_key="lid",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda d: d.get("lid_open"),
    ),
    OmniBinaryDescription(
        key="door_1",
        translation_key="door_1",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door(1),
    ),
    OmniBinaryDescription(
        key="door_2",
        translation_key="door_2",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door(2),
    ),
    OmniBinaryDescription(
        key="filter",
        translation_key="filter",
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("filter"),
    ),
    OmniBinaryDescription(
        key="running",
        translation_key="running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: (str(d.get("mode") or "").lower() in RUNNING_MODES) or d.get("current_task") is not None,
    ),
    OmniBinaryDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: bool(d.get("alarms")),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: OmniConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(OmniBinarySensor(coord, desc) for desc in BINARY_SENSORS)


class OmniBinarySensor(OmniEntity, BinarySensorEntity):
    entity_description: OmniBinaryDescription

    def __init__(self, coordinator: OmniCoordinator, description: OmniBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        if self.entity_description.always_available:
            return True
        return super().available
