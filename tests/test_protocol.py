"""Tests for the read-only Makera Z1 protocol (no Home Assistant needed).

Run: python -m pytest tests
"""
import asyncio
import importlib.util
import pathlib
import sys

import pytest

# load protocol.py directly: the package __init__ imports Home Assistant
_spec = importlib.util.spec_from_file_location(
    "makera_protocol", pathlib.Path(__file__).parent.parent / "custom_components/makera_z1/protocol.py")
P = importlib.util.module_from_spec(_spec)
sys.modules["makera_protocol"] = P
_spec.loader.exec_module(P)

# Real answer of the Z1 on 2026-11-10 (idle)
IDLE = ("<Idle|MPos:-1.0000,-1.0000,-1.0000,0.0000,0.0000|WPos:184.5250,187.4570,88.7022,-90.0000,0.0000"
        "|F:0.0,2000.0,100.0|S:0.0,10000.0,100.0,0,22.1,23.7,0,0,0,0|T:1,-3.959,-1|L:0, 0, 0, 0.0,100.0"
        "|C:3,1,0,1|E:0,0,0,772,7610|OTA:0,0>")


def test_status_frame_matches_live_capture():
    assert P.build_frame(0xA1, b"?") == bytes.fromhex("86680004a13f353355aa")


def test_progress_frame_matches_live_capture():
    assert P.build_frame(0xA2, b"progress") == bytes.fromhex("8668000ba270726f677265737359 4855aa".replace(" ", ""))


@pytest.mark.parametrize("ftype,payload", [
    (0xA1, b"\x18"), (0xA1, b"!"), (0xA1, b"~"), (0xA2, b"G0 X0"), (0xA2, b"play /sd/a.nc"),
    (0xA2, b"reset"), (0xA2, b"abort"), (0xA2, b"progress\n"), (0xF1, b""), (0xB0, b"x"),
])
def test_everything_else_is_refused(ftype, payload):
    with pytest.raises(ValueError):
        P.build_frame(ftype, payload)


def _frame(ftype, payload):
    body = (len(payload) + 3).to_bytes(2, "big") + bytes([ftype]) + payload
    return P.HEADER + body + P.crc16_xmodem(body).to_bytes(2, "big") + P.FOOTER


def test_reader_splits_frames_and_skips_junk_and_bad_crc():
    good = _frame(0x81, IDLE.encode())
    bad = bytearray(_frame(0x90, b"broken"))
    bad[-3] ^= 0xFF
    stream = b"\x00junk" + good + bytes(bad) + _frame(0x90, b"ok")
    r = P.FrameReader()
    out = []
    for i in range(0, len(stream), 7):  # arrives in small chunks
        out += r.feed(stream[i:i + 7])
    assert out == [(0x81, IDLE.encode()), (0x90, b"ok")]


def test_parse_idle_status():
    s = P.parse_status(IDLE)
    assert s.state == "idle"
    assert s.value("WPos", 2) == pytest.approx(88.7022)
    assert s.value("S", 0) == 0.0 and s.value("S", 4) == pytest.approx(22.1)
    assert s.value("T", 0) == 1
    assert s.model == "Z1"
    assert s.halt_reason is None
    assert s.value("P", 1) is None


def test_parse_running_and_alarm():
    s = P.parse_status("<Run|WPos:1,2,3,0,0|F:850.0,1000.0,100.0|S:12000.0,12000.0,100.0,1,35.0,30.0|P:120,42,3600>")
    assert s.state == "run" and s.value("P", 1) == 42 and s.value("P", 2) == 3600
    a = P.parse_status("<Alarm|H:11|C:4>")
    assert a.state == "alarm" and a.halt_reason == "cover_open" and a.model == "Z1 Pro"
    assert P.parse_status("<Weird|C:3>").state == "unknown"


def test_parse_progress_variants():
    assert P.parse_progress("Not currently playing\r\n") == P.Progress()
    p = P.parse_progress("file: /sd/gcodes/Schild.nc, 42 % complete, elapsed time: 01:02:03, est time: 00:10:00\r\n")
    assert (p.file, p.percent, p.elapsed, p.remaining) == ("Schild.nc", 42, 3723, 600)
    p = P.parse_progress("file: /sd/a.nc, 5 % complete, elapsed time: 00:00:09\r\n")
    assert p.remaining is None and p.percent == 5
    p = P.parse_progress("SD print is paused at 250/1000\r\n")
    assert p.paused and p.percent == 25


def test_reader_finds_frame_after_false_header():
    good = _frame(0x81, b"<Idle>")
    stream = P.HEADER + b"\x00\x05\x90xx" + good  # a fake header whose "frame" swallows the real one
    assert P.FrameReader().feed(stream) == [(0x81, b"<Idle>")]


def test_h0_is_no_alarm():
    assert P.parse_status("<Idle|H:0>").halt_reason is None


def test_camera_url():
    assert P.camera_url("192.168.1.50") == "ws://192.168.1.50:82/ws_video"
    assert P.camera_url("fe80::1") == "ws://[fe80::1]:82/ws_video"


def test_progress_garbage_is_empty():
    assert P.parse_progress("\x00\xffwhatever") == P.Progress()


def test_client_against_fake_machine():
    received = bytearray()

    async def run():
        async def handle(reader, writer):
            data = await reader.read(64)
            received.extend(data)
            if data == P.build_frame(0xA1, b"?"):
                writer.write(_frame(0x81, IDLE.encode()))
            else:  # progress answer split over two frames
                writer.write(_frame(0x90, b"file: /sd/x.nc, 10 % complete, ") + _frame(0x90, b"elapsed time: 00:01:00\r\n"))
            await writer.drain()
            await asyncio.sleep(1)
            writer.close()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        c = P.MakeraClient("127.0.0.1", port, timeout=2)
        status, progress = await c.status(), await c.progress()
        server.close()
        return status, progress
    status, progress = asyncio.run(run())
    assert status.state == "idle"
    assert (progress.file, progress.percent, progress.elapsed) == ("x.nc", 10, 60)
    # the machine saw exactly the two read-only requests and nothing else
    assert bytes(received) == P.build_frame(0xA1, b"?") + P.build_frame(0xA2, b"progress")


def test_chatty_machine_cannot_hold_the_client():
    async def run():
        async def handle(reader, writer):
            await reader.read(64)
            try:
                while True:  # floods progress frames without pause
                    writer.write(_frame(0x90, b"spam "))
                    await writer.drain()
                    await asyncio.sleep(0.01)
            except (ConnectionError, OSError):
                pass
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        start = loop.time()
        await P.MakeraClient("127.0.0.1", port, timeout=1).progress()
        elapsed = loop.time() - start
        server.close()
        return elapsed
    assert asyncio.run(run()) < 1.5


def test_client_unreachable_raises():
    with pytest.raises(P.MakeraError):
        asyncio.run(P.MakeraClient("127.0.0.1", 1, timeout=1).status())
