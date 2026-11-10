"""Camera: the Z1 streams JPEG frames over a WebSocket on port 82 after the text message 'start_stream'.

The machine's camera may serve only one viewer, so all of Home Assistant shares one connection: snapshots and
every live view (MJPEG) subscribe to the same feed. It is opened on the first subscriber and closed when the
last one leaves.
"""
from __future__ import annotations

import asyncio

import aiohttp
from aiohttp import web

from homeassistant.components.camera import Camera
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LOGGER
from .coordinator import MakeraConfigEntry
from .entity import MakeraEntity
from .protocol import CAMERA_START, camera_url

JPEG = b"\xff\xd8"
TIMEOUT = 8


class CameraFeed:
    """One WebSocket to the machine, fanned out to any number of subscribers (latest frames only)."""

    def __init__(self, hass: HomeAssistant, url: str) -> None:
        self._hass, self._url = hass, url
        self._subscribers: set[asyncio.Queue[bytes | None]] = set()
        self._task: asyncio.Task | None = None

    def subscribe(self) -> asyncio.Queue[bytes | None]:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=2)
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._task = self._hass.async_create_background_task(self._run(), "makera_z1 camera feed")
        return queue

    def unsubscribe(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._subscribers.discard(queue)
        if not self._subscribers and self._task and not self._task.done():
            self._task.cancel()

    def _publish(self, frame: bytes | None) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                queue.get_nowait()  # drop the oldest frame for slow viewers
            queue.put_nowait(frame)

    async def _run(self) -> None:
        session = async_get_clientsession(self._hass)
        try:
            async with session.ws_connect(self._url, timeout=aiohttp.ClientWSTimeout(ws_receive=TIMEOUT),
                                          heartbeat=None, max_msg_size=0) as ws:
                await ws.send_str(CAMERA_START)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.BINARY and msg.data[:2] == JPEG:
                        self._publish(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            LOGGER.debug("Makera camera feed ended: %s", err)
        # reached on a normal end or a connection error (not when cancelled): tell viewers the feed is gone
        self._publish(None)


async def async_setup_entry(hass: HomeAssistant, entry: MakeraConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([MakeraCamera(entry.runtime_data)])


class MakeraCamera(MakeraEntity, Camera):
    _attr_frame_interval = 0.1

    def __init__(self, coordinator) -> None:
        MakeraEntity.__init__(self, coordinator, "camera")
        Camera.__init__(self)
        self.content_type = "image/jpeg"
        self._feed = CameraFeed(coordinator.hass, camera_url(coordinator.config_entry.data[CONF_HOST]))

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        queue = self._feed.subscribe()
        try:
            async with asyncio.timeout(TIMEOUT):
                return await queue.get()
        except TimeoutError:
            LOGGER.debug("Makera camera: no frame within %s s", TIMEOUT)
            return None
        finally:
            self._feed.unsubscribe(queue)

    async def handle_async_mjpeg_stream(self, request: web.Request) -> web.StreamResponse | None:
        response = web.StreamResponse()
        response.content_type = "multipart/x-mixed-replace;boundary=frame"
        await response.prepare(request)
        queue = self._feed.subscribe()
        try:
            while (frame := await asyncio.wait_for(queue.get(), TIMEOUT)) is not None:
                await response.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
        except (aiohttp.ClientError, TimeoutError, ConnectionResetError) as err:
            LOGGER.debug("Makera camera stream ended: %s", err)
        finally:
            self._feed.unsubscribe(queue)
        return response
