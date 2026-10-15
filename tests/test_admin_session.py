"""Controlled stream tests for the owned read-only Admin session."""

import asyncio
import struct
from unittest.mock import AsyncMock, Mock

import pytest

from app.simulation.openttd.admin_protocol import (
    AdminProtocolError,
    encode_admin_ping,
    encode_admin_quit,
)
from app.simulation.openttd.admin_session import AdminSession, AdminSessionStopped


def _writer():
    writer = Mock(spec=asyncio.StreamWriter)
    writer.is_closing.return_value = False
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    return writer


@pytest.mark.parametrize("bad_id", [4, 5, 6, 8, 100, 255])
def test_session_rejects_gameplay_packets_before_any_write(bad_id: int) -> None:
    async def scenario() -> None:
        writer = _writer()
        session = AdminSession(asyncio.StreamReader(), writer)
        with pytest.raises(AdminProtocolError, match="not read-only"):
            await session.send(encode_admin_ping(42), struct.pack("<HB", 3, bad_id))
        writer.write.assert_not_called()
        await session.close()
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["none", "write", "drain", "wait_closed", "cancel_drain"])
def test_close_is_idempotent_even_when_quit_or_close_fails(failure: str) -> None:
    async def scenario() -> None:
        writer = _writer()
        if failure == "write":
            writer.write.side_effect = OSError("disconnected")
        elif failure == "drain":
            writer.drain.side_effect = OSError("disconnected")
        elif failure == "wait_closed":
            writer.wait_closed.side_effect = OSError("disconnected")
        elif failure == "cancel_drain":
            writer.drain.side_effect = asyncio.CancelledError
        session = AdminSession(asyncio.StreamReader(), writer)
        if failure == "cancel_drain":
            with pytest.raises(asyncio.CancelledError):
                await session.close(quit=True)
        else:
            await session.close(quit=True)
        await session.close(quit=True)
        writer.write.assert_called_once_with(encode_admin_quit())
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
        with pytest.raises(AdminProtocolError, match="closed"):
            await session.send(encode_admin_ping(1))

    asyncio.run(scenario())


def test_stop_interrupts_pending_read_and_reaps_read_task() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        entered = asyncio.Event()
        finished = asyncio.Event()
        session = AdminSession(asyncio.StreamReader(), _writer())

        async def read(reader: asyncio.StreamReader, timeout: float) -> bytes:
            entered.set()
            try:
                return await reader.read(4096)
            finally:
                finished.set()

        task = asyncio.create_task(session.read(read, 10, stop))
        await entered.wait()
        stop.set()
        with pytest.raises(AdminSessionStopped):
            await task
        assert finished.is_set()
        await session.close()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(scenario())


def test_cancelling_read_reaps_stop_waiter_and_reader_task() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        finished = asyncio.Event()
        session = AdminSession(asyncio.StreamReader(), _writer())

        async def read(reader: asyncio.StreamReader, timeout: float) -> bytes:
            entered.set()
            try:
                return await reader.read(4096)
            finally:
                finished.set()

        task = asyncio.create_task(session.read(read, 10, asyncio.Event()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        await session.close()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(scenario())
