# Changelog

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
