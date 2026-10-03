"""One read-only, connection-local OpenTTD 13.4 Admin observer.

The runner owns the server and decides outcomes. This component owns only its
socket and emits source-typed measurements plus bounded connection events.
"""

import asyncio
import inspect
import ipaddress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.simulation.openttd.admin_protocol import (
    AdminFrameDecoder,
    AdminFrequency,
    AdminProtocolError,
    AdminServerErrorCode,
    AdminUpdateType,
    CompanyNew,
    CompanyRemove,
    CompanyUpdate,
    ServerBanned,
    ServerError,
    ServerFull,
    ServerNewGame,
    ServerPong,
    ServerProtocol,
    ServerShutdown,
    ServerWelcome,
    UnknownPacket,
    encode_admin_join,
    encode_admin_ping,
    encode_admin_poll,
    encode_admin_update_frequency,
)
from app.simulation.openttd.admin_session import AdminSession, AdminSessionStopped
from app.simulation.openttd.telemetry import (
    CompanyEconomyObservation,
    CompanyInfoObservation,
    CompanyStatsObservation,
    GameDateObservation,
)


@dataclass(frozen=True)
class ExpectedServerIdentity:
    revision: str
    seed: int
    map_name: str
    width: int
    height: int
    landscape: int

    def matches(self, welcome: ServerWelcome) -> bool:
        return (
            welcome.revision in {"13.4", "OpenTTD 13.4"}
            and welcome.revision == self.revision
            and welcome.seed == self.seed
            and welcome.map_name == self.map_name
            and welcome.width == self.width
            and welcome.height == self.height
            and welcome.landscape == self.landscape
            and welcome.dedicated
        )


