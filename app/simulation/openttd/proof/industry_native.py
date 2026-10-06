"""Future industry backend: inherited owned runtime, one secure connection/query."""

import asyncio
import hashlib
import os
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
from app.simulation.openttd.industry_page import IndustryPageReceipt
from app.simulation.openttd.secure_admin import SecureAdminSession
from app.simulation.openttd.world_info import WorldInfoResponse

from .industry_contract import INDUSTRY_REQUEST
from .industry_evidence import parse_industry_proof_evidence
from .native import NativeBackend


class IndustryRecordedSession(GameScriptSession):
    def __init__(self, session):
        super().__init__(session.reader, session._writer)
        self.session = session
        self.sent = self.responses = 0
        self.packets: list[dict] = []
        self.events: list[str] = []
        self.decoder = AdminFrameDecoder()
        self.response_payload: bytes | None = None
        self.receipt: IndustryPageReceipt | None = None

    async def send(self, *frames):
        for frame in frames:
            if frame[2] == ADMIN_GAMESCRIPT:
                if self.sent or decode_gamescript(frame[3:]) != INDUSTRY_REQUEST.to_bytes():
                    raise ValueError(
                        "Exactly one frozen industry-page request; no other query/retry"
                    )
                self.sent += 1
                self.events.append("INDUSTRY_PAGE_REQUEST_SENT")
        await self.session.send(*frames)
        for frame in frames:
            self._record("outbound", frame[2], frame[3:])

    def _record(self, direction, kind, body):
        frame = struct.pack("<HB", len(body) + 3, kind) + body
        self.packets.append(
            dict(
                record=len(self.packets) + 1,
                direction=direction,
                packet_type=kind,
                sha256=hashlib.sha256(frame).hexdigest(),
            )
        )

    async def receive(self, size=4096):
        raw = await self.session.receive(size)
        for kind, body in self.decoder.feed_frames(raw):
            self._record("inbound", kind, body)
            if kind == SERVER_GAMESCRIPT:
                self.responses += 1
                if self.responses != 1 or self.events != ["INDUSTRY_PAGE_REQUEST_SENT"]:
                    raise ValueError("Duplicate/unrequested industry response")
                # Retain observed bytes even if protocol/semantic validation fails later.
                self.response_payload = body[:-1] if body.endswith(b"\0") else body
                self.events.append("INDUSTRY_PAGE_RESPONSE_RECEIVED")
                payload = decode_gamescript(body)
                self.receipt = IndustryPageReceipt.correlate(INDUSTRY_REQUEST.to_bytes(), payload)
                self.events.append("TRANSPORT_RECEIPT_CREATED")
        return raw

    async def close(self, *, quit=False):
        await self.session.close(quit=quit)

    def snapshot(self):
        return dict(
            ordered_sequence=list(self.events),
            packets=self.packets,
            requests_sent=self.sent,
            matching_responses=self.responses,
            retries=0,
            request_sha256=hashlib.sha256(INDUSTRY_REQUEST.to_bytes()).hexdigest(),
            response_sha256=None
            if self.response_payload is None
            else hashlib.sha256(self.response_payload).hexdigest(),
        )


def owned_admin_listener(pid: int, port: int) -> bool:
    """Read /proc, never connect as a readiness probe. Match loopback listener inode to child."""
    owned = set()
    for fd in (os.path.join("/proc", str(pid), "fd"),):
        for name in os.listdir(fd):
            try:
                link = os.readlink(os.path.join(fd, name))
                if link.startswith("socket:["):
                    owned.add(link[8:-1])
            except OSError:
                continue
    with open("/proc/net/tcp") as table:
        return any(
            columns[1] == f"0100007F:{port:04X}" and columns[3] == "0A" and columns[9] in owned
            for line in table.readlines()[1:]
            if len(columns := line.split()) >= 10
        )


class IndustryNativeBackend(NativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self._connection_claimed = False
        self.industry_session: IndustryRecordedSession | None = None

    @property
    def welcome(self):
        if self.session is None or self.session.welcome is None:
            raise ValueError("Independent encrypted SERVER_WELCOME unavailable")
        return self.session.welcome

    async def authenticate(self, prepared, gates):
        if self._connection_claimed or self.session is not None:
            raise ValueError("One Admin connection only; no auth retry")
        deadline = time.monotonic() + 30
        while True:
            self.health()
            assert self.process is not None
            if owned_admin_listener(self.process.pid, prepared.endpoints[1]):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Owned Admin listener readiness deadline")
            await asyncio.sleep(0.01)
        self._connection_claimed = True
        if self._key is None:
            raise ValueError("Preflight credentials missing")
        self.session = await SecureAdminSession.connect_secure(
            "127.0.0.1", prepared.endpoints[1], 5, key=self._key
        )
        # Inherited authentication now sees an existing session: no connect/probe loop.
        return await super().authenticate(prepared, gates)

    def configure_transport(self, prepared, protocol):
        if prepared.request != INDUSTRY_REQUEST or self.session is None:
            raise ValueError("Frozen industry-page preparation required")
        self.industry_session = IndustryRecordedSession(self.session)
        self.transport = GameScriptTransport(self.industry_session, protocol)

    async def ping(self, request):
        raise ValueError("No ping application request in industry proof")

    async def industry_page(self, request):
        if self._sent or request != INDUSTRY_REQUEST:
            raise ValueError("Exactly one frozen industry query; no retry")
        self._sent = True
        assert self.transport is not None and self.industry_session is not None
        world = WorldInfoResponse("admin-welcome-context", self.welcome.width, self.welcome.height)
        exchange = await self.transport.industry_page(request, world, timeout=15)
        exchange.validate(world)
        self.industry_session.events.append("PAGE_VALIDATED")
        return exchange

    async def wait_industry(self, prepared, *, complete):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            evidence = parse_industry_proof_evidence(
                prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
            )
            if len(evidence.ordered_sequence) == (5 if complete else 1):
                return evidence
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit industry GameScript evidence deadline")
            await asyncio.sleep(0.01)

    def industry_network_evidence(self):
        return {} if self.industry_session is None else self.industry_session.snapshot()

    def industry_response_payload(self):
        return None if self.industry_session is None else self.industry_session.response_payload

    def industry_receipt(self):
        return None if self.industry_session is None else self.industry_session.receipt
