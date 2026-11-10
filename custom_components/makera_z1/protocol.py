"""Read-only client for the Makera Z1 LAN protocol.

TCP port 2222 carries binary frames (see MakeraZ1Firmware src/libs/PublicData.h, SerialConsole.cpp):

    86 68 | LEN (2, big endian) | TYPE (1) | PAYLOAD | CRC16 (2) | 55 AA
    LEN = len(PAYLOAD) + 3, CRC-16/XMODEM over LEN|TYPE|PAYLOAD

Only two requests are ever sent, and the client refuses anything else: the real-time status query ``?`` and
the console command ``progress``. Everything else on that channel moves the machine, changes settings or
transfers files. The camera is a separate WebSocket on port 82 that streams JPEG frames after ``start_stream``.

This module has no Home Assistant imports so it can be tested on its own.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

PORT = 2222
CAMERA_START = "start_stream"


def camera_url(host: str) -> str:
    if ":" in host and not host.startswith("["):  # IPv6 literal
        host = f"[{host}]"
    return f"ws://{host}:82/ws_video"

MAX_ANSWERS = 64  # frames collected per request at most

HEADER = b"\x86\x68"
FOOTER = b"\x55\xaa"

TYPE_CTRL_SINGLE = 0xA1  # one real-time byte
TYPE_CTRL_MULTI = 0xA2  # one console line
TYPE_STATUS = 0x81
TYPE_INFO = 0x90

# The only frames this client may send.
ALLOWED_REQUESTS = frozenset({(TYPE_CTRL_SINGLE, b"?"), (TYPE_CTRL_MULTI, b"progress")})

STATES = ["idle", "run", "hold", "pause", "wait", "tool", "alarm", "home", "sleep", "unknown"]
# Machine is doing a job or is in the middle of one: poll faster.
BUSY_STATES = {"run", "hold", "pause", "wait", "tool", "home"}

HALT_REASONS = {
    1: "manual", 2: "home_fail", 3: "probe_fail", 4: "calibrate_fail", 5: "atc_home_fail",
    6: "atc_tool_invalid", 7: "atc_no_tool", 8: "atc_has_tool", 9: "spindle_overheated", 10: "soft_limit",
    11: "cover_open", 12: "probe_invalid", 13: "e_stop", 14: "power_overheated", 15: "not_homed",
    21: "hard_limit", 22: "motor_error_x", 23: "motor_error_y", 24: "motor_error_z", 25: "spindle_stall",
    26: "sd_error", 41: "spindle_alarm",
}
MODELS = {2: "Carvera Air", 3: "Z1", 4: "Z1 Pro"}


class MakeraError(Exception):
    """Machine not reachable or answered garbage."""


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def build_frame(ftype: int, payload: bytes) -> bytes:
    if (ftype, payload) not in ALLOWED_REQUESTS:
        raise ValueError(f"refusing to send frame 0x{ftype:02x} {payload!r}: not a read-only request")
    body = (len(payload) + 3).to_bytes(2, "big") + bytes([ftype]) + payload
    return HEADER + body + crc16_xmodem(body).to_bytes(2, "big") + FOOTER


class FrameReader:
    """Splits a byte stream into (type, payload) frames; resynchronises on the header after junk."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf += data
        frames = []
        while True:
            start = self._buf.find(HEADER)
            if start < 0:
                del self._buf[:-1]  # keep a possible first header byte
                return frames
            del self._buf[:start]
            if len(self._buf) < 4:
                return frames
            length = int.from_bytes(self._buf[2:4], "big")
            total = length + 6
            if length < 3 or length > 515:
                del self._buf[:2]  # not a real header
                continue
            if len(self._buf) < total:
                return frames
            frame = bytes(self._buf[:total])
            body, crc = frame[2:-4], int.from_bytes(frame[-4:-2], "big")
            if frame[-2:] != FOOTER or crc16_xmodem(body) != crc:
                del self._buf[:2]  # false header: resync from the next byte, a real frame may start inside
                continue
            del self._buf[:total]
            frames.append((body[2], body[3:]))


def _numbers(text: str) -> list[float]:
    out = []
    for part in text.split(","):
        try:
            out.append(float(part.strip()))
        except ValueError:
            out.append(float("nan"))
    return out


