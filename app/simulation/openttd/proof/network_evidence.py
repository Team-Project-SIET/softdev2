"""Proof-only observer over production Admin streams; no cryptographic changes."""

import asyncio
import hashlib
import struct

from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_ping
from app.simulation.openttd.gamescript_protocol import Ack, CommunicationReceipt, PingRequest
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    decode_gamescript,
)

from .causality import NetworkPacketRecord, NetworkProofEvidence


class RecordedProofSession(GameScriptSession):
    """Delegate all I/O/security to the supplied production session.

    Capture only post-authentication packet metadata and public ping/ACK payloads.
    The completion AdminPing/Pong barrier drains packets queued after the ACK,
    rejecting duplicates without another application request or a timed sleep.
    """

    def __init__(self, session: GameScriptSession, request: PingRequest):
        super().__init__(session.reader, session._writer)
        self.session = session
        self.request = request
        self.events: list[str] = []
        self.packets: list[NetworkPacketRecord] = []
        self.response: bytes | None = None
        self.receipt: CommunicationReceipt | None = None
        self.send_attempts = 0
        self.sent = 0
        self.acks = 0
        self.decoder = AdminFrameDecoder()
        self._finished = False

    def _record(self, direction: str, frame: bytes) -> None:
        self.packets.append(
            NetworkPacketRecord(
                len(self.packets) + 1, direction, frame[2], hashlib.sha256(frame).hexdigest()
            )
        )

    async def send(self, *frames: bytes) -> None:
        for frame in frames:
            if frame[2] == ADMIN_GAMESCRIPT:
                self.send_attempts += 1
                if self.send_attempts != 1:
                    raise ValueError("Second application request/retry prohibited")
                if decode_gamescript(frame[3:]) != self.request.to_bytes():
                    raise ValueError("Application request differs from frozen canonical bytes")
        await self.session.send(*frames)
        for frame in frames:
            self._record("outbound", frame)
            if frame[2] == ADMIN_GAMESCRIPT:
                self.sent += 1
                self.events.append("REQUEST_SENT")

    async def receive(self, size: int = 4096) -> bytes:
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            frame = struct.pack("<HB", len(body) + 3, kind) + body
            self._record("inbound", frame)
            if kind == SERVER_GAMESCRIPT:
                if self.sent != 1:
                    raise ValueError("Network ACK precedes application request")
                payload = decode_gamescript(body)
                ack = Ack.parse(payload)
                if ack.request_id != self.request.request_id:
                    raise ValueError("Network ACK request ID mismatch")
                self.acks += 1
                if self.acks != 1:
                    raise ValueError("Duplicate matching network ACK")
                self.response = payload
                self.events.append("NETWORK_ACK_RECEIVED")
        return raw

    async def finish(self, receipt: CommunicationReceipt) -> NetworkProofEvidence:
        if self._finished:
            raise ValueError("Network proof completion cannot be retried")
        self._finished = True
        self.receipt = receipt
        self.events.append("RECEIPT_CREATED")
        self.snapshot().validate_chain()
        token = 0x154
        decoder = AdminFrameDecoder()
        async with asyncio.timeout(5):
            await self.send(encode_admin_ping(token))
            while True:
                raw = await self.receive()
                if not raw:
                    raise ValueError("Admin disconnect before completion barrier")
                frames = decoder.feed_frames(raw)
                for kind, body in frames:
                    if kind == 126:
                        if body != struct.pack("<I", token):
                            raise ValueError("Unexpected completion barrier token")
                        return self.snapshot()
                    raise ValueError("Unexpected packet before completion barrier")

    def snapshot(self) -> NetworkProofEvidence:
        return NetworkProofEvidence(
            self.request.to_bytes(),
            self.response,
            self.receipt,
            tuple(self.events),
            self.sent,
            self.acks,
            max(0, self.send_attempts - 1),
            tuple(self.packets),
        )

    async def close(self, *, quit: bool = False) -> None:
        await self.session.close(quit=quit)
