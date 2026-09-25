"""Small synthetic tests; none launches OpenTTD."""

import asyncio
import struct
from types import SimpleNamespace

import pytest

from prototype.live_admin.lab_seam import dedicated_arguments
from prototype.live_admin.protocol import (
    Date,
    ServerProtocol,
    check_error,
    frame,
    parse,
    receive,
)
from prototype.live_admin.run import connect


def test_signed_economy_and_statistics():
    payload = struct.pack(
        "<BqqqHqHHqHH", 0, -50, 100000, -2500, 65535, 500000, 100, 42, 400000, 80, 10
    )
    economy = parse(117, payload + b"future extension")
    assert (economy.money, economy.loan, economy.income) == (-50, 100000, -2500)
    assert economy.quarters[1].value == 400000
    stats = parse(118, struct.pack("<B10H", 0, *range(1, 11)))
    assert stats.vehicles == (1, 2, 3, 4, 5)
    assert stats.stations == (6, 7, 8, 9, 10)
    with pytest.raises(struct.error):
        parse(117, payload[:-1])


def test_handshake_info_and_date():
    assert parse(103, b"\x02\x01\x03\x00\x3d\x00\x00") == ServerProtocol(2, {3: 61})
    welcome = parse(
        104, b"lab\0" + b"13.4\0\x01\0" + struct.pack("<IBIHH", 17, 0, 712223, 256, 256)
    )
    assert welcome.revision == "13.4" and welcome.seed == 17
    info = parse(
        114,
        b"\0Road Co\0Manager\0"
        + struct.pack("<B?I?B4B", 3, False, 1950, True, 0, 255, 255, 255, 255),
    )
    assert info.is_ai and info.share_owners == (255,) * 4
    assert Date(712223).iso == "1950-01-01"
    assert parse(250, b"arbitrary extension") is None
    with pytest.raises(RuntimeError, match="rejected"):
        check_error(102, b"\x03")


def test_fragmented_coalesced_frames_eof_and_invalid_length():
    async def exercise():
        reader = asyncio.StreamReader()
        wire = frame(107, struct.pack("<I", 712223)) + frame(250, b"unknown")
        task = asyncio.create_task(receive(reader))
        for byte in wire:
            reader.feed_data(bytes([byte]))
            await asyncio.sleep(0)
        assert await task == (107, struct.pack("<I", 712223))
        assert await receive(reader) == (250, b"unknown")
        reader.feed_eof()
        with pytest.raises(asyncio.IncompleteReadError):
            await receive(reader)
        bad = asyncio.StreamReader()
        bad.feed_data(b"\x02\0")
        with pytest.raises(ValueError):
            await receive(bad)

    asyncio.run(exercise())


def test_connection_failure_and_cancellation():
    async def exercise():
        with pytest.raises(RuntimeError, match="exited"):
            await connect(1, SimpleNamespace(returncode=1))
        with pytest.raises(TimeoutError):
            await connect(1, SimpleNamespace(returncode=None), timeout=0.01)
        task = asyncio.create_task(connect(1, SimpleNamespace(returncode=None)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


def test_launch_preserves_seed_and_config(monkeypatch):
    monkeypatch.setenv("PROTOTYPE_GAME_PORT", "45678")
    args = dedicated_arguments(
        ("openttd", "-g", "-G", "17", "-vnull:ticks=8880", "-c", "/tmp/example.cfg")
    )
    assert "-vnull:ticks=8880" not in args
    assert args[args.index("-G") + 1] == "17"
    assert args[args.index("-c") + 1] == "/tmp/example.cfg"
    assert "-D127.0.0.1:45678" in args


def test_worker_seam_restores_subprocess(monkeypatch):
    from prototype.live_admin import lab_seam

    original = lab_seam.openttdlab.subprocess

    def fake_experiment(*args):
        assert lab_seam.openttdlab.subprocess.STDOUT == original.STDOUT
        assert lab_seam.openttdlab.subprocess.check_output == lab_seam.dedicated_check_output
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(lab_seam, "STOCK_RUN_EXPERIMENT", fake_experiment)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        lab_seam.run_dedicated_experiment()
    assert lab_seam.openttdlab.subprocess is original


@pytest.mark.parametrize("reject", [True, False])
def test_listener_closes_socket_on_rejection_or_cancellation(monkeypatch, tmp_path, reject):
    from prototype.live_admin import run

    monkeypatch.setattr(run, "OUTPUT", tmp_path)

    async def exercise():
        joined = asyncio.Event()
        closed = asyncio.Event()

        async def server(reader, writer):
            try:
                assert (await receive(reader))[0] == 0
                joined.set()
                if reject:
                    writer.write(frame(102, b"\x03"))
                    await writer.drain()
                await reader.read()  # EOF after listener's AdminQuit / socket close
            finally:
                writer.close()
                await writer.wait_closed()
                closed.set()

        async with await asyncio.start_server(server, "127.0.0.1", 0) as service:
            port = service.sockets[0].getsockname()[1]
            evidence = {}
            task = asyncio.create_task(
                run.listen(
                    port, "synthetic-test-password", SimpleNamespace(returncode=None), evidence
                )
            )
            await asyncio.wait_for(joined.wait(), 1)
            if not reject:
                task.cancel()
            with pytest.raises(RuntimeError if reject else asyncio.CancelledError):
                await task
            await asyncio.wait_for(closed.wait(), 1)
            assert evidence["socket_closed"] is True

    asyncio.run(exercise())
