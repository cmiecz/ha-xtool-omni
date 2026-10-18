# xTool O1 Omni — Home Assistant integration

Local, push-based integration for the **xTool O1 Omni UV printer**. No cloud, no xTool account.
Talks to the printer's own WebSocket API on port 28900 (the same one xTool Studio uses).

## Entities

| Entity | Notes |
|---|---|
| Status | Device mode: `Idle`, `Measure`, printing modes… (attributes: alarms, last notification) |
| Running / Alarm | Binary sensors derived from mode and alarm list |
| Lid, Door 1, Door 2 | Open/closed, pushed live by the printer |
| Temperature, Humidity | Inside the enclosure |
| UV Cyan / Magenta / Yellow / … ink tanks | Remaining ml per tank (attributes: % full, serial) |
| Moisturizing tank 1 / 2 | Remaining ml |
| Waste tank level | Raw level value |
| Print head 1 / 2 temperature | |
| Job, Job progress, Last job finished | From the printer's task list and live reports |
| UV lamp / Air purifier / Total print time, Total prints | Lifetime counters |
| Wi-Fi signal | dBm (disabled by default) |
| Buttons | Home all axes, Refresh |

Events: every device `NOTIFY` is fired on the HA bus as `xtool_omni_event`.

## Install

**HACS:** add this repo as a custom repository (type *Integration*), install, restart HA.

**Manual:** copy `custom_components/xtool_omni` into your HA `config/custom_components/` folder and restart HA.

Then *Settings → Devices & services → Add integration → xTool O1 Omni* and enter the printer's IP.

## Protocol notes

Reverse-engineered from xTool Studio 1.9.11 (Oct 2026). Summary:

- `wss://<ip>:28900/websocket?id=<uuid>&function=instruction`, TLS 1.2, xTool private CA (verification disabled), `permessage-deflate`.
- Each message: 10-byte header (`BA BE`, 3-byte length, type `0x04`, CRC-16/ARC of body, CRC-16/ARC of header) + compact JSON.
- Auth: `GET /v1/user/parity` with `userID=mk-guest`, `userKey=bWFrZWJsb2NrLXh0b29s`.
- The device pushes `REPORT` (state) and `NOTIFY` (events) messages unprompted.

Tested on firmware `40.101.013.01.ht1`.
