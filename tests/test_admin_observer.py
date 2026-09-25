"""Controlled Admin peer tests; scripted bytes are synthesized from 13.4 source."""

import ast
import asyncio
import struct
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from app.simulation.openttd.admin_observer import (
    AdminObserver,
    CompanyLifecycleKind,
    ExpectedServerIdentity,
    ObserverCompanyLifecycle,
    ObserverHealth,
    ObserverMeasurement,
    ObserverState,
    ObserverUnknownPacket,
)
from app.simulation.openttd.telemetry import (
    CompanyEconomyObservation,
    CompanyInfoObservation,
    CompanyStatsObservation,
)


class _ManualTiming:
    def __init__(self) -> None:
        self.current = 0.0
        self._advanced = asyncio.Event()

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds
        self._advanced.set()
        self._advanced = asyncio.Event()

    async def _until(self, deadline: float) -> None:
        while self.current < deadline:
            event = self._advanced
            await event.wait()

    async def read(self, reader: asyncio.StreamReader, timeout: float) -> bytes:
        read_task = asyncio.create_task(reader.read(4096))
        timer_task = asyncio.create_task(self._until(self.current + timeout))
        try:
            done, _ = await asyncio.wait(
                (read_task, timer_task), return_when=asyncio.FIRST_COMPLETED
            )
            if read_task in done:
                return read_task.result()
            raise TimeoutError
        finally:
            for task in (read_task, timer_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(read_task, timer_task, return_exceptions=True)


def _frame(packet_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HB", len(payload) + 3, packet_id) + payload


def _protocol() -> bytes:
    payload = (
        b"\x02"
        + b"".join(
            struct.pack("<BHH", 1, kind, mask)
            for kind, mask in ((0, 63), (2, 65), (3, 61), (4, 61))
        )
        + b"\x00"
    )
    return _frame(103, payload)


def _welcome(
    *,
    revision: bytes = b"OpenTTD 13.4",
    dedicated: int = 1,
    map_name: bytes = b"",
    seed: int = 17,
    landscape: int = 0,
    width: int = 256,
    height: int = 256,
) -> bytes:
    return _frame(
        104,
        b"Server\0"
        + revision
        + b"\0"
        + bytes([dedicated])
        + map_name
        + b"\0"
        + struct.pack("<IBIHH", seed, landscape, 712223, width, height),
    )


async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    length = struct.unpack("<H", await reader.readexactly(2))[0]
    data = await reader.readexactly(length - 2)
    return data[0], data[1:]


async def _with_peer(
    peer: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    observe: Callable[[str, int], Awaitable[None]],
) -> None:
    tasks: set[asyncio.Task[None]] = set()

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(peer(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    try:
        await observe("127.0.0.1", server.sockets[0].getsockname()[1])
        if tasks:
            await asyncio.gather(*tasks)
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def test_authentication_readiness_and_typed_date() -> None:
    async def scenario() -> None:
        outbound: list[tuple[int, bytes]] = []
        events: list[object] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            outbound.append(await _read_frame(reader))
            writer.write(_protocol() + _welcome())
            await writer.drain()
            for _ in range(8):
                outbound.append(await _read_frame(reader))
            writer.write(_frame(107, struct.pack("<I", 712223)) + _frame(106))
            await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        async def observe(host: str, port: int) -> None:
            observer = AdminObserver(
                host,
                port,
                "password",
                "test-observer",
                "1",
                ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
            )
            await observer.run(events.append)

        await _with_peer(peer, observe)
        assert outbound[0] == (0, b"password\0test-observer\0" + b"1\0")
        assert [packet_id for packet_id, _ in outbound[1:]] == [2, 2, 2, 2, 3, 3, 3, 3]
        assert [struct.unpack("<HH", body) for packet_id, body in outbound[1:5]] == [
            (0, 2),
            (2, 64),
            (3, 8),
            (4, 8),
        ]
        assert [struct.unpack("<BI", body) for packet_id, body in outbound[5:9]] == [
            (0, 0xFFFFFFFF),
            (2, 0xFFFFFFFF),
            (3, 0xFFFFFFFF),
            (4, 0xFFFFFFFF),
        ]
        assert ObserverHealth(ObserverState.READY) in events
        assert any(
            isinstance(event, ObserverMeasurement) and event.payload.game_day == 712223
            for event in events
        )
        assert ObserverHealth(ObserverState.SERVER_SHUTDOWN) in events
        assert all(packet_id in {0, 1, 2, 3, 7} for packet_id, _ in outbound)

    asyncio.run(scenario())


async def _scripted_observation(
    response: bytes,
    *,
    handshake_timeout: float = 0.05,
    expected: ExpectedServerIdentity | None = None,
) -> tuple[list[object], list[tuple[int, bytes]]]:
    events: list[object] = []
    outbound: list[tuple[int, bytes]] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        outbound.append(await _read_frame(reader))
        writer.write(response)
        await writer.drain()
        while True:
            try:
                outbound.append(await _read_frame(reader))
            except asyncio.IncompleteReadError:
                break
        writer.close()
        await writer.wait_closed()

    async def observe(host: str, port: int) -> None:
        observer = AdminObserver(
            host,
            port,
            "bad-password",
            "observer",
            "1",
            expected or ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
            handshake_timeout=handshake_timeout,
        )
        await observer.run(events.append)

    await _with_peer(peer, observe)
    return events, outbound


@pytest.mark.parametrize(
    "rejection_id,payload,state",
    [
        (100, b"", ObserverState.CONNECTION_REJECTED),
        (101, b"", ObserverState.CONNECTION_REJECTED),
        (102, b"\x0a", ObserverState.AUTHENTICATION_REJECTED),
        (102, b"\x04", ObserverState.PROTOCOL_REJECTED),
    ],
)
def test_rejection_reason_is_classified_without_password_retry(
    rejection_id: int, payload: bytes, state: ObserverState
) -> None:
    events, outbound = asyncio.run(_scripted_observation(_frame(rejection_id, payload)))
    assert ObserverHealth(state) in events
    assert [packet_id for packet_id, _ in outbound] == [0]
    assert ObserverHealth(ObserverState.READY) not in events


@pytest.mark.parametrize(
    "response",
    [
        _frame(103, b"\x03\x00") + _welcome(),
        _frame(103, b"\x02\x01\x00\x00\x01\x00\x00") + _welcome(),
        _protocol() + _welcome(revision=b"wrong-revision"),
        _protocol() + _welcome(dedicated=0),
        _protocol() + _welcome(seed=18),
        _protocol() + _welcome(map_name=b"other-map"),
        _protocol() + _welcome(width=512),
        _protocol() + _welcome(landscape=1),
    ],
)
def test_protocol_version_frequencies_and_welcome_identity_must_match(response: bytes) -> None:
    events, _ = asyncio.run(_scripted_observation(response))
    assert ObserverHealth(ObserverState.PROTOCOL_REJECTED) in events
    assert ObserverHealth(ObserverState.READY) not in events


def test_missing_initial_date_never_reports_ready() -> None:
    async def scenario() -> None:
        timing = _ManualTiming()
        configured = asyncio.Event()
        events: list[object] = []
        outbound: list[tuple[int, bytes]] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            outbound.append(await _read_frame(reader))
            writer.write(_protocol() + _welcome())
            await writer.drain()
            for _ in range(8):
                outbound.append(await _read_frame(reader))
            configured.set()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        async def observe(host: str, port: int) -> None:
            task = asyncio.create_task(
                AdminObserver(
                    host,
                    port,
                    "password",
                    "observer",
                    "1",
                    ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
                    timing=timing,
                ).run(events.append)
            )
            await asyncio.wait_for(configured.wait(), 1)
            timing.advance(10.0)
            await asyncio.wait_for(task, 1)

        await _with_peer(peer, observe)
        assert ObserverHealth(ObserverState.AUTHENTICATED) in events
        assert ObserverHealth(ObserverState.PROTOCOL_REJECTED) in events
        assert ObserverHealth(ObserverState.READY) not in events
        assert [packet_id for packet_id, _ in outbound].count(0) == 1

    asyncio.run(scenario())


def test_failed_local_connection_reports_loss_without_authentication() -> None:
    async def scenario() -> None:
        server = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        events: list[object] = []
        await AdminObserver(
            "127.0.0.1",
            port,
            "password",
            "observer",
            "1",
            ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
        ).run(events.append)
        assert events == [
            ObserverHealth(ObserverState.CONNECTING),
            ObserverHealth(ObserverState.CONNECTION_LOST),
        ]

    asyncio.run(scenario())


def test_non_loopback_admin_host_is_rejected_before_connection() -> None:
    with pytest.raises(ValueError, match="loopback"):
        AdminObserver(
            "192.0.2.1",
            3977,
            "password",
            "observer",
            "1",
            ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
        )


def test_monthly_company_info_poll_and_lifecycle_refreshes_preserve_identity() -> None:
    async def scenario() -> None:
        events: list[object] = []
        outbound: list[tuple[int, bytes]] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            outbound.append(await _read_frame(reader))
            writer.write(_protocol() + _welcome())
            await writer.drain()
            for _ in range(8):
                outbound.append(await _read_frame(reader))
            wire = (
                _frame(107, struct.pack("<I", 712223))
                + _frame(107, struct.pack("<I", 712254))
                + _frame(113, b"\x02")
                + _frame(
                    115, b"\x02New\0Manager\0" + struct.pack("<BBB4B", 1, 0, 0, 255, 255, 255, 255)
                )
                + _frame(116, b"\x02\x01")
            )
            writer.write(wire)
            await writer.drain()
            for _ in range(3):
                outbound.append(await _read_frame(reader))
            writer.write(_frame(106))
            await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        async def observe(host: str, port: int) -> None:
            await AdminObserver(
                host,
                port,
                "password",
                "observer",
                "1",
                ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
            ).run(events.append)

        await _with_peer(peer, observe)
        assert [struct.unpack("<BI", body) for packet_id, body in outbound[9:]] == [
            (2, 0xFFFFFFFF),
            (2, 2),
            (2, 2),
        ]
        assert ObserverCompanyLifecycle(CompanyLifecycleKind.NEW, 2) in events
        assert ObserverCompanyLifecycle(CompanyLifecycleKind.UPDATE, 2) in events
        assert ObserverCompanyLifecycle(CompanyLifecycleKind.REMOVE, 2, 1) in events
        assert all(packet_id in {0, 1, 2, 3, 7} for packet_id, _ in outbound)

    asyncio.run(scenario())


def test_typed_measurements_unknown_packet_and_shutdown() -> None:
    info = b"\x02Road Co\0Manager\0" + struct.pack("<BBIBB4B", 1, 0, 1950, 1, 0, 255, 255, 255, 255)
    economy = struct.pack("<BqqqHqHHqHH", 2, -50, 100, -2500, 65535, 800, 3, 2, 0, 0, 0)
    stats = struct.pack("<B10H", 2, *range(1, 11))
    response = (
        _protocol()
        + _welcome()
        + _frame(107, struct.pack("<I", 712223))
        + _frame(250, b"opaque")
        + _frame(114, info)
        + _frame(117, economy)
        + _frame(118, stats)
        + _frame(106)
    )
    events, _ = asyncio.run(_scripted_observation(response))
    payloads = [event.payload for event in events if isinstance(event, ObserverMeasurement)]
    assert isinstance(payloads[1], CompanyInfoObservation)
    assert isinstance(payloads[2], CompanyEconomyObservation)
    assert payloads[2].admin_year_to_date_net_income_gbp == -2500
    assert payloads[2].current_quarter_cargo_may_be_saturated
    assert isinstance(payloads[3], CompanyStatsObservation)
    assert payloads[3].primary_vehicles.train == 1
    assert ObserverUnknownPacket(250, 6) in events
    assert ObserverHealth(ObserverState.SERVER_SHUTDOWN) in events


def test_new_game_notification_is_a_world_reset_not_success() -> None:
    response = _protocol() + _welcome() + _frame(107, struct.pack("<I", 712223)) + _frame(105)
    events, _ = asyncio.run(_scripted_observation(response))
    assert ObserverHealth(ObserverState.WORLD_RESET) in events
    assert ObserverHealth(ObserverState.SERVER_SHUTDOWN) not in events


def test_clean_eof_is_distinct_from_malformed_known_packet() -> None:
    async def closed_peer(response: bytes, extra: bytes = b"") -> list[object]:
        events: list[object] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await _read_frame(reader)
            writer.write(response)
            await writer.drain()
            for _ in range(8):
                await _read_frame(reader)
            if extra:
                writer.write(extra)
                await writer.drain()
            writer.close()
            await writer.wait_closed()

        async def observe(host: str, port: int) -> None:
            await AdminObserver(
                host,
                port,
                "password",
                "observer",
                "1",
                ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
            ).run(events.append)

        await _with_peer(peer, observe)
        return events

    prefix = _protocol() + _welcome() + _frame(107, struct.pack("<I", 712223))
    eof = asyncio.run(closed_peer(prefix))
    malformed = asyncio.run(closed_peer(prefix, _frame(117, b"\x02\x01")))
    assert ObserverHealth(ObserverState.EOF) in eof
    assert ObserverHealth(ObserverState.MALFORMED_PACKET) in malformed


def test_heartbeat_ping_pong_and_missing_pong_deadline() -> None:
    async def run_peer(reply: str) -> tuple[list[object], list[tuple[int, bytes]]]:
        timing = _ManualTiming()
        ready = asyncio.Event()
        ping_received = asyncio.Event()
        events: list[object] = []
        outbound: list[tuple[int, bytes]] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            outbound.append(await _read_frame(reader))
            writer.write(_protocol() + _welcome())
            await writer.drain()
            for _ in range(8):
                outbound.append(await _read_frame(reader))
            writer.write(_frame(107, struct.pack("<I", 712223)))
            await writer.drain()
            ping = await _read_frame(reader)
            outbound.append(ping)
            ping_received.set()
            if reply != "missing":
                token = ping[1] if reply == "valid" else struct.pack("<I", 999)
                writer.write(_frame(126, token) + _frame(106))
                await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        async def observe(host: str, port: int) -> None:
            def emit(event: object) -> None:
                events.append(event)
                if event == ObserverHealth(ObserverState.READY):
                    ready.set()

            task = asyncio.create_task(
                AdminObserver(
                    host,
                    port,
                    "password",
                    "observer",
                    "1",
                    ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
                    timing=timing,
                ).run(emit)
            )
            await asyncio.wait_for(ready.wait(), 1)
            timing.advance(5.0)
            await asyncio.wait_for(ping_received.wait(), 1)
            if reply == "missing":
                timing.advance(15.0)
            await asyncio.wait_for(task, 1)

        await _with_peer(peer, observe)
        return events, outbound

    success, outbound = asyncio.run(run_peer("valid"))
    loss, _ = asyncio.run(run_peer("missing"))
    invalid, _ = asyncio.run(run_peer("invalid"))
    assert outbound[9][0] == 7
    assert ObserverHealth(ObserverState.SERVER_SHUTDOWN) in success
    assert ObserverHealth(ObserverState.HEARTBEAT_FAILURE) in loss
    assert ObserverHealth(ObserverState.PROTOCOL_REJECTED) in invalid


def test_cancellation_closes_socket_without_background_observer_tasks() -> None:
    async def scenario() -> None:
        ready = asyncio.Event()
        eof = asyncio.Event()
        events: list[object] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await _read_frame(reader)
            writer.write(_protocol() + _welcome())
            await writer.drain()
            for _ in range(8):
                await _read_frame(reader)
            writer.write(_frame(107, struct.pack("<I", 712223)))
            await writer.drain()
            await reader.read()
            eof.set()
            writer.close()
            await writer.wait_closed()

        async def observe(host: str, port: int) -> None:
            def emit(event: object) -> None:
                events.append(event)
                if event == ObserverHealth(ObserverState.READY):
                    ready.set()

            task = asyncio.create_task(
                AdminObserver(
                    host,
                    port,
                    "password",
                    "observer",
                    "1",
                    ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0),
                ).run(emit)
            )
            await asyncio.wait_for(ready.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(eof.wait(), 1)
            assert task.done()

        await _with_peer(peer, observe)
        assert ObserverHealth(ObserverState.CANCELLED) in events

    asyncio.run(scenario())


def test_observer_has_no_prototype_process_or_game_control_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "app/simulation/openttd/admin_observer.py"
    syntax = ast.parse(path.read_text())
    imported = [
        alias.name
        for node in ast.walk(syntax)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [node.module or "" for node in ast.walk(syntax) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name.startswith(("prototype", "subprocess", "signal", "os")) for name in imported
    )
