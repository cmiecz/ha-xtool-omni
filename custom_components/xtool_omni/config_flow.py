"""Config flow for xTool O1 Omni."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OmniAuthError, OmniClient, OmniConnectionError
from .const import CONF_HOST, CONF_PORT, DEFAULT_NAME, DEFAULT_PORT, DOMAIN, EP_MACHINE_INFO

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class OmniConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            client = OmniClient(
                host,
                async_get_clientsession(self.hass, verify_ssl=False),
                port=port,
                timezone=str(self.hass.config.time_zone or "UTC"),
            )
            try:
                await client.connect()
                info = await client.get(EP_MACHINE_INFO) or {}
            except OmniAuthError:
                errors["base"] = "invalid_auth"
            except OmniConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            finally:
                await client.disconnect()

            if not errors:
                uid = info.get("uuid") or info.get("sn") or host
                await self.async_set_unique_id(uid)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                title = info.get("deviceName") or DEFAULT_NAME
                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)
