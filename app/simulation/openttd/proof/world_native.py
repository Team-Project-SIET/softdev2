"""World-info backend sharing the proven secure native startup and lifecycle."""

import asyncio
import hashlib
import struct
import time

from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
)
from app.simulation.openttd.world_info import WorldInfoResponse
from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

from .harness import WORLD_REQUEST
from .native import NativeBackend


class WorldRecordedSession(GameScriptSession):
    """Sanitized post-auth packet metadata; application sends and responses are unique."""

    def __init__(self, session):
        super().__init__(session.reader, session._writer)
        self.session = session
        self.sent = 0
        self.responses = 0
        self.packets: list[dict] = []
        self.events: list[str] = []
        self.decoder = AdminFrameDecoder()

    def record(self, direction, frame):
        self.packets.append(
            {
                "record": len(self.packets) + 1,
                "direction": direction,
                "packet_type": frame[2],
                "sha256": hashlib.sha256(frame).hexdigest(),
            }
        )

    async def send(self, *frames):
        for frame in frames:
            if frame[2] == ADMIN_GAMESCRIPT:
                if self.sent or decode_gamescript(frame[3:]) != WORLD_REQUEST.to_bytes():
                    raise ValueError("Second/different world-info request prohibited")
                self.sent += 1
        await self.session.send(*frames)
        for frame in frames:
            self.record("outbound", frame)
            if frame[2] == ADMIN_GAMESCRIPT:
                self.events.append("WORLD_INFO_REQUEST_SENT")

    async def receive(self, size=4096):
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            self.record("inbound", struct.pack("<HB", len(body) + 3, kind) + body)
            if kind == SERVER_GAMESCRIPT:
                response = WorldInfoResponse.parse(decode_gamescript(body))
                if (
                    self.events != ["WORLD_INFO_REQUEST_SENT"]
                    or response.request_id != WORLD_REQUEST.request_id
                ):
                    raise ValueError("Duplicate/uncorrelated world-info response")
                self.responses += 1
                self.events.append("WORLD_INFO_RESPONSE_RECEIVED")
        return raw

    async def close(self, *, quit=False):
        await self.session.close(quit=quit)


class WorldNativeBackend(NativeBackend):
    def configure_transport(self, prepared, protocol):
        if prepared.request != WORLD_REQUEST or self.session is None:
            raise ValueError("Frozen world-info preparation required")
        self.world_session = WorldRecordedSession(self.session)
        self.transport = GameScriptTransport(self.world_session, protocol)

    @property
    def welcome(self):
        if self.session is None or self.session.welcome is None:
            raise ValueError("Independent encrypted SERVER_WELCOME unavailable")
        return self.session.welcome

    async def world_info(self, request):
        if self._sent or request != WORLD_REQUEST:
            raise ValueError("Exactly one frozen world-info request; no retry")
        self._sent = True
        assert self.transport is not None
        exchange = await self.transport.world_info(request, timeout=15)
        if self.world_session.events != ["WORLD_INFO_REQUEST_SENT", "WORLD_INFO_RESPONSE_RECEIVED"]:
            raise ValueError("World-info network ordering invalid")
        self.world_session.events.append("TRANSPORT_RECEIPT_CREATED")
        return exchange

    def world_network_evidence(self):
        return {
            "ordered_sequence": list(self.world_session.events),
            "packets": self.world_session.packets,
            "requests_sent": self.world_session.sent,
            "matching_responses": self.world_session.responses,
            "retries": 0,
        }

    async def wait_world(self, prepared, *, complete):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            evidence = parse_world_info_evidence(
                prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
            )
            if len(evidence.ordered_sequence) == (5 if complete else 1):
                return evidence
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit world-info GameScript evidence deadline")
            # Observation pacing only; a complete native record is the condition.
            await asyncio.sleep(0.01)