@dataclass
class Status:
    state: str
    fields: dict[str, list[float]] = field(default_factory=dict)
    raw: str = ""

    def value(self, key: str, index: int) -> float | None:
        vals = self.fields.get(key)
        if not vals or index >= len(vals) or vals[index] != vals[index]:  # missing or NaN
            return None
        return vals[index]

    @property
    def halt_reason(self) -> str | None:
        code = self.value("H", 0)
        if code is None or code <= 0:
            return None
        return HALT_REASONS.get(int(code), f"code_{int(code)}")

    @property
    def model(self) -> str | None:
        code = self.value("C", 0)
        return None if code is None else MODELS.get(int(code), f"model {int(code)}")


def parse_status(text: str) -> Status:
    """Parse ``<Idle|MPos:...|WPos:...|F:...|S:...|T:...|P:...|H:...>``."""
    text = text.strip().strip("\x00")
    m = re.search(r"<([^>]*)>", text)
    if not m:
        raise MakeraError(f"no status in {text!r}")
    parts = m.group(1).split("|")
    state = parts[0].strip().lower()
    if state not in STATES:
        state = "unknown"
    fields = {}
    for part in parts[1:]:
        key, sep, rest = part.partition(":")
        if sep:
            fields[key.strip()] = _numbers(rest)
    return Status(state=state, fields=fields, raw=m.group(0))


@dataclass
class Progress:
    file: str | None = None
    percent: int | None = None
    elapsed: int | None = None
    remaining: int | None = None
    paused: bool = False


def _hms(text: str) -> int:
    h, m, s = (int(x) for x in text.split(":"))
    return h * 3600 + m * 60 + s


def parse_progress(text: str) -> Progress:
    """Parse the answer to ``progress`` (Player.cpp)."""
    if "Not currently playing" in text:
        return Progress()
    if m := re.search(r"paused at (\d+)/(\d+)", text):
        done, size = int(m.group(1)), int(m.group(2))
        return Progress(percent=round(done * 100 / size) if size else None, paused=True)
    m = re.search(r"file: (.*?), (\d+) % complete, elapsed time: (\d+:\d\d:\d\d)(?:, est time: (\d+:\d\d:\d\d))?", text)
    if not m:
        return Progress()
    name = m.group(1).rsplit("/", 1)[-1]
    return Progress(file=name, percent=int(m.group(2)), elapsed=_hms(m.group(3)),
                    remaining=_hms(m.group(4)) if m.group(4) else None)


class MakeraClient:
    """Connects for each query and disconnects again, so Makera Studio is not locked out."""

    def __init__(self, host: str, port: int = PORT, timeout: float = 5.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    async def _exchange(self, ftype: int, payload: bytes, want: int, settle: float) -> list[bytes]:
        frame = build_frame(ftype, payload)
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), self.timeout)
        except (OSError, asyncio.TimeoutError) as err:
            raise MakeraError(f"cannot connect to {self.host}:{self.port}: {err}") from err
        parser, answers = FrameReader(), []
        try:
            writer.write(frame)
            await writer.drain()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout
            while len(answers) < MAX_ANSWERS:
                # once an answer is in, wait only `settle` seconds for continuation frames,
                # but never past the overall deadline (a chatty peer must not keep us here)
                remaining = deadline - loop.time()
                wait = min(settle, remaining) if answers else remaining
                if wait <= 0:
                    break
                try:
                    data = await asyncio.wait_for(reader.read(1024), wait)
                except asyncio.TimeoutError:
                    break
                if not data:
                    break
                answers += [p for t, p in parser.feed(data) if t == want]
                if answers and settle == 0:
                    break
        except OSError as err:
            raise MakeraError(f"connection to {self.host} failed: {err}") from err
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError):
                pass
        if not answers:
            raise MakeraError(f"no answer from {self.host}")
        return answers

    async def status(self) -> Status:
        answers = await self._exchange(TYPE_CTRL_SINGLE, b"?", TYPE_STATUS, settle=0)
        return parse_status(answers[0].decode("utf-8", "replace"))

    async def progress(self) -> Progress:
        answers = await self._exchange(TYPE_CTRL_MULTI, b"progress", TYPE_INFO, settle=0.3)
        return parse_progress(b"".join(answers).decode("utf-8", "replace"))
