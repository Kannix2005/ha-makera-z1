# Makera Z1 for Home Assistant

Local, **read-only** integration for the [Makera Z1](https://www.makera.com/) desktop CNC over WiFi.
No cloud, no account, no extra Python packages.

## What you get

| Entity | Notes |
|---|---|
| State | Idle, Running, Hold, Paused, Waiting, Tool change, Alarm, Homing, Sleep |
| Alarm reason | e.g. cover open, emergency stop, soft/hard limit, spindle overheated |
| Job progress / file / elapsed / remaining | while a job runs (remaining = the machine's own estimate) |
| Spindle speed, spindle temperature, power supply temperature | |
| Tool, feed rate, work position X/Y/Z | position and PSU temperature are diagnostic entities |
| Online, Job running, Alarm | binary sensors; *Online* shows *off* instead of *unavailable* when the machine is switched off |
| Camera | snapshot and live view (MJPEG) of the built-in camera |

The machine is polled every 10 s, every 2 s while a job runs and every 30 s while it is off.

## Safety

The Z1 accepts machine commands on the same TCP port. This integration sends **only two requests** — the
real-time status query `?` and the console command `progress` — and its protocol layer refuses to build any
other frame (`protocol.py`, `ALLOWED_REQUESTS`, covered by tests). It cannot move the machine, start or stop
jobs, switch the spindle or laser, or change settings.

Each poll opens a short TCP connection and closes it again, so Makera Studio can still connect.

## Installation

HACS / Home Assistant Marketplace: add this repository as a custom repository (type *Integration*), install
**Makera Z1**, restart Home Assistant. Or copy `custom_components/makera_z1` into your configuration folder.

Then *Settings → Devices & services → Add integration → Makera Z1* and enter the machine's IP address.
Give the machine a fixed DHCP lease in your router; the integration does not discover it.

## Protocol

TCP 2222, binary frames `86 68 | LEN | TYPE | PAYLOAD | CRC16/XMODEM | 55 AA`, as implemented in Makera's
open-source firmware ([MakeraInc/MakeraZ1Firmware](https://github.com/MakeraInc/MakeraZ1Firmware),
`src/libs/PublicData.h`, `src/modules/communication/SerialConsole.cpp`). Status answers are GRBL-style strings
(`<Idle|MPos:…|WPos:…|F:…|S:…|T:…|P:…|H:…>`, see `src/libs/Kernel.cpp`). The camera is a WebSocket at
`ws://<ip>:82/ws_video` that sends JPEG frames after the text message `start_stream`.

## Known limits

- The camera may allow only one viewer: while Home Assistant shows the live view, Makera Studio's camera
  view may stop, and the other way round.
- Tested with a Z1 on firmware 1.1.x. The Z1 Pro and Carvera Air use the same firmware family and should work,
  but are untested.

This project is not affiliated with Makera.

## Development

```
python3 -m venv venv && venv/bin/pip install pytest
venv/bin/python -m pytest tests
```
