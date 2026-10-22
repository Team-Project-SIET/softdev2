"""Single-use simulated lifecycle; no native connection, launch or authorization."""

import asyncio
import hashlib
import math
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from app.simulation.openttd.admin_protocol import (
    AdminClientPacketType,
    AdminFrameDecoder,
    ServerProtocol,
    ServerWelcome,
    decode_server_packet,
    encode_admin_quit,
)
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    decode_gamescript,
    gamescript_subscription,
)
from app.simulation.openttd.terrain_accounting import TerrainFrameBudget
from app.simulation.openttd.terrain_pagination import PaginationBudget
from app.simulation.openttd.terrain_paired_evidence import (
    verify_paired_package,
    write_paired_package,
)
from app.simulation.openttd.terrain_sweeps import (
    TerrainSweepContext,
    TerrainTwoSweep,
    TwoSweepBudget,
    VerifiedTerrainPair,
)
from app.simulation.openttd.tile_facts import TileFactsExchange
from app.simulation.openttd.tile_facts_evidence import parse_tile_facts_evidence


@dataclass(frozen=True)
class SimulatedRuntime:
    process_identity: str
    context: TerrainSweepContext
    alive: bool
    authenticated: bool
    encrypted: bool
    buffered_bytes: int


@dataclass(frozen=True)
class SimulatedConnection:
    session: GameScriptSession
    establishment: tuple[bytes, bytes]


@dataclass(frozen=True)
class SimulatedCleanup:
    reaped: bool
    connection_closed: bool
    listener_closed: bool
    credentials_disposed: bool
    errors: tuple[str, ...]


class SimulatedBackend(Protocol):
    """External simulation seam. Implementations must never open native resources."""

    mode: str
    session: GameScriptSession | None

    async def launch(self) -> None: ...
    async def connect(self) -> SimulatedConnection: ...
    def snapshot(self) -> SimulatedRuntime: ...
    async def page_evidence(self, exchange: TileFactsExchange) -> bytes: ...
    async def cleanup(self) -> SimulatedCleanup: ...


@dataclass(frozen=True)
class IntegrationLimits:
    """Selected controlled caps from the design; never measured native capacity."""

    post_auth_frames: int = 838
    simulated_stream_bytes: int = 838 * 32767
    buffered_bytes: int = 65536
    startup_seconds: float = 60.0
    page_seconds: float = 15.0
    evidence_seconds: float = 10.0
    session_seconds: float = 2660.0
    cleanup_seconds: float = 20.0
    finalization_seconds: float = 15.0

    def __post_init__(self):
        for value, ceiling in (
            (self.post_auth_frames, 838),
            (self.simulated_stream_bytes, 838 * 32767),
            (self.buffered_bytes, AdminFrameDecoder.MAX_FEED_BYTES),
        ):
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError("Invalid integration resource limit")
        for name, ceiling in (
            ("startup_seconds", 60),
            ("page_seconds", 15),
            ("evidence_seconds", 10),
            ("session_seconds", 2660),
            ("cleanup_seconds", 20),
            ("finalization_seconds", 15),
        ):
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 < value <= ceiling
            ):
                raise ValueError("Invalid integration deadline")


@dataclass(frozen=True)
class ControlledFrame:
    direction: str
    phase: str
    packet_type: int
    plaintext_bytes: int
    simulated_encrypted_bytes: int
    sha256: str


@dataclass(frozen=True)
class ControlledAccounting:
    post_auth_frames: int
    query_operations: int
    simulated_stream_bytes: int
    frames: tuple[ControlledFrame, ...]


@dataclass(frozen=True)
class ControlledIntegrationResult:
    pair: VerifiedTerrainPair
    descriptor_sha256: str
    accounting: ControlledAccounting
    states: tuple[str, ...]
    authentication: Literal["SIMULATED_ONLY"] = field(default="SIMULATED_ONLY", init=False)


