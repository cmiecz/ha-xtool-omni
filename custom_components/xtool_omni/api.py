"""Local WebSocket client for the xTool O1 Omni.

Protocol (reverse-engineered from xTool Studio 1.9.11):
  wss://<host>:28900/websocket?id=<uuid>&function=instruction
  Each binary WebSocket message = 10-byte header + compact JSON body.
    0-1  magic 0xBABE
    2-4  body length, big-endian
    5    type (0x04 = JSON)
    6-7  CRC-16/ARC of body, big-endian
    8-9  CRC-16/ARC of header[0:8], big-endian
  Requests: {"type":"request","method":"GET","url":"/v1/...","params":{},"data":{},
             "timestamp":<ms>,"transactionId":<n>}
  Responses: {"type":"response","code":0,"data":{...},"transactionId":<n>}
  Device pushes: {"type":"request","method":"REPORT"|"NOTIFY","data":...}
  Auth: GET /v1/user/parity with the built-in guest credential.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import struct
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .const import (
    DEFAULT_PORT,
    EP_PARITY,
    EP_PING,
    GUEST_USER_ID,
    GUEST_USER_KEY,
    PING_INTERVAL,
    REQUEST_TIMEOUT,
    WS_MAGIC,
    WS_TYPE_JSON,
)

_LOGGER = logging.getLogger(__name__)

PushCallback = Callable[[str, Any], Awaitable[None] | None]


class OmniError(Exception):
    """Base error."""


class OmniConnectionError(OmniError):
    """Could not connect."""


class OmniAuthError(OmniError):
    """Device rejected the guest login."""


def crc16_arc(data: bytes) -> int:
    """CRC-16/ARC (poly 0x8005 reflected, init 0, xorout 0)."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def pack_frame(obj: dict) -> bytes:
    """Encode a JSON message into an Omni WebSocket frame."""
    body = json.dumps(obj, separators=(",", ":")).encode()
    hdr = (
        WS_MAGIC
        + len(body).to_bytes(3, "big")
        + bytes([WS_TYPE_JSON])
        + struct.pack(">H", crc16_arc(body))
    )
    hdr += struct.pack(">H", crc16_arc(hdr))
    return hdr + body


def unpack_frame(frame: bytes) -> dict | None:
    """Decode an Omni WebSocket frame into JSON (None if not a JSON frame)."""
    if len(frame) < 10 or frame[:2] != WS_MAGIC:
        return None
    if frame[5] != WS_TYPE_JSON:
        return None
    length = int.from_bytes(frame[2:5], "big")
    body = frame[10 : 10 + length]
    try:
        return json.loads(body)
    except ValueError:
        _LOGGER.debug("Non-JSON body: %r", body[:80])
        return None


