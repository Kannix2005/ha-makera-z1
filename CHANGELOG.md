# Changelog

## 0.1.2 – 2026-11-11

- Makera brand icon for the integration (shown in Home Assistant and HACS).
- GitHub validation: HACS action, hassfest and the test suite run on every push.
- No functional changes.

## 0.1.1 – 2026-11-10

Hardening after a security review; no change in behaviour.

- Camera: WebSocket messages are limited to 4 MiB (was unlimited), so a faulty device cannot exhaust memory.
- Status/progress queries: the overall timeout now always applies and at most 64 answer frames are collected,
  so a peer that keeps sending cannot hold a poll open.

## 0.1.0 – 2026-11-10

First release.

- Read-only status over the Z1's own TCP protocol (port 2222): state, alarm reason, job progress, file,
  elapsed and remaining time, spindle speed and temperatures, tool, feed rate, work position.
- Binary sensors *Online*, *Job running*, *Alarm*.
- Camera (snapshot and MJPEG live view) from the built-in camera on port 82.
- Only the status query `?` and `progress` are ever sent; the protocol layer refuses every other frame so the
  integration can never move the machine or change settings.
- Polls every 10 s, every 2 s during a job, every 30 s while the machine is off; connects per poll so Makera
  Studio is not locked out.
