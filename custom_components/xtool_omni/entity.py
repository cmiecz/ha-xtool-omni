"""Base entity for xTool O1 Omni."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import OmniCoordinator


class OmniEntity(CoordinatorEntity[OmniCoordinator]):
    """Common device info / availability."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OmniCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        info = coordinator.machine_info or {}
        self._uid_base = info.get("uuid") or info.get("sn") or coordinator.client.host
        self._attr_unique_id = f"{self._uid_base}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        info = self.coordinator.machine_info or {}
        fw = info.get("firmware") or {}
        mac = (self.coordinator.data.get("wifi") or {}).get("mac_addr")
        di = DeviceInfo(
            identifiers={(DOMAIN, self._uid_base)},
            manufacturer=MANUFACTURER,
            model=info.get("deviceName") or "O1 Omni",
            name=info.get("deviceName") or "xTool O1 Omni",
            serial_number=info.get("sn"),
            sw_version=fw.get("version"),
            configuration_url=f"https://{self.coordinator.client.host}:{self.coordinator.client.port}/",
        )
        if mac:
            di["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
        return di

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data.get("online"))
