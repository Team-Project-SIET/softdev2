"""Future industry backend: inherited owned runtime, one secure connection/query."""

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
from app.simulation.openttd.industry_cargo import IndustryCargoReceipt
from app.simulation.openttd.secure_admin import SecureAdminSession

from .cargo_contract import CARGO_REQUEST
from .cargo_evidence import parse_cargo_proof_evidence
from .industry_native import owned_admin_listener
from .native import NativeBackend


class CargoRecordedSession(GameScriptSession):
    def __init__(self, session):
        super().__init__(session.reader, session._writer)
        self.session = session
        self.sent = self.responses = 0
        self.packets: list[dict] = []
        self.events: list[str] = []
        self.decoder = AdminFrameDecoder()
        self.response_payload: bytes | None = None
        self.receipt: IndustryCargoReceipt | None = None

    async def send(self, *frames):
        for frame in frames:
            if frame[2] == ADMIN_GAMESCRIPT:
                if self.sent or decode_gamescript(frame[3:]) != CARGO_REQUEST.to_bytes():
                    raise ValueError(
                        "Exactly one frozen industry-cargo request; no other query/retry"
                    )
                self.sent += 1
                self.events.append("INDUSTRY_CARGO_REQUEST_SENT")
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
                if self.responses != 1 or self.events != ["INDUSTRY_CARGO_REQUEST_SENT"]:
                    raise ValueError("Duplicate/unrequested industry response")
                # Retain observed bytes even if protocol/semantic validation fails later.
                self.response_payload = body[:-1] if body.endswith(b"\0") else body
                self.events.append("INDUSTRY_CARGO_RESPONSE_RECEIVED")
                payload = decode_gamescript(body)
                self.receipt = IndustryCargoReceipt.correlate_transport(
                    CARGO_REQUEST.to_bytes(), payload
                )
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
            request_sha256=hashlib.sha256(CARGO_REQUEST.to_bytes()).hexdigest(),
            response_sha256=None
            if self.response_payload is None
            else hashlib.sha256(self.response_payload).hexdigest(),
        )


class CargoNativeBackend(NativeBackend):
    def __init__(self, *, authorized_one_launch=False):
        super().__init__(authorized_one_launch=authorized_one_launch)
        self._connection_claimed = False
        self.cargo_session: CargoRecordedSession | None = None

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
        if prepared.request != CARGO_REQUEST or self.session is None:
            raise ValueError("Frozen industry-cargo preparation required")
        self.cargo_session = CargoRecordedSession(self.session)
        self.transport = GameScriptTransport(self.cargo_session, protocol)

    async def ping(self, request):
        raise ValueError("No ping application request in industry proof")

    async def industry_cargo(self, request):
        if self._sent or request != CARGO_REQUEST:
            raise ValueError("Exactly one frozen cargo query; no retry")
        self._sent = True
        assert self.transport is not None and self.cargo_session is not None
        exchange = await self.transport.industry_cargo(request, timeout=15)
        exchange.validate()
        self.cargo_session.events.append("CAPABILITY_VALIDATED")
        return exchange

    async def wait_cargo(self, prepared, *, complete):
        deadline = time.monotonic() + 10
        while True:
            self.health()
            evidence = parse_cargo_proof_evidence(
                prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
            )
            if len(evidence.ordered_sequence) == (5 if complete else 1):
                return evidence
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit industry GameScript evidence deadline")
            await asyncio.sleep(0.01)

    def cargo_network_evidence(self):
        return {} if self.cargo_session is None else self.cargo_session.snapshot()

    def cargo_response_payload(self):
        return None if self.cargo_session is None else self.cargo_session.response_payload

    def cargo_receipt(self):
        return None if self.cargo_session is None else self.cargo_session.receipt
