"""One owned Admin TCP stream; read-only writes and deterministic cleanup."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, Self

from app.simulation.openttd.admin_protocol import (
    AdminProtocolError,
    encode_admin_quit,
    validate_admin_client_frame,
)


class AdminWriter(Protocol):
    def write(self, data: bytes, /) -> None: ...
    async def drain(self) -> None: ...
    def close(self) -> None: ...
    async def wait_closed(self) -> None: ...
    def is_closing(self) -> bool: ...
    def get_extra_info(self, name: str) -> object: ...


class AdminSessionStopped(Exception):
    """The caller requested graceful shutdown while a read was pending."""


class AdminStream:
    """Shared owned TCP stream; concrete sessions supply their outbound policy."""

    def validate_outbound(self, frame: bytes) -> None:
        raise NotImplementedError("A concrete Admin session must supply its write policy")

    def __init__(self, reader: asyncio.StreamReader, writer: AdminWriter) -> None:
        self.reader = reader
        self._writer = writer
        self._closed = False

    @classmethod
    async def connect(cls, host: str, port: int, timeout: float) -> Self:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        return cls(reader, writer)

    @property
    def peername(self) -> object:
        return self._writer.get_extra_info("peername")

    def encode_outbound(self, frame: bytes) -> bytes:
        """Wire hook; plaintext observer behavior is unchanged."""
        return frame

    async def receive(self, size: int = 4096) -> bytes:
        return await self.reader.read(size)

    async def send(self, *frames: bytes) -> None:
        if self._closed:
            raise AdminProtocolError("Admin session is closed")
        for frame in frames:
            self.validate_outbound(frame)
        for frame in frames:
            self._writer.write(self.encode_outbound(frame))
        await self._writer.drain()

    async def read(
        self,
        read: Callable[[asyncio.StreamReader, float], Awaitable[bytes]],
        timeout: float,
        stop: asyncio.Event | None = None,
    ) -> bytes:
        if stop is None:
            return await read(self.reader, timeout)
        if stop.is_set():
            raise AdminSessionStopped
        reading = asyncio.ensure_future(read(self.reader, timeout))
        stopping = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait((reading, stopping), return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                raise AdminSessionStopped
            return reading.result()
        finally:
            for task in (reading, stopping):
                if not task.done():
                    task.cancel()
            await asyncio.gather(reading, stopping, return_exceptions=True)

    async def close(self, *, quit: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if quit and not self._writer.is_closing():
                try:
                    self._writer.write(self.encode_outbound(encode_admin_quit()))
                    await asyncio.wait_for(self._writer.drain(), 1.0)
                except OSError, TimeoutError:
                    pass
        finally:
            self._writer.close()
            try:
                await asyncio.wait_for(self._writer.wait_closed(), 1.0)
            except OSError, TimeoutError:
                pass


class AdminSession(AdminStream):
    """P04 read-only policy; GameScript and gameplay packets remain forbidden."""

    def validate_outbound(self, frame: bytes) -> None:
        validate_admin_client_frame(frame)
