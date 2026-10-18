"""Sensors for xTool O1 Omni."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OmniConfigEntry, OmniCoordinator
from .entity import OmniEntity


@dataclass(frozen=True, kw_only=True)
class OmniSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _task_progress(d: dict) -> float | None:
    t = d.get("current_task") or {}
    cur, tot = t.get("currentPrintPass"), t.get("totalPrintPass")
    if not tot:
        return None
    return round(100 * float(cur or 0) / float(tot), 1)


def _task_name(d: dict) -> str | None:
    t = d.get("current_task") or d.get("last_task") or {}
    return t.get("name")


def _task_attrs(d: dict) -> dict:
    t = d.get("current_task") or d.get("last_task") or {}
    out = {k: t.get(k) for k in ("id", "status", "processingMode", "type", "estimateTime", "processingTime", "currentPrintPass", "totalPrintPass", "printNum") if k in t}
    for k in ("createdAt", "updatedAt"):
        if t.get(k):
            out[k] = datetime.fromtimestamp(t[k] / 1000, tz=UTC).isoformat()
    out["running"] = d.get("current_task") is not None
    return out


def _last_job_finished(d: dict) -> datetime | None:
    t = d.get("last_task") or {}
    if t.get("updatedAt") and str(t.get("status", "")).upper() == "FINISHED":
        return datetime.fromtimestamp(t["updatedAt"] / 1000, tz=UTC)
    return None


def _seconds_to_hours(v: Any) -> float | None:
    try:
        return round(float(v) / 3600, 2)
    except (TypeError, ValueError):
        return None


SENSORS: tuple[OmniSensorDescription, ...] = (
    OmniSensorDescription(
        key="mode",
        translation_key="mode",
        icon="mdi:printer-3d",
        value_fn=lambda d: d.get("mode"),
        attrs_fn=lambda d: {"alarms": d.get("alarms"), "last_notify": d.get("last_notify")},
    ),
    OmniSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda d: d.get("temp"),
    ),
    OmniSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda d: d.get("humidity"),
    ),
    OmniSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: (d.get("wifi") or {}).get("rssi_dbm"),
        attrs_fn=lambda d: {"ssid": (d.get("wifi") or {}).get("ssid"), "ip": (d.get("wifi") or {}).get("ip")},
    ),
    OmniSensorDescription(
        key="job_name",
        translation_key="job_name",
        icon="mdi:file-document-outline",
        value_fn=_task_name,
        attrs_fn=_task_attrs,
    ),
    OmniSensorDescription(
        key="job_progress",
        translation_key="job_progress",
        icon="mdi:progress-clock",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_task_progress,
    ),
    OmniSensorDescription(
        key="last_job_finished",
        translation_key="last_job_finished",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_job_finished,
    ),
    OmniSensorDescription(
        key="waste_tank",
        translation_key="waste_tank",
        icon="mdi:delete-variant",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.get("waste") or {}).get("level_value"),
        attrs_fn=lambda d: {"level": (d.get("waste") or {}).get("level"), "exist": (d.get("waste") or {}).get("exist")},
    ),
    OmniSensorDescription(
        key="uv_lamp_hours",
        translation_key="uv_lamp_hours",
        icon="mdi:lightbulb-on-outline",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _seconds_to_hours((d.get("config") or {}).get("uvLampRunTime")),
    ),
    OmniSensorDescription(
        key="air_purifier_hours",
        translation_key="air_purifier_hours",
        icon="mdi:air-filter",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _seconds_to_hours((d.get("config") or {}).get("airPurifierRunTime")),
    ),
    OmniSensorDescription(
        key="print_count",
        translation_key="print_count",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("config") or {}).get("processCount"),
    ),
    OmniSensorDescription(
        key="print_hours",
        translation_key="print_hours",
        icon="mdi:timer-outline",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _seconds_to_hours((d.get("config") or {}).get("processTotalTime")),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: OmniConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    entities: list[SensorEntity] = [OmniSensor(coord, desc) for desc in SENSORS]
    known_tanks: set[str] = set()
    known_moist: set[int] = set()
    known_heads: set[int] = set()

    @callback
    def _add_dynamic() -> None:
        new: list[SensorEntity] = []
        for pos in (coord.data.get("ink_tanks") or {}):
            if pos not in known_tanks:
                known_tanks.add(pos)
                new.append(OmniInkTankSensor(coord, pos))
        for idx in (coord.data.get("moisturizing") or {}):
            if idx not in known_moist:
                known_moist.add(idx)
                new.append(OmniMoisturizingSensor(coord, idx))
        for road in (coord.data.get("heads") or {}):
            if road not in known_heads:
                known_heads.add(road)
                new.append(OmniHeadTempSensor(coord, road))
        if new:
            async_add_entities(new)

    async_add_entities(entities)
    _add_dynamic()
    entry.async_on_unload(coord.async_add_listener(_add_dynamic))


class OmniSensor(OmniEntity, SensorEntity):
    entity_description: OmniSensorDescription

    def __init__(self, coordinator: OmniCoordinator, description: OmniSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.coordinator.data)
        return None


class OmniInkTankSensor(OmniEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water"

    _attr_suggested_unit_of_measurement = UnitOfVolume.MILLILITERS

    def __init__(self, coordinator: OmniCoordinator, key: str) -> None:
        super().__init__(coordinator, f"ink_tank_{key}")
        self._tank_key = key
        t = self._tank()
        name = t.get("name") or f"Ink tank {key}"
        # two tanks can share a name (e.g. two DTG White); add the slot to the second
        same = [k for k, v in (coordinator.data.get("ink_tanks") or {}).items() if v.get("name") == name]
        if len(same) > 1 and same.index(key) > 0:
            name = f"{name} {same.index(key) + 1}"
        self._attr_name = name

    def _tank(self) -> dict:
        return (self.coordinator.data.get("ink_tanks") or {}).get(self._tank_key, {})

    @property
    def native_value(self) -> float | None:
        return self._tank().get("remain_ml")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self._tank()
        full = t.get("full_ml") or 0
        rem = t.get("remain_ml")
        return {
            "full_ml": full,
            "percent": round(100 * rem / full, 1) if full and rem is not None else None,
            "level": t.get("level"),
            "level_value": t.get("level_value"),
            "serial": t.get("serial"),
            "installed": t.get("exist"),
            "ink_line": {1: "UV", 2: "DTG"}.get(t.get("road"), t.get("road")),
            "slot": t.get("slot"),
        }


class OmniMoisturizingSensor(OmniEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-opacity"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_unit_of_measurement = UnitOfVolume.MILLILITERS

    def __init__(self, coordinator: OmniCoordinator, idx: int) -> None:
        super().__init__(coordinator, f"moisturizing_{idx}")
        self._idx = idx
        self._attr_name = f"Moisturizing tank {idx}"

    def _tank(self) -> dict:
        return (self.coordinator.data.get("moisturizing") or {}).get(self._idx, {})

    @property
    def native_value(self) -> float | None:
        return self._tank().get("remain_ml")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self._tank()
        return {"full_ml": t.get("full_ml"), "serial": t.get("serial"), "installed": t.get("exist")}


class OmniHeadTempSensor(OmniEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: OmniCoordinator, road: int) -> None:
        super().__init__(coordinator, f"head_{road}_temperature")
        self._road = road
        self._attr_name = f"Print head {road} temperature"

    def _head(self) -> dict:
        return (self.coordinator.data.get("heads") or {}).get(self._road, {})

    @property
    def native_value(self) -> float | None:
        return self._head().get("temp")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        h = self._head()
        return {"work_state": h.get("work_state"), "ink_type": h.get("ink_type"), "present": h.get("exit_state")}