def _ssl_context() -> ssl.SSLContext:
    """The Omni presents a cert from xTool's private CA; skip verification."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class OmniClient:
    """Persistent connection to one Omni."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        port: int = DEFAULT_PORT,
        timezone: str = "UTC",
    ) -> None:
        self.host = host
        self.port = port
        self.timezone = timezone
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._tid = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._push_callback: PushCallback | None = None
        self._disconnect_callback: Callable[[], None] | None = None
        self._ssl = _ssl_context()
        self.connected = False

    # ------------------------------------------------------------------ connection
    @property
    def url(self) -> str:
        return (
            f"wss://{self.host}:{self.port}/websocket"
            f"?id={uuid.uuid4()}&function=instruction"
        )

    def set_push_callback(self, cb: PushCallback | None) -> None:
        self._push_callback = cb

    def set_disconnect_callback(self, cb: Callable[[], None] | None) -> None:
        self._disconnect_callback = cb

    async def connect(self) -> None:
        """Open the WebSocket and authenticate."""
        try:
            async with asyncio.timeout(15):
                self._ws = await self._session.ws_connect(
                    self.url,
                    ssl=self._ssl,
                    compress=15,
                    heartbeat=None,
                    headers={
                        "User-Agent": "HomeAssistant xtool_omni (compatible; xToolStudio/1.9.11)",
                        "Origin": "atomm://renderer",
                    },
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise OmniConnectionError(f"Cannot connect to {self.host}:{self.port}: {err}") from err

        self.connected = True
        self._reader_task = asyncio.create_task(self._reader(), name="xtool_omni_reader")
        try:
            resp = await self.request(
                "GET",
                EP_PARITY,
                data={
                    "userID": GUEST_USER_ID,
                    "userKey": GUEST_USER_KEY,
                    "timezone": self.timezone,
                    "token": "",
                },
            )
        except OmniError:
            await self.disconnect()
            raise
        if resp.get("code") != 0:
            await self.disconnect()
            raise OmniAuthError(f"Auth rejected: {resp.get('message')}")
        self._ping_task = asyncio.create_task(self._pinger(), name="xtool_omni_ping")
        _LOGGER.debug("Connected and authenticated to Omni at %s", self.host)

    async def disconnect(self) -> None:
        self.connected = False
        for task in (self._ping_task, self._reader_task):
            if task and not task.done() and task is not asyncio.current_task():
                task.cancel()
        self._ping_task = None
        self._reader_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(OmniConnectionError("Disconnected"))
        self._pending.clear()
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._ws = None

    # ------------------------------------------------------------------ messaging
    async def request(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        params: dict | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict:
        """Send a request and wait for its response."""
        if not self._ws or self._ws.closed:
            raise OmniConnectionError("Not connected")
        self._tid += 1
        tid = self._tid
        msg = {
            "type": "request",
            "method": method,
            "url": url,
            "params": params or {},
            "data": data or {},
            "timestamp": int(time.time() * 1000),
            "transactionId": tid,
        }
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[tid] = fut
        try:
            await self._ws.send_bytes(pack_frame(msg))
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as err:
            raise OmniConnectionError(f"Timeout waiting for {url}") from err
        except (aiohttp.ClientError, ConnectionResetError) as err:
            raise OmniConnectionError(str(err)) from err
        finally:
            self._pending.pop(tid, None)

    async def get(self, url: str, **kw: Any) -> Any:
        """GET helper returning just the data payload."""
        resp = await self.request("GET", url, **kw)
        if resp.get("code") not in (0, None):
            _LOGGER.debug("GET %s -> code %s %s", url, resp.get("code"), resp.get("message"))
        return resp.get("data")

    async def post(self, url: str, **kw: Any) -> Any:
        resp = await self.request("POST", url, **kw)
        return resp.get("data")

    async def _reader(self) -> None:
        assert self._ws is not None
        try:
            async for ws_msg in self._ws:
                if ws_msg.type == aiohttp.WSMsgType.BINARY:
                    payload = ws_msg.data
                elif ws_msg.type == aiohttp.WSMsgType.TEXT:
                    payload = ws_msg.data.encode()
                elif ws_msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
                else:
                    continue
                msg = unpack_frame(payload)
                if not msg:
                    continue
                if msg.get("type") == "response":
                    fut = self._pending.get(msg.get("transactionId"))
                    if fut and not fut.done():
                        fut.set_result(msg)
                    continue
                method = msg.get("method")
                if method in ("REPORT", "NOTIFY") and self._push_callback:
                    try:
                        result = self._push_callback(method, msg.get("data"))
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Error in push callback")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Reader loop ended with error", exc_info=True)
        finally:
            was_connected = self.connected
            self.connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(OmniConnectionError("Connection closed"))
            if was_connected and self._disconnect_callback:
                self._disconnect_callback()

    async def _pinger(self) -> None:
        try:
            while self.connected:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await self.request("GET", EP_PING, timeout=PING_INTERVAL * 2)
                except OmniConnectionError:
                    _LOGGER.debug("Ping failed; dropping connection")
                    await self.disconnect()
                    if self._disconnect_callback:
                        self._disconnect_callback()
                    return
        except asyncio.CancelledError:
            raise
