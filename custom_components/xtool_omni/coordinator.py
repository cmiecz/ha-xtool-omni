"""Data coordinator for the xTool O1 Omni."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OmniAuthError, OmniClient, OmniConnectionError, OmniError
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONFIG_KEYS,
    DEFAULT_PORT,
    DOMAIN,
    EP_CONFIG,
    EP_HEAD_PARAM,
    EP_INK_TANK,
    EP_MACHINE_INFO,
    EP_MAINT_TANK,
    EP_PERIPHERAL,
    EP_STATE_SYNC,
    EP_TASK_LIST,
    EP_TEMP_HUMIDITY,
    EP_WIFI,
    INK_TANK_FALLBACK_NAMES,
    POLL_INTERVAL,
    RECONNECT_MAX,
    RECONNECT_MIN,
)

_LOGGER = logging.getLogger(__name__)

type OmniConfigEntry = ConfigEntry[OmniCoordinator]


class OmniCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps a live connection to the Omni and a merged state dict."""

    config_entry: OmniConfigEntry

    def __init__(self, hass: HomeAssistant, entry: OmniConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=POLL_INTERVAL),
            config_entry=entry,
        )
        self.client = OmniClient(
            entry.data[CONF_HOST],
            async_get_clientsession(hass, verify_ssl=False),
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            timezone=str(hass.config.time_zone or "UTC"),
        )
        self.client.set_push_callback(self._handle_push)
        self.client.set_disconnect_callback(self._handle_disconnect)
        self._reconnect_task: asyncio.Task | None = None
        self._backoff = RECONNECT_MIN
        self.data = self._empty_state()
        self.machine_info: dict[str, Any] = {}

    # ------------------------------------------------------------------ lifecycle
    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "online": False,
            "mode": None,
            "alarms": [],
            "wifi": {},
            "temp": None,
            "humidity": None,
            "lid_open": None,
            "doors": {},
            "filter": None,
            "pallet": None,
            "ink_tanks": {},
            "moisturizing": {},
            "waste": {},
            "heads": {},
            "power_error": None,
            "config": {},
            "last_task": None,
            "current_task": None,
            "last_notify": None,
        }

    async def async_connect(self) -> None:
        """Initial connect; raises on failure so config entry setup can retry."""
        await self.client.connect()
        self.data["online"] = True
        self._backoff = RECONNECT_MIN

    async def async_shutdown(self) -> None:
        if self._reconnect_task:
            self._reconnect_task.cancel()
        await self.client.disconnect()
        await super().async_shutdown()

    @callback
    def _handle_disconnect(self) -> None:
        _LOGGER.warning("Lost connection to Omni at %s; will reconnect", self.client.host)
        self.data["online"] = False
        self.async_set_updated_data(self.data)
        if not self._reconnect_task or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_background_task(
                self._reconnect_loop(), name="xtool_omni_reconnect"
            )

    async def _reconnect_loop(self) -> None:
        while not self.client.connected:
            await asyncio.sleep(self._backoff)
            try:
                await self.client.connect()
            except OmniError as err:
                _LOGGER.debug("Reconnect failed: %s", err)
                self._backoff = min(self._backoff * 2, RECONNECT_MAX)
                continue
            _LOGGER.info("Reconnected to Omni at %s", self.client.host)
            self._backoff = RECONNECT_MIN
            self.data["online"] = True
            await self.async_request_refresh()

    # ------------------------------------------------------------------ polling
    async def _async_update_data(self) -> dict[str, Any]:
        if not self.client.connected:
            if not self._reconnect_task or self._reconnect_task.done():
                self._handle_disconnect()
            raise UpdateFailed("Omni not connected")
        try:
            if not self.machine_info:
                self.machine_info = await self.client.get(EP_MACHINE_INFO) or {}
            wifi, th, periph, ink, maint, heads, tasks, cfg = await asyncio.gather(
                self.client.get(EP_WIFI),
                self.client.get(EP_TEMP_HUMIDITY),
                self.client.get(EP_PERIPHERAL),
                self.client.get(EP_INK_TANK),
                self.client.get(EP_MAINT_TANK),
                self.client.get(EP_HEAD_PARAM),
                self.client.get(EP_TASK_LIST),
                self.client.get(EP_CONFIG, data={"kv": CONFIG_KEYS}),
                return_exceptions=True,
            )
        except OmniAuthError as err:
            raise UpdateFailed(f"Auth error: {err}") from err
        except OmniConnectionError as err:
            raise UpdateFailed(str(err)) from err

        d = self.data
        d["online"] = True
        if isinstance(wifi, dict):
            d["wifi"] = wifi
        if isinstance(th, dict):
            d["temp"] = th.get("temp")
            d["humidity"] = th.get("humity")
        if isinstance(periph, dict):
            self._apply_peripheral(periph)
        if isinstance(ink, dict):
            self._apply_ink(ink)
        if isinstance(maint, dict):
            self._apply_maint(maint)
        if isinstance(heads, dict):
            self._apply_heads(heads)
        if isinstance(tasks, dict):
            self._apply_tasks(tasks)
        if isinstance(cfg, dict):
            d["config"].update(cfg)
        # ask the device to push its state block (mode, alarms)
        try:
            await self.client.post(EP_STATE_SYNC)
        except OmniError:
            pass
        return d

    # ------------------------------------------------------------------ push
    def _handle_push(self, method: str, data: Any) -> None:
        if method == "NOTIFY":
            if isinstance(data, list) and data:
                self.data["last_notify"] = data[-1]
                for ev in data:
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_event",
                        {"host": self.client.host, **({k: v for k, v in ev.items()} if isinstance(ev, dict) else {"event": ev})},
                    )
            self.async_set_updated_data(self.data)
            return
        if not isinstance(data, dict):
            return
        for key, val in data.items():
            if key == "/v1/platform/device/state" and isinstance(val, dict):
                self.data["mode"] = val.get("mode", self.data["mode"])
                if "task" in val:
                    self.data["current_task"] = val["task"]
            elif key == "/v1/platform/device/alarm":
                self.data["alarms"] = val if isinstance(val, list) else []
            elif key == "/v1/platform/device/machine-info" and isinstance(val, dict):
                self.machine_info = val
            elif key == "/v1/project/device/info" and isinstance(val, dict):
                self._apply_device_info(val)
            elif key == "/v1/project/device/peripheral-status" and isinstance(val, dict):
                self._apply_peripheral(val)
            elif key == "/v1/project/device/temp-humity" and isinstance(val, dict):
                self.data["temp"] = val.get("temp")
                self.data["humidity"] = val.get("humity")
            elif key.startswith("/v1/project/task") and isinstance(val, dict):
                # progress reports for a running job land here
                self.data["current_task"] = {**(self.data.get("current_task") or {}), **val}
        self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------ parsers
    def _apply_peripheral(self, p: dict) -> None:
        d = self.data
        d["lid_open"] = bool(p.get("lid"))
        d["doors"] = {int(x.get("type", i + 1)): bool(x.get("status")) for i, x in enumerate(p.get("doors", []))}
        d["filter"] = p.get("filter")
        d["pallet"] = p.get("pallet")

    def _apply_ink(self, ink: dict) -> None:
        tanks: dict[int, dict] = {}
        for road, lst in ink.items():
            if not isinstance(lst, list):
                continue
            for i, t in enumerate(lst):
                tid = int(t.get("tank_id", i))
                pos = i + 1  # device uses 1-based in /ink-tank and 0-based in /device/info
                prev = self.data["ink_tanks"].get(pos, {})
                tanks[pos] = {
                    "name": t.get("name") or prev.get("name") or INK_TANK_FALLBACK_NAMES.get(pos, f"Tank {pos}"),
                    "remain_ml": t.get("remain_ml"),
                    "full_ml": t.get("full_ml"),
                    "level": t.get("level"),
                    "level_value": t.get("level_value"),
                    "serial": t.get("serial"),
                    "exist": t.get("exist"),
                    "road": road,
                    "tank_id": tid,
                }
        if tanks:
            self.data["ink_tanks"] = tanks

    def _apply_maint(self, m: dict) -> None:
        mo = {}
        for i, t in enumerate(m.get("moisturizing", [])):
            idx = int(t.get("index", i + 1))
            mo[idx] = t
        self.data["moisturizing"] = mo
        if isinstance(m.get("waste"), dict):
            self.data["waste"] = m["waste"]

    def _apply_heads(self, h: dict) -> None:
        heads = {}
        for i, hp in enumerate(h.get("printer_head_param", [])):
            heads[int(hp.get("ink_road", i + 1))] = hp
        self.data["heads"] = heads
        self.data["power_error"] = h.get("power_error")

    def _apply_tasks(self, t: dict) -> None:
        hist = t.get("history_tasks") or []
        if hist:
            self.data["last_task"] = hist[0]
            running = [x for x in hist if str(x.get("status", "")).upper() not in ("FINISHED", "CANCELED", "CANCELLED", "FAILED", "STOPPED")]
            self.data["current_task"] = running[0] if running else None

    def _apply_device_info(self, info: dict) -> None:
        d = self.data
        if "humity" in info:
            d["humidity"] = info["humity"]
        if "temp" in info:
            d["temp"] = info["temp"]
        if isinstance(info.get("ink_tanks"), dict):
            self._apply_ink(info["ink_tanks"])
        if isinstance(info.get("maintenance_tank"), dict):
            self._apply_maint(info["maintenance_tank"])
        if isinstance(info.get("peripheral_status"), dict):
            self._apply_peripheral(info["peripheral_status"])
        for k in ("airPurifierRunTime", "uvLampRunTime", "opticalPathRunTime", "processCount", "processTotalTime"):
            if k in info:
                d["config"][k] = info[k]
        if "mode" in info:
            d["mode"] = info["mode"]