class _ObservedSession(GameScriptSession):
    """Observe supplied plaintext frames. Adding 16 models overhead, not encryption."""

    def __init__(
        self, supplied: GameScriptSession, observe: Callable[[str, bytes], None], buffer_limit: int
    ):
        self.supplied = supplied
        self.observe = observe
        self.decoder = AdminFrameDecoder()
        self.buffer_limit = buffer_limit
        self.pending_bytes = 0
        self.closed = False
        self.expected: bytes | None = None
        self.sent = self.response_seen = self.ping_sent = self.pong_seen = False

    def expect(self, raw: bytes):
        self.expected = raw
        self.sent = self.response_seen = self.ping_sent = self.pong_seen = False

    async def send(self, *frames: bytes):
        if self.closed:
            raise ValueError("Simulated session closed; no retry")
        for frame in frames:
            self.validate_outbound(frame)
            if frame[2] == ADMIN_GAMESCRIPT:
                if (
                    self.sent
                    or self.expected is None
                    or decode_gamescript(frame[3:]) != self.expected
                ):
                    raise ValueError("Unplanned or repeated request")
                self.sent = True
            elif frame[2] == AdminClientPacketType.PING:
                token = 0x153 if self.expected is None else 0x154
                if self.ping_sent or frame[3:] != struct.pack("<I", token):
                    raise ValueError("Unexpected completion ping")
                self.ping_sent = True
            elif frame != gamescript_subscription() and frame != encode_admin_quit():
                raise ValueError("Unselected outbound packet")
            self.observe("outbound", frame)
        await self.supplied.send(*frames)

    async def receive(self, size: int = 4096) -> bytes:
        raw = await self.supplied.receive(size)
        if len(raw) + self.pending_bytes > self.buffer_limit:
            raise ValueError("Controlled receive buffer budget exhausted")
        self.pending_bytes += len(raw)
        frames = self.decoder.feed_wire_frames(raw)
        self.pending_bytes -= sum(len(frame) for frame in frames)
        for frame in frames:
            if frame[2] == SERVER_GAMESCRIPT:
                if not self.sent or self.response_seen or self.ping_sent:
                    raise ValueError("Duplicate, stale or unexpected response")
                self.response_seen = True
            elif frame[2] == 126:
                token = 0x153 if self.expected is None else 0x154
                if not self.ping_sent or self.pong_seen or frame[3:] != struct.pack("<I", token):
                    raise ValueError("Unexpected completion pong")
                self.pong_seen = True
            else:
                raise ValueError("Unselected inbound packet")
            self.observe("inbound", frame)
        return raw

    async def close(self, *, quit: bool = False):
        if not self.closed:
            if quit:
                await self.send(encode_admin_quit())
            self.closed = True
            await self.supplied.close()


