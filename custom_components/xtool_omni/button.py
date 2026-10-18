"""Buttons for xTool O1 Omni."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import OmniError
from .const import EP_HOME, EP_STATE_SYNC
from .coordinator import OmniConfigEntry, OmniCoordinator
from .entity import OmniEntity

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="home",
        translation_key="home",
        icon="mdi:home-import-outline",
    ),
    ButtonEntityDescription(
        key="refresh",
        translation_key="refresh",
        icon="mdi:refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: OmniConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(OmniButton(coord, desc) for desc in BUTTONS)


class OmniButton(OmniEntity, ButtonEntity):
    def __init__(self, coordinator: OmniCoordinator, description: ButtonEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        client = self.coordinator.client
        try:
            if self.entity_description.key == "home":
                await client.post(EP_HOME, params={"axis": "ALL"})
            elif self.entity_description.key == "refresh":
                await client.post(EP_STATE_SYNC)
                await self.coordinator.async_request_refresh()
        except OmniError as err:
            raise HomeAssistantError(f"Omni command failed: {err}") from err