class ObserverState(StrEnum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    READY = "ready"
    AUTHENTICATION_REJECTED = "authentication_rejected"
    CONNECTION_REJECTED = "connection_rejected"
    PROTOCOL_REJECTED = "protocol_rejected"
    SERVER_SHUTDOWN = "server_shutdown"
    CONNECTION_LOST = "connection_lost"
    EOF = "eof"
    MALFORMED_PACKET = "malformed_packet"
    CANCELLED = "cancelled"
    HEARTBEAT_FAILURE = "heartbeat_failure"
    WORLD_RESET = "world_reset"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ObserverHealth:
    state: ObserverState
    subscriptions: tuple[tuple[AdminUpdateType, AdminFrequency], ...] | None = None

    def __post_init__(self) -> None:
        if self.state is ObserverState.READY and not self.subscriptions:
            raise ValueError("READY requires effective subscriptions")
        if self.state is not ObserverState.READY and self.subscriptions is not None:
            raise ValueError("READY requires effective subscriptions")


type MeasurementPayload = (
    GameDateObservation
    | CompanyInfoObservation
    | CompanyEconomyObservation
    | CompanyStatsObservation
)


@dataclass(frozen=True)
class ObserverMeasurement:
    payload: MeasurementPayload


class CompanyLifecycleKind(StrEnum):
    NEW = "new"
    UPDATE = "update"
    REMOVE = "remove"


@dataclass(frozen=True)
class ObserverCompanyLifecycle:
    kind: CompanyLifecycleKind
    company_id: int
    remove_reason_code: int | None = None


@dataclass(frozen=True)
class ObserverUnknownPacket:
    packet_id: int
    payload_length: int


@dataclass(frozen=True)
class ObserverWelcome:
    server: ServerWelcome


type ObserverEvent = (
    ObserverHealth
    | ObserverMeasurement
    | ObserverCompanyLifecycle
    | ObserverUnknownPacket
    | ObserverWelcome
)
type EventSink = Callable[[ObserverEvent], None | Awaitable[None]]


class ObserverTiming(Protocol):
    """Narrow clock/read seam for deterministic deadline tests."""

    def now(self) -> float: ...

    async def read(self, reader: asyncio.StreamReader, timeout: float) -> bytes: ...


class _AsyncioTiming:
    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def read(self, reader: asyncio.StreamReader, timeout: float) -> bytes:
        return await asyncio.wait_for(reader.read(4096), timeout)


class _Phase(StrEnum):
    PROTOCOL = "protocol"
    WELCOME = "welcome"
    INITIAL_DATE = "initial_date"
    READY = "ready"


class AdminObserver:
    """Authenticate, negotiate and watch one local Admin connection.

    `run` is the only active entry point. Cancelling its task closes its socket;
    no background tasks or server-process handles are created.
    """

    HANDSHAKE_SECONDS = 10.0
    HEARTBEAT_SECONDS = 5.0
    HEARTBEAT_LOSS_SECONDS = 15.0

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        client_name: str,
        client_version: str,
        expected: ExpectedServerIdentity,
        *,
        connect_timeout: float = 10.0,
        handshake_timeout: float = HANDSHAKE_SECONDS,
        heartbeat_interval: float = HEARTBEAT_SECONDS,
        heartbeat_timeout: float = HEARTBEAT_LOSS_SECONDS,
        timing: ObserverTiming | None = None,
    ) -> None:
        try:
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            raise ValueError("Admin observer supports loopback hosts only")
        if not 1 <= port <= 65535:
            raise ValueError("invalid Admin port")
        if min(connect_timeout, handshake_timeout, heartbeat_interval, heartbeat_timeout) <= 0:
            raise ValueError("observer deadlines must be positive")
        if heartbeat_timeout <= heartbeat_interval:
            raise ValueError("heartbeat response deadline must exceed ping interval")
        self.host = host
        self.port = port
        self._password = password
        self._client_name = client_name
        self._client_version = client_version
        self.expected = expected
        self.connect_timeout = connect_timeout
        self.handshake_timeout = handshake_timeout
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self._timing = timing or _AsyncioTiming()

    async def run(self, emit: EventSink, *, stop: asyncio.Event | None = None) -> None:
        """Observe one connection; setting `stop` interrupts reads and sends Quit.

        Task cancellation also closes the session and propagates CancelledError.
        The observer never starts a server or reconnects after a terminal event.
        """

        async def publish(event: ObserverEvent) -> None:
            result = emit(event)
            if inspect.isawaitable(result):
                await result

        await publish(ObserverHealth(ObserverState.CONNECTING))
        session: AdminSession | None = None
        authenticated = False
        terminal = False
        try:
            try:
                session = await AdminSession.connect(self.host, self.port, self.connect_timeout)
            except OSError, TimeoutError:
                await publish(ObserverHealth(ObserverState.CONNECTION_LOST))
                return
            assert session is not None
            peer = session.peername
            try:
                peer_is_local = (
                    isinstance(peer, tuple) and ipaddress.ip_address(peer[0]).is_loopback
                )
            except ValueError:
                peer_is_local = False
            if not peer_is_local:
                await publish(ObserverHealth(ObserverState.CONNECTION_REJECTED))
                return
            await publish(ObserverHealth(ObserverState.CONNECTED))
            handshake_deadline = self._timing.now() + self.handshake_timeout
            await session.send(
                encode_admin_join(self._password, self._client_name, self._client_version)
            )
            decoder = AdminFrameDecoder()
            phase = _Phase.PROTOCOL
            selected_subscriptions: tuple[tuple[AdminUpdateType, AdminFrequency], ...] | None = None
            last_month: tuple[int, int] | None = None
            ping_token = 0
            pending_ping: int | None = None
            ping_sent_at = 0.0
            next_ping_at = float("inf")

            while True:
                now = self._timing.now()
                deadline = (
                    handshake_deadline
                    if phase is not _Phase.READY
                    else (
                        ping_sent_at + self.heartbeat_timeout
                        if pending_ping is not None
                        else next_ping_at
                    )
                )
                if now >= deadline:
                    if phase is not _Phase.READY:
                        await publish(ObserverHealth(ObserverState.PROTOCOL_REJECTED))
                        return
                    if pending_ping is not None:
                        await publish(ObserverHealth(ObserverState.HEARTBEAT_FAILURE))
                        return
                    ping_token = (ping_token + 1) & 0xFFFFFFFF
                    await session.send(encode_admin_ping(ping_token))
                    pending_ping = ping_token
                    ping_sent_at = self._timing.now()
                    continue
                try:
                    chunk = await session.read(self._timing.read, deadline - now, stop)
                except AdminSessionStopped:
                    await publish(ObserverHealth(ObserverState.STOPPED))
                    return
                except TimeoutError:
                    continue
                except OSError:
                    await publish(ObserverHealth(ObserverState.CONNECTION_LOST))
                    return
                if not chunk:
                    try:
                        decoder.finish()
                    except AdminProtocolError:
                        await publish(ObserverHealth(ObserverState.MALFORMED_PACKET))
                    else:
                        await publish(ObserverHealth(ObserverState.EOF))
                    return
                try:
                    packets = decoder.feed(chunk)
                except AdminProtocolError, ValueError:
                    await publish(ObserverHealth(ObserverState.MALFORMED_PACKET))
                    return
                for packet in packets:
                    if isinstance(packet, (ServerFull, ServerBanned)):
                        await publish(ObserverHealth(ObserverState.CONNECTION_REJECTED))
                        return
                    if isinstance(packet, ServerError):
                        state = (
                            ObserverState.AUTHENTICATION_REJECTED
                            if phase is _Phase.PROTOCOL
                            and packet.error_code == AdminServerErrorCode.WRONG_PASSWORD
                            else ObserverState.PROTOCOL_REJECTED
                        )
                        await publish(ObserverHealth(state))
                        return
                    if isinstance(packet, ServerShutdown):
                        terminal = True
                        await publish(ObserverHealth(ObserverState.SERVER_SHUTDOWN))
                        return
                    if isinstance(packet, ServerNewGame):
                        terminal = True
                        await publish(ObserverHealth(ObserverState.WORLD_RESET))
                        return
                    if isinstance(packet, UnknownPacket):
                        await publish(
                            ObserverUnknownPacket(packet.packet_id, packet.payload_length)
                        )
                        continue
                    if phase is _Phase.PROTOCOL:
                        if not isinstance(packet, ServerProtocol) or not self._supports_required(
                            packet
                        ):
                            await publish(ObserverHealth(ObserverState.PROTOCOL_REJECTED))
                            return
                        phase = _Phase.WELCOME
                        authenticated = True
                        await publish(ObserverHealth(ObserverState.AUTHENTICATED))
                        continue
                    if phase is _Phase.WELCOME:
                        if not isinstance(packet, ServerWelcome) or not self.expected.matches(
                            packet
                        ):
                            await publish(ObserverHealth(ObserverState.PROTOCOL_REJECTED))
                            return
                        await publish(ObserverWelcome(packet))
                        phase = _Phase.INITIAL_DATE
                        selected_subscriptions = self._subscriptions()
                        await session.send(
                            *(
                                encode_admin_update_frequency(kind, frequency)
                                for kind, frequency in selected_subscriptions
                            ),
                            *(encode_admin_poll(kind) for kind in self._initial_polls()),
                        )
                        continue
                    if isinstance(packet, (ServerProtocol, ServerWelcome)):
                        await publish(ObserverHealth(ObserverState.PROTOCOL_REJECTED))
                        return
                    if isinstance(packet, ServerPong):
                        if pending_ping is None or packet.token != pending_ping:
                            await publish(ObserverHealth(ObserverState.PROTOCOL_REJECTED))
                            return
                        pending_ping = None
                        next_ping_at = self._timing.now() + self.heartbeat_interval
                        continue
                    if isinstance(packet, (CompanyNew, CompanyUpdate, CompanyRemove)):
                        kind = (
                            CompanyLifecycleKind.NEW
                            if isinstance(packet, CompanyNew)
                            else CompanyLifecycleKind.UPDATE
                            if isinstance(packet, CompanyUpdate)
                            else CompanyLifecycleKind.REMOVE
                        )
                        reason = packet.reason_code if isinstance(packet, CompanyRemove) else None
                        await publish(ObserverCompanyLifecycle(kind, packet.company_id, reason))
                        if kind is not CompanyLifecycleKind.REMOVE:
                            await session.send(
                                encode_admin_poll(AdminUpdateType.COMPANY_INFO, packet.company_id)
                            )
                        continue
                    if isinstance(
                        packet,
                        (
                            GameDateObservation,
                            CompanyInfoObservation,
                            CompanyEconomyObservation,
                            CompanyStatsObservation,
                        ),
                    ):
                        await publish(ObserverMeasurement(packet))
                        if isinstance(packet, GameDateObservation):
                            month = (packet.calendar_date.year, packet.calendar_date.month)
                            if last_month is not None and month != last_month:
                                await session.send(encode_admin_poll(AdminUpdateType.COMPANY_INFO))
                            last_month = month
                            if phase is _Phase.INITIAL_DATE:
                                phase = _Phase.READY
                                next_ping_at = self._timing.now() + self.heartbeat_interval
                                assert selected_subscriptions is not None
                                await publish(
                                    ObserverHealth(ObserverState.READY, selected_subscriptions)
                                )
            # No process or persistence ownership here.
        except asyncio.CancelledError:
            await publish(ObserverHealth(ObserverState.CANCELLED))
            raise
        except OSError:
            await publish(ObserverHealth(ObserverState.CONNECTION_LOST))
        finally:
            if session is not None:
                await session.close(quit=authenticated and not terminal)

    @staticmethod
    def _subscriptions() -> tuple[tuple[AdminUpdateType, AdminFrequency], ...]:
        return (
            (AdminUpdateType.DATE, AdminFrequency.DAILY),
            (AdminUpdateType.COMPANY_INFO, AdminFrequency.AUTOMATIC),
            (AdminUpdateType.COMPANY_ECONOMY, AdminFrequency.MONTHLY),
            (AdminUpdateType.COMPANY_STATS, AdminFrequency.MONTHLY),
        )

    @staticmethod
    def _initial_polls() -> tuple[AdminUpdateType, ...]:
        return (
            AdminUpdateType.DATE,
            AdminUpdateType.COMPANY_INFO,
            AdminUpdateType.COMPANY_ECONOMY,
            AdminUpdateType.COMPANY_STATS,
        )

    @classmethod
    def _supports_required(cls, protocol: ServerProtocol) -> bool:
        return protocol.version == 2 and all(
            protocol.supports(kind, frequency) and protocol.supports(kind, AdminFrequency.POLL)
            for kind, frequency in cls._subscriptions()
        )