class ControlledTerrainAcquisition:
    """Collect once, clean, then accept with explicit caller-pinned authority."""

    def __init__(
        self,
        context: TerrainSweepContext,
        *,
        per_sweep_budget: PaginationBudget = PaginationBudget(),
        combined_budget: TwoSweepBudget = TwoSweepBudget(),
        limits: IntegrationLimits = IntegrationLimits(),
        monotonic: Callable[[], float] = time.monotonic,
    ):
        limits.__post_init__()
        self._pair = TerrainTwoSweep(
            context, per_sweep_budget=per_sweep_budget, combined_budget=combined_budget
        )
        self._context, self._per, self._combined = context, per_sweep_budget, combined_budget
        self._limits, self._clock = limits, monotonic
        self._state = "PREPARED"
        self._collect_started = False
        self._states = [self._state]
        self._reason: str | None = None
        self._frames = TerrainFrameBudget()
        self._records: list[ControlledFrame] = []
        self._stream_bytes = 0
        self._session: _ObservedSession | None = None
        self._identity: str | None = None
        self._directory: Path | None = None
        self._accepted: VerifiedTerrainPair | None = None
        self._last_time: float | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def diagnostics(self) -> dict:
        return dict(
            state=self.state,
            reason=self._reason,
            states=tuple(self._states),
            exchanges=self._pair.progress["exchanges"],
        )

    def _move(self, state: str):
        self._state = state
        self._states.append(state)

    def _reject(self, reason: str):
        self._reason = reason
        if self.state != "REJECTED":
            self._move("REJECTED")

    def _now(self) -> float:
        value = self._clock()
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or (self._last_time is not None and value < self._last_time)
        ):
            raise ValueError("Invalid monotonic clock")
        self._last_time = value
        return value

    async def _wait[T](self, action: Callable[[], Awaitable[T]], deadline: float) -> T:
        remaining = deadline - self._now()
        if remaining <= 0:
            raise TimeoutError("Controlled session deadline expired")
        value = await asyncio.wait_for(action(), remaining)
        if self._now() >= deadline:
            raise TimeoutError("Controlled session deadline expired")
        return value

    def _health(self, backend: SimulatedBackend, *, quiescent: bool = False):
        if backend.mode != "CONTROLLED_SIMULATED":
            raise ValueError("Simulated backend identity changed")
        s = backend.snapshot()
        if (
            not isinstance(s, SimulatedRuntime)
            or s.context != self._context
            or type(s.alive) is not bool
            or not s.alive
            or not isinstance(s.process_identity, str)
            or not s.process_identity
            or (self._identity is not None and s.process_identity != self._identity)
            or type(s.buffered_bytes) is not int
            or not 0 <= s.buffered_bytes <= self._limits.buffered_bytes
        ):
            raise ValueError("Simulated process/world/buffer identity invalid")
        if self._session is not None and (
            backend.session is not self._session.supplied
            or s.authenticated is not True
            or s.encrypted is not True
            or (quiescent and s.buffered_bytes != 0)
        ):
            raise ValueError("Simulated session changed or not quiescent")
        self._identity = s.process_identity

    def _observe(self, direction: str, frame: bytes):
        size = len(frame) + 16
        cleanup = direction == "outbound" and frame == encode_admin_quit()
        reserve = 0 if cleanup else 1
        if (
            size > AdminFrameDecoder.MAX_FRAME_LENGTH
            or self._frames.total_frames + 1 > self._limits.post_auth_frames - reserve
            or self._stream_bytes + size > self._limits.simulated_stream_bytes - 19 * reserve
        ):
            raise ValueError("Controlled frame/stream byte budget exhausted")
        self._frames.observe(direction, frame)
        self._stream_bytes += size
        self._records.append(
            ControlledFrame(
                direction,
                "cleanup" if cleanup else self._frames.phase,
                frame[2],
                len(frame),
                size,
                hashlib.sha256(frame).hexdigest(),
            )
        )

    async def collect(self, backend: SimulatedBackend, directory: Path) -> str:
        if self.state != "PREPARED" or self._collect_started:
            raise ValueError("One controlled collection only; no retry")
        self._collect_started = True
        if backend.mode != "CONTROLLED_SIMULATED":
            self._reject("Only an explicit simulated backend is permitted")
            raise ValueError(self._reason)
        started = self._now()
        deadline = started + min(
            self._limits.session_seconds,
            self._limits.startup_seconds + 25 * 2 * len(self._pair.requests),
        )
        startup = min(deadline, started + self._limits.startup_seconds)
        error: BaseException | None = None
        try:
            await self._wait(backend.launch, startup)
            self._health(backend)
            connection = await self._wait(backend.connect, startup)
            if (
                not isinstance(connection, SimulatedConnection)
                or len(connection.establishment) != 2
            ):
                raise ValueError("Invalid simulated establishment")
            packets = []
            for kind, raw in zip((103, 104), connection.establishment, strict=True):
                if len(raw) < 3 or raw[2] != kind or int.from_bytes(raw[:2], "little") != len(raw):
                    raise ValueError("Invalid simulated establishment frames")
                self._observe("inbound", raw)
                packets.append(decode_server_packet(kind, raw[3:]))
            protocol, welcome = packets
            if (
                not isinstance(protocol, ServerProtocol)
                or not isinstance(welcome, ServerWelcome)
                or welcome.revision != "15.3"
                or not welcome.dedicated
                or (welcome.width, welcome.height)
                != (self._context.map_width, self._context.map_height)
            ):
                raise ValueError("Simulated welcome identity mismatch")
            self._session = _ObservedSession(
                connection.session, self._observe, self._limits.buffered_bytes
            )
            self._health(backend)
            transport = GameScriptTransport(self._session, protocol)
            self._move("CONNECTED")
            self._frames.enter("setup")
            await self._wait(
                lambda: transport.subscribe(timeout=min(5, self._limits.startup_seconds)), startup
            )
            self._health(backend, quiescent=True)
            for sweep in (1, 2):
                self._move("SWEEP_" + str(sweep))
                self._frames.enter("sweep" + str(sweep))
                sweep_operations = 0
                sweep_request_bytes = 0
                for request in self._pair.requests:
                    self._health(backend, quiescent=True)
                    prior = self._pair.progress["exchanges"]
                    if (
                        len(request.to_bytes()) > self._per.page_request_bytes
                        or sweep_request_bytes + len(request.to_bytes())
                        > self._per.max_request_bytes
                        or sum(len(e.request_payload) for e in prior) + len(request.to_bytes())
                        > self._combined.max_request_bytes
                    ):
                        raise ValueError("Planned request byte budget exhausted")
                    operations = min(
                        8,
                        self._per.max_operations - sweep_operations,
                        self._combined.max_operations - self._frames.query_operations,
                    )
                    if operations < 4:
                        raise ValueError("Query operation budget exhausted before send")
                    self._session.expect(request.to_bytes())
                    before = self._frames.query_operations
                    ex = await self._wait(
                        lambda: transport.tile_facts_page(
                            request, timeout=self._limits.page_seconds, operation_budget=operations
                        ),
                        min(deadline, self._now() + self._limits.page_seconds),
                    )
                    self._session.decoder.require_empty()
                    self._health(backend, quiescent=True)
                    if self._frames.query_operations - before != ex.protocol_operations:
                        raise ValueError("Observed frame/query accounting mismatch")
                    raw = await self._wait(
                        lambda: backend.page_evidence(ex),
                        min(deadline, self._now() + self._limits.evidence_seconds),
                    )
                    if not isinstance(raw, bytes) or not 0 < len(raw) <= 262144:
                        raise ValueError("Bounded simulated lifecycle evidence required")
                    parse_tile_facts_evidence(raw, request.request_id).require_complete(ex)
                    self._health(backend, quiescent=True)
                    self._pair.accept(
                        (self._context.acquisition_id, sweep), backend.snapshot().context, ex
                    )
                    sweep_operations += ex.protocol_operations
                    sweep_request_bytes += len(ex.request_payload)
                self._pair.complete_sweep()
            self._accepted = self._pair.finish()
            self._move("VERIFIED")
        except BaseException as failure:
            error = failure
            self._reject(str(failure))
        finally:

            async def dispose():
                close_error: BaseException | None = None
                try:
                    if self._session is not None:
                        if error is None:
                            self._frames.enter("cleanup")
                        await self._session.close(quit=error is None)
                except BaseException as failure:
                    close_error = failure
                finally:
                    outcome = await backend.cleanup()
                if close_error is not None:
                    raise close_error
                return outcome

            try:
                cleanup = await self._wait(dispose, self._now() + self._limits.cleanup_seconds)
                if (
                    not isinstance(cleanup, SimulatedCleanup)
                    or any(
                        value is not True
                        for value in (
                            cleanup.reaped,
                            cleanup.connection_closed,
                            cleanup.listener_closed,
                            cleanup.credentials_disposed,
                        )
                    )
                    or cleanup.errors != ()
                    or backend.snapshot().alive is not False
                ):
                    raise ValueError("Simulated cleanup or credential disposal failed")
            except BaseException as failure:
                self._reject("Cleanup failed: " + str(failure))
                if error is None:
                    error = failure
        if error is not None:
            if isinstance(error, asyncio.CancelledError):
                raise error
            raise ValueError("Controlled acquisition rejected: " + str(self._reason)) from error
        self._move("CLEANED")
        assert self._accepted is not None
        final_deadline = self._now() + self._limits.finalization_seconds
        try:
            digest = write_paired_package(self._accepted, directory)
            if self._now() >= final_deadline:
                raise TimeoutError("Controlled finalization deadline expired")
        except (ValueError, OSError, TimeoutError) as failure:
            self._reject(str(failure))
            raise
        self._directory = directory
        return digest

    def accept(self, *, expected_descriptor_sha256: str) -> ControlledIntegrationResult:
        if self.state != "CLEANED" or self._directory is None:
            if self.state not in ("REJECTED", "CONTROLLED_ACCEPTED"):
                self._reject("Premature controlled acceptance")
            raise ValueError("Cleaned controlled evidence required before acceptance")
        try:
            pair = verify_paired_package(
                self._directory, expected_descriptor_sha256=expected_descriptor_sha256
            )
            if (
                pair != self._accepted
                or pair.metadata["query_operations"] != self._frames.query_operations
            ):
                raise ValueError("Replayed pair/accounting differs from collected evidence")
        except (ValueError, OSError) as failure:
            self._reject(str(failure))
            raise
        self._move("CONTROLLED_ACCEPTED")
        return ControlledIntegrationResult(
            pair,
            expected_descriptor_sha256,
            ControlledAccounting(
                self._frames.total_frames,
                self._frames.query_operations,
                self._stream_bytes,
                tuple(self._records),
            ),
            tuple(self._states),
        )
